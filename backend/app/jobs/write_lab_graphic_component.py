"""The `write_lab_graphic_component` job: a language model reads the brief of a Graphics lab run
and writes the Remotion component of the `generated_component` engine (GFX-010,
`Graphics_lab_implementation_phases.md` §4.5.3).

`services/graphics_component_engine.start` creates the job and, with it, one render row that has
this job as its `input_job_id`. The job's input is `{requested, run_id}`; everything else is read
from the run when the job starts: the line, the orientation, the brief and the resolved brief.

The job makes one to three calls to the model, in this order:

1. The component. Its request is built in `services/graphics_component_writer.py` and its answer
   is checked in `services/graphics_code_checks.py` (the static checks). An answer that breaks a
   rule is unusable, and the corrected retry of `jobs/llm_call.py` tells the model what was wrong
   (that is calls 1 and 2).
2. The browser check. The motion service transpiles the code and draws three still frames
   (`POST /checks`). With no error the component is done.
3. With an error (it does not compile, or it fails when drawn), the model is asked once more (the
   call has one attempt of its own) with its code and the error. The new code is checked in the
   browser the same way. When it still fails, or the new answer cannot be used, the job fails
   and the card shows the code and the errors; no render is queued.

A component is never lost to the check: when the motion service cannot be reached, the code is
saved as "not checked" and the render then reports the service's message.

In the transaction that marks the job succeeded, the component becomes the `input` of the render
row, `{code, checks, warnings}`, and its render job is queued. The warnings are the numbers that
are not traced to a fact (G-7): a fact's value typed in the code, and a number in the text the
browser showed that the line does not say.

The model is the **story role**. A paid job, so the rules in `jobs/llm_call.py` hold: a refusal
is never retried, every answer is saved the moment it arrives, and a restart queues it again
(`never_rerun`). Logs hold the job id, what each attempt did and its token counts, never the line
or the code.
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
    graphics_code_checks,
    graphics_component_engine,
    graphics_component_writer,
    graphics_engines,
    graphics_lab,
    llm_target,
)
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = graphics_component_engine.COMPONENT_JOB_TYPE
# The longest one call may take: a component is long.
REQUEST_TIMEOUT_S: Final = 900.0

_BAD_INPUT = "This job has no run to read."
_NO_BRIEF = "The run has no brief to write a component for."
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
class _Checked:
    """What the browser check came to. `answer` is the service's answer, or None when the check
    could not be made, and `reason` says why.
    """

    answer: dict[str, Any] | None
    reason: str | None = None

    @property
    def failed(self) -> bool:
        return self.answer is not None and not self.answer.get("ok")


def _code_reader() -> llm_call.ReadAnswer:
    """Reads the model's answer: code that passes the static checks, or why it cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, str | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            code = graphics_component_writer.parse_code(result.content)
            graphics_code_checks.check_code(code)
        except ValueError as exc:
            return str(exc), None
        return None, code

    return read


def _errors_of(answer: dict[str, Any]) -> list[str]:
    """The errors of a failed check, as sentences for the card and for the model."""
    sentences: list[str] = []
    for item in answer.get("errors") or []:
        message = str(item.get("message"))
        if answer.get("stage") == "transpile":
            sentences.append(f"The code does not compile: {message}")
        elif item.get("frame") is not None:
            sentences.append(f"Drawing frame {item['frame']} failed: {message}")
        else:
            sentences.append(message)
    return sentences or ["The component could not be drawn."]


class WriteLabGraphicComponentHandler(JobHandler):
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
            run_id = job_input.get(graphics_component_engine.COMPONENT_DEDUPE_KEY)
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
        body = graphics_component_writer.build_request(
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

        read = _code_reader()
        first = await llm_call.ask_model(job_id, target, body, read, timeout_s=REQUEST_TIMEOUT_S)
        code: str | None = first.value
        if code is None:
            await self._fail(job_id, f"The component could not be written: {first.failure}")
            return

        checked = await self._check(job_id, task, code)
        calls: dict[str, Any] = {"component": first.record()}
        usage = _sum_usage(first.usage)
        asked_again = False

        if checked.failed:
            # The one more ask: its own single attempt, with the code and the errors.
            assert checked.answer is not None
            retry_body = graphics_component_writer.repair_request(
                body, code, _errors_of(checked.answer)
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
            calls["repair"] = second.record()
            usage = _sum_usage(first.usage, second.usage)
            asked_again = True
            if second.value is not None:
                code = second.value
                checked = await self._check(job_id, task, code)
            # An unusable second answer keeps the first code and its errors.

        warnings = _warnings(task, code, checked)
        checks = _checks_record(checked, asked_again)
        saved = {"code": code, "checks": checks, "warnings": warnings}

        if checked.failed:
            assert checked.answer is not None
            message = "The component does not work: " + " ".join(_errors_of(checked.answer))
            await self._fail(job_id, message, saved)
            return

        await self._phase(job_id, phases.SAVING_COMPONENT)
        await self._save(job_id, saved, calls, usage, started)

    # --- The browser check ------------------------------------------------------------

    async def _check(self, job_id: int, task: _Task, code: str) -> _Checked:
        """Has the motion service compile `code` and draw three frames. A service that cannot be
        reached, or cannot run the check, is not a failure of the job.
        """
        await self._phase(job_id, phases.CHECKING_COMPONENT)
        resolved = task.resolved
        body = {
            "width": int(resolved["width"]),
            "height": int(resolved["height"]),
            "fps": int(resolved["fps"]),
            "frames": int(resolved["frames"]),
            "resolved": resolved,
            "code": code,
        }
        try:
            async with SessionLocal() as session:
                base_url = await settings_service.get_str(session, settings_service.MOTION_URL_KEY)
            answer = await motion_renderer.checks(base_url, body)
        except motion_renderer.MotionServiceError as exc:
            _logger.warning("job %d: the component could not be checked: %s", job_id, exc)
            return _Checked(None, str(exc))
        return _Checked(answer)

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
        saved: dict[str, Any],
        calls: dict[str, Any],
        usage: dict[str, int],
        started: float,
    ) -> None:
        """Saves the component as the input of the render of the job, queues the render when its
        renderer is built, and finishes the job, in one transaction.
        """
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
                "checks": saved["checks"],
                "usage": usage,
                "renders": [render.id for render in renders],
                "queued": queued,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the component is not kept.
                await session.rollback()
                return
            await session.commit()
        _logger.info(
            "job %d: component saved (%d characters, checked=%s, asked again=%s, warnings=%d), "
            "usage=%s",
            job_id,
            len(saved["code"]),
            saved["checks"]["checked"],
            saved["checks"]["asked_again"],
            len(saved["warnings"]),
            usage,
        )

    # --- Small helpers ----------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        await phase_writer.note(job_id, phase)

    async def _fail(self, job_id: int, message: str, saved: dict[str, Any] | None = None) -> None:
        """Fails the job and puts the message on its render, so the engine's card shows it. With
        `saved` (code that was written but does not work) the code and the errors go on the render
        too, and no render is queued.
        """
        async with SessionLocal() as session:
            for render in await self._renders_of(session, job_id):
                if saved is not None:
                    render.input = saved
                render.last_error = message[: store.ERROR_MAX_CHARS]
            await store.fail_job(session, job_id, message)


def _warnings(task: _Task, code: str, checked: _Checked) -> list[str]:
    """The warnings of a component: its code's, and the text the browser showed."""
    warnings = graphics_code_checks.code_warnings(code, task.resolved, task.brief)
    if checked.answer is not None and checked.answer.get("ok"):
        warnings += graphics_code_checks.text_warnings(
            checked.answer.get("texts") or [], task.line_text, task.resolved
        )
    return warnings


def _checks_record(checked: _Checked, asked_again: bool) -> dict[str, Any]:
    """What is stored of the browser check: `checked` is false when it could not be made."""
    answer = checked.answer
    record: dict[str, Any] = {
        "checked": answer is not None,
        "passed": None if answer is None else bool(answer.get("ok")),
        "stage": None if answer is None else answer.get("stage"),
        "errors": [] if answer is None or answer.get("ok") else _errors_of(answer),
        "check_s": None if answer is None else answer.get("check_s"),
        "asked_again": asked_again,
    }
    if answer is None:
        record["reason"] = checked.reason
    return record


def _sum_usage(*counts: dict[str, int] | None) -> dict[str, int]:
    """The tokens of the calls that were answered, added up. Empty when none was."""
    total: dict[str, int] = {}
    for one in counts:
        for key, value in (one or {}).items():
            total[key] = total.get(key, 0) + value
    return total
