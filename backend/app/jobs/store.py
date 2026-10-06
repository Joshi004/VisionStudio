"""Job helpers: every change to a `job` row goes through here (ANALYSIS.md Section 3.3, 4.2).

Rules that hold throughout:

- Each helper changes a row with a conditional UPDATE that names the status the row must
  be in. If something else changed the row first (a Cancel, for example), the UPDATE
  matches nothing and the helper returns False instead of overwriting that change.
- Each helper commits, except `finish_job`: its caller commits it together with the result
  rows, so a job is never "succeeded" without its result.
- To change a JSON column, a new object is assigned (Phase 1 decision).
- No transaction is held across a network call. Callers read, commit, call out, then write.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, Scene
from app.db.types import UTCDateTime, utcnow
from app.jobs import phases

_logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "running")
ERROR_MAX_CHARS = 4000

# Job types that can be cancelled while they run, because the server has a cancel for them
# (Phase 9). A transcription cannot yet: its cancel is not built.
REMOTE_CANCEL_TYPES = frozenset({"generate_clip"})

# One backend process, so a module lock is enough to make "create, unless one is active" atomic.
_create_lock = asyncio.Lock()


class JobActionError(Exception):
    """An action on a job that is refused. The message is meant to be shown to the user."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class JobRow:
    """A job with the names the Activity page shows next to it."""

    job: Job
    project_name: str
    scene_index: int | None


def can_cancel(job: Job) -> bool:
    """A job that has not started, one the server no longer knows, or (for the types that
    have a cancel on the server) a running one that is not yet fetching its result.
    """
    if job.status == "queued" or is_not_found(job):
        return True
    return (
        job.status == "running"
        and job.type in REMOTE_CANCEL_TYPES
        and job.phase not in phases.FINISHING_PHASES
    )


def needs_remote_cancel(job: Job) -> bool:
    """Is there a job on the server to cancel? Only a running job that has been submitted,
    and that the server still knows.
    """
    return job.status == "running" and job.provider_job_id is not None and not is_not_found(job)


def can_resubmit(job: Job) -> bool:
    return is_not_found(job)


def is_not_found(job: Job) -> bool:
    return job.status == "running" and job.phase == phases.NOT_FOUND


async def _update(
    session: AsyncSession, job_id: int, expected: tuple[str, ...], **values: Any
) -> bool:
    """UPDATE the row only while it is in one of the `expected` statuses. No commit."""
    statement = (
        update(Job)
        .where(Job.id == job_id, Job.status.in_(expected))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult[Any], await session.execute(statement))
    return result.rowcount == 1


async def create_job(
    session: AsyncSession,
    *,
    project_id: int,
    type: str,
    provider: str,
    input: dict[str, Any],
    scene_id: int | None = None,
    commit: bool = True,
) -> tuple[Job, bool]:
    """Creates a queued job, unless one of this type is already active for the project
    (or for the scene). Returns `(job, created)`: the existing job when it was not created.

    This is what makes two quick clicks on one button create one job (Section 3.3).

    With `commit=False` the job is only flushed, so a caller can create several jobs in one
    transaction (Generate all) and commit them together. It must hold the database's write
    lock already (see `scenes_service.lock_scenes`), so nobody else can create a job
    between the check and the commit.
    """
    async with _create_lock:
        statement = (
            select(Job)
            .where(
                Job.project_id == project_id,
                Job.type == type,
                Job.status.in_(ACTIVE_STATUSES),
                Job.scene_id.is_(None) if scene_id is None else Job.scene_id == scene_id,
            )
            .order_by(Job.id)
            .limit(1)
            .execution_options(populate_existing=True)
        )
        existing = (await session.execute(statement)).scalars().first()
        if existing is not None:
            if commit:
                await session.commit()
            return existing, False

        job = Job(
            project_id=project_id,
            scene_id=scene_id,
            type=type,
            status="queued",
            phase=phases.WAITING_TO_START,
            provider=provider,
            input=input,
            attempt=1,
        )
        session.add(job)
        if commit:
            await session.commit()
        else:
            await session.flush()
    _logger.info("job %d created: type=%s project=%d", job.id, type, project_id)
    return job, True


async def claim(session: AsyncSession, job_id: int) -> bool:
    """queued -> running. False when the job is no longer queued (it was cancelled)."""
    claimed = await _update(
        session,
        job_id,
        ("queued",),
        status="running",
        phase=phases.STARTING,
        started_at=func.coalesce(Job.started_at, literal(utcnow(), UTCDateTime())),
    )
    await session.commit()
    return claimed


async def set_phase(session: AsyncSession, job_id: int, phase: str, *, status: str) -> None:
    """Changes the phase of a job in `status`. Writes nothing when it is already that phase."""
    statement = (
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == status,
            or_(Job.phase.is_(None), Job.phase != phase),
        )
        .values(phase=phase)
        .execution_options(synchronize_session=False)
    )
    await session.execute(statement)
    await session.commit()


async def mark_submitted(
    session: AsyncSession, job_id: int, provider_job_id: str, input: dict[str, Any]
) -> bool:
    """Saves the server's job id and the exact request, right after the submit succeeded."""
    saved = await _update(
        session,
        job_id,
        ("running",),
        provider_job_id=provider_job_id,
        input=input,
        phase=phases.QUEUED_ON_CLUSTER,
        last_checked_at=utcnow(),
    )
    await session.commit()
    if saved:
        _logger.info("job %d submitted: provider_job_id=%s", job_id, provider_job_id)
    return saved


async def update_input(session: AsyncSession, job_id: int, input: dict[str, Any]) -> bool:
    """Replaces the `input` of a running job with the exact request, before it is sent."""
    saved = await _update(session, job_id, ("running",), input=input)
    await session.commit()
    return saved


async def record_output(session: AsyncSession, job_id: int, output: dict[str, Any]) -> bool:
    """Saves what a running job has so far (for a paid call: the answer, at once). The final
    `output` is written by `finish_job`, which replaces this.
    """
    saved = await _update(session, job_id, ("running",), output=output)
    await session.commit()
    return saved


async def record_poll(
    session: AsyncSession,
    job_id: int,
    phase: str,
    output: dict[str, Any] | None = None,
) -> None:
    """Notes that the server was asked about a running job, and what it said. `output`, when
    given, replaces the job's output (a clip job keeps the server's progress there).
    """
    values: dict[str, Any] = {"phase": phase, "last_checked_at": utcnow()}
    if output is not None:
        values["output"] = output
    await _update(session, job_id, ("running",), **values)
    await session.commit()


async def merge_output(session: AsyncSession, job_id: int, values: dict[str, Any]) -> None:
    """Adds keys to the output of a job that has finished (succeeded, failed or cancelled):
    what the cleanup or the cancel on the server answered. A new object is assigned.
    """
    job = await _load(session, job_id)
    if job is None or job.status in ACTIVE_STATUSES:
        await session.commit()
        return
    merged = {**(job.output if isinstance(job.output, dict) else {}), **values}
    await _update(session, job_id, ("succeeded", "failed", "cancelled"), output=merged)
    await session.commit()


async def requeue(
    session: AsyncSession, job_id: int, phase: str, *, next_attempt: bool = False
) -> bool:
    """running -> queued, forgetting the server's job id so the next start submits afresh."""
    values: dict[str, Any] = {"status": "queued", "phase": phase, "provider_job_id": None}
    if next_attempt:
        values["attempt"] = Job.attempt + 1
    requeued = await _update(session, job_id, ("running",), **values)
    await session.commit()
    if requeued:
        _logger.info("job %d queued again: %s", job_id, phase)
    return requeued


async def finish_job(
    session: AsyncSession,
    job_id: int,
    output: dict[str, Any],
    result_asset_id: int | None = None,
) -> bool:
    """running -> succeeded. Flushes but does not commit: the caller commits it together
    with the rows the job produced. False means the job was no longer running.
    """
    finished = await _update(
        session,
        job_id,
        ("running",),
        status="succeeded",
        phase=phases.DONE,
        output=output,
        result_asset_id=result_asset_id,
        error=None,
        finished_at=utcnow(),
    )
    await session.flush()
    return finished


async def fail_job(session: AsyncSession, job_id: int, error: str) -> bool:
    """queued or running -> failed, with the reason shown to the user."""
    failed = await _update(
        session,
        job_id,
        ACTIVE_STATUSES,
        status="failed",
        phase=phases.FAILED,
        error=error[:ERROR_MAX_CHARS],
        finished_at=utcnow(),
    )
    await session.commit()
    if failed:
        _logger.info("job %d failed: %s", job_id, error[:200].replace("\n", " "))
    return failed


async def _load(session: AsyncSession, job_id: int) -> Job | None:
    statement = select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
    return (await session.execute(statement)).scalars().first()


async def cancel_job(session: AsyncSession, job_id: int) -> Job:
    """Cancels a job that has not started, one the server no longer knows, or a running clip
    job (the caller cancels it on the server first, see `needs_remote_cancel`).

    Any other running job cannot be cancelled: a transcription is already on the GPU server
    (its cancel is not built), and a call to the language model cannot be taken back.
    """
    job = await _load(session, job_id)
    if job is None:
        raise JobActionError(404, f"Job {job_id} does not exist.")
    if not can_cancel(job):
        if job.status == "running" and job.phase in phases.FINISHING_PHASES:
            message = (
                "The clip has been made and is being downloaded and checked, so it can no "
                "longer be cancelled. Wait a moment and refresh."
            )
        elif job.status == "running" and job.provider == "gpu":
            message = "This job is already running on the GPU server and cannot be cancelled."
        elif job.status == "running":
            message = "This job is already running and cannot be cancelled."
        else:
            message = f"This job has already finished ({job.status})."
        raise JobActionError(409, message)

    cancelled = await _update(
        session,
        job_id,
        ("queued", "running"),
        status="cancelled",
        phase=phases.CANCELLED,
        finished_at=utcnow(),
    )
    await session.commit()
    job = await _load(session, job_id)
    if not cancelled or job is None or job.status != "cancelled":
        raise JobActionError(
            409, "The job changed while it was being cancelled. Refresh and try again."
        )
    _logger.info("job %d cancelled", job_id)
    return job


async def resubmit_job(session: AsyncSession, job_id: int) -> Job:
    """Queues a job the server does not know again, with the next attempt number."""
    job = await _load(session, job_id)
    if job is None:
        raise JobActionError(404, f"Job {job_id} does not exist.")
    if not can_resubmit(job):
        raise JobActionError(
            409, "Only a job that is not found on the server can be submitted again."
        )

    requeued = await _update(
        session,
        job_id,
        ("running",),
        status="queued",
        phase=phases.WAITING_TO_START,
        provider_job_id=None,
        attempt=Job.attempt + 1,
        error=None,
    )
    await session.commit()
    job = await _load(session, job_id)
    if not requeued or job is None:
        raise JobActionError(
            409, "The job changed while it was being resubmitted. Refresh and try again."
        )
    _logger.info("job %d resubmitted: attempt %d", job_id, job.attempt)
    return job


async def get_job(session: AsyncSession, job_id: int) -> Job | None:
    return await _load(session, job_id)


async def latest_job(session: AsyncSession, project_id: int, type: str) -> Job | None:
    """The newest job of a type for a project, whatever its status."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == type)
        .order_by(Job.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def latest_jobs_by_scene(session: AsyncSession, project_id: int, type: str) -> dict[int, Job]:
    """The newest job of a type for each scene of a project (ANALYSIS.md Section 3.4)."""
    newest = (
        select(func.max(Job.id))
        .where(Job.project_id == project_id, Job.type == type, Job.scene_id.is_not(None))
        .group_by(Job.scene_id)
    )
    statement = select(Job).where(Job.id.in_(newest)).execution_options(populate_existing=True)
    jobs = (await session.execute(statement)).scalars().all()
    return {job.scene_id: job for job in jobs if job.scene_id is not None}


async def waiting_job_count(session: AsyncSession) -> int:
    """GPU jobs that are waiting because the GPU API changed or is not approved (the banner)."""
    statement = select(func.count(Job.id)).where(
        Job.status == "queued",
        Job.provider == "gpu",
        Job.phase.like(f"{phases.PAUSED_PREFIX}%"),
    )
    return int((await session.execute(statement)).scalar_one())


def _rows_statement() -> Any:
    return (
        select(Job, Project.name, Scene.index)
        .join(Project, Project.id == Job.project_id)
        .outerjoin(Scene, Scene.id == Job.scene_id)
        .execution_options(populate_existing=True)
    )


async def list_jobs(session: AsyncSession, *, project_id: int | None, limit: int) -> list[JobRow]:
    """Jobs with their project and scene names, newest first."""
    statement = _rows_statement().order_by(Job.id.desc()).limit(limit)
    if project_id is not None:
        statement = statement.where(Job.project_id == project_id)
    result = await session.execute(statement)
    return [
        JobRow(job=job, project_name=name, scene_index=index) for job, name, index in result.all()
    ]


async def get_job_row(session: AsyncSession, job_id: int) -> JobRow | None:
    result = await session.execute(_rows_statement().where(Job.id == job_id))
    row = result.first()
    if row is None:
        return None
    job, name, index = row
    return JobRow(job=job, project_name=name, scene_index=index)
