"""The checks the footage import makes on a round's results (FTG-011,
`Footage_broll_implementation_phases.md` §4.8, checks 1 to 5).

Pure: the caller (`services/footage_import.py`) has already read `result.json` and the files it
names, safely, and passes them in. Nothing here touches the disk or the database, apart from the
PDF and picture bytes it is given. The capture tool's `validate` applies checks 1 to 4 too, in the
same order and with the same rules, so what passes `validate` imports. The import does not trust
that run: it checks again.

- Check 1, the shape: the schema, the ids, every value one the contract allows.
- Check 2, the files: plain names, used once, within their size limit, the recorded SHA-256, the
  type read from the content, the picture's real size.
- Check 3, the video: ffprobe's facts. It needs the file on disk, so the import runs it
  (`video_media_problems` says what is wrong, given what ffprobe printed).
- Check 4, the places: `use` inside `window`, `cuts` inside `window`, focus rectangles inside the
  picture.
- Check 5, the warnings: never a refusal, shown on the review card.

A failure in checks 1 to 4 makes that piece unusable and gives its reason. The agent's words (the
summary, `what_it_shows`, notes) are data: they are length-checked here and stored as text. They
are never used as a path or as HTML.

**Times.** A video piece's `window`, `use`, `moment_s` and `cuts` are seconds of the *source* video
in the result. They are stored as they are in `footage_item.capture` (`footage_clips.video_times`
moves them back by the window's start), except `cuts`, which the item stores in seconds of the
stored video (the window's start taken off), as `footage_item.cuts` is.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

from app.services import evidence_text, ffmpeg
from app.services.evidence_checks import (
    EPSILON,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_PDF_BYTES,
    MAX_RECTS,
    MAX_TEXT_BYTES,
    PLAIN_NAME,
    TEXT_LIMITS,
    VIDEO_ID,
    FileProblem,
    FileRead,
    _file_type_ok,
    _http,
    _is_number,
    _is_text,
    _Reasons,
    shown,
)
from app.services.footage_frames import strip_layout

RESULT_SCHEMA: Final = "visio.footage.result"
RESULT_VERSION: Final = 1
TOOL_NAME: Final = "visio-footage-capture"

STATUSES: Final = ("found", "not_found", "blocked")
KINDS: Final = ("video", "image", "page", "pdf")
TIERS: Final = ("official", "press", "commons", "news", "creator", "other")
SAME_EVENT: Final = ("yes", "no", "unknown")
ON_SCREEN_TEXT: Final = ("none", "small", "large")
YOUTUBE_LICENCES: Final = ("standard", "creative_commons", "unknown")
# Tiers that are not the subject's own or an official source (a warning on the card).
UNOFFICIAL_TIERS: Final = ("news", "creator", "other")

DEFAULT_MAX_PIECES: Final = 3
MAX_ATTEMPTS: Final = 40
MAX_RESULT_BYTES: Final = 1024 * 1024
MAX_CLIP_BYTES: Final = 60 * 1024 * 1024
MAX_STRIP_BYTES: Final = MAX_IMAGE_BYTES

# A video piece's `use` lasts this long, and its window is at most this long.
CLIP_MIN_S: Final = 2.0
CLIP_MAX_S: Final = 15.0
MAX_SHORT_SIDE: Final = 1080
# Below this shorter side a video or a picture gets the low resolution warning.
LOW_RES_SHORT_SIDE: Final = 720
VIDEO_DURATION_TOLERANCE_S: Final = 0.5
FPS_TOLERANCE: Final = 0.01
VIDEO_CODEC: Final = "h264"
PIXEL_FORMAT: Final = "yuv420p"

# A page is captured from its top, at most this many screens tall, at the evidence viewports.
PAGE_HEIGHTS: Final = 4
_VIEWPORTS: Final = {
    "landscape": ([1280, 720], 2),
    "portrait": ([360, 640], 4),
}
# How far a PDF picture's shape may be from the page's.
PDF_ASPECT_TOLERANCE: Final = 0.01

LIMITS: Final = {
    **TEXT_LIMITS,
    "what_it_shows": 1000,
    "licence": 200,
    "event_date": 10,
}
_DATE_LENGTH: Final = 10
YOUTUBE_HOSTS: Final = ("youtube.com", "youtu.be")

# The files each kind may name: result key, short slot name, kind of file, size limit, required.
# The order is the order of the checks and of the files in an item's key.
_SLOTS: Final = {
    "image": (("image", "image", "image", MAX_IMAGE_BYTES, True),),
    "page": (
        ("image", "image", "png", MAX_IMAGE_BYTES, True),
        ("text_copy", "text", "text", MAX_TEXT_BYTES, True),
    ),
    "pdf": (
        ("image", "image", "png", MAX_IMAGE_BYTES, True),
        ("text_copy", "text", "text", MAX_TEXT_BYTES, True),
        ("source_copy", "pdf", "pdf", MAX_PDF_BYTES, True),
    ),
    "video": (
        ("media", "video", "mp4", MAX_CLIP_BYTES, True),
        ("strip", "strip", "jpeg", MAX_STRIP_BYTES, True),
    ),
}
_NO_SLOTS: Final[tuple[tuple[str, str, str, int, bool], ...]] = ()
_JPEG_SIGNATURE: Final = b"\xff\xd8\xff"
_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"


def slots_for(kind: object) -> tuple[tuple[str, str, str, int, bool], ...]:
    """The file slots of a kind of piece: result key, short slot name, kind of file, limit,
    required. A kind that is not known has none."""
    return _SLOTS.get(kind, _NO_SLOTS) if isinstance(kind, str) else _NO_SLOTS


def stored_extension(slot: str, content: bytes) -> str:
    """The extension a stored file gets, from its slot and its content: a picture is `jpg` or
    `png` as it really is, never as its name says."""
    if slot == "image":
        return "jpg" if content.startswith(_JPEG_SIGNATURE) else "png"
    return {"video": "mp4", "strip": "jpg", "text": "txt", "pdf": "pdf"}[slot]


def valid_piece_id(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 2 and value[0] == "p" and value[1] in "123456789"
    )


@dataclass
class PieceCheck:
    """The outcome for one piece."""

    # The id stored in the row: the agent's id when it is valid and first, else `?<position>`.
    piece_id: str
    usable: bool
    # {"shape": {"ok": true}, "files": {"ok": false, "reason": "a sentence"}, ...}
    checks: dict[str, dict[str, Any]]
    # Every reason a check failed, as sentences (for the report).
    reasons: list[str]
    warnings: list[dict[str, str]]
    item_key: str
    kind: str | None = None
    tier: str | None = None
    source: dict[str, Any] | None = None
    what_it_shows: str | None = None
    same_event: str | None = None
    event_date: str | None = None
    on_screen_text: str | None = None
    agent_notes: str | None = None
    # Tidied values of the capture block, set only for a usable piece.
    capture: dict[str, Any] | None = None
    # slot -> (file name in the mark folder, real SHA-256) of the files that were read as the
    # right type. The import copies them only when the piece is usable.
    files: dict[str, tuple[str, str]] = field(default_factory=dict)
    # A video's cut times in seconds of the stored video, for a usable video.
    cuts: list[float] | None = None
    # Seconds of the window, to compare with the file's own length (a video).
    window_s: float | None = None


@dataclass
class MarkCheck:
    """The outcome for one mark."""

    # None when the mark has no usable `result.json`.
    status: str | None
    summary: str
    attempts: list[dict[str, str]]
    problems: list[str]
    warnings: list[str]
    pieces: list[PieceCheck]
    # A `result.json` exists but cannot be used (not "no result").
    invalid: bool = False


# --- Reading helpers ---------------------------------------------------------------------------


def named_files(result: dict[str, Any], max_pieces: int) -> list[str]:
    """The plain names the first `max_pieces` pieces name, once each. A name that is not plain
    (a path, `scans/...`) is never listed, so it is never read."""
    pieces = result.get("pieces")
    names: list[str] = []
    if not isinstance(pieces, list):
        return names
    for item in pieces[:max_pieces]:
        capture = item.get("capture") if isinstance(item, dict) else None
        if not isinstance(capture, dict):
            continue
        for key, _slot, _kind, _limit, _required in slots_for(item.get("kind")):
            name = capture.get(key)
            if isinstance(name, str) and PLAIN_NAME.match(name) and name not in names:
                names.append(name)
    return names


def slot_limit(result: dict[str, Any], name: str) -> int:
    """The largest size a file may have, by the slot it is named for (the biggest of them when
    two slots name it; the check says that a file may not be used twice)."""
    limit = 0
    pieces = result.get("pieces")
    for item in pieces if isinstance(pieces, list) else []:
        capture = item.get("capture") if isinstance(item, dict) else None
        if isinstance(capture, dict):
            for key, _slot, _kind, size, _required in slots_for(item.get("kind")):
                if capture.get(key) == name:
                    limit = max(limit, size)
    return limit


# --- The mark ----------------------------------------------------------------------------------


def no_result(reason: str | None, *, invalid: bool) -> MarkCheck:
    """A mark with no usable result. `invalid` is true when a `result.json` was there. A mark with
    no result at all has no reason to give (`None`)."""
    return MarkCheck(
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
            and len(attempt["what"]) <= LIMITS["attempt"]
            and len(attempt["outcome"]) <= LIMITS["attempt"]
        ):
            attempts.append(
                {"what": attempt["what"].strip(), "outcome": attempt["outcome"].strip()}
            )
        else:
            problems.append("an attempt is not {what, outcome} of reasonable length.")
            return []
    return attempts


def check_mark(
    *,
    mark_id: str,
    round_id: str,
    max_pieces: int,
    orientation: str,
    result: dict[str, Any],
    files: dict[str, FileRead],
    folder_problem: str | None,
) -> MarkCheck:
    """Checks one mark's `result.json` and the files it names. `files` are the files the reader
    read by name, and `folder_problem` says that the mark's folder holds something that is never
    allowed (a link)."""
    problems: list[str] = []
    # Check 1 for the whole result. Any failure here makes the whole result unusable.
    if result.get("schema") != RESULT_SCHEMA or result.get("version") != RESULT_VERSION:
        problems.append("result.json is not a version 1 footage result.")
    if result.get("round_id") != round_id:
        problems.append(f"round_id is {shown(result.get('round_id'))}, not {shown(round_id)}.")
    if result.get("mark_id") != mark_id:
        problems.append("result.json is not this mark's result.")
    status = result.get("status")
    if status is None:
        problems.append("the status is not set (the report command was not run).")
    elif status not in STATUSES:
        problems.append(f"status {shown(status)} is not one of: {', '.join(STATUSES)}.")
    summary = result.get("summary")
    if not _is_text(summary):
        problems.append("the summary is empty (the report command was not run).")
    elif len(summary) > LIMITS["summary"]:
        problems.append("the summary is too long.")
    attempts = _check_attempts(result.get("attempts"), problems)
    pieces_value = result.get("pieces")
    if not isinstance(pieces_value, list):
        problems.append("pieces is not a list.")
    if problems:
        return no_result(" ".join(problems), invalid=True)
    assert isinstance(summary, str) and isinstance(pieces_value, list)

    # The status against the pieces. These are problems to show, and the status is kept.
    if status == "found" and not pieces_value:
        problems.append("The status is found but there is no piece.")
    if status in ("not_found", "blocked") and pieces_value:
        problems.append(f"The status is {status}, which means no pieces, but there are some.")
    if status == "not_found" and not attempts:
        problems.append("The status is not_found but no attempt is listed.")
    if folder_problem is not None:
        problems.append(folder_problem)
    examined = pieces_value[:max_pieces]
    if len(pieces_value) > max_pieces:
        problems.append(
            f"{len(pieces_value)} pieces, the limit is {max_pieces}. "
            "The first ones were looked at and the rest were left out."
        )

    pieces: list[PieceCheck] = []
    seen_ids: set[str] = set()
    seen_keys: dict[str, str] = {}
    for position, item in enumerate(examined, start=1):
        piece = _check_piece(
            item,
            position=position,
            mark_id=mark_id,
            orientation=orientation,
            files=files,
            seen_ids=seen_ids,
            folder_problem=folder_problem,
        )
        if piece.usable:
            earlier = seen_keys.get(piece.item_key)
            if earlier is not None:
                mark_unusable(
                    mark_id, piece, "duplicate", f"This is the same footage as {earlier}."
                )
            else:
                seen_keys[piece.item_key] = piece.piece_id
        pieces.append(piece)

    warnings: list[str] = []
    if pieces and not any(piece.usable for piece in pieces):
        warnings.append("No piece for this mark passed the checks.")
    return MarkCheck(
        status=status,
        summary=summary.strip(),
        attempts=attempts,
        problems=problems,
        warnings=warnings,
        pieces=pieces,
    )


def mark_unusable(mark_id: str, piece: PieceCheck, check: str, reason: str) -> None:
    """Makes a piece that passed the checks unusable for a reason found later (the media check of
    a video, which needs ffprobe; a duplicate). Its files are not copied, and its key becomes the
    key of an unusable piece."""
    label = f"piece {piece.piece_id}" if not piece.piece_id.startswith("?") else "piece"
    piece.usable = False
    piece.files = {}
    piece.capture = None
    piece.cuts = None
    piece.checks[check] = {"ok": False, "reason": reason}
    piece.reasons.append(f"{label}: {reason}")
    piece.item_key = _item_key(mark_id, values={}, unusable_id=piece.piece_id)


# --- One piece ---------------------------------------------------------------------------------


def _check_piece(
    item: object,
    *,
    position: int,
    mark_id: str,
    orientation: str,
    files: dict[str, FileRead],
    seen_ids: set[str],
    folder_problem: str | None,
) -> PieceCheck:
    fallback_id = f"?{position}"
    if not isinstance(item, dict):
        reason = "This piece is not an object."
        return PieceCheck(
            piece_id=fallback_id,
            usable=False,
            checks={"shape": {"ok": False, "reason": reason}},
            reasons=[reason],
            warnings=[],
            item_key=_item_key(mark_id, values={}, unusable_id=fallback_id),
        )

    shape, file_problems, place_problems = (_Reasons() for _ in range(3))

    # Check 1: shape.
    raw_id = item.get("id")
    piece_id = fallback_id
    if valid_piece_id(raw_id) and raw_id not in seen_ids:
        piece_id = str(raw_id)
    else:
        shape(f"The id {shown(raw_id)} is not valid or is used twice.")
    if isinstance(raw_id, str):
        seen_ids.add(raw_id)
    label = f"piece {piece_id}" if piece_id != fallback_id else f"piece #{position}"
    kind = _allowed(item.get("kind"), KINDS, "kind", shape)
    tier = _allowed(item.get("tier"), TIERS, "tier", shape)
    same_event = _allowed(item.get("same_event"), SAME_EVENT, "same_event", shape)
    on_screen_text = _allowed(item.get("on_screen_text"), ON_SCREEN_TEXT, "on_screen_text", shape)
    source = _tidy_source(item.get("source"), kind, shape)
    what_it_shows = item.get("what_it_shows")
    if not _is_text(what_it_shows):
        shape("what_it_shows is missing.")
        what_it_shows = None
    elif len(what_it_shows) > LIMITS["what_it_shows"]:
        shape("what_it_shows is too long.")
        what_it_shows = None
    else:
        what_it_shows = what_it_shows.strip()
    event_date = item.get("event_date")
    if not _date_or_none(event_date):
        shape("event_date must be a date written YYYY-MM-DD, or null.")
        event_date = None
    notes = item.get("agent_notes")
    if notes is None:
        notes = ""
    if not isinstance(notes, str) or len(notes) > LIMITS["notes"]:
        shape("agent_notes is not text or is too long.")
        notes = None
    capture = item.get("capture")
    if not isinstance(capture, dict):
        shape("capture is missing.")
        capture = {}
    elif capture.get("tool") != TOOL_NAME:
        shape(f"The capture was not made by {TOOL_NAME} (captures are never written by hand).")

    # Check 2: files.
    if folder_problem is not None:
        file_problems(folder_problem)
    slots = slots_for(kind)
    data, named = _check_files(capture, files, file_problems, slots)
    size = _check_image(data.get("image"), capture.get("image_px"), file_problems)

    focus_missing = False
    cuts: list[float] | None = None
    window_s: float | None = None
    tidy: dict[str, Any] | None = None
    short_side: int | None = None
    if kind == "video":
        cuts, window_s, tidy = _check_video_places(capture, place_problems)
        _check_strip_picture(capture, data.get("strip"), file_problems)
        video_px = capture.get("video_px")
        short_side = _short_side(video_px)
        if short_side is None:
            place_problems("capture.video_px must be [width, height].")
    elif kind in ("image", "page", "pdf") and size is not None:
        short_side = min(size)
        if kind == "page":
            _check_page_shape(orientation, capture, size, file_problems)
        document = None
        if kind == "pdf" and "source_copy" in data:
            try:
                document = evidence_text.open_pdf(data["source_copy"])
            except evidence_text.PdfRefused as error:
                file_problems(str(error))
        try:
            if document is not None:
                _check_pdf_shape(capture, document, size, file_problems)
            focus_missing = _check_focus(kind, capture, data, document, place_problems)
        finally:
            if document is not None:
                document.close()
        tidy = _tidy_still(capture, kind, size)

    checks = {
        "shape": shape.result(),
        "files": file_problems.result(),
        "places": place_problems.result(),
    }
    reasons = [
        str(checks[name]["reason"])
        for name in ("shape", "files", "places")
        if "reason" in checks[name]
    ]
    usable = all(entry["ok"] for entry in checks.values()) and tidy is not None

    hashes = {slot: _sha(data.get(key)) for key, slot, _, _, _ in slots}
    values: dict[str, Any] = {
        "kind": kind,
        "hashes": hashes,
        "slots": [slot for _, slot, _, _, _ in slots],
    }
    if kind == "video":
        values["use"] = _use_pair(capture)
    else:
        values["page"] = capture.get("page") if kind == "pdf" else None
        values["rects"] = _rounded_rects(capture.get("focus_rects"))
    piece = PieceCheck(
        piece_id=piece_id,
        usable=usable,
        checks=checks,
        reasons=[f"{label}: {reason}" for reason in reasons],
        warnings=[],
        item_key=_item_key(mark_id, values=values, unusable_id=None if usable else piece_id),
        kind=kind,
        tier=tier,
        source=source,
        what_it_shows=what_it_shows,
        same_event=same_event,
        event_date=event_date,
        on_screen_text=on_screen_text,
        agent_notes=notes.strip() if isinstance(notes, str) else None,
    )
    if usable:
        piece.files = {
            slot: (named[key], hashes[slot] or "")
            for key, slot, _, _, _ in slots
            if key in named and hashes[slot] is not None
        }
        piece.capture = tidy
        piece.cuts = cuts
        piece.window_s = window_s
        piece.warnings = _warnings(
            kind=kind,
            tier=tier,
            same_event=same_event,
            on_screen_text=on_screen_text,
            source=source,
            capture=capture,
            short_side=short_side,
            focus_missing=focus_missing,
        )
    return piece


def _allowed(value: object, allowed: tuple[str, ...], name: str, shape: _Reasons) -> str | None:
    """A value of an enumeration, or None (stored as NULL) with a reason when it is not one."""
    if isinstance(value, str) and value in allowed:
        return value
    shape(f"{name} must be one of: {', '.join(allowed)}.")
    return None


def _date_or_none(value: object) -> bool:
    if value is None:
        return True
    if not (isinstance(value, str) and len(value) == _DATE_LENGTH):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return value[4] == "-" and value[7] == "-"


def _sha(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _tidy_source(source: object, kind: str | None, shape: _Reasons) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        shape("source is missing.")
        return None
    ok = True
    out: dict[str, Any] = {}
    for key in ("url", "final_url"):
        value = source.get(key)
        if not _is_text(value) or len(value) > LIMITS["url"] or not _http(value.strip()):
            shape(f"source.{key} must be an http or https address.")
            ok = False
            continue
        out[key] = value.strip()
        if kind == "video":
            host = (urlsplit(out[key]).hostname or "").lower()
            if not any(host == name or host.endswith(f".{name}") for name in YOUTUBE_HOSTS):
                shape(f"source.{key} must be a YouTube address for a video.")
                ok = False
    for key in ("publisher", "retrieved_at"):
        value = source.get(key)
        if not _is_text(value) or len(value) > LIMITS[key]:
            shape(f"source.{key} is missing or too long.")
            ok = False
        else:
            out[key] = value.strip()
    for key in ("title", "licence"):
        value = source.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            out[key] = None
        elif isinstance(value, str) and len(value) <= LIMITS[key]:
            out[key] = value.strip()
        else:
            shape(f"source.{key} is not text or is too long.")
            ok = False
    licence_url = source.get("licence_url")
    if licence_url is None or (isinstance(licence_url, str) and not licence_url.strip()):
        out["licence_url"] = None
    elif (
        isinstance(licence_url, str)
        and len(licence_url) <= LIMITS["url"]
        and _http(licence_url.strip())
    ):
        out["licence_url"] = licence_url.strip()
    else:
        shape("source.licence_url must be an http or https address, or null.")
        ok = False
    published = source.get("published")
    if _date_or_none(published):
        out["published"] = published
    else:
        shape("source.published must be a date written YYYY-MM-DD, or null.")
        ok = False
    return out if ok else None


# --- Check 2: files ----------------------------------------------------------------------------


def _type_ok(wanted: str, content: bytes) -> bool:
    if wanted == "image":
        return content.startswith((_JPEG_SIGNATURE, _PNG_SIGNATURE))
    if wanted == "jpeg":
        return content.startswith(_JPEG_SIGNATURE)
    if wanted == "mp4":
        return content[4:8] == b"ftyp"
    return _file_type_ok(wanted, content)


_TYPE_NAMES: Final = {"image": "JPEG or PNG", "mp4": "MP4", "jpeg": "JPEG"}


def _check_files(
    capture: dict[str, Any],
    files: dict[str, FileRead],
    problem: _Reasons,
    slots: tuple[tuple[str, str, str, int, bool], ...],
) -> tuple[dict[str, bytes], dict[str, str]]:
    """Checks the files a capture names. Returns the bytes of those read as the right type, by
    result key, and the names the capture gave, by result key."""
    if not slots:
        return {}, {}
    hashes = capture.get("sha256")
    if not isinstance(hashes, dict):
        problem("capture.sha256 is missing.")
        hashes = {}
    data: dict[str, bytes] = {}
    named: dict[str, str] = {}
    used: set[str] = set()
    for key, _slot, kind, limit, required in slots:
        name = capture.get(key)
        if name is None:
            if required:
                problem(f"capture.{key} is missing.")
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
        if not _type_ok(kind, content):
            problem(f"{name} is not a real {_TYPE_NAMES.get(kind, kind)} file.")
            continue
        data[key] = content
    return data, named


def _picture_size(content: bytes) -> tuple[int, int] | None:
    """The size of a picture, read from its header. None when it cannot be read."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            return image.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        return None


def _decodes(content: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        return False
    return True


def _check_image(
    content: bytes | None, image_px: object, problem: _Reasons
) -> tuple[int, int] | None:
    """The picture can be read, is not too big, and `image_px` is its real size."""
    if content is None:
        return None
    size = _picture_size(content)
    if size is None:
        problem("The image cannot be read.")
        return None
    if size[0] * size[1] > MAX_IMAGE_PIXELS:
        problem("The image has too many pixels.")
        return None
    if not _decodes(content):
        problem("The image cannot be read.")
        return None
    width, height = size
    if (
        not isinstance(image_px, list)
        or len(image_px) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in image_px)
        or image_px != [width, height]
    ):
        problem(f"image_px {shown(image_px)} is not the image's real size [{width}, {height}].")
        return None
    return width, height


def _check_page_shape(
    orientation: str, capture: dict[str, Any], size: tuple[int, int], problem: _Reasons
) -> None:
    """A page picture is the viewport's width and from one to `PAGE_HEIGHTS` screens tall."""
    viewport, scale = _VIEWPORTS["portrait" if orientation == "portrait" else "landscape"]
    if capture.get("viewport") != viewport or capture.get("device_scale") != scale:
        problem(
            f"the viewport is {shown(capture.get('viewport'))} at scale "
            f"{shown(capture.get('device_scale'))}, but a {orientation} project is captured at "
            f"{viewport} at scale {scale}."
        )
        return
    width, height = size
    if width != viewport[0] * scale:
        problem(f"The image is {width} pixels wide, not {viewport[0] * scale}.")
    screen = viewport[1] * scale
    if height < screen or height > PAGE_HEIGHTS * screen:
        problem(
            f"The image is {height} pixels tall, but a page is from one to {PAGE_HEIGHTS} "
            f"screens ({screen} to {PAGE_HEIGHTS * screen} pixels)."
        )


def _check_pdf_shape(
    capture: dict[str, Any], document: Any, size: tuple[int, int], problem: _Reasons
) -> None:
    """The picture is the whole page: it has the page's shape."""
    page = capture.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= len(document):
        problem(f"page {shown(page)} is not a page of the PDF (1 to {len(document)}).")
        return
    pdf_page = document[page - 1]
    try:
        page_w, page_h = pdf_page.get_size()
    finally:
        pdf_page.close()
    if page_w <= 0 or page_h <= 0:
        problem("The PDF page has no size.")
    elif abs((size[0] / size[1]) / (page_w / page_h) - 1) > PDF_ASPECT_TOLERANCE:
        problem("The image does not have the shape of the PDF page (it must be the whole page).")


def _short_side(size: object) -> int | None:
    if (
        isinstance(size, list)
        and len(size) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in size)
    ):
        return min(size)
    return None


def _check_strip_picture(capture: dict[str, Any], strip: bytes | None, problem: _Reasons) -> None:
    """The strip can be read and has the size its own layout keys say. (That the layout is the
    one for the video's real length is checked with the media.)"""
    columns, rows = capture.get("strip_columns"), capture.get("strip_rows")
    tile = capture.get("strip_tile_px")
    frames, every = capture.get("strip_frames"), capture.get("strip_every_s")
    if not (
        _is_int(columns)
        and _is_int(rows)
        and _is_int(frames)
        and _is_number(every)
        and every > 0
        and isinstance(tile, list)
        and len(tile) == 2
        and all(_is_int(v) for v in tile)
    ):
        problem(
            "The strip's layout (strip_every_s, strip_columns, strip_rows, strip_tile_px, "
            "strip_frames) is missing or not numbers."
        )
        return
    if columns < 1 or rows < 1 or frames < 1 or tile[0] < 1 or tile[1] < 1:
        problem("The strip's layout has a value below one.")
        return
    if rows != math.ceil(frames / columns):
        problem("The strip's rows do not fit its frames and columns.")
        return
    if strip is None:
        return
    size = _picture_size(strip)
    if size is None or not _decodes(strip):
        problem("The strip cannot be read.")
        return
    if size != (columns * tile[0], rows * tile[1]):
        problem(
            f"The strip is {size[0]}x{size[1]}, but its layout makes "
            f"{columns * tile[0]}x{rows * tile[1]}."
        )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --- Check 4: the places -----------------------------------------------------------------------


def _pair(value: object) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    start, end = value.get("start_s"), value.get("end_s")
    if _is_number(start) and _is_number(end):
        return float(start), float(end)
    return None


def _use_pair(capture: dict[str, Any]) -> list[float] | None:
    found = _pair(capture.get("use"))
    return None if found is None else [round(found[0], 3), round(found[1], 3)]


def _rounded_rects(rects: object) -> list[list[float]] | None:
    if not isinstance(rects, list) or not rects:
        return None
    return [
        [round(float(v), 6) for v in rect]
        for rect in rects
        if isinstance(rect, list) and all(_is_number(v) for v in rect)
    ]


def _check_video_places(
    capture: dict[str, Any], problem: _Reasons
) -> tuple[list[float] | None, float | None, dict[str, Any] | None]:
    """The facts the tool wrote for a video, as its `validate` checks them. Returns the cut times
    in seconds of the stored video, the window's length and the tidied capture (None when a
    place is wrong). The media itself is probed by the import."""
    video_id = capture.get("video_id")
    if not (isinstance(video_id, str) and VIDEO_ID.match(video_id)):
        problem("capture.video_id is not a YouTube video id (11 characters).")
    if capture.get("youtube_licence") not in YOUTUBE_LICENCES:
        problem(f"capture.youtube_licence must be one of: {', '.join(YOUTUBE_LICENCES)}.")
    upload_date = capture.get("upload_date")
    if not _date_or_none(upload_date):
        problem("capture.upload_date must be a date written YYYY-MM-DD, or null.")
    for key in ("channel", "channel_id"):
        value = capture.get(key)
        if value is not None and not (isinstance(value, str) and len(value) <= LIMITS["publisher"]):
            problem(f"capture.{key} is not text or is too long.")
    fps = capture.get("fps")
    if not _is_number(fps) or not 0 < fps <= 240:
        problem("capture.fps must be a number above 0.")

    duration = capture.get("duration_s")
    window = _pair(capture.get("window"))
    use = _pair(capture.get("use"))
    ok = True
    if not _is_number(duration) or duration <= 0:
        problem("capture.duration_s must be a number above 0.")
        ok = False
    if window is None:
        problem("capture.window must be {start_s, end_s}.")
        ok = False
    if use is None:
        problem("capture.use must be {start_s, end_s}.")
        ok = False
    if not ok or window is None or use is None or not isinstance(duration, int | float):
        return None, None, None
    if window[0] < -EPSILON or window[1] <= window[0] or window[1] > duration + EPSILON:
        problem("the window must lie inside the video (0 to duration_s).")
        return None, None, None
    if use[0] < window[0] - EPSILON or use[1] > window[1] + EPSILON or use[1] <= use[0]:
        problem("use must lie inside the window.")
        return None, None, None
    length = use[1] - use[0]
    if not CLIP_MIN_S - EPSILON <= length <= CLIP_MAX_S + EPSILON:
        problem(
            f"use lasts {length:.1f} s, but it must last {CLIP_MIN_S:.0f} to {CLIP_MAX_S:.0f} s."
        )
        return None, None, None
    moment = capture.get("moment_s")
    if moment is not None:
        if not _is_number(moment):
            problem("moment_s must be a number or null.")
            return None, None, None
        if not use[0] - EPSILON <= moment <= use[1] + EPSILON:
            problem("moment_s must lie inside use.")
            return None, None, None
    cuts = capture.get("cuts")
    if not isinstance(cuts, list) or not all(_is_number(cut) for cut in cuts):
        problem("cuts must be a list of times in seconds.")
        return None, None, None
    if any(later <= earlier for earlier, later in zip(cuts, cuts[1:], strict=False)):
        problem("cuts must be in order, each later than the one before.")
        return None, None, None
    if any(not window[0] < cut < window[1] for cut in cuts):
        problem("every cut must lie inside the window.")
        return None, None, None
    if not (
        _is_text_or_none(capture.get("channel")) and _is_text_or_none(capture.get("channel_id"))
    ):
        return None, None, None
    version = capture.get("tool_version")
    tidy: dict[str, Any] = {
        "tool": TOOL_NAME,
        "tool_version": version if isinstance(version, str) and len(version) <= 20 else None,
        "video_id": video_id,
        "channel": capture.get("channel"),
        "channel_id": capture.get("channel_id"),
        "upload_date": upload_date,
        "youtube_licence": capture.get("youtube_licence"),
        "duration_s": float(duration),
        "window": {"start_s": window[0], "end_s": window[1]},
        "use": {"start_s": use[0], "end_s": use[1]},
        "moment_s": None if moment is None else float(moment),
        "video_px": capture.get("video_px"),
        "fps": float(fps) if _is_number(fps) else None,
        "strip_every_s": capture.get("strip_every_s"),
        "strip_columns": capture.get("strip_columns"),
        "strip_rows": capture.get("strip_rows"),
        "strip_tile_px": capture.get("strip_tile_px"),
        "strip_frames": capture.get("strip_frames"),
    }
    stored_cuts = [round(float(cut) - window[0], 3) for cut in cuts]
    return stored_cuts, window[1] - window[0], tidy


def _is_text_or_none(value: object) -> bool:
    return value is None or (isinstance(value, str) and len(value) <= LIMITS["publisher"])


def _check_focus(
    kind: str,
    capture: dict[str, Any],
    data: dict[str, bytes],
    document: Any,
    problem: _Reasons,
) -> bool:
    """`focus_rects` lie inside the image, and `focus_text` goes with them. An image has no focus.
    Returns True when focus words were asked for and are not in the page's text (a warning, never
    a refusal)."""
    rects = capture.get("focus_rects")
    focus_text = capture.get("focus_text")
    if kind == "image":
        if rects or focus_text is not None:
            problem("An image has no focus.")
        return False
    if not isinstance(rects, list):
        problem("focus_rects must be a list (empty when no focus was asked).")
        return False
    if len(rects) > MAX_RECTS:
        problem(f"{len(rects)} focus rectangles, the limit is {MAX_RECTS}.")
        return False
    valid = True
    for number, rect in enumerate(rects, start=1):
        if not (
            isinstance(rect, list) and len(rect) == 4 and all(_is_number(value) for value in rect)
        ):
            problem(f"Focus rectangle {number} is not [x, y, width, height].")
            valid = False
            continue
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            problem(f"Focus rectangle {number} is empty.")
            valid = False
        elif x < -EPSILON or y < -EPSILON or x + w > 1 + EPSILON or y + h > 1 + EPSILON:
            problem(f"Focus rectangle {number} is outside the image.")
            valid = False
    if not rects:
        if focus_text is not None:
            problem("focus_text is set but there are no focus rectangles.")
        return False
    if not _is_text(focus_text) or len(focus_text) > LIMITS["what_it_shows"]:
        problem("There are focus rectangles but focus_text is missing or too long.")
        return False
    if not valid:
        return False
    wanted = evidence_text.normalise(str(focus_text))
    if kind == "page":
        if "text_copy" not in data:
            return False
        return not evidence_text.quote_in_text(data["text_copy"].decode("utf-8"), wanted)
    page = capture.get("page")
    if document is None or not (_is_int(page) and 1 <= page <= len(document)):
        return False
    raw = evidence_text.page_text(document, page - 1)
    return not evidence_text.quote_in_pdf_text(raw, wanted)


def _tidy_still(capture: dict[str, Any], kind: str, size: tuple[int, int]) -> dict[str, Any]:
    """The `capture` block of an image, page or PDF as stored: what the review and the clip draw
    from. File names and hashes are left out (the stored paths and hashes are columns of the
    item)."""
    version = capture.get("tool_version")
    viewport = capture.get("viewport")
    scale = capture.get("render_scale")
    page_url = capture.get("page_url")
    tidy: dict[str, Any] = {
        "tool": TOOL_NAME,
        "tool_version": version if isinstance(version, str) and len(version) <= 20 else None,
        "image_px": list(size),
        "viewport": list(viewport) if kind == "page" and isinstance(viewport, list) else None,
        "device_scale": capture.get("device_scale") if kind == "page" else None,
        "page": capture.get("page") if kind == "pdf" else None,
        "render_scale": float(scale) if kind == "pdf" and _is_number(scale) else None,
        "page_url": (
            page_url.strip()
            if kind == "image"
            and isinstance(page_url, str)
            and len(page_url) <= LIMITS["url"]
            and _http(page_url.strip())
            else None
        ),
    }
    if kind in ("page", "pdf"):
        rects = capture.get("focus_rects")
        tidy["focus_rects"] = (
            [[float(v) for v in rect] for rect in rects] if isinstance(rects, list) else []
        )
        text = capture.get("focus_text")
        tidy["focus_text"] = " ".join(text.split()) if isinstance(text, str) and rects else None
    return tidy


# --- Check 3: the video's media ----------------------------------------------------------------


def video_media_problems(
    container: ffmpeg.ProbeResult | None,
    video: ffmpeg.VideoProbe | None,
    capture: dict[str, Any],
    window_s: float,
) -> list[str]:
    """Why a video is not what the capture tool makes and the render reads, as sentences. Pure:
    `container` and `video` are what ffprobe printed (None when it could not read the file),
    `capture` is the tidied capture of the piece and `window_s` the window's length."""
    if container is None or video is None:
        return ["The video cannot be read (ffprobe found no picture in it)."]
    problems: list[str] = []
    if container.video_stream_count != 1:
        problems.append(
            f"The video needs exactly one video stream (it has {container.video_stream_count})."
        )
    if container.audio_streams or video.audio is not None:
        problems.append("The video has sound, but footage is always muted.")
    if video.codec_name != VIDEO_CODEC:
        problems.append(f"The video codec is {video.codec_name!r}, not {VIDEO_CODEC}.")
    if video.pix_fmt != PIXEL_FORMAT:
        problems.append(f"The pixel format is {video.pix_fmt!r}, not {PIXEL_FORMAT}.")
    if not video.width or not video.height:
        problems.append("The video has no picture size.")
    else:
        if min(video.width, video.height) > MAX_SHORT_SIDE:
            problems.append(
                f"The video's shorter side is {min(video.width, video.height)} px, "
                f"the limit is {MAX_SHORT_SIDE}."
            )
        if capture.get("video_px") != [video.width, video.height]:
            problems.append(
                f"The video is {video.width}x{video.height}, but video_px says "
                f"{capture.get('video_px')}."
            )
    if video.fps is None or video.fps <= 0:
        problems.append("The video has no frame rate.")
    elif abs(float(capture.get("fps") or 0) - video.fps) > FPS_TOLERANCE:
        problems.append(
            f"fps {shown(capture.get('fps'))} is not the video's real rate ({video.fps:.3f})."
        )
    if video.duration_s is None or abs(video.duration_s - window_s) > VIDEO_DURATION_TOLERANCE_S:
        shown_length = "unknown" if video.duration_s is None else f"{video.duration_s:.2f} s"
        problems.append(
            f"The video lasts {shown_length}, but its window is {window_s:.2f} s "
            f"(more than {VIDEO_DURATION_TOLERANCE_S} s apart)."
        )
    elif not problems:
        problems.extend(_strip_layout_problems(capture, video.duration_s, window_s))
    return problems


def _strip_layout_problems(
    capture: dict[str, Any], duration_s: float, window_s: float
) -> list[str]:
    """The strip keys are the layout the app uses for a video of this length. The tool measured
    the file's own length and the app measures it again, which can differ by a frame, so the
    layout for either that length or the window's is accepted."""
    candidates = [strip_layout(duration_s), strip_layout(window_s)]
    for layout in candidates:
        if (
            capture.get("strip_every_s") == layout.every_s
            and capture.get("strip_columns") == layout.columns
            and capture.get("strip_rows") == layout.rows
            and capture.get("strip_tile_px") == [layout.tile_w, layout.tile_h]
            and capture.get("strip_frames") == layout.frames
        ):
            return []
    wanted = candidates[0]
    return [
        f"The strip's layout is not the app's for a video of {duration_s:.1f} s "
        f"({wanted.frames} frames of {wanted.every_s} s in {wanted.columns} columns of "
        f"{wanted.tile_w}x{wanted.tile_h})."
    ]


# --- Check 5: the warnings ---------------------------------------------------------------------


def _same(first: object, second: object) -> bool:
    def clean(value: object) -> str:
        return " ".join(str(value).split()).casefold()

    return clean(first) == clean(second)


def _warnings(
    *,
    kind: str | None,
    tier: str | None,
    same_event: str | None,
    on_screen_text: str | None,
    source: dict[str, Any] | None,
    capture: dict[str, Any],
    short_side: int | None,
    focus_missing: bool,
) -> list[dict[str, str]]:
    """The warnings of §4.8 check 5, each `{code, message}`. They never refuse a piece."""
    found: list[dict[str, str]] = []

    def warn(code: str, message: str) -> None:
        found.append({"code": code, "message": message})

    if kind in ("video", "image") and short_side is not None and short_side < LOW_RES_SHORT_SIDE:
        warn(
            "low_resolution",
            f"The picture is small (its shorter side is {short_side} pixels); it may look soft "
            "full screen.",
        )
    if same_event == "no":
        warn(
            "file_footage",
            "File footage: this shows another occasion, not the event the words describe.",
        )
    if same_event == "unknown":
        warn("event_not_checked", "It was not checked that this shows the event described.")
    if on_screen_text in ("small", "large"):
        warn(
            "text_on_picture",
            "There is text on the picture "
            + ("(a small logo or caption)." if on_screen_text == "small" else "(large text)."),
        )
    if tier in UNOFFICIAL_TIERS:
        warn("not_official", "This is not an official source.")
    publisher = source.get("publisher") if source is not None else None
    channel = capture.get("channel")
    if kind == "video" and isinstance(channel, str) and channel and publisher:
        if not _same(channel, publisher):
            warn(
                "channel_not_publisher",
                f"The YouTube channel ({channel[:60]}) is not the publisher named "
                f"({str(publisher)[:60]}).",
            )
    licence = source.get("licence") if source is not None else None
    unknown_licence = not licence and (
        tier == "commons"
        or kind == "image"
        or (kind == "video" and capture.get("youtube_licence") == "unknown")
    )
    if unknown_licence:
        warn("licence_unknown", "The licence is not known.")
    if focus_missing:
        warn("focus_not_found", "The focus words were not found in the page's own text.")
    return found


# --- The item key ------------------------------------------------------------------------------


def _item_key(mark_id: str, *, values: dict[str, Any], unusable_id: str | None) -> str:
    """What tells an item that did not change from one import to the next: the mark, the kind, the
    part used (a video), the page and focus rectangles, and the real hashes of the files. The
    piece's own id is left out, so renumbering keeps the owner's decisions. A piece that is not
    usable gets its id as well, so its key never equals a usable piece's. 64 characters."""
    hashes = values.get("hashes") or {}
    slots = values.get("slots") or []
    payload: dict[str, Any] = {
        "mark": mark_id,
        "kind": values.get("kind"),
        "use": values.get("use"),
        "page": values.get("page"),
        "rects": values.get("rects"),
        "files": [hashes.get(slot) for slot in slots],
    }
    if unusable_id is not None:
        payload["unusable"] = unusable_id
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()
