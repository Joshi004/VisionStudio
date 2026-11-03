"""`/api/projects/{project_id}/graphic-theme`: the graphics theme stage of a continuous explainer
(EXG-002).

- `POST .../run` starts the `write_graphic_theme` job: one model call writes the palette, the
  accent, the background style, the motion, the mood and the reason. The body may hold
  `feedback`, the owner's note on the newest theme.
- `GET ...` answers everything the board panel shows for the stage in one call: the newest
  version, the list of versions, the newest job and why the newest version is out of date.
  "Out of date" is worked out on every read.
- `GET .../versions/{version}` answers one older (or the newest) version.

The rows and the job are made by `app/services/graphic_theme.py`. The answers never return ORM
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
from app.db.models import GraphicTheme, Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import graphic_theme as graphic_theme_service
from app.services import graphics_resolve, user_feedback

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or version."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Not a continuous explainer with graphics on, the Story Bible is missing, "
        "or the note cannot be used.",
    }
}

Source = Literal["ai", "manual"]
Palette = Literal["dark", "light"]
Background = Literal["solid", "gradient", "grid", "glow"]
Motion = Literal["snappy", "smooth", "calm"]


# --- What the theme holds --------------------------------------------------------------------


class GraphicThemeLookOut(BaseModel):
    palette: Palette
    # The accent that is used: the model's, or the palette's default when it could not be read.
    accent: str
    background: Background
    motion: Motion
    mood: str


class GraphicThemeContent(BaseModel):
    theme: GraphicThemeLookOut
    reason: str
    # Why the model's accent was replaced, one sentence each. Empty when it was kept.
    notes: list[str]


class GraphicThemeColoursOut(BaseModel):
    """The colours the graphics are drawn with, from the palette and the accent."""

    background: str
    surface: str
    text: str
    muted: str
    accent: str
    positive: str
    negative: str
    number: str


class GraphicThemeVersionOut(BaseModel):
    version: int
    source: Source
    job_id: int | None
    created_at: datetime
    # The owner's note this version was made with, or None.
    feedback: str | None


class GraphicThemeOut(GraphicThemeVersionOut):
    id: int
    content: GraphicThemeContent
    colours: GraphicThemeColoursOut


class GraphicThemeJobOut(BaseModel):
    """The newest `write_graphic_theme` job of the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class GraphicThemeState(BaseModel):
    latest: GraphicThemeOut | None
    versions: list[GraphicThemeVersionOut]
    job: GraphicThemeJobOut | None
    # Only the newest version is judged. False when there is no version.
    out_of_date: bool
    # One sentence for each thing the newest version was built from that has changed.
    reasons: list[str]
    # Why no theme can be written yet (or at all for this project), or None.
    blocked_reason: str | None
    # False for a story and for an explainer with graphics off.
    wanted: bool


class GraphicThemeRun(BaseModel):
    job_id: int


class GraphicThemeRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The owner's note on the newest theme. `user_feedback.clean` checks it again.
    feedback: str | None = Field(default=None, max_length=user_feedback.MAX_CHARS)


# --- Mapping ---------------------------------------------------------------------------------


def _version_out(row: GraphicTheme) -> GraphicThemeVersionOut:
    return GraphicThemeVersionOut(
        version=row.version,
        source=cast(Source, row.source),
        job_id=row.job_id,
        created_at=row.created_at,
        feedback=user_feedback.text_of(row.inputs),
    )


def _colours(content: GraphicThemeContent) -> GraphicThemeColoursOut:
    # The stored accent was already resolved, so this gives no second note.
    colours, _notes = graphics_resolve.theme_for(content.theme.model_dump())
    return GraphicThemeColoursOut(
        **{key: colours[key] for key in GraphicThemeColoursOut.model_fields}
    )


def _theme_out(row: GraphicTheme) -> GraphicThemeOut:
    content = GraphicThemeContent.model_validate(row.content)
    return GraphicThemeOut(
        **_version_out(row).model_dump(),
        id=row.id,
        content=content,
        colours=_colours(content),
    )


async def _state(session: AsyncSession, project: Project) -> GraphicThemeState:
    state = await graphic_theme_service.state(session, project)
    job = state.job
    return GraphicThemeState(
        latest=_theme_out(state.latest) if state.latest is not None else None,
        versions=[_version_out(row) for row in state.versions],
        job=(
            GraphicThemeJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        out_of_date=state.out_of_date,
        reasons=state.reasons,
        blocked_reason=state.blocked_reason,
        wanted=state.wanted,
    )


# --- Endpoints -------------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/graphic-theme/run",
    response_model=GraphicThemeRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_graphic_theme(
    project_id: int, session: SessionDep, body: GraphicThemeRunIn | None = None
) -> GraphicThemeRun:
    """Starts the job that writes the graphics theme. If one is already waiting or running for
    the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await graphic_theme_service.start_run(
            session, project, feedback=body.feedback if body is not None else None
        )
    except graphic_theme_service.GraphicThemeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return GraphicThemeRun(job_id=job.id)


@router.get(
    "/projects/{project_id}/graphic-theme",
    response_model=GraphicThemeState,
    responses=_NOT_FOUND,
)
async def get_graphic_theme(project_id: int, session: SessionDep) -> GraphicThemeState:
    return await _state(session, await load_project(session, project_id))


@router.get(
    "/projects/{project_id}/graphic-theme/versions/{version}",
    response_model=GraphicThemeOut,
    responses=_NOT_FOUND,
)
async def get_graphic_theme_version(
    project_id: int,
    version: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> GraphicThemeOut:
    project = await load_project(session, project_id)
    row = await graphic_theme_service.get_version(session, project.id, version)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"The project has no graphics look version {version}."
        )
    return _theme_out(row)
