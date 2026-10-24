"""What is in a sound: silences, the loudest moment, sudden sounds, quiet points, places where the
sound changes character, and how it ends (MUSIC-003, `Music_implementation_phases.md` 4.6, 4.8).

Pure functions on an array of samples. Nothing here reads a file or the database: the caller
(`services/audio_measurements.py`) decodes the file with FFmpeg to mono float samples at
`SAMPLE_RATE` and passes them in. Loudness in LUFS and true peak are measured by FFmpeg
(`ffmpeg.scan_loudness`), not here.

Everything runs on one grid of 20 ms frames. Times in a result are seconds from the start of
the file. Every number that decides a result is a constant below, and `PARAMETERS` is stored with
each result, so a stored result says how it was made. **Raise `ANALYSIS_VERSION` whenever a
constant or a rule changes**, so files are measured again.

Limits worth knowing (the thresholds are starting values, tuned by ear on real recordings):

- Onset times are good to about 50 ms (a sound already playing at the start of the file is an
  onset at about 0.03 s). They tell where a sudden sound begins, not exactly which
  sample; a later phase refines a point it must place exactly.
- Change points need 2 s of sound on each side, so none is reported in the first or the last 2 s.
- A change point is where the *spectrum* (and so also the level) moves, which is what a person
  hears as "the music changes". Beatless score has no beat to lean on, so a slow change gives a
  weak peak. A weak result is reported as weak (`strength`), not hidden.
"""

from __future__ import annotations

import math
from typing import Any, Final

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

ANALYSIS_VERSION: Final = 1

# Samples are decoded at this rate. 22.05 kHz keeps everything a person hears as sudden or
# changing (up to 11 kHz) and keeps a ten-minute recording small.
SAMPLE_RATE: Final = 22050

# The grid: one frame is 20 ms.
FRAME_SAMPLES: Final = SAMPLE_RATE // 50
FRAME_S: Final = FRAME_SAMPLES / SAMPLE_RATE

# --- silences --------------------------------------------------------------------------------
# A frame is silent when it is this far below the loud level of the file (the 95th percentile of
# the frame levels), and never above SILENCE_CEILING_DB. The relative rule makes it work for a
# quiet voice and a loud score alike.
SILENCE_BELOW_LOUD_DB: Final = 40.0
SILENCE_LOUD_PERCENTILE: Final = 95.0
SILENCE_FLOOR_DB: Final = -70.0
# A silence inside the sound must last this long to be listed.
MIN_SILENCE_S: Final = 0.25
# Below this peak the whole file is treated as digital silence (-100 dBFS).
SILENT_PEAK: Final = 1e-5

# --- the loudest moment ----------------------------------------------------------------------
LOUDEST_WINDOW_FRAMES: Final = 5  # a 100 ms envelope

# --- spectrum (onsets and change points) -----------------------------------------------------
N_FFT: Final = 1024
BLOCK_FRAMES: Final = 400  # frames per block of the spectrum, to bound memory
# Spectra are averaged over 5 frames (0.1 s) for the change points.
BUCKET_FRAMES: Final = 5
BUCKET_S: Final = BUCKET_FRAMES * FRAME_S

# --- onsets ----------------------------------------------------------------------------------
ONSET_STD: Final = 3.0  # standard deviations above the file's mean spectral flux
ONSET_MIN_GAP_S: Final = 0.08
MAX_ONSETS: Final = 100

# --- quiet points ----------------------------------------------------------------------------
QUIET_WINDOW_FRAMES: Final = 25  # a 0.5 s envelope
QUIET_NEIGHBOURHOOD_S: Final = 1.5  # the lowest point within this distance either side
QUIET_BELOW_MEDIAN_DB: Final = 6.0
QUIET_MIN_GAP_S: Final = 2.0
MAX_QUIET_POINTS: Final = 10

# --- change points ---------------------------------------------------------------------------
CHANGE_SPAN_S: Final = 2.0  # the sound this long before is compared with this long after
CHANGE_STD: Final = 1.5
CHANGE_MIN_GAP_S: Final = 3.0
MAX_CHANGE_POINTS: Final = 8

# --- the ending ------------------------------------------------------------------------------
ENDING_TAIL_S: Final = 0.5  # the last part of the sound before its trailing silence
ENDING_LOUD_PERCENTILE: Final = 90.0
# The tail this far under the loud level of the piece, or more, is a decay. Less is a cut.
ENDING_DECAY_DB: Final = 6.0

# What is stored with a result.
PARAMETERS: Final[dict[str, Any]] = {
    "sample_rate": SAMPLE_RATE,
    "frame_s": FRAME_S,
    "silence_below_loud_db": SILENCE_BELOW_LOUD_DB,
    "silence_floor_db": SILENCE_FLOOR_DB,
    "min_silence_s": MIN_SILENCE_S,
    "onset_std": ONSET_STD,
    "onset_min_gap_s": ONSET_MIN_GAP_S,
    "quiet_below_median_db": QUIET_BELOW_MEDIAN_DB,
    "quiet_min_gap_s": QUIET_MIN_GAP_S,
    "change_span_s": CHANGE_SPAN_S,
    "change_std": CHANGE_STD,
    "change_min_gap_s": CHANGE_MIN_GAP_S,
    "ending_tail_s": ENDING_TAIL_S,
    "ending_decay_db": ENDING_DECAY_DB,
}

Samples = NDArray[np.float32]


def analyse(samples: Samples) -> dict[str, Any]:
    """Measures mono float samples at `SAMPLE_RATE`. Returns a JSON-ready dictionary with
    `duration_s`, `leading_silence_s`, `trailing_silence_s`, `silences`, `loudest_moment`,
    `onsets`, `quiet_points`, `change_points` and `ending`.

    A file too short for one frame, or all silence, has empty lists and `None` where a moment or
    an ending cannot exist.
    """
    duration_s = len(samples) / SAMPLE_RATE
    result: dict[str, Any] = {
        "duration_s": _round(duration_s, 3),
        "leading_silence_s": 0.0,
        "trailing_silence_s": 0.0,
        "silences": [],
        "loudest_moment": None,
        "onsets": [],
        "quiet_points": [],
        "change_points": [],
        "ending": None,
    }
    frame_count = len(samples) // FRAME_SAMPLES
    if frame_count < 1:
        return result

    energy = _frame_energy(samples, frame_count)
    level_db = _to_db(energy)
    peak = float(np.max(np.abs(samples)))
    if peak < SILENT_PEAK:
        result["leading_silence_s"] = result["trailing_silence_s"] = _round(duration_s, 3)
        return result

    silent = _silent_frames(level_db)
    runs = _runs(silent)
    leading_frames = runs[0][1] if runs and runs[0][0] == 0 else 0
    trailing_frames = frame_count - runs[-1][0] if runs and runs[-1][1] == frame_count else 0
    result["leading_silence_s"] = _round(leading_frames * FRAME_S, 3)
    result["trailing_silence_s"] = _round(trailing_frames * FRAME_S, 3)
    result["silences"] = [
        {"start_s": _round(start * FRAME_S, 3), "end_s": _round(end * FRAME_S, 3)}
        for start, end in runs
        if start > 0 and end < frame_count and (end - start) * FRAME_S >= MIN_SILENCE_S
    ]

    result["loudest_moment"] = _loudest_moment(energy)
    result["quiet_points"] = _quiet_points(energy, leading_frames, frame_count - trailing_frames)
    result["ending"] = _ending(energy, leading_frames, frame_count - trailing_frames)

    flux, buckets = _spectrum(samples / peak)
    result["onsets"] = _onsets(flux)
    result["change_points"] = _change_points(buckets)
    return result


# --- the frame grid --------------------------------------------------------------------------


def _frame_energy(samples: Samples, frame_count: int) -> NDArray[np.float64]:
    """The mean square of each 20 ms frame."""
    frames = samples[: frame_count * FRAME_SAMPLES].reshape(frame_count, FRAME_SAMPLES)
    return np.mean(np.square(frames, dtype=np.float64), axis=1)


def _to_db(energy: NDArray[np.float64]) -> NDArray[np.float64]:
    """Mean square as dB relative to full scale. Silence reads -120 and never -inf."""
    return 10.0 * np.log10(np.maximum(energy, 1e-12))


def _moving_mean(values: NDArray[np.float64], width: int) -> NDArray[np.float64]:
    """The mean of every `width` frames in a row. Shorter than the input by `width - 1`, so no
    window is ever cut off at an edge (which would pull the ends towards silence)."""
    return np.convolve(values, np.full(width, 1.0 / width), mode="valid")


def _centre_s(index: int, width: int) -> float:
    """The time at the middle of the window of `width` frames that starts at frame `index`."""
    return (index + width / 2) * FRAME_S


def _round(value: float, digits: int) -> float:
    return round(float(value), digits)


# --- silences --------------------------------------------------------------------------------


def _silent_frames(level_db: NDArray[np.float64]) -> NDArray[np.bool_]:
    loud = float(np.percentile(level_db, SILENCE_LOUD_PERCENTILE))
    threshold = max(loud - SILENCE_BELOW_LOUD_DB, SILENCE_FLOOR_DB)
    return level_db <= threshold


def _runs(mask: NDArray[np.bool_]) -> list[tuple[int, int]]:
    """The runs of True in `mask` as (first frame, one past the last frame)."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(start), int(end)) for start, end in zip(edges[::2], edges[1::2], strict=True)]


# --- the loudest moment, quiet points, the ending --------------------------------------------


def _loudest_moment(energy: NDArray[np.float64]) -> dict[str, float] | None:
    """The middle of the loudest 100 ms. A 100 ms window, not the 3 s of short-term loudness, so
    the crack of an effect is found where it is."""
    if len(energy) < LOUDEST_WINDOW_FRAMES:
        return None
    envelope = _moving_mean(energy, LOUDEST_WINDOW_FRAMES)
    index = int(np.argmax(envelope))
    return {
        "time_s": _round(_centre_s(index, LOUDEST_WINDOW_FRAMES), 3),
        "level_db": _round(float(_to_db(envelope[index : index + 1])[0]), 1),
    }


def _quiet_points(
    energy: NDArray[np.float64], first_frame: int, end_frame: int
) -> list[dict[str, float]]:
    """The lowest points of the sound between its leading and trailing silence: the lowest 0.5 s
    envelope within QUIET_NEIGHBOURHOOD_S either side, at least QUIET_BELOW_MEDIAN_DB under the
    median of the envelope. The quietest come first in the choice; the answer is in time order.
    """
    span = energy[first_frame:end_frame]
    if len(span) < QUIET_WINDOW_FRAMES:
        return []
    level = _to_db(_moving_mean(span, QUIET_WINDOW_FRAMES))
    reach = round(QUIET_NEIGHBOURHOOD_S / FRAME_S)
    padded = np.pad(level, reach, mode="edge")
    lowest_nearby = sliding_window_view(padded, 2 * reach + 1).min(axis=1)
    is_lowest = level <= lowest_nearby
    limit = float(np.median(level)) - QUIET_BELOW_MEDIAN_DB
    candidates = np.flatnonzero(is_lowest & (level <= limit))
    # The quietest points first, so a dip is kept over a nearby shallower one.
    chosen = _spread(
        sorted(candidates.tolist(), key=lambda i: level[i]),
        round(QUIET_MIN_GAP_S / FRAME_S),
        MAX_QUIET_POINTS,
    )
    return [
        {
            "time_s": _round(_centre_s(first_frame + i, QUIET_WINDOW_FRAMES), 3),
            "level_db": _round(float(level[i]), 1),
        }
        for i in chosen
    ]


def _ending(energy: NDArray[np.float64], first_frame: int, end_frame: int) -> dict[str, Any] | None:
    """Whether the sound dies away or is cut off. The last ENDING_TAIL_S before the trailing
    silence is compared with the loud level of the piece (the 90th percentile of its 100 ms
    envelope). Under it by ENDING_DECAY_DB or more is a `decay` (a real ending or a fade); less is a
    `cut`, which stops while still as loud as the piece.

    A cut in the middle of a quiet passage reads as a decay: what is measured is how loud the
    last moment is, not whether the music finished a phrase.
    """
    span = energy[first_frame:end_frame]
    if len(span) < 1:
        return None
    tail_frames = min(len(span), max(1, round(ENDING_TAIL_S / FRAME_S)))
    tail_db = float(_to_db(np.array([np.mean(span[-tail_frames:])]))[0])
    if len(span) >= LOUDEST_WINDOW_FRAMES:
        envelope = _moving_mean(span, LOUDEST_WINDOW_FRAMES)
    else:
        envelope = span
    loud_db = float(np.percentile(_to_db(envelope), ENDING_LOUD_PERCENTILE))
    drop_db = loud_db - tail_db
    return {
        "kind": "decay" if drop_db >= ENDING_DECAY_DB else "cut",
        "end_level_db": _round(tail_db, 1),
        "drop_db": _round(drop_db, 1),
    }


def _spread(ordered: list[int], min_gap: int, limit: int) -> list[int]:
    """Takes indexes in the order given, skipping any closer than `min_gap` to one already
    taken, up to `limit`. Returns the taken indexes in ascending order."""
    taken: list[int] = []
    for index in ordered:
        if len(taken) >= limit:
            break
        if all(abs(index - other) >= min_gap for other in taken):
            taken.append(index)
    return sorted(taken)


# --- the spectrum: onsets and change points --------------------------------------------------


def _spectrum(samples: Samples) -> tuple[NDArray[np.float64], NDArray[np.float32]]:
    """Spectral flux per frame and the average log-spectrum per 0.1 s.

    The spectrum is worked out in blocks, so a long recording never holds all of it at once.
    `samples` are scaled so the loudest sample is 1, which makes the numbers comparable between
    quiet and loud files.

    Returns (`flux`, `buckets`): `flux[i]` is how much the log-spectrum of frame i rose over that
    of frame i - 1, and `flux[0]` how much it rose over silence (so a sound that starts at full
    strength is an onset at the very start); `buckets[j]` is the mean log-spectrum of frames
    `5j .. 5j + 4`. A last group of fewer than 5 frames is dropped.
    """
    if len(samples) < N_FFT:
        samples = np.pad(samples, (0, N_FFT - len(samples)))
    frames = sliding_window_view(samples, N_FFT)[::FRAME_SAMPLES]
    window = np.hanning(N_FFT).astype(np.float32)
    bins = N_FFT // 2 + 1

    flux = np.zeros(len(frames))
    bucket_blocks: list[NDArray[np.float32]] = []
    previous: NDArray[np.float32] | None = None
    for start in range(0, len(frames), BLOCK_FRAMES):
        block = frames[start : start + BLOCK_FRAMES] * window
        log_spectrum = np.log1p(np.abs(np.fft.rfft(block, axis=1))).astype(np.float32)
        before = np.zeros_like(log_spectrum[:1]) if previous is None else previous
        rise = np.diff(log_spectrum, axis=0, prepend=before)
        flux[start : start + len(block)] = np.maximum(rise, 0).sum(axis=1)
        previous = log_spectrum[-1:]

        # BLOCK_FRAMES is a multiple of BUCKET_FRAMES, so only the last block can be left over.
        usable = len(log_spectrum) // BUCKET_FRAMES * BUCKET_FRAMES
        if usable:
            grouped = log_spectrum[:usable].reshape(-1, BUCKET_FRAMES, bins)
            bucket_blocks.append(grouped.mean(axis=1))
    buckets = (
        np.concatenate(bucket_blocks) if bucket_blocks else np.zeros((0, bins), dtype=np.float32)
    )
    return flux, buckets


def _onsets(flux: NDArray[np.float64]) -> list[dict[str, float]]:
    """Sudden sounds: the peaks of the spectral flux that stand ONSET_STD standard deviations
    above its mean. `strength` is how many standard deviations a peak stands above the mean.

    The first frame is not part of the mean and the spread: its flux is the rise from silence,
    which is large for any sound that is already playing at the start of the file. It is
    reported as an onset when it stands out like any other peak.
    """
    if len(flux) < 3:
        return []
    rest = flux[1:]
    spread = float(np.std(rest))
    if spread == 0:
        return []
    mean = float(np.mean(rest))
    threshold = mean + ONSET_STD * spread
    peaks = _local_maxima(flux, threshold)
    if flux[0] > threshold and flux[0] > flux[1]:
        peaks.append(0)
    chosen = _spread(
        sorted(peaks, key=lambda i: -flux[i]), round(ONSET_MIN_GAP_S / FRAME_S), MAX_ONSETS
    )
    # The window of frame i starts at i frames and is N_FFT long: its middle is the time.
    return [
        {
            "time_s": _round((i * FRAME_SAMPLES + N_FFT / 2) / SAMPLE_RATE, 3),
            "strength": _round((float(flux[i]) - mean) / spread, 1),
        }
        for i in chosen
    ]


def _change_points(buckets: NDArray[np.float32]) -> list[dict[str, float]]:
    """Where the sound changes character: for every 0.1 s, the distance between the average
    spectrum of the CHANGE_SPAN_S before it and of the same time after it. The strongest peaks
    that stand CHANGE_STD standard deviations above the mean distance and are at least
    CHANGE_MIN_GAP_S apart are kept. `strength` is the number of standard deviations.

    A level change moves the whole log-spectrum, so a sudden swell counts as well as a change of
    instruments. A slow fade moves it steadily, which gives a flat distance and no peak.
    """
    count = len(buckets)
    span = min(round(CHANGE_SPAN_S / BUCKET_S), (count - 1) // 2)
    if span < 5:  # under half a second each side: nothing can be compared
        return []

    sums = np.concatenate(
        (np.zeros((1, buckets.shape[1])), np.cumsum(buckets, axis=0, dtype=np.float64))
    )
    centres = np.arange(span, count - span + 1)
    after = (sums[centres + span] - sums[centres]) / span
    before = (sums[centres] - sums[centres - span]) / span
    distance = np.linalg.norm(after - before, axis=1) / math.sqrt(buckets.shape[1])

    spread = float(np.std(distance))
    if len(distance) < 3 or spread == 0:
        return []
    mean = float(np.mean(distance))
    peaks = _local_maxima(distance, mean + CHANGE_STD * spread)
    chosen = _spread(
        sorted(peaks, key=lambda i: -distance[i]),
        round(CHANGE_MIN_GAP_S / BUCKET_S),
        MAX_CHANGE_POINTS,
    )
    return [
        {
            "time_s": _round(int(centres[i]) * BUCKET_S, 3),
            "strength": _round((float(distance[i]) - mean) / spread, 1),
        }
        for i in chosen
    ]


def _local_maxima(values: NDArray[np.float64], threshold: float) -> list[int]:
    """The indexes of the values above `threshold` that are not lower than the value before and
    are higher than the value after."""
    inner = values[1:-1]
    is_peak = (inner >= values[:-2]) & (inner > values[2:]) & (inner > threshold)
    return (np.flatnonzero(is_peak) + 1).tolist()
