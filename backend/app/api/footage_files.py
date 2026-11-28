"""The owner's own photos and videos on a footage mark (FTG-003).

- `GET /api/projects/{project_id}/footage-files` answers the files shown on each mark, in the
  order they are shown, and where each stands (a video is "preparing" until the job
  `prepare_footage_file` has made it ready).
- `POST .../footage-marks/{mark_id}/files?kind=image|video[&credit=...]` receives one file as the
  raw request body (`application/octet-stream`), checks it, stores it and shows it after the
  mark's other files. A video also queues the job that makes it ready.
- `DELETE .../footage-files/{item_key}` takes a file off its mark.
- `PUT .../footage-marks/{mark_id}/order` puts the files of a mark in a new order.
- `PUT .../footage-files/{item_key}/use` moves where a video starts and ends.
- `POST .../footage-files/{item_key}/preview` queues a 6 second preview of the file as it will be
  drawn over the shots (FTG-005); the newest one is on the file in the list above.

Every change is a new version of the owner's footage decisions (`services/footage_decisions.py`).
Every route answers 422 for a project without footage. The answers never return ORM objects.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal, cast

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import content_length, load_project, require_octet_stream
from app.db.models import Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import footage_clips, footage_marks
from app.services import footage_files as files_service
from app.services.storage import media_url

router = APIRouter()

MarkId = Annotated[str, Path(max_length=50)]
ItemKey = Annotated[str, Path(max_length=100)]

_UPLOAD_BODY: Final[dict[str, Any]] = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project, mark or file."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The project has no footage, the file or the request breaks a rule.",
    }
}

FileKind = Literal["image", "video"]
FileStatus = Literal["preparing", "ready", "failed"]


# --- What the files hold ---------------------------------------------------------------------


class FootageFileStripOut(BaseModel):
    """How the strip image of a video is laid out: tile `n` (from 0) is the frame at
    `n * every_s` seconds, `columns` tiles to a row, each `tile_w` wide and `tile_h` high."""

    every_s: float
    columns: int
    rows: int
    tile_w: int
    tile_h: int
    frames: int


class FootageFileUseOut(BaseModel):
    """The part of a video that is shown, in seconds of the prepared video."""

    start_s: float
    end_s: float


class FootagePreviewOut(BaseModel):
    """The newest preview video of a file (FTG-005)."""

    job_id: int | None
    status: JobStatus
    error: str | None
    # The 6 second video, under /media, once it is made.
    video_url: str | None
    # The video's own warnings, such as a cut that could not be kept off the edges.
    warnings: list[str]
    # It was made with other settings than a preview made now would have.
    out_of_date: bool
    width: int
    height: int


class FootagePreviewStarted(BaseModel):
    job_id: int


class FootageFileOut(BaseModel):
    item_key: str
    mark_id: str
    kind: FileKind
    # The owner's credit line, if they wrote one.
    credit: str | None
    status: FileStatus
    # Why a video could not be made ready, when `status` is `failed`.
    error: str | None
    # The picture of an image, or the prepared video (null until a video is ready). Under /media.
    media_url: str | None
    strip_url: str | None
    strip: FootageFileStripOut | None
    width: int | None
    height: int | None
    duration_s: float | None
    use: FootageFileUseOut | None
    # The newest preview, null when none was made.
    preview: FootagePreviewOut | None


class FootageFilesState(BaseModel):
    # False for a story, a lines explainer and a project with footage off.
    wanted: bool
    # Every file shown on each mark, in the order shown.
    files: list[FootageFileOut]
    # True while a video of the project is being made ready.
    preparing: bool


class FootageFileStored(BaseModel):
    item_key: str
    kind: FileKind
    # The job that makes a video ready; null for an image.
    job_id: int | None


# --- What a change sends ---------------------------------------------------------------------


class FootageOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The item keys shown on the mark, in the new order.
    shown: list[StrictStr] = Field(max_length=50)


class FootageUseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_s: StrictFloat | StrictInt = Field(ge=0, le=100000)
    end_s: StrictFloat | StrictInt = Field(ge=0, le=100000)


# --- Mapping ---------------------------------------------------------------------------------


def _refusal(exc: files_service.FootageFilesError) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


def _strip_out(strip: dict[str, Any] | None) -> FootageFileStripOut | None:
    if strip is None or any(value is None for value in strip.values()):
        return None
    tile = strip["strip_tile_px"]
    return FootageFileStripOut(
        every_s=strip["strip_every_s"],
        columns=strip["strip_columns"],
        rows=strip["strip_rows"],
        tile_w=tile[0],
        tile_h=tile[1],
        frames=strip["strip_frames"],
    )


def _preview_out(preview: footage_clips.Preview | None) -> FootagePreviewOut | None:
    if preview is None:
        return None
    return FootagePreviewOut(
        job_id=preview.job_id,
        status=cast(JobStatus, preview.status),
        error=preview.error,
        video_url=media_url(preview.media_path) if preview.media_path else None,
        warnings=preview.warnings,
        out_of_date=preview.out_of_date,
        width=preview.width,
        height=preview.height,
    )


def _file_out(view: files_service.FileView) -> FootageFileOut:
    use = view.use
    return FootageFileOut(
        item_key=view.item_key,
        mark_id=view.mark_id,
        kind=cast(FileKind, view.kind),
        credit=view.credit,
        status=cast(FileStatus, view.status),
        error=view.error,
        media_url=view.media_url,
        strip_url=view.strip_url,
        strip=_strip_out(view.strip),
        width=view.width,
        height=view.height,
        duration_s=view.duration_s,
        use=(
            FootageFileUseOut(start_s=use["start_s"], end_s=use["end_s"])
            if isinstance(use, dict)
            else None
        ),
        preview=_preview_out(view.preview),
    )


async def _state(session: AsyncSession, project: Project) -> FootageFilesState:
    state = await files_service.files_state(session, project)
    return FootageFilesState(
        wanted=footage_marks.wanted(project),
        files=[_file_out(view) for view in state.files],
        preparing=state.preparing,
    )


# --- Endpoints -------------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/footage-files",
    response_model=FootageFilesState,
    responses=_NOT_FOUND,
)
async def get_footage_files(project_id: int, session: SessionDep) -> FootageFilesState:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/footage-marks/{mark_id}/files",
    response_model=FootageFileStored,
    status_code=status.HTTP_201_CREATED,
    responses={
        **_NOT_FOUND,
        **_INVALID,
        413: {"model": ErrorResponse, "description": "The file is larger than the limit."},
        415: {
            "model": ErrorResponse,
            "description": "The body is not sent as application/octet-stream.",
        },
    },
    openapi_extra=_UPLOAD_BODY,
)
async def upload_footage_file(
    project_id: int,
    mark_id: MarkId,
    request: Request,
    session: SessionDep,
    kind: Annotated[FileKind, Query()],
    credit: Annotated[str | None, Query(max_length=500)] = None,
) -> FootageFileStored:
    """Adds a photo (PNG, JPEG or WebP) or a video (MP4, MOV, MKV or WebM), sent as the raw request
    body, to a footage mark. It is accepted at once and shown after the mark's other files.
    """
    require_octet_stream(request)
    project = await load_project(session, project_id)
    try:
        stored = await files_service.receive_file(
            session,
            project,
            mark_id,
            kind,
            credit,
            request.stream(),
            content_length(request),
        )
    except files_service.FootageFilesError as exc:
        raise _refusal(exc) from exc
    if stored.job_id is not None:
        dispatcher.nudge()
    return FootageFileStored(
        item_key=stored.item_key, kind=cast(FileKind, stored.kind), job_id=stored.job_id
    )


@router.delete(
    "/projects/{project_id}/footage-files/{item_key}",
    response_model=FootageFilesState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def remove_footage_file(
    project_id: int, item_key: ItemKey, session: SessionDep
) -> FootageFilesState:
    """Takes a file off its mark. The stored file stays."""
    project = await load_project(session, project_id)
    try:
        await files_service.remove_file(session, project, item_key)
    except files_service.FootageFilesError as exc:
        raise _refusal(exc) from exc
    return await _state(session, project)


@router.put(
    "/projects/{project_id}/footage-marks/{mark_id}/order",
    response_model=FootageFilesState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def reorder_footage_files(
    project_id: int, mark_id: MarkId, body: FootageOrderIn, session: SessionDep
) -> FootageFilesState:
    """Puts the files shown on a mark in a new order. The list must hold exactly the files shown
    now, once each."""
    project = await load_project(session, project_id)
    try:
        await files_service.reorder_files(session, project, mark_id, body.shown)
    except files_service.FootageFilesError as exc:
        raise _refusal(exc) from exc
    return await _state(session, project)


@router.put(
    "/projects/{project_id}/footage-files/{item_key}/use",
    response_model=FootageFilesState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def set_footage_file_use(
    project_id: int, item_key: ItemKey, body: FootageUseIn, session: SessionDep
) -> FootageFilesState:
    """Moves where a video starts and ends: steps of half a second, 2 to 30 seconds."""
    project = await load_project(session, project_id)
    try:
        await files_service.set_use(
            session, project, item_key, float(body.start_s), float(body.end_s)
        )
    except files_service.FootageFilesError as exc:
        raise _refusal(exc) from exc
    return await _state(session, project)


@router.post(
    "/projects/{project_id}/footage-files/{item_key}/preview",
    response_model=FootagePreviewStarted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def start_footage_preview(
    project_id: int, item_key: ItemKey, session: SessionDep
) -> FootagePreviewStarted:
    """Queues a 6 second preview of a file shown on a mark, drawn the way it will be over the
    shots. Asking again while one is being made answers the same job."""
    project = await load_project(session, project_id)
    try:
        job = await footage_clips.queue_preview(session, project, item_key)
    except footage_clips.FootageClipError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    dispatcher.nudge()
    return FootagePreviewStarted(job_id=job.id)
