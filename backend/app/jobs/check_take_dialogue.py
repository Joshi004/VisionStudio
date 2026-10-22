"""The `check_take_dialogue` job: does a take's clip really contain its dialogue? (PHASE-031)

The clip of a take that carries dialogue goes to Parakeet on the GPU server, and the words that
come back are compared with the shot's dialogue lines (`services/dialogue_check.py`). It is a
remote job rebuilt from the narration `transcribe` job (readable at the git tag
`narration-final`), so the three steps follow `JobHandler`:

- `start`: upload the stored clip, submit the transcription, save the server's job id.
- `poll`: ask the server about the job once per tick.
- `finish`: download the transcript, compare it with the lines, store the result.

The result is written on `shot_take.dialogue_check` in the same transaction that finishes the job.
A take that passed is selected then (`selected_at`), so a dialogue take becomes its shot's
selected take only after both checks pass. A take that failed is not selected, and when the rules
allow it the shot is generated again with another seed (`shot_takes.queue_retry`, the same retry
as a clip that failed its technical check). An empty transcript is a valid answer (nothing was
said): it fails the check, not the job.

Failure handling follows ANALYSIS.md Section 5.8. A dropped connection never fails the job. The
job fails only when the server says it failed (other than pre-emption), refuses the request, or
returns something that cannot be used. A job that fails leaves the take **not checked**, and
**Check takes** queues it again.

The job is not in `store.REMOTE_CANCEL_TYPES`: it runs for seconds, and the cancel on the server
is sent to the GPU server URL, which may not be the transcription URL.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Job, ShotTake
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.jobs import dispatcher, phases, store
from app.jobs.generate_shot import start_dependents
from app.jobs.gpu_job import SERVER_RETRY_DELAY_S, is_preemption, phase_for_poll_error
from app.jobs.handlers import JobHandler
from app.providers import gpu_server, transcriber
from app.providers.gpu_server import GpuCallError
from app.services import dialogue_check, shot_takes, take_validation
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = shot_takes.DIALOGUE_JOB_TYPE

TRANSCRIPTION_URL_KEY: Final = "transcription_url"
PARTITION_KEY: Final = "gpu_partition"
CLIP_MIME: Final = "video/mp4"


class CheckTakeDialogueHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "gpu"
    restart_rule = "resume"

    # --- start: upload and submit -----------------------------------------------

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            recorded = dict(job.input) if isinstance(job.input, dict) else {}
            take_id = recorded.get(shot_takes.DIALOGUE_DEDUPE_KEY)
            take = await session.get(ShotTake, take_id) if isinstance(take_id, int) else None
            base_url = await settings_service.get_str(session, TRANSCRIPTION_URL_KEY)
            partition = await settings_service.get_str(session, PARTITION_KEY)
            clip_path = take.path if take is not None else None
            await session.commit()

        if take is None or clip_path is None:
            await self._fail(job_id, "The take this check was queued for has no clip any more.")
            return
        try:
            path = get_storage().get_path(clip_path)
        except StorageError:
            await self._fail(job_id, "The clip file could not be found on disk.")
            return
        if not path.is_file():
            await self._fail(job_id, "The clip file could not be found on disk.")
            return

        filename = f"take-{take_id}.mp4"
        retried_server_error = False
        retried_asset = False
        while True:
            try:
                await self._phase(job_id, phases.UPLOADING_CLIP_FOR_TRANSCRIPT)
                remote_asset_id = await gpu_server.upload_file(base_url, path, filename, CLIP_MIME)
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

        # The job's own keys (`take_id`) stay on the input: `finish` and the dedupe read them.
        submitted = {
            **recorded,
            "server_url": docker_mapped(base_url),
            "upload": {
                "filename": filename,
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

    # --- finish: download, compare, store ---------------------------------------------

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

        await self._phase(job_id, phases.COMPARING_DIALOGUE)
        retry_take_id, selected_take_id = await self._compare_and_store(job, base_url, body, spoken)
        await self._retry(retry_take_id)
        # A take of **Generate all** that has just become selected starts the shot that
        # continues it (PHASE-032).
        await start_dependents(selected_take_id)

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
                        f"after {phases.MAX_ATTEMPTS} attempts. Press Check takes to try again.",
                    )
            elif exc.kind in ("bad_answer", "rejected"):
                await store.fail_job(session, job.id, f"The transcript could not be used: {exc}")
            else:
                await store.record_poll(session, job.id, phase_for_poll_error(exc))

    async def _compare_and_store(
        self,
        job: Job,
        base_url: str,
        body: dict[str, Any],
        spoken: list[transcriber.SpokenWord],
    ) -> tuple[int | None, int | None]:
        """Judges the transcript and saves the result with the finished job. Returns
        `(retry_take_id, selected_take_id)`: the take's id when it failed and a retry may be
        queued, and the take's id when this check is what made it the shot's selected take.
        """
        recorded = job.input if isinstance(job.input, dict) else {}
        take_id = recorded.get(shot_takes.DIALOGUE_DEDUPE_KEY)
        retry_take_id: int | None = None
        selected_take_id: int | None = None

        async with SessionLocal() as session:
            take = await session.get(ShotTake, take_id) if isinstance(take_id, int) else None
            if take is None:
                await store.fail_job(session, job.id, "The take this check was made for is gone.")
                return None, None
            lines = await shot_takes.dialogue_lines(session, take)
            threshold = await settings_service.get_int(
                session, settings_service.DIALOGUE_MATCH_THRESHOLD_KEY
            )
            result = dialogue_check.compare(lines, spoken, threshold)
            take.dialogue_check = result.to_json(
                lines, spoken, threshold=threshold, checked_at=utcnow()
            )
            output: dict[str, Any] = {
                "take_id": take.id,
                "take_number": take.take_number,
                "processing_time": _processing_time(body),
                "check": {
                    "passed": result.passed,
                    "similarity": result.similarity,
                    "threshold": threshold,
                    "problems": [problem.code for problem in result.problems],
                },
            }
            if result.passed:
                # Only a clip that passed its technical check is ever sent here, but the
                # selection rule is kept in one place and never trusts that. A take that
                # already has a `selected_at` (made before this phase, or chosen by the user)
                # keeps it: checking it again must not move the shot's selection.
                if (
                    take.selected_at is None
                    and take.path is not None
                    and take_validation.passed(take.validation)
                ):
                    take.selected_at = await shot_takes.selection_time(
                        session, take.project_id, take.scene_id, take.shot_id
                    )
                    selected_take_id = take.id
            else:
                retry_take_id = take.id
            # The result and the finished job are saved together or not at all.
            if not await store.finish_job(session, job.id, output):
                await session.rollback()
                _logger.warning("job %d: transcript compared but the job is not running", job.id)
                return None, None
            await session.commit()

        _logger.info(
            "job %d: dialogue of take %s checked: passed=%s similarity=%s%% (needed %s%%)",
            job.id,
            take_id,
            result.passed,
            result.similarity,
            threshold,
        )

        # Best effort: a failure here is recorded and never fails the check.
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.merge_output(session, job.id, {"purge": purge})
        return retry_take_id, selected_take_id

    @staticmethod
    async def _purge(base_url: str, provider_job_id: str | None) -> dict[str, Any]:
        if not provider_job_id:
            return {"skipped": "no server job"}
        try:
            return (await gpu_server.purge_job(base_url, provider_job_id)).to_json()
        except GpuCallError as exc:
            _logger.warning("could not purge server job %s: %s", provider_job_id, exc)
            return {"error": str(exc)}

    @staticmethod
    async def _retry(take_id: int | None) -> None:
        """Queues the automatic retry of a take whose dialogue did not match, when the rules
        allow it. Never raises: the check's own outcome is already saved.
        """
        if take_id is None:
            return
        try:
            async with SessionLocal() as session:
                retry_job = await shot_takes.queue_retry(session, take_id)
        except Exception:
            _logger.exception("take %d: the automatic retry could not be queued", take_id)
            return
        if retry_job is not None:
            dispatcher.nudge()
            _logger.info(
                "take %d failed its dialogue check: retry queued as job %d", take_id, retry_job.id
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


def _processing_time(body: dict[str, Any]) -> float | None:
    value = body.get("processing_time")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
