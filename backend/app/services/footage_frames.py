"""Making an owner's video ready, and looking at it (FTG-003,
`Footage_broll_implementation_phases.md` §4.7 and §4.12).

Three FFmpeg jobs, each one function:

- `prepare`: the stored copy of an owner's video. H.264, `yuv420p`, **no sound** (FT-7), the
  shorter side at most `MAX_SHORT_SIDE` pixels, a constant frame rate. Metadata, chapters, other
  streams and subtitles are dropped.
- `write_strip`: one JPEG with a frame every `STRIP_EVERY_S` seconds, laid out in a grid of
  `STRIP_COLUMNS` tiles per row, each `STRIP_TILE_W` x `STRIP_TILE_H` (the picture is fitted into
  the tile, never cropped). Tile `n` (from 0) is the frame at `n * STRIP_EVERY_S` seconds.
- `find_cuts`: the times of the cuts between shots, by FFmpeg's scene detection.

The capture tool (`tools/evidence-capture`) is a separate uv project and writes the same strip and
finds cuts the same way for the agent's videos (FTG-009). Its code is a copy, so the thresholds
below are the values to keep the same in both.

Every call goes through `services/ffmpeg.run_tool`: an argument list, never a shell, low
priority, a time limit, and input files passed as plain `file:` paths.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.services.ffmpeg import ToolError, file_input, run_tool

_logger = logging.getLogger(__name__)

# The longest the shorter side of a stored video may be. A portrait 1080x1920 video keeps its size.
MAX_SHORT_SIDE: Final = 1080
# The frame rate of the stored copy is the source's, never above this.
MAX_FPS: Final = 60.0
DEFAULT_FPS: Final = 30.0

STRIP_EVERY_S: Final = 0.5
STRIP_COLUMNS: Final = 10
STRIP_TILE_W: Final = 192
STRIP_TILE_H: Final = 108
STRIP_JPEG_QUALITY: Final = 4  # FFmpeg's `-q:v`: 2 is best, 31 worst.

# FFmpeg's scene score (0 to 1) above which a frame counts as the first of a new shot.
CUT_SCENE_THRESHOLD: Final = 0.3
# Scene detection looks at a small copy of the picture: it is faster and as good for cuts.
_CUT_PROBE_WIDTH: Final = 320

PREPARE_TIMEOUT_S: Final = 1800.0
STRIP_TIMEOUT_S: Final = 600.0
CUTS_TIMEOUT_S: Final = 600.0
_STDERR_CHARS: Final = 300

_PTS_TIME = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


class FramesError(Exception):
    """FFmpeg could not do it. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class StripLayout:
    """Where each frame is in the strip."""

    every_s: float
    columns: int
    rows: int
    tile_w: int
    tile_h: int
    frames: int


def stored_fps(source_fps: float | None) -> float:
    """The frame rate of the stored copy: the source's, at most `MAX_FPS`; the default when the
    source's is not known."""
    if source_fps is None or not math.isfinite(source_fps) or source_fps <= 0:
        return DEFAULT_FPS
    return min(source_fps, MAX_FPS)


def strip_layout(duration_s: float) -> StripLayout:
    """The grid of the strip of a video of `duration_s` seconds: one tile per half second,
    the last one possibly covering less."""
    frames = max(1, math.ceil(duration_s / STRIP_EVERY_S))
    return StripLayout(
        every_s=STRIP_EVERY_S,
        columns=STRIP_COLUMNS,
        rows=math.ceil(frames / STRIP_COLUMNS),
        tile_w=STRIP_TILE_W,
        tile_h=STRIP_TILE_H,
        frames=frames,
    )


def prepare_args(src: Path, dest: Path, fps: float) -> list[str]:
    """The FFmpeg arguments that make the stored copy of an owner's video at `dest` (an MP4)."""
    # Landscape: the height is at most the cap and the width follows. Portrait: the other way.
    # `-2` keeps the shape and makes the size even, which `yuv420p` needs.
    scale = (
        f"scale=w='if(gte(iw,ih),-2,min(iw,{MAX_SHORT_SIDE}))'"
        f":h='if(gte(iw,ih),min(ih,{MAX_SHORT_SIDE}),-2)',setsar=1,format=yuv420p"
    )
    return [
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-loglevel",
        "error",
        "-y",
        "-i",
        file_input(src),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-vf",
        scale,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-r",
        f"{stored_fps(fps):.3f}",
        "-fps_mode",
        "cfr",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        dest.resolve().as_posix(),
    ]


def strip_args(video: Path, dest: Path, layout: StripLayout) -> list[str]:
    """The FFmpeg arguments that write the strip of `video` at `dest` (a JPEG)."""
    tile = (
        f"fps=fps={1 / layout.every_s:g}:round=up,"
        f"scale={layout.tile_w}:{layout.tile_h}:force_original_aspect_ratio=decrease,"
        f"pad={layout.tile_w}:{layout.tile_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"tile={layout.columns}x{layout.rows}"
    )
    return [
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-loglevel",
        "error",
        "-y",
        "-i",
        file_input(video),
        "-an",
        "-vf",
        tile,
        "-frames:v",
        "1",
        "-q:v",
        str(STRIP_JPEG_QUALITY),
        dest.resolve().as_posix(),
    ]


def cut_args(video: Path) -> list[str]:
    """The FFmpeg arguments that print the first frame of every new shot (`showinfo`)."""
    graph = f"scale={_CUT_PROBE_WIDTH}:-2,select='gt(scene,{CUT_SCENE_THRESHOLD:g})',showinfo"
    return [
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-loglevel",
        "info",
        "-i",
        file_input(video),
        "-an",
        "-vf",
        graph,
        "-f",
        "null",
        "-",
    ]


def parse_cuts(log: str, duration_s: float) -> list[float]:
    """The cut times in `log` (what `showinfo` printed), in order, in seconds to a millisecond,
    leaving out anything at the very start or at or past the end."""
    times: list[float] = []
    for line in log.splitlines():
        if "showinfo" not in line:
            continue
        match = _PTS_TIME.search(line)
        if match is None:
            continue
        time_s = round(float(match.group(1)), 3)
        if 0 < time_s < duration_s and (not times or time_s > times[-1]):
            times.append(time_s)
    return times


async def _run(tool_args: list[str], timeout_s: float, what: str) -> bytes:
    """Runs FFmpeg; returns its stderr. Raises FramesError with a sentence when it fails."""
    try:
        result = await run_tool("ffmpeg", tool_args, timeout_s=timeout_s)
    except ToolError as exc:
        _logger.warning("ffmpeg could not %s: %s", what, exc)
        raise FramesError(f"The video could not be {what}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        _logger.info("ffmpeg %s exit code %s: %s", what, result.returncode, detail[:_STDERR_CHARS])
        raise FramesError(f"The video could not be {what}. The file may be damaged.")
    return result.stderr


async def prepare(src: Path, dest: Path, fps: float) -> None:
    """Writes the stored copy of `src` at `dest`. `dest` is overwritten. Raises FramesError."""
    await _run(prepare_args(src, dest, fps), PREPARE_TIMEOUT_S, "made ready")


async def write_strip(video: Path, dest: Path, layout: StripLayout) -> None:
    """Writes the strip of `video` at `dest`. Raises FramesError."""
    await _run(strip_args(video, dest, layout), STRIP_TIMEOUT_S, "shown as a strip of frames")
    if not dest.is_file() or dest.stat().st_size == 0:
        raise FramesError("The strip of frames could not be made.")


async def find_cuts(video: Path, duration_s: float) -> list[float]:
    """The times in seconds where a new shot starts, in order. Raises FramesError."""
    log = await _run(cut_args(video), CUTS_TIMEOUT_S, "searched for cuts")
    return parse_cuts(log.decode("utf-8", errors="replace"), duration_s)
