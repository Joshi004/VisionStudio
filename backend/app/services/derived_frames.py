"""The frames that are actually sent to the GPU server (ANALYSIS.md Section 5.3; Phase 8
decision, built here).

A scene's frames are stored as uploaded. At submission, each one is normalised (upright,
RGB, centre-cropped and resized to the project's generation size *at that moment*) and the
result is stored as a lossless PNG: an `asset` row with `kind='frame'` and
`source='derived'`. The job records the ids of these files, so what was sent can always be
looked at again, and a resubmission sends the very same files.

The provenance says exactly how the file was made. An existing derived asset with the same
provenance is reused instead of making another one.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset
from app.services import frame_images
from app.services.assets import add_asset
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)


class FrameNotUsable(Exception):
    """The original frame cannot be read. The message is meant to be shown to the user."""


async def _one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def _existing(
    session: AsyncSession, original: Asset, provenance: dict[str, Any]
) -> Asset | None:
    statement = (
        select(Asset)
        .where(
            Asset.project_id == original.project_id,
            Asset.kind == "frame",
            Asset.source == "derived",
            Asset.mime == "image/png",
            Asset.width == provenance["width"],
            Asset.height == provenance["height"],
            func.json_extract(Asset.provenance, "$.derived_from_asset_id") == original.id,
        )
        .order_by(Asset.id.desc())
        .execution_options(populate_existing=True)
    )
    storage = get_storage()
    for asset in (await session.execute(statement)).scalars():
        recorded = asset.provenance
        if not isinstance(recorded, dict) or recorded != provenance:
            continue
        try:
            if storage.get_path(asset.path).is_file():
                return asset
        except StorageError:
            continue
    return None


async def frame_to_send(session: AsyncSession, original: Asset, width: int, height: int) -> Asset:
    """The derived PNG for `original` at `width` x `height`: an existing one with the same
    provenance, or a new one made now.

    Ends the session's transaction before the Pillow work (never hold one across slow
    work), and commits the new asset row. Raises FrameNotUsable.
    """
    provenance: dict[str, Any] = {
        "derived_from_asset_id": original.id,
        "width": width,
        "height": height,
        "normalise_version": frame_images.NORMALISE_VERSION,
    }
    found = await _existing(session, original, provenance)
    if found is not None:
        await session.commit()
        return found
    await session.commit()

    storage = get_storage()
    try:
        source_path = storage.get_path(original.path)
    except StorageError:
        raise FrameNotUsable("A frame's file could not be found on disk.") from None

    try:
        png = await frame_images.run_pillow(
            frame_images.render_frame_png, source_path, width, height
        )
    except Exception as exc:  # Pillow raises many kinds of error for a damaged file.
        _logger.warning("frame %d could not be normalised: %s", original.id, exc)
        raise FrameNotUsable(
            "A frame could not be read to prepare it for the video model. Upload it again."
        ) from None

    temp = await storage.receive(_one_chunk(png), max_bytes=len(png))
    try:
        stored = await storage.save(temp, original.project_id, "png")
    except BaseException:
        storage.discard(temp)
        raise

    try:
        asset = await add_asset(
            session,
            project_id=original.project_id,
            kind="frame",
            stored=stored,
            mime="image/png",
            size_bytes=temp.size_bytes,
            sha256=temp.sha256,
            source="derived",
            width=width,
            height=height,
            provenance=provenance,
        )
        await session.commit()
    except BaseException:
        # Stored files are never deleted, so this leaves an unreferenced file behind.
        _logger.warning("derived frame stored but not recorded: %s", stored.relative_path)
        raise
    _logger.info(
        "derived frame stored: asset=%d from=%d %dx%d %d bytes",
        asset.id,
        original.id,
        width,
        height,
        temp.size_bytes,
    )
    return asset
