"""The geometry the five templates share, ported from `motion/src/templates/layout.ts` (§4.5.1,
"The template layout"). Lengths are in CSS pixels of the video (1920 x 1080 or 1080 x 1920) and are
rounded where the TypeScript rounds, with `js_round`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

from app.services.graphics_python.motion import js_round, progress_at
from app.services.graphics_python.spec import cannot_draw
from app.services.graphics_templates import FIT_SHARE, LINE_HEIGHT, measure

__all__ = [
    "FIT_SHARE",
    "LINE_HEIGHT",
    "Ctx",
    "beat_frame",
    "change_colour",
    "content_top",
    "enter_of",
    "fit_number",
    "lines_height",
    "make_ctx",
    "measure_of",
    "text_height",
    "text_of",
]

# The share of the height that a part slides up while it enters (§4.5.1).
SLIDE_SHARE: Final = 0.03


@dataclass(frozen=True)
class Ctx:
    frame: int
    width: int
    height: int
    resolved: dict[str, Any]
    theme: dict[str, Any]
    spec: dict[str, Any]
    motion: str
    # The safe area, and its width.
    left: int
    top: int
    right: int
    W: int
    # The title size and the body size of the look rules, before any text is made smaller.
    title_size: int
    body_size: int
    # The lowest y a part may reach: the top of the caption area, less 3 percent of the height.
    bottom: int
    # The width of the thin lines (grid, baseline, node borders).
    stroke: int
    landscape: bool


def make_ctx(frame: int, body: dict[str, Any], spec: dict[str, Any]) -> Ctx:
    width, height = int(body["width"]), int(body["height"])
    resolved = body["resolved"]
    landscape = width >= height
    area = resolved["safe_area"]
    theme = resolved["theme"]
    return Ctx(
        frame=frame,
        width=width,
        height=height,
        resolved=resolved,
        theme=theme,
        spec=spec,
        motion=theme["motion"],
        left=area["left"],
        top=area["top"],
        right=area["right"],
        W=area["right"] - area["left"],
        title_size=js_round((0.06 if landscape else 0.036) * height),
        body_size=js_round((0.032 if landscape else 0.024) * height),
        bottom=resolved["caption_zone"]["top"] - js_round(0.03 * height),
        stroke=max(1, js_round(height / 540)),
        landscape=landscape,
    )


# --- What the resolved brief holds ---------------------------------------------------------------


def beat_frame(ctx: Ctx, beat: str) -> int:
    found = ctx.resolved["beats"].get(beat)
    if found is None:
        raise cannot_draw(f"the beat {beat} is not in the resolved brief.")
    return int(found["frame"])


def enter_of(ctx: Ctx, beat: str) -> float:
    """How far the part that enters on `beat` has come, from 0 to 1."""
    return progress_at(ctx.frame, beat_frame(ctx, beat), ctx.motion)


def measure_of(ctx: Ctx, ref: str) -> dict[str, Any]:
    found = ctx.resolved["facts"].get(ref) or ctx.resolved["derived"].get(ref)
    if found is None:
        raise cannot_draw(f"{ref} is not a fact or a derived value.")
    return found


def text_of(ctx: Ctx, path: str) -> dict[str, Any]:
    found = ctx.spec["text"].get(path)
    if found is None:
        raise cannot_draw(f'the spec has no layout for the text "{path}".')
    return found


# --- Sizes ---------------------------------------------------------------------------------------


def text_height(size: float, lines: int = 1) -> float:
    return lines * size * LINE_HEIGHT


def lines_height(layout: dict[str, Any]) -> float:
    return text_height(layout["size"], len(layout["lines"]))


def content_top(ctx: Ctx) -> int:
    """The top of the content box: below the title when there is one."""
    title = ctx.spec["text"].get("title")
    if title is None:
        return ctx.top
    return ctx.top + js_round(lines_height(title)) + js_round(0.04 * ctx.height)


def fit_number(text: str, base: int, space: float) -> int:
    """The size a number is drawn at: `base`, or the largest whole pixel size at which its final
    text is within 97 percent of its space. The text of a number is written by code and is not
    split. Measured in the display font, as GFX-006 measures every text.
    """
    width = measure(text, "display", base)
    limit = space * FIT_SHARE
    return base if width <= limit else max(1, math.floor(base * limit / width))


def change_colour(ctx: Ctx, value: float) -> str:
    """The colour of a change: `positive` above zero, `negative` below, `text` at zero."""
    if value > 0:
        return ctx.theme["positive"]
    if value < 0:
        return ctx.theme["negative"]
    return ctx.theme["text"]
