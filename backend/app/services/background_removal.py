"""Removing the backdrop of a character's reference picture (project cast).

Qwen-Image has no transparent output and no negative prompt, so a character's reference picture
is asked for on a plain white studio backdrop (the `QWEN_IMAGE_21_CHARACTER_SHEET` profile in
`image_prompt_profiles.py`) and the backdrop is cut away here, afterwards. `rembg` is used for
it: a segmentation model that finds the subject, whatever colour the subject is. That is why the
backdrop is white and not a chroma-key green or blue: a key colour would cut into costumes and
skin of the same colour (a blue-skinned god, a green garment), while a segmentation model does
not look at the colour.

Two functions, both blocking: run them through `frame_images.run_pillow`.

- `remove_background`: the picture as a PNG with a transparent backdrop. This is what is stored.
- `flatten_on_white`: that PNG on plain white again, as an RGB PNG. This is what is sent to the
  image model as a reference, because what a server does with transparent pixels is not known,
  while a white backdrop is exactly what the picture was made on.

The model (about 170 MB) is downloaded the first time it is used. `U2NET_HOME` points the
download at the data volume, because the backend's user has no home directory to write to.
"""

from __future__ import annotations

import io
import os
import threading
from pathlib import Path
from typing import Any, Final

from PIL import Image

from app.core.config import get_config

MODEL_NAME: Final = "isnet-general-use"

_session: Any = None
_session_lock = threading.Lock()


class BackgroundRemovalError(Exception):
    """The backdrop could not be removed. The message is meant to be shown to the user."""


def _get_session() -> Any:
    """The model, loaded once. `rembg` and its runtime are imported here, not at start-up,
    because importing them is slow and most runs of the backend never need them.
    """
    global _session
    with _session_lock:
        if _session is None:
            os.environ.setdefault("U2NET_HOME", str(get_config().data_dir / "rembg"))
            from rembg import new_session

            _session = new_session(MODEL_NAME)
        return _session


def remove_background(path: Path) -> bytes:
    """The picture at `path` as an RGBA PNG whose backdrop is transparent.

    Raises BackgroundRemovalError when the model finds no subject at all (every pixel would be
    transparent), because a reference picture with nothing in it is useless.
    """
    try:
        with Image.open(path) as image:
            image.load()
            source = image.convert("RGB")
    except (OSError, ValueError) as exc:
        raise BackgroundRemovalError(f"The picture could not be read: {exc}") from None

    try:
        from rembg import remove

        cut = remove(source, session=_get_session(), post_process_mask=True)
    except Exception as exc:  # the runtime and the model download raise many kinds of error
        raise BackgroundRemovalError(f"The backdrop could not be removed: {exc}") from None

    cut = cut.convert("RGBA")
    if cut.getchannel("A").getextrema()[1] == 0:
        raise BackgroundRemovalError("No character was found in the picture to keep.")
    buffer = io.BytesIO()
    cut.save(buffer, "PNG")
    return buffer.getvalue()


def flatten_on_white(path: Path) -> bytes:
    """The picture at `path` as an RGB PNG, with any transparency replaced by plain white."""
    with Image.open(path) as image:
        image.load()
        rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    flat = Image.alpha_composite(white, rgba).convert("RGB")
    buffer = io.BytesIO()
    flat.save(buffer, "PNG")
    return buffer.getvalue()
