"""`/api/projects/{project_id}/story-bible`: the Story Bible stage (PHASE-004).

- `POST .../run` starts the `write_story_bible` job from the project's saved story. When the
  newest version was written by the user, the body must confirm the replacement (PHASE-037).
- `PUT ...` saves the user's edited bible as the next version (`source` is `manual`).
- `GET ...` answers everything the story workspace shows for the stage in one call: the newest
  version, the list of versions, the newest job (running, failed or done) and whether the story
  has changed since the newest version was made. "Out of date" is worked out on every read.
- `GET .../versions/{version}` answers one older (or the newest) version.

The rows and the job are made by `app/services/story_bible.py`. The answers never return ORM
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
from app.db.models import Project, StoryBible
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.services import story_bible as story_bible_service

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or version."}}
_INVALID = {422: {"model": ErrorResponse, "description": "There is no saved story to read."}}

Source = Literal["ai", "manual"]


class StorytellingStyle(BaseModel):
    narration: str


class StoryBibleContent(BaseModel):
    """The bible itself (`Path_ahead.md` Section 6)."""

    title: str
    language: str
    genre: list[str]
    tone: list[str]
    visual_style: str
    time_period: str
    storytelling_style: StorytellingStyle
    world_rules: list[str]


class StoryBibleVersionOut(BaseModel):
    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class StoryBibleOut(StoryBibleVersionOut):
    id: int
    content: StoryBibleContent


class StoryBibleJobOut(BaseModel):
    """The newest `write_story_bible` job of the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class StoryBibleState(BaseModel):
    latest: StoryBibleOut | None
    versions: list[StoryBibleVersionOut]
    job: StoryBibleJobOut | None
    # Only the newest version is judged: whether the story text is no longer the one it was
    # made from. False when there is no version.
    out_of_date: bool
    # True when running the model again would add a version after one the user wrote.
    needs_confirmation: bool


class StoryBibleRun(BaseModel):
    job_id: int


class StoryBibleRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False


class StorytellingStyleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narration: str = Field(max_length=5000)


class StoryBibleSaveIn(BaseModel):
    """The bible as the user edited it. `language` is not sent: code fixes it to `en`. The size
    limits that matter are checked by `story_bible_writer.check_bible`; these only keep a
    request from being huge.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=5000)
    genre: list[str] = Field(max_length=100)
    tone: list[str] = Field(max_length=100)
    visual_style: str = Field(max_length=5000)
    time_period: str = Field(max_length=5000)
    storytelling_style: StorytellingStyleIn
    world_rules: list[str] = Field(max_length=100)


def _version_out(bible: StoryBible) -> StoryBibleVersionOut:
    return StoryBibleVersionOut(
        # The database CHECK constraint keeps `source` to the two allowed values.
        version=bible.version,
        source=cast(Source, bible.source),
        job_id=bible.job_id,
        created_at=bible.created_at,
    )


def _bible_out(bible: StoryBible) -> StoryBibleOut:
    return StoryBibleOut(
        **_version_out(bible).model_dump(),
        id=bible.id,
        content=StoryBibleContent.model_validate(bible.content),
    )


@router.post(
    "/projects/{project_id}/story-bible/run",
    response_model=StoryBibleRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_story_bible(
    project_id: int, session: SessionDep, body: StoryBibleRunIn | None = None
) -> StoryBibleRun:
    """Starts the job that writes the next version from the saved story. If one is already
    waiting or running for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await story_bible_service.start_run(
            session,
            project,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except story_bible_service.StoryBibleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return StoryBibleRun(job_id=job.id)


async def _state(session: AsyncSession, project: Project) -> StoryBibleState:
    latest = await story_bible_service.latest(session, project.id)
    versions = await story_bible_service.list_versions(session, project.id)
    job = await store.latest_job(session, project.id, story_bible_service.JOB_TYPE)
    return StoryBibleState(
        latest=_bible_out(latest) if latest is not None else None,
        versions=[_version_out(bible) for bible in versions],
        job=(
            StoryBibleJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        out_of_date=(
            story_bible_service.is_out_of_date(project.script_text, latest)
            if latest is not None
            else False
        ),
        needs_confirmation=(
            latest is not None and latest.source == story_bible_service.SOURCE_MANUAL
        ),
    )


@router.get(
    "/projects/{project_id}/story-bible",
    response_model=StoryBibleState,
    responses=_NOT_FOUND,
)
async def get_story_bible(project_id: int, session: SessionDep) -> StoryBibleState:
    return await _state(session, await load_project(session, project_id))


@router.put(
    "/projects/{project_id}/story-bible",
    response_model=StoryBibleState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_story_bible(
    project_id: int, body: StoryBibleSaveIn, session: SessionDep
) -> StoryBibleState:
    """Saves the whole edited bible as the next version, written by the user."""
    project = await load_project(session, project_id)
    try:
        await story_bible_service.save_manual(session, project, body.model_dump())
    except story_bible_service.StoryBibleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _state(session, project)


@router.get(
    "/projects/{project_id}/story-bible/versions/{version}",
    response_model=StoryBibleOut,
    responses=_NOT_FOUND,
)
async def get_story_bible_version(
    project_id: int,
    version: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> StoryBibleOut:
    project = await load_project(session, project_id)
    bible = await story_bible_service.get_version(session, project.id, version)
    if bible is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"The project has no Story Bible version {version}."
        )
    return _bible_out(bible)
