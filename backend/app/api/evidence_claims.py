"""`/api/projects/{project_id}/evidence-claims`: the words of the story that need proof
(EVD-002).

- `GET ...` answers the claims as they stand in the story now, the newest job, and whether the
  project has claims at all. Marks that moved with an edit of the story, and claims whose words
  are gone (`words_changed`), are worked out on every read. So are the script rules of a sound
  bite (`soundbite_block`, `soundbite_warnings`, `soundbite_hints`, SB-005).
- `POST .../marks` marks words of the saved story as a claim, with an optional note and kind.
- `PATCH .../{claim_id}` changes a claim's note, kind, `want` or `speaker`, or keeps or drops a
  proposal of GLM. A sound bite is refused (422) unless the words are whole sentences in
  quotation marks.
- `DELETE .../{claim_id}` removes one of the owner's marks.
- `POST .../suggest` starts the `suggest_evidence_claims` job: one model call proposes more claims.

Every change is a new version of the claim list (`source` `manual`; the job's is `ai`). Every
route answers 422 for a project without evidence, and 409 while the model is proposing. The rows
and the job are made by `app/services/evidence_claims.py`. The answers never return ORM objects.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import evidence_claims as claims_service

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or claim."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The project has no evidence, the story is not saved, or the request breaks "
        "a rule.",
    },
    409: {"model": ErrorResponse, "description": "GLM is proposing claims."},
}

Origin = Literal["owner", "glm"]
Kind = Literal["number", "quote", "statement", "event", "other"]
Want = Literal["evidence", "soundbite"]


# --- What the claims hold --------------------------------------------------------------------


class SoundbiteWarningOut(BaseModel):
    """One script rule a sound bite breaks without being blocked (SB-005)."""

    code: str
    message: str
    # The offending words: shared words, the filler phrase, or the end of the lead-in. May be empty.
    words: list[str]


class EvidenceClaimOut(BaseModel):
    id: str
    origin: Origin
    # Character positions in the project's `script_text`; `end` is not included.
    start: int
    end: int
    text: str
    hint: str
    kind_hint: Kind
    # `soundbite` when the owner wants a clip of the person saying the quote (SB-001).
    want: Want
    # Who says a sound bite; null for any other claim.
    speaker: str | None
    # GLM's reason; empty for the owner's marks.
    reason: str
    # True for the owner's marks. For a proposal: null until the owner decides, then true (kept)
    # or false (dropped).
    kept: bool | None
    # The words of the claim are no longer in the story, or no longer stand alone there.
    words_changed: bool
    # Why the words cannot be (or no longer are) a sound bite: they must be whole sentences in
    # quotation marks. Null when they can, and for a claim whose words changed. Worked out on
    # every read (SB-005).
    soundbite_block: str | None
    # Script rules a sound bite breaks without being blocked. Empty for any other claim.
    soundbite_warnings: list[SoundbiteWarningOut]
    # Advice the owner judges alone. Empty for any other claim.
    soundbite_hints: list[str]


class EvidenceClaimsJobOut(BaseModel):
    """The newest `suggest_evidence_claims` job of the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class EvidenceClaimsState(BaseModel):
    # The newest claim list version, or null when there is none.
    version: int | None
    claims: list[EvidenceClaimOut]
    job: EvidenceClaimsJobOut | None
    # Why no claim can be marked or proposed now (or at all for this project), or null.
    blocked_reason: str | None
    # False for a story, a lines explainer and a project with evidence off.
    wanted: bool
    # True once GLM has been asked, and answered, for this project.
    has_ai_version: bool


class EvidenceClaimsRun(BaseModel):
    job_id: int


# --- What a change sends ---------------------------------------------------------------------


class EvidenceMarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: StrictInt = Field(ge=0, le=_MAX_INT)
    end: StrictInt = Field(ge=0, le=_MAX_INT)
    # The words as the owner saw them in the saved story: a stale page is refused.
    text: StrictStr = Field(max_length=500)
    hint: StrictStr = Field(default="", max_length=1000)
    # Left out: "number" when the words say a number, otherwise "statement".
    kind_hint: Kind | None = None


class EvidenceClaimEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Left out: not changed.
    hint: StrictStr | None = Field(default=None, max_length=1000)
    kind_hint: Kind | None = None
    # Only for a proposal of GLM.
    kept: StrictBool | None = None
    # Left out: not changed. A sound bite needs a speaker; choosing "evidence" clears it.
    want: Want | None = None
    speaker: StrictStr | None = Field(default=None, max_length=300)


# --- Mapping ---------------------------------------------------------------------------------


async def _state(session: AsyncSession, project: Project) -> EvidenceClaimsState:
    state = await claims_service.state(session, project)
    job = state.job
    return EvidenceClaimsState(
        version=state.latest.version if state.latest is not None else None,
        claims=[EvidenceClaimOut(**claim) for claim in state.claims],
        job=(
            EvidenceClaimsJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        blocked_reason=state.blocked_reason,
        wanted=state.wanted,
        has_ai_version=state.has_ai_version,
    )


def _refusal(exc: claims_service.EvidenceClaimsError) -> HTTPException:
    if isinstance(exc, claims_service.ClaimNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, claims_service.BusyError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


# --- Endpoints -------------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/evidence-claims",
    response_model=EvidenceClaimsState,
    responses=_NOT_FOUND,
)
async def get_evidence_claims(project_id: int, session: SessionDep) -> EvidenceClaimsState:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/evidence-claims/marks",
    response_model=EvidenceClaimsState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def mark_evidence_claim(
    project_id: int, body: EvidenceMarkIn, session: SessionDep
) -> EvidenceClaimsState:
    """Marks words of the saved story as a claim, as a new version written by the owner."""
    project = await load_project(session, project_id)
    try:
        await claims_service.add_mark(
            session,
            project,
            start=body.start,
            end=body.end,
            text=body.text,
            hint=body.hint,
            kind_hint=body.kind_hint,
        )
    except claims_service.EvidenceClaimsError as exc:
        raise _refusal(exc) from exc
    return await _state(session, project)


@router.post(
    "/projects/{project_id}/evidence-claims/suggest",
    response_model=EvidenceClaimsRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def suggest_evidence_claims(project_id: int, session: SessionDep) -> EvidenceClaimsRun:
    """Starts the job that asks GLM for more claims. If one is already waiting or running for the
    project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await claims_service.start_suggest(session, project)
    except claims_service.EvidenceClaimsError as exc:
        raise _refusal(exc) from exc
    dispatcher.nudge()
    return EvidenceClaimsRun(job_id=job.id)


@router.patch(
    "/projects/{project_id}/evidence-claims/{claim_id}",
    response_model=EvidenceClaimsState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def edit_evidence_claim(
    project_id: int,
    claim_id: Annotated[str, Path(max_length=50)],
    body: EvidenceClaimEditIn,
    session: SessionDep,
) -> EvidenceClaimsState:
    """Changes a claim's note, kind, `want` or `speaker`, or keeps or drops a proposal of GLM."""
    project = await load_project(session, project_id)
    try:
        await claims_service.update_claim(
            session,
            project,
            claim_id,
            hint=body.hint,
            kind_hint=body.kind_hint,
            kept=body.kept,
            want=body.want,
            speaker=body.speaker,
        )
    except claims_service.EvidenceClaimsError as exc:
        raise _refusal(exc) from exc
    return await _state(session, project)


@router.delete(
    "/projects/{project_id}/evidence-claims/{claim_id}",
    response_model=EvidenceClaimsState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def remove_evidence_claim(
    project_id: int,
    claim_id: Annotated[str, Path(max_length=50)],
    session: SessionDep,
) -> EvidenceClaimsState:
    """Removes one of the owner's marks. A proposal of GLM is dropped instead (PATCH)."""
    project = await load_project(session, project_id)
    try:
        await claims_service.remove_mark(session, project, claim_id)
    except claims_service.EvidenceClaimsError as exc:
        raise _refusal(exc) from exc
    return await _state(session, project)
