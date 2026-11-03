"""`kpi_card`: one big number, with a change and a caption (§4.5.1). Ported from
`motion/src/templates/KpiCard.tsx`. `center` stacks the three in the middle of the content box.
`split` puts the number on the left half, and the change and the caption on the right half; each
half is centred vertically.
"""

from __future__ import annotations

from app.services.graphics_python.canvas import Canvas
from app.services.graphics_python.layout import (
    Ctx,
    change_colour,
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
from app.services.graphics_python.text import num, text_at


def draw(canvas: Canvas, ctx: Ctx) -> None:
    fields, beats = ctx.spec["fields"], ctx.spec["beats"]
    split = ctx.spec["variant"] == "split"
    top = content_top(ctx)
    available = ctx.bottom - top
    gap = js_round(0.02 * ctx.height)

    # The number is 14 percent of the height (landscape) or 7 percent (portrait); in `split` it
    # keeps a tenth of the left half free. It is made smaller when it does not fit.
    space = (ctx.W / 2) * 0.9 if split else ctx.W
    value_base = js_round((0.14 if ctx.landscape else 0.07) * ctx.height)
    value_size = fit_number(measure_of(ctx, fields["value"])["display"], value_base, space)
    value_height = text_height(value_size)

    change = fields.get("change")
    change_size = (
        0
        if change is None
        else fit_number(measure_of(ctx, change)["display"], ctx.title_size, space)
    )
    caption = fields.get("caption")
    caption_height = 0 if caption is None else lines_height(text_of(ctx, "caption"))

    side_height = (
        (0 if change is None else text_height(change_size))
        + (gap if change is not None and caption is not None else 0)
        + caption_height
    )
    stack_height = value_height + (gap + side_height if side_height > 0 else 0)
    if (max(value_height, side_height) if split else stack_height) > available:
        raise cannot_draw(
            "the number, its change and its caption do not fit above the caption area."
        )

    centre_x = ctx.left + ctx.W / 2
    value_x = ctx.left if split else centre_x
    value_y = js_round(
        top + (available - value_height) / 2 if split else top + (available - stack_height) / 2
    )
    side_x = ctx.left + ctx.W / 2 if split else centre_x
    side_y = js_round(
        top + (available - side_height) / 2 if split else value_y + value_height + gap
    )

    value_p = enter_of(ctx, beats["value"])
    change_y = side_y
    if change is not None:
        side_y += js_round(text_height(change_size) + gap)
    sign = 0 if change is None else measure_of(ctx, change)["value"]

    anchor = "left" if split else "center"
    with canvas.layer(value_p, slide=True):
        num(
            canvas,
            ctx,
            fields["value"],
            size=value_size,
            x=value_x,
            y=value_y,
            anchor=anchor,
            p=value_p,
            colour=ctx.theme["text"],
        )
    if change is not None and beats.get("change") is not None:
        change_p = enter_of(ctx, beats["change"])
        with canvas.layer(change_p, slide=True):
            num(
                canvas,
                ctx,
                change,
                size=change_size,
                x=side_x,
                y=change_y,
                anchor=anchor,
                p=change_p,
                colour=change_colour(ctx, sign),
            )
    if caption is not None and beats.get("caption") is not None:
        with canvas.layer(enter_of(ctx, beats["caption"]), slide=True):
            text_at(
                canvas,
                ctx,
                "caption",
                ctx.theme["muted"],
                left=side_x if split else ctx.left,
                top=side_y,
                width=ctx.W / 2 if split else ctx.W,
                align="left" if split else "center",
            )
