"""The pictures of the thumbnail flow, drawn with Pillow.

Two jobs:

- `frame_jpeg` makes a small JPEG of a frame of the video, to send to the vision model with the
  request that writes the concepts.
- `compose` makes the finished thumbnail: the picture the image model made, fitted to the
  thumbnail size, with the headline drawn in the area the concept left empty for it. The
  headline is drawn by code, not by the image model, so its spelling is always right and the
  owner can change it later without a GPU run.

The text is only ever drawn as pixels from the bundled font; it is never put into a command or
a filter. Blocking work is run through `frame_images.run_pillow`.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from app.services import font_metrics, frame_images

# The size of the finished thumbnail for each orientation of a project (width, height).
LANDSCAPE_SIZE: Final = (1280, 720)
PORTRAIT_SIZE: Final = (720, 1280)

# A frame sent to the vision model: its longest side and the most bytes of JPEG. Four frames go
# in one request, and the paid endpoint is known to refuse an image request over about 1 MB
# (`services/photo_describer.py`), so each frame is kept small.
FRAME_MAX_SIDE_PX: Final = 768
FRAME_MAX_JPEG_BYTES: Final = 150_000
_FRAME_QUALITIES: Final = (80, 70, 60, 50, 40)

# The headline: at most this many lines, in white with a black outline unless an accent is given.
MAX_LINES: Final = 2
_DEFAULT_FILL: Final = (255, 255, 255)
_OUTLINE: Final = (0, 0, 0)
_ACCENT: Final = re.compile(r"#[0-9A-Fa-f]{6}")
_MAX_FONT_SHARE: Final = 0.30  # of the picture's height
_MIN_FONT_PX: Final = 14
_OUTLINE_SHARE: Final = 0.12  # of the font size
_LINE_SPACING: Final = 1.1

# Where each text area is, as (left, top, right, bottom) shares of the picture.
_AREAS: Final[dict[str, tuple[float, float, float, float]]] = {
    "left": (0.04, 0.08, 0.50, 0.92),
    "right": (0.50, 0.08, 0.96, 0.92),
    "top": (0.04, 0.05, 0.96, 0.40),
    "bottom": (0.04, 0.60, 0.96, 0.95),
    "top_left": (0.04, 0.05, 0.55, 0.45),
    "top_right": (0.45, 0.05, 0.96, 0.45),
    "bottom_left": (0.04, 0.55, 0.55, 0.95),
    "bottom_right": (0.45, 0.55, 0.96, 0.95),
}


class ThumbnailPictureError(ValueError):
    """A picture that cannot be made or used. The message is meant to be shown to the user."""


def size_for(orientation: str) -> tuple[int, int]:
    """The thumbnail's size for a project's orientation (`portrait` or `landscape`)."""
    return PORTRAIT_SIZE if orientation == "portrait" else LANDSCAPE_SIZE


def valid_accent(accent: str | None) -> str | None:
    """`accent` when it is a `#RRGGBB` colour, otherwise None."""
    return accent if isinstance(accent, str) and _ACCENT.fullmatch(accent) else None


# --- A frame for the model -----------------------------------------------------------------


def _frame_jpeg(path: Path) -> bytes:
    try:
        with Image.open(path) as image:
            image.load()
            picture = image.convert("RGB")
    except (OSError, ValueError) as exc:
        raise ThumbnailPictureError(f"The frame could not be read: {exc}") from None
    picture.thumbnail((FRAME_MAX_SIDE_PX, FRAME_MAX_SIDE_PX))
    for quality in _FRAME_QUALITIES:
        buffer = io.BytesIO()
        picture.save(buffer, "JPEG", quality=quality)
        if buffer.tell() <= FRAME_MAX_JPEG_BYTES:
            return buffer.getvalue()
    raise ThumbnailPictureError("The frame is too detailed to send.")


async def frame_jpeg(path: Path) -> bytes:
    """The frame at `path` as a small JPEG. Raises ThumbnailPictureError."""
    return await frame_images.run_pillow(_frame_jpeg, path)


# --- The finished thumbnail ----------------------------------------------------------------


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_metrics.FONT_FILE), max(_MIN_FONT_PX, size))


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """The text broken into lines no wider than `width` where it can be (a word wider than that
    stays on a line of its own).
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _layout(
    canvas: ImageDraw.ImageDraw, text: str, box_width: float, box_height: float, picture_height: int
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """The largest font in which the text fits the box in at most `MAX_LINES` lines. Returns
    the font, the lines and the outline width. When nothing fits, the smallest size is used.
    """
    size = round(picture_height * _MAX_FONT_SHARE)
    while True:
        font = _font(size)
        outline = max(2, round(font.size * _OUTLINE_SHARE))
        lines = _wrap(text, font, box_width - 2 * outline)
        widest = max(
            (canvas.textbbox((0, 0), line, font=font, stroke_width=outline)[2] for line in lines),
            default=0,
        )
        block = len(lines) * font.size * _LINE_SPACING
        fits = len(lines) <= MAX_LINES and widest <= box_width and block <= box_height
        if fits or font.size <= _MIN_FONT_PX:
            return font, lines, outline
        size -= 2


def _compose(
    source: Path,
    dest: Path,
    width: int,
    height: int,
    headline: str,
    text_area: str,
    accent: str | None,
) -> None:
    try:
        with Image.open(source) as opened:
            opened.load()
            picture = frame_images.normalise_frame(opened, width, height)
    except (OSError, ValueError) as exc:
        raise ThumbnailPictureError(f"The picture could not be read: {exc}") from None

    text = " ".join(headline.split())
    area = _AREAS.get(text_area)
    if text and area is not None:
        canvas = ImageDraw.Draw(picture)
        left, top, right, bottom = (
            area[0] * width,
            area[1] * height,
            area[2] * width,
            area[3] * height,
        )
        box_width, box_height = right - left, bottom - top
        font, lines, outline = _layout(canvas, text, box_width, box_height, height)
        line_height = font.size * _LINE_SPACING
        block = len(lines) * line_height
        if "top" in text_area:
            y = top
        elif "bottom" in text_area:
            y = bottom - block
        else:
            y = top + (box_height - block) / 2
        fill = tuple(int(accent[i : i + 2], 16) for i in (1, 3, 5)) if accent else _DEFAULT_FILL
        for line in lines:
            line_width = canvas.textbbox((0, 0), line, font=font, stroke_width=outline)[2]
            if "left" in text_area:
                x = left
            elif "right" in text_area:
                x = right - line_width
            else:
                x = left + (box_width - line_width) / 2
            canvas.text(
                (x, y),
                line,
                font=font,
                fill=fill,
                stroke_width=outline,
                stroke_fill=_OUTLINE,
            )
            y += line_height

    with dest.open("xb") as file:
        picture.save(file, format="PNG")


async def compose(
    source: Path,
    dest: Path,
    *,
    width: int,
    height: int,
    headline: str,
    text_area: str,
    accent: str | None = None,
) -> None:
    """Writes the finished thumbnail as a new PNG file at `dest` (created with "xb", never over
    an existing file): the picture at `source`, centre-cropped to `width` x `height`, with the
    headline drawn in `text_area` (an empty headline draws nothing). `accent` is the fill of
    the text as `#RRGGBB`, white when it is None. Raises ThumbnailPictureError.
    """
    await frame_images.run_pillow(
        _compose, source, dest, width, height, headline, text_area, valid_accent(accent)
    )
