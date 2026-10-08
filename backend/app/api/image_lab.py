"""The Image lab (Phase 13): manual tests of Bitdeer's image API.

`POST /api/lab/images/runs` makes one call (text to image, image to image, or an edit) and
answers with the saved run when it is done. It takes 25 to 40 s, so it is one synchronous
request, not a job, and nginx gives `/api/lab/` a longer time limit. It is a paid call and
only ever starts from this request. See `services/image_lab.py`.

The other routes read the database only: the history of runs, one run with its request and
raw answer, the lab's own images (uploads and results), and a project's frames, so they can
be picked as references. An image is uploaded as the raw request body, like a scene's frame.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from app.api.errors import ErrorResponse
from app.api.projects import content_length, load_project, require_octet_stream
from app.db.models import LabImage, LabRun
from app.db.session import SessionDep
from app.services import frame_images, image_lab
from app.services.image_lab import LabForm, LabInputError, Ref
from app.services.storage import media_url

_logger = logging.getLogger(__name__)

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID = 2**63 - 1
RunId = Annotated[int, Path(ge=1, le=_MAX_ID)]
Id = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]

_UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}

LabMode = Literal["text_to_image", "image_to_image", "edit"]


class LabReferenceIn(BaseModel):
    """An image to send as a reference: one the lab holds, or a project's frame asset."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["lab", "asset"]
    id: Id


class LabRunRequest(BaseModel):
    """The form of the Image lab. Each field is sent as it is, so the page can show what the
    API does with it: the API may ignore any of them.
    """

    model_config = ConfigDict(extra="forbid")

    mode: LabMode
    model: StrictStr = image_lab.DEFAULT_MODEL
    prompt: StrictStr
    size: StrictStr = "1632x2880"
    # True or false is sent. Null sends nothing, to see the API's own default.
    watermark: StrictBool | None = False
    seed: StrictInt | None = None
    # A number asks for an image set (`sequential_image_generation: auto`) of at most that many.
    sequential_max_images: StrictInt | None = None
    # How the `image` field goes out in image to image mode.
    image_field_as: Literal["list", "string"] = "list"
    # The name of the file field in edit mode.
    edit_field_name: Literal["image", "image[]"] = "image"
    # Any other parameter, as a JSON object. Checked in the handler, for a readable message.
    extra: Any = None
    references: list[LabReferenceIn] = Field(default_factory=list, max_length=100)


class LabImageOut(BaseModel):
    id: int
    created_at: datetime
    origin: Literal["upload", "result"]
    run_id: int | None
    # The position among the run's results, from 0. None for an upload.
    output_index: int | None
    url: str
    mime: str
    width: int
    height: int
    size_bytes: int


class LabReferenceOut(BaseModel):
    source: Literal["lab", "asset"]
    id: int
    # None when the image is gone.
    url: str | None
    width: int | None
    height: int | None


class LabRunOut(BaseModel):
    id: int
    created_at: datetime
    mode: LabMode
    endpoint: str
    model: str
    prompt: str
    params: dict[str, Any]
    status: Literal["succeeded", "failed"]
    http_status: int | None
    error: str | None
    seconds: float | None
    request_bytes: int | None
    usage: dict[str, Any] | None
    # An estimate: the number of generated images times Bitdeer's price for one.
    estimated_cost_usd: float | None
    images: list[LabImageOut]
    references: list[LabReferenceOut]
    # The request as sent and the answer as received, with every image replaced by its size.
    # Only the single-run answers carry them: the history list leaves them out.
    request: Any | None
    response: Any | None


class LabRunsOut(BaseModel):
    runs: list[LabRunOut]
    # Pass this as `before_id` for the next page. None when there are no more.
    next_before_id: int | None


class LabLibraryOut(BaseModel):
    images: list[LabImageOut]


class ProjectFrameOut(BaseModel):
    asset_id: int
    created_at: datetime
    # "upload", "derived" (the exact file sent to the GPU server) or "ai".
    source: str
    url: str
    mime: str
    width: int | None
    height: int | None
    size_bytes: int
    # Where the frame is used now: the scene's number (from 1) and the slot.
    scene_number: int | None
    slot: Literal["first", "last"] | None


class ProjectFramesOut(BaseModel):
    frames: list[ProjectFrameOut]


def _image_out(image: LabImage) -> LabImageOut:
    return LabImageOut(
        id=image.id,
        created_at=image.created_at,
        origin="upload" if image.origin == "upload" else "result",
        run_id=image.run_id,
        output_index=image.output_index,
        url=media_url(image.path),
        mime=image.mime,
        width=image.width,
        height=image.height,
        size_bytes=image.size_bytes,
    )


def _run_out(
    run: LabRun,
    images: list[LabImage],
    details: dict[tuple[str, int], image_lab.ReferenceDetail],
    *,
    with_payloads: bool,
) -> LabRunOut:
    references: list[LabReferenceOut] = []
    for item in run.reference_images if isinstance(run.reference_images, list) else []:
        source = "asset" if item.get("source") == "asset" else "lab"
        reference_id = item.get("id") if isinstance(item.get("id"), int) else 0
        detail = details.get((source, reference_id))
        references.append(
            LabReferenceOut(
                source=source,
                id=reference_id,
                url=media_url(detail.path) if detail is not None else None,
                width=detail.width if detail is not None else None,
                height=detail.height if detail is not None else None,
            )
        )
    return LabRunOut(
        id=run.id,
        created_at=run.created_at,
        mode=run.mode,  # type: ignore[arg-type]  # the database CHECK keeps this to the modes
        endpoint=run.endpoint,
        model=run.model,
        prompt=run.prompt,
        params=run.params if isinstance(run.params, dict) else {},
        status="succeeded" if run.status == "succeeded" else "failed",
        http_status=run.http_status,
        error=run.error,
        seconds=run.seconds,
        request_bytes=run.request_bytes,
        usage=run.usage if isinstance(run.usage, dict) else None,
        estimated_cost_usd=image_lab.estimate_cost(
            run.usage if isinstance(run.usage, dict) else None
        ),
        images=[_image_out(image) for image in images],
        references=references,
        request=run.request if with_payloads else None,
        response=run.response if with_payloads else None,
    )


async def _runs_out(
    session: SessionDep, runs: list[LabRun], *, with_payloads: bool
) -> list[LabRunOut]:
    images = await image_lab.images_by_run(session, [run.id for run in runs])
    details = await image_lab.reference_details(session, runs)
    return [
        _run_out(run, images.get(run.id, []), details, with_payloads=with_payloads) for run in runs
    ]


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


@router.post(
    "/lab/images/runs",
    response_model=LabRunOut,
    responses={
        422: {
            "model": ErrorResponse,
            "description": "The form is not acceptable: an empty prompt, too many or missing "
            "references, a reference that does not exist, or a bad extra JSON.",
        }
    },
)
async def create_run(body: LabRunRequest, session: SessionDep) -> LabRunOut:
    """Makes one call to the image API (a paid call, about 25 to 40 s) and answers with the
    saved run. A call that failed or was refused is a saved run too, with its `error`. The
    request is answered when the call is done; if the browser goes away first, the call still
    finishes and the run is kept.
    """
    if body.extra is not None and not isinstance(body.extra, dict):
        raise _unprocessable('The extra JSON must be an object, like {"guidance_scale": 7.5}.')
    form = LabForm(
        mode=body.mode,
        model=body.model,
        prompt=body.prompt,
        size=body.size,
        watermark=body.watermark,
        seed=body.seed,
        sequential_max_images=body.sequential_max_images,
        image_field_as=body.image_field_as,
        edit_field_name=body.edit_field_name,
        extra=dict(body.extra or {}),
        references=[Ref(source=item.source, id=item.id) for item in body.references],
    )
    # No transaction of this request stays open during the call.
    await session.commit()
    try:
        run_id = await image_lab.start_run(form)
    except LabInputError as exc:
        raise _unprocessable(str(exc)) from exc

    run = await image_lab.get_run(session, run_id)
    if run is None:  # cannot happen: runs are never deleted
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "The run was not saved.")
    return (await _runs_out(session, [run], with_payloads=True))[0]


@router.get("/lab/images/runs", response_model=LabRunsOut)
async def list_runs(
    session: SessionDep,
    before_id: Annotated[int | None, Query(ge=1, le=_MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> LabRunsOut:
    """The history, newest first. Reads the database only."""
    runs = await image_lab.list_runs(session, before_id, limit)
    return LabRunsOut(
        runs=await _runs_out(session, runs, with_payloads=False),
        next_before_id=runs[-1].id if len(runs) == limit else None,
    )


@router.get(
    "/lab/images/runs/{run_id}",
    response_model=LabRunOut,
    responses={404: {"model": ErrorResponse, "description": "No run has this id."}},
)
async def get_run(run_id: RunId, session: SessionDep) -> LabRunOut:
    """One run, with the request and the answer."""
    run = await image_lab.get_run(session, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} does not exist.")
    return (await _runs_out(session, [run], with_payloads=True))[0]


@router.post(
    "/lab/images/uploads",
    response_model=LabImageOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        413: {"model": ErrorResponse, "description": "The file is larger than the limit."},
        415: {
            "model": ErrorResponse,
            "description": "The body is not sent as application/octet-stream.",
        },
        422: {"model": ErrorResponse, "description": "The file is not an acceptable image."},
    },
    openapi_extra=_UPLOAD_BODY,
)
async def upload_image(request: Request, session: SessionDep) -> LabImageOut:
    """Stores a PNG, JPEG or WebP image sent as the raw request body, so it can be used as a
    reference. The rules are those of a scene's frame.
    """
    require_octet_stream(request)
    # No transaction of this request stays open while the file is received and decoded.
    await session.commit()
    try:
        image = await image_lab.upload_image(request.stream(), content_length(request))
    except frame_images.FrameRejected as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return _image_out(image)


@router.get("/lab/images/library", response_model=LabLibraryOut)
async def get_library(session: SessionDep) -> LabLibraryOut:
    """The newest 60 lab images, uploads and results together."""
    return LabLibraryOut(images=[_image_out(image) for image in await image_lab.library(session)])


@router.get(
    "/lab/images/project-frames",
    response_model=ProjectFramesOut,
    responses={404: {"model": ErrorResponse, "description": "No project has this id."}},
)
async def get_project_frames(
    session: SessionDep, project_id: Annotated[int, Query(ge=1, le=_MAX_ID)]
) -> ProjectFramesOut:
    """A project's frames, newest first, so one can be picked as a reference."""
    project = await load_project(session, project_id)
    frames = await image_lab.project_frames(session, project.id)
    return ProjectFramesOut(
        frames=[
            ProjectFrameOut(
                asset_id=frame.asset.id,
                created_at=frame.asset.created_at,
                source=frame.asset.source,
                url=media_url(frame.asset.path),
                mime=frame.asset.mime,
                width=frame.asset.width,
                height=frame.asset.height,
                size_bytes=frame.asset.size_bytes,
                scene_number=frame.scene_number,
                slot="first" if frame.slot == "first" else "last" if frame.slot == "last" else None,
            )
            for frame in frames
        ]
    )
