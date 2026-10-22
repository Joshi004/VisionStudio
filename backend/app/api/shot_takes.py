"""`/api/projects/{project_id}/shot-takes`: the generation of each shot's clip (PHASE-027).

- `GET ...` answers everything the story workspace shows in one call: the newest list of scenes,
  and for each scene its shots (from the newest shot plan) with the status of each shot's
  generation (`not_generated`, `generated`, `out_of_date`, `failed`, `unchecked`), why it is out
  of date, every take of the shot (newest first, with the clip's address, its measured length,
  its state: `generating`, `ready` or `failed`, and its technical check), which take is
  selected (only a take that passed its check can be), the newest job, and whether Generate may
  be pressed. Out of date is worked out on every read.
- `POST .../check` ("Check takes") starts the local job that checks the clips made before the
  checks existed. It starts no generation.
- `POST .../run` ("Generate all") starts one job for every shot, in every scene, whose prompt is
  compiled and current and that has no current take and is not already being generated.
- `POST .../{scene_id}/run` starts the jobs for the shots of one scene.
- `POST .../{scene_id}/{shot_id}/run` starts one more take of one shot (Generate or Regenerate).
- `POST .../{scene_id}/{shot_id}/takes/{take_id}/select` makes a ready take the shot's selected
  one.

A job makes a new take (`services/shot_takes.py`); nothing is written to the Character Lab and no
other shot changes. The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.discovery import DiscoveryJobOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Job
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import shot_takes, storage
from app.services.shot_takes import SceneEntry, ShotEntry, TakeEntry

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The shot's prompt is not compiled and current, a picture or an audio "
        "file is missing, the GPU API has no such endpoint, the take cannot be selected, or "
        "the scene, shot or take is not in the newest list of scenes and shot plan.",
    }
}

Status = Literal["not_generated", "generated", "out_of_date", "failed", "unchecked"]
TakeState = Literal["generating", "ready", "failed"]
PromptStatus = Literal["not_compiled", "compiled", "out_of_date"]
ShotType = Literal["establishing", "action", "reaction", "dialogue", "insert", "transition"]
ProblemKind = Literal["clip", "plan"]


class TakeProblemOut(BaseModel):
    code: str
    message: str


class TakeValidationOut(BaseModel):
    """The technical check of a take's clip (PHASE-029). `kind` is `clip` when another seed may
    fix it (retried automatically) and `plan` when the shot's scene has to be planned again.
    """

    passed: bool
    kind: ProblemKind | None
    problems: list[TakeProblemOut]
    checked_at: datetime | None


class ShotTakeOut(BaseModel):
    id: int
    take_number: int
    state: TakeState
    # True for the one take of the shot that is selected.
    selected: bool
    seed: int
    # The clip's address; None until the take is ready.
    url: str | None
    # What the clip measured at ffprobe, None until the take is ready.
    duration_s: float | None
    frame_count: int | None
    width: int | None
    height: int | None
    has_audio: bool | None
    size_bytes: int | None
    # Why this take is out of date, one sentence each. Empty when it is current.
    reasons: list[str]
    created_at: datetime
    selected_at: datetime | None
    job: DiscoveryJobOut | None
    # The technical check, or None when the clip has not been checked.
    validation: TakeValidationOut | None
    # 0 for a take somebody asked for; n for the nth automatic retry of a failed clip.
    retry_attempt: int


class TakeShotSkeletonOut(BaseModel):
    id: str
    type: ShotType
    description: str
    # The shot's length on the timeline: the clip is at least this long.
    duration_seconds: float


class ShotTakesEntryOut(BaseModel):
    shot: TakeShotSkeletonOut
    status: Status
    # Why the selected take is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # Where the shot's compiled prompt stands: the clip is generated from it.
    prompt_status: PromptStatus
    takes: list[ShotTakeOut]
    selected_take_id: int | None
    # The newest take's job, whatever its status.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None


class SceneShotTakesOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    description: str
    shots: list[ShotTakesEntryOut]


class ShotTakesOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    entries: list[SceneShotTakesOut]
    # Why nothing can be generated yet, or None.
    blocked_reason: str | None
    # How many ready takes have no check yet, and the newest job that checks them.
    unchecked_count: int
    check_job: DiscoveryJobOut | None
    # The most automatic retries a failed clip gets (0 means none).
    max_retries: int


class ShotTakesSkippedOut(BaseModel):
    scene_id: str
    # None when the whole scene was skipped.
    shot_id: str | None
    title: str
    reason: str


class ShotTakesRunManyOut(BaseModel):
    job_ids: list[int]
    skipped: list[ShotTakesSkippedOut]


class ShotTakesRunOneOut(BaseModel):
    job_id: int


class SelectedTakeOut(BaseModel):
    take_id: int
    selected_at: datetime


class ShotTakesCheckOut(BaseModel):
    job_id: int


def _job_out(job: Job | None) -> DiscoveryJobOut | None:
    if job is None:
        return None
    return DiscoveryJobOut(
        id=job.id,
        status=cast(JobStatus, job.status),
        phase=job.phase,
        error=job.error,
    )


def _validation_out(validation: dict[str, Any] | None) -> TakeValidationOut | None:
    if validation is None:
        return None
    checked_at = validation.get("checked_at")
    return TakeValidationOut(
        passed=validation.get("passed") is True,
        kind=cast(ProblemKind | None, validation.get("kind")),
        problems=[
            TakeProblemOut(code=problem["code"], message=problem["message"])
            for problem in validation.get("problems", [])
        ],
        checked_at=datetime.fromisoformat(checked_at) if isinstance(checked_at, str) else None,
    )


def _take_out(entry: TakeEntry) -> ShotTakeOut:
    row = entry.row
    audio = row.audio
    return ShotTakeOut(
        id=row.id,
        take_number=row.take_number,
        state=entry.state,
        selected=entry.selected,
        seed=row.seed,
        url=storage.media_url(row.path) if row.path is not None else None,
        duration_s=row.duration_s,
        frame_count=row.frame_count,
        width=row.width,
        height=row.height,
        has_audio=(audio is not None) if row.path is not None else None,
        size_bytes=row.size_bytes,
        reasons=entry.reasons,
        created_at=row.created_at,
        selected_at=row.selected_at,
        job=_job_out(entry.job),
        validation=_validation_out(entry.validation),
        retry_attempt=entry.retry_attempt,
    )


def _shot_out(entry: ShotEntry) -> ShotTakesEntryOut:
    shot = entry.shot
    selected = entry.selected
    return ShotTakesEntryOut(
        shot=TakeShotSkeletonOut(
            id=shot["id"],
            type=shot["type"],
            description=shot["description"],
            duration_seconds=entry.duration_s,
        ),
        status=entry.status,
        reasons=entry.reasons,
        prompt_status=cast(PromptStatus, entry.prompt_status),
        takes=[_take_out(take) for take in entry.takes],
        selected_take_id=selected.row.id if selected is not None else None,
        job=_job_out(entry.job),
        can_run=entry.can_run,
        blocked_reason=entry.blocked_reason,
    )


def _scene_out(entry: SceneEntry) -> SceneShotTakesOut:
    return SceneShotTakesOut(
        id=entry.item["id"],
        index=entry.item["index"],
        title=entry.item["title"],
        description=entry.item["description"],
        shots=[_shot_out(shot) for shot in entry.shots],
    )


def _run_many_out(started: shot_takes.StartResult) -> ShotTakesRunManyOut:
    return ShotTakesRunManyOut(
        job_ids=started.job_ids,
        skipped=[
            ShotTakesSkippedOut(
                scene_id=item.scene_id,
                shot_id=item.shot_id,
                title=item.title,
                reason=item.reason,
            )
            for item in started.skipped
        ],
    )


def _refused(exc: shot_takes.ShotTakesError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/shot-takes",
    response_model=ShotTakesOut,
    responses=_NOT_FOUND,
)
async def get_shot_takes(project_id: int, session: SessionDep) -> ShotTakesOut:
    project = await load_project(session, project_id)
    result = await shot_takes.state(session, project)
    return ShotTakesOut(
        scenes_version=result.scenes_version,
        entries=[_scene_out(entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
        unchecked_count=result.unchecked_count,
        check_job=_job_out(result.check_job),
        max_retries=result.max_retries,
    )


@router.post(
    "/projects/{project_id}/shot-takes/check",
    response_model=ShotTakesCheckOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def check_takes(project_id: int, session: SessionDep) -> ShotTakesCheckOut:
    """Starts the job that checks the clips made before the checks existed. It starts no
    generation. If it is already waiting or running, that job's id is returned.
    """
    project = await load_project(session, project_id)
    try:
        job = await shot_takes.start_check(session, project)
    except shot_takes.ShotTakesError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return ShotTakesCheckOut(job_id=job.id)


@router.post(
    "/projects/{project_id}/shot-takes/run",
    response_model=ShotTakesRunManyOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> ShotTakesRunManyOut:
    """Starts a job for every shot that has no current take and is not already being
    generated. The shots that cannot be generated are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await shot_takes.start_all(session, project)
    except shot_takes.ShotTakesError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return _run_many_out(started)


@router.post(
    "/projects/{project_id}/shot-takes/{scene_id}/run",
    response_model=ShotTakesRunManyOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_scene(
    project_id: int, scene_id: DiscoveryId, session: SessionDep
) -> ShotTakesRunManyOut:
    """Starts a job for every shot of one scene that has no current take and is not already
    being generated.
    """
    project = await load_project(session, project_id)
    try:
        started = await shot_takes.start_scene(session, project, scene_id)
    except shot_takes.ShotTakesError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return _run_many_out(started)


@router.post(
    "/projects/{project_id}/shot-takes/{scene_id}/{shot_id}/run",
    response_model=ShotTakesRunOneOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_shot(
    project_id: int, scene_id: DiscoveryId, shot_id: DiscoveryId, session: SessionDep
) -> ShotTakesRunOneOut:
    """Starts the job that makes one more take of a shot. If it already has a job waiting or
    running, that job's id is returned and no second take is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await shot_takes.start_shot(session, project, scene_id, shot_id)
    except shot_takes.ShotTakesError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return ShotTakesRunOneOut(job_id=job.id)


@router.post(
    "/projects/{project_id}/shot-takes/{scene_id}/{shot_id}/takes/{take_id}/select",
    response_model=SelectedTakeOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def select_take(
    project_id: int,
    scene_id: DiscoveryId,
    shot_id: DiscoveryId,
    take_id: int,
    session: SessionDep,
) -> SelectedTakeOut:
    """Makes a ready take the selected one of its shot. The other shots do not change."""
    project = await load_project(session, project_id)
    try:
        take = await shot_takes.select_take(session, project, scene_id, shot_id, take_id)
    except shot_takes.ShotTakesError as exc:
        raise _refused(exc) from exc
    assert take.selected_at is not None  # `select_take` just set it
    return SelectedTakeOut(take_id=take.id, selected_at=take.selected_at)
