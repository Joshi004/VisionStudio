"""The `write_lab_graphic_block_scene` job: a language model reads the brief of a Graphics lab run
and the library of building blocks, and designs the scene of the `remotion_blocks` engine
(GFX-009, `Graphics_lab_implementation_phases.md` §4.5.2).

`services/graphics_block_engine.start` creates the job and, with it, one render row that has this
job as its `input_job_id`. The job's input is `{requested, run_id}`; everything else is read from
the run when the job starts: the line, the orientation, the brief and the resolved brief.

The job makes one to three calls to the model, in this order:

1. The scene. Its request is built in `services/graphics_block_scene_writer.py` and its answer is
   checked in `services/graphics_blocks.py`. An answer that breaks a rule is unusable, and the
   corrected retry of `jobs/llm_call.py` tells the model what was wrong (that is calls 1 and 2).
2. The layout. The motion service lays the scene out in the browser and reports where each text
   lands (`POST /layout`). Code turns the report into problems: text too small, outside the safe
   area, over the caption band, or on another element. With no problem the scene is done.
3. With problems, the model is asked once more (the call has one attempt of its own) with its
   scene and the list. A usable new scene is measured again and kept unless it has more problems
   than the first. A failed or unusable re-ask keeps the first scene.

A scene is never lost to the layout check: when the motion service cannot be reached, the scene
is saved as "layout not checked" and the render then reports the service's message.

In the transaction that marks the job succeeded, the scene becomes the `input` of the render row
and its render job is queued. A failure puts its message on the row.

The model is the **story role**. A paid job, so the rules in `jobs/llm_call.py` hold: a refusal
is never retried, every answer is saved the moment it arrives, and a restart queues it again
(`never_rerun`). Logs hold the job id, what each attempt did and its token counts, never the line
or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select

from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import LabGraphicRender, LabGraphicRun
from app.db.session import SessionLocal
from app.jobs import llm_call, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm, motion_renderer
from app.services import (
    graphics_block_engine,
    graphics_block_scene_writer,
    graphics_blocks,
    graphics_engines,
    graphics_lab,
    llm_target,
)
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = graphics_block_engine.SCENE_JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no run to read."
_NO_BRIEF = "The run has no brief to design a scene for."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """What the job reads from its run: the run's line, orientation, brief and resolved brief."""

    run_id: int
    line_text: str
    orientation: str
    brief: dict[str, Any]
    resolved: dict[str, Any]


@dataclass(frozen=True)
class _Measured:
    """What the layout check came to: `problems` is None when the scene could not be measured,
    and `reason` says why.
    """

    problems: list[str] | None
    reason: str | None = None


def _scene_reader(line_text: str, resolved: dict[str, Any]) -> llm_call.ReadAnswer:
    """Reads the model's answer: the checked scene, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = graphics_block_scene_writer.parse_answer(result.content)
            if not isinstance(answer, dict):
                raise ValueError("The model's answer was not a JSON object.")
            scene = graphics_blocks.check_scene(answer, line_text, resolved)
        except ValueError as exc:
            return str(exc), None
        return None, scene

    return read


class WriteLabGraphicBlockSceneHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            target = await llm_target.resolve(session, STORY_MODEL_KEY)
            run_id = job_input.get(graphics_block_engine.SCENE_DEDUPE_KEY)
            task: _Task | None = None
            problem = _BAD_INPUT
            if isinstance(run_id, int) and not isinstance(run_id, bool):
                run = await session.get(LabGraphicRun, run_id)
                if run is not None and run.brief is not None and run.resolved is not None:
                    task = _Task(
                        run_id=run.id,
                        line_text=run.line_text,
                        orientation=run.orientation,
                        brief=run.brief,
                        resolved=run.resolved,
                    )
                else:
                    problem = _NO_BRIEF
            await session.commit()

        if task is None:
            await self._fail(job_id, problem)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = graphics_block_scene_writer.build_request(
            task.line_text, task.orientation, task.brief, task.resolved, model=target.model
        )
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            instructions_sha256=llm_call.instructions_sha256(body),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        read = _scene_reader(task.line_text, task.resolved)
        first = await llm_call.ask_model(job_id, target, body, read, timeout_s=REQUEST_TIMEOUT_S)
        scene: dict[str, Any] | None = first.value
        if scene is None:
            await self._fail(job_id, f"The block scene could not be written: {first.failure}")
            return

        measured = await self._measure(job_id, task, scene)
        layout: dict[str, Any] = {"checked": measured.problems is not None, "asked_again": False}
        calls: dict[str, Any] = {"block_scene": first.record()}
        usage = _sum_usage(first.usage)

        if measured.problems:
            # The one more ask: its own single attempt, with the scene and the problems.
            retry_body = graphics_block_scene_writer.layout_retry_request(
                body, scene, measured.problems
            )
            second = await llm_call.ask_model(
                job_id,
                target,
                retry_body,
                read,
                timeout_s=REQUEST_TIMEOUT_S,
                keep={"calls": dict(calls)},
                max_attempts=1,
            )
            calls["layout_retry"] = second.record()
            usage = _sum_usage(first.usage, second.usage)
            layout["asked_again"] = True
            if second.value is not None:
                again = await self._measure(job_id, task, second.value)
                if again.problems is not None and len(again.problems) <= len(measured.problems):
                    scene, measured = second.value, again
                else:
                    layout["kept_first"] = True
            else:
                layout["kept_first"] = True

        layout["problems"] = measured.problems or []
        if measured.problems is None:
            layout["reason"] = measured.reason

        await self._phase(job_id, phases.SAVING_BLOCK_SCENE)
        await self._save(job_id, scene, layout, calls, usage, started)

    # --- The layout check -------------------------------------------------------------

    async def _measure(self, job_id: int, task: _Task, scene: dict[str, Any]) -> _Measured:
        """Has the motion service lay `scene` out and turns its report into problems. A service
        that cannot be reached, or does not accept the scene, is not a failure of the job.
        """
        await self._phase(job_id, phases.CHECKING_BLOCK_LAYOUT)
        resolved = task.resolved
        body = {
            "width": int(resolved["width"]),
            "height": int(resolved["height"]),
            "fps": int(resolved["fps"]),
            "frames": int(resolved["frames"]),
            "resolved": resolved,
            "input": scene,
            "at_frames": graphics_blocks.layout_frames(scene, resolved),
        }
        try:
            async with SessionLocal() as session:
                base_url = await settings_service.get_str(session, settings_service.MOTION_URL_KEY)
            report = await motion_renderer.layout(base_url, body)
        except motion_renderer.MotionServiceError as exc:
            _logger.warning("job %d: the layout could not be measured: %s", job_id, exc)
            return _Measured(None, str(exc))
        return _Measured(graphics_blocks.layout_problems(report, resolved))

    # --- Finishing --------------------------------------------------------------------

    @staticmethod
    async def _renders_of(session: Any, job_id: int) -> list[LabGraphicRender]:
        statement = (
            select(LabGraphicRender)
            .where(LabGraphicRender.input_job_id == job_id)
            .order_by(LabGraphicRender.id)
            .execution_options(populate_existing=True)
        )
        return list((await session.execute(statement)).scalars())

    async def _save(
        self,
        job_id: int,
        scene: dict[str, Any],
        layout: dict[str, Any],
        calls: dict[str, Any],
        usage: dict[str, int],
        started: float,
    ) -> None:
        """Saves the scene as the input of the render of the job, queues the render when its
        renderer is built, and finishes the job, in one transaction.
        """
        saved = {**scene, "layout": layout}
        async with SessionLocal() as session:
            renders = await self._renders_of(session, job_id)
            queued: list[str] = []
            for render in renders:
                render.input = saved
                render.last_error = None
                engine = graphics_engines.ENGINES[render.engine]  # type: ignore[index]
                if engine.renderer_built:
                    await graphics_lab.queue_render(session, render)
                    queued.append(render.engine)
            output = {
                "calls": calls,
                "layout": layout,
                "usage": usage,
                "renders": [render.id for render in renders],
                "queued": queued,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the scene is not kept.
                await session.rollback()
                return
            await session.commit()
        _logger.info(
            "job %d: block scene saved (%d elements, layout checked=%s, problems=%d, "
            "asked again=%s), usage=%s",
            job_id,
            len(scene["elements"]),
            layout["checked"],
            len(layout["problems"]),
            layout["asked_again"],
            usage,
        )

    # --- Small helpers ----------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        await phase_writer.note(job_id, phase)

    async def _fail(self, job_id: int, message: str) -> None:
        """Fails the job and puts the message on its render, so the engine's card shows it."""
        async with SessionLocal() as session:
            for render in await self._renders_of(session, job_id):
                render.last_error = message[: store.ERROR_MAX_CHARS]
            await store.fail_job(session, job_id, message)


def _sum_usage(*counts: dict[str, int] | None) -> dict[str, int]:
    """The tokens of the calls that were answered, added up. Empty when none was."""
    total: dict[str, int] = {}
    for one in counts:
        for key, value in (one or {}).items():
            total[key] = total.get(key, 0) + value
    return total
