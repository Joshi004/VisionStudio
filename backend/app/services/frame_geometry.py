"""The size to ask the image model for, and how much to cut off the bottom (Phase 17;
FIRST_FRAME_PIPELINE_PHASES.md Section 1.6). Pure: no I/O.

Bitdeer stamps a faint "AI generated" label in a rounded box in the bottom-right corner of
every image, whatever the request says. The frame is therefore made taller than needed, the
bottom band is cut off, and the rest is shrunk to exactly the project's generation size. Only
the height is ever cut, never the width. The sizing rule ("1.5x"):

1. Ask for 1.5 times the generation size, plus a crop band `C` on the height.
2. Cut `C` pixels off the bottom.
3. Resize by exactly 2/3 to the generation size. This is a resize, so nothing is lost at the
   sides.

The box grows with the image's **short side** and keeps its pixel size when only the long side
changes. Measured on lab images (box top, from the bottom edge, as a share of the short side):

    1632 -> 157 px (0.0962)   1600 -> 154 px (0.0963)   1856 -> 179 px (0.0964, Phase 17)
    3072 -> 294 px (0.0957)

`BOX_TOP_PER_10000` is the highest of them, rounded up. The band is the smallest multiple of
16 that clears the box top by `CROP_MARGIN_PX`. For a landscape frame the band is part of the
short side (the height), so it is solved together with the size. If the label ever moves,
change the constants and raise `GEOMETRY_VERSION`: every frame records the version it was
made with.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

GEOMETRY_VERSION: Final = 1
RULE: Final = "1.5x"

# The box's top edge, as parts in 10,000 of the image's short side (the highest measured share
# was 0.0964, so 0.0965).
BOX_TOP_PER_10000: Final = 965
# How far above the box top the cut must be.
CROP_MARGIN_PX: Final = 32
# The cut is a multiple of this.
CROP_STEP_PX: Final = 16
# The video model's sizes are multiples of this, and so is every size a project may have.
SIZE_MULTIPLE: Final = 64


@dataclass(frozen=True)
class FrameGeometry:
    """What to ask the image model for, and what to do with its answer."""

    gen_width: int
    gen_height: int
    request_width: int
    request_height: int
    # Pixels cut off the bottom of the answer.
    crop_bottom: int

    @property
    def request_size(self) -> str:
        """The `size` of the request, for example "1632x3072"."""
        return f"{self.request_width}x{self.request_height}"


def _box_top_px(short_side: int) -> int:
    """The distance of the label box's top edge from the bottom edge, rounded up."""
    return -(-BOX_TOP_PER_10000 * short_side // 10_000)


def crop_band(request_width: int, base_height: int) -> int:
    """The smallest band (a multiple of 16) that clears the label by 32 px, for an image
    `request_width` wide whose height, before the band is added, is `base_height`.
    """
    band = CROP_STEP_PX
    while True:
        short_side = min(request_width, base_height + band)
        if band >= _box_top_px(short_side) + CROP_MARGIN_PX:
            return band
        band += CROP_STEP_PX


def _check_side(name: str, value: int) -> None:
    if value <= 0 or value % SIZE_MULTIPLE != 0:
        raise ValueError(
            f"The generation {name} is {value}, which is not a multiple of {SIZE_MULTIPLE}. "
            "Change it in Project settings."
        )


def frame_geometry(gen_width: int, gen_height: int) -> FrameGeometry:
    """The request size and the crop band for a project's generation size.

    Raises ValueError (with a message for the user) when a side is not a positive multiple of
    64, or when the result would not come back to exactly the generation size.
    """
    _check_side("width", gen_width)
    _check_side("height", gen_height)

    request_width = gen_width * 3 // 2
    base_height = gen_height * 3 // 2
    band = crop_band(request_width, base_height)
    geometry = FrameGeometry(
        gen_width=gen_width,
        gen_height=gen_height,
        request_width=request_width,
        request_height=base_height + band,
        crop_bottom=band,
    )
    check_geometry(geometry)
    return geometry


def check_geometry(geometry: FrameGeometry) -> None:
    """Raises ValueError unless cutting the band and resizing by 2/3 gives exactly the
    generation size.
    """
    cut_height = geometry.request_height - geometry.crop_bottom
    exact = (
        geometry.request_width * 2 == geometry.gen_width * 3
        and cut_height * 2 == geometry.gen_height * 3
        and 0 < geometry.crop_bottom < geometry.request_height
    )
    if not exact:
        raise ValueError(
            f"The frame size {geometry.gen_width} x {geometry.gen_height} cannot be made "
            "exactly from a taller image."
        )
