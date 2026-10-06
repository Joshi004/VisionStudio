"""Checking and normalising frame images (ANALYSIS.md Section 5.3 and 5.9).

A frame is the first or last image of a scene. Two jobs live here, and both use Pillow:

- `inspect_image` decides whether an upload is an acceptable frame: a real PNG, JPEG or
  WebP (decided from the file's content, never its name), within the pixel limit, not
  animated, and fully readable.
- `normalise_frame` turns any accepted image into exactly what the video model gets:
  upright, RGB, centre-cropped to the generation aspect ratio and resized to the
  generation size. The preview in the page and (from Phase 9) the file sent to the GPU
  server both come from this one function, so the page shows what will be sent.

Only the original upload is stored. The normalised image is made on demand, because the
generation size can change after an upload.

Pillow work is blocking, so callers run it through `run_pillow`, which keeps it off the
event loop and allows only a couple of images in memory at once.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import anyio.to_thread
from PIL import Image, ImageOps, UnidentifiedImageError

FRAME_MAX_MB: Final = 40
FRAME_MAX_BYTES: Final = FRAME_MAX_MB * 1024 * 1024
FRAME_MAX_PIXELS: Final = 40_000_000
_MEGAPIXEL: Final = 1_000_000

# Bump when `normalise_frame` changes what it produces, so cached previews are not reused.
NORMALISE_VERSION: Final = 1

PREVIEW_JPEG_QUALITY: Final = 92

# Warn (never refuse) when more than this share of a side is cropped away, or when the image
# has to be enlarged by more than this share.
_WARN_CROP_SHARE: Final = 0.10
_WARN_ENLARGE_SHARE: Final = 0.10

# Pillow opens a JPEG that carries extra images (what many cameras and phones write for an
# ordinary photo) as "MPO" by itself, so MPO is not listed here. Only its first image is used.
_FORMATS: Final = ["PNG", "JPEG", "WEBP"]
_ANIMATED_FORMATS: Final = frozenset({"PNG", "WEBP"})
_EXIF_ORIENTATION: Final = 0x0112
# EXIF orientations that turn the image by a quarter, so width and height swap.
_QUARTER_TURNS: Final = frozenset({5, 6, 7, 8})

_SIXTEEN_BIT_MODES: Final = frozenset({"I", "I;16", "I;16L", "I;16B"})

_TOO_MANY_PIXELS: Final = f"The limit is {FRAME_MAX_PIXELS // _MEGAPIXEL} megapixels."

# At most this many images are decoded at the same time (an 8K image takes about 100 MB).
_PILLOW_SLOTS: Final = asyncio.Semaphore(2)


class FrameRejected(Exception):
    """An upload that is refused. The message is meant to be shown to the user."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class ImageInfo:
    ext: str
    mime: str
    # The size as displayed, after the EXIF orientation is applied.
    width: int
    height: int


# Pillow's format name -> the stored file extension and MIME type.
_STORED_AS: Final[dict[str, tuple[str, str]]] = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "MPO": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
}


async def run_pillow[T](fn: Callable[..., T], *args: object) -> T:
    """Runs blocking Pillow work in a thread, two at a time."""
    async with _PILLOW_SLOTS:
        return await anyio.to_thread.run_sync(fn, *args)


def inspect_image(path: Path) -> ImageInfo:
    """Checks that the file is an acceptable frame and reads its format and size.

    Blocking: run it through `run_pillow`. Raises FrameRejected (422) with a message for
    the user. The whole image is decoded once, so a truncated or damaged file is caught
    here and not later, when a preview or a GPU run needs it.
    """
    try:
        with Image.open(path, formats=_FORMATS) as image:
            return _inspect(image)
    except FrameRejected:
        raise
    except Image.DecompressionBombError:
        raise FrameRejected(422, f"The image has far too many pixels. {_TOO_MANY_PIXELS}") from None
    except UnidentifiedImageError:
        raise FrameRejected(422, "Upload a PNG, JPEG or WebP image.") from None
    except OSError:
        raise FrameRejected(422, "The image could not be read. It may be damaged.") from None


def _inspect(image: Image.Image) -> ImageInfo:
    width, height = image.size
    if width * height > FRAME_MAX_PIXELS:
        megapixels = round(width * height / _MEGAPIXEL)
        raise FrameRejected(
            422, f"The image is {width} x {height} ({megapixels} megapixels). {_TOO_MANY_PIXELS}"
        )
    image_format = image.format or ""
    if image_format not in _STORED_AS:
        raise FrameRejected(422, "Upload a PNG, JPEG or WebP image.")
    if image_format in _ANIMATED_FORMATS and getattr(image, "is_animated", False):
        raise FrameRejected(422, "Animated images cannot be used as frames.")

    try:
        image.load()
        orientation = image.getexif().get(_EXIF_ORIENTATION)
    except Exception:  # Pillow raises many kinds of error for a damaged file.
        raise FrameRejected(422, "The image could not be read. It may be damaged.") from None
    if orientation in _QUARTER_TURNS:
        width, height = height, width

    ext, mime = _STORED_AS[image_format]
    return ImageInfo(ext=ext, mime=mime, width=width, height=height)


def _to_rgb(image: Image.Image) -> Image.Image:
    """RGB, whatever the mode: 16-bit scaled down, transparency flattened onto white."""
    if image.mode in _SIXTEEN_BIT_MODES:
        # Converting directly would turn every value above 255 white.
        image = image.point(lambda value: value * (1 / 256)).convert("L")
        image.info.pop("transparency", None)
    if image.has_transparency_data:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(white, rgba)
    return image.convert("RGB")


def normalise_frame(image: Image.Image, width: int, height: int) -> Image.Image:
    """The image as the video model gets it: upright, RGB, centre-cropped to the aspect
    ratio of `width` x `height` and resized to exactly that size (ANALYSIS.md Section 5.3).

    Pure: no files. `image` must be loaded, and is not changed.
    """
    upright = ImageOps.exif_transpose(image)
    return ImageOps.fit(
        _to_rgb(upright),
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def frame_warnings(width: int, height: int, gen_width: int, gen_height: int) -> list[str]:
    """What the user should know about fitting a `width` x `height` image to the generation
    size. Warnings only: nothing is refused for them.
    """
    if width <= 0 or height <= 0:
        return []
    # The image is scaled until it covers the target, then the overflow is cropped away.
    scale = max(gen_width / width, gen_height / height)
    warnings: list[str] = []

    cropped_width = 1 - gen_width / (width * scale)
    cropped_height = 1 - gen_height / (height * scale)
    if cropped_width > _WARN_CROP_SHARE:
        warnings.append(
            f"About {round(cropped_width * 100)}% of the image's width is cropped away to fit "
            f"{gen_width} x {gen_height}."
        )
    if cropped_height > _WARN_CROP_SHARE:
        warnings.append(
            f"About {round(cropped_height * 100)}% of the image's height is cropped away to fit "
            f"{gen_width} x {gen_height}."
        )
    if scale > 1 + _WARN_ENLARGE_SHARE:
        warnings.append(
            f"The image is smaller than {gen_width} x {gen_height} and is enlarged by "
            f"{round((scale - 1) * 100)}%, so it may look soft."
        )
    return warnings


def render_preview_jpeg(path: Path, width: int, height: int) -> bytes:
    """The normalised frame as a JPEG, for the page. Blocking: run it through `run_pillow`.

    The framing and size are exactly what Phase 9 sends. Only the file format differs:
    Phase 9 sends a lossless PNG.
    """
    with Image.open(path, formats=_FORMATS) as image:
        image.load()
        normalised = normalise_frame(image, width, height)
    buffer = io.BytesIO()
    normalised.save(buffer, "JPEG", quality=PREVIEW_JPEG_QUALITY)
    return buffer.getvalue()
