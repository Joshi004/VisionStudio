"""`bar_comparison`: two to six values side by side (§4.5.1). Ported from
`motion/src/templates/BarComparison.tsx`. Bars start at zero, every bar has the same unit, and a bar
grows over the same time as other parts arrive. A bar with `emphasis` is `accent`; when some bars
have it, the others are `muted`; when none has it, all are `accent`.
"""

from __future__ import annotations

import math
from typing import Any

from app.services.graphics_python.canvas import Canvas
from app.services.graphics_python.layout import (
    Ctx,
    content_top,
    enter_of,
    fit_number,
    lines_height,
    measure_of,
    text_height,
    text_of,
)
from app.services.graphics_python.motion import js_round
from app.services.graphics_python.spec import cannot_draw
from app.services.graphics_python.text import num, number_width, pill, pill_size, text_at

# The most a bar is thick: 20 percent of the safe width (vertical) or 9 percent of the height
# (horizontal), so two bars are not two slabs.
_MAX_VERTICAL_THICKNESS = 0.2
_MAX_HORIZONTAL_THICKNESS = 0.09


def draw(canvas: Canvas, ctx: Ctx) -> None:
    fields, beats = ctx.spec["fields"], ctx.spec["beats"]
    bars: list[dict[str, Any]] = []
    for index, bar in enumerate(fields["bars"]):
        if index >= len(beats["bars"]):
            raise cannot_draw(f"bar {index + 1} has no beat.")
        measure = measure_of(ctx, bar["value"])
        bars.append(
            {
                "value": measure["value"],
                "display": measure["display"],
                "ref": bar["value"],
                "p": enter_of(ctx, beats["bars"][index]),
                "label": f"bars.{index}.label",
                "emphasis": bar.get("emphasis") is True,
            }
        )
    any_emphasis = any(bar["emphasis"] for bar in bars)

    def colour_of(emphasis: bool) -> str:
        return ctx.theme["accent"] if not any_emphasis or emphasis else ctx.theme["muted"]

    highlight = fields.get("highlight")
    box = None if highlight is None else pill_size(ctx, highlight["value"])
    gap = js_round(0.01 * ctx.height)
    lowest = min(0, *(bar["value"] for bar in bars))
    highest = max(0, *(bar["value"] for bar in bars))
    span = (highest - lowest) or 1
    top = content_top(ctx) + (0 if box is None else box.height + js_round(0.02 * ctx.height))
    radius = max(2, js_round(ctx.height / 270))

    if highlight is not None:
        highlight_p = enter_of(ctx, highlight["beat"])
        with canvas.layer(highlight_p, slide=True):
            pill(
                canvas,
                ctx,
                highlight["value"],
                right=ctx.right,
                top=content_top(ctx),
                p=highlight_p,
            )

    first = bars[0]["p"]
    if ctx.spec["variant"] == "vertical":
        _vertical(canvas, ctx, bars, colour_of, top, gap, lowest, highest, span, radius, first)
    else:
        _horizontal(canvas, ctx, bars, colour_of, top, lowest, span, radius, first)


def _vertical(canvas, ctx, bars, colour_of, top, gap, lowest, highest, span, radius, first) -> None:
    slot = ctx.W / len(bars)
    bar_width = js_round(min(0.6 * slot, _MAX_VERTICAL_THICKNESS * ctx.W))
    value_size = min(fit_number(bar["display"], ctx.body_size, slot) for bar in bars)
    value_row = js_round(text_height(value_size)) + gap
    labels_height = js_round(max(lines_height(text_of(ctx, bar["label"])) for bar in bars)) + gap
    label_top = ctx.bottom - labels_height + gap
    plot_top = top + value_row
    plot_bottom = label_top - gap - (value_row if lowest < 0 else 0)
    if plot_bottom - plot_top < js_round(0.15 * ctx.height):
        raise cannot_draw(
            "the bars, their values and their labels do not fit above the caption area."
        )
    scale = (plot_bottom - plot_top) / span
    baseline = js_round(plot_top + highest * scale)

    if first > 0:
        canvas.rect(
            ctx.left,
            baseline - ctx.stroke // 2,
            ctx.W,
            ctx.stroke,
            ctx.theme["muted"],
            alpha=first,
        )
    for index, bar in enumerate(bars):
        centre = ctx.left + (index + 0.5) * slot
        full = abs(bar["value"]) * scale
        grown = js_round(full * bar["p"])
        rises = bar["value"] >= 0
        bar_top = baseline - grown if rises else baseline
        final_top = baseline - js_round(full) if rises else baseline
        value_y = (
            final_top - gap - js_round(text_height(value_size))
            if rises
            else baseline + js_round(full) + gap
        )
        canvas.rect(
            js_round(centre - bar_width / 2),
            bar_top,
            bar_width,
            grown,
            colour_of(bar["emphasis"]),
            radius=radius,
        )
        with canvas.layer(bar["p"], slide=True):
            num(
                canvas,
                ctx,
                bar["ref"],
                size=value_size,
                x=centre,
                y=value_y,
                anchor="center",
                p=bar["p"],
                colour=ctx.theme["text"],
            )
            text_at(
                canvas,
                ctx,
                bar["label"],
                ctx.theme["muted"],
                left=ctx.left + index * slot,
                top=label_top,
                width=slot,
                align="center",
            )


def _horizontal(canvas, ctx, bars, colour_of, top, lowest, span, radius, first) -> None:
    """One row for each bar, the label on the left, the value at the end of the bar."""
    row_height = (ctx.bottom - top) / len(bars)
    label_height = max(lines_height(text_of(ctx, bar["label"])) for bar in bars)
    if row_height < label_height or row_height < js_round(0.05 * ctx.height):
        raise cannot_draw("the bars and their labels do not fit above the caption area.")
    label_width = 0.3 * ctx.W
    space = js_round(0.015 * ctx.W)
    value_size = min(fit_number(bar["display"], ctx.body_size, 0.2 * ctx.W) for bar in bars)
    value_width = math.ceil(max(number_width(ctx, bar["ref"], value_size) for bar in bars))
    area_left = ctx.left + label_width + space + (value_width + space if lowest < 0 else 0)
    area_right = ctx.right - value_width - space
    scale = (area_right - area_left) / span
    baseline = js_round(area_left - lowest * scale)
    thickness = js_round(min(0.6 * row_height, _MAX_HORIZONTAL_THICKNESS * ctx.height))

    if first > 0:
        canvas.rect(
            baseline - ctx.stroke // 2,
            top,
            ctx.stroke,
            ctx.bottom - top,
            ctx.theme["muted"],
            alpha=first,
        )
    for index, bar in enumerate(bars):
        row_top = top + index * row_height
        bar_top = js_round(row_top + (row_height - thickness) / 2)
        full = abs(bar["value"]) * scale
        grown = js_round(full * bar["p"])
        rises = bar["value"] >= 0
        bar_left = baseline if rises else baseline - grown
        value_y = js_round(row_top + (row_height - text_height(value_size)) / 2)
        value_x = baseline + js_round(full) + space if rises else baseline - js_round(full) - space
        canvas.rect(
            bar_left,
            bar_top,
            grown,
            thickness,
            colour_of(bar["emphasis"]),
            radius=radius,
        )
        with canvas.layer(bar["p"], slide=True):
            num(
                canvas,
                ctx,
                bar["ref"],
                size=value_size,
                x=value_x,
                y=value_y,
                anchor="left" if rises else "right",
                p=bar["p"],
                colour=ctx.theme["text"],
            )
            text_at(
                canvas,
                ctx,
                bar["label"],
                ctx.theme["muted"],
                left=ctx.left,
                top=js_round(row_top + (row_height - lines_height(text_of(ctx, bar["label"]))) / 2),
                width=label_width,
                align="right",
            )
