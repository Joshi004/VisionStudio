"""`/api/projects`: projects, their sizes and their story text.

The story is stored in the `script_text` column. Every edit is a PATCH on the project, so all
the rules sit in one function (`app/services/projects.py`). A project's detail also carries the
story's estimated length (`app/services/story_length.py`). The answers never return ORM objects.

`load_project`, `content_length` and `require_octet_stream` are shared by the lab
routers (the Image lab picks a project's frames, and every upload endpoint reads its
file as the raw request body).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.db.models import Project
from app.db.session import SessionDep
from app.services import projects as projects_service
from app.services import review_points as review_points_service
from app.services import story_length as story_length_service
from app.services.review_points import ReviewPointKey

router = APIRouter()

Orientation = Literal["landscape", "portrait"]
SpeechMode = Literal["both", "no_dialogue", "no_narration"]
ProjectKind = Literal["story", "explainer"]
VoiceTrack = Literal["lines", "continuous"]

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_PROJECT_ID = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No project has this id."}}
_INVALID = {422: {"model": ErrorResponse, "description": "A value breaks a rule."}}


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    orientation: Orientation
    speech_mode: SpeechMode = "both"
    # `explainer` (EXPLAINER-002) needs a presenter from the Character Lab and may have a set from
    # the Environment Lab. Its speech mode is always `both`, whatever is sent.
    kind: ProjectKind = "story"
    presenter_character_id: StrictInt | None = None
    set_environment_id: StrictInt | None = None
    # Word-synced captions and callouts (EXPLAINER-007). Only an explainer keeps them.
    captions: StrictBool = True
    callouts: StrictBool = True
    # How an explainer's speech is made (FLOW-002). Left out, an explainer gets `continuous`. A
    # story is always `lines`. The delivery text is for a continuous explainer only.
    voice_track: VoiceTrack | None = None
    presenter_delivery: StrictStr | None = None


class ProjectUpdate(BaseModel):
    """Only the fields that are sent are changed. The orientation, the speech mode, the kind and
    the voice track cannot be changed.
    """

    model_config = ConfigDict(extra="forbid")

    name: StrictStr | None = None
    gen_width: StrictInt | None = None
    gen_height: StrictInt | None = None
    out_width: StrictInt | None = None
    out_height: StrictInt | None = None
    fps: StrictInt | None = None
    script_text: StrictStr | None = None
    # The review points the pipeline stops at (PHASE-041). The whole list is sent.
    review_points: list[ReviewPointKey] | None = None
    # Whether the story gets planned music (MUSIC-006). Can be changed at any time.
    music_enabled: StrictBool | None = None
    # Whether a render includes the beds and point sounds (MUSIC-012). Can be changed at any time.
    ambience_enabled: StrictBool | None = None
    # Whether an explainer's render draws captions, and callouts (EXPLAINER-007). Only an
    # explainer can change them, at any time.
    captions: StrictBool | None = None
    callouts: StrictBool | None = None
    # The text that steers a continuous explainer's voice (FLOW-002). Null or blank clears it.
    presenter_delivery: StrictStr | None = None


class ProjectSummary(BaseModel):
    id: int
    name: str
    orientation: Orientation
    created_at: datetime
    has_script: bool


class StoryLengthOut(BaseModel):
    """The story's size and estimated length, and the pace and limit the estimate used."""

    word_count: int
    estimated_seconds: int
    words_per_minute: int
    limit_seconds: int
    over_limit: bool


class ProjectDetail(BaseModel):
    id: int
    name: str
    orientation: Orientation
    speech_mode: SpeechMode
    kind: ProjectKind
    created_at: datetime
    gen_width: int
    gen_height: int
    out_width: int
    out_height: int
    fps: int
    script_text: str | None
    # The review points the project has enabled, in the order of the pipeline. None by default.
    review_points: list[ReviewPointKey]
    # Whether the story gets planned music. On by default.
    music_enabled: bool
    # Whether a render includes the beds and point sounds. On by default.
    ambience_enabled: bool
    # Whether an explainer gets word-synced captions, and callouts. On by default. A story
    # never reads them.
    captions: bool
    callouts: bool
    # How the speech is made: `lines` for a story and for an explainer made before FLOW-002.
    voice_track: VoiceTrack
    # The owner's voice text for a continuous explainer. Null when there is none.
    presenter_delivery: str | None
    story_length: StoryLengthOut


def _orientation(project: Project) -> Orientation:
    # The database CHECK constraint keeps this to the two allowed values.
    return cast(Orientation, project.orientation)


def _speech_mode(project: Project) -> SpeechMode:
    # The database CHECK constraint keeps this to the three allowed values.
    return cast(SpeechMode, project.speech_mode)


def _kind(project: Project) -> ProjectKind:
    # The database CHECK constraint keeps this to the two allowed values.
    return cast(ProjectKind, project.kind)


def _voice_track(project: Project) -> VoiceTrack:
    # The database CHECK constraint keeps this to the two allowed values.
    return cast(VoiceTrack, project.voice_track)


def _review_points(project: Project) -> list[ReviewPointKey]:
    # Stored normalized, but read defensively: only known keys are ever returned.
    stored = project.review_points if isinstance(project.review_points, list) else []
    return cast(list[ReviewPointKey], review_points_service.normalize(stored))


async def _detail(session: AsyncSession, project: Project) -> ProjectDetail:
    policy = await story_length_service.read_story_length_policy(session)
    length = story_length_service.story_length(project.script_text, policy)
    return ProjectDetail(
        id=project.id,
        name=project.name,
        orientation=_orientation(project),
        speech_mode=_speech_mode(project),
        kind=_kind(project),
        created_at=project.created_at,
        gen_width=project.gen_width,
        gen_height=project.gen_height,
        out_width=project.out_width,
        out_height=project.out_height,
        fps=project.fps,
        script_text=project.script_text,
        review_points=_review_points(project),
        music_enabled=project.music_enabled,
        ambience_enabled=project.ambience_enabled,
        captions=project.captions,
        callouts=project.callouts,
        voice_track=_voice_track(project),
        presenter_delivery=project.presenter_delivery,
        story_length=StoryLengthOut(
            word_count=length.word_count,
            estimated_seconds=length.estimated_seconds,
            words_per_minute=length.words_per_minute,
            limit_seconds=length.limit_seconds,
            over_limit=length.over_limit,
        ),
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
        project = await projects_service.create_project(
            session,
            body.name,
            body.orientation,
            body.speech_mode,
            body.kind,
            body.presenter_character_id,
            body.set_environment_id,
            body.captions,
            body.callouts,
            body.voice_track,
            body.presenter_delivery,
        )
    except projects_service.ProjectValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _detail(session, project)


@router.get("/projects/{project_id}", response_model=ProjectDetail, responses=_NOT_FOUND)
async def get_project(project_id: int, session: SessionDep) -> ProjectDetail:
    return await _detail(session, await load_project(session, project_id))


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectDetail,
    responses={**_NOT_FOUND, **_INVALID},
)
async def update_project(
    project_id: int, body: ProjectUpdate, session: SessionDep
) -> ProjectDetail:
    """Changes the fields that are sent: the name, the sizes, the frame rate, the story and the
    review points.
    """
    project = await load_project(session, project_id)
    try:
        project = await projects_service.update_project(
            session, project, body.model_dump(exclude_unset=True)
        )
    except projects_service.ProjectValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _detail(session, project)


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
