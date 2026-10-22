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

1. *checking the clips*: every clip and narration speech is read with ffprobe, and each clip must
   have the frames its shot needs, so a bad file is named before any FFmpeg run is spent;
2. *measuring the sound levels*: each clip's sound over the part its shot uses, so every shot can
   be brought to the same loudness (a cut then does not jump);
3. *placing the narration*: one WAV of the whole story's length with every narration speech at its
   own place, and its loudness measured;
4. *trimming shot i of n* (stage 1): each clip becomes a MOV with exactly its frame count, at the
   output size, with its sound at 48 kHz stereo, at its gain and lowered where narration plays;
5. *joining the shots and mixing the sound* (stage 2): the MOVs are joined, the narration is laid
   over their sound, and the final H.264 and AAC file is written;
6. *checking the video*: size, frame count, fps and length are compared with the timeline;
7. *saving the video*: the file is stored, and the `story_render` row and the finished job are
   saved in one transaction.

Every temporary file is removed afterwards, whatever happens (a crash is covered by the clean-up
of the temp folder at start). Logs hold the job id and the step, never a path's content.
"""

from __future__ import annotations

import asyncio
import logging
import time
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
TRIM_TIMEOUT_S: Final = 300.0
JOIN_TIMEOUT_S: Final = 3600.0
# How much of FFmpeg's own error text a failed job shows.
ERROR_TAIL_CHARS: Final = 500

VIDEO_SETTINGS: Final = "libx264 crf 18 preset medium yuv420p"
AUDIO_SETTINGS: Final = "aac 192k 48000 Hz stereo"
_CHANGED_MESSAGE: Final = (
    "This render's timeline is not one this version understands. Render again."
)
_SAMPLES_PER_MS: Final = render_commands.SAMPLE_RATE // 1000


class _RenderFailed(Exception):
    """A failure with a message meant for the user. It fails the job."""


@dataclass(frozen=True)
class _Shot:
    scene_id: str
    scene_index: int
    shot_id: str
    frames: int
    take_id: int
    take_number: int
    path: str
    source_frames: int
    duck: tuple[tuple[float, float], ...]

    @property
    def label(self) -> str:
        return f"{self.shot_id} of scene {self.scene_index}"


@dataclass(frozen=True)
class _Narration:
    unit_id: str
    path: str
    start_ms: int
    seconds: float


@dataclass(frozen=True)
class _Timeline:
    fps: int
    width: int
    height: int
    total_frames: int
    shots: list[_Shot]
    narration: list[_Narration]
    shot_target_lufs: float
    narration_target_lufs: float
    max_boost_db: float
    duck_db: float
    duck_ramp_s: float


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


def parse_timeline(recorded: object) -> _Timeline:
    """Reads `job.input` back into a timeline. Raises `_RenderFailed` for anything the handler
    does not understand, instead of rendering something half right.
    """
    raw = recorded.get("timeline") if isinstance(recorded, dict) else None
    if not isinstance(raw, dict) or raw.get("version") != story_render_plan.TIMELINE_VERSION:
        raise _RenderFailed(_CHANGED_MESSAGE)

    fps, width, height = _whole(raw.get("fps")), _whole(raw.get("width")), _whole(raw.get("height"))
    total = _whole(raw.get("total_frames"))
    entries, speeches, constants = raw.get("shots"), raw.get("narration"), raw.get("constants")
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
    ):
        raise _RenderFailed(_CHANGED_MESSAGE)

    shots: list[_Shot] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise _RenderFailed(_CHANGED_MESSAGE)
        frames, take_id = _whole(entry.get("frames")), _whole(entry.get("take_id"))
        source_frames, number = _whole(entry.get("source_frames")), _whole(entry.get("take_number"))
        index = _whole(entry.get("scene_index"))
        duck = _windows(entry.get("duck"))
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
            or not isinstance(scene_id, str)
            or not isinstance(shot_id, str)
            or not isinstance(path, str)
        ):
            raise _RenderFailed(_CHANGED_MESSAGE)
        shots.append(
            _Shot(scene_id, index, shot_id, frames, take_id, number, path, source_frames, duck)
        )
    if sum(shot.frames for shot in shots) != total:
        raise _RenderFailed(_CHANGED_MESSAGE)

    narration: list[_Narration] = []
    for speech in speeches:
        if not isinstance(speech, dict):
            raise _RenderFailed(_CHANGED_MESSAGE)
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
            raise _RenderFailed(_CHANGED_MESSAGE)
        narration.append(_Narration(unit_id, path, start_ms, seconds))
    narration.sort(key=lambda speech: speech.start_ms)

    values = {
        key: _number(constants.get(key))
        for key in (
            "shot_target_lufs",
            "narration_target_lufs",
            "max_boost_db",
            "duck_db",
            "duck_ramp_s",
        )
    }
    if any(value is None for value in values.values()):
        raise _RenderFailed(_CHANGED_MESSAGE)
    duck_db, ramp = values["duck_db"], values["duck_ramp_s"]
    assert duck_db is not None and ramp is not None  # checked just above
    if duck_db >= 0 or ramp <= 0:
        raise _RenderFailed(_CHANGED_MESSAGE)
    return _Timeline(
        fps=fps,
        width=width,
        height=height,
        total_frames=total,
        shots=shots,
        narration=narration,
        shot_target_lufs=values["shot_target_lufs"] or 0.0,
        narration_target_lufs=values["narration_target_lufs"] or 0.0,
        max_boost_db=values["max_boost_db"] or 0.0,
        duck_db=duck_db,
        duck_ramp_s=ramp,
    )


@dataclass(frozen=True)
class _Source:
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
        except _RenderFailed as exc:
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
        sources, speeches = await _check_sources(storage, timeline)

        await self._phase(job_id, phases.MEASURING_LEVELS)
        shot_lufs = await _measure_shots(timeline, sources)

        # The narration layer, placed on the story's timeline.
        await self._phase(job_id, phases.PLACING_NARRATION)
        narration_path: Path | None = None
        narration_lufs: float | None = None
        narration_gain = 0.0
        if timeline.narration:
            narration_path = storage.new_temp_path("wav")
            temp_paths.append(narration_path)
            slots = [
                render_commands.NarrationInput(
                    path=path,
                    channels=channels,
                    start_sample=speech.start_ms * _SAMPLES_PER_MS,
                    seconds=speech.seconds,
                )
                for speech, (path, channels) in zip(timeline.narration, speeches, strict=True)
            ]
            await _run_ffmpeg(
                render_commands.narration_track_args(
                    slots,
                    narration_path,
                    total_samples=render_commands.sample_count(timeline.total_frames, timeline.fps),
                ),
                NARRATION_TIMEOUT_S,
                "placing the narration",
            )
            # Measured as it sits in the mix: silence between the speeches is not counted.
            narration_lufs = await ffmpeg.measure_loudness(narration_path)
            narration_gain = story_render_plan.gain_toward(
                narration_lufs, timeline.narration_target_lufs, timeline.max_boost_db
            )

        # Stage 1: each clip, trimmed to its shot, at its gain, ducked under the narration.
        started = time.monotonic()
        trimmed: list[Path] = []
        sounds: list[_ShotSound] = []
        for number, shot in enumerate(timeline.shots, start=1):
            await self._phase(job_id, phases.trimming_shot(number, len(timeline.shots)))
            source = sources[number - 1]
            audio = None
            lufs = shot_lufs[number - 1]
            if source.probe.audio is not None:
                gain = story_render_plan.gain_toward(
                    lufs, timeline.shot_target_lufs, timeline.max_boost_db
                )
                audio = render_commands.ClipAudio(
                    channels=source.probe.audio.channels,
                    duration_s=source.probe.audio.duration_s,
                    gain_db=gain,
                    duck_windows=shot.duck,
                    duck_db=timeline.duck_db,
                    duck_ramp_s=timeline.duck_ramp_s,
                )
            sounds.append(
                _ShotSound(
                    label="clip" if audio is not None else "none in the clip",
                    loudness_lufs=lufs,
                    gain_db=None if audio is None else audio.gain_db,
                )
            )
            dest = storage.new_temp_path("mov")
            temp_paths.append(dest)
            await _run_ffmpeg(
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

        # Stage 2: join, lay the narration over, encode.
        await self._phase(job_id, phases.JOINING_STORY)
        started = time.monotonic()
        listing = storage.new_temp_path("txt")
        temp_paths.append(listing)
        await asyncio.to_thread(_write_new_file, listing, render_commands.concat_list(trimmed))
        final = storage.new_temp_path("mp4")
        temp_paths.append(final)
        await _run_ffmpeg(
            render_commands.story_mix_args(
                listing,
                final,
                fps=timeline.fps,
                narration=narration_path,
                narration_gain_db=narration_gain,
            ),
            JOIN_TIMEOUT_S,
            "joining the shots and mixing the sound",
        )
        join_seconds = time.monotonic() - started

        await self._phase(job_id, phases.CHECKING_STORY_VIDEO)
        probe = await _check_final(final, timeline)

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
        timeline: _Timeline,
        sounds: list[_ShotSound],
        narration: tuple[float | None, float | None],
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


async def _check_sources(
    storage: Storage, timeline: _Timeline
) -> tuple[list[_Source], list[tuple[Path, int | None]]]:
    """Reads every clip and every narration speech, and refuses one that cannot be used. Returns
    the clips in the order of the timeline, and the narration files with their channel counts.
    """
    sources: list[_Source] = []
    speeches: list[tuple[Path, int | None]] = []
    try:
        for shot in timeline.shots:
            path = storage.get_path(shot.path)
            probe = await ffmpeg.probe_video(path)
            if probe is None or probe.frame_count is None:
                raise _RenderFailed(
                    f"The clip of shot {shot.label} could not be read. Regenerate it, or use "
                    "another take."
                )
            if probe.frame_count < shot.source_frames:
                raise _RenderFailed(
                    f"The clip of shot {shot.label} has {probe.frame_count} frames; the shot "
                    f"needs {shot.source_frames}. Regenerate it, or use another take."
                )
            sources.append(_Source(path=path, probe=probe))
        for speech in timeline.narration:
            path = storage.get_path(speech.path)
            speech_probe = await ffmpeg.probe(path)
            if speech_probe is None or not speech_probe.audio_streams:
                raise _RenderFailed(
                    f"The speech of the narration {speech.unit_id} could not be read. Make it "
                    "again."
                )
            speeches.append((path, speech_probe.audio_streams[0].channels))
    except StorageError as exc:
        raise _RenderFailed("A file of this render could not be found on disk.") from exc
    return sources, speeches


async def _measure_shots(timeline: _Timeline, sources: list[_Source]) -> list[float | None]:
    """The loudness (LUFS) of each clip's sound over the part its shot uses, in the order of the
    timeline. A clip with no sound is not measured. Every sound is measured after the same
    conversion to stereo the render does, so a mono clip is compared as it will be heard.
    """
    levels: list[float | None] = []
    for shot, source in zip(timeline.shots, sources, strict=True):
        audio = source.probe.audio
        if audio is None:
            levels.append(None)
            continue
        levels.append(
            await ffmpeg.measure_loudness(
                source.path,
                duration_s=shot.frames / timeline.fps,
                pre_filters=render_commands.stereo_filters(audio.channels),
            )
        )
    return levels


def _tenth(value: float | None) -> float | None:
    """A level rounded to 0.1 dB for the render's record."""
    return None if value is None else round(value, 1)


def _write_new_file(path: Path, text: str) -> None:
    """Creates a temp file with "xb" (see `services/storage.py`), never over an existing one."""
    with path.open("xb") as file:
        file.write(text.encode("utf-8"))


async def _run_ffmpeg(args: list[str], timeout_s: float, doing: str) -> None:
    """Runs FFmpeg, and turns any failure into a message for the user."""
    try:
        result = await ffmpeg.run_tool("ffmpeg", args, timeout_s=timeout_s)
    except ffmpeg.ToolError as exc:
        raise _RenderFailed(f"FFmpeg stopped while {doing}: {exc}") from exc
    if result.returncode != 0:
        tail = result.stderr.decode("utf-8", errors="replace").strip()[-ERROR_TAIL_CHARS:]
        raise _RenderFailed(f"FFmpeg failed while {doing}: {tail or 'no error text'}")


async def _check_final(path: Path, timeline: _Timeline) -> ffmpeg.VideoProbe:
    """Compares the rendered file with the timeline: the video must be exactly its frames, at
    the output size and fps, and the video and the sound as long as the timeline to within one
    frame.
    """
    probe = await ffmpeg.probe_video(path)
    if probe is None or probe.frame_count is None:
        raise _RenderFailed("The rendered video could not be read.")
    if probe.width != timeline.width or probe.height != timeline.height:
        raise _RenderFailed(
            f"The rendered video is {probe.width} x {probe.height}; the project's output size "
            f"is {timeline.width} x {timeline.height}."
        )
    if probe.frame_count != timeline.total_frames:
        raise _RenderFailed(
            f"The rendered video has {probe.frame_count} frames; the timeline has "
            f"{timeline.total_frames}."
        )
    if probe.fps is None or abs(probe.fps - timeline.fps) > 0.001:
        raise _RenderFailed(
            f"The rendered video is {probe.fps} fps; the project is {timeline.fps}."
        )
    if probe.audio is None:
        raise _RenderFailed("The rendered video has no sound.")

    expected = timeline.total_frames / timeline.fps
    one_frame = 1 / timeline.fps
    lengths = {"video": probe.duration_s, "sound": probe.audio.duration_s}
    for name, length in lengths.items():
        if length is None or abs(length - expected) > one_frame:
            raise _RenderFailed(
                f"The rendered {name} lasts {length} s; the timeline lasts {expected:.3f} s."
            )
    return probe
