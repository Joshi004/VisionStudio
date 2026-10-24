"""Measuring one sound file, once (MUSIC-003, `Music_implementation_phases.md` 4.6, 4.8).

`measure(session, path, sha256)` is the one way the rest of the app asks "where does this get
loud, where is it quiet, where does it change, does it end". It works for any audio the app
holds (a lab run, a speech recording, an H3 clip's sound, later a music take): a video file is
measured on its first audio stream.

The result belongs to the file's content. It is stored in `audio_measurement`, keyed by the
file's SHA-256 and `audio_analysis.ANALYSIS_VERSION`, so the same bytes are measured once however
many rows point at them, and a changed analysis measures again. The caller passes the hash it
already stores; nothing here hashes a file.

FFmpeg does the loudness (`ffmpeg.scan_loudness`: LUFS, true peak, clipping) and decodes the
sound to mono samples. `audio_analysis` does the rest on those samples, in a worker thread so the
event loop is not held.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Final

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AudioMeasurement
from app.services import audio_analysis, ffmpeg

_logger = logging.getLogger(__name__)

# A longer file is refused: stories are up to about ten minutes (D-13), and a recording past
# fifteen is not something a phase of this plan makes.
MAX_DURATION_S: Final = 900.0
# The short-term loudness is stored every half second (FFmpeg makes it every 0.1 s).
SHORT_TERM_STEP_S: Final = 0.5
# A file whose peak is this close to full scale is clipping (-0.1 dBFS).
CLIPPING_PEAK_DBFS: Final = -0.1


# Every run card asks for its measurements, so the first page after an upgrade can ask for twenty
# new files at once. Each takes a few FFmpeg runs and some CPU: only this many are measured at a
# time, and the rest wait.
_MAX_AT_ONCE: Final = 2
_slots = asyncio.Semaphore(_MAX_AT_ONCE)


class MeasurementError(Exception):
    """The file could not be measured. The message is meant to be shown to the user."""


async def measure(session: AsyncSession, path: Path, sha256: str) -> dict[str, Any]:
    """The measurements of the audio in `path`, whose content hash is `sha256`.

    Reads the stored result when there is one for this hash and this version of the analysis,
    else measures the file and stores the result. Raises `MeasurementError`.
    """
    stored = await _stored(session, sha256)
    if stored is not None:
        return stored

    async with _slots:
        content = await _measure_file(path)
    # Two requests for the same new file may both get here. The first row stays, and both
    # callers return what is stored, so they never disagree.
    statement = (
        insert(AudioMeasurement)
        .values(sha256=sha256, analysis_version=audio_analysis.ANALYSIS_VERSION, content=content)
        .on_conflict_do_nothing(index_elements=["sha256", "analysis_version"])
    )
    await session.execute(statement)
    await session.commit()
    return await _stored(session, sha256) or content


async def _stored(session: AsyncSession, sha256: str) -> dict[str, Any] | None:
    row = await session.scalar(
        select(AudioMeasurement).where(
            AudioMeasurement.sha256 == sha256,
            AudioMeasurement.analysis_version == audio_analysis.ANALYSIS_VERSION,
        )
    )
    if row is None or not isinstance(row.content, dict):
        return None
    return row.content


async def _measure_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MeasurementError("The audio file is missing.")
    probe = await ffmpeg.probe(path)
    stream = probe.audio_streams[0] if probe is not None and probe.audio_streams else None
    if probe is None or stream is None:
        raise MeasurementError("The audio could not be read, or the file has no sound.")
    declared_s = probe.duration_s or stream.duration_s
    if declared_s is not None and declared_s > MAX_DURATION_S:
        raise MeasurementError(
            f"The audio is {declared_s / 60:.0f} minutes long. "
            f"Files up to {MAX_DURATION_S / 60:.0f} minutes are measured."
        )

    scan = await ffmpeg.scan_loudness(path)
    if scan is None:
        raise MeasurementError("The loudness of the audio could not be measured.")
    raw = await ffmpeg.decode_mono_float(
        path, audio_analysis.SAMPLE_RATE, max_seconds=MAX_DURATION_S
    )
    if raw is None:
        raise MeasurementError("The audio could not be decoded.")
    # Whole 4-byte samples only, in case the output was cut short.
    samples = np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<f4").astype(np.float32)
    analysis = await asyncio.to_thread(audio_analysis.analyse, samples)

    return {
        "analysis_version": audio_analysis.ANALYSIS_VERSION,
        "parameters": audio_analysis.PARAMETERS,
        "sample_rate": stream.sample_rate,
        "channels": stream.channels,
        **analysis,
        "loudness": _loudness(scan),
        "short_term_loudness": {
            "step_s": SHORT_TERM_STEP_S,
            "lufs": _short_term_curve(scan.short_term),
        },
    }


def _loudness(scan: ffmpeg.LoudnessScan) -> dict[str, Any]:
    clipping = scan.sample_peak_dbfs is not None and scan.sample_peak_dbfs >= CLIPPING_PEAK_DBFS
    return {
        "integrated_lufs": _rounded(scan.integrated_lufs, 1),
        "loudness_range_lu": _rounded(scan.loudness_range_lu, 1),
        "true_peak_dbtp": _rounded(scan.true_peak_dbtp, 1),
        "sample_peak_dbfs": _rounded(scan.sample_peak_dbfs, 1),
        "clipping": clipping,
        # The samples at the highest level, which is only a count of clipped samples when the
        # highest level is full scale.
        "clipped_sample_count": scan.peak_sample_count if clipping else 0,
    }


def _short_term_curve(pairs: list[tuple[float, float | None]]) -> list[float | None]:
    """The short-term loudness every SHORT_TERM_STEP_S: the value at index i is the loudness of
    the 3 seconds that end at i * SHORT_TERM_STEP_S. None where it is not defined (the first 3
    seconds, and silence)."""
    per_step = round(SHORT_TERM_STEP_S / 0.1)
    curve: list[float | None] = []
    for time_s, value in pairs:
        tenths = round(time_s * 10)
        if tenths % per_step != 0:
            continue
        index = tenths // per_step
        while len(curve) <= index:
            curve.append(None)
        curve[index] = _rounded(value, 1)
    return curve


def _rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)
