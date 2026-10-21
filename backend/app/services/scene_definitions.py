"""The Scene Definition stage of a story project (PHASE-014, `Path_ahead.md` Section 16).

Each discovered scene (`services/discovery.py`, kind `scenes`) gets one `define_scene` job. The
job asks the model for the scene's dramatic definition and `save_definition` stores it as a new
`scene_definition` row: one immutable row per run, numbered per scene, with the provenance of
the artifact convention (D-3). Unlike the character and environment stages, nothing is written
to the Character Lab and no pin moves: a scene definition belongs to the project alone.

The model is given all of the story's character and environment definitions and chooses the
scene's environment and characters itself (scene discovery records no ids, D-15); code checks
the choice (`services/scene_definition_writer.check_definition`). The environment state and the
look names are stored as requests in the model's own words. PHASE-016 resolves them.

- A scene can only be defined when everything it reads is ready: the saved story, an up-to-date
  StoryBible, up-to-date lists of scenes, characters and environments, and **every** discovered
  character and environment linked and defined (`defined`, not `out_of_date`). The reason says
  what is missing.
- `start_run` queues the job for one scene. `start_all` queues one for every scene that is not
  defined and current already and not being defined. The jobs run side by side when the pool
  allows (`store.create_job` with `dedupe_key`).
- `state` is what the story workspace shows: for each scene its status, why it is out of date,
  its newest definition and job. **Out of date is worked out on every read** and never stored:
  the story or the StoryBible changed, the scene itself (or its neighbours' summaries) changed,
  or a character or the environment the scene chose is gone from the newest list, linked to
  another library object, or has a different definition. A definition's own hash is compared,
  not the pinned version number, because the images and voices of PHASE-010 and PHASE-011 move
  a pin without changing the definition. A character found again that the scene did not choose
  does not mark it.
- `save_definition` is called by the job and flushes without committing; the job commits it
  together with finishing itself. It records, among the artifacts the version was built from,
  the definitions of **only** the characters and the environment the scene chose, not every
  definition the model was shown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Job,
    LibraryCharacterVersion,
    Project,
    SceneDefinition,
    SceneDiscovery,
    StoryBible,
)
from app.jobs import store
from app.services import (
    character_definitions,
    discovery,
    environment_definitions,
    environment_versions,
    scene_definition_writer,
    story_bible,
)

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "define_scene"
# Two presses on one scene make one job; two scenes run side by side.
DEDUPE_KEY: Final = "scene_id"

# How many of a project's newest definition jobs are read to find each scene's newest one.
_JOB_LOOKBACK: Final = 500

STORY_BIBLE_KIND: Final = "story_bible"
CHARACTER_DISCOVERY_KIND: Final = "character_discovery"
ENVIRONMENT_DISCOVERY_KIND: Final = "environment_discovery"
SCENE_DISCOVERY_KIND: Final = "scene_discovery"
CHARACTER_DEFINITION_KIND: Final = "character_definition"
ENVIRONMENT_DEFINITION_KIND: Final = "environment_definition"

# `not_defined`: no definition was written for this scene. `defined`: written, and nothing it
# was built from has changed. `out_of_date`: written, and something it was built from has
# changed (see the reasons).
Status = Literal["not_defined", "defined", "out_of_date"]

_STATUS_WORDS: Final = {
    "unlinked": "not linked",
    "not_defined": "not defined",
    "out_of_date": "out of date",
}


class SceneDefinitionError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class SceneEntry:
    """One entry of the newest list of scenes and where its definition stands."""

    item: dict[str, Any]
    status: Status
    # Why a defined scene is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The newest definition of this scene, when it has one.
    row: SceneDefinition | None
    # The newest definition job of this scene, whatever its status.
    job: Job | None
    # Whether the Define button may be pressed, and the reason when it may not.
    can_run: bool
    blocked_reason: str | None

    @property
    def definition(self) -> dict[str, Any] | None:
        return self.row.content if self.row is not None else None


@dataclass(frozen=True)
class DefinitionsState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    entries: list[SceneEntry]
    # Why nothing can be defined yet, or None.
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    """A scene that "Define all" did not start, and why."""

    scene_id: str
    title: str
    reason: str


@dataclass(frozen=True)
class StartAllResult:
    job_ids: list[int]
    skipped: list[Skipped]


@dataclass(frozen=True)
class _Current:
    """A discovered character or environment as it stands now: what it is linked to and the
    definition its link pins.
    """

    kind: str
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
    environments: discovery.Discovery | None
    # The newest list's entries that are linked, by `(kind, discovery id)`.
    current: dict[tuple[str, str], _Current]
    # Every entry of the two newest lists that is not defined and current, with its status.
    not_ready: list[tuple[str, str]]
    blocked_reason: str | None


# --- Loading ------------------------------------------------------------------------------


async def _pinned_character_definition(
    session: AsyncSession, character_id: int, version: int
) -> dict[str, Any] | None:
    statement = select(LibraryCharacterVersion).where(
        LibraryCharacterVersion.character_id == character_id,
        LibraryCharacterVersion.version == version,
    )
    row = (await session.execute(statement)).scalars().first()
    return row.definition if row is not None else None


def _blocked_reason(
    story: str | None,
    bible: StoryBible | None,
    scenes: SceneDiscovery | None,
    characters: discovery.Discovery | None,
    environments: discovery.Discovery | None,
    not_ready: list[tuple[str, str]],
) -> str | None:
    """Why no scene can be defined, or None when one can."""
    if story is None or not story.strip():
        return "Save the story first: a scene is defined from the story."
    if bible is None:
        return "Run the Story Bible first: a scene is defined with its help."
    if story_bible.is_out_of_date(story, bible):
        return (
            "The Story Bible is out of date, because the story has changed since it was "
            "written. Re-run the Story Bible first, then define the scenes."
        )
    lists: list[tuple[str, discovery.Discovery | None]] = [
        ("scenes", scenes),
        ("characters", characters),
        ("environments", environments),
    ]
    for name, row in lists:
        if row is None:
            return f"Find the {name} first: a scene is defined with their help."
        if discovery.is_out_of_date(story, row, bible.version):
            return (
                f"The {name} are out of date, because the story or the Story Bible has changed "
                f"since they were found. Find the {name} again first, then define the scenes."
            )
    if not_ready:
        names = ", ".join(label for _kind, label in not_ready)
        return (
            "Every character and environment has to be linked and defined first, because a "
            f"scene chooses among them. Not ready: {names}."
        )
    return None


async def _load(session: AsyncSession, project: Project) -> _Loaded:
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    scenes = cast(SceneDiscovery | None, await discovery.latest(session, "scenes", project.id))
    characters = await discovery.latest(session, "characters", project.id)
    environments = await discovery.latest(session, "environments", project.id)

    current: dict[tuple[str, str], _Current] = {}
    not_ready: list[tuple[str, str]] = []
    if characters is not None:
        for entry in (await character_definitions.state(session, project)).entries:
            item = entry.item
            if entry.status != "defined" or entry.entry.info is None:
                word = _STATUS_WORDS.get(entry.status, entry.status)
                not_ready.append((CHARACTER_DEFINITION_KIND, f"{item['name']} ({word})"))
                continue
            link = entry.entry.info.link
            current[(CHARACTER_DEFINITION_KIND, item["id"])] = _Current(
                kind=CHARACTER_DEFINITION_KIND,
                discovery_id=item["id"],
                name=item["name"],
                description=item["description"],
                library_id=link.character_id,
                version=link.pinned_version,
                definition=await _pinned_character_definition(
                    session, link.character_id, link.pinned_version
                ),
            )
    if environments is not None:
        for env_entry in (await environment_definitions.state(session, project)).entries:
            item = env_entry.item
            if env_entry.status != "defined" or env_entry.entry.info is None:
                word = _STATUS_WORDS.get(env_entry.status, env_entry.status)
                not_ready.append((ENVIRONMENT_DEFINITION_KIND, f"{item['name']} ({word})"))
                continue
            link_env = env_entry.entry.info.link
            pinned = await environment_versions.get_version(
                session, link_env.environment_id, link_env.pinned_version
            )
            current[(ENVIRONMENT_DEFINITION_KIND, item["id"])] = _Current(
                kind=ENVIRONMENT_DEFINITION_KIND,
                discovery_id=item["id"],
                name=item["name"],
                description=item["description"],
                library_id=link_env.environment_id,
                version=link_env.pinned_version,
                definition=pinned.definition if pinned is not None else None,
            )

    return _Loaded(
        story=story,
        bible=bible,
        scenes=scenes,
        characters=characters,
        environments=environments,
        current=current,
        not_ready=not_ready,
        blocked_reason=_blocked_reason(story, bible, scenes, characters, environments, not_ready),
    )


def _scene_items(loaded: _Loaded) -> list[dict[str, Any]]:
    if loaded.scenes is None:
        return []
    return cast(list[dict[str, Any]], loaded.scenes.content["scenes"])


def _neighbours(
    items: list[dict[str, Any]], position: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    previous = items[position - 1] if position > 0 else None
    next_ = items[position + 1] if position + 1 < len(items) else None
    return previous, next_


def _summary(scene: dict[str, Any] | None) -> dict[str, str] | None:
    """A neighbouring scene as the model sees it: its id, title and description, no text."""
    if scene is None:
        return None
    return {"id": scene["id"], "title": scene["title"], "description": scene["description"]}


def _for_model(current: _Current) -> dict[str, Any]:
    """A character or environment as the model sees it."""
    return {
        "id": current.discovery_id,
        "name": current.name,
        "description": current.description,
        "definition": current.definition,
    }


def _shown(current: _Current) -> dict[str, Any]:
    """The record of one definition the model was shown, in the artifact shape of D-3."""
    return {
        "kind": current.kind,
        "id": current.library_id,
        "version": current.version,
        "discovery_id": current.discovery_id,
        "name": current.name,
        "definition_sha256": scene_definition_writer.definition_sha256(current.definition),
    }


# --- Starting runs ------------------------------------------------------------------------


async def _queue(
    session: AsyncSession, project: Project, loaded: _Loaded, position: int
) -> tuple[Job, bool]:
    """Queues the job for the scene at this position of the newest list, and returns
    `(job, created)`. `created` is False when the scene already has a job waiting or running,
    which is returned instead. The caller has checked that nothing is blocked.
    """
    story, bible = loaded.story, loaded.bible
    assert story is not None and bible is not None  # the callers refuse a blocked state first
    assert loaded.scenes is not None and loaded.characters is not None
    assert loaded.environments is not None
    items = _scene_items(loaded)
    scene = items[position]
    previous, next_ = _neighbours(items, position)
    story_hash = story_bible.story_sha256(story)

    characters = [
        current for current in loaded.current.values() if current.kind == CHARACTER_DEFINITION_KIND
    ]
    environments = [
        current
        for current in loaded.current.values()
        if current.kind == ENVIRONMENT_DEFINITION_KIND
    ]
    inputs = {
        "project_id": project.id,
        "scene_id": scene["id"],
        "story_sha256": story_hash,
        "scene_sha256": scene_definition_writer.scene_sha256(scene, previous, next_),
        "artifacts": [
            {"kind": STORY_BIBLE_KIND, "id": bible.id, "version": bible.version},
            {
                "kind": CHARACTER_DISCOVERY_KIND,
                "id": loaded.characters.id,
                "version": loaded.characters.version,
            },
            {
                "kind": ENVIRONMENT_DISCOVERY_KIND,
                "id": loaded.environments.id,
                "version": loaded.environments.version,
            },
            {
                "kind": SCENE_DISCOVERY_KIND,
                "id": loaded.scenes.id,
                "version": loaded.scenes.version,
            },
        ],
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
            "scene_id": scene["id"],
            "scene": {
                "index": scene["index"],
                "id": scene["id"],
                "title": scene["title"],
                "description": scene["description"],
                "text": scene["text"],
            },
            "previous": _summary(previous),
            "next": _summary(next_),
            "characters": [_for_model(current) for current in characters],
            "environments": [_for_model(current) for current in environments],
            # What the model was shown, so that only what it chooses is recorded (D-3).
            "shown": [_shown(current) for current in characters + environments],
            # Written onto the version the job makes (D-3).
            "inputs": inputs,
        },
        dedupe_key=DEDUPE_KEY,
    )


async def start_run(session: AsyncSession, project: Project, scene_id: str) -> Job:
    """Queues the job that defines one scene, and commits. If that scene already has a job
    waiting or running, that job is returned and no new one is made. Raises
    SceneDefinitionError.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise SceneDefinitionError(loaded.blocked_reason)
    items = _scene_items(loaded)
    position = next((i for i, item in enumerate(items) if item["id"] == scene_id), None)
    if position is None:
        raise SceneDefinitionError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    job, _created = await _queue(session, project, loaded, position)
    return job


async def start_all(session: AsyncSession, project: Project) -> StartAllResult:
    """Queues a job for every scene that is not defined and current already and not being
    defined, and commits each. Raises SceneDefinitionError when nothing can be defined yet.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise SceneDefinitionError(loaded.blocked_reason)
    current = {
        entry.item["id"]: entry for entry in (await _build(session, project, loaded)).entries
    }
    job_ids: list[int] = []
    skipped: list[Skipped] = []
    for position, item in enumerate(_scene_items(loaded)):
        if current[item["id"]].status == "defined":
            skipped.append(Skipped(item["id"], item["title"], "Already defined and up to date."))
            continue
        job, created = await _queue(session, project, loaded, position)
        if created:
            job_ids.append(job.id)
        else:
            skipped.append(Skipped(item["id"], item["title"], "Already being defined."))
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
    scene_hash: str,
    current: dict[tuple[str, str], _Current],
    listed: dict[str, set[str]],
) -> list[str]:
    """Why a definition written for this scene is no longer current, one sentence each.
    `listed` is the ids of the newest lists of characters and environments, by artifact kind.
    """
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
    if inputs.get("scene_sha256") != scene_hash:
        reasons.append("The scene, or the scene before or after it, has changed.")

    for artifact in inputs.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        kind = artifact.get("kind")
        if kind not in (CHARACTER_DEFINITION_KIND, ENVIRONMENT_DEFINITION_KIND):
            continue
        discovery_id = artifact.get("discovery_id")
        name = artifact.get("name") or discovery_id
        what = "character" if kind == CHARACTER_DEFINITION_KIND else "environment"
        if discovery_id not in listed.get(kind, set()):
            reasons.append(f"{name} is no longer in the list of {what}s.")
            continue
        now = current.get((kind, discovery_id))
        if now is None or now.library_id != artifact.get("id"):
            reasons.append(f"{name} is now linked to a different {what}, or not linked.")
        elif scene_definition_writer.definition_sha256(now.definition) != artifact.get(
            "definition_sha256"
        ):
            reasons.append(f"The definition of {name} has changed since this one was written.")
    return reasons


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest definition job of each scene of the project, by its id."""
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


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, SceneDefinition]:
    """The newest definition of each scene of the project, by its id."""
    statement = (
        select(SceneDefinition)
        .where(SceneDefinition.project_id == project_id)
        .order_by(SceneDefinition.version.desc(), SceneDefinition.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, SceneDefinition] = {}
    for row in (await session.execute(statement)).scalars():
        if row.scene_id not in newest:
            newest[row.scene_id] = row
    return newest


def _list_ids(row: discovery.Discovery | None, key: str) -> set[str]:
    if row is None:
        return set()
    return {item["id"] for item in row.content[key]}


async def _build(session: AsyncSession, project: Project, loaded: _Loaded) -> DefinitionsState:
    items = _scene_items(loaded)
    jobs = await _newest_jobs(session, project.id)
    rows = await _newest_rows(session, project.id)
    listed = {
        CHARACTER_DEFINITION_KIND: _list_ids(loaded.characters, "characters"),
        ENVIRONMENT_DEFINITION_KIND: _list_ids(loaded.environments, "environments"),
    }
    newest_bible_version = loaded.bible.version if loaded.bible is not None else None

    entries: list[SceneEntry] = []
    for position, item in enumerate(items):
        row = rows.get(item["id"])
        job = jobs.get(item["id"])
        active = job is not None and job.status in store.ACTIVE_STATUSES
        status: Status = "not_defined"
        reasons: list[str] = []
        if row is not None and isinstance(row.inputs, dict):
            previous, next_ = _neighbours(items, position)
            reasons = _out_of_date_reasons(
                row.inputs,
                loaded.story,
                newest_bible_version,
                scene_definition_writer.scene_sha256(item, previous, next_),
                loaded.current,
                listed,
            )
            status = "out_of_date" if reasons else "defined"
        blocked_reason = loaded.blocked_reason
        if blocked_reason is None and active:
            blocked_reason = "A definition is already being written."
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
    return DefinitionsState(
        scenes_version=loaded.scenes.version if loaded.scenes is not None else None,
        entries=entries,
        blocked_reason=loaded.blocked_reason,
    )


async def state(session: AsyncSession, project: Project) -> DefinitionsState:
    """The newest list of scenes with where each definition stands. Worked out on every read;
    nothing here is stored.
    """
    return await _build(session, project, await _load(session, project))


# --- Saving a definition ------------------------------------------------------------------


async def save_definition(
    session: AsyncSession,
    *,
    project_id: int,
    scene_id: str,
    definition: dict[str, Any],
    job_id: int,
    inputs: dict[str, Any],
    shown: list[dict[str, Any]],
) -> SceneDefinition:
    """Adds the scene's next version. Flushes but does not commit: the job commits it together
    with finishing itself, so a job is never "succeeded" without its result.

    `inputs` is what the job was started with; the definition of each character and the
    environment the model chose is added to its artifacts, taken from `shown`. A definition the
    model was shown and did not choose is not recorded, so a scene is only out of date because
    of what it uses.
    """
    chosen: list[tuple[str, str]] = [
        (ENVIRONMENT_DEFINITION_KIND, definition["environment_id"]),
        *((CHARACTER_DEFINITION_KIND, character) for character in definition["characters"]),
    ]
    recorded = [
        record
        for kind, discovery_id in chosen
        for record in shown
        if record.get("kind") == kind and record.get("discovery_id") == discovery_id
    ]
    stored_inputs = {**inputs, "artifacts": [*inputs.get("artifacts", []), *recorded]}

    statement = select(func.max(SceneDefinition.version)).where(
        SceneDefinition.project_id == project_id, SceneDefinition.scene_id == scene_id
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = SceneDefinition(
        project_id=project_id,
        scene_id=scene_id,
        version=(highest or 0) + 1,
        source="ai",
        job_id=job_id,
        inputs=stored_inputs,
        content=definition,
    )
    session.add(row)
    await session.flush()
    _logger.info(
        "job %d: scene '%s' of project %d defined, version %d",
        job_id,
        scene_id,
        project_id,
        row.version,
    )
    return row
