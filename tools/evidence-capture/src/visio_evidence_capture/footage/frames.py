"""Looking at a video: strips, contact sheets, cut times and ffprobe (FTG-009, §4.7).

`strip_layout`, `strip_args`, `cut_args` and `parse_cuts` are a copy of the app's
(`backend/app/services/footage_frames.py`), with the same constants from `__init__.py`: the strip
the tool writes for a clip must look like the strip the app writes for an owner's video, and the
cut times must come from the same scene detection. FFmpeg is always started with an argument
list, never a shell, and with its input as a plain `file:` path.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from ..rounds import Refused
from . import (
    CUT_PROBE_WIDTH,
    CUT_SCENE_THRESHOLD,
    SHEET_COLUMNS,
    SHEET_JPEG_QUALITY,
    SHEET_ROWS,
    SHEET_TILE_H,
    SHEET_TILE_W,
    STRIP_COLUMNS,
    STRIP_EVERY_S,
    STRIP_JPEG_QUALITY,
    STRIP_TILE_H,
    STRIP_TILE_W,
)

PROBE_TIMEOUT_S: Final = 60
STRIP_TIMEOUT_S: Final = 300
CUTS_TIMEOUT_S: Final = 300
STDERR_CHARS: Final = 300

_PTS_TIME = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


def file_input(path: Path) -> str:
    """An input for `-i` that FFmpeg cannot take for a URL, a pipe or an option."""
    return "file:" + path.resolve().as_posix()


def _base_args() -> list[str]:
    return ["-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y"]


def run_ffmpeg(args: list[str], timeout_s: float, what: str) -> str:
    """Run FFmpeg. Returns its stderr. Refuses with a sentence when it fails."""
    try:
        done = subprocess.run(
            ["ffmpeg", *args], capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(f"ffmpeg could not {what}: {error}") from error
    if done.returncode != 0:
        detail = " ".join(done.stderr.split())[:STDERR_CHARS]
        raise Refused(f"ffmpeg could not {what} (exit code {done.returncode}): {detail}")
    return done.stderr


# --- The strip and the cuts (a copy of the app's code) ---------------------------------------


@dataclass(frozen=True)
class StripLayout:
    every_s: float
    columns: int
    rows: int
    tile_w: int
    tile_h: int
    frames: int


def strip_layout(duration_s: float) -> StripLayout:
    """The grid of the strip of a video of `duration_s` seconds: one tile per half second, the
    last one possibly covering less."""
    frames = max(1, math.ceil(duration_s / STRIP_EVERY_S))
    return StripLayout(
        every_s=STRIP_EVERY_S,
        columns=STRIP_COLUMNS,
        rows=math.ceil(frames / STRIP_COLUMNS),
        tile_w=STRIP_TILE_W,
        tile_h=STRIP_TILE_H,
        frames=frames,
    )


def strip_args(video: Path, dest: Path, layout: StripLayout) -> list[str]:
    tile = (
        f"fps=fps={1 / layout.every_s:g}:round=up,"
        f"scale={layout.tile_w}:{layout.tile_h}:force_original_aspect_ratio=decrease,"
        f"pad={layout.tile_w}:{layout.tile_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"tile={layout.columns}x{layout.rows}"
    )
    return [
        *_base_args(),
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
    graph = f"scale={CUT_PROBE_WIDTH}:-2,select='gt(scene,{CUT_SCENE_THRESHOLD:g})',showinfo"
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


def write_strip(video: Path, dest: Path, layout: StripLayout) -> None:
    run_ffmpeg(strip_args(video, dest, layout), STRIP_TIMEOUT_S, "write the strip of frames")
    if not dest.is_file() or dest.stat().st_size == 0:
        raise Refused("The strip of frames could not be made.")


def find_cuts(video: Path, duration_s: float) -> list[float]:
    """The times, in seconds of `video`, where a new shot starts."""
    log = run_ffmpeg(cut_args(video), CUTS_TIMEOUT_S, "search for cuts")
    return parse_cuts(log, duration_s)


# --- ffprobe ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoFacts:
    duration_s: float
    width: int
    height: int
    codec: str
    pix_fmt: str
    fps: float
    video_streams: int
    audio_streams: int
    other_streams: int

    @property
    def short_side(self) -> int:
        return min(self.width, self.height)


def _rate(text: object) -> float:
    """`30000/1001` as 29.97, 0 when it cannot be read."""
    try:
        top, _, bottom = str(text).partition("/")
        value = float(top) / (float(bottom) if bottom else 1.0)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return value if math.isfinite(value) and value > 0 else 0.0


def probe(path: Path) -> VideoFacts:
    """What ffprobe says about a video file. Refuses when it cannot be read."""
    try:
        done = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                file_input(path),
            ],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(f"ffprobe could not read {path.name}: {error}") from error
    if done.returncode != 0:
        raise Refused(f"{path.name} is not a media file that ffprobe can read.")
    try:
        data = json.loads(done.stdout)
        streams = data.get("streams") or []
        video = [s for s in streams if s.get("codec_type") == "video"]
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        first = video[0] if video else {}
        duration = float(data["format"]["duration"])
        return VideoFacts(
            duration_s=duration,
            width=int(first.get("width") or 0),
            height=int(first.get("height") or 0),
            codec=str(first.get("codec_name") or ""),
            pix_fmt=str(first.get("pix_fmt") or ""),
            fps=_rate(first.get("avg_frame_rate")) or _rate(first.get("r_frame_rate")),
            video_streams=len(video),
            audio_streams=len(audio),
            other_streams=len(streams) - len(video) - len(audio),
        )
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise Refused(f"ffprobe's answer for {path.name} cannot be read.") from error


# --- Contact sheets --------------------------------------------------------------------------

SHEET_FRAMES: Final = SHEET_COLUMNS * SHEET_ROWS
_STAMP_SIZE: Final = 22
_STAMP_PAD: Final = 4


def _font() -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=_STAMP_SIZE)


@dataclass(frozen=True)
class Sheet:
    path: Path
    first_s: float
    last_s: float
    frames: int


def write_sheets(
    tiles: list[tuple[float, Image.Image]],
    folder: Path,
    label,
) -> list[Sheet]:
    """Lay `tiles` (a time in seconds and a picture) out as contact sheets of 6 x 6 frames, each
    1920 x 1080, with each frame's time (as `label(time)` says) in its top-left corner. Files are
    `sheet-01.jpg` and on. A picture is fitted into its cell, never cropped."""
    font = _font()
    sheets: list[Sheet] = []
    for number, start in enumerate(range(0, len(tiles), SHEET_FRAMES), start=1):
        chunk = tiles[start : start + SHEET_FRAMES]
        canvas = Image.new("RGB", (SHEET_COLUMNS * SHEET_TILE_W, SHEET_ROWS * SHEET_TILE_H))
        draw = ImageDraw.Draw(canvas)
        for index, (time_s, picture) in enumerate(chunk):
            column, row = index % SHEET_COLUMNS, index // SHEET_COLUMNS
            fitted = picture.convert("RGB")
            scale = min(SHEET_TILE_W / fitted.width, SHEET_TILE_H / fitted.height)
            size = (max(1, round(fitted.width * scale)), max(1, round(fitted.height * scale)))
            fitted = fitted.resize(size, Image.Resampling.LANCZOS)
            left = column * SHEET_TILE_W + (SHEET_TILE_W - size[0]) // 2
            top = row * SHEET_TILE_H + (SHEET_TILE_H - size[1]) // 2
            canvas.paste(fitted, (left, top))
            text = label(time_s)
            box = draw.textbbox((0, 0), text, font=font)
            x0, y0 = column * SHEET_TILE_W, row * SHEET_TILE_H
            draw.rectangle(
                (x0, y0, x0 + box[2] + 2 * _STAMP_PAD, y0 + box[3] + 2 * _STAMP_PAD),
                fill=(0, 0, 0),
            )
            draw.text((x0 + _STAMP_PAD, y0 + _STAMP_PAD), text, fill=(255, 255, 0), font=font)
        path = folder / f"sheet-{number:02d}.jpg"
        canvas.save(path, format="JPEG", quality=SHEET_JPEG_QUALITY)
        sheets.append(Sheet(path, chunk[0][0], chunk[-1][0], len(chunk)))
    return sheets


def sample_args(video: Path, folder: Path) -> list[str]:
    """The FFmpeg arguments that write a picture every `STRIP_EVERY_S` seconds of `video` as
    `f0001.jpg`, `f0002.jpg`, ...: file `n` (from 1) is the frame at `(n - 1) * STRIP_EVERY_S`
    seconds. The pictures are fitted into a sheet cell, never cropped."""
    graph = (
        f"fps=fps={1 / STRIP_EVERY_S:g}:round=up,"
        f"scale={SHEET_TILE_W}:{SHEET_TILE_H}:force_original_aspect_ratio=decrease"
    )
    return [
        *_base_args(),
        "-i",
        file_input(video),
        "-an",
        "-vf",
        graph,
        "-q:v",
        "3",
        (folder / "f%04d.jpg").resolve().as_posix(),
    ]


def sample_pictures(video: Path, folder: Path) -> list[Path]:
    """Write the sample pictures of `sample_args` into `folder` and list them in order."""
    run_ffmpeg(sample_args(video, folder), STRIP_TIMEOUT_S, "take pictures from the video")
    return sorted(folder.glob("f*.jpg"))
