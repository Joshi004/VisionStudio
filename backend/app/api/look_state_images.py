"""`/api/projects/{project_id}/look-state-images`: the pictures of the new looks and environment
states (PHASE-017).

- `GET ...` answers everything the story workspace shows in one call: every new named look and
  environment state of the newest resolution (PHASE-016) with the scenes that use it, the status
  of its pictures (`unavailable`, `none`, `in_progress`, `failed`, `ready`), where an unfinished
  one is, why a failed one failed, the look itself (the Character Lab's shape) or the state's
  picture, and whether Make may be pressed. All of it is worked out on every read.
- `POST .../run` ("Make pictures for all") starts every one that has none yet and can be made
  now, skipping (with the reason) every other one.
- `POST .../looks/{record_id}/run` and `POST .../states/{record_id}/run` start one. If its
  pictures are being made already, the same id is returned and nothing new starts. Pressing it
  again after a failure makes a fresh attempt.

A look is made by the Character Lab's own pipeline and a state is one image-edit run
(`services/look_state_images.py`). One angle of a look is made again with the lab's own
endpoint (`POST /api/lab/characters/looks/{look_id}/angles/{angle}`). The answers never return
ORM objects.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, cast

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel

from app.api.character_images import Angle, FailedAngleOut
from app.api.character_lab import LookOut, look_out
from app.api.environment_lab import PictureOut
from app.api.errors import ErrorResponse
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import look_state_images
from app.services.look_state_images import ImageItem
from app.services.storage import media_url

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
RecordId = Annotated[int, Path(ge=1, le=_MAX_ID)]

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no resolution or it is out of date, or the look or state is "
        "not in it, or its character or environment is not ready for it.",
    }
}

Kind = Literal["look", "state"]
Status = Literal["unavailable", "none", "in_progress", "failed", "ready"]
Stage = Literal["drawing", "making_master", "making_angles"]


class LookStateImageItemOut(BaseModel):
    """One new look or environment state of the newest resolution."""

    kind: Kind
    # The id of the named look or the state in the Character Lab library.
    id: int
    slug: str
    name: str
    description: str
    # The discovered character's or environment's id in the project, and its name.
    subject_id: str
    subject_name: str
    # The titles of the scenes that use it.
    scenes: list[str]
    status: Status
    # Only while `status` is `in_progress`.
    stage: Stage | None
    # A look only: how many of the five angles have a picture, and which could not be made.
    angles_ready: int
    failed_angles: list[FailedAngleOut]
    # Why a `failed` item failed.
    error: str | None
    # A look's newest attempt, in the Character Lab's shape. None for a state.
    look: LookOut | None
    # A state's picture, once it has one. None for a look.
    image: PictureOut | None
    can_run: bool
    blocked_reason: str | None
    # Why the pictures of a `ready` item are out of date (PHASE-039); empty when they are not.
    reasons: list[str]


class LookStateImagesOut(BaseModel):
    # None when the project has no resolution of its looks and states yet.
    resolution_version: int | None
    items: list[LookStateImageItemOut]
    # Why nothing can be started at all (no resolution, or it is out of date), or None.
    blocked_reason: str | None


class LookStateSkippedOut(BaseModel):
    kind: Kind
    id: int
    name: str
    reason: str


class LookStateRunAllOut(BaseModel):
    look_ids: list[int]
    state_ids: list[int]
    skipped: list[LookStateSkippedOut]


class LookRunOut(BaseModel):
    look_id: int


class StateRunOut(BaseModel):
    state_id: int


async def _item_out(session: SessionDep, item: ImageItem) -> LookStateImageItemOut:
    return LookStateImageItemOut(
        kind=item.kind,
        id=item.record_id,
        slug=item.slug,
        name=item.name,
        description=item.description,
        subject_id=item.subject_id,
        subject_name=item.subject_name,
        scenes=item.scenes,
        status=item.status,
        stage=item.stage,
        angles_ready=item.angles_ready,
        failed_angles=[
            FailedAngleOut(angle=cast(Angle, failed.angle), error=failed.error)
            for failed in item.failed_angles
        ],
        error=item.error,
        look=await look_out(session, item.look) if item.look is not None else None,
        image=(
            PictureOut(id=item.image.id, url=media_url(item.image.path))
            if item.image is not None
            else None
        ),
        can_run=item.can_run,
        blocked_reason=item.blocked_reason,
        reasons=item.reasons,
    )


def _refused(exc: look_state_images.LookStateImageError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/look-state-images",
    response_model=LookStateImagesOut,
    responses=_NOT_FOUND,
)
async def get_look_state_images(project_id: int, session: SessionDep) -> LookStateImagesOut:
    project = await load_project(session, project_id)
    result = await look_state_images.state(session, project)
    return LookStateImagesOut(
        resolution_version=result.resolution_version,
        items=[await _item_out(session, item) for item in result.items],
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/look-state-images/run",
    response_model=LookStateRunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> LookStateRunAllOut:
    """Starts the pictures of every new look and state that has none yet and can be made now.
    Every other one is skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await look_state_images.start_all(session, project)
    except look_state_images.LookStateImageError as exc:
        raise _refused(exc) from exc
    if started.look_ids or started.state_ids:
        dispatcher.nudge()
    return LookStateRunAllOut(
        look_ids=started.look_ids,
        state_ids=started.state_ids,
        skipped=[
            LookStateSkippedOut(
                kind=item.kind, id=item.record_id, name=item.name, reason=item.reason
            )
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/look-state-images/looks/{record_id}/run",
    response_model=LookRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_look(project_id: int, record_id: RecordId, session: SessionDep) -> LookRunOut:
    """Starts the pictures of one new look. If they are being made already, that look's id is
    returned and no second look is made.
    """
    project = await load_project(session, project_id)
    try:
        look_id, created = await look_state_images.start_look_record(session, project, record_id)
    except look_state_images.LookStateImageError as exc:
        raise _refused(exc) from exc
    if created:
        dispatcher.nudge()
    return LookRunOut(look_id=look_id)


@router.post(
    "/projects/{project_id}/look-state-images/states/{record_id}/run",
    response_model=StateRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_state(project_id: int, record_id: RecordId, session: SessionDep) -> StateRunOut:
    """Starts the picture of one new state. If it is being made already, nothing new starts."""
    project = await load_project(session, project_id)
    try:
        state_id, created = await look_state_images.start_state_record(session, project, record_id)
    except look_state_images.LookStateImageError as exc:
        raise _refused(exc) from exc
    if created:
        dispatcher.nudge()
    return StateRunOut(state_id=state_id)
