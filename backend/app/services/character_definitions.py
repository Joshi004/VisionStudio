"""The Character Definition stage of a story project (PHASE-009, `Path_ahead.md` Section 11).

Each discovered character that is linked to a library character (`services/character_links.py`)
gets one `define_character` job. The job asks the model for the structured definition and
`save_definition` stores it **on the library character**: the profile fields are overwritten
from it (`services/character_definition_writer.to_profile`), the character's `definition` holds
the structured form, a new `library_character_version` is written (`source` is `ai`, with the
job and the inputs it was built from, D-3), and the project's pin moves to that version. That
last step is this stage's own change to the pin; a lab edit never moves it.

- `start_run` queues the job for one entry. It refuses, readably, when the story, the
  StoryBible or the link is missing, and when the character was chosen from the library
  (`how = "mapped"`) and the user has not confirmed the overwrite.
- `start_all` queues a job for every linked entry that the pipeline made (`how = "created"`)
  and that is not archived or already being defined. A mapped character is never touched by it,
  except one from the project's cast (see below) that still needs a definition.
  The jobs run side by side when the pool allows (`store.create_job` with `dedupe_key`).
- `state` is what the story workspace shows: for each entry its link, its status, why it is out
  of date, the definition the pinned version holds and the newest job. **Out of date is
  worked out on every read** and never stored: a version is judged only when it was written
  for this project and this entry, and then the story text, the StoryBible and the entry's name
  and description are compared with what its `inputs` recorded.
- `save_definition` is called by the job and flushes without committing; the job commits it
  together with finishing itself.

A mapped character that is in the project's cast (`services/project_cast.py`, PHASE-048) is a
**reused** character, and the user already chose to use it, so nothing asks before it is
defined. Its mode decides the rest: with `as_is` a pinned version that holds a definition counts
as `defined` whatever project it was written for, and is never judged out of date; with
`rewrite_text` the normal rules apply, so a definition is written for this story. Either way a
definition that is written treats the character's current profile as fixed (`keep_look`).

The relations between the project's characters (`services/character_relations.py`, PHASE-047)
are part of the model's input: each of the other characters carries what it is to this one
(`relation_to_this`). A definition records the version of the relations it read and a hash of
the relations this character is in (`inputs.relations_sha256`), so it is out of date when its
own relations change. A definition made before relations existed counts as having none.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Job,
    LibraryCharacter,
    LibraryCharacterVersion,
    Project,
    ProjectCharacterLink,
    StoryBible,
)
from app.db.types import utcnow
from app.jobs import store
from app.services import (
    character_definition_writer,
    character_links,
    character_relations,
    character_versions,
    discovery,
    project_cast,
    story_bible,
)
from app.services.character_links import EntryState

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "define_character"
# Two presses on one character make one job; two characters run side by side.
DEDUPE_KEY: Final = "discovery_id"

# How many of a project's newest definition jobs are read to find each entry's newest one.
_JOB_LOOKBACK: Final = 500

STORY_BIBLE_KIND: Final = "story_bible"
CHARACTER_DISCOVERY_KIND: Final = "character_discovery"

# `unlinked`: no library character yet. `not_defined`: linked, but no definition was written for
# this entry in this project. `defined`: written, and nothing it was built from has changed.
# `out_of_date`: written, and something it was built from has changed (see the reasons).
Status = Literal["unlinked", "not_defined", "defined", "out_of_date"]


class CharacterDefinitionError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class EntryDefinition:
    """One entry of the newest list of characters and where its definition stands."""

    item: dict[str, Any]
    entry: EntryState
    status: Status
    # Why a defined entry is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The pinned version, when it holds a definition written for this entry (else None).
    version: LibraryCharacterVersion | None
    # The newest definition job of this entry, whatever its status.
    job: Job | None
    # Whether the Define button may be pressed, and the reason when it may not.
    can_run: bool
    blocked_reason: str | None
    # True when pressing Define overwrites a character the user chose from the library, so the
    # user is asked first.
    needs_confirmation: bool

    @property
    def definition(self) -> dict[str, Any] | None:
        return self.version.definition if self.version is not None else None


@dataclass(frozen=True)
class DefinitionsState:
    """What the story workspace shows. `discovery_version` is None when no list exists."""

    discovery_version: int | None
    entries: list[EntryDefinition]
    # Why nothing can be defined yet (no story, no up-to-date StoryBible), or None.
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    """An entry that "Define all" did not start, and why."""

    discovery_id: str
    name: str
    reason: str


@dataclass(frozen=True)
class StartAllResult:
    job_ids: list[int]
    skipped: list[Skipped]


# --- Inputs -------------------------------------------------------------------------------


def entry_sha256(item: dict[str, Any]) -> str:
    """A name for the entry as the model saw it: its name and its one-line description."""
    text = json.dumps(
        {"name": item["name"], "description": item["description"]},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _blocked_reason(story: str | None, bible: StoryBible | None) -> str | None:
    """Why nothing can be defined from this story and StoryBible, or None when it can."""
    if story is None or not story.strip():
        return "Save the story first: a character is defined from the story."
    if bible is None:
        return "Run the Story Bible first: a character is defined with its help."
    if story_bible.is_out_of_date(story, bible):
        return (
            "The Story Bible is out of date, because the story has changed since it was "
            "written. Re-run the Story Bible first, then define the characters."
        )
    return None


async def _require_inputs(session: AsyncSession, project: Project) -> tuple[str, StoryBible]:
    """The saved story and its up-to-date StoryBible. Raises CharacterDefinitionError."""
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    reason = _blocked_reason(story, bible)
    if reason is not None or story is None or bible is None:
        raise CharacterDefinitionError(reason or "There is no story to define from.")
    return story, bible


def _entry_refusal(entry: EntryState) -> str | None:
    """Why this entry cannot be defined on its own (no link, or an archived character)."""
    if entry.info is None:
        return (
            f"'{entry.item['name']}' is not linked to a Character Lab character yet. Link it first."
        )
    if entry.info.character.archived:
        return (
            f"{entry.info.character.name} is archived. Unarchive it in the Character Lab to "
            "define it."
        )
    return None


def _reuse(entry: EntryState, modes: dict[int, project_cast.Mode]) -> project_cast.Mode | None:
    """The cast mode of the entry when it is a reused character, else None."""
    if entry.info is None:
        return None
    return project_cast.reuse_mode(modes, entry.info.link.character_id, entry.info.link.how)


def _needs_confirmation(entry: EntryState, modes: dict[int, project_cast.Mode]) -> bool:
    """Whether defining the entry overwrites a character the user chose by hand. A character
    from the project's cast does not: choosing it for the cast was the confirmation.
    """
    return (
        entry.info is not None and entry.info.link.how == "mapped" and _reuse(entry, modes) is None
    )


def _other(other: dict[str, Any], this_id: str, relations: list[dict[str, str]]) -> dict[str, str]:
    """One of the other characters as the model sees it, with what it is to this one when the
    project's relations say.
    """
    seen = {"id": other["id"], "name": other["name"], "description": other["description"]}
    relation = character_relations.relation_to(relations, this_id, other["id"])
    if relation is not None:
        seen["relation_to_this"] = relation
    return seen


async def _queue(
    session: AsyncSession,
    project: Project,
    story: str,
    bible: StoryBible,
    newest: discovery.Discovery,
    entry: EntryState,
    items: list[dict[str, Any]],
    relations: character_relations.RelationsState,
    *,
    keep_look: bool,
) -> tuple[Job, bool]:
    """Queues the job for one linked entry, and returns `(job, created)`. `created` is False
    when the entry already has a job waiting or running, which is returned instead.
    """
    assert entry.info is not None  # the callers refuse an unlinked entry first
    item = entry.item
    story_hash = story_bible.story_sha256(story)
    entry_hash = entry_sha256(item)
    artifacts = [
        {"kind": STORY_BIBLE_KIND, "id": bible.id, "version": bible.version},
        {"kind": CHARACTER_DISCOVERY_KIND, "id": newest.id, "version": newest.version},
    ]
    relations_artifact = character_relations.relations_artifact(relations.version)
    if relations_artifact is not None:
        artifacts.append(relations_artifact)
    inputs = {
        "project_id": project.id,
        "discovery_id": item["id"],
        "story_sha256": story_hash,
        "entry_sha256": entry_hash,
        "relations_sha256": character_relations.entry_relations_sha256(
            relations.relations, item["id"]
        ),
        "artifacts": artifacts,
    }
    return await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "story_text": story,
            "story_sha256": story_hash,
            "story_bible_id": bible.id,
            "story_bible_version": bible.version,
            "discovery_version": newest.version,
            "discovery_id": item["id"],
            "entry": {
                "id": item["id"],
                "name": item["name"],
                "description": item["description"],
            },
            "others": [
                _other(other, item["id"], relations.relations)
                for other in items
                if other["id"] != item["id"]
            ],
            "character_id": entry.info.link.character_id,
            # A reused character: its current profile is fixed (PHASE-048).
            "keep_look": keep_look,
            # Written onto the version the job makes (D-3).
            "inputs": inputs,
        },
        dedupe_key=DEDUPE_KEY,
    )


async def _entries(
    session: AsyncSession, project: Project
) -> tuple[discovery.Discovery, list[dict[str, Any]], list[EntryState]]:
    """The newest list of characters (its row, its items) and each item's link. Raises
    CharacterDefinitionError when there is no list.
    """
    newest = await discovery.latest(session, "characters", project.id)
    if newest is None:
        raise CharacterDefinitionError("Find the characters first: there is nothing to define yet.")
    links = await character_links.state(session, project.id)
    return newest, newest.content["characters"], links.entries


# --- Starting runs ------------------------------------------------------------------------


async def start_run(
    session: AsyncSession,
    project: Project,
    discovery_id: str,
    *,
    confirm_overwrite: bool = False,
) -> Job:
    """Queues the job that defines one character, and commits. If that character already has
    a job waiting or running, that job is returned and no new one is made.

    A character the user chose from the library (`mapped`) is overwritten only when
    `confirm_overwrite` is true. Raises CharacterDefinitionError.
    """
    story, bible = await _require_inputs(session, project)
    newest, items, entries = await _entries(session, project)
    entry = next((entry for entry in entries if entry.item["id"] == discovery_id), None)
    if entry is None:
        raise CharacterDefinitionError(
            f"There is no character '{discovery_id}' in the newest list of characters."
        )
    refusal = _entry_refusal(entry)
    if refusal is not None:
        raise CharacterDefinitionError(refusal)
    modes = await project_cast.cast_modes(session, project.id, "characters")
    if _needs_confirmation(entry, modes) and not confirm_overwrite:
        raise CharacterDefinitionError(
            f"{entry.item['name']} was chosen from the Character Lab. Defining it overwrites "
            "its appearance, outfit, personality, voice description, age, gender, species and "
            "era, so it has to be confirmed."
        )
    relations = await character_relations.state(session, project)
    job, _created = await _queue(
        session,
        project,
        story,
        bible,
        newest,
        entry,
        items,
        relations,
        keep_look=_reuse(entry, modes) is not None,
    )
    return job


async def start_all(session: AsyncSession, project: Project) -> StartAllResult:
    """Queues a job for every linked character that the pipeline made and that is not archived
    or already being defined, and commits each. A character chosen from the library is
    skipped (define it on its own, which asks first). Raises CharacterDefinitionError when
    there is no story, StoryBible or list of characters.
    """
    story, bible = await _require_inputs(session, project)
    newest, items, entries = await _entries(session, project)
    relations = await character_relations.state(session, project)
    modes = await project_cast.cast_modes(session, project.id, "characters")
    current = {item.item["id"]: item for item in (await state(session, project)).entries}
    job_ids: list[int] = []
    skipped: list[Skipped] = []
    for entry in entries:
        name = entry.item["name"]
        refusal = _entry_refusal(entry)
        if refusal is not None:
            skipped.append(Skipped(entry.item["id"], name, refusal))
            continue
        reuse = _reuse(entry, modes)
        if reuse == "as_is" and current[entry.item["id"]].status == "defined":
            skipped.append(Skipped(entry.item["id"], name, "Reused from the library as it is."))
            continue
        if _needs_confirmation(entry, modes):
            skipped.append(
                Skipped(
                    entry.item["id"],
                    name,
                    "Chosen from the Character Lab: define it on its own, which asks first.",
                )
            )
            continue
        job, created = await _queue(
            session,
            project,
            story,
            bible,
            newest,
            entry,
            items,
            relations,
            keep_look=reuse is not None,
        )
        if created:
            job_ids.append(job.id)
        else:
            skipped.append(Skipped(entry.item["id"], name, "Already being defined."))
    return StartAllResult(job_ids=job_ids, skipped=skipped)


# --- Reading the state --------------------------------------------------------------------


def _recorded_version(inputs: dict[str, Any], kind: str) -> int | None:
    """The version of the artifact of this kind that `inputs` says the definition read."""
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            version = artifact.get("version")
            return version if isinstance(version, int) else None
    return None


def _out_of_date_reasons(
    inputs: dict[str, Any],
    story: str | None,
    newest_bible_version: int | None,
    item: dict[str, Any],
    relations_sha256: str,
) -> list[str]:
    """Why a definition written for this entry is no longer current, one sentence each."""
    reasons: list[str] = []
    if story is None or not story.strip():
        reasons.append("The story is now empty.")
    elif inputs.get("story_sha256") != story_bible.story_sha256(story):
        reasons.append("The story has changed since this definition was written.")
    recorded_bible = _recorded_version(inputs, STORY_BIBLE_KIND)
    if recorded_bible is None or (
        newest_bible_version is not None and newest_bible_version > recorded_bible
    ):
        reasons.append("The Story Bible has been written again since this definition was made.")
    if inputs.get("entry_sha256") != entry_sha256(item):
        reasons.append("The character's name or description has changed in the list.")
    # A definition made before relations existed did not record a hash: it read none.
    recorded_relations = inputs.get("relations_sha256", character_relations.EMPTY_RELATIONS_SHA256)
    if recorded_relations != relations_sha256:
        reasons.append("The character's relations have changed since this definition was made.")
    return reasons


async def _pinned_version(
    session: AsyncSession, character_id: int, version: int
) -> LibraryCharacterVersion | None:
    statement = select(LibraryCharacterVersion).where(
        LibraryCharacterVersion.character_id == character_id,
        LibraryCharacterVersion.version == version,
    )
    return (await session.execute(statement)).scalars().first()


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest definition job of each discovered character of the project, by its id."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == JOB_TYPE)
        .order_by(Job.id.desc())
        .limit(_JOB_LOOKBACK)
        .execution_options(populate_existing=True)
    )
    newest: dict[str, Job] = {}
    for job in (await session.execute(statement)).scalars():
        key = job.input.get(DEDUPE_KEY) if isinstance(job.input, dict) else None
        if isinstance(key, str) and key not in newest:
            newest[key] = job
    return newest


async def state(session: AsyncSession, project: Project) -> DefinitionsState:
    """The newest list of characters with where each definition stands. Worked out on every
    read; nothing here is stored.
    """
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    blocked = _blocked_reason(story, bible)
    newest_bible_version = bible.version if bible is not None else None
    links = await character_links.state(session, project.id)
    jobs = await _newest_jobs(session, project.id)
    relations = (await character_relations.state(session, project)).relations
    modes = await project_cast.cast_modes(session, project.id, "characters")

    entries: list[EntryDefinition] = []
    for entry in links.entries:
        item = entry.item
        job = jobs.get(item["id"])
        active = job is not None and job.status in store.ACTIVE_STATUSES
        status: Status = "unlinked"
        reasons: list[str] = []
        version: LibraryCharacterVersion | None = None
        if entry.info is not None:
            status = "not_defined"
            pinned = await _pinned_version(
                session, entry.info.link.character_id, entry.info.link.pinned_version
            )
            inputs = pinned.inputs if pinned is not None else None
            if (
                _reuse(entry, modes) == "as_is"
                and pinned is not None
                and pinned.definition is not None
            ):
                # A character reused as it is: its own definition counts, whatever project
                # wrote it, and it is never out of date (the story did not make it).
                version = pinned
                status = "defined"
            # Otherwise only a definition written for this entry in this project counts: a
            # pinned version made by hand in the lab, or defined for another project, does not.
            elif (
                pinned is not None
                and pinned.definition is not None
                and isinstance(inputs, dict)
                and inputs.get("project_id") == project.id
                and inputs.get("discovery_id") == item["id"]
            ):
                version = pinned
                reasons = _out_of_date_reasons(
                    inputs,
                    story,
                    newest_bible_version,
                    item,
                    character_relations.entry_relations_sha256(relations, item["id"]),
                )
                status = "out_of_date" if reasons else "defined"

        refusal = _entry_refusal(entry)
        blocked_reason = blocked or refusal
        if blocked_reason is None and active:
            blocked_reason = "A definition is already being written."
        entries.append(
            EntryDefinition(
                item=item,
                entry=entry,
                status=status,
                reasons=reasons,
                version=version,
                job=job,
                can_run=blocked_reason is None,
                blocked_reason=blocked_reason,
                needs_confirmation=_needs_confirmation(entry, modes),
            )
        )
    return DefinitionsState(
        discovery_version=links.discovery_version, entries=entries, blocked_reason=blocked
    )


# --- Saving a definition ------------------------------------------------------------------


async def save_definition(
    session: AsyncSession,
    *,
    project_id: int,
    discovery_id: str,
    character_id: int,
    definition: dict[str, Any],
    job_id: int,
    inputs: dict[str, Any],
) -> LibraryCharacterVersion:
    """Writes the definition onto the library character, adds its next version, and moves the
    project's pin to it. Flushes but does not commit: the job commits it together with
    finishing itself, so a job is never "succeeded" without its result.

    The profile fields the definition fills are overwritten (the name and the notes are not).
    If the character already holds exactly this definition, built from the same inputs, no
    version is added and the pin moves to the newest one. Raises CharacterDefinitionError when
    the link was removed, or moved to another character, while the model was answering.
    """
    statement = select(ProjectCharacterLink).where(
        ProjectCharacterLink.project_id == project_id,
        ProjectCharacterLink.discovery_id == discovery_id,
    )
    link = (await session.execute(statement)).scalars().first()
    if link is None or link.character_id != character_id:
        raise CharacterDefinitionError(
            f"The link of '{discovery_id}' to the Character Lab changed while the definition "
            "was being written, so it was not saved."
        )
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise CharacterDefinitionError("The character is no longer in the Character Lab.")

    profile = character_definition_writer.to_profile(definition)
    for field in character_definition_writer.PROFILE_FIELDS_WRITTEN:
        setattr(character, field, profile[field])
    character.definition = definition
    character.updated_at = utcnow()

    version = await character_versions.record_version_if_changed(
        session, character, source="ai", job_id=job_id, inputs=inputs
    )
    if version is None:
        version = await character_versions.latest_version(session, character_id)
    assert version is not None  # a character with a definition always has a version

    link.pinned_version = version.version
    link.updated_at = utcnow()
    await session.flush()
    _logger.info(
        "job %d: character %d defined as '%s' for project %d, pinned at version %d",
        job_id,
        character_id,
        discovery_id,
        project_id,
        version.version,
    )
    return version
