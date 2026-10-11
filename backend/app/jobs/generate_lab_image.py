"""The `lab_image` job: one image from the Image lab, made by Qwen-Image-2.1 on the GPU server
(Phase 22).

The lab belongs to no project, so the job has none (`job.project_id` is NULL). Its request was
built and checked when the run was created (`services/image_lab.create_qwen_run`) and is stored in
`job.input`, so `start` only submits it, and every later attempt (after a pre-emption, an expired
result or a server that could not be reached) sends the very same one. The steps every Qwen image
job shares are `RemoteImageHandler`'s (`jobs/remote_image.py`).

`store_image` keeps the PNG exactly as it came, under `media/lab/`, and in one transaction adds
it as a lab image, marks the `lab_run` row `succeeded` and finishes the job. A job that fails or
is cancelled leaves its run `running`: the page reads the job's status as well.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbound
from app.core import settings as settings_service
from app.db.models import Job, LabImage, LabRun
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.jobs import phases, store
from app.jobs.generate_clip import GPU_URL_KEY
from app.jobs.remote_image import RemoteImageHandler
from app.services import frame_images, image_lab
from app.services.frame_images import FrameRejected
from app.services.storage import StorageError, TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = image_lab.RUN_JOB
# Each run loads about 31 GB of model weights on the GPU server, so only a couple at a time.
CONCURRENCY_LIMIT: Final = 2


class GenerateLabImageHandler(RemoteImageHandler):
    job_type = JOB_TYPE

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return CONCURRENCY_LIMIT

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
        await self.submit(job_id, base_url, request, recorded)

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
        # Best effort: a failure here is recorded and never fails the run.
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.merge_output(session, job.id, {"purge": purge})
