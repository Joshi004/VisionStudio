"""`/api/jobs`: every unit of background work (ANALYSIS.md Section 3.3, 4.2, 8).

The Activity page reads these. The answers never return ORM objects. Cancelling and
resubmitting are the only actions: starting work belongs to the resource that owns it
(for example `POST /api/projects/{id}/transcribe`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.db.models import Job
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobActionError, JobRow

router = APIRouter()

JobType = Literal["transcribe", "plan_scenes", "generate_clip", "render_final"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
JobProvider = Literal["gpu", "llm", "local"]

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_JOB_ID = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No job has this id."}}
_NOT_ALLOWED = {
    409: {"model": ErrorResponse, "description": "The job is not in a state that allows it."}
}


class JobSummary(BaseModel):
    id: int
    project_id: int
    project_name: str
    scene_id: int | None
    scene_index: int | None
    type: JobType
    status: JobStatus
    phase: str | None
    provider: JobProvider
    attempt: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_checked_at: datetime | None
    can_cancel: bool
    can_resubmit: bool


class JobDetail(JobSummary):
    provider_job_id: str | None
    # The exact request and the provider's answer, as stored (DATABASE_STRUCTURE.md Section 5).
    input: Any
    output: Any
    result_asset_id: int | None


def job_summary(row: JobRow) -> JobSummary:
    job = row.job
    return JobSummary(
        id=job.id,
        project_id=job.project_id,
        project_name=row.project_name,
        scene_id=job.scene_id,
        scene_index=row.scene_index,
        # The database CHECK constraints keep these to the allowed values.
        type=cast(JobType, job.type),
        status=cast(JobStatus, job.status),
        phase=job.phase,
        provider=cast(JobProvider, job.provider),
        attempt=job.attempt,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        last_checked_at=job.last_checked_at,
        can_cancel=store.can_cancel(job),
        can_resubmit=store.can_resubmit(job),
    )


def job_detail(row: JobRow) -> JobDetail:
    job: Job = row.job
    return JobDetail(
        **job_summary(row).model_dump(),
        provider_job_id=job.provider_job_id,
        input=job.input,
        output=job.output,
        result_asset_id=job.result_asset_id,
    )


async def _load_row(session: AsyncSession, job_id: int) -> JobRow:
    row = None
    if 1 <= job_id <= _MAX_JOB_ID:
        row = await store.get_job_row(session, job_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id} does not exist.")
    return row


@router.get("/jobs", response_model=list[JobSummary])
async def list_jobs(
    session: SessionDep,
    project_id: Annotated[int | None, Query(ge=1, le=_MAX_JOB_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[JobSummary]:
    """Jobs, newest first: all of them, or those of one project."""
    rows = await store.list_jobs(session, project_id=project_id, limit=limit)
    return [job_summary(row) for row in rows]


@router.get("/jobs/{job_id}", response_model=JobDetail, responses=_NOT_FOUND)
async def get_job(job_id: int, session: SessionDep) -> JobDetail:
    return job_detail(await _load_row(session, job_id))


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobDetail,
    responses={**_NOT_FOUND, **_NOT_ALLOWED},
)
async def cancel_job(job_id: int, session: SessionDep) -> JobDetail:
    """Cancels a job that has not started, or one the GPU server no longer knows."""
    await _load_row(session, job_id)
    try:
        await store.cancel_job(session, job_id)
    except JobActionError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    dispatcher.nudge()
    return job_detail(await _load_row(session, job_id))


@router.post(
    "/jobs/{job_id}/resubmit",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_NOT_ALLOWED},
)
async def resubmit_job(job_id: int, session: SessionDep) -> JobDetail:
    """Queues a job the GPU server does not know again, as a new attempt."""
    await _load_row(session, job_id)
    try:
        await store.resubmit_job(session, job_id)
    except JobActionError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    dispatcher.nudge()
    return job_detail(await _load_row(session, job_id))
