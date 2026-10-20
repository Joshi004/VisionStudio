"""Immutable versions of a library character (PHASE-007).

`library_character` is the editable head of a character. Every time what defines the character
for production changes (its profile, its voice, or its current look), one
`library_character_version` row is added: a snapshot, never changed afterwards, so a project can
later pin a version and still read exactly what it was.

A version holds:

- the twelve **profile** fields (`PROFILE_FIELDS`);
- the **voice**: `voice_id` and `voice_description` (the description is kept because the
  definition stages write into it);
- the **look**: the current look's id and the exact picture of each of its angles
  (`look_references`). A `redo_angle` later updates the look's own `character_reference` row in
  place, which never touches a snapshot: an old version keeps showing the picture it had.

Archiving is not a version change.

`record_version_if_changed` is the only writer. It builds the snapshot of the character as it is
now and adds the next version only if that differs from the newest one, so saving the same form
twice makes no version. It adds and flushes but never commits: the caller commits the change and
its version together.

Only a **ready** look is frozen. While the current look is being redone (`making_angles`), its
pictures are half old and half new, so the newest version's look part is carried forward as it
is; the redo writes its own version once the look is ready again.

Numbering is the newest number plus one (the same way `character_looks` numbers looks), so two
changes committed at the very same moment could collide on `UNIQUE (character_id, version)` and
one of them would fail. With one backend process that is very unlikely, and it is accepted.

This module reads columns and writes version rows only. It starts no job and calls no model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CharacterLook,
    CharacterReference,
    LibraryCharacter,
    LibraryCharacterVersion,
)

# The profile columns a version freezes, in the order the profile form shows them.
PROFILE_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "age",
    "gender",
    "species",
    "era_kind",
    "era_years",
    "era_setting",
    "appearance",
    "outfit",
    "personality",
    "notes",
    "has_visible_mouth",
)

# What a version changed compared with the one before it. `created` is the first version.
Change = Literal["created", "profile", "look", "voice"]


@dataclass(frozen=True)
class Snapshot:
    """What a version freezes, before it is written."""

    profile: dict[str, Any]
    voice_id: int | None
    voice_description: str | None
    look_id: int | None
    look_references: list[dict[str, Any]]


@dataclass(frozen=True)
class VersionEntry:
    """A stored version and what it changed compared with the one before it."""

    version: LibraryCharacterVersion
    changes: list[Change]


async def latest_version(
    session: AsyncSession, character_id: int
) -> LibraryCharacterVersion | None:
    """The character's newest version, or None if it has none yet."""
    statement = (
        select(LibraryCharacterVersion)
        .where(LibraryCharacterVersion.character_id == character_id)
        .order_by(LibraryCharacterVersion.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def _look_part(
    session: AsyncSession,
    character: LibraryCharacter,
    newest: LibraryCharacterVersion | None,
) -> tuple[int | None, list[dict[str, Any]]]:
    """The look id and the angle pictures a snapshot freezes: the current look's, when it is
    ready; the newest version's, carried forward, while the current look is being redone; and
    nothing when the character has no look.
    """
    look = (
        await session.get(CharacterLook, character.current_look_id)
        if character.current_look_id is not None
        else None
    )
    if look is None:
        return None, []
    if look.status != "ready":
        if newest is None:
            return None, []
        return newest.look_id, list(newest.look_references)

    statement = select(CharacterReference).where(CharacterReference.look_id == look.id)
    references = (await session.execute(statement)).scalars().all()
    # Sorted by angle name: the same order every time, so two snapshots of the same pictures
    # compare equal. The API puts them in the display order when it reads them.
    pictures = [
        {
            "angle": reference.angle,
            "lab_image_id": reference.lab_image_id,
            "cutout_path": reference.cutout_path,
        }
        for reference in sorted(references, key=lambda reference: reference.angle)
        if reference.lab_image_id is not None
    ]
    return look.id, pictures


async def snapshot(
    session: AsyncSession,
    character: LibraryCharacter,
    newest: LibraryCharacterVersion | None,
) -> Snapshot:
    """The character as it is now, in the shape a version freezes. `newest` is its newest
    version (or None): the look part is carried forward from it while the look is being redone.
    """
    look_id, look_references = await _look_part(session, character, newest)
    return Snapshot(
        profile={field: getattr(character, field) for field in PROFILE_FIELDS},
        voice_id=character.voice_id,
        voice_description=character.voice_description,
        look_id=look_id,
        look_references=look_references,
    )


def _same(version: LibraryCharacterVersion, current: Snapshot) -> bool:
    return (
        version.profile == current.profile
        and version.voice_id == current.voice_id
        and version.voice_description == current.voice_description
        and version.look_id == current.look_id
        and version.look_references == current.look_references
    )


async def record_version_if_changed(
    session: AsyncSession, character: LibraryCharacter
) -> LibraryCharacterVersion | None:
    """Adds the character's next version when it differs from the newest one, and returns it;
    returns None when nothing that a version freezes has changed. Flushes (the character must
    already have an id) but does not commit: the caller commits the change with its version.
    """
    newest = await latest_version(session, character.id)
    current = await snapshot(session, character, newest)
    if newest is not None and _same(newest, current):
        return None
    version = LibraryCharacterVersion(
        character_id=character.id,
        version=(newest.version if newest is not None else 0) + 1,
        source="manual",
        profile=current.profile,
        voice_id=current.voice_id,
        voice_description=current.voice_description,
        look_id=current.look_id,
        look_references=current.look_references,
    )
    session.add(version)
    await session.flush()
    return version


def changes_between(
    previous: LibraryCharacterVersion | None, current: LibraryCharacterVersion
) -> list[Change]:
    """What `current` changed compared with `previous` (the version before it). Pure. The first
    version, with nothing before it, is `created`. Worked out when read, never stored.
    """
    if previous is None:
        return ["created"]
    changes: list[Change] = []
    if previous.profile != current.profile:
        changes.append("profile")
    if previous.look_id != current.look_id or previous.look_references != current.look_references:
        changes.append("look")
    if (
        previous.voice_id != current.voice_id
        or previous.voice_description != current.voice_description
    ):
        changes.append("voice")
    return changes


async def list_versions(session: AsyncSession, character_id: int) -> list[VersionEntry]:
    """Every version of the character, newest first, each with what it changed."""
    statement = (
        select(LibraryCharacterVersion)
        .where(LibraryCharacterVersion.character_id == character_id)
        .order_by(LibraryCharacterVersion.version.asc())
    )
    versions = (await session.execute(statement)).scalars().all()
    entries: list[VersionEntry] = []
    previous: LibraryCharacterVersion | None = None
    for version in versions:
        entries.append(VersionEntry(version=version, changes=changes_between(previous, version)))
        previous = version
    entries.reverse()
    return entries
