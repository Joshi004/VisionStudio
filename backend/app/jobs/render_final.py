"""The `render_final` job: the finished video (ANALYSIS.md Section 3.2, 5.5 and 5.6).

It is a local job: everything happens in `start`, in FFmpeg child processes (never in the
event loop), and there is no provider job id. The dispatcher limits it to "maximum parallel
FFmpeg runs", and every FFmpeg run is at low priority (`ffmpeg.run_tool`).

It renders the **timeline stored on the job** (`job.input.timeline`, built at the click by
`services/renders.py`) and nothing else, so what happens to the scenes afterwards does not
matter, and a restart renders the same timeline again from the start (`start_again`).

The steps, which are also the phases the page shows:

1. *checking the clips*: every clip is read with ffprobe and must have the frames its scene
   needs, so a bad file is named before any FFmpeg run is spent on the others. Then, when the
   clip sound volume is above 0, the loudness of the voiceover and of the part of each clip's
   sound its scene uses is measured, so each clip can be set at the same distance under the
   voice (`render_commands.clip_gain_db`);
2. *trimming clip i of n* (stage 1): each clip becomes a MOV with exactly its frame count,
   at the output size, with its sound at 48 kHz stereo, at its gain, or silence;
3. *joining the clips and mixing the sound* (stage 2): the MOVs are joined, the clip sound
   is mixed under the voiceover, and the final H.264 and AAC file is written;
4. *checking the video*: size, frame count, fps and length are compared with the timeline;
5. *saving the video*: the file is stored, and the asset and the finished job are saved in
   one transaction.

Every temporary file is removed afterwards, whatever happens (a crash is covered by the
cleanup of `/data/tmp` at start). Logs hold the job id and the step, never a path's content.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Asset
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.handlers import JobHandler
from app.services import ffmpeg, render_commands, renders
from app.services.assets import add_asset
from app.services.storage import Storage, StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = renders.RENDER_JOB
MAX_PARALLEL_KEY: Final = "max_parallel_ffmpeg"

TRIM_TIMEOUT_S: Final = 300.0
JOIN_TIMEOUT_S: Final = 1800.0
# How much of FFmpeg's own error text a failed job shows.
ERROR_TAIL_CHARS: Final = 500

VIDEO_SETTINGS: Final = "libx264 crf 18 preset medium yuv420p"
AUDIO_SETTINGS: Final = "aac 192k 48000 Hz stereo"
_CHANGED_MESSAGE: Final = (
    "This render's timeline is not one this version understands. Render again."
)


class _RenderFailed(Exception):
    """A failure with a message meant for the user. It fails the job."""


@dataclass(frozen=True)
class _Clip:
    scene_index: int
    frames: int
    asset_id: int
    clip_sound: bool

    @property
    def number(self) -> int:
        return self.scene_index + 1


@dataclass(frozen=True)
class _Timeline:
    fps: int
    width: int
    height: int
    volume: float
    voiceover_id: int
    voiceover_duration_s: float | None
    total_frames: int
    clips: list[_Clip]


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_timeline(recorded: object) -> _Timeline:
    """Reads `job.input` back into a timeline. Raises `_RenderFailed` for anything the
    handler does not understand, instead of rendering something half right.
    """
    raw = recorded.get("timeline") if isinstance(recorded, dict) else None
    if not isinstance(raw, dict) or raw.get("version") != renders.TIMELINE_VERSION:
        raise _RenderFailed(_CHANGED_MESSAGE)

    fps, width, height = _whole(raw.get("fps")), _whole(raw.get("width")), _whole(raw.get("height"))
    total = _whole(raw.get("total_frames"))
    volume = raw.get("clip_sound_volume")
    voiceover = raw.get("voiceover")
    entries = raw.get("clips")
    if (
        fps is None
        or fps < 1
        or width is None
        or width < 2
        or height is None
        or height < 2
        or total is None
        or isinstance(volume, bool)
        or not isinstance(volume, int | float)
        or volume < 0
        or not isinstance(voiceover, dict)
        or _whole(voiceover.get("asset_id")) is None
        or not isinstance(entries, list)
        or not entries
    ):
        raise _RenderFailed(_CHANGED_MESSAGE)

    clips: list[_Clip] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise _RenderFailed(_CHANGED_MESSAGE)
        index, frames, asset_id = (
            _whole(entry.get("scene_index")),
            _whole(entry.get("frames")),
            _whole(entry.get("asset_id")),
        )
        sound = entry.get("clip_sound")
        if index is None or frames is None or frames < 1 or asset_id is None:
            raise _RenderFailed(_CHANGED_MESSAGE)
        clips.append(_Clip(index, frames, asset_id, sound is True))
    if sum(clip.frames for clip in clips) != total:
        raise _RenderFailed(_CHANGED_MESSAGE)

    duration = voiceover.get("duration_s")
    return _Timeline(
        fps=fps,
        width=width,
        height=height,
        volume=float(volume),
        voiceover_id=_whole(voiceover.get("asset_id")) or 0,
        voiceover_duration_s=(
            float(duration)
            if isinstance(duration, int | float) and not isinstance(duration, bool)
            else None
        ),
        total_frames=total,
        clips=clips,
    )


@dataclass(frozen=True)
class _ClipSound:
    """Where a scene's sound in the render came from and what was done to it, for the job's
    output. `loudness_lufs` is None when the clip was not measured (no sound, muted, volume
    0, or too quiet or short to measure), and `gain_db` is None when no gain was applied.
    """

    label: str
    loudness_lufs: float | None
    gain_db: float | None


class RenderFinalHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return await settings_service.get_int(session, MAX_PARALLEL_KEY)

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
        if job is None or job.status != "running":
            return
        timeline = parse_timeline(job.input)

        await self._phase(job_id, phases.CHECKING_CLIPS)
        sources, voiceover_path, voiceover_channels, voiceover_s = await self._check_sources(
            storage, timeline
        )
        voiceover_lufs, clip_lufs = await _measure_levels(
            timeline, sources, voiceover_path, voiceover_channels
        )

        # Stage 1: each clip, trimmed to its scene.
        started = time.monotonic()
        trimmed: list[Path] = []
        sounds: list[_ClipSound] = []
        for number, clip in enumerate(timeline.clips, start=1):
            await self._phase(job_id, phases.trimming(number, len(timeline.clips)))
            source = sources[clip.asset_id]
            audio = None
            if timeline.volume > 0 and clip.clip_sound and source.probe.audio is not None:
                audio = render_commands.ClipAudio(
                    channels=source.probe.audio.channels,
                    duration_s=source.probe.audio.duration_s,
                    gain_db=render_commands.clip_gain_db(
                        timeline.volume, voiceover_lufs, clip_lufs[number - 1]
                    ),
                )
            sounds.append(
                _ClipSound(
                    label=_sound_label(clip, audio, timeline.volume),
                    loudness_lufs=clip_lufs[number - 1],
                    gain_db=None if audio is None else audio.gain_db,
                )
            )
            dest = storage.new_temp_path("mov")
            temp_paths.append(dest)
            await _run_ffmpeg(
                render_commands.trim_args(
                    source.path,
                    dest,
                    frames=clip.frames,
                    fps=timeline.fps,
                    width=timeline.width,
                    height=timeline.height,
                    audio=audio,
                ),
                TRIM_TIMEOUT_S,
                f"trimming the clip of scene {clip.number}",
            )
            trimmed.append(dest)
        trim_seconds = time.monotonic() - started

        # Stage 2: join, mix, encode.
        await self._phase(job_id, phases.JOINING)
        started = time.monotonic()
        listing = storage.new_temp_path("txt")
        temp_paths.append(listing)
        await asyncio.to_thread(_write_new_file, listing, render_commands.concat_list(trimmed))
        final = storage.new_temp_path("mp4")
        temp_paths.append(final)
        await _run_ffmpeg(
            render_commands.join_args(
                listing,
                voiceover_path,
                final,
                fps=timeline.fps,
                voiceover_channels=voiceover_channels,
            ),
            JOIN_TIMEOUT_S,
            "joining the clips and mixing the sound",
        )
        join_seconds = time.monotonic() - started

        await self._phase(job_id, phases.CHECKING_VIDEO)
        probe = await _check_final(final, timeline, voiceover_s)

        await self._phase(job_id, phases.SAVING_VIDEO)
        await self._save(
            job_id,
            job.project_id,
            storage,
            final,
            probe,
            timeline,
            sounds,
            voiceover_lufs,
            (trim_seconds, join_seconds),
        )

    @staticmethod
    async def _check_sources(
        storage: Storage, timeline: _Timeline
    ) -> tuple[dict[int, _Source], Path, int | None, float | None]:
        """Reads the voiceover and every clip, and refuses one that cannot be used."""
        async with SessionLocal() as session:
            assets: dict[int, Asset | None] = {
                asset_id: await session.get(Asset, asset_id)
                for asset_id in {timeline.voiceover_id, *(c.asset_id for c in timeline.clips)}
            }
            await session.commit()

        try:
            voiceover = assets[timeline.voiceover_id]
            if voiceover is None:
                raise _RenderFailed("The voiceover of this project no longer exists.")
            voiceover_path = storage.get_path(voiceover.path)
            voiceover_probe = await ffmpeg.probe(voiceover_path)
            if voiceover_probe is None or not voiceover_probe.audio_streams:
                raise _RenderFailed("The voiceover could not be read.")

            sources: dict[int, _Source] = {}
            for clip in timeline.clips:
                asset = assets[clip.asset_id]
                if asset is None or asset.kind != "clip":
                    raise _RenderFailed(
                        f"The clip of scene {clip.number} no longer exists. Select a take "
                        "and render again."
                    )
                path = storage.get_path(asset.path)
                if clip.asset_id in sources:
                    continue
                probe = await ffmpeg.probe_video(path)
                if probe is None or probe.frame_count is None:
                    raise _RenderFailed(
                        f"The clip of scene {clip.number} could not be read. Regenerate it, "
                        "or use another take."
                    )
                if probe.frame_count < clip.frames:
                    raise _RenderFailed(
                        f"The clip of scene {clip.number} has {probe.frame_count} frames; the "
                        f"scene needs {clip.frames}. Regenerate it, or use another take."
                    )
                sources[clip.asset_id] = _Source(path=path, probe=probe)
        except StorageError as exc:
            raise _RenderFailed("A file of this render could not be found on disk.") from exc

        duration = voiceover_probe.duration_s or timeline.voiceover_duration_s
        return (
            sources,
            voiceover_path,
            voiceover_probe.audio_streams[0].channels,
            duration,
        )

    @staticmethod
    async def _save(
        job_id: int,
        project_id: int,
        storage: Storage,
        final: Path,
        probe: ffmpeg.VideoProbe,
        timeline: _Timeline,
        sounds: list[_ClipSound],
        voiceover_lufs: float | None,
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
            "voiceover_loudness_lufs": _tenth(voiceover_lufs),
            "clips": [
                {
                    "scene_index": clip.scene_index,
                    "sound": sound.label,
                    "loudness_lufs": _tenth(sound.loudness_lufs),
                    "gain_db": _tenth(sound.gain_db),
                }
                for clip, sound in zip(timeline.clips, sounds, strict=True)
            ],
            "seconds": {"trim": round(seconds[0], 1), "join": round(seconds[1], 1)},
        }
        provenance: dict[str, Any] = {
            "job_id": job_id,
            "timeline_version": renders.TIMELINE_VERSION,
            "voiceover_asset_id": timeline.voiceover_id,
            "clip_asset_ids": [clip.asset_id for clip in timeline.clips],
            "clip_sound_volume": timeline.volume,
            "clip_sound_level": "share of the voiceover's measured loudness",
            "voiceover_loudness_lufs": _tenth(voiceover_lufs),
            "muted_scene_indexes": [c.scene_index for c in timeline.clips if not c.clip_sound],
            "fps": timeline.fps,
            "frame_count": probe.frame_count,
            "ffmpeg_version": await ffmpeg.tool_version("ffmpeg"),
            "video": VIDEO_SETTINGS,
            "audio": AUDIO_SETTINGS,
        }

        # The video, the finished job and nothing else: saved together or not at all.
        async with SessionLocal() as session:
            asset = await add_asset(
                session,
                project_id=project_id,
                kind="final",
                stored=stored,
                mime="video/mp4",
                size_bytes=temp.size_bytes,
                sha256=temp.sha256,
                source="derived",
                duration_s=probe.duration_s,
                width=probe.width,
                height=probe.height,
                provenance=provenance,
            )
            if not await store.finish_job(session, job_id, output, result_asset_id=asset.id):
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
            "job %d: video stored: asset=%d frames=%s %sx%s %.2f s, trim %.1f s, join %.1f s",
            job_id,
            asset.id,
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


@dataclass(frozen=True)
class _Source:
    path: Path
    probe: ffmpeg.VideoProbe


def _sound_label(clip: _Clip, audio: render_commands.ClipAudio | None, volume: float) -> str:
    """Where a scene's sound in the render came from, for the job's output."""
    if audio is not None:
        return "clip"
    if not clip.clip_sound:
        return "muted"
    return "off (volume 0)" if volume <= 0 else "none in the clip"


def _tenth(value: float | None) -> float | None:
    """A level rounded to 0.1 dB for the job's output."""
    return None if value is None else round(value, 1)


async def _measure_levels(
    timeline: _Timeline,
    sources: dict[int, _Source],
    voiceover_path: Path,
    voiceover_channels: int | None,
) -> tuple[float | None, list[float | None]]:
    """The loudness (LUFS) of the voiceover, and of each clip's sound over the part its
    scene uses (in the order of the timeline). Nothing is measured when the clip sound
    volume is 0, and a clip with no sound, or whose switch is off, is not measured either.

    Every sound is measured after the same conversion to stereo the render does, because
    that is how the mix hears it: a mono voiceover on two channels is 3 dB louder than the
    file measures, and comparing it as mono would put the clips 3 dB too far under it.

    A level that cannot be measured is None, and the clip then gets the plain volume
    (`render_commands.clip_gain_db`). With no voiceover level, no clip is measured: it
    would not be used.
    """
    levels: list[float | None] = [None] * len(timeline.clips)
    if timeline.volume <= 0:
        return None, levels
    voiceover_lufs = await ffmpeg.measure_loudness(
        voiceover_path, pre_filters=render_commands.stereo_filters(voiceover_channels)
    )
    if voiceover_lufs is None:
        return None, levels
    for position, clip in enumerate(timeline.clips):
        audio = sources[clip.asset_id].probe.audio
        if clip.clip_sound and audio is not None:
            levels[position] = await ffmpeg.measure_loudness(
                sources[clip.asset_id].path,
                duration_s=clip.frames / timeline.fps,
                pre_filters=render_commands.stereo_filters(audio.channels),
            )
    return voiceover_lufs, levels


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


async def _check_final(
    path: Path, timeline: _Timeline, voiceover_s: float | None
) -> ffmpeg.VideoProbe:
    """Compares the rendered file with the timeline: the video must be exactly its frames,
    at the output size and fps, and the video and the sound as long as the voiceover to
    within one frame (ANALYSIS.md Section 5.5).
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

    if voiceover_s is not None:
        one_frame = 1 / timeline.fps
        lengths = {"video": probe.duration_s, "sound": probe.audio.duration_s}
        for name, length in lengths.items():
            if length is None or abs(length - voiceover_s) > one_frame:
                raise _RenderFailed(
                    f"The rendered {name} lasts {length} s; the voiceover lasts "
                    f"{voiceover_s:.3f} s."
                )
    return probe
