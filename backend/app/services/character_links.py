"""Links between a story project's discovered characters and library characters (PHASE-008).

Character discovery (`services/discovery.py`) lists the story's characters as `{id, name,
description}`. This module backs each of them with a Character Lab library character
(`library_character`) and pins one version of it (`library_character_version`), so the lab can
edit a character without silently changing a project (`Path_ahead.md` Section 11 and 38).

A link is a `project_character_link` row, found by `(project_id, discovery_id)`: the slug `id`
of the discovered character is the only thing that ties it to the list. So when discovery is
run again, a link is kept for every id that is still in the newest list, with no matching code
(the rule the owner chose: same id, nothing else). A new id starts unlinked, and a link whose
id is no longer in the list is kept and reported as `orphaned`, so it comes back if a later run
brings the id back.

There are two ways to link an entry of the newest list:

- **create**: a new library character is made from the entry
  (`character_library.create_from_discovery`) and its version 1 is pinned. `link_all` does that
  for every unlinked entry.
- **map**: an existing library character is chosen and its newest version is pinned. A
  character that has no version yet (made before PHASE-007) gets its version 1 written first,
  so there is always something to pin.

A pin never moves because of a lab edit: "a newer version is available" is worked out on read
by comparing the pin with the character's newest version (never stored, D-3). Moving a pin to a
newer version is adoption (PHASE-042). Mapping an entry to a different character pins that
character's newest version; mapping it to the character it already has changes nothing.

A project uses a library character for at most one discovered character, so "Young Arjun" and
"Arjun" stay two characters (D-14: relations are not stored). Nothing here starts a job or
calls a model: every action is a database write that commits once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CharacterDiscovery,
    LibraryCharacter,
    LibraryCharacterVersion,
    Project,
    ProjectCharacterLink,
)
from app.db.types import utcnow
from app.services import character_library, character_versions, discovery

_KIND: Final = "characters"


class CharacterLinkError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


class LinkNotFoundError(CharacterLinkError):
    """The entry has no link to remove."""


@dataclass(frozen=True)
class LinkInfo:
    """A link, with what is read from its library character."""

    link: ProjectCharacterLink
    character: LibraryCharacter
    # The number of the character's newest version, or None when it has none.
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
    # Links whose discovered character is not in the newest list.
    orphaned: list[LinkInfo]


@dataclass(frozen=True)
class Usage:
    """One project that uses a library character, as the lab shows it."""

    link: ProjectCharacterLink
    project_name: str
    newest_version: int | None

    @property
    def newer_version_available(self) -> bool:
        return self.newest_version is not None and self.newest_version > self.link.pinned_version


def _items(row: CharacterDiscovery) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], row.content[_KIND])


async def _newest_discovery(session: AsyncSession, project_id: int) -> CharacterDiscovery | None:
    return cast(CharacterDiscovery | None, await discovery.latest(session, _KIND, project_id))


async def _newest_versions(session: AsyncSession, character_ids: set[int]) -> dict[int, int]:
    """Each character's newest version number. A character with no version is left out."""
    if not character_ids:
        return {}
    statement = (
        select(LibraryCharacterVersion.character_id, func.max(LibraryCharacterVersion.version))
        .where(LibraryCharacterVersion.character_id.in_(character_ids))
        .group_by(LibraryCharacterVersion.character_id)
    )
    return {character_id: newest for character_id, newest in (await session.execute(statement))}


async def _project_links(session: AsyncSession, project_id: int) -> list[ProjectCharacterLink]:
    statement = (
        select(ProjectCharacterLink)
        .where(ProjectCharacterLink.project_id == project_id)
        .order_by(ProjectCharacterLink.id)
    )
    return list((await session.execute(statement)).scalars())


async def _link_infos(session: AsyncSession, links: list[ProjectCharacterLink]) -> list[LinkInfo]:
    character_ids = {link.character_id for link in links}
    characters: dict[int, LibraryCharacter] = {}
    if character_ids:
        found = await session.execute(
            select(LibraryCharacter).where(LibraryCharacter.id.in_(character_ids))
        )
        characters = {character.id: character for character in found.scalars()}
    newest = await _newest_versions(session, character_ids)
    return [
        LinkInfo(
            link=link,
            character=characters[link.character_id],
            newest_version=newest.get(link.character_id),
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
) -> tuple[CharacterDiscovery, dict[str, Any]]:
    """The newest discovered list, and the entry of it with this id. Raises CharacterLinkError."""
    newest = await _newest_discovery(session, project_id)
    if newest is None:
        raise CharacterLinkError("Find the characters first: there is nothing to link yet.")
    for item in _items(newest):
        if item["id"] == discovery_id:
            return newest, item
    raise CharacterLinkError(
        f"There is no character '{discovery_id}' in the newest list of characters."
    )


async def _link_for(
    session: AsyncSession, project_id: int, discovery_id: str
) -> ProjectCharacterLink | None:
    statement = select(ProjectCharacterLink).where(
        ProjectCharacterLink.project_id == project_id,
        ProjectCharacterLink.discovery_id == discovery_id,
    )
    return (await session.execute(statement)).scalars().first()


async def _commit(session: AsyncSession) -> None:
    """Commits. A unique key that is broken here means the same entry or character was linked
    by another request a moment ago, so the change is undone and the user is told to look again.
    """
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise CharacterLinkError(
            "The character was linked by another request at the same moment. "
            "Reload the page and try again."
        ) from exc


async def _create_one(
    session: AsyncSession, project_id: int, newest: CharacterDiscovery, item: dict[str, Any]
) -> ProjectCharacterLink:
    """Makes the library character for an unlinked entry and links it, pinning its version 1.
    Flushes; the caller commits.
    """
    try:
        character = await character_library.create_from_discovery(
            session,
            name=item["name"],
            description=item["description"],
            project_id=project_id,
            discovery_id=item["id"],
        )
    except character_library.CharacterLibraryError as exc:
        raise CharacterLinkError(str(exc)) from exc
    version = await character_versions.latest_version(session, character.id)
    assert version is not None  # `create_from_discovery` just wrote version 1
    link = ProjectCharacterLink(
        project_id=project_id,
        discovery_id=item["id"],
        character_id=character.id,
        pinned_version=version.version,
        how="created",
        discovery_version=newest.version,
    )
    session.add(link)
    await session.flush()
    return link


async def create(session: AsyncSession, project: Project, discovery_id: str) -> None:
    """Makes a new library character from the entry and pins its version 1. Commits. Raises
    CharacterLinkError when there is no such entry in the newest list or it is already linked.
    """
    newest, item = await _require_entry(session, project.id, discovery_id)
    if await _link_for(session, project.id, discovery_id) is not None:
        raise CharacterLinkError(f"'{discovery_id}' is already linked.")
    await _create_one(session, project.id, newest, item)
    await _commit(session)


async def link_all(session: AsyncSession, project: Project) -> int:
    """Makes a library character for every unlinked entry of the newest list, all in one
    commit, and returns how many were made (0 when everything is linked already). Raises
    CharacterLinkError when no list exists.
    """
    newest = await _newest_discovery(session, project.id)
    if newest is None:
        raise CharacterLinkError("Find the characters first: there is nothing to link yet.")
    linked = {link.discovery_id for link in await _project_links(session, project.id)}
    made = 0
    for item in _items(newest):
        if item["id"] in linked:
            continue
        await _create_one(session, project.id, newest, item)
        made += 1
    if made:
        await _commit(session)
    return made


async def map_to_existing(
    session: AsyncSession, project: Project, discovery_id: str, character_id: int
) -> None:
    """Links the entry to an existing library character and pins its newest version. Commits.
    Raises CharacterLinkError for an entry that is not in the newest list, a character that is
    missing or archived, or one that the project already uses for another entry.

    If the entry is already linked to this character, nothing changes (the pin stays where it
    is). If it is linked to another one, the link moves to this one.
    """
    newest, _item = await _require_entry(session, project.id, discovery_id)
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise CharacterLinkError(f"There is no character {character_id} in the Character Lab.")
    if character.archived:
        raise CharacterLinkError(
            f"{character.name} is archived. Unarchive it in the Character Lab to use it."
        )

    existing = await _link_for(session, project.id, discovery_id)
    if existing is not None and existing.character_id == character_id:
        return

    statement = select(ProjectCharacterLink).where(
        ProjectCharacterLink.project_id == project.id,
        ProjectCharacterLink.character_id == character_id,
    )
    used_for = (await session.execute(statement)).scalars().first()
    if used_for is not None:
        raise CharacterLinkError(
            f"{character.name} is already used for '{used_for.discovery_id}' in this project. "
            "Unlink that one first."
        )

    version = await character_versions.latest_version(session, character_id)
    if version is None:
        # A character made before versions existed: write its version 1 so there is one to pin.
        version = await character_versions.record_version_if_changed(session, character)
        assert version is not None  # a character with no version always gets one
    if existing is None:
        session.add(
            ProjectCharacterLink(
                project_id=project.id,
                discovery_id=discovery_id,
                character_id=character_id,
                pinned_version=version.version,
                how="mapped",
                discovery_version=newest.version,
            )
        )
    else:
        existing.character_id = character_id
        existing.pinned_version = version.version
        existing.how = "mapped"
        existing.discovery_version = newest.version
        existing.updated_at = utcnow()
    await _commit(session)


async def unlink(session: AsyncSession, project: Project, discovery_id: str) -> None:
    """Removes the link of this discovered character, whether or not it is in the newest list.
    The library character stays in the lab. Commits. Raises LinkNotFoundError.
    """
    link = await _link_for(session, project.id, discovery_id)
    if link is None:
        raise LinkNotFoundError(f"'{discovery_id}' is not linked.")
    await session.delete(link)
    await session.commit()


async def used_by(session: AsyncSession, character_id: int) -> list[Usage]:
    """The projects that use the library character, with the version each pins, newest link
    first.
    """
    statement = (
        select(ProjectCharacterLink, Project.name)
        .join(Project, Project.id == ProjectCharacterLink.project_id)
        .where(ProjectCharacterLink.character_id == character_id)
        .order_by(ProjectCharacterLink.id.desc())
    )
    rows = (await session.execute(statement)).all()
    newest = (await _newest_versions(session, {character_id})).get(character_id)
    return [Usage(link=link, project_name=name, newest_version=newest) for link, name in rows]
