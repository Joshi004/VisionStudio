"""The `render_callout_preview` job: the preview of one attempt of a callout of a motion explainer
(CMO-003, `Callouts_motion_implementation_phases.md` §4.5).

It is `render_shot_graphic` for a callout, with these differences: the callout is drawn at its
nominal zone (the first of `resolved.zones`) and nominal length, on a grey backdrop so that an
ordinary H.264 file shows it and a browser plays it; the final transparent clips are drawn by the
render (CMO-005), not here; and the file is the attempt's `preview_path`, a project file
(`media/<project_id>/`).

The input is `{callout_graphic_id}`. The attempt holds what is drawn (`input`: the component code)
and the resolved callout it is drawn from (`inputs.resolved`).

1. An attempt made for new words or new colours (`inputs.rerender_of`) has code that was written
   for other words. It is checked again first, in the browser and by the callout rules, which
   costs no model call. A component that no longer works (a longer word that is cut, say) has
   failed.
2. The motion service draws the preview, and it is downloaded.
3. `ffprobe` checks it: the exact frame count, the size, the frame rate, H.264 and `yuv420p`.
   Any difference fails the job. The file is not kept.
4. The file is stored, and the attempt gets its path, its metrics and its warnings.

A preview the motion service says it could not draw, or does not finish in time, is repaired: the
job fails, and in the same transaction a new attempt of the component and its write job in repair
mode are queued, with the code and the error, while the chain's repairs
(`graphics_component_repairs`) last. The same holds for code that fails the free check of step 1.
With the repairs used up the component has failed outright. A service that cannot be reached is
neither repaired nor a failure outright (`MotionServiceError`): it says nothing about the
component, and the preview is made again later. A frame count, size or frame rate that is wrong
is not either.

A local job: nothing is paid for and no model is asked. A restart makes the preview again from the
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
from app.db.models import CalloutGraphic, Project
from app.db.session import SessionLocal
from app.jobs import (
    callout_graphic_common,
    motion_draw,
    phase_writer,
    phases,
    shot_graphic_common,
    store,
)
from app.jobs.handlers import JobHandler
from app.jobs.render_story import RenderFailed
from app.providers import motion_renderer
from app.services import (
    callout_component_checks,
    callout_graphics,
    ffmpeg,
    graphics_render,
)
from app.services.storage import Storage, StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = callout_graphics.PREVIEW_JOB_TYPE
# The composition of `motion/src/Root.tsx` that draws a callout.
COMPOSITION: Final = "Callout"


class ComponentFailed(RenderFailed):
    """A component that cannot be drawn (it failed its check again). It is repaired, or fails
    outright when the repairs are used up. `errors` are the sentences the model is given.
    """

    def __init__(self, message: str, errors: list[str]) -> None:
        super().__init__(message)
        self.errors = errors


class VideoMismatch(RenderFailed):
    """The drawn file is not the preview that was asked for. `metrics` says what it is."""

    def __init__(self, message: str, metrics: dict[str, Any]) -> None:
        super().__init__(message)
        self.metrics = metrics


@dataclass
class _Plan:
    """What one job draws: the attempt, the zone and length, and what it draws from."""

    row_id: int
    project_id: int
    zone: dict[str, Any]
    fps: int
    frames: int
    resolved: dict[str, Any]
    input: Any
    rerender: bool


class RenderCalloutPreviewHandler(JobHandler):
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
            value = recorded.get(callout_graphics.PREVIEW_DEDUPE_KEY)
            row_id = value if isinstance(value, int) and not isinstance(value, bool) else None
            if row_id is None:
                raise RenderFailed("The job names no callout graphic.")
            await self._render(job_id, row_id, storage, temp_paths)
        except ComponentFailed as exc:
            await _fail_drawing(job_id, row_id, str(exc), exc.errors)
        except motion_draw.MotionRenderFailed as exc:
            await _fail_drawing(job_id, row_id, str(exc), [str(exc)])
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
            callout_graphic_common.MOTION_ENGINE,
            width=int(plan.zone["width"]),
            height=int(plan.zone["height"]),
            fps=plan.fps,
            frames=plan.frames,
            resolved=callout_component_checks.motion_resolved(
                plan.resolved, plan.zone, backdrop=callout_graphics.BACKDROP
            ),
            input=None,
            code=graphics_render.code_of(plan.input),
        )
        render_s = await motion_draw.draw_in_motion(job_id, base_url, body, video)

        await phase_writer.note(job_id, phases.CHECKING_GRAPHIC)
        probe = await ffmpeg.probe_video(video)
        if probe is None or probe.frame_count is None:
            raise RenderFailed("The rendered video could not be read.")
        checks, mismatches = graphics_render.check_probe(
            probe,
            width=int(plan.zone["width"]),
            height=int(plan.zone["height"]),
            fps=plan.fps,
            frames=plan.frames,
        )
        metrics: dict[str, Any] = {
            "engine": callout_graphic_common.MOTION_ENGINE,
            "composition": COMPOSITION,
            "zone": plan.zone["placement"],
            "backdrop": callout_graphics.BACKDROP,
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
            "encoding": dict(graphics_render.ENCODING),
            "versions": versions,
        }
        if mismatches:
            raise VideoMismatch(" ".join(mismatches), metrics)

        warnings = graphics_render.component_warnings(plan.input)
        await phase_writer.note(job_id, phases.SAVING_GRAPHIC)
        temp = await storage.describe_temp(video)
        stored = await storage.save(temp, plan.project_id, "mp4")
        await _save(job_id, plan, stored.relative_path, metrics, warnings)

    async def _check_again(self, job_id: int, plan: _Plan) -> None:
        """Checks the code of an attempt made for new words or colours once more, free of any
        model call, and brings its recorded checks and warnings up to date. Raises
        ComponentFailed for a component that no longer works.
        """
        code = graphics_render.code_of(plan.input)
        if code is None:
            raise RenderFailed("The component has no code to draw.")
        checked = await callout_graphic_common.check_callout_component(job_id, plan.resolved, code)
        if checked.failed:
            assert checked.answer is not None
            errors = shot_graphic_common.errors_of(checked.answer)
            raise ComponentFailed(
                "The component does not work with the new words or colours: " + " ".join(errors),
                errors,
            )
        async with SessionLocal() as session:
            limit = await callout_graphics.repair_limit(session)
        plan.input = {
            "code": code,
            "checks": shot_graphic_common.checks_record(checked, 0, limit),
            "warnings": callout_graphic_common.component_warnings(code, plan.resolved),
        }


async def _plan(row_id: int) -> _Plan:
    """Reads what the job draws. Raises RenderFailed."""
    async with SessionLocal() as session:
        row = await session.get(CalloutGraphic, row_id)
        if row is None:
            raise RenderFailed("The callout graphic this job was made for is gone.")
        inputs = row.inputs if isinstance(row.inputs, dict) else {}
        resolved = inputs.get("resolved")
        if not isinstance(resolved, dict) or not resolved.get("zones"):
            raise RenderFailed("The callout graphic has no resolved callout to draw from.")
        if row.input is None:
            raise RenderFailed(
                "The callout graphic has nothing to draw yet: its model call did not finish."
            )
        plan = _Plan(
            row_id=row.id,
            project_id=row.project_id,
            zone=dict(resolved["zones"][0]),
            fps=int(resolved["fps"]),
            frames=int(resolved["frames"]),
            resolved=resolved,
            input=row.input,
            rerender=inputs.get("rerender_of") is not None,
        )
        await session.commit()
    return plan


async def _save(
    job_id: int, plan: _Plan, path: str, metrics: dict[str, Any], warnings: list[str]
) -> None:
    """Saves the preview on the attempt and finishes the job in one transaction."""
    async with SessionLocal() as session:
        row = await session.get(CalloutGraphic, plan.row_id)
        if row is None:
            await session.rollback()
            _logger.warning(
                "job %d: preview stored but the callout graphic is gone: %s", job_id, path
            )
            return
        row.input = plan.input
        row.preview_path = path
        row.metrics = metrics
        row.warnings = warnings
        row.last_error = None
        row.failed_outright = False
        output = {
            "path": path,
            "size_bytes": metrics["size_bytes"],
            "metrics": metrics,
            "warnings": warnings,
            "callout_graphic_id": plan.row_id,
        }
        if not await store.finish_job(session, job_id, output):
            await session.rollback()
            # Stored files are never deleted here.
            _logger.warning("job %d: preview stored but the job is gone: %s", job_id, path)
            return
        await session.commit()
    _logger.info("job %d: callout preview rendered (%d frames)", job_id, plan.frames)


async def _fail_drawing(job_id: int, row_id: int | None, message: str, errors: list[str]) -> None:
    """Fails the job of a preview the motion service could not draw, or of a component that no
    longer works with new words or colours. The model is asked to repair it, while its chain has
    repairs left: a new attempt (`repair_of`) and its write job are queued in the same
    transaction that fails this job. With none left, the component has failed outright and the
    attempt says after how many repairs. A callout that has moved on is not repaired and not
    marked: the next Make starts from what is current.
    """
    if row_id is None:
        await _fail(job_id, row_id, message)
        return
    async with SessionLocal() as session:
        job = await store.get_job(session, job_id)
        row = await session.get(CalloutGraphic, row_id)
        project = await session.get(Project, row.project_id) if row is not None else None
        if (
            job is None
            or job.status != "running"
            or row is None
            or project is None
            or row.engine != callout_graphics.COMPONENT
        ):
            await session.rollback()
            await _fail(job_id, row_id, message)
            return
        used = await callout_graphics.repairs_used(session, row)
        allowed = await callout_graphics.repair_limit(session)
        repair_job_id: int | None = None
        if used < allowed:
            repair = await callout_graphics.queue_repair(
                session, project, row, shot_graphic_common.repair_errors(errors), used
            )
            repair_job_id = repair.id if repair is not None else None
            # Either repaired, or nothing to repair now: not a failure outright.
            row.last_error = message[: store.ERROR_MAX_CHARS]
            row.failed_outright = False
        else:
            row.last_error = shot_graphic_common.outright_message(used, errors)[
                : store.ERROR_MAX_CHARS
            ]
            row.failed_outright = True
        await store.fail_job(session, job_id, message)
    if repair_job_id is not None:
        _logger.info("job %d: the component is repaired by job %d", job_id, repair_job_id)


async def _fail(
    job_id: int,
    row_id: int | None,
    message: str,
    *,
    metrics: dict[str, Any] | None = None,
) -> None:
    """Fails the job and puts the message on the attempt."""
    if row_id is None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
        return
    await callout_graphic_common.fail_attempt(job_id, row_id, message, metrics=metrics)
