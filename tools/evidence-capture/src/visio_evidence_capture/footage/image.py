"""Capture of a picture (the footage `image` command): fetch it, check what it is, store it."""

from __future__ import annotations

import io
import os
from urllib.parse import urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

from .. import MAX_IMAGE_BYTES
from ..netguard import check_url, fetch_image
from ..rounds import sha256_of
from . import LOW_RES_LONG_SIDE, MAX_IMAGE_PIXELS, TOOL_NAME, TOOL_VERSION
from .rounds import Captured, Described, FootageRound, Refused, file_names, piece_entry

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_QUALITY = 95
EXIF_ORIENTATION = 0x0112
CONTACT_ENV = "VISIO_FOOTAGE_CONTACT"
CONTACT_MAX_CHARS = 200


def sniff(data: bytes) -> str | None:
    """`JPEG`, `PNG` or `WEBP` from the first bytes, or None. A name or a content type is never
    trusted."""
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith(PNG_SIGNATURE):
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def _png(image: Image.Image) -> bytes:
    if image.mode not in ("RGB", "RGBA", "L", "LA"):
        image = image.convert(
            "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


def prepare_image(data: bytes) -> tuple[bytes, str, tuple[int, int], list[str]]:
    """Check a fetched picture and return what is stored: its bytes, the file kind (`png` or
    `jpeg`), its size in pixels and notes for the agent. The header is read first, so a picture
    with too many pixels is refused before it is decoded. WebP is stored as PNG. A JPEG that a
    camera turned (EXIF orientation) is stored upright, so that the stored size is what is shown.
    Any other picture is stored as it came.
    """
    found = sniff(data)
    if found is None:
        raise Refused(
            "That address did not give a JPEG, PNG or WebP picture. For a web page, use the "
            "page command."
        )
    notes: list[str] = []
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != found:
                raise Refused("The picture's type does not match its content.")
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                raise Refused(
                    f"The picture is {width}x{height}, over the limit of "
                    f"{MAX_IMAGE_PIXELS // 1_000_000} million pixels."
                )
            if found == "WEBP":
                image.load()
                stored, kind = _png(image), "png"
                notes.append("The WebP picture is stored as PNG.")
            elif found == "JPEG" and image.getexif().get(EXIF_ORIENTATION, 1) != 1:
                upright = ImageOps.exif_transpose(image)
                stored, kind = _jpeg(upright), "jpeg"
                notes.append("The JPEG was turned upright (its EXIF orientation) and saved again.")
                width, height = upright.size
            else:
                image.load()
                stored, kind = data, "png" if found == "PNG" else "jpeg"
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as error:
        raise Refused(f"The picture cannot be read: {error}") from error
    if len(stored) > MAX_IMAGE_BYTES:
        raise Refused(f"The picture is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
    return stored, kind, (width, height), notes


def contact_from_env() -> str | None:
    """Who runs the tool (an email address or a website), from `VISIO_FOOTAGE_CONTACT`. It goes
    into the request's User-Agent, so it must be one plain printable line."""
    text = " ".join(os.environ.get(CONTACT_ENV, "").split())
    if not text:
        return None
    if len(text) > CONTACT_MAX_CHARS or not text.isprintable() or ";" in text or "(" in text:
        raise Refused(
            f"{CONTACT_ENV} must be one plain line (no ; or brackets) of at most "
            f"{CONTACT_MAX_CHARS} characters."
        )
    return text


def _fetch(url: str) -> tuple[bytes, str]:
    contact = contact_from_env()
    # With a contact the tool names itself and says who runs it, as Wikimedia asks of every
    # program that fetches from it; without one the request looks like a browser's.
    user_agent = (
        f"{TOOL_NAME}/{TOOL_VERSION} (personal video research tool; {contact})" if contact else None
    )
    try:
        return fetch_image(url, user_agent=user_agent)
    except Refused as error:
        host = urlsplit(url).hostname or ""
        if contact is None and "answered 403" in str(error) and host.endswith("wikimedia.org"):
            raise Refused(
                f"{error} Wikimedia refuses programs that do not say who runs them. Set "
                f"{CONTACT_ENV} to your email address or website and run the command again."
            ) from error
        raise


def capture_image(
    rnd: FootageRound,
    *,
    mark_id: str,
    piece_id: str,
    url: str,
    page_url: str | None,
    described: Described,
) -> Captured:
    """Fetch the picture at `url` and make the entry of a piece of kind `image`."""
    rnd.mark(mark_id)
    rnd.check_room(mark_id, piece_id)
    if page_url is not None:
        check_url(page_url)  # Checked, never opened: it only says where the picture was found.
    check_url(url)
    data, final_url = _fetch(url)
    stored, kind, (width, height), notes = prepare_image(data)

    names = file_names(piece_id)
    name = names["image_jpeg"] if kind == "jpeg" else names["image"]
    files = {name: stored}
    capture = {
        "image": name,
        "image_px": [width, height],
        "page_url": page_url,
        "sha256": {name: sha256_of(stored)},
    }
    if max(width, height) < LOW_RES_LONG_SIDE:
        notes.append(
            f"WARNING: the picture is small ({width}x{height}); it will look soft full screen. "
            "Look for a larger one."
        )
    notes.append(f"Captured an image of {width}x{height}.")
    entry = piece_entry(
        piece_id=piece_id,
        kind="image",
        described=described,
        url=url,
        final_url=final_url,
        title=None,
        capture=capture,
    )
    return Captured(entry=entry, files=files, notes=notes)
