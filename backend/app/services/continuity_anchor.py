"""The frame a continuity shot starts from (PHASE-032, Q-7).

A continuity shot carries straight on from the shot before it. Its anchor is the frame its
predecessor's selected take ends on, **at the predecessor's target duration**: a shot's length is
stored on H3's own length (D-9), so this is normally the last frame of the file. A plan made
before that, or a project at another frame rate, can have a take a few frames longer than its
shot (the render cuts the tail), and the frame at the target is the last one the viewer sees.
That frame is cut from the clip with FFmpeg and stored as an `asset`
row (`kind='frame'`, `source='derived'`), which the video handler already accepts as a first
frame (`{"source": "asset", "id": ...}`) and as a reference picture. No table and no migration
are needed.

The frame depends on the take it is cut from, so `provenance` records the take id and the frame
number, and a frame already cut from the same take at the same frame number is reused (a retry,
or a second press, does not cut it again).
"""

from __future__ import annotations

import logging
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, ShotTake
from app.services import assets, ffmpeg, frame_counts, frame_images
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

PROVENANCE_KIND: Final = "continuity_anchor"
# How many of a project's newest derived frames are looked through to find one to reuse.
_REUSE_LOOKBACK: Final = 300


class AnchorError(ValueError):
    """A frame that cannot be made. The message is meant to be shown to the user."""


def frame_index(
    target_seconds: float, frame_count: int | None, fps: int = frame_counts.H3_FPS
) -> int:
    """The number of the last frame shown of a shot of `target_seconds`: the frames before the
    boundary at the target time (`frame_counts.boundary_frame`) are shown, so the last of them is
    one less. It is kept inside the clip when the clip's own frame count is known.
    """
    last_shown = max(0, frame_counts.boundary_frame(target_seconds, fps) - 1)
    if frame_count is not None and frame_count > 0:
        return min(last_shown, frame_count - 1)
    return last_shown


def _matches(asset: Asset, take_id: int, index: int) -> bool:
    provenance: Any = asset.provenance
    return (
        isinstance(provenance, dict)
        and provenance.get("kind") == PROVENANCE_KIND
        and provenance.get("take_id") == take_id
        and provenance.get("frame_index") == index
    )


async def _reusable(
    session: AsyncSession, project_id: int, take_id: int, index: int
) -> Asset | None:
    statement = (
        select(Asset)
        .where(
            Asset.project_id == project_id,
            Asset.kind == "frame",
            Asset.source == "derived",
        )
        .order_by(Asset.id.desc())
        .limit(_REUSE_LOOKBACK)
    )
    for asset in (await session.execute(statement)).scalars():
        if _matches(asset, take_id, index):
            # Only an asset whose file is still there is worth reusing.
            try:
                if get_storage().get_path(asset.path).is_file():
                    return asset
            except StorageError:
                continue
    return None


async def anchor_asset(
    session: AsyncSession,
    *,
    project_id: int,
    take: ShotTake,
    target_seconds: float,
    from_shot_id: str,
) -> Asset:
    """The anchor frame of the shot that continues `take`'s shot: an `asset` row for the frame at
    the take's target duration. Flushes but does not commit. Raises AnchorError.
    """
    if take.path is None:
        raise AnchorError(f"The take of '{from_shot_id}' has no clip to cut a frame from.")
    index = frame_index(target_seconds, take.frame_count)
    reused = await _reusable(session, project_id, take.id, index)
    if reused is not None:
        return reused

    storage = get_storage()
    try:
        source = storage.get_path(take.path)
    except StorageError:
        raise AnchorError(f"The clip of '{from_shot_id}' could not be found on disk.") from None
    if not source.is_file():
        raise AnchorError(f"The clip of '{from_shot_id}' could not be found on disk.")

    temp = storage.new_temp_path("png")
    try:
        problem = await ffmpeg.extract_frame(source, index, temp)
        if problem is not None:
            raise AnchorError(
                f"The last frame of '{from_shot_id}' could not be cut from its clip: {problem}"
            )
        try:
            info = await frame_images.run_pillow(frame_images.inspect_image, temp)
        except frame_images.FrameRejected as exc:
            raise AnchorError(
                f"The last frame of '{from_shot_id}' could not be read: {exc.message}"
            ) from None
        described = await storage.describe_temp(temp)
        stored = await storage.save(described, project_id, info.ext)
    finally:
        # `save` moves the file; a failure before it leaves the temp file to remove.
        temp.unlink(missing_ok=True)

    asset = await assets.add_asset(
        session,
        project_id=project_id,
        kind="frame",
        stored=stored,
        mime=info.mime,
        size_bytes=described.size_bytes,
        sha256=described.sha256,
        source="derived",
        width=info.width,
        height=info.height,
        provenance={
            "kind": PROVENANCE_KIND,
            "take_id": take.id,
            "take_number": take.take_number,
            "shot_id": from_shot_id,
            "frame_index": index,
            "target_seconds": target_seconds,
        },
    )
    _logger.info(
        "continuity anchor of shot '%s' of project %d: frame %d of take %d, asset %d",
        from_shot_id,
        project_id,
        index,
        take.id,
        asset.id,
    )
    return asset
