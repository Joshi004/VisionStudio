"""`flow_diagram`: two to six steps in a chain (§4.5.1). Ported from
`motion/src/templates/FlowDiagram.tsx`. A node is a rounded `surface` box with an `accent` border;
the arrow to a node draws in as the node arrives. In `horizontal` the nodes share the safe width
with a gap of 6 percent of it; in `vertical` they are 0.7 W / 0.85 wide and centred, and the gaps
shrink (from 5 percent of the height down to 2 percent) before the layout is refused.
"""

from __future__ import annotations

from app.services.graphics_python.canvas import Canvas
from app.services.graphics_python.layout import (
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
    nodes = [
        (f"nodes.{index}.label", enter_of(ctx, node["beat"]))
        for index, node in enumerate(ctx.spec["fields"]["nodes"])
    ]
    count = len(nodes)
    horizontal = ctx.spec["variant"] == "horizontal"
    top = content_top(ctx)
    available = ctx.bottom - top

    # Every node is as high as the tallest label needs, plus 0.35 of its size above and below.
    text_heights = [lines_height(text_of(ctx, path)) for path, _p in nodes]
    tallest = max(text_of(ctx, path)["size"] for path, _p in nodes)
    padding = js_round(0.35 * tallest)
    node_height = js_round(max(text_heights)) + 2 * padding

    node_width = (
        (ctx.W - (count - 1) * 0.06 * ctx.W) / count if horizontal else (0.7 * ctx.W) / 0.85
    )
    border = max(2, js_round(ctx.height / 360))
    radius = js_round(0.3 * tallest)

    if horizontal:
        gap = 0.06 * ctx.W
        origin_x = float(ctx.left)
        if node_height > available:
            raise cannot_draw("the steps do not fit above the caption area.")
        origin_y = top + (available - node_height) / 2
    else:
        gap = min(js_round(0.05 * ctx.height), (available - count * node_height) / (count - 1))
        if gap < js_round(0.02 * ctx.height):
            raise cannot_draw("the steps do not fit above the caption area.")
        origin_x = ctx.left + (ctx.W - node_width) / 2
        origin_y = top + (available - (count * node_height + (count - 1) * gap)) / 2

    def place(index: int) -> tuple[float, float]:
        if horizontal:
            return origin_x + index * (node_width + gap), origin_y
        return origin_x, origin_y + index * (node_height + gap)

    head = js_round(0.012 * ctx.height)
    thickness = max(2, js_round(ctx.height / 270))
    muted = ctx.theme["muted"]

    for index in range(1, count):
        p = nodes[index][1]
        if p <= 0:
            continue
        with canvas.layer(p):
            start, end = place(index - 1), place(index)
            # The arrow runs across the gap and keeps 15 percent of it free at both ends.
            margin = 0.15 * gap
            if horizontal:
                x1, y1 = start[0] + node_width + margin, start[1] + node_height / 2
                x2, y2 = end[0] - margin, end[1] + node_height / 2
            else:
                x1, y1 = start[0] + node_width / 2, start[1] + node_height + margin
                x2, y2 = end[0] + node_width / 2, end[1] - margin
            tip_x = x1 + (x2 - x1) * p
            tip_y = y1 + (y2 - y1) * p
            wing = head * 0.7
            if horizontal:
                arrowhead = [
                    (tip_x, tip_y),
                    (tip_x - head, tip_y - wing),
                    (tip_x - head, tip_y + wing),
                ]
                shaft_x, shaft_y = tip_x - head, tip_y
            else:
                arrowhead = [
                    (tip_x, tip_y),
                    (tip_x - wing, tip_y - head),
                    (tip_x + wing, tip_y - head),
                ]
                # The shaft stops at the base of the head.
                shaft_x, shaft_y = tip_x, tip_y - head
            canvas.line(
                (x1, y1), (max(x1, shaft_x), max(y1, shaft_y)), thickness, muted, round_caps=True
            )
            canvas.polygon(arrowhead, muted)

    for index, (path, p) in enumerate(nodes):
        x, y = place(index)
        label = text_of(ctx, path)
        with canvas.layer(p, slide=True):
            width = js_round(node_width)
            canvas.rect(
                js_round(x), js_round(y), width, node_height, ctx.theme["accent"], radius=radius
            )
            canvas.rect(
                js_round(x) + border,
                js_round(y) + border,
                width - 2 * border,
                node_height - 2 * border,
                ctx.theme["surface"],
                radius=max(0, radius - border),
            )
            text_at(
                canvas,
                ctx,
                path,
                ctx.theme["text"],
                left=js_round(x),
                top=js_round(y + (node_height - lines_height(label)) / 2),
                width=width,
                align="center",
            )
