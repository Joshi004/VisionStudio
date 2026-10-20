"""`/api/lab/environments`: the environment library of the Character lab (PHASE-012).

A `library_environment` is a reusable place: a profile and one canonical reference picture per
version. It belongs to no project (a story project links to one in PHASE-013).

- Every change of the profile adds an immutable version (`environment_versions`);
  `GET /{id}/versions` lists them, newest first, read-only. Each version has its own canonical
  picture, which an edit never carries forward.
- `POST /{id}/references` starts an attempt for the newest version: a language model writes the
  prompt, then four 16:9 candidate pictures are made. `POST /references/{id}/choose` makes one
  the canonical picture of the version the attempt was made for. Only the newest version's
  picture can be chosen or replaced.

`POST .../references` answers at once with HTTP 202; the dispatcher does the work and the page
polls. The rules are in `services/environment_library.py` and `environment_references.py`. A
candidate picture is an ordinary Image lab run, so it also appears in that lab's history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal
from typing import cast as typing_cast

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobSummary, job_summary
from app.db.models import (
    EnvironmentReference,
    Job,
    LabImage,
    LabRun,
    LibraryEnvironment,
    LibraryEnvironmentVersion,
)
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import (
    environment_library,
    environment_references,
    environment_versions,
    image_lab,
)
from app.services.environment_library import EnvironmentLibraryError
from app.services.environment_references import EnvironmentReferenceError
from app.services.storage import media_url

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
Id = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]
EnvironmentId = Annotated[int, Path(ge=1, le=_MAX_ID)]
ReferenceId = Annotated[int, Path(ge=1, le=_MAX_ID)]

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No environment has this id."}}
_INVALID = {422: {"model": ErrorResponse, "description": "The request breaks a rule."}}

EraKind = Literal["present", "past", "future"]
ReferenceStatus = Literal["writing_prompt", "ready", "failed"]


def _missing(message: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, message)


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _job_summary(job: Job | None) -> JobSummary | None:
    if job is None:
        return None
    return job_summary(JobRow(job=job, project_name=store.owner_name(job, None)))


# --- The environment's profile -------------------------------------------------------------


class EnvironmentIn(BaseModel):
    """The create form. Every field is sent, even when it has not changed."""

    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    description: StrictStr
    era_kind: EraKind = "present"
    era_years: StrictInt | None = None
    era_setting: StrictStr | None = None
    atmosphere: StrictStr | None = None
    notes: StrictStr | None = None


class EnvironmentPatch(BaseModel):
    """What to change in an environment: any profile field, and/or `archived`. A profile field
    that is left out keeps its current value.
    """

    model_config = ConfigDict(extra="forbid")

    name: StrictStr | None = None
    description: StrictStr | None = None
    era_kind: EraKind | None = None
    era_years: StrictInt | None = None
    era_setting: StrictStr | None = None
    atmosphere: StrictStr | None = None
    notes: StrictStr | None = None
    archived: StrictBool | None = None


class PictureOut(BaseModel):
    """A canonical picture: the Image lab image and where to show it."""

    id: int
    url: str


class EnvironmentOut(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    name: str
    description: str
    era_kind: EraKind
    era_years: int | None
    era_setting: str | None
    atmosphere: str | None
    notes: str | None
    archived: bool
    # The number of the environment's newest version.
    version: int | None
    # The canonical picture of the newest version. None until one is chosen, and again after an
    # edit adds a version (the picture belongs to the text it was made for).
    image: PictureOut | None


class EnvironmentsOut(BaseModel):
    environments: list[EnvironmentOut]
    next_before_id: int | None


async def _picture(session: AsyncSession, image_id: int | None) -> PictureOut | None:
    if image_id is None:
        return None
    image = await session.get(LabImage, image_id)
    return PictureOut(id=image.id, url=media_url(image.path)) if image is not None else None


async def _environment_out(
    session: AsyncSession, environment: LibraryEnvironment
) -> EnvironmentOut:
    newest = await environment_versions.latest_version(session, environment.id)
    return EnvironmentOut(
        id=environment.id,
        created_at=environment.created_at,
        updated_at=environment.updated_at,
        name=environment.name,
        description=environment.description,
        era_kind=typing_cast(EraKind, environment.era_kind),
        era_years=environment.era_years,
        era_setting=environment.era_setting,
        atmosphere=environment.atmosphere,
        notes=environment.notes,
        archived=environment.archived,
        version=newest.version if newest is not None else None,
        image=await _picture(session, newest.reference_image_id if newest is not None else None),
    )


def _form(body: EnvironmentIn) -> environment_library.EnvironmentForm:
    return environment_library.EnvironmentForm(
        name=body.name,
        description=body.description,
        era_kind=body.era_kind,
        era_years=body.era_years,
        era_setting=body.era_setting,
        atmosphere=body.atmosphere,
        notes=body.notes,
    )


def _merged_form(
    environment: LibraryEnvironment, body: EnvironmentPatch
) -> environment_library.EnvironmentForm:
    sent = body.model_fields_set

    def pick(field: str) -> Any:
        return getattr(body, field) if field in sent else getattr(environment, field)

    return environment_library.EnvironmentForm(
        name=pick("name"),
        description=pick("description"),
        era_kind=pick("era_kind"),
        era_years=pick("era_years"),
        era_setting=pick("era_setting"),
        atmosphere=pick("atmosphere"),
        notes=pick("notes"),
    )


@router.get("/lab/environments", response_model=EnvironmentsOut)
async def list_environments(
    session: SessionDep,
    include_archived: bool = False,
    before_id: Annotated[int | None, Query(ge=1, le=_MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> EnvironmentsOut:
    """The newest environments first. Pass the last id you have as `before_id` for the next
    page.
    """
    environments = await environment_library.list_environments(
        session, include_archived=include_archived, before_id=before_id, limit=limit
    )
    return EnvironmentsOut(
        environments=[await _environment_out(session, env) for env in environments],
        next_before_id=environments[-1].id if len(environments) == limit else None,
    )


@router.post(
    "/lab/environments",
    response_model=EnvironmentOut,
    status_code=status.HTTP_201_CREATED,
    responses=_INVALID,
)
async def create_environment(body: EnvironmentIn, session: SessionDep) -> EnvironmentOut:
    """Saves a new environment's profile, as its version 1. Its picture is made afterwards."""
    try:
        environment = await environment_library.create_environment(session, _form(body))
    except EnvironmentLibraryError as exc:
        raise _unprocessable(str(exc)) from exc
    return await _environment_out(session, environment)


@router.get(
    "/lab/environments/{environment_id}", response_model=EnvironmentOut, responses=_NOT_FOUND
)
async def get_environment(environment_id: EnvironmentId, session: SessionDep) -> EnvironmentOut:
    environment = await environment_library.get_environment(session, environment_id)
    if environment is None:
        raise _missing(f"There is no environment {environment_id}.")
    return await _environment_out(session, environment)


@router.patch(
    "/lab/environments/{environment_id}",
    response_model=EnvironmentOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def edit_environment(
    environment_id: EnvironmentId, body: EnvironmentPatch, session: SessionDep
) -> EnvironmentOut:
    """Changes the profile, archives or unarchives an environment, or both at once. A change to
    the profile adds a version; archiving does not.
    """
    environment = await environment_library.get_environment(session, environment_id)
    if environment is None:
        raise _missing(f"There is no environment {environment_id}.")
    sent = body.model_fields_set
    if not sent:
        raise _unprocessable("Send at least one field to change.")
    try:
        if sent - {"archived"}:
            environment = await environment_library.update_environment(
                session, environment_id, _merged_form(environment, body)
            )
        if "archived" in sent and body.archived is not None:
            environment = await environment_library.set_archived(
                session, environment_id, body.archived
            )
    except EnvironmentLibraryError as exc:
        raise _unprocessable(str(exc)) from exc
    return await _environment_out(session, environment)


# --- An environment's versions (read-only) ---------------------------------------------------


class EnvironmentProfileOut(BaseModel):
    """The profile as a version froze it."""

    name: str
    description: str
    era_kind: EraKind
    era_years: int | None
    era_setting: str | None
    atmosphere: str | None
    notes: str | None


class EnvironmentVersionOut(BaseModel):
    id: int
    version: int
    created_at: datetime
    source: Literal["ai", "manual"]
    # What this version changed compared with the one before it.
    changes: list[environment_versions.Change]
    profile: EnvironmentProfileOut
    # The canonical picture of this version. None when none was chosen for it.
    image: PictureOut | None


@router.get(
    "/lab/environments/{environment_id}/versions",
    response_model=list[EnvironmentVersionOut],
    responses=_NOT_FOUND,
)
async def list_versions(
    environment_id: EnvironmentId, session: SessionDep
) -> list[EnvironmentVersionOut]:
    """Every version of this environment, newest first, each with what it changed and its own
    picture. A version is never edited: it is added when the profile changes.
    """
    if await environment_library.get_environment(session, environment_id) is None:
        raise _missing(f"There is no environment {environment_id}.")
    entries = await environment_versions.list_versions(session, environment_id)
    return [
        EnvironmentVersionOut(
            id=entry.version.id,
            version=entry.version.version,
            created_at=entry.version.created_at,
            source=typing_cast(Literal["ai", "manual"], entry.version.source),
            changes=entry.changes,
            profile=EnvironmentProfileOut.model_validate(entry.version.profile),
            image=await _picture(session, entry.version.reference_image_id),
        )
        for entry in entries
    ]


# --- An environment's reference pictures -------------------------------------------------------


class ReferenceCandidateOut(BaseModel):
    id: int
    url: str | None
    job: JobSummary | None
    # True for the candidate whose picture is the version's canonical picture.
    chosen: bool


class ReferenceOut(BaseModel):
    id: int
    created_at: datetime
    # The number of the version this attempt was made for.
    version: int
    # True once an edit added a newer version: the attempt is shown, but cannot be chosen from.
    frozen: bool
    status: ReferenceStatus
    prompt: str | None
    error: str | None
    prompt_job: JobSummary | None
    candidates: list[ReferenceCandidateOut]


async def _reference_out(
    session: AsyncSession, attempt: EnvironmentReference, newest_id: int | None
) -> ReferenceOut:
    version = await session.get(LibraryEnvironmentVersion, attempt.version_id)
    prompt_job = await session.get(Job, attempt.prompt_job_id) if attempt.prompt_job_id else None
    candidates = await environment_references.candidates_for(session, attempt.id)
    run_ids = [c.lab_run_id for c in candidates if c.lab_run_id is not None]
    runs: dict[int, LabRun] = {}
    if run_ids:
        found = await session.execute(select(LabRun).where(LabRun.id.in_(run_ids)))
        runs = {run.id: run for run in found.scalars()}
    jobs = await image_lab.jobs_for_runs(session, list(runs.values()))
    images = await image_lab.images_by_run(session, run_ids)
    chosen_image_id = version.reference_image_id if version is not None else None

    candidates_out = []
    for candidate in candidates:
        found_images = images.get(candidate.lab_run_id or 0)
        image = found_images[0] if found_images else None
        candidates_out.append(
            ReferenceCandidateOut(
                id=candidate.id,
                url=media_url(image.path) if image is not None else None,
                job=_job_summary(jobs.get(candidate.lab_run_id or 0)),
                chosen=image is not None and image.id == chosen_image_id,
            )
        )
    return ReferenceOut(
        id=attempt.id,
        created_at=attempt.created_at,
        version=version.version if version is not None else 0,
        frozen=newest_id is None or attempt.version_id != newest_id,
        status=typing_cast(ReferenceStatus, attempt.status),
        prompt=attempt.prompt,
        error=attempt.error,
        prompt_job=_job_summary(prompt_job),
        candidates=candidates_out,
    )


@router.post(
    "/lab/environments/{environment_id}/references",
    response_model=ReferenceOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def start_reference(environment_id: EnvironmentId, session: SessionDep) -> ReferenceOut:
    """Starts an attempt to make a canonical picture for the newest version: a language model
    writes the prompt, then four candidate pictures are made to choose from.
    """
    if await environment_library.get_environment(session, environment_id) is None:
        raise _missing(f"There is no environment {environment_id}.")
    try:
        attempt = await environment_references.start_reference(session, environment_id)
    except EnvironmentReferenceError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    newest = await environment_versions.latest_version(session, environment_id)
    return await _reference_out(session, attempt, newest.id if newest else None)


@router.get(
    "/lab/environments/{environment_id}/references",
    response_model=list[ReferenceOut],
    responses=_NOT_FOUND,
)
async def list_references(environment_id: EnvironmentId, session: SessionDep) -> list[ReferenceOut]:
    """Every attempt to make a picture for this environment, newest first."""
    if await environment_library.get_environment(session, environment_id) is None:
        raise _missing(f"There is no environment {environment_id}.")
    newest = await environment_versions.latest_version(session, environment_id)
    attempts = await environment_references.list_references(session, environment_id)
    return [
        await _reference_out(session, attempt, newest.id if newest else None)
        for attempt in attempts
    ]


class ChooseReferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: Id


@router.post(
    "/lab/environments/references/{reference_id}/choose",
    response_model=ReferenceOut,
    responses={404: {"model": ErrorResponse, "description": "No attempt has this id."}, **_INVALID},
)
async def choose_reference(
    reference_id: ReferenceId, body: ChooseReferenceIn, session: SessionDep
) -> ReferenceOut:
    """Makes one candidate the canonical picture of the version this attempt was made for. It
    replaces a picture chosen earlier. Only the newest version can be changed.
    """
    attempt = await session.get(EnvironmentReference, reference_id)
    if attempt is None:
        raise _missing(f"There is no reference {reference_id}.")
    try:
        await environment_references.choose(session, reference_id, body.candidate_id)
    except EnvironmentReferenceError as exc:
        raise _unprocessable(str(exc)) from exc
    newest = await environment_versions.latest_version(session, attempt.environment_id)
    return await _reference_out(session, attempt, newest.id if newest else None)
