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
- Automatically: `queue_check_if_ready` is called after every `define_shot` job and every
  `repair_shot_cut` job. When that was the last shot of its scene to be defined (or the last
  repair of a wave) and nothing else is running for the scene, the scene's check is queued.
- By hand: `start_scene` and `start_all` (the **Check continuity** buttons) queue a check at
  round 0.

**Reconciling.** The mismatch of a check belongs to a **cut** (a boundary), not to either shot.
After a check, `queue_repairs` queues one `repair_shot_cut` job for each cut of the next **wave**
(`shot_continuity_writer.wave`: the cuts that do not line up, taken in order, leaving out one
that shares a shot with a cut already taken). A repair sees both shots, decides which side
changes and keeps the outer edges as they are (`shot_cut_repair_writer`). When the whole wave is
done the scene is checked again, which starts the next wave if cuts still do not line up. A
check's `round` is how many waves came before it; waves stop when the round reaches
`shot_continuity_max_rounds`, and what still does not line up is shown. `start_cut_repair` (the
**Fix this cut** button) repairs one cut at round 0, which starts the count again, and the
automatic waves follow it. A definition or a check the user asks for starts the count again.

**Off the critical path.** Nothing waits for this stage and nothing else reads its status yet.

`state` is what the story workspace shows. **Out of date is worked out on every read** and never
stored: a check covers the shot definitions it read; once any of them is newer, the scene reads
`not_checked`. While repairs run the scene reads `reconciling` and still lists the cuts that
were found, each with its repair job.
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
# The repair of one cut (`jobs/repair_shot_cut.py`). Two presses on one cut make one job; cuts
# that share no shot run side by side. The key is `scene/boundary`.
REPAIR_JOB_TYPE: Final = shot_definitions.REPAIR_JOB_TYPE
REPAIR_DEDUPE_KEY: Final = "cut_key"

# How many of a project's newest check jobs are read to find each scene's newest one.
_JOB_LOOKBACK: Final = 500

STORY_BIBLE_KIND: Final = "story_bible"
SCENE_DEFINITION_KIND: Final = "scene_definition"
SHOT_PLAN_KIND: Final = "shot_plan"
SHOT_DEFINITION_KIND: Final = "shot_definition"

# `not_checked`: no check covers the shots as they are now (or the shots are not all defined).
# `checking`: the check is running. `reconciling`: cuts are being repaired for continuity.
# `consistent`: the newest check covers the shots and found nothing. `mismatches`: it found some.
Status = Literal["not_checked", "checking", "reconciling", "consistent", "mismatches"]


class ShotContinuityError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class ShotFlag:
    """One shot of a scene and whether a continuity repair made its newest definition."""

    shot_id: str
    # The round of the continuity check that made this shot's newest definition, when it was
    # repaired for continuity; else None. 0 is a repair the user asked for.
    redefined_round: int | None


@dataclass(frozen=True)
class CutMismatch:
    """A cut (boundary) that does not line up. A mismatch belongs to the cut, not to either
    shot, so it is shown between the two shots.
    """

    id: str
    # A shot id, `scene_start` or `scene_end`.
    before: str
    after: str
    problem: str
    # The newest repair job of this cut, when one was made after the newest check.
    job: Job | None
    # Whether Fix this cut may be pressed, and the reason when it may not.
    can_repair: bool
    blocked_reason: str | None


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
    # The cuts that do not line up, when `mismatches` or `reconciling`.
    mismatches: list[CutMismatch]
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


def _not_ready_reason(
    entry: shot_definitions.SceneEntry, check_active: bool, repair_active: bool = False
) -> str | None:
    """Why this scene cannot be checked now, or None: its shots must all be defined and current
    and nothing may be running for the scene (a check, or the repair of a cut).
    """
    if not entry.shots:
        return "The shots of this scene are not planned."
    if check_active:
        return "The continuity of this scene is being checked."
    if repair_active:
        return "The cuts of this scene are being repaired for continuity."
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


def _active_repair_round(repairs: dict[str, Job]) -> int | None:
    """The round of the repairs running for a scene (`repairs` is its newest repair job of each
    cut, by boundary id), or None when none run. A repair the user asked for is round 0 and is
    shown as round 1: the first wave it starts.
    """
    rounds = [
        _round_of_integer(job.input.get("round"))
        for job in repairs.values()
        if _is_active(job) and isinstance(job.input, dict)
    ]
    return max(1, *rounds) if rounds else None


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


async def _newest_repairs(session: AsyncSession, project_id: int) -> dict[str, dict[str, Job]]:
    """The newest repair job of each cut of the project: `{scene id: {boundary id: job}}`."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == REPAIR_JOB_TYPE)
        .order_by(Job.id.desc())
        .limit(_JOB_LOOKBACK)
        .execution_options(populate_existing=True)
    )
    newest: dict[str, dict[str, Job]] = {}
    for job in (await session.execute(statement)).scalars():
        if not isinstance(job.input, dict):
            continue
        scene_id = job.input.get("scene_id")
        boundary_id = job.input.get("boundary_id")
        if isinstance(scene_id, str) and isinstance(boundary_id, str):
            newest.setdefault(scene_id, {}).setdefault(boundary_id, job)
    return newest


def _repair_active(repairs: dict[str, Job]) -> bool:
    return any(_is_active(job) for job in repairs.values())


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


def _shot_flags(entry: shot_definitions.SceneEntry) -> list[ShotFlag]:
    flags: list[ShotFlag] = []
    for shot in entry.shots:
        continuity = _continuity_of(shot.row)
        redefined = _round_of_integer(continuity.get("round")) if continuity is not None else None
        flags.append(ShotFlag(shot.shot["id"], redefined))
    return flags


def _cut_mismatches(
    verdict: list[dict[str, Any]],
    row: ShotContinuityCheck,
    repairs: dict[str, Job],
    can_repair: bool,
    blocked_reason: str | None,
) -> list[CutMismatch]:
    """The cuts of a check that do not line up. A repair job made before the check is not
    shown: it belongs to an older verdict of the cut.
    """
    result: list[CutMismatch] = []
    for boundary in verdict:
        if boundary["matches"]:
            continue
        repair = repairs.get(boundary["id"])
        fresh = repair is not None and (row.job_id is None or repair.id > row.job_id)
        result.append(
            CutMismatch(
                id=boundary["id"],
                before=boundary["before"],
                after=boundary["after"],
                problem=boundary["problem"],
                job=repair if fresh else None,
                can_repair=can_repair,
                blocked_reason=blocked_reason,
            )
        )
    return result


def _scene_state(
    entry: shot_definitions.SceneEntry,
    row: ShotContinuityCheck | None,
    job: Job | None,
    repairs: dict[str, Job],
    max_rounds: int,
) -> SceneContinuity:
    check_active = _is_active(job)
    reconciling = _active_repair_round(repairs)
    reason = _not_ready_reason(entry, check_active, reconciling is not None)

    status: Status
    if check_active:
        status = "checking"
    elif reconciling is not None:
        status = "reconciling"
    elif reason is not None or row is None or not _covers(row, entry):
        status = "not_checked"
    else:
        status = "consistent" if row.content["mismatch_count"] == 0 else "mismatches"

    # The cuts are listed while the repairs run too: the shots are not changed until they end.
    verdict = (
        row.content["boundaries"]
        if row is not None
        and status in ("consistent", "mismatches", "reconciling")
        and _covers(row, entry)
        else None
    )
    mismatches = (
        _cut_mismatches(verdict, row, repairs, status == "mismatches", reason)
        if verdict is not None and row is not None and status in ("mismatches", "reconciling")
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
        shots=_shot_flags(entry),
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
    repairs = await _newest_repairs(session, project.id)
    max_rounds = await settings_service.get_int(
        session, settings_service.SHOT_CONTINUITY_MAX_ROUNDS_KEY
    )
    return ShotContinuityState(
        scenes_version=definitions.scenes_version,
        max_rounds=max_rounds,
        entries=[
            _scene_state(
                entry,
                rows.get(entry.item["id"]),
                jobs.get(entry.item["id"]),
                repairs.get(entry.item["id"], {}),
                max_rounds,
            )
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
    repairs = (await _newest_repairs(session, project.id)).get(scene_id, {})
    reason = _not_ready_reason(entry, False, _repair_active(repairs))
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
        reason = _not_ready_reason(
            entry,
            status_of.get(scene_id) == "checking",
            status_of.get(scene_id) == "reconciling",
        )
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
    when no check is queued. Called after every `define_shot` job and every `repair_shot_cut`
    job (a wave is checked once, after its last repair).

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
    repairs = (await _newest_repairs(session, project_id)).get(scene_id, {})
    if _not_ready_reason(entry, _is_active(job), _repair_active(repairs)) is not None:
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


# --- Repairing cuts -----------------------------------------------------------------------


def _cut_key(scene_id: str, boundary_id: str) -> str:
    return f"{scene_id}/{boundary_id}"


async def _queue_repair(
    session: AsyncSession,
    project: Project,
    entry: shot_definitions.SceneEntry,
    check: ShotContinuityCheck,
    boundary: dict[str, Any],
    round_: int,
) -> tuple[Job, bool]:
    """Queues the repair of one cut of this check and returns `(job, created)`. `created` is
    False when the cut already has a repair waiting or running, which is returned instead. The
    scene must be ready (`_not_ready_reason`) and the check must cover it. Raises
    ShotContinuityError.

    The job reads both shots of the cut with their newest specification. The shots the repair
    may not change keep their outer edge (`shot_continuity_writer.editable_and_frozen`).
    `round_` is recorded on the versions the job makes, so that the next check knows which
    round it belongs to.
    """
    scene_id = entry.item["id"]
    boundary_id = boundary["id"]
    edit = shot_continuity_writer.editable_and_frozen(boundary)
    shot_ids = shot_continuity_writer.shots_of_boundary(boundary)
    try:
        context = await shot_definitions.cut_context(session, project, scene_id, shot_ids)
    except shot_definitions.ShotDefinitionsError as exc:
        raise ShotContinuityError(str(exc)) from exc

    common = context.shots[0].fields
    continuity = {"check_id": check.id, "round": round_, "boundary_id": boundary_id}
    shots = [
        {
            "shot_id": item.shot_id,
            "shot": item.fields["shot"],
            "events": item.fields["events"],
            "speech": item.fields["speech"],
            "dialogue": item.fields["dialogue"],
            "duration": item.fields["duration"],
            # What the repair read: it is not saved over a newer version.
            "specification": item.row.content,
            "read_definition_id": item.row.id,
            "read_definition_version": item.row.version,
            # Written onto the version the job makes (D-3).
            "inputs": {**item.fields["inputs"], "continuity": continuity},
        }
        for item in context.shots
    ]
    return await store.create_job(
        session,
        project_id=project.id,
        type=REPAIR_JOB_TYPE,
        provider="llm",
        input={
            REPAIR_DEDUPE_KEY: _cut_key(scene_id, boundary_id),
            "scene_id": scene_id,
            "boundary_id": boundary_id,
            "check_id": check.id,
            "round": round_,
            # The shots a Define press must leave alone while this job runs.
            "locked_shot_ids": shot_ids,
            "story_bible_id": common["story_bible_id"],
            "story_bible_version": common["story_bible_version"],
            "shot_plan_id": common["shot_plan_id"],
            "scene": common["scene"],
            "scene_definition": common["scene_definition"],
            "scene_character_ids": common["scene_character_ids"],
            "cut": {
                "id": boundary_id,
                "before": boundary["before"],
                "after": boundary["after"],
                "before_state": boundary["before_state"],
                "after_state": boundary["after_state"],
                "problem": boundary["problem"],
                "editable_shots": edit.editable,
                "frozen": edit.frozen,
            },
            "shots": shots,
            "characters": common["characters"],
            "environment": common["environment"],
        },
        dedupe_key=REPAIR_DEDUPE_KEY,
    )


async def queue_repairs(session: AsyncSession, project_id: int, check_id: int) -> list[Job]:
    """Queues the next wave of repairs for the cuts that do not line up in this check, one job
    per cut, and commits each. Returns the jobs queued. Nothing is queued when the check found
    no mismatch, the rounds are used up (`shot_continuity_max_rounds`), a newer check exists, or
    the shots were changed since the check read them (then the check no longer describes them).

    A wave holds the cuts that share no shot (`shot_continuity_writer.wave`); the rest wait for
    the next check.
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
    repairs = (await _newest_repairs(session, project_id)).get(check.scene_id, {})
    if (
        entry is None
        or _not_ready_reason(entry, False, _repair_active(repairs)) is not None
        or not _covers(check, entry)
    ):
        return []

    jobs: list[Job] = []
    for boundary in shot_continuity_writer.wave(check.content["boundaries"]):
        try:
            job, created = await _queue_repair(
                session, project, entry, check, boundary, check.round + 1
            )
        except ShotContinuityError as exc:
            _logger.info(
                "cut %s of scene '%s' of project %d: not repaired for continuity: %s",
                boundary["id"],
                check.scene_id,
                project_id,
                exc,
            )
            continue
        if created:
            jobs.append(job)
    return jobs


async def start_cut_repair(
    session: AsyncSession, project: Project, scene_id: str, boundary_id: str
) -> Job:
    """Queues the repair of one cut that the newest check found not lining up, at round 0 (the
    user's request starts the count again, so automatic waves follow it), and commits. If the
    cut already has a repair waiting or running, that job is returned. Raises
    ShotContinuityError when the scene is not ready, the newest check does not cover the shots
    as they are now, or the cut lines up.
    """
    definitions = await shot_definitions.state(session, project)
    entry = _find_scene(definitions, scene_id)
    repairs = (await _newest_repairs(session, project.id)).get(scene_id, {})
    existing = repairs.get(boundary_id)
    if existing is not None and _is_active(existing):
        return existing
    job = (await _newest_jobs(session, project.id)).get(scene_id)
    reason = _not_ready_reason(entry, _is_active(job), _repair_active(repairs))
    if reason is not None:
        raise ShotContinuityError(reason)
    check = (await _newest_rows(session, project.id)).get(scene_id)
    if check is None or not _covers(check, entry):
        raise ShotContinuityError("Check the continuity of this scene first.")
    boundary = next(
        (item for item in check.content["boundaries"] if item["id"] == boundary_id), None
    )
    if boundary is None:
        raise ShotContinuityError(f"There is no cut '{boundary_id}' in the newest check.")
    if boundary["matches"]:
        raise ShotContinuityError("This cut lines up already.")
    repair, _created = await _queue_repair(session, project, entry, check, boundary, 0)
    return repair


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
