"""Adopting another version of a library character or environment (PHASE-042).

A story project pins one version of each library character and environment it links
(`services/character_links.py`, `services/environment_links.py`). A pin never moves because of a
lab edit, so after the lab makes a newer version a project is behind. **Adopting** moves the pin
of chosen projects to a chosen version: from the lab for several projects at once, or from one
project for one entry (any version, newer or older).

Adopting only moves the pin. What depends on the pin goes out of date by the rules of PHASE-039
and is rebuilt by the user with "Regenerate out-of-date" (PHASE-040), project by project. Nothing
here starts a job or calls a model: every action is a database write that commits once.

**Provenance.** A version made by hand in the lab has no `inputs`, and the Character and
Environment Definition stages only count a pinned version as defined when its `inputs` name the
project and the entry (D-3). So a link also keeps `provenance_version`: the version whose
`inputs` still stand for the project's own definition. `effective_inputs` returns the pinned
version's own `inputs` when they name the project and the entry, and otherwise those of
`provenance_version`. The content (definition, pictures, voice) always comes from the pinned
version; only the record of what the story said comes from the provenance version, so a changed
story still marks the definition out of date.

**Complete projects.** A project is complete once it has a rendered final video (Q-9): a
`story_render` row exists, and renders are only stored when they succeed. In the lab's list a
project that is not complete and is behind the newest version is pre-selected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Job,
    LibraryCharacterVersion,
    LibraryEnvironmentVersion,
    Project,
    ProjectCharacterLink,
    ProjectEnvironmentLink,
    StoryRender,
)
from app.db.types import utcnow
from app.jobs import store

Kind = Literal["character", "environment"]


class AdoptionError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


class LinkNotFoundError(AdoptionError):
    """The project has no link for this entry."""


@dataclass(frozen=True)
class _KindInfo:
    """The tables and columns that differ between characters and environments."""

    label: str
    link_model: Any
    version_model: Any
    # The name of the column that holds the library item's id, on the link and on the version.
    item_column: str


_KINDS: Final[dict[str, _KindInfo]] = {
    "character": _KindInfo(
        "character", ProjectCharacterLink, LibraryCharacterVersion, "character_id"
    ),
    "environment": _KindInfo(
        "environment", ProjectEnvironmentLink, LibraryEnvironmentVersion, "environment_id"
    ),
}

_WORK_RUNNING: Final = "Work is running in this project. Wait for it to finish or stop it first."


@dataclass(frozen=True)
class Candidate:
    """One project that uses a library item, and whether it can adopt the newest version."""

    link: Any
    project_name: str
    newest_version: int | None
    # The project has a rendered final video (Q-9).
    complete: bool
    # Why the project cannot move to the newest version now, or None.
    blocked_reason: str | None

    @property
    def newer_version_available(self) -> bool:
        return self.newest_version is not None and self.newest_version > self.link.pinned_version

    @property
    def preselected(self) -> bool:
        """Ticked by default: not complete, behind the newest version, and able to adopt."""
        return not self.complete and self.newer_version_available and self.blocked_reason is None


# --- Provenance ------------------------------------------------------------------------------


def names_project(inputs: Any, project_id: int, discovery_id: str) -> bool:
    """Whether a version's `inputs` say it was written for this entry of this project."""
    return (
        isinstance(inputs, dict)
        and inputs.get("project_id") == project_id
        and inputs.get("discovery_id") == discovery_id
    )


def _item_id(kind: _KindInfo, link: Any) -> int:
    return int(getattr(link, kind.item_column))


async def _get_version(
    session: AsyncSession, kind: _KindInfo, item_id: int, version: int
) -> Any | None:
    statement = select(kind.version_model).where(
        getattr(kind.version_model, kind.item_column) == item_id,
        kind.version_model.version == version,
    )
    return (await session.execute(statement)).scalars().first()


async def effective_inputs(
    session: AsyncSession, kind: Kind, link: Any, pinned: Any | None
) -> dict[str, Any] | None:
    """The `inputs` that stand for the project's own definition of this entry: the pinned
    version's, when they name the project and the entry, and otherwise those of the link's
    `provenance_version`. None when there are none (a version made by hand and never defined
    by this project).
    """
    if pinned is not None and names_project(pinned.inputs, link.project_id, link.discovery_id):
        inputs: dict[str, Any] = pinned.inputs
        return inputs
    if link.provenance_version is None:
        return None
    info = _KINDS[kind]
    version = await _get_version(session, info, _item_id(info, link), link.provenance_version)
    if version is not None and names_project(version.inputs, link.project_id, link.discovery_id):
        inputs = version.inputs
        return inputs
    return None


async def _next_provenance(
    session: AsyncSession, info: _KindInfo, link: Any, target: Any
) -> int | None:
    """The `provenance_version` the link gets when its pin moves to `target`."""
    if names_project(target.inputs, link.project_id, link.discovery_id):
        return None  # the target carries the project's own provenance
    current = await _get_version(session, info, _item_id(info, link), link.pinned_version)
    if current is not None and names_project(current.inputs, link.project_id, link.discovery_id):
        return int(current.version)
    return link.provenance_version  # keep what the link already points at


# --- Reading ---------------------------------------------------------------------------------


async def _newest_version(session: AsyncSession, info: _KindInfo, item_id: int) -> Any | None:
    statement = (
        select(info.version_model)
        .where(getattr(info.version_model, info.item_column) == item_id)
        .order_by(info.version_model.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def _projects_with(
    session: AsyncSession, column: Any, project_ids: set[int], *where: Any
) -> set[int]:
    if not project_ids:
        return set()
    statement = select(column).where(column.in_(project_ids), *where).distinct()
    return {project_id for (project_id,) in await session.execute(statement) if project_id}


def _blocked_reason(link: Any, target: Any | None, kind: Kind, working: set[int]) -> str | None:
    """Why the link cannot move to `target` now. A link that already pins it is not blocked."""
    if target is None:
        return "There is no such version."
    if link.pinned_version == target.version:
        return None
    if link.project_id in working:
        return _WORK_RUNNING
    if kind == "environment" and target.reference_image_id is None:
        return f"Version {target.version} has no picture. Choose a picture for it in the lab first."
    return None


async def candidates(session: AsyncSession, kind: Kind, item_id: int) -> list[Candidate]:
    """The projects that use the library item, newest link first, each with whether it is
    complete and whether it can adopt the item's newest version now.
    """
    info = _KINDS[kind]
    link_model = info.link_model
    statement = (
        select(link_model, Project.name)
        .join(Project, Project.id == link_model.project_id)
        .where(getattr(link_model, info.item_column) == item_id)
        .order_by(link_model.id.desc())
        .execution_options(populate_existing=True)
    )
    rows = (await session.execute(statement)).all()
    newest = await _newest_version(session, info, item_id)
    project_ids = {link.project_id for link, _name in rows}
    complete = await _projects_with(session, StoryRender.project_id, project_ids)
    working = await _working_projects(session, project_ids)
    return [
        Candidate(
            link=link,
            project_name=name,
            newest_version=newest.version if newest is not None else None,
            complete=link.project_id in complete,
            blocked_reason=_blocked_reason(link, newest, kind, working) if newest else None,
        )
        for link, name in rows
    ]


# --- Adopting --------------------------------------------------------------------------------


async def _move(session: AsyncSession, info: _KindInfo, link: Any, target: Any) -> None:
    """Moves the link's pin to `target` and sets its provenance. Does not commit."""
    link.provenance_version = await _next_provenance(session, info, link, target)
    link.pinned_version = target.version
    link.updated_at = utcnow()


async def _working_projects(session: AsyncSession, project_ids: set[int]) -> set[int]:
    return await _projects_with(
        session, Job.project_id, project_ids, Job.status.in_(store.ACTIVE_STATUSES)
    )


async def adopt_many(
    session: AsyncSession, kind: Kind, item_id: int, version: int, project_ids: list[int]
) -> int:
    """Moves the pin of every listed project to `version` of the library item, all in one
    commit, and returns how many pins moved (a project that already pins it is skipped).
    Raises AdoptionError, writing nothing, when the version does not exist, a project does not
    use the item, or any project cannot adopt now (the message names it).
    """
    info = _KINDS[kind]
    target = await _get_version(session, info, item_id, version)
    if target is None:
        raise AdoptionError(f"There is no version {version} of this {info.label}.")
    statement = (
        select(info.link_model)
        .where(
            getattr(info.link_model, info.item_column) == item_id,
            info.link_model.project_id.in_(set(project_ids)),
        )
        .execution_options(populate_existing=True)
    )
    links = {link.project_id: link for link in (await session.execute(statement)).scalars()}
    names = {
        project_id: name
        for project_id, name in await session.execute(
            select(Project.id, Project.name).where(Project.id.in_(set(project_ids)))
        )
    }
    working = await _working_projects(session, set(project_ids))

    to_move: list[Any] = []
    for project_id in project_ids:
        link = links.get(project_id)
        if link is None:
            raise AdoptionError(f"Project {project_id} does not use this {info.label}.")
        reason = _blocked_reason(link, target, kind, working)
        if reason is not None:
            raise AdoptionError(f"{names.get(project_id, project_id)}: {reason}")
        if link.pinned_version != version:
            to_move.append(link)
    for link in to_move:
        await _move(session, info, link, target)
    if to_move:
        await session.commit()
    return len(to_move)


async def adopt_one(
    session: AsyncSession, kind: Kind, project_id: int, discovery_id: str, version: int
) -> None:
    """Moves one project's pin for one entry to `version` of the library item it is linked to.
    Commits. Raises LinkNotFoundError when the entry has no link, and AdoptionError when the
    version does not exist or the project cannot adopt now. A project that already pins the
    version is left alone.
    """
    info = _KINDS[kind]
    link_model = info.link_model
    statement = (
        select(link_model)
        .where(link_model.project_id == project_id, link_model.discovery_id == discovery_id)
        .execution_options(populate_existing=True)
    )
    link = (await session.execute(statement)).scalars().first()
    if link is None:
        raise LinkNotFoundError(f"'{discovery_id}' is not linked.")
    target = await _get_version(session, info, _item_id(info, link), version)
    working = await _working_projects(session, {project_id})
    reason = _blocked_reason(link, target, kind, working)
    if reason is not None:
        raise AdoptionError(reason)
    if link.pinned_version == version:
        return
    await _move(session, info, link, target)
    await session.commit()
