"""The four backgrounds of the theme (§4.5.1), drawn over the whole frame, the caption area
included. They do not move, so each is built once for a render, at `SCALE` times the size, and
every frame starts from a copy of it. Ported from `motion/src/templates/Background.tsx`.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from app.services.graphics_python.canvas import SCALE, rgba
from app.services.graphics_python.motion import js_round


def _rgb(colour: str) -> tuple[int, int, int]:
    red, green, blue, _alpha = rgba(colour)
    return red, green, blue


def build_background(theme: dict[str, Any], width: int, height: int) -> Image.Image:
    """The theme's background as an RGB picture of the video's size times `SCALE`."""
    size = (width * SCALE, height * SCALE)
    base = _rgb(theme["background"])
    style = theme["background_style"]
    if style == "gradient":
        return _gradient(base, _rgb(theme["surface"]), size)
    if style == "grid":
        return _grid(base, _rgb(theme["surface"]), width, height)
    if style == "glow":
        return _glow(base, _rgb(theme["accent"]), width, height)
    return Image.new("RGB", size, base)


def _gradient(top: tuple[int, int, int], bottom: tuple[int, int, int], size: tuple[int, int]):
    """A vertical gradient from `background` at the top to `surface` at the bottom."""
    width, height = size
    shares = ((np.arange(height) + 0.5) / height)[:, None]
    column = np.rint(np.array(top) + (np.array(bottom) - np.array(top)) * shares)
    rows = np.repeat(column.astype(np.uint8)[:, None, :], width, axis=1)
    return Image.fromarray(rows, "RGB")


def _grid(base: tuple[int, int, int], line: tuple[int, int, int], width: int, height: int):
    """`surface` lines `max(1, round(h / 540))` thick every `round(0.08 h)`, from the top left
    corner.
    """
    image = Image.new("RGB", (width * SCALE, height * SCALE), base)
    draw = ImageDraw.Draw(image)
    step = js_round(0.08 * height)
    thickness = max(1, js_round(height / 540))
    for y in range(0, height, step):
        draw.rectangle((0, y * SCALE, width * SCALE - 1, (y + thickness) * SCALE - 1), fill=line)
    for x in range(0, width, step):
        draw.rectangle((x * SCALE, 0, (x + thickness) * SCALE - 1, height * SCALE - 1), fill=line)
    return image


def _glow(base: tuple[int, int, int], accent: tuple[int, int, int], width: int, height: int):
    """A circular glow of `accent` at 8 percent opacity in the centre, fading out linearly to 0 at
    a radius of `round(0.6 x max(width, height))`. Smooth, so it is made at the video's size and
    stretched.
    """
    radius = js_round(0.6 * max(width, height))
    xs = (np.arange(width) + 0.5 - width / 2)[None, :]
    ys = (np.arange(height) + 0.5 - height / 2)[:, None]
    alpha = 0.08 * np.clip(1 - np.hypot(xs, ys) / radius, 0, 1)[:, :, None]
    mixed = np.array(base) + (np.array(accent) - np.array(base)) * alpha
    small = Image.fromarray(np.rint(mixed).astype(np.uint8), "RGB")
    return small.resize((width * SCALE, height * SCALE), Image.Resampling.BILINEAR)
