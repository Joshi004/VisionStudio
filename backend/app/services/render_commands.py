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

from app.services.ffmpeg import LoudnormMeasure, file_input

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
    # The gain given to this clip's sound, in dB. See `clip_gain_db` (the story render's own
    # gain, `story_render_plan.shot_gain_db`, may also be a small boost).
    gain_db: float
    # The stretches of the clip, in its own seconds, in which narration plays and the sound is
    # lowered by `duck_db` (negative), with ramps of `duck_ramp_s`. See `duck_volume_filter`.
    duck_windows: tuple[tuple[float, float], ...] = ()
    duck_db: float = 0.0
    duck_ramp_s: float = 0.0
    # The stretches in which an ambience bed plays and the shot's own sound is lowered by
    # `bed_duck_db` (MD-17, MUSIC-012). Empty when the setting is 0.
    bed_duck_windows: tuple[tuple[float, float], ...] = ()
    bed_duck_db: float = 0.0
    bed_duck_ramp_s: float = 0.0


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


def duck_volume_filter(
    windows: Sequence[tuple[float, float]], depth_db: float, ramp_s: float
) -> str:
    """A `volume` filter that lowers the sound by `depth_db` (negative) inside each window and
    brings it back with linear ramps (PHASE-028).

    `windows` are `(start, end)` in the sound's own seconds. The sound reaches its full depth at
    `start` (the fall begins `ramp_s` earlier) and starts to come back at `end` (it is whole
    again `ramp_s` later). Where two windows' ramps meet, the deeper one wins. The expression is
    evaluated per audio frame (`eval=frame`), so the gain moves in steps of one frame (about
    21 ms for 1024 samples at 48 kHz), which is smooth enough for ramps of a quarter second.

    Every number is a formatted float and never text from outside, and the expression is quoted
    so the commas inside it are not read as filter separators.
    """
    if depth_db >= 0:
        raise ValueError("The ducking depth must be below 0 dB.")
    if ramp_s <= 0:
        raise ValueError("The ducking ramp must be longer than 0 s.")
    if not windows:
        raise ValueError("A ducking filter needs at least one window.")
    drop = 1 - 10 ** (depth_db / 20)
    return f"volume='1-{drop:.6f}*{_envelope(windows, ramp_s)}':eval=frame"


def _envelope(windows: Sequence[tuple[float, float]], ramp_s: float) -> str:
    """An FFmpeg expression of `t` that is 0 outside the windows and their ramps and 1 inside
    them. The product of the rise and the fall is both ramps at once, whatever the window's
    length, and where two windows' ramps meet the higher one wins.
    """
    depths = [
        f"(clip((t-({start - ramp_s:.6f}))/{ramp_s:.6f},0,1)"
        f"*clip((({end + ramp_s:.6f})-t)/{ramp_s:.6f},0,1))"
        for start, end in windows
    ]
    deepest = depths[0]
    for other in depths[1:]:
        deepest = f"max({deepest},{other})"
    return deepest


def gain_bump_filter(windows: Sequence[tuple[float, float]], gain_db: float, ramp_s: float) -> str:
    """A `volume` filter that raises the sound by `gain_db` (above 0) inside each window, with
    linear ramps, the opposite of `duck_volume_filter` (a swell of an ambience bed, MUSIC-012).
    """
    if gain_db <= 0:
        raise ValueError("The swell must be above 0 dB.")
    if ramp_s <= 0:
        raise ValueError("The swell ramp must be longer than 0 s.")
    if not windows:
        raise ValueError("A swell filter needs at least one window.")
    rise = 10 ** (gain_db / 20) - 1
    return f"volume='1+{rise:.6f}*{_envelope(windows, ramp_s)}':eval=frame"


def sample_count(frames: int, fps: int) -> int:
    """How many samples of 48 kHz sound last as long as `frames` frames at `fps`."""
    return round(frames * SAMPLE_RATE / fps)


def shot_sound_graph(audio: ClipAudio | None, samples: int) -> str:
    """The filter graph (`[0:a:0]` in, `[a]` out) of one shot's sound: `samples` samples of
    48 kHz stereo 16-bit sound, at the clip's gain, lowered under the narration (and under a
    bed), faded at both ends, or silence when `audio` is None. One definition for the render's
    stage 1 (`trim_args`) and the preview (`shot_audio_args`), so the two cannot differ.
    """
    scene_s = samples / SAMPLE_RATE
    if audio is None or (audio.duration_s is not None and audio.duration_s <= 0):
        return (
            f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=end_sample={samples},"
            f"asetpts=PTS-STARTPTS,aformat=sample_fmts=s16:sample_rates={SAMPLE_RATE}"
            ":channel_layouts=stereo[a]"
        )
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
        # After `asetpts`, so the ducking's `t` is the clip's own time, from 0.
        *(
            [duck_volume_filter(audio.duck_windows, audio.duck_db, audio.duck_ramp_s)]
            if audio.duck_windows
            else []
        ),
        *(
            [duck_volume_filter(audio.bed_duck_windows, audio.bed_duck_db, audio.bed_duck_ramp_s)]
            if audio.bed_duck_windows and audio.bed_duck_db < 0
            else []
        ),
        f"atrim=end={available:.6f}",
        f"afade=t=in:st=0:d={fade:.6f}",
        f"afade=t=out:st={available - fade:.6f}:d={fade:.6f}",
        f"apad=whole_len={samples}",
        f"atrim=end_sample={samples}",
        f"aformat=sample_fmts=s16:sample_rates={SAMPLE_RATE}:channel_layouts=stereo",
    ]
    return "[0:a:0]" + ",".join(steps) + "[a]"


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

    # `scale ... increase` covers the output size and `crop` takes the centre, so a 1088 wide
    # clip for a 1080 wide video only loses 4 pixels on each side, with no resampling.
    # `tpad` repeats the last frame once, in case the clip is one frame short of its shot: a shot's
    # length is stored on H3's own length, so a project at another frame rate can need one frame
    # more than the clip has after the rates are converted (D-9). A longer clip is cut as before.
    video = (
        f"[0:v:0]fps={fps},tpad=stop_mode=clone:stop=1,trim=end_frame={frames},"
        "setpts=PTS-STARTPTS,"
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},setsar=1,format=yuv420p[v]"
    )

    sound = shot_sound_graph(audio, samples)

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


# --- The story render (PHASE-028) ---------------------------------------------------------------


@dataclass(frozen=True)
class NarrationInput:
    """One narration speech and where it starts on the story's timeline."""

    path: Path
    channels: int | None
    start_sample: int
    # How long the speech is, in seconds, as it was measured.
    seconds: float


def narration_track_args(
    units: Sequence[NarrationInput], dest: Path, *, total_samples: int
) -> list[str]:
    """The narration layer: one 48 kHz stereo WAV of exactly `total_samples` samples with each
    speech at its own start sample and silence everywhere else.

    The pieces are joined with the `concat` filter (silence, speech, silence, speech, ...) rather
    than delayed and mixed, so every start is a sample-exact position and nothing can overlap. A
    speech is cut to its slot (it never runs into the next speech or past the end) and padded
    with silence to its measured length. The units must be in order of their start.
    """
    if not units:
        raise ValueError("The narration track needs at least one speech.")
    labels: list[str] = []
    steps: list[str] = []
    cursor = 0
    inputs: list[str] = []
    for position, unit in enumerate(units):
        next_start = (
            units[position + 1].start_sample if position + 1 < len(units) else total_samples
        )
        start = max(unit.start_sample, cursor)
        length = min(round(unit.seconds * SAMPLE_RATE), next_start - start, total_samples - start)
        if length < 1:
            continue
        if start > cursor:
            gap = f"gap{position}"
            steps.append(
                f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=end_sample={start - cursor},"
                f"asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}"
                f":channel_layouts=stereo[{gap}]"
            )
            labels.append(gap)
        index = len(inputs) // 2  # `inputs` holds `-i` and a path for each file
        inputs += ["-i", file_input(unit.path)]
        speech = f"speech{position}"
        chain = [
            *stereo_filters(unit.channels),
            f"aresample={SAMPLE_RATE}",
            f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo",
            f"apad=whole_len={length}",
            f"atrim=end_sample={length}",
            "asetpts=PTS-STARTPTS",
        ]
        steps.append(f"[{index}:a:0]" + ",".join(chain) + f"[{speech}]")
        labels.append(speech)
        cursor = start + length
    if not inputs:
        raise ValueError("No narration speech fits on the timeline.")
    if cursor < total_samples:
        steps.append(
            f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=end_sample={total_samples - cursor},"
            f"asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}"
            ":channel_layouts=stereo[tail]"
        )
        labels.append("tail")

    graph = ";".join(steps) + ";" + "".join(f"[{label}]" for label in labels)
    graph += f"concat=n={len(labels)}:v=0:a=1[out]"
    return [
        *_BASE,
        *inputs,
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-c:a",
        "pcm_s16le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-f",
        "wav",
        file_input(dest),
    ]


# --- The music layers and the master (MUSIC-012) --------------------------------------------

_FADE_CURVES: Final = {"linear": "tri", "equal_power": "qsin"}
_FLOAT_STEREO: Final = f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo"
_LIMITER: Final = "alimiter=limit=0.97:level=0"


@dataclass(frozen=True)
class LaneSound:
    """One placed sound of a music lane: where it starts on the story's timeline, the part of
    the file it plays, its fades and its own ducks, dips and swells. Every window is in the
    sound's own seconds (0 is its first sample), as `story_render_plan` records them.
    """

    path: Path
    channels: int | None
    start_sample: int
    in_sample: int
    length_samples: int
    gain_db: float
    fade_in_samples: int
    fade_in_shape: str
    fade_out_samples: int
    fade_out_shape: str
    duck_windows: tuple[tuple[float, float], ...] = ()
    duck_db: float = 0.0
    duck_ramp_s: float = 0.0
    dip_windows: tuple[tuple[float, float], ...] = ()
    dip_db: float = 0.0
    dip_ramp_s: float = 0.0
    bump_windows: tuple[tuple[float, float], ...] = ()
    bump_db: float = 0.0
    bump_ramp_s: float = 0.0


def _lane_chain(sound: LaneSound, total_samples: int) -> list[str]:
    length = sound.length_samples
    steps = [
        *stereo_filters(sound.channels),
        # Resampled first: the placement counts samples at 48 kHz, whatever the file's rate.
        f"aresample={SAMPLE_RATE}",
        _FLOAT_STEREO,
        f"atrim=start_sample={sound.in_sample}:end_sample={sound.in_sample + length}",
        "asetpts=PTS-STARTPTS",
        f"volume={sound.gain_db:.2f}dB",
    ]
    if sound.fade_in_samples > 0:
        curve = _FADE_CURVES[sound.fade_in_shape]
        steps.append(f"afade=t=in:ss=0:ns={sound.fade_in_samples}:curve={curve}")
    if sound.fade_out_samples > 0:
        curve = _FADE_CURVES[sound.fade_out_shape]
        steps.append(
            f"afade=t=out:ss={length - sound.fade_out_samples}:ns={sound.fade_out_samples}"
            f":curve={curve}"
        )
    # After `asetpts`, so every window's `t` is the sound's own time, from 0.
    if sound.duck_windows and sound.duck_db < 0:
        steps.append(duck_volume_filter(sound.duck_windows, sound.duck_db, sound.duck_ramp_s))
    if sound.dip_windows and sound.dip_db < 0:
        steps.append(duck_volume_filter(sound.dip_windows, sound.dip_db, sound.dip_ramp_s))
    if sound.bump_windows and sound.bump_db > 0:
        steps.append(gain_bump_filter(sound.bump_windows, sound.bump_db, sound.bump_ramp_s))
    if sound.start_sample > 0:
        steps.append(f"adelay={sound.start_sample}S|{sound.start_sample}S")
    steps += [
        f"apad=whole_len={total_samples}",
        f"atrim=end_sample={total_samples}",
        "asetpts=PTS-STARTPTS",
    ]
    return steps


def music_lane_args(sounds: Sequence[LaneSound], dest: Path, *, total_samples: int) -> list[str]:
    """One music lane: a 32-bit float 48 kHz stereo WAV of exactly `total_samples` samples with
    every sound at its own start sample (sample-exact: `adelay` counts samples) and silence
    everywhere else. Sounds that overlap, such as the two sides of a crossfade, are added
    (`amix normalize=0`), and their fades make the crossfade.
    """
    if not sounds:
        raise ValueError("A music lane needs at least one sound.")
    if total_samples < 1:
        raise ValueError("A music lane needs at least one sample.")
    inputs: list[str] = []
    steps: list[str] = []
    labels: list[str] = []
    for number, sound in enumerate(sounds):
        if sound.length_samples < 1:
            raise ValueError("A placed sound needs at least one sample.")
        inputs += ["-i", file_input(sound.path)]
        label = f"s{number}"
        steps.append(f"[{number}:a:0]" + ",".join(_lane_chain(sound, total_samples)) + f"[{label}]")
        labels.append(f"[{label}]")
    if len(labels) == 1:
        steps[0] = steps[0][: -len(labels[0])] + "[lane]"
        graph = ";".join(steps)
    else:
        graph = ";".join(steps) + ";" + "".join(labels)
        graph += (
            f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0[lane]"
        )
    return [
        *_BASE,
        *inputs,
        "-filter_complex",
        graph,
        "-map",
        "[lane]",
        "-c:a",
        "pcm_f32le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-f",
        "wav",
        file_input(dest),
    ]


def premaster_mix_args(
    list_path: Path,
    dest: Path,
    *,
    narration: Path | None,
    narration_gain_db: float,
    lanes: Sequence[Path] = (),
) -> list[str]:
    """Stage 2 of the story render: the sound of the joined shots, the narration layer and the
    music lanes mixed into one 32-bit float WAV, the pre-master.

    The shots' sound is already at its level and ducked under the narration (stage 1), the lanes
    already hold the music's own level and ducks. Everything is mixed as it is (`normalize=0`, so
    nothing is made quieter by the mix) and a limiter keeps a peak from clipping. The shots' sound
    is the first input and sets the length (`duration=first`): the joined shots, exactly the
    timeline's frames. Without narration and lanes the shots' sound is only limited, and with
    narration only, this is the mix the render has always made.
    """
    graph_parts: list[str] = []
    labels: list[str] = []
    extra_inputs: list[str] = []
    if narration is not None:
        extra_inputs += ["-i", file_input(narration)]
    for lane in lanes:
        extra_inputs += ["-i", file_input(lane)]
    if narration is None and not lanes:
        graph = f"[0:a:0]{_FLOAT_STEREO},{_LIMITER},{_FLOAT_STEREO}[mix]"
    else:
        graph_parts.append(f"[0:a:0]{_FLOAT_STEREO}[shots]")
        labels.append("[shots]")
        position = 1
        if narration is not None:
            graph_parts.append(
                f"[{position}:a:0]volume={narration_gain_db:.2f}dB,{_FLOAT_STEREO}[narration]"
            )
            labels.append("[narration]")
            position += 1
        for number in range(len(lanes)):
            graph_parts.append(f"[{position}:a:0]{_FLOAT_STEREO}[lane{number}]")
            labels.append(f"[lane{number}]")
            position += 1
        graph = (
            ";".join(graph_parts)
            + ";"
            + "".join(labels)
            + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
            + f"{_LIMITER},{_FLOAT_STEREO}[mix]"
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
        *extra_inputs,
        "-filter_complex",
        graph,
        "-map",
        "[mix]",
        "-c:a",
        "pcm_f32le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-f",
        "wav",
        file_input(dest),
    ]


@dataclass(frozen=True)
class Normalization:
    """The second pass of `loudnorm`: the targets and what the first pass measured."""

    target_lufs: float
    true_peak_db: float
    lra: float
    measured: LoudnormMeasure


def master_filters(norm: Normalization | None) -> list[str]:
    """The filters that bring the pre-master to the target loudness and true-peak ceiling (the
    second pass of `loudnorm`, linear when the sound allows it), back at 48 kHz. Without
    measurements (a sound too quiet or too short to measure) the sound is left as it is.
    """
    if norm is None:
        return [_FLOAT_STEREO]
    m = norm.measured
    return [
        f"loudnorm=I={norm.target_lufs:.2f}:TP={norm.true_peak_db:.2f}:LRA={norm.lra:.2f}"
        f":measured_I={m.input_i:.2f}:measured_TP={m.input_tp:.2f}:measured_LRA={m.input_lra:.2f}"
        f":measured_thresh={m.input_thresh:.2f}:offset={m.target_offset:.2f}:linear=true",
        # loudnorm works at 192 kHz inside and hands that rate on.
        f"aresample={SAMPLE_RATE}",
        # In its dynamic mode, loudnorm stamps its last block as a full 100 ms, so the file
        # would claim a length rounded up to 0.1 s. The samples themselves are right.
        "asetpts=N/SR/TB",
        _FLOAT_STEREO,
    ]


def final_encode_args(
    list_path: Path,
    premaster: Path,
    dest: Path,
    *,
    fps: int,
    norm: Normalization | None,
) -> list[str]:
    """The last stage: the joined shots' picture and the normalized pre-master, encoded as the
    finished H.264 and AAC video. The picture is the first input and the pre-master the second.
    """
    graph = "[1:a:0]" + ",".join(master_filters(norm)) + "[out]"
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
        file_input(premaster),
        "-filter_complex",
        graph,
        "-map",
        "0:v:0",
        "-map",
        "[out]",
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


# --- The preview (MUSIC-012, MD-20) ---------------------------------------------------------


def shot_audio_args(
    src: Path, dest: Path, *, frames: int, fps: int, audio: ClipAudio | None
) -> list[str]:
    """One shot's sound alone, as the render's stage 1 makes it (`shot_sound_graph`), as a 16-bit
    WAV: for the preview, which has no picture.
    """
    if frames < 1:
        raise ValueError("A clip needs at least one frame.")
    return [
        *_BASE,
        "-i",
        file_input(src),
        "-filter_complex",
        shot_sound_graph(audio, sample_count(frames, fps)),
        "-map",
        "[a]",
        "-c:a",
        "pcm_s16le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-f",
        "wav",
        file_input(dest),
    ]


def silence_args(dest: Path, *, samples: int) -> list[str]:
    """`samples` samples of silence as a 16-bit 48 kHz stereo WAV (a shot outside a preview)."""
    if samples < 1:
        raise ValueError("A silence needs at least one sample.")
    graph = (
        f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=end_sample={samples},asetpts=PTS-STARTPTS,"
        f"aformat=sample_fmts=s16:sample_rates={SAMPLE_RATE}:channel_layouts=stereo[a]"
    )
    return [
        *_BASE,
        "-filter_complex",
        graph,
        "-map",
        "[a]",
        "-c:a",
        "pcm_s16le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-f",
        "wav",
        file_input(dest),
    ]


def window_args(src: Path, dest: Path, *, start_sample: int, end_sample: int) -> list[str]:
    """The part of a 48 kHz WAV from `start_sample` to `end_sample`, as a float WAV."""
    if start_sample < 0 or end_sample <= start_sample:
        raise ValueError("A window needs an end after its start.")
    return [
        *_BASE,
        "-i",
        file_input(src),
        "-af",
        f"atrim=start_sample={start_sample}:end_sample={end_sample},asetpts=PTS-STARTPTS",
        "-c:a",
        "pcm_f32le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-f",
        "wav",
        file_input(dest),
    ]


def audio_encode_args(src: Path, dest: Path, *, norm: Normalization | None) -> list[str]:
    """A normalized, AAC-encoded sound-only file (the preview), with the render's own master."""
    return [
        *_BASE,
        "-i",
        file_input(src),
        "-af",
        ",".join(master_filters(norm)),
        "-vn",
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
