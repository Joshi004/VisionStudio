"""Immutable versions of a library environment (PHASE-012).

`library_environment` is the editable head of an environment. Every time its profile changes,
one `library_environment_version` row is added: a snapshot of the profile, never changed
afterwards, so a project can later pin a version (PHASE-013) and still read exactly what it was.
This is the same shape as `character_versions.py`, with a profile and no voice or look.

A version also holds its canonical reference picture (`reference_image_id`). That picture is
made for that version's text, so an edit never carries it forward: the new version starts with
none, and the older version keeps its own. The picture is set by
`environment_references.choose`, which only allows it on the environment's newest version.

Archiving is not a version change.

`record_version_if_changed` is the only writer of a new version. It adds one only if the
profile differs from the newest version's, so saving the same form twice makes no version. It
adds and flushes but never commits: the caller commits the change and its version together.

Numbering is the newest number plus one, so two changes committed at the very same moment could
collide on `UNIQUE (environment_id, version)` and one would fail. It is a single-user app and
the failure stores nothing wrong, so this is accepted (as for characters).

This module reads columns and writes version rows only. It starts no job and calls no model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LibraryEnvironment, LibraryEnvironmentVersion

# The profile columns a version freezes, in the order the form shows them.
PROFILE_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "description",
    "era_kind",
    "era_years",
    "era_setting",
    "atmosphere",
    "notes",
)

# What a version changed compared with the one before it. `created` is the first version.
Change = Literal["created", "profile"]

# Who made the change: a person in the lab, or (later) the pipeline.
Source = Literal["ai", "manual"]


@dataclass(frozen=True)
class VersionEntry:
    """A stored version and what it changed compared with the one before it."""

    version: LibraryEnvironmentVersion
    changes: list[Change]


def profile_of(environment: LibraryEnvironment) -> dict[str, Any]:
    """The environment's profile as a version freezes it."""
    return {field: getattr(environment, field) for field in PROFILE_FIELDS}


async def latest_version(
    session: AsyncSession, environment_id: int
) -> LibraryEnvironmentVersion | None:
    """The environment's newest version, or None if it has none yet."""
    statement = (
        select(LibraryEnvironmentVersion)
        .where(LibraryEnvironmentVersion.environment_id == environment_id)
        .order_by(LibraryEnvironmentVersion.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def record_version_if_changed(
    session: AsyncSession,
    environment: LibraryEnvironment,
    *,
    source: Source = "manual",
) -> LibraryEnvironmentVersion | None:
    """Adds the environment's next version when its profile differs from the newest one, and
    returns it; returns None when nothing a version freezes has changed. Flushes (the
    environment must already have an id) but does not commit.
    """
    newest = await latest_version(session, environment.id)
    current = profile_of(environment)
    if newest is not None and newest.profile == current:
        return None
    version = LibraryEnvironmentVersion(
        environment_id=environment.id,
        version=(newest.version if newest is not None else 0) + 1,
        source=source,
        profile=current,
    )
    session.add(version)
    await session.flush()
    return version


def changes_between(
    previous: LibraryEnvironmentVersion | None, current: LibraryEnvironmentVersion
) -> list[Change]:
    """What `current` changed compared with `previous` (the version before it). Pure. The first
    version, with nothing before it, is `created`. Worked out when read, never stored.
    """
    if previous is None:
        return ["created"]
    return ["profile"] if previous.profile != current.profile else []


async def list_versions(session: AsyncSession, environment_id: int) -> list[VersionEntry]:
    """Every version of the environment, newest first, each with what it changed."""
    statement = (
        select(LibraryEnvironmentVersion)
        .where(LibraryEnvironmentVersion.environment_id == environment_id)
        .order_by(LibraryEnvironmentVersion.version.asc())
        .execution_options(populate_existing=True)
    )
    versions = (await session.execute(statement)).scalars().all()
    entries: list[VersionEntry] = []
    previous: LibraryEnvironmentVersion | None = None
    for version in versions:
        entries.append(VersionEntry(version=version, changes=changes_between(previous, version)))
        previous = version
    entries.reverse()
    return entries
