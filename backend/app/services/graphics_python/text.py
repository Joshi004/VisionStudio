"""Text, numbers and pills, ported from `motion/src/templates/Text.tsx`. Text is drawn exactly as
the spec laid it out (its font, its size and its lines): nothing is fitted or broken here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.services.graphics_python.canvas import Canvas
from app.services.graphics_python.layout import (
    LINE_HEIGHT,
    Ctx,
    fit_number,
    measure_of,
    text_of,
)
from app.services.graphics_python.motion import counted_text, js_round
from app.services.graphics_python.spec import cannot_draw
from app.services.graphics_templates import measure

_ALIGN_SHARE = {"left": 0.0, "center": 0.5, "right": 1.0}


def lines(
    canvas: Canvas,
    layout: dict[str, Any],
    colour: str,
    *,
    left: float,
    top: float,
    width: float,
    align: str,
) -> None:
    """A text laid out by the spec, in a box `width` wide that starts at (`left`, `top`)."""
    size = layout["size"]
    x = left + width * _ALIGN_SHARE[align]
    for index, line in enumerate(layout["lines"]):
        canvas.text(
            line,
            layout["font"],
            size,
            colour,
            x=x,
            top=top + index * size * LINE_HEIGHT,
            align=align,
        )


def text_at(
    canvas: Canvas,
    ctx: Ctx,
    path: str,
    colour: str,
    *,
    left: float,
    top: float,
    width: float,
    align: str,
) -> None:
    """The text laid out under `path` of the spec."""
    lines(canvas, text_of(ctx, path), colour, left=left, top=top, width=width, align=align)


def number_width(ctx: Ctx, ref: str, size: int) -> float:
    """The final width of a number's text at a size."""
    return measure(measure_of(ctx, ref)["display"], "display", size)


def num(
    canvas: Canvas,
    ctx: Ctx,
    item: str,
    *,
    size: int,
    x: float,
    y: float,
    anchor: str,
    p: float,
    colour: str,
) -> None:
    """A fact or derived value in the display font, counting up as `p` goes from 0 to 1. `x` is
    where the text starts, ends or is centred, as `anchor` says. The box has the width of the
    final text and the digits grow inside it from its left edge, so nothing moves while a number
    counts. A year (unit `none`) does not count.
    """
    found = measure_of(ctx, item)
    width = number_width(ctx, item, size)
    left = x if anchor == "left" else x - width / 2 if anchor == "center" else x - width
    shown = counted_text(found["display"], p, found["unit"] != "none")
    canvas.text(shown, "display", size, colour, x=left, top=y)


@dataclass(frozen=True)
class PillBox:
    size: int
    pad_x: int
    pad_y: int
    width: int
    height: int


def pill_size(ctx: Ctx, ref: str) -> PillBox:
    """The box of a pill: its text is as large as the body text, made smaller to fit 30 percent of
    the safe width.
    """
    size = fit_number(measure_of(ctx, ref)["display"], ctx.body_size, ctx.W * 0.3)
    pad_x = js_round(0.6 * size)
    pad_y = js_round(0.3 * size)
    return PillBox(
        size=size,
        pad_x=pad_x,
        pad_y=pad_y,
        width=math.ceil(number_width(ctx, ref, size)) + 2 * pad_x,
        height=js_round(size * LINE_HEIGHT) + 2 * pad_y,
    )


def pill(canvas: Canvas, ctx: Ctx, item: str, *, right: float, top: float, p: float) -> None:
    """A rounded `accent` label with a number in it (the highlight of the bars, the end label of
    the line).
    """
    box = pill_size(ctx, item)
    if box.width > ctx.W:
        raise cannot_draw(f"the label for {item} is wider than the safe area.")
    left = right - box.width
    canvas.rect(left, top, box.width, box.height, ctx.theme["accent"], radius=box.height / 2)
    num(
        canvas,
        ctx,
        item,
        size=box.size,
        x=left + box.pad_x,
        y=top + box.pad_y,
        anchor="left",
        p=p,
        colour=ctx.theme["background"],
    )
