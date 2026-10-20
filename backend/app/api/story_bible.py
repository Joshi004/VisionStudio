"""`/api/projects/{project_id}/story-bible`: the Story Bible stage (PHASE-004).

- `POST .../run` starts the `write_story_bible` job from the project's saved story.
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
from pydantic import BaseModel

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import StoryBible
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


class StoryBibleRun(BaseModel):
    job_id: int


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
async def run_story_bible(project_id: int, session: SessionDep) -> StoryBibleRun:
    """Starts the job that writes the next version from the saved story. If one is already
    waiting or running for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await story_bible_service.start_run(session, project)
    except story_bible_service.StoryBibleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return StoryBibleRun(job_id=job.id)


@router.get(
    "/projects/{project_id}/story-bible",
    response_model=StoryBibleState,
    responses=_NOT_FOUND,
)
async def get_story_bible(project_id: int, session: SessionDep) -> StoryBibleState:
    project = await load_project(session, project_id)
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
    )


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
