"""`/api/projects/{project_id}/looks-and-states`: the look and environment-state resolution
(PHASE-016).

- `GET ...` answers everything the story workspace shows in one call: for each scene of the
  newest list, what its environment-state request and each character's look request resolved to
  (`default`, an existing named look or state, or a new one), the version's provenance, why it
  is out of date, the newest job, and whether Resolve may be pressed. Out of date is worked out
  on every read.
- `POST .../run` starts the one `resolve_looks_states` job of the project. If one is already
  waiting or running, its id is returned and no second job is made.

A job stores a new version of the resolution and creates the new named looks and environment
states in the library (`services/look_state_resolution.py`). The answers never return ORM
objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.discovery import DiscoveryJobOut
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import look_state_resolution
from app.services.look_state_resolution import ResolvedItem, SceneResolution

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no saved story, up-to-date Story Bible or list of scenes, or a "
        "scene is not defined yet or is out of date.",
    }
}

Source = Literal["ai", "manual"]
# `default`: the canonical look or reference. `reuse`: a named look or state that existed.
# `new`: created by the run that made this version.
How = Literal["default", "reuse", "new"]


class LookStateItemOut(BaseModel):
    """One request of a scene and what it resolved to. `id`, `name` and `description` are None
    for `default`.
    """

    # The discovered character's or environment's slug id, and its name.
    subject_id: str
    subject_name: str
    # What the scene asked for, in the model's own words.
    request: str
    how: How
    id: str | None
    name: str | None
    description: str | None


class LookStateSceneOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    # Whether the newest version covers this scene at all.
    resolved: bool
    # Whether the newest version was made from this scene's newest definition.
    current: bool
    environment: LookStateItemOut | None
    # One per character the scene named in its look requests. A character left out looks as
    # defined and has no entry.
    looks: list[LookStateItemOut]


class LookStateVersionOut(BaseModel):
    """The provenance of the newest resolution (D-3)."""

    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class LookStateResolutionOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    # None when there is no version yet.
    version: LookStateVersionOut | None
    scenes: list[LookStateSceneOut]
    # Why the newest version is out of date, one sentence each.
    reasons: list[str]
    # The newest resolution job, whatever its status.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None


class LookStateRunOut(BaseModel):
    job_id: int


def _item_out(item: ResolvedItem) -> LookStateItemOut:
    return LookStateItemOut(
        subject_id=item.subject_id,
        subject_name=item.subject_name,
        request=item.request,
        how=cast(How, item.how),
        id=item.id,
        name=item.name,
        description=item.description,
    )


def _scene_out(scene: SceneResolution) -> LookStateSceneOut:
    return LookStateSceneOut(
        id=scene.scene_id,
        index=scene.index,
        title=scene.title,
        resolved=scene.resolved,
        current=scene.current,
        environment=_item_out(scene.environment) if scene.environment is not None else None,
        looks=[_item_out(look) for look in scene.looks],
    )


def _state_out(result: look_state_resolution.ResolutionState) -> LookStateResolutionOut:
    row = result.version
    job = result.job
    return LookStateResolutionOut(
        scenes_version=result.scenes_version,
        version=(
            LookStateVersionOut(
                version=row.version,
                # The database CHECK constraint keeps `source` to the two allowed values.
                source=cast(Source, row.source),
                job_id=row.job_id,
                created_at=row.created_at,
            )
            if row is not None
            else None
        ),
        scenes=[_scene_out(scene) for scene in result.scenes],
        reasons=result.reasons,
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
        can_run=result.can_run,
        blocked_reason=result.blocked_reason,
    )


@router.get(
    "/projects/{project_id}/looks-and-states",
    response_model=LookStateResolutionOut,
    responses=_NOT_FOUND,
)
async def get_looks_and_states(project_id: int, session: SessionDep) -> LookStateResolutionOut:
    project = await load_project(session, project_id)
    return _state_out(await look_state_resolution.state(session, project))


@router.post(
    "/projects/{project_id}/looks-and-states/run",
    response_model=LookStateRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_looks_and_states(project_id: int, session: SessionDep) -> LookStateRunOut:
    """Starts the job that resolves every look and environment state the scenes asked for. If
    one is already waiting or running for the project, its id is returned and no second job is
    made.
    """
    project = await load_project(session, project_id)
    try:
        job = await look_state_resolution.start_run(session, project)
    except look_state_resolution.LookStateResolutionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return LookStateRunOut(job_id=job.id)
