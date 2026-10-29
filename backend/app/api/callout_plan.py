"""`/api/projects/{project_id}/callout-plan`: the callout plan stage of an explainer
(EXPLAINER-009).

- `POST .../run` starts the `write_callout_plan` job: one model call writes the accent colour and
  the callouts, and code checks them for display rules. When the newest version was written by
  the owner, the body must confirm the replacement.
- `PUT ...` saves the owner's edit as the next version (`source` is `manual`): the text, type and
  role of each callout, and whether it is turned on. Callouts cannot be added or removed. The
  edit is checked by the same display rules, against the script as it is now.
- `GET ...` answers everything the board panel shows for the stage in one call: the newest
  version, the list of versions, the newest job, why the newest version is out of date, the
  display limits and the script lines the callouts sit on. "Out of date" is worked out on every
  read.
- `GET .../versions/{version}` answers one older (or the newest) version.

The rows and the job are made by `app/services/callout_plan.py`. The answers never return ORM
objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import CalloutPlan, Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import callout_plan as callout_plan_service

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or version."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Not an explainer with callouts on, the speech is not ready, or the "
        "callouts break a display rule.",
    }
}

Source = Literal["ai", "manual"]
CalloutType = Literal["emphasis", "number", "question", "comparison", "list", "section_title"]
Role = Literal["accent", "number", "negative", "positive"]


# --- What the plan holds ---------------------------------------------------------------------


class CalloutItemOut(BaseModel):
    text: str
    phrase: str


class CalloutSideOut(BaseModel):
    text: str
    phrase: str
    role: Role


class CalloutOut(BaseModel):
    id: str
    type: CalloutType
    # None for a comparison: each of its sides has a role.
    role: Role | None
    enabled: bool
    scene_id: str
    unit_id: str
    phrase: str
    # The text of every type but a list and a comparison.
    text: str | None
    items: list[CalloutItemOut] | None
    sides: list[CalloutSideOut] | None
    # Where the callout is on the estimated timeline, in seconds from the start of the video.
    estimated_start_s: float
    # Things to look at that do not stop the plan (a number the script does not say, a phrase
    # that was not found).
    warnings: list[str]


class CalloutAccentOut(BaseModel):
    colour: str
    reason: str
    # Why the default colour was used instead of the model's, or None.
    note: str | None


class CalloutPlanContent(BaseModel):
    accent: CalloutAccentOut
    callouts: list[CalloutOut]


class CalloutPlanVersionOut(BaseModel):
    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class CalloutPlanOut(CalloutPlanVersionOut):
    id: int
    content: CalloutPlanContent


class CalloutPlanJobOut(BaseModel):
    """The newest `write_callout_plan` job of the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class CalloutScriptLineOut(BaseModel):
    scene_id: str
    scene_title: str
    unit_id: str
    text: str
    # Seconds from the start of the video, estimated from the length of each line.
    start_s: float


class CalloutRulesOut(BaseModel):
    min_gap_ms: int
    per_minute_max: int


class CalloutPlanState(BaseModel):
    latest: CalloutPlanOut | None
    versions: list[CalloutPlanVersionOut]
    job: CalloutPlanJobOut | None
    # Only the newest version is judged. False when there is no version.
    out_of_date: bool
    # One sentence for each thing the newest version was built from that has changed.
    reasons: list[str]
    # True when running the model again would add a version after one the owner wrote.
    needs_confirmation: bool
    # Why no callout plan can be written yet (or at all for this project), or None.
    blocked_reason: str | None
    # False for a story, and for an explainer with callouts off.
    wanted: bool
    rules: CalloutRulesOut
    # The script the callouts sit on. Empty while blocked.
    script: list[CalloutScriptLineOut]


class CalloutPlanRun(BaseModel):
    job_id: int


class CalloutPlanRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False


# --- What an edit sends ----------------------------------------------------------------------


class CalloutItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=300)
    # Left out for a new item: it then sits where its callout does.
    phrase: str | None = Field(default=None, max_length=500)


class CalloutSideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=300)
    phrase: str | None = Field(default=None, max_length=500)
    role: Role | None = None


class CalloutEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=50)
    type: CalloutType
    role: Role | None = None
    enabled: bool
    text: str | None = Field(default=None, max_length=300)
    items: list[CalloutItemIn] | None = Field(default=None, max_length=10)
    sides: list[CalloutSideIn] | None = Field(default=None, max_length=10)


class CalloutPlanSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Exactly the callouts of the newest version.
    callouts: list[CalloutEditIn] = Field(max_length=500)


# --- Mapping ---------------------------------------------------------------------------------


def _version_out(row: CalloutPlan) -> CalloutPlanVersionOut:
    return CalloutPlanVersionOut(
        version=row.version,
        source=cast(Source, row.source),
        job_id=row.job_id,
        created_at=row.created_at,
    )


def _plan_out(row: CalloutPlan) -> CalloutPlanOut:
    return CalloutPlanOut(
        **_version_out(row).model_dump(),
        id=row.id,
        content=CalloutPlanContent.model_validate(row.content),
    )


async def _state(session: AsyncSession, project: Project) -> CalloutPlanState:
    state = await callout_plan_service.state(session, project)
    job = state.job
    return CalloutPlanState(
        latest=_plan_out(state.latest) if state.latest is not None else None,
        versions=[_version_out(row) for row in state.versions],
        job=(
            CalloutPlanJobOut(
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
        needs_confirmation=state.needs_confirmation,
        blocked_reason=state.blocked_reason,
        wanted=state.wanted,
        rules=CalloutRulesOut(**state.rules.as_dict()),
        script=[
            CalloutScriptLineOut(
                scene_id=unit.scene_id,
                scene_title=unit.scene_title,
                unit_id=unit.unit_id,
                text=unit.text,
                start_s=round(unit.start_s, 1),
            )
            for unit in state.script
        ],
    )


# --- Endpoints -------------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/callout-plan/run",
    response_model=CalloutPlanRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_callout_plan(
    project_id: int, session: SessionDep, body: CalloutPlanRunIn | None = None
) -> CalloutPlanRun:
    """Starts the job that writes the callout plan. If one is already waiting or running for the
    project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await callout_plan_service.start_run(
            session,
            project,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except callout_plan_service.CalloutPlanError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return CalloutPlanRun(job_id=job.id)


@router.get(
    "/projects/{project_id}/callout-plan",
    response_model=CalloutPlanState,
    responses=_NOT_FOUND,
)
async def get_callout_plan(project_id: int, session: SessionDep) -> CalloutPlanState:
    return await _state(session, await load_project(session, project_id))


@router.put(
    "/projects/{project_id}/callout-plan",
    response_model=CalloutPlanState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_callout_plan(
    project_id: int, body: CalloutPlanSaveIn, session: SessionDep
) -> CalloutPlanState:
    """Saves the edited callouts as the next version, written by the owner."""
    project = await load_project(session, project_id)
    try:
        await callout_plan_service.save_manual(
            session, project, [edit.model_dump() for edit in body.callouts]
        )
    except callout_plan_service.CalloutPlanError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _state(session, project)


@router.get(
    "/projects/{project_id}/callout-plan/versions/{version}",
    response_model=CalloutPlanOut,
    responses=_NOT_FOUND,
)
async def get_callout_plan_version(
    project_id: int,
    version: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> CalloutPlanOut:
    project = await load_project(session, project_id)
    row = await callout_plan_service.get_version(session, project.id, version)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"The project has no callout plan version {version}."
        )
    return _plan_out(row)
