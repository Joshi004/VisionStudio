"""The pipeline board: where every step of the story pipeline stands, in one read.

The answer has one row per step of `story_pipeline.STEPS`, made from what the run itself
looks at: each step's adapter `evaluate()` (`story_pipeline_targets.py`), which says for each
target (a character, a scene, a shot, or the project) whether it is done, has work going on,
is out of date, failed or cannot go on. Nothing is stored and nothing is written.

It is meant to be read in a GET request, where each stage's `state()` is computed once
(`db/state_memo.py`). Without that, evaluating all steps would compute the same stage hundreds
of times.

One status per step, the first rule that fits (`step_status`):

1. `off`: the step is switched off for the project (the music steps with music off).
2. `running`: a target has work going on (a job queued or running, or its follow-on work is
   about to show up).
3. `attention`: a target failed and nothing is going on for it.
4. `out_of_date`: a target's output exists and is out of date.
5. `done`: every target is done. A step with no targets is done only once the steps it needs are.
6. `waiting`: a step it needs is not done.
7. `attention`: a target cannot go on, and says why.
8. `ready`: it can be started by hand now.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project
from app.jobs import store
from app.services import activity as activity_service
from app.services import story_pipeline as pipeline
from app.services.story_pipeline import STEP_KEYS, STEPS, RunOptions, Target
from app.services.story_pipeline_targets import ADAPTERS

_logger = logging.getLogger(__name__)

BoardStatus = Literal["off", "running", "attention", "out_of_date", "done", "waiting", "ready"]
BoardMode = Literal[
    "pipeline_review", "pipeline_paused", "pipeline_running", "manual_running", "idle"
]

# The steps that are switched off when the project's music is off (MD-21).
MUSIC_STEPS: Final = frozenset(
    {
        "music_bible",
        "music_themes",
        "music_plan",
        "music_cues",
        "music_generation",
        "music_placement",
    }
)

# The group each step is shown in.
GROUPS: Final[dict[str, str]] = {
    "story_bible": "story",
    "character_discovery": "story",
    "environment_discovery": "story",
    "scene_discovery": "story",
    "links": "story",
    "relations": "characters",
    "character_definitions": "characters",
    "character_images": "characters",
    "voices": "characters",
    "environment_definitions": "environments",
    "environment_views": "environments",
    "scene_definitions": "scenes",
    "events": "scenes",
    "resolution": "scenes",
    "scene_staging": "scenes",
    "look_state_images": "scenes",
    "speech_units": "speech",
    "speech_synthesis": "speech",
    "music_bible": "music",
    "music_themes": "music",
    "music_plan": "music",
    "music_cues": "music",
    "music_generation": "music",
    "music_placement": "music",
    "shot_plans": "shots",
    "shot_definitions": "shots",
    "shot_continuity": "shots",
    "references": "shots",
    "generation_requests": "shots",
    "prompts": "shots",
    "shot_generation": "shots",
    "render": "render",
}

_REASON_MAX_CHARS: Final = 300
_UNREADABLE: Final = "Could not read this step. See the backend log."


def _check_groups() -> None:
    """Every step has a group, and no group names a step that does not exist."""
    missing = [key for key in STEP_KEYS if key not in GROUPS]
    unknown = [key for key in GROUPS if key not in STEP_KEYS]
    if missing or unknown:
        raise ValueError(f"pipeline_board: steps without a group {missing}, unknown {unknown}")
    if not MUSIC_STEPS <= set(STEP_KEYS):
        raise ValueError("pipeline_board: MUSIC_STEPS names a step that does not exist")


_check_groups()


@dataclass(frozen=True)
class StepCounts:
    """What a step's targets say, counted."""

    total: int = 0
    done: int = 0
    # Targets with work going on, or about to get some.
    active: int = 0
    # Targets whose output exists and is out of date.
    stale: int = 0
    # Targets that are not done, have nothing going on, and whose newest job failed.
    failed: int = 0
    # Targets that are not done, have nothing going on, and cannot go on.
    blocked: int = 0
    # Why the first such target failed or cannot go on.
    reason: str | None = None


@dataclass(frozen=True)
class BoardStep:
    key: str
    label: str
    group: str
    needs: tuple[str, ...]
    status: BoardStatus
    counts: StepCounts
    # The steps it needs that are not done (and not off).
    blocked_by: tuple[str, ...]


@dataclass(frozen=True)
class BoardRun:
    """The project's newest run of the pipeline, whatever its status."""

    job_id: int
    status: str
    phase: str | None
    paused_at: str | None
    review_at: str | None


@dataclass(frozen=True)
class Board:
    revision: str
    mode: BoardMode
    run: BoardRun | None
    queued: int
    running: int
    paused: int
    # The steps that are ready to be started by hand, in the order of the pipeline.
    next_keys: tuple[str, ...]
    steps: list[BoardStep]


def _short(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= _REASON_MAX_CHARS:
        return one_line
    return f"{one_line[: _REASON_MAX_CHARS - 1]}…"


def count_targets(targets: list[Target]) -> StepCounts:
    """Counts a step's targets. Pure."""
    active = stale = failed = blocked = done = 0
    reason: str | None = None
    for target in targets:
        done += target.done
        stale += target.stale
        if target.done:
            continue
        if target.active or target.settling:
            active += 1
        elif target.block is not None:
            blocked += 1
            reason = reason or _short(target.block)
        elif target.last_error is not None:
            failed += 1
            reason = reason or _short(target.last_error)
    return StepCounts(
        total=len(targets),
        done=done,
        active=active,
        stale=stale,
        failed=failed,
        blocked=blocked,
        reason=reason,
    )


def step_status(counts: StepCounts, needs_done: bool, off: bool) -> BoardStatus:
    """The one status of a step. Pure. `needs_done`: every step it needs is done (or off)."""
    if off:
        return "off"
    if counts.active:
        return "running"
    if counts.failed:
        return "attention"
    if counts.stale:
        return "out_of_date"
    if counts.done == counts.total and (counts.total > 0 or needs_done):
        return "done"
    if not needs_done:
        return "waiting"
    if counts.blocked:
        return "attention"
    return "ready"


def _mode_of(run: Job | None, run_output: dict[str, Any], busy: bool) -> BoardMode:
    if run is not None and run.status in store.ACTIVE_STATUSES:
        if run_output["review_at"] is not None:
            return "pipeline_review"
        if run_output["paused_at"] is not None:
            return "pipeline_paused"
        return "pipeline_running"
    return "manual_running" if busy else "idle"


async def _read_step(
    session: AsyncSession, project: Project, step: pipeline.Step
) -> StepCounts | None:
    """The counts of one step, or None when its stage could not be read. One broken stage must
    not take the whole board down.
    """
    try:
        view = await ADAPTERS[step.key].evaluate(session, project, RunOptions())
    except Exception:
        _logger.exception("pipeline board: step '%s' could not be read", step.key)
        return None
    return count_targets(view.targets)


async def build(session: AsyncSession, project: Project) -> Board:
    """Where every step stands. Read-only."""
    # The revision is read first: a change while the board is being made gives the next poll
    # a new revision, so nothing is missed.
    activity = await activity_service.snapshot(session, project.id)
    music_off = not project.music_enabled

    statuses: dict[str, BoardStatus] = {}
    steps: list[BoardStep] = []
    for step in STEPS:  # the order of STEPS puts every step after the steps it needs
        off = music_off and step.key in MUSIC_STEPS
        needs_done = all(statuses[key] in ("done", "off") for key in step.needs)
        counts: StepCounts | None = (
            StepCounts() if off else await _read_step(session, project, step)
        )
        if counts is None:
            status: BoardStatus = "attention"
            counts = StepCounts(reason=_UNREADABLE)
        else:
            status = step_status(counts, needs_done, off)
        statuses[step.key] = status
        steps.append(
            BoardStep(
                key=step.key,
                label=step.label,
                group=GROUPS[step.key],
                needs=step.needs,
                status=status,
                counts=counts,
                blocked_by=tuple(key for key in step.needs if statuses[key] not in ("done", "off")),
            )
        )

    run = await store.latest_job(session, project.id, pipeline.JOB_TYPE)
    run_output = pipeline.read_output(run.output) if run is not None else pipeline.new_output()
    active = run is not None and run.status in store.ACTIVE_STATUSES
    return Board(
        revision=activity.revision,
        mode=_mode_of(run, run_output, activity.queued + activity.running + activity.paused > 0),
        run=(
            BoardRun(
                job_id=run.id,
                status=run.status,
                phase=run.phase,
                # A run that has ended is not waiting for anybody.
                paused_at=run_output["paused_at"] if active else None,
                review_at=run_output["review_at"] if active else None,
            )
            if run is not None
            else None
        ),
        queued=activity.queued,
        running=activity.running,
        paused=activity.paused,
        next_keys=tuple(step.key for step in steps if step.status == "ready"),
        steps=steps,
    )
