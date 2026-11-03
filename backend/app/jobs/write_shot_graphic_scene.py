"""The `write_shot_graphic_scene` job: a language model reads the brief of one graphic shot of a
continuous explainer and the library of building blocks, and designs the scene of the
`remotion_blocks` version (EXG-005, `Explainer_graphics_implementation_phases.md` §3.6).

It is the Graphics lab's block-scene job (`write_lab_graphic_block_scene`) for a shot.
`services/shot_graphics` creates the job together with its attempt (a `shot_graphic` row) and
copies into the job's input everything it reads: the shot's words (`line`), the sentences around
them (`context`), the video's `mood`, the orientation, the stored `brief` and the `resolved` brief.

The job makes one to three calls to the model, in this order:

1. The scene. Its request is built in `services/graphics_block_scene_writer.py` and its answer is
   checked in `services/graphics_blocks.py`, against the **context** of the shot: a number in a
   text must be said in the shot's words or the sentences around them, or be shown by a fact
   (the soft rule, §3.2). An answer that breaks a rule is unusable, and the corrected retry of
   `jobs/llm_call.py` tells the model what was wrong (that is calls 1 and 2).
2. The layout. The motion service lays the scene out in the browser and reports where each text
   lands (`POST /layout`). Code turns the report into problems: text too small, outside the safe
   area, over the caption band, or on another element. With no problem the scene is done.
3. With problems, the model is asked once more (the call has one attempt of its own) with its
   scene and the list. A usable new scene is measured again and kept unless it has more problems
   than the first. A failed or unusable re-ask keeps the first scene.

A scene is never lost to the layout check: when the motion service cannot be reached, the scene
is saved as "layout not checked" and the render then reports the service's message.

In the transaction that marks the job succeeded, the scene becomes the attempt's `input` and its
render job is queued. A failure puts its message on the attempt.

The model is the **story role**. A paid job, so the rules in `jobs/llm_call.py` hold: a refusal
is never retried, every answer is saved the moment it arrives, and a restart queues it again
(`never_rerun`). Logs hold the job id, what each attempt did and its token counts, never the
words or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import ShotGraphic
from app.db.session import SessionLocal
from app.jobs import llm_call, phase_writer, phases, shot_graphic_common, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import (
    graphics_block_scene_writer,
    graphics_blocks,
    llm_target,
    shot_graphics,
)
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = shot_graphics.WRITE_JOB_TYPES[shot_graphics.BLOCKS]
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no graphic to design."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    row_id: int
    line: str
    context: str
    mood: str
    orientation: str
    brief: dict[str, Any]
    resolved: dict[str, Any]


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    row_id = job_input.get(shot_graphics.RENDER_DEDUPE_KEY)
    line = job_input.get("line")
    context = job_input.get("context")
    mood = job_input.get("mood")
    orientation = job_input.get("orientation")
    brief = job_input.get("brief")
    resolved = job_input.get("resolved")
    if (
        not isinstance(row_id, int)
        or isinstance(row_id, bool)
        or not isinstance(line, str)
        or not line.strip()
        or not isinstance(context, str)
        or not isinstance(mood, str)
        or not isinstance(orientation, str)
        or not isinstance(brief, dict)
        or not isinstance(resolved, dict)
    ):
        return None
    return _Task(row_id, line, context, mood, orientation, brief, resolved)


def _scene_reader(context: str, resolved: dict[str, Any]) -> llm_call.ReadAnswer:
    """Reads the model's answer: the checked scene, or why the answer cannot be used. The numbers
    of a text are checked against the context of the shot.
    """

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return shot_graphic_common.TOO_LONG, None
        try:
            answer = graphics_block_scene_writer.parse_answer(result.content)
            if not isinstance(answer, dict):
                raise ValueError("The model's answer was not a JSON object.")
            scene = graphics_blocks.check_scene(answer, context, resolved)
        except ValueError as exc:
            return str(exc), None
        return None, scene

    return read


class WriteShotGraphicSceneHandler(JobHandler):
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
            await session.commit()

        task = _read_task(job_input)
        if task is None:
            row_id = job_input.get(shot_graphics.RENDER_DEDUPE_KEY)
            if isinstance(row_id, int):
                await shot_graphic_common.fail_attempt(job_id, row_id, _BAD_INPUT)
            else:
                async with SessionLocal() as session:
                    await store.fail_job(session, job_id, _BAD_INPUT)
            return

        await phase_writer.note(job_id, phases.PREPARING_PROMPT)
        body = graphics_block_scene_writer.build_request(
            task.line,
            task.orientation,
            task.brief,
            task.resolved,
            model=target.model,
            mood=task.mood,
        )
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            instructions_sha256=llm_call.instructions_sha256(body),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        read = _scene_reader(task.context, task.resolved)
        first = await llm_call.ask_model(job_id, target, body, read, timeout_s=REQUEST_TIMEOUT_S)
        scene: dict[str, Any] | None = first.value
        if scene is None:
            await shot_graphic_common.fail_attempt(
                job_id, task.row_id, f"The block scene could not be written: {first.failure}"
            )
            return

        measured = await shot_graphic_common.measure_layout(job_id, task.resolved, scene)
        layout: dict[str, Any] = {"checked": measured.problems is not None, "asked_again": False}
        calls: dict[str, Any] = {"block_scene": first.record()}
        usage = shot_graphic_common.sum_usage(first.usage)

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
            usage = shot_graphic_common.sum_usage(first.usage, second.usage)
            layout["asked_again"] = True
            if second.value is not None:
                again = await shot_graphic_common.measure_layout(
                    job_id, task.resolved, second.value
                )
                if again.problems is not None and len(again.problems) <= len(measured.problems):
                    scene, measured = second.value, again
                else:
                    layout["kept_first"] = True
            else:
                layout["kept_first"] = True

        layout["problems"] = measured.problems or []
        if measured.problems is None:
            layout["reason"] = measured.reason

        await phase_writer.note(job_id, phases.SAVING_BLOCK_SCENE)
        await self._save(job_id, task, scene, layout, calls, usage, started)

    async def _save(
        self,
        job_id: int,
        task: _Task,
        scene: dict[str, Any],
        layout: dict[str, Any],
        calls: dict[str, Any],
        usage: dict[str, int],
        started: float,
    ) -> None:
        """Saves the scene as the input of the attempt, queues its render, and finishes the job,
        in one transaction.
        """
        async with SessionLocal() as session:
            row = await session.get(ShotGraphic, task.row_id)
            if row is None:
                await store.fail_job(session, job_id, "The attempt this job was made for is gone.")
                return
            row.input = {**scene, "layout": layout}
            row.last_error = None
            render = await shot_graphics.queue_render(session, row)
            output = {
                "calls": calls,
                "layout": layout,
                "usage": usage,
                "shot_graphic_id": row.id,
                "render_job_id": render.id,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the scene is not kept.
                await session.rollback()
                return
            await session.commit()
        _logger.info(
            "job %d: shot block scene saved (%d elements, layout checked=%s, problems=%d, "
            "asked again=%s), usage=%s",
            job_id,
            len(scene["elements"]),
            layout["checked"],
            len(layout["problems"]),
            layout["asked_again"],
            usage,
        )
