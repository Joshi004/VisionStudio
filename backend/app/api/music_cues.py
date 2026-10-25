"""`/api/projects/{project_id}/music-cues`: the detail and prompts of the music cues (MUSIC-009).

- `GET ...` answers everything the story workspace shows for the stage in one call: the newest
  music plan's version, each cue with its plan line, its detail (exact anchors, the broad order of
  moods, hit requests, mix notes), the prompts it needs generated with their wordings and
  warnings, its objection to the plan, the newest job, and why it is out of date; and the audit
  of all prompts. "Out of date" is worked out on every read.
- `POST .../run` starts one `write_music_cue` job for every cue that has no current detail, or
  for the one cue named by `cue_id`.
- `POST .../audit` starts the `audit_music_cues` job over every cue's prompts.

Nothing here edits a cue by hand: the rows are made by the jobs (`app/services/music_cues.py`).
The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.music_plan import AnchorOut, CueOut
from app.api.projects import load_project
from app.db.models import Job, MusicCue, MusicCueAudit, Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import music_cues as music_cues_service

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Music is off, the plan or the shots are not ready, or nothing can be run.",
    }
}


class MusicCueJobOut(BaseModel):
    """A `write_music_cue` or `audit_music_cues` job, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class OrderStepOut(BaseModel):
    mood: str
    # Where this mood gives way to the next; null for the last step.
    until: AnchorOut | None


class HitRequestOut(BaseModel):
    id: str
    description: str
    at: AnchorOut


class MixOut(BaseModel):
    under_voice: str
    swell_in_gaps: bool
    notes: str | None


class DetailOut(BaseModel):
    """The cue's detail. A cue that spans time has `start`, `end`, the order of moods and its
    hits; a point sound has `at` and a `description`.
    """

    start: AnchorOut | None = None
    end: AnchorOut | None = None
    at: AnchorOut | None = None
    span_s: float | None = None
    fade_in_s: float | None = None
    fade_out_s: float | None = None
    internal_order: list[OrderStepOut] = Field(default_factory=list)
    hit_requests: list[HitRequestOut] = Field(default_factory=list)
    description: str | None = None
    mix: MixOut


class WordingAuditOut(BaseModel):
    problem: str


class WordingOut(BaseModel):
    # The fields sent to the music model's server, apart from the seed.
    fields: dict[str, Any]
    # What is wrong that does not stop the wording (an instrument the Bible says to avoid).
    warnings: list[str]
    # Set when the audit fixed this wording.
    audit: WordingAuditOut | None


class ProfileRef(BaseModel):
    id: str
    version: int


class ItemOut(BaseModel):
    """One thing that is generated: the cue itself, or a hit it asked for."""

    id: str
    role: str
    cue_id: str
    kind: str
    model: str
    profile: ProfileRef
    # `text` for every item: a theme is not converted (MD-6).
    source: str
    # What is known about the theme of a themed cue: its recording and what is fixed from it.
    theme: dict[str, Any] | None
    # The tempo, key and time signature a theme fixes, or null.
    fixed: dict[str, Any] | None
    span_s: float | None
    requested_s: float | None
    length_capped: bool
    description: str | None
    wordings: list[WordingOut]


class PushbackOut(BaseModel):
    problem: str
    suggestion: str
    # True when the plan is sent back for a revision; false when it could not be (the cue then
    # got its prompts anyway).
    sent: bool


class MusicCueVersionOut(BaseModel):
    id: int
    version: int
    # `ai`, or `audit` for a row the audit made by fixing wordings.
    source: str
    job_id: int | None
    created_at: datetime
    detail: DetailOut
    # Empty while the cue waits for the plan to be revised.
    items: list[ItemOut]
    pushback: PushbackOut | None


class MusicCueEntryOut(BaseModel):
    cue: CueOut
    # False for a silence and for a sound that H3 makes: there is nothing to write.
    makes_audio: bool
    row: MusicCueVersionOut | None
    job: MusicCueJobOut | None
    out_of_date: bool
    reasons: list[str]
    # Why the cue cannot be detailed now, or null.
    blocked_reason: str | None
    # Its current detail and prompts are saved, or it waits for the plan to be revised.
    done: bool
    active: bool
    waiting_for_revision: bool


class FixOut(BaseModel):
    item: str
    wording: int
    problem: str
    fields: dict[str, Any]
    warnings: list[str]


class AuditOut(BaseModel):
    id: int
    job_id: int | None
    created_at: datetime
    verdict: str
    fixes: list[FixOut]
    # The audit covers the newest rows of every cue.
    current: bool


class MusicCuesState(BaseModel):
    plan_version: int | None
    cues: list[MusicCueEntryOut]
    audit: AuditOut | None
    audit_job: MusicCueJobOut | None
    audit_active: bool
    # Cues have objected and the plan can be sent back for a revision.
    revision_pending: bool
    revision_active: bool
    revisions_used: int
    revisions_allowed: int
    # Why no cue can be detailed yet, or null.
    blocked_reason: str | None
    music_enabled: bool
    # The settings the prompts are written with.
    wordings: int
    handles_s: int


class MusicCuesRun(BaseModel):
    job_ids: list[int]


class MusicCuesAuditRun(BaseModel):
    job_id: int


# --- Mapping rows to answers ---------------------------------------------------------------


def _job_out(job: Job | None) -> MusicCueJobOut | None:
    if job is None:
        return None
    return MusicCueJobOut(
        id=job.id, status=cast(JobStatus, job.status), phase=job.phase, error=job.error
    )


def _row_out(row: MusicCue) -> MusicCueVersionOut:
    return MusicCueVersionOut(
        id=row.id,
        version=row.version,
        source=row.source,
        job_id=row.job_id,
        created_at=row.created_at,
        detail=DetailOut.model_validate(row.detail),
        items=[ItemOut.model_validate(item) for item in row.items],
        pushback=PushbackOut.model_validate(row.pushback) if row.pushback else None,
    )


def _audit_out(row: MusicCueAudit, current: bool) -> AuditOut:
    return AuditOut(
        id=row.id,
        job_id=row.job_id,
        created_at=row.created_at,
        verdict=row.findings["verdict"],
        fixes=[FixOut.model_validate(fix) for fix in row.findings["fixes"]],
        current=current,
    )


async def _state(session: AsyncSession, project: Project) -> MusicCuesState:
    state = await music_cues_service.state(session, project)
    return MusicCuesState(
        plan_version=state.plan.version if state.plan is not None else None,
        cues=[
            MusicCueEntryOut(
                cue=CueOut.model_validate(view.cue),
                makes_audio=view.makes_audio,
                row=_row_out(view.row) if view.row is not None else None,
                job=_job_out(view.job),
                out_of_date=view.out_of_date,
                reasons=view.reasons,
                blocked_reason=view.blocked_reason,
                done=view.done,
                active=view.active,
                waiting_for_revision=view.waiting_for_revision,
            )
            for view in state.cues
        ],
        audit=_audit_out(state.audit, state.audit_current) if state.audit is not None else None,
        audit_job=_job_out(state.audit_job),
        audit_active=state.audit_active,
        revision_pending=state.revision_pending,
        revision_active=state.revision_active,
        revisions_used=state.revisions_used,
        revisions_allowed=state.revisions_allowed,
        blocked_reason=state.blocked_reason,
        music_enabled=state.music_enabled,
        wordings=state.wordings,
        handles_s=state.handles_s,
    )


# --- Endpoints -----------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/music-cues",
    response_model=MusicCuesState,
    responses=_NOT_FOUND,
)
async def get_music_cues(project_id: int, session: SessionDep) -> MusicCuesState:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/music-cues/run",
    response_model=MusicCuesRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_music_cues(
    project_id: int,
    session: SessionDep,
    cue_id: Annotated[
        str | None,
        Query(max_length=200, description="Detail only this cue, even if it is up to date."),
    ] = None,
) -> MusicCuesRun:
    """Starts a job for every cue that has no current detail (or for the cue named by `cue_id`).
    A cue that already has a job waiting or running keeps it, and its id is returned.
    """
    project = await load_project(session, project_id)
    try:
        jobs = await music_cues_service.start_run(session, project, cue_id=cue_id)
    except music_cues_service.MusicCueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return MusicCuesRun(job_ids=[job.id for job in jobs])


@router.post(
    "/projects/{project_id}/music-cues/audit",
    response_model=MusicCuesAuditRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def audit_music_cues(project_id: int, session: SessionDep) -> MusicCuesAuditRun:
    """Starts the job that audits every cue's prompts together. If one is already waiting or
    running for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await music_cues_service.start_audit(session, project)
    except music_cues_service.MusicCueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return MusicCuesAuditRun(job_id=job.id)
