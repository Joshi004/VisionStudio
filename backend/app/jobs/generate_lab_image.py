"""The `lab_image` job: one image from the Image lab, made by Qwen-Image-2.1 on the GPU server
(Phase 22), or by its edit endpoint (Phase 25: the Character lab's other angles, made from a
look's chosen front-view picture; the Image lab page itself still only tries text to image).

The lab belongs to no project, so the job has none (`job.project_id` is NULL). Its request was
built and checked when the run was created (`services/image_lab.create_qwen_run` or
`create_qwen_edit_run`) and is stored in `job.input`, so `start` only submits it (uploading the
edit's references first), and every later attempt (after a pre-emption, an expired result or a
server that could not be reached) sends the very same request and uploads the same references
again, because the server deletes the inputs of a job when it ends. The steps every Qwen image
job shares are `RemoteImageHandler`'s (`jobs/remote_image.py`).

`store_image` keeps the PNG exactly as it came, under `media/lab/`, and in one transaction adds
it as a lab image, marks the `lab_run` row `succeeded` and finishes the job. A job that fails or
is cancelled leaves its run `running`: the page reads the job's status as well.

A picture made for the Character lab (Phase 25) best-effort nudges what it belongs to along
once it is stored: a look's angle reference (`character_looks.on_angle_image_stored`) or a
take's own picture (`character_takes.on_image_stored`). A plain Image lab run is neither and
both are no-ops for it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from app.core import outbound
from app.core import settings as settings_service
from app.db.models import Asset, Job, LabImage, LabRun
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.jobs import dispatcher, phases, store
from app.jobs.gpu_job import GPU_URL_KEY
from app.jobs.remote_image import RemoteImageHandler
from app.providers import image_generator
from app.services import character_looks, character_takes, frame_images, image_lab
from app.services.frame_images import FrameRejected
from app.services.storage import StorageError, TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = image_lab.RUN_JOB


class GenerateLabImageHandler(RemoteImageHandler):
    job_type = JOB_TYPE

    # --- start: submit the stored request -------------------------------------------------

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            await session.commit()

        recorded = job.input if isinstance(job.input, dict) else {}
        request = recorded.get("request")
        if not isinstance(request, dict):
            await self._fail(job_id, "The request of this run was not saved, so it was not sent.")
            return

        if recorded.get("endpoint") == image_generator.EDIT_PATH:

            async def build_body() -> tuple[dict[str, Any], dict[str, Any]]:
                return await self._upload_references(base_url, recorded)

            await self.submit(
                job_id,
                base_url,
                request,
                recorded,
                endpoint=image_generator.EDIT_PATH,
                build_body=build_body,
            )
            return
        await self.submit(job_id, base_url, request, recorded)

    @staticmethod
    async def _reference_path(source: str, ref_id: int) -> str | None:
        """The stored path of a `{source, id}` reference, or None when it is gone."""
        async with SessionLocal() as session:
            if source == "lab":
                image = await session.get(LabImage, ref_id)
                path = image.path if image is not None else None
            else:
                asset = await session.get(Asset, ref_id)
                path = asset.path if asset is not None and asset.kind == "frame" else None
            await session.commit()
        return path

    @classmethod
    async def _upload_references(
        cls, base_url: str, recorded: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Uploads every reference named on the job's input, in order, and makes the edit body.
        Runs at every start, because the server deletes the inputs of a job when it ends.
        Raises `GpuCallError` and `StorageError`.
        """
        references = recorded.get("references")
        references = references if isinstance(references, list) else []
        request = recorded.get("request")
        request = request if isinstance(request, dict) else {}
        storage = get_storage()
        remote_ids: list[str] = []
        uploads: list[dict[str, Any]] = []
        for number, item in enumerate(references, start=1):
            source = item.get("source") if isinstance(item, dict) else None
            ref_id = item.get("id") if isinstance(item, dict) else None
            if source not in ("lab", "asset") or not isinstance(ref_id, int):
                raise StorageError(f"Reference {number} is not recorded correctly.")
            relative_path = await cls._reference_path(source, ref_id)
            if relative_path is None:
                raise StorageError(f"Reference {number} is gone.")
            # The server reads the file's type from the filename's extension, not from the
            # Content-Type header, so keeping the stored file's own extension is what matters.
            suffix = Path(relative_path).suffix or ".png"
            filename = f"reference-{source}-{ref_id}{suffix}"
            remote_id = await image_generator.upload_reference(
                base_url, storage.get_path(relative_path), filename
            )
            remote_ids.append(remote_id)
            uploads.append(
                {"source": source, "id": ref_id, "filename": filename, "remote_asset_id": remote_id}
            )
        body = image_generator.with_references(request, remote_ids)
        return body, {"uploads": uploads, "body": body}

    # --- store the image -----------------------------------------------------------------

    async def store_image(
        self, job: Job, base_url: str, result: outbound.DownloadResult, dest: Path
    ) -> None:
        recorded = job.input if isinstance(job.input, dict) else {}
        run_id = recorded.get("run_id")
        storage = get_storage()
        try:
            info = await frame_images.run_pillow(frame_images.inspect_image, dest)
        except FrameRejected as exc:
            await self._fail_and_purge(job, base_url, f"The image could not be used: {exc.message}")
            return

        await self._phase(job.id, phases.SAVING_IMAGE)
        try:
            temp = TempFile(path=dest, size_bytes=result.size_bytes, sha256=result.sha256)
            stored = await storage.save_lab(temp, info.ext)
        except StorageError as exc:
            await self._fail_and_purge(job, base_url, f"The image could not be stored: {exc}")
            return

        output: dict[str, Any] = dict(job.output) if isinstance(job.output, dict) else {}
        output["run_id"] = run_id
        output["returned_size"] = {"width": info.width, "height": info.height}
        # From the click to now: it includes the time the job waited for the GPU.
        seconds = round((utcnow() - job.created_at).total_seconds(), 1)

        # The image, the run and the finished job are saved together or not at all.
        async with SessionLocal() as session:
            run = await session.get(LabRun, run_id) if isinstance(run_id, int) else None
            if run is not None:
                run.status = "succeeded"
                run.error = None
                run.seconds = seconds
                run.response = {
                    "remote": output.get("remote"),
                    "expected_size": recorded.get("expected_size"),
                    "returned_size": output["returned_size"],
                }
                session.add(
                    LabImage(
                        origin="result",
                        run_id=run.id,
                        output_index=0,
                        path=stored.relative_path,
                        mime=info.mime,
                        width=info.width,
                        height=info.height,
                        size_bytes=result.size_bytes,
                        sha256=result.sha256,
                    )
                )
            else:
                _logger.warning("job %d: image stored but its run %s is gone", job.id, run_id)
            if not await store.finish_job(session, job.id, output):
                await session.rollback()
                # Cancelled in the meantime. Stored files are never deleted.
                _logger.warning(
                    "job %d: image stored but the job is no longer running: %s",
                    job.id,
                    stored.relative_path,
                )
                return
            await session.commit()

        _logger.info(
            "job %d: lab image stored: run=%s %dx%d %.1f s",
            job.id,
            run_id,
            info.width,
            info.height,
            seconds,
        )
        if isinstance(run_id, int):
            await self._continue_character_lab(job.id, run_id)
        # Best effort: a failure here is recorded and never fails the run.
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.merge_output(session, job.id, {"purge": purge})

    @staticmethod
    async def _continue_character_lab(job_id: int, run_id: int) -> None:
        """Nudges along whatever this picture belongs to in the Character lab, if anything.
        Best effort: a failure never fails the picture (it is stored), and the thing it
        belongs to can be continued by hand.
        """
        try:
            await character_looks.on_angle_image_stored(run_id)
            started = await character_takes.on_image_stored(run_id)
        except Exception:
            _logger.exception("job %d: the character lab could not continue", job_id)
            return
        if started:
            dispatcher.nudge()
