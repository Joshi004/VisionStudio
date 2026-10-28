"""Two cheap, read-only answers about a project, for the pipeline board.

- `GET /api/projects/{project_id}/activity`: a `revision` that changes whenever anything in the
  project changes (a job, a saved result, an edit), and how many jobs are queued, running or
  paused. Two small queries; no stage is computed. A client asks it every few seconds and
  fetches what is heavy only when the revision is new.
- `GET /api/projects/{project_id}/pipeline-board`: one row for each step of the story
  pipeline (status, how many targets are done, what it waits for, why it cannot go on), and
  the header: the newest run, whether it is paused or at a review point, whether jobs are
  going on by hand, and which steps are ready to start. It is made from what the pipeline run
  itself looks at (`services/story_pipeline_targets.py`), so it says what a run would.

Neither writes anything. The answers never return ORM objects.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.session import SessionDep
from app.services import activity as activity_service
from app.services import pipeline_board

router = APIRouter()

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such project."}
}


class ActivityOut(BaseModel):
    # Changes whenever anything in the project changes. Compare it, never read it.
    revision: str
    # Jobs waiting to start (not paused, not the pipeline run), and jobs running.
    queued: int
    running: int
    # Queued jobs held back because the GPU API changed or is not approved.
    paused: int
    # A run of the whole pipeline is waiting or running (it may be paused or at a review).
    pipeline_active: bool


class BoardStepOut(BaseModel):
    key: str
    label: str
    group: str
    needs: list[str]
    status: Literal["off", "running", "attention", "out_of_date", "done", "waiting", "ready"]
    # How many targets (characters, scenes, shots, or the project) are done, of how many.
    done: int
    total: int
    # Targets with work going on, out of date, and failed.
    active: int
    stale: int
    failed: int
    # The steps it needs that are not done yet.
    blocked_by: list[str]
    # Why a target failed or cannot go on, when there is one. None otherwise.
    blocked_reason: str | None


class BoardRunOut(BaseModel):
    job_id: int
    status: JobStatus
    phase: str | None
    # The step the run is paused after, and the review point it waits at. None unless the run
    # is waiting for the user to press Continue.
    paused_at: str | None
    review_at: str | None


class PipelineBoardOut(BaseModel):
    revision: str
    mode: Literal[
        "pipeline_review", "pipeline_paused", "pipeline_running", "manual_running", "idle"
    ]
    # The project's newest run, whatever its status. None when it never had one.
    run: BoardRunOut | None
    queued: int
    running: int
    paused: int
    # The steps that can be started by hand now, in the order of the pipeline.
    next_keys: list[str]
    steps: list[BoardStepOut]


@router.get(
    "/projects/{project_id}/activity",
    response_model=ActivityOut,
    responses=_NOT_FOUND,
)
async def get_activity(project_id: int, session: SessionDep) -> ActivityOut:
    project = await load_project(session, project_id)
    activity = await activity_service.snapshot(session, project.id)
    return ActivityOut(
        revision=activity.revision,
        queued=activity.queued,
        running=activity.running,
        paused=activity.paused,
        pipeline_active=activity.pipeline_active,
    )


@router.get(
    "/projects/{project_id}/pipeline-board",
    response_model=PipelineBoardOut,
    responses=_NOT_FOUND,
)
async def get_pipeline_board(project_id: int, session: SessionDep) -> PipelineBoardOut:
    project = await load_project(session, project_id)
    board = await pipeline_board.build(session, project)
    return PipelineBoardOut(
        revision=board.revision,
        mode=board.mode,
        run=(
            BoardRunOut(
                job_id=board.run.job_id,
                status=cast(JobStatus, board.run.status),
                phase=board.run.phase,
                paused_at=board.run.paused_at,
                review_at=board.run.review_at,
            )
            if board.run is not None
            else None
        ),
        queued=board.queued,
        running=board.running,
        paused=board.paused,
        next_keys=list(board.next_keys),
        steps=[
            BoardStepOut(
                key=step.key,
                label=step.label,
                group=step.group,
                needs=list(step.needs),
                status=step.status,
                done=step.counts.done,
                total=step.counts.total,
                active=step.counts.active,
                stale=step.counts.stale,
                failed=step.counts.failed,
                blocked_by=list(step.blocked_by),
                blocked_reason=step.counts.reason,
            )
            for step in board.steps
        ],
    )
