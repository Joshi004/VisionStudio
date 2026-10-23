"""`/api/projects/{project_id}/environment-definitions`: the Environment Definition stage
(PHASE-013).

- `GET ...` answers everything the story workspace shows in one call: the newest list of
  environments, and for each entry its library environment, its status (`unlinked`,
  `not_defined`, `defined`, `out_of_date`), why it is out of date, the definition the pinned
  version holds, the newest job, whether Define may be pressed, and how the canonical picture
  of the pinned version is doing. Out of date is worked out on every read.
- `POST .../run` ("Define all") starts one job per linked environment that the pipeline made,
  skipping (with the reason) an environment chosen from the library, an archived one, one that
  is defined and up to date already and one that is already being defined.
- `POST .../{discovery_id}/run` starts the job for one environment. An environment chosen from
  the library is overwritten only when the body says `confirm_overwrite: true`.
- `POST .../{discovery_id}/picture` starts the canonical picture of the pinned version again,
  for a defined environment that has none (it failed, or was never started).
- `POST .../{discovery_id}/replace-picture` makes a new canonical picture for a defined
  environment that has one (PHASE-039): a new version with no picture is pinned and its picture
  is started; the old picture stays with the old version.

A job writes the definition onto the library environment, as a new version the project pins,
and starts its picture (`services/environment_definitions.py`). The answers never return ORM
objects. The definition models here are also used by the Character Lab endpoints, which show
it read-only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.api.discovery import DiscoveryJobOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import environment_definitions
from app.services.environment_definitions import EntryDefinition, PictureState
from app.services.storage import media_url

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no saved story, up-to-date Story Bible or scenes, or list of "
        "environments, or the environment is not linked, is archived, or needs confirming.",
    }
}

Source = Literal["ai", "manual"]
Status = Literal["unlinked", "not_defined", "defined", "out_of_date"]
PictureStatus = Literal["unavailable", "none", "in_progress", "failed", "ready"]
PictureStage = Literal["writing_prompt", "drawing"]
EraKind = Literal["present", "past", "future"]


# --- The definition, as `Path_ahead.md` Section 13 gives it (plus the era) -----------------


class EnvironmentVisualIdentityOut(BaseModel):
    walls: str
    floor: str
    windows: str
    doors: str
    furniture: str
    color_palette: str


class EnvironmentAtmosphereOut(BaseModel):
    baseline: str


class EnvironmentEraOut(BaseModel):
    kind: EraKind
    years: int | None
    setting: str | None


SpatialSide = Literal["ahead", "left", "right", "behind"]


class EnvironmentSidesOut(BaseModel):
    ahead: str
    left: str
    right: str
    behind: str


class EnvironmentZoneOut(BaseModel):
    id: str
    name: str
    side: SpatialSide
    description: str


class EnvironmentSpatialPlanOut(BaseModel):
    """What is on every side of the master picture's camera, and where people can stand
    (PHASE-050).
    """

    master_view: str
    sides: EnvironmentSidesOut
    zones: list[EnvironmentZoneOut]


class EnvironmentDefinitionOut(BaseModel):
    id: str
    architecture: str
    layout: str
    # None for a definition written before PHASE-050.
    spatial_plan: EnvironmentSpatialPlanOut | None = None
    visual_identity: EnvironmentVisualIdentityOut
    important_landmarks: list[str]
    atmosphere: EnvironmentAtmosphereOut
    continuity_rules: list[str]
    era: EnvironmentEraOut


# --- The stage's state ----------------------------------------------------------------------


class EnvironmentDefinitionVersionOut(BaseModel):
    """The version of the library environment that holds the definition (the one the project
    pins): the provenance of the definition (D-3).
    """

    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class PictureImageOut(BaseModel):
    """A canonical picture: the Image lab image and where to show it."""

    id: int
    url: str


class EnvironmentPictureOut(BaseModel):
    """How the canonical picture of the version the project pins is doing."""

    status: PictureStatus
    # While `in_progress`: which step it is on.
    stage: PictureStage | None
    # While `failed`: why.
    error: str | None
    image: PictureImageOut | None
    # Whether Retry picture may be pressed, and the reason when it may not.
    can_run: bool
    blocked_reason: str | None


class EnvironmentDefinitionEntryOut(BaseModel):
    """One entry of the newest list of environments."""

    id: str
    name: str
    description: str
    # The library environment the entry is linked to, and the version the project pins. None
    # while the entry is unlinked.
    environment_id: int | None
    environment_name: str | None
    pinned_version: int | None
    status: Status
    # Why a defined entry is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The definition the pinned version holds, when it was written for this entry in this
    # project. None otherwise.
    definition: EnvironmentDefinitionOut | None
    version: EnvironmentDefinitionVersionOut | None
    # The newest definition job of this entry, whatever its status.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None
    # True for an environment chosen from the library: defining it overwrites its profile, so
    # the user is asked first.
    needs_confirmation: bool
    picture: EnvironmentPictureOut


class EnvironmentDefinitionsOut(BaseModel):
    # None when the project has no discovered environments yet.
    discovery_version: int | None
    entries: list[EnvironmentDefinitionEntryOut]
    # Why nothing can be defined yet (no saved story, up-to-date Story Bible or up-to-date
    # scenes), or None.
    blocked_reason: str | None


class EnvironmentRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required for an environment chosen from the library (it is overwritten).
    confirm_overwrite: bool = False


class EnvironmentSkippedOut(BaseModel):
    discovery_id: str
    name: str
    reason: str


class EnvironmentRunAllOut(BaseModel):
    job_ids: list[int]
    skipped: list[EnvironmentSkippedOut]


class EnvironmentRunOut(BaseModel):
    job_id: int


class EnvironmentPictureRunOut(BaseModel):
    reference_id: int


def _picture_out(picture: PictureState) -> EnvironmentPictureOut:
    return EnvironmentPictureOut(
        status=picture.status,
        stage=picture.stage,
        error=picture.error,
        image=(
            PictureImageOut(id=picture.image.id, url=media_url(picture.image.path))
            if picture.image is not None
            else None
        ),
        can_run=picture.can_run,
        blocked_reason=picture.blocked_reason,
    )


def _entry_out(entry: EntryDefinition) -> EnvironmentDefinitionEntryOut:
    info = entry.entry.info
    version = entry.version
    job = entry.job
    definition = entry.definition
    return EnvironmentDefinitionEntryOut(
        id=entry.item["id"],
        name=entry.item["name"],
        description=entry.item["description"],
        environment_id=info.environment.id if info is not None else None,
        environment_name=info.environment.name if info is not None else None,
        pinned_version=info.link.pinned_version if info is not None else None,
        status=entry.status,
        reasons=entry.reasons,
        definition=(
            EnvironmentDefinitionOut.model_validate(definition) if definition is not None else None
        ),
        version=(
            EnvironmentDefinitionVersionOut(
                version=version.version,
                # The database CHECK constraint keeps `source` to the two allowed values.
                source=cast(Source, version.source),
                job_id=version.job_id,
                created_at=version.created_at,
            )
            if version is not None
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
        picture=_picture_out(entry.picture),
    )


def _refused(exc: environment_definitions.EnvironmentDefinitionError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/environment-definitions",
    response_model=EnvironmentDefinitionsOut,
    responses=_NOT_FOUND,
)
async def get_environment_definitions(
    project_id: int, session: SessionDep
) -> EnvironmentDefinitionsOut:
    project = await load_project(session, project_id)
    result = await environment_definitions.state(session, project)
    return EnvironmentDefinitionsOut(
        discovery_version=result.discovery_version,
        entries=[_entry_out(entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/environment-definitions/run",
    response_model=EnvironmentRunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> EnvironmentRunAllOut:
    """Starts a job for every linked environment the pipeline made. An environment chosen from
    the library, an archived one, one defined and up to date already and one already being
    defined are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await environment_definitions.start_all(session, project)
    except environment_definitions.EnvironmentDefinitionError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return EnvironmentRunAllOut(
        job_ids=started.job_ids,
        skipped=[
            EnvironmentSkippedOut(
                discovery_id=item.discovery_id, name=item.name, reason=item.reason
            )
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/environment-definitions/{discovery_id}/run",
    response_model=EnvironmentRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_one(
    project_id: int,
    discovery_id: DiscoveryId,
    session: SessionDep,
    body: EnvironmentRunIn | None = None,
) -> EnvironmentRunOut:
    """Starts the job that defines one environment. If it already has a job waiting or running,
    that job's id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await environment_definitions.start_run(
            session,
            project,
            discovery_id,
            confirm_overwrite=body.confirm_overwrite if body is not None else False,
        )
    except environment_definitions.EnvironmentDefinitionError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return EnvironmentRunOut(job_id=job.id)


@router.post(
    "/projects/{project_id}/environment-definitions/{discovery_id}/picture",
    response_model=EnvironmentPictureRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_picture(
    project_id: int, discovery_id: DiscoveryId, session: SessionDep
) -> EnvironmentPictureRunOut:
    """Starts the canonical picture of the version the project pins again, for a defined
    environment that has no picture.
    """
    project = await load_project(session, project_id)
    try:
        attempt = await environment_definitions.start_picture(session, project, discovery_id)
    except environment_definitions.EnvironmentDefinitionError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return EnvironmentPictureRunOut(reference_id=attempt.id)


@router.post(
    "/projects/{project_id}/environment-definitions/{discovery_id}/replace-picture",
    response_model=EnvironmentPictureRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def replace_picture(
    project_id: int, discovery_id: DiscoveryId, session: SessionDep
) -> EnvironmentPictureRunOut:
    """Makes a new canonical picture for a defined environment that already has one (PHASE-039).
    The old picture stays with its version; the project moves to a new version and what used
    the old picture reads out of date.
    """
    project = await load_project(session, project_id)
    try:
        attempt = await environment_definitions.replace_picture(session, project, discovery_id)
    except environment_definitions.EnvironmentDefinitionError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return EnvironmentPictureRunOut(reference_id=attempt.id)
