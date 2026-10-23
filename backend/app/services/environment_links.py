"""Links between a story project's discovered environments and library environments (PHASE-013).

Environment discovery (`services/discovery.py`) lists the story's places as `{id, name,
description}`. This module backs each of them with a Character Lab library environment
(`library_environment`) and pins one version of it (`library_environment_version`), so the lab
can edit an environment without silently changing a project (`Path_ahead.md` Section 13). It is
the environment twin of `services/character_links.py` and follows the same rules.

A link is a `project_environment_link` row, found by `(project_id, discovery_id)`: the slug `id`
of the discovered environment is the only thing that ties it to the list. So when discovery is
run again, a link is kept for every id that is still in the newest list, with no matching code
(the rule the owner chose for characters: same id, nothing else). A new id starts unlinked, and
a link whose id is no longer in the list is kept and reported as `orphaned`, so it comes back if
a later run brings the id back.

There are two ways to link an entry of the newest list:

- **create**: a new library environment is made from the entry
  (`environment_library.create_from_discovery`) and its version 1 is pinned. `link_all` does
  that for every unlinked entry.
- **map**: an existing library environment is chosen and its newest version is pinned.

A pin never moves because of a lab edit: "a newer version is available" is worked out on read
by comparing the pin with the environment's newest version (never stored, D-3). The pipeline's
own Environment Definition stage moves the pin to the version it writes
(`services/environment_definitions.save_definition`); moving a pin to a version a person made
in the lab is adoption (PHASE-042). Mapping an entry to a different environment pins that
environment's newest version; mapping it to the environment it already has changes nothing.

A project uses a library environment for at most one discovered environment. Nothing here
starts a job or calls a model: every action is a database write that commits once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    EnvironmentDiscovery,
    LibraryEnvironment,
    LibraryEnvironmentVersion,
    Project,
    ProjectEnvironmentLink,
)
from app.db.types import utcnow
from app.services import discovery, environment_library, environment_versions, project_cast

_KIND: Final = "environments"


class EnvironmentLinkError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


class LinkNotFoundError(EnvironmentLinkError):
    """The entry has no link to remove."""


@dataclass(frozen=True)
class LinkInfo:
    """A link, with what is read from its library environment."""

    link: ProjectEnvironmentLink
    environment: LibraryEnvironment
    # The number of the environment's newest version, or None when it has none.
    newest_version: int | None

    @property
    def newer_version_available(self) -> bool:
        """Whether the lab has made a version after the one the project pins."""
        return self.newest_version is not None and self.newest_version > self.link.pinned_version


@dataclass(frozen=True)
class EntryState:
    """One entry of the newest discovered list, and its link (None while it is unlinked)."""

    item: dict[str, Any]
    info: LinkInfo | None


@dataclass(frozen=True)
class LinksState:
    """What the story workspace shows. `discovery_version` is None when no list exists."""

    discovery_version: int | None
    entries: list[EntryState]
    # Links whose discovered environment is not in the newest list.
    orphaned: list[LinkInfo]


@dataclass(frozen=True)
class Usage:
    """One project that uses a library environment, as the lab shows it."""

    link: ProjectEnvironmentLink
    project_name: str
    newest_version: int | None

    @property
    def newer_version_available(self) -> bool:
        return self.newest_version is not None and self.newest_version > self.link.pinned_version


def _items(row: EnvironmentDiscovery) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], row.content[_KIND])


async def _newest_discovery(session: AsyncSession, project_id: int) -> EnvironmentDiscovery | None:
    return cast(EnvironmentDiscovery | None, await discovery.latest(session, _KIND, project_id))


async def _newest_versions(session: AsyncSession, environment_ids: set[int]) -> dict[int, int]:
    """Each environment's newest version number. An environment with no version is left out."""
    if not environment_ids:
        return {}
    statement = (
        select(
            LibraryEnvironmentVersion.environment_id,
            func.max(LibraryEnvironmentVersion.version),
        )
        .where(LibraryEnvironmentVersion.environment_id.in_(environment_ids))
        .group_by(LibraryEnvironmentVersion.environment_id)
    )
    return {environment_id: newest for environment_id, newest in (await session.execute(statement))}


async def _project_links(session: AsyncSession, project_id: int) -> list[ProjectEnvironmentLink]:
    statement = (
        select(ProjectEnvironmentLink)
        .where(ProjectEnvironmentLink.project_id == project_id)
        .order_by(ProjectEnvironmentLink.id)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars())


async def _link_infos(session: AsyncSession, links: list[ProjectEnvironmentLink]) -> list[LinkInfo]:
    environment_ids = {link.environment_id for link in links}
    environments: dict[int, LibraryEnvironment] = {}
    if environment_ids:
        found = await session.execute(
            select(LibraryEnvironment)
            .where(LibraryEnvironment.id.in_(environment_ids))
            .execution_options(populate_existing=True)
        )
        environments = {environment.id: environment for environment in found.scalars()}
    newest = await _newest_versions(session, environment_ids)
    return [
        LinkInfo(
            link=link,
            environment=environments[link.environment_id],
            newest_version=newest.get(link.environment_id),
        )
        for link in links
    ]


async def state(session: AsyncSession, project_id: int) -> LinksState:
    """The newest discovered list with each entry's link, and the links that are no longer in
    the list. Worked out on every read.
    """
    newest = await _newest_discovery(session, project_id)
    infos = await _link_infos(session, await _project_links(session, project_id))
    by_discovery_id = {info.link.discovery_id: info for info in infos}
    items = _items(newest) if newest is not None else []
    listed = {item["id"] for item in items}
    return LinksState(
        discovery_version=newest.version if newest is not None else None,
        entries=[EntryState(item=item, info=by_discovery_id.get(item["id"])) for item in items],
        orphaned=[info for info in infos if info.link.discovery_id not in listed],
    )


async def _require_entry(
    session: AsyncSession, project_id: int, discovery_id: str
) -> tuple[EnvironmentDiscovery, dict[str, Any]]:
    """The newest discovered list, and the entry of it with this id. Raises
    EnvironmentLinkError.
    """
    newest = await _newest_discovery(session, project_id)
    if newest is None:
        raise EnvironmentLinkError("Find the environments first: there is nothing to link yet.")
    for item in _items(newest):
        if item["id"] == discovery_id:
            return newest, item
    raise EnvironmentLinkError(
        f"There is no environment '{discovery_id}' in the newest list of environments."
    )


async def _link_for(
    session: AsyncSession, project_id: int, discovery_id: str
) -> ProjectEnvironmentLink | None:
    statement = select(ProjectEnvironmentLink).where(
        ProjectEnvironmentLink.project_id == project_id,
        ProjectEnvironmentLink.discovery_id == discovery_id,
    )
    return (await session.execute(statement)).scalars().first()


async def _commit(session: AsyncSession) -> None:
    """Commits. A unique key that is broken here means the same entry or environment was linked
    by another request a moment ago, so the change is undone and the user is told to look again.
    """
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise EnvironmentLinkError(
            "The environment was linked by another request at the same moment. "
            "Reload the page and try again."
        ) from exc


async def _create_one(
    session: AsyncSession, project_id: int, newest: EnvironmentDiscovery, item: dict[str, Any]
) -> ProjectEnvironmentLink:
    """Makes the library environment for an unlinked entry and links it, pinning its version 1.
    Flushes; the caller commits.
    """
    try:
        environment = await environment_library.create_from_discovery(
            session,
            name=item["name"],
            description=item["description"],
            project_id=project_id,
            discovery_id=item["id"],
        )
    except environment_library.EnvironmentLibraryError as exc:
        raise EnvironmentLinkError(str(exc)) from exc
    version = await environment_versions.latest_version(session, environment.id)
    assert version is not None  # `create_from_discovery` just wrote version 1
    link = ProjectEnvironmentLink(
        project_id=project_id,
        discovery_id=item["id"],
        environment_id=environment.id,
        pinned_version=version.version,
        how="created",
        discovery_version=newest.version,
    )
    session.add(link)
    await session.flush()
    return link


async def create(session: AsyncSession, project: Project, discovery_id: str) -> None:
    """Makes a new library environment from the entry and pins its version 1. Commits. Raises
    EnvironmentLinkError when there is no such entry in the newest list or it is already linked.
    """
    newest, item = await _require_entry(session, project.id, discovery_id)
    if await _link_for(session, project.id, discovery_id) is not None:
        raise EnvironmentLinkError(f"'{discovery_id}' is already linked.")
    await _create_one(session, project.id, newest, item)
    await _commit(session)


async def link_all(session: AsyncSession, project: Project) -> int:
    """Links every unlinked entry of the newest list, all in one commit, and returns how many
    were linked (0 when everything is linked already). Raises EnvironmentLinkError when no list
    exists.

    An entry that discovery matched to an environment of the project's cast (its `library_id`,
    PHASE-048) is mapped to that library environment. Every other entry gets a new library
    environment made from it.
    """
    newest = await _newest_discovery(session, project.id)
    if newest is None:
        raise EnvironmentLinkError("Find the environments first: there is nothing to link yet.")
    links = await _project_links(session, project.id)
    linked = {link.discovery_id for link in links}
    used = {link.environment_id for link in links}
    in_cast = await project_cast.cast_modes(session, project.id, _KIND)
    made = 0
    for item in _items(newest):
        if item["id"] in linked:
            continue
        library_id = item.get("library_id")
        if isinstance(library_id, int) and library_id in in_cast and library_id not in used:
            await _map_one(session, project.id, newest, item["id"], library_id)
            used.add(library_id)
        else:
            await _create_one(session, project.id, newest, item)
        made += 1
    if made:
        await _commit(session)
    return made


async def _map_one(
    session: AsyncSession,
    project_id: int,
    newest: EnvironmentDiscovery,
    discovery_id: str,
    environment_id: int,
) -> None:
    """Links the entry to an existing library environment and pins its newest version. Flushes;
    the caller commits. Raises EnvironmentLinkError for an environment that is missing or
    archived, or one that the project already uses for another entry.

    If the entry is already linked to this environment, nothing changes (the pin stays where it
    is). If it is linked to another one, the link moves to this one.
    """
    environment = await session.get(LibraryEnvironment, environment_id)
    if environment is None:
        raise EnvironmentLinkError(
            f"There is no environment {environment_id} in the Character Lab."
        )
    if environment.archived:
        raise EnvironmentLinkError(
            f"{environment.name} is archived. Unarchive it in the Character Lab to use it."
        )

    existing = await _link_for(session, project_id, discovery_id)
    if existing is not None and existing.environment_id == environment_id:
        return

    statement = select(ProjectEnvironmentLink).where(
        ProjectEnvironmentLink.project_id == project_id,
        ProjectEnvironmentLink.environment_id == environment_id,
    )
    used_for = (await session.execute(statement)).scalars().first()
    if used_for is not None:
        raise EnvironmentLinkError(
            f"{environment.name} is already used for '{used_for.discovery_id}' in this project. "
            "Unlink that one first."
        )

    version = await environment_versions.latest_version(session, environment_id)
    if version is None:
        # An environment with no version (cannot happen through the lab, which writes version 1
        # when it is created): write version 1 so there is one to pin.
        version = await environment_versions.record_version_if_changed(session, environment)
        assert version is not None  # an environment with no version always gets one
    if existing is None:
        session.add(
            ProjectEnvironmentLink(
                project_id=project_id,
                discovery_id=discovery_id,
                environment_id=environment_id,
                pinned_version=version.version,
                how="mapped",
                discovery_version=newest.version,
            )
        )
    else:
        existing.environment_id = environment_id
        existing.pinned_version = version.version
        existing.provenance_version = None  # a different environment: nothing carries over
        existing.how = "mapped"
        existing.discovery_version = newest.version
        existing.updated_at = utcnow()
    await session.flush()


async def map_to_existing(
    session: AsyncSession, project: Project, discovery_id: str, environment_id: int
) -> None:
    """Links the entry to an existing library environment and pins its newest version. Commits.
    Raises EnvironmentLinkError for an entry that is not in the newest list, an environment
    that is missing or archived, or one that the project already uses for another entry.

    If the entry is already linked to this environment, nothing changes (the pin stays where it
    is). If it is linked to another one, the link moves to this one.
    """
    newest, _item = await _require_entry(session, project.id, discovery_id)
    await _map_one(session, project.id, newest, discovery_id, environment_id)
    await _commit(session)


async def unlink(session: AsyncSession, project: Project, discovery_id: str) -> None:
    """Removes the link of this discovered environment, whether or not it is in the newest
    list. The library environment stays in the lab. Commits. Raises LinkNotFoundError.
    """
    link = await _link_for(session, project.id, discovery_id)
    if link is None:
        raise LinkNotFoundError(f"'{discovery_id}' is not linked.")
    await session.delete(link)
    await session.commit()


async def used_by(session: AsyncSession, environment_id: int) -> list[Usage]:
    """The projects that use the library environment, with the version each pins, newest link
    first.
    """
    statement = (
        select(ProjectEnvironmentLink, Project.name)
        .join(Project, Project.id == ProjectEnvironmentLink.project_id)
        .where(ProjectEnvironmentLink.environment_id == environment_id)
        .order_by(ProjectEnvironmentLink.id.desc())
        .execution_options(populate_existing=True)
    )
    rows = (await session.execute(statement)).all()
    newest = (await _newest_versions(session, {environment_id})).get(environment_id)
    return [Usage(link=link, project_name=name, newest_version=newest) for link, name in rows]
