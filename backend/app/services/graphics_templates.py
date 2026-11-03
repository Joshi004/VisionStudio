"""The template catalogue of the Graphics lab, and the checks of a template spec (GFX-006,
`Graphics_lab_implementation_phases.md` §4.5.1).

Pure functions, no I/O besides reading the two bundled font files.

The catalogue has five templates. One model call reads the brief and answers either a **template
spec** (a template, a variant, the fields of that template and the beat of each part) or
`{"template": null, "reason": "..."}` when no template fits. "No template fits" is a valid answer.
`check_spec` turns the answer into the stored spec, or raises ValueError with a message fit for
the user and for the model's corrected retry. Long text is never cut: a text over its limit is
refused.

**What the checks hold to.**

- Known template, variant, fields and beats; no unknown keys.
- The limits and counts of the catalogue.
- Every ref names a fact or a derived value of the brief, and every beat id exists. The beats of a
  list (bars, points, nodes, items) never go backwards in frame.
- The number rule (G-7): a number in any text field must be said in the line or be the on-screen
  text of a fact or a derived value.
- The bars of one chart, or the points of one line, all have the same unit.
- Every text fits its space (below).

**Text fit.** GFX-007 and GFX-008 draw the same spec independently, so the checks also decide how
each text is laid out, and the result is stored in the spec under `text`, keyed by the field path
(`title`, `bars.0.label`, ...) as `{font, size, lines}`. Both renderers draw exactly those sizes
and line breaks. A text is measured in its font at the size it is drawn at, in pixels, and has to
fit within `FIT_SHARE` of the width of its space (the rest leaves room for the small differences
between two renderers' kerning). It is tried on one line from its full size down to 70 percent of
it, then on two lines (split at the word break that keeps the longer line shortest) in the same
range. Past that the spec is refused. Only widths are checked: where a text sits vertically is the
renderers' business, inside the safe area and above the caption area.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from typing import Any, Final

from PIL import ImageFont

from app.services.callout_plan_writer import format_number
from app.services.font_metrics import FONTS_DIR
from app.services.number_words import numbers_in

# Stored in each spec, so a renderer can tell which catalogue the spec was written for.
CATALOGUE_VERSION: Final = 1

REASON_MAX_CHARS: Final = 200
TITLE_MAX_CHARS: Final = 32
CAPTION_MAX_CHARS: Final = 60
BAR_LABEL_MAX_CHARS: Final = 16
POINT_LABEL_MAX_CHARS: Final = 10
NODE_LABEL_MAX_CHARS: Final = 24
ITEM_MAX_CHARS: Final = 48

# The least a text may be shrunk to, and how much of its space it may fill.
MIN_SIZE_SHARE: Final = 0.7
FIT_SHARE: Final = 0.97
# The height of a line of text, as a share of its size (for the renderers).
LINE_HEIGHT: Final = 1.2

# The sizes of the look rules, as a share of the video's height: landscape, then portrait.
TITLE_SIZE_SHARE: Final = (0.06, 0.036)
BODY_SIZE_SHARE: Final = (0.032, 0.024)

# The two fonts of G-11 (`graphics_lab.DISPLAY_FONT_FILE` and `TEXT_FONT_FILE` name the same
# files; they are not imported, because `graphics_lab` imports the engine registry that imports
# this module). `display` is for titles and numbers, `text` for all other text.
FONT_FILES: Final = {"display": "Montserrat-ExtraBold.ttf", "text": "Inter-Medium.ttf"}
_REFERENCE_SIZE: Final = 1000

# The space of a text, as a share of the width of the safe area (§4.5.1).
BAR_LABEL_SHARE_HORIZONTAL: Final = 0.3
BAR_LABEL_SHARE_VERTICAL: Final = 0.9
NODE_LABEL_SHARE: Final = 0.85
NODE_GAP_SHARE: Final = 0.06
NODE_VERTICAL_SHARE: Final = 0.7
ITEM_SHARE: Final = 0.92


@dataclass(frozen=True)
class Template:
    """One template of the catalogue, as the instructions describe it to the model."""

    key: str
    label: str
    variants: tuple[str, ...]
    purpose: str
    fields: str
    rules: str


CATALOGUE: Final = (
    Template(
        key="kpi_card",
        label="KPI card",
        variants=("center", "split"),
        purpose="One big number, with or without a change.",
        fields=(
            '{"title": text (32), "value": ref, "change": ref (optional), '
            '"caption": text (60, optional)}; beats {"title", "value", and "change" and '
            '"caption" when the field is given}'
        ),
        rules="The colour of a change follows its sign.",
    ),
    Template(
        key="bar_comparison",
        label="Bar comparison",
        variants=("vertical", "horizontal"),
        purpose="Two to six values set side by side.",
        fields=(
            '{"title": text (32), "bars": 2 to 6 of {"label": text (16), "value": ref, '
            '"emphasis": true (optional)}, "highlight": {"value": ref, "beat": beat id} '
            '(optional)}; beats {"title", "bars": one beat id for each bar}'
        ),
        rules="Bars start at zero and every bar has the same unit.",
    ),
    Template(
        key="line_trend",
        label="Line trend",
        variants=("line", "area"),
        purpose="Values over time, three to twelve points.",
        fields=(
            '{"title": text (32), "points": 3 to 12 of {"label": text (10), "value": ref}, '
            '"end_label": ref (optional)}; beats {"title", "points": one beat id for each '
            'point, and "end_label" when the field is given}'
        ),
        rules=(
            "The axis is fitted to the data and always shows its values. The line draws "
            "through each point as its beat arrives. Every point has the same unit."
        ),
    ),
    Template(
        key="flow_diagram",
        label="Flow diagram",
        variants=("horizontal", "vertical"),
        purpose="Two to six steps in a chain.",
        fields=(
            '{"title": text (32), "nodes": 2 to 6 of {"label": text (24), "beat": beat id}}; '
            'beats {"title"}'
        ),
        rules=(
            "The arrow to a node appears with the node. A portrait video uses "
            '"vertical" unless you choose otherwise.'
        ),
    ),
    Template(
        key="bullet_build",
        label="Bullet build",
        variants=("list", "statement"),
        purpose="A few points that build up one by one, or one short sentence shown large.",
        fields=(
            '{"title": text (32, optional), "items": 1 to 4 of {"text": text (48), '
            '"beat": beat id}}; beats {"title" when the title is given}'
        ),
        rules='"statement" has exactly one item, shown large and centred.',
    ),
)
TEMPLATES: Final = {template.key: template for template in CATALOGUE}

# The most text each limited field may have, by the name the model sees in the answer.
LIMIT_NAMES: Final = {
    "reason": REASON_MAX_CHARS,
    "title": TITLE_MAX_CHARS,
    "caption": CAPTION_MAX_CHARS,
    "bars[].label": BAR_LABEL_MAX_CHARS,
    "points[].label": POINT_LABEL_MAX_CHARS,
    "nodes[].label": NODE_LABEL_MAX_CHARS,
    "items[].text": ITEM_MAX_CHARS,
}


# --- Measuring and fitting text ----------------------------------------------------------------


@lru_cache(maxsize=2)
def _font(role: str) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / FONT_FILES[role]), _REFERENCE_SIZE)


def measure(text: str, role: str, size: int) -> float:
    """The width in pixels of `text` on one line, drawn in the font `role` (`display` or `text`)
    at a font size of `size` pixels (the size of the em, as CSS and Pillow take it).
    """
    return float(_font(role).getlength(text)) / _REFERENCE_SIZE * size


def _fitting_size(width_per_px: float, base: int, limit: float) -> int | None:
    """The largest whole-pixel size up to `base` at which a line `width_per_px` wide (at one
    pixel) is within `limit`, or None when that is under 70 percent of `base`.
    """
    size = min(base, math.floor(limit / width_per_px)) if width_per_px > 0 else base
    return size if size >= math.ceil(base * MIN_SIZE_SHARE) else None


def fit_text(text: str, role: str, base: int, box_width: float) -> dict[str, Any] | None:
    """How `text` is laid out in a space `box_width` pixels wide: `{font, size, lines}`, or None
    when it does not fit even on two lines at 70 percent of `base`.
    """
    limit = box_width * FIT_SHARE
    one_line = _fitting_size(measure(text, role, 1), base, limit)
    if one_line is not None:
        return {"font": role, "size": one_line, "lines": [text]}
    words = text.split()
    best: tuple[float, list[str]] | None = None
    for cut in range(1, len(words)):
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
        longest = max(measure(line, role, 1) for line in lines)
        if best is None or longest < best[0]:
            best = (longest, lines)
    if best is None:
        return None
    two_lines = _fitting_size(best[0], base, limit)
    if two_lines is None:
        return None
    return {"font": role, "size": two_lines, "lines": best[1]}


# --- Reading the answer ------------------------------------------------------------------------


def object_of(
    value: object, name: str, required: Sequence[str], optional: Sequence[str] = ()
) -> dict[str, Any]:
    """The object with its `null` keys dropped. Refused when it is not an object, has a key that
    is not allowed, or lacks a required one.
    """
    if not isinstance(value, dict):
        raise ValueError(f"The {name} was not an object.")
    given = {key: item for key, item in value.items() if item is not None}
    unknown = [key for key in given if key not in required and key not in optional]
    if unknown:
        raise ValueError(f'The {name} has "{unknown[0]}", which is not allowed there.')
    missing = [key for key in required if key not in given]
    if missing:
        raise ValueError(f'The {name} has no "{missing[0]}".')
    return given


def items_of(value: object, name: str, least: int, most: int) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f'The "{name}" were not a list.')
    if not least <= len(value) <= most:
        wanted = f"exactly {least}" if least == most else f"{least} to {most}"
        raise ValueError(f'There were {len(value)} "{name}"; it must be {wanted}.')
    return value


def line_of_text(value: object, name: str, max_chars: int) -> str:
    """One piece of text on one line, never cut: refused when it is empty or too long."""
    if not isinstance(value, str):
        raise ValueError(f'The "{name}" was missing or was not text.')
    text = " ".join(value.split())
    if not text:
        raise ValueError(f'The "{name}" was empty.')
    if len(text) > max_chars:
        raise ValueError(
            f'The "{name}" "{text}" was {len(text)} characters; the most allowed is {max_chars}.'
        )
    return text


@dataclass
class _Context:
    """What the checks of one spec read, and the text layout they write."""

    line: str
    resolved: dict[str, Any]
    landscape: bool = field(init=False)
    safe_width: int = field(init=False)
    title_size: int = field(init=False)
    body_size: int = field(init=False)
    units: dict[str, str] = field(init=False)
    frames: dict[str, int] = field(init=False)
    allowed_numbers: set[Decimal] = field(init=False)
    text: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        resolved = self.resolved
        height = int(resolved["height"])
        self.landscape = int(resolved["width"]) >= height
        index = 0 if self.landscape else 1
        self.title_size = round(TITLE_SIZE_SHARE[index] * height)
        self.body_size = round(BODY_SIZE_SHARE[index] * height)
        area = resolved["safe_area"]
        self.safe_width = int(area["right"]) - int(area["left"])
        values = {**resolved["facts"], **resolved["derived"]}
        self.units = {key: str(item["unit"]) for key, item in values.items()}
        self.frames = {key: int(item["frame"]) for key, item in resolved["beats"].items()}
        allowed = numbers_in(self.line)
        for item in values.values():
            allowed |= numbers_in(str(item["display"]))
        self.allowed_numbers = allowed

    # --- ids ---

    def ref(self, value: object, name: str) -> str:
        """A fact or derived id of the brief."""
        if not isinstance(value, str) or value not in self.units:
            raise ValueError(f"The {name} {value!r} is not a fact or derived id of the brief.")
        return value

    def beat(self, value: object, name: str) -> str:
        if not isinstance(value, str) or value not in self.frames:
            raise ValueError(f"The {name} {value!r} is not a beat id of the brief.")
        return value

    def beats_in_order(self, beat_ids: Sequence[str], name: str) -> list[str]:
        """The beats of a list: none of them comes before the one before it."""
        for earlier, later in zip(beat_ids, beat_ids[1:], strict=False):
            if self.frames[later] < self.frames[earlier]:
                raise ValueError(
                    f"The beats in {name} go backwards: {later} comes before {earlier} "
                    "in the line. They must follow the order of the line."
                )
        return list(beat_ids)

    def beat_list(self, value: object, name: str, count: int) -> list[str]:
        """One beat id for each of `count` parts."""
        entries = items_of(value, name, count, count)
        return self.beats_in_order([self.beat(entry, f"beat in {name}") for entry in entries], name)

    def same_unit(self, refs: Sequence[str], name: str) -> None:
        units = {self.units[ref] for ref in refs}
        if len(units) > 1:
            raise ValueError(
                f"The {name} mix the units {', '.join(sorted(units))}. They must all have one unit."
            )

    # --- text ---

    def words(
        self,
        value: object,
        path: str,
        max_chars: int,
        role: str,
        box_width: float,
        *,
        large: bool = False,
    ) -> str:
        """A text field: one line of at most `max_chars`, with no number the line does not say,
        that fits a space `box_width` pixels wide. Its layout is recorded under `text[path]`.
        `large` draws a `text` field at the title size (a statement).
        """
        text = line_of_text(value, path, max_chars)
        unsaid = sorted(numbers_in(text) - self.allowed_numbers)
        if unsaid:
            raise ValueError(
                f'The "{path}" "{text}" shows the number {format_number(unsaid[0])}, which the '
                "line does not say. Every number on screen must come from the line."
            )
        base = self.title_size if role == "display" or large else self.body_size
        fitted = fit_text(text, role, base, box_width)
        if fitted is None:
            raise ValueError(
                f'The "{path}" "{text}" is too long for its space ({box_width:.0f} px wide): it '
                "does not fit even on two lines at 70 percent of its size. Make it shorter."
            )
        self.text[path] = fitted
        return text

    def title(self, value: object, path: str = "title") -> str:
        return self.words(value, path, TITLE_MAX_CHARS, "display", self.safe_width)


# --- The five templates ------------------------------------------------------------------------


def _kpi_card(
    ctx: _Context, variant: str, fields: object, beats: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    given = object_of(fields, "fields", ("title", "value"), ("change", "caption"))
    out_fields: dict[str, Any] = {
        "title": ctx.title(given["title"]),
        "value": ctx.ref(given["value"], "value"),
    }
    required = ["title", "value"]
    if "change" in given:
        out_fields["change"] = ctx.ref(given["change"], "change")
        required.append("change")
    if "caption" in given:
        share = 1.0 if variant == "center" else 0.5
        out_fields["caption"] = ctx.words(
            given["caption"], "caption", CAPTION_MAX_CHARS, "text", ctx.safe_width * share
        )
        required.append("caption")
    placed = object_of(beats, "beats", required)
    return out_fields, {key: ctx.beat(placed[key], f"beat of {key}") for key in required}


def _bar_comparison(
    ctx: _Context, variant: str, fields: object, beats: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    given = object_of(fields, "fields", ("title", "bars"), ("highlight",))
    title = ctx.title(given["title"])
    bars_in = items_of(given["bars"], "bars", 2, 6)
    count = len(bars_in)
    label_box = (
        ctx.safe_width * BAR_LABEL_SHARE_VERTICAL / count
        if variant == "vertical"
        else ctx.safe_width * BAR_LABEL_SHARE_HORIZONTAL
    )
    bars: list[dict[str, Any]] = []
    for position, raw in enumerate(bars_in):
        name = f"bar {position + 1}"
        bar = object_of(raw, name, ("label", "value"), ("emphasis",))
        entry: dict[str, Any] = {
            "label": ctx.words(
                bar["label"], f"bars.{position}.label", BAR_LABEL_MAX_CHARS, "text", label_box
            ),
            "value": ctx.ref(bar["value"], f"value of {name}"),
        }
        if "emphasis" in bar:
            if not isinstance(bar["emphasis"], bool):
                raise ValueError(f"The emphasis of {name} must be true or false.")
            entry["emphasis"] = bar["emphasis"]
        bars.append(entry)
    ctx.same_unit([bar["value"] for bar in bars], "bars")
    out_fields: dict[str, Any] = {"title": title, "bars": bars}
    if "highlight" in given:
        highlight = object_of(given["highlight"], "highlight", ("value", "beat"))
        out_fields["highlight"] = {
            "value": ctx.ref(highlight["value"], "value of the highlight"),
            "beat": ctx.beat(highlight["beat"], "beat of the highlight"),
        }
    placed = object_of(beats, "beats", ("title", "bars"))
    return out_fields, {
        "title": ctx.beat(placed["title"], "beat of the title"),
        "bars": ctx.beat_list(placed["bars"], "beats.bars", count),
    }


def _line_trend(
    ctx: _Context, variant: str, fields: object, beats: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    del variant
    given = object_of(fields, "fields", ("title", "points"), ("end_label",))
    title = ctx.title(given["title"])
    points_in = items_of(given["points"], "points", 3, 12)
    count = len(points_in)
    points: list[dict[str, Any]] = []
    for position, raw in enumerate(points_in):
        name = f"point {position + 1}"
        point = object_of(raw, name, ("label", "value"))
        points.append(
            {
                "label": ctx.words(
                    point["label"],
                    f"points.{position}.label",
                    POINT_LABEL_MAX_CHARS,
                    "text",
                    ctx.safe_width / count,
                ),
                "value": ctx.ref(point["value"], f"value of {name}"),
            }
        )
    ctx.same_unit([point["value"] for point in points], "points")
    out_fields: dict[str, Any] = {"title": title, "points": points}
    required = ["title", "points"]
    if "end_label" in given:
        out_fields["end_label"] = ctx.ref(given["end_label"], "end_label")
        required.append("end_label")
    placed = object_of(beats, "beats", required)
    out_beats: dict[str, Any] = {
        "title": ctx.beat(placed["title"], "beat of the title"),
        "points": ctx.beat_list(placed["points"], "beats.points", count),
    }
    if "end_label" in placed:
        out_beats["end_label"] = ctx.beat(placed["end_label"], "beat of the end label")
    return out_fields, out_beats


def _flow_diagram(
    ctx: _Context, variant: str, fields: object, beats: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    given = object_of(fields, "fields", ("title", "nodes"))
    title = ctx.title(given["title"])
    nodes_in = items_of(given["nodes"], "nodes", 2, 6)
    count = len(nodes_in)
    if variant == "horizontal":
        gaps = (count - 1) * NODE_GAP_SHARE * ctx.safe_width
        label_box = (ctx.safe_width - gaps) / count * NODE_LABEL_SHARE
    else:
        label_box = ctx.safe_width * NODE_VERTICAL_SHARE
    nodes: list[dict[str, Any]] = []
    for position, raw in enumerate(nodes_in):
        node = object_of(raw, f"node {position + 1}", ("label", "beat"))
        nodes.append(
            {
                "label": ctx.words(
                    node["label"],
                    f"nodes.{position}.label",
                    NODE_LABEL_MAX_CHARS,
                    "text",
                    label_box,
                ),
                "beat": ctx.beat(node["beat"], f"beat of node {position + 1}"),
            }
        )
    ctx.beats_in_order([node["beat"] for node in nodes], "fields.nodes")
    placed = object_of(beats, "beats", ("title",))
    return {"title": title, "nodes": nodes}, {
        "title": ctx.beat(placed["title"], "beat of the title")
    }


def _bullet_build(
    ctx: _Context, variant: str, fields: object, beats: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    given = object_of(fields, "fields", ("items",), ("title",))
    out_fields: dict[str, Any] = {}
    required: list[str] = []
    if "title" in given:
        out_fields["title"] = ctx.title(given["title"])
        required.append("title")
    most = 1 if variant == "statement" else 4
    items: list[dict[str, Any]] = []
    for position, raw in enumerate(items_of(given["items"], "items", 1, most)):
        item = object_of(raw, f"item {position + 1}", ("text", "beat"))
        if variant == "statement":
            text = ctx.words(
                item["text"], f"items.{position}.text", ITEM_MAX_CHARS, "display", ctx.safe_width
            )
        else:
            text = ctx.words(
                item["text"],
                f"items.{position}.text",
                ITEM_MAX_CHARS,
                "text",
                ctx.safe_width * ITEM_SHARE,
            )
        items.append({"text": text, "beat": ctx.beat(item["beat"], f"beat of item {position + 1}")})
    ctx.beats_in_order([item["beat"] for item in items], "fields.items")
    out_fields["items"] = items
    placed = object_of(beats, "beats", required)
    return out_fields, {key: ctx.beat(placed[key], f"beat of the {key}") for key in required}


_CHECKS: Final = {
    "kpi_card": _kpi_card,
    "bar_comparison": _bar_comparison,
    "line_trend": _line_trend,
    "flow_diagram": _flow_diagram,
    "bullet_build": _bullet_build,
}


# --- The spec ----------------------------------------------------------------------------------


def default_variant(template: str, landscape: bool) -> str:
    """The variant used when the answer names none: the first one, and for a flow diagram
    `vertical` in a portrait video.
    """
    if template == "flow_diagram" and not landscape:
        return "vertical"
    return TEMPLATES[template].variants[0]


def check_spec(answer: dict[str, Any], line: str, resolved: dict[str, Any]) -> dict[str, Any]:
    """The model's answer as the stored input of the two template engines (§4.5.1): a template
    spec with the layout of its texts, or `{"template": None, "reason": ...}`. Raises ValueError
    with a message fit for the user and for the model's corrected retry.
    """
    template = answer.get("template")
    if template is None:
        return {
            "template": None,
            "reason": line_of_text(answer.get("reason"), "reason", REASON_MAX_CHARS),
            "catalogue_version": CATALOGUE_VERSION,
        }
    if not isinstance(template, str) or template not in TEMPLATES:
        raise ValueError(
            f"The template was {template!r}; it must be one of {', '.join(TEMPLATES)}, or null "
            "with a reason when none fits."
        )
    unknown = [key for key in answer if key not in ("template", "variant", "fields", "beats")]
    if unknown:
        raise ValueError(f'The answer has "{unknown[0]}", which is not allowed there.')
    ctx = _Context(line=line, resolved=resolved)
    variant = answer.get("variant")
    if variant is None:
        variant = default_variant(template, ctx.landscape)
    allowed = TEMPLATES[template].variants
    if not isinstance(variant, str) or variant not in allowed:
        raise ValueError(
            f"The variant of {template} was {variant!r}; it must be one of {', '.join(allowed)}."
        )
    fields, beats = _CHECKS[template](ctx, variant, answer.get("fields"), answer.get("beats"))
    return {
        "template": template,
        "variant": variant,
        "fields": fields,
        "beats": beats,
        "text": ctx.text,
        "catalogue_version": CATALOGUE_VERSION,
    }
