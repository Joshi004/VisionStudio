"""The story pipeline (PHASE-030): the rules of one run that takes a story from its text to a
rendered video with one click.

A run is one `story_pipeline` job (`jobs/story_pipeline.py`). It makes the same jobs the stage
buttons make, in the order of `STEPS`, and skips everything that is up to date. This module holds
what does not touch a stage: the steps and their order, the planning rules (pure), the run's
stored state, and starting, continuing and stopping a run. What "up to date" means for each step
lives in `services/story_pipeline_targets.py`.

- **Steps.** A step is a whole stage ("Define the characters"). It starts when the steps it
  `needs` are complete. A step is complete when every one of its targets (a character, a scene, a
  shot, or the project) is done.
- **Tries.** A target gets at most `MAX_TRIES` jobs per step in one run, paid language model
  calls included: the page says so before the run starts. When no target can go on, the run stops
  and says what is wrong.
- **Pauses.** At the start the user ticks the steps to pause after (none by default). The run
  pauses once a ticked step is complete, only if the run made jobs in it, and goes on when the
  user presses Continue.
- **Scope (PHASE-040).** A run is of scope `all` (everything that is not up to date, including
  what was never made) or `out_of_date` (only what exists and is out of date, plus what those
  regenerations make necessary; anything else is "left alone"). See `plan_step`.
- **Overwrites.** Some targets hold what the user chose or wrote (a library character, a
  hand-written relation, a hand-picked narrator voice). The run replaces them only when the user
  allowed it once at the start (`confirm_overwrite`).

The run's state lives in `job.output` (see `new_output`); there is no table of its own.
"""

from __future__ import annotations

import copy
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project
from app.jobs import phases, store
from app.services import review_points as review_rules

JOB_TYPE: Final = store.PIPELINE_RUN_TYPE
# What a run makes: everything that is not up to date, or only what exists and is out of date
# (and what that makes necessary).
Scope = Literal["all", "out_of_date"]
SCOPES: Final[tuple[Scope, ...]] = ("all", "out_of_date")
SCOPE_ALL: Final[Scope] = "all"
SCOPE_OUT_OF_DATE: Final[Scope] = "out_of_date"
# Jobs one target may be given in one step in one run.
MAX_TRIES: Final = 3
# Saved in `job.provider_job_id` so the dispatcher asks the run `poll` at every tick. It is not
# an id on any server.
MARKER: Final = "pipeline"

_ERROR_MAX_CHARS: Final = 300
_MAX_PROBLEMS_SHOWN: Final = 10
# The project as a whole is the one target of a step that has no list of targets.
PROJECT_KEY: Final = "project"


class StoryPipelineError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- The steps ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    # The steps that must be complete before this one starts.
    needs: tuple[str, ...] = ()
    # True when the step does its work in the run itself and makes no job, so the steps after it
    # can be looked at in the same poll.
    inline: bool = False


# The order is a valid order to look at the steps in: each comes after the steps it needs.
STEPS: Final[tuple[Step, ...]] = (
    Step("story_bible", "Story Bible"),
    Step("character_discovery", "Find the characters", ("story_bible",)),
    Step("environment_discovery", "Find the environments", ("story_bible",)),
    Step("scene_discovery", "Find the scenes", ("story_bible",)),
    Step(
        "links",
        "Link to the libraries",
        ("character_discovery", "environment_discovery"),
        inline=True,
    ),
    Step("relations", "Character relations", ("character_discovery",)),
    Step("character_definitions", "Define the characters", ("links", "relations")),
    Step(
        "environment_definitions",
        "Define the environments and draw their pictures",
        ("links", "scene_discovery"),
    ),
    Step("character_images", "Draw the characters", ("character_definitions",)),
    Step("voices", "Voices and narrator", ("character_definitions",)),
    Step(
        "scene_definitions",
        "Define the scenes",
        ("character_definitions", "environment_definitions"),
    ),
    Step("events", "Extract the events", ("scene_definitions",)),
    # MUSIC-006: the story's musical identity. Skipped as complete when the project's music is
    # switched off.
    Step("music_bible", "Write the Music Bible", ("events",)),
    # MUSIC-007: a recording of each theme, and its emotional versions. Also skipped as complete
    # when music is switched off.
    Step("music_themes", "Record the themes", ("music_bible",)),
    Step("resolution", "Resolve looks and states", ("scene_definitions",)),
    Step(
        "scene_staging",
        "Stage the scenes",
        ("scene_definitions", "events", "environment_definitions"),
    ),
    Step(
        "environment_views",
        "Plan and draw the views of each place",
        ("scene_staging",),
    ),
    Step(
        "look_state_images",
        "Draw the looks and states",
        ("resolution", "character_images", "environment_definitions", "environment_views"),
    ),
    Step("speech_units", "Plan the speech", ("events",), inline=True),
    Step("speech_synthesis", "Speak the lines", ("speech_units", "voices")),
    Step("shot_plans", "Plan the shots", ("speech_synthesis", "scene_staging")),
    # MUSIC-008: where score, ambience, hits and silence go. It needs every scene's timeline and
    # runs beside the shot definitions (QM-16, option b). Skipped as complete when music is off.
    Step("music_plan", "Plan the music", ("shot_plans", "music_bible")),
    Step(
        "shot_definitions",
        "Define the shots",
        ("shot_plans", "resolution", "environment_views"),
    ),
    # MUSIC-009: the exact detail of each cue and its prompts, then an audit of all prompts. A cue
    # may send the plan back once (a revision target in this step). Skipped when music is off.
    Step(
        "music_cues",
        "Detail the music cues",
        ("music_plan", "music_themes", "shot_definitions"),
    ),
    Step("shot_continuity", "Check shot continuity", ("shot_definitions",)),
    Step(
        "references",
        "Choose the references",
        ("shot_continuity", "look_state_images"),
    ),
    Step("generation_requests", "Plan the generation requests", ("references",), inline=True),
    Step("prompts", "Compile the shot prompts", ("generation_requests",)),
    Step("shot_generation", "Generate the clips", ("prompts",)),
    Step("render", "Render the video", ("shot_generation",)),
)

STEP_KEYS: Final = tuple(step.key for step in STEPS)
STEP_LABELS: Final = {step.key: step.label for step in STEPS}


def _check_graph() -> None:
    """Every step comes after the steps it needs: the order of `STEPS` is then a valid order to
    look at them in, and the graph has no cycle.
    """
    seen: set[str] = set()
    for step in STEPS:
        if step.key in seen:
            raise ValueError(f"step {step.key} is listed twice")
        unknown = [key for key in step.needs if key not in seen]
        if unknown:
            raise ValueError(f"step {step.key} needs {unknown}, not before it")
        seen.add(step.key)


_check_graph()


def _check_review_points() -> None:
    """Every step a review point names exists, and no step is in two review points."""
    seen: set[str] = set()
    for point in review_rules.REVIEW_POINTS:
        for key in point.steps:
            if key not in STEP_KEYS:
                raise ValueError(f"review point {point.key} names the unknown step {key}")
            if key in seen:
                raise ValueError(f"step {key} is in two review points")
            seen.add(key)


_check_review_points()


# --- What the user chose when starting ------------------------------------------------------


@dataclass(frozen=True)
class RunOptions:
    """The choices made once, at the start of a run."""

    # The keys of the steps to pause after.
    pause_after: frozenset[str] = frozenset()
    # Whether the run may replace what the user chose or wrote.
    confirm_overwrite: bool = False
    # What the run makes (PHASE-040).
    scope: Scope = SCOPE_ALL
    # The keys of the project's review points that the run stops at (PHASE-041). Copied from the
    # project when the run starts, so changing the settings does not change a run that is going.
    review_points: frozenset[str] = frozenset()

    @classmethod
    def from_input(cls, value: object) -> RunOptions:
        data: dict[str, Any] = value if isinstance(value, dict) else {}
        keys = data.get("pause_after")
        points = data.get("review_points")
        return cls(
            pause_after=frozenset(
                key for key in (keys if isinstance(keys, list) else []) if key in STEP_KEYS
            ),
            confirm_overwrite=data.get("confirm_overwrite") is True,
            scope=SCOPE_OUT_OF_DATE if data.get("scope") == SCOPE_OUT_OF_DATE else SCOPE_ALL,
            review_points=frozenset(
                review_rules.normalize(points if isinstance(points, list) else [])
            ),
        )


# --- Targets and plans ----------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """One thing a step must get done: a character, a scene, a shot, or the project."""

    key: str
    # What a problem names ("Mira", "Scene 2: The cellar"). Empty for the project.
    label: str
    done: bool
    # A job (or look, or picture) of this step is queued or running for it, whoever started it.
    active: bool = False
    # Why nothing can be made for it now. Another try would not help.
    block: str | None = None
    # The stage's own follow-on work for it has not shown up yet (a re-plan, the repairs of a
    # check). The run waits a little instead of reporting it.
    settling: bool = False
    # What the user must allow before it is replaced. None when nothing needs allowing.
    consent: str | None = None
    # Why its newest job failed, for the message when its tries are used up.
    last_error: str | None = None
    # Targets of the same step that must be done first (a character drawn from another one).
    waits_for: tuple[str, ...] = ()
    # What the start function of the stage needs to find it (a scene id, a shot id).
    ref: tuple[str, ...] = ()
    # An output of this target exists and its stage says it is out of date (PHASE-040). Only the
    # `out_of_date` scope reads it.
    stale: bool = False
    # The targets that belong together (the scene of a shot or a line). None: the whole step.
    group: str | None = None
    # The stage already has something for this target that is not usable (a shot whose clips
    # all failed). It is not a missing target, so the `out_of_date` scope does not add it.
    existing: bool = False
    # The user rejected this target at a review point (PHASE-041): it is done, and is made
    # again. Set by `plan_step`, never by an adapter. The stage's start function is then given
    # consent to replace it, because rejecting it is what asks for that.
    redo: bool = False


@dataclass(frozen=True)
class StepView:
    """Where one step stands, read from its stage."""

    targets: list[Target]
    # Things to tell the user that are not problems.
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Started:
    """What starting one target did: the jobs it made (none for work done inline) or why it
    could not.
    """

    target: Target
    job_ids: tuple[int, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class Problem:
    step_key: str
    target_key: str
    label: str
    tries: int
    message: str

    def text(self) -> str:
        message = self.message if self.message.endswith((".", "!", "?")) else f"{self.message}."
        return f"{self.label}: {message}" if self.label and self.label not in message else message

    def as_json(self) -> dict[str, Any]:
        return {
            "step": self.step_key,
            "target": self.target_key,
            "label": self.label,
            "tries": self.tries,
            "message": self.message,
        }


@dataclass(frozen=True)
class StepPlan:
    done: int
    total: int
    # Targets with work in progress (or about to settle).
    waiting: int
    creates: list[Target]
    problems: list[Problem]
    warnings: list[str] = field(default_factory=list)
    # Targets the `out_of_date` scope leaves as they are. They are not in `done` or `total`.
    left_alone: int = 0

    @property
    def complete(self) -> bool:
        return self.done == self.total


def _short(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= _ERROR_MAX_CHARS:
        return one_line
    return f"{one_line[: _ERROR_MAX_CHARS - 1]}…"


def exhausted_message(tries: int, last_error: str | None) -> str:
    """Why a target that was tried `MAX_TRIES` times is reported."""
    reason = _short(last_error) if last_error else "it finished, but the result is still missing"
    return f"Tried {tries} times without success. The last try: {reason}"


def consent_message(consent: str) -> str:
    return (
        f"{consent} Tick “Allow overwrite” when you start the pipeline, and run it again. "
        "Until then this is left as it is."
    )


def in_scope(
    target: Target, options: RunOptions, made_upstream: bool, groups: set[str | None]
) -> bool:
    """Whether the run looks at a target that is not done. Pure.

    Scope `all`: always. Scope `out_of_date`: a target whose output is out of date, one that is
    being worked on, or one that was never made but that the run's own work upstream makes
    necessary (`made_upstream`) in a group that already has an output (a new shot of a scene
    that was planned again). Everything else is left alone.
    """
    if options.scope == SCOPE_ALL:
        return True
    if target.stale or target.active or target.settling or target.redo:
        return True
    return made_upstream and not target.existing and target.group in groups


def plan_step(
    step: Step,
    view: StepView,
    tries: Mapping[str, int],
    errors: Mapping[str, str],
    options: RunOptions,
    made_upstream: bool = False,
    rejected: Collection[str] = (),
) -> StepPlan:
    """What to do now about a step. Pure.

    For each target that is not done, in this order: leave it alone when the scope says so; wait
    when work is in progress for it; wait when a target it waits for is not done yet; wait while
    the stage's own follow-on work settles; report it when it needs consent that was not given,
    when nothing can be made for it, or when it has had `MAX_TRIES`; otherwise create the next
    job.

    `made_upstream` is whether the run has made work in a step this one needs (scope
    `out_of_date` only).

    `rejected` holds the keys of the targets the user rejected at a review point (PHASE-041).
    Such a target is not done until it has been made again: while nothing was started for it
    (`tries` is 0), while work is in progress for it, and while its newest job failed.
    """
    pending: list[Target] = []
    for target in view.targets:
        if not target.done:
            pending.append(target)
        elif target.key in rejected and (
            target.active or not tries.get(target.key, 0) or target.last_error is not None
        ):
            pending.append(replace(target, done=False, redo=True))
    # The groups that already have an output (a done or an out-of-date target, or one that is
    # being worked on): what "the same scene already has shots" is judged by.
    groups = {
        target.group for target in view.targets if target.done or target.stale or target.active
    }
    left_alone = [
        target for target in pending if not in_scope(target, options, made_upstream, groups)
    ]
    left_keys = {target.key for target in left_alone}
    pending = [target for target in pending if target.key not in left_keys]
    pending_keys = {target.key for target in pending}
    waiting = 0
    creates: list[Target] = []
    problems: list[Problem] = []
    progressing: set[str] = set()
    following: list[Target] = []

    for target in pending:
        tried = tries.get(target.key, 0)
        if target.active:
            waiting += 1
            progressing.add(target.key)
        elif any(key in pending_keys for key in target.waits_for):
            following.append(target)
        elif target.settling:
            waiting += 1
            progressing.add(target.key)
        elif target.block is not None:
            problems.append(Problem(step.key, target.key, target.label, tried, target.block))
        elif target.consent is not None and not options.confirm_overwrite:
            problems.append(
                Problem(step.key, target.key, target.label, tried, consent_message(target.consent))
            )
        elif tried >= MAX_TRIES:
            message = exhausted_message(tried, errors.get(target.key) or target.last_error)
            problems.append(Problem(step.key, target.key, target.label, tried, message))
        else:
            creates.append(target)
            progressing.add(target.key)

    # A target that waits is decided last: the one it waits for may itself be waiting.
    for target in following:
        blockers = [key for key in target.waits_for if key in pending_keys]
        if all(key in progressing for key in blockers):
            waiting += 1
            progressing.add(target.key)
        # Otherwise the one it waits for is reported, and counting this one as going on would
        # keep the run alive for ever.

    pending_count = len(view.targets) - len(left_alone)
    return StepPlan(
        done=pending_count - len(pending),
        total=pending_count,
        waiting=waiting,
        creates=creates,
        problems=problems,
        warnings=list(view.warnings),
        left_alone=len(left_alone),
    )


def failure_message(done: int, total: int, problems: Sequence[Problem]) -> str:
    """What a stopped run says: how far it got, and what is wrong, step by step."""
    shown = problems[:_MAX_PROBLEMS_SHOWN]
    by_step: dict[str, list[str]] = {}
    for problem in shown:
        by_step.setdefault(problem.step_key, []).append(problem.text())
    parts = " ".join(
        f"{STEP_LABELS.get(key, key)}: {' '.join(texts)}" for key, texts in by_step.items()
    )
    more = len(problems) - len(shown)
    tail = f" And {more} more." if more > 0 else ""
    return f"Stopped with {done} of {total} steps done. {parts}{tail}"


def idle_message(done: int, total: int, incomplete: Sequence[Step]) -> str:
    """What a run says when nothing is running, nothing can be started and nothing is reported,
    yet it is not finished. It should not happen: it is a way out, so a run never hangs.
    """
    labels = ", ".join(step.label.lower() for step in incomplete)
    return (
        f"Stopped with {done} of {total} steps done: nothing is running and nothing can be "
        f"started, but these steps are not complete: {labels}. Run the pipeline again to try "
        "them."
    )


# --- The run's stored state -----------------------------------------------------------------

StepStatus = Literal["pending", "running", "done", "skipped", "failed"]
COMPLETE_STATUSES: Final = ("done", "skipped")


def new_output() -> dict[str, Any]:
    """The output of a run that has just started: every step waiting, nothing made yet."""
    return {
        "steps": {
            step.key: {"status": "pending", "done": 0, "total": 0, "left_alone": 0}
            for step in STEPS
        },
        # step key -> target key -> how many jobs this run has given the target.
        "tries": {step.key: {} for step in STEPS},
        # step key -> target key -> why the newest try failed.
        "errors": {step.key: {} for step in STEPS},
        # The id of every job this run made (the stages that make no job add none).
        "job_ids": [],
        "problems": [],
        "warnings": [],
        # The step the run is paused after, or None.
        "paused_at": None,
        # The steps the user has already pressed Continue after.
        "continued": [],
        # The review point the run waits at (PHASE-041), or None.
        "review_at": None,
        # The review points the user has already passed (approved, or nothing was made in them).
        "reviewed": [],
        # step key -> the targets the user rejected, to be made again.
        "rejected": {},
        # True after Continue: the next look reads the steps that were complete again, so what
        # was edited during the pause is seen.
        "recheck": False,
    }


def read_output(value: object) -> dict[str, Any]:
    """A copy of a run's stored output that is safe to change (the stored JSON is replaced by a
    new object, never changed in place). Anything that is not a run's output starts afresh.
    """
    if not isinstance(value, dict) or not isinstance(value.get("steps"), dict):
        return new_output()
    output: dict[str, Any] = copy.deepcopy(value)
    fresh = new_output()
    for key in STEP_KEYS:
        if not isinstance(output["steps"].get(key), dict):
            output["steps"][key] = fresh["steps"][key]
    for name in ("tries", "errors"):
        if not isinstance(output.get(name), dict):
            output[name] = fresh[name]
        for key in STEP_KEYS:
            if not isinstance(output[name].get(key), dict):
                output[name][key] = {}
    for name in ("job_ids", "problems", "warnings", "continued", "reviewed"):
        if not isinstance(output.get(name), list):
            output[name] = []
    for name in ("paused_at", "review_at"):
        if not isinstance(output.get(name), str):
            output[name] = None
    rejected = output.get("rejected")
    output["rejected"] = (
        {
            key: [target for target in targets if isinstance(target, str)]
            for key, targets in rejected.items()
            if key in STEP_KEYS and isinstance(targets, list)
        }
        if isinstance(rejected, dict)
        else {}
    )
    output["recheck"] = output.get("recheck") is True
    return output


def complete_keys(output: Mapping[str, Any]) -> set[str]:
    """The steps the run has passed: complete, or complete when it got to them."""
    return {key for key in STEP_KEYS if output["steps"][key].get("status") in COMPLETE_STATUSES}


def record_progress(
    output: dict[str, Any], step_key: str, plan: StepPlan, *, status: StepStatus
) -> None:
    entry = output["steps"][step_key]
    entry["status"] = status
    entry["done"] = plan.done
    entry["total"] = plan.total
    entry["left_alone"] = plan.left_alone


def made_no_jobs(output: Mapping[str, Any], step_key: str) -> bool:
    """Whether the run has started nothing in a step (so a completed step was already complete)."""
    return not output["tries"][step_key]


def record_try(output: dict[str, Any], step_key: str, target_key: str, started: Started) -> None:
    """Counts one try for a target, with the jobs it made and why it failed, if it did."""
    counts = output["tries"][step_key]
    counts[target_key] = int(counts.get(target_key, 0)) + 1
    output["job_ids"].extend(started.job_ids)
    if started.error is not None:
        output["errors"][step_key][target_key] = _short(started.error)
    else:
        output["errors"][step_key].pop(target_key, None)


def add_warnings(output: dict[str, Any], warnings: Sequence[str]) -> None:
    for text in warnings:
        if text not in output["warnings"]:
            output["warnings"].append(text)


def phase_of(
    output: Mapping[str, Any],
    running: Sequence[tuple[str, int, int]],
    scope: Scope = SCOPE_ALL,
) -> str:
    """The phase label of the run: how many steps are complete and what is going on."""
    text = phases.pipeline_progress(len(complete_keys(output)), len(STEPS), running)
    return f"Regenerating what is out of date: {text}" if scope == SCOPE_OUT_OF_DATE else text


# --- Starting, continuing and stopping a run ------------------------------------------------


async def active_jobs(session: AsyncSession, project_id: int) -> list[Job]:
    """The project's jobs that are waiting or running, whatever they are."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.status.in_(store.ACTIVE_STATUSES))
        .order_by(Job.id)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars().all())


async def active_run(session: AsyncSession, project_id: int) -> Job | None:
    """The project's run that is waiting or running, or None."""
    job = await store.latest_job(session, project_id, JOB_TYPE)
    return job if job is not None and job.status in store.ACTIVE_STATUSES else None


def start_block(project: Project, active: Sequence[Job]) -> str | None:
    """Why a run cannot start now, or None. Pure. A run waits for no other job: two kinds of
    work on one project at once could replace each other's results.
    """
    if project.script_text is None or not project.script_text.strip():
        return "Save the story first: the pipeline starts from it."
    if active:
        many = len(active) > 1
        return (
            f"{len(active)} {'jobs are' if many else 'job is'} waiting or running for this "
            f"project. Wait for {'them' if many else 'it'} to finish, or cancel "
            f"{'them' if many else 'it'}, before running the whole pipeline."
        )
    return None


async def start_run(
    session: AsyncSession,
    project: Project,
    *,
    pause_after: Sequence[str],
    confirm_overwrite: bool,
    scope: Scope = SCOPE_ALL,
) -> tuple[Job, bool]:
    """Queues a run, and commits. Returns `(job, created)`: a run that is already waiting or
    running is returned as it is (`created` False), with the choices it was started with.
    Raises StoryPipelineError for an unknown step or when a run cannot start now.

    Whether the user has allowed the overwrites is decided by the caller (`confirmations`).
    """
    if scope not in SCOPES:
        raise StoryPipelineError(f"There is no scope {scope!r}.")
    unknown = [key for key in pause_after if key not in STEP_KEYS]
    if unknown:
        raise StoryPipelineError(f"There is no step {', '.join(repr(key) for key in unknown)}.")
    existing = await active_run(session, project.id)
    if existing is not None:
        return existing, False
    blocked = start_block(project, await active_jobs(session, project.id))
    if blocked is not None:
        raise StoryPipelineError(blocked)
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input={
            "requested": JOB_TYPE,
            # In the order of the steps, without repeats.
            "pause_after": [key for key in STEP_KEYS if key in set(pause_after)],
            "confirm_overwrite": confirm_overwrite,
            "scope": scope,
            # The project's review points as they are now (PHASE-041).
            "review_points": review_rules.normalize(
                project.review_points if isinstance(project.review_points, list) else []
            ),
        },
    )
    return job, created


async def continue_run(
    session: AsyncSession,
    project: Project,
    rejected: Mapping[str, Sequence[str]] | None = None,
) -> Job:
    """Lets a paused run go on, and commits. Raises StoryPipelineError when the project has no
    run, or its run is not paused.

    `rejected` (PHASE-041) maps a step key to the targets the user rejected at a review point.
    Only a run waiting at a review point takes it, and only for the steps of that point; whether
    each target exists is checked by the caller. A rejected target gets its tries back and is
    made again, and the run waits at the same review point once more. With nothing rejected the
    review point counts as passed.

    Every Continue makes the run read the steps that were complete again, so what the user
    edited while it waited is seen.
    """
    run = await active_run(session, project.id)
    if run is None:
        raise StoryPipelineError("There is no run going on for this project.")
    output = read_output(run.output)
    paused = output["paused_at"]
    review = output["review_at"]
    if paused is None and review is None:
        raise StoryPipelineError("The run is not paused.")
    wanted = {step: list(dict.fromkeys(keys)) for step, keys in (rejected or {}).items() if keys}
    if wanted and review is None:
        raise StoryPipelineError("The run is paused, not at a review point: nothing to reject.")
    if paused is not None:
        if paused not in output["continued"]:
            output["continued"].append(paused)
        output["paused_at"] = None
    if review is not None:
        _leave_review(output, review, wanted)
        output["review_at"] = None
    output["recheck"] = True
    if not await store.save_progress(
        session,
        run.id,
        phase=phase_of(output, [], RunOptions.from_input(run.input).scope),
        output=output,
    ):
        await session.rollback()
        raise StoryPipelineError("The run is no longer going.")
    await session.commit()
    return run


def _leave_review(output: dict[str, Any], review: str, rejected: Mapping[str, list[str]]) -> None:
    """Records the user's answer at a review point in the run's output (changes it in place)."""
    point = review_rules.POINTS_BY_KEY.get(review)
    steps = point.steps if point is not None else ()
    foreign = [step for step in rejected if step not in steps]
    if foreign:
        raise StoryPipelineError(
            f"The step {foreign[0]!r} is not part of this review point, so nothing in it can be "
            "rejected."
        )
    if not rejected:
        if review not in output["reviewed"]:
            output["reviewed"].append(review)
        return
    # The point stays unreviewed: the run waits here again once the targets are made again.
    for step, keys in rejected.items():
        known = output["rejected"].setdefault(step, [])
        known.extend(key for key in keys if key not in known)
        for key in keys:
            output["tries"][step].pop(key, None)
            output["errors"][step].pop(key, None)
        output["steps"][step]["status"] = "running"


async def cancel_queued_children(session: AsyncSession, run: Job) -> int:
    """Cancels the jobs that have not started, so a stopped run leaves no paid work waiting: the
    jobs the run made, and the jobs of the project made after the run began (the stages queue
    follow-on jobs of their own). A job that is already running finishes on its own. Commits.
    Returns how many were cancelled.
    """
    wanted = {
        job_id
        for job_id in read_output(run.output)["job_ids"]
        if isinstance(job_id, int) and not isinstance(job_id, bool)
    }
    if run.project_id is not None:
        statement = select(Job.id).where(
            Job.project_id == run.project_id, Job.status == "queued", Job.id > run.id
        )
        wanted.update((await session.execute(statement)).scalars().all())
    cancelled = 0
    for job_id in sorted(wanted):
        child = await store.get_job(session, job_id)
        if child is None or child.status != "queued" or child.project_id != run.project_id:
            continue
        try:
            await store.cancel_job(session, job_id)
            cancelled += 1
        except store.JobActionError:
            continue  # it started in the meantime
    await session.commit()
    return cancelled
