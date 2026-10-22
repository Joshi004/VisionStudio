"""Cutting a scene's narration and dialogue events into speech units (PHASE-018,
`Path_ahead.md` Section 19). Pure: no I/O, no model.

A *speech unit* is the text that will be turned into one audio asset (PHASE-019). Each
`narration` or `dialogue` event gives one unit, or several when its estimated length is over the
limit for its kind:

- **Narration** has no shot to fit inside, because it can run across several shots. An event
  estimated above `narration_max_seconds` is cut at sentence ends, then, for a sentence that is
  still too long, at commas, semicolons and colons.
- **Dialogue** is played inside one shot, so it is cut only when it would not fit one
  (`dialogue_max_seconds`), and only at sentence ends.

A piece that cannot be cut any further (one sentence, or one clause, over the limit) is kept
whole and reported as a warning. Cutting packs whole pieces into units as full as the limit allows.

The estimate is the words divided by a speaking pace, times a factor for how the line is
delivered. It is a planning figure only; PHASE-019 measures the real length.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.services import speech_chunks

SECONDS_PER_MINUTE: Final = 60
# No line is estimated shorter than this: even "Yes." takes a moment to say.
MIN_UNIT_SECONDS: Final = 0.5

# Words in a dialogue event's `delivery.emotion` that slow a line down or speed it up. They are
# matched at the start of a word, so "whispering" and "tired" are found by "whisper" and "tire".
_SLOWER_STEMS: Final = ("whisper", "sad", "hesitan", "tire", "fear", "solemn", "slow")
_FASTER_STEMS: Final = ("excit", "angr", "anger", "urgent", "panic", "hurr", "fast")
SLOWER_FACTOR: Final = 1.15
FASTER_FACTOR: Final = 0.9

_WORD: Final = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class SpeechRules:
    """The settings that decide the estimates and the cuts, as they stand now."""

    words_per_minute: int
    narration_max_seconds: int
    dialogue_max_seconds: int


@dataclass(frozen=True)
class SpeechWarning:
    event_id: str
    message: str


def delivery_factor(emotion: str | None) -> float:
    """How much longer (above 1) or shorter (below 1) a line takes because of how it is said.
    No emotion, an unknown one, or one that points both ways gives 1.
    """
    if not emotion:
        return 1.0
    words = _WORD.findall(emotion.lower())
    slower = any(word.startswith(stem) for word in words for stem in _SLOWER_STEMS)
    faster = any(word.startswith(stem) for word in words for stem in _FASTER_STEMS)
    if slower and not faster:
        return SLOWER_FACTOR
    if faster and not slower:
        return FASTER_FACTOR
    return 1.0


def _raw_seconds(text: str, factor: float, words_per_minute: int) -> float:
    return len(text.split()) * SECONDS_PER_MINUTE / words_per_minute * factor


def estimate_seconds(text: str, emotion: str | None, words_per_minute: int) -> float:
    """The estimated time to say the text: at least `MIN_UNIT_SECONDS`, to a tenth of a second."""
    raw = _raw_seconds(text, delivery_factor(emotion), words_per_minute)
    return round(max(raw, MIN_UNIT_SECONDS), 1)


def _pack(pieces: Sequence[str], fits: Callable[[str], bool]) -> list[str]:
    """Joins neighbouring pieces while the result still fits. The pieces keep the whitespace
    that followed them, so they are joined with nothing between. A piece that does not fit on
    its own stays alone.
    """
    units: list[str] = []
    current = ""
    for piece in pieces:
        if current and fits((current + piece).strip()):
            current += piece
        else:
            if current:
                units.append(current.strip())
            current = piece
    if current.strip():
        units.append(current.strip())
    return units


def _cut(
    text: str,
    levels: Sequence[Callable[[str], list[str]]],
    fits: Callable[[str], bool],
) -> list[str]:
    """The text as pieces that each fit, cut at the first level that helps; a piece that is
    still too long goes on to the next level. A piece with no level left is returned whole.
    """
    if fits(text) or not levels:
        return [text]
    pieces: list[str] = []
    for part in levels[0](text):
        if fits(part.strip()):
            pieces.append(part)
        else:
            pieces.extend(_cut(part, levels[1:], fits))
    return pieces


def split_narration(text: str, factor: float, rules: SpeechRules) -> list[str]:
    """The narration text as units under the narration limit, cut at sentences, then clauses."""

    def fits(piece: str) -> bool:
        raw = _raw_seconds(piece, factor, rules.words_per_minute)
        return raw <= rules.narration_max_seconds

    levels = (speech_chunks.sentences, speech_chunks.clauses)
    return _pack(_cut(text, levels, fits), fits)


def split_dialogue(text: str, factor: float, rules: SpeechRules) -> list[str]:
    """The dialogue text as units that fit one shot, cut only at sentence ends."""

    def fits(piece: str) -> bool:
        raw = _raw_seconds(piece, factor, rules.words_per_minute)
        return raw <= rules.dialogue_max_seconds

    return _pack(_cut(text, (speech_chunks.sentences,), fits), fits)


def plan_units(
    events: Sequence[dict[str, Any]],
    rules: SpeechRules,
    *,
    parts_by_event: Mapping[str, Sequence[str]] | None = None,
) -> tuple[list[dict[str, Any]], list[SpeechWarning]]:
    """The speech units of one scene's events, in order, and the warnings.

    With `parts_by_event` (the user's own cuts, by event id, PHASE-037) the units are made from
    those pieces instead of the automatic split: an event with no entry gets no unit, which
    `check_coverage` refuses, and the pieces must hold exactly the words of the event, in
    order. Ids, estimates and warnings are worked out as for an automatic split.

    Only `narration` and `dialogue` events make units. Code sets each unit's id (`su_1`,
    `su_2`, ...) and `order`. `speaker_id` is None for narration. `part` and `parts` say which
    piece of its event a unit is. Raises ValueError if the units do not cover the events
    exactly (see `check_coverage`), which would be a mistake in this module.
    """
    units: list[dict[str, Any]] = []
    warnings: list[SpeechWarning] = []
    for event in events:
        kind = event.get("type")
        if kind not in ("narration", "dialogue"):
            continue
        text = " ".join(str(event.get("text") or "").split())
        if not text:
            warnings.append(SpeechWarning(event["id"], "The event has no text, so it has no unit."))
            continue
        delivery = event.get("delivery") if kind == "dialogue" else None
        emotion = delivery.get("emotion") if isinstance(delivery, dict) else None
        factor = delivery_factor(emotion)
        limit = rules.narration_max_seconds if kind == "narration" else rules.dialogue_max_seconds
        if parts_by_event is None:
            split = split_narration if kind == "narration" else split_dialogue
            parts = split(text, factor, rules)
        else:
            parts = [" ".join(part.split()) for part in parts_by_event.get(event["id"], [])]
            parts = [part for part in parts if part]
            if parts and " ".join(parts).split() != text.split():
                raise ValueError(
                    f"The units of event {event['id']} do not hold its text exactly: the words "
                    "must stay the same and in the same order, and only the cuts may move."
                )
        for index, part in enumerate(parts, start=1):
            order = len(units) + 1
            units.append(
                {
                    "id": f"su_{order}",
                    "event_id": event["id"],
                    "kind": kind,
                    "speaker_id": event.get("speaker_id") if kind == "dialogue" else None,
                    "text": part,
                    "delivery": delivery if isinstance(delivery, dict) else None,
                    "order": order,
                    "part": index,
                    "parts": len(parts),
                    "estimated_seconds": estimate_seconds(part, emotion, rules.words_per_minute),
                }
            )
            if _raw_seconds(part, factor, rules.words_per_minute) > limit:
                where = "sentence" if kind == "dialogue" else "sentence or clause"
                seconds = units[-1]["estimated_seconds"]
                warnings.append(
                    SpeechWarning(
                        event["id"],
                        f"One {where} is about {seconds:g} s, over the limit of {limit} s, "
                        "and cannot be cut any further, so it is kept whole.",
                    )
                )
    check_coverage(events, units)
    return units, warnings


def _squeeze(text: str) -> str:
    """The text with all whitespace removed, so that cuts and spacing do not matter."""
    return "".join(text.split())


def check_coverage(events: Sequence[dict[str, Any]], units: Sequence[dict[str, Any]]) -> None:
    """Raises ValueError unless the units cover every narration and dialogue event exactly once
    (all its words, none of another event's), in the order of the events.
    """
    expected = [
        event
        for event in events
        if event.get("type") in ("narration", "dialogue") and _squeeze(str(event.get("text") or ""))
    ]
    position = 0
    for event in expected:
        mine: list[dict[str, Any]] = []
        while position < len(units) and units[position]["event_id"] == event["id"]:
            mine.append(units[position])
            position += 1
        if not mine:
            raise ValueError(f"Event {event['id']} has no speech unit.")
        if _squeeze("".join(unit["text"] for unit in mine)) != _squeeze(str(event["text"])):
            raise ValueError(f"The units of event {event['id']} do not hold its text.")
    if position != len(units):
        raise ValueError("A speech unit belongs to no speech event, or is out of order.")
    orders = [unit["order"] for unit in units]
    if orders != list(range(1, len(units) + 1)):
        raise ValueError("The speech units are not numbered in order.")
