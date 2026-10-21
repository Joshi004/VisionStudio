"""`/api/projects/{project_id}/shot-continuity`: the shot continuity check (PHASE-023).

- `GET ...` answers everything the story workspace shows in one call: for each scene where its
  continuity stands (`not_checked`, `checking`, `reconciling`, `consistent`, `mismatches`), the
  boundaries that do not line up, each shot's flag, the round being worked on and the newest
  job. Worked out on every read.
- `POST .../run` ("Check all continuity") starts a check for every scene whose shots are all
  defined and current, that is not consistent already and is not already being checked.
- `POST .../{scene_id}/run` starts the check of one scene.

A check is made by `services/shot_continuity.py` automatically after a scene's last shot is
defined, and by these buttons. The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.discovery import DiscoveryJobOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import shot_continuity

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The scene's shots are not all defined and current, the scene is not in "
        "the newest list of scenes, or the StoryBible is missing.",
    }
}

ContinuityStatus = Literal["not_checked", "checking", "reconciling", "consistent", "mismatches"]
ContinuityFlag = Literal["not_checked", "ok", "mismatch"]


class ShotContinuityFlagOut(BaseModel):
    """One shot of a scene and where its continuity stands."""

    shot_id: str
    flag: ContinuityFlag
    # What the check found at this shot's boundaries. Empty unless `mismatch`.
    problems: list[str]
    # The round of the check that made this shot's newest definition, when it was defined again
    # for continuity.
    redefined_round: int | None


class ContinuityMismatchOut(BaseModel):
    """A boundary that does not line up. `before` and `after` are a shot id, `scene_start` or
    `scene_end`.
    """

    id: str
    before: str
    after: str
    problem: str


class ContinuityVersionOut(BaseModel):
    """The provenance of the newest check of a scene (D-3)."""

    version: int
    # How many re-definitions for continuity came before this check.
    round: int
    job_id: int | None
    created_at: datetime


class SceneContinuityOut(BaseModel):
    id: str
    index: int
    title: str
    status: ContinuityStatus
    version: ContinuityVersionOut | None
    # The newest check job of this scene, whatever its status.
    job: DiscoveryJobOut | None
    # The round being worked on while `reconciling`, else the newest check's round.
    round: int
    max_rounds: int
    # The boundaries that do not line up. Only when `mismatches`.
    mismatches: list[ContinuityMismatchOut]
    # True when `mismatches` and no more rounds are left.
    round_limit_reached: bool
    shots: list[ShotContinuityFlagOut]
    can_run: bool
    blocked_reason: str | None


class ShotContinuityOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    max_rounds: int
    entries: list[SceneContinuityOut]
    # Why nothing can be checked yet, or None.
    blocked_reason: str | None


class ShotContinuitySkippedOut(BaseModel):
    scene_id: str
    title: str
    reason: str


class ShotContinuityRunManyOut(BaseModel):
    job_ids: list[int]
    skipped: list[ShotContinuitySkippedOut]


class ShotContinuityRunOneOut(BaseModel):
    job_id: int


def _scene_out(scene: shot_continuity.SceneContinuity) -> SceneContinuityOut:
    row = scene.row
    job = scene.job
    return SceneContinuityOut(
        id=scene.item["id"],
        index=scene.item["index"],
        title=scene.item["title"],
        status=scene.status,
        version=(
            ContinuityVersionOut(
                version=row.version,
                round=row.round,
                job_id=row.job_id,
                created_at=row.created_at,
            )
            if row is not None
            else None
        ),
        job=(
            DiscoveryJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        round=scene.round,
        max_rounds=scene.max_rounds,
        mismatches=[ContinuityMismatchOut.model_validate(item) for item in scene.mismatches],
        round_limit_reached=scene.round_limit_reached,
        shots=[
            ShotContinuityFlagOut(
                shot_id=flag.shot_id,
                flag=flag.flag,
                problems=flag.problems,
                redefined_round=flag.redefined_round,
            )
            for flag in scene.shots
        ],
        can_run=scene.can_run,
        blocked_reason=scene.blocked_reason,
    )


def _refused(exc: shot_continuity.ShotContinuityError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/shot-continuity",
    response_model=ShotContinuityOut,
    responses=_NOT_FOUND,
)
async def get_shot_continuity(project_id: int, session: SessionDep) -> ShotContinuityOut:
    project = await load_project(session, project_id)
    result = await shot_continuity.state(session, project)
    return ShotContinuityOut(
        scenes_version=result.scenes_version,
        max_rounds=result.max_rounds,
        entries=[_scene_out(entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/shot-continuity/run",
    response_model=ShotContinuityRunManyOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> ShotContinuityRunManyOut:
    """Starts a check for every scene whose shots are all defined and current, that is not
    consistent already and is not already being checked. The others are skipped, with the
    reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await shot_continuity.start_all(session, project)
    except shot_continuity.ShotContinuityError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return ShotContinuityRunManyOut(
        job_ids=started.job_ids,
        skipped=[
            ShotContinuitySkippedOut(scene_id=item.scene_id, title=item.title, reason=item.reason)
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/shot-continuity/{scene_id}/run",
    response_model=ShotContinuityRunOneOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_scene(
    project_id: int, scene_id: DiscoveryId, session: SessionDep
) -> ShotContinuityRunOneOut:
    """Starts the check of one scene. If it already has a check waiting or running, that job's
    id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await shot_continuity.start_scene(session, project, scene_id)
    except shot_continuity.ShotContinuityError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return ShotContinuityRunOneOut(job_id=job.id)
