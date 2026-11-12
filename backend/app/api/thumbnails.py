"""`/api/projects/{project_id}/thumbnails` and `.../thumbnail-concepts`: the optional thumbnail
flow of a project, for a story and for an explainer.

1. `POST .../thumbnail-concepts/run` starts the `write_thumbnail_concepts` job: the story model
   writes four different thumbnail concepts from the script. The body may hold `feedback`, the
   owner's note on the newest version.
2. `PUT .../thumbnail-concepts` saves the owner's edit of the four concepts as a new version.
3. `POST .../thumbnails` makes one picture for each chosen concept of a version (GPU work).
4. `PUT .../thumbnails/{id}/headline` changes a headline and draws the picture again (no GPU).
5. `POST .../thumbnails/{id}/choose` makes a finished thumbnail the project's chosen one.
6. `GET .../thumbnails` answers everything the board panel shows in one call: the newest
   concepts, their versions, the people who may appear, the newest job, why the ideas are out of
   date, and every thumbnail. "Out of date" is worked out on every read.

The rows and jobs are made by `app/services/thumbnail_concepts.py` and
`app/services/thumbnails.py`. The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Job, Project, ThumbnailConcepts
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import thumbnail_concept_writer as writer
from app.services import thumbnail_concepts as concepts_service
from app.services import thumbnails as thumbnails_service
from app.services import user_feedback
from app.services.storage import media_url

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The Story Bible is missing, the ideas or the note cannot be used, or "
        "the thumbnail cannot be made.",
    }
}

Source = Literal["ai", "manual"]
TextArea = Literal[
    "left", "right", "top", "bottom", "top_left", "top_right", "bottom_left", "bottom_right"
]


# --- What the concepts hold ------------------------------------------------------------------


class PersonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=100)
    look: str = Field(max_length=100)
    expression: str = Field(max_length=500)
    pose: str = Field(max_length=500)


class ConceptIn(BaseModel):
    """One concept as the owner saves it. The service checks it again with the model's rules."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=500)
    idea: str = Field(max_length=2000)
    composition: str = Field(max_length=2000)
    background: str = Field(max_length=2000)
    mood: str = Field(max_length=500)
    headline: str = Field(max_length=500)
    text_area: TextArea
    people: list[PersonIn] = Field(max_length=writer.MAX_PEOPLE)
    # The id of the place that is the setting, or None. The service checks it again.
    environment: str | None = Field(default=None, max_length=100)
    people_reason: str = Field(max_length=1000)


class ConceptsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concepts: list[ConceptIn] = Field(
        min_length=writer.CONCEPT_COUNT, max_length=writer.CONCEPT_COUNT
    )


class PersonOut(BaseModel):
    id: str
    look: str
    expression: str
    pose: str


class ConceptOut(BaseModel):
    label: str
    idea: str
    composition: str
    background: str
    mood: str
    headline: str
    text_area: TextArea
    people: list[PersonOut]
    # The id of the place that is the setting. None for none, and for ideas made before places.
    environment: str | None = None
    people_reason: str


class ConceptsContent(BaseModel):
    concepts: list[ConceptOut]


class ThumbnailLookOut(BaseModel):
    slug: str
    description: str


class CastOptionOut(BaseModel):
    """A person who may appear, with the looks the owner may give them."""

    id: str
    name: str
    about: str
    looks: list[ThumbnailLookOut]


class PlaceOptionOut(BaseModel):
    """A place that may be the setting of a thumbnail."""

    id: str
    name: str


class ConceptsVersionOut(BaseModel):
    version: int
    source: Source
    job_id: int | None
    created_at: datetime
    # The owner's note this version was made with, or None.
    feedback: str | None


class ConceptsOut(ConceptsVersionOut):
    id: int
    content: ConceptsContent


class ThumbnailJobOut(BaseModel):
    """A job's status, whatever it is."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class IdeasState(BaseModel):
    latest: ConceptsOut | None
    versions: list[ConceptsVersionOut]
    job: ThumbnailJobOut | None
    # Only the newest version is judged. False when there is no version.
    out_of_date: bool
    reasons: list[str]
    # Why no ideas can be written yet, or None.
    blocked_reason: str | None
    cast: list[CastOptionOut]
    # The places that may be the setting now. Empty for an explainer.
    places: list[PlaceOptionOut]


# --- What a thumbnail holds ------------------------------------------------------------------


class ThumbnailOut(BaseModel):
    id: int
    concept_version: int
    concept_index: int
    headline: str
    text_area: TextArea
    chosen: bool
    # The finished picture with the headline drawn on it, or None until it exists.
    url: str | None
    width: int | None
    height: int | None
    # Whether the image model's picture is stored. False while it is still being made, and
    # also when the picture failed.
    has_picture: bool
    created_at: datetime
    # The job that makes the picture; None when it is gone.
    job: ThumbnailJobOut | None
    error: str | None
    # Why the ideas it was made from are out of date. Empty when they are current.
    reasons: list[str]


class ThumbnailsState(BaseModel):
    ideas: IdeasState
    thumbnails: list[ThumbnailOut]
    # The size of a finished thumbnail of this project.
    width: int
    height: int


class ThumbnailRunOut(BaseModel):
    job_id: int


class ThumbnailRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The owner's note on the newest version. `user_feedback.clean` checks it again.
    feedback: str | None = Field(default=None, max_length=user_feedback.MAX_CHARS)


class MakeThumbnailsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_version: int = Field(ge=1, le=_MAX_INT)
    # The numbers of the chosen concepts of that version, from 0.
    indexes: list[int] = Field(min_length=1, max_length=writer.CONCEPT_COUNT)


class ThumbnailHeadlineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(max_length=500)


class ThumbnailChooseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chosen: bool = True


# --- Mapping ---------------------------------------------------------------------------------


def _job_out(job: Job | None) -> ThumbnailJobOut | None:
    if job is None:
        return None
    return ThumbnailJobOut(
        id=job.id, status=cast(JobStatus, job.status), phase=job.phase, error=job.error
    )


def _version_out(row: ThumbnailConcepts) -> ConceptsVersionOut:
    return ConceptsVersionOut(
        version=row.version,
        source=cast(Source, row.source),
        job_id=row.job_id,
        created_at=row.created_at,
        feedback=user_feedback.text_of(row.inputs),
    )


def _concepts_out(row: ThumbnailConcepts) -> ConceptsOut:
    return ConceptsOut(
        **_version_out(row).model_dump(),
        id=row.id,
        content=ConceptsContent.model_validate(row.content),
    )


def _ideas_out(state: concepts_service.ConceptsState) -> IdeasState:
    return IdeasState(
        latest=_concepts_out(state.latest) if state.latest is not None else None,
        versions=[_version_out(row) for row in state.versions],
        job=_job_out(state.job),
        out_of_date=state.out_of_date,
        reasons=state.reasons,
        blocked_reason=state.blocked_reason,
        cast=[
            CastOptionOut(
                id=option.id,
                name=option.name,
                about=option.about,
                looks=[
                    ThumbnailLookOut(slug=look.slug, description=look.description)
                    for look in option.looks
                ],
            )
            for option in state.cast
        ],
        places=[PlaceOptionOut(id=place.id, name=place.name) for place in state.places],
    )


async def _state(session: AsyncSession, project: Project) -> ThumbnailsState:
    state = await thumbnails_service.state(session, project)
    return ThumbnailsState(
        ideas=_ideas_out(state.concepts),
        thumbnails=[
            ThumbnailOut(
                id=entry.row.id,
                concept_version=entry.row.concept_version,
                concept_index=entry.row.concept_index,
                headline=entry.row.headline,
                text_area=cast(TextArea, entry.row.text_area),
                chosen=entry.row.chosen,
                url=media_url(entry.row.path) if entry.row.path is not None else None,
                width=entry.row.width,
                height=entry.row.height,
                has_picture=entry.row.background_image_id is not None,
                created_at=entry.row.created_at,
                job=_job_out(entry.job),
                error=entry.error,
                reasons=entry.reasons,
            )
            for entry in state.thumbnails
        ],
        width=state.width,
        height=state.height,
    )


# --- Endpoints -------------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/thumbnails",
    response_model=ThumbnailsState,
    responses=_NOT_FOUND,
)
async def get_thumbnails(project_id: int, session: SessionDep) -> ThumbnailsState:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/thumbnail-concepts/run",
    response_model=ThumbnailRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_thumbnail_concepts(
    project_id: int, session: SessionDep, body: ThumbnailRunIn | None = None
) -> ThumbnailRunOut:
    """Starts the job that writes the four thumbnail concepts. If one is already waiting or
    running for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await concepts_service.start_run(
            session, project, feedback=body.feedback if body is not None else None
        )
    except concepts_service.ThumbnailConceptsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return ThumbnailRunOut(job_id=job.id)


@router.put(
    "/projects/{project_id}/thumbnail-concepts",
    response_model=ThumbnailsState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_thumbnail_concepts(
    project_id: int, body: ConceptsIn, session: SessionDep
) -> ThumbnailsState:
    """Saves the owner's edit of the four concepts as the next version."""
    project = await load_project(session, project_id)
    try:
        await concepts_service.save_manual(
            session, project, [concept.model_dump() for concept in body.concepts]
        )
    except concepts_service.ThumbnailConceptsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _state(session, project)


@router.post(
    "/projects/{project_id}/thumbnails",
    response_model=ThumbnailsState,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def make_thumbnails(
    project_id: int, body: MakeThumbnailsIn, session: SessionDep
) -> ThumbnailsState:
    """Starts one picture for each chosen concept of a version."""
    project = await load_project(session, project_id)
    try:
        await thumbnails_service.start_images(session, project, body.concept_version, body.indexes)
    except thumbnails_service.ThumbnailError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return await _state(session, project)


@router.put(
    "/projects/{project_id}/thumbnails/{thumbnail_id}/headline",
    response_model=ThumbnailsState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def change_headline(
    project_id: int, thumbnail_id: int, body: ThumbnailHeadlineIn, session: SessionDep
) -> ThumbnailsState:
    """Changes a headline and draws the picture again. No GPU work."""
    project = await load_project(session, project_id)
    try:
        await thumbnails_service.set_headline(session, project, thumbnail_id, body.headline)
    except thumbnails_service.ThumbnailError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _state(session, project)


@router.post(
    "/projects/{project_id}/thumbnails/{thumbnail_id}/choose",
    response_model=ThumbnailsState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def choose_thumbnail(
    project_id: int, thumbnail_id: int, session: SessionDep, body: ThumbnailChooseIn | None = None
) -> ThumbnailsState:
    """Makes a finished thumbnail the project's chosen one (`chosen` false clears the choice)."""
    project = await load_project(session, project_id)
    try:
        await thumbnails_service.set_chosen(
            session, project, thumbnail_id, body.chosen if body is not None else True
        )
    except thumbnails_service.ThumbnailError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _state(session, project)
