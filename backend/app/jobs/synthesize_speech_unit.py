"""The `synthesize_speech_unit` job: one speech unit of a story spoken in a saved voice
(PHASE-019).

It is `SpeechHandler` (Breeze TTS on the GPU server), so the upload of the voice, the pieces of a
long text, the polling, the pre-emption retries and the resume after a restart are the shared
ones. `store_result` stores the WAV under the project's media folder and fills in the
`speech_unit_audio` row the job was queued with (`services/speech_synthesis.py`): the file, its
checksum and the **measured** length, in one transaction with the finished job. For an explainer
with captions or callouts on, the job that times the words of the speech is queued in that same
transaction (`jobs/time_speech_words.py`, EXPLAINER-007).
"""

from __future__ import annotations

import logging
from typing import Any, Final

from sqlalchemy import select

from app.db.models import Job, Project, SpeechUnitAudio
from app.db.session import SessionLocal
from app.jobs import dispatcher, store
from app.jobs.synthesize_speech import SpeechFile, SpeechHandler
from app.services import speech_synthesis, word_timings
from app.services.storage import get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = speech_synthesis.JOB_TYPE


class SynthesizeSpeechUnitHandler(SpeechHandler):
    job_type = JOB_TYPE

    async def store_result(self, job: Job, speech: SpeechFile) -> bool:
        if job.project_id is None:
            # A unit's job is always made with its project; this only guards a damaged row.
            async with SessionLocal() as session:
                await store.fail_job(session, job.id, "The speech belongs to no project.")
            return False
        stored = await get_storage().save(speech.temp, job.project_id, "wav")
        output: dict[str, Any] = {
            "speech": {
                "duration_s": speech.duration_s,
                "sample_rate": speech.sample_rate,
                "channels": speech.channels,
                "size_bytes": speech.temp.size_bytes,
            },
        }

        # The file on the audio row and the finished job are saved together or not at all.
        queued_timing = False
        async with SessionLocal() as session:
            statement = select(SpeechUnitAudio).where(SpeechUnitAudio.job_id == job.id)
            row = (await session.execute(statement)).scalars().first()
            if row is not None:
                row.path = stored.relative_path
                row.size_bytes = speech.temp.size_bytes
                row.sha256 = speech.temp.sha256
                row.duration_s = speech.duration_s
                row.sample_rate = speech.sample_rate
                # An explainer with captions or callouts on needs the time of each word of
                # this speech (EXPLAINER-007). The job is saved with the speech.
                project = await session.get(Project, job.project_id)
                # A scene's take (FLOW-003) is timed by FLOW-004, not here.
                if (
                    project is not None
                    and row.kind != speech_synthesis.KIND_TAKE
                    and word_timings.wanted(project)
                ):
                    await word_timings.queue(session, row, commit=False)
                    queued_timing = True
            else:
                _logger.warning("job %d: speech stored but its audio row is gone", job.id)
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
        if queued_timing:
            dispatcher.nudge()
        return True
