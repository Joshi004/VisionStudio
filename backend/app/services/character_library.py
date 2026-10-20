"""The Character lab's own cast: a global, project-independent library of characters
(Phase 25).

A story project links each of its discovered characters to a `library_character` and pins one
of its versions (`services/character_links.py`, PHASE-008); `create_from_discovery` makes the
character for a link. (The narration cast tables this once stayed apart from are gone,
PHASE-046.) A character is never deleted, only archived, like every other row this app keeps
(voices, stored files).

`character_card` renders everything the look and take prompt writers need as one block of
plain English, so there is exactly one place that turns the row's columns into words.

Gender and species are a growable choice: a small set of suggestions, plus every value a
character already has, read fresh each time (`gender_options`, `species_options`). There is no
separate table of "known values" to keep in sync: the characters themselves are that list.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, LibraryCharacter, Voice
from app.db.types import utcnow
from app.jobs import store
from app.providers import speech_synthesizer
from app.services import character_versions, voice_lab, voices
from app.services.voice_lab import RunRow, VoiceLabForm, VoiceLabInputError

_logger = logging.getLogger(__name__)

# The job that writes a look's master image prompt, or a voice audition's sample line
# (`requested`: "master" | "audition"). One job type for both: both are a language model
# call that establishes one of the character's own identity assets.
PROMPT_JOB: Final = "write_character_look_prompt"

NAME_MAX_CHARS: Final = 80
GENDER_MAX_CHARS: Final = 40
SPECIES_MAX_CHARS: Final = 40
APPEARANCE_MAX_CHARS: Final = 2000
OUTFIT_MAX_CHARS: Final = 500
PERSONALITY_MAX_CHARS: Final = 1000
NOTES_MAX_CHARS: Final = 1000
ERA_SETTING_MAX_CHARS: Final = 200
MIN_AGE: Final = 0
MAX_AGE: Final = 2000
MIN_ERA_YEARS: Final = 1
MAX_ERA_YEARS: Final = 10_000
LIST_LIMIT: Final = 200

EraKind = Literal["present", "past", "future"]
ERA_KINDS: Final[tuple[EraKind, ...]] = ("present", "past", "future")

VOICE_DESCRIPTION_MAX_CHARS: Final = speech_synthesizer.INSTRUCTION_MAX_CHARS
# How many design-mode samples one audition makes, to choose from.
AUDITION_SAMPLE_COUNT: Final = 3

Framing = Literal["close_up", "medium", "wide"]
FRAMINGS: Final[tuple[Framing, ...]] = ("close_up", "medium", "wide")
Angle = Literal["front", "three_quarter", "profile", "back", "face"]
ANGLES: Final[tuple[Angle, ...]] = ("front", "three_quarter", "profile", "back", "face")

# Pre-seeded suggestions. Growable: `gender_options` and `species_options` add every distinct
# value a character already has, so a value anyone has typed stays offered to the next author.
GENDER_SUGGESTIONS: Final[tuple[str, ...]] = ("female", "male", "non-binary", "none")
SPECIES_SUGGESTIONS: Final[tuple[str, ...]] = (
    "human",
    "robot",
    "alien",
    "fish",
    "dog",
    "cat",
    "bird",
    "dragon",
)

# Which reference angles a take's picture or video uses, at most 2 per character (leaves room
# for more characters sharing a picture, later).
_ANGLES_FOR_FRAMING: Final[dict[Framing, tuple[Angle, ...]]] = {
    "close_up": ("face", "three_quarter"),
    "medium": ("front", "three_quarter"),
    "wide": ("front",),
}


class CharacterLibraryError(ValueError):
    """Something the form gets wrong. The message is meant for the user (HTTP 422)."""


@dataclass(frozen=True)
class CharacterForm:
    """What the profile step of the drawer, or an edit, sends."""

    name: str
    age: int | None
    gender: str
    species: str
    era_kind: EraKind
    era_years: int | None
    era_setting: str | None
    appearance: str
    outfit: str | None
    personality: str | None
    notes: str | None
    has_visible_mouth: bool


def _clean(value: str | None) -> str | None:
    return None if value is None or not value.strip() else " ".join(value.split())


def _too_long(value: str | None, limit: int, what: str) -> None:
    if value is not None and len(value) > limit:
        raise CharacterLibraryError(f"The {what} must be at most {limit:,} characters.")


def validate_form(form: CharacterForm) -> None:
    """Raises CharacterLibraryError for a form no character should be saved with."""
    if not form.name.strip():
        raise CharacterLibraryError("Give the character a name.")
    _too_long(form.name, NAME_MAX_CHARS, "name")
    if not form.species.strip():
        raise CharacterLibraryError("Give the character a species.")
    _too_long(form.species, SPECIES_MAX_CHARS, "species")
    if not form.appearance.strip():
        raise CharacterLibraryError("Describe the character's appearance.")
    _too_long(form.appearance, APPEARANCE_MAX_CHARS, "appearance")
    _too_long(form.gender, GENDER_MAX_CHARS, "gender")
    _too_long(form.outfit, OUTFIT_MAX_CHARS, "outfit")
    _too_long(form.personality, PERSONALITY_MAX_CHARS, "personality")
    _too_long(form.notes, NOTES_MAX_CHARS, "notes")
    _too_long(form.era_setting, ERA_SETTING_MAX_CHARS, "era setting")
    if form.age is not None and not MIN_AGE <= form.age <= MAX_AGE:
        raise CharacterLibraryError(f"Age must be from {MIN_AGE} to {MAX_AGE:,}.")
    if form.era_kind not in ERA_KINDS:
        raise CharacterLibraryError("Choose present, past or future.")
    if form.era_kind == "present":
        if form.era_years is not None:
            raise CharacterLibraryError("The present has no number of years: leave it out.")
    elif form.era_years is None or not MIN_ERA_YEARS <= form.era_years <= MAX_ERA_YEARS:
        raise CharacterLibraryError(
            f"Give the number of years, from {MIN_ERA_YEARS} to {MAX_ERA_YEARS:,}."
        )


def _apply(character: LibraryCharacter, form: CharacterForm) -> None:
    character.name = form.name.strip()
    character.age = form.age
    character.gender = _clean(form.gender) or ""
    character.species = form.species.strip()
    character.era_kind = form.era_kind
    character.era_years = form.era_years
    character.era_setting = _clean(form.era_setting)
    character.appearance = form.appearance.strip()
    character.outfit = _clean(form.outfit)
    character.personality = _clean(form.personality)
    character.notes = _clean(form.notes)
    character.has_visible_mouth = form.has_visible_mouth


async def create_character(session: AsyncSession, form: CharacterForm) -> LibraryCharacter:
    """Checks the form and saves a new character, as its version 1. Commits. Raises
    CharacterLibraryError.
    """
    validate_form(form)
    character = LibraryCharacter(name="", species="")
    _apply(character, form)
    session.add(character)
    await session.flush()  # the character's id, for its first version
    await character_versions.record_version_if_changed(session, character)
    await session.commit()
    _logger.info("character %d created: %s", character.id, character.name)
    return character


async def create_from_discovery(
    session: AsyncSession,
    *,
    name: str,
    description: str,
    project_id: int,
    discovery_id: str,
) -> LibraryCharacter:
    """Makes a library character from a story project's discovered character (PHASE-008), as
    its version 1 (`source` is `ai`, because the text came from the model). Flushes but does
    not commit: the caller commits it together with the link, so a character is never made
    without its link. Raises CharacterLibraryError.

    The discovery gives only a name and one line. The name becomes the name and the line
    becomes the notes. The species and the appearance stay empty until the Character
    Definition stage writes them (PHASE-009), so the lab form's rule that both are given is not
    applied here (editing the character in the lab still asks for them). The character is
    marked with the project and the discovered character it came from.
    """
    clean_name = _clean(name)
    if clean_name is None:
        raise CharacterLibraryError("Give the character a name.")
    _too_long(clean_name, NAME_MAX_CHARS, "name")
    notes = _clean(description)
    _too_long(notes, NOTES_MAX_CHARS, "notes")
    character = LibraryCharacter(
        name=clean_name,
        species="",
        notes=notes,
        origin_project_id=project_id,
        origin_discovery_id=discovery_id,
    )
    session.add(character)
    await session.flush()  # the character's id, for its first version
    await character_versions.record_version_if_changed(session, character, source="ai")
    _logger.info(
        "character %d created from project %d's discovered character %s",
        character.id,
        project_id,
        discovery_id,
    )
    return character


async def update_character(
    session: AsyncSession, character_id: int, form: CharacterForm
) -> LibraryCharacter:
    """Checks the form and saves it onto an existing character, and adds a new version when
    the profile changed. Commits. Raises CharacterLibraryError.
    """
    validate_form(form)
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise CharacterLibraryError(f"There is no character {character_id}.")
    _apply(character, form)
    character.updated_at = utcnow()
    await character_versions.record_version_if_changed(session, character)
    await session.commit()
    _logger.info("character %d updated", character.id)
    return character


async def set_archived(
    session: AsyncSession, character_id: int, archived: bool
) -> LibraryCharacter:
    """Archives or unarchives a character. Never deletes one. Commits."""
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise CharacterLibraryError(f"There is no character {character_id}.")
    character.archived = archived
    character.updated_at = utcnow()
    await session.commit()
    return character


async def get_character(session: AsyncSession, character_id: int) -> LibraryCharacter | None:
    return await session.get(LibraryCharacter, character_id)


async def list_characters(
    session: AsyncSession, *, include_archived: bool, before_id: int | None, limit: int
) -> list[LibraryCharacter]:
    """The newest characters first, `limit` of them (at most LIST_LIMIT), those with an id
    below `before_id` if given. Archived characters are left out unless asked for.
    """
    statement = (
        select(LibraryCharacter)
        .order_by(LibraryCharacter.id.desc())
        .limit(min(limit, LIST_LIMIT))
        .execution_options(populate_existing=True)
    )
    if not include_archived:
        statement = statement.where(LibraryCharacter.archived.is_(False))
    if before_id is not None:
        statement = statement.where(LibraryCharacter.id < before_id)
    return list((await session.execute(statement)).scalars().all())


def _grown(suggestions: tuple[str, ...], used: list[str]) -> list[str]:
    """The suggestions, in order, plus every used value that is not already one of them, in
    the order they were found. Case keeps whatever the author typed; matching to avoid a
    duplicate is case-insensitive, so "Human" does not sit next to "human".
    """
    seen = {value.casefold() for value in suggestions}
    extra: list[str] = []
    for value in used:
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            extra.append(value)
    return [*suggestions, *extra]


async def gender_options(session: AsyncSession) -> list[str]:
    """The growable list of gender choices: the suggestions, then every value a character
    already has that is not one of them.
    """
    used = (await session.execute(select(LibraryCharacter.gender))).scalars().all()
    return _grown(GENDER_SUGGESTIONS, list(used))


async def species_options(session: AsyncSession) -> list[str]:
    """The growable list of species choices: the suggestions, then every value a character
    already has that is not one of them.
    """
    used = (await session.execute(select(LibraryCharacter.species))).scalars().all()
    return _grown(SPECIES_SUGGESTIONS, list(used))


# --- The character card: everything a prompt writer is told about the character -----------


def _era_text(character: LibraryCharacter) -> str:
    """The character's time, in words. The year is worked out from today's date, so a card
    written today and one written next year say the same thing about the same character.
    """
    if character.era_kind == "present":
        return "set in the present day"
    years = character.era_years or 0
    today = date.today()
    if character.era_kind == "past":
        year = today.year - years
        text = f"set about {years:,} years in the past, around {year}"
    else:
        year = today.year + years
        text = f"set about {years:,} years in the future, around {year}"
    if character.era_setting:
        text += f" ({character.era_setting})"
    return text


def character_card(character: LibraryCharacter) -> str:
    """Everything a prompt writer (a look's master picture, a take's prompts, a voice
    audition) is told about the character, as one block of plain English. Pure: it reads
    columns only, and never the character's name is used by a picture or video prompt writer
    on its own (the appearance is what draws it), but the card as a whole may name it, since a
    language model is not an image model and draws nothing from the name.
    """
    lines = [
        f"Name: {character.name}.",
        f"Age: {character.age} years old." if character.age is not None else "Age: not given.",
    ]
    if character.gender:
        lines.append(f"Gender: {character.gender}.")
    # A character the pipeline made from a discovered character has no species or appearance
    # until its definition is written (PHASE-009): leave the empty lines out of the card.
    if character.species:
        lines.append(f"Species: {character.species}.")
    lines.append(f"Time: {_era_text(character)}.")
    if character.appearance:
        lines.append(f"Appearance: {character.appearance}")
    if character.outfit:
        lines.append(f"Outfit: {character.outfit}")
    if character.personality:
        lines.append(f"Personality: {character.personality}")
    if character.notes:
        lines.append(f"Other notes: {character.notes}")
    lines.append(
        "Has no visible mouth to lip-sync (a robot's screen face, an animal, an object)."
        if not character.has_visible_mouth
        else "Has a visible mouth."
    )
    return "\n".join(lines)


def references_for(framing: Framing) -> tuple[Angle, ...]:
    """Which reference angles a take's picture or video is made from, for this framing."""
    return _ANGLES_FOR_FRAMING[framing]


# --- The character's voice ------------------------------------------------------------------

# A take's voice step always uses a saved voice, steered by a delivery instruction the language
# model writes (`direction` mode): never a fresh "design" voice, so a character sounds the same
# in every take. `design` mode is for the audition only, to try candidates before one is saved.


def has_voice(character: LibraryCharacter) -> bool:
    """Whether the character has a saved voice a take can use. A character with only a
    description (not yet auditioned, or not yet chosen) is mute for take purposes, the same as
    one with no voice at all.
    """
    return character.voice_id is not None


async def set_voice_description(
    session: AsyncSession, character_id: int, voice_description: str | None
) -> LibraryCharacter:
    """Sets what the audition's design-mode samples are made from, and adds a new version when
    it changed. Commits. Raises CharacterLibraryError.
    """
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise CharacterLibraryError(f"There is no character {character_id}.")
    description = _clean(voice_description)
    _too_long(description, VOICE_DESCRIPTION_MAX_CHARS, "voice description")
    character.voice_description = description
    character.updated_at = utcnow()
    await character_versions.record_version_if_changed(session, character)
    await session.commit()
    return character


async def set_voice(
    session: AsyncSession, character_id: int, voice_id: int | None
) -> LibraryCharacter:
    """Sets the character's voice to a saved voice, or clears it (mute), and adds a new
    version when it changed. Commits. Raises CharacterLibraryError.
    """
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise CharacterLibraryError(f"There is no character {character_id}.")
    if voice_id is not None and await session.get(Voice, voice_id) is None:
        raise CharacterLibraryError(f"There is no saved voice {voice_id}.")
    character.voice_id = voice_id
    character.updated_at = utcnow()
    await character_versions.record_version_if_changed(session, character)
    await session.commit()
    _logger.info("character %d voice set: voice_id=%s", character.id, voice_id)
    return character


async def start_audition_line(session: AsyncSession, character_id: int) -> Job:
    """Starts the job that writes a short line of dialogue the character might say, to read
    aloud while auditioning its voice. Commits. Raises CharacterLibraryError.

    Each call is a paid try of its own, so none is merged into an earlier one: trying another
    line is what the audition is for.
    """
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise CharacterLibraryError(f"There is no character {character_id}.")
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=PROMPT_JOB,
        provider="llm",
        input={"requested": "audition", "character_id": character_id},
        dedupe=False,
    )
    return job


async def start_auditions(session: AsyncSession, character_id: int, line: str) -> list[RunRow]:
    """Starts AUDITION_SAMPLE_COUNT design-mode speech samples of `line`, from the character's
    voice description, to choose a voice from. Commits. Raises CharacterLibraryError.
    """
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise CharacterLibraryError(f"There is no character {character_id}.")
    if not character.voice_description:
        raise CharacterLibraryError("Write a description of the voice first.")
    if not line.strip():
        raise CharacterLibraryError("Write the sample line first.")
    rows: list[RunRow] = []
    for _ in range(AUDITION_SAMPLE_COUNT):
        form = VoiceLabForm(
            mode="design",
            text=line.strip(),
            instruction=character.voice_description,
            voice_id=None,
            seed=None,
            cfg_scale=None,
        )
        try:
            rows.append(await voice_lab.create_run(session, form, commit=False))
        except VoiceLabInputError as exc:
            raise CharacterLibraryError(str(exc)) from exc
    await session.commit()
    return rows


async def choose_audition(
    session: AsyncSession, character_id: int, voice_run_id: int, name: str
) -> LibraryCharacter:
    """Saves an audition sample as a named voice (`services/voices.create_from_run`) and sets
    it as the character's voice. Commits. Raises CharacterLibraryError and
    `services.voices.VoiceInputError`.
    """
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise CharacterLibraryError(f"There is no character {character_id}.")
    voice = await voices.create_from_run(session, voice_run_id, name, transcript=None)
    return await set_voice(session, character_id, voice.id)
