"""Importing a footage research round's results (FTG-011,
`Footage_broll_implementation_phases.md` §4.8).

`start_import` queues the `import_footage` job. When it runs, `make_import` reads the newest
round's `results/` folder, checks every piece (`services/footage_checks.py`), copies the files of
the usable pieces into storage under generated names, and adds a `footage_import` row with one
`footage_item` row per piece. The job commits those rows when it finishes itself.

**The round folder is untrusted input (FT-6).** The same rules as for evidence:

- Only the mark ids of the round's stored brief are looked at, never the folder names on disk, and
  the files read are only the ones a `result.json` names with a plain name. A name with a slash
  is never plain, so the `scans/` folder (the tool's working files) is never read or copied.
- A file is opened without following links, must be a regular file, and is read with a size limit;
  the whole round is limited too.
- The round folder is never changed. Nothing is written into it.
- A piece that fails a check is stored with its reasons and **none of its files is copied**.
- The agent's file names are never stored as paths: a copied file gets a name `Storage` makes.

The generic file-safety code (the budget, the no-link read, the temp write, deleting files that
were copied for rows that were not kept) is the evidence import's, used as it is.

**Importing again** adds the next version with every item. A file whose SHA-256 is the same as one
an earlier import of this round stored is not copied again: its stored path is used (after the
stored file is checked to still have that hash). The owner's decisions name items by `item_key`,
which does not change while the files and the places in them do not.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import anyio.to_thread
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FootageImport, FootageItem, FootageRound, Job, Project
from app.jobs import store
from app.services import ffmpeg, footage_decisions, footage_marks, footage_rounds
from app.services.evidence_checks import MAX_RESULT_BYTES, PLAIN_NAME, FileProblem, FileRead
from app.services.evidence_import import (
    MAX_ROUND_BYTES,
    Budget,
    _read_regular,
    _write_new,
    discard_files,
)
from app.services.footage_checks import (
    DEFAULT_MAX_PIECES,
    MarkCheck,
    PieceCheck,
    check_mark,
    mark_unusable,
    named_files,
    no_result,
    slot_limit,
    stored_extension,
    video_media_problems,
)
from app.services.storage import StorageError, TempFile, get_storage

JOB_TYPE: Final = "import_footage"

_MAX_FOLDER_ENTRIES: Final = 1000
_MAX_PIECES_CEILING: Final = 9

NO_ROUND_MESSAGE: Final = "There is no research round yet. Write the brief first."
BRIEF_RUNNING_MESSAGE: Final = "A brief is being written. Import when it is done."
NO_RESULTS_MESSAGE: Final = (
    "No result has been written in the round's results folder yet. Run the research first."
)
ROUND_TOO_LARGE: Final = "was left out because the round's files are too large in all."

# The item columns (path, SHA-256) each stored slot fills.
_SLOT_COLUMNS: Final = {
    "video": ("video_path", "video_sha256"),
    "strip": ("strip_path", "strip_sha256"),
    "image": ("image_path", "image_sha256"),
    "text": ("text_path", "text_sha256"),
    "pdf": ("pdf_path", "pdf_sha256"),
}


class FootageImportError(ValueError):
    """An import that cannot be done. The message is meant to be shown to the user."""


# --- Reading the round folder (blocking) -------------------------------------------------------


@dataclass
class MarkRead:
    """What was read for one mark."""

    result: dict[str, Any] | None = None
    # No `result.json` (or no mark folder) at all.
    missing: bool = False
    # Why a `result.json` that exists cannot be used.
    problem: str | None = None
    # Something in the mark's folder that is never allowed (a link).
    folder_problem: str | None = None
    files: dict[str, FileRead] = field(default_factory=dict)


def round_dir(project_id: int, round_no: int) -> Path:
    """The round's folder, made from the numbers (never from a stored or an on-disk name).
    Raises FootageImportError when it is not an ordinary folder under `footage/`.
    """
    root = footage_rounds.footage_root().resolve()
    folder = root / str(int(project_id)) / f"r{int(round_no)}"
    if folder.is_symlink() or not folder.is_dir() or folder.resolve() != folder:
        raise FootageImportError(f"The round folder r{int(round_no)} is not in the files folder.")
    results = folder / "results"
    if results.is_symlink() or not results.is_dir():
        raise FootageImportError("The round's results folder is missing or is a link.")
    return folder


def valid_mark_id(mark_id: str) -> bool:
    return mark_id.startswith("f") and mark_id[1:].isdigit() and len(mark_id) <= 9


def read_mark(folder: Path, mark_id: str, max_pieces: int, budget: Budget) -> MarkRead:
    """Reads one mark's `result.json` and the files it names. Blocking: call it from a thread.
    `mark_id` comes from the stored brief and is checked to be a plain mark id. Only the top
    level of the mark's folder is listed (to find links); `scans/` is never entered.
    """
    if not valid_mark_id(mark_id):
        return MarkRead(problem="The mark id is not valid.")
    mark_folder = folder / "results" / mark_id
    if mark_folder.is_symlink():
        return MarkRead(problem=f"results/{mark_id} is a link.")
    if not mark_folder.exists():
        return MarkRead(missing=True)
    if not mark_folder.is_dir():
        return MarkRead(problem=f"results/{mark_id} is not a folder.")
    folder_problem = None
    try:
        for count, entry in enumerate(mark_folder.iterdir()):
            if count >= _MAX_FOLDER_ENTRIES:
                folder_problem = "The mark folder holds too many files."
                break
            if entry.is_symlink():
                folder_problem = (
                    f"{entry.name[:60]} is a link. Links are never allowed in a mark folder."
                )
                break
    except OSError:
        return MarkRead(problem=f"results/{mark_id} cannot be read.")

    raw = _read_regular(mark_folder / "result.json", MAX_RESULT_BYTES, budget)
    if isinstance(raw, FileProblem):
        if raw.reason == "is missing":
            return MarkRead(missing=True, folder_problem=folder_problem)
        return MarkRead(problem=f"result.json {raw.reason}.", folder_problem=folder_problem)
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return MarkRead(
            problem="result.json cannot be read as JSON.", folder_problem=folder_problem
        )
    if not isinstance(result, dict):
        return MarkRead(problem="result.json is not an object.", folder_problem=folder_problem)

    files: dict[str, FileRead] = {}
    for name in named_files(result, max_pieces):
        if PLAIN_NAME.match(name):
            files[name] = _read_regular(mark_folder / name, slot_limit(result, name), budget)
    return MarkRead(result=result, folder_problem=folder_problem, files=files)


def has_results(project_id: int, round_no: int, mark_ids: Sequence[str]) -> bool:
    """Whether any mark of the round has a `result.json`. Blocking."""
    try:
        folder = round_dir(project_id, round_no)
    except FootageImportError:
        return False
    for mark_id in mark_ids:
        if not valid_mark_id(mark_id):
            continue
        path = folder / "results" / mark_id / "result.json"
        if path.is_file() and not path.is_symlink():
            return True
    return False


# --- The media of a video (check 3) ------------------------------------------------------------


def _write_temp(data: bytes) -> Path:
    """Writes bytes to a new temp file and returns its path. Blocking."""
    storage = get_storage()
    path = storage.new_temp_path("mp4")
    _write_new(path, data)
    return path


async def _media_problem(data: bytes, capture: dict[str, Any], window_s: float) -> str | None:
    """Probes and decodes a video's bytes (through a temp file that is removed again) and says
    what is wrong with it, or None. ffprobe and ffmpeg read it as the render will."""
    temp_path = await anyio.to_thread.run_sync(_write_temp, data)
    try:
        container = await ffmpeg.probe(temp_path)
        video = await ffmpeg.probe_video(temp_path)
        problems = video_media_problems(container, video, capture, window_s)
        if problems:
            return " ".join(problems)
        decode = await ffmpeg.decode_problem(temp_path)
        if decode is not None:
            return f"The video does not play to the end: {decode}"
        return None
    finally:
        temp_path.unlink(missing_ok=True)


# --- Starting an import ------------------------------------------------------------------------


def import_refusal(current: footage_rounds.FootageRoundsState) -> str | None:
    """Why the newest round cannot be imported now, or None. Cheap: it does not look at the
    folder, so it can be read on every poll.
    """
    if not current.wanted:
        return footage_marks.OFF_MESSAGE
    row = current.round
    if row is None:
        return NO_ROUND_MESSAGE
    if not current.live:
        return f"The marks changed since round r{row.round_no}. Write a new round."
    if current.job is not None and current.job.status in ("queued", "running"):
        return BRIEF_RUNNING_MESSAGE
    return current.folder_problem


def brief_mark_ids(row: FootageRound) -> list[str]:
    marks = row.brief.get("marks") if isinstance(row.brief, dict) else None
    return [
        mark["id"]
        for mark in (marks if isinstance(marks, list) else [])
        if isinstance(mark, dict) and isinstance(mark.get("id"), str)
    ]


async def start_import(session: AsyncSession, project: Project) -> Job:
    """Queues the job that imports the newest round. If one is already waiting or running, that
    job is returned. Raises FootageImportError with the reason when nothing can be imported now.
    Commits.
    """
    current = await footage_rounds.state(session, project)
    reason = import_refusal(current)
    if reason is not None:
        raise FootageImportError(reason)
    row = current.round
    assert row is not None
    found = await anyio.to_thread.run_sync(
        has_results, project.id, row.round_no, brief_mark_ids(row)
    )
    if not found:
        raise FootageImportError(NO_RESULTS_MESSAGE)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input={"round_no": row.round_no, "round_id": f"r{row.round_no}"},
    )
    return job


async def latest_import(session: AsyncSession, round_id: int) -> FootageImport | None:
    """The round's newest import, or None."""
    statement = (
        select(FootageImport)
        .where(FootageImport.round_id == round_id)
        .order_by(FootageImport.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def items_of(session: AsyncSession, import_id: int) -> list[FootageItem]:
    statement = (
        select(FootageItem).where(FootageItem.import_id == import_id).order_by(FootageItem.id)
    )
    return list((await session.execute(statement)).scalars().all())


# --- Doing the import --------------------------------------------------------------------------


def _suffix_of(path: str) -> str:
    return Path(path).suffix.lstrip(".").lower()


async def _earlier_files(session: AsyncSession, round_id: int) -> dict[tuple[str, str], str]:
    """The stored files of this round's earlier imports, by (extension, SHA-256)."""
    columns = [column for pair in _SLOT_COLUMNS.values() for column in pair]
    statement = (
        select(*(getattr(FootageItem, name) for name in columns))
        .join(FootageImport, FootageImport.id == FootageItem.import_id)
        .where(FootageImport.round_id == round_id)
    )
    found: dict[tuple[str, str], str] = {}
    for row in (await session.execute(statement)).all():
        for path, sha in zip(row[0::2], row[1::2], strict=True):
            if path is not None and sha is not None:
                found[(_suffix_of(path), sha)] = path
    return found


def _write_temp_as(extension: str, data: bytes) -> Path:
    storage = get_storage()
    path = storage.new_temp_path(extension)
    _write_new(path, data)
    return path


async def _store_file(
    project_id: int,
    extension: str,
    data: bytes,
    sha256: str,
    reuse: dict[tuple[str, str], str],
    new_paths: list[str],
) -> str:
    """The stored path of a file: one an earlier import stored with the same hash (when it is
    still there and still has that hash), or a new copy under a generated name.
    """
    storage = get_storage()
    earlier = reuse.get((extension, sha256))
    if earlier is not None:
        try:
            _size, actual = await storage.hash_stored(earlier)
        except (StorageError, OSError):
            actual = None
        if actual == sha256:
            return earlier
    temp_path = await anyio.to_thread.run_sync(_write_temp_as, extension, data)
    try:
        stored = await storage.save(
            TempFile(path=temp_path, size_bytes=len(data), sha256=sha256), project_id, extension
        )
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    new_paths.append(stored.relative_path)
    reuse[(extension, sha256)] = stored.relative_path
    return stored.relative_path


def _max_pieces(brief: dict[str, Any]) -> int:
    rules = brief.get("rules")
    value = rules.get("max_pieces_per_mark") if isinstance(rules, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= _MAX_PIECES_CEILING:
        return value
    return DEFAULT_MAX_PIECES


def _orientation(brief: dict[str, Any]) -> str:
    project = brief.get("project")
    value = project.get("orientation") if isinstance(project, dict) else None
    return "portrait" if value == "portrait" else "landscape"


def _result_entry(check: MarkCheck) -> dict[str, Any]:
    return {
        "status": check.status,
        "summary": check.summary,
        "attempts": check.attempts,
        "problems": check.problems,
        "warnings": check.warnings,
    }


def _report(checks: dict[str, MarkCheck]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    items = usable = 0
    for check in checks.values():
        if check.status is not None:
            key = check.status
        else:
            key = "invalid" if check.invalid else "no_result"
        by_status[key] = by_status.get(key, 0) + 1
        items += len(check.pieces)
        usable += sum(1 for piece in check.pieces if piece.usable)
    return {"marks": len(checks), "by_status": by_status, "items": items, "usable_items": usable}


async def make_import(
    session: AsyncSession,
    project: Project,
    job_id: int,
    round_no: int,
    new_paths: list[str],
) -> FootageImport:
    """Imports the newest round: reads and checks its results, copies the files of the usable
    pieces, and adds the import and its items (flushed, not committed: the job commits them with
    finishing itself). Every stored file this adds is appended to `new_paths`, so that the caller
    can delete them if the rows are not kept. Raises FootageImportError when the round cannot be
    imported now, and StorageError or OSError when a file cannot be stored.
    """
    current = await footage_rounds.state(session, project)
    row = current.round
    if row is not None and row.round_no != round_no:
        raise FootageImportError(
            f"Round r{row.round_no} was written while this import waited. Import again."
        )
    reason = import_refusal(current)
    if reason is not None:
        raise FootageImportError(reason)
    assert row is not None
    brief = row.brief
    marks = [item for item in brief.get("marks", []) if isinstance(item, dict)]
    mark_ids = brief_mark_ids(row)
    folder = await anyio.to_thread.run_sync(round_dir, project.id, row.round_no)
    if not await anyio.to_thread.run_sync(has_results, project.id, row.round_no, mark_ids):
        raise FootageImportError(NO_RESULTS_MESSAGE)
    max_pieces = _max_pieces(brief)
    orientation = _orientation(brief)
    round_id = f"r{row.round_no}"
    project_id = project.id
    reuse = await _earlier_files(session, row.id)
    budget = Budget(MAX_ROUND_BYTES)

    checks: dict[str, MarkCheck] = {}
    stored: dict[str, list[tuple[PieceCheck, dict[str, tuple[str, str]]]]] = {}
    for mark in marks:
        mark_id = mark.get("id")
        if not isinstance(mark_id, str):
            continue
        read = await anyio.to_thread.run_sync(read_mark, folder, mark_id, max_pieces, budget)
        if read.result is None:
            check = no_result(read.problem, invalid=not read.missing)
        else:
            check = await anyio.to_thread.run_sync(
                functools.partial(
                    check_mark,
                    mark_id=mark_id,
                    round_id=round_id,
                    max_pieces=max_pieces,
                    orientation=orientation,
                    result=read.result,
                    files=read.files,
                    folder_problem=read.folder_problem,
                )
            )
        for piece in check.pieces:
            if (
                piece.usable
                and piece.kind == "video"
                and piece.capture is not None
                and piece.window_s is not None
            ):
                video_bytes = read.files[piece.files["video"][0]]
                assert isinstance(video_bytes, bytes)
                problem = await _media_problem(video_bytes, piece.capture, piece.window_s)
                if problem is not None:
                    mark_unusable(mark_id, piece, "media", problem)
        if check.pieces and not any(piece.usable for piece in check.pieces):
            sentence = "No piece for this mark passed the checks."
            if sentence not in check.warnings:
                check.warnings.append(sentence)
        checks[mark_id] = check
        copied: list[tuple[PieceCheck, dict[str, tuple[str, str]]]] = []
        for piece in check.pieces:
            paths: dict[str, tuple[str, str]] = {}
            if piece.usable:
                for slot, (name, sha256) in piece.files.items():
                    data = read.files[name]
                    assert isinstance(data, bytes)
                    path = await _store_file(
                        project_id, stored_extension(slot, data), data, sha256, reuse, new_paths
                    )
                    paths[slot] = (path, sha256)
            copied.append((piece, paths))
        stored[mark_id] = copied

    highest = (
        await session.execute(
            select(func.max(FootageImport.version)).where(FootageImport.round_id == row.id)
        )
    ).scalar_one_or_none()
    record = FootageImport(
        project_id=project_id,
        round_id=row.id,
        version=(highest or 0) + 1,
        job_id=job_id,
        results={mark_id: _result_entry(check) for mark_id, check in checks.items()},
        report=_report(checks),
    )
    session.add(record)
    await session.flush()
    for mark_id, pairs in stored.items():
        for piece, paths in pairs:
            session.add(_item_row(project_id, record.id, mark_id, piece, paths))
    await session.flush()
    # A new import of a reviewed round has to be reviewed again (FTG-012): the round reads
    # `imported` until the owner presses Review done. Stored with the import, in one transaction.
    await footage_decisions.set_round_reviewed(session, project, round_id, False, commit=False)
    return record


def _item_row(
    project_id: int,
    import_id: int,
    mark_id: str,
    piece: PieceCheck,
    paths: dict[str, tuple[str, str]],
) -> FootageItem:
    columns: dict[str, str | None] = {}
    for slot, (path_column, sha_column) in _SLOT_COLUMNS.items():
        columns[path_column] = paths[slot][0] if slot in paths else None
        columns[sha_column] = paths[slot][1] if slot in paths else None
    return FootageItem(
        project_id=project_id,
        import_id=import_id,
        mark_id=mark_id,
        piece_id=piece.piece_id,
        item_key=piece.item_key,
        origin="agent",
        kind=piece.kind,
        tier=piece.tier,
        source=piece.source,
        what_it_shows=piece.what_it_shows,
        same_event=piece.same_event,
        event_date=piece.event_date,
        on_screen_text=piece.on_screen_text,
        agent_notes=piece.agent_notes,
        capture=piece.capture,
        cuts=piece.cuts,
        usable=piece.usable,
        checks=piece.checks,
        warnings=piece.warnings,
        **columns,
    )


__all__ = [
    "JOB_TYPE",
    "FootageImportError",
    "discard_files",
    "import_refusal",
    "items_of",
    "latest_import",
    "make_import",
    "start_import",
]
