"""The Shot Definition stage of a story project (PHASE-022, `Path_ahead.md` Sections 26 and 27).

Each planned shot gets one `define_shot` job. The job asks the model exactly how that one shot
looks, moves and sounds, and `save_shot_definition` stores the checked answer as a new
`shot_definition` row: one immutable row per run, numbered per shot, with the provenance of the
artifact convention (D-3). Like a shot plan, a shot definition belongs to the project alone:
nothing is written to the Character Lab and no pin moves.

The model reads the StoryBible, the scene and its definition, the shot's skeleton and its source
events, the speech heard during the shot, the characters of the scene with the look each
resolved to (PHASE-016), the environment with its resolved state, and the skeletons of the shots
before and after it. Code checks the answer (`services/shot_definition_writer`) and writes the
shot's id, its duration (from the scene's timeline, PHASE-021) and its dialogue.

- A scene's shots can only be defined when everything they read is ready: the scene's shot plan
  is current and its timeline is **ready for generation** (no planning job running, no blocking
  problem), the project's look and state resolution exists, is current and covers the scene, and
  every character and the environment the scene chose is linked and defined. The reason says
  what is missing.
- `start_shot` queues the job for one shot, `start_scene` one for every shot of a scene that is
  not defined and current and not being defined, and `start_all` the same for every scene. The
  jobs run side by side when the pool allows (`store.create_job` with `dedupe_key`).
- `state` is what the story workspace shows: for each scene its shots with their status, why a
  shot is out of date, its newest specification and job. **Out of date is worked out on every
  read** and never stored: the scene's shots were planned again, the shot plan is out of date
  (which covers the story, the StoryBible, the scene, its events, speech and the definitions of
  its characters and environment), or the looks and states were resolved again or are out of
  date.
- A shot that a cut repair (PHASE-023) is working on cannot be defined until the repair ends.
  `cut_context` gives that repair the newest specification of each shot of the cut, and
  `_shot_fields` is the one place that works out what the model is shown about a shot.
- `save_shot_definition` is called by the job and flushes without committing; the job commits it
  together with finishing itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, ShotDefinition, ShotPlan, StoryBible
from app.jobs import store
from app.services import (
    look_state_resolution,
    scene_definition_writer,
    scene_definitions,
    scene_timeline,
    shot_plans,
    speech_units,
    story_bible,
)

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "define_shot"
# Two presses on one shot make one job; two shots run side by side. The key is `scene/shot`.
DEDUPE_KEY: Final = "shot_key"
# The job that repairs a cut between two shots (PHASE-023, `jobs/repair_shot_cut.py`). While one
# runs, the shots it works on cannot be defined.
REPAIR_JOB_TYPE: Final = "repair_shot_cut"
REPAIRING_REASON: Final = "This shot is being repaired for continuity."

# How many of a project's newest definition jobs are read to find each shot's newest one.
_JOB_LOOKBACK: Final = 2000

STORY_BIBLE_KIND: Final = "story_bible"
SCENE_DEFINITION_KIND: Final = "scene_definition"
SHOT_PLAN_KIND: Final = "shot_plan"
RESOLUTION_KIND: Final = "look_state_resolution"
CHARACTER_DEFINITION_KIND: Final = scene_definitions.CHARACTER_DEFINITION_KIND
ENVIRONMENT_DEFINITION_KIND: Final = scene_definitions.ENVIRONMENT_DEFINITION_KIND

# `not_defined`: no specification was made for this shot. `defined`: made, and nothing it was
# built from has changed. `out_of_date`: made, and something it was built from has changed (see
# the reasons).
Status = Literal["not_defined", "defined", "out_of_date"]

_TOLERANCE: Final = 1e-6


class ShotDefinitionsError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class ShotEntry:
    """One shot of a scene's newest shot plan and where its definition stands."""

    # The shot's skeleton as the plan stores it.
    shot: dict[str, Any]
    # Where it falls in the scene, from the timeline; None when the timeline cannot be read.
    start_s: float | None
    duration_s: float
    status: Status
    # Why a defined shot is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The newest specification of this shot, when it has one.
    row: ShotDefinition | None
    # The newest definition job of this shot, whatever its status.
    job: Job | None
    # Whether the Define button may be pressed, and the reason when it may not.
    can_run: bool
    blocked_reason: str | None

    @property
    def content(self) -> dict[str, Any] | None:
        return self.row.content if self.row is not None else None


@dataclass(frozen=True)
class SceneEntry:
    """One scene of the newest list of scenes and where its shots' definitions stand."""

    item: dict[str, Any]
    # The newest shot plan of the scene, when it has one.
    plan: ShotPlan | None
    plan_status: shot_plans.Status
    shots: list[ShotEntry]
    # Why this scene's shots cannot be defined, or None. The same for each of its shots, apart
    # from a shot that is already being defined.
    blocked_reason: str | None
    # Whether any shot of the scene may be defined now.
    can_run: bool


@dataclass(frozen=True)
class ShotDefinitionsState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    entries: list[SceneEntry]
    # Why nothing can be defined yet, or None.
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    """A shot (or, with no `shot_id`, a whole scene) that a "Define" press did not start."""

    scene_id: str
    shot_id: str | None
    title: str
    reason: str


@dataclass(frozen=True)
class StartResult:
    job_ids: list[int]
    skipped: list[Skipped]


@dataclass(frozen=True)
class _Loaded:
    """Everything a run or a read of the state needs, loaded once."""

    story: str | None
    bible: StoryBible | None
    plans: shot_plans.ShotPlansState
    plan_by_scene: dict[str, shot_plans.SceneEntry]
    resolution: look_state_resolution.ResolutionState
    resolution_by_scene: dict[str, look_state_resolution.SceneResolution]
    definitions: dict[str, scene_definitions.SceneEntry]
    current: dict[tuple[str, str], scene_definitions.CurrentDefinition]
    speech: dict[str, speech_units.SceneEntry]
    blocked_reason: str | None


# --- Loading ------------------------------------------------------------------------------


def _blocked_reason(
    story: str | None, bible: StoryBible | None, plans_reason: str | None
) -> str | None:
    if story is None or not story.strip():
        return "Save the story first: shots are defined from the story's shot plans."
    if bible is None:
        return "Run the Story Bible first: shots are defined with its help."
    return plans_reason


async def _load(session: AsyncSession, project: Project) -> _Loaded:
    plans = await shot_plans.state(session, project)
    resolution = await look_state_resolution.state(session, project)
    definitions = await scene_definitions.state(session, project)
    speech = await speech_units.state(session, project)
    bible = await story_bible.latest(session, project.id)
    return _Loaded(
        story=project.script_text,
        bible=bible,
        plans=plans,
        plan_by_scene={entry.item["id"]: entry for entry in plans.entries},
        resolution=resolution,
        resolution_by_scene={scene.scene_id: scene for scene in resolution.scenes},
        definitions={entry.item["id"]: entry for entry in definitions.entries},
        current=await scene_definitions.current_definitions(session, project),
        speech={entry.item["id"]: entry for entry in speech.entries},
        blocked_reason=_blocked_reason(project.script_text, bible, plans.blocked_reason),
    )


def _chosen(definition: dict[str, Any]) -> list[tuple[str, str]]:
    """What a scene definition chose, as `(kind, discovery id)`: its environment, then its
    characters.
    """
    return [
        (ENVIRONMENT_DEFINITION_KIND, definition["environment_id"]),
        *((CHARACTER_DEFINITION_KIND, character) for character in definition["characters"]),
    ]


def _scene_refusal(loaded: _Loaded, scene_id: str) -> str | None:
    """Why this scene's shots cannot be defined now, or None."""
    if loaded.blocked_reason is not None:
        return loaded.blocked_reason
    plan = loaded.plan_by_scene.get(scene_id)
    if plan is None or plan.row is None:
        return "Plan this scene's shots first: they are defined from the shot plan."
    if not plan.generation_ready:
        return (
            plan.generation_blocked_reason
            or "The shots of this scene are not ready for generation."
        ) + " Plan the shots again first."
    if loaded.resolution.version is None:
        return (
            "Resolve the looks and states first: each shot is defined with the look of "
            "each character."
        )
    if loaded.resolution.reasons:
        return "The resolved looks and states are out of date. Resolve them again first."
    resolved = loaded.resolution_by_scene.get(scene_id)
    if resolved is None or not resolved.resolved:
        return "The looks and states of this scene were not resolved. Resolve them again first."
    if not resolved.current:
        return (
            "The looks and states of this scene were resolved from an older definition. "
            "Resolve them again first."
        )
    definition = loaded.definitions.get(scene_id)
    if definition is None or definition.row is None:
        return "Define this scene first: its shots are defined from its definition."
    for kind, discovery_id in _chosen(definition.row.content):
        if (kind, discovery_id) not in loaded.current:
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


def _for_model(
    current: scene_definitions.CurrentDefinition, resolved: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": current.discovery_id,
        "name": current.name,
        "description": current.description,
        "definition": current.definition,
        **resolved,
    }


def _resolved_item(item: look_state_resolution.ResolvedItem | None, key: str) -> dict[str, Any]:
    """What a look or a state resolved to, as the model reads it. `how` is `default` (as the
    definition describes it), `reuse` or `new`; the name and description are None for `default`.
    """
    if item is None:
        return {key: {"request": None, "how": "default", "name": None, "description": None}}
    return {
        key: {
            "request": item.request,
            "how": item.how,
            "name": item.name,
            "description": item.description,
        }
    }


def _skeleton(shot: dict[str, Any], duration: float) -> dict[str, Any]:
    """A shot's skeleton as the model reads it: the plan's fields, with the length from the
    timeline in place of the planner's target.
    """
    return {
        "id": shot["id"],
        "type": shot["type"],
        "description": shot["description"],
        "source_event_ids": shot["source_event_ids"],
        "speech_unit_ids": shot["speech_unit_ids"],
        "duration_seconds": duration,
    }


def _durations(timeline: scene_timeline.SceneTimeline) -> dict[str, tuple[float, float]]:
    """`(start, duration)` of each shot of a timeline, by shot id."""
    return {
        span.shot_id: (span.start_s, round(span.end_s - span.start_s, 3)) for span in timeline.shots
    }


def _speech_in_shot(
    shot: dict[str, Any],
    start_s: float,
    duration: float,
    timeline: scene_timeline.SceneTimeline,
    units: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """`(speech, dialogue)` for one shot: each speech unit it carries with where it plays
    inside the shot, and the shot's lines of dialogue as `{unit_id, speaker_id, text}`.
    """
    spans = {span.unit_id: span for span in timeline.units}
    speech: list[dict[str, Any]] = []
    dialogue: list[dict[str, str]] = []
    for unit_id in shot["speech_unit_ids"]:
        unit = units[unit_id]
        span = spans[unit_id]
        speech.append(
            {
                "id": unit_id,
                "kind": unit["kind"],
                "speaker_id": unit["speaker_id"],
                "text": unit["text"],
                "measured_seconds": round(span.end_s - span.start_s, 3),
                "starts_in_shot_seconds": round(max(0.0, span.start_s - start_s), 3),
                "ends_in_shot_seconds": round(min(duration, span.end_s - start_s), 3),
                "continues_from_previous_shot": span.start_s < start_s - _TOLERANCE,
                "continues_into_next_shot": span.end_s > start_s + duration + _TOLERANCE,
            }
        )
        if unit["kind"] == "dialogue":
            dialogue.append(
                {"unit_id": unit_id, "speaker_id": unit["speaker_id"], "text": unit["text"]}
            )
    return speech, dialogue


def _unit_map(speech: speech_units.SceneEntry | None) -> dict[str, dict[str, Any]]:
    content = speech.content if speech is not None else None
    return {unit["id"]: unit for unit in content["units"]} if content is not None else {}


def _shot_fields(loaded: _Loaded, project_id: int, scene_id: str, shot_id: str) -> dict[str, Any]:
    """Everything the model is shown about one shot, as the fields of a job's input (without
    the dedupe key): the scene and its definition, the shot with its neighbours, its events and
    speech, the characters and the environment, and the `inputs` that are written onto the
    version the job makes (D-3). The scene must not be refused. Used by the job that defines the
    shot and by the repair of a cut (PHASE-023). Raises ShotDefinitionsError for an unknown shot.
    """
    bible = loaded.bible
    assert bible is not None and loaded.story is not None  # not blocked
    plan_entry = loaded.plan_by_scene[scene_id]
    plan_row = plan_entry.row
    timeline = plan_entry.timeline
    resolution_row = loaded.resolution.version
    assert plan_row is not None and timeline is not None and resolution_row is not None
    definition_row = loaded.definitions[scene_id].row
    assert definition_row is not None  # the refusal made sure
    resolved = loaded.resolution_by_scene[scene_id]

    shots: list[dict[str, Any]] = plan_row.content["shots"]
    position = next((i for i, shot in enumerate(shots) if shot["id"] == shot_id), None)
    if position is None:
        raise ShotDefinitionsError(
            f"There is no shot '{shot_id}' in the newest shot plan of the scene '{scene_id}'."
        )
    placed = _durations(timeline)
    shot = shots[position]
    start_s, duration = placed[shot_id]

    def neighbour(index: int) -> dict[str, Any] | None:
        if index < 0 or index >= len(shots):
            return None
        return _skeleton(shots[index], placed[shots[index]["id"]][1])

    item = plan_entry.item
    definition = definition_row.content
    events_row = loaded.speech[scene_id].events.row
    assert events_row is not None  # a ready plan has events
    shown_event_ids = set(shot["source_event_ids"])
    shot_events = [
        event for event in events_row.content["events"] if event["id"] in shown_event_ids
    ]
    speech, dialogue = _speech_in_shot(
        shot, start_s, duration, timeline, _unit_map(loaded.speech.get(scene_id))
    )

    chosen_characters = [
        (CHARACTER_DEFINITION_KIND, character_id) for character_id in definition["characters"]
    ]
    environment_key = (ENVIRONMENT_DEFINITION_KIND, definition["environment_id"])
    looks = {look.subject_id: look for look in resolved.looks}
    characters = [
        _for_model(loaded.current[key], _resolved_item(looks.get(key[1]), "look"))
        for key in chosen_characters
    ]
    environment = _for_model(
        loaded.current[environment_key], _resolved_item(resolved.environment, "state")
    )
    chosen = [environment_key, *chosen_characters]

    shot_for_model = {
        **_skeleton(shot, duration),
        "position": position + 1,
        "shot_count": len(shots),
        "starts_at_seconds_in_scene": start_s,
    }
    inputs = {
        "project_id": project_id,
        "scene_id": scene_id,
        "shot_id": shot_id,
        "story_sha256": story_bible.story_sha256(loaded.story),
        "artifacts": [
            {"kind": STORY_BIBLE_KIND, "id": bible.id, "version": bible.version},
            {
                "kind": SCENE_DEFINITION_KIND,
                "id": definition_row.id,
                "version": definition_row.version,
            },
            {"kind": SHOT_PLAN_KIND, "id": plan_row.id, "version": plan_row.version},
            {
                "kind": RESOLUTION_KIND,
                "id": resolution_row.id,
                "version": resolution_row.version,
            },
            *(
                _shown(kind, discovery_id, loaded.current[(kind, discovery_id)])
                for kind, discovery_id in chosen
            ),
        ],
        "shot": {"id": shot_id, "duration_seconds": duration},
    }
    return {
        "story_bible_id": bible.id,
        "story_bible_version": bible.version,
        "scene_id": scene_id,
        "shot_id": shot_id,
        "shot_plan_id": plan_row.id,
        "scene": {
            "index": item["index"],
            "id": item["id"],
            "title": item["title"],
            "description": item["description"],
        },
        "scene_definition": definition,
        "scene_character_ids": definition["characters"],
        "shot": shot_for_model,
        "previous_shot": neighbour(position - 1),
        "next_shot": neighbour(position + 1),
        "events": shot_events,
        "speech": speech,
        "dialogue": dialogue,
        "duration": duration,
        "characters": characters,
        "environment": environment,
        # Written onto the version the job makes (D-3).
        "inputs": inputs,
    }


def _shot_key(scene_id: str, shot_id: str) -> str:
    return f"{scene_id}/{shot_id}"


async def _repair_locked(session: AsyncSession, project_id: int) -> set[str]:
    """The `scene/shot` keys of the shots that a cut repair (PHASE-023) is working on now. Such
    a shot cannot be defined: the repair would save over it, or be thrown away.
    """
    statement = (
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.type == REPAIR_JOB_TYPE,
            Job.status.in_(store.ACTIVE_STATUSES),
        )
        .execution_options(populate_existing=True)
    )
    locked: set[str] = set()
    for job in (await session.execute(statement)).scalars():
        if not isinstance(job.input, dict):
            continue
        scene_id = job.input.get("scene_id")
        shot_ids = job.input.get("locked_shot_ids")
        if isinstance(scene_id, str) and isinstance(shot_ids, list):
            locked.update(_shot_key(scene_id, item) for item in shot_ids if isinstance(item, str))
    return locked


async def _queue(
    session: AsyncSession,
    project: Project,
    loaded: _Loaded,
    scene_id: str,
    shot_id: str,
) -> tuple[Job, bool]:
    """Queues the job for this shot and returns `(job, created)`. `created` is False when the
    shot already has a job waiting or running, which is returned instead. Raises
    ShotDefinitionsError when this shot cannot be defined, among other reasons because a cut
    repair is working on it.
    """
    refusal = _scene_refusal(loaded, scene_id)
    if refusal is not None:
        raise ShotDefinitionsError(refusal)
    if _shot_key(scene_id, shot_id) in await _repair_locked(session, project.id):
        raise ShotDefinitionsError(REPAIRING_REASON)
    return await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            DEDUPE_KEY: _shot_key(scene_id, shot_id),
            **_shot_fields(loaded, project.id, scene_id, shot_id),
        },
        dedupe_key=DEDUPE_KEY,
    )


@dataclass(frozen=True)
class CutShot:
    """One shot a cut repair reads: what the model is shown, and what the version it makes
    records.
    """

    shot_id: str
    # The fields of `_shot_fields` for this shot.
    fields: dict[str, Any]
    # The newest specification of the shot when the repair was prepared, and its row.
    row: ShotDefinition


@dataclass(frozen=True)
class CutContext:
    """What a repair of one cut reads (PHASE-023): the shots on its two sides, each with its
    newest specification, in order.
    """

    shots: list[CutShot]


async def cut_context(
    session: AsyncSession, project: Project, scene_id: str, shot_ids: list[str]
) -> CutContext:
    """What the repair of a cut between these shots of one scene reads. Every shot must be
    defined and current and none may be locked by another repair. Raises ShotDefinitionsError.
    """
    loaded = await _load(session, project)
    _find_scene(loaded, scene_id)
    refusal = _scene_refusal(loaded, scene_id)
    if refusal is not None:
        raise ShotDefinitionsError(refusal)
    locked = await _repair_locked(session, project.id)
    rows = await _newest_rows(session, project.id)
    shots: list[CutShot] = []
    for shot_id in shot_ids:
        key = _shot_key(scene_id, shot_id)
        if key in locked:
            raise ShotDefinitionsError(REPAIRING_REASON)
        row = rows.get(key)
        if row is None:
            raise ShotDefinitionsError(f"The shot '{shot_id}' is not defined. Define it first.")
        shots.append(
            CutShot(
                shot_id=shot_id,
                fields=_shot_fields(loaded, project.id, scene_id, shot_id),
                row=row,
            )
        )
    return CutContext(shots=shots)


async def newest_row(
    session: AsyncSession, project_id: int, scene_id: str, shot_id: str
) -> ShotDefinition | None:
    """The newest specification of one shot, read now."""
    statement = (
        select(ShotDefinition)
        .where(
            ShotDefinition.project_id == project_id,
            ShotDefinition.scene_id == scene_id,
            ShotDefinition.shot_id == shot_id,
        )
        .order_by(ShotDefinition.version.desc(), ShotDefinition.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def start_shot(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    shot_id: str,
) -> Job:
    """Queues the job that defines one shot, and commits. If that shot already has a job
    waiting or running, that job is returned and no new one is made. Raises
    ShotDefinitionsError.
    """
    loaded = await _load(session, project)
    _find_scene(loaded, scene_id)
    job, _created = await _queue(session, project, loaded, scene_id, shot_id)
    return job


def _find_scene(loaded: _Loaded, scene_id: str) -> shot_plans.SceneEntry:
    entry = loaded.plan_by_scene.get(scene_id)
    if entry is None:
        raise ShotDefinitionsError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    return entry


async def _start_scene_shots(
    session: AsyncSession,
    project: Project,
    loaded: _Loaded,
    state_entry: SceneEntry,
    result: StartResult,
) -> None:
    """Queues a job for every shot of the scene that is not defined and current, and not being
    defined, adding to `result`. The scene must not be refused.
    """
    title = state_entry.item["title"]
    scene_id = state_entry.item["id"]
    for shot in state_entry.shots:
        shot_id = shot.shot["id"]
        if shot.status == "defined":
            result.skipped.append(
                Skipped(scene_id, shot_id, title, "Already defined and up to date.")
            )
            continue
        try:
            job, created = await _queue(session, project, loaded, scene_id, shot_id)
        except ShotDefinitionsError as exc:
            # A shot a cut repair is working on: the others are still defined.
            result.skipped.append(Skipped(scene_id, shot_id, title, str(exc)))
            continue
        if created:
            result.job_ids.append(job.id)
        else:
            result.skipped.append(Skipped(scene_id, shot_id, title, "Already being defined."))


async def start_scene(session: AsyncSession, project: Project, scene_id: str) -> StartResult:
    """Queues a job for every shot of one scene that is not defined and current already and is
    not being defined. Raises ShotDefinitionsError when the scene's shots cannot be defined.
    """
    loaded = await _load(session, project)
    _find_scene(loaded, scene_id)
    refusal = _scene_refusal(loaded, scene_id)
    if refusal is not None:
        raise ShotDefinitionsError(refusal)
    state = await _build(session, project, loaded)
    entry = next(entry for entry in state.entries if entry.item["id"] == scene_id)
    result = StartResult(job_ids=[], skipped=[])
    await _start_scene_shots(session, project, loaded, entry, result)
    return result


async def start_all(session: AsyncSession, project: Project) -> StartResult:
    """Queues a job for every shot, in every scene that can be defined, that is not defined and
    current already and is not being defined. A scene that cannot be defined is skipped with
    the reason. Raises ShotDefinitionsError when nothing can be defined yet.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise ShotDefinitionsError(loaded.blocked_reason)
    state = await _build(session, project, loaded)
    result = StartResult(job_ids=[], skipped=[])
    for entry in state.entries:
        scene_id = entry.item["id"]
        refusal = _scene_refusal(loaded, scene_id)
        if refusal is not None:
            result.skipped.append(Skipped(scene_id, None, entry.item["title"], refusal))
            continue
        await _start_scene_shots(session, project, loaded, entry, result)
    return result


# --- Reading the state --------------------------------------------------------------------


def _recorded(inputs: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """The first artifact of this kind that `inputs` says the specification was built from."""
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            return artifact
    return None


def _out_of_date_reasons(
    row: ShotDefinition,
    loaded: _Loaded,
    plan: shot_plans.SceneEntry,
    resolved: look_state_resolution.SceneResolution | None,
) -> list[str]:
    """Why a specification made for this shot is no longer current, one sentence each."""
    inputs = row.inputs
    reasons: list[str] = []
    if plan.row is None:
        reasons.append("The scene has no shot plan now.")
    else:
        if plan.status == "out_of_date":
            reasons.append("The shot plan of the scene is out of date.")
        recorded_plan = _recorded(inputs, SHOT_PLAN_KIND)
        if recorded_plan is None or recorded_plan.get("id") != plan.row.id:
            reasons.append("The shots of the scene were planned again since this shot was defined.")

    newest = loaded.resolution.version
    recorded_resolution = _recorded(inputs, RESOLUTION_KIND)
    if newest is None:
        reasons.append("The looks and states are no longer resolved.")
    else:
        if recorded_resolution is None or recorded_resolution.get("id") != newest.id:
            reasons.append("The looks and states were resolved again since this shot was defined.")
        elif loaded.resolution.reasons:
            reasons.append("The resolved looks and states are out of date.")
        elif resolved is None or not resolved.current:
            reasons.append(
                "The looks and states of the scene were resolved from an older definition."
            )
    return reasons


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest definition job of each shot of the project, by its `scene/shot` key."""
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


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, ShotDefinition]:
    """The newest specification of each shot of the project, by its `scene/shot` key."""
    statement = (
        select(ShotDefinition)
        .where(ShotDefinition.project_id == project_id)
        .order_by(ShotDefinition.version.desc(), ShotDefinition.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, ShotDefinition] = {}
    for row in (await session.execute(statement)).scalars():
        key = _shot_key(row.scene_id, row.shot_id)
        if key not in newest:
            newest[key] = row
    return newest


async def _build(session: AsyncSession, project: Project, loaded: _Loaded) -> ShotDefinitionsState:
    jobs = await _newest_jobs(session, project.id)
    rows = await _newest_rows(session, project.id)
    locked = await _repair_locked(session, project.id)

    entries: list[SceneEntry] = []
    for plan in loaded.plans.entries:
        scene_id = plan.item["id"]
        refusal = _scene_refusal(loaded, scene_id)
        resolved = loaded.resolution_by_scene.get(scene_id)
        placed = _durations(plan.timeline) if plan.timeline is not None else {}
        shots: list[ShotEntry] = []
        for shot in plan.content["shots"] if plan.content is not None else []:
            key = _shot_key(scene_id, shot["id"])
            row = rows.get(key)
            job = jobs.get(key)
            active = job is not None and job.status in store.ACTIVE_STATUSES
            status: Status = "not_defined"
            reasons: list[str] = []
            if row is not None and isinstance(row.inputs, dict):
                reasons = _out_of_date_reasons(row, loaded, plan, resolved)
                status = "out_of_date" if reasons else "defined"
            blocked = refusal
            if blocked is None and active:
                blocked = "This shot is already being defined."
            if blocked is None and key in locked:
                blocked = REPAIRING_REASON
            start_s, duration = placed.get(shot["id"], (None, shot["target_duration"]))
            shots.append(
                ShotEntry(
                    shot=shot,
                    start_s=start_s,
                    duration_s=duration,
                    status=status,
                    reasons=reasons,
                    row=row,
                    job=job,
                    can_run=blocked is None,
                    blocked_reason=blocked,
                )
            )
        entries.append(
            SceneEntry(
                item=plan.item,
                plan=plan.row,
                plan_status=plan.status,
                shots=shots,
                blocked_reason=refusal,
                can_run=refusal is None and any(shot.can_run for shot in shots),
            )
        )
    return ShotDefinitionsState(
        scenes_version=loaded.plans.scenes_version,
        entries=entries,
        blocked_reason=loaded.blocked_reason,
    )


async def state(session: AsyncSession, project: Project) -> ShotDefinitionsState:
    """The newest list of scenes with where each shot's definition stands. Worked out on every
    read; nothing here is stored.
    """
    return await _build(session, project, await _load(session, project))


# --- Saving the specification -------------------------------------------------------------


async def save_shot_definition(
    session: AsyncSession,
    *,
    project_id: int,
    scene_id: str,
    shot_id: str,
    shot_plan_id: int,
    content: dict[str, Any],
    job_id: int,
    inputs: dict[str, Any],
) -> ShotDefinition:
    """Adds the shot's next version. Flushes but does not commit: the job commits it together
    with finishing itself, so a job is never "succeeded" without its result.

    `inputs` is what the job was started with and is stored as it is.
    """
    statement = select(func.max(ShotDefinition.version)).where(
        ShotDefinition.project_id == project_id,
        ShotDefinition.scene_id == scene_id,
        ShotDefinition.shot_id == shot_id,
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = ShotDefinition(
        project_id=project_id,
        scene_id=scene_id,
        shot_id=shot_id,
        shot_plan_id=shot_plan_id,
        version=(highest or 0) + 1,
        source="ai",
        job_id=job_id,
        inputs=inputs,
        content=content,
    )
    session.add(row)
    await session.flush()
    _logger.info(
        "job %d: definition of shot '%s' of scene '%s' of project %d saved, version %d",
        job_id,
        shot_id,
        scene_id,
        project_id,
        row.version,
    )
    return row
