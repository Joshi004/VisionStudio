"""Where graphic overlays go (OVL-003, `Graphic_overlays_implementation_phases.md` section 4.2).

A graphic overlay is a graphic the owner asked for (a graphic suggestion), laid full screen over
the shots under the words it covers. The shot plan is not touched: code decides, on read, from the
suggestions and the timeline of a scene whose plan is current.

Pure: no I/O, no clock. Times are seconds on the scene's timeline (`scene_timeline`), the same
numbers as `ShotSpan.start_s` and `end_s`.

**Rules** (`place_overlays`):

- One overlay for each run of words of a suggestion in a scene (`runs`). A sound bite's words are
  taken out of a suggestion (OV-5), so a suggestion it cuts into pieces gives one overlay for each.
- A run starts in the middle of the pause before its first word and ends in the middle of the pause
  after its last word (the caller works these out the way the cut planner places a cut).
- It is cut short where a sound bite shot starts and starts after one that is on screen: no
  overlay is ever drawn over a sound bite shot.
- It is at least `MIN_S` long. A shorter one runs on after its last word, up to the next overlay or
  sound bite shot or the end of the scene, and then starts up to `MAX_LEAD_S` earlier. With no
  room it is not placed.
- It is at most `MAX_FRAMES` frames long, counted as its graphic is drawn (`clip_frames`: its
  frames plus one spare frame, like a graphic shot). A longer one is not placed: the owner splits
  it.
- Two overlays never overlap, and a lengthened one ends `GAP_S` before the next one starts.
- The key of an overlay is `{scene_id}/{first}-{last}`: the first and last word in the scene's
  take, counted from 1. Never the suggestion's `g` number, which is renumbered when suggestions
  are added or removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.services import evidence_cards, graphic_suggestions
from app.services.frame_counts import target_frames

# An overlay is on screen for at least this long, like a graphic shot
# (`cut_planning_writer.SHORTEST_GRAPHIC_S`).
MIN_S: Final = 3.0
# The most frames and the frame rate of a graphic the motion service draws
# (`shot_graphics.MAX_FRAMES`, `graphics_lab.FPS`): 30 s.
MAX_FRAMES: Final = 720
FPS: Final = 24
# The spare frame a drawn clip has (`scene_timeline._GRAPHIC_SPARE_FRAMES`).
SPARE_FRAMES: Final = 1
# A short overlay may start up to this long before its natural start, when it has no room after.
MAX_LEAD_S: Final = 1.0
# A lengthened overlay ends this long before the next one starts (`evidence_cards.GAP_S`).
GAP_S: Final = evidence_cards.GAP_S

NO_ROOM: Final = "no_room"
TOO_LONG: Final = "too_long"
SOUNDBITE: Final = "soundbite"
ONE_WORD: Final = "one_word"
UNPLACED_TEXT: Final = {
    NO_ROOM: (
        "There is less than 3 seconds of room for this graphic before the next graphic or "
        "sound bite, or before the end of the scene."
    ),
    TOO_LONG: (
        "These words take about 30 seconds or more to say: split the suggestion into shorter ones."
    ),
    SOUNDBITE: graphic_suggestions.SOUNDBITE_REASON,
    ONE_WORD: (
        "Only one word of this suggestion is left beside a sound bite, so it gets no graphic."
    ),
}

_DECIMALS: Final = 3
# Float noise allowed when a length is compared with `MIN_S`.
_EPSILON: Final = 1e-6


@dataclass(frozen=True)
class Wanted:
    """One run of words to place: `first_word` to `last_word` of the scene's take (counted from
    1), with the natural times in the scene: the middle of the pause before the first word and of
    the pause after the last."""

    scene_id: str
    suggestion_id: str
    text: str
    first_word: int
    last_word: int
    start_s: float
    end_s: float

    @property
    def overlay_id(self) -> str:
        return f"{self.first_word}-{self.last_word}"

    @property
    def key(self) -> str:
        return f"{self.scene_id}/{self.overlay_id}"


@dataclass(frozen=True)
class Overlay:
    """One placed overlay, from `start_s` to `end_s`, over the shots in `shot_ids` (never a sound
    bite shot)."""

    scene_id: str
    suggestion_id: str
    text: str
    first_word: int
    last_word: int
    start_s: float
    end_s: float
    shot_ids: tuple[str, ...]

    @property
    def overlay_id(self) -> str:
        return f"{self.first_word}-{self.last_word}"

    @property
    def key(self) -> str:
        return f"{self.scene_id}/{self.overlay_id}"

    @property
    def length_s(self) -> float:
        return round(self.end_s - self.start_s, _DECIMALS)


@dataclass(frozen=True)
class Unplaced:
    """Words the owner suggested a graphic for that got none, and why. `key` is None when no run
    of words was left to give a key (every word is a sound bite)."""

    scene_id: str
    suggestion_id: str
    text: str
    key: str | None
    code: str

    @property
    def message(self) -> str:
        return UNPLACED_TEXT[self.code]


@dataclass(frozen=True)
class Placement:
    overlays: tuple[Overlay, ...]
    unplaced: tuple[Unplaced, ...]


def _r(value: float) -> float:
    return round(value, _DECIMALS)


def clip_frames(start_s: float, end_s: float) -> int:
    """The frames of the graphic drawn for an overlay from `start_s` to `end_s`: its frames on the
    24 fps grid plus one spare frame, the same count a graphic shot gets
    (`scene_timeline.ShotSpan.clip_frames`). Pure."""
    return target_frames(start_s, end_s, FPS) + SPARE_FRAMES


def runs(words: list[int], soundbite_words: set[int]) -> list[tuple[int, int]]:
    """The unbroken runs of `words` (positions in the take, from 0, in order) as `(first, last)`.
    A run is broken only where a sound bite's word lies between two neighbours; a position that
    is simply missing from `words` (a word of the take the story text did not match) is bridged.
    """
    found: list[tuple[int, int]] = []
    for position in sorted(words):
        if position in soundbite_words:
            continue
        if found and not any(
            between in soundbite_words for between in range(found[-1][1] + 1, position)
        ):
            found[-1] = (found[-1][0], position)
        else:
            found.append((position, position))
    return found


def _bites(slots: list[evidence_cards.Slot]) -> list[tuple[float, float]]:
    return sorted(
        (slot.start_s, slot.end_s) for slot in slots if slot.type == evidence_cards.SOUNDBITE
    )


def _unplaced(wanted: Wanted, code: str) -> Unplaced:
    return Unplaced(wanted.scene_id, wanted.suggestion_id, wanted.text, wanted.key, code)


def place_overlays(
    wanted: list[Wanted], slots: list[evidence_cards.Slot], total_s: float
) -> Placement:
    """The overlays of one scene, in time order. Pure."""
    bites = _bites(slots)
    ordered = sorted(wanted, key=lambda run: (run.start_s, run.first_word))
    overlays: list[Overlay] = []
    unplaced: list[Unplaced] = []
    previous_end: float | None = None
    for index, run in enumerate(ordered):
        start = run.start_s
        end = min(run.end_s, total_s)
        for bite_start, bite_end in bites:
            if bite_start <= start < bite_end:
                start = bite_end  # no overlay over a sound bite shot
        later_bites = [bite_start for bite_start, _ in bites if bite_start > start]
        if later_bites and later_bites[0] < end:
            end = later_bites[0]
        if end - start <= 0:
            unplaced.append(_unplaced(run, NO_ROOM))
            continue
        if clip_frames(start, end) > MAX_FRAMES:
            unplaced.append(_unplaced(run, TOO_LONG))
            continue
        if end - start < MIN_S - _EPSILON:
            limits = [total_s]
            if index + 1 < len(ordered):
                limits.append(ordered[index + 1].start_s - GAP_S)
            if later_bites:
                limits.append(later_bites[0] - GAP_S)
            end = max(end, min(start + MIN_S, *limits))
        if end - start < MIN_S - _EPSILON:
            floors = [0.0, start - MAX_LEAD_S]
            if previous_end is not None:
                floors.append(previous_end + GAP_S)
            floors.extend(bite_end for _, bite_end in bites if bite_end <= start)
            start = max(max(floors), end - MIN_S)
        if end - start < MIN_S - _EPSILON:
            unplaced.append(_unplaced(run, NO_ROOM))
            continue
        start, end = _r(start), _r(end)
        if clip_frames(start, end) > MAX_FRAMES:
            unplaced.append(_unplaced(run, TOO_LONG))
            continue
        overlays.append(
            Overlay(
                scene_id=run.scene_id,
                suggestion_id=run.suggestion_id,
                text=run.text,
                first_word=run.first_word,
                last_word=run.last_word,
                start_s=start,
                end_s=end,
                shot_ids=tuple(
                    slot.shot_id
                    for slot in slots
                    if slot.type != evidence_cards.SOUNDBITE
                    and slot.start_s < end
                    and slot.end_s > start
                ),
            )
        )
        previous_end = end
    return Placement(overlays=tuple(overlays), unplaced=tuple(unplaced))
