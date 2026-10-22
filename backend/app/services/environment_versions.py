"""Immutable versions of a library environment (PHASE-012, PHASE-013).

`library_environment` is the editable head of an environment. Every time its profile changes,
one `library_environment_version` row is added: a snapshot of the profile, never changed
afterwards, so a project can pin a version (PHASE-013) and still read exactly what it was.
This is the same shape as `character_versions.py`, with a profile and no voice or look.

A version holds:

- the seven **profile** fields (`PROFILE_FIELDS`);
- the structured **definition** the Environment Definition stage wrote (PHASE-013), as the head
  held it. A lab edit carries it forward unchanged;
- the pictures of the environment's **states** (PHASE-017, `states`): `[{slug, state_id,
  reference_image_id}]` for the states that have a picture;
- for a version the pipeline made, its provenance (D-3): `job_id` and `inputs`. A version made
  by hand has neither.

A version also holds its canonical reference picture (`reference_image_id`). That picture is
made for that version's text, so an edit never carries it forward: the new version starts with
none, and the older version keeps its own. The picture is set by
`environment_references.choose` (the author, in the lab) or by the pipeline's own attempt
(`environment_references.on_candidate_image_stored`); neither is a change of the profile, so
neither adds a version.

Archiving is not a version change.

`record_version_if_changed` is the only writer of a new version. It adds one only if what a
version freezes differs from the newest version's, so saving the same form twice makes no
version. A pipeline run also passes the `inputs` it was built from: the same content built from
different inputs (the story changed, and the model happened to give the same definition) is a
new version, so the version's provenance is never out of date for the run that asked. It adds
and flushes but never commits: the caller commits the change and its version together.

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

from app.db.models import EnvironmentState, LibraryEnvironment, LibraryEnvironmentVersion

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
Change = Literal["created", "profile", "definition", "states"]

# Who made the change: a person in the lab, or the pipeline from the model's text.
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


async def get_version(
    session: AsyncSession, environment_id: int, version: int
) -> LibraryEnvironmentVersion | None:
    """One version of the environment by its number, or None when there is no such version."""
    statement = select(LibraryEnvironmentVersion).where(
        LibraryEnvironmentVersion.environment_id == environment_id,
        LibraryEnvironmentVersion.version == version,
    )
    return (await session.execute(statement)).scalars().first()


async def _states_part(
    session: AsyncSession, environment: LibraryEnvironment
) -> list[dict[str, Any]]:
    """The pictures of the environment's states (PHASE-017) a version freezes, sorted by slug.
    A state with no picture yet is not in it.
    """
    statement = (
        select(EnvironmentState)
        .where(EnvironmentState.environment_id == environment.id)
        .where(EnvironmentState.reference_image_id.is_not(None))
        .order_by(EnvironmentState.slug)
        .execution_options(populate_existing=True)
    )
    return [
        {"slug": state.slug, "state_id": state.id, "reference_image_id": state.reference_image_id}
        for state in (await session.execute(statement)).scalars().all()
    ]


def _same(
    version: LibraryEnvironmentVersion,
    profile: dict[str, Any],
    definition: dict[str, Any] | None,
    states: list[dict[str, Any]],
    inputs: dict[str, Any] | None,
) -> bool:
    """Whether the version already holds what the environment freezes. A run that states its
    `inputs` also needs the version to have been built from those inputs.
    """
    return (
        version.profile == profile
        and version.definition == definition
        and (version.states or []) == states
        and (inputs is None or version.inputs == inputs)
    )


async def record_version_if_changed(
    session: AsyncSession,
    environment: LibraryEnvironment,
    *,
    source: Source = "manual",
    job_id: int | None = None,
    inputs: dict[str, Any] | None = None,
    carry_picture: bool = False,
    keep_picture: bool = False,
    new_picture: bool = False,
) -> LibraryEnvironmentVersion | None:
    """Adds the environment's next version when it differs from the newest one, and returns
    it; returns None when nothing that a version freezes has changed. Flushes (the environment
    must already have an id) but does not commit.

    `source` is `manual` for a change made by hand in the lab. The pipeline passes `ai` for the
    first version of an environment it makes from a discovered environment (PHASE-013), whose
    text came from the model, and for a version its Environment Definition stage writes,
    together with that job's `job_id` and the `inputs` the definition was built from (D-3).
    With `inputs`, the same content built from other inputs is a new version too.

    The version also freezes the pictures of the environment's states (PHASE-017). A new version
    starts with no canonical picture, because the picture was made for the old text; only a
    version written because a state's picture arrived passes `carry_picture`, and then, when
    the profile and the definition are the newest version's own, the canonical picture is
    carried forward, because it is still the picture of that same text.

    `keep_picture` carries the newest version's canonical picture forward even though the text
    changed. The Environment Definition stage passes it for an environment the user reuses from
    the library (PHASE-048): the picture is the look the user wants to keep, so the new text
    does not start a new one.

    `new_picture` (PHASE-039, "Replace picture") writes a version even though nothing it freezes
    changed, and it starts with no picture: the old picture stays with the old version, and a
    new one is made for this one. It never carries a picture forward.
    """
    newest = await latest_version(session, environment.id)
    profile = profile_of(environment)
    definition = environment.definition
    states = await _states_part(session, environment)
    if (
        not new_picture
        and newest is not None
        and _same(newest, profile, definition, states, inputs)
    ):
        return None
    same_text = newest is not None and newest.profile == profile and newest.definition == definition
    carried_picture = (
        newest.reference_image_id
        if newest is not None
        and not new_picture
        and (keep_picture or (carry_picture and same_text))
        else None
    )
    version = LibraryEnvironmentVersion(
        environment_id=environment.id,
        version=(newest.version if newest is not None else 0) + 1,
        source=source,
        profile=profile,
        definition=definition,
        states=states,
        reference_image_id=carried_picture,
        job_id=job_id,
        inputs=inputs,
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
    changes: list[Change] = []
    if previous.profile != current.profile:
        changes.append("profile")
    if previous.definition != current.definition:
        changes.append("definition")
    if (previous.states or []) != (current.states or []):
        changes.append("states")
    return changes


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
