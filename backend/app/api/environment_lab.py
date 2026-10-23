"""`/api/lab/environments`: the environment library of the Character lab (PHASE-012).

A `library_environment` is a reusable place: a profile and one canonical reference picture per
version. It belongs to no project. A story project links each discovered environment to one and
pins a version of it (`/api/projects/{id}/environment-links`, PHASE-013); `GET /{id}/projects`
lists the projects that use an environment, `POST /{id}/adopt` moves the pins of chosen
projects to a version of it (PHASE-042), and an environment the pipeline made for a project
carries its `origin` and the `definition` the Environment Definition stage wrote.

- Every change of the profile adds an immutable version (`environment_versions`);
  `GET /{id}/versions` lists them, newest first, read-only. Each version has its own canonical
  picture, which an edit never carries forward, and says which projects pin it.
- `POST /{id}/references` starts an attempt for the newest version: a language model writes the
  prompt, then four 16:9 candidate pictures are made. `POST /references/{id}/choose` makes one
  the canonical picture of the version the attempt was made for. Only the newest version's
  picture can be chosen or replaced, and not one that a project pins and that already has its
  picture.

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

from app.api.environment_definitions import EnvironmentDefinitionOut
from app.api.errors import ErrorResponse
from app.api.jobs import JobSummary, job_summary
from app.api.library_adoption import AdoptIn
from app.db.models import (
    EnvironmentReference,
    EnvironmentState,
    EnvironmentView,
    Job,
    LabImage,
    LabRun,
    LibraryEnvironment,
    LibraryEnvironmentVersion,
    Project,
)
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import (
    environment_library,
    environment_links,
    environment_references,
    environment_versions,
    image_lab,
    library_adoption,
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


class EnvironmentOriginOut(BaseModel):
    """The story project and discovered environment a library environment was made from."""

    project_id: int
    project_name: str
    discovery_id: str


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
    # True when the newest version is pinned by a project and already has its picture: that
    # picture cannot be replaced. Edit the environment to make a version with no picture.
    picture_locked: bool
    # Set only for an environment the pipeline made from a project's discovered environment
    # (PHASE-013). None for an environment made in the lab.
    origin: EnvironmentOriginOut | None
    # The newest structured definition the Environment Definition stage wrote (PHASE-013),
    # read-only. None until one is written.
    definition: EnvironmentDefinitionOut | None


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
    origin_project = (
        await session.get(Project, environment.origin_project_id)
        if environment.origin_project_id is not None
        else None
    )
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
        picture_locked=(
            await environment_references.is_frozen(session, newest) if newest is not None else False
        ),
        origin=(
            EnvironmentOriginOut(
                project_id=origin_project.id,
                project_name=origin_project.name,
                discovery_id=environment.origin_discovery_id,
            )
            if origin_project is not None and environment.origin_discovery_id is not None
            else None
        ),
        definition=(
            EnvironmentDefinitionOut.model_validate(environment.definition)
            if environment.definition is not None
            else None
        ),
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


class PinnedByOut(BaseModel):
    """A story project that pins a version."""

    project_id: int
    project_name: str
    discovery_id: str


class StatePictureOut(BaseModel):
    """The picture of one environment state as a version froze it (PHASE-017)."""

    slug: str
    name: str
    image: PictureOut | None


class ViewPictureOut(BaseModel):
    """The picture of one environment view as a version froze it (PHASE-052)."""

    slug: str
    name: str
    image: PictureOut | None
    # The view's pictures in the environment's states (PHASE-053), by state slug.
    states: list[StatePictureOut]


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
    # The structured definition at this version (PHASE-013). None when it had none.
    definition: EnvironmentDefinitionOut | None
    # The job that wrote the definition, for a version the pipeline made. None for a version
    # made by hand.
    job_id: int | None
    # The story projects that pin this version.
    pinned_by: list[PinnedByOut]
    # The pictures of the environment's states (such as night) this version froze, by slug
    # (PHASE-017). Empty when there were none.
    states: list[StatePictureOut]
    # The pictures of the environment's views (PHASE-052) this version froze, by slug.
    views: list[ViewPictureOut]


@router.get(
    "/lab/environments/{environment_id}/versions",
    response_model=list[EnvironmentVersionOut],
    responses=_NOT_FOUND,
)
async def list_versions(
    environment_id: EnvironmentId, session: SessionDep
) -> list[EnvironmentVersionOut]:
    """Every version of this environment, newest first, each with what it changed, its own
    picture and the projects that pin it. A version is never edited: it is added when the
    profile changes.
    """
    if await environment_library.get_environment(session, environment_id) is None:
        raise _missing(f"There is no environment {environment_id}.")
    entries = await environment_versions.list_versions(session, environment_id)
    usages = await environment_links.used_by(session, environment_id)
    state_ids = {frozen["state_id"] for entry in entries for frozen in entry.version.states or []}
    for entry in entries:
        for frozen_view in entry.version.views or []:
            state_ids.update(frozen["state_id"] for frozen in frozen_view["states"])
    state_names: dict[int, str] = {}
    if state_ids:
        found = await session.execute(
            select(EnvironmentState).where(EnvironmentState.id.in_(state_ids))
        )
        state_names = {record.id: record.name for record in found.scalars()}
    view_ids = {frozen["view_id"] for entry in entries for frozen in entry.version.views or []}
    view_names: dict[int, str] = {}
    if view_ids:
        found_views = await session.execute(
            select(EnvironmentView).where(EnvironmentView.id.in_(view_ids))
        )
        view_names = {record.id: record.name for record in found_views.scalars()}
    return [
        EnvironmentVersionOut(
            id=entry.version.id,
            version=entry.version.version,
            created_at=entry.version.created_at,
            source=typing_cast(Literal["ai", "manual"], entry.version.source),
            changes=entry.changes,
            profile=EnvironmentProfileOut.model_validate(entry.version.profile),
            image=await _picture(session, entry.version.reference_image_id),
            definition=(
                EnvironmentDefinitionOut.model_validate(entry.version.definition)
                if entry.version.definition is not None
                else None
            ),
            job_id=entry.version.job_id,
            pinned_by=[
                PinnedByOut(
                    project_id=usage.link.project_id,
                    project_name=usage.project_name,
                    discovery_id=usage.link.discovery_id,
                )
                for usage in usages
                if usage.link.pinned_version == entry.version.version
            ],
            states=[
                StatePictureOut(
                    slug=frozen["slug"],
                    name=state_names.get(frozen["state_id"], frozen["slug"]),
                    image=await _picture(session, frozen["reference_image_id"]),
                )
                for frozen in entry.version.states or []
            ],
            views=[
                ViewPictureOut(
                    slug=frozen["slug"],
                    name=view_names.get(frozen["view_id"], frozen["slug"]),
                    image=await _picture(session, frozen["reference_image_id"]),
                    states=[
                        StatePictureOut(
                            slug=frozen_state["slug"],
                            name=state_names.get(frozen_state["state_id"], frozen_state["slug"]),
                            image=await _picture(session, frozen_state["reference_image_id"]),
                        )
                        for frozen_state in frozen["states"]
                    ],
                )
                for frozen in entry.version.views or []
            ],
        )
        for entry in entries
    ]


# --- An environment's states (read-only) ------------------------------------------------------


class EnvironmentStateOut(BaseModel):
    """A named state of a library environment, such as night (PHASE-016, PHASE-017)."""

    id: int
    slug: str
    name: str
    description: str
    source: Literal["ai", "manual"]
    created_at: datetime
    # The project whose resolution created it, when that project still exists.
    origin_project_id: int | None
    # The state's picture, an edit of the canonical one. None until it is made.
    image: PictureOut | None


@router.get(
    "/lab/environments/{environment_id}/states",
    response_model=list[EnvironmentStateOut],
    responses=_NOT_FOUND,
)
async def list_environment_states(
    environment_id: EnvironmentId, session: SessionDep
) -> list[EnvironmentStateOut]:
    """The named states of this environment, oldest first, each with its picture once it is
    made. Read-only: a story project's resolution creates them and makes their pictures.
    """
    if await environment_library.get_environment(session, environment_id) is None:
        raise _missing(f"There is no environment {environment_id}.")
    statement = (
        select(EnvironmentState)
        .where(EnvironmentState.environment_id == environment_id)
        .order_by(EnvironmentState.id)
        .execution_options(populate_existing=True)
    )
    records = (await session.execute(statement)).scalars().all()
    return [
        EnvironmentStateOut(
            id=record.id,
            slug=record.slug,
            name=record.name,
            description=record.description,
            source=typing_cast(Literal["ai", "manual"], record.source),
            created_at=record.created_at,
            origin_project_id=record.origin_project_id,
            image=await _picture(session, record.reference_image_id),
        )
        for record in records
    ]


# --- The projects that use an environment (read-only) --------------------------------------


class EnvironmentUsageOut(BaseModel):
    """One story project that uses the environment, and the version it pins."""

    project_id: int
    project_name: str
    # The project's discovered environment this one backs.
    discovery_id: str
    # `created`: the pipeline made the environment for the project. `mapped`: the user chose it.
    how: Literal["created", "mapped"]
    pinned_version: int
    # The environment's newest version, and whether it is later than the pinned one. The pin
    # does not move because of a lab edit.
    newest_version: int | None
    newer_version_available: bool
    # PHASE-042: the project has a rendered final video, so it is "complete".
    complete: bool
    # Ticked by default in the adoption dialog: not complete, behind, and able to adopt.
    preselected: bool
    # Why the project cannot adopt the newest version now (for example it has no picture), or
    # None.
    blocked_reason: str | None


async def _usage_out(session: AsyncSession, environment_id: int) -> list[EnvironmentUsageOut]:
    candidates = await library_adoption.candidates(session, "environment", environment_id)
    return [
        EnvironmentUsageOut(
            project_id=candidate.link.project_id,
            project_name=candidate.project_name,
            discovery_id=candidate.link.discovery_id,
            how=typing_cast(Literal["created", "mapped"], candidate.link.how),
            pinned_version=candidate.link.pinned_version,
            newest_version=candidate.newest_version,
            newer_version_available=candidate.newer_version_available,
            complete=candidate.complete,
            preselected=candidate.preselected,
            blocked_reason=candidate.blocked_reason,
        )
        for candidate in candidates
    ]


@router.get(
    "/lab/environments/{environment_id}/projects",
    response_model=list[EnvironmentUsageOut],
    responses=_NOT_FOUND,
)
async def list_environment_projects(
    environment_id: EnvironmentId, session: SessionDep
) -> list[EnvironmentUsageOut]:
    """The story projects that use this environment, each with the version it pins, whether
    it is complete (it has a final render) and whether it can adopt the newest version now.
    """
    if await environment_library.get_environment(session, environment_id) is None:
        raise _missing(f"There is no environment {environment_id}.")
    return await _usage_out(session, environment_id)


@router.post(
    "/lab/environments/{environment_id}/adopt",
    response_model=list[EnvironmentUsageOut],
    responses={**_NOT_FOUND, **_INVALID},
)
async def adopt_environment_version(
    environment_id: EnvironmentId, body: AdoptIn, session: SessionDep
) -> list[EnvironmentUsageOut]:
    """Moves the pins of the chosen projects to one version of this environment (PHASE-042),
    all or none. The version needs a picture. Nothing is made again: what depends on the
    environment goes out of date in each project, and that project's "Regenerate out-of-date"
    rebuilds it. Answers with the updated list of projects.
    """
    if await environment_library.get_environment(session, environment_id) is None:
        raise _missing(f"There is no environment {environment_id}.")
    try:
        await library_adoption.adopt_many(
            session, "environment", environment_id, body.version, body.project_ids
        )
    except library_adoption.AdoptionError as exc:
        raise _unprocessable(str(exc)) from exc
    return await _usage_out(session, environment_id)


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
    # True once an edit added a newer version, or when a project pins the version and it
    # already has its picture: the attempt is shown, but cannot be chosen from.
    frozen: bool
    # True for an attempt the story pipeline made (one candidate, taken as the picture by
    # itself); False for one made in the lab.
    from_project: bool
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
        frozen=(
            newest_id is None
            or attempt.version_id != newest_id
            or version is None
            or await environment_references.is_frozen(session, version)
        ),
        from_project=attempt.project_id is not None,
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
