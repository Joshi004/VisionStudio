"""`line_trend`: values over time, three to twelve points (§4.5.1). Ported from
`motion/src/templates/LineTrend.tsx`. The axis is fitted to the data with 10 percent padding and has
faint grid lines but no tick numbers (every number on screen comes from the line, G-7): each point
shows its own value instead. The line draws through each point as its beat arrives. `area` also
fills under the line, revealed with it.
"""

from __future__ import annotations

from typing import Any

from app.services.graphics_python.canvas import Canvas, Point
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
from app.services.graphics_python.text import num, pill, pill_size, text_at


def _between(start: Point, end: Point, p: float) -> Point:
    return start[0] + (end[0] - start[0]) * p, start[1] + (end[1] - start[1]) * p


def draw(canvas: Canvas, ctx: Ctx) -> None:
    fields, beats = ctx.spec["fields"], ctx.spec["beats"]
    points: list[dict[str, Any]] = []
    for index, point in enumerate(fields["points"]):
        if index >= len(beats["points"]):
            raise cannot_draw(f"point {index + 1} has no beat.")
        measure = measure_of(ctx, point["value"])
        points.append(
            {
                "value": measure["value"],
                "display": measure["display"],
                "ref": point["value"],
                "p": enter_of(ctx, beats["points"][index]),
                "label": f"points.{index}.label",
            }
        )
    count = len(points)
    slot = ctx.W / count
    gap = js_round(0.01 * ctx.height)

    end_label = fields.get("end_label")
    box = None if end_label is None else pill_size(ctx, end_label)
    value_size = min(fit_number(point["display"], ctx.body_size, slot) for point in points)
    value_row = js_round(text_height(value_size)) + gap
    labels_height = (
        js_round(max(lines_height(text_of(ctx, point["label"])) for point in points)) + gap
    )
    label_top = ctx.bottom - labels_height + gap

    plot_top = (
        content_top(ctx)
        + (0 if box is None else box.height + js_round(0.02 * ctx.height))
        + value_row
    )
    plot_bottom = label_top - gap
    if plot_bottom - plot_top < js_round(0.15 * ctx.height):
        raise cannot_draw("the line, its values and its labels do not fit above the caption area.")

    # The range of the axis: the data with 10 percent of its spread on both sides.
    low = min(point["value"] for point in points)
    high = max(point["value"] for point in points)
    spread = (high - low) or max(1, 0.1 * abs(high))
    axis_low = low - 0.1 * spread
    axis_high = high + 0.1 * spread
    at: list[Point] = [
        (
            ctx.left + (index + 0.5) * slot,
            plot_bottom
            - ((point["value"] - axis_low) / (axis_high - axis_low)) * (plot_bottom - plot_top),
        )
        for index, point in enumerate(points)
    ]

    # What of the line has been drawn: the first point once its beat has come, then each segment
    # as far as its point's beat has progressed.
    reached: list[Point] = []
    for index, point in enumerate(points):
        if point["p"] <= 0:
            continue
        reached.append(at[index] if index == 0 else _between(at[index - 1], at[index], point["p"]))

    thickness = max(3, js_round(0.004 * ctx.height))
    dot = js_round(0.008 * ctx.height)
    accent = ctx.theme["accent"]

    for share in (0, 0.5, 1):
        y = js_round(plot_top + share * (plot_bottom - plot_top))
        canvas.line((ctx.left, y), (ctx.right, y), ctx.stroke, ctx.theme["surface"])
    if ctx.spec["variant"] == "area" and reached:
        canvas.polygon(
            [(reached[0][0], plot_bottom), *reached, (reached[-1][0], plot_bottom)],
            accent,
            alpha=0.2,
        )
    if len(reached) > 1:
        canvas.polyline(reached, thickness, accent)
    for index, point in enumerate(points):
        if point["p"] > 0:
            canvas.ellipse(at[index][0], at[index][1], dot * point["p"], accent, alpha=point["p"])

    for index, point in enumerate(points):
        here = at[index]
        with canvas.layer(point["p"], slide=True):
            num(
                canvas,
                ctx,
                point["ref"],
                size=value_size,
                x=here[0],
                y=js_round(here[1] - dot - gap - text_height(value_size)),
                anchor="center",
                p=point["p"],
                colour=ctx.theme["text"],
            )
            text_at(
                canvas,
                ctx,
                point["label"],
                ctx.theme["muted"],
                left=ctx.left + index * slot,
                top=label_top,
                width=slot,
                align="center",
            )
    if end_label is not None and beats.get("end_label") is not None:
        end_p = enter_of(ctx, beats["end_label"])
        with canvas.layer(end_p, slide=True):
            pill(canvas, ctx, end_label, right=ctx.right, top=content_top(ctx), p=end_p)
