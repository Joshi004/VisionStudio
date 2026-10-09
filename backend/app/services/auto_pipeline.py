"""The automatic video pipeline: the steps, and what "done" means for each of them.

One run (an `auto_pipeline` job, driven by `jobs/auto_pipeline.py`) goes through `STEPS` in
order. It creates the same jobs the manual buttons create, and moves on to the next step only
when every scene (or the project, for a project-level step) has finished the current one.

This module holds the rules, so the handler only has to orchestrate them:

- `evaluate`: for one step, reads the database and answers with the targets of the step (each
  scene, or the project) and whether each is done, being worked on, or cannot get a job.
  It reuses the rules of the manual steps (`is_candidate`, `scene_block`, `generation_block`,
  `render_block` and so on), so the run never does what the buttons would refuse.
- `plan_step`: pure. From those targets and the jobs this run has already made for them, it
  decides what to do now: wait, create the next job, or report a problem. A target gets at most
  `MAX_TRIES` jobs from one run per step.
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
from app.services import clips as clips_service
from app.services import first_frames as frames_service
from app.services import image_prompts as prompts_service
from app.services import renders as renders_service
from app.services import scene_cuts, scene_inputs, scene_planner, transcript_matching
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
    # One job per scene, or one for the project.
    per_scene: bool
    # What is still missing when a job finished and its target is not done (for the report).
    missing: str
    # The step asks the language model: a second try must not reuse the stored answer.
    asks_model: bool = False


STEPS: Final[tuple[Step, ...]] = (
    Step(
        "transcribe",
        "Transcribe the voiceover",
        transcripts_service.TRANSCRIBE_JOB,
        "gpu",
        False,
        "a current transcript",
    ),
    Step(
        "scenes",
        "Propose scenes",
        scenes_service.PLAN_JOB,
        "llm",
        False,
        "scenes that match the script",
        asks_model=True,
    ),
    Step(
        "descriptions",
        "Draft descriptions",
        DRAFT_JOB,
        "llm",
        False,
        "a description for every scene",
        asks_model=True,
    ),
    Step(
        "image_prompts",
        "Write image prompts",
        prompts_service.IMAGE_PROMPT_JOB,
        "llm",
        True,
        "an image prompt",
        asks_model=True,
    ),
    Step(
        "first_frames",
        "Make first frames",
        frames_service.FRAME_JOB,
        "image",
        True,
        "a first frame",
    ),
    Step(
        "clips",
        "Generate clips",
        clips_service.GENERATE_JOB,
        "gpu",
        True,
        "a clip",
    ),
    Step(
        "render",
        "Render the final video",
        renders_service.RENDER_JOB,
        "local",
        False,
        "a finished video",
    ),
)
STEP_KEYS: Final = tuple(step.key for step in STEPS)


def step_index(key: object) -> int:
    return STEP_KEYS.index(key) if isinstance(key, str) and key in STEP_KEYS else 0


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


@dataclass(frozen=True)
class Problem:
    scene_id: int | None
    scene_number: int | None
    tries: int
    message: str

    def text(self) -> str:
        message = self.message if self.message.endswith((".", "!", "?")) else f"{self.message}."
        return message if self.scene_number is None else f"Scene {self.scene_number}: {message}"

    def as_json(self, step_key: str) -> dict[str, Any]:
        return {
            "step": step_key,
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

    @property
    def complete(self) -> bool:
        return self.done == self.total


def _short(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= _ERROR_MAX_CHARS:
        return one_line
    return f"{one_line[: _ERROR_MAX_CHARS - 1]}…"


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


def plan_step(step: Step, view: StepView, run_jobs: Mapping[str, Sequence[Job]]) -> StepPlan:
    """What to do now about a step. Pure.

    For each target that is not done: wait when a job is in progress for it; report it when no
    job can be made or it has had `MAX_TRIES`; otherwise create the next job.
    """
    pending = [target for target in view.targets if not target.done]
    waiting = 0
    creates: list[Create] = []
    problems: list[Problem] = []

    for target in pending:
        tried = run_jobs.get(target.key, [])
        if target.active is not None or any(job.status in store.ACTIVE_STATUSES for job in tried):
            waiting += 1
        elif view.block is not None:
            continue  # reported once, below
        elif target.block is not None:
            problems.append(Problem(target.scene_id, target.scene_number, len(tried), target.block))
        elif len(tried) >= MAX_TRIES:
            problems.append(
                Problem(
                    target.scene_id,
                    target.scene_number,
                    len(tried),
                    exhausted_message(step, tried),
                )
            )
        else:
            creates.append(Create(target, retry=bool(tried)))

    if view.block is not None and pending:
        problems.append(Problem(None, None, 0, view.block))

    return StepPlan(
        done=len(view.targets) - len(pending),
        total=len(view.targets),
        waiting=waiting,
        creates=creates,
        problems=problems,
    )


def failure_message(number: int, total: int, step: Step, problems: Sequence[Problem]) -> str:
    """What a stopped run says: the step it stopped at, and what is wrong."""
    shown = problems[:_MAX_PROBLEMS_SHOWN]
    parts = " ".join(problem.text() for problem in shown)
    more = len(problems) - len(shown)
    tail = f" And {more} more." if more > 0 else ""
    return f"Stopped at step {number} of {total}, {step.label.lower()}. {parts}{tail}"


# --- The run's stored state -----------------------------------------------------------------


def new_output() -> dict[str, Any]:
    """The output of a run that has just started: every step waiting, no job made yet."""
    return {
        "step": STEPS[0].key,
        "steps": {step.key: {"status": "pending", "done": 0, "total": 0} for step in STEPS},
        # step key -> target key -> ids of the jobs this run made, oldest first.
        "jobs": {step.key: {} for step in STEPS},
        "problems": [],
    }


def read_output(value: object) -> dict[str, Any]:
    """A copy of a run's stored output that is safe to change (the stored JSON is replaced by a
    new object, never changed in place). Anything that is not a run's output starts afresh.
    """
    if (
        not isinstance(value, dict)
        or value.get("step") not in STEP_KEYS
        or not isinstance(value.get("steps"), dict)
        or not isinstance(value.get("jobs"), dict)
    ):
        return new_output()
    output: dict[str, Any] = copy.deepcopy(value)
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


def start_block(project: Project, active: Sequence[Job]) -> str | None:
    """Why a run cannot start now, or None. Pure. The run waits for no other job: two kinds of
    work on one project at once could replace each other's results.
    """
    if project.voiceover_asset_id is None:
        return "Upload a voiceover first."
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
    return await store.create_job(
        session,
        project_id=project.id,
        type=step.job_type,
        provider=step.provider,
        scene_id=create.target.scene_id,
        input=job_input,
        commit=False,
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
) -> Target:
    return Target(
        key=str(scene.id),
        scene_id=scene.id,
        scene_number=scene.index + 1,
        done=done,
        active=active,
        block=None if done else block,
        job_input=job_input,
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
    project = ctx.project
    state = await scenes_service.scenes_state(session, project)
    block = await _prompts_block(session, project, state)
    active_frames = await frames_service.active_frame_jobs(session, project.id)
    active_prompts = await prompts_service.active_prompt_jobs(session, project.id)
    states = await prompts_service.prompt_states(session, project, state.scenes)
    frames = await scene_inputs.load_frames(session, state.scenes)

    targets: list[Target] = []
    for scene in state.scenes:
        asset = frames.get(scene.first_frame_asset_id or 0)
        out_of_date = frames_service.is_ai_frame(asset) and frames_service.frame_out_of_date(
            scene, asset
        )
        done = scene.first_frame_asset_id is not None and not out_of_date
        prompt_out_of_date = scene.id in states and states[scene.id].out_of_date
        targets.append(
            _scene_target(
                scene,
                done=done,
                # A prompt being written for the scene is waited for, not reported.
                active=active_frames.get(scene.id) or active_prompts.get(scene.id),
                block=frames_service.scene_block(
                    scene, prompt_out_of_date=prompt_out_of_date, prompt_job_active=False
                ),
                # A frame the author uploaded counts as done above, so it is never replaced.
                job_input={
                    "requested": "generate_all",
                    "replace_upload": False,
                    "first_frame_at_click": scene.first_frame_asset_id,
                },
            )
        )
    return StepView(targets, block=block)


async def _clips(session: AsyncSession, ctx: RunContext) -> StepView:
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
    "transcribe": _transcribe,
    "scenes": _scenes,
    "descriptions": _descriptions,
    "image_prompts": _image_prompts,
    "first_frames": _first_frames,
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
            scene_id=item.get("scene_id"),
            scene_number=item.get("scene_number"),
            tries=int(item.get("tries", 0)),
            message=str(item.get("message", "")),
        )
        for item in data["problems"]
        if isinstance(item, dict)
    ]
    return RunState(steps=steps, problems=problems)
