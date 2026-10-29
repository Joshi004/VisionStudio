"""The `time_lab_speech_words` job: when is each word of an Audio video test's speech spoken?
(AVLAB)

It is `time_speech_words` for a speech that is not a speech unit of a story: the test's whole
speech goes to Parakeet and the heard words are matched to the test's text
(`word_timings.align`). The upload, the polling and the download are the parent's; only what is
timed and where the result goes differ.

The result is the test's `word_timing` column, written in the same transaction that finishes the
job. Once it is saved, the parts of the test are cut and their clips started
(`av_lab.on_timing_finished`, best effort: a failure there is kept on the test and never fails
the job).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job
from app.db.session import SessionLocal
from app.jobs import dispatcher, store
from app.jobs.time_speech_words import TimeSpeechWordsHandler, processing_time
from app.providers import transcriber
from app.services import av_lab, word_timings

_logger = logging.getLogger(__name__)


class TimeLabSpeechWordsHandler(TimeSpeechWordsHandler):
    job_type = av_lab.TIMING_JOB
    target_key = av_lab.DEDUPE_KEY

    async def _speech_path(self, session: AsyncSession, target_id: object) -> str | None:
        if not isinstance(target_id, int):
            return None
        found = await av_lab.speech_for_timing(session, target_id)
        return found[0] if found is not None else None

    async def _match_and_store(
        self, job: Job, body: dict[str, Any], spoken: list[transcriber.SpokenWord]
    ) -> bool:
        recorded = job.input if isinstance(job.input, dict) else {}
        test_id = recorded.get(self.target_key)

        async with SessionLocal() as session:
            found = (
                await av_lab.speech_for_timing(session, test_id)
                if isinstance(test_id, int)
                else None
            )
            if found is None or not isinstance(test_id, int):
                await store.fail_job(
                    session, job.id, "The speech this timing was made for is gone."
                )
                return False
            _path, text, duration_s = found
            threshold = await settings_service.get_int(
                session, settings_service.WORD_TIMING_MATCH_THRESHOLD_KEY
            )
            if duration_s is None:
                duration_s = max((word.end for word in spoken), default=0.0)
            alignment = word_timings.align(text, spoken, duration_s, threshold)
            saved = await av_lab.store_timing(
                session, test_id, av_lab.timing_dict(alignment, threshold)
            )
            output: dict[str, Any] = {
                "test_id": test_id,
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
            "job %d: test %d timed: source=%s match=%s%%",
            job.id,
            test_id,
            alignment.source,
            alignment.match_percent,
        )
        await self._continue_test(job.id, test_id)
        return True

    @staticmethod
    async def _continue_test(job_id: int, test_id: int) -> None:
        """Cuts the parts and starts their clips. Best effort: the timing is saved, and a failure
        is kept on the test.
        """
        try:
            started = await av_lab.on_timing_finished(test_id)
        except Exception:
            _logger.exception("job %d: the parts of test %d could not be made", job_id, test_id)
            return
        if started:
            dispatcher.nudge()
