"""The checks the import makes on a round's results (EVD-006,
`Evidence_layer_implementation_phases.md` §4.6, checks 1 to 5).

Pure: the caller (`services/evidence_import.py`) has already read `result.json` and the files it
names, safely, and passes them in. Nothing here touches the disk or the database.

The capture tool's `validate` command applies checks 1 to 4 too, in the same order and with the
same rules, so what passes `validate` imports. The import does not trust that run: it checks
again. Beyond `validate` it is a little stricter, because the app shows the values to the owner:

- an image must be a PNG (the only image the tool makes);
- `url`, `final_url` and `archive_url` must start with http:// or https://;
- text values have the same length limits the tool keeps;
- a link anywhere in a claim folder makes every piece of that claim unusable.

A failure in checks 1 to 4 makes that piece unusable and gives its reason. Check 5 (a number the
claim says that the quote does not) is a warning only.

The agent's words (the quote, `what_it_says`, `agent_notes`, the summary) are data: they are
tidied and length-checked here and stored as text. They are never used as a path or as HTML.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Final

from PIL import Image, UnidentifiedImageError

from app.services import evidence_text
from app.services.number_words import numbers_in

RESULT_SCHEMA: Final = "visio.evidence.result"
RESULT_VERSION: Final = 1
TOOL_NAME: Final = "visio-evidence-capture"

STATUSES: Final = ("found", "partial", "not_found", "contradicted", "blocked")
STATUSES_WITH_EVIDENCE: Final = ("found", "partial", "contradicted")
KINDS: Final = ("web", "pdf")
RELATIONS: Final = ("supports", "partly_supports", "contradicts", "context")
TIERS: Final = ("primary", "secondary", "other")

# Limits. They are the capture tool's, so that output which passes `validate` imports.
MAX_RESULT_BYTES: Final = 1024 * 1024
MAX_IMAGE_BYTES: Final = 20 * 1024 * 1024
MAX_TEXT_BYTES: Final = 5 * 1024 * 1024
MAX_PDF_BYTES: Final = 50 * 1024 * 1024
MAX_IMAGE_PIXELS: Final = 40_000_000
MAX_RECTS: Final = 12
QUOTE_MIN_CHARS: Final = 3
QUOTE_MAX_CHARS: Final = 600
MAX_ATTEMPTS: Final = 40
TEXT_LIMITS: Final = {
    "publisher": 200,
    "title": 300,
    "author": 200,
    "what_it_says": 1000,
    "notes": 2000,
    "summary": 1500,
    "attempt": 500,
    "url": 2000,
    "retrieved_at": 40,
}
DEFAULT_MAX_EVIDENCE: Final = 3

# The files a piece of evidence may name: result key, short slot name, kind of file, size limit.
# The order is the order of the checks.
SLOTS: Final = (
    ("image", "image", "png", MAX_IMAGE_BYTES),
    ("context_image", "context", "png", MAX_IMAGE_BYTES),
    ("text_copy", "text", "text", MAX_TEXT_BYTES),
    ("source_copy", "pdf", "pdf", MAX_PDF_BYTES),
)
SLOT_ORDER: Final = tuple(slot for _, slot, _, _ in SLOTS)

PLAIN_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
EVIDENCE_ID: Final = re.compile(r"^e\d{1,2}$")
DATE_TEXT: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
EPSILON: Final = 1e-5
_SHOWN_NAME_CHARS: Final = 60


@dataclass(frozen=True)
class FileProblem:
    """A file the reader could not use, and why (in a few words, for a sentence)."""

    reason: str


# A file the reader read (its bytes), or why it could not.
FileRead = bytes | FileProblem


@dataclass
class PieceCheck:
    """The outcome for one piece of evidence."""

    # The id stored in the row: the agent's id when it is valid and first, else `?<position>`.
    evidence_id: str
    usable: bool
    # {"shape": {"ok": true}, "files": {"ok": false, "reason": "a sentence"}, ...}
    checks: dict[str, dict[str, Any]]
    # Every reason a check failed, as sentences (for the report).
    reasons: list[str]
    warnings: list[dict[str, str]]
    item_key: str
    kind: str | None = None
    relation: str | None = None
    source_tier: str | None = None
    source: dict[str, Any] | None = None
    quote: str | None = None
    what_it_says: str | None = None
    agent_notes: str | None = None
    # Tidied values of the capture block, set only for a usable piece.
    capture: dict[str, Any] | None = None
    # slot -> (file name in the claim folder, real SHA-256). The files that were read as the
    # right type; the import copies them only when the piece is usable.
    files: dict[str, tuple[str, str]] = field(default_factory=dict)


@dataclass
class ClaimCheck:
    """The outcome for one claim."""

    # None when the claim has no usable `result.json`.
    status: str | None
    summary: str
    attempts: list[dict[str, str]]
    problems: list[str]
    warnings: list[str]
    pieces: list[PieceCheck]
    # A `result.json` exists but cannot be used (not "no result").
    invalid: bool = False


def shown(value: object) -> str:
    """A value of the agent's, cut short, for a sentence."""
    text = repr(value)
    return text if len(text) <= _SHOWN_NAME_CHARS else text[: _SHOWN_NAME_CHARS - 3] + "..."


def _is_text(value: object, *, allow_empty: bool = False) -> bool:
    return isinstance(value, str) and (allow_empty or bool(value.strip()))


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _http(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


# --- The claim --------------------------------------------------------------------------------


def no_result(reason: str | None, *, invalid: bool) -> ClaimCheck:
    """A claim with no usable result. `invalid` is true when a `result.json` was there. A claim
    with no result at all has no reason to give (`None`).
    """
    return ClaimCheck(
        status=None,
        summary="",
        attempts=[],
        problems=[reason] if reason else [],
        warnings=[],
        pieces=[],
        invalid=invalid,
    )


def _check_attempts(value: object, problems: list[str]) -> list[dict[str, str]]:
    attempts: list[dict[str, str]] = []
    if not isinstance(value, list):
        problems.append("attempts is not a list.")
        return attempts
    if len(value) > MAX_ATTEMPTS:
        problems.append(f"{len(value)} attempts, the limit is {MAX_ATTEMPTS}.")
        return attempts
    for attempt in value:
        if (
            isinstance(attempt, dict)
            and _is_text(attempt.get("what"))
            and _is_text(attempt.get("outcome"))
            and len(attempt["what"]) <= TEXT_LIMITS["attempt"]
            and len(attempt["outcome"]) <= TEXT_LIMITS["attempt"]
        ):
            attempts.append(
                {"what": attempt["what"].strip(), "outcome": attempt["outcome"].strip()}
            )
        else:
            problems.append("an attempt is not {what, outcome} of reasonable length.")
            return []
    return attempts


def check_claim(
    *,
    claim: dict[str, Any],
    round_id: str,
    max_evidence: int,
    result: dict[str, Any],
    files: dict[str, FileRead],
    folder_problem: str | None,
) -> ClaimCheck:
    """Checks one claim's `result.json` and the files it names. `claim` is the claim's entry of
    the brief, `files` the files the reader read by name, and `folder_problem` says that the
    claim's folder holds something that is never allowed (a link).
    """
    claim_id = claim["id"]
    problems: list[str] = []
    # Check 1 for the whole result. Any failure here makes the whole result unusable.
    if result.get("schema") != RESULT_SCHEMA or result.get("version") != RESULT_VERSION:
        problems.append("result.json is not a version 1 evidence result.")
    if result.get("round_id") != round_id:
        problems.append(f"round_id is {shown(result.get('round_id'))}, not {shown(round_id)}.")
    if result.get("claim_id") != claim_id:
        problems.append("result.json is not this claim's result.")
    status = result.get("status")
    if status is None:
        problems.append("the status is not set (the report command was not run).")
    elif status not in STATUSES:
        problems.append(f"status {shown(status)} is not one of: {', '.join(STATUSES)}.")
    summary = result.get("summary")
    if not _is_text(summary):
        problems.append("the summary is empty (the report command was not run).")
    elif len(summary) > TEXT_LIMITS["summary"]:
        problems.append("the summary is too long.")
    attempts = _check_attempts(result.get("attempts"), problems)
    evidence = result.get("evidence")
    if not isinstance(evidence, list):
        problems.append("evidence is not a list.")
    if problems:
        return no_result(" ".join(problems), invalid=True)
    assert isinstance(summary, str) and isinstance(evidence, list)

    # The status against the evidence. These are problems to show, and the status is kept.
    if status in STATUSES_WITH_EVIDENCE and not evidence:
        problems.append(f"The status is {status} but there is no evidence.")
    if status in ("not_found", "blocked") and evidence:
        problems.append(f"The status is {status}, which means no evidence, but there is some.")
    if status == "not_found" and not attempts:
        problems.append("The status is not_found but no attempt is listed.")
    if folder_problem is not None:
        problems.append(folder_problem)
    examined = evidence[:max_evidence]
    if len(evidence) > max_evidence:
        problems.append(
            f"{len(evidence)} pieces of evidence, the limit is {max_evidence}. "
            "The first ones were looked at and the rest were left out."
        )

    pieces: list[PieceCheck] = []
    seen_ids: set[str] = set()
    seen_keys: dict[str, str] = {}
    for position, item in enumerate(examined, start=1):
        piece = _check_piece(
            item,
            position=position,
            claim=claim,
            files=files,
            seen_ids=seen_ids,
            folder_problem=folder_problem,
        )
        if piece.usable:
            earlier = seen_keys.get(piece.item_key)
            if earlier is not None:
                reason = f"This is the same evidence as {earlier}."
                piece.usable = False
                piece.reasons.append(reason)
                piece.checks["duplicate"] = {"ok": False, "reason": reason}
                piece.item_key = _item_key(
                    claim_id,
                    piece_values={},
                    unusable_id=piece.evidence_id,
                )
            else:
                seen_keys[piece.item_key] = piece.evidence_id
        pieces.append(piece)

    warnings: list[str] = []
    if status in ("found", "partial") and not any(
        piece.relation in ("supports", "partly_supports") for piece in pieces
    ):
        warnings.append(f"The status is {status} but no evidence supports the claim.")
    if status == "contradicted" and not any(piece.relation == "contradicts" for piece in pieces):
        warnings.append("The status is contradicted but no evidence contradicts the claim.")
    if pieces and not any(piece.usable for piece in pieces):
        warnings.append("No piece of evidence for this claim passed the checks.")
    return ClaimCheck(
        status=status,
        summary=summary.strip(),
        attempts=attempts,
        problems=problems,
        warnings=warnings,
        pieces=pieces,
    )


# --- One piece of evidence ----------------------------------------------------------------------


class _Reasons:
    """Collects the reasons one check fails."""

    def __init__(self) -> None:
        self.items: list[str] = []

    def __call__(self, text: str) -> None:
        self.items.append(text)

    def result(self) -> dict[str, Any]:
        if not self.items:
            return {"ok": True}
        return {"ok": False, "reason": " ".join(self.items)}


def _check_piece(
    item: object,
    *,
    position: int,
    claim: dict[str, Any],
    files: dict[str, FileRead],
    seen_ids: set[str],
    folder_problem: str | None,
) -> PieceCheck:
    claim_id = claim["id"]
    fallback_id = f"?{position}"
    if not isinstance(item, dict):
        reason = "This piece of evidence is not an object."
        return PieceCheck(
            evidence_id=fallback_id,
            usable=False,
            checks={"shape": {"ok": False, "reason": reason}},
            reasons=[reason],
            warnings=[],
            item_key=_item_key(claim_id, piece_values={}, unusable_id=fallback_id),
        )

    shape, file_problems, quote_problems, rect_problems = (_Reasons() for _ in range(4))

    # Check 1: shape.
    raw_id = item.get("id")
    evidence_id = fallback_id
    if isinstance(raw_id, str) and EVIDENCE_ID.match(raw_id) and raw_id not in seen_ids:
        evidence_id = raw_id
    else:
        shape(f"The id {shown(raw_id)} is not valid or is used twice.")
    if isinstance(raw_id, str):
        seen_ids.add(raw_id)
    label = f"evidence {evidence_id}" if evidence_id != fallback_id else f"evidence #{position}"
    kind = item.get("kind") if item.get("kind") in KINDS else None
    if kind is None:
        shape(f"kind must be one of: {', '.join(KINDS)}.")
    relation = item.get("relation") if item.get("relation") in RELATIONS else None
    if relation is None:
        shape(f"relation must be one of: {', '.join(RELATIONS)}.")
    tier = item.get("source_tier") if item.get("source_tier") in TIERS else None
    if tier is None:
        shape(f"source_tier must be one of: {', '.join(TIERS)}.")
    source = _tidy_source(item.get("source"), shape)
    quote = _tidy_quote(item.get("quote"), shape)
    what_it_says = item.get("what_it_says")
    if not _is_text(what_it_says):
        shape("what_it_says is missing.")
        what_it_says = None
    elif len(what_it_says) > TEXT_LIMITS["what_it_says"]:
        shape("what_it_says is too long.")
        what_it_says = None
    else:
        what_it_says = what_it_says.strip()
    notes = item.get("agent_notes")
    if notes is None:
        notes = ""
    if not isinstance(notes, str) or len(notes) > TEXT_LIMITS["notes"]:
        shape("agent_notes is not text or is too long.")
        notes = None
    capture = item.get("capture")
    if not isinstance(capture, dict):
        shape("capture is missing.")
        capture = {}
    elif capture.get("tool") != TOOL_NAME:
        shape(f"The capture was not made by {TOOL_NAME} (coordinates are never written by hand).")

    # Check 2: files.
    if folder_problem is not None:
        file_problems(folder_problem)
    data, named = _check_files(capture, files, file_problems)
    image_size = _check_image(data.get("image"), capture, file_problems)
    context_box = None
    if "context_image" in data:
        context_box = _check_context_box(capture.get("context_box"), file_problems)

    # Check 3: the quote is in the source.
    page = None
    if quote is not None:
        page = _check_quote(kind, quote, capture, data, quote_problems)

    # Check 4: rectangles.
    rects = _check_rects(capture.get("rects"), rect_problems)

    checks = {
        "shape": shape.result(),
        "files": file_problems.result(),
        "quote": quote_problems.result(),
        "rects": rect_problems.result(),
    }
    reasons = [
        f"{checks[name]['reason']}"
        for name in ("shape", "files", "quote", "rects")
        if "reason" in checks[name]
    ]
    usable = all(entry["ok"] for entry in checks.values())

    # Check 5: numbers. A warning, never a refusal.
    warnings: list[dict[str, str]] = []
    if quote is not None:
        for number in sorted(numbers_in(str(claim.get("text", ""))) - numbers_in(quote)):
            warnings.append(
                {
                    "code": "number_not_in_quote",
                    "message": f"The claim says {_show_number(number)}, but the quote does not.",
                }
            )

    hashes = {slot: _sha(data.get(key)) for key, slot, _, _ in SLOTS}
    values = {
        "kind": kind,
        "relation": relation,
        "quote": quote,
        "page": page,
        "rects": rects,
        "hashes": hashes,
    }
    piece = PieceCheck(
        evidence_id=evidence_id,
        usable=usable,
        checks=checks,
        reasons=[f"{label}: {reason}" for reason in reasons],
        warnings=warnings,
        item_key=_item_key(
            claim_id,
            piece_values=values,
            unusable_id=None if usable else evidence_id,
        ),
        kind=kind,
        relation=relation,
        source_tier=tier,
        source=source,
        quote=quote,
        what_it_says=what_it_says,
        agent_notes=notes.strip() if isinstance(notes, str) else None,
    )
    if usable:
        piece.files = {
            slot: (named[key], hashes[slot] or "")
            for key, slot, _, _ in SLOTS
            if key in named and hashes[slot] is not None
        }
        piece.capture = _tidy_capture(capture, kind, image_size, context_box, page, rects)
    return piece


def _sha(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _show_number(number: Decimal) -> str:
    text = format(number.normalize(), "f")
    return text


def _tidy_source(source: object, shape: _Reasons) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        shape("source is missing.")
        return None
    ok = True
    out: dict[str, Any] = {}
    for key in ("url", "final_url"):
        value = source.get(key)
        if not _is_text(value) or len(value) > TEXT_LIMITS["url"] or not _http(value.strip()):
            shape(f"source.{key} must be an http or https address.")
            ok = False
        else:
            out[key] = value.strip()
    for key in ("publisher", "retrieved_at"):
        value = source.get(key)
        if not _is_text(value) or len(value) > TEXT_LIMITS[key]:
            shape(f"source.{key} is missing or too long.")
            ok = False
        else:
            out[key] = value.strip()
    for key in ("title", "author"):
        value = source.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            out[key] = None
        elif isinstance(value, str) and len(value) <= TEXT_LIMITS[key]:
            out[key] = value.strip()
        else:
            shape(f"source.{key} is not text or is too long.")
            ok = False
    archive = source.get("archive_url")
    if archive is None or (isinstance(archive, str) and not archive.strip()):
        out["archive_url"] = None
    elif isinstance(archive, str) and len(archive) <= TEXT_LIMITS["url"] and _http(archive.strip()):
        out["archive_url"] = archive.strip()
    else:
        shape("source.archive_url must be an http or https address, or null.")
        ok = False
    published = source.get("published")
    if published is None:
        out["published"] = None
    else:
        try:
            if not (isinstance(published, str) and DATE_TEXT.match(published)):
                raise ValueError
            date.fromisoformat(published)
            out["published"] = published
        except ValueError:
            shape("source.published must be a date written YYYY-MM-DD, or null.")
            ok = False
    return out if ok else None


def _tidy_quote(quote: object, shape: _Reasons) -> str | None:
    if not _is_text(quote):
        shape("quote is missing.")
        return None
    assert isinstance(quote, str)
    if len(quote) > QUOTE_MAX_CHARS:
        shape(f"The quote is too long (the limit is {QUOTE_MAX_CHARS} characters).")
        return None
    if len(evidence_text.normalise(quote)) < QUOTE_MIN_CHARS:
        shape(f"The quote is too short (at least {QUOTE_MIN_CHARS} characters).")
        return None
    return " ".join(quote.split())


# --- Check 2: files ----------------------------------------------------------------------------


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


def _check_files(
    capture: dict[str, Any], files: dict[str, FileRead], problem: _Reasons
) -> tuple[dict[str, bytes], dict[str, str]]:
    """Checks the files a capture names. Returns the bytes of those read as the right type, by
    result key, and the names the capture gave, by result key.
    """
    hashes = capture.get("sha256")
    if not isinstance(hashes, dict):
        problem("capture.sha256 is missing.")
        hashes = {}
    data: dict[str, bytes] = {}
    named: dict[str, str] = {}
    used: set[str] = set()
    for key, _slot, kind, limit in SLOTS:
        name = capture.get(key)
        if name is None:
            if key == "image":
                problem("capture.image is missing.")
            continue
        if not isinstance(name, str) or not PLAIN_NAME.match(name):
            problem(f"capture.{key}: the file name {shown(name)} is not a plain name.")
            continue
        if name in used:
            problem(f"capture.{key}: {name} is used for two files.")
            continue
        used.add(name)
        content = files.get(name)
        if content is None:
            problem(f"capture.{key}: {name} was not read.")
            continue
        if isinstance(content, FileProblem):
            problem(f"capture.{key}: {name} {content.reason}.")
            continue
        named[key] = name
        if len(content) > limit:
            problem(f"{name} is too large ({len(content)} bytes, the limit is {limit}).")
            continue
        if hashes.get(name) != hashlib.sha256(content).hexdigest():
            problem(f"{name} does not match its recorded SHA-256 (it was changed).")
        if not _file_type_ok(kind, content):
            problem(f"{name} is not a real {kind} file.")
            continue
        data[key] = content
    return data, named


def _check_image(
    content: bytes | None, capture: dict[str, Any], problem: _Reasons
) -> tuple[int, int] | None:
    """The image's own size must be `image_px`, and the viewport times its scale."""
    if content is None:
        return None
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        problem("The image cannot be read.")
        return None
    if width * height > MAX_IMAGE_PIXELS:
        problem("The image has too many pixels.")
        return None
    image_px = capture.get("image_px")
    if (
        not isinstance(image_px, list)
        or len(image_px) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in image_px)
        or image_px != [width, height]
    ):
        problem(f"image_px {shown(image_px)} is not the image's real size [{width}, {height}].")
        return None
    viewport = capture.get("viewport")
    if viewport is not None:
        try:
            expected = [
                viewport["width"] * viewport["device_scale"],
                viewport["height"] * viewport["device_scale"],
            ]
        except (KeyError, TypeError):
            problem("viewport must have width, height and device_scale.")
            return None
        if expected != [width, height]:
            problem(f"The image is {width}x{height}, but the viewport says {expected}.")
            return None
    return width, height


def _check_context_box(box: object, problem: _Reasons) -> list[float] | None:
    if box is None:
        return None
    if (
        not isinstance(box, list)
        or len(box) != 4
        or not all(_is_number(v) for v in box)
        or box[0] < -EPSILON
        or box[1] < -EPSILON
        or box[2] <= 0
        or box[3] <= 0
        or box[0] + box[2] > 1 + EPSILON
        or box[1] + box[3] > 1 + EPSILON
    ):
        problem("context_box is not [x, y, width, height] inside the context image.")
        return None
    return [float(v) for v in box]


# --- Check 3: the quote ------------------------------------------------------------------------


def _check_quote(
    kind: object, quote: str, capture: dict[str, Any], data: dict[str, bytes], problem: _Reasons
) -> int | None:
    """Finds the quote in the source's text. Returns the PDF page (None for a web capture)."""
    wanted = evidence_text.normalise(quote)
    if kind == "web":
        if "text_copy" not in data:
            problem("A web capture needs its text copy to check the quote.")
        elif not evidence_text.quote_in_text(data["text_copy"].decode("utf-8"), wanted):
            problem("The quote is not in the text copy.")
        return None
    if kind != "pdf":
        problem("The quote was not checked because the kind is not valid.")
        return None
    page = capture.get("page")
    if "source_copy" not in data:
        problem("A PDF capture needs its source copy to check the quote.")
        return None
    try:
        document = evidence_text.open_pdf(data["source_copy"])
    except evidence_text.PdfRefused as error:
        problem(str(error))
        return None
    try:
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= len(document):
            problem(f"page {shown(page)} is not a page of the PDF (1 to {len(document)}).")
            return None
        raw = evidence_text.page_text(document, page - 1)
    finally:
        document.close()
    if not evidence_text.quote_in_pdf_text(raw, wanted):
        problem(f"The quote is not on page {page} of the PDF.")
        return None
    return page


# --- Check 4: rectangles -----------------------------------------------------------------------


def _check_rects(rects: object, problem: _Reasons) -> list[list[float]] | None:
    if not isinstance(rects, list) or not rects:
        problem("rects is empty or missing.")
        return None
    if len(rects) > MAX_RECTS:
        problem(f"{len(rects)} rectangles, the limit is {MAX_RECTS}.")
        return None
    good: list[list[float]] = []
    valid = True
    for number, rect in enumerate(rects, start=1):
        if not isinstance(rect, list) or len(rect) != 4 or not all(_is_number(v) for v in rect):
            problem(f"Rectangle {number} is not [x, y, width, height].")
            valid = False
            continue
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            problem(f"Rectangle {number} is empty.")
            valid = False
        elif x < -EPSILON or y < -EPSILON or x + w > 1 + EPSILON or y + h > 1 + EPSILON:
            problem(f"Rectangle {number} is outside the image.")
            valid = False
        else:
            good.append([float(x), float(y), float(w), float(h)])
    return good if valid else None


# --- The stored values -------------------------------------------------------------------------


def _tidy_capture(
    capture: dict[str, Any],
    kind: str | None,
    image_size: tuple[int, int] | None,
    context_box: list[float] | None,
    page: int | None,
    rects: list[list[float]] | None,
) -> dict[str, Any]:
    """The `capture` block as stored: what EVD-007 and EVD-008 draw from. File names and hashes
    are left out (the stored paths and hashes are columns of the item).
    """
    viewport = capture.get("viewport")
    tidy_viewport = None
    if isinstance(viewport, dict):
        tidy_viewport = {
            key: viewport[key] for key in ("width", "height", "device_scale") if key in viewport
        }
    scale = capture.get("render_scale")
    version = capture.get("tool_version")
    return {
        "tool": TOOL_NAME,
        "tool_version": version if isinstance(version, str) and len(version) <= 20 else None,
        "image_px": list(image_size) if image_size is not None else None,
        "context_box": context_box,
        "page": page if kind == "pdf" else None,
        "viewport": tidy_viewport,
        "render_scale": float(scale) if _is_number(scale) else None,
        "rects": rects,
    }


def _item_key(claim_id: str, *, piece_values: dict[str, Any], unusable_id: str | None) -> str:
    """What tells an item that did not change from one import to the next: the claim, the kind,
    the relation, the quote (normalised), the page, the rectangles and the real hashes of the
    files. The piece's own id is left out, so renumbering keeps the owner's decisions. A piece
    that is not usable gets its id as well, so its key never equals a usable piece's.
    """
    rects = piece_values.get("rects")
    quote = piece_values.get("quote")
    hashes = piece_values.get("hashes") or {}
    payload: dict[str, Any] = {
        "claim": claim_id,
        "kind": piece_values.get("kind"),
        "relation": piece_values.get("relation"),
        "quote": evidence_text.normalise(quote) if isinstance(quote, str) else None,
        "page": piece_values.get("page"),
        "rects": [[round(v, 6) for v in rect] for rect in rects] if rects else None,
        "files": [hashes.get(slot) for slot in SLOT_ORDER],
    }
    if unusable_id is not None:
        payload["unusable"] = unusable_id
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()
