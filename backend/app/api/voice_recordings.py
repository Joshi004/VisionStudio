"""`/api/projects/{project_id}/voice-recordings`: the recordings of a recorded explainer (REC-003).

`GET .../full` gives the script of the whole video to read and where the newest full recording
stands (REC-004); `POST .../full` receives a recording of the whole script (the same body and
checks as a scene's) and queues its transcription; `POST .../full/{recording_id}/retry` queues
the job of the newest full recording that failed. `PUT .../full/{recording_id}/boundaries` and
`POST .../full/{recording_id}/boundaries/keep-all` decide the tight boundaries of the newest one,
and `GET .../full/{recording_id}/excerpt` gives a short part of it as a WAV (REC-005).
`POST .../full/{recording_id}/patches` receives a recording of one region of it (a patch, REC-006),
`POST .../patches/splice` splices every accepted patch into a new version of it, and
`POST .../patches/{patch_id}/retry` transcribes a patch again after a failure.

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

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, Field, model_validator

from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.projects import content_length, load_project, require_octet_stream
from app.db.models import Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import full_recordings, speech_synthesis, voice_recordings
from app.services.recording_boundaries import BoundaryDecision

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
    # The window a hand-set cut point may be in, in seconds from the start of the recording.
    min_cut_s: float
    max_cut_s: float
    tight: bool
    reasons: list[str]
    before_words: str
    after_words: str
    # The owner's decision (REC-005): `keep`, `cut_at` or None, and its cut point (for `cut_at`).
    decision: Literal["keep", "cut_at"] | None
    decision_cut_s: float | None
    # Where the recording is cut at this boundary now.
    final_cut_s: float


class RegionBoundaryOut(BaseModel):
    after_scene_id: str
    before_scene_id: str
    tight: bool


class PatchRegionOut(BaseModel):
    """A stretch of the recording that can be recorded again, and its newest patch (REC-006)."""

    first_word: int
    last_word: int
    # What to read, and the same text cut at the scene changes inside it.
    text: str
    parts: list[str]
    before_context: str
    after_context: str
    boundaries: list[RegionBoundaryOut]
    patch_id: int | None
    patch_stage: Literal["transcribing", "transcription_failed", "refused", "accepted"] | None
    patch_message: str | None
    patch_match_percent: float | None


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
    # The tight boundaries nobody has decided.
    open_count: int
    # True when the script was changed after this recording was made.
    script_changed: bool
    # True when "Try again" does something: the transcription or the split failed.
    can_retry: bool
    # True when a tight boundary can be decided now (not while the recording is being split).
    can_decide: bool
    # The stretches that can be recorded again (REC-006).
    regions: list[PatchRegionOut]
    accepted_patch_count: int
    # True when "Splice" does something: a part is accepted and nothing blocks it.
    can_splice: bool
    # True when a part can be recorded or uploaded now.
    can_patch: bool
    splice_stage: Literal["splicing", "splice_failed"] | None
    splice_error: str | None


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


class BoundaryDecisionIn(BaseModel):
    after_scene_id: str = Field(min_length=1, max_length=200)
    before_scene_id: str = Field(min_length=1, max_length=200)
    decision: Literal["keep", "cut_at"]
    # Seconds from the start of the recording: needed for `cut_at`, not allowed for `keep`.
    cut_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _cut_point_matches_decision(self) -> BoundaryDecisionIn:
        if (self.decision == "cut_at") != (self.cut_s is not None):
            raise ValueError("A cut point is needed when, and only when, cutting at it.")
        return self


class DecisionOut(BaseModel):
    # The job that splits the recording again, or None when nothing had to be split.
    split_job_id: int | None


def _decision_name(decided: BoundaryDecision | None) -> Literal["keep", "cut_at"] | None:
    if decided is None:
        return None
    return "cut_at" if decided.decision == "cut_at" else "keep"


def _region_out(item: full_recordings.RegionStatus) -> PatchRegionOut:
    region = item.region
    return PatchRegionOut(
        first_word=region.first_word,
        last_word=region.last_word,
        text=region.text,
        parts=region.parts,
        before_context=region.before_context,
        after_context=region.after_context,
        boundaries=[
            RegionBoundaryOut(
                after_scene_id=boundary.after_scene_id,
                before_scene_id=boundary.before_scene_id,
                tight=boundary.tight,
            )
            for boundary in region.boundaries
        ],
        patch_id=item.patch.id if item.patch is not None else None,
        patch_stage=item.stage,
        patch_message=item.message,
        patch_match_percent=item.match_percent,
    )


def _state_out(
    status: full_recordings.FullRecordingStatus, script: voice_recordings.FullScript
) -> FullRecordingStateOut:
    recording = status.recording
    can_patch = (
        status.stage in full_recordings.DECIDABLE_STAGES and status.splice_stage != "splicing"
    )
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
    boundaries: list[SceneBoundaryOut] = []
    for boundary, final_cut_s in zip(status.boundaries, status.cuts, strict=True):
        decided = status.decisions.get((boundary.after_scene_id, boundary.before_scene_id))
        boundaries.append(
            SceneBoundaryOut(
                after_scene_id=boundary.after_scene_id,
                before_scene_id=boundary.before_scene_id,
                pause_s=boundary.pause_s,
                cut_s=boundary.cut_s,
                min_cut_s=boundary.min_cut_s,
                max_cut_s=boundary.max_cut_s,
                tight=boundary.tight,
                reasons=boundary.reasons,
                before_words=boundary.before_words,
                after_words=boundary.after_words,
                decision=_decision_name(decided),
                decision_cut_s=decided.cut_s if decided else None,
                final_cut_s=final_cut_s,
            )
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
        boundaries=boundaries,
        tight_count=status.tight_count,
        open_count=status.open_count,
        script_changed=script.blocked_reason is None and script.script_key != recorded_key,
        can_retry=status.stage in ("transcription_failed", "split_failed"),
        can_decide=status.stage in full_recordings.DECIDABLE_STAGES,
        regions=[_region_out(item) for item in status.regions],
        accepted_patch_count=status.accepted_count,
        can_splice=can_patch
        and status.accepted_count > 0
        and not any(item.stage == "transcribing" for item in status.regions),
        can_patch=can_patch,
        splice_stage=status.splice_stage,
        splice_error=status.splice_error,
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


# --- Tight boundaries (REC-005) -----------------------------------------------------------------

_DECISION_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    404: {"model": ErrorResponse, "description": "No such project."},
    422: {
        "model": ErrorResponse,
        "description": "The project's voice is not recorded, the recording is not the newest "
        "full recording or cannot be decided now, or the decision is not allowed (not a tight "
        "boundary, or a cut point outside its window or out of order).",
    },
}


async def _recorded_project(session: SessionDep, project_id: int) -> Project:
    project = await load_project(session, project_id)
    if not speech_synthesis.is_recorded(project):
        raise HTTPException(422, voice_recordings.NOT_RECORDED_PROJECT)
    return project


@router.put(
    "/projects/{project_id}/voice-recordings/full/{recording_id}/boundaries",
    response_model=DecisionOut,
    responses=_DECISION_RESPONSES,
)
async def decide_boundary(
    project_id: int,
    recording_id: Annotated[int, Path(ge=1)],
    body: BoundaryDecisionIn,
    session: SessionDep,
) -> DecisionOut:
    """Decides one tight boundary of the newest full recording: keep it as is (cut in the middle
    of the pause) or cut at a point of the owner's choosing. It replaces an earlier decision. The
    recording is split again when nothing is left to decide and a scene has no take at its cuts.
    """
    project = await _recorded_project(session, project_id)
    try:
        job = await full_recordings.decide(
            session,
            project,
            recording_id,
            body.after_scene_id,
            body.before_scene_id,
            body.decision,
            body.cut_s,
        )
    except full_recordings.FullRecordingError as exc:
        raise HTTPException(422, str(exc)) from exc
    if job is not None:
        dispatcher.nudge()
    return DecisionOut(split_job_id=job.id if job is not None else None)


@router.post(
    "/projects/{project_id}/voice-recordings/full/{recording_id}/boundaries/keep-all",
    response_model=DecisionOut,
    responses=_DECISION_RESPONSES,
)
async def keep_all_boundaries(
    project_id: int, recording_id: Annotated[int, Path(ge=1)], session: SessionDep
) -> DecisionOut:
    """Keeps as is every tight boundary of the newest full recording that nobody has decided."""
    project = await _recorded_project(session, project_id)
    try:
        job = await full_recordings.keep_all(session, project, recording_id)
    except full_recordings.FullRecordingError as exc:
        raise HTTPException(422, str(exc)) from exc
    if job is not None:
        dispatcher.nudge()
    return DecisionOut(split_job_id=job.id if job is not None else None)


@router.get(
    "/projects/{project_id}/voice-recordings/full/{recording_id}/excerpt",
    response_class=Response,
    responses={
        200: {
            "description": "A WAV (mono, 24 kHz, 16-bit) of the part asked for.",
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
        },
        404: {"model": ErrorResponse, "description": "No such project or full recording."},
        422: {
            "model": ErrorResponse,
            "description": "The part is empty, longer than 10 seconds or outside the recording.",
        },
    },
)
async def get_recording_excerpt(
    project_id: int,
    recording_id: Annotated[int, Path(ge=1)],
    session: SessionDep,
    start_s: Annotated[float, Query(ge=0, allow_inf_nan=False)],
    end_s: Annotated[float, Query(ge=0, allow_inf_nan=False)],
) -> Response:
    """A part of a full recording, at most 10 seconds, for the player and the cut point editor
    of a tight boundary.
    """
    project = await _recorded_project(session, project_id)
    try:
        wav = await full_recordings.excerpt(session, project, recording_id, start_s, end_s)
    except full_recordings.RecordingNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except full_recordings.FullRecordingError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(content=wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


# --- Patches (REC-006) --------------------------------------------------------------------------


class PatchStoredOut(BaseModel):
    patch_id: int
    duration_s: float
    # The job that transcribes the patch.
    timing_job_id: int


class SpliceOut(BaseModel):
    # The job that splices the accepted patches into a new version of the recording.
    splice_job_id: int


@router.post(
    "/projects/{project_id}/voice-recordings/full/{recording_id}/patches",
    response_model=PatchStoredOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse, "description": "No such project."},
        409: {
            "model": ErrorResponse,
            "description": "The recording is not the newest full recording, or the part to "
            "record has changed since the person was shown it.",
        },
        413: {"model": ErrorResponse, "description": "The file is larger than the limit."},
        415: {
            "model": ErrorResponse,
            "description": "The body is not sent as application/octet-stream.",
        },
        422: {
            "model": ErrorResponse,
            "description": "The project is not recorded, parts cannot be recorded now, or the "
            "file is not acceptable.",
        },
    },
    openapi_extra=_UPLOAD_BODY,
)
async def upload_patch(
    project_id: int,
    recording_id: Annotated[int, Path(ge=1)],
    request: Request,
    session: SessionDep,
    origin: Annotated[Literal["browser", "upload"], Query()],
    first_word: Annotated[int, Query(ge=0, le=2**31)],
    last_word: Annotated[int, Query(ge=0, le=2**31)],
) -> PatchStoredOut:
    """Makes a recording (WAV, MP3, WebM or MP4/M4A, sent as the raw request body) a patch of one
    region of the newest full recording and queues its transcription. The region is named by the
    positions of its first and last words, as the full recording's state lists them.
    """
    require_octet_stream(request)
    project = await load_project(session, project_id)
    try:
        stored = await voice_recordings.receive_patch(
            session,
            project,
            recording_id,
            first_word,
            last_word,
            origin,
            request.stream(),
            content_length(request),
        )
    except voice_recordings.RecordingInputError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    dispatcher.nudge()
    return PatchStoredOut(
        patch_id=stored.patch_id,
        duration_s=stored.duration_s,
        timing_job_id=stored.timing_job_id,
    )


@router.post(
    "/projects/{project_id}/voice-recordings/full/{recording_id}/patches/splice",
    response_model=SpliceOut,
    responses={
        404: {"model": ErrorResponse, "description": "No such project."},
        409: {"model": ErrorResponse, "description": "Not the newest full recording."},
        422: {
            "model": ErrorResponse,
            "description": "The project's voice is not recorded, no part is accepted, or a part "
            "is still being transcribed.",
        },
    },
)
async def splice_patches(
    project_id: int, recording_id: Annotated[int, Path(ge=1)], session: SessionDep
) -> SpliceOut:
    """Splices every accepted patch into the newest full recording as a new version."""
    project = await _recorded_project(session, project_id)
    try:
        job = await full_recordings.queue_splice(session, project, recording_id)
    except full_recordings.PatchTargetChanged as exc:
        raise HTTPException(409, str(exc)) from exc
    except full_recordings.FullRecordingError as exc:
        raise HTTPException(422, str(exc)) from exc
    dispatcher.nudge()
    return SpliceOut(splice_job_id=job.id)


@router.post(
    "/projects/{project_id}/voice-recordings/full/{recording_id}/patches/{patch_id}/retry",
    response_model=RetryOut,
    responses={
        404: {"model": ErrorResponse, "description": "No such project."},
        409: {"model": ErrorResponse, "description": "Not the newest full recording."},
        422: {"model": ErrorResponse, "description": "Nothing failed for this part."},
    },
)
async def retry_patch(
    project_id: int,
    recording_id: Annotated[int, Path(ge=1)],
    patch_id: Annotated[int, Path(ge=1)],
    session: SessionDep,
) -> RetryOut:
    """Queues the transcription of a patch again, when it failed."""
    project = await _recorded_project(session, project_id)
    try:
        job = await full_recordings.retry_patch(session, project, recording_id, patch_id)
    except full_recordings.PatchTargetChanged as exc:
        raise HTTPException(409, str(exc)) from exc
    except full_recordings.FullRecordingError as exc:
        raise HTTPException(422, str(exc)) from exc
    dispatcher.nudge()
    return RetryOut(job_id=job.id)
