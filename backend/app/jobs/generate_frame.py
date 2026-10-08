"""The `generate_frame` job: one image from the image model for one scene's first frame
(ANALYSIS.md Section 4.2 and 6.2; Phase 17).

It is a scene job (`job.scene_id`) and a paid job, so the rules of the other paid jobs hold:

- It only starts from a click (`POST .../generate-first-frames` or `.../generate-first-frame`).
- **One call, never retried, never cached.** Every image costs money and comes out different
  (the Phase 13 rule), so there is no second attempt and no answer cache. A failed call is
  shown, and the user decides whether to pay again.
- Everything that can be checked for free is checked before the call: the blocks, the
  manual-first rule (an uploaded frame is only replaced when the click confirmed it), and the
  size. The exact request is saved on the job before the call.
- The answer is saved on the job the moment it arrives, and the raw image is stored as an asset
  before anything is done to it. A paid image is never lost to a later failure.
- A restart never re-runs it (`never_rerun`): the dispatcher fails it with a message. A raw
  image that was already stored stays, and is named in `job.output`.

What it makes (`services/frame_geometry.py`): the image model is asked for 1.5 times the
generation size plus a band, because it stamps a label in the bottom-right corner. The band is
cut off the bottom and the rest is shrunk by 2/3 to exactly the generation size
(`services/frame_images.crop_bottom_and_fit`). **The crop is measured at the size asked for, so
it is never applied to an image of another size**: the job fails instead, and keeps the raw
image.

The frame becomes the scene's first frame only if the scene's first frame is still the one the
job started from and its cut is unchanged (`services/first_frames.attach_block`). Otherwise
the frame is kept, listed among the scene's earlier frames, and the job still succeeds: the
image is paid for and usable.

It is a local-style job: everything happens in `start`. There is no provider job id. Logs hold
ids, sizes, seconds and usage, never the prompt.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Asset, Project, Scene
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.handlers import JobHandler
from app.jobs.plan_scenes import LLM_URL_KEY
from app.providers import image_api
from app.services import first_frames as frames_service
from app.services import frame_images, scene_inputs
from app.services import image_prompts as prompts_service
from app.services import scenes as scenes_service
from app.services.assets import add_asset
from app.services.descriptions import DRAFT_JOB
from app.services.frame_geometry import (
    BOX_TOP_PER_10000,
    CROP_MARGIN_PX,
    GEOMETRY_VERSION,
    RULE,
    FrameGeometry,
    frame_geometry,
)
from app.services.frame_images import FrameRejected
from app.services.storage import StorageError, StoredFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = frames_service.FRAME_JOB
IMAGE_MODEL_KEY: Final = "image_model"
MAX_PARALLEL_KEY: Final = "max_parallel_image_generations"

_UPLOAD_ADDED = (
    "A frame was attached to this scene after the click, so no image was made. Generate "
    "again to replace it."
)


@dataclass
class _Read:
    """What `start` reads before the call. `block` is why no image may be made, if any."""

    job_input: dict[str, Any]
    project: Project | None
    scene: Scene | None
    block: str | None
    base_url: str
    model: str


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


def _geometry_record(geometry: FrameGeometry) -> dict[str, Any]:
    return {
        "rule": RULE,
        "version": GEOMETRY_VERSION,
        "gen_width": geometry.gen_width,
        "gen_height": geometry.gen_height,
        "request_width": geometry.request_width,
        "request_height": geometry.request_height,
        "crop_bottom": geometry.crop_bottom,
    }


class GenerateFrameHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "image"
    restart_rule = "never_rerun"

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return await settings_service.get_int(session, MAX_PARALLEL_KEY)

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        read = await self._read(job_id)
        if read is None:
            return
        if read.project is None or read.scene is None:
            await self._fail(job_id, "The project or the scene no longer exists.")
            return
        if read.block is not None:
            await self._fail(job_id, read.block)
            return
        project, scene = read.project, read.scene

        await self._phase(job_id, phases.PREPARING_IMAGE_REQUEST)
        try:
            geometry = frame_geometry(project.gen_width, project.gen_height)
        except ValueError as exc:
            await self._fail(job_id, str(exc))
            return
        prompt = (scene.image_prompt or "").strip()
        body = {
            "model": read.model,
            "prompt": prompt,
            "size": geometry.request_size,
            "response_format": "b64_json",
        }
        scene_sent = _scene_record(scene)
        replacing_asset_id = scene.first_frame_asset_id
        job_input = {
            **read.job_input,
            "scene_sent": scene_sent,
            "image_prompt": prompt,
            "image_prompt_source": scene.image_prompt_source,
            "image_prompt_job_id": scene.image_prompt_job_id,
            "replacing_asset_id": replacing_asset_id,
            "geometry": _geometry_record(geometry),
            "server_url": docker_mapped(read.base_url),
            "endpoint": image_api.GENERATIONS_PATH,
            "request": body,
        }
        async with SessionLocal() as session:
            if not await store.update_input(session, job_id, job_input):
                return  # cancelled while preparing: nothing was paid for

        # The one paid call. No transaction is open, and nothing here retries it.
        await self._phase(job_id, phases.GENERATING_IMAGE)
        result = await image_api.generate(read.base_url, body)
        output: dict[str, Any] = {
            "http_status": result.http_status,
            "seconds": round(result.seconds, 1),
            "usage": result.usage,
            "response": result.response,
            "error": result.error,
            "raw_asset_id": None,
            "returned_size": None,
        }
        await self._record(job_id, output)
        if not result.ok:
            reason = (result.error or "No explanation was given.").rstrip()
            if not reason.endswith((".", "!", "?")):
                reason += "."
            await self._fail(
                job_id,
                f"The image could not be made: {reason} It was not retried automatically.",
            )
            return
        _logger.info(
            "job %d: image answered: http=%s %.1f s usage=%s",
            job_id,
            result.http_status,
            result.seconds,
            result.usage,
        )

        # The raw image first, exactly as it came: it is what was paid for.
        await self._phase(job_id, phases.SAVING_IMAGE)
        storage = get_storage()
        image_bytes = result.images[0]
        try:
            temp = await storage.receive(_one_chunk(image_bytes), max_bytes=len(image_bytes))
            try:
                info = await frame_images.run_pillow(frame_images.inspect_image, temp.path)
                raw_stored = await storage.save(temp, project.id, info.ext)
            except BaseException:
                storage.discard(temp)
                raise
        except FrameRejected as exc:
            await self._fail(job_id, f"The image could not be used: {exc.message}")
            return
        except StorageError as exc:
            await self._fail(job_id, f"The image could not be stored: {exc}")
            return

        raw_provenance = {
            "role": "seedream_raw",
            "provider": "bitdeer",
            "model": read.model,
            "job_id": job_id,
            "scene_id": scene.id,
            "prompt": prompt,
            "requested_size": {"width": geometry.request_width, "height": geometry.request_height},
            "usage": result.usage,
            "seconds": round(result.seconds, 1),
        }
        async with SessionLocal() as session:
            try:
                raw = await add_asset(
                    session,
                    project_id=project.id,
                    kind="frame",
                    stored=raw_stored,
                    mime=info.mime,
                    size_bytes=temp.size_bytes,
                    sha256=temp.sha256,
                    source="ai",
                    width=info.width,
                    height=info.height,
                    provenance=raw_provenance,
                )
                await session.commit()
            except BaseException:
                # Stored files are never deleted, so this leaves an unreferenced file behind.
                _logger.warning(
                    "job %d: image stored but not recorded: %s", job_id, raw_stored.relative_path
                )
                raise
        output["raw_asset_id"] = raw.id
        output["returned_size"] = {"width": info.width, "height": info.height}
        await self._record(job_id, output)

        if (info.width, info.height) != (geometry.request_width, geometry.request_height):
            await self._fail(
                job_id,
                f"The image model returned {info.width} x {info.height}, not the "
                f"{geometry.request_width} x {geometry.request_height} asked for. The crop is "
                f"measured at the size asked for, so no frame was made. The image is kept as "
                f"asset {raw.id}.",
            )
            return

        await self._phase(job_id, phases.CROPPING_FRAME)
        try:
            png = await frame_images.run_pillow(
                frame_images.crop_bottom_and_fit,
                raw_stored.path,
                geometry.crop_bottom,
                geometry.gen_width,
                geometry.gen_height,
            )
            frame_temp = await storage.receive(_one_chunk(png), max_bytes=len(png))
            try:
                frame_stored = await storage.save(frame_temp, project.id, "png")
            except BaseException:
                storage.discard(frame_temp)
                raise
        except (ValueError, OSError, StorageError) as exc:
            await self._fail(
                job_id,
                f"The frame could not be made from the image: {exc} The image is kept as "
                f"asset {raw.id}.",
            )
            return

        await self._save(
            job_id,
            project=project,
            scene_sent=scene_sent,
            replacing_asset_id=replacing_asset_id,
            geometry=geometry,
            prompt=prompt,
            scene=scene,
            read=read,
            raw=raw,
            result=result,
            frame_stored=frame_stored,
            frame_size=(frame_temp.size_bytes, frame_temp.sha256),
            output=output,
            started=started,
        )

    # --- Reading ----------------------------------------------------------------------

    async def _read(self, job_id: int) -> _Read | None:
        """Everything `start` needs, in one short read. None when there is nothing to run. The
        reasons an image may not be made are worked out here, before any call.
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
            base_url = await settings_service.get_str(session, LLM_URL_KEY)
            model = await settings_service.get_str(session, IMAGE_MODEL_KEY)
            await session.commit()
        return _Read(
            job_input=job_input,
            project=project,
            scene=scene,
            block=block,
            base_url=base_url,
            model=model,
        )

    # --- Saving the frame -----------------------------------------------------------------

    async def _save(
        self,
        job_id: int,
        *,
        project: Project,
        scene: Scene,
        scene_sent: dict[str, Any],
        replacing_asset_id: int | None,
        geometry: FrameGeometry,
        prompt: str,
        read: _Read,
        raw: Asset,
        result: image_api.ImageCallResult,
        frame_stored: StoredFile,
        frame_size: tuple[int, str],
        output: dict[str, Any],
        started: float,
    ) -> None:
        """Stores the frame and, if the scene still allows it, makes it the first frame, and
        finishes the job: all in one transaction.
        """
        await self._phase(job_id, phases.SAVING_FRAME)
        provenance: dict[str, Any] = {
            "role": "first_frame",
            "provider": "bitdeer",
            "model": read.model,
            "endpoint": image_api.GENERATIONS_PATH,
            "server_url": docker_mapped(read.base_url),
            "job_id": job_id,
            "scene_id": scene.id,
            "scene_start_s": scene.start_s,
            "scene_end_s": scene.end_s,
            "prompt": prompt,
            "image_prompt_source": scene.image_prompt_source,
            "image_prompt_job_id": scene.image_prompt_job_id,
            "requested_size": {"width": geometry.request_width, "height": geometry.request_height},
            "returned_size": output["returned_size"],
            "crop_bottom": geometry.crop_bottom,
            "geometry": {
                "rule": RULE,
                "version": GEOMETRY_VERSION,
                "box_top_per_10000": BOX_TOP_PER_10000,
                "margin_px": CROP_MARGIN_PX,
            },
            "resized_to": {"width": geometry.gen_width, "height": geometry.gen_height},
            "raw_asset_id": raw.id,
            "usage": result.usage,
            "seconds": round(result.seconds, 1),
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
                    job_id,
                    scene.id,
                    frame_stored.relative_path,
                )
                return
            frame = await add_asset(
                session,
                project_id=project.id,
                kind="frame",
                stored=frame_stored,
                mime="image/png",
                size_bytes=size_bytes,
                sha256=sha256,
                source="ai",
                width=geometry.gen_width,
                height=geometry.gen_height,
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
                "crop_bottom": geometry.crop_bottom,
                "total_seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, final, result_asset_id=frame.id):
                await session.rollback()
                _logger.warning(
                    "job %d: frame stored but the job is no longer running: %s",
                    job_id,
                    frame_stored.relative_path,
                )
                return
            await session.commit()

        _logger.info(
            "job %d: first frame made: scene=%d raw=%d frame=%d %dx%d from %dx%d crop=%d "
            "attached=%s %.1f s usage=%s",
            job_id,
            scene.id,
            raw.id,
            frame.id,
            geometry.gen_width,
            geometry.gen_height,
            geometry.request_width,
            geometry.request_height,
            geometry.crop_bottom,
            attached,
            final["total_seconds"],
            result.usage,
        )

    # --- Small helpers ----------------------------------------------------------------------

    @staticmethod
    async def _record(job_id: int, output: dict[str, Any]) -> None:
        async with SessionLocal() as session:
            await store.record_output(session, job_id, dict(output))

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
