"""`/api/projects/{project_id}/voice-recordings`: the recordings of a recorded explainer (REC-003).

`GET .../full` gives the script of the whole video to read and where the newest full recording
stands (REC-004); `POST .../full` receives a recording of the whole script (the same body and
checks as a scene's) and queues its transcription; `POST .../full/{recording_id}/retry` queues
the job of the newest full recording that failed.

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

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel

from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.projects import content_length, load_project, require_octet_stream
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import full_recordings, speech_synthesis, voice_recordings

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


# --- A full recording (REC-004) ----------------------------------------------------------------


class ScriptSceneOut(BaseModel):
    scene_id: str
    index: int | None
    title: str
    # What the person reads for this scene, word for word.
    text: str


class FullScriptOut(BaseModel):
    scenes: list[ScriptSceneOut]
    # Identifies this text: it is sent back with the recording, so a script that changed in the
    # meantime is refused.
    script_key: str
    # Why nothing can be recorded yet, or None.
    blocked_reason: str | None


class SceneBoundaryOut(BaseModel):
    after_scene_id: str
    before_scene_id: str
    # The silence between the two scenes' words, and where the recording would be cut.
    pause_s: float
    cut_s: float
    tight: bool
    reasons: list[str]
    before_words: str
    after_words: str


class FullRecordingStateOut(BaseModel):
    recording_id: int
    version: int
    origin: str
    duration_s: float
    stage: Literal[
        "transcribing",
        "transcription_failed",
        "refused",
        "tight",
        "splitting",
        "split_failed",
        "split",
    ]
    # One sentence about where it stands.
    message: str
    match_percent: float | None
    threshold: int | None
    error: str | None
    boundaries: list[SceneBoundaryOut]
    tight_count: int
    # True when the script was changed after this recording was made.
    script_changed: bool
    # True when "Try again" does something: the transcription or the split failed.
    can_retry: bool


class FullRecordingOut(BaseModel):
    script: FullScriptOut
    newest: FullRecordingStateOut | None


class FullRecordingStoredOut(BaseModel):
    recording_id: int
    version: int
    duration_s: float
    timing_job_id: int


class RetryOut(BaseModel):
    job_id: int


def _state_out(
    status: full_recordings.FullRecordingStatus, script: voice_recordings.FullScript
) -> FullRecordingStateOut:
    recording = status.recording
    recorded_key = voice_recordings.script_key_of(
        [
            voice_recordings.ScriptScene(
                scene_id=scene.scene_id,
                index=None,
                title="",
                text=scene.text,
                plan_id=0,
                plan_version=0,
            )
            for scene in status.scenes
        ]
    )
    return FullRecordingStateOut(
        recording_id=recording.id,
        version=recording.version or 0,
        origin=recording.origin,
        duration_s=recording.duration_s,
        stage=status.stage,
        message=full_recordings.stage_message(status),
        match_percent=status.match_percent,
        threshold=status.threshold,
        error=status.error,
        boundaries=[
            SceneBoundaryOut(
                after_scene_id=boundary.after_scene_id,
                before_scene_id=boundary.before_scene_id,
                pause_s=boundary.pause_s,
                cut_s=boundary.cut_s,
                tight=boundary.tight,
                reasons=boundary.reasons,
                before_words=boundary.before_words,
                after_words=boundary.after_words,
            )
            for boundary in status.boundaries
        ],
        tight_count=status.tight_count,
        script_changed=script.blocked_reason is None and script.script_key != recorded_key,
        can_retry=status.stage in ("transcription_failed", "split_failed"),
    )


@router.get(
    "/projects/{project_id}/voice-recordings/full",
    response_model=FullRecordingOut,
    responses={
        404: {"model": ErrorResponse, "description": "No such project."},
        422: {"model": ErrorResponse, "description": "The project's voice is not recorded."},
    },
)
async def get_full_recording(project_id: int, session: SessionDep) -> FullRecordingOut:
    """The script of the whole video to read, and where the newest full recording stands. Worked
    out on every read.
    """
    project = await load_project(session, project_id)
    if not speech_synthesis.is_recorded(project):
        raise HTTPException(422, voice_recordings.NOT_RECORDED_PROJECT)
    script = await voice_recordings.full_script(session, project)
    newest = await full_recordings.newest(session, project)
    return FullRecordingOut(
        script=FullScriptOut(
            scenes=[
                ScriptSceneOut(
                    scene_id=scene.scene_id,
                    index=scene.index,
                    title=scene.title,
                    text=scene.text,
                )
                for scene in script.scenes
            ],
            script_key=script.script_key,
            blocked_reason=script.blocked_reason,
        ),
        newest=_state_out(newest, script) if newest is not None else None,
    )


@router.post(
    "/projects/{project_id}/voice-recordings/full",
    response_model=FullRecordingStoredOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse, "description": "No such project."},
        409: {
            "model": ErrorResponse,
            "description": "The script changed since the person was shown it.",
        },
        413: {"model": ErrorResponse, "description": "The file is larger than the limit."},
        415: {
            "model": ErrorResponse,
            "description": "The body is not sent as application/octet-stream.",
        },
        422: {
            "model": ErrorResponse,
            "description": "The project is not recorded, a scene's speech is not planned, or "
            "the file is not acceptable.",
        },
    },
    openapi_extra=_UPLOAD_BODY,
)
async def upload_full_recording(
    project_id: int,
    request: Request,
    session: SessionDep,
    origin: Annotated[Literal["browser", "upload"], Query()],
    script_key: Annotated[str, Query(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")],
) -> FullRecordingStoredOut:
    """Makes a recording of the whole script (WAV, MP3, WebM or MP4/M4A, sent as the raw request
    body) the project's newest full recording and queues its transcription.
    """
    require_octet_stream(request)
    project = await load_project(session, project_id)
    try:
        stored = await voice_recordings.receive_full_recording(
            session,
            project,
            script_key,
            origin,
            request.stream(),
            content_length(request),
        )
    except voice_recordings.RecordingInputError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    dispatcher.nudge()
    return FullRecordingStoredOut(
        recording_id=stored.recording_id,
        version=stored.version,
        duration_s=stored.duration_s,
        timing_job_id=stored.timing_job_id,
    )


@router.post(
    "/projects/{project_id}/voice-recordings/full/{recording_id}/retry",
    response_model=RetryOut,
    responses={
        404: {"model": ErrorResponse, "description": "No such project."},
        422: {
            "model": ErrorResponse,
            "description": "The recording is not the newest full recording, or nothing failed.",
        },
    },
)
async def retry_full_recording(
    project_id: int, recording_id: Annotated[int, Path(ge=1)], session: SessionDep
) -> RetryOut:
    """Queues the transcription or the split of the newest full recording again, when it failed."""
    project = await load_project(session, project_id)
    if not speech_synthesis.is_recorded(project):
        raise HTTPException(422, voice_recordings.NOT_RECORDED_PROJECT)
    try:
        job = await full_recordings.retry(session, project, recording_id)
    except full_recordings.FullRecordingError as exc:
        raise HTTPException(422, str(exc)) from exc
    dispatcher.nudge()
    return RetryOut(job_id=job.id)
