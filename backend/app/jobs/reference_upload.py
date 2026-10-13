"""Uploading the reference pictures of a scene's cast to the GPU server, for the image model's
edit (project cast). Used by `generate_frame` for a scene that shows characters or a place.

A character's picture is stored with a transparent backdrop (`services/background_removal.py`).
It is sent on plain white instead: what a server does with transparent pixels is not known, and
white is exactly what the picture was made on. A place's picture is sent as it is.

It runs at every start of a job, because the server deletes the inputs of a job when it ends, so
a job that is submitted again needs them again (`RemoteImageHandler.submit`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.db.models import Asset
from app.db.session import SessionLocal
from app.providers import image_generator
from app.services import background_removal, frame_images
from app.services import cast as cast_service
from app.services.storage import StorageError, get_storage


async def _one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def upload_references(
    base_url: str, references: Sequence[tuple[str, int]]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Uploads the pictures, in order, and returns the server's asset ids with a record of what
    was uploaded. `references` are `(kind, asset id)`: the characters' pictures first, in the
    scene's order, then the place's. Raises `GpuCallError` (an upload failed) or `StorageError`
    (a file is missing).
    """
    storage = get_storage()
    remote_ids: list[str] = []
    uploads: list[dict[str, Any]] = []
    for kind, asset_id in references:
        async with SessionLocal() as session:
            asset = await session.get(Asset, asset_id)
            await session.commit()
        if asset is None:
            raise StorageError("A reference picture is gone.")
        path = storage.get_path(asset.path)
        if not path.is_file():
            raise StorageError("A reference picture's file could not be found on disk.")

        filename = f"reference-{asset.id}.png"
        if kind == cast_service.CHARACTER:
            flat = await frame_images.run_pillow(background_removal.flatten_on_white, path)
            temp = await storage.receive(_one_chunk(flat), max_bytes=len(flat))
            try:
                remote_id = await image_generator.upload_reference(base_url, temp.path, filename)
            finally:
                storage.discard(temp)
            sent_bytes = temp.size_bytes
        else:
            remote_id = await image_generator.upload_reference(base_url, path, filename)
            sent_bytes = asset.size_bytes
        remote_ids.append(remote_id)
        uploads.append(
            {
                "asset_id": asset.id,
                "cast_kind": kind,
                "filename": filename,
                "size_bytes": sent_bytes,
                "flattened_on_white": kind == cast_service.CHARACTER,
                "remote_asset_id": remote_id,
            }
        )
    return remote_ids, uploads
