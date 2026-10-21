"""The shot continuity check of a story project (PHASE-023, `Path_ahead.md` Section 26, "Shot
continuity").

Shot definitions run in parallel (PHASE-022), so neighbouring shots can disagree about where a
character is when one shot ends and the next begins. For each scene, one `check_shot_continuity`
job asks the model to judge every boundary of the scene (its start, each cut, its end;
`services/shot_continuity_writer`), and `save_check` stores the verdict as a new
`shot_continuity_check` row: one immutable row per check, numbered per scene, with the provenance
of the artifact convention (D-3). Nothing is written to the Character Lab and no shot is changed
by the check itself.

**When it runs.**
- Automatically: `queue_check_if_ready` is called after every `define_shot` job. When that was the
  last shot of its scene to be defined and nothing else is running for the scene, the scene's
  check is queued.
- By hand: `start_scene` and `start_all` (the **Check continuity** buttons) queue a check at
  round 0.

**Reconciling.** After a check, `queue_redefinitions` defines again the shots that do not line up
(`shots_to_redefine`: the later shot of a failing cut, the first shot for a scene-start mismatch,
the last for a scene-end mismatch), passing what they must match as data
(`shot_definitions.start_shot(..., continuity=...)`). When they are all defined, the scene is
checked again. A check's `round` is how many such re-definitions came before it; re-definitions
stop when the round reaches `shot_continuity_max_rounds`, and what still does not line up is shown.
A definition or a check the user asks for starts the count again.

**Off the critical path.** Nothing waits for this stage and nothing else reads its status yet.

`state` is what the story workspace shows. **Out of date is worked out on every read** and never
stored: a check covers the shot definitions it read; once any of them is newer, the scene reads
`not_checked`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, Project, ShotContinuityCheck
from app.jobs import store
from app.services import (
    scene_definitions,
    shot_continuity_writer,
    shot_definitions,
    story_bible,
)

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "check_shot_continuity"
# Two presses on one scene make one job; two scenes run side by side.
DEDUPE_KEY: Final = "scene_id"

# How many of a project's newest check jobs are read to find each scene's newest one.
_JOB_LOOKBACK: Final = 500

STORY_BIBLE_KIND: Final = "story_bible"
SCENE_DEFINITION_KIND: Final = "scene_definition"
SHOT_PLAN_KIND: Final = "shot_plan"
SHOT_DEFINITION_KIND: Final = "shot_definition"

# `not_checked`: no check covers the shots as they are now (or the shots are not all defined).
# `checking`: the check is running. `reconciling`: shots are being defined again for continuity.
# `consistent`: the newest check covers the shots and found nothing. `mismatches`: it found some.
Status = Literal["not_checked", "checking", "reconciling", "consistent", "mismatches"]
# One shot's place in the check. `ok` and `mismatch` only when a check covers the shots.
Flag = Literal["not_checked", "ok", "mismatch"]


class ShotContinuityError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class ShotFlag:
    """One shot of a scene and where its continuity stands."""

    shot_id: str
    flag: Flag
    # What the check found at this shot's boundaries, one sentence each. Empty unless `mismatch`.
    problems: list[str]
    # The round of the continuity check that made this shot's newest definition, when it was
    # defined again for continuity; else None.
    redefined_round: int | None


@dataclass(frozen=True)
class SceneContinuity:
    """One scene of the newest list of scenes and where its continuity stands."""

    item: dict[str, Any]
    status: Status
    # The newest check of the scene, when it has one, and the newest check job.
    row: ShotContinuityCheck | None
    job: Job | None
    # The round being worked on (`reconciling`), else the newest check's round, else 0.
    round: int
    max_rounds: int
    # The boundaries that do not match, when `mismatches`: `{id, before, after, problem}`.
    mismatches: list[dict[str, Any]]
    # True when `mismatches` and no more rounds are left.
    round_limit_reached: bool
    shots: list[ShotFlag]
    # Whether Check continuity may be pressed, and the reason when it may not.
    can_run: bool
    blocked_reason: str | None


@dataclass(frozen=True)
class ShotContinuityState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    max_rounds: int
    entries: list[SceneContinuity]
    # Why nothing can be checked yet, or None.
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    """A scene that a "Check continuity" press did not start, and why."""

    scene_id: str
    title: str
    reason: str


@dataclass(frozen=True)
class StartResult:
    job_ids: list[int]
    skipped: list[Skipped]


# --- Small rules --------------------------------------------------------------------------


def _is_active(job: Job | None) -> bool:
    return job is not None and job.status in store.ACTIVE_STATUSES


def _not_ready_reason(entry: shot_definitions.SceneEntry, check_active: bool) -> str | None:
    """Why this scene cannot be checked now, or None: its shots must all be defined and current
    and nothing may be running for the scene.
    """
    if not entry.shots:
        return "The shots of this scene are not planned."
    if check_active:
        return "The continuity of this scene is being checked."
    for shot in entry.shots:
        shot_id = shot.shot["id"]
        if _is_active(shot.job):
            return f"The shot '{shot_id}' is being defined."
        if shot.status == "not_defined":
            return f"The shot '{shot_id}' is not defined. Define the shots first."
        if shot.status == "out_of_date":
            return f"The shot '{shot_id}' is out of date. Define it again first."
    return None


def _covers(row: ShotContinuityCheck, entry: shot_definitions.SceneEntry) -> bool:
    """Whether this check read exactly the shot plan and the shot definitions the scene has now."""
    if entry.plan is None or row.shot_plan_id != entry.plan.id:
        return False
    artifacts = row.inputs.get("artifacts") if isinstance(row.inputs, dict) else None
    recorded = {
        (artifact.get("shot_id"), artifact.get("id"))
        for artifact in artifacts or []
        if isinstance(artifact, dict) and artifact.get("kind") == SHOT_DEFINITION_KIND
    }
    current = {(shot.shot["id"], shot.row.id) for shot in entry.shots if shot.row is not None}
    return len(current) == len(entry.shots) and recorded == current


def _continuity_of(row: Any) -> dict[str, Any] | None:
    """The `inputs.continuity` of a shot definition made for continuity, or None."""
    inputs = getattr(row, "inputs", None)
    value = inputs.get("continuity") if isinstance(inputs, dict) else None
    return value if isinstance(value, dict) else None


def _round_of_integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _round_of_definitions(
    entry: shot_definitions.SceneEntry, newest_check: ShotContinuityCheck | None
) -> int:
    """The round a check made now belongs to. The newest definition of the scene's shots tells:
    if it was made for continuity by the newest check, the round it carries; if the user made it
    (or no check came before it), 0.
    """
    rows = [shot.row for shot in entry.shots if shot.row is not None]
    if not rows or newest_check is None:
        return 0
    newest = max(rows, key=lambda row: row.id)
    continuity = _continuity_of(newest)
    if continuity is None or continuity.get("check_id") != newest_check.id:
        return 0
    return _round_of_integer(continuity.get("round"))


def _active_reconciling_round(entry: shot_definitions.SceneEntry) -> int | None:
    """The round of the re-definitions running for this scene, or None when none run."""
    rounds: list[int] = []
    for shot in entry.shots:
        job = shot.job
        if not _is_active(job) or job is None or not isinstance(job.input, dict):
            continue
        continuity = job.input.get("continuity")
        if isinstance(continuity, dict):
            rounds.append(_round_of_integer(continuity.get("round")))
    return max(rounds) if rounds else None


# --- Reading the state --------------------------------------------------------------------


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest check job of each scene of the project, by scene id."""
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


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, ShotContinuityCheck]:
    """The newest check of each scene of the project, by scene id."""
    statement = (
        select(ShotContinuityCheck)
        .where(ShotContinuityCheck.project_id == project_id)
        .order_by(ShotContinuityCheck.version.desc(), ShotContinuityCheck.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, ShotContinuityCheck] = {}
    for row in (await session.execute(statement)).scalars():
        if row.scene_id not in newest:
            newest[row.scene_id] = row
    return newest


def _shot_flags(
    entry: shot_definitions.SceneEntry, verdict: list[dict[str, Any]] | None
) -> list[ShotFlag]:
    flags: list[ShotFlag] = []
    for shot in entry.shots:
        shot_id = shot.shot["id"]
        continuity = _continuity_of(shot.row)
        redefined = _round_of_integer(continuity.get("round")) if continuity is not None else None
        if verdict is None:
            flags.append(ShotFlag(shot_id, "not_checked", [], redefined))
            continue
        problems = [
            boundary["problem"]
            for boundary in verdict
            if not boundary["matches"]
            and shot_id in (boundary["before"], boundary["after"])
            and boundary["problem"] is not None
        ]
        flags.append(ShotFlag(shot_id, "mismatch" if problems else "ok", problems, redefined))
    return flags


def _scene_state(
    entry: shot_definitions.SceneEntry,
    row: ShotContinuityCheck | None,
    job: Job | None,
    max_rounds: int,
) -> SceneContinuity:
    check_active = _is_active(job)
    reconciling = _active_reconciling_round(entry)
    reason = _not_ready_reason(entry, check_active)

    status: Status
    if check_active:
        status = "checking"
    elif reconciling is not None:
        status = "reconciling"
    elif reason is not None or row is None or not _covers(row, entry):
        status = "not_checked"
    else:
        status = "consistent" if row.content["mismatch_count"] == 0 else "mismatches"

    covered = status in ("consistent", "mismatches") and row is not None
    verdict = row.content["boundaries"] if covered and row is not None else None
    mismatches = (
        [
            {
                "id": boundary["id"],
                "before": boundary["before"],
                "after": boundary["after"],
                "problem": boundary["problem"],
            }
            for boundary in verdict
            if not boundary["matches"]
        ]
        if verdict is not None and status == "mismatches"
        else []
    )
    round_now = reconciling if reconciling is not None else (row.round if row is not None else 0)
    return SceneContinuity(
        item=entry.item,
        status=status,
        row=row,
        job=job,
        round=round_now,
        max_rounds=max_rounds,
        mismatches=mismatches,
        round_limit_reached=status == "mismatches" and row is not None and row.round >= max_rounds,
        shots=_shot_flags(entry, verdict),
        can_run=reason is None,
        blocked_reason=reason,
    )


async def state(session: AsyncSession, project: Project) -> ShotContinuityState:
    """The newest list of scenes with where each scene's continuity stands. Worked out on every
    read; nothing here is stored.
    """
    definitions = await shot_definitions.state(session, project)
    rows = await _newest_rows(session, project.id)
    jobs = await _newest_jobs(session, project.id)
    max_rounds = await settings_service.get_int(
        session, settings_service.SHOT_CONTINUITY_MAX_ROUNDS_KEY
    )
    return ShotContinuityState(
        scenes_version=definitions.scenes_version,
        max_rounds=max_rounds,
        entries=[
            _scene_state(entry, rows.get(entry.item["id"]), jobs.get(entry.item["id"]), max_rounds)
            for entry in definitions.entries
        ],
        blocked_reason=definitions.blocked_reason,
    )


# --- Starting a check ---------------------------------------------------------------------


async def _queue_check(
    session: AsyncSession,
    project: Project,
    entry: shot_definitions.SceneEntry,
    round_: int,
) -> tuple[Job, bool]:
    """Queues the check of this scene and returns `(job, created)`. `created` is False when the
    scene already has a check waiting or running, which is returned instead. The scene must be
    ready (`_not_ready_reason`). Raises ShotContinuityError.
    """
    scene_id = entry.item["id"]
    bible = await story_bible.latest(session, project.id)
    if bible is None or project.script_text is None or not project.script_text.strip():
        raise ShotContinuityError("Run the Story Bible first: continuity is checked with its help.")
    plan = entry.plan
    contents = [shot.content for shot in entry.shots]
    if plan is None or any(content is None for content in contents):
        raise ShotContinuityError("Define every shot of this scene first.")
    definitions = {
        scene.item["id"]: scene
        for scene in (await scene_definitions.state(session, project)).entries
    }
    scene_definition = definitions.get(scene_id)
    if scene_definition is None or scene_definition.row is None:
        raise ShotContinuityError(
            "Define this scene first: its continuity starts from its definition."
        )
    current = await scene_definitions.current_definitions(session, project)

    shot_contents: list[dict[str, Any]] = [content for content in contents if content is not None]
    boundary_list = shot_continuity_writer.boundaries(scene_definition.row.content, shot_contents)
    characters = [
        {
            "id": character_id,
            "name": current[(scene_definitions.CHARACTER_DEFINITION_KIND, character_id)].name
            if (scene_definitions.CHARACTER_DEFINITION_KIND, character_id) in current
            else character_id,
        }
        for character_id in scene_definition.row.content["characters"]
    ]
    inputs = {
        "project_id": project.id,
        "scene_id": scene_id,
        "story_sha256": story_bible.story_sha256(project.script_text),
        "artifacts": [
            {"kind": STORY_BIBLE_KIND, "id": bible.id, "version": bible.version},
            {
                "kind": SCENE_DEFINITION_KIND,
                "id": scene_definition.row.id,
                "version": scene_definition.row.version,
            },
            {"kind": SHOT_PLAN_KIND, "id": plan.id, "version": plan.version},
            *(
                {
                    "kind": SHOT_DEFINITION_KIND,
                    "id": shot.row.id,
                    "version": shot.row.version,
                    "shot_id": shot.shot["id"],
                }
                for shot in entry.shots
                if shot.row is not None
            ),
        ],
    }
    return await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            DEDUPE_KEY: scene_id,
            "story_bible_id": bible.id,
            "story_bible_version": bible.version,
            "shot_plan_id": plan.id,
            "round": round_,
            "scene": {
                "index": entry.item["index"],
                "id": scene_id,
                "title": entry.item["title"],
                "description": entry.item["description"],
            },
            "characters": characters,
            "shots": [shot_continuity_writer.shot_summary(content) for content in shot_contents],
            "boundaries": boundary_list,
            # Written onto the check the job makes (D-3).
            "inputs": inputs,
        },
        dedupe_key=DEDUPE_KEY,
    )


def _find_scene(
    definitions: shot_definitions.ShotDefinitionsState, scene_id: str
) -> shot_definitions.SceneEntry:
    entry = next((entry for entry in definitions.entries if entry.item["id"] == scene_id), None)
    if entry is None:
        raise ShotContinuityError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    return entry


async def start_scene(session: AsyncSession, project: Project, scene_id: str) -> Job:
    """Queues the check of one scene at round 0, and commits. A scene that is checked already is
    checked again: pressing the button is the user's request. If the scene already has a check
    waiting or running, that job is returned and no new one is made. Raises ShotContinuityError.
    """
    definitions = await shot_definitions.state(session, project)
    entry = _find_scene(definitions, scene_id)
    job = (await _newest_jobs(session, project.id)).get(scene_id)
    if _is_active(job) and job is not None:
        return job
    reason = _not_ready_reason(entry, False)
    if reason is not None:
        raise ShotContinuityError(reason)
    job, _created = await _queue_check(session, project, entry, 0)
    return job


async def start_all(session: AsyncSession, project: Project) -> StartResult:
    """Queues the check of every scene whose shots are all defined and current, that is not
    consistent already and is not being checked. The others are skipped, with the reason.
    Raises ShotContinuityError when nothing can be checked yet.
    """
    definitions = await shot_definitions.state(session, project)
    if definitions.blocked_reason is not None:
        raise ShotContinuityError(definitions.blocked_reason)
    current = await state(session, project)
    status_of = {scene.item["id"]: scene.status for scene in current.entries}
    result = StartResult(job_ids=[], skipped=[])
    for entry in definitions.entries:
        scene_id = entry.item["id"]
        title = entry.item["title"]
        if status_of.get(scene_id) == "consistent":
            result.skipped.append(Skipped(scene_id, title, "Already consistent and up to date."))
            continue
        reason = _not_ready_reason(entry, status_of.get(scene_id) == "checking")
        if reason is not None:
            result.skipped.append(Skipped(scene_id, title, reason))
            continue
        job, created = await _queue_check(session, project, entry, 0)
        if created:
            result.job_ids.append(job.id)
        else:
            result.skipped.append(Skipped(scene_id, title, "Already being checked."))
    return result


async def queue_check_if_ready(session: AsyncSession, project_id: int, scene_id: str) -> Job | None:
    """Queues the check of this scene when its shots are all defined and current, nothing runs
    for it, and no check covers these exact definitions yet; commits. Returns the job, or None
    when no check is queued. Called after every `define_shot` job.

    The check's round comes from the newest definition (`_round_of_definitions`): a definition
    the user made starts the count again.
    """
    project = await session.get(Project, project_id)
    if project is None:
        return None
    definitions = await shot_definitions.state(session, project)
    entry = next((entry for entry in definitions.entries if entry.item["id"] == scene_id), None)
    if entry is None:
        return None
    job = (await _newest_jobs(session, project_id)).get(scene_id)
    if _not_ready_reason(entry, _is_active(job)) is not None:
        return None
    row = (await _newest_rows(session, project_id)).get(scene_id)
    if row is not None and _covers(row, entry):
        return None
    try:
        queued, created = await _queue_check(
            session, project, entry, _round_of_definitions(entry, row)
        )
    except ShotContinuityError as exc:
        _logger.info(
            "scene '%s' of project %d: continuity not checked by itself: %s",
            scene_id,
            project_id,
            exc,
        )
        return None
    return queued if created else None


# --- Defining shots again -----------------------------------------------------------------


async def queue_redefinitions(session: AsyncSession, project_id: int, check_id: int) -> list[Job]:
    """Defines again the shots that do not line up in this check, and commits each. Returns the
    jobs queued. Nothing is queued when the check found no mismatch, the rounds are used up
    (`shot_continuity_max_rounds`), a newer check exists, or the shots were changed since the
    check read them (then the check no longer describes them).
    """
    project = await session.get(Project, project_id)
    check = await session.get(ShotContinuityCheck, check_id)
    if project is None or check is None or check.content["mismatch_count"] == 0:
        return []
    max_rounds = await settings_service.get_int(
        session, settings_service.SHOT_CONTINUITY_MAX_ROUNDS_KEY
    )
    if check.round >= max_rounds:
        _logger.info(
            "scene '%s' of project %d: %d boundaries do not line up, the %d rounds are used",
            check.scene_id,
            project_id,
            check.content["mismatch_count"],
            max_rounds,
        )
        return []
    newest = (await _newest_rows(session, project_id)).get(check.scene_id)
    if newest is None or newest.id != check.id:
        return []
    definitions = await shot_definitions.state(session, project)
    entry = next((e for e in definitions.entries if e.item["id"] == check.scene_id), None)
    if entry is None or _not_ready_reason(entry, False) is not None or not _covers(check, entry):
        return []

    jobs: list[Job] = []
    for redefinition in shot_continuity_writer.shots_to_redefine(check.content["boundaries"]):
        continuity = {
            "check_id": check.id,
            "round": check.round + 1,
            "must_start_from": redefinition.must_start_from,
            "must_end_at": redefinition.must_end_at,
            "problems": redefinition.problems,
        }
        try:
            jobs.append(
                await shot_definitions.start_shot(
                    session, project, check.scene_id, redefinition.shot_id, continuity
                )
            )
        except shot_definitions.ShotDefinitionsError as exc:
            _logger.info(
                "shot '%s' of scene '%s' of project %d: not defined again for continuity: %s",
                redefinition.shot_id,
                check.scene_id,
                project_id,
                exc,
            )
    return jobs


# --- Saving the check ---------------------------------------------------------------------


async def save_check(
    session: AsyncSession,
    *,
    project_id: int,
    scene_id: str,
    shot_plan_id: int,
    round_: int,
    content: dict[str, Any],
    job_id: int,
    inputs: dict[str, Any],
) -> ShotContinuityCheck:
    """Adds the scene's next check. Flushes but does not commit: the job commits it together
    with finishing itself, so a job is never "succeeded" without its result.

    `inputs` is what the job was started with and is stored as it is.
    """
    statement = select(func.max(ShotContinuityCheck.version)).where(
        ShotContinuityCheck.project_id == project_id,
        ShotContinuityCheck.scene_id == scene_id,
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = ShotContinuityCheck(
        project_id=project_id,
        scene_id=scene_id,
        shot_plan_id=shot_plan_id,
        version=(highest or 0) + 1,
        round=round_,
        source="ai",
        job_id=job_id,
        inputs=inputs,
        content=content,
    )
    session.add(row)
    await session.flush()
    _logger.info(
        "job %d: continuity check of scene '%s' of project %d saved, version %d, round %d, "
        "%d mismatches",
        job_id,
        scene_id,
        project_id,
        row.version,
        row.round,
        content["mismatch_count"],
    )
    return row
