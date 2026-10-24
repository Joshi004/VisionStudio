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
import re
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


@dataclass(frozen=True)
class VideoProbe:
    """What a generated clip contains (Phase 9 checks it before storing it)."""

    width: int | None
    height: int | None
    fps: float | None
    # The number of frames, counted from the file's packets. None when ffprobe cannot tell.
    frame_count: int | None
    duration_s: float | None
    # The first audio stream, or None when the clip has no sound.
    audio: AudioStream | None


async def probe_video(path: Path, *, timeout_s: float = 120.0) -> VideoProbe | None:
    """Reads a video file, counting its frames. Returns None when ffprobe cannot read the
    file, cannot run, or the file has no video stream. Never raises.

    `-count_packets` reads the whole file once, so this is slower than `probe` (a few
    seconds for a clip), and it is how the number of frames is known for certain.
    """
    args = [
        "-v",
        "error",
        "-count_packets",
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
    return _parse_video_probe(data)


async def decode_problem(path: Path, *, timeout_s: float = 300.0) -> str | None:
    """Decodes a whole media file and throws the pictures and sound away, to find out whether it
    decodes to the end (a damaged or cut-off file is read by ffprobe but fails here). Returns
    None when it decodes, else a short message with the first error. Never raises.

    `-xerror` stops at the first decoding error and makes FFmpeg exit with a failure.
    """
    args = ["-v", "error", "-xerror", "-i", file_input(path), "-f", "null", "-"]
    try:
        result = await run_tool("ffmpeg", args, timeout_s=timeout_s)
    except ToolError as exc:
        _logger.warning("ffmpeg could not decode a clip: %s", exc)
        return str(exc)
    if result.returncode == 0:
        return None
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    first_line = stderr.splitlines()[0] if stderr else ""
    _logger.info("ffmpeg decode exit code %s: %s", result.returncode, stderr[:_STDERR_LOG_CHARS])
    return first_line[:200] or f"ffmpeg exited with code {result.returncode}."


async def extract_frame(
    clip: Path, frame_index: int, destination: Path, *, timeout_s: float = 120.0
) -> str | None:
    """Writes one frame of a video as a lossless PNG: the frame at `frame_index`, counted from 0
    in the order the clip plays. `destination` must not exist yet. Returns None on success, else
    a short message. Never raises.

    The filter is the render's own (`trim=start_frame=..:end_frame=..`, `render_commands`), so a
    frame index means the same thing here as there.
    """
    if frame_index < 0:
        return "The frame number is below zero."
    args = [
        "-v",
        "error",
        "-i",
        file_input(clip),
        "-an",
        "-vf",
        f"trim=start_frame={frame_index}:end_frame={frame_index + 1},setpts=PTS-STARTPTS",
        "-frames:v",
        "1",
        destination.resolve().as_posix(),
    ]
    try:
        result = await run_tool("ffmpeg", args, timeout_s=timeout_s)
    except ToolError as exc:
        _logger.warning("ffmpeg could not cut a frame: %s", exc)
        return str(exc)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        _logger.info("ffmpeg frame exit code %s: %s", result.returncode, stderr[:_STDERR_LOG_CHARS])
        first_line = stderr.splitlines()[0] if stderr else ""
        return first_line[:200] or f"ffmpeg exited with code {result.returncode}."
    if not destination.is_file() or destination.stat().st_size == 0:
        return f"The clip has no frame number {frame_index}."
    return None


def _frame_rate(value: object) -> float | None:
    """ffprobe prints a rate as a fraction such as "24/1"."""
    if not isinstance(value, str) or "/" not in value:
        return _number(value)
    numerator, _, denominator = value.partition("/")
    top, bottom = _number(numerator), _number(denominator)
    if top is None or bottom is None or bottom == 0:
        return None
    return top / bottom


def _parse_video_probe(data: Any) -> VideoProbe | None:
    if not isinstance(data, dict):
        return None
    streams = data.get("streams")
    video: dict[str, Any] | None = None
    audio: AudioStream | None = None
    for stream in streams if isinstance(streams, list) else []:
        if not isinstance(stream, dict):
            continue
        kind = stream.get("codec_type")
        if kind == "video" and video is None:
            disposition = stream.get("disposition")
            if not (isinstance(disposition, dict) and disposition.get("attached_pic") == 1):
                video = stream
        elif kind == "audio" and audio is None:
            audio = AudioStream(
                codec_name=stream.get("codec_name"),
                sample_rate=_whole_number(stream.get("sample_rate")),
                channels=_whole_number(stream.get("channels")),
                duration_s=_number(stream.get("duration")),
            )
    if video is None:
        return None

    media_format = data.get("format")
    format_duration = (
        _number(media_format.get("duration")) if isinstance(media_format, dict) else None
    )
    # The packet count is exact. The container's own frame count is only a fallback.
    frame_count = _whole_number(video.get("nb_read_packets"))
    if frame_count is None:
        frame_count = _whole_number(video.get("nb_frames"))
    return VideoProbe(
        width=_whole_number(video.get("width")),
        height=_whole_number(video.get("height")),
        fps=_frame_rate(video.get("avg_frame_rate")) or _frame_rate(video.get("r_frame_rate")),
        frame_count=frame_count,
        duration_s=_number(video.get("duration")) or format_duration,
        audio=audio,
    )


# Below this, the sound is silence for loudness purposes (the gate of EBU R128 is -70 LUFS).
_SILENCE_LUFS = -70.0
# The JSON block `loudnorm` prints at the end of its measuring run.
_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


async def measure_loudness(
    path: Path,
    *,
    duration_s: float | None = None,
    pre_filters: Sequence[str] = (),
    timeout_s: float = 120.0,
) -> float | None:
    """The integrated loudness of a file's first audio stream, in LUFS (EBU R128).

    With `duration_s`, only the first `duration_s` seconds are measured: a clip is longer
    than the scene that uses it, and only the scene's part is heard. The measuring run
    writes nothing (`-f null`).

    `pre_filters` are audio filters applied before the measurement, so the sound is measured
    as it will be heard. A mono file counts 3 dB louder once it plays on two channels, so
    two sounds that end up in one stereo mix are compared after the same conversion to
    stereo (`render_commands.stereo_filters`).

    Returns None when the file has no sound, is silent (at or below -70 LUFS) or is too
    short to measure (loudness is measured in 400 ms blocks), when FFmpeg cannot run, or
    when it prints something unusable. Never raises.
    """
    args = ["-hide_banner", "-nostdin", "-nostats", "-loglevel", "info"]
    if duration_s is not None:
        args += ["-t", f"{duration_s:.6f}"]
    args += [
        "-i",
        file_input(path),
        "-vn",
        "-map",
        "0:a:0",
        "-af",
        ",".join([*pre_filters, "loudnorm=print_format=json"]),
        "-f",
        "null",
        "-",
    ]
    try:
        result = await run_tool("ffmpeg", args, timeout_s=timeout_s)
    except ToolError as exc:
        _logger.warning("ffmpeg could not measure loudness: %s", exc)
        return None

    text = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        tail = text[-_STDERR_LOG_CHARS:]
        _logger.info("ffmpeg loudness exit code %s: %s", result.returncode, tail.strip())
        return None

    # The last block is the measurement; anything before it is the input description.
    blocks = _LOUDNORM_JSON.findall(text)
    if not blocks:
        return None
    try:
        data = json.loads(blocks[-1])
    except ValueError:
        _logger.warning("ffmpeg printed a loudness block that is not JSON")
        return None
    loudness = _number(data.get("input_i")) if isinstance(data, dict) else None
    if loudness is None or loudness <= _SILENCE_LUFS:
        return None
    return loudness


@dataclass(frozen=True)
class LoudnessScan:
    """What one pass of FFmpeg's EBU R128 scanner and `astats` measured in a file (MUSIC-003)."""

    # None when the file is silent (at or below -70 LUFS) or too short to measure.
    integrated_lufs: float | None
    loudness_range_lu: float | None
    # None when the file is digital silence.
    true_peak_dbtp: float | None
    sample_peak_dbfs: float | None
    # How many samples sit at the highest level the file reaches. Only clipping when that level
    # is at full scale, so the caller reads it together with `sample_peak_dbfs`.
    peak_sample_count: int
    # (time_s, LUFS) every 0.1 s. The value at a time is the loudness of the 3 seconds that end
    # there, so it is None for the first 3 seconds (the window is not full) and for silence.
    short_term: list[tuple[float, float | None]]


_SCAN_TIMEOUT_S = 300.0
# `ebur128` prints this level while its 3 s window is not full or the sound is silent.
_SHORT_TERM_FLOOR_LUFS = -120.0
_FRAME_TIME = re.compile(r"pts_time:(\S+)")
_SHORT_TERM = re.compile(r"lavfi\.r128\.S=(\S+)")
_SCAN_INTEGRATED = re.compile(r"Integrated loudness:\s*\n\s*I:\s+(\S+)\s+LUFS")
_SCAN_RANGE = re.compile(r"Loudness range:\s*\n\s*LRA:\s+(\S+)\s+LU")
_SCAN_TRUE_PEAK = re.compile(r"True peak:\s*\n\s*Peak:\s+(\S+)\s+dBFS")
_STATS_PEAK_LEVEL = re.compile(r"Peak level dB:\s+(\S+)")
_STATS_PEAK_COUNT = re.compile(r"Peak count:\s+(\S+)")


def _last_number(pattern: re.Pattern[str], text: str) -> float | None:
    """The number after the last match of `pattern`. "-inf" and anything unreadable give None."""
    matches = pattern.findall(text)
    return _number(matches[-1]) if matches else None


async def scan_loudness(path: Path, *, timeout_s: float = _SCAN_TIMEOUT_S) -> LoudnessScan | None:
    """Measures a file's first audio stream in one FFmpeg run: integrated loudness, loudness
    range, true peak, the short-term loudness over time, the sample peak and how many samples
    reach it. Nothing is written (`-f null`).

    Returns None when the file has no sound stream, FFmpeg cannot run, or it prints something
    unusable. Never raises.
    """
    filters = (
        "ebur128=peak=true:metadata=1,"
        "ametadata=mode=print:key=lavfi.r128.S:file=-,"
        "astats=measure_perchannel=none:measure_overall=Peak_level+Peak_count"
    )
    args = [
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-loglevel",
        "info",
        "-i",
        file_input(path),
        "-vn",
        "-map",
        "0:a:0",
        "-af",
        filters,
        "-f",
        "null",
        "-",
    ]
    try:
        result = await run_tool("ffmpeg", args, timeout_s=timeout_s)
    except ToolError as exc:
        _logger.warning("ffmpeg could not scan loudness: %s", exc)
        return None
    log = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        _logger.info("ffmpeg scan exit code %s: %s", result.returncode, log[-_STDERR_LOG_CHARS:])
        return None
    # The summary is only printed when the scanner ran to the end.
    if _SCAN_INTEGRATED.search(log) is None:
        return None

    integrated = _last_number(_SCAN_INTEGRATED, log)
    if integrated is not None and integrated <= _SILENCE_LUFS:
        integrated = None
    count = _last_number(_STATS_PEAK_COUNT, log)
    return LoudnessScan(
        integrated_lufs=integrated,
        loudness_range_lu=_last_number(_SCAN_RANGE, log),
        true_peak_dbtp=_last_number(_SCAN_TRUE_PEAK, log),
        sample_peak_dbfs=_last_number(_STATS_PEAK_LEVEL, log),
        peak_sample_count=int(round(count)) if count is not None else 0,
        short_term=_parse_short_term(result.stdout.decode("utf-8", errors="replace")),
    )


def _parse_short_term(text: str) -> list[tuple[float, float | None]]:
    """The (time, LUFS) pairs `ametadata` printed: a line with the frame's time, then one with
    the value."""
    curve: list[tuple[float, float | None]] = []
    time_s: float | None = None
    for line in text.splitlines():
        time_match = _FRAME_TIME.search(line)
        if time_match is not None:
            time_s = _number(time_match.group(1))
            continue
        value_match = _SHORT_TERM.search(line)
        if value_match is not None and time_s is not None:
            value = _number(value_match.group(1))
            if value is not None and value <= _SHORT_TERM_FLOOR_LUFS:
                value = None
            curve.append((time_s, value))
            time_s = None
    return curve


async def decode_mono_float(
    path: Path, sample_rate: int, *, max_seconds: float, timeout_s: float = 300.0
) -> bytes | None:
    """The first audio stream of a file as raw mono 32-bit float samples (little-endian) at
    `sample_rate`, read from FFmpeg's output. At most `max_seconds` are decoded, so the answer
    cannot grow without limit. Returns None when the file has no sound stream, FFmpeg cannot run,
    or it fails. Never raises.
    """
    args = [
        "-v",
        "error",
        "-nostdin",
        "-t",
        f"{max_seconds:.3f}",
        "-i",
        file_input(path),
        "-vn",
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "-",
    ]
    try:
        result = await run_tool("ffmpeg", args, timeout_s=timeout_s)
    except ToolError as exc:
        _logger.warning("ffmpeg could not decode audio: %s", exc)
        return None
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")[:_STDERR_LOG_CHARS]
        _logger.info("ffmpeg decode exit code %s: %s", result.returncode, stderr.strip())
        return None
    return result.stdout


JOIN_SAMPLE_RATE = 48_000


async def join_audio(
    parts: Sequence[Path],
    dest: Path,
    *,
    gap_s: float = 0.0,
    tail_s: float = 0.0,
    timeout_s: float = 300.0,
) -> str | None:
    """Puts the first audio stream of each file in `parts` end to end in a new FLAC at `dest`
    (48 kHz, stereo, 24-bit), with `gap_s` seconds of silence between neighbours and `tail_s`
    seconds of silence at the end. Returns None on success, or a sentence for the user when
    FFmpeg could not do it. Never raises.
    """
    args = ["-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y"]
    for part in parts:
        args += ["-i", file_input(part)]
    convert = f"aresample={JOIN_SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"
    silence = f"anullsrc=r={JOIN_SAMPLE_RATE}:cl=stereo:d={{seconds:.6f}}"

    graph: list[str] = []
    labels: list[str] = []
    for index in range(len(parts)):
        if index > 0 and gap_s > 0:
            graph.append(silence.format(seconds=gap_s) + f"[gap{index}]")
            labels.append(f"[gap{index}]")
        graph.append(f"[{index}:a:0]{convert}[part{index}]")
        labels.append(f"[part{index}]")
    if tail_s > 0:
        graph.append(silence.format(seconds=tail_s) + "[tail]")
        labels.append("[tail]")
    graph.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[joined]")
    args += [
        "-filter_complex",
        ";".join(graph),
        "-map",
        "[joined]",
        "-c:a",
        "flac",
        "-sample_fmt",
        "s32",
        "-ar",
        str(JOIN_SAMPLE_RATE),
        "-f",
        "flac",
        dest.resolve().as_posix(),
    ]
    try:
        result = await run_tool("ffmpeg", args, timeout_s=timeout_s)
    except ToolError as exc:
        _logger.warning("ffmpeg could not join audio: %s", exc)
        return "The audio could not be joined: FFmpeg did not run."
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")[:_STDERR_LOG_CHARS]
        _logger.info("ffmpeg join exit code %s: %s", result.returncode, stderr.strip())
        return "The audio could not be joined. A file may be damaged."
    return None


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
