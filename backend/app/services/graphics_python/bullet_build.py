"""`bullet_build`: a few points that build up one by one, or one short sentence shown large
(§4.5.1). Ported from `motion/src/templates/BulletBuild.tsx`. In a `list` the items stack from the
top of the content box, each with an `accent` dot, and the text starts at L + 0.08 W (the `0.92 W`
space the text was fitted to). A `statement` is one centred line in the display font, in the middle
of the content box.
"""

from __future__ import annotations

from app.services.graphics_python.canvas import Canvas
from app.services.graphics_python.layout import (
    LINE_HEIGHT,
    Ctx,
    content_top,
    enter_of,
    lines_height,
    text_of,
)
from app.services.graphics_python.motion import js_round
from app.services.graphics_python.spec import cannot_draw
from app.services.graphics_python.text import text_at


def draw(canvas: Canvas, ctx: Ctx) -> None:
    items = [
        (f"items.{index}.text", enter_of(ctx, item["beat"]))
        for index, item in enumerate(ctx.spec["fields"]["items"])
    ]
    top = content_top(ctx)
    available = ctx.bottom - top

    if ctx.spec["variant"] == "statement":
        if not items:
            raise cannot_draw("the statement has no item.")
        path, p = items[0]
        height = lines_height(text_of(ctx, path))
        if height > available:
            raise cannot_draw("the statement does not fit above the caption area.")
        with canvas.layer(p, slide=True):
            text_at(
                canvas,
                ctx,
                path,
                ctx.theme["text"],
                left=ctx.left,
                top=js_round(top + (available - height) / 2),
                width=ctx.W,
                align="center",
            )
        return

    heights = [lines_height(text_of(ctx, path)) for path, _p in items]
    sizes = [text_of(ctx, path)["size"] for path, _p in items]
    gaps = [js_round(0.6 * size) for size in sizes]
    if sum(heights) + sum(gaps[:-1]) > available:
        raise cannot_draw("the items do not fit above the caption area.")

    y = float(top)
    for index, (path, p) in enumerate(items):
        size = sizes[index]
        item_top = js_round(y)
        y += heights[index] + gaps[index]
        radius = js_round(0.18 * size)
        with canvas.layer(p, slide=True):
            canvas.rect(
                js_round(ctx.left + 0.04 * ctx.W - radius),
                js_round(item_top + (size * LINE_HEIGHT) / 2 - radius),
                2 * radius,
                2 * radius,
                ctx.theme["accent"],
                radius=radius,
            )
            text_at(
                canvas,
                ctx,
                path,
                ctx.theme["text"],
                left=js_round(ctx.left + 0.08 * ctx.W),
                top=item_top,
                width=js_round(0.92 * ctx.W),
                align="left",
            )
