"""The library characters and environments a project used that were deleted (PHASE-055).

`services/library_deletion.py` writes one `project_missing_library_item` row per project that
used the deleted item. This module reads and clears them for the link services
(`character_links`, `environment_links`):

- an entry of the newest discovered list that has such a row and no link is shown as "deleted
  from the library", and the pipeline does not make a new library item for it by itself;
- linking the entry again (creating it again, or picking another item) clears the row.

A row also written for an item that was only in the project's cast is kept after the link is
gone, because the cast hash counts it (`services/discovery.current_cast_sha256`).
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProjectMissingLibraryItem

Kind = Literal["character", "environment"]


async def by_discovery_id(
    session: AsyncSession, project_id: int, kind: Kind
) -> dict[str, ProjectMissingLibraryItem]:
    """The project's deleted items that are still waiting for their discovered entry to be
    linked again, by the entry's id.
    """
    rows = await session.execute(
        select(ProjectMissingLibraryItem).where(
            ProjectMissingLibraryItem.project_id == project_id,
            ProjectMissingLibraryItem.kind == kind,
            ProjectMissingLibraryItem.discovery_id.is_not(None),
        )
    )
    return {row.discovery_id: row for row in rows.scalars() if row.discovery_id is not None}


async def clear_for_entry(
    session: AsyncSession, project_id: int, kind: Kind, discovery_id: str
) -> None:
    """The entry is linked again: its deleted item no longer needs the user's attention. A row
    for an item that was in the cast stays, without the entry; any other row is removed.
    Flushes; the caller commits.
    """
    rows = await session.execute(
        select(ProjectMissingLibraryItem).where(
            ProjectMissingLibraryItem.project_id == project_id,
            ProjectMissingLibraryItem.kind == kind,
            ProjectMissingLibraryItem.discovery_id == discovery_id,
        )
    )
    row = rows.scalars().first()
    if row is None:
        return
    if row.in_cast:
        row.discovery_id = None
    else:
        await session.execute(
            delete(ProjectMissingLibraryItem).where(ProjectMissingLibraryItem.id == row.id)
        )
    await session.flush()
