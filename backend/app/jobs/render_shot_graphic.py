"""The `render_shot_graphic` job: the video of one attempt of a graphic shot of a continuous
explainer (EXG-005, `Explainer_graphics_implementation_phases.md` §3.6).

It is the Graphics lab's render job (`render_lab_graphic`) for a shot, with three differences:
the story render needs an exact clip, so a wrong frame count, size or frame rate **fails** the
render; no voice is added, because the story render plays the take over the clip; and the video is
a project file (`media/<project_id>/`).

The input is `{shot_graphic_id}`. The attempt holds what is drawn (`input`: the component code or
the block scene) and the resolved brief it is drawn from (`inputs.resolved`).

1. An attempt made by a new theme (`inputs.rerender_of`) has an input that was written for the
   old look. It is checked again first, which costs no model call: a component in the browser, a
   block scene by measuring its layout (§3.3). A component that no longer compiles or draws has
   failed outright (§3.7); a block scene keeps its new layout problems as warnings.
2. The motion service draws the video, and it is downloaded.
3. `ffprobe` checks it: the exact frame count, the size, 24 frames a second, H.264 and `yuv420p`.
   Any difference fails the job. The video is not kept.
4. The video is stored, and the attempt gets its path, its frame count, its metrics and its
   warnings.

A render the motion service says it could not draw, or does not finish in time, is a failure
outright for a component. A service that cannot be reached is not (`MotionServiceError`): it says
nothing about the graphic, and the render is started again later. A frame count, size or frame
rate that is wrong is not either.

A local job: nothing is paid for and no model is asked. A restart makes the video again from the
start. Logs hold the job id, never the words.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import ShotGraphic, ShotGraphicBrief
from app.db.session import SessionLocal
from app.jobs import motion_draw, phase_writer, phases, shot_graphic_common, store
from app.jobs.handlers import JobHandler
from app.jobs.render_story import RenderFailed
from app.providers import motion_renderer
from app.services import ffmpeg, graphics_render, shot_graphics
from app.services.storage import Storage, StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = shot_graphics.RENDER_JOB_TYPE


class ComponentFailed(RenderFailed):
    """A component that cannot be drawn (it failed its check again). A failure outright."""


class VideoMismatch(RenderFailed):
    """The drawn file is not the clip that was asked for. `metrics` says what it is."""

    def __init__(self, message: str, metrics: dict[str, Any]) -> None:
        super().__init__(message)
        self.metrics = metrics


@dataclass
class _Plan:
    """What one job draws: the attempt, its size, what it draws from and what it is checked
    against.
    """

    row_id: int
    project_id: int
    engine: str
    width: int
    height: int
    fps: int
    frames: int
    resolved: dict[str, Any]
    input: Any
    rerender: bool
    brief: dict[str, Any]
    context: str


class RenderShotGraphicHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return await settings_service.get_int(session, settings_service.GRAPHICS_MAX_RENDERS_KEY)

    async def start(self, job_id: int) -> None:
        storage = get_storage()
        temp_paths: list[Path] = []
        row_id: int | None = None
        try:
            async with SessionLocal() as session:
                job = await store.get_job(session, job_id)
                await session.commit()
            if job is None or job.status != "running":
                return
            recorded = job.input if isinstance(job.input, dict) else {}
            value = recorded.get(shot_graphics.RENDER_DEDUPE_KEY)
            row_id = value if isinstance(value, int) and not isinstance(value, bool) else None
            if row_id is None:
                raise RenderFailed("The job names no graphic.")
            await self._render(job_id, row_id, storage, temp_paths)
        except (motion_draw.MotionRenderFailed, ComponentFailed) as exc:
            await _fail(job_id, row_id, str(exc), outright=True)
        except VideoMismatch as exc:
            await _fail(job_id, row_id, str(exc), metrics=exc.metrics)
        except (RenderFailed, motion_renderer.MotionServiceError) as exc:
            await _fail(job_id, row_id, str(exc))
        except StorageError as exc:
            await _fail(job_id, row_id, f"A file could not be stored: {exc}")
        finally:
            for path in temp_paths:
                storage.discard(path)

    async def _render(
        self, job_id: int, row_id: int, storage: Storage, temp_paths: list[Path]
    ) -> None:
        started = time.monotonic()
        plan = await _plan(row_id)

        # The service's versions go with the metrics, and an unreachable service is reported
        # now, before anything else is done.
        async with SessionLocal() as session:
            base_url = await settings_service.get_str(session, settings_service.MOTION_URL_KEY)
        health = await motion_renderer.health(base_url)
        versions = {"remotion": health.get("remotion"), "chrome": health.get("chrome")}

        if plan.rerender:
            await self._check_again(job_id, plan)

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
            code=graphics_render.code_of(plan.input),
        )
        render_s = await motion_draw.draw_in_motion(job_id, base_url, body, video)

        await phase_writer.note(job_id, phases.CHECKING_GRAPHIC)
        probe = await ffmpeg.probe_video(video)
        if probe is None or probe.frame_count is None:
            raise RenderFailed("The rendered video could not be read.")
        checks, mismatches = graphics_render.check_probe(
            probe, width=plan.width, height=plan.height, fps=plan.fps, frames=plan.frames
        )
        metrics: dict[str, Any] = {
            "engine": plan.engine,
            "composition": graphics_render.COMPOSITION_OF[plan.engine],
            "render_s": render_s,
            "job_s": round(time.monotonic() - started, 3),
            "size_bytes": video.stat().st_size,
            "frames": probe.frame_count,
            "width": probe.width,
            "height": probe.height,
            "fps": probe.fps,
            "codec": probe.codec_name,
            "pix_fmt": probe.pix_fmt,
            "checks": checks,
            "timing_source": plan.resolved.get("timing_source"),
            "voice": False,
            "encoding": dict(graphics_render.ENCODING),
            "versions": versions,
        }
        if mismatches:
            raise VideoMismatch(" ".join(mismatches), metrics)

        problems = graphics_render.input_warnings(plan.input)
        untraced = graphics_render.component_warnings(plan.input)
        metrics["layout_problems"] = len(problems)
        if plan.engine == shot_graphics.COMPONENT:
            metrics["untraced_numbers"] = len(untraced)

        await phase_writer.note(job_id, phases.SAVING_GRAPHIC)
        temp = await storage.describe_temp(video)
        stored = await storage.save(temp, plan.project_id, "mp4")
        await _save(
            job_id, plan, stored.relative_path, probe.frame_count, metrics, problems + untraced
        )

    async def _check_again(self, job_id: int, plan: _Plan) -> None:
        """Checks the input of an attempt made by a new theme once more, free of any model call
        (§3.3), and brings its recorded checks and warnings up to date. Raises ComponentFailed
        for a component that no longer works.
        """
        assert isinstance(plan.input, dict)
        if plan.engine == shot_graphics.COMPONENT:
            code = graphics_render.code_of(plan.input)
            if code is None:
                raise RenderFailed("The component has no code to draw.")
            checked = await shot_graphic_common.check_component(job_id, plan.resolved, code)
            if checked.failed:
                assert checked.answer is not None
                raise ComponentFailed(
                    "The component does not work with the new look: "
                    + " ".join(shot_graphic_common.errors_of(checked.answer))
                )
            plan.input = {
                "code": code,
                "checks": shot_graphic_common.checks_record(checked, False),
                "warnings": shot_graphic_common.component_warnings(
                    code, checked, plan.brief, plan.context, plan.resolved
                ),
            }
            return
        scene = {key: value for key, value in plan.input.items() if key != "layout"}
        measured = await shot_graphic_common.measure_layout(job_id, plan.resolved, scene)
        layout: dict[str, Any] = {
            "checked": measured.problems is not None,
            "asked_again": False,
            "problems": measured.problems or [],
        }
        if measured.problems is None:
            layout["reason"] = measured.reason
        plan.input = {**scene, "layout": layout}


async def _plan(row_id: int) -> _Plan:
    """Reads what the job draws. Raises RenderFailed."""
    async with SessionLocal() as session:
        row = await session.get(ShotGraphic, row_id)
        if row is None:
            raise RenderFailed("The graphic this job was made for is gone.")
        brief = await session.get(ShotGraphicBrief, row.brief_id)
        inputs = row.inputs if isinstance(row.inputs, dict) else {}
        resolved = inputs.get("resolved")
        if not isinstance(resolved, dict) or brief is None:
            raise RenderFailed("The graphic has no resolved brief to draw from.")
        if row.input is None:
            raise RenderFailed(
                "The graphic has nothing to draw yet: its model call did not finish."
            )
        context = brief.inputs.get("context") if isinstance(brief.inputs, dict) else None
        plan = _Plan(
            row_id=row.id,
            project_id=row.project_id,
            engine=row.engine,
            width=int(resolved["width"]),
            height=int(resolved["height"]),
            fps=int(resolved["fps"]),
            frames=int(resolved["frames"]),
            resolved=resolved,
            input=row.input,
            rerender=inputs.get("rerender_of") is not None,
            brief=brief.content,
            context=str(context.get("text") or "") if isinstance(context, dict) else "",
        )
        await session.commit()
    return plan


async def _save(
    job_id: int,
    plan: _Plan,
    path: str,
    frame_count: int,
    metrics: dict[str, Any],
    warnings: list[str],
) -> None:
    """Saves the video on the attempt and finishes the job in one transaction."""
    async with SessionLocal() as session:
        row = await session.get(ShotGraphic, plan.row_id)
        if row is None:
            await session.rollback()
            _logger.warning("job %d: video stored but the graphic is gone: %s", job_id, path)
            return
        row.input = plan.input
        row.media_path = path
        row.frame_count = frame_count
        row.metrics = metrics
        row.warnings = warnings
        row.last_error = None
        row.failed_outright = False
        output = {
            "path": path,
            "size_bytes": metrics["size_bytes"],
            "metrics": metrics,
            "warnings": warnings,
            "shot_graphic_id": plan.row_id,
        }
        if not await store.finish_job(session, job_id, output):
            await session.rollback()
            # Stored files are never deleted here.
            _logger.warning("job %d: video stored but the job is gone: %s", job_id, path)
            return
        await session.commit()
    _logger.info("job %d: shot graphic rendered (%d frames, %s)", job_id, plan.frames, plan.engine)


async def _fail(
    job_id: int,
    row_id: int | None,
    message: str,
    *,
    outright: bool = False,
    metrics: dict[str, Any] | None = None,
) -> None:
    """Fails the job and puts the message on the attempt. `outright` marks it only for a
    component (§3.7): the blocks have no such state.
    """
    if row_id is None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
        return
    is_component = False
    async with SessionLocal() as session:
        row = await session.get(ShotGraphic, row_id)
        is_component = row is not None and row.engine == shot_graphics.COMPONENT
    await shot_graphic_common.fail_attempt(
        job_id, row_id, message, metrics=metrics, outright=outright and is_component
    )
