"""The split evidence shot: an evidence shot that shares the screen with a callout (EVD-016,
`Evidence_layer_implementation_phases.md` §4.7).

Pure functions, no I/O, no clock.

**When a shot is split** (`split_shots`). A callout is on screen only where a graphic or an
evidence shot is not (EVD-009), so a callout that starts inside an evidence shot used to be left
out. Now the shot is drawn **split** and the callout is kept. A shot is split when a callout
starts inside it, can stay up for at least `min_visible_ms` before the shot ends, and is not a
section title (a title fills the screen, so it is still left out). The times are those
`callout_render` places the callout at (`callout_render.timing_of`), on the scene's timeline.

**Where the two panels are** (`panels`). The picture's orientation decides:

- portrait: the callout panel is the top `PORTRAIT_CALLOUT_SHARE` of the frame and the evidence
  the rest below it (30 % / 70 %);
- landscape: the evidence panel is the left half and the callout panel the right half (50 / 50),
  like two portraits side by side.

**Where the callout goes** (`callout_zone`). The zone a callout fills inside its panel. In
landscape it has the size of the zone beside the presenter that callouts already have, so a
graphic checked there fits; in portrait it is the upper part of the callout panel.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

Rect = tuple[int, int, int, int]

# The share of a portrait frame's height the callout panel takes; the evidence panel has the rest.
PORTRAIT_CALLOUT_SHARE: Final = 0.30
# The share a portrait frame's height the graphic takes when it shares the screen with evidence
# (OVL-007); the evidence panel has the rest.
PORTRAIT_GRAPHIC_SHARE: Final = 0.50

# The zone of a callout in its panel, as shares of the frame: `(centre x, width, top, bottom)`.
# Portrait fills the width of the panel above the line between the panels; landscape is the size and
# height of the zone a callout has beside the presenter (`callout_render.zone_box`), centred in
# the right half.
_PORTRAIT_ZONE: Final = (0.5, 0.84, 0.05, 0.28)
_LANDSCAPE_ZONE: Final = (0.75, 0.40, 0.08, 0.40)

EDGE_TOP: Final = "top"
EDGE_RIGHT: Final = "right"

TITLE_KIND: Final = "section_title"


@dataclass(frozen=True)
class Panels:
    """The two panels of a split frame, each `(x, y, width, height)` in pixels with even sizes.
    `edge` is the side of the evidence panel that touches the callout panel."""

    evidence: Rect
    callout: Rect
    edge: str


@dataclass(frozen=True)
class CalloutAt:
    """A callout as `split_shots` reads it: when it starts and, if nothing came after it, ends, in
    milliseconds on the scene's timeline."""

    callout_id: str
    kind: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class ShotAt:
    """An evidence shot of a scene, in milliseconds on the scene's timeline."""

    shot_id: str
    start_ms: int
    end_ms: int


def _even(value: float) -> int:
    return round(value / 2) * 2


def is_portrait(width: int, height: int) -> bool:
    return height > width


def panels(width: int, height: int) -> Panels:
    """The evidence panel and the callout panel of a frame this size. Pure."""
    if is_portrait(width, height):
        top = _even(PORTRAIT_CALLOUT_SHARE * height)
        return Panels(
            evidence=(0, top, width, height - top),
            callout=(0, 0, width, top),
            edge=EDGE_TOP,
        )
    half = _even(width / 2)
    return Panels(
        evidence=(0, 0, half, height),
        callout=(half, 0, width - half, height),
        edge=EDGE_RIGHT,
    )


def graphic_split_panels(width: int, height: int) -> Panels:
    """The panels of a stretch where a graphic overlay and evidence share the screen (OVL-007).
    `evidence` is the evidence panel and `callout` is the graphic's panel. Landscape is the same as
    `panels` (evidence left, graphic right, half each); portrait puts the graphic on top and the
    evidence below, half each. Pure."""
    if is_portrait(width, height):
        top = _even(PORTRAIT_GRAPHIC_SHARE * height)
        return Panels(
            evidence=(0, top, width, height - top),
            callout=(0, 0, width, top),
            edge=EDGE_TOP,
        )
    return panels(width, height)


def callout_zone(width: int, height: int) -> tuple[float, float, float, float]:
    """The zone a callout fills in a split frame: `(centre x, width, top, bottom)` in pixels."""
    centre, zone_width, top, bottom = (
        _PORTRAIT_ZONE if is_portrait(width, height) else _LANDSCAPE_ZONE
    )
    return width * centre, width * zone_width, height * top, height * bottom


def split_shots(
    callouts: Sequence[CalloutAt], shots: Sequence[ShotAt], min_visible_ms: int
) -> dict[str, tuple[str, ...]]:
    """The evidence shots to draw split, each with the callouts that land in it, by shot id. A
    shot that no callout lands in is not here. Pure.
    """
    found: dict[str, list[str]] = {}
    for callout in callouts:
        if callout.kind == TITLE_KIND:
            continue
        for shot in shots:
            if not shot.start_ms <= callout.start_ms < shot.end_ms:
                continue
            if min(callout.end_ms, shot.end_ms) - callout.start_ms >= min_visible_ms:
                found.setdefault(shot.shot_id, []).append(callout.callout_id)
            break
    return {shot_id: tuple(ids) for shot_id, ids in found.items()}
