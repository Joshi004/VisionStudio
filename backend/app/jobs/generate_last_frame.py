"""The `generate_last_frame` job: one last frame for one scene, made by editing the scene's first
frame with Qwen-Image-2.1's edit endpoint on the GPU server (ANALYSIS.md Section 4.2 and 6.2;
Phase 23).

It is a remote job, like `generate_frame`, and shares its steps. The steps every Qwen image job
shares (submit, poll, download, the failure rules) are `RemoteImageHandler`'s
(`jobs/remote_image.py`), and what is done with the PNG afterwards is `SceneFrameHandler`'s
(`jobs/scene_frame.py`). This module is what is particular to a scene's last frame:

- `start`: check that a frame may be made, build the request (the first time only) and submit it.
- the hooks that say which prompt the frame records and how it becomes the scene's last frame.

**It only starts from a click** (`POST .../generate-last-frames` or `.../generate-last-frame`),
or from the automatic run, and everything that can be checked for free is checked before anything
is sent: the blocks, the manual-first rule (an uploaded last frame is only replaced when the click
confirmed it) and the approved GPU API (it must have the edit endpoint).

**What is edited.** The picture the edit starts from is the scene's first frame, and it is sent as
a reference image (`reference_image_asset_ids`). When the first frame was made by the image model,
the reference is its *raw* 2K image (`provenance.raw_asset_id`) and the request asks for the same
shape (`provenance.aspect_ratio`), so the result goes through the identical fit and crop and stays
aligned with the first frame: two frames that differ only in framing would make the video model
slide the whole picture. A first frame the author uploaded has no raw image: the normalised PNG that
the video model gets (`derived_frames.frame_to_send`) is sent and no shape is asked for, so the
result follows the shape of that picture.

**The request is built once.** The first `start` stores it in `job.input`: the edit prompt, the
mode (Settings, "Image mode"), the shape and a random seed (and which picture is the reference).
Every later attempt (after a pre-emption, an expired result or a server that could not be reached)
sends the same stored request and uploads the same reference again, because the server deletes the
inputs of a job when it ends. A new seed comes only with a new job.

The frame becomes the scene's last frame only if the scene's cut is unchanged, its last frame is
still the one the job started from and its first frame is still the one that was edited
(`services/last_frames.attach_block`). Otherwise the frame is kept, listed among the scene's
earlier last frames, and the job still succeeds.

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
from app.jobs.generate_frame import IMAGE_MODE_KEY
from app.jobs.scene_frame import SceneFrameHandler, scene_record
from app.providers import contract_guard, image_generator
from app.services import api_contract, derived_frames, image_models, scene_inputs
from app.services import first_frames as first_frames_service
from app.services import image_prompts as image_prompts_service
from app.services import last_frame_prompts as last_prompts_service
from app.services import last_frames as last_frames_service
from app.services import scenes as scenes_service
from app.services.descriptions import DRAFT_JOB
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = last_frames_service.LAST_FRAME_JOB

_UPLOAD_ADDED = (
    "A last frame was attached to this scene after the click, so no image was made. Generate "
    "again to replace it."
)
_REFERENCE_GONE = "The scene's first frame could not be read, so the last frame cannot be edited."


@dataclass
class _Read:
    """What `start` reads before it submits. `block` is why no image may be made, if any."""

    job_input: dict[str, Any]
    project: Project | None
    scene: Scene | None
    first_frame: Asset | None
    block: str | None
    base_url: str
    partition: str
    mode: image_models.ImageMode
    # The approved OpenAPI document, or None when none is recorded.
    spec: dict[str, Any] | None


@dataclass(frozen=True)
class _Plan:
    """What a start submits: the request, and the job's input as stored (which a submission
    extends).
    """

    request: dict[str, Any]
    recorded: dict[str, Any]


class GenerateLastFrameHandler(SceneFrameHandler):
    job_type = JOB_TYPE
    label = "last frame"
    role = "last_frame"

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

        base_url = read.base_url
        ready: _Plan = plan

        async def build_body() -> tuple[dict[str, Any], dict[str, Any]]:
            return await self._upload_reference(base_url, ready)

        await self.submit(
            job_id,
            base_url,
            ready.request,
            ready.recorded,
            endpoint=image_generator.EDIT_PATH,
            build_body=build_body,
        )

    @staticmethod
    def _stored_plan(job_input: dict[str, Any]) -> _Plan | None:
        """The plan of an earlier attempt, read back from the job's input. None the first time."""
        request = job_input.get("request")
        if (
            not isinstance(request, dict)
            or job_input.get("endpoint") != image_generator.EDIT_PATH
            or not isinstance(job_input.get("scene_sent"), dict)
            or not isinstance(job_input.get("reference"), dict)
        ):
            return None
        return _Plan(request=request, recorded=job_input)

    async def _prepare(
        self, job_id: int, read: _Read, project: Project, scene: Scene
    ) -> _Plan | None:
        """Works out the request and the reference picture and stores them on the job, before
        anything is sent. Runs on the first attempt only. Fails the job (returns None) when the
        approved GPU API has no edit endpoint, the first frame cannot be read, or the request
        would be refused.
        """
        await self._phase(job_id, phases.PREPARING_IMAGE_REQUEST)
        first_frame = read.first_frame
        if first_frame is None:
            await self._fail(job_id, _REFERENCE_GONE)
            return None
        prompt = (scene.last_frame_prompt or "").strip()
        async with SessionLocal() as session:
            try:
                reference, aspect_ratio = await self._reference(session, project, first_frame)
            except (derived_frames.FrameNotUsable, StorageError) as exc:
                await session.rollback()
                await self._fail(job_id, str(exc) or _REFERENCE_GONE)
                return None
            await session.commit()

        try:
            image_generator.check_edit_endpoint(read.spec)
            request = image_generator.build_edit_request(
                prompt=prompt,
                mode=read.mode,
                seed=secrets.randbelow(image_models.SEED_LIMIT),
                aspect_ratio=aspect_ratio,
                partition=read.partition,
            )
        except ValueError as exc:
            await self._fail(job_id, str(exc))
            return None

        expected = image_models.ASPECT_SIZES.get(aspect_ratio or "")
        recorded: dict[str, Any] = {
            **read.job_input,
            "scene_sent": scene_record(scene),
            "edit_prompt": prompt,
            "last_frame_prompt_source": scene.last_frame_prompt_source,
            "last_frame_prompt_job_id": scene.last_frame_prompt_job_id,
            "replacing_asset_id": scene.last_frame_asset_id,
            "reference": {
                "first_frame_asset_id": first_frame.id,
                "sent_asset_id": reference.id,
                "is_raw": reference.id != first_frame.id and reference.source == "ai",
            },
            "frame_size": {"width": project.gen_width, "height": project.gen_height},
            "image_model": image_models.MODEL_ID,
            "image_mode": read.mode,
            "aspect_ratio": aspect_ratio,
            "expected_size": {"width": expected[0], "height": expected[1]} if expected else None,
            "endpoint": image_generator.EDIT_PATH,
            "request": request,
        }
        async with SessionLocal() as session:
            if not await store.update_input(session, job_id, recorded):
                return None  # cancelled while preparing: nothing was sent
        return _Plan(request=request, recorded=recorded)

    @staticmethod
    async def _reference(
        session: AsyncSession, project: Project, first_frame: Asset
    ) -> tuple[Asset, str | None]:
        """The picture to edit, and the shape to ask for (None: the shape of that picture).

        A first frame the image model made is edited from its raw image, in the shape it asked
        for. Any other first frame is sent as the video model gets it, normalised to the
        project's generation size.
        """
        provenance: Any = first_frame.provenance
        raw_id = provenance.get("raw_asset_id") if isinstance(provenance, dict) else None
        if (
            first_frames_service.is_ai_frame(first_frame)
            and isinstance(raw_id, int)
            and not isinstance(raw_id, bool)
        ):
            raw = await session.get(Asset, raw_id)
            if raw is not None and raw.kind == "frame" and raw.project_id == project.id:
                try:
                    present = get_storage().get_path(raw.path).is_file()
                except StorageError:
                    present = False
                if present:
                    shape = provenance.get("aspect_ratio")
                    return raw, shape if shape in image_models.ASPECT_RATIOS else None
        sent = await derived_frames.frame_to_send(
            session, first_frame, project.gen_width, project.gen_height
        )
        return sent, None

    @staticmethod
    async def _upload_reference(
        base_url: str, plan: _Plan
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Uploads the reference picture and makes the body to send. It runs at every start,
        because the server deletes the inputs of a job when it ends. Raises `GpuCallError` and
        `StorageError`.
        """
        reference = plan.recorded["reference"]
        sent_id = reference.get("sent_asset_id")
        async with SessionLocal() as session:
            asset = await session.get(Asset, sent_id) if isinstance(sent_id, int) else None
            await session.commit()
        if asset is None:
            raise StorageError("The reference picture is gone.")
        filename = f"reference-{asset.id}.png"
        remote_id = await image_generator.upload_reference(
            base_url, get_storage().get_path(asset.path), filename
        )
        body = image_generator.with_references(plan.request, [remote_id])
        uploads = [
            {
                "asset_id": asset.id,
                "filename": filename,
                "size_bytes": asset.size_bytes,
                "remote_asset_id": remote_id,
            }
        ]
        return body, {"uploads": uploads, "body": body}

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
            first_frame: Asset | None = None
            if project is not None and scene is not None:
                # The same refusals as the endpoints: things may have changed while the job
                # waited for its turn.
                state = await scenes_service.scenes_state(session, project)
                draft_job = await store.latest_job(session, project.id, DRAFT_JOB)
                prompt_states = await last_prompts_service.prompt_states(session, project, [scene])
                active_prompts = await last_prompts_service.active_prompt_jobs(session, project.id)
                active_firsts = await first_frames_service.active_frame_jobs(session, project.id)
                frames = await scene_inputs.load_frames(session, [scene])
                first_frame = frames.get(scene.first_frame_asset_id or 0)
                last_frame = frames.get(scene.last_frame_asset_id or 0)
                block = image_prompts_service.project_block(
                    state.scenes,
                    plan_job=state.job,
                    stale_reasons=state.stale_reasons,
                    draft_job=draft_job,
                ) or last_frames_service.scene_block(
                    scene,
                    first_frame,
                    prompt_out_of_date=scene.id in prompt_states
                    and prompt_states[scene.id].out_of_date,
                    prompt_job_active=scene.id in active_prompts,
                    first_frame_job_active=scene.id in active_firsts,
                )
                # Manual-first: an uploaded last frame is replaced only when the click
                # confirmed that very frame.
                if block is None and last_frames_service.needs_upload_confirmation(
                    scene, last_frame
                ):
                    confirmed = (
                        job_input.get("replace_upload") is True
                        and job_input.get("last_frame_at_click") == scene.last_frame_asset_id
                    )
                    if not confirmed:
                        block = _UPLOAD_ADDED
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            partition = await settings_service.get_str(session, PARTITION_KEY)
            mode = image_models.resolve_mode(
                await settings_service.get_str(session, IMAGE_MODE_KEY)
            )
            bodies = await contract_guard.latest_bodies(session)
            await session.commit()
        spec = next((body for body in bodies if api_contract.is_openapi(body)), None)
        return _Read(
            job_input=job_input,
            project=project,
            scene=scene,
            first_frame=first_frame,
            block=block,
            base_url=base_url,
            partition=partition,
            mode=mode,
            spec=spec,
        )

    # --- What a last frame does with the image (`SceneFrameHandler`'s hooks) ---------------

    def prompt_provenance(self, recorded: dict[str, Any]) -> dict[str, Any]:
        reference = recorded.get("reference")
        reference = reference if isinstance(reference, dict) else {}
        return {
            "prompt": recorded.get("edit_prompt"),
            "last_frame_prompt_source": recorded.get("last_frame_prompt_source"),
            "last_frame_prompt_job_id": recorded.get("last_frame_prompt_job_id"),
            "reference_asset_id": reference.get("first_frame_asset_id"),
            "reference_sent_asset_id": reference.get("sent_asset_id"),
        }

    def attach_reason(self, current: Scene, recorded: dict[str, Any]) -> str | None:
        scene_sent = recorded.get("scene_sent")
        replacing = recorded.get("replacing_asset_id")
        reference = recorded.get("reference")
        edited = reference.get("first_frame_asset_id") if isinstance(reference, dict) else None
        return last_frames_service.attach_block(
            current,
            scene_sent if isinstance(scene_sent, dict) else {},
            replacing if isinstance(replacing, int) else None,
            edited if isinstance(edited, int) else None,
        )

    async def attach(
        self, session: AsyncSession, current: Scene, frame: Asset, recorded: dict[str, Any]
    ) -> dict[str, Any]:
        current.last_frame_asset_id = frame.id
        # A scene that continues this scene's action starts on this frame, in the same
        # transaction, so the two never disagree.
        chained = await last_frames_service.apply_chains(session, current.project_id)
        return {"chained_scene_ids": chained}
