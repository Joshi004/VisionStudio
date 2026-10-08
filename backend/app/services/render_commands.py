"""The FFmpeg commands of the final render (ANALYSIS.md Section 5.6). Pure: no I/O.

The render has two stages, and each is one FFmpeg run:

1. **Trim, per clip** (`trim_args`): the clip's picture is cut to exactly the scene's frame
   count, cropped to the output size, at the project's fps; its sound is cut to the same
   length, made 48 kHz stereo, lowered by the clip's own gain (see below) and faded for 20 ms
   at both ends, or replaced by silence of the same length. The result is a MOV with visually
   lossless H.264 and uncompressed PCM sound. (MP4 is a poor container for PCM, and MOV keeps
   exact timestamps.)
2. **Join and mix** (`join_args`): the trimmed clips are joined in order with FFmpeg's concat
   demuxer (they all share the same parameters), their sound is mixed under the voiceover,
   and the final H.264 and AAC file is written.

**The clip sound level is relative to the voiceover.** The project's clip sound volume is a
share of the voiceover's level: at 5%, a clip's sound sits 26 dB under the voice, whatever
loudness the clip came with. The render measures the voiceover and each clip's loudness
(`ffmpeg.measure_loudness`), and `clip_gain_db` gives each clip the gain that puts it at that
distance under the voice. A clip is never made louder than it is.

The voiceover stays at its own level. FFmpeg's `amix` divides every input by the number of
inputs unless told not to, which would make the voiceover 6 dB quieter (measured on the
image's FFmpeg 7.1.5), so the mix uses `normalize=0`. A mono voiceover is made stereo with
`pan`, because the automatic conversion lowers it by 3 dB.

Every input and output path goes through `ffmpeg.file_input`, so FFmpeg reads and writes a
plain file and never a protocol or an option.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.services.ffmpeg import file_input

SAMPLE_RATE: Final = 48000
# The fade at both ends of a clip's sound, so a cut never clicks.
FADE_S: Final = 0.02

_BASE: Final = ["-hide_banner", "-nostdin", "-loglevel", "error", "-n"]
_PAN_MONO_TO_STEREO: Final = "pan=stereo|c0=c0|c1=c0"
_STEREO: Final = "aformat=channel_layouts=stereo"


@dataclass(frozen=True)
class ClipAudio:
    """The sound of a clip that is used in the render (a muted clip has none)."""

    channels: int | None
    # How long the sound is, as ffprobe reports it. LTX sound is 17 to 45 ms shorter than
    # its video, so the rest of the scene is filled with silence.
    duration_s: float | None
    # The gain given to this clip's sound, in dB (0 or less). See `clip_gain_db`.
    gain_db: float


def clip_gain_db(volume: float, voice_lufs: float | None, clip_lufs: float | None) -> float:
    """The gain, in dB, that puts a clip's sound `volume` (a share of the voiceover's level)
    under the voiceover. `volume` is from above 0 to 1: 0.2 is 14 dB under the voice, 0.05 is
    26 dB under.

    With both loudnesses (in LUFS) the clip is brought to `voice + 20 * log10(volume)`, and a
    clip that is already quieter than that keeps its own level: it is never boosted, so the
    16-bit sound cannot clip. When either loudness is unknown (a silent or very short clip),
    the plain volume is used, as if the clip were as loud as the voice.
    """
    if volume <= 0:
        raise ValueError("The clip sound volume must be above 0.")
    below_voice_db = 20 * math.log10(volume)
    if voice_lufs is None or clip_lufs is None:
        return below_voice_db
    return min(0.0, voice_lufs + below_voice_db - clip_lufs)


def stereo_filters(channels: int | None) -> list[str]:
    """What turns a source into stereo without changing its level.

    A mono source is copied to both channels (the automatic conversion would lower it by
    3 dB), stereo is left alone, and anything else is downmixed by FFmpeg.
    """
    if channels == 1:
        return [_PAN_MONO_TO_STEREO]
    if channels == 2:
        return []
    return [_STEREO]


def sample_count(frames: int, fps: int) -> int:
    """How many samples of 48 kHz sound last as long as `frames` frames at `fps`."""
    return round(frames * SAMPLE_RATE / fps)


def trim_args(
    src: Path,
    dest: Path,
    *,
    frames: int,
    fps: int,
    width: int,
    height: int,
    audio: ClipAudio | None,
) -> list[str]:
    """Stage 1: one clip, trimmed to `frames` frames, at the output size, as a MOV.

    `audio` is None for silence (a muted scene, a clip with no sound, or a clip sound volume
    of 0).
    """
    if frames < 1:
        raise ValueError("A clip needs at least one frame.")
    samples = sample_count(frames, fps)
    scene_s = samples / SAMPLE_RATE

    # `scale ... increase` covers the output size and `crop` takes the centre, so a 1088 wide
    # clip for a 1080 wide video only loses 4 pixels on each side, with no resampling.
    video = (
        f"[0:v:0]fps={fps},trim=end_frame={frames},setpts=PTS-STARTPTS,"
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},setsar=1,format=yuv420p[v]"
    )

    if audio is None or (audio.duration_s is not None and audio.duration_s <= 0):
        sound = (
            f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=end_sample={samples},"
            f"asetpts=PTS-STARTPTS,aformat=sample_fmts=s16:sample_rates={SAMPLE_RATE}"
            ":channel_layouts=stereo[a]"
        )
    else:
        # The sound ends where the clip's own sound ends (or the scene does, if that is
        # first). The fade-out is placed there, not at the padded end: a fade on the silence
        # would leave a click where the real sound stops.
        available = scene_s if audio.duration_s is None else min(audio.duration_s, scene_s)
        fade = min(FADE_S, available / 2)
        steps = [
            *stereo_filters(audio.channels),
            f"aresample={SAMPLE_RATE}",
            f"volume={audio.gain_db:.2f}dB",
            "asetpts=PTS-STARTPTS",
            f"atrim=end={available:.6f}",
            f"afade=t=in:st=0:d={fade:.6f}",
            f"afade=t=out:st={available - fade:.6f}:d={fade:.6f}",
            f"apad=whole_len={samples}",
            f"atrim=end_sample={samples}",
            f"aformat=sample_fmts=s16:sample_rates={SAMPLE_RATE}:channel_layouts=stereo",
        ]
        sound = "[0:a:0]" + ",".join(steps) + "[a]"

    return [
        *_BASE,
        "-i",
        file_input(src),
        "-filter_complex",
        f"{video};{sound}",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-frames:v",
        str(frames),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "12",
        # No B-frames: every packet's decode and display times agree, so the joined files
        # cannot shift against each other.
        "-bf",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-fps_mode",
        "cfr",
        "-c:a",
        "pcm_s16le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-f",
        "mov",
        file_input(dest),
    ]


def concat_list(paths: Sequence[Path]) -> str:
    """The list file the concat demuxer reads: one `file` line per trimmed clip."""
    lines = []
    for path in paths:
        name = file_input(path).replace("'", "'\\''")
        lines.append(f"file '{name}'\n")
    return "".join(lines)


def join_args(
    list_path: Path,
    voiceover: Path,
    dest: Path,
    *,
    fps: int,
    voiceover_channels: int | None,
) -> list[str]:
    """Stage 2: join the trimmed clips, mix their sound under the voiceover, and encode.

    The clips' sound is already at its level under the voice (stage 1), so it is mixed as
    it is. The voiceover is the first mix input and sets the length of the sound
    (`duration=first`). The video is the joined clips: exactly the timeline's frames.
    """
    voice = [
        *stereo_filters(voiceover_channels),
        f"aresample={SAMPLE_RATE}",
        f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo",
    ]
    graph = (
        f"[1:a:0]{','.join(voice)}[voice];"
        f"[0:a:0]aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo[clips];"
        "[voice][clips]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]"
    )
    return [
        *_BASE,
        "-f",
        "concat",
        "-safe",
        "0",
        "-protocol_whitelist",
        "file",
        "-i",
        file_input(list_path),
        "-i",
        file_input(voiceover),
        "-filter_complex",
        graph,
        "-map",
        "0:v:0",
        "-map",
        "[mix]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-fps_mode",
        "cfr",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        file_input(dest),
    ]
