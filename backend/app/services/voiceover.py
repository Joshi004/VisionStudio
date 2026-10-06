"""Receiving, checking and storing the voiceover (ANALYSIS.md Section 3.5, 5.1 and 5.9).

The type of an upload is decided by what ffprobe finds in the file, never by
its name or the Content-Type the client sent. Only WAV, MP3, M4A and FLAC are
accepted: all four are on the transcription endpoint's list (Section 5.1), so
Phase 5 can send the file as it is, and all four play in current browsers.

The voiceover is kept exactly as uploaded. A new upload creates a new asset and
repoints the project at it; the old file and its row stay (stored files are
never deleted in iteration 1).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from dataclasses import dataclass
from typing import Final

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, Project
from app.services.assets import add_asset
from app.services.ffmpeg import ProbeResult, probe
from app.services.storage import TooLargeError, get_storage

_logger = logging.getLogger(__name__)

VOICEOVER_MAX_MB: Final = 400
VOICEOVER_MAX_BYTES: Final = VOICEOVER_MAX_MB * 1024 * 1024

TOO_LARGE_MESSAGE: Final = f"The file is larger than {VOICEOVER_MAX_MB} MB."


class VoiceoverRejected(Exception):
    """An upload that is refused. The message is meant to be shown to the user."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


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


def classify(result: ProbeResult | None) -> AcceptedAudio:
    """Decides whether a probed file is an acceptable voiceover.

    Raises VoiceoverRejected with a message for the user when it is not.
    """
    if result is None:
        raise VoiceoverRejected(422, "This file could not be read as audio.")

    names = {name.strip() for name in result.format_name.split(",")}
    audio_format = next((_FORMATS[name] for name in _FORMATS if name in names), None)
    if audio_format is None:
        found = result.format_long_name or result.format_name
        raise VoiceoverRejected(422, f"Upload a WAV, MP3, M4A or FLAC file. This file is {found}.")
    if result.video_stream_count > 0:
        raise VoiceoverRejected(422, "This file contains video. Upload an audio file.")
    if not result.audio_streams:
        raise VoiceoverRejected(422, "This file has no audio.")

    duration_s = _audio_duration(result)
    if duration_s is None:
        raise VoiceoverRejected(422, "Could not read the length of this audio.")
    return AcceptedAudio(ext=audio_format.ext, mime=audio_format.mime, duration_s=duration_s)


async def upload_voiceover(
    session: AsyncSession,
    project_id: int,
    chunks: AsyncIterable[bytes],
    content_length: int | None,
) -> Asset:
    """Receives, checks and stores a voiceover, then points the project at it.

    The caller has already checked that the project exists and has ended its
    own read transaction, so none is open while the file is received and probed.
    A temp file never outlives a failed upload.
    """
    if content_length is not None and content_length > VOICEOVER_MAX_BYTES:
        raise VoiceoverRejected(413, TOO_LARGE_MESSAGE)

    storage = get_storage()
    try:
        temp = await storage.receive(chunks, max_bytes=VOICEOVER_MAX_BYTES)
    except TooLargeError:
        raise VoiceoverRejected(413, TOO_LARGE_MESSAGE) from None

    try:
        if temp.size_bytes == 0:
            raise VoiceoverRejected(422, "The file is empty.")
        accepted = classify(await probe(temp.path))
        stored = await storage.save(temp, project_id, accepted.ext)
    except BaseException:
        # After a successful save the temp file is already gone; discard ignores that.
        storage.discard(temp)
        raise

    try:
        asset = await add_asset(
            session,
            project_id=project_id,
            kind="voiceover",
            stored=stored,
            mime=accepted.mime,
            size_bytes=temp.size_bytes,
            sha256=temp.sha256,
            source="upload",
            duration_s=accepted.duration_s,
        )
        await session.execute(
            update(Project).where(Project.id == project_id).values(voiceover_asset_id=asset.id)
        )
        await session.commit()
    except BaseException:
        # Stored files are never deleted, so this leaves an unreferenced file behind.
        _logger.warning("voiceover stored but not recorded: %s", stored.relative_path)
        raise

    _logger.info(
        "voiceover stored: project=%d asset=%d %s %.1fs %d bytes",
        project_id,
        asset.id,
        accepted.ext,
        accepted.duration_s,
        temp.size_bytes,
    )
    return asset
