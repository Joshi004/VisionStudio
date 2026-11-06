"""The `write_callout_scene` job: a language model reads one callout of a motion explainer and the
library of building blocks, and designs the scene of its `remotion_blocks` version (CMO-004,
`Callouts_motion_implementation_phases.md` §4.4.2 and §4.5).

It is `write_shot_graphic_scene` for a callout. `services/callout_graphics` creates the job
together with its attempt (a `callout_graphic` row) and copies into the job's input everything it
reads: the callout's line, the video's mood, the orientation and the `resolved` callout (the parts
and their frames, the colours, the callout look, the length and the zones, already worked out by
code).

The job makes one to three calls to the model, in this order:

1. The scene. Its request is built in `services/callout_scene_writer.py` and its answer is checked
   in `services/graphics_blocks.py` (`check_callout_scene`): only the callout blocks, every part
   shown exactly once and named by reference, no text of the model's own, no exit, effects that
   follow the callout look. An answer that breaks a rule is unusable, and the corrected retry of
   `jobs/llm_call.py` tells the model what was wrong (that is calls 1 and 2). No usable answer is
   a failure outright: the attempt has no scene and is marked `failed_outright`.
2. The layout. The motion service lays the scene out in the browser at every zone of the callout
   and reports where each text lands (`POST /layout`, callout mode). Code turns the reports into
   problems: text too small, outside the zone, or on another element's text.
3. With problems, the model is asked once more (the call has one attempt of its own) with its
   scene and the list. A usable new scene is measured again and kept unless it has more problems
   than the first. A failed or unusable re-ask keeps the first scene.

A scene is never lost to the layout check: when the motion service cannot be reached, the scene is
saved as "layout not checked" and the preview then reports the service's message.

In the transaction that marks the job succeeded, the scene becomes the attempt's `input`
(`{blocks_version, elements, layout}`) and its preview job is queued.

The model is the **story role**. A paid job, so the rules in `jobs/llm_call.py` hold: a refusal
is never retried, every answer is saved the moment it arrives, and a restart queues it again
(`never_rerun`). Logs hold the job id, what each attempt did and its token counts, never the words
or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import CalloutGraphic
from app.db.session import SessionLocal
from app.jobs import (
    callout_graphic_common,
    llm_call,
    phase_writer,
    phases,
    shot_graphic_common,
    store,
)
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import (
    callout_graphics,
    callout_scene_writer,
    graphics_blocks,
    llm_target,
)
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = callout_graphics.WRITE_JOB_TYPES[callout_graphics.BLOCKS]
# The longest one call may take.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no callout to design."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    row_id: int
    line: str
    mood: str
    orientation: str
    resolved: dict[str, Any]


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    row_id = job_input.get(callout_graphics.PREVIEW_DEDUPE_KEY)
    line = job_input.get("line")
    mood = job_input.get("mood")
    orientation = job_input.get("orientation")
    resolved = job_input.get("resolved")
    if (
        not isinstance(row_id, int)
        or isinstance(row_id, bool)
        or not isinstance(line, str)
        or not isinstance(mood, str)
        or not isinstance(orientation, str)
        or not isinstance(resolved, dict)
        or not isinstance(resolved.get("parts"), list)
        or not isinstance(resolved.get("zones"), list)
        or not resolved["zones"]
        or not isinstance(resolved.get("frame_width"), int)
        or not isinstance(resolved.get("look"), dict)
    ):
        return None
    return _Task(row_id, line, mood, orientation, resolved)


def _scene_reader(resolved: dict[str, Any]) -> llm_call.ReadAnswer:
    """Reads the model's answer: the checked scene, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return shot_graphic_common.TOO_LONG, None
        try:
            answer = callout_scene_writer.parse_answer(result.content)
            if not isinstance(answer, dict):
                raise ValueError("The model's answer was not a JSON object.")
            scene = graphics_blocks.check_callout_scene(answer, resolved)
        except ValueError as exc:
            return str(exc), None
        return None, scene

    return read


class WriteCalloutSceneHandler(JobHandler):
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
            row_id = job_input.get(callout_graphics.PREVIEW_DEDUPE_KEY)
            if isinstance(row_id, int):
                await callout_graphic_common.fail_attempt(job_id, row_id, _BAD_INPUT)
            else:
                async with SessionLocal() as session:
                    await store.fail_job(session, job_id, _BAD_INPUT)
            return

        await phase_writer.note(job_id, phases.PREPARING_PROMPT)
        body = callout_scene_writer.build_request(
            task.resolved, task.line, task.mood, task.orientation, model=target.model
        )
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            instructions_sha256=llm_call.instructions_sha256(body),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        read = _scene_reader(task.resolved)
        first = await llm_call.ask_model(job_id, target, body, read, timeout_s=REQUEST_TIMEOUT_S)
        scene: dict[str, Any] | None = first.value
        if scene is None:
            await callout_graphic_common.fail_attempt(
                job_id,
                task.row_id,
                f"The block scene could not be written: {first.failure}",
                outright=True,
            )
            return

        measured = await callout_graphic_common.measure_callout_layout(job_id, task.resolved, scene)
        layout: dict[str, Any] = {"checked": measured.problems is not None, "asked_again": False}
        calls: dict[str, Any] = {"block_scene": first.record()}
        usage = shot_graphic_common.sum_usage(first.usage)

        if measured.problems:
            # The one more ask: its own single attempt, with the scene and the problems.
            retry_body = callout_scene_writer.layout_retry_request(body, scene, measured.problems)
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
                again = await callout_graphic_common.measure_callout_layout(
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
        """Saves the scene as the input of the attempt, queues its preview, and finishes the job,
        in one transaction.
        """
        async with SessionLocal() as session:
            row = await session.get(CalloutGraphic, task.row_id)
            if row is None:
                await store.fail_job(session, job_id, "The attempt this job was made for is gone.")
                return
            row.input = {**scene, "layout": layout}
            row.last_error = None
            row.failed_outright = False
            preview = await callout_graphics.queue_preview(session, row)
            output = {
                "calls": calls,
                "layout": layout,
                "usage": usage,
                "callout_graphic_id": row.id,
                "preview_job_id": preview.id,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the scene is not kept.
                await session.rollback()
                return
            await session.commit()
        _logger.info(
            "job %d: callout block scene saved (%d elements, layout checked=%s, problems=%d, "
            "asked again=%s), usage=%s",
            job_id,
            len(scene["elements"]),
            layout["checked"],
            len(layout["problems"]),
            layout["asked_again"],
            usage,
        )
