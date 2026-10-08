"""Scene inputs (Phase 8): the description, the first and last frame, and the frame preview.

`PATCH .../scenes/{id}` saves the description, the two frame descriptions (Phase 12 added
the frame descriptions) and the first frame's image prompt (Phase 16). `POST` and `DELETE`
`.../scenes/{id}/frames/{slot}` set and remove a frame. Each answers with the scenes as they
are afterwards (`ScenesOut`), so the page shows the change without another request.

`GET .../frames/{asset_id}/preview` renders a stored frame as the video model will get it:
RGB, centre-cropped and resized to the project's generation size (ANALYSIS.md Section 5.3).
Only the original is stored, so this is made on request. The size is part of the address, and
it must be the project's current one, so a page that has not been refreshed since the size
changed gets a 404 and never shows an old framing as the current one.
"""

from __future__ import annotations

import logging
from typing import Final

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.projects import content_length, load_project, require_octet_stream
from app.api.scenes import ScenesOut, scenes_out
from app.db.models import Asset
from app.db.session import SessionDep
from app.services import frame_images, scene_inputs
from app.services.scene_inputs import FrameSlot
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1

_NOT_FOUND = {
    404: {"model": ErrorResponse, "description": "No project, scene or frame has this id."}
}

_FRAME_UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}

_PREVIEW_CACHE_CONTROL: Final = "private, no-cache"


class SceneUpdate(BaseModel):
    """The texts of a scene. Only the fields that are sent are changed, and null or blank
    clears one. A text that is saved becomes the author's (`manual`): a later AI draft never
    overwrites it.
    """

    model_config = ConfigDict(extra="forbid")

    scene_description: StrictStr | None = None
    first_frame_description: StrictStr | None = None
    last_frame_description: StrictStr | None = None
    # The detailed prompt for the image model that makes the first frame (Phase 16).
    image_prompt: StrictStr | None = None


def _scene_missing(scene_id: int) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND, f"Scene {scene_id} does not exist in this project."
    )


async def _require_scene(session: AsyncSession, project_id: int, scene_id: int) -> None:
    scene = None
    if 1 <= scene_id <= _MAX_ID:
        scene = await scene_inputs.get_scene(session, project_id, scene_id)
    if scene is None:
        raise _scene_missing(scene_id)


@router.patch(
    "/projects/{project_id}/scenes/{scene_id}",
    response_model=ScenesOut,
    responses={
        **_NOT_FOUND,
        422: {"model": ErrorResponse, "description": "A text is too long."},
    },
)
async def update_scene(
    project_id: int, scene_id: int, body: SceneUpdate, session: SessionDep
) -> ScenesOut:
    """Saves the scene's description, frame descriptions and image prompt that are sent. Each
    one that changes is marked as written by the author (`manual`).
    """
    project = await load_project(session, project_id)
    await _require_scene(session, project.id, scene_id)
    try:
        await scene_inputs.set_texts(
            session, project.id, scene_id, body.model_dump(exclude_unset=True)
        )
    except scene_inputs.DescriptionTooLong as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except scene_inputs.SceneGone:
        raise _scene_missing(scene_id) from None
    return await scenes_out(session, project)


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/frames/{slot}",
    response_model=ScenesOut,
    responses={
        **_NOT_FOUND,
        413: {"model": ErrorResponse, "description": "The file is larger than the limit."},
        415: {
            "model": ErrorResponse,
            "description": "The body is not sent as application/octet-stream.",
        },
        422: {"model": ErrorResponse, "description": "The file is not an acceptable frame."},
    },
    openapi_extra=_FRAME_UPLOAD_BODY,
)
async def upload_frame(
    project_id: int, scene_id: int, slot: FrameSlot, request: Request, session: SessionDep
) -> ScenesOut:
    """Stores a PNG, JPEG or WebP image sent as the raw request body as the scene's first or
    last frame. A frame already there is replaced; its file stays on disk.
    """
    project = await load_project(session, project_id)
    await _require_scene(session, project.id, scene_id)
    require_octet_stream(request)

    # End the read transaction: none may stay open while the file is received and decoded.
    await session.commit()

    try:
        await scene_inputs.upload_frame(
            session, project.id, scene_id, slot, request.stream(), content_length(request)
        )
    except frame_images.FrameRejected as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    except scene_inputs.SceneGone:
        raise _scene_missing(scene_id) from None
    return await scenes_out(session, project)


@router.delete(
    "/projects/{project_id}/scenes/{scene_id}/frames/{slot}",
    response_model=ScenesOut,
    responses=_NOT_FOUND,
)
async def remove_frame(
    project_id: int, scene_id: int, slot: FrameSlot, session: SessionDep
) -> ScenesOut:
    """Clears the scene's first or last frame. The asset row and the file stay."""
    project = await load_project(session, project_id)
    await _require_scene(session, project.id, scene_id)
    try:
        await scene_inputs.clear_frame(session, project.id, scene_id, slot)
    except scene_inputs.SceneGone:
        raise _scene_missing(scene_id) from None
    return await scenes_out(session, project)


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    candidates = [part.strip().removeprefix("W/") for part in header.split(",")]
    return "*" in candidates or etag in candidates


@router.get(
    "/projects/{project_id}/frames/{asset_id}/preview",
    response_class=Response,
    responses={
        200: {
            "description": "The frame as it will be sent, as a JPEG.",
            "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}},
        },
        304: {"description": "The browser's copy is current."},
        **_NOT_FOUND,
    },
)
async def frame_preview(
    project_id: int,
    asset_id: int,
    width: int,
    height: int,
    request: Request,
    session: SessionDep,
) -> Response:
    """The stored frame normalised to `width` x `height`, which must be the project's
    current generation size.
    """
    project = await load_project(session, project_id)
    asset = await session.get(Asset, asset_id) if 1 <= asset_id <= _MAX_ID else None
    if asset is None or asset.project_id != project.id or asset.kind != "frame":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Project has no frame {asset_id}.")
    if (width, height) != (project.gen_width, project.gen_height):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "The generation size has changed. Press Refresh."
        )

    # The preview depends only on the original, the size and the way it is normalised.
    etag = f'"{asset.sha256[:16]}-{width}x{height}-v{frame_images.NORMALISE_VERSION}"'
    headers = {
        "ETag": etag,
        "Cache-Control": _PREVIEW_CACHE_CONTROL,
        "X-Content-Type-Options": "nosniff",
    }
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    try:
        path = get_storage().get_path(asset.path)
        data = await frame_images.run_pillow(frame_images.render_preview_jpeg, path, width, height)
    except (StorageError, OSError):
        _logger.warning("frame preview failed: asset=%d path=%s", asset.id, asset.path)
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "The frame's file could not be read."
        ) from None
    _logger.info(
        "frame preview rendered: project=%d asset=%d %dx%d %d bytes",
        project.id,
        asset.id,
        width,
        height,
        len(data),
    )
    return Response(content=data, media_type="image/jpeg", headers=headers)
