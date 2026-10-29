"""The `preview_music_mix` job: hear the music in context (MUSIC-012, MD-20).

A local job, like `render_story` (its own pool, so one preview at a time; FFmpeg only; a restart
makes the preview again from the start). It makes a sound-only AAC file of one window of the story
(a scene, or a cue with two seconds around it) with the render's own mix:

1. `services/music_preview.build` gives the render's timeline (version 2, with the music and the
   settings as they are now) and the window. With a take that is not selected, the placer has run
   again with that take (no model is asked);
2. the layers are made with the render's functions (`jobs/render_story.py`): the narration (all
   of it, so its level is the render's), the music lanes (only the sounds the window touches) and
   the sound of each shot the window touches; the other shots are silence;
3. the pre-master is mixed and cut to the window, brought to the target loudness with the same two
   passes of `loudnorm` as the render (over the window, so its level is close to, not the same
   as, in the full render), and encoded;
4. the file is stored, and the job is finished with its place and length.

Every temporary file is removed afterwards. Logs hold the job id, never the story.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Final

from app.db.models import Project
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.handlers import JobHandler
from app.jobs.render_story import (
    PREMASTER_TIMEOUT_S,
    TRIM_TIMEOUT_S,
    RenderFailed,
    Timeline,
    VoiceLevel,
    build_lanes,
    build_narration,
    build_voice,
    clip_audio,
    measure_master,
    measure_shot,
    mix_sound,
    parse_timeline,
    probe_music,
    probe_shot,
    probe_speech,
    probe_take,
    run_ffmpeg,
    voice_matches,
    write_new_file,
)
from app.services import ffmpeg, music_preview, render_commands, story_render_plan
from app.services.storage import Storage, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = music_preview.JOB_TYPE
ENCODE_TIMEOUT_S: Final = 600.0
# The file may differ from the window by the encoder's own padding.
LENGTH_TOLERANCE_S: Final = 0.25
_NO_PROJECT = "The project of this job no longer exists."


class PreviewMusicMixHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def start(self, job_id: int) -> None:
        storage = get_storage()
        temp_paths: list[Path] = []
        try:
            await self._preview(job_id, storage, temp_paths)
        except (RenderFailed, music_preview.MusicPreviewError) as exc:
            async with SessionLocal() as session:
                await store.fail_job(session, job_id, str(exc))
        finally:
            for path in temp_paths:
                storage.discard(path)

    async def _preview(self, job_id: int, storage: Storage, temp_paths: list[Path]) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            await session.commit()
        if job is None or job.status != "running":
            return
        if job.project_id is None:
            raise RenderFailed(_NO_PROJECT)
        project_id = job.project_id
        target = music_preview.Target.of_input(job.input)

        await self._phase(job_id, phases.PREPARING_PREVIEW)
        async with SessionLocal() as session:
            project = await session.get(Project, project_id)
            if project is None:
                raise RenderFailed(_NO_PROJECT)
            built = await music_preview.build(session, project, target)
            await session.commit()
        timeline = parse_timeline({"timeline": built.timeline})
        window = (built.start_sample, built.end_sample)

        await self._phase(job_id, phases.CHECKING_RENDER_CLIPS)
        starts = _shot_starts(timeline)
        wanted = [
            number
            for number, shot in enumerate(timeline.shots)
            if _touches(starts[number], timeline.fps, shot.frames, window)
        ]
        sources = {number: await probe_shot(storage, timeline.shots[number]) for number in wanted}
        speeches = [(speech, *await probe_speech(storage, speech)) for speech in timeline.narration]
        take_files = [(take, *await probe_take(storage, take)) for take in timeline.voice or []]
        music_files = (
            [
                (sound, *await probe_music(storage, sound))
                for sound in timeline.music.sounds
                if sound.start_sample < window[1]
                and sound.start_sample + sound.length_samples > window[0]
            ]
            if timeline.music is not None
            else []
        )

        await self._phase(job_id, phases.MEASURING_LEVELS)
        lufs = {
            number: (
                None
                if timeline.shots[number].voice == story_render_plan.VOICE_TAKE
                else await measure_shot(timeline.shots[number], source, timeline.fps)
            )
            for number, source in sources.items()
        }

        # The narration, or the voice takes of a continuous explainer (FLOW-008): all of it, so
        # its level is the render's.
        voice_levels: dict[str, VoiceLevel] = {}
        if timeline.voice is None:
            await self._phase(job_id, phases.PLACING_NARRATION)
            narration_path, _lufs, narration_gain = await build_narration(
                storage, timeline, speeches, temp_paths
            )
        else:
            await self._phase(job_id, phases.PLACING_VOICE)
            narration_path, voice_levels = await build_voice(
                storage, timeline, take_files, temp_paths
            )
            narration_gain = 0.0
        matches = await voice_matches(timeline, take_files, voice_levels, sorted(sources))

        lanes: list[tuple[str, Path]] = []
        if music_files:
            await self._phase(job_id, phases.PLACING_MUSIC_LAYERS)
            lanes = await build_lanes(storage, timeline, music_files, temp_paths)

        shot_sounds: list[Path] = []
        for number, shot in enumerate(timeline.shots):
            await self._phase(job_id, phases.trimming_shot(number + 1, len(timeline.shots)))
            dest = storage.new_temp_path("wav")
            temp_paths.append(dest)
            if number in sources:
                audio = clip_audio(
                    timeline, shot, sources[number], lufs[number], matches.get(number)
                )
                args = render_commands.shot_audio_args(
                    sources[number].path, dest, frames=shot.frames, fps=timeline.fps, audio=audio
                )
            else:
                args = render_commands.silence_args(
                    dest, samples=render_commands.sample_count(shot.frames, timeline.fps)
                )
            await run_ffmpeg(args, TRIM_TIMEOUT_S, f"making the sound of shot {shot.label}")
            shot_sounds.append(dest)

        await self._phase(job_id, phases.MIXING_SOUND)
        listing = storage.new_temp_path("txt")
        temp_paths.append(listing)
        await asyncio.to_thread(write_new_file, listing, render_commands.concat_list(shot_sounds))
        premaster = await mix_sound(
            storage,
            listing,
            narration_path,
            narration_gain,
            [path for _, path in lanes],
            temp_paths,
        )
        cut = storage.new_temp_path("wav")
        temp_paths.append(cut)
        await run_ffmpeg(
            render_commands.window_args(
                premaster, cut, start_sample=window[0], end_sample=window[1]
            ),
            PREMASTER_TIMEOUT_S,
            "cutting the preview's window",
        )

        await self._phase(job_id, phases.MEASURING_MIX)
        norm, _measured = await measure_master(timeline, cut)
        final = storage.new_temp_path("m4a")
        temp_paths.append(final)
        await run_ffmpeg(
            render_commands.audio_encode_args(cut, final, norm=norm),
            ENCODE_TIMEOUT_S,
            "encoding the preview",
        )
        duration = await _check_length(final, window)

        await self._phase(job_id, phases.SAVING_PREVIEW)
        await self._save(job_id, project_id, storage, final, duration, window, timeline, lanes)

    @staticmethod
    async def _save(
        job_id: int,
        project_id: int,
        storage: Storage,
        final: Path,
        duration: float,
        window: tuple[int, int],
        timeline: Timeline,
        lanes: list[tuple[str, Path]],
    ) -> None:
        temp = await storage.describe_temp(final)
        stored = await storage.save(temp, project_id, "m4a")
        rate = render_commands.SAMPLE_RATE
        output: dict[str, Any] = {
            "file": {
                "path": stored.relative_path,
                "size_bytes": temp.size_bytes,
                "sha256": temp.sha256,
                "duration_s": duration,
            },
            "window": {"start_s": window[0] / rate, "end_s": window[1] / rate},
            "lanes": [lane for lane, _ in lanes],
            "ambience": timeline.music.ambience if timeline.music is not None else None,
        }
        async with SessionLocal() as session:
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                # Stored files are never deleted.
                _logger.warning(
                    "job %d: preview stored but the job is no longer running: %s",
                    job_id,
                    stored.relative_path,
                )
                return
            await session.commit()
        _logger.info("job %d: music preview stored (%.1f s)", job_id, duration)

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")


def _shot_starts(timeline: Timeline) -> list[int]:
    """The frame each shot starts on, in order."""
    starts: list[int] = []
    cursor = 0
    for shot in timeline.shots:
        starts.append(cursor)
        cursor += shot.frames
    return starts


def _touches(start_frame: int, fps: int, frames: int, window: tuple[int, int]) -> bool:
    """Whether a shot's span overlaps the window (in samples)."""
    start = render_commands.sample_count(start_frame, fps)
    end = render_commands.sample_count(start_frame + frames, fps)
    return start < window[1] and end > window[0]


async def _check_length(path: Path, window: tuple[int, int]) -> float:
    """The preview's length in seconds: the window's, to within the encoder's padding."""
    probed = await ffmpeg.probe(path)
    duration = probed.audio_streams[0].duration_s if probed and probed.audio_streams else None
    if duration is None:
        raise RenderFailed("The preview could not be read.")
    expected = (window[1] - window[0]) / render_commands.SAMPLE_RATE
    if abs(duration - expected) > LENGTH_TOLERANCE_S:
        raise RenderFailed(f"The preview lasts {duration:.2f} s; its window is {expected:.2f} s.")
    return duration
