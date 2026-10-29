"""The FFmpeg commands of the Audio video lab's two videos (AVLAB). Pure: nothing here runs a
process, reads a file or touches the database; `jobs/render_av_test.py` runs the commands.

A test's speech lasts `D` seconds and its marked parts are spans of it. The output is laid out
in whole frames (24 fps, the clip's own): between the parts it shows a still of the first frame,
inside a part it shows that part's clip from its first frame. One picture track is made once
(`video_args`, without sound) and both outputs reuse it unchanged, so the two videos differ in
their sound only:

- **Mixed** (`mixed_args`): the speech is heard in the gaps; inside a part the clip's own sound
  (what H3 generated with the picture) is heard instead of the speech.
- **TTS only** (`tts_args`): the clips are muted and the speech is heard from 0 to the end.

Every piece of the mixed sound is cut to exactly its length in frames, so the sound and the
picture stay in step however many cuts there are. Every path goes through `ffmpeg.file_input`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from app.services import frame_counts
from app.services.ffmpeg import file_input

FPS: Final = frame_counts.H3_FPS
SAMPLE_RATE: Final = 48000
AUDIO_BITRATE: Final = "192k"
VIDEO_CRF: Final = "18"
# What a clip may be short of its part, in frames, before the last picture is held.
_HOLD_FRAMES: Final = 2

_BASE: Final = ["-hide_banner", "-nostdin", "-loglevel", "error", "-n"]
_AUDIO_FORMAT: Final = f"aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo"


class RenderLayoutError(ValueError):
    """The parts cannot be laid out. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class Piece:
    """A stretch of the output: `still` (the first frame) or `clip` (part number `part`, 0-based),
    from frame `start_frame` up to `end_frame` (not included).
    """

    kind: Literal["still", "clip"]
    start_frame: int
    end_frame: int
    part: int | None

    @property
    def frames(self) -> int:
        return self.end_frame - self.start_frame

    @property
    def start_s(self) -> float:
        return self.start_frame / FPS

    @property
    def length_s(self) -> float:
        return self.frames / FPS


def layout(spans: Sequence[tuple[float, float]], duration_s: float) -> tuple[int, list[Piece]]:
    """The output's frame count and its pieces, in order, from the parts' spans in seconds (in
    order, not overlapping). The last part may run to the end of the speech. Raises
    RenderLayoutError for a part shorter than a frame.
    """
    total = frame_counts.boundary_frame(duration_s, FPS)
    pieces: list[Piece] = []
    cursor = 0
    for number, (start_s, end_s) in enumerate(spans):
        first = max(frame_counts.boundary_frame(start_s, FPS), cursor)
        reaches_end = end_s >= duration_s - 1e-6
        last = total if reaches_end else min(frame_counts.boundary_frame(end_s, FPS), total)
        if last <= first:
            raise RenderLayoutError(f"Part {number + 1} is shorter than one video frame.")
        if first > cursor:
            pieces.append(Piece("still", cursor, first, None))
        pieces.append(Piece("clip", first, last, number))
        cursor = last
    if cursor < total:
        pieces.append(Piece("still", cursor, total, None))
    return total, pieces


def _seconds(value: float) -> str:
    return f"{value:.6f}"


def _picture_filter(width: int, height: int, frames: int, *, hold: bool) -> str:
    """One piece's picture: at the output's size (the picture is fitted inside, never cropped),
    24 fps, and exactly `frames` frames. A clip that is a frame or two short holds its last
    picture (`hold`).
    """
    steps = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "setsar=1",
        f"fps={FPS}",
        "format=yuv420p",
    ]
    if hold:
        steps.append(f"tpad=stop_mode=clone:stop={_HOLD_FRAMES}")
    steps += [f"trim=end_frame={frames}", "setpts=PTS-STARTPTS"]
    return ",".join(steps)


def video_args(
    still: Path,
    clips: Sequence[Path],
    pieces: Sequence[Piece],
    dest: Path,
    *,
    total_frames: int,
    width: int,
    height: int,
) -> list[str]:
    """The picture track alone (no sound), as an H.264 MP4 of exactly `total_frames` frames.
    `clips[n]` is the clip of part `n`.
    """
    if not pieces:
        raise ValueError("A video needs at least one piece.")
    inputs: list[str] = []
    graph: list[str] = []
    for index, piece in enumerate(pieces):
        if piece.kind == "still":
            inputs += ["-loop", "1", "-framerate", str(FPS), "-i", file_input(still)]
        else:
            inputs += ["-i", file_input(clips[piece.part or 0])]
        graph.append(
            f"[{index}:v]"
            + _picture_filter(width, height, piece.frames, hold=piece.kind == "clip")
            + f"[v{index}]"
        )
    joined = "".join(f"[v{index}]" for index in range(len(pieces)))
    graph.append(f"{joined}concat=n={len(pieces)}:v=1:a=0[v]")
    return [
        *_BASE,
        *inputs,
        "-filter_complex",
        ";".join(graph),
        "-map",
        "[v]",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        VIDEO_CRF,
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        "-frames:v",
        str(total_frames),
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        file_input(dest),
    ]


def _mux_tail(dest: Path) -> list[str]:
    return [
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        AUDIO_BITRATE,
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        file_input(dest),
    ]


def mixed_args(
    video: Path,
    speech: Path,
    clips: Sequence[Path],
    clip_has_audio: Sequence[bool],
    pieces: Sequence[Piece],
    dest: Path,
) -> list[str]:
    """The video with the speech in the gaps and each clip's own sound inside its part. Every
    piece of sound is exactly as long as its picture; a clip with no sound track is silent.
    """
    inputs = ["-i", file_input(video), "-i", file_input(speech)]
    for clip in clips:
        inputs += ["-i", file_input(clip)]
    graph: list[str] = []
    for index, piece in enumerate(pieces):
        length = _seconds(piece.length_s)
        if piece.kind == "still":
            source = f"[1:a]atrim=start={_seconds(piece.start_s)}:duration={length}"
        elif clip_has_audio[piece.part or 0]:
            source = f"[{2 + (piece.part or 0)}:a]atrim=duration={length}"
        else:
            source = f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={length}"
        graph.append(
            f"{source},asetpts=PTS-STARTPTS,{_AUDIO_FORMAT},"
            f"apad=whole_dur={length},atrim=duration={length}[a{index}]"
        )
    joined = "".join(f"[a{index}]" for index in range(len(pieces)))
    graph.append(f"{joined}concat=n={len(pieces)}:v=0:a=1[a]")
    return [*_BASE, *inputs, "-filter_complex", ";".join(graph), *_mux_tail(dest)]


def tts_args(video: Path, speech: Path, dest: Path, *, total_frames: int) -> list[str]:
    """The video with the speech from 0 to the end of the picture, and no clip sound."""
    length = _seconds(total_frames / FPS)
    graph = (
        f"[1:a]{_AUDIO_FORMAT},apad=whole_dur={length},atrim=duration={length},"
        "asetpts=PTS-STARTPTS[a]"
    )
    return [
        *_BASE,
        "-i",
        file_input(video),
        "-i",
        file_input(speech),
        "-filter_complex",
        graph,
        *_mux_tail(dest),
    ]
