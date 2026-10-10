"""The `lab_voice` job: one speech from the Voice lab (Phase 21).

It is `SpeechHandler` with one piece of text, and `store_result` stores the WAV under
`media/lab/` and writes it on the `lab_voice_run` row, in one transaction with the finished
job. The job belongs to no project (`job.project_id` is NULL).
"""

from __future__ import annotations

import logging
from typing import Any, Final

from app.db.models import Job, LabVoiceRun
from app.db.session import SessionLocal
from app.jobs import store
from app.jobs.synthesize_speech import SpeechFile, SpeechHandler
from app.services import voice_lab
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
        return True
