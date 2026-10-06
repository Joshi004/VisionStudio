"""A scene's inputs: its description and its first and last frame (ANALYSIS.md Section 4.2).

Manual-first: whoever made an input, it is the same column or asset row, and only
`scene_description_source` and `asset.source` say where it came from. Readiness is computed
from the columns and never stored (DATABASE_STRUCTURE.md Section 4.4).

A frame upload follows the voiceover's pattern (`services/voiceover.py`): the file is
received into the temp folder, checked, moved into the media folder under a generated name,
and recorded as an `asset` row together with the link from the scene, in one transaction.
The original file is kept as uploaded. The normalised frame is made on demand
(`services/frame_images.py`). Files are never deleted: removing a frame only clears the link.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable, Sequence
from typing import Any, Final, Literal, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, Scene
from app.services import frame_images
from app.services.assets import add_asset
from app.services.frame_images import FrameRejected
from app.services.storage import TooLargeError, get_storage

_logger = logging.getLogger(__name__)

MissingInput = Literal["description", "first_frame", "last_frame"]
FrameSlot = Literal["first", "last"]

DESCRIPTION_MAX_CHARS: Final = 4000

_SLOT_COLUMNS: Final[dict[FrameSlot, str]] = {
    "first": "first_frame_asset_id",
    "last": "last_frame_asset_id",
}

_TOO_LARGE: Final = f"The file is larger than {frame_images.FRAME_MAX_MB} MB."


class SceneGone(Exception):
    """The scene no longer exists, or belongs to another project."""


class DescriptionTooLong(ValueError):
    """The message is meant to be shown to the user."""


def missing_inputs(scene: Scene | Any) -> list[MissingInput]:
    """What a scene still needs before a clip can be generated: a description and both
    frames. Pure, and the only definition of "ready".
    """
    description = scene.scene_description
    missing: list[MissingInput] = []
    if not (isinstance(description, str) and description.strip()):
        missing.append("description")
    if scene.first_frame_asset_id is None:
        missing.append("first_frame")
    if scene.last_frame_asset_id is None:
        missing.append("last_frame")
    return missing


def is_ready(scene: Scene | Any) -> bool:
    return not missing_inputs(scene)


async def get_scene(session: AsyncSession, project_id: int, scene_id: int) -> Scene | None:
    """The scene, only if it belongs to the project."""
    scene = await session.get(Scene, scene_id)
    return scene if scene is not None and scene.project_id == project_id else None


async def load_frames(session: AsyncSession, scenes: Sequence[Scene]) -> dict[int, Asset]:
    """The frame assets the scenes point at, by asset id, in one query."""
    ids = {
        asset_id
        for scene in scenes
        for asset_id in (scene.first_frame_asset_id, scene.last_frame_asset_id)
        if asset_id is not None
    }
    if not ids:
        return {}
    statement = (
        select(Asset)
        .where(Asset.id.in_(ids), Asset.kind == "frame")
        .execution_options(populate_existing=True)
    )
    return {asset.id: asset for asset in (await session.execute(statement)).scalars()}


def _was_updated(result: object) -> bool:
    return cast(CursorResult[Any], result).rowcount == 1


async def set_description(
    session: AsyncSession, project_id: int, scene_id: int, text: str | None
) -> None:
    """Saves the description as typed by the user (`scene_description_source = manual`).

    The text is trimmed, and a blank description clears both columns. Commits.
    Raises DescriptionTooLong or SceneGone.
    """
    cleaned = (text or "").strip()
    if len(cleaned) > DESCRIPTION_MAX_CHARS:
        raise DescriptionTooLong(
            f"The description must be at most {DESCRIPTION_MAX_CHARS:,} characters."
        )
    result = await session.execute(
        update(Scene)
        .where(Scene.id == scene_id, Scene.project_id == project_id)
        .values(
            scene_description=cleaned or None,
            scene_description_source="manual" if cleaned else None,
        )
        .execution_options(synchronize_session=False)
    )
    if not _was_updated(result):
        await session.rollback()
        raise SceneGone
    await session.commit()


async def clear_frame(
    session: AsyncSession, project_id: int, scene_id: int, slot: FrameSlot
) -> None:
    """Removes a frame from the scene. The asset row and the file stay. Commits.

    Succeeds when the slot is already empty. Raises SceneGone.
    """
    result = await session.execute(
        update(Scene)
        .where(Scene.id == scene_id, Scene.project_id == project_id)
        .values({_SLOT_COLUMNS[slot]: None})
        .execution_options(synchronize_session=False)
    )
    if not _was_updated(result):
        await session.rollback()
        raise SceneGone
    await session.commit()
    _logger.info("scene %d: %s frame removed", scene_id, slot)


async def upload_frame(
    session: AsyncSession,
    project_id: int,
    scene_id: int,
    slot: FrameSlot,
    chunks: AsyncIterable[bytes],
    content_length: int | None,
) -> Asset:
    """Receives, checks and stores a frame, then points the scene's slot at it.

    The caller has already checked that the scene exists and has ended its own read
    transaction, so none is open while the file is received and decoded. A temp file never
    outlives a failed upload. Raises FrameRejected or SceneGone.
    """
    if content_length is not None and content_length > frame_images.FRAME_MAX_BYTES:
        raise FrameRejected(413, _TOO_LARGE)

    storage = get_storage()
    try:
        temp = await storage.receive(chunks, max_bytes=frame_images.FRAME_MAX_BYTES)
    except TooLargeError:
        raise FrameRejected(413, _TOO_LARGE) from None

    try:
        if temp.size_bytes == 0:
            raise FrameRejected(422, "The file is empty.")
        info = await frame_images.run_pillow(frame_images.inspect_image, temp.path)
        stored = await storage.save(temp, project_id, info.ext)
    except BaseException:
        # After a successful save the temp file is already gone; discard ignores that.
        storage.discard(temp)
        raise

    try:
        asset = await add_asset(
            session,
            project_id=project_id,
            kind="frame",
            stored=stored,
            mime=info.mime,
            size_bytes=temp.size_bytes,
            sha256=temp.sha256,
            source="upload",
            width=info.width,
            height=info.height,
        )
        result = await session.execute(
            update(Scene)
            .where(Scene.id == scene_id, Scene.project_id == project_id)
            .values({_SLOT_COLUMNS[slot]: asset.id})
            .execution_options(synchronize_session=False)
        )
        if not _was_updated(result):
            # The scene went away during the upload (a cut edit merged it).
            await session.rollback()
            _logger.warning("frame stored but not recorded: %s", stored.relative_path)
            raise SceneGone
        await session.commit()
    except SceneGone:
        raise
    except BaseException:
        # Stored files are never deleted, so this leaves an unreferenced file behind.
        _logger.warning("frame stored but not recorded: %s", stored.relative_path)
        raise

    _logger.info(
        "frame stored: project=%d scene=%d slot=%s asset=%d %s %dx%d %d bytes",
        project_id,
        scene_id,
        slot,
        asset.id,
        info.ext,
        info.width,
        info.height,
        temp.size_bytes,
    )
    return asset
