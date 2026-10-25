"""`/api/projects/{project_id}/music-takes`: the takes of the music cues (MUSIC-010).

- `GET ...` answers everything the story workspace shows for the stage in one call: for each
  thing to generate (a cue, or a hit it asked for) its takes with their recordings and checks,
  the selected one, whether it is locked, and why it is out of date. Selected, locked and out of
  date are worked out on every read.
- `POST .../run` queues the takes of every item that has none for its cue's current detail, or of
  the one item named by `item_id`. A paid GPU run: it starts only from here or from a pipeline run.
- `POST .../{take_id}/select` selects a take. `POST .../{take_id}/reject` rejects it with a note
  and starts the rewrite of its prompt. `POST` and `DELETE .../{take_id}/lock` lock and unlock.

Nothing is edited by hand: the rows are made by the jobs (`app/services/music_takes.py`). The
answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.music_lab import LabMusicRunOut, run_out
from app.api.projects import load_project
from app.db.models import Job, Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import music_takes

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1
_MAX_TEXT = 200

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Music is off, the cues are not ready, or the request cannot be done now.",
    }
}

TakeStatus = Literal["generating", "checking", "passed", "check_failed", "failed"]
SelectedBy = Literal["auto", "owner"]
Action = Literal["generate", "regenerate", "retry"]


class TakeCheckOut(BaseModel):
    """The technical check of a take (`music_takes.check_take`)."""

    passed: bool
    # What failed, in plain words. Empty when it passed.
    problems: list[str]
    # The numbers measured from the audio, or null when it could not be measured.
    facts: dict[str, Any] | None


class MusicTakeOut(BaseModel):
    id: int
    # 1 for the first round of an item; a rewritten prompt starts the next round.
    round: int
    # Which wording of the item it was made from, or null for a rewritten prompt.
    wording: int | None
    seed: int
    # The fields sent to the music model's server, apart from the seed.
    fields: dict[str, Any]
    requested_s: float
    status: TakeStatus
    # The recording (a lab run): its job, player URL, measurements endpoint and rating.
    run: LabMusicRunOut | None
    # None until the audio exists and has been checked.
    check: TakeCheckOut | None
    # Why the take failed or did not pass, in plain words.
    problems: list[str]
    selected: bool
    selected_by: SelectedBy | None
    rejected: bool
    reject_note: str | None
    locked: bool
    # A locked take carried over from an earlier plan version.
    inherited: bool
    # Made for the cue's current detail.
    current: bool
    # The take this one was made from after its rejection, or null.
    of_take_id: int | None
    created_at: datetime


class RewriteJobOut(BaseModel):
    """The newest `rewrite_music_prompt` job of the item, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class MusicTakeItemOut(BaseModel):
    """One thing to generate and where its takes stand."""

    id: str
    cue_id: str
    # `cue` or `hit`.
    role: str
    kind: str
    model: str
    summary: str
    span_s: float | None
    requested_s: float | None
    takes: list[MusicTakeOut]
    selected_take_id: int | None
    locked: bool
    round: int
    retries_used: int
    rewrite_job: RewriteJobOut | None
    out_of_date: bool
    reasons: list[str]
    # True when making it again would replace a take the owner chose.
    needs_confirmation: bool
    # Why nothing can be made now, or null.
    blocked_reason: str | None
    # A take passed its check and is selected (or the owner locked it).
    done: bool
    # Something is being made or rewritten now.
    active: bool
    # What a run would start next, or null.
    action: Action | None
    # Why it got nowhere (no take passed its check, a rewrite failed), or null.
    last_error: str | None


class MusicTakesState(BaseModel):
    plan_version: int | None
    items: list[MusicTakeItemOut]
    music_enabled: bool
    # Why nothing can be made yet, or null.
    blocked_reason: str | None
    # The settings a run uses now.
    max_retries: int
    wordings: int


class MusicTakesRun(BaseModel):
    # The takes it queued (their jobs). Empty when everything is done or already being made.
    job_ids: list[int]


class MusicTakesRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_owner: bool = False


class MusicTakeRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=music_takes.NOTE_MAX_CHARS)


class MusicTakeRejectOut(BaseModel):
    # The `rewrite_music_prompt` job that writes the new prompt.
    job_id: int


# --- Mapping rows to answers ---------------------------------------------------------------


def _check_out(check: object) -> TakeCheckOut | None:
    if not isinstance(check, dict) or not isinstance(check.get("passed"), bool):
        return None
    return TakeCheckOut.model_validate(check)


def _job_out(job: Job | None) -> RewriteJobOut | None:
    if job is None:
        return None
    return RewriteJobOut(
        id=job.id, status=cast(JobStatus, job.status), phase=job.phase, error=job.error
    )


def _take_out(take: music_takes.TakeView) -> MusicTakeOut:
    row = take.row
    feedback = row.feedback if isinstance(row.feedback, dict) else None
    of_take_id = feedback.get("of_take_id") if feedback is not None else None
    return MusicTakeOut(
        id=row.id,
        round=row.round,
        wording=row.wording,
        seed=row.seed,
        fields=dict(row.fields),
        requested_s=row.requested_s,
        status=take.status,
        run=run_out(take.run) if take.run is not None else None,
        check=_check_out(row.check_result),
        problems=take.problems,
        selected=take.selected,
        # The database CHECK constraint keeps `selected_by` to the two allowed values.
        selected_by=cast(SelectedBy | None, row.selected_by),
        rejected=row.rejected_at is not None,
        reject_note=row.reject_note,
        locked=row.locked_at is not None,
        inherited=take.inherited,
        current=take.current,
        of_take_id=of_take_id if isinstance(of_take_id, int) else None,
        created_at=row.created_at,
    )


def _item_out(view: music_takes.ItemView) -> MusicTakeItemOut:
    item = view.item
    return MusicTakeItemOut(
        id=view.item_id,
        cue_id=str(item["cue_id"]),
        role=str(item["role"]),
        kind=str(item["kind"]),
        model=str(item["model"]),
        summary=str(view.cue_view.cue["summary"]),
        span_s=item.get("span_s"),
        requested_s=item.get("requested_s"),
        takes=[_take_out(take) for take in view.takes],
        selected_take_id=view.selection.row.id if view.selection is not None else None,
        locked=view.locked,
        round=view.round,
        retries_used=view.retries_used,
        rewrite_job=_job_out(view.rewrite_job),
        out_of_date=view.out_of_date,
        reasons=view.reasons,
        needs_confirmation=view.needs_confirmation,
        blocked_reason=view.blocked_reason,
        done=view.done,
        active=view.active,
        action=cast(Action | None, view.action),
        last_error=view.last_error,
    )


async def _state(session: AsyncSession, project: Project) -> MusicTakesState:
    if await music_takes.settle(project.id):
        dispatcher.nudge()
    current = await music_takes.state(session, project)
    return MusicTakesState(
        plan_version=current.plan.version if current.plan is not None else None,
        items=[_item_out(view) for view in current.items],
        music_enabled=current.music_enabled,
        blocked_reason=current.blocked_reason,
        max_retries=current.max_retries,
        wordings=current.wordings,
    )


def _refused(exc: music_takes.MusicTakeError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


# --- Endpoints -----------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/music-takes",
    response_model=MusicTakesState,
    responses=_NOT_FOUND,
)
async def get_music_takes(project_id: int, session: SessionDep) -> MusicTakesState:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/music-takes/run",
    response_model=MusicTakesRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_music_takes(
    project_id: int,
    session: SessionDep,
    body: MusicTakesRunIn | None = None,
    item_id: Annotated[str | None, Query(max_length=_MAX_TEXT)] = None,
) -> MusicTakesRun:
    """Queues the takes of every item that has none for its cue's current detail, or of the item
    named by `item_id`. One take is made for each wording, all at once. Paid GPU calls start only
    from here (or from a pipeline run), never by themselves.
    """
    project = await load_project(session, project_id)
    try:
        job_ids = await music_takes.start_run(
            session,
            project,
            item_id=item_id,
            confirm_replace_owner=body.confirm_replace_owner if body is not None else False,
        )
    except music_takes.MusicTakeError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return MusicTakesRun(job_ids=list(job_ids))


@router.post(
    "/projects/{project_id}/music-takes/{take_id}/select",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND, **_INVALID},
)
async def select_music_take(
    project_id: int,
    take_id: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> None:
    """Selects a take, also one that failed its check. The item's automatic retries stop."""
    project = await load_project(session, project_id)
    try:
        await music_takes.select_take(session, project, take_id)
    except music_takes.MusicTakeError as exc:
        raise _refused(exc) from exc


@router.post(
    "/projects/{project_id}/music-takes/{take_id}/reject",
    response_model=MusicTakeRejectOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def reject_music_take(
    project_id: int,
    take_id: Annotated[int, Path(ge=1, le=_MAX_INT)],
    body: MusicTakeRejectIn,
    session: SessionDep,
) -> MusicTakeRejectOut:
    """Rejects a take with a note. The model rewrites the cue's prompt from the note (a paid
    language model call) and a new take is made from it.
    """
    project = await load_project(session, project_id)
    try:
        job_id = await music_takes.reject(session, project, take_id, body.note)
    except music_takes.MusicTakeError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return MusicTakeRejectOut(job_id=job_id)


@router.post(
    "/projects/{project_id}/music-takes/{take_id}/lock",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND, **_INVALID},
)
async def lock_music_take(
    project_id: int,
    take_id: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> None:
    """Locks the selected take: it is never regenerated, and carries over to a matching cue of a
    later plan version.
    """
    project = await load_project(session, project_id)
    try:
        await music_takes.lock(session, project, take_id)
    except music_takes.MusicTakeError as exc:
        raise _refused(exc) from exc


@router.delete(
    "/projects/{project_id}/music-takes/{take_id}/lock",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND, **_INVALID},
)
async def unlock_music_take(
    project_id: int,
    take_id: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> None:
    """Removes the lock of a take."""
    project = await load_project(session, project_id)
    try:
        await music_takes.unlock(session, project, take_id)
    except music_takes.MusicTakeError as exc:
        raise _refused(exc) from exc
