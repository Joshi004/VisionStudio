"""The `transcribe` job: the voiceover goes to Parakeet on the GPU server, and the words
that come back are matched to the script (ANALYSIS.md Section 5.1 and 6.4).

It is a remote job, so the three steps follow `JobHandler`:

- `start`: upload the voiceover, submit the job, save the server's job id.
- `poll`: ask the server about the job once per tick.
- `finish`: download the transcript, match it to the script, store it.

Failure handling follows ANALYSIS.md Section 5.8. A dropped connection never fails the
job. The job fails only when the server says it failed (other than pre-emption), refuses
the request, or returns something that cannot be used.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Asset, Job, Project, Transcript
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.jobs import phases, store
from app.jobs.handlers import JobHandler
from app.providers import gpu_server, transcriber
from app.providers.gpu_server import GpuCallError
from app.services import transcript_matching
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "transcribe"
# At most this many transcriptions run on the server at once (a constant, not a setting).
CONCURRENCY_LIMIT: Final = 2
SERVER_RETRY_DELAY_S: Final = 5.0

TRANSCRIPTION_URL_KEY: Final = "transcription_url"
PARTITION_KEY: Final = "gpu_partition"

# ANALYSIS.md Section 5.8: a job killed by a higher-priority one is resubmitted unchanged.
_PREEMPTION: Final = re.compile(r"pre-?empt|sigterm|exit code:? ?(?:137|143)", re.IGNORECASE)


def is_preemption(error: str) -> bool:
    return _PREEMPTION.search(error) is not None


class TranscribeHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "gpu"
    restart_rule = "resume"

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return CONCURRENCY_LIMIT

    # --- start: upload and submit -----------------------------------------------

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            voiceover_id = (
                job.input.get("voiceover_asset_id") if isinstance(job.input, dict) else None
            )
            voiceover = (
                await session.get(Asset, voiceover_id) if isinstance(voiceover_id, int) else None
            )
            base_url = await settings_service.get_str(session, TRANSCRIPTION_URL_KEY)
            partition = await settings_service.get_str(session, PARTITION_KEY)
            await session.commit()

        if voiceover is None:
            await self._fail(job_id, "The voiceover for this job no longer exists.")
            return
        extension = Path(voiceover.path).suffix.lstrip(".").lower()
        if extension not in transcriber.PARAKEET_EXTENSIONS:
            await self._fail(
                job_id, f"The transcription server does not accept .{extension or '?'} files."
            )
            return
        try:
            path = get_storage().get_path(voiceover.path)
        except StorageError:
            await self._fail(job_id, "The voiceover file could not be found on disk.")
            return

        filename = f"voiceover-{voiceover.id}.{extension}"
        retried_server_error = False
        retried_asset = False
        while True:
            try:
                await self._phase(job_id, phases.UPLOADING_VOICEOVER)
                remote_asset_id = await gpu_server.upload_file(
                    base_url, path, filename, voiceover.mime
                )
                await self._phase(job_id, phases.SUBMITTING)
                provider_job_id = await transcriber.submit(base_url, remote_asset_id, partition)
                break
            except GpuCallError as exc:
                if exc.kind == "server_error" and not retried_server_error:
                    retried_server_error = True
                    await asyncio.sleep(SERVER_RETRY_DELAY_S)
                    continue
                unknown_asset = (
                    exc.status_code == 400 and "invalid asset reference" in exc.message.lower()
                )
                if exc.kind == "rejected" and unknown_asset and not retried_asset:
                    retried_asset = True  # the server lost the upload: send it again
                    continue
                await self._give_up_starting(job_id, exc)
                return

        submitted = {
            "voiceover_asset_id": voiceover.id,
            "server_url": docker_mapped(base_url),
            "upload": {
                "filename": filename,
                "size_bytes": voiceover.size_bytes,
                "remote_asset_id": remote_asset_id,
            },
            "endpoint": transcriber.TRANSCRIBE_PATH,
            "body": transcriber.build_body(remote_asset_id, partition),
        }
        async with SessionLocal() as session:
            await store.mark_submitted(session, job_id, provider_job_id, submitted)

    async def _give_up_starting(self, job_id: int, exc: GpuCallError) -> None:
        async with SessionLocal() as session:
            if exc.kind == "unreachable":
                await store.requeue(session, job_id, phases.WAITING_SERVER_UNREACHABLE)
            elif exc.kind == "busy":
                await store.requeue(session, job_id, phases.WAITING_SERVER_BUSY)
            else:
                await store.fail_job(session, job_id, f"Could not start the transcription: {exc}")

    # --- poll --------------------------------------------------------------------

    async def poll(self, job_id: int) -> bool:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            base_url = await settings_service.get_str(session, TRANSCRIPTION_URL_KEY)
            await session.commit()
        if job is None or job.status != "running" or not job.provider_job_id:
            return False

        try:
            remote = await gpu_server.job_status(base_url, job.provider_job_id)
        except GpuCallError as exc:
            await self._record_poll(job_id, _phase_for_poll_error(exc))
            return False

        if remote.status == "queued":
            await self._record_poll(job_id, phases.QUEUED_ON_CLUSTER)
        elif remote.status == "running":
            await self._record_poll(job_id, phases.RUNNING_ON_CLUSTER)
        elif remote.status == "succeeded":
            return True
        else:
            await self._server_reported_failure(job, remote.error)
        return False

    async def _server_reported_failure(self, job: Job, error: str | None) -> None:
        message = error or "The server reported the job as failed."
        async with SessionLocal() as session:
            if is_preemption(message) and job.attempt < phases.MAX_ATTEMPTS:
                await store.requeue(
                    session, job.id, phases.preempted(job.attempt + 1), next_attempt=True
                )
            else:
                await store.fail_job(
                    session, job.id, f"The GPU server reported an error: {message}"
                )

    # --- finish: download, match, store ---------------------------------------------

    async def finish(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            base_url = await settings_service.get_str(session, TRANSCRIPTION_URL_KEY)
            await session.commit()
        if job is None or job.status != "running" or not job.provider_job_id:
            return

        await self._phase(job_id, phases.DOWNLOADING_TRANSCRIPT)
        try:
            body = await gpu_server.job_result_json(base_url, job.provider_job_id)
        except GpuCallError as exc:
            await self._result_not_downloaded(job, exc)
            return

        try:
            spoken = transcriber.parse_result(body)
        except ValueError as exc:
            await self._fail(job_id, f"The transcript could not be used: {exc}")
            return
        if not spoken:
            await self._fail(job_id, "No speech was found in the voiceover.")
            return

        await self._phase(job_id, phases.MATCHING)
        await self._match_and_store(job, body, spoken)

    async def _result_not_downloaded(self, job: Job, exc: GpuCallError) -> None:
        """The download did not give a transcript. Only a result that cannot be used fails."""
        async with SessionLocal() as session:
            if exc.kind == "rejected" and exc.status_code == 409:
                return  # not finished after all: the next tick asks again
            if exc.kind == "rejected" and exc.status_code == 410:
                await store.requeue(session, job.id, phases.EXPIRED, next_attempt=True)
            elif exc.kind == "bad_answer":
                await store.fail_job(session, job.id, f"The transcript could not be used: {exc}")
            else:
                await store.record_poll(session, job.id, _phase_for_poll_error(exc))

    async def _match_and_store(
        self, job: Job, body: dict[str, Any], spoken: list[transcriber.SpokenWord]
    ) -> None:
        async with SessionLocal() as session:
            project = await session.get(Project, job.project_id)
            voiceover_id = (
                job.input.get("voiceover_asset_id") if isinstance(job.input, dict) else None
            )
            voiceover = (
                await session.get(Asset, voiceover_id) if isinstance(voiceover_id, int) else None
            )
            await session.commit()

        if project is None or voiceover is None:
            await self._fail(job.id, "The project or its voiceover no longer exists.")
            return
        script = project.script_text
        if script is None or not script.strip():
            await self._fail(
                job.id,
                "The script is empty, so the transcript cannot be matched to it. "
                "Paste the script and transcribe again.",
            )
            return

        audio_end_s = voiceover.duration_s if voiceover.duration_s else spoken[-1].end
        result = await asyncio.to_thread(
            transcript_matching.match_transcript, script, spoken, audio_end_s
        )
        warnings = transcript_matching.mismatch_warnings(result.counts)
        counts = result.counts

        async with SessionLocal() as session:
            transcript = Transcript(
                project_id=project.id,
                provider="parakeet",
                language=project.language,
                words=body,
                script_words=result.script_words,
                voiceover_asset_id=voiceover.id,
                script_sha256=transcript_matching.script_sha256(script),
            )
            session.add(transcript)
            await session.flush()
            output = {
                "transcript_id": transcript.id,
                "processing_time": _processing_time(body),
                "script_words": counts.script_words,
                "matched": counts.matched,
                "interpolated": counts.interpolated,
                "spoken_words": counts.spoken_words,
                "extra_spoken": counts.extra_spoken,
                "warnings": warnings,
            }
            # The transcript and the finished job are saved together or not at all.
            if not await store.finish_job(session, job.id, output):
                await session.rollback()
                return
            await session.commit()

        elapsed = (utcnow() - job.created_at).total_seconds()
        _logger.info(
            "job %d: transcript stored: script_words=%d matched=%d interpolated=%d "
            "spoken=%d extra=%d end_to_end=%.0fs",
            job.id,
            counts.script_words,
            counts.matched,
            counts.interpolated,
            counts.spoken_words,
            counts.extra_spoken,
            elapsed,
        )

    # --- small helpers ---------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _record_poll(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.record_poll(session, job_id, phase)

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)


def _phase_for_poll_error(exc: GpuCallError) -> str:
    """What to show while the server cannot be asked. None of these fails the job."""
    if exc.kind == "unreachable":
        return phases.SERVER_UNREACHABLE_CHECKING
    if exc.kind == "not_found":
        return phases.NOT_FOUND
    if exc.status_code is not None:
        return f"waiting: the server answered HTTP {exc.status_code}, checking again"
    return "waiting: the server's answer was not usable, checking again"


def _processing_time(body: dict[str, Any]) -> float | None:
    value = body.get("processing_time")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
