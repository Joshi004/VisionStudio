"""The image model: Qwen-Image-2.1 on the GPU server. Pure functions, no I/O.

Qwen-Image-2.1 has two modes, and they are two different checkpoints (so one seed gives a
different picture in each):

- `quality`: the base checkpoint. 40 denoising steps unless a request says otherwise.
- `fast`: the Turbo checkpoint. Always 8 steps.

It makes only seven picture shapes, all at its native 2K size (`ASPECT_SIZES`). A project's
generation size is not one of them, so `pick_aspect_ratio` chooses the nearest shape and the
frame is then fitted to the generation size by `services/frame_images.normalise_frame`.

The ids here are what the settings store. The request itself is built in
`providers/image_generator.py`.
"""

from __future__ import annotations

import math
from typing import Final, Literal, TypeGuard, get_args

ImageMode = Literal["quality", "fast"]

MODE_IDS: Final[tuple[ImageMode, ...]] = get_args(ImageMode)
LABELS: Final[dict[ImageMode, str]] = {
    "quality": "Quality (base model, 40 steps)",
    "fast": "Fast (Turbo model, 8 steps)",
}
# Used when the saved setting is somehow not a known mode.
DEFAULT_MODE: Final[ImageMode] = "quality"
# The global setting that holds the mode.
IMAGE_MODE_KEY: Final = "image_mode"

# What is recorded on an asset that this model made.
MODEL_ID: Final = "qwen-image-2.1"
MODEL_LABEL: Final = "Qwen-Image-2.1"

# The seven shapes the model makes, with the pixel size of each (width, height).
ASPECT_SIZES: Final[dict[str, tuple[int, int]]] = {
    "1:1": (2048, 2048),
    "4:3": (2400, 1792),
    "3:4": (1792, 2400),
    "3:2": (2528, 1696),
    "2:3": (1696, 2528),
    "16:9": (2752, 1536),
    "9:16": (1536, 2752),
}
ASPECT_RATIOS: Final[tuple[str, ...]] = tuple(ASPECT_SIZES)

# Seeds are drawn below this, so they fit the server's field (0 to 2147483647).
SEED_LIMIT: Final = 2**31


def is_image_mode(value: object) -> TypeGuard[ImageMode]:
    return isinstance(value, str) and value in MODE_IDS


def resolve_mode(value: object) -> ImageMode:
    """The mode to use for a saved setting. A value that is not a known mode gives the default."""
    return value if is_image_mode(value) else DEFAULT_MODE


def label(mode: object) -> str:
    """The name to show for a mode id. An unknown value is shown as it is."""
    return LABELS[mode] if is_image_mode(mode) else str(mode)


def pick_aspect_ratio(width: int, height: int) -> str:
    """The model's shape that is nearest to `width` x `height`, compared by the ratio of the
    two sides (so 1088 x 1920 gives 9:16 and 1920 x 1088 gives 16:9).

    Raises ValueError for a side that is not positive.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"The frame size {width} x {height} is not valid.")
    target = math.log(width / height)
    return min(
        ASPECT_SIZES,
        key=lambda ratio: abs(math.log(ASPECT_SIZES[ratio][0] / ASPECT_SIZES[ratio][1]) - target),
    )
