"""The `lab_voice` job: one speech from the Voice lab (Phase 21).

It is `SpeechHandler` with one piece of text, and `store_result` stores the WAV under
`media/lab/` and writes it on the `lab_voice_run` row, in one transaction with the finished
job. The job belongs to no project (`job.project_id` is NULL).

A speech made for a take of the Character lab (Phase 25) best-effort nudges that take along
when it has been stored (`character_takes.on_voice_finished`); a speech made for anything else
(a plain Voice lab run) finds no take and does nothing further.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from app.db.models import Job, LabVoiceRun
from app.db.session import SessionLocal
from app.jobs import dispatcher, store
from app.jobs.synthesize_speech import SpeechFile, SpeechHandler
from app.services import character_takes, voice_lab
from app.services.storage import get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = voice_lab.RUN_JOB


class LabVoiceHandler(SpeechHandler):
    job_type = JOB_TYPE

    async def store_result(self, job: Job, speech: SpeechFile) -> bool:
        recorded = job.input if isinstance(job.input, dict) else {}
        run_id = recorded.get("run_id")
        stored = await get_storage().save_lab(speech.temp, "wav")
        output: dict[str, Any] = {
            "run_id": run_id,
            "speech": {
                "duration_s": speech.duration_s,
                "sample_rate": speech.sample_rate,
                "channels": speech.channels,
                "size_bytes": speech.temp.size_bytes,
            },
        }

        # The file on the run and the finished job are saved together or not at all.
        async with SessionLocal() as session:
            run = await session.get(LabVoiceRun, run_id) if isinstance(run_id, int) else None
            if run is not None:
                run.path = stored.relative_path
                run.size_bytes = speech.temp.size_bytes
                run.sha256 = speech.temp.sha256
                run.duration_s = speech.duration_s
            else:
                _logger.warning("job %d: speech stored but its run %s is gone", job.id, run_id)
            if not await store.finish_job(session, job.id, output):
                await session.rollback()
                # Cancelled in the meantime. Stored files are never deleted.
                _logger.warning(
                    "job %d: speech stored but the job is no longer running: %s",
                    job.id,
                    stored.relative_path,
                )
                return False
            await session.commit()

        if isinstance(run_id, int):
            await self._continue_take(job.id, run_id)
        return True

    @staticmethod
    async def _continue_take(job_id: int, run_id: int) -> None:
        """Starts the next step of the Character lab take this speech was made for, if any.
        A plain Voice lab run (not linked to a take) is a no-op here. Best effort: a failure
        never fails the speech (it is stored), and the take's next step can be started by hand.
        """
        try:
            started = await character_takes.on_voice_finished(run_id)
        except Exception:
            _logger.exception("job %d: the take could not continue after its speech", job_id)
            return
        if started:
            dispatcher.nudge()
