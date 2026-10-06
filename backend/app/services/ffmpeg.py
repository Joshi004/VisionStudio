"""The FFmpeg and ffprobe wrapper (ANALYSIS.md Section 5.6).

Rules every caller gets by going through `run_tool`:

- an argument list, never a shell;
- low priority (`nice`), so a render or a probe never starves the API;
- a time limit, after which the process is killed;
- input files passed through `file_input()`, so FFmpeg reads the value as a
  plain file and never as a protocol (`http:`, `concat:`) or an option.

`tool_version()` is what `GET /api/health` reports. `probe()` is the first
real use (Phase 3: checking uploads); the render phases build on `run_tool`.
"""

from __future__ import annotations

import asyncio
import asyncio.subprocess
import json
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

_logger = logging.getLogger(__name__)
_VERSION_TIMEOUT_SECONDS = 10
_NICE_LEVEL = "10"
_STDERR_LOG_CHARS = 500

Tool = Literal["ffmpeg", "ffprobe"]


class ToolError(Exception):
    """The tool could not be started, or ran past its time limit."""


@dataclass(frozen=True)
class ToolResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def file_input(path: Path) -> str:
    """The value to pass as an input file: an absolute path with the `file:` prefix."""
    return f"file:{path.resolve()}"


async def run_tool(tool: Tool, args: Sequence[str], *, timeout_s: float) -> ToolResult:
    """Runs `tool` with `args` at low priority and returns its output.

    A non-zero exit code is returned, not raised, because it is a normal answer
    for a file the tool cannot read. `ToolError` means there was no answer.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "nice",
            "-n",
            _NICE_LEVEL,
            tool,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ToolError(f"Could not start {tool}.") from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except (TimeoutError, asyncio.CancelledError) as exc:
        process.kill()
        await process.wait()
        if isinstance(exc, TimeoutError):
            raise ToolError(f"{tool} did not finish within {timeout_s:g} seconds.") from None
        raise

    return ToolResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
    )


@dataclass(frozen=True)
class AudioStream:
    codec_name: str | None
    sample_rate: int | None
    channels: int | None
    duration_s: float | None


@dataclass(frozen=True)
class ProbeResult:
    format_name: str
    format_long_name: str | None
    duration_s: float | None
    audio_streams: list[AudioStream]
    # Pictures attached to an audio file (cover art) are not counted.
    video_stream_count: int


async def probe(path: Path, *, timeout_s: float = 30.0) -> ProbeResult | None:
    """Reads a media file's container and streams with ffprobe.

    Returns None when ffprobe cannot read the file, cannot run, or prints
    something unusable. Never raises.
    """
    args = [
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        file_input(path),
    ]
    try:
        result = await run_tool("ffprobe", args, timeout_s=timeout_s)
    except ToolError as exc:
        _logger.warning("ffprobe could not run: %s", exc)
        return None

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")[:_STDERR_LOG_CHARS]
        _logger.info("ffprobe exit code %s: %s", result.returncode, stderr.strip())
        return None

    try:
        data = json.loads(result.stdout)
    except ValueError:
        _logger.warning("ffprobe printed output that is not JSON")
        return None
    return _parse_probe(data)


def _number(value: object) -> float | None:
    """ffprobe prints numbers as strings, and "N/A" when it does not know."""
    try:
        number = float(str(value))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _whole_number(value: object) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _parse_probe(data: Any) -> ProbeResult | None:
    if not isinstance(data, dict):
        return None
    media_format = data.get("format")
    if not isinstance(media_format, dict) or not isinstance(media_format.get("format_name"), str):
        return None

    audio_streams: list[AudioStream] = []
    video_stream_count = 0
    streams = data.get("streams")
    for stream in streams if isinstance(streams, list) else []:
        if not isinstance(stream, dict):
            continue
        kind = stream.get("codec_type")
        if kind == "audio":
            audio_streams.append(
                AudioStream(
                    codec_name=stream.get("codec_name"),
                    sample_rate=_whole_number(stream.get("sample_rate")),
                    channels=_whole_number(stream.get("channels")),
                    duration_s=_number(stream.get("duration")),
                )
            )
        elif kind == "video":
            disposition = stream.get("disposition")
            is_cover_art = isinstance(disposition, dict) and disposition.get("attached_pic") == 1
            if not is_cover_art:
                video_stream_count += 1

    long_name = media_format.get("format_long_name")
    return ProbeResult(
        format_name=media_format["format_name"],
        format_long_name=long_name if isinstance(long_name, str) else None,
        duration_s=_number(media_format.get("duration")),
        audio_streams=audio_streams,
        video_stream_count=video_stream_count,
    )


async def tool_version(tool: Tool) -> str | None:
    """Returns the tool's version string (e.g. "7.1.5-0+deb13u1").

    Returns None if the binary is missing, times out, or prints something
    this function does not recognise. Never raises.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            tool,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        _logger.warning("could not start %s", tool)
        return None

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=_VERSION_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        _logger.warning("%s -version timed out", tool)
        return None

    first_line = stdout.decode("utf-8", errors="replace").splitlines()[:1]
    if not first_line:
        return None

    # Expected shape: "ffmpeg version 7.1.5-0+deb13u1 Copyright (c) 2000-2025 ..."
    parts = first_line[0].split()
    if len(parts) >= 3 and parts[0] == tool and parts[1] == "version":
        return parts[2]
    return None
