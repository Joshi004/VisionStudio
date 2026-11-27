"""Where footage goes (FTG-004, `Footage_broll_implementation_phases.md` section 4.9).

Footage is real picture laid full screen over the presenter and B-roll shots under the words of a
footage mark, while the narrator keeps talking. The shot plan is not touched: code decides, on
read, from the marks, the pieces the owner chose to show and the timeline of a scene whose plan
is current.

Pure: no I/O, no clock. Times are seconds on the scene's timeline (`scene_timeline`), the same
numbers as `ShotSpan.start_s` and `end_s`.

**Rules** (`place_footage`):

- One **run** for each unbroken stretch of a mark's words in a scene (the caller breaks a run at
  a sound bite's words, as for graphic overlays). A run goes from the middle of the pause before
  its first word to the middle of the pause after its last word (the caller works these out the
  way the cut planner places a cut).
- Footage never covers a drawn shot (graphic, evidence, sound bite), a graphic overlay or a split
  stretch (FT-12): that time is cut out of the run, and each part left is placed on its own. The
  key of a part is `{scene_id}/{first}-{last}`: its first and last word in the scene's take,
  counted from 1. A part with no word in it is dropped.
- A part with a single word, left beside something footage may not cover, gets no footage.
- A part is at least `MIN_S` long. A shorter one runs on after its last word, up to the next thing
  it may not cover, the next part or the end of the scene, and then starts up to `MAX_LEAD_S`
  earlier. With no room it is not placed.
- The parts of one mark in a scene take the pieces the owner chose in order: a part starts at the
  piece after the last one the part before it showed, and goes back to the first piece when the
  list runs out. A part never shows a piece twice, and shows only as many as fit at `MIN_PIECE_S`
  each (the first ones; the others get a note). A new scene starts again from the first piece.
- A part's time is shared out evenly, but a video gets at most its `length_s` and a still piece at
  most `STILL_MAX_S`. Time that a piece cannot use goes to the pieces that still can use it. When
  every piece is full the part ends there and the shot under it shows again.
- A boundary between two pieces moves to the middle of the nearest pause between words when one
  is within `SNAP_S` and every piece stays within its own limits.
- The key of a placed piece is `{part key}:{item_key}`. The same words and the same piece keep the
  same key, so a clip is not drawn again when other marks change.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.services import evidence_cards, graphic_overlays, graphic_suggestions

# Footage is on screen for at least this long.
MIN_S: Final = 2.0
# A short run may start up to this long before its natural start, when it has no room after.
MAX_LEAD_S: Final = 1.0
# Every piece of a montage is on screen for at least this long.
MIN_PIECE_S: Final = 1.5
# A boundary between pieces moves to a pause at most this far away.
SNAP_S: Final = 0.5
# The longest a still piece (image, page, PDF) is on screen: the most the motion service draws
# (`graphic_overlays.MAX_FRAMES` at `FPS`), less the spare frame a drawn clip has and one frame
# that rounding the two ends to the frame grid may add.
STILL_MAX_S: Final = (graphic_overlays.MAX_FRAMES - graphic_overlays.SPARE_FRAMES - 1) / (
    graphic_overlays.FPS
)

VIDEO: Final = "video"

NO_ROOM: Final = "no_room"
COVERED: Final = "covered"
SOUNDBITE: Final = "soundbite"
ONE_WORD: Final = "one_word"
TOO_SHORT: Final = "too_short"
UNPLACED_TEXT: Final = {
    NO_ROOM: (
        "There is less than 2 seconds of room for this footage before the next graphic, "
        "evidence or sound bite shot, or before the end of the scene."
    ),
    COVERED: (
        "A graphic, evidence or sound bite shot, or a graphic overlay, covers all of these words."
    ),
    SOUNDBITE: graphic_suggestions.SOUNDBITE_REASON,
    ONE_WORD: (
        "Only one word of these words is left beside a graphic, evidence or a sound bite, "
        "so it gets no footage."
    ),
    TOO_SHORT: "Every piece chosen for these words is shorter than 1.5 seconds.",
}

LEFT_OUT: Final = "left_out"
CUT_SHORT: Final = "cut_short"
NOTE_TEXT: Final = {
    LEFT_OUT: (
        "There is no room for it: the words are said too fast to show every piece for at "
        "least 1.5 seconds."
    ),
    CUT_SHORT: "A photo, page or PDF is shown for at most 30 seconds, so it is cut short.",
}

_DECIMALS: Final = 3
# Float noise allowed when lengths and times are compared.
_EPSILON: Final = 1e-6


@dataclass(frozen=True)
class Piece:
    """A piece the owner chose to show. `length_s` is how long a video can play, None for a still
    piece."""

    item_key: str
    kind: str
    length_s: float | None

    @property
    def cap_s(self) -> float:
        return self.length_s if self.length_s is not None else STILL_MAX_S


@dataclass(frozen=True)
class WordAt:
    """A word of the scene's take: its position counted from 1 and its times in the scene."""

    number: int
    start_s: float
    end_s: float

    @property
    def middle_s(self) -> float:
        return (self.start_s + self.end_s) / 2


@dataclass(frozen=True)
class Wanted:
    """One run of a mark's words in a scene: the natural times (the middle of the pause before the
    first word and of the pause after the last), the words in it and the pieces to show.
    `trimmed` is true when a sound bite took words out of the mark."""

    scene_id: str
    mark_id: str
    text: str
    pieces: tuple[Piece, ...]
    words: tuple[WordAt, ...]
    start_s: float
    end_s: float
    trimmed: bool = False


@dataclass(frozen=True)
class PlacedPiece:
    """One piece on screen from `start_s` to `end_s`, over the shots in `shot_ids` (never a drawn
    shot). `run_key` is the key of its part, `index` its place in the part, from 0."""

    scene_id: str
    mark_id: str
    run_key: str
    item_key: str
    kind: str
    index: int
    start_s: float
    end_s: float
    shot_ids: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.run_key}:{self.item_key}"

    @property
    def length_s(self) -> float:
        return round(self.end_s - self.start_s, _DECIMALS)


@dataclass(frozen=True)
class Unplaced:
    """Words of a mark that got no footage, and why. `key` is None when no part was left to give
    a key."""

    scene_id: str
    mark_id: str
    text: str
    key: str | None
    code: str

    @property
    def message(self) -> str:
        return UNPLACED_TEXT[self.code]


@dataclass(frozen=True)
class PieceNote:
    """A piece of a mark that is left out or cut short in a scene, and why."""

    scene_id: str
    mark_id: str
    text: str
    item_key: str
    code: str

    @property
    def message(self) -> str:
        return NOTE_TEXT[self.code]


@dataclass(frozen=True)
class Placement:
    pieces: tuple[PlacedPiece, ...]
    unplaced: tuple[Unplaced, ...]
    notes: tuple[PieceNote, ...]


@dataclass(frozen=True)
class _Part:
    run: Wanted
    start_s: float
    end_s: float
    first_word: int
    last_word: int

    @property
    def key(self) -> str:
        return f"{self.run.scene_id}/{self.first_word}-{self.last_word}"


def _r(value: float) -> float:
    return round(value, _DECIMALS)


def _subtract(
    start_s: float, end_s: float, blocked: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    """What is left of `start_s` to `end_s` when the `blocked` spans (sorted by start) are cut
    out."""
    parts: list[tuple[float, float]] = []
    cursor = start_s
    for blocked_start, blocked_end in blocked:
        if blocked_end <= cursor:
            continue
        if blocked_start >= end_s:
            break
        if blocked_start > cursor:
            parts.append((cursor, blocked_start))
        cursor = max(cursor, blocked_end)
        if cursor >= end_s:
            break
    if cursor < end_s:
        parts.append((cursor, end_s))
    return [(first, last) for first, last in parts if last - first > _EPSILON]


def _share(length_s: float, caps: Sequence[float]) -> list[float]:
    """Shares `length_s` evenly, a piece taking at most its cap; what a capped piece cannot use is
    shared out among the others. The sum is `length_s`, or the sum of the caps when that is less."""
    shares = [0.0] * len(caps)
    open_pieces = list(range(len(caps)))
    remaining = length_s
    while open_pieces:
        even = remaining / len(open_pieces)
        full = [index for index in open_pieces if caps[index] <= even + _EPSILON]
        if not full:
            for index in open_pieces:
                shares[index] = even
            break
        for index in full:
            shares[index] = caps[index]
            remaining -= caps[index]
        open_pieces = [index for index in open_pieces if index not in full]
    return shares


def _snap(edges: list[float], caps: Sequence[float], pauses: Sequence[float]) -> None:
    """Moves each inner boundary in `edges` (the piece `k` runs from `edges[k]` to `edges[k + 1]`)
    to the nearest pause within `SNAP_S` that keeps both pieces within their limits."""
    for boundary in range(1, len(edges) - 1):
        low = max(edges[boundary - 1] + MIN_PIECE_S, edges[boundary + 1] - caps[boundary])
        high = min(edges[boundary + 1] - MIN_PIECE_S, edges[boundary - 1] + caps[boundary - 1])
        options = [
            pause
            for pause in pauses
            if abs(pause - edges[boundary]) <= SNAP_S + _EPSILON
            and low - _EPSILON <= pause <= high + _EPSILON
        ]
        if options:
            edges[boundary] = min(options, key=lambda pause: (abs(pause - edges[boundary]), pause))


def _parts(
    run: Wanted, total_s: float, blocked: Sequence[tuple[float, float]], unplaced: list[Unplaced]
) -> list[_Part]:
    """The parts of a run that footage may cover, each with words in it. Adds to `unplaced` why a
    run, or part of it, got none."""
    end_s = min(run.end_s, total_s)
    found: list[_Part] = []
    for start, end in _subtract(run.start_s, end_s, blocked):
        inside = [word.number for word in run.words if start <= word.middle_s < end]
        if inside:
            found.append(_Part(run, start, end, min(inside), max(inside)))
    if not found:
        unplaced.append(Unplaced(run.scene_id, run.mark_id, run.text, None, COVERED))
        return []
    kept: list[_Part] = []
    for part in found:
        words = [word for word in run.words if part.first_word <= word.number <= part.last_word]
        if len(words) == 1 and (run.trimmed or len(words) < len(run.words)):
            unplaced.append(Unplaced(run.scene_id, run.mark_id, run.text, part.key, ONE_WORD))
        else:
            kept.append(part)
    return kept


def place_footage(
    wanted: Sequence[Wanted],
    slots: Sequence[evidence_cards.Slot],
    blocked: Sequence[tuple[float, float]],
    pauses: Sequence[float],
    total_s: float,
) -> Placement:
    """The footage of one scene, in time order. `slots` are the scene's shots, `blocked` the other
    spans footage may not cover (graphic overlays, split stretches) and `pauses` the scene times of
    the middle of each pause between words. Pure."""
    avoid = sorted([(slot.start_s, slot.end_s) for slot in slots if slot.drawn] + list(blocked))
    unplaced: list[Unplaced] = []
    parts: list[_Part] = []
    for run in wanted:
        parts.extend(_parts(run, total_s, avoid, unplaced))
    parts.sort(key=lambda part: (part.start_s, part.first_word))

    placed: list[PlacedPiece] = []
    cursors: dict[str, int] = {}
    shown: dict[str, set[str]] = {}
    cut_short: dict[str, set[str]] = {}
    previous_end: float | None = None
    for number, part in enumerate(parts):
        run = part.run
        pieces = tuple(
            piece
            for piece in run.pieces
            if piece.length_s is None or piece.length_s >= MIN_PIECE_S - _EPSILON
        )
        if not pieces:
            unplaced.append(Unplaced(run.scene_id, run.mark_id, run.text, part.key, TOO_SHORT))
            continue

        start, end = part.start_s, part.end_s
        if end - start < MIN_S - _EPSILON:
            limits = [total_s]
            if number + 1 < len(parts):
                limits.append(parts[number + 1].start_s)
            limits.extend(first for first, _ in avoid if first >= end - _EPSILON)
            end = max(end, min(start + MIN_S, *limits))
        if end - start < MIN_S - _EPSILON:
            floors = [0.0, start - MAX_LEAD_S]
            if previous_end is not None:
                floors.append(previous_end)
            floors.extend(last for _, last in avoid if last <= start + _EPSILON)
            start = max(max(floors), end - MIN_S)
        if end - start < MIN_S - _EPSILON:
            unplaced.append(Unplaced(run.scene_id, run.mark_id, run.text, part.key, NO_ROOM))
            continue

        length = end - start
        count = min(len(pieces), max(1, math.floor((length + _EPSILON) / MIN_PIECE_S)))
        first = cursors.get(run.mark_id, 0) % len(pieces)
        chosen = [pieces[(first + offset) % len(pieces)] for offset in range(count)]
        cursors[run.mark_id] = (first + count) % len(pieces)
        caps = [piece.cap_s for piece in chosen]
        shares = _share(length, caps)
        filled = sum(shares)
        if filled < length - _EPSILON:
            end = start + filled
            for piece, cap, share in zip(chosen, caps, shares, strict=True):
                if piece.length_s is None and share >= cap - _EPSILON:
                    cut_short.setdefault(run.mark_id, set()).add(piece.item_key)

        edges = [start]
        for share in shares:
            edges.append(edges[-1] + share)
        edges[-1] = end
        _snap(edges, caps, pauses)
        edges = [_r(edge) for edge in edges]

        for index, piece in enumerate(chosen):
            piece_start, piece_end = edges[index], edges[index + 1]
            placed.append(
                PlacedPiece(
                    scene_id=run.scene_id,
                    mark_id=run.mark_id,
                    run_key=part.key,
                    item_key=piece.item_key,
                    kind=piece.kind,
                    index=index,
                    start_s=piece_start,
                    end_s=piece_end,
                    shot_ids=tuple(
                        slot.shot_id
                        for slot in slots
                        if not slot.drawn and slot.start_s < piece_end and slot.end_s > piece_start
                    ),
                )
            )
            shown.setdefault(run.mark_id, set()).add(piece.item_key)
        previous_end = edges[-1]

    notes: list[PieceNote] = []
    seen: set[str] = set()
    for run in wanted:
        if run.mark_id in seen or run.mark_id not in shown:
            continue
        seen.add(run.mark_id)
        for piece in run.pieces:
            if piece.item_key not in shown[run.mark_id]:
                notes.append(
                    PieceNote(run.scene_id, run.mark_id, run.text, piece.item_key, LEFT_OUT)
                )
            elif piece.item_key in cut_short.get(run.mark_id, set()):
                notes.append(
                    PieceNote(run.scene_id, run.mark_id, run.text, piece.item_key, CUT_SHORT)
                )
    return Placement(pieces=tuple(placed), unplaced=tuple(unplaced), notes=tuple(notes))
