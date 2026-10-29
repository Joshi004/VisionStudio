"""The clock of a scene's take: its timed words, and where each speech unit sits in it (FLOW-004).

A continuous explainer speaks each scene as one take (FLOW-003): the scene's unit texts joined in
order with one space. The take's words are timed by the `time_speech_words` job like any speech
(`services/word_timings.py`), so every script word has a start and an end in seconds from the
start of the take. Because the take's text is the units joined, each script word belongs to
exactly one unit, and a unit's **span** is the start of its first word to the end of its last
word. The pauses between units belong to no unit. Spans are in order and never overlap, because
the timed words never go backwards.

- `unit_spans` is pure: the units and the timed words go in, the spans come out.
- `scene_clocks` reads a project: for each scene with a take it gives the words and spans when
  the take is ready and timed from what Parakeet heard, and otherwise the reason the cut planning
  (FLOW-005) must wait. A take whose match fell below the threshold has **estimated** timing,
  which is not good enough to cut on, so it is blocked and has to be made again.

Nothing here is stored. A take is only `ready` when its text is the current units joined, so the
word counts always line up with the current units.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, SpeechUnitAudio, SpeechWordTiming
from app.services import speech_synthesis, word_timings
from app.services.word_timings import WordTimingError

NOT_MADE_REASON: Final = "Make this scene's take first."
IN_PROGRESS_REASON: Final = "This scene's take is being made."
OUT_OF_DATE_REASON: Final = "This scene's take is out of date. Make the take again."
NOT_TIMED_REASON: Final = "The words of this scene's take are not timed yet."
# The reasons that pass by themselves: a take being made, or being timed. Any other reason needs
# the user (a take to make again, a timing that failed, a poor match).
WAITING_REASONS: Final = (IN_PROGRESS_REASON, NOT_TIMED_REASON)


@dataclass(frozen=True)
class UnitSpan:
    """Where one speech unit sits inside its scene's take, in seconds from the take's start."""

    unit_id: str
    # The positions (from 0) of the unit's first and last word in the take's words.
    first_word: int
    last_word: int
    start: float
    end: float


@dataclass(frozen=True)
class TakeClock:
    """The words of one scene's take and the span of each unit, or why there are none."""

    scene_id: str
    audio: SpeechUnitAudio | None
    timing: SpeechWordTiming | None
    # The take's script words in order, each `{"text", "start", "end"}`. Empty when blocked.
    words: list[dict[str, Any]]
    spans: list[UnitSpan]
    # None only when the take is ready and timed from what Parakeet heard.
    blocked_reason: str | None


# --- Pure rules ---------------------------------------------------------------------------


def poor_match_reason(match_percent: float | None, threshold: int | None) -> str:
    """Why a take with estimated timing cannot be cut on."""
    return (
        f"Only {match_percent or 0}% of this take's words matched what was heard "
        f"({threshold or 0}% needed), which is too few to cut on. Make the scene's take again."
    )


def unit_spans(units: Sequence[dict[str, Any]], words: Sequence[dict[str, Any]]) -> list[UnitSpan]:
    """The span of each unit inside the take's timed words. Each unit takes the next
    `len(text.split())` words, the same split `word_timings.align` makes of the take's text.
    Raises WordTimingError when the units and the words do not add up.
    """
    spans: list[UnitSpan] = []
    position = 0
    for unit in units:
        count = len(str(unit["text"]).split())
        if count == 0:
            raise WordTimingError(f"The speech unit '{unit['id']}' has no words.")
        last = position + count - 1
        if last >= len(words):
            raise WordTimingError(
                "The take has fewer timed words than the scene's speech units. "
                "Make the scene's take again."
            )
        spans.append(
            UnitSpan(
                unit_id=str(unit["id"]),
                first_word=position,
                last_word=last,
                start=float(words[position]["start"]),
                end=float(words[last]["end"]),
            )
        )
        position = last + 1
    if position != len(words):
        raise WordTimingError(
            "The take has more timed words than the scene's speech units. "
            "Make the scene's take again."
        )
    return spans


# --- Reading a project --------------------------------------------------------------------


def _blocked(
    scene_id: str,
    reason: str,
    audio: SpeechUnitAudio | None = None,
    timing: SpeechWordTiming | None = None,
) -> TakeClock:
    return TakeClock(scene_id, audio, timing, [], [], reason)


def blocked_reason_of(
    take: speech_synthesis.TakeEntry, entry: word_timings.TimingEntry | None
) -> str | None:
    """Why this take cannot go on to cut planning, or None when it is ready and timed from what
    Parakeet heard. Worked out from the take's state and the state of its timing.
    """
    if take.status == "in_progress":
        return IN_PROGRESS_REASON
    if take.status == "out_of_date":
        return OUT_OF_DATE_REASON
    if take.status != "ready" or take.audio is None:
        return NOT_MADE_REASON
    if entry is None or entry.status in ("none", "in_progress"):
        return NOT_TIMED_REASON
    if entry.status == "failed":
        return f"{NOT_TIMED_REASON} {entry.error or ''}".strip()
    if entry.status == "estimated":
        timing = entry.timing
        return poor_match_reason(
            timing.match_percent if timing is not None else None,
            timing.threshold if timing is not None else None,
        )
    return None


async def scene_clocks(session: AsyncSession, project: Project) -> dict[str, TakeClock]:
    """The clock of the take of every scene that has one, by scene id. Empty for a project that
    does not speak in takes.
    """
    if not word_timings.times_takes(project):
        return {}
    audio_state = await speech_synthesis.state(session, project)
    timings = await word_timings.state(session, project)
    clocks: dict[str, TakeClock] = {}
    for scene in audio_state.scenes:
        take = scene.take
        if take is None:
            continue
        scene_id = str(scene.scene.item["id"])
        entry = timings.get(take.audio.id) if take.audio is not None else None
        reason = blocked_reason_of(take, entry)
        if reason is not None:
            clocks[scene_id] = _blocked(
                scene_id, reason, take.audio, entry.timing if entry is not None else None
            )
            continue
        assert entry is not None and entry.timing is not None  # `reason` is None only when timed
        words = list(entry.timing.words)
        try:
            spans = unit_spans([unit.unit for unit in scene.units], words)
        except WordTimingError as exc:
            clocks[scene_id] = _blocked(scene_id, str(exc), take.audio, entry.timing)
            continue
        clocks[scene_id] = TakeClock(scene_id, take.audio, entry.timing, words, spans, None)
    return clocks
