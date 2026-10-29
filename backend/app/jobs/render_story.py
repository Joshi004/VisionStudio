"""The `render_story` job: the story's finished video (PHASE-028, `Path_ahead.md` Section 33).

It is a local job: everything happens in `start`, in FFmpeg child processes (never in the event
loop), and there is no provider job id. It is its own pool (one render at a time), and every
FFmpeg run is at low priority (`ffmpeg.run_tool`).

It renders the **timeline stored on the job** (`job.input.timeline`, frozen when Render was
pressed by `services/story_renders.start_render`) and nothing else, so what happens to the shots
afterwards does not matter, and a restart renders the same timeline again from the start
(`start_again`). The pure rules are in `services/story_render_plan.py` and the commands in
`services/render_commands.py`.

The steps, which are also the phases the page shows:

1. *checking the clips*: every clip, narration speech and music file is read with ffprobe, and
   each clip must have the frames its shot needs, so a bad file is named before any FFmpeg run is
   spent;
2. *measuring the sound levels*: each clip's sound over the part its shot uses, so every shot can
   be brought to the same loudness (a cut then does not jump);
3. *placing the narration*: one WAV of the whole story's length with every narration speech at its
   own place, and its loudness measured. For a continuous explainer (FLOW-008) this is *placing
   the voice*: each scene's take at its place, cut around the presenter shots that use their
   clip's own voice (`build_voice`), and the sound of a presenter clip is dropped, or, for those
   shots, brought to the take's loudness and faded at both ends;
4. *placing the music layers* (MUSIC-012, only with music): the score, the ambience beds and the
   sounds (hits and point sounds), each one WAV of the whole story's length, with every placed
   sound at its own sample, its fades, its ducks under the voice, its dips and its swells;
5. *trimming shot i of n* (stage 1): each clip becomes a MOV with exactly its frame count, at the
   output size, with its sound at 48 kHz stereo, at its gain and lowered where narration plays
   (and under an ambience bed, when that setting is on);
6. *mixing the sound* (stage 2): the shots' sound, the narration and the music layers become one
   float WAV, the pre-master;
7. *measuring the mix*: the first pass of `loudnorm` over the pre-master (MD-19);
8. *writing the captions and callouts* (EXPLAINER-008 and 010, only for an explainer with either):
   the frozen caption groups and callouts become one ASS file (`services/caption_ass.py`);
   *joining the shots and encoding the video* (stage 3): the MOVs are joined, the captions and
   callouts are burned into the picture with the bundled font, the pre-master is brought to the
   target loudness and true-peak ceiling by the second pass of `loudnorm`, and the final H.264
   and AAC file is written;
9. *checking the video*: size, frame count, fps and length are compared with the timeline;
10. *measuring the finished sound*: the loudness and true peak of the file, recorded on the render
    (a miss of the target is a note, not a failure);
11. *saving the video*: the file is stored, and the `story_render` row and the finished job are
    saved in one transaction.

Every temporary file is removed afterwards, whatever happens (a crash is covered by the clean-up
of the temp folder at start). Logs hold the job id and the step, never a path's content.

The helpers below that the music preview (`jobs/preview_music_mix.py`) also uses are public, so
the preview makes its sound with the same functions as the render.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.handlers import JobHandler
from app.services import (
    callout_render,
    caption_ass,
    caption_plan,
    ffmpeg,
    font_metrics,
    render_commands,
    story_render_plan,
    story_renders,
)
from app.services.storage import Storage, StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = story_renders.JOB_TYPE

NARRATION_TIMEOUT_S: Final = 600.0
LANE_TIMEOUT_S: Final = 900.0
TRIM_TIMEOUT_S: Final = 300.0
PREMASTER_TIMEOUT_S: Final = 1800.0
JOIN_TIMEOUT_S: Final = 3600.0
# How much of FFmpeg's own error text a failed job shows.
ERROR_TAIL_CHARS: Final = 500

# The fonts the captions are drawn with, bundled with the app (EXPLAINER-008), so a render looks
# the same on any machine.
FONTS_DIR: Final = font_metrics.FONTS_DIR
VIDEO_SETTINGS: Final = "libx264 crf 18 preset medium yuv420p"
AUDIO_SETTINGS: Final = "aac 192k 48000 Hz stereo"
_CHANGED_MESSAGE: Final = (
    "This render's timeline is not one this version understands. Render again."
)
SAMPLES_PER_MS: Final = render_commands.SAMPLE_RATE // 1000
# The order the lanes are made in (and listed in the render's record).
LANES: Final = (
    story_render_plan.LANE_BED,
    story_render_plan.LANE_SCORE,
    story_render_plan.LANE_SOUNDS,
)
_SHAPES: Final = ("linear", "equal_power")
# A finished sound this far from the target loudness (in LU) is noted on the render.
LOUDNESS_TOLERANCE_LU: Final = 1.0
# ... and this far above the ceiling (in dB) too. Meters read a true peak to about a tenth.
TRUE_PEAK_TOLERANCE_DB: Final = 0.1


class RenderFailed(Exception):
    """A failure with a message meant for the user. It fails the job."""


@dataclass(frozen=True)
class VoiceWindow:
    """The part of a scene's take under a shot that uses its clip's own voice, in the take's own
    seconds.
    """

    start_s: float
    end_s: float


@dataclass(frozen=True)
class Shot:
    scene_id: str
    scene_index: int
    shot_id: str
    frames: int
    take_id: int
    take_number: int
    path: str
    source_frames: int
    duck: tuple[tuple[float, float], ...]
    bed_duck: tuple[tuple[float, float], ...]
    # Only in a continuous explainer: `take` (the sound of the clip is dropped) or `clip` (the
    # clip's own sound is the voice) for a presenter shot, None for any other shot.
    voice: str | None = None
    voice_window: VoiceWindow | None = None

    @property
    def label(self) -> str:
        return f"{self.shot_id} of scene {self.scene_index}"


@dataclass(frozen=True)
class Narration:
    unit_id: str
    path: str
    start_ms: int
    seconds: float


@dataclass(frozen=True)
class VoicePiece:
    """A part of a voice take that is heard: where it starts in the story (samples at 48 kHz),
    the part of the take it plays, and the fades at its ends.
    """

    in_sample: int
    start_sample: int
    length_samples: int
    fade_in_samples: int
    fade_out_samples: int


@dataclass(frozen=True)
class VoiceTake:
    scene_id: str
    audio_id: int
    path: str
    seconds: float
    pieces: tuple[VoicePiece, ...]


@dataclass(frozen=True)
class VoiceLevel:
    """What was done to a voice take: its loudness, and the gain that brings it to its target."""

    lufs: float | None
    gain_db: float


@dataclass(frozen=True)
class VoiceMatch:
    """What a shot on its clip's own voice is matched to: the loudness of the take over the same
    span (None when it could not be measured) and the gain the take has in the mix.
    """

    take_span_lufs: float | None
    take_gain_db: float


@dataclass(frozen=True)
class MusicSound:
    """A placed music sound, as `story_render_plan` recorded it."""

    item_id: str
    cue_id: str
    lane: str
    path: str
    start_sample: int
    in_sample: int
    length_samples: int
    gain_db: float
    fade_in_samples: int
    fade_in_shape: str
    fade_out_samples: int
    fade_out_shape: str
    duck: tuple[tuple[float, float], ...]
    duck_db: float | None
    dips: tuple[tuple[float, float], ...]
    bumps: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Music:
    placement_id: int
    placement_version: int
    ambience: bool
    total_samples: int
    sounds: list[MusicSound]
    left_out: int


@dataclass(frozen=True)
class Timeline:
    fps: int
    width: int
    height: int
    total_frames: int
    shots: list[Shot]
    narration: list[Narration]
    voice: list[VoiceTake] | None
    music: Music | None
    captions: caption_plan.CaptionTrack | None
    callouts: callout_render.CalloutTrack | None
    shot_target_lufs: float
    narration_target_lufs: float
    max_boost_db: float
    voice_fade_s: float
    duck_db: float
    duck_ramp_s: float
    music_duck_ramp_s: float
    dip_db: float
    dip_ramp_s: float
    swell_db: float
    swell_ramp_s: float
    bed_shot_duck_db: float
    bed_shot_ramp_s: float
    master_lufs: float
    master_true_peak_db: float
    master_lra: float

    @property
    def total_samples(self) -> int:
        return render_commands.sample_count(self.total_frames, self.fps)


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _windows(value: object) -> tuple[tuple[float, float], ...] | None:
    if not isinstance(value, list):
        return None
    windows: list[tuple[float, float]] = []
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            return None
        start, end = _number(pair[0]), _number(pair[1])
        if start is None or end is None:
            return None
        windows.append((start, end))
    return tuple(windows)


def _fade(value: object) -> tuple[int, str]:
    if not isinstance(value, dict):
        raise RenderFailed(_CHANGED_MESSAGE)
    samples, shape = _whole(value.get("samples")), value.get("shape")
    if samples is None or samples < 0 or shape not in _SHAPES:
        raise RenderFailed(_CHANGED_MESSAGE)
    return samples, str(shape)


def _parse_sound(entry: object) -> MusicSound:
    if not isinstance(entry, dict):
        raise RenderFailed(_CHANGED_MESSAGE)
    start, source_in = _whole(entry.get("start_sample")), _whole(entry.get("in_sample"))
    length, gain = _whole(entry.get("length_samples")), _number(entry.get("gain_db"))
    duck, dips, bumps = (
        _windows(entry.get("duck")),
        _windows(entry.get("dips")),
        _windows(entry.get("bumps")),
    )
    duck_db = entry.get("duck_db")
    item_id, cue_id, lane, path = (
        entry.get("item_id"),
        entry.get("cue_id"),
        entry.get("lane"),
        entry.get("path"),
    )
    if (
        start is None
        or start < 0
        or source_in is None
        or source_in < 0
        or length is None
        or length < 1
        or gain is None
        or duck is None
        or dips is None
        or bumps is None
        or (duck_db is not None and _number(duck_db) is None)
        or not isinstance(item_id, str)
        or not isinstance(cue_id, str)
        or lane not in LANES
        or not isinstance(path, str)
    ):
        raise RenderFailed(_CHANGED_MESSAGE)
    fade_in, fade_out = _fade(entry.get("fade_in")), _fade(entry.get("fade_out"))
    return MusicSound(
        item_id=item_id,
        cue_id=cue_id,
        lane=str(lane),
        path=path,
        start_sample=start,
        in_sample=source_in,
        length_samples=length,
        gain_db=gain,
        fade_in_samples=fade_in[0],
        fade_in_shape=fade_in[1],
        fade_out_samples=fade_out[0],
        fade_out_shape=fade_out[1],
        duck=duck,
        duck_db=_number(duck_db),
        dips=dips,
        bumps=bumps,
    )


def _parse_music(raw: object) -> Music | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise RenderFailed(_CHANGED_MESSAGE)
    placement_id, version = _whole(raw.get("placement_id")), _whole(raw.get("placement_version"))
    total, sounds = _whole(raw.get("total_samples")), raw.get("sounds")
    ambience, left_out = raw.get("ambience"), raw.get("left_out")
    if (
        placement_id is None
        or version is None
        or total is None
        or total < 1
        or not isinstance(sounds, list)
        or not isinstance(ambience, bool)
        or not isinstance(left_out, list)
    ):
        raise RenderFailed(_CHANGED_MESSAGE)
    return Music(
        placement_id=placement_id,
        placement_version=version,
        ambience=ambience,
        total_samples=total,
        sounds=[_parse_sound(entry) for entry in sounds],
        left_out=len(left_out),
    )


def _parse_captions(
    raw: dict[str, Any], width: int, height: int
) -> caption_plan.CaptionTrack | None:
    """The captions of the timeline, or None for a render without. The key must be there (a
    timeline of version 3 always has it), and the style must be made for this output size.
    """
    if "captions" not in raw:
        raise RenderFailed(_CHANGED_MESSAGE)
    try:
        track = caption_plan.parse_track(raw["captions"])
    except caption_plan.CaptionError as exc:
        raise RenderFailed(_CHANGED_MESSAGE) from exc
    if track is not None and (track.style.play_res_x, track.style.play_res_y) != (width, height):
        raise RenderFailed(_CHANGED_MESSAGE)
    return track


def _parse_callouts(
    raw: dict[str, Any], width: int, height: int
) -> callout_render.CalloutTrack | None:
    """The callouts of the timeline, or None for a render without. The key must be there (a
    timeline of version 4 always has it), and the style must be made for this output size.
    """
    if "callouts" not in raw:
        raise RenderFailed(_CHANGED_MESSAGE)
    try:
        track = callout_render.parse_track(raw["callouts"])
    except callout_render.CalloutError as exc:
        raise RenderFailed(_CHANGED_MESSAGE) from exc
    if track is not None and (track.style.play_res_x, track.style.play_res_y) != (width, height):
        raise RenderFailed(_CHANGED_MESSAGE)
    return track


# What a shot's `voice` may be (see `Shot`).
_SHOT_VOICES: Final = (None, story_render_plan.VOICE_TAKE, story_render_plan.VOICE_CLIP)

_CONSTANT_KEYS: Final = (
    "shot_target_lufs",
    "narration_target_lufs",
    "max_boost_db",
    "voice_fade_s",
    "duck_db",
    "duck_ramp_s",
    "music_duck_ramp_s",
    "dip_db",
    "dip_ramp_s",
    "swell_db",
    "swell_ramp_s",
    "bed_shot_duck_db",
    "bed_shot_ramp_s",
)


def _parse_voice(raw: object) -> list[VoiceTake] | None:
    """The voice takes of the timeline, or None for a render without. Their pieces must lie
    inside the take.
    """
    if raw is None:
        return None
    entries = raw.get("takes") if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        raise RenderFailed(_CHANGED_MESSAGE)
    takes: list[VoiceTake] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise RenderFailed(_CHANGED_MESSAGE)
        scene_id, path, audio_id = (
            entry.get("scene_id"),
            entry.get("path"),
            _whole(entry.get("audio_id")),
        )
        seconds, pieces = _number(entry.get("seconds")), entry.get("pieces")
        if (
            not isinstance(scene_id, str)
            or not isinstance(path, str)
            or audio_id is None
            or seconds is None
            or seconds <= 0
            or not isinstance(pieces, list)
        ):
            raise RenderFailed(_CHANGED_MESSAGE)
        parsed: list[VoicePiece] = []
        for piece in pieces:
            if not isinstance(piece, dict):
                raise RenderFailed(_CHANGED_MESSAGE)
            numbers = [
                _whole(piece.get(key))
                for key in (
                    "in_sample",
                    "start_sample",
                    "length_samples",
                    "fade_in_samples",
                    "fade_out_samples",
                )
            ]
            if any(value is None or value < 0 for value in numbers) or not numbers[2]:
                raise RenderFailed(_CHANGED_MESSAGE)
            in_sample, start, length, fade_in, fade_out = (value or 0 for value in numbers)
            if fade_in > length or fade_out > length:
                raise RenderFailed(_CHANGED_MESSAGE)
            parsed.append(VoicePiece(in_sample, start, length, fade_in, fade_out))
        takes.append(VoiceTake(scene_id, audio_id, path, seconds, tuple(parsed)))
    return takes


def _parse_voice_window(raw: object) -> VoiceWindow | None:
    if raw is None:
        return None
    start = _number(raw.get("start_s")) if isinstance(raw, dict) else None
    end = _number(raw.get("end_s")) if isinstance(raw, dict) else None
    if start is None or end is None or start < 0 or end <= start:
        raise RenderFailed(_CHANGED_MESSAGE)
    return VoiceWindow(start, end)


def parse_timeline(recorded: object) -> Timeline:
    """Reads `job.input` (or a `{"timeline": ...}` made in memory) back into a timeline. Raises
    `RenderFailed` for anything the handler does not understand, instead of rendering something
    half right.
    """
    raw = recorded.get("timeline") if isinstance(recorded, dict) else None
    if not isinstance(raw, dict) or raw.get("version") != story_render_plan.TIMELINE_VERSION:
        raise RenderFailed(_CHANGED_MESSAGE)

    fps, width, height = _whole(raw.get("fps")), _whole(raw.get("width")), _whole(raw.get("height"))
    total = _whole(raw.get("total_frames"))
    entries, speeches, constants = raw.get("shots"), raw.get("narration"), raw.get("constants")
    master = raw.get("master")
    if (
        fps is None
        or fps < 1
        or width is None
        or width < 2
        or height is None
        or height < 2
        or total is None
        or not isinstance(entries, list)
        or not entries
        or not isinstance(speeches, list)
        or not isinstance(constants, dict)
        or not isinstance(master, dict)
    ):
        raise RenderFailed(_CHANGED_MESSAGE)

    shots: list[Shot] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise RenderFailed(_CHANGED_MESSAGE)
        frames, take_id = _whole(entry.get("frames")), _whole(entry.get("take_id"))
        source_frames, number = _whole(entry.get("source_frames")), _whole(entry.get("take_number"))
        index = _whole(entry.get("scene_index"))
        duck, bed_duck = _windows(entry.get("duck")), _windows(entry.get("bed_duck"))
        voice_of_shot, window = entry.get("voice"), _parse_voice_window(entry.get("voice_window"))
        scene_id, shot_id, path = entry.get("scene_id"), entry.get("shot_id"), entry.get("path")
        if (
            frames is None
            or frames < 1
            or take_id is None
            or source_frames is None
            or source_frames < 1
            or number is None
            or index is None
            or duck is None
            or bed_duck is None
            or voice_of_shot not in _SHOT_VOICES
            or not isinstance(scene_id, str)
            or not isinstance(shot_id, str)
            or not isinstance(path, str)
        ):
            raise RenderFailed(_CHANGED_MESSAGE)
        shots.append(
            Shot(
                scene_id,
                index,
                shot_id,
                frames,
                take_id,
                number,
                path,
                source_frames,
                duck,
                bed_duck,
                voice_of_shot,
                window,
            )
        )
    if sum(shot.frames for shot in shots) != total:
        raise RenderFailed(_CHANGED_MESSAGE)

    narration: list[Narration] = []
    for speech in speeches:
        if not isinstance(speech, dict):
            raise RenderFailed(_CHANGED_MESSAGE)
        start_ms, seconds = _whole(speech.get("start_ms")), _number(speech.get("seconds"))
        unit_id, path = speech.get("unit_id"), speech.get("path")
        if (
            start_ms is None
            or start_ms < 0
            or seconds is None
            or seconds <= 0
            or not isinstance(unit_id, str)
            or not isinstance(path, str)
        ):
            raise RenderFailed(_CHANGED_MESSAGE)
        narration.append(Narration(unit_id, path, start_ms, seconds))
    narration.sort(key=lambda speech: speech.start_ms)
    voice = _parse_voice(raw.get("voice"))
    # The voice is the narration of a continuous explainer: a timeline has one or the other, and
    # only a continuous one has shots on a voice.
    if voice is None and any(shot.voice is not None for shot in shots):
        raise RenderFailed(_CHANGED_MESSAGE)
    if voice is not None and narration:
        raise RenderFailed(_CHANGED_MESSAGE)

    values = {key: _number(constants.get(key)) for key in _CONSTANT_KEYS}
    goals = {key: _number(master.get(key)) for key in ("target_lufs", "true_peak_db", "lra")}
    if any(value is None for value in (*values.values(), *goals.values())):
        raise RenderFailed(_CHANGED_MESSAGE)
    duck_db, ramp = values["duck_db"], values["duck_ramp_s"]
    assert duck_db is not None and ramp is not None  # checked just above
    if duck_db >= 0 or ramp <= 0:
        raise RenderFailed(_CHANGED_MESSAGE)
    music = _parse_music(raw.get("music"))
    if music is not None and music.total_samples != render_commands.sample_count(total, fps):
        raise RenderFailed(_CHANGED_MESSAGE)
    captions = _parse_captions(raw, width, height)
    callouts = _parse_callouts(raw, width, height)

    def known(key: str) -> float:
        return values[key] or 0.0

    return Timeline(
        fps=fps,
        width=width,
        height=height,
        total_frames=total,
        shots=shots,
        narration=narration,
        voice=voice,
        music=music,
        captions=captions,
        callouts=callouts,
        shot_target_lufs=known("shot_target_lufs"),
        narration_target_lufs=known("narration_target_lufs"),
        max_boost_db=known("max_boost_db"),
        voice_fade_s=known("voice_fade_s"),
        duck_db=duck_db,
        duck_ramp_s=ramp,
        music_duck_ramp_s=known("music_duck_ramp_s"),
        dip_db=known("dip_db"),
        dip_ramp_s=known("dip_ramp_s"),
        swell_db=known("swell_db"),
        swell_ramp_s=known("swell_ramp_s"),
        bed_shot_duck_db=known("bed_shot_duck_db"),
        bed_shot_ramp_s=known("bed_shot_ramp_s"),
        master_lufs=goals["target_lufs"] or 0.0,
        master_true_peak_db=goals["true_peak_db"] or 0.0,
        master_lra=goals["lra"] or 0.0,
    )


@dataclass(frozen=True)
class Source:
    path: Path
    probe: ffmpeg.VideoProbe


@dataclass(frozen=True)
class _ShotSound:
    """What was done to a shot's sound, for the render's record. `loudness_lufs` is None when it
    was not measured (no sound, or too quiet or short to measure).
    """

    label: str
    loudness_lufs: float | None
    gain_db: float | None


class RenderStoryHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def start(self, job_id: int) -> None:
        storage = get_storage()
        temp_paths: list[Path] = []
        try:
            await self._render(job_id, storage, temp_paths)
        except RenderFailed as exc:
            async with SessionLocal() as session:
                await store.fail_job(session, job_id, str(exc))
        finally:
            for path in temp_paths:
                storage.discard(path)

    # --- the render ---------------------------------------------------------------

    async def _render(self, job_id: int, storage: Storage, temp_paths: list[Path]) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            await session.commit()
        if job is None or job.status != "running" or job.project_id is None:
            return
        timeline = parse_timeline(job.input)

        await self._phase(job_id, phases.CHECKING_RENDER_CLIPS)
        sources = [await probe_shot(storage, shot) for shot in timeline.shots]
        speeches = [(speech, *await probe_speech(storage, speech)) for speech in timeline.narration]
        take_files = [(take, *await probe_take(storage, take)) for take in timeline.voice or []]
        music_files = (
            [(sound, *await probe_music(storage, sound)) for sound in timeline.music.sounds]
            if timeline.music is not None
            else []
        )

        await self._phase(job_id, phases.MEASURING_LEVELS)
        shot_lufs = [
            # The sound of a presenter clip on the take's voice is dropped: not measured.
            None
            if shot.voice == story_render_plan.VOICE_TAKE
            else await measure_shot(shot, source, timeline.fps)
            for shot, source in zip(timeline.shots, sources, strict=True)
        ]

        # The narration layer, placed on the story's timeline. A continuous explainer has the
        # scenes' takes instead (FLOW-008).
        narration_path: Path | None = None
        narration_lufs: float | None = None
        narration_gain = 0.0
        voice_levels: dict[str, VoiceLevel] = {}
        if timeline.voice is None:
            await self._phase(job_id, phases.PLACING_NARRATION)
            narration_path, narration_lufs, narration_gain = await build_narration(
                storage, timeline, speeches, temp_paths
            )
        else:
            await self._phase(job_id, phases.PLACING_VOICE)
            narration_path, voice_levels = await build_voice(
                storage, timeline, take_files, temp_paths
            )
        matches = await voice_matches(
            timeline, take_files, voice_levels, range(len(timeline.shots))
        )

        # The music layers (MUSIC-012).
        lanes: list[tuple[str, Path]] = []
        if music_files:
            await self._phase(job_id, phases.PLACING_MUSIC_LAYERS)
            lanes = await build_lanes(storage, timeline, music_files, temp_paths)

        # Stage 1: each clip, trimmed to its shot, at its gain, ducked under the narration.
        started = time.monotonic()
        trimmed: list[Path] = []
        sounds: list[_ShotSound] = []
        for number, shot in enumerate(timeline.shots, start=1):
            await self._phase(job_id, phases.trimming_shot(number, len(timeline.shots)))
            source = sources[number - 1]
            audio = clip_audio(
                timeline, shot, source, shot_lufs[number - 1], matches.get(number - 1)
            )
            sounds.append(
                _ShotSound(
                    label=_sound_label(shot, audio),
                    loudness_lufs=shot_lufs[number - 1],
                    gain_db=None if audio is None else audio.gain_db,
                )
            )
            dest = storage.new_temp_path("mov")
            temp_paths.append(dest)
            await run_ffmpeg(
                render_commands.trim_args(
                    source.path,
                    dest,
                    frames=shot.frames,
                    fps=timeline.fps,
                    width=timeline.width,
                    height=timeline.height,
                    audio=audio,
                ),
                TRIM_TIMEOUT_S,
                f"trimming the clip of shot {shot.label}",
            )
            trimmed.append(dest)
        trim_seconds = time.monotonic() - started

        # Stage 2: the sound of the shots, the narration and the music, mixed.
        await self._phase(job_id, phases.MIXING_SOUND)
        listing = storage.new_temp_path("txt")
        temp_paths.append(listing)
        await asyncio.to_thread(write_new_file, listing, render_commands.concat_list(trimmed))
        premaster = await mix_sound(
            storage,
            listing,
            narration_path,
            narration_gain,
            [path for _, path in lanes],
            temp_paths,
        )
        await self._phase(job_id, phases.MEASURING_MIX)
        norm, measured = await measure_master(timeline, premaster)

        # The captions and callouts of an explainer, as one ASS file the final encode burns in.
        captions: tuple[Path, Path] | None = None
        has_captions = timeline.captions is not None and bool(timeline.captions.groups)
        has_callouts = timeline.callouts is not None and bool(timeline.callouts.entries)
        if has_captions or has_callouts:
            await self._phase(job_id, phases.WRITING_CAPTIONS)
            captions = await write_subtitles(
                storage,
                timeline.captions if has_captions else None,
                timeline.callouts if has_callouts else None,
                temp_paths,
            )

        # Stage 3: join the picture, bring the sound to its target, encode.
        await self._phase(job_id, phases.JOINING_STORY)
        started = time.monotonic()
        final = storage.new_temp_path("mp4")
        temp_paths.append(final)
        try:
            encode = render_commands.final_encode_args(
                listing, premaster, final, fps=timeline.fps, norm=norm, captions=captions
            )
        except ValueError as exc:
            raise RenderFailed("The captions or callouts could not be added to the video.") from exc
        await run_ffmpeg(encode, JOIN_TIMEOUT_S, "joining the shots and encoding the video")
        join_seconds = time.monotonic() - started

        await self._phase(job_id, phases.CHECKING_STORY_VIDEO)
        probe = await _check_final(final, timeline)

        await self._phase(job_id, phases.MEASURING_FINAL_SOUND)
        scan = await ffmpeg.scan_loudness(final)
        master = _master_record(timeline, measured, norm is not None, scan)

        await self._phase(job_id, phases.SAVING_STORY_VIDEO)
        await self._save(
            job_id,
            job.project_id,
            job.input,
            storage,
            final,
            probe,
            timeline,
            sounds,
            (narration_lufs, narration_gain if timeline.narration else None),
            _voice_record(timeline, voice_levels),
            _music_record(timeline, lanes),
            master,
            (trim_seconds, join_seconds),
        )

    @staticmethod
    async def _save(
        job_id: int,
        project_id: int,
        recorded: Any,
        storage: Storage,
        final: Path,
        probe: ffmpeg.VideoProbe,
        timeline: Timeline,
        sounds: list[_ShotSound],
        narration: tuple[float | None, float | None],
        voice: list[dict[str, Any]] | None,
        music: dict[str, Any] | None,
        master: dict[str, Any],
        seconds: tuple[float, float],
    ) -> None:
        temp = await storage.describe_temp(final)
        stored = await storage.save(temp, project_id, "mp4")
        audio = probe.audio
        audio_out = (
            {
                "codec": audio.codec_name,
                "sample_rate": audio.sample_rate,
                "channels": audio.channels,
                "duration_s": audio.duration_s,
            }
            if audio is not None
            else None
        )
        levels: dict[str, Any] = {
            "shots": [
                {
                    "scene_id": shot.scene_id,
                    "shot_id": shot.shot_id,
                    "take_id": shot.take_id,
                    "sound": sound.label,
                    "loudness_lufs": _tenth(sound.loudness_lufs),
                    "gain_db": _tenth(sound.gain_db),
                }
                for shot, sound in zip(timeline.shots, sounds, strict=True)
            ],
            "narration": (
                {
                    "units": len(timeline.narration),
                    "loudness_lufs": _tenth(narration[0]),
                    "gain_db": _tenth(narration[1]),
                }
                if timeline.narration
                else None
            ),
            "voice": voice,
            "music": music,
            "master": master,
        }
        output: dict[str, Any] = {
            "final": {
                "frame_count": probe.frame_count,
                "fps": probe.fps,
                "width": probe.width,
                "height": probe.height,
                "duration_s": probe.duration_s,
                "size_bytes": temp.size_bytes,
                "audio": audio_out,
            },
            "levels": levels,
            "captions": (
                {
                    "layout": timeline.captions.style.layout,
                    "groups": len(timeline.captions.groups),
                    "words": sum(len(group.words) for group in timeline.captions.groups),
                }
                if timeline.captions is not None
                else None
            ),
            "callouts": (
                {
                    "count": len(timeline.callouts.entries),
                    "by_type": _count_by_type(timeline.callouts),
                }
                if timeline.callouts is not None
                else None
            ),
            "ffmpeg_version": await ffmpeg.tool_version("ffmpeg"),
            "video": VIDEO_SETTINGS,
            "audio": AUDIO_SETTINGS,
            "seconds": {"trim": round(seconds[0], 1), "join": round(seconds[1], 1)},
        }

        # The render, the finished job and nothing else: saved together or not at all.
        async with SessionLocal() as session:
            row = await story_renders.save_story_render(
                session,
                project_id=project_id,
                job_id=job_id,
                inputs=recorded["timeline"],
                levels=levels,
                path=stored.relative_path,
                size_bytes=temp.size_bytes,
                sha256=temp.sha256,
                width=probe.width,
                height=probe.height,
                frame_count=probe.frame_count,
                duration_s=probe.duration_s,
                audio=audio_out,
            )
            output["render_number"] = row.render_number
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                # Stored files are never deleted.
                _logger.warning(
                    "job %d: video stored but the job is no longer running: %s",
                    job_id,
                    stored.relative_path,
                )
                return
            await session.commit()
        _logger.info(
            "job %d: story video stored: render=%d frames=%s %sx%s %.2f s, trim %.1f s, "
            "join %.1f s",
            job_id,
            output["render_number"],
            probe.frame_count,
            probe.width,
            probe.height,
            probe.duration_s or 0.0,
            seconds[0],
            seconds[1],
        )

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")


# --- Reading the files ----------------------------------------------------------------------


async def probe_shot(storage: Storage, shot: Shot) -> Source:
    """Reads a shot's clip, and refuses one that cannot be used."""
    try:
        path = storage.get_path(shot.path)
    except StorageError as exc:
        raise RenderFailed("A file of this render could not be found on disk.") from exc
    probe = await ffmpeg.probe_video(path)
    if probe is None or probe.frame_count is None:
        raise RenderFailed(
            f"The clip of shot {shot.label} could not be read. Regenerate it, or use another take."
        )
    if probe.frame_count < shot.source_frames:
        raise RenderFailed(
            f"The clip of shot {shot.label} has {probe.frame_count} frames; the shot "
            f"needs {shot.source_frames}. Regenerate it, or use another take."
        )
    return Source(path=path, probe=probe)


async def probe_speech(storage: Storage, speech: Narration) -> tuple[Path, int | None]:
    """A narration speech's file and its channel count."""
    try:
        path = storage.get_path(speech.path)
    except StorageError as exc:
        raise RenderFailed("A file of this render could not be found on disk.") from exc
    probed = await ffmpeg.probe(path)
    if probed is None or not probed.audio_streams:
        raise RenderFailed(
            f"The speech of the narration {speech.unit_id} could not be read. Make it again."
        )
    return path, probed.audio_streams[0].channels


async def probe_take(storage: Storage, take: VoiceTake) -> tuple[Path, int | None]:
    """A scene's voice take file and its channel count."""
    try:
        path = storage.get_path(take.path)
    except StorageError as exc:
        raise RenderFailed("A file of this render could not be found on disk.") from exc
    probed = await ffmpeg.probe(path)
    if probed is None or not probed.audio_streams:
        raise RenderFailed(
            f"The voice take of scene {take.scene_id} could not be read. Make the take again."
        )
    return path, probed.audio_streams[0].channels


async def probe_music(storage: Storage, sound: MusicSound) -> tuple[Path, int | None]:
    """A placed music sound's file and its channel count."""
    try:
        path = storage.get_path(sound.path)
    except StorageError as exc:
        raise RenderFailed("A file of this render could not be found on disk.") from exc
    probed = await ffmpeg.probe(path)
    if probed is None or not probed.audio_streams:
        raise RenderFailed(
            f"The music of '{sound.cue_id}' could not be read. Make it again, then place the music."
        )
    return path, probed.audio_streams[0].channels


async def measure_shot(shot: Shot, source: Source, fps: int) -> float | None:
    """The loudness (LUFS) of a clip's sound over the part its shot uses. A clip with no sound is
    not measured. The sound is measured after the same conversion to stereo the render does, so a
    mono clip is compared as it will be heard.
    """
    audio = source.probe.audio
    if audio is None:
        return None
    return await ffmpeg.measure_loudness(
        source.path,
        duration_s=shot.frames / fps,
        pre_filters=render_commands.stereo_filters(audio.channels),
    )


def clip_audio(
    timeline: Timeline,
    shot: Shot,
    source: Source,
    lufs: float | None,
    match: VoiceMatch | None = None,
) -> render_commands.ClipAudio | None:
    """What stage 1 does to a clip's sound, or None for a clip with no sound.

    In a continuous explainer (FLOW-008) the sound of a presenter clip on the take's voice is
    dropped (None). A presenter clip on its own voice is brought to the loudness the take has
    there (`match`), is not ducked, and fades over `voice_fade_s` at both ends, where the take
    fades the other way.
    """
    if shot.voice == story_render_plan.VOICE_TAKE:
        return None
    audio = source.probe.audio
    if shot.voice == story_render_plan.VOICE_CLIP:
        if audio is None:
            raise RenderFailed(
                f"The clip of shot {shot.label} has no sound, so it cannot be its voice. "
                "Switch it back to the take's voice, or select another take."
            )
        match = match or VoiceMatch(None, 0.0)
        return render_commands.ClipAudio(
            channels=audio.channels,
            duration_s=audio.duration_s,
            gain_db=story_render_plan.voice_match_gain(
                lufs,
                match.take_span_lufs,
                match.take_gain_db,
                timeline.shot_target_lufs,
                timeline.max_boost_db,
            ),
            fade_s=timeline.voice_fade_s,
        )
    if audio is None:
        return None
    return render_commands.ClipAudio(
        channels=audio.channels,
        duration_s=audio.duration_s,
        gain_db=story_render_plan.gain_toward(
            lufs, timeline.shot_target_lufs, timeline.max_boost_db
        ),
        duck_windows=shot.duck,
        duck_db=timeline.duck_db,
        duck_ramp_s=timeline.duck_ramp_s,
        bed_duck_windows=shot.bed_duck,
        bed_duck_db=timeline.bed_shot_duck_db,
        bed_duck_ramp_s=timeline.bed_shot_ramp_s,
    )


# --- Building the layers --------------------------------------------------------------------


async def build_narration(
    storage: Storage,
    timeline: Timeline,
    speeches: Sequence[tuple[Narration, Path, int | None]],
    temp_paths: list[Path],
) -> tuple[Path | None, float | None, float]:
    """The narration layer of the story's length with the given speeches at their places: its
    path, its loudness as it sits in the mix (silence between the speeches is not counted) and
    the gain that brings it to its target. `(None, None, 0.0)` with no speech.
    """
    if not speeches:
        return None, None, 0.0
    path = storage.new_temp_path("wav")
    temp_paths.append(path)
    slots = [
        render_commands.NarrationInput(
            path=file,
            channels=channels,
            start_sample=speech.start_ms * SAMPLES_PER_MS,
            seconds=speech.seconds,
        )
        for speech, file, channels in speeches
    ]
    await run_ffmpeg(
        render_commands.narration_track_args(slots, path, total_samples=timeline.total_samples),
        NARRATION_TIMEOUT_S,
        "placing the narration",
    )
    lufs = await ffmpeg.measure_loudness(path)
    gain = story_render_plan.gain_toward(
        lufs, timeline.narration_target_lufs, timeline.max_boost_db
    )
    return path, lufs, gain


async def build_voice(
    storage: Storage,
    timeline: Timeline,
    files: Sequence[tuple[VoiceTake, Path, int | None]],
    temp_paths: list[Path],
) -> tuple[Path | None, dict[str, VoiceLevel]]:
    """The voice layer of a continuous explainer (FLOW-008): one WAV of the story's length with
    each scene's take, brought to the narration's loudness, at its place. A take plays in pieces
    that leave out the presenter shots on their clip's own voice, with a crossfade at each edge
    (`story_render_plan.voice_pieces`). Its path (None when no piece is heard) and, by scene id,
    each take's loudness and gain. The layer is already at its level: mix it with a gain of 0.
    """
    levels: dict[str, VoiceLevel] = {}
    members: list[render_commands.LaneSound] = []
    for take, path, channels in files:
        lufs = await ffmpeg.measure_loudness(
            path, pre_filters=render_commands.stereo_filters(channels)
        )
        gain = story_render_plan.gain_toward(
            lufs, timeline.narration_target_lufs, timeline.max_boost_db
        )
        levels[take.scene_id] = VoiceLevel(lufs, gain)
        members += [
            render_commands.LaneSound(
                path=path,
                channels=channels,
                start_sample=piece.start_sample,
                in_sample=piece.in_sample,
                length_samples=piece.length_samples,
                gain_db=gain,
                fade_in_samples=piece.fade_in_samples,
                fade_in_shape="linear",
                fade_out_samples=piece.fade_out_samples,
                fade_out_shape="linear",
            )
            for piece in take.pieces
        ]
    if not members:
        return None, levels
    dest = storage.new_temp_path("wav")
    temp_paths.append(dest)
    await run_ffmpeg(
        render_commands.music_lane_args(members, dest, total_samples=timeline.total_samples),
        LANE_TIMEOUT_S,
        "placing the voice",
    )
    return dest, levels


async def voice_matches(
    timeline: Timeline,
    files: Sequence[tuple[VoiceTake, Path, int | None]],
    levels: dict[str, VoiceLevel],
    numbers: Sequence[int],
) -> dict[int, VoiceMatch]:
    """For each shot (by its position, from `numbers`) that uses its clip's own voice, what its
    loudness is matched to: the loudness of the scene's take over the shot's span, and the take's
    gain.
    """
    by_scene = {take.scene_id: (path, channels) for take, path, channels in files}
    matches: dict[int, VoiceMatch] = {}
    for number in numbers:
        shot = timeline.shots[number]
        if shot.voice != story_render_plan.VOICE_CLIP:
            continue
        level = levels.get(shot.scene_id)
        found = by_scene.get(shot.scene_id)
        window = shot.voice_window
        span_lufs: float | None = None
        if found is not None and window is not None:
            span_lufs = await ffmpeg.measure_loudness(
                found[0],
                start_s=window.start_s,
                duration_s=window.end_s - window.start_s,
                pre_filters=render_commands.stereo_filters(found[1]),
            )
        matches[number] = VoiceMatch(span_lufs, level.gain_db if level is not None else 0.0)
    return matches


def _lane_sound(
    timeline: Timeline, sound: MusicSound, path: Path, channels: int | None
) -> render_commands.LaneSound:
    return render_commands.LaneSound(
        path=path,
        channels=channels,
        start_sample=sound.start_sample,
        in_sample=sound.in_sample,
        length_samples=sound.length_samples,
        gain_db=sound.gain_db,
        fade_in_samples=sound.fade_in_samples,
        fade_in_shape=sound.fade_in_shape,
        fade_out_samples=sound.fade_out_samples,
        fade_out_shape=sound.fade_out_shape,
        duck_windows=sound.duck,
        duck_db=sound.duck_db or 0.0,
        duck_ramp_s=timeline.music_duck_ramp_s,
        dip_windows=sound.dips,
        dip_db=timeline.dip_db,
        dip_ramp_s=timeline.dip_ramp_s,
        bump_windows=sound.bumps,
        bump_db=timeline.swell_db,
        bump_ramp_s=timeline.swell_ramp_s,
    )


async def build_lanes(
    storage: Storage,
    timeline: Timeline,
    files: Sequence[tuple[MusicSound, Path, int | None]],
    temp_paths: list[Path],
) -> list[tuple[str, Path]]:
    """One WAV of the story's length for each lane that has a sound among `files` (the beds, the
    score, then the sounds): `(lane, path)`.
    """
    lanes: list[tuple[str, Path]] = []
    for lane in LANES:
        members = [
            _lane_sound(timeline, sound, path, channels)
            for sound, path, channels in files
            if sound.lane == lane
        ]
        if not members:
            continue
        dest = storage.new_temp_path("wav")
        temp_paths.append(dest)
        await run_ffmpeg(
            render_commands.music_lane_args(members, dest, total_samples=timeline.total_samples),
            LANE_TIMEOUT_S,
            f"placing the {lane} music layer",
        )
        lanes.append((lane, dest))
    return lanes


async def mix_sound(
    storage: Storage,
    listing: Path,
    narration: Path | None,
    narration_gain_db: float,
    lanes: Sequence[Path],
    temp_paths: list[Path],
) -> Path:
    """The pre-master: the sound of the joined shots in `listing`, the narration and the lanes in
    one float WAV.
    """
    premaster = storage.new_temp_path("wav")
    temp_paths.append(premaster)
    await run_ffmpeg(
        render_commands.premaster_mix_args(
            listing,
            premaster,
            narration=narration,
            narration_gain_db=narration_gain_db,
            lanes=lanes,
        ),
        PREMASTER_TIMEOUT_S,
        "mixing the sound",
    )
    return premaster


async def measure_master(
    timeline: Timeline, premaster: Path
) -> tuple[render_commands.Normalization | None, ffmpeg.LoudnormMeasure | None]:
    """The first pass of `loudnorm` over the pre-master. The normalization is None when the sound
    is too quiet or too short to measure: it is then left as it is.
    """
    measured = await ffmpeg.measure_loudnorm(
        premaster,
        target_lufs=timeline.master_lufs,
        true_peak_db=timeline.master_true_peak_db,
        lra=timeline.master_lra,
    )
    if measured is None:
        return None, None
    return (
        render_commands.Normalization(
            target_lufs=timeline.master_lufs,
            true_peak_db=timeline.master_true_peak_db,
            lra=timeline.master_lra,
            measured=measured,
        ),
        measured,
    )


def _sound_label(shot: Shot, audio: render_commands.ClipAudio | None) -> str:
    """What a shot's sound was, for the render's record."""
    if shot.voice == story_render_plan.VOICE_TAKE:
        return "dropped (the take is the voice)"
    if shot.voice == story_render_plan.VOICE_CLIP:
        return "clip voice"
    return "clip" if audio is not None else "none in the clip"


def _voice_record(timeline: Timeline, levels: dict[str, VoiceLevel]) -> list[dict[str, Any]] | None:
    """What the render's record says about the voice takes: None when it has none."""
    if timeline.voice is None:
        return None
    return [
        {
            "scene_id": take.scene_id,
            "audio_id": take.audio_id,
            "loudness_lufs": _tenth(levels[take.scene_id].lufs)
            if take.scene_id in levels
            else None,
            "gain_db": _tenth(levels[take.scene_id].gain_db) if take.scene_id in levels else None,
            "pieces": len(take.pieces),
        }
        for take in timeline.voice
    ]


def _music_record(timeline: Timeline, lanes: list[tuple[str, Path]]) -> dict[str, Any] | None:
    """What the render's record says about the music: None when there was none."""
    music = timeline.music
    if music is None:
        return None
    counts = {lane: sum(1 for sound in music.sounds if sound.lane == lane) for lane in LANES}
    return {
        "placement_id": music.placement_id,
        "placement_version": music.placement_version,
        "ambience": music.ambience,
        "sounds": len(music.sounds),
        "left_out": music.left_out,
        "lanes": {lane: counts[lane] for lane, _ in lanes},
    }


def _master_record(
    timeline: Timeline,
    measured: ffmpeg.LoudnormMeasure | None,
    normalized: bool,
    scan: ffmpeg.LoudnessScan | None,
) -> dict[str, Any]:
    """The loudness of the finished sound against its target, with a note for each miss."""
    notes: list[str] = []
    final_lufs = scan.integrated_lufs if scan is not None else None
    final_peak = scan.true_peak_dbtp if scan is not None else None
    if not normalized:
        notes.append(
            "The sound was too quiet or too short to measure, so it was not brought to the "
            "target loudness."
        )
    elif final_lufs is None:
        notes.append("The loudness of the finished video could not be measured.")
    elif abs(final_lufs - timeline.master_lufs) > LOUDNESS_TOLERANCE_LU:
        notes.append(
            f"The finished video measures {final_lufs:.1f} LUFS; the target is "
            f"{timeline.master_lufs:.0f} LUFS."
        )
    if (
        normalized
        and final_peak is not None
        and final_peak > timeline.master_true_peak_db + TRUE_PEAK_TOLERANCE_DB
    ):
        notes.append(
            f"The finished video's true peak is {final_peak:.1f} dBTP; the ceiling is "
            f"{timeline.master_true_peak_db:.0f} dBTP."
        )
    return {
        "target_lufs": timeline.master_lufs,
        "true_peak_db": timeline.master_true_peak_db,
        "premaster_lufs": _tenth(measured.input_i if measured is not None else None),
        "premaster_true_peak_dbtp": _tenth(measured.input_tp if measured is not None else None),
        "normalized": normalized,
        "final_lufs": _tenth(final_lufs),
        "final_true_peak_dbtp": _tenth(final_peak),
        "notes": notes,
    }


def _tenth(value: float | None) -> float | None:
    """A level rounded to 0.1 dB for the render's record."""
    return None if value is None else round(value, 1)


def write_new_file(path: Path, text: str) -> None:
    """Creates a temp file with "xb" (see `services/storage.py`), never over an existing one."""
    with path.open("xb") as file:
        file.write(text.encode("utf-8"))


def _count_by_type(track: callout_render.CalloutTrack) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in track.entries:
        counts[entry.type] = counts.get(entry.type, 0) + 1
    return counts


async def write_subtitles(
    storage: Storage,
    captions: caption_plan.CaptionTrack | None,
    callouts: callout_render.CalloutTrack | None,
    temp_paths: list[Path],
) -> tuple[Path, Path]:
    """Writes the captions and the callouts as one ASS file in the temp folder. Returns the file
    and the folder of the bundled fonts, which is what `final_encode_args` burns in.
    """
    if not FONTS_DIR.is_dir():
        raise RenderFailed("The caption font is missing from this installation.")
    path = storage.new_temp_path("ass")
    temp_paths.append(path)
    await asyncio.to_thread(write_new_file, path, caption_ass.ass_document(captions, callouts))
    return path, FONTS_DIR


async def run_ffmpeg(args: list[str], timeout_s: float, doing: str) -> None:
    """Runs FFmpeg, and turns any failure into a message for the user."""
    try:
        result = await ffmpeg.run_tool("ffmpeg", args, timeout_s=timeout_s)
    except ffmpeg.ToolError as exc:
        raise RenderFailed(f"FFmpeg stopped while {doing}: {exc}") from exc
    if result.returncode != 0:
        tail = result.stderr.decode("utf-8", errors="replace").strip()[-ERROR_TAIL_CHARS:]
        raise RenderFailed(f"FFmpeg failed while {doing}: {tail or 'no error text'}")


async def _check_final(path: Path, timeline: Timeline) -> ffmpeg.VideoProbe:
    """Compares the rendered file with the timeline: the video must be exactly its frames, at
    the output size and fps, and the video and the sound as long as the timeline to within one
    frame.
    """
    probe = await ffmpeg.probe_video(path)
    if probe is None or probe.frame_count is None:
        raise RenderFailed("The rendered video could not be read.")
    if probe.width != timeline.width or probe.height != timeline.height:
        raise RenderFailed(
            f"The rendered video is {probe.width} x {probe.height}; the project's output size "
            f"is {timeline.width} x {timeline.height}."
        )
    if probe.frame_count != timeline.total_frames:
        raise RenderFailed(
            f"The rendered video has {probe.frame_count} frames; the timeline has "
            f"{timeline.total_frames}."
        )
    if probe.fps is None or abs(probe.fps - timeline.fps) > 0.001:
        raise RenderFailed(f"The rendered video is {probe.fps} fps; the project is {timeline.fps}.")
    if probe.audio is None:
        raise RenderFailed("The rendered video has no sound.")

    expected = timeline.total_frames / timeline.fps
    one_frame = 1 / timeline.fps
    lengths = {"video": probe.duration_s, "sound": probe.audio.duration_s}
    for name, length in lengths.items():
        if length is None or abs(length - expected) > one_frame:
            raise RenderFailed(
                f"The rendered {name} lasts {length} s; the timeline lasts {expected:.3f} s."
            )
    return probe
