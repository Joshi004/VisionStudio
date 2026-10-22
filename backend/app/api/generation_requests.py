"""`/api/projects/{project_id}/generation-requests`: the generation request of each shot
(PHASE-025).

- `GET ...` answers everything the story workspace shows in one call: the newest list of scenes,
  and for each scene its shots (from the newest shot plan) with the status of each shot's request
  (`not_planned`, `planned`, `out_of_date`), why it is out of date, the newest request (route,
  endpoint, frame count, size, the ordered pictures and the ordered dialogue audios, with their
  addresses) with its provenance, and whether Plan may be pressed. Out of date is worked out on
  every read.
- `POST .../run` ("Plan all") plans every shot, in every scene, that has none or an out of date
  request.
- `POST .../{scene_id}/run` does the same for one scene.
- `POST .../{scene_id}/{shot_id}/run` does it for one shot.

Planning is done by code in the request, with no model, no job and no call to the GPU server, so
the answer is 200 and says which shots were done and which were skipped and why. A request is a
new version of the shot's request (`services/generation_requests.py`). The answers never return
ORM objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.projects import load_project
from app.db.models import LabImage, SpeechUnitAudio
from app.db.session import SessionDep
from app.services import generation_requests, shot_prompts, storage
from app.services.generation_requests import SceneEntry, ShotEntry

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The shot's references are not chosen and current, its speech is not "
        "ready, its length is outside the limits, or the scene or shot is not in the newest "
        "list of scenes and shot plan.",
    }
}

Source = Literal["ai", "manual"]
Status = Literal["not_planned", "planned", "out_of_date"]
ShotType = Literal["establishing", "action", "reaction", "dialogue", "insert", "transition"]
PictureKind = Literal["character", "environment"]
ManifestStatus = Literal["not_selected", "selected", "out_of_date"]
Route = Literal["reference", "text"]


class RequestPictureOut(BaseModel):
    """One picture of the request, in the order it is sent. A prompt calls it `<Picture n>`."""

    label: str
    order: int
    lab_image_id: int
    # None when the picture no longer exists.
    url: str | None
    kind: PictureKind
    subject_id: str
    subject_name: str
    view: str
    variant: str


class RequestAudioOut(BaseModel):
    """One dialogue audio of the request, in the order it is sent. A prompt calls it
    `<Audio n>`.
    """

    label: str
    order: int
    unit_id: str
    speaker_id: str
    text: str
    # False when the speaker is not in the shot: the voice comes from an unseen speaker (Q-4).
    speaker_visible: bool
    speech_unit_audio_id: int
    # None when the file is no longer stored.
    url: str | None
    duration_s: float
    starts_in_shot_seconds: float
    # How the audio is used by the video model. `partially_copy` today.
    marker: str


class GenerationRequestOut(BaseModel):
    model: str
    route: Route
    endpoint: str
    orientation: str
    width: int
    height: int
    fps: int
    # The shot's length on the timeline, and the frame count asked for it (the smallest
    # `17n + 5` at or above it).
    target_seconds: float
    num_frames: int
    clip_seconds: float
    match_audio_duration: bool
    pictures: list[RequestPictureOut]
    audios: list[RequestAudioOut]
    notes: list[str]


class GenerationRequestVersionOut(BaseModel):
    """The provenance of the newest request of a shot (D-3)."""

    version: int
    source: Source
    created_at: datetime


class RequestShotSkeletonOut(BaseModel):
    id: str
    type: ShotType
    description: str
    duration_seconds: float


class GenerationRequestEntryOut(BaseModel):
    shot: RequestShotSkeletonOut
    # Where the shot's reference manifest stands: the request is planned from it.
    manifest_status: ManifestStatus
    status: Status
    # Why a planned request is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    request: GenerationRequestOut | None
    version: GenerationRequestVersionOut | None
    can_run: bool
    blocked_reason: str | None


class SceneGenerationRequestsOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    description: str
    shots: list[GenerationRequestEntryOut]


class GenerationRequestsOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    entries: list[SceneGenerationRequestsOut]
    # Why nothing can be planned yet, or None.
    blocked_reason: str | None


class GenerationPlannedOut(BaseModel):
    scene_id: str
    shot_id: str
    version: int


class GenerationSkippedOut(BaseModel):
    scene_id: str
    shot_id: str | None
    title: str
    reason: str


class GenerationRequestsRunOut(BaseModel):
    planned: list[GenerationPlannedOut]
    skipped: list[GenerationSkippedOut]


@dataclass(frozen=True)
class _Urls:
    pictures: dict[int, str]
    audios: dict[int, str]


async def _urls(state: generation_requests.GenerationRequestsState, session: SessionDep) -> _Urls:
    """The address of every picture and audio the newest requests name, by id."""
    picture_ids: set[int] = set()
    audio_ids: set[int] = set()
    for scene in state.entries:
        for shot in scene.shots:
            if shot.row is not None:
                picture_ids.update(item["lab_image_id"] for item in shot.row.content["pictures"])
                audio_ids.update(
                    item["speech_unit_audio_id"] for item in shot.row.content["audios"]
                )
    pictures: dict[int, str] = {}
    audios: dict[int, str] = {}
    if picture_ids:
        rows = (
            await session.execute(
                select(LabImage.id, LabImage.path).where(LabImage.id.in_(picture_ids))
            )
        ).all()
        pictures = {image_id: storage.media_url(path) for image_id, path in rows}
    if audio_ids:
        rows = (
            await session.execute(
                select(SpeechUnitAudio.id, SpeechUnitAudio.path).where(
                    SpeechUnitAudio.id.in_(audio_ids), SpeechUnitAudio.path.is_not(None)
                )
            )
        ).all()
        audios = {audio_id: storage.media_url(path) for audio_id, path in rows if path is not None}
    return _Urls(pictures=pictures, audios=audios)


def _request_out(content: dict[str, Any], urls: _Urls) -> GenerationRequestOut:
    return GenerationRequestOut(
        model=content["model"],
        route=content["route"],
        endpoint=content["endpoint"],
        orientation=content["orientation"],
        width=content["width"],
        height=content["height"],
        fps=content["fps"],
        target_seconds=content["target_seconds"],
        num_frames=content["num_frames"],
        clip_seconds=content["clip_seconds"],
        match_audio_duration=content["match_audio_duration"],
        pictures=[
            RequestPictureOut(**picture, url=urls.pictures.get(picture["lab_image_id"]))
            for picture in content["pictures"]
        ],
        audios=[
            RequestAudioOut(**audio, url=urls.audios.get(audio["speech_unit_audio_id"]))
            for audio in content["audios"]
        ],
        notes=content["notes"],
    )


def _shot_out(entry: ShotEntry, urls: _Urls) -> GenerationRequestEntryOut:
    shot = entry.shot
    row = entry.row
    return GenerationRequestEntryOut(
        shot=RequestShotSkeletonOut(
            id=shot["id"],
            type=shot["type"],
            description=shot["description"],
            duration_seconds=entry.duration_s,
        ),
        manifest_status=cast(ManifestStatus, entry.manifest_status),
        status=entry.status,
        reasons=entry.reasons,
        request=_request_out(row.content, urls) if row is not None else None,
        version=(
            GenerationRequestVersionOut(
                version=row.version,
                # The database CHECK constraint keeps `source` to the two allowed values.
                source=cast(Source, row.source),
                created_at=row.created_at,
            )
            if row is not None
            else None
        ),
        can_run=entry.can_run,
        blocked_reason=entry.blocked_reason,
    )


def _scene_out(entry: SceneEntry, urls: _Urls) -> SceneGenerationRequestsOut:
    return SceneGenerationRequestsOut(
        id=entry.item["id"],
        index=entry.item["index"],
        title=entry.item["title"],
        description=entry.item["description"],
        shots=[_shot_out(shot, urls) for shot in entry.shots],
    )


def _run_out(result: generation_requests.PlanResult) -> GenerationRequestsRunOut:
    return GenerationRequestsRunOut(
        planned=[
            GenerationPlannedOut(scene_id=item.scene_id, shot_id=item.shot_id, version=item.version)
            for item in result.planned
        ],
        skipped=[
            GenerationSkippedOut(
                scene_id=item.scene_id, shot_id=item.shot_id, title=item.title, reason=item.reason
            )
            for item in result.skipped
        ],
    )


def _refused(exc: generation_requests.GenerationRequestsError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


async def _compile_prompts(project_id: int, result: generation_requests.PlanResult) -> None:
    """Queues the prompt of each shot whose request was just planned (PHASE-026). It never
    fails the press: a shot that cannot be compiled yet is left for the user's **Compile**.
    """
    for item in result.planned:
        await shot_prompts.queue_after_planning(project_id, item.scene_id, item.shot_id)


@router.get(
    "/projects/{project_id}/generation-requests",
    response_model=GenerationRequestsOut,
    responses=_NOT_FOUND,
)
async def get_generation_requests(project_id: int, session: SessionDep) -> GenerationRequestsOut:
    project = await load_project(session, project_id)
    result = await generation_requests.state(session, project)
    urls = await _urls(result, session)
    return GenerationRequestsOut(
        scenes_version=result.scenes_version,
        entries=[_scene_out(entry, urls) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/generation-requests/run",
    response_model=GenerationRequestsRunOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> GenerationRequestsRunOut:
    """Plans the request of every shot that has none or an out of date one. The shots that
    cannot be done are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        result = await generation_requests.plan_all(session, project)
    except generation_requests.GenerationRequestsError as exc:
        raise _refused(exc) from exc
    await _compile_prompts(project_id, result)
    return _run_out(result)


@router.post(
    "/projects/{project_id}/generation-requests/{scene_id}/run",
    response_model=GenerationRequestsRunOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_scene(
    project_id: int, scene_id: DiscoveryId, session: SessionDep
) -> GenerationRequestsRunOut:
    """Plans the request of every shot of one scene that has none or an out of date one."""
    project = await load_project(session, project_id)
    try:
        result = await generation_requests.plan_scene(session, project, scene_id)
    except generation_requests.GenerationRequestsError as exc:
        raise _refused(exc) from exc
    await _compile_prompts(project_id, result)
    return _run_out(result)


@router.post(
    "/projects/{project_id}/generation-requests/{scene_id}/{shot_id}/run",
    response_model=GenerationRequestsRunOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_shot(
    project_id: int, scene_id: DiscoveryId, shot_id: DiscoveryId, session: SessionDep
) -> GenerationRequestsRunOut:
    """Plans the request of one shot. Refused with the reason when it cannot be done."""
    project = await load_project(session, project_id)
    try:
        result = await generation_requests.plan_shot(session, project, scene_id, shot_id)
    except generation_requests.GenerationRequestsError as exc:
        raise _refused(exc) from exc
    await _compile_prompts(project_id, result)
    return _run_out(result)
