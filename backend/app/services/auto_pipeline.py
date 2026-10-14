"""The automatic video pipeline: the steps, and what "done" means for each of them.

One run (an `auto_pipeline` job, driven by `jobs/auto_pipeline.py`) works through `STEPS`, which
is a graph, not a queue. It creates the same jobs the manual buttons create, and a step does not
wait for the one before it unless it has to:

- `Step.needs`: steps that must be complete before this step makes any job (the data it reads
  is only final then). Steps that need nothing from each other run at the same time: the cast
  is found from the script while the voiceover is made, transcribed and cut into scenes.
- `Step.follows` and `Target.waits_for`: steps this one streams behind. A target (a scene, a
  character, a place) waits only for the *same* scene or member in the earlier step, so its job
  starts the moment that one is done, while other scenes are still in the earlier step. A scene
  whose first frame is ready does not wait for the other scenes' frames to make its clip.

How many jobs run at once is not decided here. The run creates every job that is ready, and the
dispatcher starts them as the two shared pools allow (`jobs/pools.py`).

This module holds the rules, so the handler only has to orchestrate them:

- `evaluate`: for one step, reads the database and answers with the targets of the step (each
  scene, or the project) and whether each is done, being worked on, or cannot get a job.
  It reuses the rules of the manual steps (`is_candidate`, `scene_block`, `generation_block`,
  `render_block` and so on), so the run never does what the buttons would refuse.
- `plan_step`: pure. From those targets, the jobs this run has already made for them and what
  the earlier steps of the same poll found (`Standing`), it decides what to do now: wait,
  create the next job, or report a problem. A target gets at most `MAX_TRIES` jobs from one run
  per step.
- The run's stored state (`job.output`): `new_output`, `read_output`, `add_job_id` and
  `load_run_jobs`. The jobs a run made are named in its output, so the count of tries survives
  a restart.

Nothing here calls a provider. The jobs it creates do, each under its own handler's rules.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, Job, Project, Scene
from app.jobs import store
from app.services import cast as cast_service
from app.services import clips as clips_service
from app.services import first_frames as frames_service
from app.services import image_prompts as prompts_service
from app.services import last_frame_prompts as last_prompts_service
from app.services import last_frames as last_frames_service
from app.services import renders as renders_service
from app.services import (
    scene_cuts,
    scene_inputs,
    scene_planner,
    transcript_matching,
    voiceover_generation,
    voices,
)
from app.services import scenes as scenes_service
from app.services import transcripts as transcripts_service
from app.services.descriptions import DRAFT_JOB, draft_block

JOB_TYPE: Final = "auto_pipeline"

# A scene gets this many jobs from one run in one step (the first try and the retries).
MAX_TRIES: Final = 3

# The key under which a project-level step keeps its jobs (a scene step uses the scene's id).
PROJECT_KEY: Final = "project"

# What the run saves in `job.provider_job_id`: it makes the dispatcher check the run every
# tick (the handler's `poll`). It is not an id on any server.
MARKER: Final = "auto"

_ERROR_MAX_CHARS: Final = 300
_MAX_PROBLEMS_SHOWN: Final = 10

# The status of a step. "skipped": the step was already complete when the run got to it, so the
# run made no job for it. "stopped" is never stored: `describe` shows it for the step a
# cancelled run was at.
StepStatus = Literal["pending", "running", "done", "skipped", "failed", "stopped"]


# --- The steps -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    key: str
    # What the page shows.
    label: str
    # The job this step creates, and who it calls.
    job_type: str
    provider: str
    # One job per scene, or one for the project. (The cast's steps are neither: a project-level
    # step that finds the cast and chooses who is in each scene, and two steps with one job per
    # character or place. They say False.)
    per_scene: bool
    # What is still missing when a job finished and its target is not done (for the report).
    missing: str
    # The step asks the language model: a second try must not reuse the stored answer.
    asks_model: bool = False
    # Steps that must be complete before this one makes any job.
    needs: tuple[str, ...] = ()
    # Steps this one streams behind: its targets wait for the same target of those steps (see
    # `Target.waits_for`), so each starts when its own input is ready. It is complete only when
    # they are too. Whatever those steps need, this one needs as well (directly or through
    # another step), so they have been reached whenever this step is.
    follows: tuple[str, ...] = ()


# What every step that works on the scenes' texts needs: the scenes are cut, their descriptions
# are drafted, and each scene knows who it shows. Nothing after this point reads them while they
# can still change.
_SCENE_INPUTS: Final = ("descriptions", "cast_assignment")

# The order here is the order the page lists the steps, and a valid order to evaluate them in:
# every step comes after the steps it needs and follows.
STEPS: Final[tuple[Step, ...]] = (
    Step(
        "voiceover",
        "Make the voiceover",
        voiceover_generation.JOB_TYPE,
        "gpu",
        False,
        "a voiceover made from the script",
    ),
    Step(
        "transcribe",
        "Transcribe the voiceover",
        transcripts_service.TRANSCRIBE_JOB,
        "gpu",
        False,
        "a current transcript",
        needs=("voiceover",),
    ),
    # The scene cuts need each word's start time, so this waits for the transcript.
    Step(
        "scenes",
        "Propose scenes",
        scenes_service.PLAN_JOB,
        "llm",
        False,
        "scenes that match the script",
        asks_model=True,
        needs=("transcribe",),
    ),
    # The project's cast (characters and places): found once from the script alone, so it starts
    # at once, beside the voiceover. Each member is drawn as soon as its prompt is written, and
    # chosen per scene once the scenes exist. A project whose script has no cast passes through
    # all four.
    Step(
        "cast",
        "Find the characters and places",
        cast_service.EXTRACT_JOB,
        "llm",
        False,
        "a cast found in the script",
        asks_model=True,
    ),
    Step(
        "cast_prompts",
        "Write reference prompts",
        cast_service.REFERENCE_PROMPT_JOB,
        "llm",
        False,
        "a reference prompt",
        asks_model=True,
        needs=("cast",),
    ),
    Step(
        "cast_images",
        "Make reference pictures",
        cast_service.REFERENCE_IMAGE_JOB,
        "gpu",
        False,
        "a reference picture",
        needs=("cast",),
        follows=("cast_prompts",),
    ),
    # Chooses from the names and the appearances, so it needs no picture.
    Step(
        "cast_assignment",
        "Choose who is in each scene",
        cast_service.ASSIGN_JOB,
        "llm",
        False,
        "a choice of character and place for every scene",
        asks_model=True,
        needs=("scenes", "cast"),
    ),
    # One call for the whole project (it keeps the story in order), and it does not read the cast.
    Step(
        "descriptions",
        "Draft descriptions",
        DRAFT_JOB,
        "llm",
        False,
        "a description for every scene",
        asks_model=True,
        needs=("scenes",),
    ),
    # The prompt names who is in the scene, so it waits for the choice.
    Step(
        "image_prompts",
        "Write image prompts",
        prompts_service.IMAGE_PROMPT_JOB,
        "llm",
        True,
        "an image prompt",
        asks_model=True,
        needs=_SCENE_INPUTS,
    ),
    # A scene waits for its own prompt and for the pictures of the members it shows.
    Step(
        "first_frames",
        "Make first frames",
        frames_service.FRAME_JOB,
        "gpu",
        True,
        "a first frame",
        needs=_SCENE_INPUTS,
        follows=("image_prompts", "cast_images"),
    ),
    # Written from text only (not from the first frame), beside the first frames.
    Step(
        "last_frame_prompts",
        "Write last frame prompts",
        last_prompts_service.LAST_FRAME_PROMPT_JOB,
        "llm",
        True,
        "a last frame prompt",
        asks_model=True,
        needs=_SCENE_INPUTS,
        follows=("image_prompts",),
    ),
    # Edited from the scene's own first frame, with its own prompt.
    Step(
        "last_frames",
        "Make last frames",
        last_frames_service.LAST_FRAME_JOB,
        "gpu",
        True,
        "a last frame",
        needs=_SCENE_INPUTS,
        follows=("first_frames", "last_frame_prompts"),
    ),
    # A scene's clip needs its first frame, and its last frame when it gets one.
    Step(
        "clips",
        "Generate clips",
        clips_service.GENERATE_JOB,
        "gpu",
        True,
        "a clip",
        needs=_SCENE_INPUTS,
        follows=("first_frames", "last_frames"),
    ),
    Step(
        "render",
        "Render the final video",
        renders_service.RENDER_JOB,
        "local",
        False,
        "a finished video",
        needs=(
            "voiceover",
            "transcribe",
            "scenes",
            "cast",
            "cast_prompts",
            "cast_images",
            "cast_assignment",
            "descriptions",
            "image_prompts",
            "first_frames",
            "last_frame_prompts",
            "last_frames",
            "clips",
        ),
    ),
)
STEP_KEYS: Final = tuple(step.key for step in STEPS)
STEP_LABELS: Final = {step.key: step.label for step in STEPS}


def _check_graph() -> None:
    """Every step comes after the steps it needs and follows: the order of `STEPS` is then a
    valid order to evaluate them in, and the graph has no cycle.
    """
    seen: set[str] = set()
    for step in STEPS:
        unknown = [key for key in (*step.needs, *step.follows) if key not in seen]
        if unknown:
            raise ValueError(f"step {step.key} needs or follows {unknown}, not before it")
        seen.add(step.key)


_check_graph()


# --- What the user confirmed when starting --------------------------------------------------


@dataclass(frozen=True)
class RunOptions:
    """The two questions the manual "Propose scenes" asks, answered once at the start."""

    accept_mismatch: bool = False
    discard_scenes_with_inputs: bool = False

    @classmethod
    def from_input(cls, value: object) -> RunOptions:
        data: dict[str, Any] = value if isinstance(value, dict) else {}
        return cls(
            accept_mismatch=data.get("accept_mismatch") is True,
            discard_scenes_with_inputs=data.get("discard_scenes_with_inputs") is True,
        )


@dataclass(frozen=True)
class RunContext:
    project: Project
    options: RunOptions
    # This run's jobs of the step being evaluated, by target key, oldest first.
    run_jobs: Mapping[str, Sequence[Job]]


# --- Targets and plans ----------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """One thing a step must get done: a scene, or the project."""

    key: str
    scene_id: int | None
    # The scene number as the user sees it (from 1). None for the project.
    scene_number: int | None
    done: bool
    # A job of this step that is queued or running for it, whoever started it.
    active: Job | None = None
    # Why no job can be made for it now. Another try would not help.
    block: str | None = None
    # What the job is created with (the run adds its own keys).
    job_input: dict[str, Any] = field(default_factory=dict)
    # The targets this one waits for, each as `(step key, target key)`: the same scene in an
    # earlier step (a clip waits for its scene's first frame), or, in this step, the previous
    # scene (a scene that continues the previous scene's action waits for that scene's last
    # frame, which becomes its first frame). A target that is done, or that does not exist, is
    # not waited for. It waits only while every target it waits for can still go on: if one
    # cannot, this one does not wait for ever, and the run stops with the reason that target
    # gave. Build each with `wait`.
    waits_for: tuple[tuple[str, str], ...] = ()
    # What a problem with this target is about, when it is neither a scene nor the project (a
    # character or a place of the cast): its name.
    label: str | None = None


@dataclass(frozen=True)
class StepView:
    targets: list[Target]
    # Why no target of the step can get a job, when that is true of the whole project (the
    # scenes are out of date, a proposal is running). Only matters while a target is not done.
    block: str | None = None


@dataclass(frozen=True)
class Create:
    target: Target
    # True from the second try on.
    retry: bool


def wait(step_key: str, target_key: str) -> tuple[str, str]:
    """A target of an earlier step, as `Target.waits_for` names it. A misspelt step would be
    waited for never, so it is refused here instead.
    """
    if step_key not in STEP_KEYS:
        raise ValueError(f"unknown step {step_key!r}")
    return step_key, target_key


@dataclass(frozen=True)
class Problem:
    # The step it is about. Empty for a problem an older run stored without one.
    step_key: str
    scene_id: int | None
    scene_number: int | None
    tries: int
    message: str

    def text(self) -> str:
        message = self.message if self.message.endswith((".", "!", "?")) else f"{self.message}."
        return message if self.scene_number is None else f"Scene {self.scene_number}: {message}"

    def as_json(self) -> dict[str, Any]:
        return {
            "step": self.step_key,
            "scene_id": self.scene_id,
            "scene_number": self.scene_number,
            "tries": self.tries,
            "message": self.message,
        }


@dataclass(frozen=True)
class StepPlan:
    done: int
    total: int
    # Targets with a job in progress.
    waiting: int
    creates: list[Create]
    problems: list[Problem]
    # The keys of the targets that are not done, and of those that have a job in progress or are
    # about to get one. The steps after this one wait on them (`Standing`).
    pending: frozenset[str] = frozenset()
    progressing: frozenset[str] = frozenset()

    @property
    def complete(self) -> bool:
        return self.done == self.total


@dataclass(frozen=True)
class Standing:
    """What the steps evaluated so far in one poll found, as `(step key, target key)`, so a
    later step can tell whether the targets it waits for are done, going on, or stuck.

    A step left out of it is either complete (all its targets are done) or `unreached`: it is
    not complete and what it needs is not, so it has made no job and nothing waits on it
    successfully.
    """

    pending: frozenset[tuple[str, str]] = frozenset()
    progressing: frozenset[tuple[str, str]] = frozenset()
    unreached: frozenset[str] = frozenset()

    def after_step(self, step_key: str, plan: StepPlan) -> Standing:
        return Standing(
            pending=self.pending | {(step_key, key) for key in plan.pending},
            progressing=self.progressing | {(step_key, key) for key in plan.progressing},
            unreached=self.unreached,
        )

    def with_unreached(self, step_key: str) -> Standing:
        return Standing(self.pending, self.progressing, self.unreached | {step_key})


def _short(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= _ERROR_MAX_CHARS:
        return one_line
    return f"{one_line[: _ERROR_MAX_CHARS - 1]}…"


def _named(target: Target, message: str) -> str:
    """The message with the name of the character or place it is about in front of it, unless
    the message names it already.
    """
    if target.label is None or target.label in message:
        return message
    return f"{target.label}: {message}"


def exhausted_message(step: Step, tried: Sequence[Job]) -> str:
    """Why a target that was tried `MAX_TRIES` times is reported."""
    last = tried[-1]
    if last.status == "failed":
        reason = _short(last.error or "it failed")
    elif last.status == "cancelled":
        reason = "it was cancelled"
    else:
        reason = f"it finished, but there is still no {step.missing}"
    return f"Tried {len(tried)} times without success. The last try: {reason}"


def plan_step(
    step: Step,
    view: StepView,
    run_jobs: Mapping[str, Sequence[Job]],
    standing: Standing,
) -> StepPlan:
    """What to do now about a step. Pure.

    For each target that is not done, in this order: wait when a job is in progress for it; wait
    when a target it waits for (`Target.waits_for`) is not done yet and can still go on; report
    it when no job can be made or it has had `MAX_TRIES`; otherwise create the next job.
    `standing` is what the steps before this one found in the same poll.
    """
    pending = [target for target in view.targets if not target.done]
    waiting = 0
    creates: list[Create] = []
    problems: list[Problem] = []
    pending_here = {(step.key, target.key) for target in pending}
    # The targets that have a job in progress or are about to get one.
    progressing: set[str] = set()

    def is_pending(wait_for: tuple[str, str]) -> bool:
        # A target that is done, or that does not exist, has nothing left to wait for. A step
        # that was not reached has made nothing, so everything in it is still to do.
        return (
            wait_for in pending_here
            or wait_for in standing.pending
            or wait_for[0] in standing.unreached
        )

    def is_progressing(wait_for: tuple[str, str]) -> bool:
        in_this_step = wait_for[0] == step.key and wait_for[1] in progressing
        return in_this_step or wait_for in standing.progressing

    # A target that waits is decided last, in the order of the view, because the one it waits
    # for may itself be waiting for an earlier one (a scene's last frame waits for the previous
    # scene's last frame, which waits for the one before).
    following: list[Target] = []

    for target in pending:
        tried = run_jobs.get(target.key, [])
        if target.active is not None or any(job.status in store.ACTIVE_STATUSES for job in tried):
            waiting += 1
            progressing.add(target.key)
        elif view.block is not None:
            continue  # reported once, below
        elif any(is_pending(wait_for) for wait_for in target.waits_for):
            following.append(target)
        elif target.block is not None:
            problems.append(
                Problem(
                    step.key,
                    target.scene_id,
                    target.scene_number,
                    len(tried),
                    _named(target, target.block),
                )
            )
        elif len(tried) >= MAX_TRIES:
            problems.append(
                Problem(
                    step.key,
                    target.scene_id,
                    target.scene_number,
                    len(tried),
                    _named(target, exhausted_message(step, tried)),
                )
            )
        else:
            creates.append(Create(target, retry=bool(tried)))
            progressing.add(target.key)

    for target in following:
        # Every target it waits for that is not done has a job in progress or will get one:
        # wait. Otherwise one of them cannot go on and is reported (or its whole step is
        # blocked, or not reached), so nothing is added here: counting this one as going on
        # would keep the run alive for ever.
        blockers = [wait_for for wait_for in target.waits_for if is_pending(wait_for)]
        if all(is_progressing(wait_for) for wait_for in blockers):
            waiting += 1
            progressing.add(target.key)

    if view.block is not None and pending:
        problems.append(Problem(step.key, None, None, 0, view.block))

    return StepPlan(
        done=len(view.targets) - len(pending),
        total=len(view.targets),
        waiting=waiting,
        creates=creates,
        problems=problems,
        pending=frozenset(target.key for target in pending),
        progressing=frozenset(progressing),
    )


def failure_message(done: int, total: int, problems: Sequence[Problem]) -> str:
    """What a stopped run says: how far it got, and what is wrong, step by step."""
    shown = problems[:_MAX_PROBLEMS_SHOWN]
    by_step: dict[str, list[str]] = {}
    for problem in shown:
        by_step.setdefault(problem.step_key, []).append(problem.text())
    parts = " ".join(
        f"{STEP_LABELS.get(key, key)}: {' '.join(texts)}" if key else " ".join(texts)
        for key, texts in by_step.items()
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
        f"started, but these steps are not complete: {labels}. Press Start again to try them."
    )


# --- The run's stored state -----------------------------------------------------------------


def new_output() -> dict[str, Any]:
    """The output of a run that has just started: every step waiting, no job made yet."""
    return {
        "steps": {step.key: {"status": "pending", "done": 0, "total": 0} for step in STEPS},
        # step key -> target key -> ids of the jobs this run made, oldest first.
        "jobs": {step.key: {} for step in STEPS},
        "problems": [],
    }


def read_output(value: object) -> dict[str, Any]:
    """A copy of a run's stored output that is safe to change (the stored JSON is replaced by a
    new object, never changed in place). Anything that is not a run's output starts afresh.

    A run made before the steps went on at the same time also stored the one step it was at
    (`step`). That is dropped: every step that is not complete is looked at in each poll, and the
    steps it had passed stay passed.
    """
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("steps"), dict)
        or not isinstance(value.get("jobs"), dict)
    ):
        return new_output()
    output: dict[str, Any] = copy.deepcopy(value)
    output.pop("step", None)
    fresh = new_output()
    for key in STEP_KEYS:
        if not isinstance(output["steps"].get(key), dict):
            output["steps"][key] = fresh["steps"][key]
        if not isinstance(output["jobs"].get(key), dict):
            output["jobs"][key] = {}
    if not isinstance(output.get("problems"), list):
        output["problems"] = []
    return output


def add_job_id(output: dict[str, Any], step_key: str, target_key: str, job_id: int) -> None:
    output["jobs"][step_key].setdefault(target_key, []).append(job_id)


def job_ids(output: Mapping[str, Any], step_key: str) -> dict[str, list[int]]:
    """The ids of the jobs the run made in a step, by target key. `output` comes from
    `read_output`.
    """
    result: dict[str, list[int]] = {}
    for key, ids in output["jobs"][step_key].items():
        if isinstance(ids, list):
            result[str(key)] = [i for i in ids if isinstance(i, int) and not isinstance(i, bool)]
    return result


async def load_run_jobs(
    session: AsyncSession, output: Mapping[str, Any], step_key: str
) -> dict[str, list[Job]]:
    """The jobs the run made in a step, by target key, oldest first. A job that no longer
    exists (its scene was replaced) is left out.
    """
    ids_by_key = job_ids(output, step_key)
    wanted = {job_id for ids in ids_by_key.values() for job_id in ids}
    if not wanted:
        return {}
    statement = select(Job).where(Job.id.in_(wanted)).execution_options(populate_existing=True)
    found = {job.id: job for job in (await session.execute(statement)).scalars()}
    return {
        key: [found[job_id] for job_id in sorted(ids) if job_id in found]
        for key, ids in ids_by_key.items()
    }


def record_progress(
    output: dict[str, Any], step_key: str, plan: StepPlan, *, status: StepStatus
) -> None:
    entry = output["steps"][step_key]
    entry["status"] = status
    entry["done"] = plan.done
    entry["total"] = plan.total


def made_no_jobs(output: Mapping[str, Any], step_key: str) -> bool:
    """Whether the run has made no job in a step (so a completed step was already complete)."""
    return not any(job_ids(output, step_key).values())


def all_job_ids(output: Mapping[str, Any]) -> list[int]:
    return [
        job_id for step in STEPS for ids in job_ids(output, step.key).values() for job_id in ids
    ]


# --- Starting a run -------------------------------------------------------------------------


async def active_jobs(session: AsyncSession, project_id: int) -> list[Job]:
    """The project's jobs that are waiting or running, whatever they are."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.status.in_(store.ACTIVE_STATUSES))
        .order_by(Job.id)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars().all())


def start_block(
    project: Project, active: Sequence[Job], voiceover: Asset | None = None
) -> str | None:
    """Why a run cannot start now, or None. Pure. The run waits for no other job: two kinds of
    work on one project at once could replace each other's results.

    Without a voiceover, the run makes one from the script, so it needs a saved voice. So does
    a voiceover that was made from an earlier script. An uploaded voiceover is used as it is.
    """
    if project.voice_id is None:
        if voiceover is None:
            return "Upload a voiceover, or choose a saved voice to make one from the script."
        if voiceover.source == "ai" and not voiceover_generation.is_current(project, voiceover):
            return (
                "The voiceover was made from an earlier script. Choose a saved voice to make "
                "it again, or upload a voiceover."
            )
    if _blank(project.script_text):
        return "Paste the script first."
    if active:
        many = len(active) > 1
        return (
            f"{len(active)} {'jobs are' if many else 'job is'} waiting or running for this "
            f"project. Wait for {'them' if many else 'it'} to finish, or cancel "
            f"{'them' if many else 'it'}, before starting the automatic flow."
        )
    return None


@dataclass(frozen=True)
class Confirmations:
    """What the user must confirm before a run, the same two questions the manual "Propose
    scenes" asks. Both are about a proposal, so they only apply when the run will propose.
    """

    # The words of the mismatch warning, when the recording differs from the script.
    mismatch: str | None
    # How many scenes have a description, frames or a clip, and would be replaced.
    scenes_with_inputs: int


async def confirmations(session: AsyncSession, project: Project) -> Confirmations:
    """What starting a run now needs the user to confirm. Read-only.

    A mismatch is known only when there is a current transcript: a run that transcribes first
    stops at the proposal instead, if the new transcript has one (see `_scenes`).
    """
    state = await scenes_service.scenes_state(session, project)
    if state.scenes and not state.stale_reasons:
        return Confirmations(mismatch=None, scenes_with_inputs=0)  # the scenes stay as they are

    transcription = await transcripts_service.transcription_state(session, project)
    mismatch = (
        " ".join(transcription.warnings)
        if transcription.transcript is not None
        and not transcription.stale_reasons
        and transcription.warnings
        else None
    )
    return Confirmations(
        mismatch=mismatch,
        scenes_with_inputs=sum(1 for scene in state.scenes if scene_cuts.has_inputs(scene)),
    )


# --- Creating a job -------------------------------------------------------------------------


async def create_child(
    session: AsyncSession, project: Project, step: Step, create: Create, *, run_id: int
) -> tuple[Job, bool]:
    """Creates the next job for a target, without committing (the caller commits it together
    with the run's output). Returns `(job, created)`: the job already active when there is one.
    """
    job_input = {**create.target.job_input, "auto_run_id": run_id}
    if step.asks_model:
        job_input["run_again"] = create.retry
    # A character's or a place's job has no scene: the member it names tells it from the jobs of
    # the other members.
    member = {
        key: job_input[key]
        for key in (cast_service.KIND_KEY, cast_service.ID_KEY)
        if key in job_input
    }
    return await store.create_job(
        session,
        project_id=project.id,
        type=step.job_type,
        provider=step.provider,
        scene_id=create.target.scene_id,
        input=job_input,
        commit=False,
        same_input=member or None,
    )


async def cancel_queued_children(session: AsyncSession, run: Job) -> int:
    """Cancels the jobs of a run that have not started, so a stopped run starts no paid work.
    A job that is already running finishes on its own. Commits. Returns how many were cancelled.
    """
    cancelled = 0
    for job_id in all_job_ids(read_output(run.output)):
        child = await store.get_job(session, job_id)
        if child is None or child.status != "queued":
            continue
        try:
            await store.cancel_job(session, job_id)
            cancelled += 1
        except store.JobActionError:
            continue  # it started in the meantime
    await session.commit()
    return cancelled


# --- Evaluating a step ----------------------------------------------------------------------


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _active(job: Job | None) -> Job | None:
    return job if job is not None and job.status in store.ACTIVE_STATUSES else None


def _scene_target(
    scene: Scene,
    *,
    done: bool,
    active: Job | None,
    block: str | None,
    job_input: dict[str, Any],
    waits_for: tuple[tuple[str, str], ...] = (),
) -> Target:
    return Target(
        key=str(scene.id),
        scene_id=scene.id,
        scene_number=scene.index + 1,
        done=done,
        active=active,
        block=None if done else block,
        job_input=job_input,
        waits_for=waits_for,
    )


def _project_target(
    *, done: bool, active: Job | None, block: str | None, job_input: dict[str, Any]
) -> Target:
    return Target(
        key=PROJECT_KEY,
        scene_id=None,
        scene_number=None,
        done=done,
        active=active,
        block=None if done else block,
        job_input=job_input,
    )


async def _voiceover(session: AsyncSession, ctx: RunContext) -> StepView:
    """A voiceover the user uploaded is done as it is. Otherwise the app makes one from the
    script, in the project's saved voice (and makes it again when the script has changed).
    """
    project = ctx.project
    asset = (
        await session.get(Asset, project.voiceover_asset_id)
        if project.voiceover_asset_id is not None
        else None
    )
    latest = await store.latest_job(session, project.id, voiceover_generation.JOB_TYPE)
    active = _active(latest)
    done = (
        asset is not None
        and (asset.source != "ai" or voiceover_generation.is_current(project, asset))
        and active is None
    )
    if done:
        return StepView([_project_target(done=True, active=None, block=None, job_input={})])

    voice = await voices.get_voice(session, project.voice_id) if project.voice_id else None
    block = voiceover_generation.block_reason(project, voice)
    job_input: dict[str, Any] = {}
    if block is None and voice is not None:
        job_input = {
            **voiceover_generation.build_input(project, voice),
            "requested": "auto_pipeline",
        }
    return StepView([_project_target(done=False, active=active, block=block, job_input=job_input)])


async def _transcribe(session: AsyncSession, ctx: RunContext) -> StepView:
    project = ctx.project
    state = await transcripts_service.transcription_state(session, project)
    active = _active(state.job)
    done = state.transcript is not None and not state.stale_reasons and active is None

    block: str | None = None
    if project.voiceover_asset_id is None:
        block = "Upload a voiceover first."
    elif _blank(project.script_text):
        block = "Paste the script first."
    return StepView(
        [
            _project_target(
                done=done,
                active=active,
                block=block,
                job_input={
                    "requested": "auto_pipeline",
                    "voiceover_asset_id": project.voiceover_asset_id,
                },
            )
        ]
    )


async def _scenes(session: AsyncSession, ctx: RunContext) -> StepView:
    project, options = ctx.project, ctx.options
    state = await scenes_service.scenes_state(session, project)
    plan_active = _active(state.job)
    done = plan_active is None and bool(state.scenes) and not state.stale_reasons
    if done:
        return StepView([_project_target(done=True, active=None, block=None, job_input={})])

    # A proposal replaces every scene, and deleting a scene deletes the jobs that point at it,
    # so it waits for the jobs the scenes have (the same rule as the manual button).
    draft_job = await store.latest_job(session, project.id, DRAFT_JOB)
    blocking: list[Job | None] = [
        plan_active,
        _active(draft_job),
        *(await clips_service.active_clip_jobs(session, project.id)).values(),
        *(await prompts_service.active_prompt_jobs(session, project.id)).values(),
        *(await frames_service.active_frame_jobs(session, project.id)).values(),
        *(await last_prompts_service.active_prompt_jobs(session, project.id)).values(),
        *(await last_frames_service.active_last_frame_jobs(session, project.id)).values(),
    ]
    active = next((job for job in blocking if job is not None), None)

    transcription = await transcripts_service.transcription_state(session, project)
    transcript = transcription.transcript
    block: str | None = None
    job_input: dict[str, Any] = {}
    if transcript is None or transcription.stale_reasons:
        block = "The transcript is out of date. Transcribe again first."
    elif _blank(project.script_text):
        block = "Paste the script first."
    else:
        words = len(transcript.script_words) if isinstance(transcript.script_words, list) else 0
        with_inputs = sum(1 for scene in state.scenes if scene_cuts.has_inputs(scene))
        if words > scene_planner.MAX_SCRIPT_WORDS:
            block = (
                f"This script has {words:,} words; scene proposal handles up to "
                f"{scene_planner.MAX_SCRIPT_WORDS:,}."
            )
        elif transcription.warnings and not options.accept_mismatch:
            block = (
                "The recording differs from the script. "
                + " ".join(transcription.warnings)
                + " Start again and confirm to go on anyway."
            )
        elif with_inputs and not options.discard_scenes_with_inputs:
            noun = "scene has" if with_inputs == 1 else "scenes have"
            block = (
                f"{with_inputs} {noun} a description, frames or a clip, and proposing scenes "
                "replaces them. Start again and confirm to go on."
            )
        else:
            job_input = {
                "requested": "auto_pipeline",
                "transcript_id": transcript.id,
                "voiceover_asset_id": project.voiceover_asset_id,
                "script_sha256": transcript_matching.script_sha256(project.script_text or ""),
                "accept_mismatch": options.accept_mismatch,
                "discard_scenes_with_inputs": options.discard_scenes_with_inputs,
            }
    return StepView([_project_target(done=False, active=active, block=block, job_input=job_input)])


async def _cast(session: AsyncSession, ctx: RunContext) -> StepView:
    """The cast is found once. A project that has one is done, whatever its script says now:
    finding it again replaces the whole cast and the pictures made for it, so a run never does
    that by itself. A script the model found no characters or places in is done too (the newest
    job succeeded for this very script), or the run would ask again for ever.
    """
    project = ctx.project
    cast = await cast_service.load_cast(session, project.id)
    latest = await store.latest_job(session, project.id, cast_service.EXTRACT_JOB)
    active = _active(latest)
    recorded: Any = latest.input if latest is not None and isinstance(latest.input, dict) else {}
    found_nothing = (
        latest is not None
        and latest.status == "succeeded"
        and recorded.get("script_sha256")
        == transcript_matching.script_sha256(project.script_text or "")
    )
    done = (not cast.is_empty or found_nothing) and active is None

    block: str | None = None
    script = project.script_text or ""
    if _blank(script):
        block = "Paste the script first."
    elif len(script.split()) > scene_planner.MAX_SCRIPT_WORDS:
        block = (
            f"This script has {len(script.split()):,} words; finding the cast handles up to "
            f"{scene_planner.MAX_SCRIPT_WORDS:,}."
        )
    return StepView(
        [
            _project_target(
                done=done,
                active=active,
                block=block,
                job_input={"requested": "auto_pipeline"},
            )
        ]
    )


async def _cast_prompts(session: AsyncSession, ctx: RunContext) -> StepView:
    """One target for each character and place that has no reference prompt yet. A prompt the
    author wrote counts: it is never replaced by a run.
    """
    project = ctx.project
    cast = await cast_service.load_cast(session, project.id)
    prompt_jobs = [cast_service.REFERENCE_PROMPT_JOB]
    active = await cast_service.active_jobs(session, project.id, prompt_jobs)
    active_by_member = {
        cast_service.member_key(*member): job
        for job in active
        if (member := cast_service.member_of_job(job)) is not None
    }
    targets: list[Target] = []
    for kind, member in cast.members():
        key = cast_service.member_key(kind, member.id)
        done = cast_service.has_prompt(member)
        targets.append(
            Target(
                key=key,
                scene_id=None,
                scene_number=None,
                done=done,
                active=active_by_member.get(key),
                block=None if done else cast_service.prompt_block(member),
                job_input={
                    "requested": "auto_pipeline",
                    cast_service.KIND_KEY: kind,
                    cast_service.ID_KEY: member.id,
                },
                label=member.name,
            )
        )
    return StepView(targets)


async def _cast_images(session: AsyncSession, ctx: RunContext) -> StepView:
    """One target for each character and place that has no reference picture yet. A picture that
    exists is never replaced by a run. A member is drawn as soon as its own prompt is written,
    while the other members' prompts are still being written.
    """
    project = ctx.project
    cast = await cast_service.load_cast(session, project.id)
    active = await cast_service.active_reference_image_jobs(session, project.id)
    targets: list[Target] = []
    for kind, member in cast.members():
        key = cast_service.member_key(kind, member.id)
        done = member.reference_asset_id is not None
        targets.append(
            Target(
                key=key,
                scene_id=None,
                scene_number=None,
                done=done,
                active=active.get(key),
                block=None if done else cast_service.image_block(member),
                job_input={
                    "requested": "auto_pipeline",
                    cast_service.KIND_KEY: kind,
                    cast_service.ID_KEY: member.id,
                },
                waits_for=(wait("cast_prompts", key),),
                label=member.name,
            )
        )
    return StepView(targets)


async def _cast_assignment(session: AsyncSession, ctx: RunContext) -> StepView:
    """Every scene has a choice of character and place. A choice of nobody counts: it is a
    choice. A project with no cast has nothing to choose from, so the step is done.
    """
    project = ctx.project
    cast = await cast_service.load_cast(session, project.id)
    state = await scenes_service.scenes_state(session, project)
    active = _active(await store.latest_job(session, project.id, cast_service.ASSIGN_JOB))
    chosen = bool(state.scenes) and all(
        scene.cast_assignment_source is not None for scene in state.scenes
    )
    done = (cast.is_empty or chosen) and active is None

    block: str | None = None
    if not state.scenes:
        block = "There are no scenes yet. Propose scenes first."
    elif state.stale_reasons:
        block = "The scenes are out of date. Propose scenes again first."
    return StepView(
        [
            _project_target(
                done=done,
                active=active,
                block=block,
                job_input={"requested": "auto_pipeline"},
            )
        ]
    )


async def _descriptions(session: AsyncSession, ctx: RunContext) -> StepView:
    state = await scenes_service.scenes_state(session, ctx.project)
    active = _active(await store.latest_job(session, ctx.project.id, DRAFT_JOB))
    described = bool(state.scenes) and all(
        not _blank(scene.scene_description) for scene in state.scenes
    )
    done = described and active is None
    block = None
    if not done and active is None:
        block = draft_block(state.scenes, plan_job=state.job, stale_reasons=state.stale_reasons)
    return StepView(
        [
            _project_target(
                done=done,
                active=active,
                block=None,
                job_input={"requested": "auto_pipeline"},
            )
        ],
        block=block,
    )


async def _prompts_block(
    session: AsyncSession, project: Project, state: scenes_service.ScenesState
) -> str | None:
    """Why no image prompt or first frame can be made for the project now, or None."""
    draft_job = await store.latest_job(session, project.id, DRAFT_JOB)
    return prompts_service.project_block(
        state.scenes,
        plan_job=state.job,
        stale_reasons=state.stale_reasons,
        draft_job=draft_job,
    )


async def _image_prompts(session: AsyncSession, ctx: RunContext) -> StepView:
    project = ctx.project
    state = await scenes_service.scenes_state(session, project)
    block = await _prompts_block(session, project, state)
    active = await prompts_service.active_prompt_jobs(session, project.id)
    states = await prompts_service.prompt_states(session, project, state.scenes)
    frames = await scene_inputs.load_frames(session, state.scenes)

    targets: list[Target] = []
    for scene in state.scenes:
        out_of_date = scene.id in states and states[scene.id].out_of_date
        # A scene whose first frame the author uploaded needs no prompt: nothing makes a frame.
        has_own_frame = frames_service.needs_upload_confirmation(
            scene, frames.get(scene.first_frame_asset_id or 0)
        )
        done = has_own_frame or (not _blank(scene.image_prompt) and not out_of_date)
        targets.append(
            _scene_target(
                scene,
                done=done,
                active=active.get(scene.id),
                block=prompts_service.scene_block(scene),
                job_input={"requested": "write_all"},
            )
        )
    return StepView(targets, block=block)


async def _first_frames(session: AsyncSession, ctx: RunContext) -> StepView:
    """A scene's frame is made as soon as the scene's own image prompt is written and the
    reference pictures of the characters and the place it shows are drawn. It does not wait for
    the other scenes' prompts, nor for the pictures of members this scene does not show.
    """
    project = ctx.project
    state = await scenes_service.scenes_state(session, project)
    block = await _prompts_block(session, project, state)
    active_frames = await frames_service.active_frame_jobs(session, project.id)
    active_prompts = await prompts_service.active_prompt_jobs(session, project.id)
    states = await prompts_service.prompt_states(session, project, state.scenes)
    frames = await scene_inputs.load_frames(session, state.scenes)
    chained = await last_frames_service.chain_sources(session, project.id, state.scenes)
    scene_casts = await cast_service.load_scene_casts(session, project.id, state.scenes)

    targets: list[Target] = []
    for scene in state.scenes:
        scene_cast = scene_casts.get(scene.id, cast_service.NO_CAST)
        asset = frames.get(scene.first_frame_asset_id or 0)
        out_of_date = frames_service.is_ai_frame(asset) and frames_service.frame_out_of_date(
            scene, asset, chain_source_id=chained.get(scene.id)
        )
        # A scene that continues the previous scene's action starts on that scene's last frame.
        # It is made in a later step (`last_frames`), and the app puts it here, so this step has
        # no job for the scene.
        done = scene.id in chained or (scene.first_frame_asset_id is not None and not out_of_date)
        prompt_out_of_date = scene.id in states and states[scene.id].out_of_date
        targets.append(
            _scene_target(
                scene,
                done=done,
                # A prompt being written for the scene is waited for, not reported.
                active=active_frames.get(scene.id) or active_prompts.get(scene.id),
                block=frames_service.scene_block(
                    scene,
                    prompt_out_of_date=prompt_out_of_date,
                    prompt_job_active=False,
                    references_block=cast_service.references_block(scene_cast),
                ),
                # A frame the author uploaded counts as done above, so it is never replaced.
                job_input={
                    "requested": "generate_all",
                    "replace_upload": False,
                    "first_frame_at_click": scene.first_frame_asset_id,
                },
                waits_for=(
                    wait("image_prompts", str(scene.id)),
                    *(
                        wait("cast_images", cast_service.member_key(kind, member.id))
                        for kind, member in scene_cast.references()
                    ),
                ),
            )
        )
    return StepView(targets, block=block)


async def _last_frame_prompts(session: AsyncSession, ctx: RunContext) -> StepView:
    """A scene's last frame prompt is written from text only (its image prompt and its
    descriptions, not the first frame), so it starts as soon as the scene's image prompt is
    written, beside the scene's first frame.
    """
    project = ctx.project
    state = await scenes_service.scenes_state(session, project)
    block = await _prompts_block(session, project, state)
    active = await last_prompts_service.active_prompt_jobs(session, project.id)
    states = await last_prompts_service.prompt_states(session, project, state.scenes)
    frames = await scene_inputs.load_frames(session, state.scenes)

    targets: list[Target] = []
    for scene in state.scenes:
        if _blank(scene.last_frame_description):
            continue  # this scene gets no last frame, so there is nothing to write for it
        out_of_date = scene.id in states and states[scene.id].out_of_date
        # A scene whose last frame the author uploaded needs no prompt: nothing makes a frame.
        has_own_frame = last_frames_service.needs_upload_confirmation(
            scene, frames.get(scene.last_frame_asset_id or 0)
        )
        done = has_own_frame or (not _blank(scene.last_frame_prompt) and not out_of_date)
        targets.append(
            _scene_target(
                scene,
                done=done,
                active=active.get(scene.id),
                block=last_prompts_service.scene_block(scene),
                job_input={"requested": "write_all"},
                waits_for=(wait("image_prompts", str(scene.id)),),
            )
        )
    return StepView(targets, block=block)


async def _last_frames(session: AsyncSession, ctx: RunContext) -> StepView:
    """The scenes that get a last frame, and the scenes that continue the previous scene's action.

    The second kind has nothing to make: its first frame is the previous scene's last frame, which
    the app puts there when that frame is attached (`last_frames.apply_chains`). So it *waits* for
    that scene (`Target.waits_for`). Its own last frame, if it gets one, is edited from that first
    frame, so it waits too.

    A scene that gets a last frame also waits for its own first frame (the frame is edited from
    it) and its own last frame prompt, and for nothing else: it starts the moment both are done,
    while other scenes are still in those steps.
    """
    project = ctx.project
    state = await scenes_service.scenes_state(session, project)
    block = await _prompts_block(session, project, state)
    active_last = await last_frames_service.active_last_frame_jobs(session, project.id)
    active_firsts = await frames_service.active_frame_jobs(session, project.id)
    active_prompts = await last_prompts_service.active_prompt_jobs(session, project.id)
    states = await last_prompts_service.prompt_states(session, project, state.scenes)
    frames = await scene_inputs.load_frames(session, state.scenes)
    chained = await last_frames_service.chain_sources(session, project.id, state.scenes)

    # Pass 1: for each scene, whether it gets a target and whether the target is done.
    done_by_scene: dict[int, bool] = {}
    chain_pending: dict[int, bool] = {}
    for scene in state.scenes:
        first = frames.get(scene.first_frame_asset_id or 0)
        last = frames.get(scene.last_frame_asset_id or 0)
        wants_last = not _blank(scene.last_frame_description)
        last_ok = scene.last_frame_asset_id is not None and not (
            frames_service.is_ai_frame(last) and last_frames_service.frame_out_of_date(scene, last)
        )
        # The first frame is replaced by the chain unless the author uploaded it.
        own_first = scene.first_frame_asset_id is not None and not frames_service.is_ai_frame(first)
        source_id = chained.get(scene.id)
        pending = (
            scene.id in chained
            and not own_first
            and (source_id is None or scene.first_frame_asset_id != source_id)
        )
        chain_pending[scene.id] = pending
        if wants_last or pending:
            done_by_scene[scene.id] = (last_ok or not wants_last) and not pending

    targets: list[Target] = []
    previous: Scene | None = None
    for scene in state.scenes:
        before, previous = previous, scene
        if scene.id not in done_by_scene:
            continue
        done = done_by_scene[scene.id]
        wants_last = not _blank(scene.last_frame_description)
        chain_source = before if chain_pending[scene.id] and before is not None else None
        waits: list[tuple[str, str]] = []
        # Waiting is only for a scene that has not finished: one that is done has delivered.
        if chain_source is not None and not done_by_scene.get(chain_source.id, True):
            waits.append(wait("last_frames", str(chain_source.id)))
        waits_for_chain = bool(waits)
        if wants_last:
            waits.append(wait("first_frames", str(scene.id)))
            waits.append(wait("last_frame_prompts", str(scene.id)))
        block_reason: str | None = None
        if chain_pending[scene.id] and not waits_for_chain:
            block_reason = (
                "The previous scene's last frame could not be used as this scene's first frame."
            )
        elif wants_last:
            block_reason = last_frames_service.scene_block(
                scene,
                frames.get(scene.first_frame_asset_id or 0),
                prompt_out_of_date=scene.id in states and states[scene.id].out_of_date,
                prompt_job_active=scene.id in active_prompts,
                first_frame_job_active=scene.id in active_firsts,
            )
        target = _scene_target(
            scene,
            done=done,
            active=active_last.get(scene.id),
            block=block_reason,
            job_input={
                "requested": "generate_all",
                "replace_upload": False,
                "last_frame_at_click": scene.last_frame_asset_id,
            },
            waits_for=tuple(waits),
        )
        targets.append(target)
    return StepView(targets, block=block)


async def _clips(session: AsyncSession, ctx: RunContext) -> StepView:
    """A scene's clip starts when the scene is ready: its first frame is made and, if it gets
    one, its last frame too. It does not wait for the other scenes' frames. (A scene that gets
    no last frame has no target in `last_frames`, so there is nothing to wait for.)
    """
    project = ctx.project
    state = await scenes_service.scenes_state(session, project)
    block = clips_service.scenes_block_reason(state.job, state.stale_reasons)
    active = await clips_service.active_clip_jobs(session, project.id)

    targets: list[Target] = []
    for scene in state.scenes:
        # A scene shorter than one frame takes no time in the video, so it needs no clip.
        silent = clips_service.target_frames_for(scene, project) < 1
        done = silent or scene.selected_clip_asset_id is not None
        targets.append(
            _scene_target(
                scene,
                done=done,
                active=active.get(scene.id),
                block=clips_service.generation_block(
                    scene, project, scenes_blocked=None, active=None
                ),
                job_input={"requested": "generate_all"},
                waits_for=(
                    wait("first_frames", str(scene.id)),
                    wait("last_frames", str(scene.id)),
                ),
            )
        )
    return StepView(targets, block=block)


async def _render(session: AsyncSession, ctx: RunContext) -> StepView:
    project = ctx.project
    if any(job.status == "succeeded" for job in ctx.run_jobs.get(PROJECT_KEY, [])):
        return StepView([_project_target(done=True, active=None, block=None, job_input={})])

    active = await renders_service.active_render(session, project.id)
    state = await scenes_service.scenes_state(session, project)
    takes = await clips_service.takes_by_scene(session, project.id)
    selected = renders_service.selected_takes(state.scenes, takes)
    block = renders_service.render_block(
        project,
        state.scenes,
        selected,
        plan_job=state.job,
        stale_reasons=state.stale_reasons,
    )
    voiceover = (
        await session.get(Asset, project.voiceover_asset_id)
        if project.voiceover_asset_id is not None
        else None
    )
    job_input: dict[str, Any] = {}
    if block is None and voiceover is None:
        block = "Upload a voiceover first."
    if block is None and voiceover is not None:
        job_input = {
            "requested": "render",
            "timeline": renders_service.build_timeline(project, state.scenes, selected, voiceover),
        }
    return StepView([_project_target(done=False, active=active, block=block, job_input=job_input)])


_Evaluator = Callable[[AsyncSession, RunContext], Coroutine[Any, Any, StepView]]

_EVALUATORS: Final[dict[str, _Evaluator]] = {
    "voiceover": _voiceover,
    "transcribe": _transcribe,
    "scenes": _scenes,
    "cast": _cast,
    "cast_prompts": _cast_prompts,
    "cast_images": _cast_images,
    "cast_assignment": _cast_assignment,
    "descriptions": _descriptions,
    "image_prompts": _image_prompts,
    "first_frames": _first_frames,
    "last_frame_prompts": _last_frame_prompts,
    "last_frames": _last_frames,
    "clips": _clips,
    "render": _render,
}


async def evaluate(session: AsyncSession, step: Step, ctx: RunContext) -> StepView:
    """Reads the database and answers with the step's targets. Read-only."""
    return await _EVALUATORS[step.key](session, ctx)


# --- What the page reads --------------------------------------------------------------------


@dataclass(frozen=True)
class StepState:
    key: str
    label: str
    status: StepStatus
    done: int
    total: int


@dataclass(frozen=True)
class RunState:
    steps: list[StepState]
    problems: list[Problem]


def describe(output: object, run_status: str) -> RunState:
    """The steps and the problems of a run, from its stored output. A run that has not written
    anything yet (still queued) shows every step waiting. A step that was running when the run
    ended is shown as `failed` (the run failed) or `stopped` (it was cancelled).
    """
    data = read_output(output)
    steps: list[StepState] = []
    for step in STEPS:
        entry = data["steps"][step.key]
        # The stored status is one the handler wrote, so it is one of the values above.
        status = cast(StepStatus, entry.get("status", "pending"))
        if status == "running" and run_status in ("failed", "cancelled"):
            status = "failed" if run_status == "failed" else "stopped"
        steps.append(
            StepState(
                key=step.key,
                label=step.label,
                status=status,
                done=int(entry.get("done", 0)),
                total=int(entry.get("total", 0)),
            )
        )
    problems = [
        Problem(
            step_key=str(item.get("step") or ""),
            scene_id=item.get("scene_id"),
            scene_number=item.get("scene_number"),
            tries=int(item.get("tries", 0)),
            message=str(item.get("message", "")),
        )
        for item in data["problems"]
        if isinstance(item, dict)
    ]
    return RunState(steps=steps, problems=problems)
