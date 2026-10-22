"""The Event Extraction stage of a story project (PHASE-015, `Path_ahead.md` Section 17).

Each defined scene gets one `extract_events` job. The job asks the model what happens in the
scene, in story order, and `save_events` stores the checked answer as a new `scene_events` row:
one immutable row per run, numbered per scene, with the provenance of the artifact convention
(D-3). Like a scene definition, a list of events belongs to the project alone: nothing is
written to the Character Lab and no pin moves.

The model reads the StoryBible, the scene and its exact text, the scene's definition
(`services/scene_definitions.py`), the definitions of the characters the scene chose and the
list of all the story's characters, so that someone speaking from off screen can be named. The
whole story is not sent. Code checks the answer (`services/event_extraction_writer`).

- A scene can only be extracted when everything it reads is ready: the saved story, an up-to-date
  StoryBible, up-to-date lists of scenes and characters, and the scene's own definition, which
  has to exist and be current. The reason says what is missing.
- `start_run` queues the job for one scene. `start_all` queues one for every scene that is not
  extracted and current already and not being extracted. The jobs run side by side when the pool
  allows (`store.create_job` with `dedupe_key`).
- `state` is what the story workspace shows: for each scene its status, why it is out of date,
  its newest events and job. **Out of date is worked out on every read** and never stored: the
  story or the StoryBible changed, the scene's text changed, the scene was defined again, a
  character the scene chose has another definition (its hash, not the pinned version number, as
  in PHASE-014), or a speaker is gone from the list of characters.
- `save_events` is called by the job and flushes without committing; the job commits it together
  with finishing itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, SceneDiscovery, SceneEvents, StoryBible
from app.jobs import store
from app.services import (
    character_definitions,
    discovery,
    event_extraction_writer,
    scene_definition_writer,
    scene_definitions,
    story_bible,
)

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "extract_events"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"
# Two presses on one scene make one job; two scenes run side by side.
DEDUPE_KEY: Final = "scene_id"

# How many of a project's newest extraction jobs are read to find each scene's newest one.
_JOB_LOOKBACK: Final = 500

STORY_BIBLE_KIND: Final = "story_bible"
CHARACTER_DISCOVERY_KIND: Final = "character_discovery"
SCENE_DISCOVERY_KIND: Final = "scene_discovery"
SCENE_DEFINITION_KIND: Final = "scene_definition"
CHARACTER_DEFINITION_KIND: Final = "character_definition"

# `not_extracted`: no events were written for this scene. `extracted`: written, and nothing
# they were built from has changed. `out_of_date`: written, and something they were built from
# has changed (see the reasons).
Status = Literal["not_extracted", "extracted", "out_of_date"]


class SceneEventsError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class SceneEntry:
    """One entry of the newest list of scenes and where its events stand."""

    item: dict[str, Any]
    status: Status
    # Why an extracted scene is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The newest events of this scene, when it has some.
    row: SceneEvents | None
    # The newest extraction job of this scene, whatever its status.
    job: Job | None
    # Whether the Extract button may be pressed, and the reason when it may not.
    can_run: bool
    blocked_reason: str | None

    @property
    def content(self) -> dict[str, Any] | None:
        return self.row.content if self.row is not None else None

    @property
    def needs_confirmation(self) -> bool:
        """Whether extracting this scene again replaces events the user wrote."""
        return self.row is not None and self.row.source == SOURCE_MANUAL


@dataclass(frozen=True)
class EventsState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    # The discovered characters as `{id, name}`, so that a speaker can be shown by name.
    characters: list[dict[str, str]]
    entries: list[SceneEntry]
    # Why nothing can be extracted yet, or None.
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    """A scene that "Extract all" did not start, and why."""

    scene_id: str
    title: str
    reason: str


@dataclass(frozen=True)
class StartAllResult:
    job_ids: list[int]
    skipped: list[Skipped]


@dataclass(frozen=True)
class _Character:
    """A discovered character that is linked and defined, as it stands now."""

    discovery_id: str
    name: str
    description: str
    library_id: int
    version: int
    definition: dict[str, Any] | None


@dataclass(frozen=True)
class _Loaded:
    """Everything a run or a read of the state needs, loaded once."""

    story: str | None
    bible: StoryBible | None
    scenes: SceneDiscovery | None
    characters: discovery.Discovery | None
    # The newest scene definitions, by scene id.
    definitions: dict[str, scene_definitions.SceneEntry]
    # The newest list's characters that are linked and defined, by discovery id.
    current: dict[str, _Character]
    blocked_reason: str | None


# --- Loading ------------------------------------------------------------------------------


def _blocked_reason(
    story: str | None,
    bible: StoryBible | None,
    scenes: SceneDiscovery | None,
    characters: discovery.Discovery | None,
) -> str | None:
    """Why no scene can be extracted, or None when one can."""
    if story is None or not story.strip():
        return "Save the story first: events are taken from the story."
    if bible is None:
        return "Run the Story Bible first: events are written with its help."
    if story_bible.is_out_of_date(story, bible):
        return (
            "The Story Bible is out of date, because the story has changed since it was "
            "written. Re-run the Story Bible first, then extract the events."
        )
    lists: list[tuple[str, discovery.Discovery | None]] = [
        ("scenes", scenes),
        ("characters", characters),
    ]
    for name, row in lists:
        if row is None:
            return f"Find the {name} first: events are written with their help."
        if discovery.is_out_of_date(story, row, bible.version):
            return (
                f"The {name} are out of date, because the story or the Story Bible has changed "
                f"since they were found. Find the {name} again first, then extract the events."
            )
    return None


async def _load(session: AsyncSession, project: Project) -> _Loaded:
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    scenes = cast(SceneDiscovery | None, await discovery.latest(session, "scenes", project.id))
    characters = await discovery.latest(session, "characters", project.id)

    definitions = {
        entry.item["id"]: entry
        for entry in (await scene_definitions.state(session, project)).entries
    }
    current: dict[str, _Character] = {}
    if characters is not None:
        for entry in (await character_definitions.state(session, project)).entries:
            if entry.status != "defined" or entry.entry.info is None or entry.version is None:
                continue
            link = entry.entry.info.link
            current[entry.item["id"]] = _Character(
                discovery_id=entry.item["id"],
                name=entry.item["name"],
                description=entry.item["description"],
                library_id=link.character_id,
                version=link.pinned_version,
                definition=entry.version.definition,
            )
    return _Loaded(
        story=story,
        bible=bible,
        scenes=scenes,
        characters=characters,
        definitions=definitions,
        current=current,
        blocked_reason=_blocked_reason(story, bible, scenes, characters),
    )


def _scene_items(loaded: _Loaded) -> list[dict[str, Any]]:
    if loaded.scenes is None:
        return []
    return cast(list[dict[str, Any]], loaded.scenes.content["scenes"])


def _character_items(loaded: _Loaded) -> list[dict[str, Any]]:
    if loaded.characters is None:
        return []
    return cast(list[dict[str, Any]], loaded.characters.content["characters"])


def _scene_refusal(definition: scene_definitions.SceneEntry | None) -> str | None:
    """Why this scene's events cannot be extracted, from its definition, or None."""
    if definition is None or definition.status == "not_defined":
        return "Define this scene first: its events are written from its definition."
    if definition.status == "out_of_date":
        return "The definition of this scene is out of date. Define the scene again first."
    return None


def _shown(character: _Character) -> dict[str, Any]:
    """The record of one character definition the model was shown, in the artifact shape of
    D-3.
    """
    return {
        "kind": CHARACTER_DEFINITION_KIND,
        "id": character.library_id,
        "version": character.version,
        "discovery_id": character.discovery_id,
        "name": character.name,
        "definition_sha256": scene_definition_writer.definition_sha256(character.definition),
    }


# --- Starting runs ------------------------------------------------------------------------


@dataclass(frozen=True)
class _Prepared:
    """What the events of one scene are made from: what a job is sent, and what a version
    records. A manual save records exactly what a job would (D-3).
    """

    scene: dict[str, Any]
    definition: dict[str, Any]
    chosen: list[_Character]
    inputs: dict[str, Any]


def _prepare(project: Project, loaded: _Loaded, position: int) -> _Prepared:
    """The inputs of the scene at this position of the newest list. Raises SceneEventsError
    when this scene cannot be extracted. The caller has checked that the project is not blocked.
    """
    story, bible = loaded.story, loaded.bible
    assert story is not None and bible is not None  # the callers refuse a blocked state first
    assert loaded.scenes is not None and loaded.characters is not None
    scene = _scene_items(loaded)[position]
    definition_entry = loaded.definitions.get(scene["id"])
    refusal = _scene_refusal(definition_entry)
    if refusal is not None:
        raise SceneEventsError(refusal)
    assert definition_entry is not None and definition_entry.row is not None
    definition_row = definition_entry.row
    definition = definition_row.content

    chosen: list[_Character] = []
    for character_id in definition["characters"]:
        character = loaded.current.get(character_id)
        if character is None:
            raise SceneEventsError(
                f"A character of this scene ({character_id}) is not linked and defined. "
                "Define the scene again first."
            )
        chosen.append(character)

    inputs = {
        "project_id": project.id,
        "scene_id": scene["id"],
        "story_sha256": story_bible.story_sha256(story),
        "scene_text_sha256": event_extraction_writer.scene_text_sha256(scene["text"]),
        "artifacts": [
            {"kind": STORY_BIBLE_KIND, "id": bible.id, "version": bible.version},
            {
                "kind": CHARACTER_DISCOVERY_KIND,
                "id": loaded.characters.id,
                "version": loaded.characters.version,
            },
            {
                "kind": SCENE_DISCOVERY_KIND,
                "id": loaded.scenes.id,
                "version": loaded.scenes.version,
            },
            {
                "kind": SCENE_DEFINITION_KIND,
                "id": definition_row.id,
                "version": definition_row.version,
            },
            *(_shown(character) for character in chosen),
        ],
    }
    return _Prepared(scene, definition, chosen, inputs)


async def _queue(
    session: AsyncSession, project: Project, loaded: _Loaded, position: int
) -> tuple[Job, bool]:
    """Queues the job for the scene at this position of the newest list, and returns
    `(job, created)`. `created` is False when the scene already has a job waiting or running,
    which is returned instead. Raises SceneEventsError when this scene cannot be extracted.
    The caller has checked that the project is not blocked.
    """
    bible = loaded.bible
    assert bible is not None  # the callers refuse a blocked state first
    prepared = _prepare(project, loaded, position)
    scene = prepared.scene
    return await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "story_bible_id": bible.id,
            "story_bible_version": bible.version,
            # The project's speech mode, which decides the event types the model may use.
            "speech_mode": project.speech_mode,
            "scene_id": scene["id"],
            "scene": {
                "index": scene["index"],
                "id": scene["id"],
                "title": scene["title"],
                "description": scene["description"],
                "text": scene["text"],
            },
            "scene_definition": prepared.definition,
            "scene_characters": [
                {
                    "id": character.discovery_id,
                    "name": character.name,
                    "description": character.description,
                    "definition": character.definition,
                }
                for character in prepared.chosen
            ],
            "characters": [
                {"id": item["id"], "name": item["name"], "description": item["description"]}
                for item in _character_items(loaded)
            ],
            # Written onto the version the job makes (D-3).
            "inputs": prepared.inputs,
        },
        dedupe_key=DEDUPE_KEY,
    )


MANUAL_REPLACE_MESSAGE: Final = (
    "The newest events of this scene were written by you. Extracting them again adds a new "
    "version from the model, so it has to be confirmed."
)
SKIPPED_MANUAL: Final = "Written by you: use this scene's own button to replace it."


async def start_run(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    *,
    confirm_replace_manual: bool = False,
) -> Job:
    """Queues the job that extracts one scene's events, and commits. If that scene already has
    a job waiting or running, that job is returned and no new one is made. When the newest
    events were written by the user, they are replaced only when `confirm_replace_manual` is
    true (PHASE-037). Raises SceneEventsError.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise SceneEventsError(loaded.blocked_reason)
    items = _scene_items(loaded)
    position = next((i for i, item in enumerate(items) if item["id"] == scene_id), None)
    if position is None:
        raise SceneEventsError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    newest = (await _newest_rows(session, project.id)).get(scene_id)
    if newest is not None and newest.source == SOURCE_MANUAL and not confirm_replace_manual:
        raise SceneEventsError(MANUAL_REPLACE_MESSAGE)
    job, _created = await _queue(session, project, loaded, position)
    return job


async def start_all(session: AsyncSession, project: Project) -> StartAllResult:
    """Queues a job for every scene that is not extracted and current already, is defined and
    is not being extracted, and commits each. Raises SceneEventsError when nothing can be
    extracted yet.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise SceneEventsError(loaded.blocked_reason)
    current = {
        entry.item["id"]: entry for entry in (await _build(session, project, loaded)).entries
    }
    job_ids: list[int] = []
    skipped: list[Skipped] = []
    for position, item in enumerate(_scene_items(loaded)):
        entry = current[item["id"]]
        if entry.status == "extracted":
            skipped.append(Skipped(item["id"], item["title"], "Already extracted and up to date."))
            continue
        if entry.needs_confirmation:
            skipped.append(Skipped(item["id"], item["title"], SKIPPED_MANUAL))
            continue
        refusal = _scene_refusal(loaded.definitions.get(item["id"]))
        if refusal is not None:
            skipped.append(Skipped(item["id"], item["title"], refusal))
            continue
        job, created = await _queue(session, project, loaded, position)
        if created:
            job_ids.append(job.id)
        else:
            skipped.append(Skipped(item["id"], item["title"], "Already being extracted."))
    return StartAllResult(job_ids=job_ids, skipped=skipped)


# --- Reading the state --------------------------------------------------------------------


def _recorded(inputs: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """The artifact of this kind that `inputs` says the events were built from."""
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            return artifact
    return None


def _out_of_date_reasons(
    row: SceneEvents,
    story: str | None,
    newest_bible_version: int | None,
    scene: dict[str, Any],
    definition: scene_definitions.SceneEntry | None,
    current: dict[str, _Character],
    listed: set[str],
) -> list[str]:
    """Why events written for this scene are no longer current, one sentence each. `listed` is
    the ids of the newest list of characters.
    """
    inputs = row.inputs
    reasons: list[str] = []
    if story is None or not story.strip():
        reasons.append("The story is now empty.")
    elif inputs.get("story_sha256") != story_bible.story_sha256(story):
        reasons.append("The story has changed since these events were written.")

    recorded_bible = _recorded(inputs, STORY_BIBLE_KIND)
    recorded_bible_version = recorded_bible.get("version") if recorded_bible else None
    if not isinstance(recorded_bible_version, int) or (
        newest_bible_version is not None and newest_bible_version > recorded_bible_version
    ):
        reasons.append("The Story Bible has been written again since these events were made.")

    if inputs.get("scene_text_sha256") != event_extraction_writer.scene_text_sha256(scene["text"]):
        reasons.append("The text of the scene has changed.")

    recorded_definition = _recorded(inputs, SCENE_DEFINITION_KIND)
    recorded_definition_version = (
        recorded_definition.get("version") if recorded_definition else None
    )
    if definition is None or definition.row is None:
        reasons.append("The scene has no definition now.")
    else:
        if definition.status == "out_of_date":
            reasons.append("The definition of the scene is out of date.")
        if (
            not isinstance(recorded_definition_version, int)
            or definition.row.version > recorded_definition_version
        ):
            reasons.append("The scene has been defined again since these events were made.")

    for artifact in inputs.get("artifacts") or []:
        if not isinstance(artifact, dict) or artifact.get("kind") != CHARACTER_DEFINITION_KIND:
            continue
        discovery_id = artifact.get("discovery_id")
        name = artifact.get("name") or discovery_id
        if discovery_id not in listed:
            reasons.append(f"{name} is no longer in the list of characters.")
            continue
        now = current.get(discovery_id)
        if now is None or now.library_id != artifact.get("id"):
            reasons.append(f"{name} is now linked to a different character, or not linked.")
        elif scene_definition_writer.definition_sha256(now.definition) != artifact.get(
            "definition_sha256"
        ):
            reasons.append(f"The definition of {name} has changed since these events were written.")

    # A speaker the scene did not choose (an off-screen voice) is not recorded as an artifact,
    # but it must still be a character of the newest list.
    for event in row.content.get("events", []):
        speaker = event.get("speaker_id")
        if speaker is not None and speaker not in listed:
            line = f"{speaker} is no longer in the list of characters."
            if line not in reasons:
                reasons.append(line)
    return reasons


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest extraction job of each scene of the project, by its id."""
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


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, SceneEvents]:
    """The newest events of each scene of the project, by its id."""
    statement = (
        select(SceneEvents)
        .where(SceneEvents.project_id == project_id)
        .order_by(SceneEvents.version.desc(), SceneEvents.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, SceneEvents] = {}
    for row in (await session.execute(statement)).scalars():
        if row.scene_id not in newest:
            newest[row.scene_id] = row
    return newest


async def _build(session: AsyncSession, project: Project, loaded: _Loaded) -> EventsState:
    jobs = await _newest_jobs(session, project.id)
    rows = await _newest_rows(session, project.id)
    listed = {item["id"] for item in _character_items(loaded)}
    newest_bible_version = loaded.bible.version if loaded.bible is not None else None

    entries: list[SceneEntry] = []
    for item in _scene_items(loaded):
        row = rows.get(item["id"])
        job = jobs.get(item["id"])
        active = job is not None and job.status in store.ACTIVE_STATUSES
        definition = loaded.definitions.get(item["id"])
        status: Status = "not_extracted"
        reasons: list[str] = []
        if row is not None and isinstance(row.inputs, dict):
            reasons = _out_of_date_reasons(
                row, loaded.story, newest_bible_version, item, definition, loaded.current, listed
            )
            status = "out_of_date" if reasons else "extracted"
        blocked_reason = loaded.blocked_reason or _scene_refusal(definition)
        if blocked_reason is None and active:
            blocked_reason = "The events are already being extracted."
        entries.append(
            SceneEntry(
                item=item,
                status=status,
                reasons=reasons,
                row=row,
                job=job,
                can_run=blocked_reason is None,
                blocked_reason=blocked_reason,
            )
        )
    return EventsState(
        scenes_version=loaded.scenes.version if loaded.scenes is not None else None,
        characters=[{"id": item["id"], "name": item["name"]} for item in _character_items(loaded)],
        entries=entries,
        blocked_reason=loaded.blocked_reason,
    )


async def state(session: AsyncSession, project: Project) -> EventsState:
    """The newest list of scenes with where each scene's events stand. Worked out on every
    read; nothing here is stored.
    """
    return await _build(session, project, await _load(session, project))


# --- Saving the events --------------------------------------------------------------------


async def save_events(
    session: AsyncSession,
    *,
    project_id: int,
    scene_id: str,
    content: dict[str, Any],
    job_id: int | None,
    inputs: dict[str, Any],
    source: str = SOURCE_AI,
) -> SceneEvents:
    """Adds the scene's next version. Flushes but does not commit: the job commits it together
    with finishing itself, so a job is never "succeeded" without its result.

    `job_id` is None and `source` is `manual` for events the user edited (`save_manual`).
    `inputs` is what the job was started with and is stored as it is: the artifacts in it are
    those of the scene's own definition and characters.
    """
    statement = select(func.max(SceneEvents.version)).where(
        SceneEvents.project_id == project_id, SceneEvents.scene_id == scene_id
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = SceneEvents(
        project_id=project_id,
        scene_id=scene_id,
        version=(highest or 0) + 1,
        source=source,
        job_id=job_id,
        inputs=inputs,
        content=content,
    )
    session.add(row)
    await session.flush()
    _logger.info(
        "job %s: events of scene '%s' of project %d saved, version %d",
        job_id,
        scene_id,
        project_id,
        row.version,
    )
    return row


async def save_manual(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    events: list[dict[str, Any]],
) -> SceneEvents:
    """Stores the user's edited events of one scene as its next version (`source` is
    `manual`), and commits (PHASE-037). It needs what a run needs (the scene's definition
    exists and is current) and is refused while the scene is being extracted. The events are
    checked the way the model's answer is (`check_answer`): the types and fields, every speaker a
    discovered character, ids `evt_1`, `evt_2`, ... set by code in the order given, and every
    speech event found in the scene's text in order. The stretches of the text no speech event
    covers are worked out again. Raises SceneEventsError.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise SceneEventsError(loaded.blocked_reason)
    items = _scene_items(loaded)
    position = next((i for i, item in enumerate(items) if item["id"] == scene_id), None)
    if position is None:
        raise SceneEventsError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    job = (await _newest_jobs(session, project.id)).get(scene_id)
    if job is not None and job.status in store.ACTIVE_STATUSES:
        raise SceneEventsError("The events are already being extracted.")

    prepared = _prepare(project, loaded, position)
    try:
        content = event_extraction_writer.check_answer(
            {"events": events},
            scene_id,
            prepared.scene["text"],
            {item["id"] for item in _character_items(loaded)},
            project.speech_mode,
        )
    except ValueError as exc:
        raise SceneEventsError(str(exc)) from exc
    row = await save_events(
        session,
        project_id=project.id,
        scene_id=scene_id,
        content=content,
        job_id=None,
        inputs=prepared.inputs,
        source=SOURCE_MANUAL,
    )
    await session.commit()
    return row
