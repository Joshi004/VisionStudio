"""Saved voices (Phase 21): a clean recording and its exact transcript, which Breeze TTS clones.

A voice comes from one of two places:

- an upload: the recording is received, checked with ffprobe (the type is decided by what
  ffprobe finds in the file, never by its name or the Content-Type the client sent: WAV, MP3,
  M4A or FLAC, audio only) and stored under `media/lab/`;
- a Voice lab run: the run's WAV is not copied, the voice points at the same stored file.

A voice is never deleted, like every stored file, and its recording never changes. Its name
and transcript can be edited. A job copies the recording's path and the transcript into its own
input when it starts, so editing a voice later never changes a speech that is already under
way.

This module never calls the GPU server.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LabVoiceRun, Voice
from app.providers import speech_synthesizer
from app.services.ffmpeg import ProbeResult, probe
from app.services.storage import TooLargeError, get_storage

_logger = logging.getLogger(__name__)

NAME_MAX_CHARS: Final = 80
TRANSCRIPT_MAX_CHARS: Final = speech_synthesizer.REFERENCE_TEXT_MAX_CHARS
# A recording to clone a voice from is short. This is far more than needed.
VOICE_MAX_MB: Final = 50
VOICE_MAX_BYTES: Final = VOICE_MAX_MB * 1024 * 1024
LIST_LIMIT: Final = 200


class VoiceInputError(Exception):
    """Something the request gets wrong. The message is meant for the user."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def clean_name(name: str) -> str:
    """The name without surrounding space. Raises VoiceInputError when it is blank or long."""
    name = name.strip()
    if not name:
        raise VoiceInputError(422, "Give the voice a name.")
    if len(name) > NAME_MAX_CHARS:
        raise VoiceInputError(422, f"The name must be at most {NAME_MAX_CHARS} characters.")
    return name


def clean_transcript(transcript: str) -> str:
    """The transcript without surrounding space. Raises VoiceInputError when it is blank or
    too long for the server.
    """
    transcript = transcript.strip()
    if not transcript:
        raise VoiceInputError(
            422, "Write what the recording says, word for word. The server needs it."
        )
    if len(transcript) > TRANSCRIPT_MAX_CHARS:
        raise VoiceInputError(
            422, f"The transcript must be at most {TRANSCRIPT_MAX_CHARS:,} characters."
        )
    return transcript


@dataclass(frozen=True)
class AcceptedAudio:
    ext: str
    mime: str
    duration_s: float


@dataclass(frozen=True)
class _AudioFormat:
    ext: str
    mime: str


# ffprobe's `format_name` is a comma-separated list of the demuxer's names. An M4A
# file is reported as "mov,mp4,m4a,3gp,3g2,mj2", so it is recognised by the "m4a" entry.
_FORMATS: Final[dict[str, _AudioFormat]] = {
    "wav": _AudioFormat("wav", "audio/wav"),
    "mp3": _AudioFormat("mp3", "audio/mpeg"),
    "flac": _AudioFormat("flac", "audio/flac"),
    "m4a": _AudioFormat("m4a", "audio/mp4"),
}


def _audio_duration(result: ProbeResult) -> float | None:
    """The container's duration, or else the longest audio stream's."""
    if result.duration_s is not None and result.duration_s > 0:
        return result.duration_s
    durations = [s.duration_s for s in result.audio_streams if s.duration_s is not None]
    longest = max(durations, default=None)
    return longest if longest is not None and longest > 0 else None


def classify_audio(result: ProbeResult | None) -> AcceptedAudio:
    """Decides whether a probed file is an acceptable recording.

    Raises VoiceInputError with a message for the user when it is not.
    """
    if result is None:
        raise VoiceInputError(422, "This file could not be read as audio.")

    names = {name.strip() for name in result.format_name.split(",")}
    audio_format = next((_FORMATS[name] for name in _FORMATS if name in names), None)
    if audio_format is None:
        found = result.format_long_name or result.format_name
        raise VoiceInputError(422, f"Upload a WAV, MP3, M4A or FLAC file. This file is {found}.")
    if result.video_stream_count > 0:
        raise VoiceInputError(422, "This file contains video. Upload an audio file.")
    if not result.audio_streams:
        raise VoiceInputError(422, "This file has no audio.")

    duration_s = _audio_duration(result)
    if duration_s is None:
        raise VoiceInputError(422, "Could not read the length of this audio.")
    return AcceptedAudio(ext=audio_format.ext, mime=audio_format.mime, duration_s=duration_s)


async def list_voices(session: AsyncSession) -> list[Voice]:
    statement = (
        select(Voice)
        .order_by(Voice.id.desc())
        .limit(LIST_LIMIT)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars().all())


async def get_voice(session: AsyncSession, voice_id: int) -> Voice | None:
    return await session.get(Voice, voice_id)


async def create_from_upload(
    session: AsyncSession,
    name: str,
    transcript: str,
    chunks: AsyncIterable[bytes],
    content_length: int | None,
) -> Voice:
    """Receives, checks and stores a recording and saves it as a voice. Commits.

    The caller has already ended its own read transaction, so none is open while the file is
    received and probed. A temp file never outlives a failed upload.
    """
    name = clean_name(name)
    transcript = clean_transcript(transcript)
    too_large = f"The recording is larger than {VOICE_MAX_MB} MB."
    if content_length is not None and content_length > VOICE_MAX_BYTES:
        raise VoiceInputError(413, too_large)

    storage = get_storage()
    try:
        temp = await storage.receive(chunks, max_bytes=VOICE_MAX_BYTES)
    except TooLargeError:
        raise VoiceInputError(413, too_large) from None

    try:
        if temp.size_bytes == 0:
            raise VoiceInputError(422, "The file is empty.")
        accepted = classify_audio(await probe(temp.path))
        stored = await storage.save_lab(temp, accepted.ext)
    except BaseException:
        # After a successful save the temp file is already gone; discard ignores that.
        storage.discard(temp)
        raise

    voice = Voice(
        name=name,
        path=stored.relative_path,
        mime=accepted.mime,
        size_bytes=temp.size_bytes,
        sha256=temp.sha256,
        duration_s=accepted.duration_s,
        transcript=transcript,
        origin="upload",
    )
    session.add(voice)
    try:
        await session.commit()
    except BaseException:
        # Stored files are never deleted, so this leaves an unreferenced file behind.
        _logger.warning("voice recording stored but not recorded: %s", stored.relative_path)
        raise
    _logger.info(
        "voice saved: id=%d upload %.1fs %d bytes", voice.id, accepted.duration_s, temp.size_bytes
    )
    return voice


async def create_from_run(
    session: AsyncSession,
    run_id: int,
    name: str,
    transcript: str | None,
    *,
    commit: bool = True,
) -> Voice:
    """Saves the speech a Voice lab run made as a voice. Commits, unless `commit` is False: the
    voice is then only flushed, so a caller (the story pipeline) can attach it and commit
    everything together. The recording is the run's own file. `transcript` is what the speech
    says; left out, it is the run's text.
    """
    name = clean_name(name)
    run = await session.get(LabVoiceRun, run_id)
    if run is None:
        raise VoiceInputError(404, f"There is no voice lab run {run_id}.")
    if run.path is None or run.size_bytes is None or run.sha256 is None or run.duration_s is None:
        raise VoiceInputError(409, "This run has no speech yet.")
    voice = Voice(
        name=name,
        path=run.path,
        mime="audio/wav",
        size_bytes=run.size_bytes,
        sha256=run.sha256,
        duration_s=run.duration_s,
        transcript=clean_transcript(run.text if transcript is None else transcript),
        origin="lab_run",
        lab_voice_run_id=run.id,
    )
    session.add(voice)
    if commit:
        await session.commit()
    else:
        await session.flush()
    _logger.info("voice saved: id=%d from lab run %d", voice.id, run.id)
    return voice


async def update_voice(
    session: AsyncSession, voice_id: int, name: str | None, transcript: str | None
) -> Voice:
    """Changes a voice's name and/or transcript. Commits. Raises VoiceInputError."""
    voice = await session.get(Voice, voice_id)
    if voice is None:
        raise VoiceInputError(404, f"Voice {voice_id} does not exist.")
    if name is not None:
        voice.name = clean_name(name)
    if transcript is not None:
        voice.transcript = clean_transcript(transcript)
    await session.commit()
    return voice
