"""A story project's cast of library characters and environments (PHASE-048).

The user can put any number of Character Lab characters and Environment Lab environments in a
project's cast before the pipeline runs. The cast has three uses:

- Discovery (`services/discovery.py`) shows the model the cast, so it can say which discovered
  character or environment is one of them (an optional `library_id` on the entry).
- Linking (`services/character_links.py`, `services/environment_links.py`) maps an entry that
  has a `library_id` to that library item instead of making a new one.
- The later steps treat a linked cast member as already built (`reuse_mode`).

Every cast member has a mode: `as_is` keeps its definition, look and voice (or canonical
picture), `rewrite_text` keeps its look and voice (or picture) but writes the text definition
again for this story.

This module only reads and writes the two cast tables. It starts no job and calls no model.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final, Literal, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    LibraryCharacter,
    LibraryEnvironment,
    ProjectCastCharacter,
    ProjectCastEnvironment,
)

Kind = Literal["characters", "environments"]
Mode = Literal["as_is", "rewrite_text"]

MODES: Final[tuple[Mode, ...]] = ("as_is", "rewrite_text")
DEFAULT_MODE: Final[Mode] = "as_is"

# The most cast members of one kind. It is the most items discovery lists
# (`discovery_writer.MAX_ITEMS`), so the model is never shown more than it could use.
MAX_MEMBERS: Final = 30

# The most characters of the summary the model is shown for one cast member.
SUMMARY_MAX_CHARS: Final = 300


class CastError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


class CastMemberNotFoundError(CastError):
    """The library item is not in the cast."""


@dataclass(frozen=True)
class CastMember:
    """One cast member and the library item it names."""

    library_id: int
    name: str
    mode: Mode
    archived: bool
    # A short plain-text description of the library item, as the model is shown it.
    summary: str


def _one_line(text: str | None) -> str:
    return " ".join((text or "").split())


def _shorten(text: str) -> str:
    if len(text) <= SUMMARY_MAX_CHARS:
        return text
    return text[: SUMMARY_MAX_CHARS - 3].rstrip() + "..."


def _character_summary(character: LibraryCharacter) -> str:
    """Who the character is: species, age and gender, then what the author wrote about it."""
    facts = [_one_line(character.species), _one_line(character.gender)]
    if character.age is not None:
        facts.append(f"age {character.age}")
    head = ", ".join(fact for fact in facts if fact)
    detail = _one_line(character.notes) or _one_line(character.appearance)
    return _shorten("; ".join(part for part in (head, detail) if part))


def _environment_summary(environment: LibraryEnvironment) -> str:
    return _shorten(_one_line(environment.description) or _one_line(environment.atmosphere))


def _check_kind(kind: str) -> Kind:
    if kind not in ("characters", "environments"):
        raise CastError(f"Unknown kind '{kind}'.")
    return cast(Kind, kind)


def _check_mode(mode: str) -> Mode:
    if mode not in MODES:
        raise CastError(f"Unknown mode '{mode}'. Use one of: {', '.join(MODES)}.")
    return cast(Mode, mode)


async def _members(session: AsyncSession, project_id: int, kind: Kind) -> list[CastMember]:
    """The project's cast of this kind, oldest first."""
    if kind == "characters":
        rows = (
            await session.execute(
                select(ProjectCastCharacter, LibraryCharacter)
                .join(LibraryCharacter, LibraryCharacter.id == ProjectCastCharacter.character_id)
                .where(ProjectCastCharacter.project_id == project_id)
                .order_by(ProjectCastCharacter.id)
            )
        ).all()
        return [
            CastMember(
                library_id=character.id,
                name=character.name,
                mode=cast(Mode, row.mode),
                archived=character.archived,
                summary=_character_summary(character),
            )
            for row, character in rows
        ]
    env_rows = (
        await session.execute(
            select(ProjectCastEnvironment, LibraryEnvironment)
            .join(
                LibraryEnvironment, LibraryEnvironment.id == ProjectCastEnvironment.environment_id
            )
            .where(ProjectCastEnvironment.project_id == project_id)
            .order_by(ProjectCastEnvironment.id)
        )
    ).all()
    return [
        CastMember(
            library_id=environment.id,
            name=environment.name,
            mode=cast(Mode, row.mode),
            archived=environment.archived,
            summary=_environment_summary(environment),
        )
        for row, environment in env_rows
    ]


async def list_cast(session: AsyncSession, project_id: int, kind: Kind) -> list[CastMember]:
    """Every cast member of this kind, including archived library items (shown as archived)."""
    return await _members(session, project_id, _check_kind(kind))


async def usable_members(session: AsyncSession, project_id: int, kind: Kind) -> list[CastMember]:
    """The cast members discovery may use: the archived ones are left out, because an archived
    library item cannot be linked.
    """
    return [member for member in await _members(session, project_id, kind) if not member.archived]


async def cast_modes(session: AsyncSession, project_id: int, kind: Kind) -> dict[int, Mode]:
    """The mode of every usable cast member, by library id."""
    return {
        member.library_id: member.mode for member in await usable_members(session, project_id, kind)
    }


def reuse_mode(modes: dict[int, Mode], library_id: int, how: str) -> Mode | None:
    """The mode of a reused entry, or None when the entry is not reused.

    An entry is reused when it is linked as `mapped` to a library item that is in the project's
    cast. An item that the user mapped by hand without adding it to the cast is not reused, so
    the pipeline still asks before it overwrites it.
    """
    if how != "mapped":
        return None
    return modes.get(library_id)


def prompt_entries(members: list[CastMember]) -> list[dict[str, str | int]]:
    """What the model is shown for each cast member."""
    return [
        {"library_id": member.library_id, "name": member.name, "summary": member.summary}
        for member in members
    ]


def cast_sha256(members: list[CastMember]) -> str:
    """A hash of which library items are in the cast. Discovery records it, so a changed cast
    makes the discovered list out of date. The modes do not count: they change nothing the
    model is shown.
    """
    return cast_sha256_of_ids([member.library_id for member in members])


def cast_sha256_of_ids(library_ids: list[int]) -> str:
    """The same hash from library ids alone. The ids of library items that were deleted from
    the lab while in the cast (PHASE-055) are counted too, so a deletion does not change it.
    """
    return hashlib.sha256(json.dumps(sorted(set(library_ids))).encode("utf-8")).hexdigest()


# The hash of an empty cast: what a discovered list made before the cast existed is taken to
# have used, so no existing project becomes out of date.
EMPTY_CAST_SHA256: Final = cast_sha256([])


async def _library_item(
    session: AsyncSession, kind: Kind, library_id: int
) -> LibraryCharacter | LibraryEnvironment:
    """The library item. Raises CastError when it is missing or archived."""
    if kind == "characters":
        character = await session.get(LibraryCharacter, library_id)
        if character is None:
            raise CastError(f"There is no character {library_id} in the Character Lab.")
        if character.archived:
            raise CastError(
                f"{character.name} is archived. Unarchive it in the Character Lab to use it."
            )
        return character
    environment = await session.get(LibraryEnvironment, library_id)
    if environment is None:
        raise CastError(f"There is no environment {library_id} in the Environment Lab.")
    if environment.archived:
        raise CastError(
            f"{environment.name} is archived. Unarchive it in the Environment Lab to use it."
        )
    return environment


async def _row(
    session: AsyncSession, project_id: int, kind: Kind, library_id: int
) -> ProjectCastCharacter | ProjectCastEnvironment | None:
    if kind == "characters":
        statement = select(ProjectCastCharacter).where(
            ProjectCastCharacter.project_id == project_id,
            ProjectCastCharacter.character_id == library_id,
        )
    else:
        statement = select(ProjectCastEnvironment).where(
            ProjectCastEnvironment.project_id == project_id,
            ProjectCastEnvironment.environment_id == library_id,
        )
    return (await session.execute(statement)).scalars().first()


async def _count(session: AsyncSession, project_id: int, kind: Kind) -> int:
    if kind == "characters":
        statement = (
            select(func.count())
            .select_from(ProjectCastCharacter)
            .where(ProjectCastCharacter.project_id == project_id)
        )
    else:
        statement = (
            select(func.count())
            .select_from(ProjectCastEnvironment)
            .where(ProjectCastEnvironment.project_id == project_id)
        )
    return int((await session.execute(statement)).scalar_one())


async def add_member(
    session: AsyncSession,
    project_id: int,
    kind: Kind,
    library_id: int,
    mode: Mode = DEFAULT_MODE,
) -> None:
    """Adds a library item to the cast. Commits. If it is in the cast already, only its mode
    is set. Raises CastError for a missing or archived item, a full cast or an unknown mode.
    """
    kind = _check_kind(kind)
    mode = _check_mode(mode)
    await _library_item(session, kind, library_id)
    existing = await _row(session, project_id, kind, library_id)
    if existing is not None:
        existing.mode = mode
    else:
        if await _count(session, project_id, kind) >= MAX_MEMBERS:
            raise CastError(f"The cast can hold at most {MAX_MEMBERS} {kind}.")
        if kind == "characters":
            session.add(
                ProjectCastCharacter(project_id=project_id, character_id=library_id, mode=mode)
            )
        else:
            session.add(
                ProjectCastEnvironment(project_id=project_id, environment_id=library_id, mode=mode)
            )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise CastError(
            "The cast was changed by another request at the same moment. "
            "Reload the page and try again."
        ) from exc


async def set_mode(
    session: AsyncSession, project_id: int, kind: Kind, library_id: int, mode: Mode
) -> None:
    """Changes the mode of a cast member. Commits. Raises CastMemberNotFoundError when the item
    is not in the cast, and CastError for an unknown mode.
    """
    kind = _check_kind(kind)
    mode = _check_mode(mode)
    row = await _row(session, project_id, kind, library_id)
    if row is None:
        raise CastMemberNotFoundError("That item is not in the cast.")
    row.mode = mode
    await session.commit()


async def remove_member(
    session: AsyncSession, project_id: int, kind: Kind, library_id: int
) -> None:
    """Takes an item out of the cast. Commits. The library item and any link already made to it
    stay; the link is then no longer a reused one. Raises CastMemberNotFoundError when the item
    is not in the cast.
    """
    kind = _check_kind(kind)
    row = await _row(session, project_id, kind, library_id)
    if row is None:
        raise CastMemberNotFoundError("That item is not in the cast.")
    await session.delete(row)
    await session.commit()
