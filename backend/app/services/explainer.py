"""The cast of an explainer project (EXPLAINER-002, EXPLAINER-003).

An explainer has one presenter, chosen from the Character Lab when the project is created, and
at most one set (an environment of the Environment Lab). Both go into the project's cast as
`as_is`, so the pipeline reuses their definition, look and voice instead of making new ones, and
the cast is then fixed: there is no way to add or remove a member afterwards.

This module checks the choices, writes the cast rows, and reads the presenter and the set back.
It starts no job and calls no model.
"""

from __future__ import annotations

import re
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    LibraryCharacter,
    LibraryEnvironment,
    Project,
    ProjectCastCharacter,
    ProjectCastEnvironment,
    ProjectCharacterLink,
)
from app.providers import speech_synthesizer
from app.services import character_library, character_versions, environment_versions
from app.services.project_kinds import KIND_EXPLAINER

# What steers a continuous explainer's voice when the owner wrote nothing and the Story Bible
# has no presenter style yet (FLOW-002).
DEFAULT_PRESENTER_DELIVERY: Final = (
    "Speak clearly and confidently at a lively, steady pace, like a friendly expert "
    "explaining to one viewer, with natural emphasis on key words and numbers."
)
assert len(DEFAULT_PRESENTER_DELIVERY) <= speech_synthesizer.INSTRUCTION_MAX_CHARS

# The kind of discovered item the presenter is, and what its one line says.
PRESENTER_DESCRIPTION: Final = "The presenter who explains the topic on camera."
SET_DESCRIPTION: Final = "The studio where the presenter speaks."


# The longest discovered id (`discovery_writer.ID_MAX_CHARS`), and the pattern an id follows.
_ID_MAX_CHARS: Final = 48
_NOT_SLUG: Final = re.compile(r"[^a-z0-9]+")


class ExplainerError(ValueError):
    """An explainer that cannot be set up. The message is meant to be shown to the user."""


def is_explainer(project: Project) -> bool:
    return project.kind == KIND_EXPLAINER


async def check_presenter(session: AsyncSession, character_id: int) -> LibraryCharacter:
    """The library character that will present. Raises ExplainerError unless it is usable: not
    archived, with a visible mouth, and a newest version that has a saved voice and a picture for
    every angle (so nothing has to be made for it).
    """
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise ExplainerError(f"There is no character {character_id} in the Character Lab.")
    if character.archived:
        raise ExplainerError(
            f"{character.name} is archived. Unarchive it in the Character Lab to use it."
        )
    if not character.has_visible_mouth:
        raise ExplainerError(f"{character.name} has no visible mouth, so it cannot present.")
    version = await character_versions.latest_version(session, character.id)
    if version is None:
        raise ExplainerError(
            f"{character.name} has no version yet. Open it in the Character Lab first."
        )
    if version.voice_id is None:
        raise ExplainerError(
            f"{character.name} has no saved voice. Choose a voice for it in the Character Lab."
        )
    angles = {
        picture.get("angle")
        for picture in version.look_references or []
        if isinstance(picture, dict) and isinstance(picture.get("lab_image_id"), int)
    }
    if not all(angle in angles for angle in character_library.ANGLES):
        raise ExplainerError(
            f"{character.name} has no finished look. Make and choose its pictures in the "
            "Character Lab."
        )
    return character


async def check_set(session: AsyncSession, environment_id: int) -> LibraryEnvironment:
    """The library environment that will be the set. Raises ExplainerError unless it is usable:
    not archived, and a newest version that has a reference picture.
    """
    environment = await session.get(LibraryEnvironment, environment_id)
    if environment is None:
        raise ExplainerError(f"There is no environment {environment_id} in the Environment Lab.")
    if environment.archived:
        raise ExplainerError(
            f"{environment.name} is archived. Unarchive it in the Environment Lab to use it."
        )
    version = await environment_versions.latest_version(session, environment.id)
    if version is None or version.reference_image_id is None:
        raise ExplainerError(
            f"{environment.name} has no reference picture. Make one in the Environment Lab."
        )
    return environment


def add_cast(session: AsyncSession, project_id: int, presenter_id: int, set_id: int | None) -> None:
    """Adds the presenter, and the set when there is one, to the project's cast as `as_is`.
    Does not commit: the caller commits together with the project.
    """
    session.add(
        ProjectCastCharacter(project_id=project_id, character_id=presenter_id, mode="as_is")
    )
    if set_id is not None:
        session.add(
            ProjectCastEnvironment(project_id=project_id, environment_id=set_id, mode="as_is")
        )


async def presenter_of(session: AsyncSession, project_id: int) -> LibraryCharacter | None:
    """The project's presenter: the one character of its cast. None when it has none."""
    statement = (
        select(LibraryCharacter)
        .join(ProjectCastCharacter, ProjectCastCharacter.character_id == LibraryCharacter.id)
        .where(ProjectCastCharacter.project_id == project_id)
        .order_by(ProjectCastCharacter.id)
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def set_of(session: AsyncSession, project_id: int) -> LibraryEnvironment | None:
    """The project's set: the one environment of its cast. None when it was left to the model."""
    statement = (
        select(LibraryEnvironment)
        .join(
            ProjectCastEnvironment, ProjectCastEnvironment.environment_id == LibraryEnvironment.id
        )
        .where(ProjectCastEnvironment.project_id == project_id)
        .order_by(ProjectCastEnvironment.id)
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


def slug_of(name: str, fallback: str) -> str:
    """A discovered id made from a library item's name: lower-case letters, digits and
    underscores, starting with a letter, at most 48 characters. `fallback` is used when the name
    has no letter or digit.
    """
    slug = _NOT_SLUG.sub("_", name.lower()).strip("_")
    if not slug:
        slug = fallback
    if not slug[0].isalpha():
        slug = f"{fallback}_{slug}"
    return slug[:_ID_MAX_CHARS].rstrip("_") or fallback


async def fixed_discovery(
    session: AsyncSession, project_id: int, kind: Literal["characters", "environments"]
) -> dict[str, Any] | None:
    """The discovered list of an explainer that no model is asked for (EXPLAINER-003): the
    presenter for the characters, and the set for the environments when the project has one.
    None for the environments of a project with no set, which the model designs (one studio).

    The item carries the `library_id`, so linking maps it to the library item and the later
    steps reuse its definition, look and voice. Raises ExplainerError when the cast is empty.
    """
    if kind == "characters":
        presenter = await presenter_of(session, project_id)
        if presenter is None:
            raise ExplainerError("This explainer has no presenter.")
        item: dict[str, Any] = {
            "id": slug_of(presenter.name, "presenter"),
            "name": presenter.name,
            "description": PRESENTER_DESCRIPTION,
            "library_id": presenter.id,
        }
        return {"characters": [item]}
    studio = await set_of(session, project_id)
    if studio is None:
        return None
    return {
        "environments": [
            {
                "id": slug_of(studio.name, "studio"),
                "name": studio.name,
                "description": SET_DESCRIPTION,
                "library_id": studio.id,
            }
        ]
    }


async def presenter_voice_id(session: AsyncSession, project_id: int) -> int | None:
    """The saved voice of the project's presenter: the voice of the version the project pins,
    or of the newest version when the presenter is not linked yet. None when there is no
    presenter or its version has no voice.
    """
    presenter = await presenter_of(session, project_id)
    if presenter is None:
        return None
    link = (
        (
            await session.execute(
                select(ProjectCharacterLink).where(
                    ProjectCharacterLink.project_id == project_id,
                    ProjectCharacterLink.character_id == presenter.id,
                )
            )
        )
        .scalars()
        .first()
    )
    version = (
        await character_versions.get_version(session, presenter.id, link.pinned_version)
        if link is not None
        else await character_versions.latest_version(session, presenter.id)
    )
    return version.voice_id if version is not None else None


async def presenter_delivery(session: AsyncSession, project: Project) -> str:
    """The instruction that steers the voice of every take of a continuous explainer (FLOW-002).

    The owner's text wins. When there is none, the newest Story Bible's way the presenter speaks
    (`storytelling_style.narration`) is used, and when there is no Bible yet, a fixed default.
    The answer is never longer than the speech model accepts. Nothing is stored.
    """
    # Imported here: the Story Bible module reaches the job store, which reaches the services.
    from app.services import story_bible

    max_chars = speech_synthesizer.INSTRUCTION_MAX_CHARS
    if project.presenter_delivery and project.presenter_delivery.strip():
        return project.presenter_delivery.strip()[:max_chars]
    bible = await story_bible.latest(session, project.id)
    content = bible.content if bible is not None and isinstance(bible.content, dict) else {}
    style = content.get("storytelling_style")
    narration = style.get("narration") if isinstance(style, dict) else None
    if isinstance(narration, str) and narration.strip():
        return f"Speak in this style: {narration.strip()}"[:max_chars]
    return DEFAULT_PRESENTER_DELIVERY
