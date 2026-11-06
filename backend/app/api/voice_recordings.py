"""`/api/projects/{project_id}/voice-recordings`: the recordings of a recorded explainer (REC-003).

`POST .../scenes/{scene_id}` receives one recording of one scene, as the raw request body (the
browser recorder's file or an uploaded one), and makes it the scene's take. The file is checked
and converted in the request (`services/voice_recordings.py`); the take is ready when the answer
comes, and the job that times its words is already queued. `origin` says where the file came
from (`browser` or `upload`), and `units_version` is the version of the scene's speech units the
person was shown, so a scene whose text changed in the meantime is refused with 409.

The answers never return ORM objects.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.projects import content_length, load_project, require_octet_stream
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import voice_recordings

router = APIRouter()

_UPLOAD_BODY: Final[dict[str, Any]] = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


class SceneRecordingOut(BaseModel):
    recording_id: int
    # The scene's new take (a `speech_unit_audio` row).
    take_audio_id: int
    duration_s: float
    # The job that times the words of the take.
    timing_job_id: int


@router.post(
    "/projects/{project_id}/voice-recordings/scenes/{scene_id}",
    response_model=SceneRecordingOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse, "description": "No such project."},
        409: {
            "model": ErrorResponse,
            "description": "The scene's text changed since the person was shown it.",
        },
        413: {"model": ErrorResponse, "description": "The file is larger than the limit."},
        415: {
            "model": ErrorResponse,
            "description": "The body is not sent as application/octet-stream.",
        },
        422: {
            "model": ErrorResponse,
            "description": "The project is not recorded, the scene cannot have a recording, or "
            "the file is not acceptable.",
        },
    },
    openapi_extra=_UPLOAD_BODY,
)
async def upload_scene_recording(
    project_id: int,
    scene_id: DiscoveryId,
    request: Request,
    session: SessionDep,
    origin: Annotated[Literal["browser", "upload"], Query()],
    units_version: Annotated[int, Query(ge=1, le=2**31)],
) -> SceneRecordingOut:
    """Makes a recording (WAV, MP3, WebM or MP4/M4A, sent as the raw request body) the take of
    one scene of a recorded explainer. A scene recorded again gets a newer take that replaces it.
    """
    require_octet_stream(request)
    project = await load_project(session, project_id)
    try:
        stored = await voice_recordings.receive_scene_recording(
            session,
            project,
            scene_id,
            units_version,
            origin,
            request.stream(),
            content_length(request),
        )
    except voice_recordings.RecordingInputError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    dispatcher.nudge()
    return SceneRecordingOut(
        recording_id=stored.recording_id,
        take_audio_id=stored.take_audio_id,
        duration_s=stored.duration_s,
        timing_job_id=stored.timing_job_id,
    )
