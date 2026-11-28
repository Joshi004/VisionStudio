"""The owner's own photos and videos on a footage mark (FTG-003,
`Footage_broll_implementation_phases.md` FT-5 and FT-11).

An owner's file is a `footage_item` row with `origin` `owner` and no import. It counts as accepted
when it is added: the same transaction writes a `footage_decision` version
(`services/footage_decisions.py`) that accepts it and shows it after the mark's other pieces.
Taking a file off the mark, changing the order, and moving a video's start and end are decision
versions too. Stored rows and files are never changed or deleted by these actions.

- **An image** (PNG, JPEG or WebP, at most 20 MB and 40 M pixels, checked from its content) is
  stored at once and is usable. A WebP is stored as a PNG.
- **A video** (an MP4 or MOV family file, or Matroska or WebM, with one video stream, at most
  500 MB and 10 minutes) is stored as it came (`upload_*`), and the job `prepare_footage_file`
  makes the copy that is shown: H.264, no sound, its strip of frames and its cut times
  (`jobs/prepare_footage_file.py`, `services/footage_frames.py`). Until then the item is not
  usable.

An item's `piece_id` is `o<n>` (n counts every file ever added to the mark) and its `item_key` is
`owner-<32 hex>`: an owner's file is never imported again, so the key never has to be worked out
from its content.

`footage_item.capture` of an owner's file: an image `{image_px: [width, height]}`; a video
`{duration_s, use: {start_s, end_s}}` first, and after the job also `video_px`, `fps`,
`strip_every_s`, `strip_columns`, `strip_rows`, `strip_tile_px` and `strip_frames`.
"""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from collections.abc import AsyncIterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FootageItem, Job, Project
from app.jobs import store
from app.services import footage_clips, footage_decisions, footage_marks, frame_images
from app.services.ffmpeg import probe
from app.services.storage import TempFile, TooLargeError, get_storage, media_url

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "prepare_footage_file"
ITEM_KEY: Final = "item_id"

KIND_IMAGE: Final = "image"
KIND_VIDEO: Final = "video"
KINDS: Final = (KIND_IMAGE, KIND_VIDEO)

IMAGE_MAX_MB: Final = 20
IMAGE_MAX_BYTES: Final = IMAGE_MAX_MB * 1024 * 1024
VIDEO_MAX_MB: Final = 500
VIDEO_MAX_BYTES: Final = VIDEO_MAX_MB * 1024 * 1024
VIDEO_MAX_S: Final = 600.0
VIDEO_MIN_S: Final = 2.0
CREDIT_MAX_CHARS: Final = 120
MAX_FILES_PER_MARK: Final = 9

# The part of a video that is shown, in steps of this many seconds (FTG-003 Scope).
USE_STEP_S: Final = 0.5
# The first part shown when the owner has not moved it, and the limits of what the owner may set.
DEFAULT_USE_S: Final = 15.0
USE_MIN_S: Final = 2.0
USE_MAX_S: Final = 30.0
_EPSILON: Final = 1e-6

# ffprobe's `format_name` of the files accepted, and the extension each is stored with. Any other
# format (a playlist, an image sequence, a raw stream) is refused.
_VIDEO_FORMATS: Final[dict[str, str]] = {
    "mov,mp4,m4a,3gp,3g2,mj2": "mp4",
    "matroska,webm": "mkv",
}

STATUS_PREPARING: Final = "preparing"
STATUS_READY: Final = "ready"
STATUS_FAILED: Final = "failed"

NOT_FOUND_MARK: Final = "There is no such footage mark."
NOT_FOUND_FILE: Final = "There is no such file."
MARK_CHANGED_MESSAGE: Final = (
    "The words of this mark are no longer in the story, so a file cannot be added to it."
)

# One at a time, so two uploads to one mark cannot take the same piece id or both pass the limit.
_ADD_LOCK = asyncio.Lock()


class FootageFilesError(Exception):
    """A request that cannot be done. The message is meant to be shown to the user."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# --- Checks (pure) -------------------------------------------------------------------------


def clean_credit(credit: str | None) -> str | None:
    """The owner's credit line as one line of plain text, or None when it is empty. Raises
    FootageFilesError when it is too long."""
    if credit is None:
        return None
    cleaned = " ".join("".join(ch for ch in credit if ch.isprintable() or ch.isspace()).split())
    if len(cleaned) > CREDIT_MAX_CHARS:
        raise FootageFilesError(422, f"A credit can be at most {CREDIT_MAX_CHARS} characters.")
    return cleaned or None


def _on_grid(seconds: float) -> bool:
    return abs(seconds / USE_STEP_S - round(seconds / USE_STEP_S)) < _EPSILON


def default_use(duration_s: float) -> dict[str, float]:
    """The part of a video shown until the owner moves it: the first 15 seconds."""
    return {"start_s": 0.0, "end_s": round(min(DEFAULT_USE_S, duration_s), 3)}


def check_use(start_s: float, end_s: float, duration_s: float) -> None:
    """Checks the start and end the owner chose for a video of `duration_s` seconds. Both are
    multiples of half a second (the end may also be the very end of the video), the part lies
    inside the video and lasts 2 to 30 seconds. Raises FootageFilesError.
    """
    if not (math.isfinite(start_s) and math.isfinite(end_s)):
        raise FootageFilesError(422, "The start and the end must be numbers.")
    at_the_end = abs(end_s - duration_s) < 0.0015
    if not _on_grid(start_s) or not (_on_grid(end_s) or at_the_end):
        raise FootageFilesError(422, "The start and the end must be in steps of half a second.")
    if start_s < 0 or end_s > duration_s + 0.0015:
        raise FootageFilesError(422, "The part shown must lie inside the video.")
    length = end_s - start_s
    if length < USE_MIN_S - _EPSILON or length > USE_MAX_S + _EPSILON:
        raise FootageFilesError(
            422, f"The part shown must last {USE_MIN_S:g} to {USE_MAX_S:g} seconds."
        )


# --- Reading marks and items ---------------------------------------------------------------


def _require_wanted(project: Project) -> None:
    if not footage_marks.wanted(project):
        raise FootageFilesError(422, footage_marks.OFF_MESSAGE)


async def _counting_mark(session: AsyncSession, project: Project, mark_id: str) -> dict[str, Any]:
    """The mark as it stands in the story, when files can be added to it. Raises
    FootageFilesError."""
    reason = footage_marks.blocked_reason(project)
    if reason is not None:
        raise FootageFilesError(422, reason)
    state = await footage_marks.state(session, project)
    mark = next((m for m in state.marks if m["id"] == mark_id), None)
    if mark is None:
        raise FootageFilesError(404, NOT_FOUND_MARK)
    if not footage_marks.is_active(mark) or mark["words_changed"]:
        raise FootageFilesError(422, MARK_CHANGED_MESSAGE)
    return mark


async def _owner_item(session: AsyncSession, project: Project, item_key: str) -> FootageItem:
    statement = select(FootageItem).where(
        FootageItem.project_id == project.id,
        FootageItem.item_key == item_key,
        FootageItem.origin == "owner",
    )
    item = (await session.execute(statement)).scalars().first()
    if item is None:
        raise FootageFilesError(404, NOT_FOUND_FILE)
    return item


async def _shown_count(session: AsyncSession, project: Project, mark_id: str) -> int:
    row = await footage_decisions.latest(session, project.id)
    return len(footage_decisions.shown_keys(row.content if row is not None else None, mark_id))


async def _next_piece_number(session: AsyncSession, project_id: int, mark_id: str) -> int:
    statement = select(func.count(FootageItem.id)).where(
        FootageItem.project_id == project_id,
        FootageItem.mark_id == mark_id,
        FootageItem.origin == "owner",
    )
    return int((await session.execute(statement)).scalar_one()) + 1


# --- Adding a file -------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredFile:
    item_key: str
    kind: str
    # The job that makes a video ready, or None for an image.
    job_id: int | None


async def receive_file(
    session: AsyncSession,
    project: Project,
    mark_id: str,
    kind: str,
    credit: str | None,
    chunks: AsyncIterable[bytes],
    content_length: int | None,
) -> StoredFile:
    """Receives, checks and stores a photo or a video the owner adds to a mark, accepts it and
    shows it after the mark's other files. A video also queues the job that makes it ready.
    Commits. Temporary files never outlive the call, and files stored by a call that fails are
    removed again. Raises FootageFilesError.
    """
    if kind not in KINDS:
        raise FootageFilesError(422, "The file must be an image or a video.")
    cleaned_credit = clean_credit(credit)
    await _counting_mark(session, project, mark_id)
    if await _shown_count(session, project, mark_id) >= MAX_FILES_PER_MARK:
        raise FootageFilesError(422, f"A mark can have at most {MAX_FILES_PER_MARK} of your files.")
    project_id = project.id
    max_bytes = IMAGE_MAX_BYTES if kind == KIND_IMAGE else VIDEO_MAX_BYTES
    too_large = f"The file is larger than {max_bytes // (1024 * 1024)} MB."
    if content_length is not None and content_length > max_bytes:
        raise FootageFilesError(413, too_large)
    # No transaction stays open while the file is received and checked.
    await session.commit()

    storage = get_storage()
    try:
        temp = await storage.receive(chunks, max_bytes=max_bytes)
    except TooLargeError:
        raise FootageFilesError(413, too_large) from None
    temps: list[TempFile | Path] = [temp]
    stored_paths: list[str] = []
    try:
        if temp.size_bytes == 0:
            raise FootageFilesError(422, "The file is empty.")
        if kind == KIND_IMAGE:
            fields = await _store_image(temp, project_id, temps, stored_paths)
        else:
            fields = await _store_video(temp, project_id, stored_paths)

        async with _ADD_LOCK:
            await session.refresh(project)
            await _counting_mark(session, project, mark_id)
            if await _shown_count(session, project, mark_id) >= MAX_FILES_PER_MARK:
                raise FootageFilesError(
                    422, f"A mark can have at most {MAX_FILES_PER_MARK} of your files."
                )
            number = await _next_piece_number(session, project_id, mark_id)
            item = FootageItem(
                project_id=project_id,
                import_id=None,
                mark_id=mark_id,
                piece_id=f"o{number}",
                item_key=f"owner-{uuid.uuid4().hex}",
                origin="owner",
                kind=kind,
                credit=cleaned_credit,
                **fields,
            )
            session.add(item)
            await session.flush()
            await footage_decisions.add_accepted(session, project, mark_id, item.item_key)
            job_id: int | None = None
            if kind == KIND_VIDEO:
                job, _created = await store.create_job(
                    session,
                    project_id=project_id,
                    type=JOB_TYPE,
                    provider="local",
                    input={ITEM_KEY: item.id},
                    commit=False,
                    dedupe_key=ITEM_KEY,
                )
                job_id = job.id
            await session.commit()
    except BaseException:
        await session.rollback()
        for path in stored_paths:
            try:
                await storage.delete_media(path)
            except Exception:  # A file that cannot be removed is left; it is not referenced.
                _logger.warning("a file of a failed footage upload was left: %s", path)
        raise
    finally:
        for leftover in temps:
            storage.discard(leftover)

    _logger.info(
        "footage file %s added to mark %s of project %d (%s, %d bytes)",
        item.item_key,
        mark_id,
        project_id,
        kind,
        temp.size_bytes,
    )
    return StoredFile(item_key=item.item_key, kind=kind, job_id=job_id)


def _webp_to_png(source: Path, dest: Path) -> None:
    """Blocking: writes the WebP at `source` as a PNG at `dest`, keeping transparency."""
    with Image.open(source, formats=["WEBP"]) as image:
        image.load()
        converted = image if image.mode in ("RGB", "RGBA", "L", "LA") else image.convert("RGBA")
        converted.save(dest, "PNG")


async def _store_image(
    temp: TempFile, project_id: int, temps: list[TempFile | Path], stored_paths: list[str]
) -> dict[str, Any]:
    """Checks the image from its content and stores it (a WebP as a PNG). Returns the item's
    fields. Raises FootageFilesError."""
    storage = get_storage()
    try:
        info = await frame_images.run_pillow(frame_images.inspect_image, temp.path)
    except frame_images.FrameRejected as exc:
        raise FootageFilesError(exc.status_code, exc.message) from exc
    to_store, ext = temp, info.ext
    if info.ext == "webp":
        converted = storage.new_temp_path("png")
        temps.append(converted)
        try:
            await frame_images.run_pillow(_webp_to_png, temp.path, converted)
        except (OSError, ValueError) as exc:
            raise FootageFilesError(422, "The image could not be read. It may be damaged.") from exc
        to_store, ext = await storage.describe_temp(converted), "png"
    stored = await storage.save(to_store, project_id, ext)
    stored_paths.append(stored.relative_path)
    return {
        "image_path": stored.relative_path,
        "image_sha256": to_store.sha256,
        "capture": {"image_px": [info.width, info.height]},
        "usable": True,
    }


async def _store_video(temp: TempFile, project_id: int, stored_paths: list[str]) -> dict[str, Any]:
    """Checks the video with ffprobe and stores it as it came. Returns the item's fields; the
    item is not usable until `prepare_footage_file` has made the copy that is shown. Raises
    FootageFilesError."""
    found = await probe(temp.path)
    if found is None:
        raise FootageFilesError(422, "The file could not be read as a video.")
    ext = _VIDEO_FORMATS.get(found.format_name)
    if ext is None:
        raise FootageFilesError(422, "Upload an MP4, MOV, MKV or WebM video.")
    if found.video_stream_count != 1:
        raise FootageFilesError(
            422,
            "The file has no picture."
            if found.video_stream_count == 0
            else "The video must have exactly one picture track.",
        )
    duration_s = found.duration_s
    if duration_s is None or not math.isfinite(duration_s) or duration_s <= 0:
        raise FootageFilesError(422, "The length of the video could not be read.")
    if duration_s > VIDEO_MAX_S:
        raise FootageFilesError(422, f"A video can be at most {VIDEO_MAX_S / 60:g} minutes long.")
    if duration_s < VIDEO_MIN_S:
        raise FootageFilesError(422, f"A video must last at least {VIDEO_MIN_S:g} seconds.")
    duration_s = round(duration_s, 3)
    stored = await get_storage().save(temp, project_id, ext)
    stored_paths.append(stored.relative_path)
    return {
        "upload_path": stored.relative_path,
        "upload_sha256": temp.sha256,
        "capture": {"duration_s": duration_s, "use": default_use(duration_s)},
        "usable": False,
    }


# --- The owner's other actions -------------------------------------------------------------


async def remove_file(session: AsyncSession, project: Project, item_key: str) -> None:
    """Takes a file off its mark. The item and its files stay stored. Commits. Raises
    FootageFilesError."""
    _require_wanted(project)
    item = await _owner_item(session, project, item_key)
    try:
        await footage_decisions.remove_item(session, project, item.mark_id, item_key)
    except footage_decisions.FootageDecisionError as exc:
        raise FootageFilesError(422, str(exc)) from exc


async def reorder_files(
    session: AsyncSession, project: Project, mark_id: str, shown: list[str]
) -> None:
    """Puts the files shown on a mark in a new order. Commits. Raises FootageFilesError."""
    _require_wanted(project)
    state = await footage_marks.state(session, project)
    if not any(m["id"] == mark_id for m in state.marks):
        raise FootageFilesError(404, NOT_FOUND_MARK)
    try:
        await footage_decisions.reorder(session, project, mark_id, shown)
    except footage_decisions.FootageDecisionError as exc:
        raise FootageFilesError(422, str(exc)) from exc


async def set_use(
    session: AsyncSession, project: Project, item_key: str, start_s: float, end_s: float
) -> None:
    """Moves where a video file starts and ends. Commits. Raises FootageFilesError."""
    _require_wanted(project)
    item = await _owner_item(session, project, item_key)
    if item.kind != KIND_VIDEO:
        raise FootageFilesError(422, "Only a video has a start and an end.")
    capture = item.capture if isinstance(item.capture, dict) else {}
    duration_s = capture.get("duration_s")
    if not isinstance(duration_s, int | float) or isinstance(duration_s, bool):
        raise FootageFilesError(422, "The length of the video is not known.")
    check_use(start_s, end_s, float(duration_s))
    try:
        await footage_decisions.set_use(session, project, item.mark_id, item_key, start_s, end_s)
    except footage_decisions.FootageDecisionError as exc:
        raise FootageFilesError(422, str(exc)) from exc


# --- Reading the state ---------------------------------------------------------------------


@dataclass(frozen=True)
class FileView:
    """One of the owner's files shown on a mark."""

    item_key: str
    mark_id: str
    kind: str
    credit: str | None
    status: str
    error: str | None
    # The picture of an image, or the prepared video (None until it is ready).
    media_url: str | None
    strip_url: str | None
    strip: dict[str, Any] | None
    width: int | None
    height: int | None
    duration_s: float | None
    use: dict[str, float] | None
    # The newest preview of the file (FTG-005), None when none was made.
    preview: footage_clips.Preview | None = None


@dataclass(frozen=True)
class FilesState:
    # Every file shown on each mark, in the order shown. Empty for a project without footage.
    files: list[FileView]
    # Whether a video of the project is still being made ready.
    preparing: bool


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _size(pixels: Any) -> tuple[int | None, int | None]:
    """`[width, height]` of a capture as a pair, or `(None, None)` when it is not that."""
    if isinstance(pixels, list) and len(pixels) == 2 and all(isinstance(v, int) for v in pixels):
        return pixels[0], pixels[1]
    return None, None


def _view(item: FootageItem, use: dict[str, float] | None, busy: set[int]) -> FileView:
    capture = item.capture if isinstance(item.capture, dict) else {}
    checks = item.checks if isinstance(item.checks, dict) else {}
    error: str | None = None
    if item.kind == KIND_IMAGE:
        status = STATUS_READY if item.usable else STATUS_FAILED
        width, height = _size(capture.get("image_px"))
        return FileView(
            item_key=item.item_key,
            mark_id=item.mark_id,
            kind=KIND_IMAGE,
            credit=item.credit,
            status=status,
            error=None,
            media_url=media_url(item.image_path) if item.image_path else None,
            strip_url=None,
            strip=None,
            width=width,
            height=height,
            duration_s=None,
            use=None,
        )
    if item.usable:
        status = STATUS_READY
    elif isinstance(checks.get("prepare"), str):
        status, error = STATUS_FAILED, checks["prepare"]
    elif item.id in busy:
        status = STATUS_PREPARING
    else:
        status, error = STATUS_FAILED, "The video was not made ready. Remove it and add it again."
    width, height = _size(capture.get("video_px"))
    strip = None
    if item.usable and item.strip_path:
        strip = {
            key: capture.get(key)
            for key in (
                "strip_every_s",
                "strip_columns",
                "strip_rows",
                "strip_tile_px",
                "strip_frames",
            )
        }
    return FileView(
        item_key=item.item_key,
        mark_id=item.mark_id,
        kind=KIND_VIDEO,
        credit=item.credit,
        status=status,
        error=error,
        media_url=media_url(item.video_path) if item.usable and item.video_path else None,
        strip_url=media_url(item.strip_path) if item.usable and item.strip_path else None,
        strip=strip,
        width=width,
        height=height,
        duration_s=_number(capture.get("duration_s")),
        use=use,
    )


async def _busy_item_ids(session: AsyncSession, project_id: int) -> set[int]:
    """The ids of the items whose `prepare_footage_file` job is waiting or running."""
    statement = select(Job).where(
        Job.project_id == project_id,
        Job.type == JOB_TYPE,
        Job.status.in_(store.ACTIVE_STATUSES),
    )
    jobs = (await session.execute(statement.execution_options(populate_existing=True))).scalars()
    found: set[int] = set()
    for job in jobs:
        value = job.input.get(ITEM_KEY) if isinstance(job.input, dict) else None
        if isinstance(value, int) and not isinstance(value, bool):
            found.add(value)
    return found


async def files_state(session: AsyncSession, project: Project) -> FilesState:
    """The owner's files shown on each mark, with where they stand. A project without footage
    reads nothing from the tables."""
    if not footage_marks.wanted(project):
        return FilesState(files=[], preparing=False)
    decisions = await footage_decisions.latest(session, project.id)
    content = decisions.content if decisions is not None else None
    entries = footage_decisions.marks_of(content)
    shown: list[tuple[str, str]] = [
        (entry["mark_id"], key) for entry in entries for key in entry["shown"]
    ]
    if not shown:
        return FilesState(files=[], preparing=False)
    statement = select(FootageItem).where(
        FootageItem.project_id == project.id,
        FootageItem.origin == "owner",
        FootageItem.item_key.in_([key for _mark, key in shown]),
    )
    items = {
        item.item_key: item
        for item in (
            await session.execute(statement.execution_options(populate_existing=True))
        ).scalars()
    }
    busy = await _busy_item_ids(session, project.id)
    uses = {entry["mark_id"]: entry["use"] for entry in entries}
    files: list[FileView] = []
    for mark_id, key in shown:
        item = items.get(key)
        if item is None:
            continue
        use: dict[str, float] | None = None
        if item.kind == KIND_VIDEO:
            moved = uses.get(mark_id, {}).get(key)
            capture = item.capture if isinstance(item.capture, dict) else {}
            use = moved if isinstance(moved, dict) else capture.get("use")
        files.append(_view(item, use, busy))
    previews = await footage_clips.previews_for(
        session, project, [items[file.item_key] for file in files if file.status == STATUS_READY]
    )
    files = [replace(file, preview=previews.get(file.item_key)) for file in files]
    return FilesState(files=files, preparing=any(f.status == STATUS_PREPARING for f in files))
