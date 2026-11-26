"""`/api/projects/{project_id}/sound-effects`: the two sound effects of a continuous explainer
(EXM-006).

- `GET ...` answers everything the project board shows for the step in one call: for each sound
  the project needs (`graphic`, `evidence`) its takes with their recordings and checks, the
  selected one, whether it is locked, and where its prompt stands. Selected and locked are worked
  out on every read.
- `POST .../run` queues the sounds that have no takes, or the one named by `role` (a new round of
  takes, also for a sound that is done). A paid language model call and GPU runs: they start only
  from here or from a pipeline run.
- `POST .../{take_id}/select` selects a take. `POST .../{take_id}/reject` rejects it with a note
  and starts the rewrite of its prompt. `POST` and `DELETE .../{take_id}/lock` lock and unlock.

Nothing is edited by hand: the rows are made by the jobs (`app/services/sound_effects.py`). The
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
from app.api.music_takes import RewriteJobOut, TakeCheckOut
from app.api.projects import load_project
from app.db.models import Job, Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import sound_effects

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Sound effects are off, the Story Bible is missing, or the request "
        "cannot be done now.",
    }
}

TakeStatus = Literal["generating", "checking", "passed", "check_failed", "failed"]
SelectedBy = Literal["auto", "owner"]
Role = Literal["graphic", "evidence"]
Action = Literal["generate", "retry"]


class SoundEffectTakeOut(BaseModel):
    id: int
    # 1 for the first round of a sound; a rewritten prompt or a new run starts the next round.
    round: int
    seed: int
    # The fields sent to the sound model's server, apart from the seed.
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
    # The take this one was made from after its rejection, or null.
    of_take_id: int | None
    created_at: datetime


class SoundEffectOut(BaseModel):
    """One of the project's sounds and where its takes stand."""

    role: Role
    label: str
    takes: list[SoundEffectTakeOut]
    selected_take_id: int | None
    locked: bool
    round: int
    retries_used: int
    # The newest `write_sound_effect` job of the sound, whatever its status.
    prompt_job: RewriteJobOut | None
    # A take passed its check and is selected (or the owner chose or locked one).
    done: bool
    # Something is being written or made now.
    active: bool
    # What a run would start next, or null.
    action: Action | None
    # Why nothing can be made now, or null.
    blocked_reason: str | None
    # Why it got nowhere (the prompt could not be written, no take passed its check), or null.
    last_error: str | None


class SoundEffectsState(BaseModel):
    # The project's switch.
    sound_effects: bool
    # Whether the project has anything to make: a continuous explainer with the switch on and
    # graphics or evidence on.
    wanted: bool
    sounds: list[SoundEffectOut]
    # Why nothing can be made yet, or null.
    blocked_reason: str | None
    # The settings a run uses now.
    max_retries: int
    takes_per_prompt: int


class SoundEffectsRun(BaseModel):
    # The jobs it queued. Empty when everything is done or already being made.
    job_ids: list[int]


class SoundEffectRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=sound_effects.NOTE_MAX_CHARS)


class SoundEffectRejectOut(BaseModel):
    # The `write_sound_effect` job that writes the new prompt.
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


def _take_out(take: sound_effects.TakeView) -> SoundEffectTakeOut:
    row = take.row
    feedback = row.feedback if isinstance(row.feedback, dict) else None
    of_take_id = feedback.get("of_take_id") if feedback is not None else None
    return SoundEffectTakeOut(
        id=row.id,
        round=row.round,
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
        of_take_id=of_take_id if isinstance(of_take_id, int) else None,
        created_at=row.created_at,
    )


def _sound_out(view: sound_effects.RoleView) -> SoundEffectOut:
    return SoundEffectOut(
        role=cast(Role, view.role),
        label=view.label,
        takes=[_take_out(take) for take in view.takes],
        selected_take_id=view.selection.row.id if view.selection is not None else None,
        locked=view.locked,
        round=view.round,
        retries_used=view.retries_used,
        prompt_job=_job_out(view.prompt_job),
        done=view.done,
        active=view.active,
        action=cast(Action | None, view.action),
        blocked_reason=view.blocked_reason,
        last_error=view.last_error,
    )


async def _state(session: AsyncSession, project: Project) -> SoundEffectsState:
    if await sound_effects.settle(project.id):
        dispatcher.nudge()
    current = await sound_effects.state(session, project)
    return SoundEffectsState(
        sound_effects=current.switched_on,
        wanted=current.wanted,
        sounds=[_sound_out(view) for view in current.roles],
        blocked_reason=current.blocked_reason,
        max_retries=current.max_retries,
        takes_per_prompt=current.takes_per_prompt,
    )


def _refused(exc: sound_effects.SoundEffectError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


# --- Endpoints -----------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/sound-effects",
    response_model=SoundEffectsState,
    responses=_NOT_FOUND,
)
async def get_sound_effects(project_id: int, session: SessionDep) -> SoundEffectsState:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/sound-effects/run",
    response_model=SoundEffectsRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_sound_effects(
    project_id: int,
    session: SessionDep,
    role: Annotated[Role | None, Query()] = None,
) -> SoundEffectsRun:
    """Queues the sounds that have no takes, or the sound named by `role` (a new round, also for
    a sound that is done, unless it is locked). Paid calls start only from here (or from a
    pipeline run), never by themselves.
    """
    project = await load_project(session, project_id)
    try:
        job_ids = await sound_effects.start_run(session, project, role=role)
    except sound_effects.SoundEffectError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return SoundEffectsRun(job_ids=list(job_ids))


@router.post(
    "/projects/{project_id}/sound-effects/{take_id}/select",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND, **_INVALID},
)
async def select_sound_effect_take(
    project_id: int,
    take_id: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> None:
    """Selects a take, also one that failed its check. The sound's automatic retries stop."""
    project = await load_project(session, project_id)
    try:
        await sound_effects.select_take(session, project, take_id)
    except sound_effects.SoundEffectError as exc:
        raise _refused(exc) from exc


@router.post(
    "/projects/{project_id}/sound-effects/{take_id}/reject",
    response_model=SoundEffectRejectOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def reject_sound_effect_take(
    project_id: int,
    take_id: Annotated[int, Path(ge=1, le=_MAX_INT)],
    body: SoundEffectRejectIn,
    session: SessionDep,
) -> SoundEffectRejectOut:
    """Rejects a take with a note. The model rewrites the sound's prompt from the note (a paid
    language model call) and a new take is made from it.
    """
    project = await load_project(session, project_id)
    try:
        job_id = await sound_effects.reject(session, project, take_id, body.note)
    except sound_effects.SoundEffectError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return SoundEffectRejectOut(job_id=job_id)


@router.post(
    "/projects/{project_id}/sound-effects/{take_id}/lock",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND, **_INVALID},
)
async def lock_sound_effect_take(
    project_id: int,
    take_id: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> None:
    """Locks the selected take: it is never regenerated."""
    project = await load_project(session, project_id)
    try:
        await sound_effects.lock(session, project, take_id)
    except sound_effects.SoundEffectError as exc:
        raise _refused(exc) from exc


@router.delete(
    "/projects/{project_id}/sound-effects/{take_id}/lock",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND, **_INVALID},
)
async def unlock_sound_effect_take(
    project_id: int,
    take_id: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> None:
    """Removes the lock of a take."""
    project = await load_project(session, project_id)
    try:
        await sound_effects.unlock(session, project, take_id)
    except sound_effects.SoundEffectError as exc:
        raise _refused(exc) from exc
