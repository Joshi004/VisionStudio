"""`validate`: checks 1 to 4 of §4.8 for every result of a footage round, so the agent can fix
problems before the owner imports. The import (FTG-011) applies the same checks again and does
not trust this one.

This version checks the still kinds (`image`, `page`, `pdf`). A `video` piece is made and checked
by the YouTube commands (FTG-009).
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Final

from PIL import Image, UnidentifiedImageError

from .. import MAX_IMAGE_BYTES, MAX_PDF_BYTES, MAX_RECTS, MAX_TEXT_BYTES
from ..pdf import find_in_text, open_pdf, page_text
from ..rounds import DATE_TEXT, Refused
from ..text import normalise, normalise_with_map
from ..validate import (
    EPSILON,
    PNG_SIGNATURE,
    Report,
    _file_type_ok,
    _is_number,
    _is_text,
    capture_file,
)
from ..web import LANDSCAPE_VIEWPORT, PORTRAIT_VIEWPORT
from . import (
    KINDS,
    LOW_RES_LONG_SIDE,
    MAX_IMAGE_PIXELS,
    ON_SCREEN_TEXT,
    PAGE_HEIGHTS,
    RESULT_SCHEMA,
    RESULT_VERSION,
    SAME_EVENT,
    STATUSES,
    STATUSES_WITH_PIECES,
    STILL_KINDS,
    TIERS,
    TOOL_NAME,
)
from .rounds import PIECE_ID, FootageRound

Problem = Callable[[str], None]

# How far the page's shape and the picture's may differ (rounding of the render size).
PDF_ASPECT_TOLERANCE: Final = 0.01


def validate_round(rnd: FootageRound) -> Report:
    report = Report()
    results = rnd.results_dir
    known = set(rnd.mark_ids)
    if results.is_dir() and not results.is_symlink():
        for folder in sorted(results.iterdir()):
            if folder.name not in known:
                report.warnings.append(
                    f"results/{folder.name} is not a mark of this round and will be ignored."
                )
    for mark_id in rnd.mark_ids:
        _validate_mark(rnd, mark_id, report)
    return report


def _validate_mark(rnd: FootageRound, mark_id: str, report: Report) -> None:
    def problem(text: str) -> None:
        report.problems.append(f"{mark_id}: {text}")

    def warn(text: str) -> None:
        report.warnings.append(f"{mark_id}: {text}")

    try:
        result = rnd.load_result(mark_id)
    except Refused as error:
        problem(str(error))
        report.rows.append((mark_id, "invalid", ""))
        return
    if result is None:
        problem("there is no result yet.")
        report.rows.append((mark_id, "no result", ""))
        return

    # Check 1: shape.
    if result.get("schema") != RESULT_SCHEMA or result.get("version") != RESULT_VERSION:
        problem("result.json is not a version 1 footage result.")
    if result.get("round_id") != rnd.round_id:
        problem(f"round_id is {result.get('round_id')!r}, not {rnd.round_id!r}.")
    status = result.get("status")
    if status is None:
        problem("the status is not set. Run the report command.")
    elif status not in STATUSES:
        problem(f"status {status!r} is not one of: {', '.join(STATUSES)}.")
    if not _is_text(result.get("summary")):
        problem("the summary is empty. Run the report command.")
    attempts = result["attempts"]
    for attempt in attempts:
        if not (
            isinstance(attempt, dict)
            and isinstance(attempt.get("what"), str)
            and isinstance(attempt.get("outcome"), str)
        ):
            problem("an attempt is not {what, outcome}.")
            break
    pieces = result["pieces"]
    if status in STATUSES_WITH_PIECES and not pieces:
        problem(f"status {status} needs at least one piece.")
    if status in ("not_found", "blocked") and pieces:
        problem(f"status {status} means no pieces, but there are some.")
    if status == "not_found" and not attempts:
        problem("not_found needs at least one attempt.")
    if len(pieces) > rnd.max_pieces:
        problem(f"{len(pieces)} pieces, the limit is {rnd.max_pieces}.")

    folder = rnd.mark_dir(mark_id, create=False)
    named: set[str] = {"result.json"}
    seen: set[str] = set()
    labels: list[str] = []
    for position, item in enumerate(pieces, start=1):
        label = f"piece #{position}"
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            problem(f"{label} has no id.")
            continue
        piece_id = item["id"]
        label = f"piece {piece_id}"
        if not PIECE_ID.match(piece_id) or piece_id in seen:
            problem(f"{label}: the id is not valid or is used twice.")
        seen.add(piece_id)
        _validate_piece(rnd, folder, item, label, problem, warn, named)
        labels.append(f"{piece_id} {item.get('kind')}")

    # `scans/` is the tool's working folder for a video (FTG-009); it is never part of a result.
    for path in sorted(folder.iterdir()):
        if path.is_symlink():
            problem(f"{path.name} is a link. Links are never allowed in a mark folder.")
        elif path.name not in named and not path.name.startswith(".") and path.name != "scans":
            warn(f"{path.name} is not used by the result and will be ignored.")
    report.rows.append((mark_id, str(status), ", ".join(labels)))


def _is_date_or_none(value: object) -> bool:
    if value is None:
        return True
    if not (isinstance(value, str) and DATE_TEXT.match(value)):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_piece(
    rnd: FootageRound,
    folder: Path,
    item: dict[str, Any],
    label: str,
    mark_problem: Problem,
    mark_warn: Problem,
    named: set[str],
) -> None:
    def problem(text: str) -> None:
        mark_problem(f"{label}: {text}")

    def warn(text: str) -> None:
        mark_warn(f"{label}: {text}")

    kind = item.get("kind")
    if kind not in KINDS:
        problem(f"kind must be one of: {', '.join(KINDS)}.")
    if item.get("tier") not in TIERS:
        problem(f"tier must be one of: {', '.join(TIERS)}.")
    if item.get("same_event") not in SAME_EVENT:
        problem(f"same_event must be one of: {', '.join(SAME_EVENT)}.")
    if item.get("on_screen_text") not in ON_SCREEN_TEXT:
        problem(f"on_screen_text must be one of: {', '.join(ON_SCREEN_TEXT)}.")
    if not _is_text(item.get("what_it_shows")):
        problem("what_it_shows is missing.")
    if not _is_date_or_none(item.get("event_date")):
        problem("event_date must be a date written YYYY-MM-DD, or null.")
    source = item.get("source")
    if not isinstance(source, dict):
        problem("source is missing.")
    else:
        for key in ("url", "final_url", "publisher", "retrieved_at"):
            if not _is_text(source.get(key)):
                problem(f"source.{key} is missing.")
        if not _is_date_or_none(source.get("published")):
            problem("source.published must be a date written YYYY-MM-DD, or null.")
    capture = item.get("capture")
    if not isinstance(capture, dict):
        problem("capture is missing.")
        return
    if capture.get("tool") != TOOL_NAME:
        problem(f"the capture was not made by {TOOL_NAME} (captures are never written by hand).")
    if kind not in STILL_KINDS:
        if kind == "video":
            problem("video pieces cannot be checked by this version of the tool.")
        return

    data = _check_files(rnd, folder, kind, capture, named, problem)
    image = data.get("image")
    size = _check_image(image, capture.get("image_px"), problem) if image is not None else None
    if size is None:
        return

    if kind == "image" and max(size) < LOW_RES_LONG_SIDE:
        warn(f"the picture is small ({size[0]}x{size[1]}); it will look soft full screen.")
    if kind == "page":
        _check_page_shape(rnd, capture, size, problem)
    if kind == "pdf":
        _check_pdf_shape(capture, data, size, problem)
    _check_focus(kind, capture, data, problem)


# --- Check 2: files --------------------------------------------------------------------------

# For each kind: the capture key, the type the content must have, the size limit, and whether
# the file must be there.
_FILES: Final = {
    "image": (("image", "image", MAX_IMAGE_BYTES, True),),
    "page": (
        ("image", "png", MAX_IMAGE_BYTES, True),
        ("text_copy", "text", MAX_TEXT_BYTES, True),
    ),
    "pdf": (
        ("image", "png", MAX_IMAGE_BYTES, True),
        ("text_copy", "text", MAX_TEXT_BYTES, True),
        ("source_copy", "pdf", MAX_PDF_BYTES, True),
    ),
}


def _type_ok(wanted: str, content: bytes) -> bool:
    if wanted == "image":
        return content.startswith((b"\xff\xd8\xff", PNG_SIGNATURE))
    return _file_type_ok(wanted, content)


def _check_files(
    rnd: FootageRound,
    folder: Path,
    kind: str,
    capture: dict[str, Any],
    named: set[str],
    problem: Problem,
) -> dict[str, bytes]:
    """The files of a piece are plain, present, not too large, unchanged and of the right type.
    Returns the content of the ones that can be used further."""
    hashes = capture.get("sha256")
    if not isinstance(hashes, dict):
        problem("capture.sha256 is missing.")
        hashes = {}
    data: dict[str, bytes] = {}
    for key, wanted, limit, required in _FILES[kind]:
        name = capture.get(key)
        if name is None:
            if required:
                problem(f"capture.{key} is missing.")
            continue
        try:
            path = capture_file(folder, name, root=rnd.root)
        except ValueError as error:
            problem(f"capture.{key}: {error}.")
            continue
        named.add(name)
        size = path.stat().st_size
        if size > limit:
            problem(f"{name} is too large ({size} bytes, the limit is {limit}).")
            continue
        content = path.read_bytes()
        if hashes.get(name) != hashlib.sha256(content).hexdigest():
            problem(f"{name} does not match its recorded SHA-256 (it was changed).")
        if not _type_ok(wanted, content):
            problem(f"{name} is not a real {'JPEG or PNG' if wanted == 'image' else wanted} file.")
            continue
        data[key] = content
    return data


def _check_image(content: bytes, image_px: object, problem: Problem) -> tuple[int, int] | None:
    """The picture can be read, is not too big, and `image_px` is its real size."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        problem("the image cannot be read.")
        return None
    if width * height > MAX_IMAGE_PIXELS:
        problem("the image has too many pixels.")
        return None
    if (
        not isinstance(image_px, list)
        or len(image_px) != 2
        or not all(isinstance(value, int) and not isinstance(value, bool) for value in image_px)
        or image_px != [width, height]
    ):
        problem(f"image_px {image_px!r} is not the image's real size [{width}, {height}].")
        return None
    return width, height


def _check_page_shape(
    rnd: FootageRound, capture: dict[str, Any], size: tuple[int, int], problem: Problem
) -> None:
    """A page picture is the viewport's width and at most `PAGE_HEIGHTS` screens tall."""
    viewport = capture.get("viewport")
    scale = capture.get("device_scale")
    expected = PORTRAIT_VIEWPORT if rnd.orientation == "portrait" else LANDSCAPE_VIEWPORT
    want = [expected["width"], expected["height"]]
    if viewport != want or scale != expected["device_scale"]:
        problem(
            f"the viewport is {viewport!r} at scale {scale!r}, but a {rnd.orientation} project "
            f"is captured at {want} at scale {expected['device_scale']}."
        )
        return
    width, height = size
    if width != want[0] * scale:
        problem(f"the image is {width} pixels wide, not {want[0] * scale}.")
    if height < want[1] * scale or height > PAGE_HEIGHTS * want[1] * scale:
        problem(
            f"the image is {height} pixels tall, but a page is from one to {PAGE_HEIGHTS} "
            f"screens ({want[1] * scale} to {PAGE_HEIGHTS * want[1] * scale} pixels)."
        )


def _check_pdf_shape(
    capture: dict[str, Any], data: dict[str, bytes], size: tuple[int, int], problem: Problem
) -> None:
    """The picture is the whole page: it has the page's shape."""
    if "source_copy" not in data:
        return
    document = _open(data["source_copy"], problem)
    if document is None:
        return
    try:
        page = capture.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= len(document):
            problem(f"page {page!r} is not a page of the PDF (1 to {len(document)}).")
            return
        pdf_page = document[page - 1]
        try:
            page_w, page_h = pdf_page.get_size()
        finally:
            pdf_page.close()
    finally:
        document.close()
    if abs((size[0] / size[1]) / (page_w / page_h) - 1) > PDF_ASPECT_TOLERANCE:
        problem("the image does not have the shape of the PDF page (it must be the whole page).")


def _open(content: bytes, problem: Problem):
    try:
        return open_pdf(content)
    except Refused as error:
        problem(str(error))
        return None


# --- Check 4: the focus ----------------------------------------------------------------------


def _check_focus(
    kind: str, capture: dict[str, Any], data: dict[str, bytes], problem: Problem
) -> None:
    """`focus_rects` lie inside the image, and `focus_text` is in the page's text. An image has
    no focus."""
    rects = capture.get("focus_rects")
    focus_text = capture.get("focus_text")
    if kind == "image":
        if rects or focus_text is not None:
            problem("an image has no focus.")
        return
    if not isinstance(rects, list):
        problem("focus_rects must be a list (empty when no focus was asked).")
        return
    if len(rects) > MAX_RECTS:
        problem(f"{len(rects)} focus rectangles, the limit is {MAX_RECTS}.")
    for number, rect in enumerate(rects, start=1):
        if not (
            isinstance(rect, list) and len(rect) == 4 and all(_is_number(value) for value in rect)
        ):
            problem(f"focus rectangle {number} is not [x, y, width, height].")
            continue
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            problem(f"focus rectangle {number} is empty.")
        elif x < -EPSILON or y < -EPSILON or x + w > 1 + EPSILON or y + h > 1 + EPSILON:
            problem(f"focus rectangle {number} is outside the image.")
    if not rects:
        if focus_text is not None:
            problem("focus_text is set but there are no focus rectangles.")
        return
    if not _is_text(focus_text):
        problem("there are focus rectangles but focus_text is missing.")
        return
    wanted = normalise(str(focus_text))
    if kind == "page":
        if "text_copy" not in data:
            return
        source = normalise_with_map(data["text_copy"].decode("utf-8"))
        if wanted not in source.text:
            problem("the focus words are not in the text copy.")
    elif "source_copy" in data:
        document = _open(data["source_copy"], problem)
        if document is None:
            return
        try:
            number = capture.get("page")
            if isinstance(number, int) and 1 <= number <= len(document):
                if find_in_text(page_text(document, number - 1), wanted) is None:
                    problem(f"the focus words are not on page {number} of the PDF.")
        finally:
            document.close()
