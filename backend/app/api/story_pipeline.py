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
  `scenes` (SCN-004) limits the run to those scenes (their ids): it makes only their targets and
  the story-wide work that is missing, no music and no full video, and ends with a render of each
  scene. `remake_from` (a step of `remake_steps`, only with scenes) makes that step's targets in
  those scenes again once, although they are up to date. A run of exactly one scene also pushes
  that scene to the front of the GPU server's queue (SCN-002). `GET` takes the same two choices
  as query parameters, so that `confirmations` are the ones that run would need.
- `POST .../continue` lets a paused run go on. A run waiting at a review point (PHASE-041) takes
  the optional body `rejected` (`{step, target}` pairs): those targets are made again and the
  run waits at the same review point once more.

The review points are the project's own setting (`PATCH /api/projects/{id}`); a run copies them
when it starts. `GET` lists them and, while a run waits at one, what there is to review.

Stopping a run is `POST /api/jobs/{id}/cancel`, which also cancels the jobs the run made that
have not started. The answers never return ORM objects.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Job, Project
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.services import (
    gpu_priority,
    review_points,
    staleness,
    story_pipeline,
    story_pipeline_targets,
)
from app.services.story_pipeline import StepStatus

router = APIRouter()
_logger = logging.getLogger(__name__)

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
# The most targets one answer at a review point may reject (a shot per target is the biggest).
_MAX_REJECTED: int = 500
# The most scenes one run may be limited to.
_MAX_SCENES: int = 200


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


class PipelineSceneOut(BaseModel):
    """A scene a run is limited to."""

    id: str
    index: int | None
    title: str


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
    # The review points the run was started with, and the one it waits at (None unless it is
    # waiting for the user to press Continue).
    review_points: list[str]
    review_at: str | None
    # What the run makes: everything that is not up to date, or only what is out of date.
    scope: Literal["all", "out_of_date"]
    # The scenes the run is limited to, in story order (SCN-004). Empty: the whole story.
    scenes: list[PipelineSceneOut]
    # The step the run makes again in those scenes, or None.
    remake_from: str | None
    # How many jobs the run has made so far (a stage that does its work in the run adds none).
    jobs_made: int


class PipelineConfirmationOut(BaseModel):
    step: str
    step_label: str
    target: str
    reason: str


class ReviewPointOut(BaseModel):
    """A place a project can ask the pipeline to wait at, with the steps it waits for."""

    key: review_points.ReviewPointKey
    label: str
    steps: list[str]


class ReviewTargetOut(BaseModel):
    """One thing to approve or reject. A step with a single target for the project has the
    step's own label.
    """

    key: str
    label: str


class ReviewStepOut(BaseModel):
    key: str
    label: str
    targets: list[ReviewTargetOut]


class ReviewOut(BaseModel):
    """What the user can review while the run waits at a review point."""

    key: review_points.ReviewPointKey
    label: str
    steps: list[ReviewStepOut]


class StoryPipelineOut(BaseModel):
    steps: list[PipelineStepOut]
    # The review points a project can enable, in the order of the pipeline.
    review_points: list[ReviewPointOut]
    # What there is to review, while the newest run waits at a review point. None otherwise.
    review: ReviewOut | None
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
    # The steps a run of some scenes can make again from, in the order of the pipeline.
    remake_steps: list[PipelineStepOut]


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
    # SCN-004: limit the run to these scenes (their ids). Empty: the whole story.
    scenes: list[Annotated[str, Field(max_length=64)]] = Field(
        default_factory=list, max_length=_MAX_SCENES
    )
    # SCN-004: make this step again in those scenes, although it is up to date.
    remake_from: Annotated[str, Field(max_length=64)] | None = None


class PipelineRunStartedOut(BaseModel):
    job_id: int


class RejectedTarget(BaseModel):
    step: Annotated[str, Field(max_length=64)]
    target: Annotated[str, Field(max_length=200)]


class PipelineContinueBody(BaseModel):
    # Targets the user rejected at a review point: they are made again. None: all approved.
    rejected: list[RejectedTarget] = Field(default_factory=list, max_length=_MAX_REJECTED)


def _steps_out() -> list[PipelineStepOut]:
    return [PipelineStepOut(key=step.key, label=step.label) for step in story_pipeline.STEPS]


def _remake_steps_out() -> list[PipelineStepOut]:
    return [
        PipelineStepOut(key=step.key, label=step.label)
        for step in story_pipeline.STEPS
        if step.key in story_pipeline.REMAKE_STEPS
    ]


def _scenes_out(scenes: list[dict[str, Any]], chosen: frozenset[str]) -> list[PipelineSceneOut]:
    """The scenes of a run's choice, in story order."""
    return [
        PipelineSceneOut(
            id=item["id"],
            index=item["index"] if isinstance(item.get("index"), int) else None,
            title=str(item.get("title") or item["id"]),
        )
        for item in scenes
        if item["id"] in chosen
    ]


def _review_points_out() -> list[ReviewPointOut]:
    return [
        ReviewPointOut(key=point.key, label=point.label, steps=list(point.steps))
        for point in review_points.REVIEW_POINTS
    ]


def _review_at_of(run: Job) -> str | None:
    """The review point a run waits at, or None."""
    return story_pipeline.read_output(run.output)["review_at"]


async def _review_out(
    session: AsyncSession,
    project: Project,
    review_at: str | None,
    options: story_pipeline.RunOptions,
) -> ReviewOut | None:
    """What the user can approve or reject at the review point the run waits at."""
    point = review_points.POINTS_BY_KEY.get(review_at) if review_at is not None else None
    if point is None:
        return None
    steps = await story_pipeline_targets.review_targets(session, project, point.key, options)
    return ReviewOut(
        key=point.key,
        label=point.label,
        steps=[
            ReviewStepOut(
                key=item.step_key,
                label=item.step_label,
                targets=[
                    ReviewTargetOut(key=target.key, label=target.label or item.step_label)
                    for target in item.targets
                ],
            )
            for item in steps
        ],
    )


def _run_out(job: Job, scenes: list[dict[str, Any]]) -> PipelineRunOut:
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
        review_points=review_points.normalize(options.review_points),
        review_at=output["review_at"] if active else None,
        scope=options.scope,
        scenes=_scenes_out(scenes, options.scenes),
        remake_from=options.remake_from,
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
async def get_story_pipeline(
    project_id: int,
    session: SessionDep,
    scenes: Annotated[
        list[Annotated[str, Field(max_length=64)]], Query(max_length=_MAX_SCENES)
    ] = [],  # noqa: B006
    remake_from: Annotated[str | None, Query(max_length=64)] = None,
) -> StoryPipelineOut:
    """The panel's state. `scenes` and `remake_from` are what a run would be started with, so
    `confirmations` say what that run would replace (SCN-004).
    """
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
    chosen = _choice(scenes, remake_from)
    pending = (
        []
        if blocked is not None
        else await story_pipeline_targets.confirmations(session, project, chosen)
    )
    review_at = _review_at_of(run) if run is not None and running else None
    run_options = (
        story_pipeline.RunOptions.from_input(run.input)
        if run is not None
        else story_pipeline.RunOptions()
    )
    return StoryPipelineOut(
        steps=_steps_out(),
        review_points=_review_points_out(),
        review=await _review_out(session, project, review_at, run_options),
        run=(
            _run_out(run, await story_pipeline.scene_items(session, project.id))
            if run is not None
            else None
        ),
        can_start=blocked is None,
        start_block=blocked,
        confirmations=[_confirmation_out(item) for item in pending],
        regenerate_confirmations=[_confirmation_out(item) for item in pending if item.stale],
        max_tries=story_pipeline.MAX_TRIES,
        remake_steps=_remake_steps_out(),
    )


def _choice(scenes: list[str], remake_from: str | None) -> story_pipeline.RunOptions:
    """The options a run started with these choices would have (what `confirmations` needs)."""
    return story_pipeline.RunOptions(
        scenes=frozenset(scenes),
        remake_from=remake_from if scenes and remake_from in story_pipeline.REMAKE_STEPS else None,
    )


def _confirmation_out(item: story_pipeline_targets.Confirmation) -> PipelineConfirmationOut:
    return PipelineConfirmationOut(
        step=item.step_key, step_label=item.step_label, target=item.target, reason=item.reason
    )


async def _nothing_out_of_date(session: AsyncSession, project: Project, scenes: set[str]) -> bool:
    """Whether there is nothing for a run of scope `out_of_date` to make: nothing is out of
    date in the project, or in the chosen scenes when there are some.
    """
    overview = await staleness.overview(session, project)
    if not scenes:
        return overview.count == 0
    return not any(item.scene_id in scenes for group in overview.groups for item in group.items)


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
    scenes = set(body.scenes)
    if body.remake_from is not None and (
        body.remake_from not in story_pipeline.REMAKE_STEPS or not scenes
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A scene can only be made again from a step of the list, and the run needs a scene.",
        )
    if await story_pipeline.active_run(session, project.id) is None:
        blocked = story_pipeline.start_block(
            project, await story_pipeline.active_jobs(session, project.id)
        )
        if blocked is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, blocked)
        if (
            body.scope == story_pipeline.SCOPE_OUT_OF_DATE
            and body.remake_from is None
            and await _nothing_out_of_date(session, project, scenes)
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Nothing is out of date in the chosen scenes, so there is nothing to regenerate."
                if scenes
                else "Nothing is out of date, so there is nothing to regenerate.",
            )
        pending = await story_pipeline_targets.confirmations(
            session, project, _choice(body.scenes, body.remake_from)
        )
        if body.scope == story_pipeline.SCOPE_OUT_OF_DATE:
            pending = [item for item in pending if item.stale]
        if pending and not body.confirm_overwrite:
            raise HTTPException(status.HTTP_409_CONFLICT, _unconfirmed_message(pending))
    try:
        job, created = await story_pipeline.start_run(
            session,
            project,
            pause_after=body.pause_after,
            confirm_overwrite=body.confirm_overwrite,
            scope=body.scope,
            scenes=body.scenes,
            remake_from=body.remake_from,
        )
    except story_pipeline.StoryPipelineError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if created and len(scenes) == 1:
        # The owner asked for this scene now (SCN-002): its clips go to the front of the queue.
        # Done before the nudge, so the first clips are sent at level 1.
        (scene_id,) = scenes
        try:
            await gpu_priority.push_scene(session, project, scene_id)
        except gpu_priority.PushError:
            _logger.warning("scene '%s' of project %d could not be pushed", scene_id, project.id)
    dispatcher.nudge()
    return PipelineRunStartedOut(job_id=job.id)


@router.post(
    "/projects/{project_id}/story-pipeline/continue",
    response_model=PipelineRunStartedOut,
    responses={**_NOT_FOUND, **_NOT_ALLOWED},
)
async def continue_story_pipeline(
    project_id: int, session: SessionDep, body: PipelineContinueBody | None = None
) -> PipelineRunStartedOut:
    """Lets a paused run go on. At a review point, the targets in `rejected` are made again and
    the run waits at the same review point once more; the others count as approved.
    """
    project = await load_project(session, project_id)
    rejected = await _check_rejected(session, project, body.rejected if body is not None else [])
    try:
        job = await story_pipeline.continue_run(session, project, rejected)
    except story_pipeline.StoryPipelineError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return PipelineRunStartedOut(job_id=job.id)


async def _check_rejected(
    session: AsyncSession, project: Project, rejected: list[RejectedTarget]
) -> dict[str, list[str]]:
    """The rejected targets by step, each checked against what the review point lists. 422 for
    one that is not there, naming it.
    """
    if not rejected:
        return {}
    run = await story_pipeline.active_run(session, project.id)
    if run is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "There is no run going on for this project."
        )
    review_at = _review_at_of(run)
    if review_at is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The run is not waiting at a review point, so there is nothing to reject.",
        )
    listed = {
        item.step_key: item
        for item in await story_pipeline_targets.review_targets(
            session, project, review_at, story_pipeline.RunOptions.from_input(run.input)
        )
    }
    found: dict[str, list[str]] = {}
    for entry in rejected:
        item = listed.get(entry.step)
        if item is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"The step {entry.step!r} is not part of this review point.",
            )
        if entry.target not in {target.key for target in item.targets}:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{item.step_label}: there is nothing to reject for {entry.target!r}.",
            )
        found.setdefault(entry.step, []).append(entry.target)
    return found
