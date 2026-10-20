"""`/api/projects/{project_id}/scenes`: the scene discovery stage (PHASE-006).

- `POST .../run` starts the `discover_scenes` job from the project's saved story and its
  newest, up-to-date StoryBible.
- `GET ...` answers everything the story workspace shows for the stage in one call: the newest
  version, the list of versions, the newest job (running, failed or done) and whether the story
  or the StoryBible has changed since the newest version was made. "Out of date" is worked out
  on every read.
- `GET .../versions/{version}` answers one older (or the newest) version.

It is the stage of `api/discovery.py` with a richer result: each scene carries the slice of
the story it owns (`text`, cut by code from the author's story), so the scenes' texts joined in
order are the whole story. The rows and the jobs are made by `app/services/discovery.py`
(`kind` is `"scenes"`). The answers never return ORM objects.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel

from app.api.discovery import DiscoveryJobOut, DiscoveryVersionOut
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.services import discovery as discovery_service
from app.services import story_bible as story_bible_service
from app.services.discovery import Discovery

router = APIRouter()

KIND: Literal["scenes"] = "scenes"

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


class SceneItem(BaseModel):
    """One discovered scene. Nothing about who is in it or where it happens is kept (D-15)."""

    index: int
    id: str
    title: str
    description: str
    # The opening words the model gave, as it gave them.
    starts_with: str
    # Where the scene's slice of the story starts and ends (characters of the story it was made
    # from), and the slice itself. `text` is exactly the story's `[start:end]`.
    start: int
    end: int
    text: str


class SceneDiscoveryOut(DiscoveryVersionOut):
    id: int
    scenes: list[SceneItem]


class SceneDiscoveryState(BaseModel):
    latest: SceneDiscoveryOut | None
    versions: list[DiscoveryVersionOut]
    job: DiscoveryJobOut | None
    # Only the newest version is judged: whether the story text is no longer the one it was
    # made from, or there is a newer StoryBible than the one it read. False when there is no
    # version.
    out_of_date: bool


class SceneDiscoveryRun(BaseModel):
    job_id: int


def _version_out(row: Discovery) -> DiscoveryVersionOut:
    return DiscoveryVersionOut(
        # The database CHECK constraint keeps `source` to the two allowed values.
        version=row.version,
        source=cast(Source, row.source),
        job_id=row.job_id,
        created_at=row.created_at,
    )


def _scenes_out(row: Discovery) -> SceneDiscoveryOut:
    return SceneDiscoveryOut(
        **_version_out(row).model_dump(),
        id=row.id,
        scenes=[SceneItem.model_validate(scene) for scene in row.content[KIND]],
    )


@router.post(
    "/projects/{project_id}/scenes/run",
    response_model=SceneDiscoveryRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_scenes(project_id: int, session: SessionDep) -> SceneDiscoveryRun:
    """Starts the job that finds the next version from the saved story. If one is already
    waiting or running for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await discovery_service.start_run(session, project, KIND)
    except discovery_service.DiscoveryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return SceneDiscoveryRun(job_id=job.id)


@router.get(
    "/projects/{project_id}/scenes",
    response_model=SceneDiscoveryState,
    responses=_NOT_FOUND,
)
async def get_scenes(project_id: int, session: SessionDep) -> SceneDiscoveryState:
    project = await load_project(session, project_id)
    latest = await discovery_service.latest(session, KIND, project.id)
    versions = await discovery_service.list_versions(session, KIND, project.id)
    job = await store.latest_job(session, project.id, discovery_service.SPECS[KIND].job_type)
    newest_bible = await story_bible_service.latest(session, project.id)
    return SceneDiscoveryState(
        latest=_scenes_out(latest) if latest is not None else None,
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
    )


@router.get(
    "/projects/{project_id}/scenes/versions/{version}",
    response_model=SceneDiscoveryOut,
    responses=_NOT_FOUND,
)
async def get_scenes_version(
    project_id: int,
    version: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> SceneDiscoveryOut:
    project = await load_project(session, project_id)
    row = await discovery_service.get_version(session, KIND, project.id, version)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"The project has no scenes version {version}."
        )
    return _scenes_out(row)
