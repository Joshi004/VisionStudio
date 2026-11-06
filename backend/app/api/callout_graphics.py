"""`/api/projects/{project_id}/callout-graphics`: the graphics of the callouts of a motion
explainer, the generated component of each callout (CMO-003).

- `GET ...` answers everything the callout panel shows for the stage in one call: each callout of
  the newest plan with where its graphics stand, and for the component every attempt with its
  preview, jobs and checks. "Out of date" is worked out on every read.
- `POST .../run` makes what is missing for every callout that is turned on (the pipeline's own
  start function): a new model call for a callout that has nothing, the preview again for code
  with no preview, and a new attempt with the code it already has for a preview that is out of
  date (new words or new colours), which asks no model.
- `POST .../{callout_id}/run` does the same for one callout.
- `POST .../{callout_id}/{engine}/ask-again` makes a new attempt of one version, with a new model
  call.

The rows and the jobs are made by `app/services/callout_graphics.py`. The answers never return ORM
objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.graphics_lab import GraphicCallOut
from app.api.jobs import JobSummary, job_summary
from app.api.projects import load_project
from app.db.models import Job, Project
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import callout_graphics, callout_plan_writer, graphics_lab
from app.services.storage import media_url

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Not a motion callouts project, the callout plan or the callout look is "
        "missing, out of date or being written, no such callout, or the version is already "
        "being made.",
    }
}

EngineKey = Literal["generated_component"]
Status = Literal["none", "writing", "rendering", "ready", "out_of_date", "failed"]
CalloutStatus = Literal["none", "working", "ready", "out_of_date", "failed"]
UsedEngine = Literal["generated_component", "box"]
UsedBecause = Literal["chosen", "default", "component_failed"]


class CalloutGraphicAttemptOut(BaseModel):
    """One attempt of one version: what it draws from, the jobs, the preview and the checks."""

    id: int
    created_at: datetime
    # The attempts of one version of a callout are numbered from 1.
    attempt: int
    # The preview is drawn from what is current now (the words, the colours and the size).
    current: bool
    # `writing` or `rendering` while a job of the attempt is waiting or running.
    stage: Literal["writing", "rendering"] | None
    # The component code, and the model call that wrote it. None until then.
    input: Any | None
    input_job: JobSummary | None
    # The time, attempts and tokens of that call. None while it has none, and for an attempt made
    # for new words or colours, which asks no model.
    input_call: GraphicCallOut | None
    preview_job: JobSummary | None
    # The finished preview, from /media. None until the preview job has stored it.
    url: str | None
    metrics: Any | None
    warnings: Any | None
    # Why it has no preview, or None.
    last_error: str | None
    # A component that has no preview and that nothing more will be tried for.
    failed_outright: bool
    # The attempt whose code this one draws again for new words or colours, or None.
    rerender_of: int | None
    # The attempt of a component whose preview failed, which this one repairs, or None.
    repair_of: int | None


class CalloutGraphicEngineOut(BaseModel):
    key: EngineKey
    label: str
    status: Status
    # A component that failed outright (no current preview, nothing more will be tried).
    failed_outright: bool
    # Why the newest attempt has no preview, or None.
    last_error: str | None
    # Newest first.
    attempts: list[CalloutGraphicAttemptOut]


class CalloutGraphicUsedOut(BaseModel):
    """What the story render draws for a callout. `box` is today's text box, for a callout whose
    component failed outright.
    """

    engine: UsedEngine
    attempt_id: int | None
    attempt: int | None
    because: UsedBecause


class CalloutGraphicCalloutOut(BaseModel):
    id: str
    type: str
    enabled: bool
    scene_id: str
    unit_id: str
    phrase: str
    # What the callout shows, in order: its text, its items or its sides.
    texts: list[str]
    estimated_start_s: float
    status: CalloutStatus
    # One sentence for each thing the previews were drawn for that has changed.
    reasons: list[str]
    # What went wrong for each version that has nothing usable, or None.
    last_error: str | None
    can_run: bool
    blocked_reason: str | None
    # How long the callout is drawn at in the preview, in seconds. None when it cannot be worked
    # out now.
    length_s: float | None
    # The version the render draws, or None when the callout has nothing yet.
    used: CalloutGraphicUsedOut | None
    # Empty for a callout that is turned off.
    engines: list[CalloutGraphicEngineOut]


class CalloutGraphicsStateOut(BaseModel):
    callouts: list[CalloutGraphicCalloutOut]
    # Why nothing can be made for the project at all, or None.
    blocked_reason: str | None
    # False unless the project draws its callouts as motion graphics.
    wanted: bool
    # The callout look's version, and whether it is current.
    look_version: int | None
    look_current: bool


class CalloutGraphicsRun(BaseModel):
    # The jobs started. Empty when everything is made.
    job_ids: list[int]


class CalloutGraphicAskRun(BaseModel):
    job_id: int


# --- Mapping ---------------------------------------------------------------------------------


def _job_out(job: Job | None, project: Project) -> JobSummary | None:
    if job is None:
        return None
    return job_summary(JobRow(job=job, project_name=store.owner_name(job, project.name)))


def _attempt_out(
    entry: callout_graphics.AttemptEntry, project: Project
) -> CalloutGraphicAttemptOut:
    row = entry.row
    call = graphics_lab.input_call_of(entry.input_job)
    rerender = row.inputs.get("rerender_of") if isinstance(row.inputs, dict) else None
    return CalloutGraphicAttemptOut(
        id=row.id,
        created_at=row.created_at,
        attempt=row.attempt,
        current=entry.current,
        stage=cast(Literal["writing", "rendering"] | None, entry.stage),
        input=row.input,
        input_job=_job_out(entry.input_job, project),
        input_call=(
            GraphicCallOut(
                seconds=call.seconds,
                attempts=call.attempts,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                reasoning_tokens=call.reasoning_tokens,
            )
            if call is not None
            else None
        ),
        preview_job=_job_out(entry.preview_job, project),
        url=media_url(row.preview_path) if row.preview_path is not None else None,
        metrics=row.metrics,
        warnings=row.warnings,
        last_error=entry.error,
        failed_outright=row.failed_outright,
        rerender_of=rerender if isinstance(rerender, int) else None,
        repair_of=row.repair_of,
    )


def _engine_out(entry: callout_graphics.EngineEntry, project: Project) -> CalloutGraphicEngineOut:
    return CalloutGraphicEngineOut(
        key=cast(EngineKey, entry.key),
        label=entry.label,
        status=cast(Status, entry.status),
        failed_outright=entry.failed_outright,
        last_error=entry.last_error,
        attempts=[_attempt_out(attempt, project) for attempt in entry.attempts],
    )


def _texts(callout: dict[str, Any]) -> list[str]:
    if callout["type"] == callout_plan_writer.TYPE_COMPARISON:
        return [side["text"] for side in callout["sides"]]
    if callout["type"] == callout_plan_writer.TYPE_LIST:
        return [item["text"] for item in callout["items"]]
    return [callout["text"]]


def _callout_out(
    entry: callout_graphics.CalloutEntry, project: Project
) -> CalloutGraphicCalloutOut:
    callout = entry.callout
    used = entry.used
    length_s = (
        round(entry.resolved["frames"] / entry.resolved["fps"], 1)
        if entry.resolved is not None
        else None
    )
    return CalloutGraphicCalloutOut(
        id=callout["id"],
        type=callout["type"],
        enabled=entry.enabled,
        scene_id=callout["scene_id"],
        unit_id=callout["unit_id"],
        phrase=callout["phrase"],
        texts=_texts(callout),
        estimated_start_s=float(callout.get("estimated_start_s") or 0.0),
        status=cast(CalloutStatus, entry.status),
        reasons=entry.reasons,
        last_error=entry.last_error,
        can_run=entry.can_run,
        blocked_reason=entry.blocked_reason,
        length_s=length_s,
        used=(
            CalloutGraphicUsedOut(
                engine=cast(UsedEngine, used.engine),
                attempt_id=used.attempt.row.id if used.attempt is not None else None,
                attempt=used.attempt.row.attempt if used.attempt is not None else None,
                because=cast(UsedBecause, used.because),
            )
            if used is not None
            else None
        ),
        engines=[_engine_out(engine, project) for engine in entry.engines],
    )


async def _state(session: AsyncSession, project: Project) -> CalloutGraphicsStateOut:
    state = await callout_graphics.state(session, project)
    return CalloutGraphicsStateOut(
        callouts=[_callout_out(entry, project) for entry in state.entries],
        blocked_reason=state.blocked_reason,
        wanted=state.wanted,
        look_version=state.look_version,
        look_current=state.look_current,
    )


# --- Endpoints -------------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/callout-graphics",
    response_model=CalloutGraphicsStateOut,
    responses=_NOT_FOUND,
)
async def get_callout_graphics(project_id: int, session: SessionDep) -> CalloutGraphicsStateOut:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/callout-graphics/run",
    response_model=CalloutGraphicsRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_callout_graphics(project_id: int, session: SessionDep) -> CalloutGraphicsRun:
    """Makes what is missing for every callout that is turned on. A callout that has a current
    preview, or whose component failed outright, is left alone. Refused with 422 when nothing can
    be made for the project now.
    """
    project = await load_project(session, project_id)
    try:
        jobs = await callout_graphics.start_all(session, project)
    except callout_graphics.CalloutGraphicsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return CalloutGraphicsRun(job_ids=[job.id for job in jobs])


@router.post(
    "/projects/{project_id}/callout-graphics/{callout_id}/run",
    response_model=CalloutGraphicsRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_callout_graphic(
    project_id: int, callout_id: DiscoveryId, session: SessionDep
) -> CalloutGraphicsRun:
    """Makes what is missing for one callout. A callout whose graphics are being made is refused
    with 422.
    """
    project = await load_project(session, project_id)
    try:
        jobs = await callout_graphics.start_callout(session, project, callout_id)
    except callout_graphics.CalloutGraphicsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return CalloutGraphicsRun(job_ids=[job.id for job in jobs])


@router.post(
    "/projects/{project_id}/callout-graphics/{callout_id}/{engine}/ask-again",
    response_model=CalloutGraphicAskRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def ask_callout_graphic_again(
    project_id: int, callout_id: DiscoveryId, engine: EngineKey, session: SessionDep
) -> CalloutGraphicAskRun:
    """A paid model call: makes one version again as a new attempt."""
    project = await load_project(session, project_id)
    try:
        job = await callout_graphics.ask_again(session, project, callout_id, engine)
    except callout_graphics.CalloutGraphicsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return CalloutGraphicAskRun(job_id=job.id)
