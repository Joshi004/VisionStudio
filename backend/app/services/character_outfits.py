"""The outfits of a library character, as the Character Lab manages them.

An outfit is a `character_named_look` (PHASE-016): a name, a short note that helps to pick it, a
description of what is worn, and the pictures made from the description. The character's own
`outfit` text is the implicit **default** outfit and has no row.

Where outfits come from: the story pipeline's look resolution (`source` is `ai`, with the project
it was made for), an explainer's presenter outfit text (the same resolution), and the author
here (`source` is `manual`).

**Deleting never changes a project.** A project reads outfit pictures from the frozen copy that
the character version it pinned holds (`LibraryCharacterVersion.named_looks`), and its
resolution points at the record by id. So a delete only sets `deleted_at`: the row, the pictures
and every version stay, the slug stays taken, and the outfit is no longer listed, offered,
resolved to or frozen into a new version.

**Editing never changes pictures that exist.** A new description makes the pictures "out of
date" (worked out on every read from the prompt the pictures were made with); making them again
adds a newer look, and a newer version of the character that new projects pin.

Pure reads and writes of rows, no model call and no GPU call. Pictures are started by
`start_pictures`, through the Character Lab's own look jobs (`character_looks.start_look`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CharacterLook,
    CharacterNamedLook,
    LibraryCharacter,
    LookStateResolution,
    Project,
    ProjectCastCharacter,
    ProjectCharacterLink,
)
from app.db.types import utcnow
from app.services import character_images, character_looks, character_versions
from app.services import look_state_edit_prompts as prompts
from app.services.look_state_resolution_writer import (
    DESCRIPTION_MAX_CHARS,
    NAME_MAX_CHARS,
    SLUG_PATTERN,
)

_logger = logging.getLogger(__name__)

NOTE_MAX_CHARS: Final = 120
SOURCE_MANUAL: Final = "manual"
DEFAULT_SLUG: Final = "default"

PicturesStatus = Literal["none", "in_progress", "ready", "failed"]

_IN_USE: Final = "Pictures are already being made for this outfit."
_SLUG_JUNK: Final = re.compile(r"[^a-z0-9]+")


class OutfitError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class ProjectRef:
    project_id: int
    project_name: str


@dataclass
class OutfitEntry:
    """One saved outfit of a character, with everything the Lab shows about it."""

    record: CharacterNamedLook
    # The look that holds the finished pictures (`record.look_id`), or None.
    look: CharacterLook | None
    pictures: PicturesStatus
    pictures_out_of_date: bool
    # The project whose resolution made the outfit, while that project still exists.
    made_for: ProjectRef | None
    used_by: list[ProjectRef] = field(default_factory=list)
    # Why pictures cannot be made now, or None when they can.
    blocked_reason: str | None = None
    # Whether these pictures are the character's current look, so the outfit is the default.
    is_default_now: bool = False


# --- Small helpers --------------------------------------------------------------------------


def _clean_line(value: str | None) -> str | None:
    """The text on one line with single spaces, or None when it is blank."""
    if value is None or not value.strip():
        return None
    return " ".join(value.split())


def _check_name(name: str | None) -> str:
    text = _clean_line(name)
    if text is None:
        raise OutfitError("Give the outfit a name.")
    if len(text) > NAME_MAX_CHARS:
        raise OutfitError(f"The name must be at most {NAME_MAX_CHARS} characters.")
    return text


def _check_note(note: str | None) -> str | None:
    text = _clean_line(note)
    if text is not None and len(text) > NOTE_MAX_CHARS:
        raise OutfitError(f"The note must be at most {NOTE_MAX_CHARS} characters.")
    return text


def _check_description(description: str | None) -> str:
    text = _clean_line(description)
    if text is None:
        raise OutfitError("Describe what the outfit is: the clothes and accessories.")
    if len(text) > DESCRIPTION_MAX_CHARS:
        raise OutfitError(f"The description must be at most {DESCRIPTION_MAX_CHARS} characters.")
    return text


def make_slug(name: str, taken: set[str]) -> str:
    """A slug for `name` that is not in `taken`: lowercase letters, digits and underscores,
    starting with a letter, at most 40 characters, never `default`.
    """
    base = _SLUG_JUNK.sub("_", name.lower()).strip("_")
    if not base or not base[0].isalpha():
        base = f"outfit_{base}".rstrip("_")
    base = base[:34].rstrip("_")
    candidate = base
    number = 2
    while candidate in taken or candidate == DEFAULT_SLUG or not SLUG_PATTERN.match(candidate):
        candidate = f"{base}_{number}"
        number += 1
    return candidate


async def get_outfit(session: AsyncSession, outfit_id: int) -> CharacterNamedLook | None:
    """The outfit with this id as the database has it now, deleted or not."""
    statement = (
        select(CharacterNamedLook)
        .where(CharacterNamedLook.id == outfit_id)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


# --- Reading --------------------------------------------------------------------------------


async def _newest_looks(session: AsyncSession, outfit_ids: list[int]) -> dict[int, CharacterLook]:
    """The newest look made for each outfit."""
    if not outfit_ids:
        return {}
    statement = (
        select(CharacterLook)
        .where(CharacterLook.named_look_id.in_(outfit_ids))
        .order_by(CharacterLook.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[int, CharacterLook] = {}
    for look in (await session.execute(statement)).scalars():
        if look.named_look_id is not None and look.named_look_id not in newest:
            newest[look.named_look_id] = look
    return newest


async def _pictures_status(session: AsyncSession, newest: CharacterLook | None) -> PicturesStatus:
    if newest is None:
        return "none"
    if newest.status == "ready":
        return "ready"
    progress = await character_images.look_progress(session, newest)
    return "in_progress" if progress.stage is not None else "failed"


def _out_of_date(
    record: CharacterNamedLook, finished: CharacterLook | None, newest: CharacterLook | None
) -> bool:
    """Whether the pictures were made from another description than the outfit has now. The
    newest attempt counts, unless it failed: then the finished pictures do.
    """
    basis = newest if newest is not None and newest.status != "failed" else finished
    if basis is None or basis.prompt is None:
        return False
    if basis.named_look_id != record.id:
        # Pictures that were not made for this outfit (the character's earlier default) have
        # no description to compare with.
        return False
    try:
        expected = prompts.look_edit_prompt(record.description).strip()
    except ValueError:
        return False
    return basis.prompt.strip() != expected


async def _front_picture_id(session: AsyncSession, character: LibraryCharacter) -> int | None:
    """The lab image of the front picture of the character's current look, or None."""
    if character.current_look_id is None:
        return None
    look = await session.get(CharacterLook, character.current_look_id)
    if look is None or look.status != "ready":
        return None
    for reference in await character_looks.references_for_look(session, look.id):
        if reference.angle == "front" and reference.lab_image_id is not None:
            return reference.lab_image_id
    return None


def _blocker(
    character: LibraryCharacter, front_id: int | None, status: PicturesStatus
) -> str | None:
    if status == "in_progress":
        return _IN_USE
    if character.archived:
        return "The character is archived. Unarchive it first."
    if front_id is None:
        return "Make the character's look first: outfits are drawn from its front picture."
    return None


async def _project_names(session: AsyncSession, project_ids: set[int]) -> dict[int, str]:
    if not project_ids:
        return {}
    found = await session.execute(
        select(Project.id, Project.name).where(Project.id.in_(project_ids))
    )
    return {project_id: name for project_id, name in found.all()}


async def _used_by(
    session: AsyncSession, character_id: int, records: list[CharacterNamedLook]
) -> dict[int, set[int]]:
    """The ids of the projects that use each outfit: the project whose newest resolution
    points at it, and an explainer whose presenter wears it.
    """
    outfit_ids = {record.id for record in records}
    used: dict[int, set[int]] = {outfit_id: set() for outfit_id in outfit_ids}
    if not outfit_ids:
        return used

    picked = await session.execute(
        select(Project.id, Project.presenter_named_look_id).where(
            Project.presenter_named_look_id.in_(outfit_ids)
        )
    )
    for project_id, outfit_id in picked.all():
        used[outfit_id].add(project_id)

    candidates: set[int] = {
        record.origin_project_id for record in records if record.origin_project_id is not None
    }
    for model in (ProjectCharacterLink, ProjectCastCharacter):
        found = await session.execute(
            select(model.project_id).where(model.character_id == character_id)
        )
        candidates.update(found.scalars().all())
    for project_id in candidates:
        newest = (
            (
                await session.execute(
                    select(LookStateResolution)
                    .where(LookStateResolution.project_id == project_id)
                    .order_by(LookStateResolution.version.desc())
                    .limit(1)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .first()
        )
        if newest is None or not isinstance(newest.content, dict):
            continue
        for scene in newest.content.get("scenes") or []:
            for look in scene.get("looks") or []:
                look_id = look.get("look_id")
                if look_id in outfit_ids:
                    used[look_id].add(project_id)
    return used


async def list_outfits(session: AsyncSession, character_id: int) -> list[OutfitEntry]:
    """The saved outfits of a character that are not deleted, oldest first. Raises OutfitError
    when the character does not exist.
    """
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise OutfitError(f"There is no character {character_id}.")
    statement = (
        select(CharacterNamedLook)
        .where(
            CharacterNamedLook.character_id == character_id,
            CharacterNamedLook.deleted_at.is_(None),
        )
        .order_by(CharacterNamedLook.id)
        .execution_options(populate_existing=True)
    )
    records = list((await session.execute(statement)).scalars().all())
    newest = await _newest_looks(session, [record.id for record in records])
    used = await _used_by(session, character_id, records)
    project_ids = {project_id for ids in used.values() for project_id in ids}
    project_ids.update(r.origin_project_id for r in records if r.origin_project_id is not None)
    names = await _project_names(session, project_ids)
    front_id = await _front_picture_id(session, character)

    entries: list[OutfitEntry] = []
    for record in records:
        finished = await session.get(CharacterLook, record.look_id) if record.look_id else None
        latest = newest.get(record.id)
        status = await _pictures_status(session, latest)
        if status == "none" and finished is not None and finished.status == "ready":
            status = "ready"
        origin = record.origin_project_id
        entries.append(
            OutfitEntry(
                record=record,
                look=finished,
                pictures=status,
                pictures_out_of_date=_out_of_date(record, finished, latest),
                made_for=(
                    ProjectRef(origin, names[origin])
                    if origin is not None and origin in names
                    else None
                ),
                used_by=[
                    ProjectRef(project_id, names[project_id])
                    for project_id in sorted(used[record.id])
                    if project_id in names
                ],
                blocked_reason=_blocker(character, front_id, status),
                is_default_now=(
                    record.look_id is not None and record.look_id == character.current_look_id
                ),
            )
        )
    return entries


# --- Writing --------------------------------------------------------------------------------


async def create_outfit(
    session: AsyncSession,
    character_id: int,
    *,
    name: str | None,
    note: str | None,
    description: str | None,
) -> CharacterNamedLook:
    """Saves a new outfit by hand and commits. Its pictures are made on request. Raises
    OutfitError.
    """
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise OutfitError(f"There is no character {character_id}.")
    checked_name = _check_name(name)
    checked_note = _check_note(note)
    checked_description = _check_description(description)
    # Every slug of the character counts as taken, deleted outfits included, so a pinned slug
    # can never point at a different outfit.
    taken = set(
        (
            await session.execute(
                select(CharacterNamedLook.slug).where(
                    CharacterNamedLook.character_id == character_id
                )
            )
        )
        .scalars()
        .all()
    )
    record = CharacterNamedLook(
        character_id=character_id,
        slug=make_slug(checked_name, taken),
        name=checked_name,
        note=checked_note,
        description=checked_description,
        source=SOURCE_MANUAL,
    )
    session.add(record)
    await session.commit()
    _logger.info("outfit %d created for character %d: %s", record.id, character_id, record.slug)
    return record


async def update_outfit(
    session: AsyncSession,
    outfit_id: int,
    *,
    name: str | None = None,
    note: str | None = None,
    description: str | None = None,
    change_note: bool = False,
) -> CharacterNamedLook:
    """Edits an outfit's name, note or description and commits. `note` is changed only when
    `change_note` is true (a blank note then clears it). Raises OutfitError.

    No picture, version or project is touched: new pictures are made on request.
    """
    record = await get_outfit(session, outfit_id)
    if record is None or record.deleted_at is not None:
        raise OutfitError(f"There is no outfit {outfit_id}.")
    if name is not None:
        record.name = _check_name(name)
    if change_note:
        record.note = _check_note(note)
    if description is not None:
        record.description = _check_description(description)
    record.updated_at = utcnow()
    await session.commit()
    _logger.info("outfit %d edited", record.id)
    return record


async def delete_outfit(session: AsyncSession, outfit_id: int) -> None:
    """Hides an outfit and commits. The row, its pictures and every version that froze it stay,
    so no project changes. Deleting an outfit twice is not an error. Raises OutfitError when
    there is no such outfit.
    """
    record = await get_outfit(session, outfit_id)
    if record is None:
        raise OutfitError(f"There is no outfit {outfit_id}.")
    if record.deleted_at is None:
        record.deleted_at = utcnow()
        await session.commit()
        _logger.info("outfit %d deleted (hidden)", record.id)


async def start_pictures(session: AsyncSession, outfit_id: int) -> CharacterLook:
    """Starts the pictures of an outfit from the Lab: an edit of the front picture of the
    character's current look, then the other four angles, as a story project's pictures are
    made. Commits. Raises OutfitError.
    """
    record = await get_outfit(session, outfit_id)
    if record is None or record.deleted_at is not None:
        raise OutfitError(f"There is no outfit {outfit_id}.")
    character = await session.get(LibraryCharacter, record.character_id)
    if character is None:
        raise OutfitError("The character no longer exists.")
    newest = (await _newest_looks(session, [record.id])).get(record.id)
    status = await _pictures_status(session, newest)
    front_id = await _front_picture_id(session, character)
    blocked = _blocker(character, front_id, status)
    if blocked is not None or front_id is None:
        raise OutfitError(blocked or "The character has no front picture.")
    try:
        prompt = prompts.look_edit_prompt(record.description)
        return await character_looks.start_look(
            session,
            character.id,
            front_id,
            prompt=prompt,
            named_look_id=record.id,
        )
    except (character_looks.CharacterLookError, ValueError) as exc:
        raise OutfitError(str(exc)) from exc


def _cut_words(text: str, limit: int) -> str:
    """`text` cut at a word boundary to at most `limit` characters."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip()


async def make_default(session: AsyncSession, outfit_id: int) -> CharacterNamedLook:
    """Makes a saved outfit the character's default and commits: its description becomes the
    profile `outfit` and its pictures become the current look. The pictures that were the
    default are kept as a saved outfit (unless some outfit holds them already), so nothing is
    lost and the old default can be deleted like any other. One manual version freezes it all,
    and no project's pin moves. Raises OutfitError.
    """
    record = await get_outfit(session, outfit_id)
    if record is None or record.deleted_at is not None:
        raise OutfitError(f"There is no outfit {outfit_id}.")
    character = await session.get(LibraryCharacter, record.character_id)
    if character is None:
        raise OutfitError("The character no longer exists.")
    if character.archived:
        raise OutfitError("The character is archived. Unarchive it first.")

    entry = next(
        (e for e in await list_outfits(session, character.id) if e.record.id == record.id), None
    )
    if entry is None or entry.look is None or entry.look.status != "ready":
        raise OutfitError("Make this outfit's pictures first: the default needs pictures.")
    if entry.is_default_now:
        raise OutfitError("This outfit is the default already.")
    if entry.pictures != "ready":
        raise OutfitError("The pictures of this outfit are being made. Wait until they are ready.")
    if entry.pictures_out_of_date:
        raise OutfitError("The pictures of this outfit are out of date. Make them again first.")

    old_look = (
        await session.get(CharacterLook, character.current_look_id)
        if character.current_look_id is not None
        else None
    )
    if old_look is not None and old_look.status != "ready":
        raise OutfitError(
            "The character's current look is still being made. Wait until it is ready."
        )

    if old_look is not None:
        holder = await session.execute(
            select(CharacterNamedLook.id).where(
                CharacterNamedLook.character_id == character.id,
                CharacterNamedLook.look_id == old_look.id,
            )
        )
        if holder.first() is None:
            taken = set(
                (
                    await session.execute(
                        select(CharacterNamedLook.slug).where(
                            CharacterNamedLook.character_id == character.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            name = f"Earlier default (look v{old_look.version})"
            session.add(
                CharacterNamedLook(
                    character_id=character.id,
                    slug=make_slug(name, taken),
                    name=name,
                    note=f"Was the default until {utcnow().date().isoformat()}",
                    description=_cut_words(
                        _clean_line(character.outfit) or "The character's earlier usual outfit.",
                        DESCRIPTION_MAX_CHARS,
                    ),
                    source=SOURCE_MANUAL,
                    look_id=old_look.id,
                )
            )
            await session.flush()

    character.outfit = record.description
    character.current_look_id = record.look_id
    character.updated_at = utcnow()
    await character_versions.record_version_if_changed(session, character)
    await session.commit()
    _logger.info("outfit %d is now the default of character %d", record.id, character.id)
    return record
