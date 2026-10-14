"""What a scene's first frame job (`generate_frame`) and its last frame job (`generate_last_frame`)
share once the GPU server has made the image (Phase 17, shared with Phase 23).

Both make one frame for one scene with Qwen-Image-2.1. The first frame is made from a prompt, the
last frame by editing the first frame, so how their requests are built and submitted differs
(and is each job's own `start`). What happens to the PNG afterwards is the same, and is here:

- `store_image`: store the PNG exactly as it came, fit it to the project's generation size and,
  if the scene still allows it, make it the scene's frame.
- `_save`: the transaction that stores the frame, attaches it and finishes the job.

**The server may keep a result for one download only** (it says so in its guide for version
0.9.0). So the raw image is stored as an asset before anything else is done with it, and a later
failure keeps that asset and names it in the error.

What it makes: Qwen-Image-2.1 answers in one of seven shapes at its native 2K size
(`services/image_models.ASPECT_SIZES`), or, for an edit that names no shape, in the shape of its
reference picture. Neither is the project's generation size. `frame_images.render_frame_png`
scales the image until it covers the generation size and cuts the overflow evenly from both
sides. That is a few percent at most for the orientation defaults (1088 x 1920 from 1536 x 2752
loses about 1.5% of the height).

A frame becomes the scene's frame only if the scene still allows it. The subclass says (`attach`
and `attach_reason`): the scene's cut must be unchanged and the frame slot must still hold what
the job started from. Otherwise the frame is kept, listed among the scene's earlier frames, and
the job still succeeds.

Logs hold ids, sizes and phases, never the prompt.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbound
from app.db.models import Asset, Job, Project, Scene
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.remote_image import RemoteImageHandler
from app.services import frame_images, image_models
from app.services import scenes as scenes_service
from app.services.assets import add_asset
from app.services.frame_images import FrameRejected
from app.services.storage import StorageError, StoredFile, TempFile, get_storage

_logger = logging.getLogger(__name__)


def scene_record(scene: Scene) -> dict[str, Any]:
    """The scene as the request was made for it: its cut. A frame is attached only while the
    scene still has this cut.
    """
    return {
        "scene_id": scene.id,
        "index": scene.index,
        "start_s": scene.start_s,
        "end_s": scene.end_s,
        "text": scene.text,
    }


async def _one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


class SceneFrameHandler(RemoteImageHandler):
    """A job that makes one frame of one scene. A subclass writes `start` (it builds the
    request and submits it) and the four hooks below.
    """

    # What the frame is called in a log line: "first frame", "last frame".
    label: str
    # What the stored frame's provenance says it is (`first_frame`, `last_frame`).
    role: str

    # --- The hooks ------------------------------------------------------------------------

    @abstractmethod
    def prompt_provenance(self, recorded: dict[str, Any]) -> dict[str, Any]:
        """What the frame's provenance says about the prompt it was made from. It has a
        `prompt` key, and whatever else says where that prompt came from.
        """

    @abstractmethod
    def attach_reason(self, current: Scene, recorded: dict[str, Any]) -> str | None:
        """Why the frame may not become the scene's frame as the scene is *now*, or None."""

    @abstractmethod
    async def attach(
        self, session: AsyncSession, current: Scene, frame: Asset, recorded: dict[str, Any]
    ) -> dict[str, Any]:
        """Makes `frame` the scene's frame, in the transaction that stores it. Returns what to
        add to the job's output.
        """

    # --- store_image ----------------------------------------------------------------------

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
            "prompt": self.prompt_provenance(recorded).get("prompt"),
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
        """Stores the frame and, if the scene still allows it, makes it the scene's frame, and
        finishes the job: all in one transaction. False when the job could not be finished
        (the scene is gone, or the job is no longer running).
        """
        await self._phase(job.id, phases.SAVING_FRAME)
        gen_width, gen_height = gen_size
        replacing = recorded.get("replacing_asset_id")
        replacing_asset_id = replacing if isinstance(replacing, int) else None
        request = recorded.get("request") if isinstance(recorded.get("request"), dict) else {}
        remote = output.get("remote") if isinstance(output.get("remote"), dict) else None
        provenance: dict[str, Any] = {
            "role": self.role,
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
            **self.prompt_provenance(recorded),
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
            reason = self.attach_reason(current, recorded)
            attached = reason is None
            extra: dict[str, Any] = {}
            if attached:
                extra = await self.attach(session, current, frame, recorded)
            final = {
                **output,
                "frame_asset_id": frame.id,
                "attached": attached,
                "not_attached_reason": reason,
                "replaced_asset_id": replacing_asset_id if attached else None,
                **extra,
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
            "job %d: %s made: scene=%d raw=%d frame=%d %dx%d from %s attached=%s",
            job.id,
            self.label,
            scene.id,
            raw.id,
            frame.id,
            gen_width,
            gen_height,
            f"{returned['width']}x{returned['height']}" if isinstance(returned, dict) else "?",
            attached,
        )
        return True
