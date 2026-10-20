"""`/api/projects/{project_id}/character-images`: the Canonical Character Images stage
(PHASE-010).

- `GET ...` answers everything the story workspace shows in one call: the newest list of
  characters, and for each entry its library character and pinned version, the status of its
  images (`unavailable`, `none`, `in_progress`, `failed`, `ready`, `out_of_date`), where an
  unfinished look is, why a failed one failed, the look itself (the same shape the Character
  Lab uses) and whether Make images may be pressed. All of it is worked out on every read.
- `POST .../run` ("Make images for all") starts a look for every defined character the
  pipeline made that has no images yet or whose images are out of date, skipping (with the
  reason) every other one. A character that is the same person as another (a younger self, an
  older self, a twin) is drawn from that other character's picture: it starts after it and
  waits for it (`made_from`, stage `waiting_for_base`).
- `POST .../{discovery_id}/run` starts the look of one character. A character chosen from the
  library gets one only when the body says `confirm_overwrite: true`. Pressing it again after
  a failure, or to replace images, makes a fresh look.

The look is made by the Character Lab's own pipeline (`services/character_looks.py`) with one
candidate taken as the master. One angle is made again with the lab's own endpoint
(`POST /api/lab/characters/looks/{look_id}/angles/{angle}`). The answers never return ORM
objects.
"""

from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.api.character_lab import LookOut, look_out
from app.api.character_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import character_images
from app.services.character_images import EntryImages

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no list of characters, or the character is not linked, not "
        "defined, out of date, archived, or needs confirming.",
    }
}

Status = Literal["unavailable", "none", "in_progress", "failed", "ready", "out_of_date"]
Stage = Literal["waiting_for_base", "writing_prompt", "making_master", "making_angles"]
Angle = Literal["front", "three_quarter", "profile", "back", "face"]


class FailedAngleOut(BaseModel):
    angle: Angle
    error: str | None


class MadeFromOut(BaseModel):
    """The character a same-face variant is drawn from (PHASE-047)."""

    discovery_id: str
    name: str
    # `younger_self`, `older_self` or `twin`: what this character is to the base.
    kind: Literal["younger_self", "older_self", "twin"]


class ImageEntryOut(BaseModel):
    """One entry of the newest list of characters."""

    id: str
    name: str
    description: str
    # The library character the entry is linked to, and the version the project pins. None
    # while the entry is unlinked.
    character_id: int | None
    character_name: str | None
    pinned_version: int | None
    # Where the definition stands (`Status` of the Character Definition stage).
    definition_status: Literal["unlinked", "not_defined", "defined", "out_of_date"]
    status: Status
    # Only while `status` is `in_progress`.
    stage: Stage | None
    # How many of the five angles have a picture.
    angles_ready: int
    # The angles whose picture could not be made.
    failed_angles: list[FailedAngleOut]
    # Why a `failed` look failed.
    error: str | None
    # Why a `ready` look is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The newest look the pipeline made for this character, in the Character Lab's shape.
    look: LookOut | None
    can_run: bool
    blocked_reason: str | None
    # True for a character chosen from the library: a look changes its current look, so the
    # user is asked first.
    needs_confirmation: bool
    # The character this one is drawn from (a younger or older self, a twin), or None.
    made_from: MadeFromOut | None


class CharacterImagesOut(BaseModel):
    # None when the project has no discovered characters yet.
    discovery_version: int | None
    entries: list[ImageEntryOut]


class ImageRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required for a character chosen from the library.
    confirm_overwrite: bool = False


class ImageSkippedOut(BaseModel):
    discovery_id: str
    name: str
    reason: str


class ImageRunAllOut(BaseModel):
    look_ids: list[int]
    skipped: list[ImageSkippedOut]


class ImageRunOut(BaseModel):
    look_id: int


async def _entry_out(session: SessionDep, item: EntryImages) -> ImageEntryOut:
    definition = item.definition
    info = definition.entry.info
    return ImageEntryOut(
        id=definition.item["id"],
        name=definition.item["name"],
        description=definition.item["description"],
        character_id=info.character.id if info is not None else None,
        character_name=info.character.name if info is not None else None,
        pinned_version=info.link.pinned_version if info is not None else None,
        definition_status=definition.status,
        status=item.status,
        stage=item.stage,
        angles_ready=item.angles_ready,
        failed_angles=[
            FailedAngleOut(angle=cast(Angle, failed.angle), error=failed.error)
            for failed in item.failed_angles
        ],
        error=item.error,
        reasons=item.reasons,
        look=await look_out(session, item.look) if item.look is not None else None,
        can_run=item.can_run,
        blocked_reason=item.blocked_reason,
        needs_confirmation=item.needs_confirmation,
        made_from=(
            MadeFromOut(
                discovery_id=item.made_from.discovery_id,
                name=item.made_from.name,
                kind=cast(Literal["younger_self", "older_self", "twin"], item.made_from.kind),
            )
            if item.made_from is not None
            else None
        ),
    )


def _refused(exc: character_images.CharacterImageError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/character-images",
    response_model=CharacterImagesOut,
    responses=_NOT_FOUND,
)
async def get_character_images(project_id: int, session: SessionDep) -> CharacterImagesOut:
    project = await load_project(session, project_id)
    result = await character_images.state(session, project)
    return CharacterImagesOut(
        discovery_version=result.discovery_version,
        entries=[await _entry_out(session, item) for item in result.entries],
    )


@router.post(
    "/projects/{project_id}/character-images/run",
    response_model=ImageRunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> ImageRunAllOut:
    """Starts a look for every defined character the pipeline made that has no images yet or
    whose images are out of date. Every other character is skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await character_images.start_all(session, project)
    except character_images.CharacterImageError as exc:
        raise _refused(exc) from exc
    if started.look_ids:
        dispatcher.nudge()
    return ImageRunAllOut(
        look_ids=started.look_ids,
        skipped=[
            ImageSkippedOut(discovery_id=item.discovery_id, name=item.name, reason=item.reason)
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/character-images/{discovery_id}/run",
    response_model=ImageRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_one(
    project_id: int,
    discovery_id: DiscoveryId,
    session: SessionDep,
    body: ImageRunIn | None = None,
) -> ImageRunOut:
    """Starts the look of one character. If it already has a look being made, that look's id
    is returned and no second look is made.
    """
    project = await load_project(session, project_id)
    try:
        look, created = await character_images.start_run(
            session,
            project,
            discovery_id,
            confirm_overwrite=body.confirm_overwrite if body is not None else False,
        )
    except character_images.CharacterImageError as exc:
        raise _refused(exc) from exc
    if created:
        dispatcher.nudge()
    return ImageRunOut(look_id=look.id)
