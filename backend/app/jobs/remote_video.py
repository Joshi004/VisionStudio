"""The remote steps every MiniMax H3 / LTX video job shares: waiting for the GPU server, the
download, pre-emption, an expired result, cleaning up and cancelling on the server.

This is the generic half of the narration pipeline's clip handler, which PHASE-046 retired
(the scene half stays readable at the git tag `narration-final`). A subclass
writes `start` (build or read the request, upload the files, submit, and save the server's job
id) and `_check_and_store` (check the downloaded clip and store it). Everything between is here:

- `poll`: ask the server about the job once per tick.
- `finish`: download the clip to a temporary file and hand it to `_check_and_store`.

Failure handling follows ANALYSIS.md Section 5.8, row by row (see the notes in each method). A
dropped connection never fails the job.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from pathlib import Path
from typing import Any

from app.core import outbound
from app.core import settings as settings_service
from app.db.models import Job
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.gpu_job import (
    GPU_URL_KEY,
    after_gone_result,
    is_preemption,
    phase_for_poll_error,
)
from app.jobs.handlers import JobHandler
from app.providers import video_generator
from app.providers.gpu_server import GpuCallError
from app.services.storage import get_storage

_logger = logging.getLogger(__name__)


class RemoteVideoHandler(JobHandler):
    provider = "gpu"
    restart_rule = "resume"

    @abstractmethod
    async def _check_and_store(
        self, job: Job, base_url: str, result: outbound.DownloadResult, dest: Path
    ) -> None:
        """Checks the downloaded clip at `dest` and stores it. Fails the job (with
        `_fail_and_purge`) when the clip is not usable.
        """

    # --- poll ---------------------------------------------------------------------

    async def poll(self, job_id: int) -> bool:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            await session.commit()
        if job is None or job.status != "running" or not job.provider_job_id:
            return False

        try:
            remote = await video_generator.status(base_url, job.provider_job_id)
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
            # From here the clip is being fetched: it can no longer be cancelled.
            await self._record_poll(job_id, phases.DOWNLOADING_CLIP, output)
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

    # --- finish: download, check, store ---------------------------------------------

    async def finish(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            await session.commit()
        if job is None or job.status != "running" or not job.provider_job_id:
            return

        await self._phase(job_id, phases.DOWNLOADING_CLIP)
        storage = get_storage()
        # Downloaded to a temporary file, and moved into place only after ffprobe passes.
        dest = storage.new_temp_path("mp4")
        try:
            try:
                result = await video_generator.download(base_url, job.provider_job_id, dest)
            except GpuCallError as exc:
                await self._result_not_downloaded(job, base_url, exc)
                return
            await self._phase(job_id, phases.CHECKING_CLIP)
            await self._check_and_store(job, base_url, result, dest)
        finally:
            storage.discard(dest)

    async def _result_not_downloaded(self, job: Job, base_url: str, exc: GpuCallError) -> None:
        """The download did not give a clip.

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
                await store.fail_job(session, job.id, f"The clip could not be downloaded: {exc}")
            else:
                await store.record_poll(session, job.id, phase_for_poll_error(exc))

    async def _result_gone(self, job: Job, base_url: str) -> None:
        """HTTP 410 on the result: the clip expired, or the server has not released it yet.

        ANALYSIS.md Section 5.8 says to check the status again. The server can answer 410
        for a while after a job finished (seen on 2026-10-06: the status already said
        `succeeded` with `result_ready`, and the file downloaded fine a minute later). So
        while the status still says the result is ready, the download is tried again at the
        next tick, up to `MAX_RESULT_RETRIES` times. Only a result that is no longer ready
        (it expired), or one that stays 410, is submitted again unchanged.
        """
        recorded = job.output if isinstance(job.output, dict) else {}
        retries = _count(recorded.get("download_retries"))
        try:
            remote = await video_generator.status(base_url, job.provider_job_id or "")
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
                await store.record_poll(session, job.id, phases.RESULT_NOT_READY, output)
            elif action == "resubmit":
                await store.requeue(session, job.id, phases.EXPIRED, next_attempt=True)
            else:
                await store.fail_job(
                    session,
                    job.id,
                    "The clip expired on the server before it could be downloaded, "
                    f"after {phases.MAX_ATTEMPTS} attempts. Regenerate to try again.",
                )

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
                    f"Could not start the clip: {exc} It was not retried automatically.",
                )

    async def _fail_and_purge(self, job: Job, base_url: str, message: str) -> None:
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.fail_job(session, job.id, message)
            await store.merge_output(session, job.id, {"purge": purge})

    # --- the server's cleanup and cancel (best effort) -----------------------------------

    @staticmethod
    async def _purge(base_url: str, provider_job_id: str | None) -> dict[str, Any]:
        """Deletes the finished job and its uploads on the server. A failure is recorded
        and ignored (ANALYSIS.md Section 5.3).
        """
        if not provider_job_id:
            return {"skipped": "no server job"}
        try:
            return (await video_generator.cleanup(base_url, provider_job_id)).to_json()
        except GpuCallError as exc:
            _logger.warning("could not purge server job %s: %s", provider_job_id, exc)
            return {"error": str(exc)}

    @staticmethod
    async def _cancel_quietly(base_url: str, provider_job_id: str) -> None:
        try:
            await video_generator.cancel(base_url, provider_job_id)
        except GpuCallError as exc:
            _logger.warning("could not cancel server job %s: %s", provider_job_id, exc)

    # --- small helpers ---------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _record_poll(job_id: int, phase: str, output: dict[str, Any] | None = None) -> None:
        async with SessionLocal() as session:
            await store.record_poll(session, job_id, phase, output)

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)

    @staticmethod
    async def _is_running(job_id: int) -> bool:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            await session.commit()
        return job is not None and job.status == "running"


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0
