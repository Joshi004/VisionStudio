"""`/api/projects/{project_id}/scene-staging`: the Scene Staging stage (PHASE-051).

- `GET ...` answers everything the story workspace shows in one call: the newest list of
  scenes, and for each scene its status (`not_staged`, `staged`, `out_of_date`), why it is out of
  date, its newest staging with its provenance, the newest job, and whether Stage may be pressed.
  Out of date is worked out on every read.
- `POST .../run` ("Stage all") starts one job per scene that is not staged and up to date
  already, can be staged and is not already being staged.
- `POST .../{scene_id}/run` starts the job for one scene. When the scene's newest staging was
  written by the user, the body must confirm the replacement.
- `PUT .../{scene_id}` saves the user's edited staging of one scene as its next version
  (`source` is `manual`). It is checked like the model's answer.

A job stores a new version of the scene's staging (`services/scene_staging.py`); nothing is
written to the Character Lab. The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.discovery import DiscoveryJobOut
from app.api.environment_definitions import EnvironmentZoneOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import scene_staging
from app.services.scene_staging import SceneEntry

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no saved story, up-to-date Story Bible or lists, or the scene "
        "is not defined and extracted yet, or the environment has no spatial plan, or the "
        "scene is not in the newest list.",
    }
}

Source = Literal["ai", "manual"]
Status = Literal["not_staged", "staged", "out_of_date"]
Side = Literal["ahead", "left", "right", "behind"]
ScreenSide = Literal["left", "right", "center"]


# --- The staging, as `Path_ahead.md` Section 46 gives it -----------------------------------


class PlacementOut(BaseModel):
    character_id: str
    zone: str
    posture: str
    faces: str
    screen_side: ScreenSide
    background_side: Side


class MoveOut(BaseModel):
    after_event_id: str
    character_id: str
    zone: str
    faces: str
    screen_side: ScreenSide
    background_side: Side


class AxisOut(BaseModel):
    between: list[str]
    camera_half: Side | None
    note: str


class StagingContentOut(BaseModel):
    scene_id: str
    placements: list[PlacementOut]
    axis: AxisOut
    group_side: Side
    moves: list[MoveOut]


# --- The stage's state ----------------------------------------------------------------------


class StagingVersionOut(BaseModel):
    """The provenance of the newest staging of a scene (D-3)."""

    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class StagingCharacterOut(BaseModel):
    id: str
    name: str


class StagingEnvironmentOut(BaseModel):
    """An environment with its zones, so the editor can offer them."""

    id: str
    name: str
    zones: list[EnvironmentZoneOut]


class StagingEntryOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    description: str
    status: Status
    # Why a staged scene is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    staging: StagingContentOut | None
    version: StagingVersionOut | None
    # The newest staging job of this scene, whatever its status.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None
    # True when staging this scene again would add a version after one the user wrote.
    needs_confirmation: bool


class SceneStagingOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    characters: list[StagingCharacterOut]
    environments: list[StagingEnvironmentOut]
    entries: list[StagingEntryOut]
    # Why nothing can be staged yet, or None.
    blocked_reason: str | None


class StagingSkippedOut(BaseModel):
    scene_id: str
    title: str
    reason: str


class StagingRunAllOut(BaseModel):
    job_ids: list[int]
    skipped: list[StagingSkippedOut]


class StagingRunOut(BaseModel):
    job_id: int


class StagingRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False


class PlacementIn(BaseModel):
    """One placement of an edited staging. The rules are checked by
    `scene_staging_writer.check_answer`; these limits only keep a request from being huge.
    """

    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(max_length=200)
    zone: str = Field(max_length=200)
    posture: str = Field(max_length=1000)
    faces: str = Field(max_length=200)
    screen_side: str = Field(max_length=20)
    background_side: str = Field(max_length=20)


class MoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    after_event_id: str = Field(max_length=200)
    character_id: str = Field(max_length=200)
    zone: str = Field(max_length=200)
    faces: str = Field(max_length=200)
    screen_side: str = Field(max_length=20)
    background_side: str = Field(max_length=20)


class AxisIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    between: list[str] = Field(default_factory=list, max_length=2)
    camera_half: str | None = Field(default=None, max_length=20)
    note: str = Field(default="", max_length=1000)


class StagingSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    placements: list[PlacementIn] = Field(max_length=50)
    axis: AxisIn
    group_side: str = Field(max_length=20)
    moves: list[MoveIn] = Field(default_factory=list, max_length=50)


def _entry_out(entry: SceneEntry) -> StagingEntryOut:
    row = entry.row
    job = entry.job
    content = entry.content
    return StagingEntryOut(
        id=entry.item["id"],
        index=entry.item["index"],
        title=entry.item["title"],
        description=entry.item["description"],
        status=entry.status,
        reasons=entry.reasons,
        staging=StagingContentOut.model_validate(content) if content is not None else None,
        version=(
            StagingVersionOut(
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
        needs_confirmation=entry.needs_confirmation,
    )


def _refused(exc: scene_staging.SceneStagingError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


async def _state_out(session: AsyncSession, project: Project) -> SceneStagingOut:
    result = await scene_staging.state(session, project)
    return SceneStagingOut(
        scenes_version=result.scenes_version,
        characters=[StagingCharacterOut(**character) for character in result.characters],
        environments=[
            StagingEnvironmentOut.model_validate(environment) for environment in result.environments
        ],
        entries=[_entry_out(entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.get(
    "/projects/{project_id}/scene-staging",
    response_model=SceneStagingOut,
    responses=_NOT_FOUND,
)
async def get_scene_staging(project_id: int, session: SessionDep) -> SceneStagingOut:
    project = await load_project(session, project_id)
    return await _state_out(session, project)


@router.post(
    "/projects/{project_id}/scene-staging/run",
    response_model=StagingRunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> StagingRunAllOut:
    """Starts a job for every scene that is not staged and up to date already, can be staged
    and is not already being staged. The others are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await scene_staging.start_all(session, project)
    except scene_staging.SceneStagingError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return StagingRunAllOut(
        job_ids=started.job_ids,
        skipped=[
            StagingSkippedOut(scene_id=item.scene_id, title=item.title, reason=item.reason)
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/scene-staging/{scene_id}/run",
    response_model=StagingRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_one(
    project_id: int,
    scene_id: DiscoveryId,
    session: SessionDep,
    body: StagingRunIn | None = None,
) -> StagingRunOut:
    """Starts the job that stages one scene. If it already has a job waiting or running, that
    job's id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await scene_staging.start_run(
            session,
            project,
            scene_id,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except scene_staging.SceneStagingError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return StagingRunOut(job_id=job.id)


@router.put(
    "/projects/{project_id}/scene-staging/{scene_id}",
    response_model=SceneStagingOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_staging(
    project_id: int, scene_id: DiscoveryId, body: StagingSaveIn, session: SessionDep
) -> SceneStagingOut:
    """Saves the whole edited staging of one scene as its next version, written by the user."""
    project = await load_project(session, project_id)
    content: dict[str, Any] = body.model_dump()
    try:
        await scene_staging.save_manual(session, project, scene_id, content)
    except scene_staging.SceneStagingError as exc:
        raise _refused(exc) from exc
    return await _state_out(session, project)
