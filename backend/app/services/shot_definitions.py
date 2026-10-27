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

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, ShotDefinition, ShotPlan, StoryBible
from app.jobs import store
from app.services import (
    environment_views,
    look_state_resolution,
    provenance,
    scene_definition_writer,
    scene_definitions,
    scene_staging,
    scene_timeline,
    shot_definition_writer,
    shot_plans,
    shot_staging,
    speech_units,
    story_bible,
    user_feedback,
)
from app.services.project_kinds import KIND_EXPLAINER

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "define_shot"
# Two presses on one shot make one job; two shots run side by side. The key is `scene/shot`.
DEDUPE_KEY: Final = "shot_key"
# The job that repairs a cut between two shots (PHASE-023, `jobs/repair_shot_cut.py`). While one
# runs, the shots it works on cannot be defined.
REPAIR_JOB_TYPE: Final = "repair_shot_cut"
REPAIRING_REASON: Final = "This shot is being repaired for continuity."

# Who wrote a specification: the model (a job), or the user's edit (PHASE-038).
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"
MANUAL_REPLACE_MESSAGE: Final = (
    "The newest definition of this shot was written by you. Defining it again adds a new "
    "version from the model, so it has to be confirmed."
)
SKIPPED_MANUAL: Final = "Written by you: use this shot's own button to replace it."

# How many of a project's newest definition jobs are read to find each shot's newest one.
_JOB_LOOKBACK: Final = 2000

STORY_BIBLE_KIND: Final = "story_bible"
SCENE_DEFINITION_KIND: Final = "scene_definition"
SHOT_PLAN_KIND: Final = "shot_plan"
RESOLUTION_KIND: Final = "look_state_resolution"
STAGING_KIND: Final = "scene_staging"
VIEW_PLAN_KIND: Final = "environment_view_plan"
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
    # Where the characters stand in this shot and the views that may stand behind it
    # (`shot_staging.for_shot`), or None when the scene is not staged yet (PHASE-054).
    staging: dict[str, Any] | None = None

    @property
    def content(self) -> dict[str, Any] | None:
        return self.row.content if self.row is not None else None

    @property
    def needs_confirmation(self) -> bool:
        """The newest specification was written by the user: the model replaces it only when
        asked (PHASE-038).
        """
        return self.row is not None and self.row.source == SOURCE_MANUAL


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
    # The staging of each scene and the view plan of each environment (PHASE-054), by id.
    staging: dict[str, scene_staging.SceneEntry]
    views: dict[str, environment_views.EnvironmentEntry]
    blocked_reason: str | None
    # An explainer project (EXPLAINER-004): its shots are the presenter's or B-roll.
    explainer: bool = False


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
    staging = await scene_staging.state(session, project)
    views = await environment_views.state(session, project)
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
        staging={entry.item["id"]: entry for entry in staging.entries},
        views={entry.discovery_id: entry for entry in views.entries},
        blocked_reason=_blocked_reason(project.script_text, bible, plans.blocked_reason),
        explainer=project.kind == KIND_EXPLAINER,
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
    return _staging_refusal(loaded, scene_id, definition.row.content["environment_id"])


def _staging_refusal(loaded: _Loaded, scene_id: str, environment_id: str) -> str | None:
    """Why the scene's shots cannot be defined for want of the views of its place (PHASE-054),
    or None. A scene that was never staged is defined as before, with no view. A staged scene's
    shots are defined from where everyone stands and from the views that may stand behind
    them, so the staging must be current and the views of its place planned and drawn.
    """
    staged = loaded.staging.get(scene_id)
    if staged is None or staged.row is None:
        return None
    if staged.status == "out_of_date":
        return "The staging of this scene is out of date. Stage it again first."
    entry = loaded.views.get(environment_id)
    if entry is None or entry.plan is None:
        return "Plan the views of this scene's place first: each shot is shown in front of a view."
    if entry.status == "out_of_date":
        return "The views planned for this scene's place are out of date. Plan them again first."
    if not any(item["scene_id"] == scene_id for item in entry.plan.content["scenes"]):
        return "The planned views of this scene's place do not cover this scene. Plan them again."
    if entry.pictures_status != "ready":
        return "Make the pictures of the views of this scene's place first."
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
    skeleton: dict[str, Any] = {
        "id": shot["id"],
        "type": shot["type"],
        "description": shot["description"],
        "source_event_ids": shot["source_event_ids"],
        "speech_unit_ids": shot["speech_unit_ids"],
        "duration_seconds": duration,
        "continues_previous": shot.get("continues_previous") is True,
    }
    if shot.get("rapid_exchange") is True:
        # PHASE-043. Written only when true, so the skeleton (and its hash, which says whether
        # a definition is out of date) of every other shot is exactly what it was before.
        skeleton["rapid_exchange"] = True
    return skeleton


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


def _skeleton_sha256(shot: dict[str, Any], duration: float, speech: list[dict[str, Any]]) -> str:
    """A hash of what the plan says about one shot: its skeleton and the speech it carries with
    the measured places of each line. It changes when this shot changes and not when another
    shot of the scene does (PHASE-039).
    """
    payload = {"shot": _skeleton(shot, duration), "speech": speech}
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def current_skeleton_sha256(
    plan: shot_plans.SceneEntry,
    shot: dict[str, Any],
    units: dict[str, dict[str, Any]],
) -> str | None:
    """`_skeleton_sha256` of a shot of the scene's newest plan as it stands now, or None when
    the plan's timeline cannot be read.
    """
    if plan.timeline is None:
        return None
    placed = _durations(plan.timeline)
    if shot["id"] not in placed:
        return None
    start_s, duration = placed[shot["id"]]
    try:
        speech, _dialogue = _speech_in_shot(shot, start_s, duration, plan.timeline, units)
    except KeyError:
        return None
    return _skeleton_sha256(shot, duration, speech)


def _resolved_record(resolved: look_state_resolution.SceneResolution) -> dict[str, Any]:
    """What the scene's looks and state resolved to, by subject: the slug of the named look or
    state, or None for the default. Written onto `inputs` by `_shot_fields`; `save_shot_definition`
    narrows it to what the shot uses.
    """
    return {
        "looks": {look.subject_id: look.id for look in resolved.looks},
        "environment": {
            "id": resolved.environment.subject_id if resolved.environment is not None else None,
            "state": resolved.environment.id if resolved.environment is not None else None,
        },
    }


def _used_character_ids(content: dict[str, Any], scene_character_ids: list[str]) -> list[str]:
    """The characters of the scene a shot uses: the ones visible in it and the ones who speak
    a line of its dialogue, in the order of the scene's characters.
    """
    used = {
        character["id"]
        for character in content.get("characters") or []
        if isinstance(character, dict) and isinstance(character.get("id"), str)
    }
    audio = content.get("audio_intent")
    for line in (audio.get("dialogue") if isinstance(audio, dict) else None) or []:
        if isinstance(line, dict) and isinstance(line.get("speaker_id"), str):
            used.add(line["speaker_id"])
    return [character_id for character_id in scene_character_ids if character_id in used]


def _narrowed_inputs(inputs: dict[str, Any], content: dict[str, Any]) -> dict[str, Any]:
    """The `inputs` a saved specification records (PHASE-039): the characters it uses, each with
    the look the scene resolved to for it, and the environment with its state; the definitions
    of the characters it does not use are left out of the artifacts. `resolved` (everything the
    scene resolved) is replaced by `uses`.
    """
    stored = {key: value for key, value in inputs.items() if key != "resolved"}
    resolved = inputs.get("resolved")
    if not isinstance(resolved, dict):
        return stored
    scene_ids = [
        artifact["discovery_id"]
        for artifact in inputs.get("artifacts") or []
        if isinstance(artifact, dict)
        and artifact.get("kind") == CHARACTER_DEFINITION_KIND
        and isinstance(artifact.get("discovery_id"), str)
    ]
    used = _used_character_ids(content, scene_ids)
    looks = resolved.get("looks") if isinstance(resolved.get("looks"), dict) else {}
    stored["uses"] = {
        "characters": used,
        "looks": {character_id: looks.get(character_id) for character_id in used},
        "environment": resolved.get("environment"),
    }
    stored["artifacts"] = [
        artifact
        for artifact in inputs.get("artifacts") or []
        if not (
            isinstance(artifact, dict)
            and artifact.get("kind") == CHARACTER_DEFINITION_KIND
            and artifact.get("discovery_id") not in used
        )
    ]
    return stored


_VIEW_FIELDS: Final = ("id", "name", "side", "framing", "zone", "description")


def _shot_staging(loaded: _Loaded, scene_id: str, shot: dict[str, Any]) -> dict[str, Any] | None:
    """What this shot is staged and framed from (`shot_staging.for_shot`), or None when the
    scene is not staged or its place has no planned views yet. Pure; the scene is not refused.
    """
    staged = loaded.staging.get(scene_id)
    definition = loaded.definitions.get(scene_id)
    speech = loaded.speech.get(scene_id)
    if (
        staged is None
        or staged.content is None
        or definition is None
        or definition.row is None
        or speech is None
        or speech.events.row is None
    ):
        return None
    environment_id = definition.row.content["environment_id"]
    entry = loaded.views.get(environment_id)
    if entry is None or entry.plan is None:
        return None
    coverage = next(
        (item for item in entry.plan.content["scenes"] if item["scene_id"] == scene_id), None
    )
    if coverage is None:
        return None
    current = loaded.current.get((ENVIRONMENT_DEFINITION_KIND, environment_id))
    plan = current.definition.get("spatial_plan") if current is not None else None
    master = plan.get("master_view") if isinstance(plan, dict) else None
    views = [shot_staging.establishing_view(master if isinstance(master, str) else None)]
    views += [
        {key: view[key] for key in _VIEW_FIELDS}
        for view in entry.plan.content["views"]
        if view["id"] != shot_staging.ESTABLISHING
    ]
    return shot_staging.for_shot(
        staging=staged.content,
        scene_event_ids=[event["id"] for event in speech.events.row.content["events"]],
        shot_event_ids=shot["source_event_ids"],
        views=views,
        coverage=coverage,
    )


def _staging_sha256(staging: dict[str, Any] | None) -> str | None:
    if staging is None:
        return None
    text = json.dumps(staging, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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

    # None for a scene that was never staged: its shots are defined as before.
    staging = _shot_staging(loaded, scene_id, shot)
    staged = loaded.staging[scene_id].row if scene_id in loaded.staging else None
    environment_views_entry = loaded.views.get(definition["environment_id"])
    plan_of_views = environment_views_entry.plan if environment_views_entry is not None else None
    staging_artifacts: list[dict[str, Any]] = []
    if staging is not None:
        assert staged is not None and plan_of_views is not None  # `_shot_staging` found them
        staging_artifacts = [
            {"kind": STAGING_KIND, "id": staged.id, "version": staged.version},
            {
                "kind": VIEW_PLAN_KIND,
                "id": plan_of_views.id,
                "version": plan_of_views.version,
                "discovery_id": definition["environment_id"],
            },
        ]

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
            *staging_artifacts,
            *(
                _shown(kind, discovery_id, loaded.current[(kind, discovery_id)])
                for kind, discovery_id in chosen
            ),
        ],
        "shot": {
            "id": shot_id,
            "duration_seconds": duration,
            "skeleton_sha256": _skeleton_sha256(shot, duration, speech),
        },
        # What the shot was staged from; the shot is out of date when it changes.
        **({"staging": {"sha256": _staging_sha256(staging)}} if staging is not None else {}),
        # Narrowed to what the shot uses by `save_shot_definition` (PHASE-039).
        "resolved": _resolved_record(resolved),
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
        "staging": staging,
        "explainer": loaded.explainer,
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
    feedback: user_feedback.Feedback | None = None,
) -> tuple[Job, bool]:
    """Queues the job for this shot and returns `(job, created)`. `created` is False when the
    shot already has a job waiting or running, which is returned instead. Raises
    ShotDefinitionsError when this shot cannot be defined, among other reasons because a cut
    repair is working on it.

    `feedback` is the user's note on the newest specification (PHASE-038). The job is given the
    note and the specification it is about; the version it saves records the note and the
    version it was about.
    """
    refusal = _scene_refusal(loaded, scene_id)
    if refusal is not None:
        raise ShotDefinitionsError(refusal)
    if _shot_key(scene_id, shot_id) in await _repair_locked(session, project.id):
        raise ShotDefinitionsError(REPAIRING_REASON)
    fields = _shot_fields(loaded, project.id, scene_id, shot_id)
    if feedback is not None:
        fields = {
            **fields,
            "inputs": {**fields["inputs"], "feedback": feedback.for_version()},
            "feedback": feedback.for_job(),
        }
    return await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={DEDUPE_KEY: _shot_key(scene_id, shot_id), **fields},
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


async def shot_contexts(
    session: AsyncSession, project: Project, keys: list[tuple[str, str]]
) -> dict[tuple[str, str], dict[str, Any] | str]:
    """What the model is shown about each of these `(scene id, shot id)` shots, as the fields of
    `_shot_fields` (the scene and its definition, the shot with its neighbours, its events and
    speech, the characters with their resolved looks, the environment with its resolved state
    and the `inputs` of D-3). Loaded once for all of them. A shot that cannot be read now is
    given as the reason (a sentence for the user) instead. Used by the prompt compilation
    (PHASE-026), which writes its prompt from the same material the shot was defined from.
    """
    loaded = await _load(session, project)
    found: dict[tuple[str, str], dict[str, Any] | str] = {}
    for scene_id, shot_id in keys:
        if scene_id not in loaded.plan_by_scene:
            found[(scene_id, shot_id)] = f"There is no scene '{scene_id}' in the newest list."
            continue
        refusal = _scene_refusal(loaded, scene_id)
        if refusal is not None:
            found[(scene_id, shot_id)] = refusal
            continue
        try:
            found[(scene_id, shot_id)] = _shot_fields(loaded, project.id, scene_id, shot_id)
        except ShotDefinitionsError as exc:
            found[(scene_id, shot_id)] = str(exc)
    return found


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
    *,
    confirm_replace_manual: bool = False,
    feedback: str | None = None,
) -> Job:
    """Queues the job that defines one shot, and commits. If that shot already has a job
    waiting or running, that job is returned and no new one is made. When the newest
    specification was written by the user, it is replaced only when `confirm_replace_manual`
    is true (PHASE-038).

    `feedback` is the user's note on the newest specification: the shot is defined again with
    the note and that specification in the request (PHASE-038). A note is never dropped silently,
    so a shot that is being defined already refuses it. Raises ShotDefinitionsError.
    """
    loaded = await _load(session, project)
    _find_scene(loaded, scene_id)
    newest = await newest_row(session, project.id, scene_id, shot_id)
    if newest is not None and newest.source == SOURCE_MANUAL and not confirm_replace_manual:
        raise ShotDefinitionsError(MANUAL_REPLACE_MESSAGE)
    note = _feedback_on(feedback, newest) if feedback is not None else None
    job, created = await _queue(session, project, loaded, scene_id, shot_id, note)
    if note is not None and not created:
        raise ShotDefinitionsError("This shot is already being defined.")
    return job


def _feedback_on(text: str, newest: ShotDefinition | None) -> user_feedback.Feedback:
    """The user's note on the newest specification of a shot, with that specification as what it
    is about. Raises ShotDefinitionsError when the note is not usable or the shot has no
    specification to talk about.
    """
    try:
        note = user_feedback.clean(text)
    except ValueError as exc:
        raise ShotDefinitionsError(str(exc)) from exc
    if newest is None:
        raise ShotDefinitionsError(
            "This shot is not defined yet, so there is nothing to comment on."
        )
    return user_feedback.Feedback(
        text=note,
        previous=shot_definition_writer.previous_specification(newest.content),
        base_version=newest.version,
    )


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
        if shot.needs_confirmation:
            result.skipped.append(Skipped(scene_id, shot_id, title, SKIPPED_MANUAL))
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


def _uses_reasons(
    uses: dict[str, Any], resolved: look_state_resolution.SceneResolution
) -> list[str]:
    """Why the looks and the state a shot used are not what the scene resolves to now. Only the
    characters the shot uses are looked at (PHASE-039).
    """
    reasons: list[str] = []
    now = {look.subject_id: look for look in resolved.looks}
    looks = uses.get("looks") if isinstance(uses.get("looks"), dict) else {}
    for character_id, slug in looks.items():
        item = now.get(character_id)
        if (item.id if item is not None else None) != slug:
            name = item.subject_name if item is not None else character_id
            reasons.append(f"The look of {name} in this scene changed since this shot was defined.")
    environment = uses.get("environment")
    recorded_state = environment.get("state") if isinstance(environment, dict) else None
    now_state = resolved.environment.id if resolved.environment is not None else None
    if now_state != recorded_state:
        reasons.append("The state of the place in this scene changed since this shot was defined.")
    return reasons


def _out_of_date_reasons(
    row: ShotDefinition,
    loaded: _Loaded,
    plan: shot_plans.SceneEntry,
    resolved: look_state_resolution.SceneResolution | None,
    skeleton_sha256: str | None,
    staging_sha256: str | None,
) -> list[str]:
    """Why a specification made for this shot is no longer current, one sentence each.

    A specification that recorded what its shot uses (PHASE-039) is judged by that: its own
    skeleton in the plan, and the looks and state of the characters it uses. Planning the scene
    again, or resolving the looks again, only makes it out of date when that changed it. An
    older specification is judged by the row ids, as before.
    """
    inputs = row.inputs
    reasons: list[str] = []
    shot = inputs.get("shot") if isinstance(inputs.get("shot"), dict) else {}
    recorded_skeleton = shot.get("skeleton_sha256")
    if plan.row is None:
        reasons.append("The scene has no shot plan now.")
    else:
        if plan.status == "out_of_date":
            reasons.append("The shot plan of the scene is out of date.")
        if isinstance(recorded_skeleton, str) and skeleton_sha256 is not None:
            if recorded_skeleton != skeleton_sha256:
                reasons.append("This shot was changed when the scene's shots were planned again.")
        elif not provenance.same_row(_recorded(inputs, SHOT_PLAN_KIND), plan.row):
            reasons.append("The shots of the scene were planned again since this shot was defined.")

    recorded_staging = inputs.get("staging")
    recorded_sha = recorded_staging.get("sha256") if isinstance(recorded_staging, dict) else None
    if isinstance(recorded_sha, str):
        if staging_sha256 is None:
            reasons.append("The scene's staging or the views of its place are no longer there.")
        elif recorded_sha != staging_sha256:
            reasons.append("The staging of this shot or the views of its place changed.")
    elif staging_sha256 is not None:
        reasons.append("This shot was defined before its scene was staged.")

    newest = loaded.resolution.version
    uses = inputs.get("uses")
    if newest is None:
        reasons.append("The looks and states are no longer resolved.")
    elif isinstance(uses, dict):
        if resolved is None or not resolved.resolved:
            reasons.append("The scene is no longer part of the resolved looks and states.")
        else:
            reasons.extend(_uses_reasons(uses, resolved))
    else:
        if not provenance.same_row(_recorded(inputs, RESOLUTION_KIND), newest):
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
        units = _unit_map(loaded.speech.get(scene_id))
        shots: list[ShotEntry] = []
        for shot in plan.content["shots"] if plan.content is not None else []:
            key = _shot_key(scene_id, shot["id"])
            row = rows.get(key)
            job = jobs.get(key)
            active = job is not None and job.status in store.ACTIVE_STATUSES
            staging = _shot_staging(loaded, scene_id, shot)
            status: Status = "not_defined"
            reasons: list[str] = []
            if row is not None and isinstance(row.inputs, dict):
                reasons = _out_of_date_reasons(
                    row,
                    loaded,
                    plan,
                    resolved,
                    current_skeleton_sha256(plan, shot, units),
                    _staging_sha256(staging),
                )
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
                    staging=staging,
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
    job_id: int | None,
    inputs: dict[str, Any],
    source: str = SOURCE_AI,
) -> ShotDefinition:
    """Adds the shot's next version. Flushes but does not commit: the job commits it together
    with finishing itself, so a job is never "succeeded" without its result.

    `inputs` is what the job was started with and is stored as it is. `job_id` is None and
    `source` is `manual` for a specification the user edited (`save_manual`).
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
        source=source,
        job_id=job_id,
        inputs=_narrowed_inputs(inputs, content),
        content=content,
    )
    session.add(row)
    await session.flush()
    _logger.info(
        "job %s: definition of shot '%s' of scene '%s' of project %d saved, version %d (%s)",
        job_id,
        shot_id,
        scene_id,
        project_id,
        row.version,
        source,
    )
    return row


async def accept_as_is(
    session: AsyncSession, project: Project, scene_id: str, shot_id: str
) -> ShotDefinition:
    """Keeps the shot's newest specification as it is and records that it was made from what
    is current now (PHASE-039). Nothing after it is started: what was made from it stays as it
    is. Raises ShotDefinitionsError.
    """
    newest = (await _newest_rows(session, project.id)).get(_shot_key(scene_id, shot_id))
    if newest is None:
        raise ShotDefinitionsError(f"Shot '{shot_id}' has no specification to accept.")
    return await save_manual(session, project, scene_id, shot_id, newest.content, accepting=newest)


async def save_manual(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    shot_id: str,
    answer: dict[str, Any],
    *,
    accepting: ShotDefinition | None = None,
) -> ShotDefinition:
    """Stores the user's edited specification of one shot as its next version (`source` is
    `manual`), and commits (PHASE-038). It needs what a run needs (a current plan, ready for
    generation, the looks and states resolved, everything linked) and is refused while the shot
    is being defined or repaired. The specification is checked the way the model's answer is
    (`shot_definition_writer.check_answer`: the id, the scene, the duration and the dialogue are
    set by code, as for a job), and the version records exactly what a job would. With
    `accepting` (PHASE-039) it also records which version the user accepted as it is. Raises
    ShotDefinitionsError.

    What follows a saved specification (references, generation request, prompt, continuity) is
    the caller's to start: see `services/shot_chain.py`.
    """
    loaded = await _load(session, project)
    _find_scene(loaded, scene_id)
    refusal = _scene_refusal(loaded, scene_id)
    if refusal is not None:
        raise ShotDefinitionsError(refusal)
    key = _shot_key(scene_id, shot_id)
    if key in await _repair_locked(session, project.id):
        raise ShotDefinitionsError(REPAIRING_REASON)
    job = (await _newest_jobs(session, project.id)).get(key)
    if job is not None and job.status in store.ACTIVE_STATUSES:
        raise ShotDefinitionsError("This shot is already being defined.")

    fields = _shot_fields(loaded, project.id, scene_id, shot_id)
    try:
        content = shot_definition_writer.check_answer(
            answer,
            scene_id=scene_id,
            shot_id=shot_id,
            duration=fields["duration"],
            scene_character_ids=fields["scene_character_ids"],
            dialogue=fields["dialogue"],
            exchange=fields["shot"].get("rapid_exchange") is True,
            staging=fields["staging"],
            explainer=fields["explainer"],
        )
    except ValueError as exc:
        raise ShotDefinitionsError(str(exc)) from exc
    row = await save_shot_definition(
        session,
        project_id=project.id,
        scene_id=scene_id,
        shot_id=shot_id,
        shot_plan_id=fields["shot_plan_id"],
        content=content,
        job_id=None,
        inputs=fields["inputs"],
        source=SOURCE_MANUAL,
    )
    if accepting is not None:
        row.inputs = provenance.accepted_inputs(row.inputs, accepting, row.content)
    await session.commit()
    return row
