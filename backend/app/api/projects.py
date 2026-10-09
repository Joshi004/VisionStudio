"""`/api/projects`: projects, their settings and guidelines, the voiceover and the script.

Every edit is a PATCH on the project, so all the rules sit in one function
(`app/services/projects.py`). The answers never return ORM objects, and the
database path of the voiceover is never returned: only its `/media/` URL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StrictFloat, StrictInt, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.db.models import Asset, Project
from app.db.session import SessionDep
from app.services import projects as projects_service
from app.services import voiceover as voiceover_service
from app.services.storage import media_url
from app.services.video_models import VideoModel

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
    min_scene_seconds: StrictFloat | None = None
    max_scene_seconds: StrictFloat | None = None
    clip_sound_volume: StrictFloat | None = None
    style_prefix: StrictStr | None = None
    prompt_suffix: StrictStr | None = None
    negative_prompt: StrictStr | None = None
    cut_instructions: StrictStr | None = None
    description_instructions: StrictStr | None = None
    script_text: StrictStr | None = None
    # `null` means "use the app's default video model".
    video_model: StrictStr | None = None


class VoiceoverOut(BaseModel):
    asset_id: int
    url: str
    mime: str
    size_bytes: int
    duration_s: float | None
    sha256: str
    created_at: datetime


class ProjectSummary(BaseModel):
    id: int
    name: str
    orientation: Orientation
    created_at: datetime
    voiceover_duration_s: float | None
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
    min_scene_seconds: float
    max_scene_seconds: float
    clip_sound_volume: float
    style_prefix: str | None
    prompt_suffix: str | None
    negative_prompt: str | None
    cut_instructions: str | None
    description_instructions: str | None
    script_text: str | None
    # The project's own choice (`ltx-2.3` or `ltx-2.5`), or null to use the app's default.
    video_model: VideoModel | None
    # The app's default video model, so the page can say what "default" means right now.
    default_video_model: VideoModel
    voiceover: VoiceoverOut | None


def _orientation(project: Project) -> Orientation:
    # The database CHECK constraint keeps this to the two allowed values.
    return cast(Orientation, project.orientation)


def _voiceover_out(asset: Asset | None) -> VoiceoverOut | None:
    if asset is None:
        return None
    return VoiceoverOut(
        asset_id=asset.id,
        url=media_url(asset.path),
        mime=asset.mime,
        size_bytes=asset.size_bytes,
        duration_s=asset.duration_s,
        sha256=asset.sha256,
        created_at=asset.created_at,
    )


def _video_model(value: str | None) -> VideoModel | None:
    # The database CHECK constraint keeps a stored value to the known models.
    return cast(VideoModel, value) if value is not None else None


def _detail(
    project: Project, voiceover: Asset | None, default_video_model: VideoModel
) -> ProjectDetail:
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
        min_scene_seconds=project.min_scene_seconds,
        max_scene_seconds=project.max_scene_seconds,
        clip_sound_volume=project.clip_sound_volume,
        style_prefix=project.style_prefix,
        prompt_suffix=project.prompt_suffix,
        negative_prompt=project.negative_prompt,
        cut_instructions=project.cut_instructions,
        description_instructions=project.description_instructions,
        script_text=project.script_text,
        video_model=_video_model(project.video_model),
        default_video_model=default_video_model,
        voiceover=_voiceover_out(voiceover),
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
    rows = await projects_service.list_projects(session)
    return [
        ProjectSummary(
            id=project.id,
            name=project.name,
            orientation=_orientation(project),
            created_at=project.created_at,
            voiceover_duration_s=None if voiceover is None else voiceover.duration_s,
            has_script=project.script_text is not None,
        )
        for project, voiceover in rows
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
    return _detail(project, None, await projects_service.default_video_model(session))


@router.get("/projects/{project_id}", response_model=ProjectDetail, responses=_NOT_FOUND)
async def get_project(project_id: int, session: SessionDep) -> ProjectDetail:
    project = await load_project(session, project_id)
    voiceover = await projects_service.get_voiceover(session, project)
    return _detail(project, voiceover, await projects_service.default_video_model(session))


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectDetail,
    responses={**_NOT_FOUND, **_INVALID},
)
async def update_project(
    project_id: int, body: ProjectUpdate, session: SessionDep
) -> ProjectDetail:
    """Changes the fields that are sent: settings, guidelines and the script."""
    project = await load_project(session, project_id)
    try:
        project = await projects_service.update_project(
            session, project, body.model_dump(exclude_unset=True)
        )
    except projects_service.ProjectValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    voiceover = await projects_service.get_voiceover(session, project)
    return _detail(project, voiceover, await projects_service.default_video_model(session))


_VOICEOVER_UPLOAD_RESPONSES = {
    **_NOT_FOUND,
    413: {"model": ErrorResponse, "description": "The file is larger than the limit."},
    415: {
        "model": ErrorResponse,
        "description": "The body is not sent as application/octet-stream.",
    },
    422: {"model": ErrorResponse, "description": "The file is not an acceptable voiceover."},
}

# The file is the request body itself, not a multipart form (no extra library needed).
_VOICEOVER_UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


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


@router.post(
    "/projects/{project_id}/voiceover",
    response_model=ProjectDetail,
    status_code=status.HTTP_201_CREATED,
    responses=_VOICEOVER_UPLOAD_RESPONSES,
    openapi_extra=_VOICEOVER_UPLOAD_BODY,
)
async def upload_voiceover(project_id: int, request: Request, session: SessionDep) -> ProjectDetail:
    """Stores the voiceover (WAV, MP3, M4A or FLAC) sent as the raw request body.

    A new upload becomes the project's voiceover. The previous file is kept.
    """
    project = await load_project(session, project_id)

    require_octet_stream(request)

    # End the read transaction: none may stay open while the file is received.
    await session.commit()

    try:
        asset = await voiceover_service.upload_voiceover(
            session, project.id, request.stream(), content_length(request)
        )
    except voiceover_service.VoiceoverRejected as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return _detail(project, asset, await projects_service.default_video_model(session))
