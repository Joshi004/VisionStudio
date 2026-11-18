"""Database snapshots in the files folder (STOR-004).

The live database stays in the Docker volume (S-2). Once a day, and whenever the owner asks, a
consistent copy of it is written to `db-snapshots/` in the files folder on the Mac, so a lost
volume does not lose the database.

How a snapshot is made: `VACUUM INTO` on a separate SQLite connection. It reads the database in
one transaction, so in WAL mode the app keeps writing meanwhile, and it writes a compact copy.
A plain file copy of a database in use is never made. The copy is written under a `.partial`
name, checked (`PRAGMA integrity_check`), then renamed into place, and only then are older
snapshots removed. So a snapshot that fails or is cut short never replaces a good one.

Only files whose names match `SNAPSHOT_NAME` or `PARTIAL_NAME`, inside `db-snapshots/`, are
ever deleted here.

Snapshots are off unless the files folder is separate from the volume and usable: a snapshot
inside the volume would not survive losing the volume.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from app.core.config import get_config
from app.services.storage import get_storage

SNAPSHOTS_FOLDER: Final = "db-snapshots"
# `app-2026-11-16_1530Z.db`: the time is UTC, so names sort in the order they were made.
_STAMP_FORMAT: Final = "%Y-%m-%d_%H%MZ"
SNAPSHOT_NAME: Final = re.compile(r"app-(\d{4}-\d{2}-\d{2}_\d{4}Z)\.db")
PARTIAL_NAME: Final = re.compile(r"app-\d{4}-\d{2}-\d{2}_\d{4}Z\.db\.partial")

CHECK_INTERVAL_S: Final = 3600
# The first check waits, so it does not compete with the work the app does right after a start.
FIRST_CHECK_DELAY_S: Final = 300
# A new snapshot is made when the newest is at least this old.
MAX_AGE: Final = timedelta(hours=24)
# The header warns when the newest is older than this, or there is none.
WARN_AFTER: Final = timedelta(days=3)
# How many snapshots stay. One is about 1.5 GB.
KEEP: Final = 1
# Free space that must remain after the new snapshot is written.
FREE_SPACE_MARGIN_BYTES: Final = 2 * 1024**3
BUSY_TIMEOUT_S: Final = 30

_logger = logging.getLogger(__name__)


class SnapshotError(Exception):
    """A snapshot that could not be made. The message is shown to the owner."""


class SnapshotsOff(Exception):
    """Snapshots are not available now. The message says why."""


class SnapshotRunning(Exception):
    """A snapshot is already being made."""


@dataclass(frozen=True)
class SnapshotInfo:
    name: str
    made_at: datetime
    size_bytes: int


@dataclass(frozen=True)
class SnapshotsStatus:
    enabled: bool
    problem: str | None
    running: bool
    last: SnapshotInfo | None
    last_error: str | None
    # Only when enabled: there is no snapshot, or the newest is older than `WARN_AFTER`.
    stale: bool


# What the loop and the API share. One event loop, so no lock is needed for these.
_running = False
_last_error: str | None = None
_loop_task: asyncio.Task[None] | None = None
_tasks: set[asyncio.Task[None]] = set()


def snapshots_dir() -> Path:
    return get_config().files_dir / SNAPSHOTS_FOLDER


# --- Reading (blocking: call from a thread) ----------------------------------------


def _problem() -> str | None:
    """A plain sentence saying why snapshots are off, or None when they can be made."""
    if not get_config().files_dir_is_separate:
        return (
            "Snapshots are off: the files folder is not set. Set VISIO_FILES_DIR in .env, "
            "because a snapshot inside the Docker volume would not survive losing the volume."
        )
    return get_storage().files_folder_problem()


def list_snapshots(folder: Path) -> list[SnapshotInfo]:
    """The snapshots in the folder, newest first. Anything else in it is ignored."""
    found: list[SnapshotInfo] = []
    if not folder.is_dir():
        return found
    for entry in folder.iterdir():
        match = SNAPSHOT_NAME.fullmatch(entry.name)
        if match is None or not entry.is_file() or entry.is_symlink():
            continue
        made_at = datetime.strptime(match.group(1), _STAMP_FORMAT).replace(tzinfo=UTC)
        found.append(SnapshotInfo(entry.name, made_at, entry.stat().st_size))
    return sorted(found, key=lambda info: info.made_at, reverse=True)


def _is_stale(last: SnapshotInfo | None, now: datetime) -> bool:
    return last is None or now - last.made_at > WARN_AFTER


def _is_due(last: SnapshotInfo | None, now: datetime) -> bool:
    return last is None or now - last.made_at >= MAX_AGE


def _read_status() -> SnapshotsStatus:
    problem = _problem()
    if problem is not None:
        return SnapshotsStatus(False, problem, _running, None, _last_error, False)
    last = next(iter(list_snapshots(snapshots_dir())), None)
    return SnapshotsStatus(
        enabled=True,
        problem=None,
        running=_running,
        last=last,
        last_error=_last_error,
        stale=_is_stale(last, datetime.now(UTC)),
    )


async def status() -> SnapshotsStatus:
    return await asyncio.to_thread(_read_status)


# --- Making a snapshot (blocking: call from a thread) ------------------------------


def _vacuum_into(db_path: Path, target: Path) -> None:
    # `isolation_level=None`: VACUUM cannot run inside a transaction.
    connection = sqlite3.connect(str(db_path), timeout=BUSY_TIMEOUT_S, isolation_level=None)
    try:
        connection.execute("VACUUM INTO ?", (str(target),))
    finally:
        connection.close()


def _check_copy(copy: Path) -> str:
    """Opens the copy on its own, runs SQLite's integrity check and returns its Alembic revision.
    `immutable=1` because nothing else touches the copy: no lock or `-shm` file is needed.
    """
    connection = sqlite3.connect(f"{copy.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        rows = connection.execute("PRAGMA integrity_check").fetchall()
        if rows != [("ok",)]:
            first = rows[0][0] if rows else "no answer"
            raise SnapshotError(f"The copy failed SQLite's integrity check: {first}")
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        if revision is None:
            raise SnapshotError("The copy has no Alembic revision, so it is not a Visio database.")
        return str(revision[0])
    finally:
        connection.close()


def _remove_partials(folder: Path) -> None:
    if not folder.is_dir():
        return
    for entry in folder.iterdir():
        if PARTIAL_NAME.fullmatch(entry.name) and entry.is_file() and not entry.is_symlink():
            entry.unlink(missing_ok=True)


def _prune(folder: Path, newest: str) -> None:
    """Keeps `newest` and, if KEEP allows, the next ones. Removes the rest."""
    others = [info for info in list_snapshots(folder) if info.name != newest]
    for info in others[max(KEEP - 1, 0) :]:
        (folder / info.name).unlink(missing_ok=True)


def make_snapshot() -> SnapshotInfo:
    """Writes, checks and keeps one new snapshot. Raises SnapshotError with a message for the
    owner when it cannot.
    """
    config = get_config()
    db_path = config.db_path
    if not db_path.is_file():
        raise SnapshotError(f"The database file {db_path} was not found.")

    folder = snapshots_dir()
    folder.mkdir(parents=True, exist_ok=True)

    wal = db_path.with_name(db_path.name + "-wal")
    needed = db_path.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
    needed += FREE_SPACE_MARGIN_BYTES
    free = shutil.disk_usage(folder).free
    if free < needed:
        raise SnapshotError(
            f"Not enough free space for a snapshot: {free // 1024**2} MB free, "
            f"{needed // 1024**2} MB needed."
        )

    name = f"app-{datetime.now(UTC).strftime(_STAMP_FORMAT)}.db"
    final = folder / name
    partial = folder / f"{name}.partial"
    partial.unlink(missing_ok=True)  # `VACUUM INTO` refuses an existing file
    try:
        _vacuum_into(db_path, partial)
        revision = _check_copy(partial)
        os.replace(partial, final)
    except sqlite3.Error as exc:
        raise SnapshotError(f"SQLite could not make the snapshot: {exc}") from exc
    except OSError as exc:
        raise SnapshotError(f"The snapshot could not be written: {exc.strerror or exc}") from exc
    finally:
        partial.unlink(missing_ok=True)

    _prune(folder, name)
    _logger.info("db snapshot: %s made, alembic revision %s", name, revision)
    return next(info for info in list_snapshots(folder) if info.name == name)


# --- Running it ----------------------------------------------------------------------


async def _run_claimed() -> None:
    """Makes a snapshot. The caller already set `_running`."""
    global _running, _last_error
    try:
        info = await asyncio.to_thread(make_snapshot)
        _last_error = None
        _logger.info("db snapshot: done, %d bytes", info.size_bytes)
    except asyncio.CancelledError:
        raise
    except SnapshotError as exc:
        _last_error = str(exc)
        _logger.error("db snapshot failed: %s", exc)
    except Exception:
        _last_error = "The snapshot failed unexpectedly. See the backend log."
        _logger.exception("db snapshot failed unexpectedly")
    finally:
        _running = False


def _claim_and_start() -> None:
    global _running
    if _running:
        raise SnapshotRunning("A snapshot is already being made.")
    _running = True
    task = asyncio.create_task(_run_claimed(), name="db-snapshot")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def request_snapshot() -> None:
    """Starts a snapshot in the background and returns at once. For the button."""
    problem = await asyncio.to_thread(_problem)
    if problem is not None:
        raise SnapshotsOff(problem)
    _claim_and_start()


async def _check_once() -> None:
    """One look: make a snapshot if there is none or the newest is a day old."""
    current = await status()
    if not current.enabled or current.running:
        return
    if _is_due(current.last, datetime.now(UTC)):
        try:
            _claim_and_start()
        except SnapshotRunning:
            pass


async def _loop() -> None:
    try:
        problem = await asyncio.to_thread(_problem)
        if problem is None and not _running:
            await asyncio.to_thread(_remove_partials, snapshots_dir())
    except Exception:
        _logger.exception("db snapshot: clean-up of leftovers failed")
    await asyncio.sleep(FIRST_CHECK_DELAY_S)
    while True:
        try:
            await _check_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("db snapshot: the daily check failed")
        await asyncio.sleep(CHECK_INTERVAL_S)


def start() -> None:
    """Starts the hourly check. Called at startup, after the dispatcher."""
    global _loop_task
    if _loop_task is None:
        _loop_task = asyncio.create_task(_loop(), name="db-snapshot-loop")


async def stop() -> None:
    """Stops the check and any snapshot being made. A snapshot cut short leaves only a
    `.partial` file, which the next start removes.
    """
    global _loop_task
    tasks = [task for task in (_loop_task, *_tasks) if task is not None]
    _loop_task = None
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
