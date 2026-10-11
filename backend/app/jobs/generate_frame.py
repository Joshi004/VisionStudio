"""The `generate_frame` job: one first frame for one scene, made by Qwen-Image-2.1 on the GPU
server (ANALYSIS.md Section 4.2 and 6.2; Phase 17).

It is a remote job, like `generate_clip`. The steps every Qwen image job shares (submit, poll,
download, the failure rules) are `RemoteImageHandler`'s (`jobs/remote_image.py`). This module is
what is particular to a scene's first frame:

- `start`: check that a frame may be made, build the request (the first time only) and submit.
- `store_image`: store the PNG as it came, fit it to the project's generation size and, if the
  scene still allows it, make it the scene's first frame.

**It only starts from a click** (`POST .../generate-first-frames` or `.../generate-first-frame`),
and everything that can be checked for free is checked before anything is sent: the blocks, the
manual-first rule (an uploaded frame is only replaced when the click confirmed it) and the
approved GPU API (it must have the image endpoint).

**The request is built once.** The first `start` stores it in `job.input`: the prompt, the mode
(Settings, "Image mode"), the nearest of the model's seven shapes and a random seed. Every later
attempt (after a pre-emption, an expired result or a server that could not be reached) sends the
same stored request, because "the correct response to a pre-emption failure is to resubmit the
exact same request unchanged" (the server's guide). A new seed comes only with a new job.

**The server may keep a result for one download only** (it says so in its guide for version 0.9.0).
So the raw image is stored as an asset before anything else is done with it, and a later failure
keeps that asset and names it in the error.

What it makes: Qwen-Image-2.1 answers in one of seven shapes at its native 2K size
(`services/image_models.ASPECT_SIZES`), which are not the project's generation size. The nearest
shape is asked for, and `frame_images.render_frame_png` scales it until it covers the generation
size and cuts the overflow evenly from both sides. That is a few percent at most for the
orientation defaults (1088 x 1920 from 1536 x 2752 loses about 1.5% of the height).

The frame becomes the scene's first frame only if the scene's first frame is still the one the
job started from and its cut is unchanged (`services/first_frames.attach_block`). Otherwise the
frame is kept, listed among the scene's earlier frames, and the job still succeeds.

Logs hold ids, sizes and phases, never the prompt.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbound
from app.core import settings as settings_service
from app.db.models import Asset, Job, Project, Scene
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.generate_clip import GPU_URL_KEY, PARTITION_KEY
from app.jobs.remote_image import RemoteImageHandler
from app.providers import contract_guard, image_generator
from app.services import api_contract, frame_images, image_models, scene_inputs
from app.services import first_frames as frames_service
from app.services import image_prompts as prompts_service
from app.services import scenes as scenes_service
from app.services.assets import add_asset
from app.services.descriptions import DRAFT_JOB
from app.services.frame_images import FrameRejected
from app.services.storage import StorageError, StoredFile, TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = frames_service.FRAME_JOB
IMAGE_MODE_KEY: Final = "image_mode"
MAX_PARALLEL_KEY: Final = "max_parallel_image_generations"

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


@dataclass(frozen=True)
class _Plan:
    """What a start submits: the request, and the job's input as stored (which a submission
    extends).
    """

    request: dict[str, Any]
    recorded: dict[str, Any]


def _scene_record(scene: Scene) -> dict[str, Any]:
    return {
        "scene_id": scene.id,
        "index": scene.index,
        "start_s": scene.start_s,
        "end_s": scene.end_s,
        "text": scene.text,
    }


async def _one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


class GenerateFrameHandler(RemoteImageHandler):
    job_type = JOB_TYPE

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return await settings_service.get_int(session, MAX_PARALLEL_KEY)

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
        await self.submit(job_id, read.base_url, plan.request, plan.recorded)

    @staticmethod
    def _stored_plan(job_input: dict[str, Any]) -> _Plan | None:
        """The plan of an earlier attempt, read back from the job's input. None the first time."""
        request = job_input.get("request")
        if (
            not isinstance(request, dict)
            or job_input.get("endpoint") != image_generator.GENERATE_PATH
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
        try:
            image_generator.check_endpoint(read.spec)
            aspect_ratio = image_models.pick_aspect_ratio(project.gen_width, project.gen_height)
            request = image_generator.build_request(
                prompt=prompt,
                mode=read.mode,
                seed=secrets.randbelow(image_models.SEED_LIMIT),
                aspect_ratio=aspect_ratio,
                partition=read.partition,
            )
        except ValueError as exc:
            await self._fail(job_id, str(exc))
            return None

        expected_width, expected_height = image_models.ASPECT_SIZES[aspect_ratio]
        recorded: dict[str, Any] = {
            **read.job_input,
            "scene_sent": _scene_record(scene),
            "image_prompt": prompt,
            "image_prompt_source": scene.image_prompt_source,
            "image_prompt_job_id": scene.image_prompt_job_id,
            "replacing_asset_id": scene.first_frame_asset_id,
            "frame_size": {"width": project.gen_width, "height": project.gen_height},
            "image_model": image_models.MODEL_ID,
            "image_mode": read.mode,
            "aspect_ratio": aspect_ratio,
            "expected_size": {"width": expected_width, "height": expected_height},
            "endpoint": image_generator.GENERATE_PATH,
            "request": request,
        }
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
            if project is not None and scene is not None:
                # The same refusals as the endpoints: things may have changed while the job
                # waited for its turn.
                state = await scenes_service.scenes_state(session, project)
                draft_job = await store.latest_job(session, project.id, DRAFT_JOB)
                prompt_states = await prompts_service.prompt_states(session, project, [scene])
                active_prompts = await prompts_service.active_prompt_jobs(session, project.id)
                frames = await scene_inputs.load_frames(session, [scene])
                first_frame: Asset | None = frames.get(scene.first_frame_asset_id or 0)
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
        )

    async def store_image(
        self, job: Job, base_url: str, result: outbound.DownloadResult, dest: Path
    ) -> None:
        """The image is downloaded. Stores it exactly as it came, then makes the frame from it.

        The raw image is stored and recorded first, and the job's output names it, so a
        failure in any later step keeps it.
        """
        recorded = job.input if isinstance(job.input, dict) else {}
        request = recorded.get("request") if isinstance(recorded.get("request"), dict) else {}
        async with SessionLocal() as session:
            project = await session.get(Project, job.project_id) if job.project_id else None
            scene = await session.get(Scene, job.scene_id) if job.scene_id else None
            await session.commit()
        if project is None or scene is None:
            await self._fail_and_purge(
                job, base_url, "The project or the scene no longer exists, so no frame was made."
            )
            return

        storage = get_storage()
        output: dict[str, Any] = dict(job.output) if isinstance(job.output, dict) else {}
        try:
            info = await frame_images.run_pillow(frame_images.inspect_image, dest)
        except FrameRejected as exc:
            await self._fail_and_purge(job, base_url, f"The image could not be used: {exc.message}")
            return

        await self._phase(job.id, phases.SAVING_IMAGE)
        remote = output.get("remote") if isinstance(output.get("remote"), dict) else None
        raw_provenance = {
            "role": "image_raw",
            "provider": "gpu_server",
            "model": recorded.get("image_model") or image_models.MODEL_ID,
            "mode": request.get("mode"),
            "seed": request.get("seed"),
            "aspect_ratio": request.get("aspect_ratio"),
            "endpoint": recorded.get("endpoint"),
            "pipeline": remote.get("pipeline") if remote else None,
            "server_url": recorded.get("server_url"),
            "provider_job_id": job.provider_job_id,
            "job_id": job.id,
            "scene_id": scene.id,
            "prompt": recorded.get("image_prompt"),
            "expected_size": recorded.get("expected_size"),
        }
        try:
            temp = TempFile(path=dest, size_bytes=result.size_bytes, sha256=result.sha256)
            raw_stored = await storage.save(temp, project.id, info.ext)
        except StorageError as exc:
            await self._fail_and_purge(job, base_url, f"The image could not be stored: {exc}")
            return
        async with SessionLocal() as session:
            try:
                raw = await add_asset(
                    session,
                    project_id=project.id,
                    kind="frame",
                    stored=raw_stored,
                    mime=info.mime,
                    size_bytes=result.size_bytes,
                    sha256=result.sha256,
                    source="ai",
                    width=info.width,
                    height=info.height,
                    provenance=raw_provenance,
                )
                await session.commit()
            except BaseException:
                # Stored files are never deleted, so this leaves an unreferenced file behind.
                _logger.warning(
                    "job %d: image stored but not recorded: %s", job.id, raw_stored.relative_path
                )
                raise
        output["raw_asset_id"] = raw.id
        output["returned_size"] = {"width": info.width, "height": info.height}
        async with SessionLocal() as session:
            await store.record_output(session, job.id, dict(output))

        frame_size = (
            recorded.get("frame_size") if isinstance(recorded.get("frame_size"), dict) else {}
        )
        gen_width = _whole(frame_size.get("width")) or project.gen_width
        gen_height = _whole(frame_size.get("height")) or project.gen_height

        await self._phase(job.id, phases.FITTING_FRAME)
        try:
            png = await frame_images.run_pillow(
                frame_images.render_frame_png, raw_stored.path, gen_width, gen_height
            )
            frame_temp = await storage.receive(_one_chunk(png), max_bytes=len(png))
            try:
                frame_stored = await storage.save(frame_temp, project.id, "png")
            except BaseException:
                storage.discard(frame_temp)
                raise
        except (ValueError, OSError, StorageError) as exc:
            await self._fail_and_purge(
                job,
                base_url,
                f"The frame could not be made from the image: {exc} The image is kept as "
                f"asset {raw.id}.",
            )
            return

        saved = await self._save(
            job,
            project=project,
            scene=scene,
            recorded=recorded,
            gen_size=(gen_width, gen_height),
            raw=raw,
            frame_stored=frame_stored,
            frame_size=(frame_temp.size_bytes, frame_temp.sha256),
            output=output,
        )
        if saved:
            # Best effort: a failure here is recorded and never fails the frame.
            purge = await self._purge(base_url, job.provider_job_id)
            async with SessionLocal() as session:
                await store.merge_output(session, job.id, {"purge": purge})

    # --- Saving the frame -----------------------------------------------------------------

    async def _save(
        self,
        job: Job,
        *,
        project: Project,
        scene: Scene,
        recorded: dict[str, Any],
        gen_size: tuple[int, int],
        raw: Asset,
        frame_stored: StoredFile,
        frame_size: tuple[int, str],
        output: dict[str, Any],
    ) -> bool:
        """Stores the frame and, if the scene still allows it, makes it the first frame, and
        finishes the job: all in one transaction. False when the job could not be finished
        (the scene is gone, or the job is no longer running).
        """
        await self._phase(job.id, phases.SAVING_FRAME)
        gen_width, gen_height = gen_size
        scene_sent = (
            recorded.get("scene_sent") if isinstance(recorded.get("scene_sent"), dict) else {}
        )
        replacing = recorded.get("replacing_asset_id")
        replacing_asset_id = replacing if isinstance(replacing, int) else None
        request = recorded.get("request") if isinstance(recorded.get("request"), dict) else {}
        remote = output.get("remote") if isinstance(output.get("remote"), dict) else None
        provenance: dict[str, Any] = {
            "role": "first_frame",
            "provider": "gpu_server",
            "model": recorded.get("image_model") or image_models.MODEL_ID,
            "mode": request.get("mode"),
            "seed": request.get("seed"),
            "aspect_ratio": request.get("aspect_ratio"),
            "endpoint": recorded.get("endpoint"),
            "pipeline": remote.get("pipeline") if remote else None,
            "server_url": recorded.get("server_url"),
            "provider_job_id": job.provider_job_id,
            "job_id": job.id,
            "scene_id": scene.id,
            "scene_start_s": scene.start_s,
            "scene_end_s": scene.end_s,
            "prompt": recorded.get("image_prompt"),
            "image_prompt_source": recorded.get("image_prompt_source"),
            "image_prompt_job_id": recorded.get("image_prompt_job_id"),
            "expected_size": recorded.get("expected_size"),
            "returned_size": output.get("returned_size"),
            "resized_to": {"width": gen_width, "height": gen_height},
            "raw_asset_id": raw.id,
        }
        size_bytes, sha256 = frame_size
        async with SessionLocal() as session:
            # Taking the database's write lock first means no cut edit and no other change of
            # the scene can happen between the check below and the write.
            await scenes_service.lock_scenes(session, project.id)
            current = await session.get(Scene, scene.id, populate_existing=True)
            if current is None:
                # The scene was merged away, and its jobs with it.
                await session.rollback()
                _logger.warning(
                    "job %d: scene %d is gone; frame stored but not recorded: %s",
                    job.id,
                    scene.id,
                    frame_stored.relative_path,
                )
                return False
            frame = await add_asset(
                session,
                project_id=project.id,
                kind="frame",
                stored=frame_stored,
                mime="image/png",
                size_bytes=size_bytes,
                sha256=sha256,
                source="ai",
                width=gen_width,
                height=gen_height,
                provenance=provenance,
            )
            reason = frames_service.attach_block(current, scene_sent, replacing_asset_id)
            attached = reason is None
            if attached:
                current.first_frame_asset_id = frame.id
            final = {
                **output,
                "frame_asset_id": frame.id,
                "attached": attached,
                "not_attached_reason": reason,
                "replaced_asset_id": replacing_asset_id if attached else None,
            }
            if not await store.finish_job(session, job.id, final, result_asset_id=frame.id):
                await session.rollback()
                _logger.warning(
                    "job %d: frame stored but the job is no longer running: %s",
                    job.id,
                    frame_stored.relative_path,
                )
                return False
            await session.commit()

        returned = output.get("returned_size")
        _logger.info(
            "job %d: first frame made: scene=%d raw=%d frame=%d %dx%d from %s attached=%s",
            job.id,
            scene.id,
            raw.id,
            frame.id,
            gen_width,
            gen_height,
            f"{returned['width']}x{returned['height']}" if isinstance(returned, dict) else "?",
            attached,
        )
        return True


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
