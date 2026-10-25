"""The Scene Staging stage of a story project (PHASE-051, `Path_ahead.md` Section 46).

Each scene that is defined and has its events gets one `stage_scene` job. The job asks the model
where each character of the scene stands, which way they face, which side of the screen they are
on and which side of the place is behind them, and `save_staging` stores the checked answer as
a new `scene_staging` row: one immutable row per run, numbered per scene, with the provenance
of the artifact convention (D-3). Like a scene definition, a staging belongs to the project
alone: nothing is written to the Character Lab and no pin moves.

The model reads the StoryBible, the scene, its definition, its events and the scene's
environment with its spatial plan (`services/scene_staging_writer`). The whole story is not
sent.

- A scene can only be staged when everything it reads is ready: the saved story, an up-to-date
  StoryBible and lists, the scene's definition and events (both current), and an environment
  whose definition has a spatial plan (PHASE-050). The reason says what is missing.
- `start_run` queues the job for one scene. `start_all` queues one for every scene that is not
  staged and current already and not being staged.
- `state` is what the story workspace shows: for each scene its status, why it is out of date,
  its newest staging and job. **Out of date is worked out on every read** and never stored.
- `save_staging` is called by the job and flushes without committing; the job commits it
  together with finishing itself. `save_manual` stores the user's edit (PHASE-037 pattern).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, SceneStaging, StoryBible
from app.jobs import store
from app.services import (
    provenance,
    scene_definition_writer,
    scene_definitions,
    scene_events,
    scene_staging_writer,
    story_bible,
)

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "stage_scene"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"
# Two presses on one scene make one job; two scenes run side by side.
DEDUPE_KEY: Final = "scene_id"

# How many of a project's newest staging jobs are read to find each scene's newest one.
_JOB_LOOKBACK: Final = 500

STORY_BIBLE_KIND: Final = "story_bible"
SCENE_DEFINITION_KIND: Final = "scene_definition"
SCENE_EVENTS_KIND: Final = "scene_events"
ENVIRONMENT_DEFINITION_KIND: Final = scene_definitions.ENVIRONMENT_DEFINITION_KIND
CHARACTER_DEFINITION_KIND: Final = scene_definitions.CHARACTER_DEFINITION_KIND

# `not_staged`: no staging was written for this scene. `staged`: written, and nothing it was
# built from has changed. `out_of_date`: written, and something it was built from has changed.
Status = Literal["not_staged", "staged", "out_of_date"]

MANUAL_REPLACE_MESSAGE: Final = (
    "The newest staging of this scene was written by you. Staging it again adds a new version "
    "from the model, so it has to be confirmed."
)
SKIPPED_MANUAL: Final = "Written by you: use this scene's own button to replace it."


class SceneStagingError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


def off_screen_of(definition: dict[str, Any]) -> list[str]:
    """The characters a scene definition says are only heard and never seen. A definition written
    before the field existed has none.
    """
    value = definition.get("off_screen")
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


@dataclass(frozen=True)
class SceneEntry:
    """One entry of the newest list of scenes and where its staging stands."""

    item: dict[str, Any]
    status: Status
    # Why a staged scene is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The newest staging of this scene, when it has one.
    row: SceneStaging | None
    # The newest staging job of this scene, whatever its status.
    job: Job | None
    # Whether the Stage button may be pressed, and the reason when it may not.
    can_run: bool
    blocked_reason: str | None
    # The discovered environment of the scene's definition, or None when it has none yet.
    environment_id: str | None = None

    @property
    def content(self) -> dict[str, Any] | None:
        return self.row.content if self.row is not None else None

    @property
    def needs_confirmation(self) -> bool:
        """Whether staging this scene again replaces a staging the user wrote."""
        return self.row is not None and self.row.source == SOURCE_MANUAL


@dataclass(frozen=True)
class StagingState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    # The discovered characters as `{id, name}` and the environments as `{id, name, zones}`, so
    # that a staging can be shown (and edited) by name.
    characters: list[dict[str, str]]
    environments: list[dict[str, Any]]
    entries: list[SceneEntry]
    # Why nothing can be staged yet, or None.
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    """A scene that "Stage all" did not start, and why."""

    scene_id: str
    title: str
    reason: str


@dataclass(frozen=True)
class StartAllResult:
    job_ids: list[int]
    skipped: list[Skipped]


@dataclass(frozen=True)
class _Loaded:
    """Everything a run or a read of the state needs, loaded once."""

    story: str | None
    bible: StoryBible | None
    scenes_version: int | None
    # The newest list's scenes and each one's definition and events entries, by scene id.
    items: list[dict[str, Any]]
    definitions: dict[str, scene_definitions.SceneEntry]
    events: dict[str, scene_events.SceneEntry]
    # The characters and environments that are linked and defined, by `(kind, discovery id)`.
    current: dict[tuple[str, str], scene_definitions.CurrentDefinition]
    characters: list[dict[str, str]]
    blocked_reason: str | None


async def _load(session: AsyncSession, project: Project) -> _Loaded:
    definitions_state = await scene_definitions.state(session, project)
    events_state = await scene_events.state(session, project)
    current = await scene_definitions.current_definitions(session, project)
    return _Loaded(
        story=project.script_text,
        bible=await story_bible.latest(session, project.id),
        scenes_version=definitions_state.scenes_version,
        items=[entry.item for entry in definitions_state.entries],
        definitions={entry.item["id"]: entry for entry in definitions_state.entries},
        events={entry.item["id"]: entry for entry in events_state.entries},
        current=current,
        characters=events_state.characters,
        blocked_reason=events_state.blocked_reason or definitions_state.blocked_reason,
    )


def _environment_of(
    loaded: _Loaded, definition: dict[str, Any]
) -> scene_definitions.CurrentDefinition | None:
    return loaded.current.get((ENVIRONMENT_DEFINITION_KIND, definition["environment_id"]))


def _environment_id_of(loaded: _Loaded, scene_id: str) -> str | None:
    """The discovered environment of the scene's newest definition, or None."""
    definition = loaded.definitions.get(scene_id)
    if definition is None or definition.row is None:
        return None
    value = definition.row.content.get("environment_id")
    return value if isinstance(value, str) else None


def _scene_refusal(loaded: _Loaded, scene_id: str) -> str | None:
    """Why this scene cannot be staged, from its definition, its events and its environment,
    or None.
    """
    definition = loaded.definitions.get(scene_id)
    if definition is None or definition.status == "not_defined" or definition.row is None:
        return "Define this scene first: its staging is written from its definition."
    if definition.status == "out_of_date":
        return "The definition of this scene is out of date. Define the scene again first."
    events = loaded.events.get(scene_id)
    if events is None or events.status == "not_extracted" or events.row is None:
        return "Extract this scene's events first: its staging is written from them."
    if events.status == "out_of_date":
        return "The events of this scene are out of date. Extract them again first."
    content = definition.row.content
    environment = _environment_of(loaded, content)
    if environment is None:
        return (
            f"The environment of this scene ({content['environment_id']}) is not linked and "
            "defined. Define the scene again first."
        )
    plan = (environment.definition or {}).get("spatial_plan")
    if not isinstance(plan, dict):
        return (
            f"The definition of {environment.name} has no spatial plan yet. Define the "
            "environment again first: it was written before spatial plans existed."
        )
    for character_id in content["characters"]:
        if (CHARACTER_DEFINITION_KIND, character_id) not in loaded.current:
            return (
                f"A character of this scene ({character_id}) is not linked and defined. "
                "Define the scene again first."
            )
    return None


# --- Starting runs ------------------------------------------------------------------------


@dataclass(frozen=True)
class _Prepared:
    """What the staging of one scene is made from: what a job is sent, and what a version
    records. A manual save records exactly what a job would (D-3).
    """

    scene: dict[str, Any]
    definition: dict[str, Any]
    events: list[dict[str, Any]]
    characters: list[dict[str, Any]]
    environment: dict[str, Any]
    spatial_plan: dict[str, Any]
    inputs: dict[str, Any]


def _prepare(project: Project, loaded: _Loaded, scene_id: str) -> _Prepared:
    """The inputs of this scene. Raises SceneStagingError when it cannot be staged. The caller
    has checked that the project is not blocked.
    """
    story, bible = loaded.story, loaded.bible
    assert story is not None and bible is not None  # the callers refuse a blocked state first
    refusal = _scene_refusal(loaded, scene_id)
    if refusal is not None:
        raise SceneStagingError(refusal)
    definition_entry = loaded.definitions[scene_id]
    events_entry = loaded.events[scene_id]
    assert definition_entry.row is not None and events_entry.row is not None
    definition = definition_entry.row.content
    environment = _environment_of(loaded, definition)
    assert environment is not None and environment.definition is not None
    scene = definition_entry.item

    characters: list[dict[str, Any]] = []
    for character_id in definition["characters"]:
        found = loaded.current[(CHARACTER_DEFINITION_KIND, character_id)]
        characters.append(
            {"id": character_id, "name": found.name, "description": found.description}
        )
    inputs = {
        "project_id": project.id,
        "scene_id": scene_id,
        "story_sha256": story_bible.story_sha256(story),
        "artifacts": [
            {"kind": STORY_BIBLE_KIND, "id": bible.id, "version": bible.version},
            {
                "kind": SCENE_DEFINITION_KIND,
                "id": definition_entry.row.id,
                "version": definition_entry.row.version,
            },
            {
                "kind": SCENE_EVENTS_KIND,
                "id": events_entry.row.id,
                "version": events_entry.row.version,
            },
            {
                "kind": ENVIRONMENT_DEFINITION_KIND,
                "id": environment.library_id,
                "version": environment.version,
                "discovery_id": environment.discovery_id,
                "name": environment.name,
                "definition_sha256": scene_definition_writer.definition_sha256(
                    environment.definition
                ),
            },
        ],
    }
    return _Prepared(
        scene={
            "index": scene["index"],
            "id": scene["id"],
            "title": scene["title"],
            "description": scene["description"],
        },
        definition=definition,
        events=events_entry.row.content["events"],
        characters=characters,
        environment={
            "id": environment.discovery_id,
            "name": environment.name,
            "description": environment.description,
            "definition": environment.definition,
        },
        spatial_plan=environment.definition["spatial_plan"],
        inputs=inputs,
    )


async def _queue(
    session: AsyncSession, project: Project, loaded: _Loaded, scene_id: str
) -> tuple[Job, bool]:
    """Queues the job for this scene, and returns `(job, created)`. `created` is False when the
    scene already has a job waiting or running, which is returned instead. Raises
    SceneStagingError when this scene cannot be staged. The caller has checked that the
    project is not blocked.
    """
    bible = loaded.bible
    assert bible is not None  # the callers refuse a blocked state first
    prepared = _prepare(project, loaded, scene_id)
    return await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "story_bible_id": bible.id,
            "story_bible_version": bible.version,
            "scene_id": scene_id,
            "scene": prepared.scene,
            "scene_definition": prepared.definition,
            "events": scene_staging_writer.events_for_model(prepared.events),
            "event_ids": [event["id"] for event in prepared.events],
            "characters": prepared.characters,
            "character_ids": [item["id"] for item in prepared.characters],
            "environment": prepared.environment,
            "spatial_plan": prepared.spatial_plan,
            # Written onto the version the job makes (D-3).
            "inputs": prepared.inputs,
        },
        dedupe_key=DEDUPE_KEY,
    )


async def start_run(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    *,
    confirm_replace_manual: bool = False,
) -> Job:
    """Queues the job that stages one scene, and commits. If that scene already has a job
    waiting or running, that job is returned and no new one is made. When the newest staging
    was written by the user, it is replaced only when `confirm_replace_manual` is true. Raises
    SceneStagingError.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise SceneStagingError(loaded.blocked_reason)
    if not any(item["id"] == scene_id for item in loaded.items):
        raise SceneStagingError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    newest = (await _newest_rows(session, project.id)).get(scene_id)
    if newest is not None and newest.source == SOURCE_MANUAL and not confirm_replace_manual:
        raise SceneStagingError(MANUAL_REPLACE_MESSAGE)
    job, _created = await _queue(session, project, loaded, scene_id)
    return job


async def start_all(session: AsyncSession, project: Project) -> StartAllResult:
    """Queues a job for every scene that is not staged and current already, can be staged and
    is not being staged, and commits each. Raises SceneStagingError when nothing can be staged
    yet.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise SceneStagingError(loaded.blocked_reason)
    current = {
        entry.item["id"]: entry for entry in (await _build(session, project, loaded)).entries
    }
    job_ids: list[int] = []
    skipped: list[Skipped] = []
    for item in loaded.items:
        entry = current[item["id"]]
        if entry.status == "staged":
            skipped.append(Skipped(item["id"], item["title"], "Already staged and up to date."))
            continue
        if entry.needs_confirmation:
            skipped.append(Skipped(item["id"], item["title"], SKIPPED_MANUAL))
            continue
        refusal = _scene_refusal(loaded, item["id"])
        if refusal is not None:
            skipped.append(Skipped(item["id"], item["title"], refusal))
            continue
        job, created = await _queue(session, project, loaded, item["id"])
        if created:
            job_ids.append(job.id)
        else:
            skipped.append(Skipped(item["id"], item["title"], "Already being staged."))
    return StartAllResult(job_ids=job_ids, skipped=skipped)


# --- Reading the state --------------------------------------------------------------------


def _recorded(inputs: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """The artifact of this kind that `inputs` says the staging was built from."""
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            return artifact
    return None


def _characters_changed(staging: dict[str, Any], definition: dict[str, Any]) -> bool:
    """Whether the characters of the scene no longer match the staging: the placed characters,
    in order, must be the definition's characters without the staging's off-screen ones, and
    everyone the definition says is only heard must be off screen in the staging.
    """
    off_screen = staging.get("off_screen") or []
    placed = [item["character_id"] for item in staging.get("placements", [])]
    expected = [item for item in definition["characters"] if item not in off_screen]
    return (
        placed != expected
        or not set(off_screen_of(definition)) <= set(off_screen)
        or not set(off_screen) <= set(definition["characters"])
    )


def _out_of_date_reasons(row: SceneStaging, loaded: _Loaded, scene_id: str) -> list[str]:
    """Why a staging written for this scene is no longer current, one sentence each."""
    inputs = row.inputs
    reasons: list[str] = []
    story = loaded.story
    if story is None or not story.strip():
        reasons.append("The story is now empty.")
    elif inputs.get("story_sha256") != story_bible.story_sha256(story):
        reasons.append("The story has changed since this staging was written.")

    recorded_bible = _recorded(inputs, STORY_BIBLE_KIND)
    recorded_bible_version = recorded_bible.get("version") if recorded_bible else None
    newest_bible_version = loaded.bible.version if loaded.bible is not None else None
    if not isinstance(recorded_bible_version, int) or (
        newest_bible_version is not None and newest_bible_version > recorded_bible_version
    ):
        reasons.append("The Story Bible has been written again since this staging was made.")

    definition = loaded.definitions.get(scene_id)
    if definition is None or definition.row is None:
        reasons.append("The scene has no definition now.")
    else:
        if definition.status == "out_of_date":
            reasons.append("The definition of the scene is out of date.")
        if not provenance.same_row(_recorded(inputs, SCENE_DEFINITION_KIND), definition.row):
            reasons.append("The scene has been defined again since this staging was made.")
        if _characters_changed(row.content, definition.row.content):
            reasons.append("The characters of the scene have changed.")

    events = loaded.events.get(scene_id)
    if events is None or events.row is None:
        reasons.append("The scene has no events now.")
    else:
        if events.status == "out_of_date":
            reasons.append("The events of the scene are out of date.")
        if not provenance.same_row(_recorded(inputs, SCENE_EVENTS_KIND), events.row):
            reasons.append("The events of the scene have been extracted again since.")

    recorded_environment = _recorded(inputs, ENVIRONMENT_DEFINITION_KIND)
    if recorded_environment is not None and definition is not None and definition.row is not None:
        environment = _environment_of(loaded, definition.row.content)
        name = recorded_environment.get("name") or recorded_environment.get("discovery_id")
        if environment is None:
            reasons.append(f"{name} is now not linked or not defined.")
        elif environment.library_id != recorded_environment.get("id"):
            reasons.append(f"{name} is now linked to a different environment.")
        elif scene_definition_writer.definition_sha256(
            environment.definition
        ) != recorded_environment.get("definition_sha256"):
            reasons.append(f"The definition of {name} has changed since this staging was made.")
    return reasons


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest staging job of each scene of the project, by its id."""
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


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, SceneStaging]:
    """The newest staging of each scene of the project, by its id."""
    statement = (
        select(SceneStaging)
        .where(SceneStaging.project_id == project_id)
        .order_by(SceneStaging.version.desc(), SceneStaging.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, SceneStaging] = {}
    for row in (await session.execute(statement)).scalars():
        if row.scene_id not in newest:
            newest[row.scene_id] = row
    return newest


def _environments_shown(loaded: _Loaded) -> list[dict[str, Any]]:
    """The linked, defined environments with their zones, so the editor can offer them."""
    shown: list[dict[str, Any]] = []
    for (kind, discovery_id), found in loaded.current.items():
        plan = (found.definition or {}).get("spatial_plan")
        if kind != ENVIRONMENT_DEFINITION_KIND or not isinstance(plan, dict):
            continue
        shown.append({"id": discovery_id, "name": found.name, "zones": plan["zones"]})
    return shown


async def _build(session: AsyncSession, project: Project, loaded: _Loaded) -> StagingState:
    jobs = await _newest_jobs(session, project.id)
    rows = await _newest_rows(session, project.id)

    entries: list[SceneEntry] = []
    for item in loaded.items:
        scene_id = item["id"]
        row = rows.get(scene_id)
        job = jobs.get(scene_id)
        active = job is not None and job.status in store.ACTIVE_STATUSES
        status: Status = "not_staged"
        reasons: list[str] = []
        if row is not None and isinstance(row.inputs, dict):
            reasons = _out_of_date_reasons(row, loaded, scene_id)
            status = "out_of_date" if reasons else "staged"
        blocked_reason = loaded.blocked_reason or _scene_refusal(loaded, scene_id)
        if blocked_reason is None and active:
            blocked_reason = "The scene is already being staged."
        entries.append(
            SceneEntry(
                item=item,
                status=status,
                reasons=reasons,
                row=row,
                job=job,
                can_run=blocked_reason is None,
                blocked_reason=blocked_reason,
                environment_id=_environment_id_of(loaded, scene_id),
            )
        )
    return StagingState(
        scenes_version=loaded.scenes_version,
        characters=loaded.characters,
        environments=_environments_shown(loaded),
        entries=entries,
        blocked_reason=loaded.blocked_reason,
    )


async def state(session: AsyncSession, project: Project) -> StagingState:
    """The newest list of scenes with where each scene's staging stands. Worked out on every
    read; nothing here is stored.
    """
    return await _build(session, project, await _load(session, project))


# --- Saving the staging -------------------------------------------------------------------


async def save_staging(
    session: AsyncSession,
    *,
    project_id: int,
    scene_id: str,
    content: dict[str, Any],
    job_id: int | None,
    inputs: dict[str, Any],
    source: str = SOURCE_AI,
) -> SceneStaging:
    """Adds the scene's next version. Flushes but does not commit: the job commits it together
    with finishing itself, so a job is never "succeeded" without its result.

    `job_id` is None and `source` is `manual` for a staging the user edited (`save_manual`).
    """
    statement = select(func.max(SceneStaging.version)).where(
        SceneStaging.project_id == project_id, SceneStaging.scene_id == scene_id
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = SceneStaging(
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
        "job %s: staging of scene '%s' of project %d saved, version %d",
        job_id,
        scene_id,
        project_id,
        row.version,
    )
    return row


async def accept_as_is(session: AsyncSession, project: Project, scene_id: str) -> SceneStaging:
    """Keeps the scene's newest staging as it is and records that it was made from what is
    current now (PHASE-039). Raises SceneStagingError.
    """
    newest = (await _newest_rows(session, project.id)).get(scene_id)
    if newest is None:
        raise SceneStagingError(f"Scene '{scene_id}' has no staging to accept.")
    return await save_manual(session, project, scene_id, newest.content, accepting=newest)


async def save_manual(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    content: dict[str, Any],
    *,
    accepting: SceneStaging | None = None,
) -> SceneStaging:
    """Stores the user's edited staging of one scene as its next version (`source` is
    `manual`), and commits (PHASE-037 pattern). It needs what a run needs (the scene's
    definition and events exist and are current) and is refused while the scene is being
    staged. The staging is checked the way the model's answer is (`check_answer`). With
    `accepting` (PHASE-039) it also records which version the user accepted as it is. Raises
    SceneStagingError.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise SceneStagingError(loaded.blocked_reason)
    if not any(item["id"] == scene_id for item in loaded.items):
        raise SceneStagingError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    job = (await _newest_jobs(session, project.id)).get(scene_id)
    if job is not None and job.status in store.ACTIVE_STATUSES:
        raise SceneStagingError("The scene is already being staged.")

    prepared = _prepare(project, loaded, scene_id)
    try:
        checked = scene_staging_writer.check_answer(
            content,
            scene_id,
            character_ids=[item["id"] for item in prepared.characters],
            event_ids=[event["id"] for event in prepared.events],
            spatial_plan=prepared.spatial_plan,
            fixed_off_screen=off_screen_of(prepared.definition),
        )
    except ValueError as exc:
        raise SceneStagingError(str(exc)) from exc
    row = await save_staging(
        session,
        project_id=project.id,
        scene_id=scene_id,
        content=checked,
        job_id=None,
        inputs=prepared.inputs,
        source=SOURCE_MANUAL,
    )
    if accepting is not None:
        row.inputs = provenance.accepted_inputs(row.inputs, accepting, row.content)
    await session.commit()
    return row
