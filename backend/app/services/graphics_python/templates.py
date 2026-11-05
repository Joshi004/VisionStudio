"""One frame of a template video: the port of the `Templates` composition
(`motion/src/templates/Templates.tsx`). The background, then the title, then the template.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from PIL import Image

from app.services.graphics_python import (
    bar_comparison,
    bullet_build,
    flow_diagram,
    kpi_card,
    line_trend,
)
from app.services.graphics_python.canvas import Canvas
from app.services.graphics_python.layout import SLIDE_SHARE, Ctx, enter_of, make_ctx
from app.services.graphics_python.motion import progress_at
from app.services.graphics_python.text import text_at

_DRAWERS: Final[dict[str, Callable[[Canvas, Ctx], None]]] = {
    "kpi_card": kpi_card.draw,
    "bar_comparison": bar_comparison.draw,
    "line_trend": line_trend.draw,
    "flow_diagram": flow_diagram.draw,
    "bullet_build": bullet_build.draw,
}


def draw_frame(
    background: Image.Image, body: dict[str, Any], spec: dict[str, Any], frame: int
) -> Canvas:
    """The picture of `frame`. Raises DrawFailed when the template cannot be drawn."""
    ctx = make_ctx(frame, body, spec)
    canvas = Canvas(background, slide=SLIDE_SHARE * ctx.height)
    title_beat = spec["beats"].get("title")
    if title_beat is not None and spec["text"].get("title") is not None:
        with canvas.layer(enter_of(ctx, title_beat), slide=True):
            text_at(
                canvas,
                ctx,
                "title",
                ctx.theme["text"],
                left=ctx.left,
                top=ctx.top,
                width=ctx.W,
                align="left",
            )
    _DRAWERS[spec["template"]](canvas, ctx)
    return canvas


def beat_progress(body: dict[str, Any], frame: int) -> tuple[float, ...]:
    """How far every beat has come at `frame`. A frame is drawn from these numbers alone, so two
    frames with the same ones are the same picture.
    """
    resolved = body["resolved"]
    motion = resolved["theme"]["motion"]
    return tuple(
        progress_at(frame, int(resolved["beats"][beat]["frame"]), motion)
        for beat in sorted(resolved["beats"])
    )
