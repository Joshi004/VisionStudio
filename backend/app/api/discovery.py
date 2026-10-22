"""`/api/projects/{project_id}/discovery/{kind}`: the character and environment discovery
stages (PHASE-005). `kind` is `characters` or `environments`; the two behave the same.

- `POST .../run` starts the discovery job from the project's saved story and its newest,
  up-to-date StoryBible.
- `GET ...` answers everything the story workspace shows for the stage in one call: the newest
  version, the list of versions, the newest job (running, failed or done) and whether the story
  or the StoryBible has changed since the newest version was made. "Out of date" is worked out
  on every read.
- `GET .../versions/{version}` answers one older (or the newest) version.
- `PUT ...` saves the user's edited list as the next version (`source` is `manual`, PHASE-037).
  `POST .../run` over a version the user wrote needs `confirm_replace_manual` in its body.

The rows and the jobs are made by `app/services/discovery.py`. The answers never return ORM
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
from app.db.models import Project
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.services import discovery as discovery_service
from app.services import discovery_edits
from app.services import story_bible as story_bible_service
from app.services.discovery import Discovery
from app.services.discovery_writer import Kind

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or version."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no saved story, or no up-to-date Story Bible, to read.",
    }
}

Source = Literal["ai", "manual"]


class DiscoveryItem(BaseModel):
    """One discovered character or environment. Nothing else is kept about it (Path_ahead.md
    Sections 7 and 8); the definition stages add the rest.
    """

    id: str
    name: str
    description: str


class DiscoveryVersionOut(BaseModel):
    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class DiscoveryOut(DiscoveryVersionOut):
    id: int
    items: list[DiscoveryItem]


class DiscoveryJobOut(BaseModel):
    """The newest discovery job of this kind for the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class DiscoveryState(BaseModel):
    latest: DiscoveryOut | None
    versions: list[DiscoveryVersionOut]
    job: DiscoveryJobOut | None
    # Only the newest version is judged: whether the story text is no longer the one it was
    # made from, or there is a newer StoryBible than the one it read. False when there is no
    # version.
    out_of_date: bool
    # True when finding the list again would add a version after one the user wrote.
    needs_confirmation: bool


class DiscoveryRun(BaseModel):
    job_id: int


class DiscoveryRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False


class DiscoveryItemIn(BaseModel):
    """One entry of an edited list. The rules (slug, sizes) are checked by
    `discovery_writer.check_items`; these limits only keep a request from being huge.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=200)
    name: str = Field(max_length=2000)
    description: str = Field(max_length=5000)


class DiscoverySaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DiscoveryItemIn] = Field(max_length=200)


def _version_out(row: Discovery) -> DiscoveryVersionOut:
    return DiscoveryVersionOut(
        # The database CHECK constraint keeps `source` to the two allowed values.
        version=row.version,
        source=cast(Source, row.source),
        job_id=row.job_id,
        created_at=row.created_at,
    )


def _discovery_out(kind: Kind, row: Discovery) -> DiscoveryOut:
    return DiscoveryOut(
        **_version_out(row).model_dump(),
        id=row.id,
        items=[DiscoveryItem.model_validate(item) for item in row.content[kind]],
    )


@router.post(
    "/projects/{project_id}/discovery/{kind}/run",
    response_model=DiscoveryRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_discovery(
    project_id: int, kind: Kind, session: SessionDep, body: DiscoveryRunIn | None = None
) -> DiscoveryRun:
    """Starts the job that finds the next version from the saved story. If one of this kind is
    already waiting or running for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await discovery_service.start_run(
            session,
            project,
            kind,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except discovery_service.DiscoveryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return DiscoveryRun(job_id=job.id)


async def _state(session: AsyncSession, project: Project, kind: Kind) -> DiscoveryState:
    latest = await discovery_service.latest(session, kind, project.id)
    versions = await discovery_service.list_versions(session, kind, project.id)
    job = await store.latest_job(session, project.id, discovery_service.SPECS[kind].job_type)
    newest_bible = await story_bible_service.latest(session, project.id)
    return DiscoveryState(
        latest=_discovery_out(kind, latest) if latest is not None else None,
        versions=[_version_out(row) for row in versions],
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
        out_of_date=(
            discovery_service.is_out_of_date(
                project.script_text,
                latest,
                newest_bible.version if newest_bible is not None else None,
            )
            if latest is not None
            else False
        ),
        needs_confirmation=(
            latest is not None and latest.source == discovery_service.SOURCE_MANUAL
        ),
    )


@router.get(
    "/projects/{project_id}/discovery/{kind}",
    response_model=DiscoveryState,
    responses=_NOT_FOUND,
)
async def get_discovery(project_id: int, kind: Kind, session: SessionDep) -> DiscoveryState:
    return await _state(session, await load_project(session, project_id), kind)


@router.put(
    "/projects/{project_id}/discovery/{kind}",
    response_model=DiscoveryState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_discovery(
    project_id: int, kind: Kind, body: DiscoverySaveIn, session: SessionDep
) -> DiscoveryState:
    """Saves the whole edited list as the next version, written by the user. Removing an entry
    that a scene still uses is refused.
    """
    project = await load_project(session, project_id)
    try:
        await discovery_edits.save_manual_list(
            session, project, kind, [item.model_dump() for item in body.items]
        )
    except discovery_service.DiscoveryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _state(session, project, kind)


@router.get(
    "/projects/{project_id}/discovery/{kind}/versions/{version}",
    response_model=DiscoveryOut,
    responses=_NOT_FOUND,
)
async def get_discovery_version(
    project_id: int,
    kind: Kind,
    version: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> DiscoveryOut:
    project = await load_project(session, project_id)
    row = await discovery_service.get_version(session, kind, project.id, version)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"The project has no {kind} version {version}."
        )
    return _discovery_out(kind, row)
