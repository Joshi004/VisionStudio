"""`/api/projects/{project_id}/footage`: the research rounds of the footage layer (FTG-007).

- `GET ...` answers where the project's footage stands: each mark that counts and whether it has
  footage (a file of the owner's, a reviewed round) or the owner chose none, the newest round (its
  folder on the Mac and whether the marks changed since its brief), what the owner has to do
  next, the newest brief job, and the prompt to paste into Cursor or Claude. A project without
  footage reads nothing from the tables.
- `POST .../brief` starts the `write_footage_brief` job: it writes the next round's folder and
  brief for the marks that are waiting. 422 with the reason when it cannot be written now.
- `POST .../continue-without` sets "no footage here" on every waiting mark, so the full render can
  go on. 422 when a mark is not decided on yet or nothing is waiting.
- `DELETE .../marks/{mark_id}/no-footage` takes that choice off one mark, so it waits again.

The import of a round and the review come with FTG-011 and FTG-012. The rows and the files are
made by `app/services/footage_rounds.py`. The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import footage_rounds

router = APIRouter()

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such project."}
}
_REFUSED: dict[int | str, dict[str, Any]] = {
    422: {
        "model": ErrorResponse,
        "description": "The project has no footage, the marks are not ready, nothing changed, "
        "nothing is waiting, or the files folder is not available.",
    }
}
_MARK_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such project or footage mark."}
}

RoundStatus = Literal["brief_written", "imported", "reviewed"]
MarkState = Literal["owner_file", "reviewed", "no_footage", "waiting"]


class FootageRoundOut(BaseModel):
    round_id: str
    round_no: int
    # The round's folder on the Mac, or null when the backend does not know where the files folder
    # is on the Mac. `folder` is relative to the files folder.
    host_folder: str | None
    folder: str
    status: RoundStatus
    # The marks that count now are not the marks of this round's brief.
    out_of_date: bool
    # How many marks the brief carries.
    marks: int
    created_at: datetime


class FootageBriefJobOut(BaseModel):
    """The newest `write_footage_brief` job of the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class FootageMarkStateOut(BaseModel):
    id: str
    text: str
    # `owner_file`: the owner's own file is on it. `reviewed`: a reviewed round covers it.
    # `no_footage`: the owner chose none. `waiting`: it needs research.
    state: MarkState


class FootageStateOut(BaseModel):
    # False for a story, a lines explainer and a project with footage off.
    wanted: bool
    # How many marks count now (not dropped, words still in the story).
    marks_count: int
    # Of those, how many have footage (an owner's file or a reviewed round), how many the owner
    # chose no footage for, and how many wait for research.
    covered_marks: int
    skipped_marks: int
    waiting_marks: int
    # What stops the marks from being sent to research (GLM's proposals not decided on, marks
    # whose words changed). Empty when nothing does.
    pending: list[str]
    # What the owner has to do next outside the app, or null.
    awaiting: str | None
    # The `footage` step is complete.
    done: bool
    # Why a brief cannot be written now, or null when one can be.
    blocked_reason: str | None
    # A brief can be written now (and no brief job is going on).
    can_write_brief: bool
    # Continue without footage can be pressed now.
    can_continue_without: bool
    marks: list[FootageMarkStateOut]
    round: FootageRoundOut | None
    job: FootageBriefJobOut | None
    # The prompt to paste into Cursor or Claude, and the skill it uses.
    prompt: str
    skill: str


class FootageBriefRun(BaseModel):
    job_id: int


def _active(job_status: str) -> bool:
    return job_status in ("queued", "running")


async def _state(session: AsyncSession, project: Project) -> FootageStateOut:
    state = await footage_rounds.state(session, project)
    row = state.round
    job = state.job
    reason = footage_rounds.refusal(state, project) if state.wanted else None
    covered = [mark for mark in state.marks if mark["id"] in state.covered]
    skipped = [
        mark for mark in covered if state.covered[mark["id"]] == footage_rounds.COVERED_NO_FOOTAGE
    ]
    return FootageStateOut(
        wanted=state.wanted,
        marks_count=len(state.marks),
        covered_marks=len(covered) - len(skipped),
        skipped_marks=len(skipped),
        waiting_marks=len(state.waiting),
        pending=state.pending,
        awaiting=footage_rounds.awaiting_text(state),
        done=footage_rounds.is_done(state),
        blocked_reason=reason,
        can_write_brief=state.wanted
        and reason is None
        and not (job is not None and _active(job.status)),
        can_continue_without=state.wanted and not state.pending and bool(state.waiting),
        marks=[
            FootageMarkStateOut(
                id=mark["id"],
                text=mark["text"],
                state=cast(MarkState, state.covered.get(mark["id"], "waiting")),
            )
            for mark in state.marks
        ],
        round=(
            FootageRoundOut(
                round_id=f"r{row.round_no}",
                round_no=row.round_no,
                host_folder=state.host_folder,
                folder=row.folder,
                status=cast(RoundStatus, state.status),
                out_of_date=not state.current,
                marks=len(row.brief.get("marks", [])) if isinstance(row.brief, dict) else 0,
                created_at=row.created_at,
            )
            if row is not None
            else None
        ),
        job=(
            FootageBriefJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        prompt=footage_rounds.README_PROMPT,
        skill=footage_rounds.SKILL_NAME,
    )


@router.get(
    "/projects/{project_id}/footage",
    response_model=FootageStateOut,
    responses=_NOT_FOUND,
)
async def get_footage(project_id: int, session: SessionDep) -> FootageStateOut:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/footage/brief",
    response_model=FootageBriefRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_REFUSED},
)
async def write_footage_brief(project_id: int, session: SessionDep) -> FootageBriefRun:
    """Starts the job that writes the next round's brief. If one is already waiting or running
    for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await footage_rounds.start_brief(session, project)
    except footage_rounds.FootageRoundsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return FootageBriefRun(job_id=job.id)


@router.post(
    "/projects/{project_id}/footage/continue-without",
    response_model=FootageStateOut,
    responses={**_NOT_FOUND, **_REFUSED},
)
async def continue_without_footage(project_id: int, session: SessionDep) -> FootageStateOut:
    """Sets "no footage here" on every mark that is waiting, as one decision version."""
    project = await load_project(session, project_id)
    try:
        await footage_rounds.continue_without_footage(session, project)
    except footage_rounds.FootageRoundsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _state(session, project)


@router.delete(
    "/projects/{project_id}/footage/marks/{mark_id}/no-footage",
    response_model=FootageStateOut,
    responses={**_MARK_NOT_FOUND, **_REFUSED},
)
async def undo_no_footage(project_id: int, mark_id: str, session: SessionDep) -> FootageStateOut:
    """Takes "no footage here" off one mark, so it waits for research again."""
    project = await load_project(session, project_id)
    try:
        await footage_rounds.undo_no_footage(session, project, mark_id)
    except footage_rounds.UnknownMarkError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except footage_rounds.FootageRoundsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _state(session, project)
