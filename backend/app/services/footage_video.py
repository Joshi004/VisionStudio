"""The FFmpeg command of a footage video clip (FTG-005, `Footage_broll_implementation_phases.md`
§4.10).

The clip is the stored, muted copy of a video (`footage_item.video_path`) cut to exactly `frames`
frames from `start_s`, at the output size and frame rate, with **no sound**. The picture is
framed like a sound bite's (`soundbite_render.framing_for`): a source with the frame's shape fills
it, any other shape is fitted over a blurred, darkened copy of itself. A portrait frame may also
be **cropped** to fill it, from the left, the centre or the right of the source (the owner's
choice, FTG-012).

The clip is never slowed down, sped up or looped. Should the stored video end before the clip
does (the clip has one spare frame, and the owner may use the very end of a video), the last frame
is held for a few frames so the count is exact.

Pure: no I/O. Every path goes through `ffmpeg.file_input`, so FFmpeg reads and writes a plain
file and never a protocol or an option.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from app.services import soundbite_render
from app.services.ffmpeg import file_input

CROP_LEFT: Final = "left"
CROP_CENTRE: Final = "centre"
CROP_RIGHT: Final = "right"
CROPS: Final = (CROP_LEFT, CROP_CENTRE, CROP_RIGHT)

# FFmpeg `crop` expressions for the left edge of the crop, by choice.
_CROP_X: Final = {CROP_LEFT: "0", CROP_CENTRE: "(iw-ow)/2", CROP_RIGHT: "iw-ow"}
# Frames of the last picture held when the source ends early. More than the one spare frame.
HOLD_FRAMES: Final = 24


def crop_of(framing: object) -> str | None:
    """The owner's portrait choice when it is one of `CROPS`, otherwise None."""
    return framing if isinstance(framing, str) and framing in CROPS else None


def _crop_chain(crop: str, width: int, height: int, fps: int) -> str:
    return (
        f"[0:v:0]fps={fps},"
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height}:x={_CROP_X[crop]}:y=(ih-oh)/2,setsar=1[pic]"
    )


def clip_graph(
    source: tuple[int, int],
    *,
    width: int,
    height: int,
    fps: int,
    frames: int,
    crop: str | None,
) -> str:
    """The `-filter_complex` of the clip: input 0 is the stored video, seeked to the clip's start.
    Outputs `[v]` of exactly `frames` frames at `fps`, `yuv420p`. `crop` fills a portrait frame; it
    is ignored for a landscape one. Raises ValueError for sizes that cannot be used."""
    if frames < 1 or fps < 1 or width < 2 or height < 2:
        raise ValueError("A clip needs a size and frames.")
    if crop is not None and crop not in CROPS:
        raise ValueError("The crop must be left, centre or right.")
    if crop is not None and height > width:
        chain = _crop_chain(crop, width, height, fps)
    else:
        framing = soundbite_render.framing_for(source, (width, height))
        chain = soundbite_render.picture_chain(framing, width, height, fps)
    hold = f"tpad=stop_mode=clone:stop={HOLD_FRAMES}"
    return f"{chain};[pic]{hold},format=yuv420p,trim=end_frame={frames},setpts=PTS-STARTPTS[v]"


def clip_args(
    src: Path, dest: Path, *, start_s: float, graph: str, frames: int, fps: int
) -> list[str]:
    """The FFmpeg arguments that write the clip at `dest` (an MP4, H.264, `yuv420p`, no audio)."""
    return [
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start_s:.3f}",
        "-i",
        file_input(src),
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-an",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-frames:v",
        str(frames),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-fps_mode",
        "cfr",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        file_input(dest),
    ]
