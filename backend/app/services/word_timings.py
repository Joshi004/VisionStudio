"""The time of every script word of a speech (EXPLAINER-007, decision E-12).

Captions and callouts follow the presenter's words, so each speech of an explainer needs a start
and an end time for each word of its **script** (never a transcript). The TTS provider returns no
word times, so Parakeet transcribes the speech's WAV (`jobs/time_speech_words.py`) and `align`
matches the heard words back to the script's words.

Two halves:

- `align`: pure rules, no I/O. The script text, the heard words, the speech's length and the
  threshold go in, an `Alignment` comes out.
- The state of a project's timings (`state`), and how they are queued (`queue`, `start`).

How `align` works:

- Both sides are split into the tokens `dialogue_check.normalize_words` makes (NFKC, lower case,
  apostrophes dropped, other punctuation turned into a space), so "Don't stop!" and "dont stop"
  are the same tokens. A script word that makes several tokens ("well-known") keeps them all, and
  the word's time runs from its first token to its last.
- The tokens are matched with `difflib.SequenceMatcher`. A matched token takes the time of the
  heard token. A script span that replaces a heard span ("five" heard as "5") shares the heard
  span's time by character count. A script token that nothing was heard for gets a share of the
  gap between its timed neighbours.
- `match_percent` is the share of script tokens that matched exactly. Below the threshold (or
  when nothing was heard) the whole speech gets **estimated** timing instead: each word gets its
  share of the speech's length by character count.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, SpeechUnitAudio, SpeechWordTiming
from app.jobs import store
from app.providers.transcriber import SpokenWord
from app.services.dialogue_check import normalize_words
from app.services.project_kinds import KIND_EXPLAINER

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "time_speech_words"
# Two presses on one speech make one job.
DEDUPE_KEY: Final = "speech_unit_audio_id"

SOURCE_PARAKEET: Final = "parakeet"
SOURCE_ESTIMATED: Final = "estimated"

# `none`: no timing and no job. `in_progress`: its job is queued or running. `failed`: its newest
# job failed or was cancelled. `timed`: made from what Parakeet heard. `estimated`: too few words
# matched, so the times were estimated.
Status = Literal["none", "in_progress", "failed", "timed", "estimated"]

_ROUND_DIGITS: Final = 3


class WordTimingError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class Alignment:
    """The result of `align`."""

    # The script's words in order, each `{"text", "start", "end"}` in seconds from the start of
    # the file.
    words: list[dict[str, Any]]
    source: str
    # In percent, 0 to 100, one decimal.
    match_percent: float
    # What Parakeet heard, as it wrote it.
    heard_text: str


@dataclass(frozen=True)
class TimingEntry:
    """Where the word timing of one stored speech stands."""

    status: Status
    timing: SpeechWordTiming | None
    error: str | None
    job: Job | None


# --- Pure matching ------------------------------------------------------------------------


def _share_out(weights: Sequence[int], start: float, end: float) -> list[tuple[float, float]]:
    """Divides `start..end` among items in proportion to their weights, in order."""
    total = sum(weights)
    span = max(end - start, 0.0)
    result: list[tuple[float, float]] = []
    used = 0
    for weight in weights:
        first = start + span * used / total
        used += weight
        result.append((first, start + span * used / total))
    return result


def _estimated(display: list[str], duration_s: float) -> list[tuple[float, float]]:
    """Each word's share of the whole speech, by character count."""
    if not display:
        return []
    return _share_out([len(word) for word in display], 0.0, duration_s)


def _heard_tokens(spoken: Sequence[SpokenWord]) -> list[tuple[str, float, float]]:
    """The heard words as tokens. A word that makes several tokens shares its time evenly."""
    tokens: list[tuple[str, float, float]] = []
    for word in spoken:
        pieces = normalize_words(word.word)
        if not pieces:
            continue
        for piece, (start, end) in zip(
            pieces, _share_out([1] * len(pieces), word.start, word.end), strict=True
        ):
            tokens.append((piece, start, end))
    return tokens


def _fill_gaps(
    times: list[tuple[float, float] | None], tokens: list[str], duration_s: float
) -> list[tuple[float, float]]:
    """Gives every script token without a time a share of the gap between its timed neighbours.
    The gap runs from 0 or to `duration_s` at the edges of the speech.
    """
    filled: list[tuple[float, float]] = []
    index = 0
    while index < len(times):
        current = times[index]
        if current is not None:
            filled.append(current)
            index += 1
            continue
        run_end = index
        while run_end < len(times) and times[run_end] is None:
            run_end += 1
        previous = filled[-1][1] if filled else 0.0
        following = times[run_end]
        gap_end = following[0] if following is not None else duration_s
        gap_end = max(gap_end, previous)
        filled.extend(
            _share_out([len(token) for token in tokens[index:run_end]], previous, gap_end)
        )
        index = run_end
    return filled


def _matched_times(
    script: list[str], heard: list[tuple[str, float, float]], duration_s: float
) -> tuple[list[tuple[float, float]], int]:
    """A time for every script token, and how many of them matched a heard token exactly."""
    times: list[tuple[float, float] | None] = [None] * len(script)
    matched = 0
    heard_words = [token for token, _start, _end in heard]
    for tag, i1, i2, j1, j2 in SequenceMatcher(
        None, script, heard_words, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            matched += i2 - i1
            for offset in range(i2 - i1):
                _token, start, end = heard[j1 + offset]
                times[i1 + offset] = (start, end)
        elif tag == "replace":
            shares = _share_out(
                [len(token) for token in script[i1:i2]], heard[j1][1], heard[j2 - 1][2]
            )
            for offset, share in enumerate(shares):
                times[i1 + offset] = share
    return _fill_gaps(times, script, duration_s), matched


def _words_json(
    display: list[str], owners: list[int], token_times: list[tuple[float, float]], duration_s: float
) -> list[dict[str, Any]]:
    """The script words with a time each: from the first token's start to the last token's end.
    A word that makes no token ("—") is a zero-length time at the end of the word before it.
    Times never go backwards and never pass the length of the speech.
    """
    first: dict[int, float] = {}
    last: dict[int, float] = {}
    for owner, (start, end) in zip(owners, token_times, strict=True):
        first.setdefault(owner, start)
        last[owner] = end

    words: list[dict[str, Any]] = []
    previous_end = 0.0
    for position, text in enumerate(display):
        start = first.get(position, previous_end)
        end = last.get(position, start)
        start = min(max(start, previous_end), duration_s)
        end = min(max(end, start), duration_s)
        words.append(
            {
                "text": text,
                "start": round(start, _ROUND_DIGITS),
                "end": round(end, _ROUND_DIGITS),
            }
        )
        previous_end = end
    return words


def align(text: str, spoken: Sequence[SpokenWord], duration_s: float, threshold: int) -> Alignment:
    """Gives every script word of `text` a start and an end time. `threshold` is a percent, 0 to
    100: the share of script tokens that must match what was heard for the heard times to be used.
    """
    display = text.split()
    heard_text = " ".join(word.word for word in spoken)
    script: list[str] = []
    owners: list[int] = []
    for position, word in enumerate(display):
        for token in normalize_words(word):
            script.append(token)
            owners.append(position)
    heard = _heard_tokens(spoken)

    def estimated(match_percent: float) -> Alignment:
        shares = _estimated(display, duration_s)
        words = [
            {"text": word, "start": round(start, _ROUND_DIGITS), "end": round(end, _ROUND_DIGITS)}
            for word, (start, end) in zip(display, shares, strict=True)
        ]
        return Alignment(words, SOURCE_ESTIMATED, match_percent, heard_text)

    if not script or not heard:
        return estimated(0.0)

    token_times, matched = _matched_times(script, heard, duration_s)
    match_percent = round(100 * matched / len(script), 1)
    if match_percent < threshold:
        return estimated(match_percent)
    words = _words_json(display, owners, token_times, duration_s)
    return Alignment(words, SOURCE_PARAKEET, match_percent, heard_text)


# --- Which projects, queueing, state ------------------------------------------------------


def wanted(project: Project) -> bool:
    """Whether the project's speeches get word timings: an explainer whose captions or callouts
    are on. A story never does.
    """
    return project.kind == KIND_EXPLAINER and (project.captions or project.callouts)


async def queue(
    session: AsyncSession, audio: SpeechUnitAudio, *, commit: bool = True
) -> tuple[Job, bool]:
    """Queues the job that times the words of one stored speech. Returns `(job, created)`: the
    job already timing it when it was not created. With `commit=False` the job is only flushed,
    so the caller saves it with the speech.
    """
    job, created = await store.create_job(
        session,
        project_id=audio.project_id,
        type=JOB_TYPE,
        provider="gpu",
        input={"requested": JOB_TYPE, DEDUPE_KEY: audio.id},
        commit=commit,
        dedupe_key=DEDUPE_KEY,
    )
    if created:
        _logger.info(
            "speech %d of project %d: word timing queued as job %d",
            audio.id,
            audio.project_id,
            job.id,
        )
    return job, created


def _job_error(job: Job) -> str:
    if job.error:
        return job.error
    return "The timing was cancelled." if job.status == "cancelled" else "The timing failed."


async def state(session: AsyncSession, project: Project) -> dict[int, TimingEntry]:
    """Where the word timing of every stored speech of the project stands, by the audio's id.
    Worked out on every read; nothing here is stored.
    """
    audio_ids = list(
        (
            await session.execute(
                select(SpeechUnitAudio.id).where(
                    SpeechUnitAudio.project_id == project.id, SpeechUnitAudio.path.is_not(None)
                )
            )
        ).scalars()
    )
    timings = {
        row.speech_unit_audio_id: row
        for row in (
            await session.execute(
                select(SpeechWordTiming)
                .where(SpeechWordTiming.project_id == project.id)
                .execution_options(populate_existing=True)
            )
        ).scalars()
    }
    newest_jobs: dict[int, Job] = {}
    jobs = await session.execute(
        select(Job)
        .where(Job.project_id == project.id, Job.type == JOB_TYPE)
        .order_by(Job.id)
        .execution_options(populate_existing=True)
    )
    for job in jobs.scalars():  # the oldest first, so the newest replaces the others
        key = job.input.get(DEDUPE_KEY) if isinstance(job.input, dict) else None
        if isinstance(key, int):
            newest_jobs[key] = job

    entries: dict[int, TimingEntry] = {}
    for audio_id in audio_ids:
        timing = timings.get(audio_id)
        job = newest_jobs.get(audio_id)
        status: Status
        error: str | None = None
        if timing is not None:
            status = "estimated" if timing.source == SOURCE_ESTIMATED else "timed"
        elif job is not None and job.status in store.ACTIVE_STATUSES:
            status = "in_progress"
        elif job is not None and job.status != "succeeded":
            status, error = "failed", _job_error(job)
        else:
            status = "none"
        entries[audio_id] = TimingEntry(status=status, timing=timing, error=error, job=job)
    return entries


async def start(session: AsyncSession, project: Project, audio_id: int) -> Job:
    """Queues the timing of one stored speech and commits. Raises WordTimingError."""
    if not wanted(project):
        raise WordTimingError(
            "Word timings are only made for an explainer with captions or callouts on."
        )
    audio = await session.get(SpeechUnitAudio, audio_id)
    if audio is None or audio.project_id != project.id:
        raise WordTimingError("This speech does not exist.")
    if audio.path is None:
        raise WordTimingError("Speak this line first.")
    existing = await session.execute(
        select(SpeechWordTiming.id).where(SpeechWordTiming.speech_unit_audio_id == audio.id)
    )
    if existing.first() is not None:
        raise WordTimingError("The words of this speech are already timed.")
    job, _created = await queue(session, audio)
    return job
