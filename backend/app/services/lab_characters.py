"""The cast of the Talking character lab (Phase 24): characters that takes can reuse.

A character is a name, the picture that pins how it looks, a description in words (the language
model that writes a take's prompts cannot see the picture, so the description is all it knows),
and an optional default voice: a saved voice that clones or is directed, and/or a description
of a voice for a speech made from a description.

The picture is referred to by `{source: "lab" | "asset", id}` like a Video lab frame and is never
copied. A character is never deleted, like every stored file. This module never calls the GPU
server.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LabCharacter, Voice
from app.providers import speech_synthesizer
from app.services import video_lab
from app.services.video_lab import FirstFrameRef

NAME_MAX_CHARS: Final = 80
DESCRIPTION_MAX_CHARS: Final = 2000
VOICE_INSTRUCTION_MAX_CHARS: Final = speech_synthesizer.INSTRUCTION_MAX_CHARS
LIST_LIMIT: Final = 200

# The fields `update_character` accepts.
_UPDATABLE: Final = frozenset({"name", "description", "image", "voice_id", "voice_instruction"})


class CharacterInputError(Exception):
    """Something the request gets wrong. The message is meant for the user."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def clean_name(name: str) -> str:
    """The name without surrounding space. Raises CharacterInputError when blank or long."""
    name = name.strip()
    if not name:
        raise CharacterInputError(422, "Give the character a name.")
    if len(name) > NAME_MAX_CHARS:
        raise CharacterInputError(422, f"The name must be at most {NAME_MAX_CHARS} characters.")
    return name


def clean_description(description: str) -> str:
    """The description without surrounding space (it may be empty)."""
    description = description.strip()
    if len(description) > DESCRIPTION_MAX_CHARS:
        raise CharacterInputError(
            422, f"The description must be at most {DESCRIPTION_MAX_CHARS:,} characters."
        )
    return description


def clean_voice_instruction(instruction: str | None) -> str | None:
    """The voice description without surrounding space, or None when blank."""
    if instruction is None or not instruction.strip():
        return None
    instruction = instruction.strip()
    if len(instruction) > VOICE_INSTRUCTION_MAX_CHARS:
        raise CharacterInputError(
            422, f"The voice description must be at most {VOICE_INSTRUCTION_MAX_CHARS} characters."
        )
    return instruction


async def _checked_image(session: AsyncSession, ref: FirstFrameRef) -> dict[str, Any]:
    """The picture as it is stored on the row, after checking that it exists."""
    try:
        await video_lab.first_frame_path(session, ref)
    except video_lab.LabVideoInputError as exc:
        raise CharacterInputError(422, str(exc)) from exc
    return {"source": ref.source, "id": ref.id}


async def _checked_voice_id(session: AsyncSession, voice_id: int | None) -> int | None:
    if voice_id is not None and await session.get(Voice, voice_id) is None:
        raise CharacterInputError(422, f"There is no saved voice {voice_id}.")
    return voice_id


async def list_characters(session: AsyncSession) -> list[LabCharacter]:
    """The cast, newest first."""
    statement = (
        select(LabCharacter)
        .order_by(LabCharacter.id.desc())
        .limit(LIST_LIMIT)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars().all())


async def get_character(session: AsyncSession, character_id: int) -> LabCharacter | None:
    return await session.get(LabCharacter, character_id)


async def create_character(
    session: AsyncSession,
    *,
    name: str,
    description: str,
    image: FirstFrameRef,
    voice_id: int | None,
    voice_instruction: str | None,
) -> LabCharacter:
    """Checks the form and saves a character. Commits. Raises CharacterInputError."""
    character = LabCharacter(
        name=clean_name(name),
        description=clean_description(description),
        image=await _checked_image(session, image),
        voice_id=await _checked_voice_id(session, voice_id),
        voice_instruction=clean_voice_instruction(voice_instruction),
    )
    session.add(character)
    await session.commit()
    return character


async def update_character(
    session: AsyncSession, character_id: int, changes: Mapping[str, Any]
) -> LabCharacter:
    """Changes the fields named in `changes` (a subset of name, description, image, voice_id and
    voice_instruction; `voice_id` and `voice_instruction` may be None to clear them). Commits.
    Raises CharacterInputError.
    """
    unknown = set(changes) - _UPDATABLE
    if unknown:
        raise CharacterInputError(422, f"These fields cannot be changed: {sorted(unknown)}.")
    character = await session.get(LabCharacter, character_id)
    if character is None:
        raise CharacterInputError(404, f"Character {character_id} does not exist.")

    if "name" in changes:
        character.name = clean_name(changes["name"])
    if "description" in changes:
        character.description = clean_description(changes["description"])
    if "image" in changes:
        character.image = await _checked_image(session, changes["image"])
    if "voice_id" in changes:
        character.voice_id = await _checked_voice_id(session, changes["voice_id"])
    if "voice_instruction" in changes:
        character.voice_instruction = clean_voice_instruction(changes["voice_instruction"])
    await session.commit()
    return character
