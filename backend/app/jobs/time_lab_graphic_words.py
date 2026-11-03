"""The `time_lab_graphic_words` job: when is each word of a Graphics lab run's line spoken?
(GFX-004)

It is `time_speech_words` for the speech of a Graphics lab run: the whole speech goes to
Parakeet and the heard words are matched to the run's line (`word_timings.align`). The upload,
the polling and the download are the parent's; only what is timed and where the result goes
differ.

The result is the run's `timing` column (`graphics_lab.voice_timing`: one entry for each word of
the line, with `source` `parakeet`, or `estimated` and a note when too few words matched),
written in the same transaction that finishes the job. Nothing starts after it for an ordinary
run: the brief is the owner's click, and it waits for this timing. A run made by the trial batch
(GFX-012, `services/graphics_trial.py`) is the exception: the trial's click already asked for the
brief and the engines, so they start now (best effort, after the timing is saved).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job
from app.db.session import SessionLocal
from app.jobs import store
from app.jobs.time_speech_words import TimeSpeechWordsHandler, processing_time
from app.providers import transcriber
from app.services import graphics_lab, graphics_trial, word_timings

_logger = logging.getLogger(__name__)


class TimeLabGraphicWordsHandler(TimeSpeechWordsHandler):
    job_type = graphics_lab.TIMING_JOB_TYPE
    target_key = graphics_lab.TIMING_DEDUPE_KEY

    async def _speech_path(self, session: AsyncSession, target_id: object) -> str | None:
        if not isinstance(target_id, int):
            return None
        found = await graphics_lab.speech_for_timing(session, target_id)
        return found[0] if found is not None else None

    async def _match_and_store(
        self, job: Job, body: dict[str, Any], spoken: list[transcriber.SpokenWord]
    ) -> bool:
        recorded = job.input if isinstance(job.input, dict) else {}
        run_id = recorded.get(self.target_key)

        async with SessionLocal() as session:
            found = (
                await graphics_lab.speech_for_timing(session, run_id)
                if isinstance(run_id, int)
                else None
            )
            if found is None or not isinstance(run_id, int):
                await store.fail_job(
                    session, job.id, "The speech this timing was made for is gone."
                )
                return False
            _path, line_text, speech_duration_s = found
            threshold = await settings_service.get_int(
                session, settings_service.WORD_TIMING_MATCH_THRESHOLD_KEY
            )
            duration_s = (
                speech_duration_s
                if speech_duration_s is not None
                else max((word.end for word in spoken), default=0.0)
            )
            alignment = word_timings.align(line_text, spoken, duration_s, threshold)
            saved = await graphics_lab.store_timing(
                session, run_id, graphics_lab.voice_timing(alignment, threshold, duration_s)
            )
            output: dict[str, Any] = {
                "run_id": run_id,
                "processing_time": processing_time(body),
                "timing": (
                    {
                        "source": alignment.source,
                        "match_percent": alignment.match_percent,
                        "threshold": threshold,
                        "words": len(alignment.words),
                    }
                    if saved
                    else {"kept": True}
                ),
            }
            # The result and the finished job are saved together or not at all.
            if not await store.finish_job(session, job.id, output):
                await session.rollback()
                _logger.warning("job %d: words matched but the job is not running", job.id)
                return False
            await session.commit()
        _logger.info(
            "job %d: graphics run %d timed: source=%s match=%s%% (needed %s%%)",
            job.id,
            run_id,
            alignment.source,
            alignment.match_percent,
            threshold,
        )
        if saved:
            await self._start_trial_run(job.id, run_id)
        return True

    @staticmethod
    async def _start_trial_run(job_id: int, run_id: int) -> None:
        """A run of a trial batch (GFX-012) has its brief and engines started now that its
        timing is stored. Best effort: a failure is kept on the run, and the job stays done.
        """
        try:
            await graphics_trial.start_after_timing(run_id)
        except Exception:
            _logger.exception("job %d: the trial could not start run %d", job_id, run_id)
