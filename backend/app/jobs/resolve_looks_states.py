"""The `resolve_looks_states` job: a language model maps every look and environment state the
scenes asked for to `default`, an existing named look or state, or one new entry, and code
checks the answer and stores it (PHASE-016, `Path_ahead.md` Sections 14 and 16).

`services/look_state_resolution.start_run` creates the job with the id and version of the
StoryBible, the plan (what each scene asked for), the requests (the same requests grouped, with
the scenes that made them), the catalog (for each character and environment with a request, its
default and the named looks or states it already has) and the `inputs` that are written onto
the version (D-3). The job loads the StoryBible, builds the request, asks the model **once** for
the whole project (so the answers agree with each other), checks the answer
(`services/look_state_resolution_writer.check_answer`), and saves it
(`services/look_state_resolution.save_resolution`) in the same transaction that marks the job
succeeded.

When every request asks for the default there is nothing to ask, so the model is not called and
the resolution is saved at once.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every story stage (D-12).
A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again with the Resolve button.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the story or the answer.
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
from app.services import discovery, llm_target, look_state_resolution
from app.services import look_state_resolution_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has nothing to resolve."
_NO_BIBLE = "The Story Bible this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `start_run` put on the job, checked."""

    plan: list[dict[str, Any]]
    requests: list[dict[str, Any]]
    catalog: dict[str, list[dict[str, Any]]]
    inputs: dict[str, Any]
    bible_id: int


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `start_run` writes is missing or the wrong
    shape (a job made by hand, or by an older version of the code).
    """
    plan = job_input.get("plan")
    requests = job_input.get("requests")
    catalog = job_input.get("catalog")
    inputs = job_input.get("inputs")
    bible_id = job_input.get("story_bible_id")
    if (
        not isinstance(plan, list)
        or not isinstance(requests, list)
        or not isinstance(catalog, dict)
        or not isinstance(catalog.get("looks"), list)
        or not isinstance(catalog.get("states"), list)
        or not isinstance(inputs, dict)
        or not isinstance(bible_id, int)
    ):
        return None
    return _Input(plan=plan, requests=requests, catalog=catalog, inputs=inputs, bible_id=bible_id)


class ResolveLooksStatesHandler(JobHandler):
    job_type = look_state_resolution.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(
        result: llm.ChatResult,
        requests: list[dict[str, Any]],
        catalog: dict[str, list[dict[str, Any]]],
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, checked answer)` when it can be stored, else `(why not,
        None)`.
        """
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = writer.parse_answer(result.content)
            return None, writer.check_answer(answer, requests, catalog)
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
            read = _read_input(job_input)
            bible = (
                await discovery.get_bible(session, project_id, read.bible_id)
                if project_id is not None and read is not None
                else None
            )
            bible_content = bible.content if bible is not None else None
            await session.commit()

        if project_id is None or read is None:
            await self._fail(job_id, _BAD_INPUT)
            return
        if bible_content is None:
            await self._fail(job_id, _NO_BIBLE)
            return

        usage: dict[str, Any] | None = None
        record: dict[str, Any] = {}
        checked: dict[str, Any] | None
        if read.requests:
            await self._phase(job_id, phases.PREPARING_PROMPT)
            body = writer.build_request(
                bible_content, read.requests, read.catalog, model=target.model
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
                lambda result: self._read(result, read.requests, read.catalog),
                timeout_s=REQUEST_TIMEOUT_S,
            )
            checked = outcome.value
            if checked is None:
                await self._fail(
                    job_id, f"The looks and states could not be resolved: {outcome.failure}"
                )
                return
            usage = outcome.usage
            record = outcome.record()
        else:
            # Nothing to decide: every request is the default.
            checked = {"new_looks": [], "new_states": [], "looks": {}, "states": {}}

        await self._phase(job_id, phases.SAVING_RESOLUTION)
        async with SessionLocal() as session:
            try:
                row = await look_state_resolution.save_resolution(
                    session,
                    project_id=project_id,
                    job_id=job_id,
                    inputs=read.inputs,
                    plan=read.plan,
                    catalog=read.catalog,
                    checked=checked,
                )
            except look_state_resolution.LookStateResolutionError as exc:
                await session.rollback()
                await self._fail(job_id, str(exc))
                return
            output = {
                **record,
                "content": None,
                "version": row.version,
                "requests": len(read.requests),
                "new_looks": len(checked["new_looks"]),
                "new_states": len(checked["new_states"]),
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version and its records are not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: looks and states resolved for project %d, version %d, usage=%s",
            job_id,
            project_id,
            row.version,
            usage,
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
