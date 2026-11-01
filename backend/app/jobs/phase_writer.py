"""The phase a running job shows, written in batches.

Every job writes a phase ("asking the model", "uploading the clip", ...) as it goes, and each
write used to open a database session of its own. With hundreds of jobs running, those short
sessions all arrive together and use up the connection pool. A phase is only a label for the
Activity page, so it does not have to reach the database at once:

- `note` keeps the latest phase of a job in memory. Nothing is awaited on the database.
- Every `FLUSH_INTERVAL_S` seconds, all the phases noted since the last flush are written in
  one session and one commit.
- A phase that something depends on is written at once: those in `phases.FINISHING_PHASES`
  (the job can no longer be cancelled), and those that start with `phases.PAUSED_PREFIX`
  (the Activity page and the paused-jobs query look for them).

The write only touches a job that is still `running`, as `store.set_phase` does, so a late flush
never changes a job that finished, was cancelled or went back to the queue.

When something else writes a job's phase (`store.set_phase`, or any change that sets `phase`), the
phase noted before it is dropped: it is older, and must not overwrite the newer one. When a job's
task ends (`settle`), its last noted phase is written, so the row never shows less than the task
last said.

If the flush loop is not running (the dispatcher has not started), `note` writes at once.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from sqlalchemy import or_, update

from app.db.models import Job
from app.db.session import SessionLocal
from app.jobs import phases, store

FLUSH_INTERVAL_S: Final = 1.0

_logger = logging.getLogger(__name__)

# Job id -> the latest phase its task noted and that is not written yet.
_pending: dict[int, str] = {}
_flush_task: asyncio.Task[None] | None = None


def _is_urgent(phase: str) -> bool:
    return phase in phases.FINISHING_PHASES or phase.startswith(phases.PAUSED_PREFIX)


async def note(job_id: int, phase: str) -> None:
    """Records the phase a running job is in. Written within `FLUSH_INTERVAL_S` seconds, or at
    once when the phase is urgent or the flush loop is not running.
    """
    if _flush_task is None or _is_urgent(phase):
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")
        return
    _pending[job_id] = phase


def discard(job_id: int) -> None:
    """Drops the phase noted for a job and not written yet. Called when another write sets the
    job's phase: the noted one is older.
    """
    _pending.pop(job_id, None)


async def settle(job_id: int) -> None:
    """Writes the phase noted for a job whose task has ended, if there is one."""
    phase = _pending.pop(job_id, None)
    if phase is None:
        return
    try:
        await _write({job_id: phase})
    except Exception:
        _logger.exception("job %d: could not write its last phase", job_id)


async def _write(phases_by_job: dict[int, str]) -> None:
    """Sets the phases of the jobs that are still running, in one session and one commit."""
    async with SessionLocal() as session:
        for job_id, phase in phases_by_job.items():
            statement = (
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status == "running",
                    or_(Job.phase.is_(None), Job.phase != phase),
                )
                .values(phase=phase)
                .execution_options(synchronize_session=False)
            )
            await session.execute(statement)
        await session.commit()


async def flush() -> None:
    """Writes every phase noted so far. A failure puts them back, unless a newer one was noted."""
    if not _pending:
        return
    batch = dict(_pending)
    _pending.clear()
    try:
        await _write(batch)
    except Exception:
        _logger.exception("phase writer: could not write %d phases", len(batch))
        for job_id, phase in batch.items():
            _pending.setdefault(job_id, phase)


async def _run() -> None:
    while True:
        await asyncio.sleep(FLUSH_INTERVAL_S)
        await flush()


def start() -> None:
    """Starts the flush loop. Called with the dispatcher."""
    global _flush_task
    if _flush_task is None:
        _flush_task = asyncio.create_task(_run(), name="phase-writer")


async def stop() -> None:
    """Stops the loop and writes what is left."""
    global _flush_task
    task, _flush_task = _flush_task, None
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await flush()
