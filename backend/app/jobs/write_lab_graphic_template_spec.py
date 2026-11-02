"""The `write_lab_graphic_template_spec` job: a language model reads the brief of a Graphics lab run
and the template catalogue, and answers a template spec, or that no template fits (GFX-006,
`Graphics_lab_implementation_phases.md` §4.5.1).

`services/graphics_template_engine.start` creates the job and, with it, one render row for each
template engine (`remotion_templates` and `python_templates`) that has this job as its
`input_job_id`. The job's input is `{requested, run_id}`; everything else is read from the run
when the job starts: the line, the orientation, the brief and the resolved brief, none of which
changes once written.

There is one call. Its request is built in `services/graphics_template_spec_writer.py` and its
answer is checked in `services/graphics_templates.py`: an answer that breaks a rule is unusable,
and the corrected retry of `jobs/llm_call.py` tells the model what was wrong. "No template fits"
is a valid answer, saved like a spec with its reason. In the transaction that marks the job
succeeded, the answer becomes the `input` of every render row of the job, and a render job is
queued for each of those rows whose engine's renderer is built (`graphics_engines.Engine
.renderer_built`) when there is a spec to draw. A failure puts its message on those rows, so the
engines' cards show it.

The model is the **story role**. A paid job, so the rules in `jobs/llm_call.py` hold: at most 2
attempts, a refusal never retried, every answer saved the moment it arrives, and a restart queues
it again (`never_rerun`). Logs hold the job id, what each attempt did and its token counts, never
the line or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select

from app.core.urls import docker_mapped
from app.db.models import LabGraphicRender, LabGraphicRun
from app.db.session import SessionLocal
from app.jobs import llm_call, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import (
    graphics_engines,
    graphics_lab,
    graphics_template_engine,
    graphics_template_spec_writer,
    graphics_templates,
    llm_target,
)
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = graphics_template_engine.SPEC_JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no run to read."
_NO_BRIEF = "The run has no brief to choose a template for."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """What the job reads from its run: the run's line, orientation, brief and resolved brief."""

    run_id: int
    line_text: str
    orientation: str
    brief: dict[str, Any]
    resolved: dict[str, Any]


def _spec_reader(line_text: str, resolved: dict[str, Any]) -> llm_call.ReadAnswer:
    """Reads the model's answer: the checked spec, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = graphics_template_spec_writer.parse_answer(result.content)
            if not isinstance(answer, dict):
                raise ValueError("The model's answer was not a JSON object.")
            spec = graphics_templates.check_spec(answer, line_text, resolved)
        except ValueError as exc:
            return str(exc), None
        return None, spec

    return read


class WriteLabGraphicTemplateSpecHandler(JobHandler):
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
            run_id = job_input.get(graphics_template_engine.SPEC_DEDUPE_KEY)
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
        body = graphics_template_spec_writer.build_request(
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

        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            _spec_reader(task.line_text, task.resolved),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        spec: dict[str, Any] | None = outcome.value
        if spec is None:
            await self._fail(job_id, f"The template spec could not be written: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_TEMPLATE_SPEC)
        await self._save(job_id, spec, outcome, started)

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
        self, job_id: int, spec: dict[str, Any], outcome: llm_call.Outcome, started: float
    ) -> None:
        """Saves the spec as the input of every render of the job, queues the renders whose
        renderer is built, and finishes the job, in one transaction.
        """
        async with SessionLocal() as session:
            renders = await self._renders_of(session, job_id)
            queued: list[str] = []
            for render in renders:
                render.input = spec
                render.last_error = None
                engine = graphics_engines.ENGINES[render.engine]  # type: ignore[index]
                if spec["template"] is not None and engine.renderer_built:
                    await graphics_lab.queue_render(session, render)
                    queued.append(render.engine)
            output = {
                "calls": {"template_spec": outcome.record()},
                "usage": outcome.usage or {},
                "template": spec["template"],
                "renders": [render.id for render in renders],
                "queued": queued,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the spec is not kept.
                await session.rollback()
                return
            await session.commit()
        _logger.info(
            "job %d: template spec saved for %d renders (template=%s), usage=%s",
            job_id,
            len(renders),
            spec["template"],
            outcome.usage,
        )

    # --- Small helpers ----------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        await phase_writer.note(job_id, phase)

    async def _fail(self, job_id: int, message: str) -> None:
        """Fails the job and puts the message on its renders, so the engines' cards show it."""
        async with SessionLocal() as session:
            for render in await self._renders_of(session, job_id):
                render.last_error = message[: store.ERROR_MAX_CHARS]
            await store.fail_job(session, job_id, message)
