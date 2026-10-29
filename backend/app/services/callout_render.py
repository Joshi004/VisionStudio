"""The callouts of an explainer render: where and when each one is drawn (EXPLAINER-010,
`Explainer_implementation_phases.md` E-14 to E-19 and §6).

Pure: no I/O, no clock. The text widths come from a `measure` function that is passed in
(`font_metrics.measure` in the app), so this module needs no font.

`story_render_plan.build_plan` gives `resolve` the callouts that are turned on in the current
callout plan (`CalloutSource`), the timed words of every speech and where the shots and the lines
of dialogue are, and gets back the **callout track** that is frozen in the timeline
(`timeline["callouts"]`). The render job reads it back with `parse_track` and
`services/caption_ass.py` writes it into the ASS file, next to the captions.

**When** (`resolve`). A callout is placed where its phrase is spoken: the closest stretch of the
unit's timed words (`callout_plan_writer.locate_phrase`, the same match the plan panel uses). A
phrase that does not match puts the callout at the start of its unit (E-15). Each item of a `list`
and each side of a `comparison` is placed by its own phrase, so they build up as they are spoken
(a list never shows its items out of order). A callout stays up for `MIN_SHOW_MS`, or until its
unit ends, whichever is longer (a section title for `SECTION_TITLE_MS` only, because the captions
are hidden while it shows). It is cut `CUT_BEFORE_NEXT_MS` before the next callout starts. When
that would leave it up for less than `MIN_VISIBLE_MS`, the later callout is dropped instead: the
times the plan was checked with are estimates, and the render never lets two callouts overlap.

**Where** (§6.2). The zone comes from the shot under the callout's start: a shot with a line of
dialogue is a presenter shot. Landscape B-roll has the upper third, centred. A landscape
presenter shot has a narrower box on one side (`PRESENTER_SIDE`). Portrait has one centred upper
area above the captions. A section title is centred.

**Fit.** Each line is measured, so a callout is never wider than its zone and stacked boxes never
overlap: a text is split into at most two balanced lines, then its font size is reduced until it
fits. A list item and a comparison side are one line. libass wrapping is off, and each line is a
part of its own with its own box (libass draws one box per line, and the boxes of lines set close
together would overlap), so the sizes known here are the sizes drawn.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.services.callout_plan_writer import (
    TYPE_COMPARISON,
    TYPE_LIST,
    TYPE_NUMBER,
    TYPE_SECTION_TITLE,
    locate_phrase,
)
from app.services.caption_plan import FONT_NAME, LAYOUT_LANDSCAPE, LAYOUT_PORTRAIT, OUTLINE_COLOUR
from app.services.dialogue_check import normalize_words

Measure = Callable[[str, int], float]

PRESENTER_LEFT: Final = "left"
PRESENTER_RIGHT: Final = "right"
# The side of the picture the presenter's callouts go on in landscape. The other side is where
# the presenter is expected to stand.
PRESENTER_SIDE: Final = PRESENTER_RIGHT

# --- When ------------------------------------------------------------------------------------
MIN_SHOW_MS: Final = 2000
SECTION_TITLE_MS: Final = 2500
CUT_BEFORE_NEXT_MS: Final = 150
# A callout cut shorter than this is not shown: the later callout is dropped instead.
MIN_VISIBLE_MS: Final = 1200
# A list item or a comparison side that would start later than this before the end of the
# callout is moved back, so it is seen for a moment at least.
MIN_PART_MS: Final = 800

# --- Colours (§6.3) --------------------------------------------------------------------------
ROLE_ACCENT: Final = "accent"
ROLE_COLOURS: Final = {
    "number": "#FFB000",
    "negative": "#FF4D4D",
    "positive": "#2ED573",
}
BOX_COLOUR: Final = OUTLINE_COLOUR
# ASS transparency of the box (0 opaque, 255 clear): about 65 percent opaque.
BOX_TRANSPARENCY: Final = 0x59

# --- Animation timings (milliseconds) --------------------------------------------------------
FADE_MS: Final = 200
SLIDE_MS: Final = 250
SLIDE_FRACTION: Final = 0.02
NUMBER_POP_FROM: Final = 80
NUMBER_POP_PEAK: Final = 112
NUMBER_POP_PEAK_MS: Final = 150
NUMBER_POP_END_MS: Final = 280
TITLE_FADE_MS: Final = 300
TITLE_GROW_FROM: Final = 95
TITLE_GROW_MS: Final = 400

# --- Layout (fractions of the output size) ---------------------------------------------------
# The share of a zone's width the text may fill, the rest is margin for any difference between
# the measured and the drawn width.
WIDTH_FILL: Final = 0.95
BORDER_RATIO: Final = 0.22
GAP_RATIO: Final = 0.30
# The gap between the lines of one text, each in its own box.
LINE_GAP_RATIO: Final = 0.12
MIN_FONT_PX: Final = 8
# Side by side is used only while the font needs no more than this share taken off.
MIN_SIDE_BY_SIDE_SCALE: Final = 0.7
COLUMN_GAP: Final = 0.02

_MS_PER_S: Final = 1000
_COLOUR: Final = re.compile(r"#[0-9A-Fa-f]{6}")
_FONT_NAME: Final = re.compile(r"[A-Za-z0-9 ]{1,60}")
_LAYOUTS: Final = (LAYOUT_LANDSCAPE, LAYOUT_PORTRAIT)

CODE_AT_UNIT_START: Final = "callout_at_unit_start"
CODE_DROPPED: Final = "callout_dropped"


class CalloutError(ValueError):
    """A recorded callout track this version cannot read."""


# --- What goes in and what comes out ---------------------------------------------------------


@dataclass(frozen=True)
class CalloutSource:
    """The callout plan a render is made with: the callouts that are turned on, in order, and
    the accent colour.
    """

    plan_id: int
    plan_version: int
    accent: str
    callouts: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class CalloutUnit:
    """One speech of the story on the story's timeline, with the time of each of its script
    words, each `(text, start_s, end_s)` in seconds from the start of its file. `words` is empty
    when the speech has no timing.
    """

    scene_id: str
    unit_id: str
    start_ms: int
    end_ms: int
    words: Sequence[tuple[str, float, float]]


@dataclass(frozen=True)
class CalloutStyle:
    """How the callouts look, in pixels of the output. Frozen in the timeline."""

    layout: str
    play_res_x: int
    play_res_y: int
    font_name: str
    box_colour: str
    box_transparency: int
    fade_ms: int
    slide_ms: int
    slide_px: int


@dataclass(frozen=True)
class CalloutPart:
    """One line of text of a callout, drawn from `start_ms` to the end of its callout. `x` is the
    middle of the line and `y` its top, in pixels.
    """

    text: str
    start_ms: int
    x: int
    y: int
    font_size: int
    border: int
    colour: str


@dataclass(frozen=True)
class CalloutEntry:
    id: str
    type: str
    start_ms: int
    end_ms: int
    on_presenter: bool
    at_unit_start: bool
    parts: tuple[CalloutPart, ...]


@dataclass(frozen=True)
class CalloutTrack:
    style: CalloutStyle
    entries: tuple[CalloutEntry, ...]


@dataclass(frozen=True)
class Resolution:
    track: CalloutTrack
    warnings: list[dict[str, Any]]


def style_for(width: int, height: int) -> CalloutStyle:
    """The callout style of an output size. A taller output is portrait."""
    return CalloutStyle(
        layout=LAYOUT_PORTRAIT if height > width else LAYOUT_LANDSCAPE,
        play_res_x=width,
        play_res_y=height,
        font_name=FONT_NAME,
        box_colour=BOX_COLOUR,
        box_transparency=BOX_TRANSPARENCY,
        fade_ms=FADE_MS,
        slide_ms=SLIDE_MS,
        slide_px=round(height * SLIDE_FRACTION),
    )


def role_colour(role: str, accent: str) -> str:
    """The colour of a role (§6.3): the video's accent, or a fixed one."""
    return accent if role == ROLE_ACCENT else ROLE_COLOURS.get(role, accent)


def windows_hiding_captions(track: CalloutTrack) -> list[tuple[int, int]]:
    """The stretches in which the captions are hidden: while a section title shows."""
    return [
        (entry.start_ms, entry.end_ms)
        for entry in track.entries
        if entry.type == TYPE_SECTION_TITLE
    ]


# --- When ------------------------------------------------------------------------------------


def _ms(seconds: float) -> int:
    return math.floor(seconds * _MS_PER_S + 0.5)


class _Words:
    """A unit's timed script words as the phrase match reads them (`normalize_words`), with the
    word each one came from.
    """

    def __init__(self, unit: CalloutUnit) -> None:
        self.unit = unit
        self.tokens: list[str] = []
        self._owner: list[int] = []
        for index, (text, _start, _end) in enumerate(unit.words):
            for token in normalize_words(text):
                self.tokens.append(token)
                self._owner.append(index)

    def start_of(self, phrase: str) -> int | None:
        """The story time (ms) the phrase is spoken at, or None when it does not match."""
        span = locate_phrase(self.tokens, phrase)
        if span is None:
            return None
        start_s = self.unit.words[self._owner[span[0]]][1]
        return max(self.unit.start_ms, self.unit.start_ms + _ms(start_s))


@dataclass
class _Spec:
    """One piece of a callout before it is placed."""

    text: str
    role: str
    start_ms: int = 0
    matched: bool = True


def _specs(callout: dict[str, Any]) -> list[_Spec]:
    """The pieces a callout shows, each with the phrase it is placed by."""
    if callout["type"] == TYPE_COMPARISON:
        return [_Spec(side["text"], side["role"]) for side in callout["sides"]]
    if callout["type"] == TYPE_LIST:
        return [_Spec(item["text"], callout["role"]) for item in callout["items"]]
    return [_Spec(callout["text"], callout["role"])]


def _phrases(callout: dict[str, Any]) -> list[str]:
    if callout["type"] == TYPE_COMPARISON:
        return [side["phrase"] for side in callout["sides"]]
    if callout["type"] == TYPE_LIST:
        return [item["phrase"] for item in callout["items"]]
    return [callout["phrase"]]


def _label(callout: dict[str, Any]) -> str:
    """How a message names a callout: its first text."""
    specs = _specs(callout)
    return f'"{specs[0].text}"' if specs else str(callout.get("id"))


@dataclass
class _Placed:
    """A callout with its times, before it is laid out."""

    callout: dict[str, Any]
    specs: list[_Spec]
    unit: CalloutUnit
    start_ms: int
    natural_end_ms: int
    at_unit_start: bool = False


def _times(callout: dict[str, Any], words: _Words, total_ms: int) -> _Placed:
    """When a callout starts (and would end if nothing came after it)."""
    unit = words.unit
    specs = _specs(callout)
    for spec, phrase in zip(specs, _phrases(callout), strict=True):
        found = words.start_of(phrase)
        spec.matched = found is not None
        spec.start_ms = found if found is not None else unit.start_ms
    if callout["type"] == TYPE_LIST:
        # The items build up in the order they are written, never earlier than the one before.
        for before, spec in zip(specs, specs[1:], strict=False):
            spec.start_ms = max(spec.start_ms, before.start_ms)
    start = min(spec.start_ms for spec in specs)
    if callout["type"] == TYPE_SECTION_TITLE:
        end = start + SECTION_TITLE_MS
    else:
        end = max(start + MIN_SHOW_MS, unit.end_ms)
    return _Placed(
        callout=callout,
        specs=specs,
        unit=unit,
        start_ms=start,
        natural_end_ms=min(end, total_ms),
        at_unit_start=not all(spec.matched for spec in specs),
    )


# --- Where -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Zone:
    """The area a callout may fill, in pixels: the middle and the width, and the top and bottom."""

    cx: float
    width: float
    top: float
    bottom: float
    # The block is centred between `top` and `bottom` instead of starting at the top.
    centred: bool = False


def _zone(kind: str, on_presenter: bool, layout: str, width: int, height: int) -> _Zone:
    if kind == TYPE_SECTION_TITLE:
        share = 0.84 if layout == LAYOUT_PORTRAIT else 0.70
        return _Zone(width / 2, width * share, height * 0.25, height * 0.75, centred=True)
    if layout == LAYOUT_PORTRAIT:
        return _Zone(width / 2, width * 0.84, height * 0.12, height * 0.55)
    if on_presenter:
        cx = width * (0.74 if PRESENTER_SIDE == PRESENTER_RIGHT else 0.26)
        return _Zone(cx, width * 0.40, height * 0.08, height * 0.40)
    return _Zone(width / 2, width * 0.70, height * 0.08, height * 0.40)


def _nominal_size(kind: str, layout: str, height: int) -> int:
    portrait = layout == LAYOUT_PORTRAIT
    if kind == TYPE_NUMBER:
        share = 0.055 if portrait else 0.09
    elif kind == TYPE_SECTION_TITLE:
        share = 0.045 if portrait else 0.08
    else:
        share = 0.032 if portrait else 0.055
    return round(height * share)


def _border(size: int) -> int:
    return max(2, round(size * BORDER_RATIO))


def _balanced_split(text: str, size: int, measure: Measure) -> tuple[float, str, str] | None:
    """The text as two lines of about the same width: `(width of the wider, first, second)`."""
    words = text.split()
    best: tuple[float, str, str] | None = None
    for place in range(1, len(words)):
        first, second = " ".join(words[:place]), " ".join(words[place:])
        widest = max(measure(first, size), measure(second, size))
        if best is None or widest < best[0]:
            best = (widest, first, second)
    return best


def _fit(
    text: str, nominal: int, available: float, max_lines: int, measure: Measure
) -> tuple[tuple[str, ...], float]:
    """The lines of a text and the share of the nominal font size (at most 1) that makes the
    widest line fit `available` pixels. Two lines are used only when one line is too wide.
    """
    width = measure(text, nominal)
    one = min(1.0, available / width) if width > 0 else 1.0
    if one >= 1.0 or max_lines < 2:
        return (text,), one
    split = _balanced_split(text, nominal, measure)
    if split is not None:
        two = min(1.0, available / split[0]) if split[0] > 0 else 1.0
        if two > one:
            return (split[1], split[2]), two
    return (text,), one


@dataclass(frozen=True)
class _Box:
    """One line of text with its own box. `y` is the top of the text; the box reaches `border`
    pixels above it and below the line.
    """

    text: str
    x: int
    y: int
    size: int
    border: int


def _line_gap(size: int) -> int:
    return round(size * LINE_GAP_RATIO)


def _block_height(lines: int, size: int) -> int:
    """The height of a text of `lines` lines, each in its own box."""
    return lines * (size + 2 * _border(size)) + (lines - 1) * _line_gap(size)


def _place(
    texts: Sequence[str],
    zone: _Zone,
    nominal: int,
    *,
    max_lines: int,
    side_by_side: bool,
    pop: float,
    width: int,
    measure: Measure,
) -> list[list[_Box]]:
    """Where each line of each text goes and how big it is: a list of lines per text. The texts
    share one font size. They stand in one column from the top of the zone (or centred in it),
    or, with `side_by_side`, in two columns. A line is drawn in a box of its own, so the lines
    of a text are kept apart by `LINE_GAP_RATIO` and never overlap.
    """
    gap_x = width * COLUMN_GAP
    column = (zone.width - gap_x) / 2 if side_by_side else zone.width
    available = column * WIDTH_FILL - 2 * _border(nominal)
    available /= pop
    fits = [_fit(text, nominal, available, max_lines, measure) for text in texts]
    size = max(MIN_FONT_PX, int(nominal * min(scale for _lines, scale in fits)))

    def total_height(font: int) -> int:
        gap = round(font * GAP_RATIO)
        return sum(_block_height(len(lines), font) for lines, _scale in fits) + gap * (
            len(texts) - 1
        )

    def boxes_at(cx: float, top: float, lines: tuple[str, ...], font: int) -> list[_Box]:
        boxes: list[_Box] = []
        for line in lines:
            boxes.append(_Box(line, round(cx), round(top) + _border(font), font, _border(font)))
            top += font + 2 * _border(font) + _line_gap(font)
        return boxes

    if side_by_side:
        left = zone.cx - zone.width / 2 + column / 2
        right = zone.cx + zone.width / 2 - column / 2
        return [
            boxes_at(cx, zone.top, lines, size)
            for (lines, _scale), cx in zip(fits, (left, right), strict=True)
        ]

    room = zone.bottom - zone.top
    if total_height(size) > room:
        size = max(MIN_FONT_PX, int(size * room / total_height(size)))
    top = (zone.top + zone.bottom) / 2 - total_height(size) / 2 if zone.centred else zone.top
    placed: list[list[_Box]] = []
    for lines, _scale in fits:
        placed.append(boxes_at(zone.cx, top, lines, size))
        top += _block_height(len(lines), size) + round(size * GAP_RATIO)
    return placed


def _layout(
    placed: _Placed,
    style: CalloutStyle,
    on_presenter: bool,
    accent: str,
    measure: Measure,
) -> tuple[CalloutPart, ...]:
    """The parts of a callout, with their places and sizes: one part for each line of text."""
    kind = placed.callout["type"]
    width, height = style.play_res_x, style.play_res_y
    zone = _zone(kind, on_presenter, style.layout, width, height)
    nominal = _nominal_size(kind, style.layout, height)
    texts = [spec.text for spec in placed.specs]
    several = len(texts) > 1
    max_lines = 1 if several or kind == TYPE_NUMBER else 2
    pop = NUMBER_POP_PEAK / 100 if kind == TYPE_NUMBER else 1.0

    def place(side_by_side: bool) -> list[list[_Box]]:
        return _place(
            texts,
            zone,
            nominal,
            max_lines=max_lines,
            side_by_side=side_by_side,
            pop=pop,
            width=width,
            measure=measure,
        )

    boxes = place(False)
    if kind == TYPE_COMPARISON and style.layout == LAYOUT_LANDSCAPE:
        beside = place(True)
        if beside[0][0].size >= nominal * MIN_SIDE_BY_SIDE_SCALE:
            boxes = beside
    return tuple(
        CalloutPart(
            text=box.text,
            start_ms=spec.start_ms,
            x=box.x,
            y=box.y,
            font_size=box.size,
            border=box.border,
            colour=role_colour(spec.role, accent),
        )
        for lines, spec in zip(boxes, placed.specs, strict=True)
        for box in lines
    )


def _on_presenter(
    start_ms: int,
    shots: Sequence[tuple[int, int]],
    dialogue: Sequence[tuple[int, int]],
) -> bool:
    """Whether the shot under `start_ms` has a line of dialogue: the presenter is on camera."""
    for shot_start, shot_end in shots:
        if shot_start <= start_ms < shot_end:
            return any(
                min(shot_end, line_end) - max(shot_start, line_start) > _MS_PER_S // 20
                for line_start, line_end in dialogue
            )
    return False


# --- Resolving -------------------------------------------------------------------------------


def _named(labels: list[str]) -> str:
    shown = ", ".join(labels[:5])
    return shown if len(labels) <= 5 else f"{shown} and {len(labels) - 5} more"


def resolve(
    source: CalloutSource,
    units: Sequence[CalloutUnit],
    shots: Sequence[tuple[int, int]],
    dialogue: Sequence[tuple[int, int]],
    total_ms: int,
    width: int,
    height: int,
    measure: Measure,
) -> Resolution:
    """The callout track of a render, and its warnings. `shots` and `dialogue` are
    `(start_ms, end_ms)` spans on the story's timeline, and `total_ms` is the length of the video.
    """
    style = style_for(width, height)
    by_ref = {(unit.scene_id, unit.unit_id): _Words(unit) for unit in units}

    candidates: list[_Placed] = []
    lost: list[str] = []
    for callout in source.callouts:
        words = by_ref.get((callout["scene_id"], callout["unit_id"]))
        if words is None:
            lost.append(_label(callout))
            continue
        placed = _times(callout, words, total_ms)
        if placed.start_ms >= total_ms:
            lost.append(_label(callout))
            continue
        candidates.append(placed)
    candidates.sort(key=lambda item: item.start_ms)

    kept: list[_Placed] = []
    for placed in candidates:
        if kept:
            previous = kept[-1]
            cut = placed.start_ms - CUT_BEFORE_NEXT_MS
            if previous.natural_end_ms > cut:
                if cut - previous.start_ms < MIN_VISIBLE_MS:
                    lost.append(_label(placed.callout))
                    continue
                previous.natural_end_ms = cut
        kept.append(placed)

    entries: list[CalloutEntry] = []
    guessed: list[str] = []
    for placed in kept:
        end = placed.natural_end_ms
        if end - placed.start_ms < MIN_VISIBLE_MS:
            lost.append(_label(placed.callout))
            continue
        for spec in placed.specs:
            spec.start_ms = min(spec.start_ms, end - MIN_PART_MS)
        on_presenter = _on_presenter(placed.start_ms, shots, dialogue)
        parts = _layout(placed, style, on_presenter, source.accent, measure)
        if placed.at_unit_start:
            guessed.append(_label(placed.callout))
        entries.append(
            CalloutEntry(
                id=str(placed.callout["id"]),
                type=str(placed.callout["type"]),
                start_ms=placed.start_ms,
                end_ms=end,
                on_presenter=on_presenter,
                at_unit_start=placed.at_unit_start,
                parts=parts,
            )
        )

    warnings: list[dict[str, Any]] = []
    if guessed:
        warnings.append(
            {
                "code": CODE_AT_UNIT_START,
                "message": "The phrase of these callouts was not found in the speech, so they "
                f"show where their line starts: {_named(guessed)}.",
            }
        )
    if lost:
        warnings.append(
            {
                "code": CODE_DROPPED,
                "message": "These callouts are left out because they would overlap another "
                f"callout, or have no place in the video: {_named(lost)}.",
            }
        )
    return Resolution(CalloutTrack(style, tuple(entries)), warnings)


# --- Recording and reading back --------------------------------------------------------------


def track_dict(track: CalloutTrack) -> dict[str, Any]:
    """The callout track as it is frozen in the timeline (JSON)."""
    style = track.style
    return {
        "style": {
            "layout": style.layout,
            "play_res_x": style.play_res_x,
            "play_res_y": style.play_res_y,
            "font_name": style.font_name,
            "box_colour": style.box_colour,
            "box_transparency": style.box_transparency,
            "fade_ms": style.fade_ms,
            "slide_ms": style.slide_ms,
            "slide_px": style.slide_px,
        },
        "entries": [
            {
                "id": entry.id,
                "type": entry.type,
                "start_ms": entry.start_ms,
                "end_ms": entry.end_ms,
                "on_presenter": entry.on_presenter,
                "at_unit_start": entry.at_unit_start,
                "parts": [
                    {
                        "text": part.text,
                        "start_ms": part.start_ms,
                        "x": part.x,
                        "y": part.y,
                        "font_size": part.font_size,
                        "border": part.border,
                        "colour": part.colour,
                    }
                    for part in entry.parts
                ],
            }
            for entry in track.entries
        ],
    }


def _whole(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CalloutError("not a whole number")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise CalloutError("not text")
    return value


def _colour(value: object) -> str:
    text = _text(value)
    if not _COLOUR.fullmatch(text):
        raise CalloutError("not a colour")
    return text


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CalloutError("not an object")
    return value


def _list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise CalloutError("not a list")
    return value


def _style_of(raw: object) -> CalloutStyle:
    data = _object(raw)
    layout, font_name = _text(data.get("layout")), _text(data.get("font_name"))
    style = CalloutStyle(
        layout=layout,
        play_res_x=_whole(data.get("play_res_x")),
        play_res_y=_whole(data.get("play_res_y")),
        font_name=font_name,
        box_colour=_colour(data.get("box_colour")),
        box_transparency=_whole(data.get("box_transparency")),
        fade_ms=_whole(data.get("fade_ms")),
        slide_ms=_whole(data.get("slide_ms")),
        slide_px=_whole(data.get("slide_px")),
    )
    if (
        layout not in _LAYOUTS
        or not _FONT_NAME.fullmatch(font_name)
        or style.play_res_x < 2
        or style.play_res_y < 2
        or not 0 <= style.box_transparency <= 255
        or style.fade_ms < 0
        or style.slide_ms < 0
        or style.slide_px < 0
    ):
        raise CalloutError("bad style")
    return style


def _part_of(raw: object) -> CalloutPart:
    data = _object(raw)
    part = CalloutPart(
        text=_text(data.get("text")),
        start_ms=_whole(data.get("start_ms")),
        x=_whole(data.get("x")),
        y=_whole(data.get("y")),
        font_size=_whole(data.get("font_size")),
        border=_whole(data.get("border")),
        colour=_colour(data.get("colour")),
    )
    if not part.text.strip() or part.start_ms < 0 or part.font_size < 1 or part.border < 0:
        raise CalloutError("bad part")
    return part


def _entry_of(raw: object) -> CalloutEntry:
    data = _object(raw)
    on_presenter, at_unit_start = data.get("on_presenter"), data.get("at_unit_start")
    if not isinstance(on_presenter, bool) or not isinstance(at_unit_start, bool):
        raise CalloutError("bad entry")
    entry = CalloutEntry(
        id=_text(data.get("id")),
        type=_text(data.get("type")),
        start_ms=_whole(data.get("start_ms")),
        end_ms=_whole(data.get("end_ms")),
        on_presenter=on_presenter,
        at_unit_start=at_unit_start,
        parts=tuple(_part_of(part) for part in _list(data.get("parts"))),
    )
    if (
        not entry.parts
        or entry.start_ms < 0
        or entry.end_ms <= entry.start_ms
        or any(part.start_ms >= entry.end_ms for part in entry.parts)
    ):
        raise CalloutError("bad entry")
    return entry


def parse_track(raw: object) -> CalloutTrack | None:
    """Reads the `callouts` entry of a timeline back. None for a render without callouts.
    Raises CalloutError for anything this version does not understand.
    """
    if raw is None:
        return None
    data = _object(raw)
    return CalloutTrack(
        style=_style_of(data.get("style")),
        entries=tuple(_entry_of(entry) for entry in _list(data.get("entries"))),
    )
