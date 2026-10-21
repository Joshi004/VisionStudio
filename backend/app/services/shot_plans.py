"""The Shot Planning stage of a story project (PHASE-020, `Path_ahead.md` Sections 22 and 25).

Each scene whose speech has been made gets one `plan_shots` job. The job asks the model how the
audience should see the scene's events, and `save_shot_plan` stores the checked answer as a new
`shot_plan` row: one immutable row per run, numbered per scene, with the provenance of the
artifact convention (D-3). Like a scene's events, a shot plan belongs to the project alone:
nothing is written to the Character Lab and no pin moves.

The model reads the StoryBible, the scene, its definition, the definitions of the characters it
chose and of its environment, its events, its speech units with the **measured** length of their
audio, and the planning target range of the duration policy (D-8). Code checks the answer
(`services/shot_planning_writer`).

- A scene can only be planned when everything it reads is ready: its definition, its events and
  its speech plan exist and are current, and **every** speech unit has its audio made, with a
  measured length. Estimates are never used. The reason says what is missing.
- `start_run` queues the job for one scene. `start_all` queues one for every scene that is not
  planned and current already and not being planned. The jobs run side by side when the pool
  allows (`store.create_job` with `dedupe_key`).
- `state` is what the story workspace shows: for each scene its status, why it is out of date,
  its newest plan and job. **Out of date is worked out on every read** and never stored: the
  story, the scene, the StoryBible, the definition, the events or the speech plan changed, the
  audio of a unit was made again, a character or the environment the scene chose has another
  definition (its hash, not the pinned version number, as in PHASE-014), or the planning
  target range is not what the plan was made with.
- `save_shot_plan` is called by the job and flushes without committing; the job commits it
  together with finishing itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, SceneDiscovery, ShotPlan, StoryBible
from app.jobs import store
from app.services import (
    discovery,
    duration_policy,
    event_extraction_writer,
    scene_definition_writer,
    scene_definitions,
    speech_synthesis,
    story_bible,
)

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "plan_shots"
# Two presses on one scene make one job; two scenes run side by side.
DEDUPE_KEY: Final = "scene_id"

# How many of a project's newest planning jobs are read to find each scene's newest one.
_JOB_LOOKBACK: Final = 500

STORY_BIBLE_KIND: Final = "story_bible"
SCENE_DISCOVERY_KIND: Final = "scene_discovery"
SCENE_DEFINITION_KIND: Final = "scene_definition"
SCENE_EVENTS_KIND: Final = "scene_events"
SPEECH_UNITS_KIND: Final = "speech_units"
SPEECH_AUDIO_KIND: Final = "speech_unit_audio"
CHARACTER_DEFINITION_KIND: Final = scene_definitions.CHARACTER_DEFINITION_KIND
ENVIRONMENT_DEFINITION_KIND: Final = scene_definitions.ENVIRONMENT_DEFINITION_KIND

# `not_planned`: no shots were planned for this scene. `planned`: planned, and nothing the plan
# was built from has changed. `out_of_date`: planned, and something it was built from has
# changed (see the reasons).
Status = Literal["not_planned", "planned", "out_of_date"]

# What a unit's audio status reads as when it is listed as not ready.
_UNIT_WORDS: Final = {
    "unavailable": "no voice",
    "none": "not made",
    "in_progress": "being made",
    "failed": "failed",
    "out_of_date": "out of date",
}


class ShotPlansError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class SceneEntry:
    """One entry of the newest list of scenes and where its shot plan stands."""

    item: dict[str, Any]
    status: Status
    # Why a planned scene is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The newest plan of this scene, when it has one.
    row: ShotPlan | None
    # The newest planning job of this scene, whatever its status.
    job: Job | None
    # Whether the Plan button may be pressed, and the reason when it may not.
    can_run: bool
    blocked_reason: str | None

    @property
    def content(self) -> dict[str, Any] | None:
        return self.row.content if self.row is not None else None


@dataclass(frozen=True)
class ShotPlansState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    # The planning target range the next plan would be given, or None when the policy cannot
    # be used.
    target_min_seconds: int | None
    target_max_seconds: int | None
    entries: list[SceneEntry]
    # Why nothing can be planned yet, or None.
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    """A scene that "Plan all" did not start, and why."""

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
    scenes: SceneDiscovery | None
    audio: speech_synthesis.AudioState
    # The newest scene definitions, by scene id.
    definitions: dict[str, scene_definitions.SceneEntry]
    # The characters and environments that are linked and defined, by `(kind, discovery id)`.
    current: dict[tuple[str, str], scene_definitions.CurrentDefinition]
    policy: duration_policy.DurationPolicy | None
    blocked_reason: str | None


# --- Loading ------------------------------------------------------------------------------


async def _load(session: AsyncSession, project: Project) -> _Loaded:
    audio = await speech_synthesis.state(session, project)
    definitions = {
        entry.item["id"]: entry
        for entry in (await scene_definitions.state(session, project)).entries
    }
    current = await scene_definitions.current_definitions(session, project)
    scenes = cast(SceneDiscovery | None, await discovery.latest(session, "scenes", project.id))

    policy: duration_policy.DurationPolicy | None = None
    policy_problem: str | None = None
    try:
        policy = await duration_policy.read_duration_policy(session)
    except duration_policy.DurationPolicyError as exc:
        policy_problem = str(exc)

    return _Loaded(
        story=project.script_text,
        bible=await story_bible.latest(session, project.id),
        scenes=scenes,
        audio=audio,
        definitions=definitions,
        current=current,
        policy=policy,
        blocked_reason=policy_problem or audio.blocked_reason,
    )


def _unit_problems(scene: speech_synthesis.SceneAudio) -> list[str]:
    """The units of a scene whose audio is not ready, as `su_2 (not made)`."""
    problems: list[str] = []
    for item in scene.units:
        if item.status != "ready":
            problems.append(f"{item.unit['id']} ({_UNIT_WORDS.get(item.status, item.status)})")
        elif item.audio is None or item.audio.duration_s is None:
            problems.append(f"{item.unit['id']} (length not measured)")
    return problems


def _chosen(definition: dict[str, Any]) -> list[tuple[str, str]]:
    """What a scene definition chose, as `(kind, discovery id)`: its environment, then its
    characters.
    """
    return [
        (ENVIRONMENT_DEFINITION_KIND, definition["environment_id"]),
        *((CHARACTER_DEFINITION_KIND, character) for character in definition["characters"]),
    ]


def _scene_refusal(
    scene: speech_synthesis.SceneAudio,
    definition: scene_definitions.SceneEntry | None,
    current: dict[tuple[str, str], scene_definitions.CurrentDefinition],
) -> str | None:
    """Why this scene's shots cannot be planned now, or None."""
    if definition is None or definition.row is None:
        return "Define this scene first: its shots are planned from its definition."
    if definition.status == "out_of_date":
        return "The definition of this scene is out of date. Define the scene again first."
    events = scene.scene.events
    if events.row is None:
        return "Extract this scene's events first: its shots are planned from them."
    if events.status == "out_of_date":
        return "The events of this scene are out of date. Extract them again first."
    if scene.scene.row is None:
        return "Plan this scene's speech units first: its shots carry them."
    if scene.scene.status == "out_of_date":
        return "The speech units of this scene are out of date. Plan them again first."
    problems = _unit_problems(scene)
    if problems:
        return "Make the speech of every unit first. Not ready: " + ", ".join(problems) + "."
    for kind, discovery_id in _chosen(definition.row.content):
        if (kind, discovery_id) not in current:
            what = "environment" if kind == ENVIRONMENT_DEFINITION_KIND else "character"
            return (
                f"The {what} '{discovery_id}' of this scene is not linked and defined. "
                "Define the scene again first."
            )
    return None


# --- Starting runs ------------------------------------------------------------------------


def _shown(
    kind: str, discovery_id: str, current: scene_definitions.CurrentDefinition
) -> dict[str, Any]:
    """The record of one definition the model was shown, in the artifact shape of D-3."""
    return {
        "kind": kind,
        "id": current.library_id,
        "version": current.version,
        "discovery_id": discovery_id,
        "name": current.name,
        "definition_sha256": scene_definition_writer.definition_sha256(current.definition),
    }


def _for_model(current: scene_definitions.CurrentDefinition) -> dict[str, Any]:
    return {
        "id": current.discovery_id,
        "name": current.name,
        "description": current.description,
        "definition": current.definition,
    }


async def _queue(
    session: AsyncSession, project: Project, loaded: _Loaded, scene: speech_synthesis.SceneAudio
) -> tuple[Job, bool]:
    """Queues the job for this scene and returns `(job, created)`. `created` is False when the
    scene already has a job waiting or running, which is returned instead. Raises
    ShotPlansError when this scene cannot be planned. The caller has checked that the project
    is not blocked.
    """
    story, bible, policy = loaded.story, loaded.bible, loaded.policy
    assert story is not None and bible is not None and policy is not None  # not blocked
    assert loaded.scenes is not None  # not blocked

    item = scene.scene.item
    definition_entry = loaded.definitions.get(item["id"])
    refusal = _scene_refusal(scene, definition_entry, loaded.current)
    if refusal is not None:
        raise ShotPlansError(refusal)
    assert definition_entry is not None and definition_entry.row is not None
    events_row = scene.scene.events.row
    plan_row = scene.scene.row
    assert events_row is not None and plan_row is not None  # the refusal made sure
    definition_row = definition_entry.row
    definition = definition_row.content

    environment_key = (ENVIRONMENT_DEFINITION_KIND, definition["environment_id"])
    chosen_characters = [
        (CHARACTER_DEFINITION_KIND, character_id) for character_id in definition["characters"]
    ]
    chosen = [environment_key, *chosen_characters]

    units: list[dict[str, Any]] = []
    audio_artifacts: list[dict[str, Any]] = []
    for entry in scene.units:
        audio = entry.audio
        assert audio is not None and audio.duration_s is not None  # the refusal made sure
        unit = entry.unit
        units.append(
            {
                "id": unit["id"],
                "event_id": unit["event_id"],
                "kind": unit["kind"],
                "speaker_id": unit["speaker_id"],
                "text": unit["text"],
                "measured_seconds": round(audio.duration_s, 2),
            }
        )
        audio_artifacts.append(
            {
                "kind": SPEECH_AUDIO_KIND,
                "unit_id": unit["id"],
                "id": audio.id,
                "audio_key": audio.audio_key,
                "duration_s": audio.duration_s,
            }
        )

    inputs = {
        "project_id": project.id,
        "scene_id": item["id"],
        "story_sha256": story_bible.story_sha256(story),
        "scene_text_sha256": event_extraction_writer.scene_text_sha256(item["text"]),
        "artifacts": [
            {"kind": STORY_BIBLE_KIND, "id": bible.id, "version": bible.version},
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
            {"kind": SCENE_EVENTS_KIND, "id": events_row.id, "version": events_row.version},
            {"kind": SPEECH_UNITS_KIND, "id": plan_row.id, "version": plan_row.version},
            *audio_artifacts,
            *(
                _shown(kind, discovery_id, loaded.current[(kind, discovery_id)])
                for kind, discovery_id in chosen
            ),
        ],
        "rules": {
            "target_min_s": policy.target_min_s,
            "target_max_s": policy.target_max_s,
        },
    }
    return await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "story_bible_id": bible.id,
            "story_bible_version": bible.version,
            "scene_id": item["id"],
            "scene": {
                "index": item["index"],
                "id": item["id"],
                "title": item["title"],
                "description": item["description"],
            },
            "scene_definition": definition,
            "scene_characters": [_for_model(loaded.current[key]) for key in chosen_characters],
            "environment": _for_model(loaded.current[environment_key]),
            "events": events_row.content["events"],
            "units": units,
            "target_min_seconds": policy.target_min_s,
            "target_max_seconds": policy.target_max_s,
            # Written onto the version the job makes (D-3).
            "inputs": inputs,
        },
        dedupe_key=DEDUPE_KEY,
    )


def _find_scene(loaded: _Loaded, scene_id: str) -> speech_synthesis.SceneAudio:
    for scene in loaded.audio.scenes:
        if scene.scene.item["id"] == scene_id:
            return scene
    raise ShotPlansError(f"There is no scene '{scene_id}' in the newest list of scenes.")


async def start_run(session: AsyncSession, project: Project, scene_id: str) -> Job:
    """Queues the job that plans one scene's shots, and commits. If that scene already has a
    job waiting or running, that job is returned and no new one is made. Raises
    ShotPlansError.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise ShotPlansError(loaded.blocked_reason)
    _blocked_by_story(loaded)
    scene = _find_scene(loaded, scene_id)
    job, _created = await _queue(session, project, loaded, scene)
    return job


def _blocked_by_story(loaded: _Loaded) -> None:
    """Raises ShotPlansError when the story, the StoryBible or the list of scenes is missing.
    The scene's own refusals (a stale definition, events or speech) say the rest.
    """
    if loaded.story is None or not loaded.story.strip():
        raise ShotPlansError("Save the story first: shots are planned from the story's events.")
    if loaded.bible is None:
        raise ShotPlansError("Run the Story Bible first: shots are planned with its help.")
    if loaded.scenes is None:
        raise ShotPlansError("Find the scenes first.")


async def start_all(session: AsyncSession, project: Project) -> StartAllResult:
    """Queues a job for every scene that is not planned and current already, can be planned
    and is not being planned. Raises ShotPlansError when nothing can be planned yet.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise ShotPlansError(loaded.blocked_reason)
    _blocked_by_story(loaded)
    current = {
        entry.item["id"]: entry for entry in (await _build(session, project, loaded)).entries
    }
    job_ids: list[int] = []
    skipped: list[Skipped] = []
    for scene in loaded.audio.scenes:
        item = scene.scene.item
        entry = current[item["id"]]
        if entry.status == "planned":
            skipped.append(Skipped(item["id"], item["title"], "Already planned and up to date."))
            continue
        refusal = _scene_refusal(scene, loaded.definitions.get(item["id"]), loaded.current)
        if refusal is not None:
            skipped.append(Skipped(item["id"], item["title"], refusal))
            continue
        job, created = await _queue(session, project, loaded, scene)
        if created:
            job_ids.append(job.id)
        else:
            skipped.append(Skipped(item["id"], item["title"], "Already being planned."))
    return StartAllResult(job_ids=job_ids, skipped=skipped)


# --- Reading the state --------------------------------------------------------------------


def _recorded(inputs: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """The first artifact of this kind that `inputs` says the plan was built from."""
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            return artifact
    return None


def _newer_than_recorded(inputs: dict[str, Any], kind: str, newest: int | None) -> bool:
    """True when the plan did not record this artifact, or a newer version exists now."""
    recorded = _recorded(inputs, kind)
    version = recorded.get("version") if recorded else None
    return not isinstance(version, int) or (newest is not None and newest > version)


def _out_of_date_reasons(
    row: ShotPlan,
    loaded: _Loaded,
    scene: speech_synthesis.SceneAudio,
    definition: scene_definitions.SceneEntry | None,
) -> list[str]:
    """Why a plan made for this scene is no longer current, one sentence each."""
    inputs = row.inputs
    reasons: list[str] = []
    story = loaded.story
    if story is None or not story.strip():
        reasons.append("The story is now empty.")
    elif inputs.get("story_sha256") != story_bible.story_sha256(story):
        reasons.append("The story has changed since these shots were planned.")

    newest_bible = loaded.bible.version if loaded.bible is not None else None
    if _newer_than_recorded(inputs, STORY_BIBLE_KIND, newest_bible):
        reasons.append("The Story Bible has been written again since these shots were planned.")

    if inputs.get("scene_text_sha256") != event_extraction_writer.scene_text_sha256(
        scene.scene.item["text"]
    ):
        reasons.append("The text of the scene has changed.")

    if definition is None or definition.row is None:
        reasons.append("The scene has no definition now.")
    else:
        if definition.status == "out_of_date":
            reasons.append("The definition of the scene is out of date.")
        if _newer_than_recorded(inputs, SCENE_DEFINITION_KIND, definition.row.version):
            reasons.append("The scene has been defined again since these shots were planned.")

    events = scene.scene.events
    if events.row is None:
        reasons.append("The scene has no events now.")
    else:
        if events.status == "out_of_date":
            reasons.append("The events of the scene are out of date.")
        if _newer_than_recorded(inputs, SCENE_EVENTS_KIND, events.row.version):
            reasons.append("The events of the scene were extracted again since these shots.")

    if scene.scene.row is None:
        reasons.append("The scene has no speech units now.")
    else:
        if scene.scene.status == "out_of_date":
            reasons.append("The speech units of the scene are out of date.")
        if _newer_than_recorded(inputs, SPEECH_UNITS_KIND, scene.scene.row.version):
            reasons.append("The speech units were planned again since these shots were planned.")

    now = {item.unit["id"]: item for item in scene.units}
    for artifact in inputs.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        kind = artifact.get("kind")
        if kind == SPEECH_AUDIO_KIND:
            unit_id = artifact.get("unit_id")
            item = now.get(unit_id)
            if item is None:
                continue  # The plan changed; the line above says so.
            if item.status != "ready" or item.audio is None:
                reasons.append(f"The speech of {unit_id} is no longer ready.")
            elif item.audio.id != artifact.get("id"):
                reasons.append(f"The speech of {unit_id} has been made again.")
        elif kind in (CHARACTER_DEFINITION_KIND, ENVIRONMENT_DEFINITION_KIND):
            discovery_id = artifact.get("discovery_id")
            name = artifact.get("name") or discovery_id
            here = loaded.current.get((kind, discovery_id))
            if here is None or here.library_id != artifact.get("id"):
                reasons.append(f"{name} is now linked to something else, or not linked.")
            elif scene_definition_writer.definition_sha256(here.definition) != artifact.get(
                "definition_sha256"
            ):
                reasons.append(f"The definition of {name} has changed since these shots.")

    policy = loaded.policy
    recorded_rules = inputs.get("rules") or {}
    if policy is not None and (
        recorded_rules.get("target_min_s") != policy.target_min_s
        or recorded_rules.get("target_max_s") != policy.target_max_s
    ):
        reasons.append("The planning target range has changed since these shots were planned.")
    return reasons


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest planning job of each scene of the project, by its id."""
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


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, ShotPlan]:
    """The newest plan of each scene of the project, by its id."""
    statement = (
        select(ShotPlan)
        .where(ShotPlan.project_id == project_id)
        .order_by(ShotPlan.version.desc(), ShotPlan.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, ShotPlan] = {}
    for row in (await session.execute(statement)).scalars():
        if row.scene_id not in newest:
            newest[row.scene_id] = row
    return newest


async def _build(session: AsyncSession, project: Project, loaded: _Loaded) -> ShotPlansState:
    jobs = await _newest_jobs(session, project.id)
    rows = await _newest_rows(session, project.id)

    entries: list[SceneEntry] = []
    for scene in loaded.audio.scenes:
        item = scene.scene.item
        row = rows.get(item["id"])
        job = jobs.get(item["id"])
        active = job is not None and job.status in store.ACTIVE_STATUSES
        definition = loaded.definitions.get(item["id"])
        status: Status = "not_planned"
        reasons: list[str] = []
        if row is not None and isinstance(row.inputs, dict):
            reasons = _out_of_date_reasons(row, loaded, scene, definition)
            status = "out_of_date" if reasons else "planned"
        blocked_reason = loaded.blocked_reason or _scene_refusal(scene, definition, loaded.current)
        if blocked_reason is None and active:
            blocked_reason = "The shots are already being planned."
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
    policy = loaded.policy
    return ShotPlansState(
        scenes_version=loaded.audio.scenes_version,
        target_min_seconds=policy.target_min_s if policy is not None else None,
        target_max_seconds=policy.target_max_s if policy is not None else None,
        entries=entries,
        blocked_reason=loaded.blocked_reason,
    )


async def state(session: AsyncSession, project: Project) -> ShotPlansState:
    """The newest list of scenes with where each scene's shot plan stands. Worked out on every
    read; nothing here is stored.
    """
    return await _build(session, project, await _load(session, project))


# --- Saving the plan ----------------------------------------------------------------------


async def save_shot_plan(
    session: AsyncSession,
    *,
    project_id: int,
    scene_id: str,
    content: dict[str, Any],
    job_id: int,
    inputs: dict[str, Any],
) -> ShotPlan:
    """Adds the scene's next version. Flushes but does not commit: the job commits it together
    with finishing itself, so a job is never "succeeded" without its result.

    `inputs` is what the job was started with and is stored as it is.
    """
    statement = select(func.max(ShotPlan.version)).where(
        ShotPlan.project_id == project_id, ShotPlan.scene_id == scene_id
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = ShotPlan(
        project_id=project_id,
        scene_id=scene_id,
        version=(highest or 0) + 1,
        source="ai",
        job_id=job_id,
        inputs=inputs,
        content=content,
    )
    session.add(row)
    await session.flush()
    _logger.info(
        "job %d: shot plan of scene '%s' of project %d saved, version %d",
        job_id,
        scene_id,
        project_id,
        row.version,
    )
    return row
