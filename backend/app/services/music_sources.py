"""The audio an edit in the Music lab starts from (MUSIC-004).

An edit (`music_lab.create_edits`) has exactly one source:

- a finished lab run, used where it is (`lab_music_run.source_run_id`): nothing is copied;
- an uploaded recording (`lab_music_source`, kind `upload`): received, checked with ffprobe (the
  type is what ffprobe finds, never the file name: WAV, MP3, M4A or FLAC, audio only) and stored
  under `media/lab/`;
- two finished lab runs put end to end, with silence between them and after them if asked
  (`lab_music_source`, kind `join`): made once with FFmpeg and stored, so it can be played and
  used by many edits. The recipe keeps where each part sits in the joined file, so the seam is
  known (a seam test repaints a window centred on it).

Stored files are never deleted. This module never calls the GPU server.
"""

from __future__ import annotations

import logging
import math
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LabMusicRun, LabMusicSource
from app.services import ffmpeg, voices
from app.services.storage import StorageError, TooLargeError, get_storage

_logger = logging.getLogger(__name__)

# The largest recording any editing model takes (ACE-Step: 600 s). A longer one is refused at the
# door, and each model's own limit is checked when an edit is made.
SOURCE_MAX_S: Final = 600.0
SOURCE_MAX_MB: Final = 200
SOURCE_MAX_BYTES: Final = SOURCE_MAX_MB * 1024 * 1024
LABEL_MAX_CHARS: Final = 80
# Silence between the two parts of a join, and after them.
JOIN_SILENCE_MAX_S: Final = 30.0
LIST_LIMIT: Final = 30

_MIMES: Final = {
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}


class MusicSourceError(Exception):
    """Something the request gets wrong. The message is meant for the user."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class ResolvedSource:
    """What an edit job needs to upload its source."""

    # The stored file, as a path under the media folder.
    path: str
    filename: str
    mime: str
    duration_s: float
    label: str
    run_id: int | None
    source_id: int | None


def clean_label(label: str) -> str:
    label = " ".join(label.split())
    if not label:
        raise MusicSourceError(422, "Give the recording a name.")
    if len(label) > LABEL_MAX_CHARS:
        raise MusicSourceError(422, f"The name must be at most {LABEL_MAX_CHARS} characters.")
    return label


def _mime_of(path: str) -> str:
    return _MIMES.get(Path(path).suffix.lower(), "application/octet-stream")


# --- Uploads ------------------------------------------------------------------------------


async def save_upload(
    session: AsyncSession,
    name: str,
    chunks: AsyncIterable[bytes],
    content_length: int | None,
) -> LabMusicSource:
    """Receives, checks and stores a recording and saves it as a source. Commits.

    The caller has already ended its own read transaction, so none is open while the file is
    received and probed. A temp file never outlives a failed upload.
    """
    label = clean_label(name)
    too_large = f"The recording is larger than {SOURCE_MAX_MB} MB."
    if content_length is not None and content_length > SOURCE_MAX_BYTES:
        raise MusicSourceError(413, too_large)

    storage = get_storage()
    try:
        temp = await storage.receive(chunks, max_bytes=SOURCE_MAX_BYTES)
    except TooLargeError:
        raise MusicSourceError(413, too_large) from None

    try:
        if temp.size_bytes == 0:
            raise MusicSourceError(422, "The file is empty.")
        probed = await ffmpeg.probe(temp.path)
        try:
            accepted = voices.classify_audio(probed)
        except voices.VoiceInputError as exc:
            raise MusicSourceError(exc.status_code, exc.message) from exc
        if accepted.duration_s > SOURCE_MAX_S:
            raise MusicSourceError(
                422,
                f"The recording is {accepted.duration_s:.0f} s long; the editing models take at "
                f"most {SOURCE_MAX_S:.0f} s.",
            )
        stream = probed.audio_streams[0] if probed is not None and probed.audio_streams else None
        stored = await storage.save_lab(temp, accepted.ext)
    except BaseException:
        # After a successful save the temp file is already gone; discard ignores that.
        storage.discard(temp)
        raise

    source = LabMusicSource(
        kind="upload",
        label=label,
        path=stored.relative_path,
        size_bytes=temp.size_bytes,
        sha256=temp.sha256,
        duration_s=accepted.duration_s,
        sample_rate=stream.sample_rate if stream is not None else None,
        channels=stream.channels if stream is not None else None,
    )
    session.add(source)
    try:
        await session.commit()
    except BaseException:
        # Stored files are never deleted, so this leaves an unreferenced file behind.
        _logger.warning("music source stored but not recorded: %s", stored.relative_path)
        raise
    _logger.info("music source saved: id=%d upload %.1f s", source.id, accepted.duration_s)
    return source


# --- Joins --------------------------------------------------------------------------------


def _silence(name: str, value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or not 0 <= value <= JOIN_SILENCE_MAX_S
    ):
        raise MusicSourceError(422, f"The {name} must be from 0 to {JOIN_SILENCE_MAX_S:g} seconds.")
    return float(value)


async def make_join(
    session: AsyncSession, run_ids: list[int], gap_s: object, tail_s: object
) -> LabMusicSource:
    """Puts two finished lab runs end to end, `gap_s` seconds of silence between them and
    `tail_s` after them, and saves the result as a source. Commits.
    """
    if len(run_ids) != 2:
        raise MusicSourceError(422, "A join takes exactly two runs.")
    gap = _silence("gap", gap_s)
    tail = _silence("silence at the end", tail_s)

    storage = get_storage()
    paths: list[Path] = []
    durations: list[float] = []
    for run_id in run_ids:
        run = await session.get(LabMusicRun, run_id)
        if run is None:
            raise MusicSourceError(422, f"Run {run_id} does not exist.")
        if run.path is None or run.duration_s is None:
            raise MusicSourceError(422, f"Run {run_id} has no audio yet.")
        try:
            path = storage.get_path(run.path)
        except StorageError:
            raise MusicSourceError(422, f"Run {run_id}'s file could not be found.") from None
        if not path.is_file():
            raise MusicSourceError(422, f"Run {run_id}'s file could not be found on disk.")
        paths.append(path)
        durations.append(run.duration_s)

    expected = sum(durations) + gap + tail
    if expected > SOURCE_MAX_S:
        raise MusicSourceError(
            422,
            f"The join would be {expected:.0f} s long; the editing models take at most "
            f"{SOURCE_MAX_S:.0f} s.",
        )

    temp_path = storage.new_temp_path("flac")
    try:
        problem = await ffmpeg.join_audio(paths, temp_path, gap_s=gap, tail_s=tail)
        if problem is not None:
            raise MusicSourceError(422, problem)
        probed = await ffmpeg.probe(temp_path)
        stream = probed.audio_streams[0] if probed is not None and probed.audio_streams else None
        duration = (
            (probed.duration_s or (stream.duration_s if stream else None)) if probed else None
        )
        if stream is None or duration is None:
            raise MusicSourceError(422, "The joined audio could not be read.")
        temp = await storage.describe_temp(temp_path)
        stored = await storage.save_lab(temp, "flac")
    except BaseException:
        storage.discard(temp_path)
        raise

    first_end = durations[0]
    second_start = first_end + gap
    recipe: dict[str, Any] = {
        "parts": [
            {"run_id": run_ids[0], "start_s": 0.0, "end_s": first_end},
            {"run_id": run_ids[1], "start_s": second_start, "end_s": second_start + durations[1]},
        ],
        "gap_s": gap,
        "tail_s": tail,
    }
    source = LabMusicSource(
        kind="join",
        label=f"Run {run_ids[0]} + run {run_ids[1]}",
        path=stored.relative_path,
        size_bytes=temp.size_bytes,
        sha256=temp.sha256,
        duration_s=duration,
        sample_rate=stream.sample_rate,
        channels=stream.channels,
        recipe=recipe,
    )
    session.add(source)
    try:
        await session.commit()
    except BaseException:
        _logger.warning("music join stored but not recorded: %s", stored.relative_path)
        raise
    _logger.info(
        "music join saved: id=%d runs=%s %.1f s (expected %.1f s)",
        source.id,
        run_ids,
        duration,
        expected,
    )
    return source


def seam_s(source: LabMusicSource) -> float | None:
    """The middle of the join of two runs, in seconds from the start of the joined file. None
    for a source that is not a join."""
    recipe = source.recipe
    if source.kind != "join" or not isinstance(recipe, dict):
        return None
    parts = recipe.get("parts")
    gap = recipe.get("gap_s")
    if not isinstance(parts, list) or len(parts) != 2 or not isinstance(parts[0], dict):
        return None
    end = parts[0].get("end_s")
    if not isinstance(end, int | float) or not isinstance(gap, int | float):
        return None
    return float(end) + float(gap) / 2


# --- Reading ------------------------------------------------------------------------------


async def list_sources(session: AsyncSession) -> list[LabMusicSource]:
    statement = (
        select(LabMusicSource)
        .order_by(LabMusicSource.id.desc())
        .limit(LIST_LIMIT)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars().all())


async def get_source(session: AsyncSession, source_id: int) -> LabMusicSource | None:
    return await session.get(LabMusicSource, source_id)


async def resolve(
    session: AsyncSession, *, run_id: int | None, source_id: int | None
) -> ResolvedSource:
    """The file an edit starts from. Exactly one of `run_id` and `source_id` is given. Raises
    MusicSourceError, with a message for the user.
    """
    if (run_id is None) == (source_id is None):
        raise MusicSourceError(422, "Choose one source: a run, an upload or a join.")
    storage = get_storage()
    if run_id is not None:
        run = await session.get(LabMusicRun, run_id)
        if run is None:
            raise MusicSourceError(422, f"Run {run_id} does not exist.")
        if run.path is None or run.duration_s is None:
            raise MusicSourceError(422, f"Run {run_id} has no audio yet.")
        path, duration, label = run.path, run.duration_s, f"Run {run_id}"
        filename_stem = f"lab-source-run-{run_id}"
    else:
        assert source_id is not None
        source = await session.get(LabMusicSource, source_id)
        if source is None:
            raise MusicSourceError(422, f"Source {source_id} does not exist.")
        path, duration, label = source.path, source.duration_s, source.label
        filename_stem = f"lab-source-{source_id}"
    try:
        if not storage.get_path(path).is_file():
            raise MusicSourceError(422, "The source's file could not be found on disk.")
    except StorageError:
        raise MusicSourceError(422, "The source's file could not be found.") from None
    # The server reads the file's type from the extension, so the stored one is kept.
    suffix = Path(path).suffix.lower()
    return ResolvedSource(
        path=path,
        filename=f"{filename_stem}{suffix}",
        mime=_mime_of(path),
        duration_s=duration,
        label=label,
        run_id=run_id,
        source_id=source_id,
    )
