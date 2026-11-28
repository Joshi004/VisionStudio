"""Capture of one page of a PDF (the footage `pdf` command): the whole page as a picture, and the
lines of the words to focus on when asked.

Evidence crops the page around its quote. Footage draws the page whole and zooms to the focus
itself (`footage_clip_layout.pdf_plan`), so the picture here is the whole page and the focus
rectangles are fractions of it.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Any

from .. import MAX_IMAGE_BYTES, MAX_RECTS, MAX_TEXT_BYTES
from ..geometry import pad_inside, to_fractions
from ..pdf import (
    MAX_RENDER_SCALE,
    _line_rects,
    _png,
    _read_source,
    find_in_text,
    open_pdf,
    page_text,
)
from ..rounds import sha256_of
from ..text import compact_copy, nearest_text, normalise_with_map
from . import MAX_IMAGE_PIXELS, PDF_LONG_SIDE_PX
from .page import check_focus_length
from .rounds import Captured, Described, FootageRound, Refused, file_names, piece_entry


def render_scale(page_w: float, page_h: float) -> float:
    """Pixels per point: the longer side at `PDF_LONG_SIDE_PX`, within the render cap and the
    pixel cap."""
    by_side = PDF_LONG_SIDE_PX / max(page_w, page_h)
    by_pixels = math.sqrt(MAX_IMAGE_PIXELS / (page_w * page_h))
    return min(MAX_RENDER_SCALE, by_side, by_pixels * 0.99)


def capture_pdf_page(
    rnd: FootageRound,
    *,
    mark_id: str,
    piece_id: str,
    url: str | None,
    file: str | None,
    source_url: str | None,
    page_number: int,
    focus: str | None,
    described: Described,
) -> Captured:
    """Render page `page_number` whole, and find `focus` on it when given."""
    rnd.mark(mark_id)
    rnd.check_room(mark_id, piece_id)
    wanted = check_focus_length(focus) if focus is not None else None
    data, final_url = _read_source(url, file, source_url)
    original_url = url if url is not None else (source_url or "")
    document = open_pdf(data)
    try:
        pages = len(document)
        if not 1 <= page_number <= pages:
            raise Refused(f"--page must be from 1 to {pages}.")
        return _capture(
            document,
            data=data,
            piece_id=piece_id,
            original_url=original_url,
            final_url=final_url,
            index=page_number - 1,
            wanted=wanted,
            described=described,
        )
    finally:
        document.close()


def _capture(
    document: Any,
    *,
    data: bytes,
    piece_id: str,
    original_url: str,
    final_url: str,
    index: int,
    wanted: str | None,
    described: Described,
) -> Captured:
    raw = page_text(document, index)
    copy_text = compact_copy(raw.replace("\ufffe", "-"))
    if len(copy_text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise Refused("The page's text is too large to keep.")
    notes: list[str] = []

    page = document[index]
    try:
        if page.get_rotation() != 0:
            raise Refused(f"Page {index + 1} is rotated, which this tool does not capture.")
        page_w, page_h = page.get_size()
        focus_rects: list[list[float]] = []
        focus_text: str | None = None
        if wanted is not None:
            if not raw.strip():
                raise Refused(
                    f"Page {index + 1} has no text layer (it is a scan), so words cannot be found "
                    "on it. Capture it with no focus."
                )
            found = find_in_text(raw, wanted)
            if found is None:
                raise Refused(_not_found_message(raw, wanted, index + 1))
            if found.match.count > 1:
                notes.append(
                    f"The focus words are on the page {found.match.count} times. The first is used."
                )
            lines = _line_rects(page, raw, found.match)
            if not lines:
                raise Refused("The focus words' place on the page could not be measured.")
            if len(lines) > MAX_RECTS:
                raise Refused(f"The focus runs over {len(lines)} lines (the limit is {MAX_RECTS}).")
            pad = max(0.5, 0.08 * median(r[3] for r in lines))
            padded = [pad_inside(line, pad, pad, page_w, page_h) for line in lines]
            focus_rects = to_fractions(padded, page_w, page_h)
            literal = " ".join(raw[found.match.start : found.match.end].split())
            focus_text = (
                literal if found.line_hyphens == "keep" and "\ufffe" not in literal else wanted
            )
        scale = render_scale(page_w, page_h)
        image = page.render(scale=scale).to_pil().convert("RGB")
        title = (document.get_metadata_value("Title") or "").strip()
    finally:
        page.close()

    image_bytes = _png(image)
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise Refused(f"The image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
    names = file_names(piece_id)
    files = {
        names["image"]: image_bytes,
        names["text_copy"]: copy_text.encode("utf-8"),
        names["source_copy"]: data,
    }
    capture = {
        "image": names["image"],
        "image_px": [image.width, image.height],
        "page": index + 1,
        "source_copy": names["source_copy"],
        "render_scale": round(scale, 4),
        "text_copy": names["text_copy"],
        "focus_text": focus_text,
        "focus_rects": focus_rects,
        "sha256": {name: sha256_of(content) for name, content in files.items()},
    }
    notes.append(
        f"Captured page {index + 1}, image {image.width}x{image.height}, "
        f"{len(focus_rects)} focus line{'s' if len(focus_rects) != 1 else ''}."
    )
    entry = piece_entry(
        piece_id=piece_id,
        kind="pdf",
        described=described,
        url=original_url,
        final_url=final_url,
        title=" ".join(title.split())[:300] or None,
        capture=capture,
    )
    return Captured(entry=entry, files=files, notes=notes)


def _not_found_message(raw: str, wanted: str, page_number: int) -> str:
    lines = [
        f"The focus words are not on page {page_number} (checked after normalising quotes and "
        "spaces)."
    ]
    near = nearest_text(normalise_with_map(raw).text, wanted)
    if near:
        lines.append("Nearest text on the page, to choose the exact words from:")
        lines.extend(f"  {number}. {text}" for number, text in enumerate(near, start=1))
    else:
        lines.append("No similar text was found on the page.")
    return "\n".join(lines)
