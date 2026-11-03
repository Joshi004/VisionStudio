"""The `render_lab_graphic` job: the video of one Graphics lab render (GFX-005, §4.7).

One job type makes every engine's video, and the test card of the Graphics tab:

1. It sends the work to the engine's renderer: the motion service for the three Remotion engines
   (and the test card), or the Python renderer for `python_templates` (GFX-008,
   `services/graphics_python`, set as `graphics_render.python_renderer` below).
2. It downloads the file and checks it with `ffprobe`: the exact frame count, the size, 24 frames
   a second, H.264 and `yuv420p`. A check that fails is a warning on the render, not a failure, so
   the trial can count it (§4.9). A file that cannot be read at all fails the job.
3. When the run has a voice, it adds it with FFmpeg, copying the video stream and cutting the
   speech to the video's length. Every engine gets the same audio. Without a voice there is no
   audio track.
4. It stores the video as lab media and records the metrics.

The input is `{requested: "lab_graphic_render", render_id}` for a render of a run, or
`{requested: "lab_graphic_test_card", orientation, frames}` for the test card, which belongs to no
run: its result (the stored file and the metrics) is the job's `output`, and a newer test card
replaces the files of the older ones (`graphics_lab.prune_test_cards`).

A local job: nothing is paid for and no model is asked. A restart makes the video again from the
start. Logs hold the job id, never the line.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import PIL
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import LabGraphicRender, LabGraphicRun
from app.db.session import SessionLocal
from app.jobs import phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.jobs.render_story import RenderFailed, run_ffmpeg
from app.providers import motion_renderer
from app.services import av_lab_render, ffmpeg, graphics_lab, graphics_python, graphics_render
from app.services.ffmpeg import VideoProbe
from app.services.storage import Storage, StorageError, get_storage

_logger = logging.getLogger(__name__)

# The Python renderer of `python_templates` (GFX-008). The hook is set here, its only reader,
# because `graphics_python` imports `graphics_render` and the other way round would be a cycle.
graphics_render.python_renderer = graphics_python.render

JOB_TYPE: Final = "render_lab_graphic"
POLL_INTERVAL_S: Final = 1.0
# The phase is rewritten every this many percent, not on every poll.
PHASE_PERCENT_STEP: Final = 5
MUX_TIMEOUT_S: Final = 300.0


class RenderLabGraphicHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return await settings_service.get_int(session, settings_service.GRAPHICS_MAX_RENDERS_KEY)

    async def start(self, job_id: int) -> None:
        storage = get_storage()
        temp_paths: list[Path] = []
        render_id: int | None = None
        try:
            async with SessionLocal() as session:
                job = await store.get_job(session, job_id)
                await session.commit()
            if job is None or job.status != "running":
                return
            recorded = job.input if isinstance(job.input, dict) else {}
            value = recorded.get(graphics_render.RENDER_DEDUPE_KEY)
            render_id = value if isinstance(value, int) else None
            await self._render(job_id, recorded, storage, temp_paths)
        except (
            RenderFailed,
            motion_renderer.MotionServiceError,
            graphics_lab.GraphicsLabInputError,
        ) as exc:
            await _fail(job_id, render_id, str(exc))
        except StorageError as exc:
            await _fail(job_id, render_id, f"A file could not be stored: {exc}")
        finally:
            for path in temp_paths:
                storage.discard(path)

    async def _render(
        self, job_id: int, recorded: dict[str, Any], storage: Storage, temp_paths: list[Path]
    ) -> None:
        started = time.monotonic()
        plan = await _plan(recorded)

        # The service's versions go with the metrics, and an unreachable service is reported
        # now, before anything else is done.
        base_url = ""
        versions: dict[str, Any] = {}
        if plan.engine != graphics_render.PYTHON_ENGINE:
            async with SessionLocal() as session:
                base_url = await settings_service.get_str(session, settings_service.MOTION_URL_KEY)
            health = await motion_renderer.health(base_url)
            versions = {"remotion": health.get("remotion"), "chrome": health.get("chrome")}
        else:
            versions = {"pillow": PIL.__version__}

        video = storage.new_temp_path("mp4")
        temp_paths.append(video)
        body = graphics_render.render_body(
            plan.engine,
            width=plan.width,
            height=plan.height,
            fps=plan.fps,
            frames=plan.frames,
            resolved=plan.resolved,
            input=plan.input,
            code=plan.code,
        )
        if plan.engine == graphics_render.PYTHON_ENGINE:
            render_s = await self._draw_in_python(job_id, body, video)
        else:
            render_s = await self._draw_in_motion(job_id, base_url, body, video)

        await phase_writer.note(job_id, phases.CHECKING_GRAPHIC)
        probe = await ffmpeg.probe_video(video)
        if probe is None or probe.frame_count is None:
            raise RenderFailed("The rendered video could not be read.")
        checks, warnings = graphics_render.check_probe(
            probe, width=plan.width, height=plan.height, fps=plan.fps, frames=plan.frames
        )

        final = video
        if plan.voice_path is not None:
            await phase_writer.note(job_id, phases.ADDING_GRAPHIC_VOICE)
            final = storage.new_temp_path("mp4")
            temp_paths.append(final)
            await run_ffmpeg(
                av_lab_render.tts_args(
                    video,
                    storage.get_path(plan.voice_path),
                    final,
                    total_frames=plan.frames,
                ),
                MUX_TIMEOUT_S,
                "adding the voice",
            )
            await _check_voiced(final, probe, plan.frames)

        await phase_writer.note(job_id, phases.SAVING_GRAPHIC)
        temp = await storage.describe_temp(final)
        stored = await storage.save_lab(temp, "mp4")
        metrics: dict[str, Any] = {
            "engine": plan.engine,
            "composition": graphics_render.COMPOSITION_OF.get(plan.engine, "python"),
            "render_s": render_s,
            "job_s": round(time.monotonic() - started, 3),
            "size_bytes": temp.size_bytes,
            "frames": probe.frame_count,
            "width": probe.width,
            "height": probe.height,
            "fps": probe.fps,
            "codec": probe.codec_name,
            "pix_fmt": probe.pix_fmt,
            "checks": checks,
            "timing_source": plan.timing_source,
            "voice": plan.voice_path is not None,
            "encoding": dict(graphics_render.ENCODING),
            "versions": versions,
        }
        await _save(job_id, plan, stored.relative_path, metrics, warnings)

    async def _draw_in_motion(
        self, job_id: int, base_url: str, body: dict[str, Any], dest: Path
    ) -> float | None:
        """Has the motion service draw the video and downloads it to `dest`. Returns the
        service's own render time in seconds.
        """
        await phase_writer.note(job_id, phases.SENDING_GRAPHIC)
        service_id = await motion_renderer.start_render(base_url, body)
        try:
            status = await _wait_for_service(job_id, base_url, service_id)
            await phase_writer.note(job_id, phases.DOWNLOADING_GRAPHIC)
            await motion_renderer.download_render(base_url, service_id, dest)
        finally:
            await motion_renderer.delete_render(base_url, service_id)
        seconds = status.get("render_s")
        return float(seconds) if isinstance(seconds, int | float) else None

    async def _draw_in_python(self, job_id: int, body: dict[str, Any], dest: Path) -> float:
        """Has the Python renderer (GFX-008) draw the video into `dest`. Returns the seconds."""
        renderer = graphics_render.python_renderer
        if renderer is None:
            raise RenderFailed("The Python renderer is not built yet (GFX-008).")
        await phase_writer.note(job_id, phases.DRAWING_GRAPHIC_IN_PYTHON)
        started = time.monotonic()
        try:
            await renderer(body, dest)
        except graphics_render.PythonRenderFailed as exc:
            raise RenderFailed(str(exc)) from exc
        return round(time.monotonic() - started, 3)


@dataclass(frozen=True)
class _Plan:
    """What one job renders: the engine, the size, the resolved brief and where it goes."""

    engine: str
    width: int
    height: int
    fps: int
    frames: int
    resolved: dict[str, Any]
    input: Any
    code: str | None
    voice_path: str | None
    timing_source: str | None
    # The render row of a run, or None for the test card (then `orientation` is set).
    render_id: int | None
    orientation: str | None


async def _plan(recorded: dict[str, Any]) -> _Plan:
    """Reads what the job renders: a render row of a run, or the test card. Raises RenderFailed."""
    if recorded.get("requested") == graphics_render.REQUESTED_TEST_CARD:
        orientation = recorded.get("orientation")
        frames = recorded.get("frames")
        if not isinstance(orientation, str) or not isinstance(frames, int):
            raise RenderFailed("The job names no orientation or length.")
        width, height = graphics_render.card_size(orientation)
        resolved = graphics_render.card_resolved(
            width, height, graphics_lab.FPS, frames, graphics_lab.FONTS
        )
        return _Plan(
            engine=graphics_render.TEST_CARD_ENGINE,
            width=width,
            height=height,
            fps=graphics_lab.FPS,
            frames=frames,
            resolved=resolved,
            input=None,
            code=None,
            voice_path=None,
            timing_source=None,
            render_id=None,
            orientation=orientation,
        )

    render_id = recorded.get(graphics_render.RENDER_DEDUPE_KEY)
    if not isinstance(render_id, int):
        raise RenderFailed("The job names no render.")
    async with SessionLocal() as session:
        render = await session.get(LabGraphicRender, render_id)
        run = await session.get(LabGraphicRun, render.run_id) if render is not None else None
        if render is None or run is None:
            raise RenderFailed("The render this job was made for is gone.")
        resolved = run.resolved
        if not isinstance(resolved, dict):
            raise RenderFailed("The run has no resolved brief to draw from. Write the brief first.")
        voice_path = await graphics_lab.voice_audio_of(session, run)
        if run.speech_run_id is not None and voice_path is None:
            raise RenderFailed("The run's speech has no file, so the voice cannot be added.")
        plan = _Plan(
            engine=render.engine,
            width=int(resolved["width"]),
            height=int(resolved["height"]),
            fps=int(resolved["fps"]),
            frames=int(resolved["frames"]),
            resolved=resolved,
            input=render.input,
            code=graphics_render.code_of(render.input),
            voice_path=voice_path,
            timing_source=resolved.get("timing_source"),
            render_id=render_id,
            orientation=run.orientation,
        )
        await session.commit()
    return plan


async def _wait_for_service(job_id: int, base_url: str, service_id: str) -> dict[str, Any]:
    """Polls the motion service until the render is done, writing its progress as the job's
    phase. Raises RenderFailed when the service says it failed or does not finish in time.
    """
    limit_s = graphics_render.RENDER_TIME_LIMIT_S + graphics_render.BACKEND_EXTRA_WAIT_S
    deadline = time.monotonic() + limit_s
    shown = -PHASE_PERCENT_STEP
    while True:
        status = await motion_renderer.render_status(base_url, service_id)
        state = status.get("state")
        if state == "done":
            return status
        if state == "failed":
            reason = status.get("error")
            raise RenderFailed(
                f"The motion service could not render the graphic: "
                f"{reason if isinstance(reason, str) and reason else 'no reason given'}"
            )
        if time.monotonic() > deadline:
            raise RenderFailed(f"The motion service did not finish within {limit_s} s.")
        progress = status.get("progress")
        percent = int(float(progress) * 100) if isinstance(progress, int | float) else 0
        if percent - shown >= PHASE_PERCENT_STEP:
            shown = percent
            await phase_writer.note(job_id, phases.rendering_graphic(percent))
        await asyncio.sleep(POLL_INTERVAL_S)


async def _check_voiced(path: Path, silent: VideoProbe, frames: int) -> None:
    """The video with the voice must have a sound track and still be exactly the same frames."""
    probe = await ffmpeg.probe_video(path)
    if probe is None or probe.frame_count is None:
        raise RenderFailed("The video with the voice could not be read.")
    if probe.frame_count != silent.frame_count:
        raise RenderFailed(
            f"Adding the voice changed the video from {silent.frame_count} to "
            f"{probe.frame_count} frames."
        )
    if probe.audio is None:
        raise RenderFailed("The video has no sound track after the voice was added.")
    expected = frames / graphics_lab.FPS
    length = probe.audio.duration_s
    if length is None or abs(length - expected) > 1 / graphics_lab.FPS:
        raise RenderFailed(
            f"The voice lasts {length} s in the video; the graphic lasts {expected:.3f} s."
        )


async def _save(
    job_id: int,
    plan: _Plan,
    path: str,
    metrics: dict[str, Any],
    warnings: list[str],
) -> None:
    """Saves the video and finishes the job in one transaction."""
    async with SessionLocal() as session:
        output: dict[str, Any] = {
            "path": path,
            "size_bytes": metrics["size_bytes"],
            "metrics": metrics,
            "warnings": warnings,
        }
        if plan.render_id is not None:
            render = await session.get(LabGraphicRender, plan.render_id)
            if render is None:
                await session.rollback()
                _logger.warning("job %d: video stored but the render is gone: %s", job_id, path)
                return
            render.media_path = path
            render.metrics = metrics
            render.warnings = warnings
            render.last_error = None
            output["render_id"] = plan.render_id
        else:
            output.update(
                {
                    "kind": "test_card",
                    "orientation": plan.orientation,
                    "width": plan.width,
                    "height": plan.height,
                    "frames": plan.frames,
                }
            )
        if not await store.finish_job(session, job_id, output):
            await session.rollback()
            # Stored files are never deleted here.
            _logger.warning("job %d: video stored but the job is gone: %s", job_id, path)
            return
        await session.commit()
        if plan.render_id is None:
            await graphics_lab.prune_test_cards(session, keep_job_id=job_id)
    _logger.info("job %d: graphic rendered (%d frames, %s)", job_id, plan.frames, plan.engine)


async def _fail(job_id: int, render_id: int | None, message: str) -> None:
    """Fails the job and puts the message on the render, so the engine's card shows it."""
    async with SessionLocal() as session:
        if render_id is not None:
            render = await session.get(LabGraphicRender, render_id)
            if render is not None:
                render.last_error = message[: store.ERROR_MAX_CHARS]
        await store.fail_job(session, job_id, message)
