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
   own place, and its loudness measured;
4. *placing the music layers* (MUSIC-012, only with music): the score, the ambience beds and the
   sounds (hits and point sounds), each one WAV of the whole story's length, with every placed
   sound at its own sample, its fades, its ducks under the voice, its dips and its swells;
5. *trimming shot i of n* (stage 1): each clip becomes a MOV with exactly its frame count, at the
   output size, with its sound at 48 kHz stereo, at its gain and lowered where narration plays
   (and under an ambience bed, when that setting is on);
6. *mixing the sound* (stage 2): the shots' sound, the narration and the music layers become one
   float WAV, the pre-master;
7. *measuring the mix*: the first pass of `loudnorm` over the pre-master (MD-19);
8. *joining the shots and encoding the video* (stage 3): the MOVs are joined, the pre-master is
   brought to the target loudness and true-peak ceiling by the second pass of `loudnorm`, and the
   final H.264 and AAC file is written;
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
    ffmpeg,
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
    music: Music | None
    shot_target_lufs: float
    narration_target_lufs: float
    max_boost_db: float
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


_CONSTANT_KEYS: Final = (
    "shot_target_lufs",
    "narration_target_lufs",
    "max_boost_db",
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

    def known(key: str) -> float:
        return values[key] or 0.0

    return Timeline(
        fps=fps,
        width=width,
        height=height,
        total_frames=total,
        shots=shots,
        narration=narration,
        music=music,
        shot_target_lufs=known("shot_target_lufs"),
        narration_target_lufs=known("narration_target_lufs"),
        max_boost_db=known("max_boost_db"),
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
        music_files = (
            [(sound, *await probe_music(storage, sound)) for sound in timeline.music.sounds]
            if timeline.music is not None
            else []
        )

        await self._phase(job_id, phases.MEASURING_LEVELS)
        shot_lufs = [
            await measure_shot(shot, source, timeline.fps)
            for shot, source in zip(timeline.shots, sources, strict=True)
        ]

        # The narration layer, placed on the story's timeline.
        await self._phase(job_id, phases.PLACING_NARRATION)
        narration_path, narration_lufs, narration_gain = await build_narration(
            storage, timeline, speeches, temp_paths
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
            audio = clip_audio(timeline, shot, source, shot_lufs[number - 1])
            sounds.append(
                _ShotSound(
                    label="clip" if audio is not None else "none in the clip",
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

        # Stage 3: join the picture, bring the sound to its target, encode.
        await self._phase(job_id, phases.JOINING_STORY)
        started = time.monotonic()
        final = storage.new_temp_path("mp4")
        temp_paths.append(final)
        await run_ffmpeg(
            render_commands.final_encode_args(
                listing, premaster, final, fps=timeline.fps, norm=norm
            ),
            JOIN_TIMEOUT_S,
            "joining the shots and encoding the video",
        )
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
    timeline: Timeline, shot: Shot, source: Source, lufs: float | None
) -> render_commands.ClipAudio | None:
    """What stage 1 does to a clip's sound, or None for a clip with no sound."""
    audio = source.probe.audio
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
