"""Patches of a full recording: which stretch to record again, and how it is spliced in (REC-006).
Pure rules, no I/O.

A tight scene boundary (REC-004) can be fixed by recording a short passage again. The passage
replaces a **region** of the full recording: the words from just after one pause to just before
another, with the scene boundary inside.

- `regions` finds them. On each side of a tight boundary the nearest pause that is at least
  `MIN_SIDE_WORDS` and at most `NEAR_SIDE_WORDS` words away is the edge of the region ("about
  one line"). With none, the search widens to `FAR_SIDE_WORDS` words, and after that the region
  runs to the start or the end of the recording. A pause is a gap of at least the setting
  between two words that were both heard. Regions that overlap or share a pause are one region.
- `check_patch` says whether a recorded patch can be used: it was transcribed well enough, its
  first and last words were heard, it leaves a short silence before and after, and at every scene
  change inside it the pause is long enough and both words next to it were heard.
- `splice_items`, `splice_pieces` and `spliced_length` plan the splice: which samples of the full
  recording are kept, which samples of each patch replace the rest, and how long the result is.
  Each join is a crossfade of `fade_samples`, which takes that many samples off the length.
- `carry_decisions` moves the owner's decisions on the boundaries outside the regions from the
  old version of the recording to the new one.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.services import recording_boundaries
from app.services.recording_boundaries import (
    Boundary,
    BoundaryDecision,
    BoundaryError,
    BoundaryKey,
    SceneSpan,
)

# "One line": the nearest pause on each side that is at least this many words from the boundary
# and, first, at most NEAR_SIDE_WORDS away; then up to FAR_SIDE_WORDS; then the end of the file.
MIN_SIDE_WORDS: Final = 4
NEAR_SIDE_WORDS: Final = 15
FAR_SIDE_WORDS: Final = 40
# How many words of the text around the region the person is shown.
CONTEXT_WORDS: Final = 12
# The gain that matches a patch to the recording around it is never larger than this, in dB.
MAX_GAIN_DB: Final = 12.0
# The loudness around a region is measured from this many seconds before it to this many after.
LOUDNESS_SPAN_S: Final = 10.0

SOURCE_PARAKEET: Final = "parakeet"


@dataclass(frozen=True)
class RegionBoundary:
    """A scene change inside a region. `local_index` is the position, in the region's words, of
    the last word of the scene before it.
    """

    after_scene_id: str
    before_scene_id: str
    local_index: int
    tight: bool


@dataclass(frozen=True)
class PatchRegion:
    """The stretch of a full recording a patch replaces."""

    # Positions (from 0, both included) in the recording's timed words.
    first_word: int
    last_word: int
    # The stretch replaced, in seconds: from the middle of the pause before the first word to the
    # middle of the pause after the last (the start or the end of the file at its edges).
    join_start_s: float
    join_end_s: float
    # The silence the recording has between `join_start_s` and the first word, and between the
    # last word and `join_end_s`: the patch keeps as much of its own.
    lead_s: float
    trail_s: float
    at_start: bool
    at_end: bool
    words: list[str]
    # The text of the region cut at its scene changes: one part for each scene (or part of one).
    parts: list[str]
    boundaries: list[RegionBoundary]
    before_context: str
    after_context: str

    @property
    def text(self) -> str:
        return " ".join(self.words)

    @property
    def key(self) -> tuple[int, int]:
        return (self.first_word, self.last_word)

    def tight_keys(self) -> list[BoundaryKey]:
        return [(item.after_scene_id, item.before_scene_id) for item in self.boundaries]


def region_json(region: PatchRegion) -> dict[str, Any]:
    """What a patch's `voice_recording.inputs.region` holds."""
    return {
        "first_word": region.first_word,
        "last_word": region.last_word,
        "join_start_s": region.join_start_s,
        "join_end_s": region.join_end_s,
        "lead_s": region.lead_s,
        "trail_s": region.trail_s,
        "boundaries": [
            {
                "after_scene_id": item.after_scene_id,
                "before_scene_id": item.before_scene_id,
                "local_index": item.local_index,
            }
            for item in region.boundaries
        ],
    }


# --- Regions --------------------------------------------------------------------------------


def _heard(word: dict[str, Any]) -> bool:
    return word.get("heard") is True


def _pause_after(words: Sequence[dict[str, Any]], index: int, pause_s: float) -> bool:
    """Whether the gap between word `index` and the next one is a pause: at least `pause_s`, and
    both words were heard (a time that was filled in is not known to be silence).
    """
    if index < 0 or index + 1 >= len(words):
        return False
    before, after = words[index], words[index + 1]
    if not (_heard(before) and _heard(after)):
        return False
    return float(after["start"]) - float(before["end"]) >= pause_s


def _first_word_for(words: Sequence[dict[str, Any]], last_before: int, pause_s: float) -> int:
    """The first word of the region on the left of a boundary whose scene before ends with word
    `last_before`: just after the nearest suitable pause, else the first word of the file.
    """
    for limit in (NEAR_SIDE_WORDS, FAR_SIDE_WORDS):
        lowest = max(0, last_before - limit)
        for gap in range(last_before - MIN_SIDE_WORDS, lowest - 1, -1):
            if _pause_after(words, gap, pause_s):
                return gap + 1
    return 0


def _last_word_for(words: Sequence[dict[str, Any]], last_before: int, pause_s: float) -> int:
    """The last word of the region on the right of a boundary: just before the nearest suitable
    pause after the scene's first word, else the last word of the file.
    """
    for limit in (NEAR_SIDE_WORDS, FAR_SIDE_WORDS):
        highest = min(len(words) - 2, last_before + limit)
        for gap in range(last_before + MIN_SIDE_WORDS, highest + 1):
            if _pause_after(words, gap, pause_s):
                return gap
    return len(words) - 1


def _make_region(
    spans: Sequence[SceneSpan],
    words: Sequence[dict[str, Any]],
    boundaries: Sequence[Boundary],
    first_word: int,
    last_word: int,
    duration_s: float,
) -> PatchRegion:
    at_start = first_word == 0
    at_end = last_word == len(words) - 1
    first_start = float(words[first_word]["start"])
    last_end = float(words[last_word]["end"])
    if at_start:
        join_start = 0.0
    else:
        previous_end = float(words[first_word - 1]["end"])
        join_start = (previous_end + first_start) / 2
    if at_end:
        join_end = max(last_end, duration_s)
    else:
        next_start = float(words[last_word + 1]["start"])
        join_end = (last_end + next_start) / 2

    inside: list[RegionBoundary] = []
    for index, boundary in enumerate(boundaries):
        last_before = spans[index].last_word
        if first_word <= last_before and last_before + 1 <= last_word:
            inside.append(
                RegionBoundary(
                    after_scene_id=boundary.after_scene_id,
                    before_scene_id=boundary.before_scene_id,
                    local_index=last_before - first_word,
                    tight=boundary.tight,
                )
            )
    texts = [str(word["text"]) for word in words[first_word : last_word + 1]]
    parts: list[str] = []
    start = 0
    for item in inside:
        parts.append(" ".join(texts[start : item.local_index + 1]))
        start = item.local_index + 1
    parts.append(" ".join(texts[start:]))
    return PatchRegion(
        first_word=first_word,
        last_word=last_word,
        join_start_s=round(join_start, 3),
        join_end_s=round(join_end, 3),
        lead_s=round(max(0.0, first_start - join_start), 3),
        trail_s=round(max(0.0, join_end - last_end), 3),
        at_start=at_start,
        at_end=at_end,
        words=texts,
        parts=parts,
        boundaries=inside,
        before_context=" ".join(
            str(word["text"]) for word in words[max(0, first_word - CONTEXT_WORDS) : first_word]
        ),
        after_context=" ".join(
            str(word["text"]) for word in words[last_word + 1 : last_word + 1 + CONTEXT_WORDS]
        ),
    )


def regions(
    spans: Sequence[SceneSpan],
    words: Sequence[dict[str, Any]],
    boundaries: Sequence[Boundary],
    pause_s: float,
    duration_s: float,
) -> list[PatchRegion]:
    """The regions to patch the tight boundaries, in order of position. `boundaries[i]` is
    between `spans[i]` and `spans[i + 1]`. Two regions that overlap, or that share the pause
    between them, are one region, so a stretch is recorded once. `duration_s` is the length of the
    recording, where a region that runs to its end stops.
    """
    ranges: list[tuple[int, int]] = []
    for index, boundary in enumerate(boundaries):
        if not boundary.tight:
            continue
        last_before = spans[index].last_word
        ranges.append(
            (
                _first_word_for(words, last_before, pause_s),
                _last_word_for(words, last_before, pause_s),
            )
        )
    ranges.sort()
    merged: list[tuple[int, int]] = []
    for first, last in ranges:
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))
    return [
        _make_region(spans, words, boundaries, first, last, duration_s) for first, last in merged
    ]


# --- Checking a patch -----------------------------------------------------------------------

TOO_SHORT_PAUSE: Final = (
    "The pause at the scene change is too short. Record it again with a clear pause."
)
NEEDS_SILENCE: Final = (
    "Leave a short pause before the first word and after the last word. Record it again."
)


def check_patch(
    region: PatchRegion,
    patch_words: Sequence[dict[str, Any]],
    *,
    source: str,
    match_percent: float,
    threshold: int,
    patch_duration_s: float,
    min_pause_s: float,
    margin_s: float,
) -> list[str]:
    """Why a recorded patch cannot be used: one sentence for each reason, empty when it can.
    `patch_words` are the patch's timed words (with the `heard` flag).
    """
    if source != SOURCE_PARAKEET:
        return [
            f"The recording matched only {match_percent:g}% of the text ({threshold}% needed). "
            "Record it again."
        ]
    if len(patch_words) != len(region.words) or not patch_words:
        return ["The recording does not hold the words of this part. Record it again."]
    reasons: list[str] = []
    first, last = patch_words[0], patch_words[-1]
    if not _heard(first):
        reasons.append(f"The first word, '{first['text']}', was not heard. Start with that word.")
    if not _heard(last):
        reasons.append(f"The last word, '{last['text']}', was not heard. End with that word.")
    # A join is a short crossfade inside the silence kept before the first word and after the
    # last: without that silence the fade would reach into a word.
    if (
        _heard(first)
        and _heard(last)
        and (
            (not region.at_start and float(first["start"]) < margin_s)
            or (not region.at_end and patch_duration_s - float(last["end"]) < margin_s)
        )
    ):
        reasons.append(NEEDS_SILENCE)
    for item in region.boundaries:
        before, after = patch_words[item.local_index], patch_words[item.local_index + 1]
        if not (_heard(before) and _heard(after)):
            reasons.append(
                f"The words at the scene change, '{before['text']}' and '{after['text']}', "
                "were not heard. Record it again."
            )
        elif float(after["start"]) - float(before["end"]) < min_pause_s:
            reasons.append(TOO_SHORT_PAUSE)
    return reasons


def patch_window_s(
    region: PatchRegion, patch_words: Sequence[dict[str, Any]], patch_duration_s: float
) -> tuple[float, float]:
    """The part of a patch that is used, in seconds: from the silence the region had before its
    first word to the silence it had after its last, as far as the patch has them.
    """
    start = max(0.0, float(patch_words[0]["start"]) - region.lead_s)
    end = min(patch_duration_s, float(patch_words[-1]["end"]) + region.trail_s)
    return start, end


# --- The splice -----------------------------------------------------------------------------


@dataclass(frozen=True)
class SpliceItem:
    """One patch in a splice. `base_start`/`base_end` are the samples of the full recording that
    are replaced; `patch_start`/`patch_end` the samples of the patch that replace them.
    """

    patch_id: int
    base_start: int
    base_end: int
    patch_start: int
    patch_end: int
    gain_db: float


@dataclass(frozen=True)
class Piece:
    """A stretch of the result: `source` is 0 for the full recording or the patch's number
    (from 1) in the list of patches.
    """

    source: int
    start: int
    end: int
    gain_db: float

    @property
    def length(self) -> int:
        return self.end - self.start


def to_sample(seconds: float, sample_rate: int, total_samples: int) -> int:
    return min(max(0, round(seconds * sample_rate)), total_samples)


def splice_pieces(
    total_samples: int, items: Sequence[SpliceItem], fade_samples: int
) -> list[Piece]:
    """The stretches that make the new recording, in order: the full recording up to the first
    replaced stretch, the first patch, the recording up to the next, and so on. `items` are in
    order and replace separate stretches. Raises BoundaryError when they do not, or when a stretch
    is too short to hold the fades at its two ends.
    """
    pieces: list[Piece] = []
    position = 0
    for number, item in enumerate(items, start=1):
        # Two patches have a stretch of the recording between them, so every join is a patch
        # against the recording.
        if (
            item.base_start < position
            or item.base_end < item.base_start
            or (number > 1 and item.base_start == position)
        ):
            raise BoundaryError("The parts to replace overlap or are out of order.")
        if item.base_end > total_samples:
            raise BoundaryError("A part to replace is outside the recording.")
        if item.base_start > position:
            pieces.append(Piece(0, position, item.base_start, 0.0))
        pieces.append(Piece(number, item.patch_start, item.patch_end, item.gain_db))
        position = item.base_end
    if position < total_samples:
        pieces.append(Piece(0, position, total_samples, 0.0))
    if not pieces:
        raise BoundaryError("There is nothing to splice.")
    for piece in pieces:
        if piece.length < 2 * fade_samples + 1:
            raise BoundaryError("A stretch of the recording is too short to be joined.")
    return pieces


def spliced_length(pieces: Sequence[Piece], fade_samples: int) -> int:
    """The length of the result in samples: the pieces end to end, less the samples each join's
    crossfade takes.
    """
    return sum(piece.length for piece in pieces) - fade_samples * (len(pieces) - 1)


def delta_samples(item: SpliceItem, fade_samples: int, joins: int) -> int:
    """By how much one patch changes the length: what it adds less what it replaces, less the
    crossfade of each of its `joins` (0, 1 or 2) joins.
    """
    return (
        (item.patch_end - item.patch_start)
        - (item.base_end - item.base_start)
        - (fade_samples * joins)
    )


def gain_db(base_lufs: float | None, patch_lufs: float | None) -> float:
    """The gain that brings a patch to the loudness of the recording around it, within
    `MAX_GAIN_DB`. 0 when either could not be measured.
    """
    if base_lufs is None or patch_lufs is None:
        return 0.0
    return round(max(-MAX_GAIN_DB, min(MAX_GAIN_DB, base_lufs - patch_lufs)), 2)


# --- Carrying decisions ---------------------------------------------------------------------


@dataclass(frozen=True)
class ReplacedStretch:
    """What a patch changed in the old version, for moving the decisions after it."""

    # Seconds, in the old version, where the replaced stretch ends.
    end_s: float
    # By how much the new version is longer after it, in seconds (negative when shorter).
    delta_s: float
    # The scene changes inside it: their decisions are not carried.
    keys: frozenset[BoundaryKey]


def carry_decisions(
    old: Mapping[BoundaryKey, BoundaryDecision],
    new_boundaries: Sequence[Boundary],
    stretches: Sequence[ReplacedStretch],
) -> dict[BoundaryKey, BoundaryDecision]:
    """The owner's decisions on the old version that still apply to the new one. A decision on a
    scene change inside a replaced stretch is not carried, and neither is one on a boundary that
    is not tight in the new version. The cut point of a `cut_at` decision moves by the change of
    length of every stretch before it, and is dropped when it is no longer allowed.
    """
    inside = {key for stretch in stretches for key in stretch.keys}
    carried: dict[BoundaryKey, BoundaryDecision] = {}
    tight = {recording_boundaries.key_of(item) for item in new_boundaries if item.tight}
    for key, decision in old.items():
        if key in inside or key not in tight:
            continue
        if decision.decision == recording_boundaries.DECISION_CUT_AT:
            if decision.cut_s is None or not math.isfinite(decision.cut_s):
                continue
            shift = sum(item.delta_s for item in stretches if item.end_s <= decision.cut_s)
            carried[key] = BoundaryDecision(decision.decision, round(decision.cut_s + shift, 3))
        else:
            carried[key] = BoundaryDecision(decision.decision, None)
    # A cut that is no longer inside its window, or out of order, is dropped: that boundary is
    # decided again.
    for index, boundary in enumerate(new_boundaries):
        decided = carried.get(recording_boundaries.key_of(boundary))
        if decided is None or decided.decision != recording_boundaries.DECISION_CUT_AT:
            continue
        try:
            recording_boundaries.check_cut(
                new_boundaries, index, decided.cut_s or 0.0, carried, check_window=True
            )
        except BoundaryError:
            del carried[recording_boundaries.key_of(boundary)]
    return carried
