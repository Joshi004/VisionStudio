"""Joining the WAV pieces of a long speech into one file (Phase 21).

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


class JoinError(Exception):
    """The pieces could not be joined. The message is meant to be shown to the user."""


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
