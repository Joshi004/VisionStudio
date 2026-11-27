"""`/api/projects/{project_id}/footage-marks`: the words of the story that real footage is shown
over (FTG-002).

- `GET ...` answers the marks as they stand in the story now, the newest job, and whether the
  project has footage at all. Marks that moved with an edit of the story, and marks whose words
  are gone (`words_changed`), are worked out on every read.
- `POST .../marks` marks words of the saved story as footage, with an optional note and kind.
- `PATCH .../{mark_id}` changes a mark's note or kind, or keeps or drops a proposal of GLM.
- `DELETE .../{mark_id}` removes one of the owner's marks.
- `POST .../suggest` starts the `suggest_footage_marks` job: one model call proposes more marks.

Every change is a new version of the mark list (`source` `manual`; the job's is `ai`). Every
route answers 422 for a project without footage, and 409 while the model is proposing. The rows
and the job are made by `app/services/footage_marks.py`. The answers never return ORM objects.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import footage_marks as marks_service

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or footage mark."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The project has no footage, the story is not saved, or the request "
        "breaks a rule.",
    },
    409: {"model": ErrorResponse, "description": "GLM is proposing footage."},
}

Origin = Literal["owner", "glm"]
Kind = Literal["any", "video", "photo", "page"]


# --- What the marks hold ---------------------------------------------------------------------


class FootageMarkOut(BaseModel):
    id: str
    origin: Origin
    # Character positions in the project's `script_text`; `end` is not included.
    start: int
    end: int
    text: str
    # One line on what the viewer should see. May be empty on an owner's mark.
    note: str
    kind_hint: Kind
    # GLM's reason; empty for the owner's marks.
    reason: str
    # True for the owner's marks. For a proposal: null until the owner decides, then true (kept)
    # or false (dropped).
    kept: bool | None
    # The words of the mark are no longer in the story, or no longer stand alone there.
    words_changed: bool


class FootageMarksJobOut(BaseModel):
    """The newest `suggest_footage_marks` job of the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class FootageMarksState(BaseModel):
    # The newest mark list version, or null when there is none.
    version: int | None
    marks: list[FootageMarkOut]
    job: FootageMarksJobOut | None
    # Why no footage can be marked or proposed now (or at all for this project), or null.
    blocked_reason: str | None
    # False for a story, a lines explainer and a project with footage off.
    wanted: bool
    # True once GLM has been asked, and answered, for this project.
    has_ai_version: bool


class FootageMarksRun(BaseModel):
    job_id: int


# --- What a change sends ---------------------------------------------------------------------


class FootageMarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: StrictInt = Field(ge=0, le=_MAX_INT)
    end: StrictInt = Field(ge=0, le=_MAX_INT)
    # The words as the owner saw them in the saved story: a stale page is refused.
    text: StrictStr = Field(max_length=500)
    note: StrictStr = Field(default="", max_length=1000)
    # Left out: "any".
    kind_hint: Kind | None = None


class FootageMarkEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Left out: not changed.
    note: StrictStr | None = Field(default=None, max_length=1000)
    kind_hint: Kind | None = None
    # Only for a proposal of GLM.
    kept: StrictBool | None = None


# --- Mapping ---------------------------------------------------------------------------------


async def _state(session: AsyncSession, project: Project) -> FootageMarksState:
    state = await marks_service.state(session, project)
    job = state.job
    return FootageMarksState(
        version=state.latest.version if state.latest is not None else None,
        marks=[FootageMarkOut(**mark) for mark in state.marks],
        job=(
            FootageMarksJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        blocked_reason=state.blocked_reason,
        wanted=state.wanted,
        has_ai_version=state.has_ai_version,
    )


def _refusal(exc: marks_service.FootageMarksError) -> HTTPException:
    if isinstance(exc, marks_service.MarkNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, marks_service.BusyError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


# --- Endpoints -------------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/footage-marks",
    response_model=FootageMarksState,
    responses=_NOT_FOUND,
)
async def get_footage_marks(project_id: int, session: SessionDep) -> FootageMarksState:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/footage-marks/marks",
    response_model=FootageMarksState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def mark_footage(
    project_id: int, body: FootageMarkIn, session: SessionDep
) -> FootageMarksState:
    """Marks words of the saved story as footage, as a new version written by the owner."""
    project = await load_project(session, project_id)
    try:
        await marks_service.add_mark(
            session,
            project,
            start=body.start,
            end=body.end,
            text=body.text,
            note=body.note,
            kind_hint=body.kind_hint,
        )
    except marks_service.FootageMarksError as exc:
        raise _refusal(exc) from exc
    return await _state(session, project)


@router.post(
    "/projects/{project_id}/footage-marks/suggest",
    response_model=FootageMarksRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def suggest_footage_marks(project_id: int, session: SessionDep) -> FootageMarksRun:
    """Starts the job that asks GLM for more footage marks. If one is already waiting or running
    for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await marks_service.start_suggest(session, project)
    except marks_service.FootageMarksError as exc:
        raise _refusal(exc) from exc
    dispatcher.nudge()
    return FootageMarksRun(job_id=job.id)


@router.patch(
    "/projects/{project_id}/footage-marks/{mark_id}",
    response_model=FootageMarksState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def edit_footage_mark(
    project_id: int,
    mark_id: Annotated[str, Path(max_length=50)],
    body: FootageMarkEditIn,
    session: SessionDep,
) -> FootageMarksState:
    """Changes a mark's note or kind, or keeps or drops a proposal of GLM."""
    project = await load_project(session, project_id)
    try:
        await marks_service.update_mark(
            session,
            project,
            mark_id,
            note=body.note,
            kind_hint=body.kind_hint,
            kept=body.kept,
        )
    except marks_service.FootageMarksError as exc:
        raise _refusal(exc) from exc
    return await _state(session, project)


@router.delete(
    "/projects/{project_id}/footage-marks/{mark_id}",
    response_model=FootageMarksState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def remove_footage_mark(
    project_id: int,
    mark_id: Annotated[str, Path(max_length=50)],
    session: SessionDep,
) -> FootageMarksState:
    """Removes one of the owner's marks. A proposal of GLM is dropped instead (PATCH)."""
    project = await load_project(session, project_id)
    try:
        await marks_service.remove_mark(session, project, mark_id)
    except marks_service.FootageMarksError as exc:
        raise _refusal(exc) from exc
    return await _state(session, project)
