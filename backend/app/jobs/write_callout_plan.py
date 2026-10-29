"""The `write_callout_plan` job: a language model suggests an explainer's accent colour and
callouts, and code checks them for display rules (EXPLAINER-009,
`Explainer_implementation_phases.md` E-14 to E-18).

`services/callout_plan.start_run` creates the job with a copy of everything it needs, taken when
the button was pressed: the Story Bible's content, the presenter's name, the scenes with their
speech units, the display limits, and the upstream rows the version is built from
(`input.bible`, `presenter_name`, `scenes`, `rules`, `saved_inputs`).

There is one call. Its request is built in `services/callout_plan_writer.py`, and its answer is
checked there: a callout that breaks a display rule makes the answer unusable, and the corrected
retry of `jobs/llm_call.py` tells the model what was wrong. The result is saved as the project's
next version, in the same transaction that marks the job succeeded.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold: at most 2 attempts, a refusal never retried, every answer saved the
moment it arrives, and a restart never re-runs it (`never_rerun`): the owner asks again with a
fresh job.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the script or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import callout_plan, llm_target
from app.services import callout_plan_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = callout_plan.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no script to read."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    bible: dict[str, Any]
    presenter_name: str
    scenes: list[dict[str, Any]]
    rules: writer.CalloutRules
    saved_inputs: dict[str, Any]


def _whole_number(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    bible = job_input.get("bible")
    presenter_name = job_input.get("presenter_name")
    scenes = job_input.get("scenes")
    rules = job_input.get("rules")
    saved_inputs = job_input.get("saved_inputs")
    if (
        not isinstance(bible, dict)
        or not isinstance(presenter_name, str)
        or not presenter_name.strip()
        or not isinstance(scenes, list)
        or not scenes
        or not isinstance(rules, dict)
        or not isinstance(saved_inputs, dict)
    ):
        return None
    min_gap_ms = _whole_number(rules.get("min_gap_ms"))
    per_minute_max = _whole_number(rules.get("per_minute_max"))
    if min_gap_ms is None or per_minute_max is None or min_gap_ms < 0 or per_minute_max < 1:
        return None
    for scene in scenes:
        if (
            not isinstance(scene, dict)
            or not isinstance(scene.get("units"), list)
            or "id" not in scene
            or "title" not in scene
        ):
            return None
    return _Task(
        bible=bible,
        presenter_name=presenter_name,
        scenes=scenes,
        rules=writer.CalloutRules(min_gap_ms=min_gap_ms, per_minute_max=per_minute_max),
        saved_inputs=saved_inputs,
    )


def _plan_reader(units: list[writer.ScriptUnit], task: _Task) -> llm_call.ReadAnswer:
    """Reads the model's answer: the stored content, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = writer.parse_answer(result.content)
            content = writer.check_plan(
                answer, units=units, presenter_name=task.presenter_name, rules=task.rules
            )
        except ValueError as exc:
            return str(exc), None
        return None, content

    return read


class WriteCalloutPlanHandler(JobHandler):
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
            project_id = job.project_id
            target = await llm_target.resolve(session, STORY_MODEL_KEY)
            await session.commit()

        task = _read_task(job_input)
        if project_id is None or task is None:
            await self._fail(job_id, _BAD_INPUT)
            return
        units = writer.script_units(task.scenes)
        if not units:
            await self._fail(job_id, _BAD_INPUT)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = writer.build_request(
            task.bible, task.presenter_name, units, task.rules, model=target.model
        )
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            calls_sent={
                "callouts": {
                    "instructions_sha256": llm_call.instructions_sha256(body),
                    "request": body,
                }
            },
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            _plan_reader(units, task),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(job_id, f"The callout plan could not be written: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_CALLOUT_PLAN)
        async with SessionLocal() as session:
            row = await callout_plan.save_version(
                session,
                project_id=project_id,
                job_id=job_id,
                inputs=task.saved_inputs,
                content=content,
            )
            output = {
                "calls": {"callouts": outcome.record()},
                "usage": outcome.usage or {},
                "callout_plan_id": row.id,
                "version": row.version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: callout plan version %d saved for project %d (%d callouts), usage=%s",
            job_id,
            row.version,
            project_id,
            len(content["callouts"]),
            outcome.usage,
        )

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
