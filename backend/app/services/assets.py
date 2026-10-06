"""Creates `asset` rows from stored files (DATABASE_STRUCTURE.md Section 4.2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset
from app.services.storage import StoredFile


async def add_asset(
    session: AsyncSession,
    *,
    project_id: int,
    kind: str,
    stored: StoredFile,
    mime: str,
    size_bytes: int,
    sha256: str,
    source: str,
    duration_s: float | None = None,
    width: int | None = None,
    height: int | None = None,
    provenance: Any | None = None,
) -> Asset:
    """Adds an asset row for a file already stored through `Storage`.

    Flushes so the new row has its id, but does not commit: the caller commits
    together with whatever else must change in the same transaction.
    """
    asset = Asset(
        project_id=project_id,
        kind=kind,
        path=stored.relative_path,
        mime=mime,
        size_bytes=size_bytes,
        duration_s=duration_s,
        width=width,
        height=height,
        sha256=sha256,
        source=source,
        provenance=provenance,
    )
    session.add(asset)
    await session.flush()
    return asset
