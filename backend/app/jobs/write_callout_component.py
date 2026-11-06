"""The `write_callout_component` job: a language model reads one callout of a motion explainer and
writes the Remotion component of its `generated_component` version (CMO-003,
`Callouts_motion_implementation_phases.md` §4.5).

It is `write_shot_graphic_component` for a callout. `services/callout_graphics` creates the job
together with its attempt (a `callout_graphic` row) and copies into the job's input everything it
reads: the callout's line, the video's mood, the orientation and the `resolved` callout (the
parts and their frames, the colours, the callout look, the length and the zones, already worked
out by code).

The job makes the component call and then at most the repairs the setting
`graphics_component_repairs` still allows the chain of attempts:

1. The component. Its request is built in `services/callout_component_writer.py` and its answer
   is checked in `services/graphics_code_checks.py` (the static checks, with the callout's own
   size limit). An answer that breaks a rule is unusable, and the corrected retry of
   `jobs/llm_call.py` tells the model what was wrong. No usable answer is a failure outright.
2. The browser check (`callout_graphic_common.check_callout_component`): the motion service draws
   still frames at every zone of the callout, and the callout rules are applied to what it drew
   (only the given words, transparent enough, nothing cut).
3. With an error, the model is asked again (each ask has one attempt of its own) with its code
   and the error, and the answer is checked the same way, until the check passes or the repairs
   are used up. A component that still fails is a failure outright: the attempt keeps the code
   and the errors, has no preview and is marked `failed_outright`; no preview is queued.

**Repair mode.** When the preview of a component failed, `render_callout_preview` queues this job
for a new attempt (`repair_of` set) with a `repair` block in its input: the code, the error and
the repairs the chain has spent. The job then skips the component call and starts at step 3.

A component is never lost to the check: when the motion service cannot be reached, the code is
saved as "not checked" and the preview then reports the service's message.

In the transaction that marks the job succeeded, the component becomes the attempt's `input`,
`{code, checks, warnings}`, and its preview job is queued.

The model is the **story role**. A paid job, so the rules in `jobs/llm_call.py` hold: a refusal
is never retried, every answer is saved the moment it arrives, and a restart queues it again
(`never_rerun`). Logs hold the job id, what each attempt did and its token counts, never the
words or the code.
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
    callout_component_writer,
    callout_graphics,
    graphics_code_checks,
    graphics_component_writer,
    llm_target,
)
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = callout_graphics.WRITE_JOB_TYPES[callout_graphics.COMPONENT]
# The longest one call may take.
REQUEST_TIMEOUT_S: Final = 900.0

_BAD_INPUT = "This job has no callout to write."


@dataclass(frozen=True)
class _Repair:
    """What a job in repair mode starts from: the code whose preview failed, the errors, and how
    many repair asks the chain has spent before this job.
    """

    code: str
    errors: list[str]
    repairs_before: int


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    row_id: int
    line: str
    mood: str
    orientation: str
    resolved: dict[str, Any]
    repair: _Repair | None


def _read_repair(value: Any) -> _Repair | None:
    """The `repair` block of the job's input, or None when it is not a usable one."""
    if not isinstance(value, dict):
        return None
    code = value.get("code")
    errors = value.get("errors")
    before = value.get("repairs_before")
    if (
        not isinstance(code, str)
        or not code.strip()
        or not isinstance(errors, list)
        or not errors
        or not all(isinstance(error, str) for error in errors)
        or not isinstance(before, int)
        or isinstance(before, bool)
        or before < 0
    ):
        return None
    return _Repair(code, list(errors), before)


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    row_id = job_input.get(callout_graphics.PREVIEW_DEDUPE_KEY)
    line = job_input.get("line")
    mood = job_input.get("mood")
    orientation = job_input.get("orientation")
    resolved = job_input.get("resolved")
    repair = _read_repair(job_input.get("repair"))
    if "repair" in job_input and repair is None:
        return None
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
    ):
        return None
    return _Task(row_id, line, mood, orientation, resolved, repair)


def _code_reader() -> llm_call.ReadAnswer:
    """Reads the model's answer: code that passes the static checks, or why it cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, str | None]:
        if result.finish_reason == "length":
            return shot_graphic_common.TOO_LONG, None
        try:
            code = graphics_component_writer.parse_code(result.content)
            graphics_code_checks.check_code(code, max_chars=callout_component_writer.MAX_CODE_CHARS)
        except ValueError as exc:
            return str(exc), None
        return None, code

    return read


class WriteCalloutComponentHandler(JobHandler):
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
            limit = await callout_graphics.repair_limit(session)
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
        body = callout_component_writer.build_request(
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

        read = _code_reader()
        calls: dict[str, Any] = {}
        usage: dict[str, int] = {}
        # The errors the next repair ask is given come from a preview (not from the check).
        rendered = task.repair is not None

        if task.repair is None:
            first = await llm_call.ask_model(
                job_id, target, body, read, timeout_s=REQUEST_TIMEOUT_S
            )
            if first.value is None:
                await callout_graphic_common.fail_attempt(
                    job_id,
                    task.row_id,
                    f"The component could not be written: {first.failure}",
                    outright=True,
                )
                return
            code = first.value
            calls["component"] = first.record()
            usage = shot_graphic_common.sum_usage(first.usage)
            checked = await callout_graphic_common.check_callout_component(
                job_id, task.resolved, code
            )
            repairs_before = 0
        else:
            # A repair of a component whose preview failed: it starts from that code and error,
            # and the first ask is already a repair.
            code = task.repair.code
            checked = shot_graphic_common.Checked(
                {
                    "ok": False,
                    "stage": "render",
                    "errors": [{"frame": None, "message": error} for error in task.repair.errors],
                }
            )
            repairs_before = task.repair.repairs_before

        # The repairs: one ask each (its own single attempt) with the code and the errors, and an
        # answer is checked again. An unusable answer keeps the code and its errors, and still
        # spends the repair. A check the service could not make leaves no error to repair.
        repairs = 0
        while checked.failed and repairs_before + repairs < limit:
            assert checked.answer is not None
            repair_body = graphics_component_writer.repair_request(
                body,
                code,
                shot_graphic_common.repair_errors(shot_graphic_common.errors_of(checked.answer)),
                rendered=rendered,
            )
            answer = await llm_call.ask_model(
                job_id,
                target,
                repair_body,
                read,
                timeout_s=REQUEST_TIMEOUT_S,
                keep={"calls": dict(calls)},
                max_attempts=1,
            )
            repairs += 1
            calls[f"repair_{repairs}"] = answer.record()
            usage = shot_graphic_common.sum_usage(usage, answer.usage)
            if answer.value is not None:
                code = answer.value
                checked = await callout_graphic_common.check_callout_component(
                    job_id, task.resolved, code
                )
                rendered = False

        saved = {
            "code": code,
            "checks": shot_graphic_common.checks_record(checked, repairs, limit),
            "warnings": callout_graphic_common.component_warnings(code, task.resolved),
        }

        if checked.failed:
            assert checked.answer is not None
            message = shot_graphic_common.outright_message(
                repairs_before + repairs, shot_graphic_common.errors_of(checked.answer)
            )
            await callout_graphic_common.fail_attempt(
                job_id, task.row_id, message, saved=saved, outright=True
            )
            return

        await phase_writer.note(job_id, phases.SAVING_COMPONENT)
        await self._save(job_id, task, saved, calls, usage, started)

    async def _save(
        self,
        job_id: int,
        task: _Task,
        saved: dict[str, Any],
        calls: dict[str, Any],
        usage: dict[str, int],
        started: float,
    ) -> None:
        """Saves the component as the input of the attempt, queues its preview, and finishes the
        job, in one transaction.
        """
        async with SessionLocal() as session:
            row = await session.get(CalloutGraphic, task.row_id)
            if row is None:
                await store.fail_job(session, job_id, "The attempt this job was made for is gone.")
                return
            row.input = saved
            row.last_error = None
            row.failed_outright = False
            preview = await callout_graphics.queue_preview(session, row)
            output = {
                "calls": calls,
                "checks": saved["checks"],
                "usage": usage,
                "callout_graphic_id": row.id,
                "preview_job_id": preview.id,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the component is not kept.
                await session.rollback()
                return
            await session.commit()
        _logger.info(
            "job %d: callout component saved (%d characters, checked=%s, repairs=%d, "
            "warnings=%d), usage=%s",
            job_id,
            len(saved["code"]),
            saved["checks"]["checked"],
            saved["checks"]["repairs"],
            len(saved["warnings"]),
            usage,
        )
