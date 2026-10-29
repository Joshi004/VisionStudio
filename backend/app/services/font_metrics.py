"""The bundled caption font, and how wide a text is in it (EXPLAINER-008, EXPLAINER-010).

The callouts are laid out before anything is rendered, so their lines are measured here with the
same font file libass is given.

**Sizes are ASS font sizes.** libass takes the size of a line (`\\fs`) as the height of the font's
cell, which is the font's `usWinAscent` plus `usWinDescent`, not the size of the em. `measure`
therefore gives the width a text has when it is drawn with `\\fs` set to `size`, and the height
of a line is `size`. This was checked against libass: a text drawn at `\\fs100` is within one
percent of the width given here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final

from PIL import ImageFont

# The fonts the captions and callouts are drawn with, bundled with the app, so a render looks the
# same on any machine. libass is pointed at the folder (`render_commands.subtitles_filter`).
FONTS_DIR: Final = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FONT_FILE: Final = FONTS_DIR / "Montserrat-ExtraBold.ttf"

# The size the font is read at: large, so the widths are exact to a fraction of a pixel after
# scaling down.
_REFERENCE_SIZE: Final = 1000


@lru_cache(maxsize=1)
def _font() -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_FILE), _REFERENCE_SIZE)


# `usWinAscent` (1109) plus `usWinDescent` (453) of Montserrat ExtraBold, in the font's 1000 units
# per em. They are the font file's own numbers: change them with the file.
_CELL_UNITS: Final = 1109 + 453
_UNITS_PER_EM: Final = 1000


def measure(text: str, size: int) -> float:
    """The width in pixels of `text` on one line, drawn with the ASS font size `size`."""
    em_widths = float(_font().getlength(text)) / _REFERENCE_SIZE
    return em_widths * max(1, size) * _UNITS_PER_EM / _CELL_UNITS
