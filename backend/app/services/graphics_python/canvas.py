"""The drawing primitives of the Python templates, on Pillow.

**Supersampling.** Pillow draws shapes and text without smooth edges of its own, so a frame is
drawn at `SCALE` times its size and reduced with a box filter (`Canvas.rgb_bytes`). Every method
takes lengths in the CSS pixels of the video and multiplies them by `SCALE`.

**Like the browser.** The templates were first drawn by Chrome (GFX-007), and this file does what
Chrome does where it matters for the same picture:

- A box (`rect`) has its edges rounded to whole pixels, as Chrome snaps a box; shapes with a
  slant (`line`, `polygon`, `ellipse`) keep their exact edges and are smooth.
- A line of text sits in a line box `1.2 x size` high, with its baseline where CSS puts it (the
  font's ascent and descent are rounded to whole pixels first, as Blink does), and the baseline
  is a whole pixel.
- A part that enters (`layer`) is faded as a group: what is shown is `p` of the part drawn over
  the picture beneath, plus `1 - p` of the picture, like CSS `opacity`. It slides up as it comes.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from functools import lru_cache
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from app.services.font_metrics import FONTS_DIR
from app.services.graphics_python.motion import js_round
from app.services.graphics_templates import FONT_FILES, LINE_HEIGHT

SCALE: Final = 3
_REFERENCE_SIZE: Final = 1000

Point = tuple[float, float]


@lru_cache(maxsize=64)
def font_at(role: str, pixels: int) -> ImageFont.FreeTypeFont:
    """The font `role` (`display` or `text`) at `pixels` pixels (already multiplied by SCALE)."""
    return ImageFont.truetype(str(FONTS_DIR / FONT_FILES[role]), pixels)


@lru_cache(maxsize=2)
def _line_metrics(role: str) -> tuple[float, float]:
    """The font's ascent and descent as shares of the font size."""
    ascent, descent = font_at(role, _REFERENCE_SIZE).getmetrics()
    return ascent / _REFERENCE_SIZE, descent / _REFERENCE_SIZE


def baseline_of(role: str, size: int, top: float) -> int:
    """The baseline of a line of text whose line box (`1.2 x size` high) starts at `top`: the
    content area (ascent plus descent, each rounded to whole pixels) is centred in the box.
    """
    ascent_share, descent_share = _line_metrics(role)
    ascent = js_round(ascent_share * size)
    descent = js_round(descent_share * size)
    return js_round(top + (size * LINE_HEIGHT - (ascent + descent)) / 2 + ascent)


def rgba(colour: str, alpha: float = 1.0) -> tuple[int, int, int, int]:
    """`#RRGGBB` and an opacity from 0 to 1, as the four numbers Pillow draws with."""
    return (
        int(colour[1:3], 16),
        int(colour[3:5], 16),
        int(colour[5:7], 16),
        js_round(alpha * 255),
    )


def _scaled(value: float) -> int:
    return js_round(value * SCALE)


class Canvas:
    """One frame, drawn at `SCALE` times its size over a copy of the background."""

    def __init__(self, background: Image.Image, slide: float):
        self._image = background.copy()
        self._draw = ImageDraw.Draw(self._image, "RGBA")
        # How far a part slides up while it enters, in CSS pixels (3 percent of the height).
        self._slide = slide
        # The drop of the part being drawn (`layer`), and whether nothing is to be drawn.
        self._dy = 0.0
        self._hidden = False

    def rgb_bytes(self) -> bytes:
        """The frame at its own size, as raw RGB rows (what FFmpeg reads)."""
        return self._image.reduce(SCALE).tobytes()

    # --- Parts that enter ------------------------------------------------------------------------

    @contextmanager
    def layer(self, p: float, *, slide: bool = False) -> Iterator[None]:
        """What is drawn inside enters as far as `p` (0 to 1) says. At 0 nothing is drawn, at 1 it
        is drawn as it is. In between it is faded as a group and, with `slide`, is lower by
        `(1 - p)` of the slide.
        """
        if p <= 0:
            was_hidden, self._hidden = self._hidden, True
            try:
                yield
            finally:
                self._hidden = was_hidden
            return
        if p >= 1:
            yield
            return
        below = self._image
        was_dy = self._dy
        self._image = below.copy()
        self._draw = ImageDraw.Draw(self._image, "RGBA")
        self._dy = (1 - p) * self._slide if slide else 0.0
        try:
            yield
        finally:
            self._image = Image.blend(below, self._image, p)
            self._draw = ImageDraw.Draw(self._image, "RGBA")
            self._dy = was_dy

    # --- Shapes ----------------------------------------------------------------------------------

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        colour: str,
        *,
        radius: float = 0.0,
        alpha: float = 1.0,
    ) -> None:
        """A box, its edges on whole pixels. The corners are as round as `radius` says, never more
        than half the shorter side.
        """
        if self._hidden:
            return
        left, right = js_round(x), js_round(x + width)
        top, bottom = js_round(y), js_round(y + height)
        if right <= left or bottom <= top:
            return
        box = (
            left * SCALE,
            _scaled(top + self._dy),
            right * SCALE - 1,
            _scaled(bottom + self._dy) - 1,
        )
        corner = min(radius, (right - left) / 2, (bottom - top) / 2) * SCALE
        fill = rgba(colour, alpha)
        if corner >= 1:
            self._draw.rounded_rectangle(box, radius=round(corner), fill=fill)
        else:
            self._draw.rectangle(box, fill=fill)

    def polygon(self, points: Sequence[Point], colour: str, *, alpha: float = 1.0) -> None:
        if self._hidden:
            return
        shifted = [(px * SCALE, (py + self._dy) * SCALE) for px, py in points]
        self._draw.polygon(shifted, fill=rgba(colour, alpha))

    def ellipse(
        self, cx: float, cy: float, radius: float, colour: str, *, alpha: float = 1.0
    ) -> None:
        if self._hidden or radius <= 0:
            return
        box = (
            _scaled(cx - radius),
            _scaled(cy + self._dy - radius),
            _scaled(cx + radius) - 1,
            _scaled(cy + self._dy + radius) - 1,
        )
        self._draw.ellipse(box, fill=rgba(colour, alpha))

    def line(
        self,
        start: Point,
        end: Point,
        width: float,
        colour: str,
        *,
        round_caps: bool = False,
    ) -> None:
        """A straight line `width` thick, with flat or round ends."""
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        half = width / 2
        if length > 0:
            nx, ny = -dy / length * half, dx / length * half
            self.polygon(
                [
                    (start[0] + nx, start[1] + ny),
                    (end[0] + nx, end[1] + ny),
                    (end[0] - nx, end[1] - ny),
                    (start[0] - nx, start[1] - ny),
                ],
                colour,
            )
        if round_caps:
            self.ellipse(start[0], start[1], half, colour)
            self.ellipse(end[0], end[1], half, colour)

    def polyline(self, points: Sequence[Point], width: float, colour: str) -> None:
        """Lines through the points with round joins and ends."""
        for start, end in zip(points, points[1:], strict=False):
            self.line(start, end, width, colour, round_caps=True)

    # --- Text ------------------------------------------------------------------------------------

    def text(
        self,
        text: str,
        role: str,
        size: int,
        colour: str,
        *,
        x: float,
        top: float,
        align: str = "left",
    ) -> None:
        """One line of text in a line box that starts at `top`. `x` is where the text starts
        (`left`), ends (`right`) or is centred (`center`).
        """
        if self._hidden or not text:
            return
        anchor = {"left": "ls", "center": "ms", "right": "rs"}[align]
        position = (_scaled(x), _scaled(baseline_of(role, size, top) + self._dy))
        self._draw.text(
            position, text, font=font_at(role, size * SCALE), fill=rgba(colour), anchor=anchor
        )
