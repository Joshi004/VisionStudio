"""The `write_lab_graphic_brief` job: a language model reads one line of an explainer script and
writes the brief of the graphic, and code checks it and resolves it (GFX-003,
`Graphics_lab_implementation_phases.md` §4.3 and §4.4).

`services/graphics_lab.start_brief` creates the job with a copy of what it needs, taken when the
button was pressed: the run's id, its line and orientation, the timing of the line's words, and
whether **Make all** started it (`input.run_id`, `line_text`, `orientation`, `timing`,
`then_start_engines`).

There is one call. Its request is built in `services/graphics_brief_writer.py`, and its answer
is checked there: a brief that breaks a rule makes the answer unusable, and the corrected retry
of `jobs/llm_call.py` tells the model what was wrong. The checked brief and the resolved brief
(`services/graphics_resolve.py`) are saved on the run in the same transaction that marks the job
succeeded. The job belongs to no project.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold: at most 2 attempts, a refusal never retried, every answer saved the
moment it arrives, and a restart queues it again (`never_rerun`).

When the job was started by **Make all**, the engines that are built are started once the brief
is saved (`graphics_lab.start_engines`). A failure there never fails this job: the brief is
already saved, and each engine keeps its own failure on its card.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the line or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import LabGraphicRun
from app.db.session import SessionLocal
from app.jobs import llm_call, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import graphics_brief_writer as writer
from app.services import graphics_lab, graphics_resolve, llm_target
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = graphics_lab.BRIEF_JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no line to read."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    run_id: int
    line_text: str
    orientation: str
    timing: dict[str, Any]
    then_start_engines: bool


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    run_id = job_input.get("run_id")
    line_text = job_input.get("line_text")
    orientation = job_input.get("orientation")
    timing = job_input.get("timing")
    if (
        not isinstance(run_id, int)
        or isinstance(run_id, bool)
        or not isinstance(line_text, str)
        or not line_text.strip()
        or orientation not in graphics_lab.ORIENTATIONS
        or not isinstance(timing, dict)
        or not isinstance(timing.get("words"), list)
        or not timing["words"]
        or not isinstance(timing.get("duration_s"), int | float)
    ):
        return None
    return _Task(
        run_id=run_id,
        line_text=line_text,
        orientation=orientation,
        timing=timing,
        then_start_engines=job_input.get("then_start_engines") is True,
    )


def _brief_reader(line_text: str) -> llm_call.ReadAnswer:
    """Reads the model's answer: the checked brief, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = writer.parse_answer(result.content)
            brief = writer.check_brief(answer, line_text)
        except ValueError as exc:
            return str(exc), None
        return None, brief

    return read


class WriteLabGraphicBriefHandler(JobHandler):
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
            await self._fail(job_id, None, _BAD_INPUT)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = writer.build_request(
            task.line_text,
            task.orientation,
            float(task.timing["duration_s"]),
            model=target.model,
        )
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            instructions_sha256=llm_call.instructions_sha256(body),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, _brief_reader(task.line_text), timeout_s=REQUEST_TIMEOUT_S
        )
        brief: dict[str, Any] | None = outcome.value
        if brief is None:
            await self._fail(
                job_id, task.run_id, f"The brief could not be written: {outcome.failure}"
            )
            return

        await self._phase(job_id, phases.SAVING_GRAPHIC_BRIEF)
        saved = await self._save(job_id, task, brief, outcome, started)
        if saved and task.then_start_engines:
            await self._start_engines(job_id, task.run_id)

    # --- Finishing --------------------------------------------------------------------

    async def _save(
        self,
        job_id: int,
        task: _Task,
        brief: dict[str, Any],
        outcome: llm_call.Outcome,
        started: float,
    ) -> bool:
        """Saves the brief and the resolved brief on the run and finishes the job, in one
        transaction. False when nothing was kept (the job failed, or was cancelled meanwhile).
        """
        async with SessionLocal() as session:
            run = await session.get(LabGraphicRun, task.run_id)
            if run is None:
                await session.rollback()
                await self._fail(job_id, None, "The run was deleted before the brief was saved.")
                return False
            width, height = graphics_lab.size_of(run)
            try:
                resolved = graphics_resolve.resolve(
                    brief, task.timing, width, height, graphics_lab.FPS, graphics_lab.FONTS
                )
            except ValueError as exc:
                await session.rollback()
                await self._fail(job_id, task.run_id, f"The brief could not be resolved: {exc}")
                return False
            run.brief = brief
            run.resolved = resolved
            run.last_error = None
            output = {
                "calls": {"brief": outcome.record()},
                "usage": outcome.usage or {},
                "run_id": run.id,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the brief is not kept.
                await session.rollback()
                return False
            await session.commit()
        _logger.info(
            "job %d: graphic brief saved for run %d (%d facts, %d beats), usage=%s",
            job_id,
            task.run_id,
            len(brief["facts"]),
            len(brief["beats"]),
            outcome.usage,
        )
        return True

    @staticmethod
    async def _start_engines(job_id: int, run_id: int) -> None:
        try:
            async with SessionLocal() as session:
                await graphics_lab.start_engines(session, run_id)
        except Exception:
            _logger.exception(
                "job %d: Make all could not start the engines of run %d", job_id, run_id
            )

    # --- Small helpers ----------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        await phase_writer.note(job_id, phase)

    @staticmethod
    async def _fail(job_id: int, run_id: int | None, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
        if run_id is None:
            return
        async with SessionLocal() as session:
            run = await session.get(LabGraphicRun, run_id)
            if run is not None:
                run.last_error = message[: store.ERROR_MAX_CHARS]
                await session.commit()
