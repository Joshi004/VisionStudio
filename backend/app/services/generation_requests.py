"""The generation request of a shot (PHASE-025, `Path_ahead.md` Section 29).

The generation request is the exact request the video model is asked for: endpoint, frame count,
size, the ordered pictures and the ordered dialogue audios. Code makes it, with no model and no
job: `services/generation_planner` holds the rule, this module gathers what the rule needs,
stores the result and says where each shot stands.

- **What a request is planned from:** the shot's reference manifest (the pictures), the shot
  definition the manifest was chosen for (which dialogue lines the shot carries and who is
  visible), the scene's timeline (the shot's length and where each line starts inside it), the
  measured audio of each dialogue line, the duration policy and the project's orientation.
- A request is a **project artifact**: one immutable `generation_request` row per planning,
  numbered per shot, with the provenance of the artifact convention (D-3). Nothing is sent to
  the GPU server and no file is uploaded: that is PHASE-027.
- A shot can be planned only when its newest manifest exists and is current, its scene's plan is
  ready for generation (PHASE-021) and the audio of every dialogue line it carries is ready.
- **Out of date is worked out on every read** and never stored: the manifest was chosen again or
  is out of date, a dialogue line's audio was made again or is no longer ready, the shot's length
  changed, the hard duration bounds changed or the project's orientation changed.
- `plan_shot`, `plan_scene` and `plan_all` are the buttons; they commit once. `plan_if_ready` is
  called after a manifest is chosen (the `define_shot` job and the manifest buttons), so a shot
  gets its request by itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GenerationRequest, Project, ShotDefinition
from app.services import (
    duration_policy,
    generation_planner,
    provenance,
    shot_plans,
    shot_references,
    speech_synthesis,
)
from app.services.duration_policy import DurationPolicy

_logger = logging.getLogger(__name__)

MANIFEST_KIND: Final = "shot_reference_manifest"
DEFINITION_KIND: Final = "shot_definition"
PLAN_KIND: Final = "shot_plan"
AUDIO_KIND: Final = "speech_unit_audio"

# `not_planned`: no request was made for this shot. `planned`: made, and nothing it was built
# from has changed. `out_of_date`: made, and something it was built from has changed (see the
# reasons).
Status = Literal["not_planned", "planned", "out_of_date"]


class GenerationRequestsError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class ShotEntry:
    """One shot of the newest shot plan and where its generation request stands."""

    shot: dict[str, Any]
    duration_s: float
    # Where the shot's reference manifest stands: `not_selected`, `selected` or `out_of_date`.
    manifest_status: str
    status: Status
    # Why a planned request is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The newest request of this shot, when it has one.
    row: GenerationRequest | None
    can_run: bool
    blocked_reason: str | None


@dataclass(frozen=True)
class SceneEntry:
    item: dict[str, Any]
    shots: list[ShotEntry]


@dataclass(frozen=True)
class GenerationRequestsState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    entries: list[SceneEntry]
    blocked_reason: str | None


@dataclass(frozen=True)
class Planned:
    scene_id: str
    shot_id: str
    version: int


@dataclass(frozen=True)
class Skipped:
    scene_id: str
    shot_id: str | None
    title: str
    reason: str


@dataclass(frozen=True)
class PlanResult:
    planned: list[Planned]
    skipped: list[Skipped]


@dataclass(frozen=True)
class _Context:
    """Everything a planning or a read of the state needs, loaded once."""

    project: Project
    references: shot_references.ShotReferencesState
    plans: dict[str, shot_plans.SceneEntry]
    # Each dialogue or narration unit's audio, by `(scene id, unit id)`.
    audio: dict[tuple[str, str], speech_synthesis.UnitEntry]
    policy: DurationPolicy | None
    policy_problem: str | None
    # The shot definitions the newest manifests were chosen for, by row id.
    definitions: dict[int, ShotDefinition]


def _key(scene_id: str, shot_id: str) -> str:
    return f"{scene_id}/{shot_id}"


async def _load(session: AsyncSession, project: Project) -> _Context:
    references = await shot_references.state(session, project)
    plans = await shot_plans.state(session, project)
    audio = await speech_synthesis.state(session, project)
    policy: DurationPolicy | None = None
    policy_problem: str | None = None
    try:
        policy = await duration_policy.read_duration_policy(session)
    except duration_policy.DurationPolicyError as exc:
        policy_problem = str(exc)

    definition_ids = {
        shot.row.shot_definition_id
        for scene in references.entries
        for shot in scene.shots
        if shot.row is not None and shot.row.shot_definition_id is not None
    }
    definitions: dict[int, ShotDefinition] = {}
    if definition_ids:
        rows = await session.execute(
            select(ShotDefinition).where(ShotDefinition.id.in_(definition_ids))
        )
        definitions = {row.id: row for row in rows.scalars()}
    return _Context(
        project=project,
        references=references,
        plans={entry.item["id"]: entry for entry in plans.entries},
        audio={
            (scene.scene.item["id"], unit.unit["id"]): unit
            for scene in audio.scenes
            for unit in scene.units
        },
        policy=policy,
        policy_problem=policy_problem,
        definitions=definitions,
    )


# --- What a shot needs ---------------------------------------------------------------------


def _dialogue_lines(definition: ShotDefinition) -> list[dict[str, Any]]:
    """The dialogue lines the shot's definition says it carries, in plan order."""
    audio_intent = definition.content.get("audio_intent")
    lines = audio_intent.get("dialogue") if isinstance(audio_intent, dict) else None
    return [line for line in lines if isinstance(line, dict)] if isinstance(lines, list) else []


def _definition_of(ctx: _Context, entry: shot_references.ShotEntry) -> ShotDefinition | None:
    row = entry.row
    if row is None or row.shot_definition_id is None:
        return None
    return ctx.definitions.get(row.shot_definition_id)


def _refusal(ctx: _Context, scene_id: str, entry: shot_references.ShotEntry) -> str | None:
    """Why this shot's request cannot be planned now, or None."""
    if ctx.policy is None:
        return ctx.policy_problem or "The shot-duration settings cannot be read."
    if entry.row is None:
        return "Choose this shot's references first: its request is planned from them."
    if entry.status == "out_of_date":
        return "The references of this shot are out of date. Choose them again first."
    definition = _definition_of(ctx, entry)
    if definition is None:
        return "The shot definition this shot's references were chosen for was not found."
    plan = ctx.plans.get(scene_id)
    if plan is None or plan.row is None:
        return "Plan this scene's shots first."
    if not plan.generation_ready:
        why = plan.generation_blocked_reason or "The shots of this scene are not ready."
        return why + " Plan the shots again first."
    if plan.timeline is None:
        return "The timeline of this scene cannot be read."
    not_ready: list[str] = []
    for line in _dialogue_lines(definition):
        unit = ctx.audio.get((scene_id, str(line.get("unit_id"))))
        if unit is None or unit.status != "ready" or unit.audio is None:
            not_ready.append(str(line.get("unit_id")))
    if not_ready:
        return (
            "Make the speech of every dialogue line first. Not ready: " + ", ".join(not_ready) + "."
        )
    return None


# --- Reading the state ---------------------------------------------------------------------


def _artifacts(inputs: Any) -> list[Any]:
    artifacts = inputs.get("artifacts") if isinstance(inputs, dict) else None
    return artifacts if isinstance(artifacts, list) else []


def _recorded(inputs: Any, kind: str) -> dict[str, Any] | None:
    for artifact in _artifacts(inputs):
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            return artifact
    return None


def _shot_seconds(ctx: _Context, scene_id: str, shot_id: str) -> float | None:
    """The shot's length on its scene's timeline, or None when the timeline cannot be read."""
    plan = ctx.plans.get(scene_id)
    timeline = plan.timeline if plan is not None else None
    if timeline is None:
        return None
    span = next((span for span in timeline.shots if span.shot_id == shot_id), None)
    return round(span.end_s - span.start_s, 3) if span is not None else None


def _whose(unit: speech_synthesis.UnitEntry | None) -> str:
    """ "Arjun's " for a line of dialogue (the speaker's id as a name), else "the narrator's "
    or nothing: it makes the reason say whose voice the line is in.
    """
    if unit is None:
        return ""
    if unit.unit.get("kind") == "narration":
        return "the narrator's "
    speaker = unit.unit.get("speaker_id")
    return f"{str(speaker).replace('_', ' ').title()}'s " if isinstance(speaker, str) else ""


def _out_of_date_reasons(
    row: GenerationRequest, ctx: _Context, scene_id: str, entry: shot_references.ShotEntry
) -> list[str]:
    """Why a request made for this shot is no longer current, one sentence each."""
    reasons: list[str] = []
    recorded = _recorded(row.inputs, MANIFEST_KIND)
    if entry.row is None:
        reasons.append("The shot has no reference pictures now.")
    elif not provenance.same_row(recorded, entry.row):
        reasons.append(
            "The references of the shot were chosen again since the request was planned."
        )
    elif entry.status == "out_of_date":
        reasons.append("The references of the shot are out of date.")

    for artifact in _artifacts(row.inputs):
        if not isinstance(artifact, dict) or artifact.get("kind") != AUDIO_KIND:
            continue
        unit_id = str(artifact.get("unit_id"))
        unit = ctx.audio.get((scene_id, unit_id))
        whose = _whose(unit)
        if unit is None or unit.status != "ready" or unit.audio is None:
            first = unit.reasons[0] if unit is not None and unit.reasons else None
            reasons.append(
                f"The speech of {whose}line '{unit_id}' is no longer ready"
                + (f": {first}" if first is not None else ".")
            )
        elif unit.audio.id != artifact.get("id"):
            reasons.append(f"The speech of {whose}line '{unit_id}' was made again.")

    seconds = _shot_seconds(ctx, scene_id, row.shot_id)
    if seconds is not None and seconds != row.content.get("target_seconds"):
        reasons.append("The length of the shot changed since its request was planned.")

    rules = row.inputs.get("rules") if isinstance(row.inputs, dict) else None
    if ctx.policy is not None and isinstance(rules, dict):
        if (
            rules.get("hard_min_s") != ctx.policy.hard_min_s
            or rules.get("hard_max_s") != ctx.policy.hard_max_s
        ):
            reasons.append("The shot-duration limits changed since its request was planned.")
    if row.inputs.get("orientation") != ctx.project.orientation:
        reasons.append("The project's orientation changed since the request was planned.")
    return reasons


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, GenerationRequest]:
    """The newest request of each shot of the project, by its `scene/shot` key."""
    statement = (
        select(GenerationRequest)
        .where(GenerationRequest.project_id == project_id)
        .order_by(GenerationRequest.version.desc(), GenerationRequest.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, GenerationRequest] = {}
    for row in (await session.execute(statement)).scalars():
        key = _key(row.scene_id, row.shot_id)
        if key not in newest:
            newest[key] = row
    return newest


def _build(ctx: _Context, rows: dict[str, GenerationRequest]) -> GenerationRequestsState:
    entries: list[SceneEntry] = []
    for scene in ctx.references.entries:
        scene_id = scene.item["id"]
        shots: list[ShotEntry] = []
        for entry in scene.shots:
            row = rows.get(_key(scene_id, entry.shot["id"]))
            status: Status = "not_planned"
            reasons: list[str] = []
            if row is not None:
                reasons = _out_of_date_reasons(row, ctx, scene_id, entry)
                status = "out_of_date" if reasons else "planned"
            blocked = _refusal(ctx, scene_id, entry)
            shots.append(
                ShotEntry(
                    shot=entry.shot,
                    duration_s=entry.duration_s,
                    manifest_status=entry.status,
                    status=status,
                    reasons=reasons,
                    row=row,
                    can_run=blocked is None,
                    blocked_reason=blocked,
                )
            )
        entries.append(SceneEntry(item=scene.item, shots=shots))
    return GenerationRequestsState(
        scenes_version=ctx.references.scenes_version,
        entries=entries,
        blocked_reason=ctx.references.blocked_reason,
    )


async def state(session: AsyncSession, project: Project) -> GenerationRequestsState:
    """The newest list of scenes with where each shot's request stands. Worked out on every
    read; nothing here is stored.
    """
    ctx = await _load(session, project)
    return _build(ctx, await _newest_rows(session, project.id))


# --- Planning ------------------------------------------------------------------------------


def continues_from(plan_content: Any, shot_id: str) -> str | None:
    """The id of the shot before `shot_id` in a shot plan's content when the plan marks the shot
    as continuing it (PHASE-032), else None. The first shot of a scene never continues.
    """
    shots = plan_content.get("shots") if isinstance(plan_content, dict) else None
    if not isinstance(shots, list):
        return None
    for position, shot in enumerate(shots):
        if isinstance(shot, dict) and shot.get("id") == shot_id:
            previous = shots[position - 1] if position > 0 else None
            if shot.get("continues_previous") is True and isinstance(previous, dict):
                previous_id = previous.get("id")
                return previous_id if isinstance(previous_id, str) else None
            return None
    return None


def _plan_inputs(
    ctx: _Context, scene_id: str, entry: shot_references.ShotEntry
) -> tuple[generation_planner.GenerationPlan, list[dict[str, Any]]]:
    """Runs the router for one shot that passed `_refusal`, and returns the plan with the
    artifacts it was made from. Raises GenerationRequestsError.
    """
    manifest = entry.row
    definition = _definition_of(ctx, entry)
    plan_entry = ctx.plans.get(scene_id)
    assert manifest is not None and definition is not None and ctx.policy is not None
    assert plan_entry is not None and plan_entry.row is not None and plan_entry.timeline is not None
    shot_id = entry.shot["id"]
    timeline = plan_entry.timeline
    span = next((span for span in timeline.shots if span.shot_id == shot_id), None)
    if span is None:
        raise GenerationRequestsError(f"The shot '{shot_id}' is not on the scene's timeline.")
    units = {unit.unit_id: unit for unit in timeline.units}

    dialogue: list[generation_planner.DialogueInput] = []
    artifacts: list[dict[str, Any]] = [
        {"kind": MANIFEST_KIND, "id": manifest.id, "version": manifest.version},
        {"kind": DEFINITION_KIND, "id": definition.id, "version": definition.version},
        {"kind": PLAN_KIND, "id": plan_entry.row.id, "version": plan_entry.row.version},
    ]
    for line in _dialogue_lines(definition):
        unit_id = str(line.get("unit_id"))
        unit = ctx.audio[(scene_id, unit_id)]
        span_of_unit = units.get(unit_id)
        audio = unit.audio
        assert audio is not None  # `_refusal` checked every line
        if span_of_unit is None:
            raise GenerationRequestsError(f"The line '{unit_id}' is not on the scene's timeline.")
        dialogue.append(
            generation_planner.DialogueInput(
                unit_id=unit_id,
                speaker_id=str(line.get("speaker_id")),
                text=str(line.get("text")),
                audio_id=audio.id,
                audio_key=audio.audio_key,
                duration_s=audio.duration_s,
                start_in_shot_s=span_of_unit.start_s - span.start_s,
            )
        )
        artifacts.append(
            {
                "kind": AUDIO_KIND,
                "id": audio.id,
                "unit_id": unit_id,
                "audio_key": audio.audio_key,
                "duration_s": audio.duration_s,
            }
        )

    visible = [
        character["id"]
        for character in definition.content.get("characters") or []
        if isinstance(character, dict) and isinstance(character.get("id"), str)
    ]
    try:
        plan = generation_planner.plan(
            scene_id=scene_id,
            shot_id=shot_id,
            target_s=span.end_s - span.start_s,
            policy=ctx.policy,
            orientation=ctx.project.orientation,
            pictures=manifest.content["references"],
            dialogue=dialogue,
            visible_character_ids=visible,
            continues_from=continues_from(plan_entry.row.content, shot_id),
        )
    except generation_planner.GenerationPlanError as exc:
        raise GenerationRequestsError(str(exc)) from exc
    return plan, artifacts


async def _add(
    session: AsyncSession, ctx: _Context, scene_id: str, entry: shot_references.ShotEntry
) -> GenerationRequest:
    """Plans and adds the shot's next request. Flushes but does not commit. Raises
    GenerationRequestsError.
    """
    plan, artifacts = _plan_inputs(ctx, scene_id, entry)
    manifest = entry.row
    policy = ctx.policy
    assert manifest is not None and policy is not None
    shot_id = entry.shot["id"]
    highest = (
        await session.execute(
            select(func.max(GenerationRequest.version)).where(
                GenerationRequest.project_id == ctx.project.id,
                GenerationRequest.scene_id == scene_id,
                GenerationRequest.shot_id == shot_id,
            )
        )
    ).scalar_one_or_none()
    row = GenerationRequest(
        project_id=ctx.project.id,
        scene_id=scene_id,
        shot_id=shot_id,
        shot_reference_manifest_id=manifest.id,
        version=(highest or 0) + 1,
        source="ai",
        job_id=None,
        inputs={
            "project_id": ctx.project.id,
            "scene_id": scene_id,
            "shot_id": shot_id,
            "artifacts": artifacts,
            "rules": {"hard_min_s": policy.hard_min_s, "hard_max_s": policy.hard_max_s},
            "orientation": ctx.project.orientation,
        },
        content=plan.as_dict(),
    )
    session.add(row)
    await session.flush()
    _logger.info(
        "generation request of shot '%s' of scene '%s' of project %d planned, version %d "
        "(%s, %d frames, %d pictures, %d audios)",
        shot_id,
        scene_id,
        ctx.project.id,
        row.version,
        plan.route,
        plan.num_frames,
        len(plan.pictures),
        len(plan.audios),
    )
    return row


async def _commit(session: AsyncSession) -> None:
    """Commits, turning a clash of two plannings of one shot into a readable refusal."""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise GenerationRequestsError(
            "The request of a shot was planned at the same moment. Try again."
        ) from exc


async def _plan_entries(
    session: AsyncSession,
    ctx: _Context,
    scene: shot_references.SceneEntry,
    current: SceneEntry,
    result: PlanResult,
) -> None:
    """Plans every shot of the scene that has no request or an out of date one, adding to
    `result`. A shot that cannot be done is skipped with the reason.
    """
    scene_id = scene.item["id"]
    title = scene.item["title"]
    by_id = {entry.shot["id"]: entry for entry in scene.shots}
    for shot in current.shots:
        shot_id = shot.shot["id"]
        if shot.status == "planned":
            result.skipped.append(
                Skipped(scene_id, shot_id, title, "Already planned and up to date.")
            )
        elif shot.blocked_reason is not None:
            result.skipped.append(Skipped(scene_id, shot_id, title, shot.blocked_reason))
        else:
            try:
                row = await _add(session, ctx, scene_id, by_id[shot_id])
            except GenerationRequestsError as exc:
                result.skipped.append(Skipped(scene_id, shot_id, title, str(exc)))
            else:
                result.planned.append(Planned(scene_id, shot_id, row.version))


async def plan_shot(
    session: AsyncSession, project: Project, scene_id: str, shot_id: str
) -> PlanResult:
    """Plans the request of one shot and commits. A request that is current already is not made
    again (the answer says so). Raises GenerationRequestsError when the shot cannot be done.
    """
    ctx = await _load(session, project)
    current = _build(ctx, await _newest_rows(session, project.id))
    scene = next((entry for entry in current.entries if entry.item["id"] == scene_id), None)
    if scene is None:
        raise GenerationRequestsError(f"There is no scene '{scene_id}' in the newest scene list.")
    shot = next((entry for entry in scene.shots if entry.shot["id"] == shot_id), None)
    if shot is None:
        raise GenerationRequestsError(
            f"There is no shot '{shot_id}' in the newest shot plan of the scene '{scene_id}'."
        )
    result = PlanResult(planned=[], skipped=[])
    if shot.status == "planned":
        result.skipped.append(
            Skipped(scene_id, shot_id, scene.item["title"], "Already planned and up to date.")
        )
        return result
    if shot.blocked_reason is not None:
        raise GenerationRequestsError(shot.blocked_reason)
    references = next(entry for entry in ctx.references.entries if entry.item["id"] == scene_id)
    reference = next(entry for entry in references.shots if entry.shot["id"] == shot_id)
    row = await _add(session, ctx, scene_id, reference)
    await _commit(session)
    result.planned.append(Planned(scene_id, shot_id, row.version))
    return result


async def plan_scene(session: AsyncSession, project: Project, scene_id: str) -> PlanResult:
    """Plans the request of every shot of one scene that has none or an out of date one, and
    commits once. Raises GenerationRequestsError for an unknown scene.
    """
    ctx = await _load(session, project)
    current = _build(ctx, await _newest_rows(session, project.id))
    scene = next((entry for entry in current.entries if entry.item["id"] == scene_id), None)
    if scene is None:
        raise GenerationRequestsError(f"There is no scene '{scene_id}' in the newest scene list.")
    references = next(entry for entry in ctx.references.entries if entry.item["id"] == scene_id)
    result = PlanResult(planned=[], skipped=[])
    await _plan_entries(session, ctx, references, scene, result)
    await _commit(session)
    return result


async def plan_all(session: AsyncSession, project: Project) -> PlanResult:
    """Plans the request of every shot, in every scene, that has none or an out of date one, and
    commits once. A shot that cannot be done is skipped with the reason. Raises
    GenerationRequestsError when nothing can be done yet.
    """
    ctx = await _load(session, project)
    if ctx.references.blocked_reason is not None:
        raise GenerationRequestsError(ctx.references.blocked_reason)
    current = _build(ctx, await _newest_rows(session, project.id))
    result = PlanResult(planned=[], skipped=[])
    for scene in current.entries:
        references = next(
            entry for entry in ctx.references.entries if entry.item["id"] == scene.item["id"]
        )
        await _plan_entries(session, ctx, references, scene, result)
    await _commit(session)
    return result


async def plan_if_ready(
    session: AsyncSession, project_id: int, scene_id: str, shot_id: str
) -> bool:
    """Plans the request of this shot when its manifest is chosen and it has no current request;
    commits. Returns whether a request was made. Called after a manifest is chosen; a shot that
    cannot be done is logged and left for the user's **Plan**.
    """
    project = await session.get(Project, project_id)
    if project is None:
        return False
    try:
        result = await plan_shot(session, project, scene_id, shot_id)
    except GenerationRequestsError as exc:
        _logger.info(
            "shot '%s' of scene '%s' of project %d: request not planned by itself: %s",
            shot_id,
            scene_id,
            project_id,
            exc,
        )
        return False
    return bool(result.planned)
