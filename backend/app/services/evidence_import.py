"""Importing a research round's results (EVD-006,
`Evidence_layer_implementation_phases.md` §4.6).

`start_import` queues the `import_evidence` job. When it runs, `make_import` reads the newest
round's `results/` folder, checks every piece of evidence (`services/evidence_checks.py`), copies
the files of the usable pieces into storage under generated names, and adds an `evidence_import`
row with one `evidence_item` row per piece. The job commits those rows when it finishes itself.

**The round folder is untrusted input (EV-7).**

- Only the claim ids of the round's stored brief are looked at, never the folder names on disk,
  and the files read are only the ones a `result.json` names with a plain name.
- A file is opened without following links, must be a regular file, and is read with a size
  limit; the whole round is limited too.
- The round folder is never changed. Nothing is written into it.
- A piece that fails a check is stored with its reasons and **none of its files is copied**.
- The agent's file names are never stored as paths: a copied file gets a name `Storage` makes.

**Importing again** adds the next version with every item. A file whose SHA-256 is the same as one
an earlier import of this round stored is not copied again: its stored path is used (after the
stored file is checked to still have that hash). The owner's decisions name items by `item_key`,
which does not change while the quote, the rectangles and the files do not.
"""

from __future__ import annotations

import errno
import functools
import json
import logging
import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import anyio.to_thread
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvidenceImport, EvidenceItem, EvidenceRound, Job, Project
from app.jobs import store
from app.services import evidence_claims, evidence_rounds, ffmpeg, soundbite_clips
from app.services.evidence_checks import (
    DEFAULT_MAX_EVIDENCE,
    MAX_RESULT_BYTES,
    PLAIN_NAME,
    ClaimCheck,
    FileProblem,
    FileRead,
    PieceCheck,
    check_claim,
    mark_unusable,
    no_result,
    slots_for,
)
from app.services.storage import StorageError, TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "import_evidence"

# What one import reads from the round folder in all (every file counted).
MAX_ROUND_BYTES: Final = 1024 * 1024 * 1024
_MAX_FOLDER_ENTRIES: Final = 1000
# The extension a stored file gets, by slot.
_EXTENSIONS: Final = {
    "image": "png",
    "context": "png",
    "text": "txt",
    "pdf": "pdf",
    "video": "mp4",
    "captions": "json",
}
# The slots an earlier import stored, with the item columns that hold their path and hash.
_STORED_SLOTS: Final = ("image", "context", "text", "pdf", "video", "captions")

NO_ROUND_MESSAGE: Final = "There is no research round yet. Write the brief first."
BRIEF_RUNNING_MESSAGE: Final = "A brief is being written. Import when it is done."
NO_RESULTS_MESSAGE: Final = (
    "No result has been written in the round's results folder yet. Run the research first."
)
ROUND_TOO_LARGE: Final = "was left out because the round's files are too large in all."


class EvidenceImportError(ValueError):
    """An import that cannot be done. The message is meant to be shown to the user."""


# --- Reading the round folder (blocking) ------------------------------------------------------


@dataclass
class ClaimRead:
    """What was read for one claim."""

    result: dict[str, Any] | None = None
    # No `result.json` (or no claim folder) at all.
    missing: bool = False
    # Why a `result.json` that exists cannot be used.
    problem: str | None = None
    # Something in the claim's folder that is never allowed (a link).
    folder_problem: str | None = None
    files: dict[str, FileRead] = field(default_factory=dict)


class Budget:
    """The bytes an import may still read."""

    def __init__(self, limit: int = MAX_ROUND_BYTES) -> None:
        self.remaining = limit


def round_dir(project_id: int, round_no: int) -> Path:
    """The round's folder, made from the numbers (never from a stored or an on-disk name).
    Raises EvidenceImportError when it is not an ordinary folder under `evidence/`.
    """
    root = evidence_rounds.evidence_root().resolve()
    folder = root / str(int(project_id)) / f"r{int(round_no)}"
    if folder.is_symlink() or not folder.is_dir() or folder.resolve() != folder:
        raise EvidenceImportError(f"The round folder r{int(round_no)} is not in the files folder.")
    results = folder / "results"
    if results.is_symlink() or not results.is_dir():
        raise EvidenceImportError("The round's results folder is missing or is a link.")
    return folder


def _read_regular(path: Path, limit: int, budget: Budget) -> bytes | FileProblem:
    """Reads a file that is a regular file, is not a link, and is within `limit` bytes."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return FileProblem("is missing")
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.EMLINK):
            return FileProblem("is a link")
        return FileProblem("cannot be opened")
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            return FileProblem("is not a regular file")
        if info.st_size > limit:
            return FileProblem(f"is too large ({info.st_size} bytes, the limit is {limit})")
        if info.st_size > budget.remaining:
            return FileProblem(ROUND_TOO_LARGE)
        with os.fdopen(descriptor, "rb", closefd=False) as file:
            content = file.read(limit + 1)
    finally:
        os.close(descriptor)
    if len(content) > limit:
        return FileProblem(f"is too large (more than {limit} bytes)")
    budget.remaining -= len(content)
    return content


def _named_files(result: dict[str, Any], max_evidence: int) -> list[str]:
    """The plain names the first `max_evidence` pieces of a result name, once each."""
    evidence = result.get("evidence")
    names: list[str] = []
    if not isinstance(evidence, list):
        return names
    for item in evidence[:max_evidence]:
        capture = item.get("capture") if isinstance(item, dict) else None
        if not isinstance(capture, dict):
            continue
        for key, _slot, _kind, _limit in slots_for(item.get("kind")):
            name = capture.get(key)
            if isinstance(name, str) and PLAIN_NAME.match(name) and name not in names:
                names.append(name)
    return names


def _slot_limit(result: dict[str, Any], name: str) -> int:
    """The largest size a file may have, by the slot it is named for (the biggest of them when
    two slots name it; the check says that a file may not be used twice)."""
    limit = 0
    evidence = result.get("evidence")
    for item in evidence if isinstance(evidence, list) else []:
        capture = item.get("capture") if isinstance(item, dict) else None
        if isinstance(capture, dict):
            for key, _slot, _kind, slot_limit in slots_for(item.get("kind")):
                if capture.get(key) == name:
                    limit = max(limit, slot_limit)
    return limit


def read_claim(folder: Path, claim_id: str, max_evidence: int, budget: Budget) -> ClaimRead:
    """Reads one claim's `result.json` and the files it names. Blocking: call it from a thread.
    `claim_id` comes from the stored brief and is checked to be a plain claim id.
    """
    if not (claim_id.startswith("c") and claim_id[1:].isdigit()):
        return ClaimRead(problem="The claim id is not valid.")
    claim_folder = folder / "results" / claim_id
    if claim_folder.is_symlink():
        return ClaimRead(problem=f"results/{claim_id} is a link.")
    if not claim_folder.exists():
        return ClaimRead(missing=True)
    if not claim_folder.is_dir():
        return ClaimRead(problem=f"results/{claim_id} is not a folder.")
    folder_problem = None
    try:
        for count, entry in enumerate(claim_folder.iterdir()):
            if count >= _MAX_FOLDER_ENTRIES:
                folder_problem = "The claim folder holds too many files."
                break
            if entry.is_symlink():
                folder_problem = (
                    f"{entry.name[:60]} is a link. Links are never allowed in a claim folder."
                )
                break
    except OSError:
        return ClaimRead(problem=f"results/{claim_id} cannot be read.")

    raw = _read_regular(claim_folder / "result.json", MAX_RESULT_BYTES, budget)
    if isinstance(raw, FileProblem):
        if raw.reason == "is missing":
            return ClaimRead(missing=True, folder_problem=folder_problem)
        return ClaimRead(problem=f"result.json {raw.reason}.", folder_problem=folder_problem)
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return ClaimRead(
            problem="result.json cannot be read as JSON.", folder_problem=folder_problem
        )
    if not isinstance(result, dict):
        return ClaimRead(problem="result.json is not an object.", folder_problem=folder_problem)

    files: dict[str, FileRead] = {}
    for name in _named_files(result, max_evidence):
        files[name] = _read_regular(claim_folder / name, _slot_limit(result, name), budget)
    return ClaimRead(result=result, folder_problem=folder_problem, files=files)


def has_results(project_id: int, round_no: int, claim_ids: Sequence[str]) -> bool:
    """Whether any claim of the round has a `result.json`. Blocking."""
    try:
        folder = round_dir(project_id, round_no)
    except EvidenceImportError:
        return False
    for claim_id in claim_ids:
        if not (claim_id.startswith("c") and claim_id[1:].isdigit()):
            continue
        path = folder / "results" / claim_id / "result.json"
        if path.is_file() and not path.is_symlink():
            return True
    return False


# --- The media of a video (SB-006) -------------------------------------------------------------

# A video's real length may differ from its window by this much (the capture tool's limit).
VIDEO_DURATION_TOLERANCE_S: Final = 0.5
MAX_VIDEO_HEIGHT: Final = 1080


def media_problems(probe: ffmpeg.VideoProbe, capture: dict[str, Any]) -> list[str]:
    """Why a video is not what the capture tool makes and the render reads, as sentences. Pure.
    `capture` is the tidied capture of the piece (the window and the size the tool wrote)."""
    problems: list[str] = []
    if probe.codec_name != "h264":
        problems.append(f"The video codec is {probe.codec_name!r}, not h264.")
    if probe.audio is None:
        problems.append("The video has no sound.")
    window = capture["window"]
    expected = window["end_s"] - window["start_s"]
    if probe.duration_s is None or abs(probe.duration_s - expected) > VIDEO_DURATION_TOLERANCE_S:
        shown = "unknown" if probe.duration_s is None else f"{probe.duration_s:.2f} s"
        problems.append(
            f"The video lasts {shown}, but its window is {expected:.2f} s "
            f"(more than {VIDEO_DURATION_TOLERANCE_S} s apart)."
        )
    if probe.height is not None and probe.height > MAX_VIDEO_HEIGHT:
        problems.append(f"The video is {probe.height} px high, the limit is {MAX_VIDEO_HEIGHT}.")
    if [probe.width, probe.height] != capture["video_px"]:
        problems.append(
            f"The video is {probe.width}x{probe.height}, but video_px says {capture['video_px']}."
        )
    return problems


async def _media_problem(data: bytes, capture: dict[str, Any]) -> str | None:
    """Probes and decodes a video's bytes (through a temp file that is removed again) and says
    what is wrong with it, or None. ffprobe and ffmpeg read it as the render will."""
    storage = get_storage()
    temp_path = await anyio.to_thread.run_sync(storage.new_temp_path, "mp4")
    try:
        await anyio.to_thread.run_sync(_write_new, temp_path, data)
        probe = await ffmpeg.probe_video(temp_path)
        if probe is None:
            return "The video cannot be read (ffprobe found no picture in it)."
        problems = media_problems(probe, capture)
        if problems:
            return " ".join(problems)
        decode = await ffmpeg.decode_problem(temp_path)
        if decode is not None:
            return f"The video does not play to the end: {decode}"
        return None
    finally:
        temp_path.unlink(missing_ok=True)


# --- Starting an import ------------------------------------------------------------------------


def import_refusal(current: evidence_rounds.EvidenceState) -> str | None:
    """Why the newest round cannot be imported now, or None. Cheap: it does not look at the
    folder, so it can be read on every poll.
    """
    if not current.wanted:
        return evidence_claims.OFF_MESSAGE
    row = current.round
    if row is None:
        return NO_ROUND_MESSAGE
    if not current.live:
        return f"The claims changed since round r{row.round_no}. Write a new round."
    if current.job is not None and current.job.status in ("queued", "running"):
        return BRIEF_RUNNING_MESSAGE
    return current.folder_problem


def brief_claim_ids(row: EvidenceRound) -> list[str]:
    claims = row.brief.get("claims") if isinstance(row.brief, dict) else None
    return [
        claim["id"]
        for claim in (claims if isinstance(claims, list) else [])
        if isinstance(claim, dict) and isinstance(claim.get("id"), str)
    ]


async def start_import(session: AsyncSession, project: Project) -> Job:
    """Queues the job that imports the newest round. If one is already waiting or running, that
    job is returned. Raises EvidenceImportError with the reason when nothing can be imported
    now. Commits.
    """
    current = await evidence_rounds.state(session, project)
    reason = import_refusal(current)
    if reason is not None:
        raise EvidenceImportError(reason)
    row = current.round
    assert row is not None
    found = await anyio.to_thread.run_sync(
        has_results, project.id, row.round_no, brief_claim_ids(row)
    )
    if not found:
        raise EvidenceImportError(NO_RESULTS_MESSAGE)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input={"round_no": row.round_no, "round_id": f"r{row.round_no}"},
    )
    return job


async def latest_import(session: AsyncSession, round_id: int) -> EvidenceImport | None:
    """The round's newest import, or None."""
    statement = (
        select(EvidenceImport)
        .where(EvidenceImport.round_id == round_id)
        .order_by(EvidenceImport.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def items_of(session: AsyncSession, import_id: int) -> list[EvidenceItem]:
    statement = (
        select(EvidenceItem).where(EvidenceItem.import_id == import_id).order_by(EvidenceItem.id)
    )
    return list((await session.execute(statement)).scalars().all())


# --- Doing the import --------------------------------------------------------------------------


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as file:
        file.write(data)


async def _earlier_files(session: AsyncSession, round_id: int) -> dict[tuple[str, str], str]:
    """The stored files of this round's earlier imports, by (extension, SHA-256)."""
    statement = (
        select(
            EvidenceItem.image_path,
            EvidenceItem.image_sha256,
            EvidenceItem.context_path,
            EvidenceItem.context_sha256,
            EvidenceItem.text_path,
            EvidenceItem.text_sha256,
            EvidenceItem.pdf_path,
            EvidenceItem.pdf_sha256,
            EvidenceItem.video_path,
            EvidenceItem.video_sha256,
            EvidenceItem.captions_path,
            EvidenceItem.captions_sha256,
        )
        .join(EvidenceImport, EvidenceImport.id == EvidenceItem.import_id)
        .where(EvidenceImport.round_id == round_id)
    )
    found: dict[tuple[str, str], str] = {}
    for row in (await session.execute(statement)).all():
        for slot, path, sha in zip(_STORED_SLOTS, row[0::2], row[1::2], strict=True):
            if path is not None and sha is not None:
                found[(_EXTENSIONS[slot], sha)] = path
    return found


async def _store_file(
    project_id: int,
    slot: str,
    data: bytes,
    sha256: str,
    reuse: dict[tuple[str, str], str],
    new_paths: list[str],
) -> str:
    """The stored path of a file: one an earlier import stored with the same hash (when it is
    still there and still has that hash), or a new copy under a generated name.
    """
    storage = get_storage()
    extension = _EXTENSIONS[slot]
    earlier = reuse.get((extension, sha256))
    if earlier is not None:
        try:
            _size, actual = await storage.hash_stored(earlier)
        except (StorageError, OSError):
            actual = None
        if actual == sha256:
            return earlier
    temp_path = await anyio.to_thread.run_sync(storage.new_temp_path, extension)
    try:
        await anyio.to_thread.run_sync(_write_new, temp_path, data)
        stored = await storage.save(
            TempFile(path=temp_path, size_bytes=len(data), sha256=sha256), project_id, extension
        )
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    new_paths.append(stored.relative_path)
    reuse[(extension, sha256)] = stored.relative_path
    return stored.relative_path


def _max_evidence(brief: dict[str, Any]) -> int:
    rules = brief.get("rules")
    value = rules.get("max_evidence_per_claim") if isinstance(rules, dict) else None
    return value if isinstance(value, int) and 1 <= value <= 20 else DEFAULT_MAX_EVIDENCE


def _result_entry(check: ClaimCheck) -> dict[str, Any]:
    return {
        "status": check.status,
        "summary": check.summary,
        "attempts": check.attempts,
        "problems": check.problems,
        "warnings": check.warnings,
    }


def _report(checks: dict[str, ClaimCheck]) -> dict[str, Any]:
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
    return {"claims": len(checks), "by_status": by_status, "items": items, "usable_items": usable}


async def make_import(
    session: AsyncSession,
    project: Project,
    job_id: int,
    round_no: int,
    new_paths: list[str],
) -> EvidenceImport:
    """Imports the newest round: reads and checks its results, copies the files of the usable
    pieces, and adds the import and its items (flushed, not committed: the job commits them with
    finishing itself). Every stored file this adds is appended to `new_paths`, so that the caller
    can delete them if the rows are not kept. Raises EvidenceImportError when the round cannot
    be imported now, and StorageError or OSError when a file cannot be stored.
    """
    current = await evidence_rounds.state(session, project)
    row = current.round
    if row is not None and row.round_no != round_no:
        raise EvidenceImportError(
            f"Round r{row.round_no} was written while this import waited. Import again."
        )
    reason = import_refusal(current)
    if reason is not None:
        raise EvidenceImportError(reason)
    assert row is not None
    brief = row.brief
    claims = [item for item in brief.get("claims", []) if isinstance(item, dict)]
    claim_ids = brief_claim_ids(row)
    folder = await anyio.to_thread.run_sync(round_dir, project.id, row.round_no)
    if not await anyio.to_thread.run_sync(has_results, project.id, row.round_no, claim_ids):
        raise EvidenceImportError(NO_RESULTS_MESSAGE)
    max_evidence = _max_evidence(brief)
    round_id = f"r{row.round_no}"
    project_id = project.id
    reuse = await _earlier_files(session, row.id)
    budget = Budget()

    checks: dict[str, ClaimCheck] = {}
    stored: dict[str, list[tuple[PieceCheck, dict[str, tuple[str, str]]]]] = {}
    for claim in claims:
        claim_id = claim.get("id")
        if not isinstance(claim_id, str):
            continue
        read = await anyio.to_thread.run_sync(read_claim, folder, claim_id, max_evidence, budget)
        if read.result is None:
            check = no_result(read.problem, invalid=not read.missing)
        else:
            check = await anyio.to_thread.run_sync(
                functools.partial(
                    check_claim,
                    claim=claim,
                    round_id=round_id,
                    max_evidence=max_evidence,
                    result=read.result,
                    files=read.files,
                    folder_problem=read.folder_problem,
                )
            )
        for piece in check.pieces:
            if piece.usable and piece.kind == "video" and piece.capture is not None:
                video_bytes = read.files[piece.files["video"][0]]
                assert isinstance(video_bytes, bytes)
                problem = await _media_problem(video_bytes, piece.capture)
                if problem is not None:
                    mark_unusable(claim_id, piece, "media", problem)
        if check.pieces and not any(piece.usable for piece in check.pieces):
            sentence = "No piece of evidence for this claim passed the checks."
            if sentence not in check.warnings:
                check.warnings.append(sentence)
        checks[claim_id] = check
        copied: list[tuple[PieceCheck, dict[str, tuple[str, str]]]] = []
        for piece in check.pieces:
            paths: dict[str, tuple[str, str]] = {}
            if piece.usable:
                for slot, (name, sha256) in piece.files.items():
                    data = read.files[name]
                    assert isinstance(data, bytes)
                    path = await _store_file(project_id, slot, data, sha256, reuse, new_paths)
                    paths[slot] = (path, sha256)
            copied.append((piece, paths))
        stored[claim_id] = copied

    highest = (
        await session.execute(
            select(func.max(EvidenceImport.version)).where(EvidenceImport.round_id == row.id)
        )
    ).scalar_one_or_none()
    record = EvidenceImport(
        project_id=project_id,
        round_id=row.id,
        version=(highest or 0) + 1,
        job_id=job_id,
        results={claim_id: _result_entry(check) for claim_id, check in checks.items()},
        report=_report(checks),
    )
    session.add(record)
    await session.flush()
    soundbite_claims = {claim["id"] for claim in claims if claim.get("want") == "soundbite"}
    clips: list[EvidenceItem] = []
    for claim_id, pairs in stored.items():
        for piece, paths in pairs:
            row_item = _item_row(project_id, record.id, claim_id, piece, paths)
            session.add(row_item)
            if piece.usable and piece.kind == "video" and claim_id in soundbite_claims:
                clips.append(row_item)
    await session.flush()
    # The clips of sound bite claims get their words from the captions that came with them
    # (SB-006). A video kept as context for an ordinary claim is only imported.
    for clip in clips:
        await soundbite_clips.analyse_now(session, clip)
    return record


def _item_row(
    project_id: int,
    import_id: int,
    claim_id: str,
    piece: PieceCheck,
    paths: dict[str, tuple[str, str]],
) -> EvidenceItem:
    def path_of(slot: str) -> str | None:
        return paths[slot][0] if slot in paths else None

    def sha_of(slot: str) -> str | None:
        return paths[slot][1] if slot in paths else None

    return EvidenceItem(
        project_id=project_id,
        import_id=import_id,
        claim_id=claim_id,
        evidence_id=piece.evidence_id,
        item_key=piece.item_key,
        kind=piece.kind,
        relation=piece.relation,
        source_tier=piece.source_tier,
        source=piece.source,
        quote=piece.quote,
        what_it_says=piece.what_it_says,
        agent_notes=piece.agent_notes,
        capture=piece.capture,
        image_path=path_of("image"),
        image_sha256=sha_of("image"),
        context_path=path_of("context"),
        context_sha256=sha_of("context"),
        text_path=path_of("text"),
        text_sha256=sha_of("text"),
        pdf_path=path_of("pdf"),
        pdf_sha256=sha_of("pdf"),
        video_path=path_of("video"),
        video_sha256=sha_of("video"),
        captions_path=path_of("captions"),
        captions_sha256=sha_of("captions"),
        usable=piece.usable,
        checks=piece.checks,
        warnings=piece.warnings,
    )


async def discard_files(paths: Sequence[str]) -> None:
    """Deletes the files an import stored when its rows were not kept. Each one is a file this
    import made (never one it reused). A failure is logged and does not stop the rest.
    """
    storage = get_storage()
    for path in paths:
        try:
            await storage.delete_media(path)
        except (StorageError, OSError):
            _logger.warning("could not remove a file of an import that was not kept: %s", path)
