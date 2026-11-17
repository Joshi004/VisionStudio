"""`/api/projects/{project_id}/evidence`: the research rounds of the evidence layer (EVD-003).

- `GET ...` answers where the project's evidence stands: the newest round (its folder on the Mac,
  whether its results are imported and reviewed, and whether the claims changed since its brief),
  what the owner has to do next, the newest brief job, and the prompt to paste into Cursor or
  Claude. A project without evidence reads nothing from the tables.
- `POST .../brief` starts the `write_evidence_brief` job: it writes the next round's folder and
  brief for the claims as they are then. 422 with the reason when it cannot be written now.
- `POST .../import` starts the `import_evidence` job (EVD-006): it reads and checks the newest
  round's results and copies the usable files into storage. 422 with the reason when it cannot
  be imported now. `GET ...` also answers the newest import's report: what each claim has, and why
  a piece of evidence was refused. Those sentences are the app's own (a few carry a cut-short
  value of the agent's); the agent's summary and quotes are not sent here.

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
from app.jobs import dispatcher, store
from app.services import evidence_import, evidence_rounds

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

_IMPORT_REFUSED: dict[int | str, dict[str, Any]] = {
    422: {
        "model": ErrorResponse,
        "description": "The results cannot be imported now: the project has no evidence, there "
        "is no round, the claims changed since the round's brief, nothing was written in "
        "results yet, or the files folder is not available.",
    }
}

RoundStatus = Literal["brief_written", "imported", "reviewed"]
ClaimStatus = Literal["found", "partial", "not_found", "contradicted", "blocked"]
ResultState = Literal["ok", "no_result", "invalid"]


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


class ImportItemOut(BaseModel):
    """One piece of evidence of the newest import."""

    evidence_id: str
    usable: bool
    # Why it was refused, one sentence per failed check. Empty for a usable piece.
    reasons: list[str]
    # Warnings that did not refuse it (a number the quote does not say).
    warnings: list[str]


class ImportClaimOut(BaseModel):
    claim_id: str
    # The claim's status as the agent reported it, or null when the claim has no usable result.
    status: ClaimStatus | None
    # `no_result`: no result.json. `invalid`: there is one and it cannot be used.
    result_state: ResultState
    problems: list[str]
    warnings: list[str]
    items: list[ImportItemOut]


class ImportReportOut(BaseModel):
    claims: int
    # Claims by status, plus `no_result` and `invalid`. Only the counts that are not zero.
    by_status: dict[str, int]
    items: int
    usable_items: int


class ImportOut(BaseModel):
    """The newest import of the newest round."""

    version: int
    created_at: datetime
    report: ImportReportOut
    claims: list[ImportClaimOut]


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
    # The newest round's results can be imported now (and no import job is going on).
    can_import: bool
    # Why they cannot be, or null. It does not look at the folder: an import with no result
    # written yet is refused when it is asked for.
    import_blocked_reason: str | None
    # The newest `import_evidence` job of the project, whatever its status.
    import_job: EvidenceBriefJobOut | None
    latest_import: ImportOut | None


class EvidenceBriefRun(BaseModel):
    job_id: int


def _active(job_status: str) -> bool:
    return job_status in ("queued", "running")


def _reasons(checks: Any) -> list[str]:
    if not isinstance(checks, dict):
        return []
    return [
        entry["reason"]
        for entry in checks.values()
        if isinstance(entry, dict) and isinstance(entry.get("reason"), str)
    ]


def _messages(warnings: Any) -> list[str]:
    if not isinstance(warnings, list):
        return []
    return [
        entry["message"]
        for entry in warnings
        if isinstance(entry, dict) and isinstance(entry.get("message"), str)
    ]


async def _latest_import(session: AsyncSession, round_row_id: int) -> ImportOut | None:
    record = await evidence_import.latest_import(session, round_row_id)
    if record is None:
        return None
    items = await evidence_import.items_of(session, record.id)
    by_claim: dict[str, list[ImportItemOut]] = {}
    for item in items:
        by_claim.setdefault(item.claim_id, []).append(
            ImportItemOut(
                evidence_id=item.evidence_id,
                usable=item.usable,
                reasons=[] if item.usable else _reasons(item.checks),
                warnings=_messages(item.warnings),
            )
        )
    claims: list[ImportClaimOut] = []
    results = record.results if isinstance(record.results, dict) else {}
    for claim_id, entry in results.items():
        if not isinstance(entry, dict):
            continue
        claim_status = entry.get("status")
        problems = [text for text in entry.get("problems", []) if isinstance(text, str)]
        claims.append(
            ImportClaimOut(
                claim_id=claim_id,
                status=cast(ClaimStatus | None, claim_status),
                result_state=(
                    "ok" if claim_status is not None else ("invalid" if problems else "no_result")
                ),
                problems=problems,
                warnings=[text for text in entry.get("warnings", []) if isinstance(text, str)],
                items=by_claim.get(claim_id, []),
            )
        )
    report = record.report if isinstance(record.report, dict) else {}
    return ImportOut(
        version=record.version,
        created_at=record.created_at,
        report=ImportReportOut(
            claims=int(report.get("claims", 0)),
            by_status={str(k): int(v) for k, v in dict(report.get("by_status", {})).items()},
            items=int(report.get("items", 0)),
            usable_items=int(report.get("usable_items", 0)),
        ),
        claims=claims,
    )


def _job_out(job: Any) -> EvidenceBriefJobOut | None:
    if job is None:
        return None
    return EvidenceBriefJobOut(
        id=job.id,
        status=cast(JobStatus, job.status),
        phase=job.phase,
        error=job.error,
    )


async def _state(session: AsyncSession, project: Project) -> EvidenceStateOut:
    state = await evidence_rounds.state(session, project)
    import_job = (
        await store.latest_job(session, project.id, evidence_import.JOB_TYPE)
        if state.wanted
        else None
    )
    import_reason = evidence_import.import_refusal(state) if state.wanted else None
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
        can_import=state.wanted
        and import_reason is None
        and not (import_job is not None and _active(import_job.status)),
        import_blocked_reason=import_reason,
        import_job=_job_out(import_job),
        latest_import=await _latest_import(session, row.id) if row is not None else None,
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


@router.post(
    "/projects/{project_id}/evidence/import",
    response_model=EvidenceBriefRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_IMPORT_REFUSED},
)
async def import_evidence(project_id: int, session: SessionDep) -> EvidenceBriefRun:
    """Starts the job that imports the newest round's results. If one is already waiting or
    running for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await evidence_import.start_import(session, project)
    except evidence_import.EvidenceImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return EvidenceBriefRun(job_id=job.id)
