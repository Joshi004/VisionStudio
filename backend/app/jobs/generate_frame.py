"""The `generate_frame` job: one first frame for one scene, made by Qwen-Image-2.1 on the GPU
server (ANALYSIS.md Section 4.2 and 6.2; Phase 17).

It is a remote job, like `generate_clip`. The steps every Qwen image job shares (submit, poll,
download, the failure rules) are `RemoteImageHandler`'s (`jobs/remote_image.py`), and what is
done with the PNG afterwards (store it as it came, fit it to the project's generation size and,
if the scene still allows it, make it the scene's frame) is `SceneFrameHandler`'s
(`jobs/scene_frame.py`), which the last frame's job shares. This module is what is particular to
a scene's first frame:

- `start`: check that a frame may be made, build the request (the first time only) and submit.
- the hooks that say which prompt the frame records and how it becomes the scene's first frame.

**It only starts from a click** (`POST .../generate-first-frames` or `.../generate-first-frame`),
and everything that can be checked for free is checked before anything is sent: the blocks, the
manual-first rule (an uploaded frame is only replaced when the click confirmed it) and the
approved GPU API (it must have the image endpoint).

**The request is built once.** The first `start` stores it in `job.input`: the prompt, the mode
(Settings, "Image mode"), the nearest of the model's seven shapes and a random seed. Every later
attempt (after a pre-emption, an expired result or a server that could not be reached) sends the
same stored request, because "the correct response to a pre-emption failure is to resubmit the
exact same request unchanged" (the server's guide). A new seed comes only with a new job.

**A scene of the cast is made by the image model's edit.** A scene that shows a character or a
place of the project's cast (`scene.character_id`, `scene.location_id`) has an image prompt
written for reference pictures (`QWEN_IMAGE_21_CHARACTER_EDIT`), so its frame is made by the edit
endpoint, with the picture of the character (image 1) and of the place (the next) as references,
uploaded at every start (`jobs/reference_upload.py`). It waits until those pictures exist
(`cast.references_block`). A scene that shows neither is made from the prompt alone, as before.

What it makes: Qwen-Image-2.1 answers in one of seven shapes at its native 2K size
(`services/image_models.ASPECT_SIZES`), which are not the project's generation size. The nearest
shape is asked for (`scene_frame.py` fits the image to the generation size).

The frame becomes the scene's first frame only if the scene's first frame is still the one the
job started from and its cut is unchanged (`services/first_frames.attach_block`). Otherwise the
frame is kept, listed among the scene's earlier frames, and the job still succeeds.

Logs hold ids, sizes and phases, never the prompt.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Asset, Project, Scene
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.generate_clip import GPU_URL_KEY, PARTITION_KEY
from app.jobs.reference_upload import upload_references
from app.jobs.scene_frame import SceneFrameHandler, scene_record
from app.providers import contract_guard, image_generator
from app.services import api_contract, image_models, scene_inputs
from app.services import cast as cast_service
from app.services import first_frames as frames_service
from app.services import image_prompts as prompts_service
from app.services import scenes as scenes_service
from app.services.descriptions import DRAFT_JOB

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = frames_service.FRAME_JOB
IMAGE_MODE_KEY: Final = "image_mode"

_UPLOAD_ADDED = (
    "A frame was attached to this scene after the click, so no image was made. Generate "
    "again to replace it."
)


@dataclass
class _Read:
    """What `start` reads before it submits. `block` is why no image may be made, if any."""

    job_input: dict[str, Any]
    project: Project | None
    scene: Scene | None
    block: str | None
    base_url: str
    partition: str
    mode: image_models.ImageMode
    # The approved OpenAPI document, or None when none is recorded.
    spec: dict[str, Any] | None
    # The one character and the one place the scene shows (the project's cast). A scene that
    # shows either is made by the image model's edit, from their reference pictures.
    scene_cast: cast_service.SceneCast = cast_service.NO_CAST


@dataclass(frozen=True)
class _Plan:
    """What a start submits: the request, and the job's input as stored (which a submission
    extends).
    """

    request: dict[str, Any]
    recorded: dict[str, Any]


class GenerateFrameHandler(SceneFrameHandler):
    job_type = JOB_TYPE
    label = "first frame"
    role = "first_frame"

    # --- start: check, prepare (once), submit ------------------------------------------

    async def start(self, job_id: int) -> None:
        read = await self._read(job_id)
        if read is None:
            return
        if read.project is None or read.scene is None:
            await self._fail(job_id, "The project or the scene no longer exists.")
            return
        if read.block is not None:
            await self._fail(job_id, read.block)
            return

        plan = self._stored_plan(read.job_input)
        if plan is None:
            plan = await self._prepare(job_id, read, read.project, read.scene)
            if plan is None:
                return  # the job was failed, or cancelled, in there

        if plan.recorded.get("endpoint") != image_generator.EDIT_PATH:
            await self.submit(job_id, read.base_url, plan.request, plan.recorded)
            return

        # A scene of the cast: the reference pictures are uploaded at every start, because the
        # server deletes the inputs of a job when it ends.
        base_url = read.base_url
        references = [
            (str(item["cast_kind"]), int(item["asset_id"]))
            for item in plan.recorded.get("references", [])
        ]

        async def build_body() -> tuple[dict[str, Any], dict[str, Any]]:
            remote_ids, uploads = await upload_references(base_url, references)
            body = image_generator.with_references(plan.request, remote_ids)
            return body, {"uploads": uploads, "body": body}

        await self.submit(
            job_id,
            base_url,
            plan.request,
            plan.recorded,
            endpoint=image_generator.EDIT_PATH,
            build_body=build_body,
        )

    @staticmethod
    def _stored_plan(job_input: dict[str, Any]) -> _Plan | None:
        """The plan of an earlier attempt, read back from the job's input. None the first time."""
        request = job_input.get("request")
        if (
            not isinstance(request, dict)
            or job_input.get("endpoint")
            not in (image_generator.GENERATE_PATH, image_generator.EDIT_PATH)
            or not isinstance(job_input.get("scene_sent"), dict)
        ):
            return None
        return _Plan(request=request, recorded=job_input)

    async def _prepare(
        self, job_id: int, read: _Read, project: Project, scene: Scene
    ) -> _Plan | None:
        """Works out the request and stores it on the job, before anything is sent. Runs on the
        first attempt only. Fails the job (returns None) when the approved GPU API has no image
        endpoint, or the request would be refused.
        """
        await self._phase(job_id, phases.PREPARING_IMAGE_REQUEST)
        prompt = (scene.image_prompt or "").strip()
        # A scene that shows a character or a place of the cast is made by the image model's
        # edit, from their pictures (the character first). Any other scene is text to image.
        references = [
            {"cast_kind": kind, "cast_id": member.id, "asset_id": member.reference_asset_id}
            for kind, member in read.scene_cast.references()
        ]
        aspect_ratio = image_models.pick_aspect_ratio(project.gen_width, project.gen_height)
        seed = secrets.randbelow(image_models.SEED_LIMIT)
        try:
            if references:
                image_generator.check_edit_endpoint(read.spec)
                request = image_generator.build_edit_request(
                    prompt=prompt,
                    mode=read.mode,
                    seed=seed,
                    aspect_ratio=aspect_ratio,
                    partition=read.partition,
                )
                endpoint = image_generator.EDIT_PATH
            else:
                image_generator.check_endpoint(read.spec)
                request = image_generator.build_request(
                    prompt=prompt,
                    mode=read.mode,
                    seed=seed,
                    aspect_ratio=aspect_ratio,
                    partition=read.partition,
                )
                endpoint = image_generator.GENERATE_PATH
        except ValueError as exc:
            await self._fail(job_id, str(exc))
            return None

        expected_width, expected_height = image_models.ASPECT_SIZES[aspect_ratio]
        recorded: dict[str, Any] = {
            **read.job_input,
            "scene_sent": scene_record(scene),
            "image_prompt": prompt,
            "image_prompt_source": scene.image_prompt_source,
            "image_prompt_job_id": scene.image_prompt_job_id,
            "replacing_asset_id": scene.first_frame_asset_id,
            "frame_size": {"width": project.gen_width, "height": project.gen_height},
            "image_model": image_models.MODEL_ID,
            "image_mode": read.mode,
            "aspect_ratio": aspect_ratio,
            "expected_size": {"width": expected_width, "height": expected_height},
            "endpoint": endpoint,
            "request": request,
        }
        if references:
            recorded["references"] = references
        async with SessionLocal() as session:
            if not await store.update_input(session, job_id, recorded):
                return None  # cancelled while preparing: nothing was sent
        return _Plan(request=request, recorded=recorded)

    # --- Reading ----------------------------------------------------------------------

    async def _read(self, job_id: int) -> _Read | None:
        """Everything `start` needs, in one short read. None when there is nothing to run. The
        reasons an image may not be made are worked out here, before anything is sent.
        """
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if (
                job is None
                or job.status != "running"
                or job.scene_id is None
                or not isinstance(job.input, dict)
            ):
                await session.commit()
                return None
            job_input: dict[str, Any] = dict(job.input)
            project = await session.get(Project, job.project_id)
            scene = await session.get(Scene, job.scene_id, populate_existing=True)
            block: str | None = None
            scene_cast = cast_service.NO_CAST
            if project is not None and scene is not None:
                # The same refusals as the endpoints: things may have changed while the job
                # waited for its turn.
                state = await scenes_service.scenes_state(session, project)
                draft_job = await store.latest_job(session, project.id, DRAFT_JOB)
                prompt_states = await prompts_service.prompt_states(session, project, [scene])
                active_prompts = await prompts_service.active_prompt_jobs(session, project.id)
                frames = await scene_inputs.load_frames(session, [scene])
                first_frame: Asset | None = frames.get(scene.first_frame_asset_id or 0)
                scene_cast = (await cast_service.load_scene_casts(session, project.id, [scene]))[
                    scene.id
                ]
                block = prompts_service.project_block(
                    state.scenes,
                    plan_job=state.job,
                    stale_reasons=state.stale_reasons,
                    draft_job=draft_job,
                ) or frames_service.scene_block(
                    scene,
                    prompt_out_of_date=scene.id in prompt_states
                    and prompt_states[scene.id].out_of_date,
                    prompt_job_active=scene.id in active_prompts,
                    references_block=cast_service.references_block(scene_cast),
                )
                # Manual-first: an uploaded frame is replaced only when the click confirmed
                # that very frame.
                if block is None and frames_service.needs_upload_confirmation(scene, first_frame):
                    confirmed = (
                        job_input.get("replace_upload") is True
                        and job_input.get("first_frame_at_click") == scene.first_frame_asset_id
                    )
                    if not confirmed:
                        block = _UPLOAD_ADDED
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            partition = await settings_service.get_str(session, PARTITION_KEY)
            mode = image_models.resolve_mode(
                await settings_service.get_str(session, IMAGE_MODE_KEY)
            )
            bodies = await contract_guard.approved_bodies(session)
            await session.commit()
        spec = next((body for body in bodies if api_contract.is_openapi(body)), None)
        return _Read(
            job_input=job_input,
            project=project,
            scene=scene,
            block=block,
            base_url=base_url,
            partition=partition,
            mode=mode,
            spec=spec,
            scene_cast=scene_cast,
        )

    # --- What a first frame does with the image (`SceneFrameHandler`'s hooks) ---------------

    def prompt_provenance(self, recorded: dict[str, Any]) -> dict[str, Any]:
        return {
            "prompt": recorded.get("image_prompt"),
            "image_prompt_source": recorded.get("image_prompt_source"),
            "image_prompt_job_id": recorded.get("image_prompt_job_id"),
            # The cast pictures the frame was made from, in the order they were sent. None for
            # a frame made from the prompt alone.
            "references": recorded.get("references"),
        }

    def attach_reason(self, current: Scene, recorded: dict[str, Any]) -> str | None:
        scene_sent = recorded.get("scene_sent")
        replacing = recorded.get("replacing_asset_id")
        return frames_service.attach_block(
            current,
            scene_sent if isinstance(scene_sent, dict) else {},
            replacing if isinstance(replacing, int) else None,
        )

    async def attach(
        self, session: AsyncSession, current: Scene, frame: Asset, recorded: dict[str, Any]
    ) -> dict[str, Any]:
        current.first_frame_asset_id = frame.id
        return {}
