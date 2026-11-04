"""The picture a scene render shows for a shot that has no clip yet (SCN-003).

A plain dark frame at the output size with, centred: which shot it is ("Scene 3 · Shot 2 of 7
(shot_5)"), why there is no clip ("No clip yet"), the shot's one-sentence description from its
plan, and how long it lasts. It is drawn with the bundled caption font, so it looks the same on
any machine. The file is a PNG that `render_commands.placeholder_args` turns into the shot's
frames.

The text only ever comes from the shot plan and this app; it is drawn as pixels, never put into
a command or a filter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from app.services import font_metrics

_BACKGROUND: Final = (34, 36, 40)
_TITLE_COLOUR: Final = (240, 240, 240)
_REASON_COLOUR: Final = (255, 196, 64)
_TEXT_COLOUR: Final = (200, 204, 210)
# Sizes as a share of the picture's height; the text block as a share of its width.
_TITLE_SIZE: Final = 0.055
_REASON_SIZE: Final = 0.045
_TEXT_SIZE: Final = 0.04
_BLOCK_WIDTH: Final = 0.84
_MAX_TEXT_LINES: Final = 6
_GAP: Final = 0.4


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_metrics.FONT_FILE), max(8, size))


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """The text broken into lines no wider than `width`, at most `_MAX_TEXT_LINES` of them (the
    last one ends with "..." when the text is longer).
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
    if len(lines) > _MAX_TEXT_LINES:
        lines = lines[:_MAX_TEXT_LINES]
        lines[-1] = lines[-1].rstrip(".") + "..."
    return lines


def draw(
    dest: Path,
    width: int,
    height: int,
    *,
    title: str,
    reason: str,
    description: str | None,
    seconds: float,
) -> None:
    """Writes the placeholder as a new PNG file at `dest` (created with "xb", never over an
    existing file).
    """
    image = Image.new("RGB", (width, height), _BACKGROUND)
    canvas = ImageDraw.Draw(image)
    block_width = width * _BLOCK_WIDTH

    title_font = _font(round(height * _TITLE_SIZE))
    reason_font = _font(round(height * _REASON_SIZE))
    text_font = _font(round(height * _TEXT_SIZE))

    rows: list[tuple[str, ImageFont.FreeTypeFont, tuple[int, int, int]]] = []
    for line in _wrap(title, title_font, block_width):
        rows.append((line, title_font, _TITLE_COLOUR))
    rows.append((reason, reason_font, _REASON_COLOUR))
    if description:
        for line in _wrap(description, text_font, block_width):
            rows.append((line, text_font, _TEXT_COLOUR))
    rows.append((f"{seconds:.2f} s", text_font, _TEXT_COLOUR))

    heights = [round(font.size * (1 + _GAP)) for _, font, _ in rows]
    top = (height - sum(heights)) / 2
    for (line, font, colour), line_height in zip(rows, heights, strict=True):
        left = (width - font.getlength(line)) / 2
        canvas.text((left, top), line, font=font, fill=colour)
        top += line_height

    with dest.open("xb") as file:
        image.save(file, format="PNG")
