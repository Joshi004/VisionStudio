"""Does a repaint or an inpaint leave the sound outside its window alone? (MUSIC-005, case L3;
the check MUSIC-004 left open.)

The source and the result are decoded to mono at 24 kHz and compared sample by sample, away
from the window (a margin on each side is left out, because the edit blends in and out of the
window). The server may also change the level of the whole result (the first real ACE-Step
repaint came back about 1 dB quieter than its source, and otherwise identical), so the result
is first scaled by the best single gain. The answer is the size of what is left of the
difference against the size of the source, in dB: -200 means identical, and the gain is
reported next to it. No GPU, no stored result: it is computed when asked.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np

from app.services import ffmpeg

SAMPLE_RATE: Final = 24_000
MARGIN_S: Final = 1.0
MAX_SECONDS: Final = 600.0
# The result counts as "unchanged outside" at or below this many dB. Provisional: it is set from
# the first real repaint (MUSIC-004 / MUSIC-005).
UNCHANGED_DB: Final = -40.0
_FLOOR_DB: Final = -200.0
# The result may be a few samples longer or shorter than the source.
_MIN_COMPARED_S: Final = 0.5


class OutsideWindowError(Exception):
    """The comparison cannot be made. The message is meant for the user."""


@dataclass(frozen=True)
class OutsideWindow:
    window_start_s: float
    window_end_s: float
    margin_s: float
    # How much sound outside the window and its margins was compared, in seconds.
    compared_s: float
    # The difference against the source outside the window, and inside it, in dB. Inside is None
    # when the window is empty.
    outside_db: float
    inside_db: float | None
    # The level of the result against the source outside the window, in dB (0: the same).
    gain_db: float
    unchanged: bool
    threshold_db: float


def _db(difference: np.ndarray, source: np.ndarray) -> float:
    source_power = float(np.mean(np.square(source, dtype=np.float64)))
    difference_power = float(np.mean(np.square(difference, dtype=np.float64)))
    if source_power <= 0.0:
        return _FLOOR_DB
    if difference_power <= 0.0:
        return _FLOOR_DB
    return max(_FLOOR_DB, 10.0 * math.log10(difference_power / source_power))


async def _decode(path: Path) -> np.ndarray:
    raw = await ffmpeg.decode_mono_float(path, SAMPLE_RATE, max_seconds=MAX_SECONDS)
    if raw is None or len(raw) < 4:
        raise OutsideWindowError("The audio could not be read.")
    return np.frombuffer(raw[: len(raw) - len(raw) % 4], dtype="<f4").astype(np.float64)


async def compare(
    source_path: Path, result_path: Path, window_start_s: float, window_end_s: float | None
) -> OutsideWindow:
    """Compares the result with the source outside `[window_start_s, window_end_s]` (the end of
    the source when `window_end_s` is None). Raises OutsideWindowError.
    """
    source = await _decode(source_path)
    result = await _decode(result_path)
    count = min(len(source), len(result))
    source, result = source[:count], result[:count]
    end_s = window_end_s if window_end_s is not None else count / SAMPLE_RATE
    index = np.arange(count) / SAMPLE_RATE
    outside = (index < window_start_s - MARGIN_S) | (index > end_s + MARGIN_S)
    inside = (index >= window_start_s) & (index <= end_s)
    if int(np.count_nonzero(outside)) < _MIN_COMPARED_S * SAMPLE_RATE:
        raise OutsideWindowError("There is too little sound outside the window to compare.")

    source_power = float(np.dot(source[outside], source[outside]))
    gain = (
        float(np.dot(result[outside], source[outside])) / source_power if source_power > 0 else 1.0
    )
    if gain <= 0:
        gain = 1.0
    difference = result - gain * source
    outside_db = _db(difference[outside], source[outside])
    inside_db = _db(difference[inside], source[inside]) if np.any(inside) else None
    return OutsideWindow(
        window_start_s=window_start_s,
        window_end_s=end_s,
        margin_s=MARGIN_S,
        compared_s=float(np.count_nonzero(outside)) / SAMPLE_RATE,
        outside_db=outside_db,
        inside_db=inside_db,
        gain_db=20.0 * math.log10(gain),
        unchanged=outside_db <= UNCHANGED_DB,
        threshold_db=UNCHANGED_DB,
    )
