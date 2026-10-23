"""Deleting a story project, and choosing which of its characters and environments go with it
(PHASE-055).

Deleting the project row removes every story artifact and job of the project (ON DELETE
CASCADE), and its media folder `media/<project_id>/` holds the files they made. The library
characters and environments the project used are separate: they are offered for deletion too,
all ticked by default, and the user can untick any of them. An item that another project uses
as well is deleted just the same when it is ticked, and that other project is flagged
(`services/library_deletion.py`).

Order: everything that could refuse is checked first, then the project row is deleted and
committed, then the ticked library items, then the files. Once the project row is gone nothing
is refused any more: a problem with one library item or file is logged and the rest goes on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Job,
    LabVoiceRun,
    LibraryCharacter,
    LibraryEnvironment,
    Project,
    ProjectCastCharacter,
    ProjectCastEnvironment,
    ProjectCharacterLink,
    ProjectEnvironmentLink,
    ShotTake,
    StoryRender,
)
from app.jobs import store
from app.services import library_deletion
from app.services.library_deletion import Kind
from app.services.storage import Storage, StorageError

_logger = logging.getLogger(__name__)

How = Literal["created", "mapped", "cast", "made_for_project"]

_KINDS: Final[tuple[Kind, ...]] = ("character", "environment")


class ProjectDeletionError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


class ProjectBusyError(ProjectDeletionError):
    """The project has work running."""


class InvalidSelectionError(ProjectDeletionError):
    """A chosen item is not one of the project's."""


@dataclass(frozen=True)
class ItemPreview:
    """One library item the project used."""

    kind: Kind
    library_id: int
    name: str
    # created: made for the project by the pipeline. mapped: chosen from the library. cast: in
    # the project's cast only. made_for_project: made for it earlier and no longer linked.
    how: How
    archived: bool
    in_cast: bool
    # The names of the other projects that use it. They are flagged if it is deleted.
    other_projects: list[str]
    # Why it cannot be deleted now, or None.
    blocked_reason: str | None


@dataclass(frozen=True)
class ProjectPreview:
    """What the delete dialog shows. `blocked_reason` is set while the project has work running."""

    project_id: int
    name: str
    blocked_reason: str | None
    take_count: int
    render_count: int
    characters: list[ItemPreview]
    environments: list[ItemPreview]


async def _is_busy(session: AsyncSession, project_id: int) -> bool:
    found = await session.execute(
        select(Job.id)
        .where(Job.project_id == project_id, Job.status.in_(store.ACTIVE_STATUSES))
        .limit(1)
    )
    return found.first() is not None


async def _how_by_id(
    session: AsyncSession, kind: Kind, project_id: int
) -> tuple[dict[int, How], set[int]]:
    """The library ids the project used and how (a link, else the cast, else made for it), and
    which of them are in its cast.
    """
    how: dict[int, How] = {}
    if kind == "character":
        links = await session.execute(
            select(ProjectCharacterLink.character_id, ProjectCharacterLink.how).where(
                ProjectCharacterLink.project_id == project_id
            )
        )
        cast = await session.execute(
            select(ProjectCastCharacter.character_id).where(
                ProjectCastCharacter.project_id == project_id
            )
        )
        origin = await session.execute(
            select(LibraryCharacter.id).where(LibraryCharacter.origin_project_id == project_id)
        )
    else:
        links = await session.execute(
            select(ProjectEnvironmentLink.environment_id, ProjectEnvironmentLink.how).where(
                ProjectEnvironmentLink.project_id == project_id
            )
        )
        cast = await session.execute(
            select(ProjectCastEnvironment.environment_id).where(
                ProjectCastEnvironment.project_id == project_id
            )
        )
        origin = await session.execute(
            select(LibraryEnvironment.id).where(LibraryEnvironment.origin_project_id == project_id)
        )
    for library_id, link_how in links.all():
        how[library_id] = "created" if link_how == "created" else "mapped"
    in_cast = set(cast.scalars())
    for library_id in sorted(in_cast):
        how.setdefault(library_id, "cast")
    for library_id in origin.scalars():
        how.setdefault(library_id, "made_for_project")
    return how, in_cast


async def _item_previews(session: AsyncSession, kind: Kind, project_id: int) -> list[ItemPreview]:
    how_by_id, in_cast = await _how_by_id(session, kind, project_id)
    previews: list[ItemPreview] = []
    for library_id in sorted(how_by_id):
        item = (
            await session.get(LibraryCharacter, library_id)
            if kind == "character"
            else await session.get(LibraryEnvironment, library_id)
        )
        if item is None:
            continue
        info = await library_deletion.preview(
            session, kind, library_id, ignore_project_id=project_id
        )
        previews.append(
            ItemPreview(
                kind=kind,
                library_id=library_id,
                name=item.name,
                how=how_by_id[library_id],
                archived=item.archived,
                in_cast=library_id in in_cast,
                other_projects=[use.project_name for use in info.projects],
                blocked_reason=info.blocked_reason,
            )
        )
    return previews


async def preview(session: AsyncSession, project: Project) -> ProjectPreview:
    """Everything the user is asked about before the project is deleted."""
    busy = await _is_busy(session, project.id)
    characters = await _item_previews(session, "character", project.id)
    environments = await _item_previews(session, "environment", project.id)
    if busy:
        # The whole project is refused, so one reason says it all.
        characters = [_without_reason(item) for item in characters]
        environments = [_without_reason(item) for item in environments]
    takes = await session.execute(
        select(func.count()).select_from(ShotTake).where(ShotTake.project_id == project.id)
    )
    renders = await session.execute(
        select(func.count()).select_from(StoryRender).where(StoryRender.project_id == project.id)
    )
    return ProjectPreview(
        project_id=project.id,
        name=project.name,
        blocked_reason="Stop the pipeline and any running work of this project first."
        if busy
        else None,
        take_count=takes.scalar_one(),
        render_count=renders.scalar_one(),
        characters=characters,
        environments=environments,
    )


def _without_reason(item: ItemPreview) -> ItemPreview:
    return ItemPreview(
        kind=item.kind,
        library_id=item.library_id,
        name=item.name,
        how=item.how,
        archived=item.archived,
        in_cast=item.in_cast,
        other_projects=item.other_projects,
        blocked_reason=None,
    )


async def delete_project(
    session: AsyncSession,
    storage: Storage,
    project: Project,
    character_ids: list[int],
    environment_ids: list[int],
) -> None:
    """Deletes the project, the chosen characters and environments, and the files, and commits.

    Raises ProjectBusyError while the project has work running, InvalidSelectionError for an
    item that the project does not use, and LibraryItemBusyError for an item that cannot be
    deleted now. Nothing is deleted when any of these is raised.
    """
    if await _is_busy(session, project.id):
        raise ProjectBusyError("Stop the pipeline and any running work of this project first.")

    project_id = project.id
    allowed = {
        "character": set((await _how_by_id(session, "character", project_id))[0]),
        "environment": set((await _how_by_id(session, "environment", project_id))[0]),
    }
    chosen: list[tuple[Kind, int]] = []
    selection: list[tuple[Kind, list[int]]] = [
        ("character", character_ids),
        ("environment", environment_ids),
    ]
    for kind, ids in selection:
        for library_id in dict.fromkeys(ids):
            if library_id not in allowed[kind]:
                raise InvalidSelectionError(
                    f"The {kind} {library_id} is not used by this project, so it cannot be "
                    "deleted with it."
                )
            await library_deletion.ensure_deletable(
                session, kind, library_id, ignore_project_id=project_id
            )
            chosen.append((kind, library_id))

    # Speech samples made for the project stay in the Voice lab's tables after the project is
    # gone (the link is SET NULL), so they are found now.
    voice_runs = await session.execute(
        select(LabVoiceRun.id).where(LabVoiceRun.project_id == project_id)
    )
    voice_run_ids = set(voice_runs.scalars())

    await session.delete(project)
    await session.commit()
    _logger.info("project %d deleted; %d library item(s) chosen", project_id, len(chosen))

    for kind, library_id in chosen:
        try:
            await library_deletion.delete_item(session, storage, kind, library_id)
        except library_deletion.LibraryDeletionError:
            # Something started on it since the check. The project is already gone, so the
            # item stays in the library and the user can delete it there.
            await session.rollback()
            _logger.warning("could not delete %s %d with the project", kind, library_id)

    await library_deletion.remove_voice_runs(session, storage, voice_run_ids)
    try:
        await storage.delete_project_dir(project_id)
    except (StorageError, OSError):
        _logger.exception("could not remove the media folder of project %d", project_id)
