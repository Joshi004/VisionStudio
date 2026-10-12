"""Joining the WAV pieces of a long speech into one file (Phase 21), and padding a speech with
silence so it lasts as long as a clip (Phase 24).

The pieces all come from the same model, so they share one format (mono, 24 kHz, 16-bit). They
are joined with FFmpeg's concat demuxer and written again as 16-bit PCM WAV, so the result has
exactly that format whatever the pieces were. Every path goes through `ffmpeg.file_input`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from app.services import ffmpeg
from app.services.render_commands import concat_list

SAMPLE_RATE: Final = 24000
JOIN_TIMEOUT_S: Final = 300.0
PAD_TIMEOUT_S: Final = 120.0


class JoinError(Exception):
    """The pieces could not be joined. The message is meant to be shown to the user."""


class PadError(Exception):
    """The speech could not be padded. The message is meant to be shown to the user."""


def pad_args(source: Path, dest: Path, min_duration_s: float) -> list[str]:
    """Writes `source` as 16-bit PCM WAV with silence added at the end, so it lasts at least
    `min_duration_s`. A longer recording is written unchanged. The sample rate and channels stay.
    """
    return [
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-n",
        "-i",
        ffmpeg.file_input(source),
        "-af",
        f"apad=whole_dur={min_duration_s:.3f}",
        "-c:a",
        "pcm_s16le",
        ffmpeg.file_input(dest),
    ]


async def pad_to(source: Path, dest: Path, min_duration_s: float) -> None:
    """Pads `source` with silence into the new WAV file `dest`. Raises PadError."""
    try:
        result = await ffmpeg.run_tool(
            "ffmpeg", pad_args(source, dest, min_duration_s), timeout_s=PAD_TIMEOUT_S
        )
    except ffmpeg.ToolError as exc:
        raise PadError(f"The speech could not be prepared for the video model: {exc}") from exc
    if result.returncode != 0:
        raise PadError("The speech could not be prepared for the video model.")


def join_args(list_path: Path, dest: Path) -> list[str]:
    return [
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-n",
        "-f",
        "concat",
        "-safe",
        "0",
        "-protocol_whitelist",
        "file",
        "-i",
        ffmpeg.file_input(list_path),
        "-c:a",
        "pcm_s16le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        ffmpeg.file_input(dest),
    ]


async def join_wavs(parts: Sequence[Path], list_path: Path, dest: Path) -> None:
    """Joins `parts` in order into the new file `dest`. `list_path` is a new file for the list
    FFmpeg reads. Raises JoinError.
    """
    list_path.write_text(concat_list(parts), encoding="utf-8")
    try:
        result = await ffmpeg.run_tool(
            "ffmpeg", join_args(list_path, dest), timeout_s=JOIN_TIMEOUT_S
        )
    except ffmpeg.ToolError as exc:
        raise JoinError(f"The speech parts could not be joined: {exc}") from exc
    if result.returncode != 0:
        raise JoinError("The speech parts could not be joined.")
