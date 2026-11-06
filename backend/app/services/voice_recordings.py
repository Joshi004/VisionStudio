"""Recordings of a person's voice for a recorded explainer (REC-003).

A continuous explainer whose `take_source` is `recorded` has each scene's take recorded by a
person instead of made by the speech model. This module receives one recording, from the browser
or an uploaded file, and makes it the take of one scene:

1. the request is checked against the scene (the project is recorded, the scene has a take, its
   plan is current, and the plan is the one the person was shown);
2. the file is received with a size limit, and its type is decided by ffprobe from its content
   (WAV, MP3, WebM or MP4/M4A, audio only), never by its name or the Content-Type the client sent;
3. FFmpeg converts it to the takes' format (mono, 24 kHz, 16-bit PCM WAV) inside the request,
   and the converted file is probed again;
4. in one transaction the file is stored under the project's media folder, a `voice_recording`
   row (scope `scene`) and a recorded `speech_unit_audio` take row are added, and the job that
   times the words of the take is queued, as `synthesize_speech_unit` does for a generated take.

The two rows share the one converted file. A recording is never changed or deleted afterwards:
recording the scene again adds a newer take, and the newest take that matches the scene's current
text is the scene's take (`speech_synthesis`). Logs hold ids and sizes, never the text.

This module never calls the GPU server.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Project, SpeechUnitAudio, VoiceRecording
from app.services import speech_synthesis, word_timings
from app.services.ffmpeg import ProbeResult, probe
from app.services.speech_audio import SAMPLE_RATE, ConvertError, convert_to_take
from app.services.storage import TempFile, TooLargeError, get_storage

_logger = logging.getLogger(__name__)

ORIGIN_BROWSER: Final = "browser"
ORIGIN_UPLOAD: Final = "upload"
SCOPE_SCENE: Final = "scene"

# ffprobe's `format_name` is a comma-separated list of the demuxer's names: a WebM file is
# "matroska,webm" and an MP4 or M4A file is "mov,mp4,m4a,3gp,3g2,mj2".
_ACCEPTED_FORMATS: Final = ("wav", "mp3", "webm", "mp4", "m4a")
_WAV_CODEC: Final = "pcm_s16le"

CHANGED_WHILE_RECORDING: Final = (
    "The text of this scene changed while you were recording. Record it again."
)
NOT_RECORDED_PROJECT: Final = (
    "This explainer's voice is generated. Choose Recorded voice in the project settings first."
)


class RecordingInputError(Exception):
    """Something the request gets wrong. The message is meant for the user."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class SceneTarget:
    """What a scene recording is for: the text the person reads and the plan it was cut from."""

    text: str
    plan_id: int
    plan_version: int


@dataclass(frozen=True)
class StoredSceneRecording:
    recording_id: int
    take_audio_id: int
    duration_s: float
    timing_job_id: int


# --- Checks -------------------------------------------------------------------------------


def classify_recording(result: ProbeResult | None) -> str:
    """Decides whether a probed file is an acceptable recording and returns its format name
    (`wav`, `mp3`, `webm`, `mp4` or `m4a`). Raises RecordingInputError with a message for the
    user when it is not.

    A container duration is not required: a recording made by a browser (WebM) often has none.
    The length is measured on the converted file instead.
    """
    if result is None:
        raise RecordingInputError(422, "This file could not be read as audio.")
    names = {name.strip() for name in result.format_name.split(",")}
    found = next((name for name in _ACCEPTED_FORMATS if name in names), None)
    if found is None:
        shown = result.format_long_name or result.format_name
        raise RecordingInputError(
            422, f"Send a WAV, MP3, WebM or MP4 recording. This file is {shown}."
        )
    if result.video_stream_count > 0:
        raise RecordingInputError(422, "This file contains video. Send an audio file.")
    if not result.audio_streams:
        raise RecordingInputError(422, "This file has no audio.")
    return found


def check_converted(result: ProbeResult | None) -> float:
    """The length in seconds of the converted file, after checking it is the takes' format.
    Raises RecordingInputError when it is not, or when it is empty.
    """
    if result is None or len(result.audio_streams) != 1:
        raise RecordingInputError(422, "The converted recording could not be read.")
    stream = result.audio_streams[0]
    if stream.codec_name != _WAV_CODEC or stream.sample_rate != SAMPLE_RATE or stream.channels != 1:
        raise RecordingInputError(422, "The recording could not be converted to the voice format.")
    duration_s = result.duration_s if result.duration_s is not None else stream.duration_s
    if duration_s is None or duration_s <= 0:
        raise RecordingInputError(422, "The recording is empty.")
    return duration_s


async def scene_target(
    session: AsyncSession, project: Project, scene_id: str, units_version: int
) -> SceneTarget:
    """The take text and plan a recording of this scene is for. Raises RecordingInputError: 422
    when the project is not recorded or the scene cannot have a recording, 409 when the scene's
    plan is no longer the one the person was shown.
    """
    if not speech_synthesis.is_recorded(project):
        raise RecordingInputError(422, NOT_RECORDED_PROJECT)
    current = await speech_synthesis.state(session, project)
    if current.blocked_reason is not None:
        raise RecordingInputError(422, current.blocked_reason)
    scene = next((item for item in current.scenes if item.scene.item["id"] == scene_id), None)
    if scene is None:
        raise RecordingInputError(
            422, f"There is no scene '{scene_id}' in the newest list of scenes."
        )
    refusal = speech_synthesis.scene_refusal(scene.scene)
    if refusal is not None:
        raise RecordingInputError(422, refusal)
    plan = scene.scene.row
    if scene.take is None or plan is None:
        # A scene with a plan but no units has nothing to read.
        raise RecordingInputError(422, "This scene has no speech to record.")
    if plan.version != units_version:
        raise RecordingInputError(409, CHANGED_WHILE_RECORDING)
    return SceneTarget(text=scene.take.text, plan_id=plan.id, plan_version=plan.version)


# --- Receiving ----------------------------------------------------------------------------


async def receive_scene_recording(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    units_version: int,
    origin: str,
    chunks: AsyncIterable[bytes],
    content_length: int | None,
) -> StoredSceneRecording:
    """Receives, checks, converts and stores a recording of one scene, and makes it the scene's
    take. Commits. The caller has already ended its own read transaction, so none is open while
    the file is received. Temporary files never outlive the call.
    """
    if origin not in (ORIGIN_BROWSER, ORIGIN_UPLOAD):
        raise RecordingInputError(422, "The origin of the recording is not known.")
    project_id = project.id

    await scene_target(session, project, scene_id, units_version)
    max_mb = await settings_service.get_int(session, settings_service.RECORDING_MAX_UPLOAD_MB_KEY)
    # No transaction stays open while the file is received and converted.
    await session.commit()

    max_bytes = max_mb * 1024 * 1024
    too_large = f"The recording is larger than {max_mb} MB."
    if content_length is not None and content_length > max_bytes:
        raise RecordingInputError(413, too_large)

    storage = get_storage()
    source: TempFile | None = None
    converted: Path | None = None
    try:
        try:
            source = await storage.receive(chunks, max_bytes=max_bytes)
        except TooLargeError:
            raise RecordingInputError(413, too_large) from None
        if source.size_bytes == 0:
            raise RecordingInputError(422, "The file is empty.")
        source_format = classify_recording(await probe(source.path))

        converted = storage.new_temp_path("wav")
        try:
            await convert_to_take(source.path, converted)
        except ConvertError as exc:
            raise RecordingInputError(422, str(exc)) from exc
        duration_s = check_converted(await probe(converted))
        wav = await storage.describe_temp(converted)

        # The text may have changed while the file was received and converted.
        target = await scene_target(session, project, scene_id, units_version)
        stored = await storage.save(wav, project_id, "wav")

        recording = VoiceRecording(
            project_id=project_id,
            scope=SCOPE_SCENE,
            scene_id=scene_id,
            text=target.text,
            origin=origin,
            path=stored.relative_path,
            size_bytes=wav.size_bytes,
            sha256=wav.sha256,
            duration_s=duration_s,
            inputs={
                "project_id": project_id,
                "artifacts": [
                    {
                        "kind": "speech_units",
                        "id": target.plan_id,
                        "version": target.plan_version,
                    }
                ],
                "source": {
                    "format": source_format,
                    "size_bytes": source.size_bytes,
                    "sha256": source.sha256,
                },
            },
        )
        session.add(recording)
        try:
            await session.flush()
            take = SpeechUnitAudio(
                project_id=project_id,
                scene_id=scene_id,
                unit_id=None,
                kind=speech_synthesis.KIND_TAKE,
                speaker_id=None,
                text=target.text,
                mode=speech_synthesis.MODE_RECORDED,
                instruction=None,
                voice_id=None,
                audio_key=speech_synthesis.recorded_take_key(target.text, wav.sha256, None, None),
                job_id=None,
                path=stored.relative_path,
                size_bytes=wav.size_bytes,
                sha256=wav.sha256,
                duration_s=duration_s,
                sample_rate=SAMPLE_RATE,
                inputs={
                    "project_id": project_id,
                    "artifacts": [
                        {
                            "kind": "speech_units",
                            "id": target.plan_id,
                            "version": target.plan_version,
                        }
                    ],
                    "recording": {"id": recording.id, "sha256": wav.sha256},
                },
            )
            session.add(take)
            await session.flush()
            # The word timing of a take is always made, and is saved with the take.
            job, _created = await word_timings.queue(session, take, commit=False)
            result = StoredSceneRecording(
                recording_id=recording.id,
                take_audio_id=take.id,
                duration_s=duration_s,
                timing_job_id=job.id,
            )
            await session.commit()
        except BaseException:
            await session.rollback()
            # Stored files are never deleted, so this leaves an unreferenced file behind.
            _logger.warning("recording stored but not recorded: %s", stored.relative_path)
            raise
    finally:
        if source is not None:
            storage.discard(source)
        if converted is not None:
            # Already moved into place after a successful save; discard ignores that.
            storage.discard(converted)

    _logger.info(
        "project %d: scene recording %d stored (%s, %.1fs, %d bytes), timing job %d",
        project_id,
        result.recording_id,
        origin,
        duration_s,
        wav.size_bytes,
        result.timing_job_id,
    )
    return result
