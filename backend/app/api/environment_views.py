"""The views of an environment (PHASE-052).

Project (`/api/projects/{project_id}/environment-views`):

- `GET ...` answers everything the story workspace shows in one call: each environment that
  scenes are set in, with its view plan (status, why it is out of date), its views (each with
  its picture and status) and the newest planning job. Worked out on every read.
- `POST .../run` ("Plan all") starts one planning job per environment that is not planned and
  current, can be planned and is not already being planned.
- `POST .../{discovery_id}/run` plans one environment.
- `POST .../{discovery_id}/pictures` starts the pictures of every view of the plan that has none.
- `POST .../views/{view_id}/remake` makes one view's picture again.

Lab (`/api/lab/environments/{environment_id}/views`): the views of a library environment, and
`POST .../{view_id}/remake`, which makes a view again from the newest version's master picture.

A planning job stores a new plan and adds library views (`services/environment_views.py`); a
picture is an edit of the master picture. The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal, cast

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.discovery import DiscoveryJobOut
from app.api.environment_lab import PictureOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import LabImage, Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import environment_library, environment_views
from app.services.environment_views import EnvironmentEntry, ViewItem
from app.services.storage import media_url

router = APIRouter()

_MAX_ID: Final = 2**63 - 1
RecordId = Annotated[int, Path(ge=1, le=_MAX_ID)]

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The scenes are not staged, the environment has no master picture or "
        "spatial plan, or there is nothing to start.",
    }
}

Side = Literal["ahead", "left", "right", "behind"]
Framing = Literal["wide", "medium", "close"]
PlanStatus = Literal["not_planned", "planned", "out_of_date"]
ViewStatus = Literal["none", "in_progress", "failed", "ready"]
ViewStage = Literal["writing_prompt", "drawing", "waiting"]


class ViewStatePictureOut(BaseModel):
    """The picture of a view in one named state of its environment (PHASE-053)."""

    slug: str
    name: str
    image: PictureOut


class ViewOut(BaseModel):
    """One view of an environment and where its picture stands."""

    id: int
    slug: str
    name: str
    side: Side
    framing: Framing
    zone: str | None
    description: str
    source: Literal["ai", "manual"]
    created_at: datetime
    # The edit prompt written for the picture, once it is written.
    prompt: str | None
    status: ViewStatus
    stage: ViewStage | None
    error: str | None
    # Why a ready picture is out of date, one sentence each.
    reasons: list[str]
    # The titles of the scenes whose backgrounds it covers (a project's plan only).
    scenes: list[str]
    # Taken from the library, not added by this project's plan (a project's plan only).
    reused: bool
    image: PictureOut | None
    # The view's pictures in the environment's named states that exist (PHASE-053).
    states: list[ViewStatePictureOut]


class PlanVersionOut(BaseModel):
    version: int
    source: Literal["ai", "manual"]
    job_id: int | None
    created_at: datetime


class SceneCoverageOut(BaseModel):
    """The views that cover each background side of one scene and its group."""

    scene_id: str
    title: str
    by_side: dict[str, list[str]]
    group: list[str]


class EnvironmentViewsEntryOut(BaseModel):
    id: str
    name: str
    status: PlanStatus
    reasons: list[str]
    version: PlanVersionOut | None
    job: DiscoveryJobOut | None
    scenes: list[str]
    coverage: list[SceneCoverageOut]
    views: list[ViewOut]
    pictures_status: ViewStatus
    can_plan: bool
    plan_blocked_reason: str | None
    can_make_pictures: bool
    pictures_blocked_reason: str | None
    # The environment's master picture, which every view is an edit of.
    master: PictureOut | None


class EnvironmentViewsOut(BaseModel):
    entries: list[EnvironmentViewsEntryOut]
    blocked_reason: str | None


class SkippedOut(BaseModel):
    id: str
    name: str
    reason: str


class PlanRunAllOut(BaseModel):
    job_ids: list[int]
    skipped: list[SkippedOut]


class JobRunOut(BaseModel):
    job_id: int


class PicturesRunOut(BaseModel):
    started: list[int]
    waiting: list[int]


def _view_out(item: ViewItem) -> ViewOut:
    view = item.view
    return ViewOut(
        id=view.id,
        slug=view.slug,
        name=view.name,
        # The database CHECK constraints keep these columns to their allowed values.
        side=cast(Side, view.side),
        framing=cast(Framing, view.framing),
        zone=view.zone,
        description=view.description,
        source=cast(Literal["ai", "manual"], view.source),
        created_at=view.created_at,
        prompt=view.prompt,
        status=item.status,
        stage=item.stage,
        error=item.error,
        reasons=item.reasons,
        scenes=item.scenes,
        reused=item.reused,
        image=(
            PictureOut(id=item.image.id, url=media_url(item.image.path))
            if item.image is not None
            else None
        ),
        states=[
            ViewStatePictureOut(
                slug=picture.slug,
                name=picture.name,
                image=PictureOut(id=picture.image.id, url=media_url(picture.image.path)),
            )
            for picture in item.states
        ],
    )


async def _master(session: AsyncSession, image_id: int | None) -> PictureOut | None:
    if image_id is None:
        return None
    image = await session.get(LabImage, image_id)
    return PictureOut(id=image.id, url=media_url(image.path)) if image is not None else None


async def _entry_out(session: AsyncSession, entry: EnvironmentEntry) -> EnvironmentViewsEntryOut:
    plan = entry.plan
    job = entry.job
    titles = {need.scene_id: need.title for need in entry.needs}
    return EnvironmentViewsEntryOut(
        id=entry.discovery_id,
        name=entry.name,
        status=entry.status,
        reasons=entry.reasons,
        version=(
            PlanVersionOut(
                version=plan.version,
                source=cast(Literal["ai", "manual"], plan.source),
                job_id=plan.job_id,
                created_at=plan.created_at,
            )
            if plan is not None
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
        scenes=entry.scenes,
        coverage=[
            SceneCoverageOut(
                scene_id=scene["scene_id"],
                title=titles.get(scene["scene_id"], scene["scene_id"]),
                by_side=scene["by_side"],
                group=scene["group"],
            )
            for scene in (plan.content["scenes"] if plan is not None else [])
        ],
        views=[_view_out(item) for item in entry.views],
        pictures_status=entry.pictures_status,
        can_plan=entry.can_plan,
        plan_blocked_reason=entry.plan_blocked_reason,
        can_make_pictures=entry.can_make_pictures,
        pictures_blocked_reason=entry.pictures_blocked_reason,
        master=await _master(session, entry.master_image_id),
    )


def _refused(exc: environment_views.EnvironmentViewError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


async def _state_out(session: AsyncSession, project: Project) -> EnvironmentViewsOut:
    result = await environment_views.state(session, project)
    return EnvironmentViewsOut(
        entries=[await _entry_out(session, entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.get(
    "/projects/{project_id}/environment-views",
    response_model=EnvironmentViewsOut,
    responses=_NOT_FOUND,
)
async def get_environment_views(project_id: int, session: SessionDep) -> EnvironmentViewsOut:
    project = await load_project(session, project_id)
    return await _state_out(session, project)


@router.post(
    "/projects/{project_id}/environment-views/run",
    response_model=PlanRunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def plan_all(project_id: int, session: SessionDep) -> PlanRunAllOut:
    """Starts a planning job for every environment that is not planned and current, can be
    planned and is not already being planned. The others are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await environment_views.start_plan_all(session, project)
    except environment_views.EnvironmentViewError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return PlanRunAllOut(
        job_ids=started.job_ids,
        skipped=[
            SkippedOut(id=item.discovery_id, name=item.name, reason=item.reason)
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/environment-views/{discovery_id}/run",
    response_model=JobRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def plan_one(project_id: int, discovery_id: DiscoveryId, session: SessionDep) -> JobRunOut:
    """Starts the job that plans one environment's views. If it already has a job waiting or
    running, that job's id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await environment_views.start_plan(session, project, discovery_id)
    except environment_views.EnvironmentViewError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return JobRunOut(job_id=job.id)


@router.post(
    "/projects/{project_id}/environment-views/{discovery_id}/pictures",
    response_model=PicturesRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def make_pictures(
    project_id: int, discovery_id: DiscoveryId, session: SessionDep
) -> PicturesRunOut:
    """Starts the picture of every view of the plan that has none and is not being made. A
    view of what is behind the master camera waits for the left and right views.
    """
    project = await load_project(session, project_id)
    try:
        result = await environment_views.start_pictures(session, project, discovery_id)
    except environment_views.EnvironmentViewError as exc:
        raise _refused(exc) from exc
    if result.started:
        dispatcher.nudge()
    return PicturesRunOut(started=result.started, waiting=result.waiting)


@router.post(
    "/projects/{project_id}/environment-views/views/{view_id}/remake",
    response_model=JobRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def remake_project_view(project_id: int, view_id: RecordId, session: SessionDep) -> JobRunOut:
    """Makes one view's picture again, from the master picture the project pins."""
    project = await load_project(session, project_id)
    try:
        job = await environment_views.remake_view(session, view_id, project)
    except environment_views.EnvironmentViewError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return JobRunOut(job_id=job.id)


# --- The Character lab ----------------------------------------------------------------------

_LAB_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such environment."}}


async def _require_environment(session: AsyncSession, environment_id: int) -> None:
    if await environment_library.get_environment(session, environment_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"There is no environment {environment_id}.")


@router.get(
    "/lab/environments/{environment_id}/views",
    response_model=list[ViewOut],
    responses=_LAB_NOT_FOUND,
)
async def list_environment_views(environment_id: RecordId, session: SessionDep) -> list[ViewOut]:
    """The views of this environment, oldest first, each with its picture once it is made. A
    story project's plan creates them.
    """
    await _require_environment(session, environment_id)
    return [_view_out(item) for item in await environment_views.lab_items(session, environment_id)]


@router.post(
    "/lab/environments/{environment_id}/views/{view_id}/remake",
    response_model=JobRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_LAB_NOT_FOUND, **_INVALID},
)
async def remake_lab_view(
    environment_id: RecordId, view_id: RecordId, session: SessionDep
) -> JobRunOut:
    """Makes one view's picture again, from the master picture of the environment's newest
    version.
    """
    await _require_environment(session, environment_id)
    view_ids = {item.view.id for item in await environment_views.lab_items(session, environment_id)}
    if view_id not in view_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This environment has no such view.")
    try:
        job = await environment_views.remake_view(session, view_id, None)
    except environment_views.EnvironmentViewError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return JobRunOut(job_id=job.id)
