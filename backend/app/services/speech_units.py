"""The Speech Planning stage of a story project (PHASE-018, `Path_ahead.md` Section 19).

Each scene whose events are extracted gets a plan of *speech units*: its narration and dialogue
events cut into pieces that will each be turned into one audio asset (PHASE-019), with an
estimated length. The cutting is plain code (`services/speech_unit_planner`), so it runs inside
the request: there is no job and no model call. `plan_scene` and `plan_all` store the result as a
new `speech_units` row: one immutable row per run, numbered per scene, with the provenance of the
artifact convention (D-3). `job_id` stays NULL.

- A scene can only be planned when its events exist and are current. The reason says what is
  missing. A scene with a current plan is skipped by `plan_all`.
- `state` is what the story workspace shows: for each scene its status, why it is out of date,
  and its newest plan. **Out of date is worked out on every read** and never stored: the scene's
  events were extracted again or are themselves out of date, or a speech rule (the pace, the
  narration limit, the dialogue limit) is not what the plan was made with.
- The rules come from the Settings page (group "Speech") and the shot-duration policy: the
  narration limit is its own setting, or the planning target maximum when that is 0, and the
  dialogue limit is the H3 maximum minus a margin.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Project, SpeechUnits
from app.services import duration_policy, scene_events, speech_unit_planner
from app.services.speech_unit_planner import SpeechRules

_logger = logging.getLogger(__name__)

SCENE_EVENTS_KIND: Final = "scene_events"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"

MANUAL_REPLACE_MESSAGE: Final = (
    "The newest speech units of this scene were written by you. Planning them again adds a "
    "new version made by code from the events, so it has to be confirmed."
)
SKIPPED_MANUAL: Final = "Written by you: use this scene's own button to replace it."

# The shortest dialogue limit that is worth planning with: below it nothing would fit.
_MIN_DIALOGUE_LIMIT_SECONDS: Final = 1

# `not_planned`: no units were made for this scene. `planned`: made, and nothing they were
# built from has changed. `out_of_date`: made, and something they were built from has changed.
Status = Literal["not_planned", "planned", "out_of_date"]

_RULE_NAMES: Final = {
    "words_per_minute": "The speech pace",
    "narration_max_seconds": "The longest narration unit",
    "dialogue_max_seconds": "The longest dialogue unit",
}


class SpeechUnitsError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class SceneEntry:
    """One scene of the newest list and where its speech units stand."""

    item: dict[str, Any]
    status: Status
    # Why a planned scene is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The newest plan of this scene, when it has one.
    row: SpeechUnits | None
    # The newest events of this scene, when it has some (what a new plan would be cut from).
    events: scene_events.SceneEntry
    can_run: bool
    blocked_reason: str | None

    @property
    def content(self) -> dict[str, Any] | None:
        return self.row.content if self.row is not None else None

    @property
    def needs_confirmation(self) -> bool:
        """Whether planning this scene again replaces units the user wrote."""
        return self.row is not None and self.row.source == SOURCE_MANUAL


@dataclass(frozen=True)
class SpeechState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    # The discovered characters as `{id, name}`, so that a speaker can be shown by name.
    characters: list[dict[str, str]]
    entries: list[SceneEntry]
    # Why nothing can be planned yet, or None.
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    """A scene that "Plan all" did not plan, and why."""

    scene_id: str
    title: str
    reason: str


@dataclass(frozen=True)
class PlanAllResult:
    planned: list[str]
    skipped: list[Skipped]


# --- The rules ----------------------------------------------------------------------------


async def _read_rules(session: AsyncSession) -> tuple[SpeechRules | None, str | None]:
    """The rules that apply now, or `(None, reason)` when they cannot be used."""
    try:
        policy = await duration_policy.read_duration_policy(session)
    except duration_policy.DurationPolicyError as exc:
        return None, str(exc)
    narration_max = await settings_service.get_int(session, settings_service.NARRATION_UNIT_MAX_KEY)
    margin = await settings_service.get_int(session, settings_service.DIALOGUE_MARGIN_KEY)
    dialogue_max = policy.hard_max_s - margin
    if dialogue_max < _MIN_DIALOGUE_LIMIT_SECONDS:
        return None, (
            f"The dialogue margin ({margin} s) leaves no room under the H3 longest shot "
            f"({policy.hard_max_s} s). Lower it in Settings, Speech."
        )
    return (
        SpeechRules(
            words_per_minute=await settings_service.get_int(
                session, settings_service.SPEECH_WPM_KEY
            ),
            narration_max_seconds=narration_max or policy.target_max_s,
            dialogue_max_seconds=dialogue_max,
        ),
        None,
    )


def _rules_dict(rules: SpeechRules) -> dict[str, int]:
    return {
        "words_per_minute": rules.words_per_minute,
        "narration_max_seconds": rules.narration_max_seconds,
        "dialogue_max_seconds": rules.dialogue_max_seconds,
    }


# --- Reading the state --------------------------------------------------------------------


def _events_refusal(events: scene_events.SceneEntry) -> str | None:
    """Why this scene's units cannot be planned, from its events, or None."""
    if events.row is None:
        return "Extract this scene's events first: speech units are cut from them."
    if events.status == "out_of_date":
        return "The events of this scene are out of date. Extract them again first."
    return None


def _out_of_date_reasons(
    row: SpeechUnits, events: scene_events.SceneEntry, rules: SpeechRules | None
) -> list[str]:
    """Why a plan is no longer current, one sentence each."""
    inputs = row.inputs
    reasons: list[str] = []
    recorded = next(
        (
            artifact
            for artifact in inputs.get("artifacts") or []
            if isinstance(artifact, dict) and artifact.get("kind") == SCENE_EVENTS_KIND
        ),
        None,
    )
    if events.row is None:
        reasons.append("The scene has no events now.")
    else:
        if recorded is None or recorded.get("version") != events.row.version:
            reasons.append("The events of the scene were extracted again since these units.")
        if events.status == "out_of_date":
            reasons.append("The events of the scene are out of date.")
    if rules is not None:
        recorded_rules = inputs.get("rules") or {}
        for key, name in _RULE_NAMES.items():
            if recorded_rules.get(key) != getattr(rules, key):
                reasons.append(f"{name} has changed since these units were planned.")
    return reasons


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, SpeechUnits]:
    """The newest plan of each scene of the project, by its id."""
    statement = (
        select(SpeechUnits)
        .where(SpeechUnits.project_id == project_id)
        .order_by(SpeechUnits.version.desc(), SpeechUnits.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, SpeechUnits] = {}
    for row in (await session.execute(statement)).scalars():
        if row.scene_id not in newest:
            newest[row.scene_id] = row
    return newest


async def state(session: AsyncSession, project: Project) -> SpeechState:
    """The newest list of scenes with where each scene's speech units stand. Worked out on
    every read; nothing here is stored.
    """
    events_state = await scene_events.state(session, project)
    rules, rules_problem = await _read_rules(session)
    rows = await _newest_rows(session, project.id)

    blocked_reason = rules_problem
    if blocked_reason is None and events_state.scenes_version is None:
        blocked_reason = events_state.blocked_reason or "Find the scenes first."

    entries: list[SceneEntry] = []
    for events in events_state.entries:
        row = rows.get(events.item["id"])
        status: Status = "not_planned"
        reasons: list[str] = []
        if row is not None and isinstance(row.inputs, dict):
            reasons = _out_of_date_reasons(row, events, rules)
            status = "out_of_date" if reasons else "planned"
        refusal = blocked_reason or _events_refusal(events)
        entries.append(
            SceneEntry(
                item=events.item,
                status=status,
                reasons=reasons,
                row=row,
                events=events,
                can_run=refusal is None,
                blocked_reason=refusal,
            )
        )
    return SpeechState(
        scenes_version=events_state.scenes_version,
        characters=events_state.characters,
        entries=entries,
        blocked_reason=blocked_reason,
    )


# --- Planning -----------------------------------------------------------------------------


async def _add_plan(
    session: AsyncSession,
    project: Project,
    entry: SceneEntry,
    rules: SpeechRules,
    *,
    parts_by_event: dict[str, list[str]] | None = None,
) -> SpeechUnits:
    """Plans one scene and adds its next version. Flushes but does not commit. With
    `parts_by_event` the units are the user's own cuts and the version is `manual`.
    """
    events_row = entry.events.row
    assert events_row is not None  # the callers refuse a scene without events first
    scene_id = entry.item["id"]
    units, warnings = speech_unit_planner.plan_units(
        events_row.content["events"], rules, parts_by_event=parts_by_event
    )
    highest = (
        await session.execute(
            select(func.max(SpeechUnits.version)).where(
                SpeechUnits.project_id == project.id, SpeechUnits.scene_id == scene_id
            )
        )
    ).scalar_one_or_none()
    row = SpeechUnits(
        project_id=project.id,
        scene_id=scene_id,
        version=(highest or 0) + 1,
        source=SOURCE_AI if parts_by_event is None else SOURCE_MANUAL,
        job_id=None,
        inputs={
            "project_id": project.id,
            "scene_id": scene_id,
            "artifacts": [
                {
                    "kind": SCENE_EVENTS_KIND,
                    "id": events_row.id,
                    "version": events_row.version,
                }
            ],
            "rules": _rules_dict(rules),
        },
        content={
            "scene_id": scene_id,
            "units": units,
            "warnings": [{"event_id": w.event_id, "message": w.message} for w in warnings],
        },
    )
    session.add(row)
    await session.flush()
    _logger.info(
        "speech units of scene '%s' of project %d planned, version %d (%d units)",
        scene_id,
        project.id,
        row.version,
        len(units),
    )
    return row


async def _commit(session: AsyncSession) -> None:
    """Commits, turning a clash of two plans of one scene into a readable refusal."""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise SpeechUnitsError(
            "The speech units of a scene were planned at the same moment. Try again."
        ) from exc


async def plan_scene(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    *,
    confirm_replace_manual: bool = False,
) -> None:
    """Plans one scene's speech units and commits. When the newest plan was written by the user
    it is replaced only when `confirm_replace_manual` is true (PHASE-037). Raises
    SpeechUnitsError.
    """
    current = await state(session, project)
    if current.blocked_reason is not None:
        raise SpeechUnitsError(current.blocked_reason)
    entry = next((item for item in current.entries if item.item["id"] == scene_id), None)
    if entry is None:
        raise SpeechUnitsError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    if entry.blocked_reason is not None:
        raise SpeechUnitsError(entry.blocked_reason)
    if entry.needs_confirmation and not confirm_replace_manual:
        raise SpeechUnitsError(MANUAL_REPLACE_MESSAGE)
    rules, problem = await _read_rules(session)
    if rules is None:
        raise SpeechUnitsError(problem or "The speech rules cannot be used.")
    await _add_plan(session, project, entry, rules)
    await _commit(session)


async def plan_all(
    session: AsyncSession, project: Project, *, confirm_replace_manual: bool = False
) -> PlanAllResult:
    """Plans every scene that has current events and no current plan, and commits once. The
    others are skipped, with the reason. A scene whose newest plan the user wrote is skipped
    unless `confirm_replace_manual` is true (PHASE-037). Raises SpeechUnitsError when nothing
    can be planned yet.
    """
    current = await state(session, project)
    if current.blocked_reason is not None:
        raise SpeechUnitsError(current.blocked_reason)
    rules, problem = await _read_rules(session)
    if rules is None:
        raise SpeechUnitsError(problem or "The speech rules cannot be used.")
    planned: list[str] = []
    skipped: list[Skipped] = []
    for entry in current.entries:
        scene_id, title = entry.item["id"], entry.item["title"]
        if entry.blocked_reason is not None:
            skipped.append(Skipped(scene_id, title, entry.blocked_reason))
        elif entry.status == "planned":
            skipped.append(Skipped(scene_id, title, "Already planned and up to date."))
        elif entry.needs_confirmation and not confirm_replace_manual:
            skipped.append(Skipped(scene_id, title, SKIPPED_MANUAL))
        else:
            await _add_plan(session, project, entry, rules)
            planned.append(scene_id)
    await _commit(session)
    return PlanAllResult(planned=planned, skipped=skipped)


async def save_manual(
    session: AsyncSession, project: Project, scene_id: str, units: list[dict[str, Any]]
) -> None:
    """Stores the user's own cuts of one scene's speech events as the scene's next version
    (`source` is `manual`), and commits (PHASE-037). `units` is a list of `{event_id, text}` in
    the order they are spoken. The scene needs what Plan needs (current events). Only the cuts
    may move: the units of each narration or dialogue event, joined, must hold exactly the
    words of the event, in order, and every speech event needs at least one unit. Ids, estimates
    and warnings are worked out by code. Raises SpeechUnitsError.
    """
    current = await state(session, project)
    if current.blocked_reason is not None:
        raise SpeechUnitsError(current.blocked_reason)
    entry = next((item for item in current.entries if item.item["id"] == scene_id), None)
    if entry is None:
        raise SpeechUnitsError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    if entry.blocked_reason is not None:
        raise SpeechUnitsError(entry.blocked_reason)
    rules, problem = await _read_rules(session)
    if rules is None:
        raise SpeechUnitsError(problem or "The speech rules cannot be used.")

    events_row = entry.events.row
    assert events_row is not None  # `blocked_reason` is set for a scene without events
    speech_ids = {
        event["id"]
        for event in events_row.content["events"]
        if event.get("type") in ("narration", "dialogue")
    }
    parts_by_event: dict[str, list[str]] = {}
    for unit in units:
        event_id = unit["event_id"]
        if event_id not in speech_ids:
            raise SpeechUnitsError(
                f"'{event_id}' is not a narration or dialogue event of the scene."
            )
        parts_by_event.setdefault(event_id, []).append(unit["text"])
    try:
        await _add_plan(session, project, entry, rules, parts_by_event=parts_by_event)
    except ValueError as exc:
        await session.rollback()
        raise SpeechUnitsError(str(exc)) from exc
    await _commit(session)
