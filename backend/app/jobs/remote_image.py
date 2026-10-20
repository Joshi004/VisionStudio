"""The remote steps every Qwen-Image-2.1 job shares (today an Image lab run, `lab_image`). It
submits one request to the GPU server, waits for it, downloads one PNG and stores it. What
differs between jobs is only how the request is made and what the PNG becomes, so a subclass
writes `start` and `store_image`, and everything between is here:

- `submit`: send the request and save the server's job id at once. An edit (which refers to
  reference images) passes `build_body`, which uploads them and makes the body.
- `poll`: ask the server about the job once per tick.
- `finish`: download the PNG into a temporary file and hand it to `store_image`.

Failure handling follows ANALYSIS.md Section 5.8, as for a clip. A dropped connection never fails
the job. A pre-emption is submitted again unchanged, up to 3 attempts. A result that answers 410
is waited for while the server still says it is ready, then submitted again (that costs only GPU
time). Anything else the server refuses stops the job, with its message.

**The server may keep a result for one download only** (its guide for version 0.9.0 says so), so
`store_image` must store the downloaded file before it does anything else with it.
"""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.core import outbound
from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Job
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.gpu_job import (
    GPU_URL_KEY,
    SERVER_RETRY_DELAY_S,
    after_gone_result,
    is_preemption,
    phase_for_poll_error,
)
from app.jobs.handlers import JobHandler
from app.providers import image_generator
from app.providers.gpu_server import GpuCallError
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

# Uploads what an edit refers to, and returns the body to send with a record of what was
# uploaded. Raises `GpuCallError` (an upload failed) or `StorageError` (a file is missing).
BuildBody = Callable[[], Awaitable[tuple[dict[str, Any], dict[str, Any]]]]


class RemoteImageHandler(JobHandler):
    provider = "gpu"
    restart_rule = "resume"

    @abstractmethod
    async def store_image(
        self, job: Job, base_url: str, result: outbound.DownloadResult, dest: Path
    ) -> None:
        """The PNG is downloaded to `dest` (a temporary file, removed afterwards). Stores it
        exactly as it came, first of all, then finishes the job (or fails it).
        """

    # --- submit ------------------------------------------------------------------------

    async def submit(
        self,
        job_id: int,
        base_url: str,
        request: dict[str, Any],
        recorded: dict[str, Any],
        *,
        endpoint: str = image_generator.GENERATE_PATH,
        build_body: BuildBody | None = None,
    ) -> None:
        """Submits the request to `endpoint`. The server's job id is saved the moment the submit
        answers, with nothing that can fail in between (ANALYSIS.md Section 3.3). `recorded` is
        the job's input, which the submission extends with the server's address.

        An edit passes `build_body` instead of a finished request: it uploads the reference
        images and returns the body to send, with a record of what was uploaded (which joins
        the job's input as `uploads`). It runs at every start, because the server deletes the
        inputs of a job when it ends, so a job that is submitted again needs them again.

        - 502 at submit: retried once after a pause.
        - No answer, or 429: the job goes back to the queue and waits.
        - 400 for an unknown asset id (an edit only): the references are uploaded again, once.
        - 422 and any other refusal: the job fails with the server's message and is not
          retried, because the request we built is what is wrong.
        """
        retried_server_error = False
        retried_asset = False
        body = request
        uploads: dict[str, Any] = {}
        while True:
            try:
                if build_body is not None:
                    await self._phase(job_id, phases.UPLOADING_REFERENCE)
                    body, uploads = await build_body()
                    if not await self._is_running(job_id):
                        return  # cancelled while uploading: nothing was submitted
                await self._phase(job_id, phases.SUBMITTING)
                provider_job_id = await image_generator.submit(base_url, body, endpoint)
                break
            except StorageError:
                await self._fail(job_id, "A reference image's file could not be found on disk.")
                return
            except GpuCallError as exc:
                if exc.kind == "server_error" and not retried_server_error:
                    retried_server_error = True
                    await asyncio.sleep(SERVER_RETRY_DELAY_S)
                    continue
                unknown_asset = (
                    exc.status_code == 400 and "invalid asset reference" in exc.message.lower()
                )
                if build_body is not None and exc.kind == "rejected" and unknown_asset:
                    if not retried_asset:
                        retried_asset = True  # the server lost an upload: send them again
                        continue
                await self._give_up_starting(job_id, exc)
                return

        submitted = {**recorded, **uploads, "server_url": docker_mapped(base_url)}
        async with SessionLocal() as session:
            saved = await store.mark_submitted(session, job_id, provider_job_id, submitted)
        if not saved:
            # Cancelled between the submit and here: the server job must be stopped too.
            await self._cancel_quietly(base_url, provider_job_id)

    async def _give_up_starting(self, job_id: int, exc: GpuCallError) -> None:
        async with SessionLocal() as session:
            if exc.kind == "unreachable":
                await store.requeue(session, job_id, phases.WAITING_SERVER_UNREACHABLE)
            elif exc.kind == "busy":
                await store.requeue(session, job_id, phases.WAITING_SERVER_BUSY)
            else:
                await store.fail_job(
                    session,
                    job_id,
                    f"Could not start the image: {exc} It was not retried automatically.",
                )

    # --- poll ---------------------------------------------------------------------

    async def poll(self, job_id: int) -> bool:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            await session.commit()
        if job is None or job.status != "running" or not job.provider_job_id:
            return False

        try:
            remote = await image_generator.status(base_url, job.provider_job_id)
        except GpuCallError as exc:
            # Never fails the job: no answer means check again. A 404 shows "not found on
            # this server" (and offers Resubmit), it does not fail.
            await self._record_poll(job_id, phase_for_poll_error(exc))
            return False

        # Keep what else the output holds (the count of download retries).
        previous = job.output if isinstance(job.output, dict) else {}
        output = {**previous, "remote": remote.to_json()}
        if remote.status == "queued":
            await self._record_poll(job_id, phases.QUEUED_ON_CLUSTER, output)
        elif remote.status == "running":
            await self._record_poll(job_id, phases.RUNNING_ON_CLUSTER, output)
        elif remote.status == "succeeded":
            # From here the image is being fetched: it can no longer be cancelled.
            await self._record_poll(job_id, phases.DOWNLOADING_IMAGE, output)
            return True
        else:
            await self._server_reported_failure(job, base_url, remote.error)
        return False

    async def _server_reported_failure(self, job: Job, base_url: str, error: str | None) -> None:
        """The server says the job failed.

        A pre-emption (or SIGTERM, exit 137 or 143) is resubmitted unchanged, up to 3 attempts
        in all. Any other failure stops here, with the server's text shown: the guide says not
        to retry blindly in a loop. Either way the failed job is purged on the server first.
        """
        message = error or "The server reported the job as failed."
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            if is_preemption(message) and job.attempt < phases.MAX_ATTEMPTS:
                await store.requeue(
                    session, job.id, phases.preempted(job.attempt + 1), next_attempt=True
                )
                return
            await store.fail_job(session, job.id, f"The GPU server reported an error: {message}")
            await store.merge_output(session, job.id, {"purge": purge})

    # --- finish: download ------------------------------------------------------------------

    async def finish(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            await session.commit()
        if job is None or job.status != "running" or not job.provider_job_id:
            return

        await self._phase(job_id, phases.DOWNLOADING_IMAGE)
        storage = get_storage()
        # Downloaded to a temporary file, and moved into place only after it was read as an image.
        dest = storage.new_temp_path("png")
        try:
            try:
                result = await image_generator.download(base_url, job.provider_job_id, dest)
            except GpuCallError as exc:
                await self._result_not_downloaded(job, base_url, exc)
                return
            await self.store_image(job, base_url, result, dest)
        finally:
            storage.discard(dest)

    async def _result_not_downloaded(self, job: Job, base_url: str, exc: GpuCallError) -> None:
        """The download did not give an image.

        - 409: the job is not finished after all. The next tick asks again.
        - 410: expired, or not released yet (see `_result_gone`).
        - 404 and no answer: shown as such, never a failure.
        - Anything unusable fails the job.
        """
        if exc.kind == "rejected" and exc.status_code == 409:
            return
        if exc.kind == "rejected" and exc.status_code == 410:
            await self._result_gone(job, base_url)
            return
        async with SessionLocal() as session:
            if exc.kind in ("bad_answer", "rejected"):
                await store.fail_job(session, job.id, f"The image could not be downloaded: {exc}")
            else:
                await store.record_poll(session, job.id, phase_for_poll_error(exc))

    async def _result_gone(self, job: Job, base_url: str) -> None:
        """HTTP 410 on the result: the image expired, or the server has not released it yet.

        The server can answer 410 for a while after a job finished, so while its status still
        says the result is ready, the download is tried again at the next tick, up to
        `MAX_RESULT_RETRIES` times. Only a result that is no longer ready (it expired, or it
        was already downloaded), or one that stays 410, is submitted again unchanged. That costs
        only GPU time, so it is the right answer to a lost result.
        """
        recorded = job.output if isinstance(job.output, dict) else {}
        retries = _count(recorded.get("download_retries"))
        try:
            remote = await image_generator.status(base_url, job.provider_job_id or "")
        except GpuCallError as exc:
            async with SessionLocal() as session:
                await store.record_poll(session, job.id, phase_for_poll_error(exc))
            return

        action = after_gone_result(
            remote.status, remote.result_ready, retries=retries, attempt=job.attempt
        )
        async with SessionLocal() as session:
            if action == "try_again":
                output = {**recorded, "remote": remote.to_json(), "download_retries": retries + 1}
                await store.record_poll(session, job.id, phases.IMAGE_NOT_READY, output)
            elif action == "resubmit":
                await store.requeue(session, job.id, phases.EXPIRED, next_attempt=True)
            else:
                await store.fail_job(
                    session,
                    job.id,
                    "The image expired on the server before it could be downloaded, "
                    f"after {phases.MAX_ATTEMPTS} attempts. Generate again to try once more.",
                )

    # --- The server's cleanup and cancel (best effort) ---------------------------------------

    async def _fail_and_purge(self, job: Job, base_url: str, message: str) -> None:
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.fail_job(session, job.id, message)
            await store.merge_output(session, job.id, {"purge": purge})

    @staticmethod
    async def _purge(base_url: str, provider_job_id: str | None) -> dict[str, Any]:
        """Deletes the finished job on the server. A failure is recorded and ignored."""
        if not provider_job_id:
            return {"skipped": "no server job"}
        try:
            return (await image_generator.cleanup(base_url, provider_job_id)).to_json()
        except GpuCallError as exc:
            _logger.warning("could not purge server job %s: %s", provider_job_id, exc)
            return {"error": str(exc)}

    @staticmethod
    async def _cancel_quietly(base_url: str, provider_job_id: str) -> None:
        try:
            await image_generator.cancel(base_url, provider_job_id)
        except GpuCallError as exc:
            _logger.warning("could not cancel server job %s: %s", provider_job_id, exc)

    # --- Small helpers ----------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _is_running(job_id: int) -> bool:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            await session.commit()
        return job is not None and job.status == "running"

    @staticmethod
    async def _record_poll(job_id: int, phase: str, output: dict[str, Any] | None = None) -> None:
        async with SessionLocal() as session:
            await store.record_poll(session, job_id, phase, output)

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0
