"""What the project page shows about a project's transcript (ANALYSIS.md Section 5.1).

The newest transcript of a project is the one that counts. It is *out of date* when the
voiceover or the script is not the one it was made from (DATABASE_STRUCTURE.md Section
4.3). The counts and the warning are worked out from the stored words every time, so
changing the warning threshold applies to transcripts that already exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, Transcript
from app.jobs import store
from app.services import transcript_matching
from app.services.transcript_matching import MatchCounts

StaleReason = Literal["script_changed", "voiceover_changed"]

TRANSCRIBE_JOB = "transcribe"


@dataclass(frozen=True)
class TranscriptionState:
    # The newest transcribe job, whatever its status. None if there never was one.
    job: Job | None
    transcript: Transcript | None
    counts: MatchCounts | None
    warnings: list[str]
    stale_reasons: list[StaleReason]
    processing_time: float | None


async def latest_transcript(session: AsyncSession, project_id: int) -> Transcript | None:
    statement = (
        select(Transcript)
        .where(Transcript.project_id == project_id)
        .order_by(Transcript.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


def stale_reasons(transcript: Transcript, project: Project) -> list[StaleReason]:
    reasons: list[StaleReason] = []
    if transcript.voiceover_asset_id != project.voiceover_asset_id:
        reasons.append("voiceover_changed")
    if transcript.script_sha256 != transcript_matching.script_sha256(project.script_text or ""):
        reasons.append("script_changed")
    return reasons


def _counts(transcript: Transcript) -> MatchCounts:
    script_words = transcript.script_words if isinstance(transcript.script_words, list) else []
    matched = sum(1 for entry in script_words if isinstance(entry, dict) and entry.get("matched"))

    spoken = 0
    words: Any = transcript.words
    heard = words.get("word_timestamps") if isinstance(words, dict) else None
    for item in heard if isinstance(heard, list) else []:
        text = item.get("word") if isinstance(item, dict) else None
        if isinstance(text, str) and transcript_matching.normalise(text):
            spoken += 1

    return MatchCounts(
        script_words=len(script_words),
        matched=matched,
        interpolated=len(script_words) - matched,
        spoken_words=spoken,
        extra_spoken=max(spoken - matched, 0),
    )


def _processing_time(transcript: Transcript) -> float | None:
    words: Any = transcript.words
    value = words.get("processing_time") if isinstance(words, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


async def transcription_state(session: AsyncSession, project: Project) -> TranscriptionState:
    job = await store.latest_job(session, project.id, TRANSCRIBE_JOB)
    transcript = await latest_transcript(session, project.id)
    if transcript is None:
        return TranscriptionState(
            job=job,
            transcript=None,
            counts=None,
            warnings=[],
            stale_reasons=[],
            processing_time=None,
        )

    counts = _counts(transcript)
    return TranscriptionState(
        job=job,
        transcript=transcript,
        counts=counts,
        warnings=transcript_matching.mismatch_warnings(counts),
        stale_reasons=stale_reasons(transcript, project),
        processing_time=_processing_time(transcript),
    )
