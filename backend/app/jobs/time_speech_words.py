"""The `time_speech_words` job: when is each script word of a speech spoken? (EXPLAINER-007)

The WAV of a speech unit goes to Parakeet on the GPU server, and the words that come back are
matched to the words of the unit's script (`services/word_timings.py`). It is a remote job built
like `check_take_dialogue` (it sends a recording to the same transcription server), so the three
steps follow `JobHandler`:

- `start`: upload the stored speech, submit the transcription, save the server's job id.
- `poll`: ask the server about the job once per tick.
- `finish`: download the transcript, match it to the script, store the result.

The result is one `speech_word_timing` row, written in the same transaction that finishes the
job. A speech whose heard words match the script too little gets **estimated** timing instead,
and the row says so. An empty transcript is a valid answer (nothing was heard): it gives
estimated timing, not a failed job. A job that fails leaves the speech **not timed**, and the
board's step queues it again.

The job is not in `store.REMOTE_CANCEL_TYPES`, for the reason `check_take_dialogue` is not: it
runs for seconds, and the cancel on the server goes to the GPU server URL, which may not be the
transcription URL.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Job, SpeechUnitAudio, SpeechWordTiming
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.gpu_job import SERVER_RETRY_DELAY_S, is_preemption, phase_for_poll_error
from app.jobs.handlers import JobHandler
from app.providers import gpu_server, transcriber
from app.providers.gpu_server import GpuCallError
from app.services import word_timings
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = word_timings.JOB_TYPE

TRANSCRIPTION_URL_KEY: Final = "transcription_url"
PARTITION_KEY: Final = "gpu_partition"
SPEECH_MIME: Final = "audio/wav"


class TimeSpeechWordsHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "gpu"
    restart_rule = "resume"
    # The key of the job's input that names what is timed (the Audio video lab times a test's
    # speech instead of a speech unit: `TimeLabSpeechWordsHandler`).
    target_key = word_timings.DEDUPE_KEY

    # --- start: upload and submit -----------------------------------------------

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            recorded = dict(job.input) if isinstance(job.input, dict) else {}
            audio_id = recorded.get(self.target_key)
            speech_path = await self._speech_path(session, audio_id)
            base_url = await settings_service.get_str(session, TRANSCRIPTION_URL_KEY)
            partition = await settings_service.get_str(session, PARTITION_KEY)
            await session.commit()

        if speech_path is None:
            await self._fail(job_id, "The speech this timing was queued for has no audio any more.")
            return
        try:
            path = get_storage().get_path(speech_path)
        except StorageError:
            await self._fail(job_id, "The speech file could not be found on disk.")
            return
        if not path.is_file():
            await self._fail(job_id, "The speech file could not be found on disk.")
            return

        filename = f"speech-{audio_id}.wav"
        retried_server_error = False
        retried_asset = False
        while True:
            try:
                await self._phase(job_id, phases.UPLOADING_SPEECH_FOR_TRANSCRIPT)
                remote_asset_id = await gpu_server.upload_file(
                    base_url, path, filename, SPEECH_MIME
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

        # The job's own key stays on the input: `finish` and the dedupe read it.
        submitted = {
            **recorded,
            "server_url": docker_mapped(base_url),
            "upload": {"filename": filename, "remote_asset_id": remote_asset_id},
            "endpoint": transcriber.TRANSCRIBE_PATH,
            "body": transcriber.build_body(remote_asset_id, partition),
        }
        async with SessionLocal() as session:
            await store.mark_submitted(session, job_id, provider_job_id, submitted)

    async def _speech_path(self, session: AsyncSession, target_id: object) -> str | None:
        """The stored path of the speech to time, or None when there is none any more."""
        audio = (
            await session.get(SpeechUnitAudio, target_id) if isinstance(target_id, int) else None
        )
        return audio.path if audio is not None else None

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
            await self._record_poll(job_id, phase_for_poll_error(exc))
            return False

        if remote.status == "queued":
            await self._record_poll(job_id, phases.QUEUED_ON_CLUSTER)
        elif remote.status == "running":
            await self._record_poll(job_id, phases.RUNNING_ON_CLUSTER)
        elif remote.status == "succeeded":
            # From here the transcript is being fetched: the job can no longer be cancelled.
            await self._record_poll(job_id, phases.DOWNLOADING_TRANSCRIPT)
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

    # --- finish: download, match, store -----------------------------------------

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

        await self._phase(job_id, phases.MATCHING_WORDS)
        if await self._match_and_store(job, body, spoken):
            # Best effort: a failure here is recorded and never fails the job.
            purge = await self._purge(base_url, job.provider_job_id)
            async with SessionLocal() as session:
                await store.merge_output(session, job.id, {"purge": purge})

    async def _result_not_downloaded(self, job: Job, exc: GpuCallError) -> None:
        """The download did not give a transcript. Only a result that cannot be used fails."""
        async with SessionLocal() as session:
            if exc.kind == "rejected" and exc.status_code == 409:
                return  # not finished after all: the next tick asks again
            if exc.kind == "rejected" and exc.status_code == 410:
                if job.attempt < phases.MAX_ATTEMPTS:
                    await store.requeue(session, job.id, phases.EXPIRED, next_attempt=True)
                else:
                    await store.fail_job(
                        session,
                        job.id,
                        "The transcript expired on the server before it could be downloaded, "
                        f"after {phases.MAX_ATTEMPTS} attempts. Time the words again.",
                    )
            elif exc.kind in ("bad_answer", "rejected"):
                await store.fail_job(session, job.id, f"The transcript could not be used: {exc}")
            else:
                await store.record_poll(session, job.id, phase_for_poll_error(exc))

    async def _match_and_store(
        self, job: Job, body: dict[str, Any], spoken: list[transcriber.SpokenWord]
    ) -> bool:
        """Matches the transcript to the script and saves the result with the finished job. True
        when the job finished.
        """
        recorded = job.input if isinstance(job.input, dict) else {}
        audio_id = recorded.get(word_timings.DEDUPE_KEY)

        async with SessionLocal() as session:
            audio = (
                await session.get(SpeechUnitAudio, audio_id) if isinstance(audio_id, int) else None
            )
            if audio is None:
                await store.fail_job(
                    session, job.id, "The speech this timing was made for is gone."
                )
                return False

            existing = (
                (
                    await session.execute(
                        select(SpeechWordTiming).where(
                            SpeechWordTiming.speech_unit_audio_id == audio.id
                        )
                    )
                )
                .scalars()
                .first()
            )
            output: dict[str, Any] = {
                "speech_unit_audio_id": audio.id,
                "processing_time": processing_time(body),
            }
            if existing is not None:
                # Timed by an earlier job in the meantime: its result stands.
                output["timing"] = {"kept": existing.id}
            else:
                threshold = await settings_service.get_int(
                    session, settings_service.WORD_TIMING_MATCH_THRESHOLD_KEY
                )
                # The length is measured when the speech is stored; the last heard word is the
                # fallback for a row that has none.
                duration_s = audio.duration_s
                if duration_s is None:
                    duration_s = max((word.end for word in spoken), default=0.0)
                alignment = word_timings.align(audio.text, spoken, duration_s, threshold)
                session.add(
                    SpeechWordTiming(
                        project_id=audio.project_id,
                        speech_unit_audio_id=audio.id,
                        source=alignment.source,
                        match_percent=alignment.match_percent,
                        threshold=threshold,
                        words=alignment.words,
                        heard_text=alignment.heard_text,
                        job_id=job.id,
                    )
                )
                output["timing"] = {
                    "source": alignment.source,
                    "match_percent": alignment.match_percent,
                    "threshold": threshold,
                    "words": len(alignment.words),
                }
                _logger.info(
                    "job %d: speech %d timed: source=%s match=%s%% (needed %s%%)",
                    job.id,
                    audio.id,
                    alignment.source,
                    alignment.match_percent,
                    threshold,
                )
            # The result and the finished job are saved together or not at all.
            if not await store.finish_job(session, job.id, output):
                await session.rollback()
                _logger.warning("job %d: words matched but the job is not running", job.id)
                return False
            await session.commit()
        return True

    @staticmethod
    async def _purge(base_url: str, provider_job_id: str | None) -> dict[str, Any]:
        if not provider_job_id:
            return {"skipped": "no server job"}
        try:
            return (await gpu_server.purge_job(base_url, provider_job_id)).to_json()
        except GpuCallError as exc:
            _logger.warning("could not purge server job %s: %s", provider_job_id, exc)
            return {"error": str(exc)}

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


def processing_time(body: dict[str, Any]) -> float | None:
    value = body.get("processing_time")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
