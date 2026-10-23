"""The `plan_environment_views` job: a language model plans which views one environment of a
story project needs, and code checks the plan and stores it as a new version of that
environment's view plan (PHASE-052, `Path_ahead.md` Section 46).

`services/environment_views._queue_plan` creates the job with the environment (its definition and
spatial plan), the prompt of its master picture, the backgrounds each scene needs
(`scenes`), the library's views that may be reused (`existing_views`) and the ids that are taken
(`unusable_slugs`), the ids of the spatial plan's zones, and the `inputs` that are written onto
the plan (D-3). The job builds the request, asks the model, checks the answer
(`environment_view_planner.check_answer`) and saves it (`environment_views.save_plan`, which
also adds a library view for every new view) in the same transaction that marks the job
succeeded. The pictures are made by a separate step (`environment_views.start_pictures`).

One job per environment, so environments are planned side by side (`store.create_job` with
`dedupe_key`). The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every story
stage (D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`). It is a local-style job: everything happens in `start`. Logs hold the job id,
what each attempt did and its token counts, never the answer.
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
from app.services import environment_view_planner as planner
from app.services import environment_views, llm_target
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no environment to plan."


@dataclass(frozen=True)
class _Input:
    """What `_queue_plan` put on the job, checked."""

    discovery_id: str
    environment_id: int
    environment: dict[str, Any]
    master_prompt: str | None
    scenes: list[dict[str, Any]]
    existing_views: list[dict[str, Any]]
    unusable_slugs: list[str]
    zone_ids: list[str]
    inputs: dict[str, Any]


def _is_text_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `_queue_plan` writes is missing or the wrong
    shape (a job made by hand, or by an older version of the code).
    """
    discovery_id = job_input.get("discovery_id")
    environment_id = job_input.get("environment_id")
    environment = job_input.get("environment")
    master_prompt = job_input.get("master_prompt")
    scenes = job_input.get("scenes")
    existing = job_input.get("existing_views")
    unusable = job_input.get("unusable_slugs")
    zone_ids = job_input.get("zone_ids")
    inputs = job_input.get("inputs")
    if (
        not isinstance(discovery_id, str)
        or not isinstance(environment_id, int)
        or not isinstance(environment, dict)
        or not (master_prompt is None or isinstance(master_prompt, str))
        or not isinstance(scenes, list)
        or not isinstance(existing, list)
        or not _is_text_list(unusable)
        or not _is_text_list(zone_ids)
        or not isinstance(inputs, dict)
    ):
        return None
    return _Input(
        discovery_id=discovery_id,
        environment_id=environment_id,
        environment=environment,
        master_prompt=master_prompt,
        scenes=scenes,
        existing_views=existing,
        unusable_slugs=unusable,
        zone_ids=zone_ids,
        inputs=inputs,
    )


class PlanEnvironmentViewsHandler(JobHandler):
    job_type = environment_views.PLAN_JOB
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(result: llm.ChatResult, read: _Input) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, content)` when it can be stored, else `(why not, None)`."""
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = planner.parse_answer(result.content)
            return None, planner.check_answer(
                answer,
                scenes=read.scenes,
                existing={item["id"]: item for item in read.existing_views},
                unusable=read.unusable_slugs,
                zone_ids=read.zone_ids,
            )
        except ValueError as exc:
            return str(exc), None

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

        read = _read_input(job_input)
        if project_id is None or read is None:
            await self._fail(job_id, _BAD_INPUT)
            return
        name = str(read.environment.get("name", read.discovery_id))

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = planner.build_request(
            environment=read.environment,
            master_prompt=read.master_prompt,
            scenes=read.scenes,
            existing_views=read.existing_views,
            model=target.model,
        )
        job_input.update(
            instructions_sha256=llm_call.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            lambda result: self._read(result, read),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(
                job_id, f"The views of '{name}' could not be planned: {outcome.failure}"
            )
            return

        await self._phase(job_id, phases.SAVING_VIEW_PLAN)
        async with SessionLocal() as session:
            try:
                row = await environment_views.save_plan(
                    session,
                    project_id=project_id,
                    discovery_id=read.discovery_id,
                    library_id=read.environment_id,
                    content=content,
                    job_id=job_id,
                    inputs=read.inputs,
                )
            except environment_views.EnvironmentViewError as exc:
                await session.rollback()
                await self._fail(job_id, f"The views of '{name}' could not be saved: {exc}")
                return
            output = {
                **outcome.record(),
                "content": None,
                "discovery_id": read.discovery_id,
                "version": row.version,
                "views": len(row.content["views"]),
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the plan is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: views of '%s' planned for project %d, version %d, %d views, usage=%s",
            job_id,
            read.discovery_id,
            project_id,
            row.version,
            len(row.content["views"]),
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
