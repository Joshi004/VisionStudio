"""A story project's Music Bible: starting the job that writes it, saving its versions, and
reading them back (MUSIC-006, `Music_implementation_phases.md` Section 4.2 and 4.3).

Every version is a new `music_bible` row and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). A version holds the four directions
written at level 0a, the choice (`by` is `ai`, or `owner` when the owner chose another
direction), and the Bible itself. `inputs` records the story hash and the exact upstream rows
it was built from, so whether it is out of date is worked out when it is read and never stored.

Three ways make a version:

- `start_run` queues a `full` job: the model writes four directions (0a), chooses one (0b) and
  expands it into the Bible (0c).
- `start_choose` queues an `expand` job: the owner picked another direction of an earlier
  version, so only 0c runs again, from the directions that version already holds.
- `save_manual` stores the owner's edit, checked the way the model's answer is.

The model reads the Story Bible, the characters and places, the estimated length, and every
scene with its moods, dramatic goal and events. Nothing is sent that needs timings (MD-3). Code
checks the answer (`services/music_bible_writer`). The jobs are `jobs/write_music_bible.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import (
    Job,
    MusicBible,
    Project,
    SceneDiscovery,
    StoryBible,
)
from app.jobs import store
from app.services import (
    discovery,
    music_bible_writer,
    provenance,
    scene_definitions,
    scene_events,
    story_bible,
    story_length,
)

JOB_TYPE: Final = "write_music_bible"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"
CHOICE_BY_AI: Final = "ai"
CHOICE_BY_OWNER: Final = "owner"
# `full` writes the directions, chooses and writes the Bible. `expand` only writes the Bible.
MODE_FULL: Final = "full"
MODE_EXPAND: Final = "expand"

STORY_BIBLE_KIND: Final = "story_bible"
SCENE_DISCOVERY_KIND: Final = "scene_discovery"
CHARACTER_DISCOVERY_KIND: Final = "character_discovery"
ENVIRONMENT_DISCOVERY_KIND: Final = "environment_discovery"
SCENE_DEFINITION_KIND: Final = "scene_definition"
SCENE_EVENTS_KIND: Final = "scene_events"

# How much of a spoken or narrated line the model is shown. The sense of the moment matters to
# music, the exact words do not.
LINE_MAX_CHARS: Final = 200

MUSIC_OFF_MESSAGE: Final = "Music is switched off for this project. Switch it on in the settings."
REPLACE_MESSAGE: Final = (
    "The newest Music Bible was written or chosen by you. Running the model adds a new version "
    "from the model, so it has to be confirmed."
)
BUSY_MESSAGE: Final = "The Music Bible is being written. Wait for it to finish first."


class MusicBibleError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- Loading what the Bible is made from ---------------------------------------------------


@dataclass(frozen=True)
class _Loaded:
    """Everything a run or a read of the state needs, loaded once."""

    story: str | None
    bible: StoryBible | None
    scenes: SceneDiscovery | None
    characters: discovery.Discovery | None
    environments: discovery.Discovery | None
    # The newest list of scenes, each with its definition and its events, in story order.
    scene_items: list[dict[str, Any]]
    definitions: dict[str, scene_definitions.SceneEntry]
    events: dict[str, scene_events.SceneEntry]
    blocked_reason: str | None

    @property
    def scene_ids(self) -> list[str]:
        return [item["id"] for item in self.scene_items]

    @property
    def character_items(self) -> list[dict[str, Any]]:
        return _items(self.characters, "characters")

    @property
    def place_items(self) -> list[dict[str, Any]]:
        return _items(self.environments, "environments")


def _items(row: discovery.Discovery | None, key: str) -> list[dict[str, Any]]:
    if row is None:
        return []
    items: list[dict[str, Any]] = row.content[key]
    return items


def _blocked_reason(
    story: str | None,
    bible: StoryBible | None,
    events: scene_events.EventsState,
) -> str | None:
    """Why no Music Bible can be written yet, or None when one can."""
    if story is None or not story.strip():
        return "Save the story first: the Music Bible is made from the story."
    if bible is None:
        return "Run the Story Bible first: the Music Bible is written with its help."
    if not events.entries:
        return events.blocked_reason or "Find the scenes first: the Music Bible covers every scene."
    for entry in events.entries:
        if entry.status != "extracted" or entry.row is None:
            return (
                f"Extract the events of the scene '{entry.item['title']}' first: the Music "
                "Bible reads the events of every scene."
            )
    return None


async def _load(session: AsyncSession, project: Project) -> _Loaded:
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    events_state = await scene_events.state(session, project)
    definitions_state = await scene_definitions.state(session, project)
    scenes = await discovery.latest(session, "scenes", project.id)
    characters = await discovery.latest(session, "characters", project.id)
    environments = await discovery.latest(session, "environments", project.id)
    return _Loaded(
        story=story,
        bible=bible,
        scenes=scenes if isinstance(scenes, SceneDiscovery) else None,
        characters=characters,
        environments=environments,
        scene_items=[entry.item for entry in events_state.entries],
        definitions={entry.item["id"]: entry for entry in definitions_state.entries},
        events={entry.item["id"]: entry for entry in events_state.entries},
        blocked_reason=_blocked_reason(story, bible, events_state),
    )


# --- The context the model reads -----------------------------------------------------------


def _short(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= LINE_MAX_CHARS:
        return one_line
    return one_line[: LINE_MAX_CHARS - 3].rstrip() + "..."


def _event_for_model(event: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    kind = event["type"]
    shown: dict[str, Any] = {"id": event["id"], "type": kind}
    if kind in ("narration", "dialogue"):
        shown["text"] = _short(event["text"])
    if kind == "dialogue":
        shown["speaker"] = names.get(event["speaker_id"], event["speaker_id"])
        delivery = event.get("delivery")
        if isinstance(delivery, dict) and delivery.get("emotion"):
            shown["emotion"] = delivery["emotion"]
    if kind in ("action", "sound_event"):
        shown["description"] = event["description"]
    return shown


def _build_context(loaded: _Loaded, estimated_seconds: int) -> dict[str, Any]:
    """The story as the model reads it. The caller has checked that nothing is blocked."""
    assert loaded.bible is not None
    bible = loaded.bible.content
    names = {item["id"]: item["name"] for item in loaded.character_items}
    scenes: list[dict[str, Any]] = []
    for item in loaded.scene_items:
        definition = loaded.definitions[item["id"]].definition
        events = loaded.events[item["id"]].content
        assert definition is not None and events is not None
        scenes.append(
            {
                "id": item["id"],
                "title": item["title"],
                "summary": item["description"],
                "mood": definition["mood"],
                "dramatic_goal": definition["dramatic_goal"],
                "events": [_event_for_model(event, names) for event in events["events"]],
            }
        )
    return {
        "story_bible": {
            "title": bible["title"],
            "genre": bible["genre"],
            "tone": bible["tone"],
            "visual_style": bible["visual_style"],
            "time_period": bible["time_period"],
            "narration_style": bible["storytelling_style"]["narration"],
            "world_rules": bible["world_rules"],
        },
        "estimated_length_seconds": estimated_seconds,
        "characters": [
            {"id": item["id"], "name": item["name"], "description": item["description"]}
            for item in loaded.character_items
        ],
        "places": [
            {"id": item["id"], "name": item["name"], "description": item["description"]}
            for item in loaded.place_items
        ],
        "scenes": scenes,
    }


def _inputs(loaded: _Loaded) -> dict[str, Any]:
    """What a version is built from, in the artifact shape of D-3. A manual save records
    exactly what a job would.
    """
    assert loaded.story is not None and loaded.bible is not None and loaded.scenes is not None
    artifacts: list[dict[str, Any]] = [
        {"kind": STORY_BIBLE_KIND, "id": loaded.bible.id, "version": loaded.bible.version},
        {
            "kind": SCENE_DISCOVERY_KIND,
            "id": loaded.scenes.id,
            "version": loaded.scenes.version,
        },
    ]
    for kind, row in (
        (CHARACTER_DISCOVERY_KIND, loaded.characters),
        (ENVIRONMENT_DISCOVERY_KIND, loaded.environments),
    ):
        if row is not None:
            artifacts.append({"kind": kind, "id": row.id, "version": row.version})
    for scene_id in loaded.scene_ids:
        definition = loaded.definitions[scene_id].row
        events = loaded.events[scene_id].row
        assert definition is not None and events is not None
        artifacts.append(
            {
                "kind": SCENE_DEFINITION_KIND,
                "id": definition.id,
                "version": definition.version,
                "scene_id": scene_id,
            }
        )
        artifacts.append(
            {
                "kind": SCENE_EVENTS_KIND,
                "id": events.id,
                "version": events.version,
                "scene_id": scene_id,
            }
        )
    return {"story_sha256": story_bible.story_sha256(loaded.story), "artifacts": artifacts}


def _refs(loaded: _Loaded) -> dict[str, list[str]]:
    """The ids a theme may stand for, by kind."""
    return {
        "character": [item["id"] for item in loaded.character_items],
        "place": [item["id"] for item in loaded.place_items],
    }


async def max_themes(session: AsyncSession) -> int:
    """The cap on themes that applies now, read at the moment of use."""
    return await settings_service.get_int(session, settings_service.MUSIC_MAX_THEMES_KEY)


async def _job_input(
    session: AsyncSession, project: Project, loaded: _Loaded, mode: str
) -> dict[str, Any]:
    """What a job is sent. It is a copy of everything the job needs, taken when the button was
    pressed, so the version made is tied to what was saved then, even if the story is edited
    while the job waits.
    """
    assert loaded.story is not None
    policy = await story_length.read_story_length_policy(session)
    length = story_length.story_length(loaded.story, policy)
    return {
        "mode": mode,
        "context": _build_context(loaded, length.estimated_seconds),
        "scene_ids": loaded.scene_ids,
        "refs": _refs(loaded),
        "max_themes": await max_themes(session),
        **_inputs(loaded),
    }


# --- Starting runs -------------------------------------------------------------------------


def needs_confirmation(row: MusicBible | None) -> bool:
    """Whether running the model again would replace what the owner wrote or chose."""
    if row is None:
        return False
    return row.source == SOURCE_MANUAL or row.choice.get("by") == CHOICE_BY_OWNER


async def _refuse_when_unable(session: AsyncSession, project: Project) -> _Loaded:
    if not project.music_enabled:
        raise MusicBibleError(MUSIC_OFF_MESSAGE)
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise MusicBibleError(loaded.blocked_reason)
    return loaded


async def start_run(
    session: AsyncSession, project: Project, *, confirm_replace_manual: bool = False
) -> Job:
    """Queues the job that writes the Music Bible from the story as it stands now (the four
    directions, the choice and the Bible), and commits. If a job of this kind is already
    waiting or running for the project, that job is returned and no new one is made (two quick
    clicks make one paid run).

    When the newest version was written or chosen by the owner, the run replaces it only when
    `confirm_replace_manual` is true. Raises MusicBibleError.
    """
    loaded = await _refuse_when_unable(session, project)
    if needs_confirmation(await latest(session, project.id)) and not confirm_replace_manual:
        raise MusicBibleError(REPLACE_MESSAGE)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input=await _job_input(session, project, loaded, MODE_FULL),
    )
    return job


async def start_choose(
    session: AsyncSession, project: Project, version: int, direction_id: str
) -> Job:
    """Queues the job that writes the Bible again from the direction the owner chose among the
    four directions of an earlier version, and commits. Only call 0c runs: the directions are
    not written again. Raises MusicBibleError.
    """
    loaded = await _refuse_when_unable(session, project)
    source = await get_version(session, project.id, version)
    if source is None:
        raise MusicBibleError(f"There is no version {version} of the Music Bible.")
    if direction_id not in {direction["id"] for direction in source.directions}:
        raise MusicBibleError(f"Version {version} has no direction '{direction_id}'.")
    active = await store.latest_job(session, project.id, JOB_TYPE)
    if active is not None and active.status in store.ACTIVE_STATUSES:
        raise MusicBibleError(BUSY_MESSAGE)
    job_input = await _job_input(session, project, loaded, MODE_EXPAND)
    job_input.update(
        directions=source.directions,
        direction_id=direction_id,
        directions_from={"id": source.id, "version": source.version},
    )
    job, _created = await store.create_job(
        session, project_id=project.id, type=JOB_TYPE, provider="llm", input=job_input
    )
    return job


# --- Versions ------------------------------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> MusicBible | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(MusicBible)
        .where(MusicBible.project_id == project_id)
        .order_by(MusicBible.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def list_versions(session: AsyncSession, project_id: int) -> list[MusicBible]:
    """Every version of the project, newest first."""
    statement = (
        select(MusicBible)
        .where(MusicBible.project_id == project_id)
        .order_by(MusicBible.version.desc())
    )
    return list((await session.execute(statement)).scalars())


async def get_version(session: AsyncSession, project_id: int, version: int) -> MusicBible | None:
    """One version of the project, or None when there is no such version."""
    statement = select(MusicBible).where(
        MusicBible.project_id == project_id, MusicBible.version == version
    )
    return (await session.execute(statement)).scalars().first()


async def _add_version(
    session: AsyncSession,
    project_id: int,
    *,
    source: str,
    job_id: int | None,
    inputs: dict[str, Any],
    directions: list[dict[str, Any]],
    choice: dict[str, Any],
    content: dict[str, Any],
) -> MusicBible:
    statement = select(func.max(MusicBible.version)).where(MusicBible.project_id == project_id)
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = MusicBible(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=source,
        job_id=job_id,
        inputs=inputs,
        directions=directions,
        choice=choice,
        content=content,
    )
    session.add(row)
    await session.flush()
    return row


async def save_version(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    inputs: dict[str, Any],
    directions: list[dict[str, Any]],
    choice: dict[str, Any],
    content: dict[str, Any],
) -> MusicBible:
    """Adds the next version, made by the model (`source` is `ai`). Flushes but does not
    commit: the job commits it together with finishing itself, so a job is never "succeeded"
    without its result.

    `inputs` is what the job was started with (the story hash, the upstream rows, and for an
    `expand` job where the directions came from).
    """
    return await _add_version(
        session,
        project_id,
        source=SOURCE_AI,
        job_id=job_id,
        inputs=inputs,
        directions=directions,
        choice=choice,
        content=content,
    )


async def save_manual(
    session: AsyncSession, project: Project, content: dict[str, Any]
) -> MusicBible:
    """Stores the owner's edited Bible as the next version (`source` is `manual`), and commits.
    The four directions and the choice are copied from the version being edited. The content
    is checked the way the model's answer is (`music_bible_writer.check_bible`): the limits,
    exactly one main theme and no more than the cap on themes, every theme standing for a real
    character or place, and the arc covering each scene once. It needs what a run needs (every
    scene's events extracted) and is refused while a job is writing the Bible. Raises
    MusicBibleError.
    """
    newest = await latest(session, project.id)
    if newest is None:
        raise MusicBibleError("There is no Music Bible to edit yet.")
    active = await store.latest_job(session, project.id, JOB_TYPE)
    if active is not None and active.status in store.ACTIVE_STATUSES:
        raise MusicBibleError(BUSY_MESSAGE)
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise MusicBibleError(loaded.blocked_reason)
    try:
        checked = music_bible_writer.check_bible(
            content,
            scene_ids=loaded.scene_ids,
            refs={kind: set(ids) for kind, ids in _refs(loaded).items()},
            max_themes=await max_themes(session),
        )
    except ValueError as exc:
        raise MusicBibleError(str(exc)) from exc
    row = await _add_version(
        session,
        project.id,
        source=SOURCE_MANUAL,
        job_id=None,
        inputs={**_inputs(loaded), "edited_from": {"id": newest.id, "version": newest.version}},
        directions=newest.directions,
        choice=newest.choice,
        content=checked,
    )
    await session.commit()
    return row


# --- Reading the state ---------------------------------------------------------------------


def _recorded(
    inputs: dict[str, Any], kind: str, scene_id: str | None = None
) -> dict[str, Any] | None:
    """The artifact of this kind (and scene) that `inputs` says the version was built from."""
    for artifact in inputs.get("artifacts") or []:
        if (
            isinstance(artifact, dict)
            and artifact.get("kind") == kind
            and artifact.get("scene_id") == scene_id
        ):
            return artifact
    return None


def _out_of_date_reasons(row: MusicBible, loaded: _Loaded) -> list[str]:
    """Why this version is no longer current, one sentence each. Worked out on every read."""
    inputs = row.inputs if isinstance(row.inputs, dict) else {}
    reasons: list[str] = []

    story = loaded.story
    if story is None or not story.strip():
        reasons.append("The story is now empty.")
    elif inputs.get("story_sha256") != story_bible.story_sha256(story):
        reasons.append("The story has changed since this Music Bible was written.")

    if not provenance.same_row(_recorded(inputs, STORY_BIBLE_KIND), loaded.bible):
        reasons.append("The Story Bible has been written again since this Music Bible was made.")
    for kind, row_now, what in (
        (SCENE_DISCOVERY_KIND, loaded.scenes, "scenes"),
        (CHARACTER_DISCOVERY_KIND, loaded.characters, "characters"),
        (ENVIRONMENT_DISCOVERY_KIND, loaded.environments, "places"),
    ):
        recorded = _recorded(inputs, kind)
        if recorded is None and row_now is None:
            continue  # it had no such list, and has none now
        if not provenance.same_row(recorded, row_now):
            reasons.append(f"The list of {what} has changed since this Music Bible was made.")

    titles = {item["id"]: item["title"] for item in loaded.scene_items}
    for kind, what, entries in (
        (SCENE_DEFINITION_KIND, "definition", loaded.definitions),
        (SCENE_EVENTS_KIND, "events", loaded.events),
    ):
        for artifact in inputs.get("artifacts") or []:
            if not isinstance(artifact, dict) or artifact.get("kind") != kind:
                continue
            scene_id = artifact.get("scene_id")
            if scene_id not in titles:
                continue  # the scene is gone: the list of scenes has already been reported
            entry = entries.get(scene_id)
            if entry is None or entry.row is None:
                reasons.append(f"The scene '{titles[scene_id]}' has no {what} now.")
            elif not provenance.same_row(artifact, entry.row):
                reasons.append(
                    f"The {what} of the scene '{titles[scene_id]}' have been written again "
                    "since this Music Bible was made."
                )
    return reasons


@dataclass(frozen=True)
class MusicBibleState:
    """What the story workspace shows."""

    latest: MusicBible | None
    versions: list[MusicBible]
    # The newest job, whatever its status.
    job: Job | None
    out_of_date: bool
    reasons: list[str]
    needs_confirmation: bool
    # Why no Music Bible can be written yet, or None.
    blocked_reason: str | None
    music_enabled: bool
    max_themes: int
    # What the editor needs to offer: the scenes in story order, and what a theme may stand for.
    scenes: list[dict[str, str]]
    characters: list[dict[str, str]]
    places: list[dict[str, str]]


async def state(session: AsyncSession, project: Project) -> MusicBibleState:
    """The project's Music Bible with where it stands. Worked out on every read; nothing here
    is stored.
    """
    loaded = await _load(session, project)
    newest = await latest(session, project.id)
    reasons = _out_of_date_reasons(newest, loaded) if newest is not None else []
    return MusicBibleState(
        latest=newest,
        versions=await list_versions(session, project.id),
        job=await store.latest_job(session, project.id, JOB_TYPE),
        out_of_date=bool(reasons),
        reasons=reasons,
        needs_confirmation=needs_confirmation(newest),
        blocked_reason=loaded.blocked_reason,
        music_enabled=project.music_enabled,
        max_themes=await max_themes(session),
        scenes=[{"id": item["id"], "title": item["title"]} for item in loaded.scene_items],
        characters=[{"id": item["id"], "name": item["name"]} for item in loaded.character_items],
        places=[{"id": item["id"], "name": item["name"]} for item in loaded.place_items],
    )
