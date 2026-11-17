"""`validate`: checks 1 to 4 of §4.6 for every result of a round, so the agent can fix problems
before the owner imports. The import (EVD-006) applies the same checks again and does not
trust this one.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Final

from PIL import Image, UnidentifiedImageError

from . import (
    KINDS,
    MAX_IMAGE_BYTES,
    MAX_PDF_BYTES,
    MAX_RECTS,
    MAX_TEXT_BYTES,
    RELATIONS,
    RESULT_SCHEMA,
    RESULT_VERSION,
    STATUSES,
    STATUSES_WITH_EVIDENCE,
    TIERS,
    TOOL_NAME,
)
from .pdf import find_in_text, open_pdf, page_text
from .rounds import DATE_TEXT, EVIDENCE_ID, Refused, Round
from .text import normalise, normalise_with_map

PLAIN_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_PIXELS: Final = 40_000_000
EPSILON: Final = 1e-5


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows: list[tuple[str, str, str]] = field(default_factory=list)  # claim, status, sources

    @property
    def ok(self) -> bool:
        return not self.problems


def capture_file(folder: Path, name: object, *, root: Path) -> Path:
    """The file `name` of a claim's folder: a plain name, a regular file (no link), inside the
    round. Raises ValueError with the reason otherwise.
    """
    if not isinstance(name, str) or not PLAIN_NAME.match(name):
        raise ValueError(f"the file name {name!r} is not a plain name")
    path = folder / name
    if path.is_symlink():
        raise ValueError(f"{name} is a link")
    if not path.is_file():
        raise ValueError(f"{name} is missing")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"{name} is outside the round")
    return path


class _Claim:
    """Collects the problems of one claim under its id."""

    def __init__(self, report: Report, claim_id: str) -> None:
        self.report = report
        self.claim_id = claim_id

    def problem(self, text: str) -> None:
        self.report.problems.append(f"{self.claim_id}: {text}")

    def warn(self, text: str) -> None:
        self.report.warnings.append(f"{self.claim_id}: {text}")


def validate_round(rnd: Round) -> Report:
    report = Report()
    results = rnd.results_dir
    known = set(rnd.claim_ids)
    if results.is_dir() and not results.is_symlink():
        for folder in sorted(results.iterdir()):
            if folder.name not in known:
                report.warnings.append(
                    f"results/{folder.name} is not a claim of this round and will be ignored."
                )
    for claim_id in rnd.claim_ids:
        _validate_claim(rnd, claim_id, report)
    return report


def _validate_claim(rnd: Round, claim_id: str, report: Report) -> None:
    claim = _Claim(report, claim_id)
    try:
        result = rnd.load_result(claim_id)
    except Refused as error:
        claim.problem(str(error))
        report.rows.append((claim_id, "invalid", ""))
        return
    if result is None:
        claim.problem("there is no result yet.")
        report.rows.append((claim_id, "no result", ""))
        return

    # Check 1: shape.
    if result.get("schema") != RESULT_SCHEMA or result.get("version") != RESULT_VERSION:
        claim.problem("result.json is not a version 1 evidence result.")
    if result.get("round_id") != rnd.round_id:
        claim.problem(f"round_id is {result.get('round_id')!r}, not {rnd.round_id!r}.")
    status = result.get("status")
    if status is None:
        claim.problem("the status is not set. Run the report command.")
    elif status not in STATUSES:
        claim.problem(f"status {status!r} is not one of: {', '.join(STATUSES)}.")
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        claim.problem("the summary is empty. Run the report command.")
    attempts = result["attempts"]
    for attempt in attempts:
        if not (
            isinstance(attempt, dict)
            and isinstance(attempt.get("what"), str)
            and isinstance(attempt.get("outcome"), str)
        ):
            claim.problem("an attempt is not {what, outcome}.")
            break
    evidence = result["evidence"]
    if status in STATUSES_WITH_EVIDENCE and not evidence:
        claim.problem(f"status {status} needs at least one piece of evidence.")
    if status in ("not_found", "blocked") and evidence:
        claim.problem(f"status {status} means no evidence, but there is some.")
    if status == "not_found" and not attempts:
        claim.problem("not_found needs at least one attempt.")
    if len(evidence) > rnd.max_evidence:
        claim.problem(f"{len(evidence)} pieces of evidence, the limit is {rnd.max_evidence}.")

    folder = rnd.claim_dir(claim_id, create=False)
    named: set[str] = {"result.json"}
    seen: set[str] = set()
    sources: list[str] = []
    for position, item in enumerate(evidence, start=1):
        label = f"evidence #{position}"
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            claim.problem(f"{label} has no id.")
            continue
        evidence_id = item["id"]
        label = f"evidence {evidence_id}"
        if not EVIDENCE_ID.match(evidence_id) or evidence_id in seen:
            claim.problem(f"{label}: the id is not valid or is used twice.")
        seen.add(evidence_id)
        _validate_evidence(rnd, folder, item, label, claim, named)
        source = item.get("source")
        if isinstance(source, dict) and isinstance(source.get("publisher"), str):
            sources.append(source["publisher"])
    if status in ("found", "partial") and not any(
        isinstance(item, dict) and item.get("relation") in ("supports", "partly_supports")
        for item in evidence
    ):
        claim.warn(f"status {status} but no evidence supports the claim.")
    if status == "contradicted" and not any(
        isinstance(item, dict) and item.get("relation") == "contradicts" for item in evidence
    ):
        claim.warn("status contradicted but no evidence contradicts the claim.")

    for path in sorted(folder.iterdir()):
        if path.is_symlink():
            claim.problem(f"{path.name} is a link. Links are never allowed in a claim folder.")
        elif path.name not in named and not path.name.startswith("."):
            claim.warn(f"{path.name} is not used by the result and will be ignored.")
    report.rows.append((claim_id, str(status), ", ".join(sources)))


def _is_text(value: object, *, allow_empty: bool = False) -> bool:
    return isinstance(value, str) and (allow_empty or bool(value.strip()))


def _validate_evidence(
    rnd: Round,
    folder: Path,
    item: dict[str, Any],
    label: str,
    claim: _Claim,
    named: set[str],
) -> None:
    def problem(text: str) -> None:
        claim.problem(f"{label}: {text}")

    # Check 1: shape.
    if item.get("kind") not in KINDS:
        problem(f"kind must be one of: {', '.join(KINDS)}.")
    if item.get("relation") not in RELATIONS:
        problem(f"relation must be one of: {', '.join(RELATIONS)}.")
    if item.get("source_tier") not in TIERS:
        problem(f"source_tier must be one of: {', '.join(TIERS)}.")
    source = item.get("source")
    if not isinstance(source, dict):
        problem("source is missing.")
    else:
        for key in ("url", "final_url", "publisher", "retrieved_at"):
            if not _is_text(source.get(key)):
                problem(f"source.{key} is missing.")
        published = source.get("published")
        if published is not None:
            try:
                valid = isinstance(published, str) and DATE_TEXT.match(published)
                if not valid:
                    raise ValueError
                date.fromisoformat(published)
            except ValueError:
                problem("source.published must be a date written YYYY-MM-DD, or null.")
    quote = item.get("quote")
    if not _is_text(quote):
        problem("quote is missing.")
    if not _is_text(item.get("what_it_says")):
        problem("what_it_says is missing.")
    capture = item.get("capture")
    if not isinstance(capture, dict):
        problem("capture is missing.")
        return
    if capture.get("tool") != TOOL_NAME:
        problem(f"the capture was not made by {TOOL_NAME} (coordinates are never written by hand).")

    # Check 2: files.
    hashes = capture.get("sha256")
    if not isinstance(hashes, dict):
        problem("capture.sha256 is missing.")
        hashes = {}
    data: dict[str, bytes] = {}
    for key, kind, limit in (
        ("image", "png", MAX_IMAGE_BYTES),
        ("context_image", "png", MAX_IMAGE_BYTES),
        ("text_copy", "text", MAX_TEXT_BYTES),
        ("source_copy", "pdf", MAX_PDF_BYTES),
    ):
        name = capture.get(key)
        if name is None:
            if key == "image":
                problem("capture.image is missing.")
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
        data[key] = content
        if hashes.get(name) != hashlib.sha256(content).hexdigest():
            problem(f"{name} does not match its recorded SHA-256 (it was changed).")
        if not _file_type_ok(kind, content):
            problem(f"{name} is not a real {kind} file.")
            data.pop(key, None)

    image_px = capture.get("image_px")
    if "image" in data:
        _check_image_size(data["image"], image_px, capture, problem)
    if "context_image" in data:
        _check_context_box(capture.get("context_box"), problem)

    # Check 3: the quote is in the source.
    if _is_text(quote):
        _check_quote(item.get("kind"), str(quote), capture, data, problem)

    # Check 4: rectangles.
    _check_rects(capture.get("rects"), problem)


def _file_type_ok(kind: str, content: bytes) -> bool:
    if kind == "png":
        return content.startswith(PNG_SIGNATURE)
    if kind == "pdf":
        return b"%PDF-" in content[:1024]
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return "\x00" not in text


def _check_image_size(content: bytes, image_px: object, capture: dict[str, Any], problem) -> None:
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        problem("the image cannot be read.")
        return
    if width * height > MAX_IMAGE_PIXELS:
        problem("the image has too many pixels.")
    if (
        not isinstance(image_px, list)
        or len(image_px) != 2
        or image_px != [width, height]
        or not all(isinstance(value, int) for value in image_px)
    ):
        problem(f"image_px {image_px!r} is not the image's real size [{width}, {height}].")
        return
    viewport = capture.get("viewport")
    if viewport is not None:
        try:
            expected = [
                viewport["width"] * viewport["device_scale"],
                viewport["height"] * viewport["device_scale"],
            ]
        except (KeyError, TypeError):
            problem("viewport must have width, height and device_scale.")
            return
        if expected != [width, height]:
            problem(f"the image is {width}x{height}, but the viewport says {expected}.")


def _check_context_box(box: object, problem) -> None:
    if box is None:
        return
    if (
        not isinstance(box, list)
        or len(box) != 4
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)
        or box[0] < -EPSILON
        or box[1] < -EPSILON
        or box[2] <= 0
        or box[3] <= 0
        or box[0] + box[2] > 1 + EPSILON
        or box[1] + box[3] > 1 + EPSILON
    ):
        problem("context_box is not [x, y, width, height] inside the context image.")


def _check_quote(
    kind: object, quote: str, capture: dict[str, Any], data: dict[str, bytes], problem
) -> None:
    wanted = normalise(quote)
    if kind == "web":
        if "text_copy" not in data:
            problem("a web capture needs its text copy to check the quote.")
            return
        source = normalise_with_map(data["text_copy"].decode("utf-8"))
        if wanted not in source.text:
            problem("the quote is not in the text copy.")
    elif kind == "pdf":
        page = capture.get("page")
        if "source_copy" not in data:
            problem("a PDF capture needs its source copy to check the quote.")
            return
        try:
            document = open_pdf(data["source_copy"])
        except Refused as error:
            problem(str(error))
            return
        try:
            if (
                not isinstance(page, int)
                or isinstance(page, bool)
                or not 1 <= page <= len(document)
            ):
                problem(f"page {page!r} is not a page of the PDF (1 to {len(document)}).")
            elif find_in_text(page_text(document, page - 1), wanted) is None:
                problem(f"the quote is not on page {page} of the PDF.")
        finally:
            document.close()


def _check_rects(rects: object, problem) -> None:
    if not isinstance(rects, list) or not rects:
        problem("rects is empty or missing.")
        return
    if len(rects) > MAX_RECTS:
        problem(f"{len(rects)} rectangles, the limit is {MAX_RECTS}.")
    for number, rect in enumerate(rects, start=1):
        if (
            not isinstance(rect, list)
            or len(rect) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in rect)
        ):
            problem(f"rectangle {number} is not [x, y, width, height].")
            continue
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            problem(f"rectangle {number} is empty.")
        elif x < -EPSILON or y < -EPSILON or x + w > 1 + EPSILON or y + h > 1 + EPSILON:
            problem(f"rectangle {number} is outside the image.")
