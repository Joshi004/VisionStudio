"""The `render_av_test` job: the two videos of an Audio video test (AVLAB).

A local job, like `preview_music_mix` (FFmpeg only; nothing is paid for and no model is asked; a
restart makes the videos again from the start):

1. `av_lab.render_sources` gives the files and the place of each part, and
   `av_lab_render.layout` lays them out in whole frames;
2. the picture is made once: the still of the first frame in the gaps, each clip inside its part;
3. the **mixed** video takes the speech in the gaps and each clip's own sound inside its part,
   the **TTS only** video takes the speech from 0 to the end; both reuse the picture as it is;
4. each file is checked (the frames of the timeline, a sound track), both are stored and the job
   is finished with them in one transaction.

Every temporary file is removed afterwards. Logs hold the job id, never the text.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.handlers import JobHandler
from app.jobs.render_story import RenderFailed, run_ffmpeg
from app.services import av_lab, av_lab_render, ffmpeg
from app.services.storage import Storage, StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = av_lab.RENDER_JOB
PICTURE_TIMEOUT_S: Final = 900.0
MUX_TIMEOUT_S: Final = 300.0


class RenderAvTestHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def start(self, job_id: int) -> None:
        storage = get_storage()
        temp_paths: list[Path] = []
        try:
            await self._render(job_id, storage, temp_paths)
        except (RenderFailed, av_lab.AvLabError, av_lab_render.RenderLayoutError) as exc:
            async with SessionLocal() as session:
                await store.fail_job(session, job_id, str(exc))
        except StorageError as exc:
            async with SessionLocal() as session:
                await store.fail_job(session, job_id, f"A file could not be stored: {exc}")
        finally:
            for path in temp_paths:
                storage.discard(path)

    async def _render(self, job_id: int, storage: Storage, temp_paths: list[Path]) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            await session.commit()
        if job is None or job.status != "running":
            return
        recorded = job.input if isinstance(job.input, dict) else {}
        test_id = recorded.get(av_lab.DEDUPE_KEY)
        if not isinstance(test_id, int):
            raise RenderFailed("The job names no test.")

        await self._phase(job_id, phases.PREPARING_AV_TEST)
        async with SessionLocal() as session:
            sources = await av_lab.render_sources(session, test_id)
            await session.commit()
        for path in (sources.still, sources.speech, *(part.clip for part in sources.parts)):
            if not path.is_file():
                raise RenderFailed("A file of the test could not be found on disk.")
        total_frames, pieces = av_lab_render.layout(
            [(part.start_s, part.end_s) for part in sources.parts], sources.speech_duration_s
        )
        clips = [part.clip for part in sources.parts]

        await self._phase(job_id, phases.RENDERING_AV_PICTURE)
        picture = storage.new_temp_path("mp4")
        temp_paths.append(picture)
        await run_ffmpeg(
            av_lab_render.video_args(
                sources.still,
                clips,
                pieces,
                picture,
                total_frames=total_frames,
                width=sources.width,
                height=sources.height,
            ),
            PICTURE_TIMEOUT_S,
            "making the picture",
        )

        await self._phase(job_id, phases.MIXING_AV_CLIP_SOUND)
        mixed = storage.new_temp_path("mp4")
        temp_paths.append(mixed)
        await run_ffmpeg(
            av_lab_render.mixed_args(
                picture,
                sources.speech,
                clips,
                [part.has_audio for part in sources.parts],
                pieces,
                mixed,
            ),
            MUX_TIMEOUT_S,
            "adding the speech and the clips' sound",
        )

        await self._phase(job_id, phases.MIXING_AV_TTS_SOUND)
        tts = storage.new_temp_path("mp4")
        temp_paths.append(tts)
        await run_ffmpeg(
            av_lab_render.tts_args(picture, sources.speech, tts, total_frames=total_frames),
            MUX_TIMEOUT_S,
            "adding the speech alone",
        )
        await _check(mixed, total_frames, "mixed")
        await _check(tts, total_frames, "TTS only")

        await self._phase(job_id, phases.SAVING_AV_VIDEOS)
        info: dict[str, Any] = {
            "fps": av_lab_render.FPS,
            "frames": total_frames,
            "duration_s": total_frames / av_lab_render.FPS,
            "width": sources.width,
            "height": sources.height,
            "pieces": [
                {
                    "kind": piece.kind,
                    "start_frame": piece.start_frame,
                    "end_frame": piece.end_frame,
                    "part": None if piece.part is None else piece.part + 1,
                }
                for piece in pieces
            ],
            "clips_without_sound": [
                number for number, part in enumerate(sources.parts, start=1) if not part.has_audio
            ],
        }
        await self._save(job_id, test_id, storage, mixed, tts, info)

    @staticmethod
    async def _save(
        job_id: int,
        test_id: int,
        storage: Storage,
        mixed: Path,
        tts: Path,
        info: dict[str, Any],
    ) -> None:
        mixed_temp = await storage.describe_temp(mixed)
        tts_temp = await storage.describe_temp(tts)
        mixed_stored = await storage.save_lab(mixed_temp, "mp4")
        tts_stored = await storage.save_lab(tts_temp, "mp4")
        output: dict[str, Any] = {
            "test_id": test_id,
            "mixed": {"path": mixed_stored.relative_path, "size_bytes": mixed_temp.size_bytes},
            "tts_only": {"path": tts_stored.relative_path, "size_bytes": tts_temp.size_bytes},
            **info,
        }
        # The videos on the test and the finished job are saved together or not at all.
        async with SessionLocal() as session:
            kept = await av_lab.store_render(
                session, test_id, mixed_stored.relative_path, tts_stored.relative_path, info
            )
            if not kept or not await store.finish_job(session, job_id, output):
                await session.rollback()
                # Stored files are never deleted.
                _logger.warning(
                    "job %d: videos stored but the test or the job is gone: %s, %s",
                    job_id,
                    mixed_stored.relative_path,
                    tts_stored.relative_path,
                )
                return
            await session.commit()
        _logger.info("job %d: test %d rendered (%d frames)", job_id, test_id, info["frames"])

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")


async def _check(path: Path, total_frames: int, name: str) -> None:
    """The rendered file must be exactly the timeline's frames and carry a sound track."""
    probe = await ffmpeg.probe_video(path)
    if probe is None or probe.frame_count is None:
        raise RenderFailed(f"The {name} video could not be read.")
    if probe.frame_count != total_frames:
        raise RenderFailed(
            f"The {name} video has {probe.frame_count} frames; it should have {total_frames}."
        )
    if probe.audio is None:
        raise RenderFailed(f"The {name} video has no sound track.")
