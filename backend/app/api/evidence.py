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

- `GET .../review`, `PUT .../review/claims/{claim_id}` and `POST .../review/done` are the owner's
  review of the newest import (EVD-007, `app/services/evidence_review.py`): accept or reject each
  usable piece, choose which accepted pieces are shown and in what order, or say a claim has no
  proof on screen. Each change is a new `evidence_review` version, and "Review done" ends the
  review. The review answer is the one place the claims' words and the agent's text (summary,
  quote, notes) are sent; the browser shows them as plain text only.

The rows and the files are made by `app/services/evidence_rounds.py`. The other answers never
return ORM objects, and never the text of the claims (the brief file holds it).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import EvidenceItem, Project
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.services import evidence_import, evidence_review, evidence_rounds
from app.services.storage import media_url

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


# --- The owner's review (EVD-007) ------------------------------------------------------------

Verdict = Literal["accepted", "rejected"]

_REVIEW_REFUSED: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such project, or no such claim in the round."},
    409: {"model": ErrorResponse, "description": "The results are being imported."},
    422: {
        "model": ErrorResponse,
        "description": "The decision is not allowed, there is nothing to review, the claims "
        "changed since the round's brief, or (Review done) a claim is not decided yet.",
    },
}


class ReviewSourceOut(BaseModel):
    """Where a piece of evidence comes from, as the import tidied it. The addresses start with
    http:// or https:// (checked on import)."""

    url: str | None
    final_url: str | None
    publisher: str | None
    title: str | None
    author: str | None
    published: str | None
    retrieved_at: str | None
    archive_url: str | None


class ReviewItemOut(BaseModel):
    item_key: str
    evidence_id: str
    usable: bool
    # Why a piece is not usable, one sentence per failed check. Empty for a usable piece.
    reasons: list[str]
    warnings: list[str]
    kind: Literal["web", "pdf"] | None
    relation: Literal["supports", "partly_supports", "contradicts", "context"] | None
    source_tier: Literal["primary", "secondary", "other"] | None
    source: ReviewSourceOut | None
    quote: str | None
    what_it_says: str | None
    agent_notes: str | None
    # The clean screenshot and the taller context image (the highlights are drawn by the browser
    # from `rects`). Null for a piece that is not usable.
    image_url: str | None
    context_url: str | None
    image_px: list[int] | None
    # `[x, y, width, height]` as fractions of the image, one per line of the quote.
    rects: list[list[float]]
    # Where the image sits inside the context image, as fractions of the context image.
    context_box: list[float] | None
    page: int | None
    # The owner's verdict, or null while undecided. Always null for a piece that is not usable.
    verdict: Verdict | None


class ReviewAttemptOut(BaseModel):
    what: str
    outcome: str


class ReviewClaimOut(BaseModel):
    claim_id: str
    origin: Literal["owner", "glm"]
    # The script words, the sentence they are in, and the owner's note, from the round's brief.
    text: str
    sentence: str
    hint: str
    status: ClaimStatus | None
    result_state: ResultState
    summary: str
    attempts: list[ReviewAttemptOut]
    problems: list[str]
    warnings: list[str]
    items: list[ReviewItemOut]
    # The item keys shown on video, in the owner's order.
    shown: list[str]
    no_proof_on_screen: bool
    # Every usable piece has a verdict and something is shown or "no proof on screen" is set (or
    # there is no usable piece and "no proof on screen" is set).
    decided: bool


class EvidenceReviewOut(BaseModel):
    """The owner's review of the newest import. `claims` is empty when there is nothing to
    review: `blocked_reason` says why."""

    round_id: str | None
    import_version: int | None
    # The newest review version of the round, or null when nothing was decided yet.
    version: int | None
    # "Review done" was pressed for the newest import and nothing changed since.
    done: bool
    editable: bool
    blocked_reason: str | None
    # The claims that are not decided yet, in the round's order.
    undecided: list[str]
    claims: list[ReviewClaimOut]


class ItemVerdictIn(BaseModel):
    item_key: str = Field(max_length=64)
    verdict: Verdict


class ClaimDecisionIn(BaseModel):
    """The whole decision on one claim. It replaces the claim's earlier decision."""

    items: list[ItemVerdictIn] = Field(max_length=20)
    # The accepted pieces to show, in order.
    shown: list[str] = Field(max_length=20)
    no_proof_on_screen: bool


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _source_out(source: Any) -> ReviewSourceOut | None:
    if not isinstance(source, dict):
        return None
    return ReviewSourceOut(
        **{
            key: _text(source.get(key))
            for key in (
                "url",
                "final_url",
                "publisher",
                "title",
                "author",
                "published",
                "retrieved_at",
                "archive_url",
            )
        }
    )


def _numbers(value: Any, length: int) -> list[float] | None:
    if (
        isinstance(value, list)
        and len(value) == length
        and all(isinstance(n, int | float) and not isinstance(n, bool) for n in value)
    ):
        return [float(n) for n in value]
    return None


def _item_out(item: EvidenceItem, verdict: str | None) -> ReviewItemOut:
    capture = item.capture if isinstance(item.capture, dict) else {}
    raw_rects = capture.get("rects")
    parsed = [_numbers(entry, 4) for entry in (raw_rects if isinstance(raw_rects, list) else [])]
    rects = [rect for rect in parsed if rect is not None]
    size = _numbers(capture.get("image_px"), 2)
    page = capture.get("page")
    return ReviewItemOut(
        item_key=item.item_key,
        evidence_id=item.evidence_id,
        usable=item.usable,
        reasons=[] if item.usable else _reasons(item.checks),
        warnings=_messages(item.warnings),
        kind=cast(Any, item.kind),
        relation=cast(Any, item.relation),
        source_tier=cast(Any, item.source_tier),
        source=_source_out(item.source),
        quote=item.quote,
        what_it_says=item.what_it_says,
        agent_notes=item.agent_notes,
        image_url=media_url(item.image_path) if item.usable and item.image_path else None,
        context_url=media_url(item.context_path) if item.usable and item.context_path else None,
        image_px=[int(n) for n in size] if size is not None else None,
        rects=rects,
        context_box=_numbers(capture.get("context_box"), 4),
        page=page if isinstance(page, int) and not isinstance(page, bool) else None,
        verdict=cast(Any, verdict) if item.usable else None,
    )


def _claim_out(claim: evidence_review.ReviewClaim) -> ReviewClaimOut:
    entry, result = claim.entry, claim.result
    problems = [text for text in result.get("problems", []) if isinstance(text, str)]
    claim_status = result.get("status")
    attempts = [
        ReviewAttemptOut(what=attempt["what"], outcome=attempt["outcome"])
        for attempt in result.get("attempts", [])
        if isinstance(attempt, dict)
        and isinstance(attempt.get("what"), str)
        and isinstance(attempt.get("outcome"), str)
    ]
    origin = entry.get("origin")
    return ReviewClaimOut(
        claim_id=entry["id"],
        origin="glm" if origin == "glm" else "owner",
        text=_text(entry.get("text")) or "",
        sentence=_text(entry.get("sentence")) or "",
        hint=_text(entry.get("hint")) or "",
        status=cast(ClaimStatus | None, claim_status),
        result_state="ok" if claim_status is not None else ("invalid" if problems else "no_result"),
        summary=_text(result.get("summary")) or "",
        attempts=attempts,
        problems=problems,
        warnings=[text for text in result.get("warnings", []) if isinstance(text, str)],
        items=[_item_out(item, claim.decision.verdicts.get(item.item_key)) for item in claim.items],
        shown=list(claim.decision.shown),
        no_proof_on_screen=claim.decision.no_proof_on_screen,
        decided=claim.decided,
    )


def _review_out(view: evidence_review.ReviewView) -> EvidenceReviewOut:
    return EvidenceReviewOut(
        round_id=view.round_id,
        import_version=view.import_version,
        version=view.version,
        done=view.done,
        editable=view.editable,
        blocked_reason=view.blocked_reason,
        undecided=view.undecided,
        claims=[_claim_out(claim) for claim in view.claims],
    )


def _review_refusal(exc: evidence_review.EvidenceReviewError) -> HTTPException:
    if isinstance(exc, evidence_review.ClaimNotInRoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, evidence_review.ImportRunningError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/evidence/review",
    response_model=EvidenceReviewOut,
    responses=_NOT_FOUND,
)
async def get_evidence_review(project_id: int, session: SessionDep) -> EvidenceReviewOut:
    project = await load_project(session, project_id)
    return _review_out(await evidence_review.view(session, project))


@router.put(
    "/projects/{project_id}/evidence/review/claims/{claim_id}",
    response_model=EvidenceReviewOut,
    responses=_REVIEW_REFUSED,
)
async def put_evidence_claim_decision(
    project_id: int, claim_id: str, body: ClaimDecisionIn, session: SessionDep
) -> EvidenceReviewOut:
    """Replaces the owner's decision on one claim. It is stored as a new version of the review
    (with "Review done" taken back), unless it changes nothing.
    """
    project = await load_project(session, project_id)
    verdicts: dict[str, str] = {}
    for entry in body.items:
        if entry.item_key in verdicts:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A piece of evidence has two verdicts.",
            )
        verdicts[entry.item_key] = entry.verdict
    decision = evidence_review.Decision(
        verdicts=verdicts, shown=list(body.shown), no_proof_on_screen=body.no_proof_on_screen
    )
    try:
        result = await evidence_review.save_claim_decision(session, project, claim_id, decision)
    except evidence_review.EvidenceReviewError as exc:
        raise _review_refusal(exc) from exc
    return _review_out(result)


@router.post(
    "/projects/{project_id}/evidence/review/done",
    response_model=EvidenceReviewOut,
    responses=_REVIEW_REFUSED,
)
async def finish_evidence_review(project_id: int, session: SessionDep) -> EvidenceReviewOut:
    """Ends the review: every claim must be decided. The `evidence` step is then complete."""
    project = await load_project(session, project_id)
    try:
        result = await evidence_review.finish_review(session, project)
    except evidence_review.EvidenceReviewError as exc:
        raise _review_refusal(exc) from exc
    return _review_out(result)
