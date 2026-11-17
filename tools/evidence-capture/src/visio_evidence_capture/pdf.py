"""Capture of a PDF: find the exact quote in a page's text, then render the page around it."""

from __future__ import annotations

import ctypes
import io
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image

from . import MAX_PDF_BYTES, MAX_RECTS, MAX_TEXT_BYTES
from .geometry import Rect, merge_lines, to_fractions
from .netguard import fetch_pdf
from .rounds import Captured, Described, Refused, Round, evidence_entry, file_names, sha256_of
from .text import (
    LINE_HYPHEN_MODES,
    LineHyphens,
    Match,
    compact_copy,
    find_quote,
    nearest_text,
    normalise_with_map,
)
from .web import check_quote_length

MAX_PDF_PAGES = 2000
# The crop is at least this share of the page's width, so that the quote is zoomed in.
MIN_CROP_WIDTH_SHARE = 0.4
MAX_RENDER_SCALE = 8.0
CONTEXT_DPI = 150
# Points are measured at this many pixels per point, so that whole-pixel answers are precise.
_MEASURE_SCALE = 16
# The video's shape: the size of a web capture's image.
_TARGET_PX = {"landscape": (2560, 1440), "portrait": (1440, 2560)}


def open_pdf(data: bytes) -> pdfium.PdfDocument:
    """Open PDF bytes. Refuses a damaged or password-protected file."""
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        raise Refused(
            f"The PDF cannot be opened (it may be damaged or password-protected): {error}"
        ) from error
    if len(document) == 0:
        raise Refused("The PDF has no pages.")
    return document


def page_text(document: pdfium.PdfDocument, index: int) -> str:
    """The text of one page (0-based) as pdfium reads it."""
    page = document[index]
    text_page = page.get_textpage()
    try:
        return text_page.get_text_range()
    finally:
        text_page.close()
        page.close()


@dataclass(frozen=True)
class Found:
    match: Match
    line_hyphens: LineHyphens


def find_in_text(raw: str, wanted: str) -> Found | None:
    """Find a normalised quote in a page's text. A hyphen at the end of a line may join two halves
    of a word, so the text is read three ways (see `text.py`).
    """
    for mode in LINE_HYPHEN_MODES:
        match = find_quote(normalise_with_map(raw, line_hyphens=mode), wanted)
        if match:
            return Found(match, mode)
    return None


def _units(raw: str, index: int) -> int:
    """pdfium counts UTF-16 units, Python counts code points: the pdfium index of `index`."""
    return index + sum(1 for char in raw[:index] if ord(char) > 0xFFFF)


def _to_points(page: pdfium.PdfPage, x: float, y: float) -> tuple[float, float]:
    """A point of the page's own coordinates (y up) as points from the top left of the page as
    it is shown (y down), through pdfium so that cropped pages are right.
    """
    width, height = page.get_size()
    out_x, out_y = ctypes.c_int(), ctypes.c_int()
    pdfium_raw.FPDF_PageToDevice(
        page.raw,
        0,
        0,
        round(width * _MEASURE_SCALE),
        round(height * _MEASURE_SCALE),
        0,
        x,
        y,
        ctypes.byref(out_x),
        ctypes.byref(out_y),
    )
    return out_x.value / _MEASURE_SCALE, out_y.value / _MEASURE_SCALE


def _line_rects(page: pdfium.PdfPage, raw: str, match: Match) -> list[Rect]:
    """The quote's lines as rectangles in points, from the top left of the page."""
    text_page = page.get_textpage()
    try:
        first = _units(raw, match.start)
        count = _units(raw, match.end) - first
        pieces: list[Rect] = []
        for number in range(text_page.count_rects(first, count)):
            left, bottom, right, top = text_page.get_rect(number)
            x0, y0 = _to_points(page, left, top)
            x1, y1 = _to_points(page, right, bottom)
            width, height = abs(x1 - x0), abs(y1 - y0)
            if width >= 0.5 and height >= 0.5:
                pieces.append((min(x0, x1), min(y0, y1), width, height))
    finally:
        text_page.close()
    return merge_lines(pieces)


def _plan_crop(
    lines: list[Rect], page_size: tuple[float, float], orientation: str
) -> tuple[float, float, float, float, float]:
    """The crop box `(x0, y0, width, height)` in points and the render scale, for the quote's
    lines. The box has the video's shape, is centred on the quote and kept inside the page when
    it fits (and centred on the page, with white around, when it does not).
    """
    page_w, page_h = page_size
    target_w, target_h = _TARGET_PX[orientation]
    aspect = target_w / target_h
    left = min(r[0] for r in lines)
    top = min(r[1] for r in lines)
    right = max(r[0] + r[2] for r in lines)
    bottom = max(r[1] + r[3] for r in lines)
    pad = max(10.0, 0.5 * median(r[3] for r in lines))
    box_w = max(right - left + 2 * pad, MIN_CROP_WIDTH_SHARE * page_w)
    box_h = max(bottom - top + 2 * pad, box_w / aspect)
    box_w = box_h * aspect
    x0 = (left + right) / 2 - box_w / 2
    y0 = (top + bottom) / 2 - box_h / 2
    x0 = min(max(x0, 0.0), page_w - box_w) if box_w <= page_w else (page_w - box_w) / 2
    y0 = min(max(y0, 0.0), page_h - box_h) if box_h <= page_h else (page_h - box_h) / 2
    scale = min(MAX_RENDER_SCALE, target_w / box_w, target_h / box_h)
    return x0, y0, box_w, box_h, scale


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _render_crop(
    page: pdfium.PdfPage, x0: float, y0: float, width: float, height: float, scale: float
) -> tuple[Image.Image, int, int]:
    """Render the box. Returns the image (white where the box is outside the page) and the pixel
    position of the box's corner in a render of the whole page at this scale.
    """
    page_w, page_h = page.get_size()
    out_w = round(width * scale)
    out_h = round(out_w * height / width)
    origin_x, origin_y = round(x0 * scale), round(y0 * scale)
    full_w, full_h = round(page_w * scale), round(page_h * scale)
    left, top = max(0, origin_x), max(0, origin_y)
    right, bottom = min(full_w, origin_x + out_w), min(full_h, origin_y + out_h)
    canvas = Image.new("RGB", (out_w, out_h), "white")
    if right > left and bottom > top:
        bitmap = page.render(
            scale=scale,
            crop=(left / scale, (full_h - bottom) / scale, (full_w - right) / scale, top / scale),
        )
        canvas.paste(bitmap.to_pil().convert("RGB"), (left - origin_x, top - origin_y))
    return canvas, origin_x, origin_y


def _read_source(url: str | None, file: str | None, source_url: str | None) -> tuple[bytes, str]:
    """The PDF's bytes and the address to record for it."""
    if (url is None) == (file is None):
        raise Refused("Give either --url or --file (with --source-url).")
    if url is not None:
        return fetch_pdf(url)
    path = Path(file or "").expanduser()
    if not source_url or not source_url.lower().startswith(("http://", "https://")):
        raise Refused("With --file, say where the PDF came from with --source-url (http or https).")
    if path.is_symlink() or not path.is_file():
        raise Refused(f"{path} is not a regular file.")
    if path.stat().st_size > MAX_PDF_BYTES:
        raise Refused(f"The PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB.")
    data = path.read_bytes()
    if b"%PDF-" not in data[:1024]:
        raise Refused(f"{path.name} is not a PDF.")
    return data, source_url


def capture_pdf(
    rnd: Round,
    *,
    claim_id: str,
    evidence_id: str,
    url: str | None,
    file: str | None,
    source_url: str | None,
    quote: str,
    page: int | None,
    described: Described,
) -> Captured:
    """Find `quote` in the PDF's text, render the page around it, and measure its lines."""
    rnd.claim(claim_id)
    rnd.check_room(claim_id, evidence_id)
    wanted = check_quote_length(quote)
    data, final_url = _read_source(url, file, source_url)
    original_url = url if url is not None else (source_url or "")
    document = open_pdf(data)
    try:
        return _capture(
            rnd,
            document,
            data=data,
            evidence_id=evidence_id,
            original_url=original_url,
            final_url=final_url,
            wanted=wanted,
            quote=quote,
            page_number=page,
            described=described,
        )
    finally:
        document.close()


def _capture(
    rnd: Round,
    document: pdfium.PdfDocument,
    *,
    data: bytes,
    evidence_id: str,
    original_url: str,
    final_url: str,
    wanted: str,
    quote: str,
    page_number: int | None,
    described: Described,
) -> Captured:
    pages = len(document)
    if page_number is not None and not 1 <= page_number <= pages:
        raise Refused(f"--page must be from 1 to {pages}.")
    if page_number is None and pages > MAX_PDF_PAGES:
        raise Refused(f"The PDF has {pages} pages. Say which one with --page.")
    indexes = [page_number - 1] if page_number is not None else list(range(pages))

    texts = {index: page_text(document, index) for index in indexes}
    if not any(text.strip() for text in texts.values()):
        raise Refused(
            "The PDF has no text layer (it is a scan). Text cannot be found without OCR, which "
            "this tool does not do."
        )

    first: tuple[int, Found] | None = None
    count = 0
    for index in indexes:
        found = find_in_text(texts[index], wanted)
        if found is None:
            continue
        count += found.match.count
        if first is None:
            first = (index, found)
    if first is None:
        raise Refused(_not_found_message(texts, wanted, page_number))
    index, found = first
    raw = texts[index]
    notes = []
    if count > 1:
        notes.append(f"The quote is in the PDF {count} times. The first one is used.")

    page = document[index]
    try:
        if page.get_rotation() != 0:
            raise Refused(f"Page {index + 1} is rotated, which this tool does not capture.")
        lines = _line_rects(page, raw, found.match)
        if not lines:
            raise Refused("The quote's place on the page could not be measured.")
        if len(lines) > MAX_RECTS:
            raise Refused(f"The quote runs over {len(lines)} lines (the limit is {MAX_RECTS}).")
        x0, y0, box_w, box_h, scale = _plan_crop(lines, page.get_size(), rnd.orientation)
        crop, origin_x, origin_y = _render_crop(page, x0, y0, box_w, box_h, scale)
        pad = max(0.5, 0.08 * median(r[3] for r in lines)) * scale
        rects_px: list[Rect] = []
        for left, top, width, height in lines:
            rx = left * scale - origin_x - pad
            ry = top * scale - origin_y - pad
            rects_px.append(
                (
                    max(0.0, rx),
                    max(0.0, ry),
                    min(crop.width - max(0.0, rx), width * scale + 2 * pad),
                    min(crop.height - max(0.0, ry), height * scale + 2 * pad),
                )
            )
        context = page.render(scale=CONTEXT_DPI / 72).to_pil().convert("RGB")
        page_w, page_h = page.get_size()
    finally:
        page.close()

    image_bytes, context_bytes = _png(crop), _png(context)
    copy_text = compact_copy(raw.replace("\ufffe", "-"))
    if len(copy_text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise Refused("The page's text is too large to keep.")
    box = [
        max(0.0, x0 / page_w),
        max(0.0, y0 / page_h),
    ]
    box.append(min(1.0, (x0 + box_w) / page_w) - box[0])
    box.append(min(1.0, (y0 + box_h) / page_h) - box[1])

    names = file_names(evidence_id)
    files = {
        names["image"]: image_bytes,
        names["context_image"]: context_bytes,
        names["text_copy"]: copy_text.encode("utf-8"),
        names["source_copy"]: data,
    }
    capture = {
        "image": names["image"],
        "image_px": [crop.width, crop.height],
        "context_image": names["context_image"],
        "context_box": [round(value, 6) for value in box],
        "text_copy": names["text_copy"],
        "source_copy": names["source_copy"],
        "page": index + 1,
        "viewport": None,
        "render_scale": round(scale, 4),
        "rects": to_fractions(rects_px, crop.width, crop.height),
        "sha256": {name: sha256_of(content) for name, content in files.items()},
    }
    title = (document.get_metadata_value("Title") or "").strip()
    literal = " ".join(raw[found.match.start : found.match.end].split())
    stored_quote = literal if found.line_hyphens == "keep" and "\ufffe" not in literal else wanted
    notes.append(
        f"Captured page {index + 1}, {len(lines)} line{'s' if len(lines) != 1 else ''}; "
        f"image {crop.width}x{crop.height}, context {context.width}x{context.height}."
    )
    entry = evidence_entry(
        evidence_id=evidence_id,
        kind="pdf",
        described=described,
        url=original_url,
        final_url=final_url,
        title=" ".join(title.split())[:300] or None,
        quote=stored_quote,
        capture=capture,
    )
    return Captured(entry=entry, files=files, notes=notes)


def _not_found_message(texts: dict[int, str], wanted: str, page_number: int | None) -> str:
    """Why the quote was not found, with the nearest text."""
    joined = "\n\n".join(texts[index] for index in sorted(texts))
    lines = []
    if page_number is None and find_in_text(joined, wanted) is not None:
        return (
            "The quote runs across a page break. Choose the words on one page only (the words "
            "before the break, or the words after it)."
        )
    where = f"on page {page_number}" if page_number is not None else "in the PDF"
    lines.append(f"The quote is not {where} (checked after normalising quotes and spaces).")
    near = nearest_text(normalise_with_map(joined).text, wanted)
    if near:
        lines.append("Nearest text in the PDF, to choose the exact words from:")
        lines.extend(f"  {number}. {text}" for number, text in enumerate(near, start=1))
    else:
        lines.append("No similar text was found.")
    return "\n".join(lines)
