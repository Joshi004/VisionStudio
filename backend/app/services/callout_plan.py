"""An explainer's callout plan: starting the job that writes it, saving its versions, and reading
them back (EXPLAINER-009, `Explainer_implementation_phases.md` E-14 to E-18).

Every version is a new `callout_plan` row and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). `content` is `{accent, callouts}`
(`services/callout_plan_writer`). `inputs` records the exact upstream rows it was built from (the
Story Bible and every scene's speech units) and the display limits it was checked against, so
whether it is out of date is worked out when it is read and never stored.

Two ways make a version:

- `start_run` queues a job: one model call writes the accent and the callouts, and code checks
  them for display rules.
- `save_manual` stores the owner's edit (text, type, role, on or off), checked by the same rules.
  Callouts cannot be added or removed here: each keeps the unit and the phrase the model gave it.

**When a plan can be made.** The project must be an explainer with `callouts` on. The Story Bible
must exist and every scene's speech units must be planned and current. The speech does not have
to be spoken yet: the checks use each unit's estimated length (`writer` docstring).

A plan is out of date when the Story Bible or any scene's speech units were made again, the scenes
changed, or the display limits changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import CalloutPlan, Job, Project, StoryBible
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    callout_plan_writer,
    explainer,
    provenance,
    speech_units,
    story_bible,
)
from app.services.callout_plan_writer import CalloutRules, ScriptUnit

JOB_TYPE: Final = "write_callout_plan"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"

STORY_BIBLE_KIND: Final = "story_bible"
SPEECH_UNITS_KIND: Final = "speech_units"

NOT_EXPLAINER_MESSAGE: Final = "Callouts are only for explainers."
OFF_MESSAGE: Final = "Callouts are switched off for this project. Switch them on in the settings."
REPLACE_MESSAGE: Final = (
    "The newest callout plan was written by you. Running the model adds a new version from the "
    "model, so it has to be confirmed."
)
BUSY_MESSAGE: Final = "The callout plan is being written. Wait for it to finish first."
NO_BIBLE_MESSAGE: Final = "Write the Story Bible first: the callouts follow its tone."
NO_PRESENTER_MESSAGE: Final = "This explainer has no presenter."
NO_PLAN_MESSAGE: Final = "There is no callout plan to edit yet."
OUT_OF_DATE_MESSAGE: Final = (
    "The callout plan is out of date, so it cannot be edited. Run it again first."
)
FIXED_SET_MESSAGE: Final = (
    "Callouts cannot be added or removed here: edit or turn off the ones listed."
)


class CalloutPlanError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


def wanted(project: Project) -> bool:
    """Whether the project has a callout plan at all: an explainer with `callouts` on."""
    return explainer.is_explainer(project) and project.callouts


def _off_message(project: Project) -> str:
    return OFF_MESSAGE if explainer.is_explainer(project) else NOT_EXPLAINER_MESSAGE


# --- Loading what the plan is made from ----------------------------------------------------


@dataclass(frozen=True)
class _Loaded:
    bible: StoryBible | None
    speech: speech_units.SpeechState
    presenter_name: str | None
    blocked_reason: str | None
    # The script on its estimated timeline, when nothing is blocked.
    units: list[ScriptUnit]


def _blocked_reason(
    bible: StoryBible | None, speech: speech_units.SpeechState, presenter_name: str | None
) -> str | None:
    if bible is None:
        return NO_BIBLE_MESSAGE
    if speech.blocked_reason is not None:
        return speech.blocked_reason
    if not speech.entries:
        return "There are no scenes yet."
    for entry in speech.entries:
        title = entry.item["title"]
        if entry.row is None:
            return f"The speech of the scene '{title}' is not planned."
        if entry.status == "out_of_date":
            return f"The speech of the scene '{title}' is out of date. Plan it again first."
    if presenter_name is None:
        return NO_PRESENTER_MESSAGE
    return None


def _scenes_for_script(speech: speech_units.SpeechState) -> list[dict[str, Any]]:
    """The scenes in story order with the parts of each speech unit the plan needs."""
    scenes: list[dict[str, Any]] = []
    for entry in speech.entries:
        content = entry.content or {}
        scenes.append(
            {
                "id": entry.item["id"],
                "title": entry.item["title"],
                "units": [
                    {
                        "id": unit["id"],
                        "text": unit["text"],
                        "estimated_seconds": unit.get("estimated_seconds") or 0,
                    }
                    for unit in content.get("units", [])
                ],
            }
        )
    return scenes


async def _load(session: AsyncSession, project: Project) -> _Loaded:
    bible = await story_bible.latest(session, project.id)
    speech = await speech_units.state(session, project)
    presenter = await explainer.presenter_of(session, project.id)
    presenter_name = presenter.name if presenter is not None else None
    blocked = _blocked_reason(bible, speech, presenter_name)
    units: list[ScriptUnit] = []
    if blocked is None:
        units = callout_plan_writer.script_units(_scenes_for_script(speech))
        if not units:
            blocked = "The speech has no lines to put a callout on."
    return _Loaded(
        bible=bible,
        speech=speech,
        presenter_name=presenter_name,
        blocked_reason=blocked,
        units=units,
    )


async def read_rules(session: AsyncSession) -> CalloutRules:
    """The display limits that apply now, read at the moment of use."""
    return CalloutRules(
        min_gap_ms=await settings_service.get_int(session, settings_service.CALLOUT_MIN_GAP_MS_KEY),
        per_minute_max=await settings_service.get_int(
            session, settings_service.CALLOUTS_PER_MINUTE_MAX_KEY
        ),
    )


def _inputs(loaded: _Loaded, rules: CalloutRules) -> dict[str, Any]:
    """What a version is built from, in the artifact shape of D-3. A manual save records exactly
    what a job would.
    """
    assert loaded.bible is not None
    artifacts: list[dict[str, Any]] = [
        {"kind": STORY_BIBLE_KIND, "id": loaded.bible.id, "version": loaded.bible.version}
    ]
    for entry in loaded.speech.entries:
        assert entry.row is not None
        artifacts.append(
            {
                "kind": SPEECH_UNITS_KIND,
                "id": entry.row.id,
                "version": entry.row.version,
                "scene_id": entry.item["id"],
            }
        )
    return {"artifacts": artifacts, "rules": rules.as_dict()}


def _job_input(loaded: _Loaded, rules: CalloutRules) -> dict[str, Any]:
    """What a job is sent: a copy of everything it needs, taken when the button was pressed."""
    assert loaded.bible is not None and loaded.presenter_name is not None
    return {
        "bible": loaded.bible.content,
        "presenter_name": loaded.presenter_name,
        "scenes": _scenes_for_script(loaded.speech),
        "rules": rules.as_dict(),
        "saved_inputs": _inputs(loaded, rules),
    }


# --- Starting runs -------------------------------------------------------------------------


def needs_confirmation(row: CalloutPlan | None) -> bool:
    """Whether running the model again would replace what the owner wrote."""
    return row is not None and row.source == SOURCE_MANUAL


async def _refuse_when_unable(session: AsyncSession, project: Project) -> _Loaded:
    if not wanted(project):
        raise CalloutPlanError(_off_message(project))
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise CalloutPlanError(loaded.blocked_reason)
    return loaded


async def start_run(
    session: AsyncSession, project: Project, *, confirm_replace_manual: bool = False
) -> Job:
    """Queues the job that writes the callout plan, from a copy of what it is made from.
    Raises CalloutPlanError when it cannot be written yet, or when it would replace the owner's
    edit and that was not confirmed. Does not commit.
    """
    loaded = await _refuse_when_unable(session, project)
    if needs_confirmation(await latest(session, project.id)) and not confirm_replace_manual:
        raise CalloutPlanError(REPLACE_MESSAGE)
    rules = await read_rules(session)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input=_job_input(loaded, rules),
    )
    return job


# --- Versions ------------------------------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> CalloutPlan | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(CalloutPlan)
        .where(CalloutPlan.project_id == project_id)
        .order_by(CalloutPlan.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def list_versions(session: AsyncSession, project_id: int) -> list[CalloutPlan]:
    """Every version of the project, newest first."""
    statement = (
        select(CalloutPlan)
        .where(CalloutPlan.project_id == project_id)
        .order_by(CalloutPlan.version.desc())
    )
    return list((await session.execute(statement)).scalars())


async def get_version(session: AsyncSession, project_id: int, version: int) -> CalloutPlan | None:
    """One version of the project, or None when there is no such version."""
    statement = select(CalloutPlan).where(
        CalloutPlan.project_id == project_id, CalloutPlan.version == version
    )
    return (await session.execute(statement)).scalars().first()


async def _add_version(
    session: AsyncSession,
    project_id: int,
    *,
    source: str,
    job_id: int | None,
    inputs: dict[str, Any],
    content: dict[str, Any],
) -> CalloutPlan:
    statement = select(func.max(CalloutPlan.version)).where(CalloutPlan.project_id == project_id)
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = CalloutPlan(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=source,
        job_id=job_id,
        inputs=inputs,
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
    content: dict[str, Any],
) -> CalloutPlan:
    """Adds the next version, made by the model (`source` is `ai`). Flushes but does not
    commit: the job commits it together with finishing itself, so a job is never "succeeded"
    without its result.
    """
    return await _add_version(
        session, project_id, source=SOURCE_AI, job_id=job_id, inputs=inputs, content=content
    )


def _merged_for_check(newest: CalloutPlan, edits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The newest version's callouts with the owner's edits laid over them, in the newest
    version's order, in the form `check_callouts` reads. What an edit does not carry (the unit,
    the phrase, the phrase of an item or a side) stays as it was. Raises CalloutPlanError when
    the edits are not exactly the callouts of the newest version.
    """
    stored = {callout["id"]: callout for callout in newest.content["callouts"]}
    edited = {edit["id"]: edit for edit in edits}
    if len(edited) != len(edits) or set(edited) != set(stored):
        raise CalloutPlanError(FIXED_SET_MESSAGE)
    merged: list[dict[str, Any]] = []
    for callout_id, before in stored.items():
        edit = edited[callout_id]
        same_type = edit["type"] == before["type"]
        merged.append(
            {
                "id": callout_id,
                "type": edit["type"],
                "role": edit.get("role"),
                "enabled": edit["enabled"],
                "unit": f"{before['scene_id']}/{before['unit_id']}",
                "phrase": before["phrase"],
                "text": edit.get("text"),
                "items": _with_phrases(edit.get("items"), before["items"] if same_type else None),
                "sides": _with_phrases(edit.get("sides"), before["sides"] if same_type else None),
            }
        )
    return merged


def _with_phrases(
    entries: list[dict[str, Any]] | None, before: list[dict[str, Any]] | None
) -> list[dict[str, Any]] | None:
    """The items or sides of an edit, each with the phrase it had when the edit has none. A
    new one has none, and the check gives it the callout's phrase.
    """
    if entries is None:
        return None
    result: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        entry = dict(entry)
        if not entry.get("phrase") and before is not None and index < len(before):
            entry["phrase"] = before[index]["phrase"]
        result.append(entry)
    return result


async def save_manual(
    session: AsyncSession, project: Project, edits: list[dict[str, Any]]
) -> CalloutPlan:
    """Stores the owner's edited callouts as the next version (`source` is `manual`), and
    commits. `edits` has one entry per callout of the newest version (`id`, `type`, `role`,
    `enabled`, and the `text`, the `items` or the `sides` of its type).

    The callouts are checked by the same display rules as the model's answer, against the script
    as it is now. The accent stays as it was. Refused while a job is writing the plan, when the
    plan is out of date (its units may no longer be what it says), and when the edits add or
    remove a callout. Raises CalloutPlanError.
    """
    newest = await latest(session, project.id)
    if newest is None:
        raise CalloutPlanError(NO_PLAN_MESSAGE)
    active = await store.latest_job(session, project.id, JOB_TYPE)
    if active is not None and active.status in store.ACTIVE_STATUSES:
        raise CalloutPlanError(BUSY_MESSAGE)
    loaded = await _refuse_when_unable(session, project)
    rules = await read_rules(session)
    if _out_of_date_reasons(newest, loaded, rules):
        raise CalloutPlanError(OUT_OF_DATE_MESSAGE)
    assert loaded.presenter_name is not None
    try:
        checked = callout_plan_writer.check_callouts(
            _merged_for_check(newest, edits),
            units=loaded.units,
            presenter_name=loaded.presenter_name,
            rules=rules,
            manual=True,
        )
    except ValueError as exc:
        raise CalloutPlanError(str(exc)) from exc
    row = await _add_version(
        session,
        project.id,
        source=SOURCE_MANUAL,
        job_id=None,
        inputs={
            **_inputs(loaded, rules),
            "edited_from": {"id": newest.id, "version": newest.version},
        },
        content={"accent": newest.content["accent"], "callouts": checked},
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


def _out_of_date_reasons(row: CalloutPlan, loaded: _Loaded, rules: CalloutRules) -> list[str]:
    """Why a version is no longer current, one sentence each."""
    inputs = row.inputs if isinstance(row.inputs, dict) else {}
    reasons: list[str] = []
    if not provenance.same_row(_recorded(inputs, STORY_BIBLE_KIND), loaded.bible):
        reasons.append("The Story Bible was written again since this plan was made.")
    recorded_scenes = {
        artifact.get("scene_id")
        for artifact in inputs.get("artifacts") or []
        if isinstance(artifact, dict) and artifact.get("kind") == SPEECH_UNITS_KIND
    }
    current_scenes = {entry.item["id"] for entry in loaded.speech.entries}
    if recorded_scenes != current_scenes:
        reasons.append("The list of scenes has changed since this plan was made.")
    else:
        for entry in loaded.speech.entries:
            recorded = _recorded(inputs, SPEECH_UNITS_KIND, entry.item["id"])
            if not provenance.same_row(recorded, entry.row):
                reasons.append(
                    f"The speech of the scene '{entry.item['title']}' changed since this plan "
                    "was made."
                )
    if inputs.get("rules") != rules.as_dict():
        reasons.append("The callout limits were changed since this plan was made.")
    return reasons


@dataclass(frozen=True)
class CalloutPlanState:
    """What the board panel shows."""

    latest: CalloutPlan | None
    versions: list[CalloutPlan]
    # The newest job, whatever its status.
    job: Job | None
    out_of_date: bool
    reasons: list[str]
    needs_confirmation: bool
    # Why no callout plan can be written yet (or at all for this project), or None.
    blocked_reason: str | None
    # Whether the project has a callout plan at all (an explainer with callouts on).
    wanted: bool
    rules: CalloutRules
    # The script the plan is checked against, so the panel can show each callout's line. Empty
    # when blocked.
    script: list[ScriptUnit]


@memoized_state
async def state(session: AsyncSession, project: Project) -> CalloutPlanState:
    """The project's callout plan with where it stands. Worked out on every read; nothing here
    is stored.
    """
    newest = await latest(session, project.id)
    versions = await list_versions(session, project.id)
    job = await store.latest_job(session, project.id, JOB_TYPE)
    rules = await read_rules(session)
    if not wanted(project):
        return CalloutPlanState(
            latest=newest,
            versions=versions,
            job=job,
            out_of_date=False,
            reasons=[],
            needs_confirmation=False,
            blocked_reason=_off_message(project),
            wanted=False,
            rules=rules,
            script=[],
        )
    loaded = await _load(session, project)
    reasons = _out_of_date_reasons(newest, loaded, rules) if newest is not None else []
    return CalloutPlanState(
        latest=newest,
        versions=versions,
        job=job,
        out_of_date=bool(reasons),
        reasons=reasons,
        needs_confirmation=needs_confirmation(newest),
        blocked_reason=loaded.blocked_reason,
        wanted=True,
        rules=rules,
        script=loaded.units,
    )
