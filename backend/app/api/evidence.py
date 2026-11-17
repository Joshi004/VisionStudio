"""`/api/projects/{project_id}/evidence`: the research rounds of the evidence layer (EVD-003).

- `GET ...` answers where the project's evidence stands: the newest round (its folder on the Mac,
  whether its results are imported and reviewed, and whether the claims changed since its brief),
  what the owner has to do next, the newest brief job, and the prompt to paste into Cursor or
  Claude. A project without evidence reads nothing from the tables.
- `POST .../brief` starts the `write_evidence_brief` job: it writes the next round's folder and
  brief for the claims as they are then. 422 with the reason when it cannot be written now.

The rows and the files are made by `app/services/evidence_rounds.py`. The answers never return
ORM objects, and never the text of the claims (the brief file holds it).
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
from app.services import evidence_rounds

router = APIRouter()

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such project."}
}
_REFUSED: dict[int | str, dict[str, Any]] = {
    422: {
        "model": ErrorResponse,
        "description": "A brief cannot be written now: the project has no evidence, the claims "
        "are not ready, nothing changed, or the files folder is not available.",
    }
}

RoundStatus = Literal["brief_written", "imported", "reviewed"]


class EvidenceRoundOut(BaseModel):
    round_id: str
    round_no: int
    # The round's folder on the Mac, or null when the backend does not know where the files folder
    # is on the Mac. `folder` is relative to the files folder.
    host_folder: str | None
    folder: str
    status: RoundStatus
    # The claims that count now are not the claims of this round's brief.
    out_of_date: bool
    # How many claims the brief carries.
    claims: int
    created_at: datetime


class EvidenceBriefJobOut(BaseModel):
    """The newest `write_evidence_brief` job of the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class EvidenceStateOut(BaseModel):
    # False for a story, a lines explainer and a project with evidence off.
    wanted: bool
    # How many claims count now (not dropped, words still in the story).
    claims_count: int
    # What stops the claims from being sent to research (GLM's proposals not decided on, claims
    # whose words changed). Empty when nothing does.
    pending: list[str]
    # What the owner has to do next outside the app, or null.
    awaiting: str | None
    # The `evidence` step is complete.
    done: bool
    # Why a brief cannot be written now, or null when one can be.
    blocked_reason: str | None
    # A brief can be written now (and no brief job is going on).
    can_write_brief: bool
    round: EvidenceRoundOut | None
    job: EvidenceBriefJobOut | None
    # The prompt to paste into Cursor or Claude, and the skill it uses.
    prompt: str
    skill: str


class EvidenceBriefRun(BaseModel):
    job_id: int


def _active(job_status: str) -> bool:
    return job_status in ("queued", "running")


async def _state(session: AsyncSession, project: Project) -> EvidenceStateOut:
    state = await evidence_rounds.state(session, project)
    row = state.round
    job = state.job
    reason = evidence_rounds.refusal(state, project) if state.wanted else None
    return EvidenceStateOut(
        wanted=state.wanted,
        claims_count=len(state.claims),
        pending=state.pending,
        awaiting=evidence_rounds.awaiting_text(state),
        done=evidence_rounds.is_done(state),
        blocked_reason=reason,
        can_write_brief=state.wanted
        and reason is None
        and not (job is not None and _active(job.status)),
        round=(
            EvidenceRoundOut(
                round_id=f"r{row.round_no}",
                round_no=row.round_no,
                host_folder=state.host_folder,
                folder=row.folder,
                status=cast(RoundStatus, state.status),
                out_of_date=not state.current,
                claims=len(row.brief.get("claims", [])) if isinstance(row.brief, dict) else 0,
                created_at=row.created_at,
            )
            if row is not None
            else None
        ),
        job=(
            EvidenceBriefJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        prompt=evidence_rounds.README_PROMPT,
        skill=evidence_rounds.SKILL_NAME,
    )


@router.get(
    "/projects/{project_id}/evidence",
    response_model=EvidenceStateOut,
    responses=_NOT_FOUND,
)
async def get_evidence(project_id: int, session: SessionDep) -> EvidenceStateOut:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/evidence/brief",
    response_model=EvidenceBriefRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_REFUSED},
)
async def write_evidence_brief(project_id: int, session: SessionDep) -> EvidenceBriefRun:
    """Starts the job that writes the next round's brief. If one is already waiting or running
    for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await evidence_rounds.start_brief(session, project)
    except evidence_rounds.EvidenceRoundsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return EvidenceBriefRun(job_id=job.id)
