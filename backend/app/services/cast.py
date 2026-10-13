"""A project's cast: the characters and the places of its story, and what their reference
pictures need (project cast and character consistency).

The cast is found by one language model job (`extract_cast`, `services/cast_extraction.py`),
edited by hand, and given one reference picture per member: a language model job writes the
prompt (`write_character_reference_prompt`) and the image model makes the picture
(`generate_character_reference`). A scene then names the characters it shows (none, one or
several: the rows of `scene_character`) and the place it shows (`scene.location_id`), written by
the `assign_cast` job or by hand, and its first frame is made from those pictures instead of from
words alone.

A *member* is a `Character` or a `Location`. The two tables share what the pictures need (a
name, an appearance, a prompt, a picture, a status), so most code here takes either, together
with its `kind`.

Pure functions, except the ones that take a session.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Character, Job, Location, Scene, SceneCharacter
from app.jobs import store
from app.providers import image_generator
from app.services.cast_extraction import CastList

EXTRACT_JOB: Final = "extract_cast"
REFERENCE_PROMPT_JOB: Final = "write_character_reference_prompt"
REFERENCE_IMAGE_JOB: Final = "generate_character_reference"
ASSIGN_JOB: Final = "assign_cast"

CHARACTER: Final = "character"
LOCATION: Final = "location"
KINDS: Final = (CHARACTER, LOCATION)

# What a reference picture's job has in its input, to say whose picture it makes.
KIND_KEY: Final = "cast_kind"
ID_KEY: Final = "cast_id"

# The image model's edit takes this many reference pictures, and a scene's first frame is made
# from the picture of each of its characters and of its place. So that the place always fits, a
# scene shows at most one picture less than that in characters. This is a limit of the image
# model, kept in code: no prompt asks for any number of characters.
MAX_SCENE_CHARACTERS: Final = image_generator.MAX_REFERENCES - 1

Member = Character | Location


# --- The cast ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Cast:
    characters: list[Character]
    locations: list[Location]

    @property
    def is_empty(self) -> bool:
        return not self.characters and not self.locations

    def members(self) -> list[tuple[str, Member]]:
        """Every member with its kind: the characters first, in the order they were found."""
        return [(CHARACTER, member) for member in self.characters] + [
            (LOCATION, member) for member in self.locations
        ]

    def find(self, kind: str, member_id: int) -> Member | None:
        pool: Sequence[Member] = self.characters if kind == CHARACTER else self.locations
        return next((member for member in pool if member.id == member_id), None)


def member_key(kind: str, member_id: int) -> str:
    """A member's name in a map or in an automatic run: `character:3`."""
    return f"{kind}:{member_id}"


def member_of_job(job: Job) -> tuple[str, int] | None:
    """Whose reference picture (or prompt) a job makes, from its input. None when it says none."""
    recorded: Any = job.input if isinstance(job.input, dict) else {}
    kind, member_id = recorded.get(KIND_KEY), recorded.get(ID_KEY)
    if kind in KINDS and isinstance(member_id, int) and not isinstance(member_id, bool):
        return kind, member_id
    return None


async def load_cast(session: AsyncSession, project_id: int) -> Cast:
    characters = (
        (
            await session.execute(
                select(Character)
                .where(Character.project_id == project_id)
                .order_by(Character.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    locations = (
        (
            await session.execute(
                select(Location)
                .where(Location.project_id == project_id)
                .order_by(Location.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return Cast(characters=list(characters), locations=list(locations))


async def get_member(
    session: AsyncSession, project_id: int, kind: str, member_id: int
) -> Member | None:
    """One member of the project's cast, as it is now, or None."""
    model = Character if kind == CHARACTER else Location
    statement = (
        select(model)
        .where(model.id == member_id, model.project_id == project_id)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def replace_cast(session: AsyncSession, project_id: int, found: CastList) -> Cast:
    """Replaces the project's whole cast with what the model found. Flushes, does not commit.

    The scenes forget who and where they showed, because those members are gone. A reference
    picture stays on disk (stored files are never deleted) but belongs to no member any more.
    """
    await session.execute(
        delete(SceneCharacter)
        .where(SceneCharacter.scene_id.in_(select(Scene.id).where(Scene.project_id == project_id)))
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(Scene)
        .where(Scene.project_id == project_id)
        .values(
            location_id=None,
            cast_assignment_source=None,
            cast_assignment_job_id=None,
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(delete(Character).where(Character.project_id == project_id))
    await session.execute(delete(Location).where(Location.project_id == project_id))
    characters = [
        Character(
            project_id=project_id,
            name=item.name,
            appearance_description=item.appearance,
            personality_description=item.personality,
            voice_description=item.voice,
        )
        for item in found.characters
    ]
    locations = [
        Location(project_id=project_id, name=item.name, appearance_description=item.appearance)
        for item in found.locations
    ]
    session.add_all([*characters, *locations])
    await session.flush()
    return Cast(characters=characters, locations=locations)


# --- A member's reference picture ----------------------------------------------------------


def has_prompt(member: Member) -> bool:
    return bool((member.reference_prompt or "").strip())


def prompt_block(member: Member) -> str | None:
    """Why a reference prompt cannot be written for the member now, or None."""
    if not member.appearance_description.strip():
        return f'"{member.name}" has no appearance description to write the prompt from.'
    return None


def image_block(member: Member) -> str | None:
    """Why the reference picture cannot be made now, or None."""
    if not has_prompt(member):
        return f'"{member.name}" has no reference prompt yet. Write it first.'
    return None


def mark_prompted(member: Member, prompt: str, job_id: int) -> None:
    """A new prompt: the picture, if there is one, was made from an older one, and stays until
    the new prompt makes another.
    """
    member.reference_prompt = prompt
    member.reference_prompt_job_id = job_id
    if member.reference_asset_id is None:
        member.status = "prompted"


def mark_ready(member: Member, asset_id: int) -> None:
    member.reference_asset_id = asset_id
    member.status = "ready"


# --- Which scene shows whom --------------------------------------------------------------


@dataclass(frozen=True)
class SceneCast:
    """The characters and the place a scene shows. It may show none, one or several characters,
    and no place.
    """

    characters: tuple[Character, ...] = ()
    location: Location | None = None

    @property
    def is_empty(self) -> bool:
        return not self.characters and self.location is None

    def references(self) -> list[tuple[str, Member]]:
        """The members whose pictures the scene's first frame is made from, in the order they
        are sent to the image model: the characters are images 1, 2 and so on, in the order
        the scene lists them, and the place is the next.
        """
        found: list[tuple[str, Member]] = [(CHARACTER, member) for member in self.characters]
        if self.location is not None:
            found.append((LOCATION, self.location))
        return found


NO_CAST: Final = SceneCast()


def references_block(scene_cast: SceneCast) -> str | None:
    """Why a scene that shows cast members cannot get its first frame yet, or None. A frame made
    without a picture the prompt counts on would show somebody else.
    """
    for kind, member in scene_cast.references():
        if member.reference_asset_id is None:
            return f'The {kind} "{member.name}" has no reference picture yet. Make it first.'
    return None


async def reference_blocks(
    session: AsyncSession, project_id: int, scenes: Sequence[Scene]
) -> dict[int, str]:
    """The scenes whose first frame must wait for a reference picture, by scene id, each with
    the reason. A scene that is not in the answer has nothing to wait for.
    """
    casts = await load_scene_casts(session, project_id, scenes)
    return {
        scene_id: reason
        for scene_id, scene_cast in casts.items()
        if (reason := references_block(scene_cast)) is not None
    }


async def load_character_ids(
    session: AsyncSession, scene_ids: Sequence[int]
) -> dict[int, list[int]]:
    """For each scene id, the ids of the characters it shows, in the order of their pictures
    (empty for a scene that shows none). One query, however many scenes.
    """
    found: dict[int, list[int]] = {scene_id: [] for scene_id in scene_ids}
    if not found:
        return found
    statement = (
        select(SceneCharacter.scene_id, SceneCharacter.character_id)
        .where(SceneCharacter.scene_id.in_(list(found)))
        .order_by(SceneCharacter.scene_id, SceneCharacter.position)
    )
    for scene_id, character_id in await session.execute(statement):
        found[scene_id].append(character_id)
    return found


async def set_scene_characters(
    session: AsyncSession, scene_id: int, character_ids: Sequence[int]
) -> None:
    """Makes these characters, in this order, the ones the scene shows (none for an empty list).
    The caller has checked that they belong to the scene's project, that none is repeated and
    that there are at most `MAX_SCENE_CHARACTERS`. Flushes, does not commit.
    """
    await session.execute(delete(SceneCharacter).where(SceneCharacter.scene_id == scene_id))
    if character_ids:
        await session.execute(
            insert(SceneCharacter),
            [
                {"scene_id": scene_id, "character_id": character_id, "position": position}
                for position, character_id in enumerate(character_ids)
            ],
        )


async def load_scene_casts(
    session: AsyncSession, project_id: int, scenes: Sequence[Scene]
) -> dict[int, SceneCast]:
    """For each scene, who and what it shows. Three queries at most, however many scenes."""
    character_ids = await load_character_ids(session, [scene.id for scene in scenes])
    if not any(character_ids.values()) and all(s.location_id is None for s in scenes):
        return {scene.id: NO_CAST for scene in scenes}
    cast = await load_cast(session, project_id)
    characters = {member.id: member for member in cast.characters}
    locations = {member.id: member for member in cast.locations}
    return {
        scene.id: SceneCast(
            characters=tuple(
                characters[character_id]
                for character_id in character_ids[scene.id]
                if character_id in characters
            ),
            location=locations.get(scene.location_id or 0),
        )
        for scene in scenes
    }


# --- Jobs -----------------------------------------------------------------------------------


async def active_jobs(session: AsyncSession, project_id: int, types: Sequence[str]) -> list[Job]:
    """The project's queued or running jobs of these types, oldest first."""
    statement = (
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.type.in_(types),
            Job.status.in_(store.ACTIVE_STATUSES),
        )
        .order_by(Job.id)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars().all())


async def active_reference_image_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The queued or running reference picture jobs, by member key."""
    jobs = await active_jobs(session, project_id, [REFERENCE_IMAGE_JOB])
    return {member_key(*member): job for job in jobs if (member := member_of_job(job)) is not None}


async def latest_member_jobs(
    session: AsyncSession, project_id: int, job_type: str
) -> dict[str, Job]:
    """The newest job of a type (`REFERENCE_PROMPT_JOB` or `REFERENCE_IMAGE_JOB`) of each member,
    whatever its status (to show why a prompt or a picture failed).
    """
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == job_type)
        .order_by(Job.id)
        .execution_options(populate_existing=True)
    )
    latest: dict[str, Job] = {}
    for job in (await session.execute(statement)).scalars():
        member = member_of_job(job)
        if member is not None:
            latest[member_key(*member)] = job
    return latest


async def has_active_cast_jobs(session: AsyncSession, project_id: int) -> bool:
    """Whether anything that reads or writes the cast is waiting or running."""
    jobs = await active_jobs(
        session, project_id, [EXTRACT_JOB, REFERENCE_PROMPT_JOB, REFERENCE_IMAGE_JOB, ASSIGN_JOB]
    )
    return bool(jobs)
