"""`/api/projects`: projects, their sizes and their script text.

Every edit is a PATCH on the project, so all the rules sit in one function
(`app/services/projects.py`). The answers never return ORM objects.

`load_project`, `content_length` and `require_octet_stream` are shared by the lab
routers (the Image lab picks a project's frames, and every upload endpoint reads its
file as the raw request body).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.db.models import Project
from app.db.session import SessionDep
from app.services import projects as projects_service

router = APIRouter()

Orientation = Literal["landscape", "portrait"]

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_PROJECT_ID = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No project has this id."}}
_INVALID = {422: {"model": ErrorResponse, "description": "A value breaks a rule."}}


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    orientation: Orientation


class ProjectUpdate(BaseModel):
    """Only the fields that are sent are changed. The orientation cannot be changed."""

    model_config = ConfigDict(extra="forbid")

    name: StrictStr | None = None
    gen_width: StrictInt | None = None
    gen_height: StrictInt | None = None
    out_width: StrictInt | None = None
    out_height: StrictInt | None = None
    fps: StrictInt | None = None
    script_text: StrictStr | None = None


class ProjectSummary(BaseModel):
    id: int
    name: str
    orientation: Orientation
    created_at: datetime
    has_script: bool


class ProjectDetail(BaseModel):
    id: int
    name: str
    orientation: Orientation
    created_at: datetime
    gen_width: int
    gen_height: int
    out_width: int
    out_height: int
    fps: int
    script_text: str | None


def _orientation(project: Project) -> Orientation:
    # The database CHECK constraint keeps this to the two allowed values.
    return cast(Orientation, project.orientation)


def _detail(project: Project) -> ProjectDetail:
    return ProjectDetail(
        id=project.id,
        name=project.name,
        orientation=_orientation(project),
        created_at=project.created_at,
        gen_width=project.gen_width,
        gen_height=project.gen_height,
        out_width=project.out_width,
        out_height=project.out_height,
        fps=project.fps,
        script_text=project.script_text,
    )


async def load_project(session: AsyncSession, project_id: int) -> Project:
    """The project, or a 404 with a readable message."""
    project = None
    if 1 <= project_id <= _MAX_PROJECT_ID:
        project = await projects_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Project {project_id} does not exist.")
    return project


@router.get("/projects", response_model=list[ProjectSummary])
async def list_projects(session: SessionDep) -> list[ProjectSummary]:
    projects = await projects_service.list_projects(session)
    return [
        ProjectSummary(
            id=project.id,
            name=project.name,
            orientation=_orientation(project),
            created_at=project.created_at,
            has_script=project.script_text is not None,
        )
        for project in projects
    ]


@router.post(
    "/projects",
    response_model=ProjectDetail,
    status_code=status.HTTP_201_CREATED,
    responses=_INVALID,
)
async def create_project(body: ProjectCreate, session: SessionDep) -> ProjectDetail:
    try:
        project = await projects_service.create_project(session, body.name, body.orientation)
    except projects_service.ProjectValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _detail(project)


@router.get("/projects/{project_id}", response_model=ProjectDetail, responses=_NOT_FOUND)
async def get_project(project_id: int, session: SessionDep) -> ProjectDetail:
    return _detail(await load_project(session, project_id))


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectDetail,
    responses={**_NOT_FOUND, **_INVALID},
)
async def update_project(
    project_id: int, body: ProjectUpdate, session: SessionDep
) -> ProjectDetail:
    """Changes the fields that are sent: the name, the sizes, the frame rate and the script."""
    project = await load_project(session, project_id)
    try:
        project = await projects_service.update_project(
            session, project, body.model_dump(exclude_unset=True)
        )
    except projects_service.ProjectValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _detail(project)


def content_length(request: Request) -> int | None:
    value = request.headers.get("content-length", "")
    return int(value) if value.isascii() and value.isdigit() else None


def require_octet_stream(request: Request) -> None:
    """415 unless the file is sent as the raw body with the content type
    application/octet-stream. A web page on another site cannot send this type without a
    CORS preflight, which this API never answers. Shared by every upload endpoint.
    """
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/octet-stream":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Send the file as the request body with the content type application/octet-stream.",
        )
