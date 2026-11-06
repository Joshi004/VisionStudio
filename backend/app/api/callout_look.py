"""`/api/projects/{project_id}/callout-look`: the callout look stage of a motion explainer
(CMO-002).

- `POST .../run` starts the `write_callout_look` job: one model call writes the panel, the
  corners, the entrance, the emphasis, the density and a note. The body may hold `feedback`, the
  owner's note on the newest look.
- `GET ...` answers everything the callout panel shows for the stage in one call: the newest
  version, the list of versions, the newest job and why the newest version is out of date.
  "Out of date" is worked out on every read.

The rows and the job are made by `app/services/callout_look.py`. The answers never return ORM
objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import CalloutLook, Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import callout_look as callout_look_service
from app.services import user_feedback

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Not a motion callouts project, the Story Bible or the graphics look is "
        "missing or out of date, or the note cannot be used.",
    }
}

Source = Literal["ai"]
Panel = Literal["none", "card", "glass", "underline", "ribbon"]
Corners = Literal["sharp", "soft", "round"]
Entrance = Literal["fade_up", "wipe", "pop", "draw"]
Density = Literal["airy", "balanced", "compact"]


# --- What the look holds ---------------------------------------------------------------------


class CalloutLookFieldsOut(BaseModel):
    panel: Panel
    corners: Corners
    entrance: Entrance
    emphasis: str
    density: Density
    notes: str


class CalloutLookContent(BaseModel):
    look: CalloutLookFieldsOut
    reason: str


class CalloutLookVersionOut(BaseModel):
    version: int
    source: Source
    job_id: int | None
    created_at: datetime
    # The owner's note this version was made with, or None.
    feedback: str | None


class CalloutLookOut(CalloutLookVersionOut):
    id: int
    content: CalloutLookContent


class CalloutLookJobOut(BaseModel):
    """The newest `write_callout_look` job of the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class CalloutLookState(BaseModel):
    latest: CalloutLookOut | None
    versions: list[CalloutLookVersionOut]
    job: CalloutLookJobOut | None
    # Only the newest version is judged. False when there is no version.
    out_of_date: bool
    # One sentence for each thing the newest version was built from that has changed.
    reasons: list[str]
    # Why no look can be written yet (or at all for this project), or None.
    blocked_reason: str | None
    # False unless the project is a continuous explainer with graphics and callouts on and the
    # callout style set to motion.
    wanted: bool


class CalloutLookRun(BaseModel):
    job_id: int


class CalloutLookRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The owner's note on the newest look. `user_feedback.clean` checks it again.
    feedback: str | None = Field(default=None, max_length=user_feedback.MAX_CHARS)


# --- Mapping ---------------------------------------------------------------------------------


def _version_out(row: CalloutLook) -> CalloutLookVersionOut:
    return CalloutLookVersionOut(
        version=row.version,
        source=cast(Source, row.source),
        job_id=row.job_id,
        created_at=row.created_at,
        feedback=user_feedback.text_of(row.inputs),
    )


def _look_out(row: CalloutLook) -> CalloutLookOut:
    return CalloutLookOut(
        **_version_out(row).model_dump(),
        id=row.id,
        content=CalloutLookContent.model_validate(row.content),
    )


async def _state(session: AsyncSession, project: Project) -> CalloutLookState:
    state = await callout_look_service.state(session, project)
    job = state.job
    return CalloutLookState(
        latest=_look_out(state.latest) if state.latest is not None else None,
        versions=[_version_out(row) for row in state.versions],
        job=(
            CalloutLookJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        out_of_date=state.out_of_date,
        reasons=state.reasons,
        blocked_reason=state.blocked_reason,
        wanted=state.wanted,
    )


# --- Endpoints -------------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/callout-look/run",
    response_model=CalloutLookRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_callout_look(
    project_id: int, session: SessionDep, body: CalloutLookRunIn | None = None
) -> CalloutLookRun:
    """Starts the job that writes the callout look. If one is already waiting or running for
    the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await callout_look_service.start_run(
            session, project, feedback=body.feedback if body is not None else None
        )
    except callout_look_service.CalloutLookError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return CalloutLookRun(job_id=job.id)


@router.get(
    "/projects/{project_id}/callout-look",
    response_model=CalloutLookState,
    responses=_NOT_FOUND,
)
async def get_callout_look(project_id: int, session: SessionDep) -> CalloutLookState:
    return await _state(session, await load_project(session, project_id))
