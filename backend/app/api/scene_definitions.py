"""`/api/projects/{project_id}/scene-definitions`: the Scene Definition stage (PHASE-014).

- `GET ...` answers everything the story workspace shows in one call: the newest list of
  scenes, and for each scene its status (`not_defined`, `defined`, `out_of_date`), why it is
  out of date, its newest definition with its provenance, the newest job, and whether Define
  may be pressed. Out of date is worked out on every read.
- `POST .../run` ("Define all") starts one job per scene that is not defined and up to date
  already and not already being defined.
- `POST .../{scene_id}/run` starts the job for one scene. When the scene's newest definition was
  written by the user, the body must confirm the replacement (PHASE-037).
- `PUT .../{scene_id}` saves the user's edited definition of one scene as its next version
  (`source` is `manual`), checked like the model's answer.

A job stores a new version of the scene's definition (`services/scene_definitions.py`); nothing
is written to the Character Lab. The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.discovery import DiscoveryJobOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import scene_definitions
from app.services.scene_definitions import SceneEntry

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no saved story, up-to-date Story Bible or lists, or a "
        "character or environment is not linked and defined yet, or the scene is not in the "
        "newest list.",
    }
}

Source = Literal["ai", "manual"]
Status = Literal["not_defined", "defined", "out_of_date"]


# --- The definition, as `Path_ahead.md` Section 16 gives it ---------------------------------


class SceneStoryContextOut(BaseModel):
    before: str
    current: str
    after: str


class SceneTimeOut(BaseModel):
    time_of_day: str
    lighting_state: str


class SceneMoodOut(BaseModel):
    start: str
    middle: str
    end: str


class SceneDefinitionOut(BaseModel):
    id: str
    story_context: SceneStoryContextOut
    environment_id: str
    # A request in the model's own words, resolved later (PHASE-016).
    environment_state: str
    time: SceneTimeOut
    characters: list[str]
    # The characters who are only heard in the scene and never seen. Empty for a definition
    # written before this field existed.
    off_screen: list[str] = []
    # Requests in the model's own words, by character id, resolved later (PHASE-016).
    character_looks: dict[str, str]
    mood: SceneMoodOut
    dramatic_goal: str
    continuity_start: dict[str, str]
    continuity_end: dict[str, str]


# --- The stage's state ----------------------------------------------------------------------


class SceneDefinitionVersionOut(BaseModel):
    """The provenance of the newest definition of a scene (D-3)."""

    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class SceneDefinitionEntryOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    description: str
    status: Status
    # Why a defined scene is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    definition: SceneDefinitionOut | None
    version: SceneDefinitionVersionOut | None
    # The newest definition job of this scene, whatever its status.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None
    # True when defining this scene again would add a version after one the user wrote.
    needs_confirmation: bool


class SceneDefinitionsOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    entries: list[SceneDefinitionEntryOut]
    # Why nothing can be defined yet, or None.
    blocked_reason: str | None


class SceneDefinitionSkippedOut(BaseModel):
    scene_id: str
    title: str
    reason: str


class SceneDefinitionRunAllOut(BaseModel):
    job_ids: list[int]
    skipped: list[SceneDefinitionSkippedOut]


class SceneDefinitionRunOut(BaseModel):
    job_id: int


class SceneDefinitionRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False


_Text = Field(max_length=5000)


class SceneStoryContextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    before: str = _Text
    current: str = _Text
    after: str = _Text


class SceneTimeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_of_day: str = _Text
    lighting_state: str = _Text


class SceneMoodIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str = _Text
    middle: str = _Text
    end: str = _Text


class SceneDefinitionIn(BaseModel):
    """An edited definition. The `id` is the scene's and is set by code. The rules (known
    ids, sizes) are checked by `scene_definition_writer.check_definition`; these limits only
    keep a request from being huge.
    """

    model_config = ConfigDict(extra="forbid")

    story_context: SceneStoryContextIn
    environment_id: str = Field(max_length=200)
    environment_state: str = _Text
    time: SceneTimeIn
    characters: list[str] = Field(max_length=200)
    off_screen: list[str] = Field(default_factory=list, max_length=200)
    character_looks: dict[str, str] = Field(max_length=200)
    mood: SceneMoodIn
    dramatic_goal: str = _Text
    continuity_start: dict[str, str] = Field(max_length=200)
    continuity_end: dict[str, str] = Field(max_length=200)


def _entry_out(entry: SceneEntry) -> SceneDefinitionEntryOut:
    row = entry.row
    job = entry.job
    definition = entry.definition
    return SceneDefinitionEntryOut(
        id=entry.item["id"],
        index=entry.item["index"],
        title=entry.item["title"],
        description=entry.item["description"],
        status=entry.status,
        reasons=entry.reasons,
        definition=(
            SceneDefinitionOut.model_validate(definition) if definition is not None else None
        ),
        version=(
            SceneDefinitionVersionOut(
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


def _refused(exc: scene_definitions.SceneDefinitionError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/scene-definitions",
    response_model=SceneDefinitionsOut,
    responses=_NOT_FOUND,
)
async def get_scene_definitions(project_id: int, session: SessionDep) -> SceneDefinitionsOut:
    project = await load_project(session, project_id)
    return await _state_out(session, project)


async def _state_out(session: AsyncSession, project: Project) -> SceneDefinitionsOut:
    result = await scene_definitions.state(session, project)
    return SceneDefinitionsOut(
        scenes_version=result.scenes_version,
        entries=[_entry_out(entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/scene-definitions/run",
    response_model=SceneDefinitionRunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> SceneDefinitionRunAllOut:
    """Starts a job for every scene that is not defined and up to date already and not already
    being defined. The others are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await scene_definitions.start_all(session, project)
    except scene_definitions.SceneDefinitionError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return SceneDefinitionRunAllOut(
        job_ids=started.job_ids,
        skipped=[
            SceneDefinitionSkippedOut(scene_id=item.scene_id, title=item.title, reason=item.reason)
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/scene-definitions/{scene_id}/run",
    response_model=SceneDefinitionRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_one(
    project_id: int,
    scene_id: DiscoveryId,
    session: SessionDep,
    body: SceneDefinitionRunIn | None = None,
) -> SceneDefinitionRunOut:
    """Starts the job that defines one scene. If it already has a job waiting or running, that
    job's id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await scene_definitions.start_run(
            session,
            project,
            scene_id,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except scene_definitions.SceneDefinitionError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return SceneDefinitionRunOut(job_id=job.id)


@router.put(
    "/projects/{project_id}/scene-definitions/{scene_id}",
    response_model=SceneDefinitionsOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_definition(
    project_id: int, scene_id: DiscoveryId, body: SceneDefinitionIn, session: SessionDep
) -> SceneDefinitionsOut:
    """Saves the edited definition of one scene as its next version, written by the user."""
    project = await load_project(session, project_id)
    try:
        await scene_definitions.save_manual(session, project, scene_id, body.model_dump())
    except scene_definitions.SceneDefinitionError as exc:
        raise _refused(exc) from exc
    return await _state_out(session, project)
