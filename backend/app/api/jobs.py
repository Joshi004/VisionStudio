"""`/api/jobs`: every unit of background work (ANALYSIS.md Section 3.3, 4.2, 8).

The Activity page reads these. The answers never return ORM objects. Cancelling and
resubmitting are the only actions: starting work belongs to the resource that owns it
(for example `POST /api/lab/images/runs`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.core import settings as settings_service
from app.db.models import Job
from app.db.session import SessionDep
from app.jobs import dispatcher, handlers, pools, store
from app.jobs.store import JobActionError, JobRow
from app.providers import video_generator
from app.providers.gpu_server import GpuCallError

GPU_URL_KEY = "gpu_api_base_url"

router = APIRouter()

JobType = Literal[
    "lab_video",
    "write_lab_video_prompt",
    "lab_voice",
    "lab_image",
    "write_character_look_prompt",
    "write_character_take_prompt",
    "write_story_bible",
    "discover_characters",
    "discover_environments",
    "discover_scenes",
    "define_character",
    "discover_relations",
]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
JobProvider = Literal["gpu", "llm", "image", "local"]

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_JOB_ID = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No job has this id."}}
_NOT_ALLOWED = {
    409: {"model": ErrorResponse, "description": "The job is not in a state that allows it."}
}


class JobSummary(BaseModel):
    id: int
    # None for a lab's jobs, which belong to no project (`project_name` then says so).
    project_id: int | None
    project_name: str
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


class PoolTypeCount(BaseModel):
    """What one kind of job is using in a pool right now."""

    type: JobType
    running: int
    queued: int


class PoolCapacity(BaseModel):
    """One of the two shared pools: how many jobs may run in it, and what is in it now."""

    pool: Literal["gpu", "paid_api"]
    label: str
    # The setting. Running jobs are never stopped when it is lowered, so `running` can be
    # above it for a while.
    limit: int
    # How many jobs are running, and how many of the `limit` slots they hold. They differ when a
    # MiniMax H3 run is going: it is one job but takes a slot for each GPU the server gave it.
    running: int
    slots_used: int
    queued: int
    # Only the kinds of job that have a job running or queued in the pool.
    by_type: list[PoolTypeCount]


class JobCapacity(BaseModel):
    pools: list[PoolCapacity]


# Registered before `/jobs/{job_id}`, which would take "capacity" for a job id.
@router.get("/jobs/capacity", response_model=JobCapacity)
async def get_capacity(session: SessionDep) -> JobCapacity:
    """The GPU server's and the paid inference API's shared slots: the limit, how many jobs
    are running and waiting for a slot in each, and which kinds of job they are.
    """
    limits = await pools.shared_limits(session)
    qwen38_keys = await pools.qwen38_model_keys(session)
    active = [(job, handlers.get_handler(job.type)) for job in await store.active_jobs(session)]

    by_type: dict[str, dict[str, PoolTypeCount]] = {pool: {} for pool in limits}
    for job, handler in sorted(active, key=lambda pair: pair[0].type):
        pool = job.type if handler is None else pools.job_pool(job, handler, qwen38_keys)
        if pool not in by_type:
            continue  # a local job is in no shared pool
        entry = by_type[pool].setdefault(
            job.type, PoolTypeCount(type=cast(JobType, job.type), running=0, queued=0)
        )
        if job.status == "running":
            entry.running += 1
        else:
            entry.queued += 1

    slots_used = pools.slots_in_use(
        [(job, handler) for job, handler in active if job.status == "running"], qwen38_keys
    )

    return JobCapacity(
        pools=[
            PoolCapacity(
                pool=cast(Literal["gpu", "paid_api"], pool),
                label=pools.POOL_LABELS[pool],
                limit=limit,
                running=sum(entry.running for entry in by_type[pool].values()),
                slots_used=slots_used[pool],
                queued=sum(entry.queued for entry in by_type[pool].values()),
                by_type=list(by_type[pool].values()),
            )
            for pool, limit in limits.items()
        ]
    )


@router.get("/jobs/{job_id}", response_model=JobDetail, responses=_NOT_FOUND)
async def get_job(job_id: int, session: SessionDep) -> JobDetail:
    return job_detail(await _load_row(session, job_id))


async def _cancel_on_server(base_url: str, provider_job_id: str) -> dict[str, Any]:
    """Asks the GPU server to stop a job. What it answers, whatever it says, is recorded.

    "Whatever it says" means an answer: the job is unknown (404), or the request was refused.
    No answer at all (no connection, a server error, a busy server) raises 503 and the job is
    left as it is, because cancelling here while the job keeps running there would waste a GPU.
    """
    try:
        return (await video_generator.cancel(base_url, provider_job_id)).to_json()
    except GpuCallError as exc:
        if exc.kind in ("not_found", "rejected", "bad_answer"):
            return {"cancelled": False, "error": str(exc)}
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The GPU server did not answer, so the job was not cancelled. Try again.",
        ) from exc


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobDetail,
    responses={
        **_NOT_FOUND,
        **_NOT_ALLOWED,
        503: {
            "model": ErrorResponse,
            "description": "The GPU server did not answer the cancel, so nothing changed.",
        },
    },
)
async def cancel_job(job_id: int, session: SessionDep) -> JobDetail:
    """Cancels a job that has not started, one the GPU server no longer knows, or a running
    image or video job (which is cancelled on the GPU server first).
    """
    job = (await _load_row(session, job_id)).job
    was_not_found = store.is_not_found(job)

    remote_answer: dict[str, Any] | None = None
    if store.can_cancel(job) and store.needs_remote_cancel(job):
        base_url = await settings_service.get_str(session, GPU_URL_KEY)
        provider_job_id = job.provider_job_id
        await session.commit()  # end the read before the call
        if provider_job_id is not None:
            remote_answer = await _cancel_on_server(base_url, provider_job_id)

    try:
        await store.cancel_job(session, job_id)
    except JobActionError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc

    # A job that was still uploading may have been submitted while it was being cancelled.
    # Its start notices (`mark_submitted` fails) and cancels it too; this covers the other order.
    after = (await _load_row(session, job_id)).job
    if (
        remote_answer is None
        and not was_not_found
        and after.provider_job_id is not None
        and after.type in store.REMOTE_CANCEL_TYPES
    ):
        base_url = await settings_service.get_str(session, GPU_URL_KEY)
        provider_job_id = after.provider_job_id
        await session.commit()
        try:
            remote_answer = (await video_generator.cancel(base_url, provider_job_id)).to_json()
        except GpuCallError as exc:
            remote_answer = {"cancelled": False, "error": str(exc)}

    if remote_answer is not None:
        await store.merge_output(session, job_id, {"cancel": remote_answer})
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
