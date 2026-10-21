"""`/api/projects/{project_id}/shot-plans`: the Shot Planning stage (PHASE-020).

- `GET ...` answers everything the story workspace shows in one call: the newest list of
  scenes, and for each scene its status (`not_planned`, `planned`, `out_of_date`), why it is out
  of date, its newest shots with their provenance and total length, the newest job, and whether
  Plan may be pressed. Out of date is worked out on every read.
- `POST .../run` ("Plan all") starts one job per scene that is not planned and up to date
  already, can be planned and is not already being planned.
- `POST .../{scene_id}/run` starts the job for one scene.

A job stores a new version of the scene's shot plan (`services/shot_plans.py`); nothing is
written to the Character Lab. The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.discovery import DiscoveryJobOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import shot_planning_writer, shot_plans
from app.services.shot_plans import SceneEntry

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no saved story, up-to-date Story Bible or scene list, or the "
        "scene's definition, events, speech units or speech are not ready, or the scene is not "
        "in the newest list.",
    }
}

Source = Literal["ai", "manual"]
Status = Literal["not_planned", "planned", "out_of_date"]
ShotType = Literal["establishing", "action", "reaction", "dialogue", "insert", "transition"]


# --- The shots, as `Path_ahead.md` Section 25 gives them -------------------------------------


class ShotOut(BaseModel):
    """One shot skeleton. The events stay the source of truth: a shot only names them."""

    id: str
    scene_id: str
    source_event_ids: list[str]
    # The speech units heard during the shot. A narration unit may be listed in several
    # consecutive shots; a dialogue unit is in exactly one.
    speech_unit_ids: list[str]
    type: ShotType
    target_duration: float
    description: str


class ShotPlanContentOut(BaseModel):
    scene_id: str
    shots: list[ShotOut]


# --- The stage's state ----------------------------------------------------------------------


class ShotPlanVersionOut(BaseModel):
    """The provenance of the newest shot plan of a scene (D-3)."""

    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class ShotPlanEntryOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    description: str
    status: Status
    # Why a planned scene is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    shots: ShotPlanContentOut | None
    # The shots' target durations added up, to a tenth of a second.
    total_seconds: float | None
    version: ShotPlanVersionOut | None
    # The newest planning job of this scene, whatever its status.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None


class ShotPlansOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    # The planning target range a new plan is given (Settings, Shot duration), or None.
    target_min_seconds: int | None
    target_max_seconds: int | None
    entries: list[ShotPlanEntryOut]
    # Why nothing can be planned yet, or None.
    blocked_reason: str | None


class ShotPlanSkippedOut(BaseModel):
    scene_id: str
    title: str
    reason: str


class ShotPlansRunAllOut(BaseModel):
    job_ids: list[int]
    skipped: list[ShotPlanSkippedOut]


class ShotPlansRunOut(BaseModel):
    job_id: int


def _entry_out(entry: SceneEntry) -> ShotPlanEntryOut:
    row = entry.row
    job = entry.job
    content = entry.content
    return ShotPlanEntryOut(
        id=entry.item["id"],
        index=entry.item["index"],
        title=entry.item["title"],
        description=entry.item["description"],
        status=entry.status,
        reasons=entry.reasons,
        shots=ShotPlanContentOut.model_validate(content) if content is not None else None,
        total_seconds=(
            shot_planning_writer.total_seconds(content["shots"]) if content is not None else None
        ),
        version=(
            ShotPlanVersionOut(
                version=row.version,
                # The database CHECK constraint keeps `source` to the two allowed values.
                source=cast(Source, row.source),
                job_id=row.job_id,
                created_at=row.created_at,
            )
            if row is not None
            else None
        ),
        job=(
            DiscoveryJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        can_run=entry.can_run,
        blocked_reason=entry.blocked_reason,
    )


def _refused(exc: shot_plans.ShotPlansError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/shot-plans",
    response_model=ShotPlansOut,
    responses=_NOT_FOUND,
)
async def get_shot_plans(project_id: int, session: SessionDep) -> ShotPlansOut:
    project = await load_project(session, project_id)
    result = await shot_plans.state(session, project)
    return ShotPlansOut(
        scenes_version=result.scenes_version,
        target_min_seconds=result.target_min_seconds,
        target_max_seconds=result.target_max_seconds,
        entries=[_entry_out(entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/shot-plans/run",
    response_model=ShotPlansRunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> ShotPlansRunAllOut:
    """Starts a job for every scene that is not planned and up to date already, can be planned
    and is not already being planned. The others are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await shot_plans.start_all(session, project)
    except shot_plans.ShotPlansError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return ShotPlansRunAllOut(
        job_ids=started.job_ids,
        skipped=[
            ShotPlanSkippedOut(scene_id=item.scene_id, title=item.title, reason=item.reason)
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/shot-plans/{scene_id}/run",
    response_model=ShotPlansRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_one(project_id: int, scene_id: DiscoveryId, session: SessionDep) -> ShotPlansRunOut:
    """Starts the job that plans one scene's shots. If it already has a job waiting or
    running, that job's id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await shot_plans.start_run(session, project, scene_id)
    except shot_plans.ShotPlansError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return ShotPlansRunOut(job_id=job.id)
