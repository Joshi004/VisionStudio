"""`/api/projects/{project_id}/story-pipeline`: the whole story, from its text to a video, with
one click (PHASE-030).

- `GET ...` answers everything the panel shows in one call: the steps (for the "Pause after"
  boxes), the newest run with each step's status and progress, its problems and warnings and
  where it is paused, whether a run can start now and why not, the targets a run would replace
  that the user must allow first, and how many tries each target gets.
- `POST .../run` starts the run. Body: `pause_after` (the keys of the steps to pause after, none
  by default), `confirm_overwrite` and `scope` (`all`, the default, or `out_of_date`: only what
  exists and is out of date, and what those regenerations make necessary, PHASE-040;
  422 when nothing is out of date). A run that is already waiting or running is returned and
  no second one is made. 409 while there are targets to replace and `confirm_overwrite` is false.
- `POST .../continue` lets a paused run go on.

Stopping a run is `POST /api/jobs/{id}/cancel`, which also cancels the jobs the run made that
have not started. The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Job
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.services import staleness, story_pipeline, story_pipeline_targets
from app.services.story_pipeline import StepStatus

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_NOT_ALLOWED = {
    422: {
        "model": ErrorResponse,
        "description": "The run cannot start now (no story, or another job is waiting or "
        "running), an unknown step was named, or there is no paused run.",
    }
}
_UNCONFIRMED = {
    409: {
        "model": ErrorResponse,
        "description": "The run would replace what the user chose or wrote, and "
        "`confirm_overwrite` is false.",
    }
}

# How many targets the 409 names before it says "and more".
_MAX_NAMED: int = 5


class PipelineStepOut(BaseModel):
    """One step of the pipeline, for the pause boxes and the list."""

    key: str
    label: str


class PipelineStepProgressOut(BaseModel):
    key: str
    label: str
    status: StepStatus
    # How many targets of the step are done, of how many. 0 of 0 before the run got to it.
    done: int
    total: int
    # How many targets the `out_of_date` scope left as they are (not counted in `done` or
    # `total`). Always 0 for a run of scope `all`.
    left_alone: int


class PipelineProblemOut(BaseModel):
    step: str
    step_label: str
    # The character, scene or shot it is about. Empty for the project.
    target: str
    tries: int
    message: str


class PipelineRunOut(BaseModel):
    job_id: int
    status: JobStatus
    phase: str | None
    # Why the run stopped, when it failed.
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    steps: list[PipelineStepProgressOut]
    problems: list[PipelineProblemOut]
    warnings: list[str]
    # The step the run is paused after, while it waits for Continue. None otherwise.
    paused_at: str | None
    # What the run was started with.
    pause_after: list[str]
    confirm_overwrite: bool
    # What the run makes: everything that is not up to date, or only what is out of date.
    scope: Literal["all", "out_of_date"]
    # How many jobs the run has made so far (a stage that does its work in the run adds none).
    jobs_made: int


class PipelineConfirmationOut(BaseModel):
    step: str
    step_label: str
    target: str
    reason: str


class StoryPipelineOut(BaseModel):
    steps: list[PipelineStepOut]
    # The newest run, whatever its status. None when the project never had one.
    run: PipelineRunOut | None
    can_start: bool
    # Why a run cannot start now, or None.
    start_block: str | None
    # What a run started now would replace, and needs the user's consent for. Empty while a run
    # cannot start.
    confirmations: list[PipelineConfirmationOut]
    # The same for a run of scope `out_of_date`: only what is out of date now.
    regenerate_confirmations: list[PipelineConfirmationOut]
    # How many jobs each target gets per step in one run.
    max_tries: int


class PipelineRunBody(BaseModel):
    # The keys of the steps to pause after. None by default: one click makes the whole video.
    pause_after: list[Annotated[str, Field(max_length=64)]] = Field(
        default_factory=list, max_length=len(story_pipeline.STEP_KEYS)
    )
    # Allows the run to replace what the user chose or wrote (library characters and
    # environments, hand-written relations, a hand-chosen narrator voice).
    confirm_overwrite: bool = False
    # `out_of_date`: regenerate only what exists and is out of date (PHASE-040).
    scope: Literal["all", "out_of_date"] = "all"


class PipelineRunStartedOut(BaseModel):
    job_id: int


def _steps_out() -> list[PipelineStepOut]:
    return [PipelineStepOut(key=step.key, label=step.label) for step in story_pipeline.STEPS]


def _run_out(job: Job) -> PipelineRunOut:
    output = story_pipeline.read_output(job.output)
    options = story_pipeline.RunOptions.from_input(job.input)
    active = job.status in store.ACTIVE_STATUSES
    return PipelineRunOut(
        job_id=job.id,
        status=cast(JobStatus, job.status),
        phase=job.phase,
        error=job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
        steps=[
            PipelineStepProgressOut(
                key=step.key,
                label=step.label,
                status=cast(StepStatus, output["steps"][step.key].get("status", "pending")),
                done=_count(output["steps"][step.key].get("done")),
                total=_count(output["steps"][step.key].get("total")),
                left_alone=_count(output["steps"][step.key].get("left_alone")),
            )
            for step in story_pipeline.STEPS
        ],
        problems=[_problem_out(problem) for problem in output["problems"]],
        warnings=[str(text) for text in output["warnings"]],
        # A run that has ended is not waiting for anybody.
        paused_at=output["paused_at"] if active else None,
        pause_after=[key for key in story_pipeline.STEP_KEYS if key in options.pause_after],
        confirm_overwrite=options.confirm_overwrite,
        scope=options.scope,
        jobs_made=len(output["job_ids"]),
    )


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _problem_out(problem: Any) -> PipelineProblemOut:
    data: dict[str, Any] = problem if isinstance(problem, dict) else {}
    step = str(data.get("step", ""))
    return PipelineProblemOut(
        step=step,
        step_label=story_pipeline.STEP_LABELS.get(step, step),
        target=str(data.get("label", "")),
        tries=_count(data.get("tries")),
        message=str(data.get("message", "")),
    )


@router.get(
    "/projects/{project_id}/story-pipeline",
    response_model=StoryPipelineOut,
    responses=_NOT_FOUND,
)
async def get_story_pipeline(project_id: int, session: SessionDep) -> StoryPipelineOut:
    project = await load_project(session, project_id)
    run = await store.latest_job(session, project.id, story_pipeline.JOB_TYPE)
    running = run is not None and run.status in store.ACTIVE_STATUSES
    if running:
        blocked: str | None = "The pipeline is already running."
    else:
        blocked = story_pipeline.start_block(
            project, await story_pipeline.active_jobs(session, project.id)
        )
    # Reading what a run would replace is heavy (it reads five stages): only when it is of use.
    pending = (
        [] if blocked is not None else await story_pipeline_targets.confirmations(session, project)
    )
    return StoryPipelineOut(
        steps=_steps_out(),
        run=_run_out(run) if run is not None else None,
        can_start=blocked is None,
        start_block=blocked,
        confirmations=[_confirmation_out(item) for item in pending],
        regenerate_confirmations=[_confirmation_out(item) for item in pending if item.stale],
        max_tries=story_pipeline.MAX_TRIES,
    )


def _confirmation_out(item: story_pipeline_targets.Confirmation) -> PipelineConfirmationOut:
    return PipelineConfirmationOut(
        step=item.step_key, step_label=item.step_label, target=item.target, reason=item.reason
    )


def _unconfirmed_message(
    pending: list[story_pipeline_targets.Confirmation],
) -> str:
    named = [
        f"{item.step_label}: {item.target}" if item.target else item.step_label
        for item in pending[:_MAX_NAMED]
    ]
    more = len(pending) - len(named)
    tail = f" and {more} more" if more > 0 else ""
    return (
        "This run would replace what you chose or wrote (" + "; ".join(named) + tail + "). "
        "Tick “Allow overwrite” to confirm, or leave those as they are by fixing them first."
    )


@router.post(
    "/projects/{project_id}/story-pipeline/run",
    response_model=PipelineRunStartedOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_NOT_ALLOWED, **_UNCONFIRMED},
)
async def run_story_pipeline(
    project_id: int, body: PipelineRunBody, session: SessionDep
) -> PipelineRunStartedOut:
    """Starts the run. If a run is already waiting or running, its job id is returned and no
    second run is made.
    """
    project = await load_project(session, project_id)
    unknown = [key for key in body.pause_after if key not in story_pipeline.STEP_KEYS]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"There is no step {', '.join(repr(key) for key in unknown)}.",
        )
    if await story_pipeline.active_run(session, project.id) is None:
        blocked = story_pipeline.start_block(
            project, await story_pipeline.active_jobs(session, project.id)
        )
        if blocked is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, blocked)
        if (
            body.scope == story_pipeline.SCOPE_OUT_OF_DATE
            and (await staleness.overview(session, project)).count == 0
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Nothing is out of date, so there is nothing to regenerate.",
            )
        pending = await story_pipeline_targets.confirmations(session, project)
        if body.scope == story_pipeline.SCOPE_OUT_OF_DATE:
            pending = [item for item in pending if item.stale]
        if pending and not body.confirm_overwrite:
            raise HTTPException(status.HTTP_409_CONFLICT, _unconfirmed_message(pending))
    try:
        job, _created = await story_pipeline.start_run(
            session,
            project,
            pause_after=body.pause_after,
            confirm_overwrite=body.confirm_overwrite,
            scope=body.scope,
        )
    except story_pipeline.StoryPipelineError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return PipelineRunStartedOut(job_id=job.id)


@router.post(
    "/projects/{project_id}/story-pipeline/continue",
    response_model=PipelineRunStartedOut,
    responses={**_NOT_FOUND, **_NOT_ALLOWED},
)
async def continue_story_pipeline(project_id: int, session: SessionDep) -> PipelineRunStartedOut:
    """Lets a paused run go on."""
    project = await load_project(session, project_id)
    try:
        job = await story_pipeline.continue_run(session, project)
    except story_pipeline.StoryPipelineError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return PipelineRunStartedOut(job_id=job.id)
