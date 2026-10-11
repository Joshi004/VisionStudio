"""`/api/lab/characters`: the cast of the Talking character lab (Phase 24).

A character is a name, the picture that pins how it looks, a description in words and an
optional default voice. The picture is picked from what the Image lab holds (or a project's
frame) and referred to by `{source, id}`; it is never copied. Characters are listed, created and
changed, never deleted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.video_lab import FirstFrameIn, FirstFrameOut, frame_out, frame_urls_for
from app.api.voice_lab import VoiceBrief
from app.db.models import LabCharacter, Voice
from app.db.session import SessionDep
from app.services import lab_characters
from app.services.video_lab import FirstFrameRef

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
Id = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]
CharacterId = Annotated[int, Path(ge=1, le=_MAX_ID)]

_INVALID = {422: {"model": ErrorResponse, "description": "The form breaks a rule."}}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "There is no such character."}}

# Fields a PATCH may leave out, but may not set to null.
_NOT_NULLABLE: Final = ("name", "description", "image")


class CharacterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    # Who the character is and what they look like. The AI that writes prompts reads this.
    description: StrictStr = ""
    image: FirstFrameIn
    # The saved voice that speaks for the character (clone, or direction with an instruction).
    voice_id: Id | None = None
    # A description of the voice, for a speech made from a description (design).
    voice_instruction: StrictStr | None = None


class CharacterUpdate(BaseModel):
    """Only the fields that are sent change. `voice_id` and `voice_instruction` may be null."""

    model_config = ConfigDict(extra="forbid")

    name: StrictStr | None = None
    description: StrictStr | None = None
    image: FirstFrameIn | None = None
    voice_id: Id | None = None
    voice_instruction: StrictStr | None = None


class CharacterOut(BaseModel):
    id: int
    created_at: datetime
    name: str
    description: str
    # The picture, for a thumbnail. Its `url` is None when the image is gone.
    image: FirstFrameOut | None
    # The default saved voice. None when there is none, or when it is gone.
    voice: VoiceBrief | None
    voice_instruction: str | None


async def characters_out(
    session: AsyncSession, characters: list[LabCharacter]
) -> list[CharacterOut]:
    """The characters with their picture URLs and voice names."""
    urls = await frame_urls_for(session, (character.image for character in characters))
    voice_ids = {c.voice_id for c in characters if c.voice_id is not None}
    names: dict[int, str] = {}
    if voice_ids:
        found = await session.execute(select(Voice.id, Voice.name).where(Voice.id.in_(voice_ids)))
        names = {voice_id: name for voice_id, name in found.all()}
    return [
        CharacterOut(
            id=character.id,
            created_at=character.created_at,
            name=character.name,
            description=character.description,
            image=frame_out(character.image, urls),
            voice=(
                VoiceBrief(id=character.voice_id, name=names[character.voice_id])
                if character.voice_id is not None and character.voice_id in names
                else None
            ),
            voice_instruction=character.voice_instruction,
        )
        for character in characters
    ]


def _error(exc: lab_characters.CharacterInputError) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


@router.get("/lab/characters", response_model=list[CharacterOut])
async def list_characters(session: SessionDep) -> list[CharacterOut]:
    """The cast, newest first."""
    return await characters_out(session, await lab_characters.list_characters(session))


@router.post(
    "/lab/characters",
    response_model=CharacterOut,
    status_code=status.HTTP_201_CREATED,
    responses=_INVALID,
)
async def create_character(body: CharacterCreate, session: SessionDep) -> CharacterOut:
    """Saves a character."""
    try:
        character = await lab_characters.create_character(
            session,
            name=body.name,
            description=body.description,
            image=FirstFrameRef(source=body.image.source, id=body.image.id),
            voice_id=body.voice_id,
            voice_instruction=body.voice_instruction,
        )
    except lab_characters.CharacterInputError as exc:
        raise _error(exc) from exc
    return (await characters_out(session, [character]))[0]


@router.patch(
    "/lab/characters/{character_id}",
    response_model=CharacterOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def update_character(
    character_id: CharacterId, body: CharacterUpdate, session: SessionDep
) -> CharacterOut:
    """Changes the fields that are sent. The picture's file is never touched."""
    changes: dict[str, Any] = {}
    for field in body.model_fields_set:
        value = getattr(body, field)
        if value is None and field in _NOT_NULLABLE:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"The {field} cannot be cleared."
            )
        if field == "image" and value is not None:
            value = FirstFrameRef(source=value.source, id=value.id)
        changes[field] = value
    try:
        character = await lab_characters.update_character(session, character_id, changes)
    except lab_characters.CharacterInputError as exc:
        raise _error(exc) from exc
    return (await characters_out(session, [character]))[0]
