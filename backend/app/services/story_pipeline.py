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
- **Overwrites.** Some targets hold what the user chose or wrote (a library character, a
  hand-written relation, a hand-picked narrator voice). The run replaces them only when the user
  allowed it once at the start (`confirm_overwrite`).

The run's state lives in `job.output` (see `new_output`); there is no table of its own.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project
from app.jobs import phases, store

JOB_TYPE: Final = store.PIPELINE_RUN_TYPE
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
    Step("resolution", "Resolve looks and states", ("scene_definitions",)),
    Step(
        "look_state_images",
        "Draw the looks and states",
        ("resolution", "character_images", "environment_definitions"),
    ),
    Step("speech_units", "Plan the speech", ("events",), inline=True),
    Step("speech_synthesis", "Speak the lines", ("speech_units", "voices")),
    Step("shot_plans", "Plan the shots", ("speech_synthesis",)),
    Step("shot_definitions", "Define the shots", ("shot_plans", "resolution")),
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


# --- What the user chose when starting ------------------------------------------------------


@dataclass(frozen=True)
class RunOptions:
    """The choices made once, at the start of a run."""

    # The keys of the steps to pause after.
    pause_after: frozenset[str] = frozenset()
    # Whether the run may replace what the user chose or wrote.
    confirm_overwrite: bool = False

    @classmethod
    def from_input(cls, value: object) -> RunOptions:
        data: dict[str, Any] = value if isinstance(value, dict) else {}
        keys = data.get("pause_after")
        return cls(
            pause_after=frozenset(
                key for key in (keys if isinstance(keys, list) else []) if key in STEP_KEYS
            ),
            confirm_overwrite=data.get("confirm_overwrite") is True,
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


def plan_step(
    step: Step,
    view: StepView,
    tries: Mapping[str, int],
    errors: Mapping[str, str],
    options: RunOptions,
) -> StepPlan:
    """What to do now about a step. Pure.

    For each target that is not done, in this order: wait when work is in progress for it; wait
    when a target it waits for is not done yet; wait while the stage's own follow-on work settles;
    report it when it needs consent that was not given, when nothing can be made for it, or when
    it has had `MAX_TRIES`; otherwise create the next job.
    """
    pending = [target for target in view.targets if not target.done]
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

    return StepPlan(
        done=len(view.targets) - len(pending),
        total=len(view.targets),
        waiting=waiting,
        creates=creates,
        problems=problems,
        warnings=list(view.warnings),
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
        "steps": {step.key: {"status": "pending", "done": 0, "total": 0} for step in STEPS},
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
    for name in ("job_ids", "problems", "warnings", "continued"):
        if not isinstance(output.get(name), list):
            output[name] = []
    if not isinstance(output.get("paused_at"), str):
        output["paused_at"] = None
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


def phase_of(output: Mapping[str, Any], running: Sequence[tuple[str, int, int]]) -> str:
    """The phase label of the run: how many steps are complete and what is going on."""
    return phases.pipeline_progress(len(complete_keys(output)), len(STEPS), running)


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
) -> tuple[Job, bool]:
    """Queues a run, and commits. Returns `(job, created)`: a run that is already waiting or
    running is returned as it is (`created` False), with the choices it was started with.
    Raises StoryPipelineError for an unknown step or when a run cannot start now.

    Whether the user has allowed the overwrites is decided by the caller (`confirmations`).
    """
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
        },
    )
    return job, created


async def continue_run(session: AsyncSession, project: Project) -> Job:
    """Lets a paused run go on, and commits. Raises StoryPipelineError when the project has no
    run, or its run is not paused.
    """
    run = await active_run(session, project.id)
    if run is None:
        raise StoryPipelineError("There is no run going on for this project.")
    output = read_output(run.output)
    paused = output["paused_at"]
    if paused is None:
        raise StoryPipelineError("The run is not paused.")
    if paused not in output["continued"]:
        output["continued"].append(paused)
    output["paused_at"] = None
    if not await store.save_progress(session, run.id, phase=phase_of(output, []), output=output):
        await session.rollback()
        raise StoryPipelineError("The run is no longer going.")
    await session.commit()
    return run


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
