"""The `design_voice` job: a language model writes the description a story voice is designed
from, and code starts the one design-mode sample that becomes the saved voice (PHASE-011).

`services/story_voices` creates the job with the `subject` (`character` or `narrator`), the
`facts` the description is written from, the `line` the sample will read, and the `inputs` that
are recorded on the voice (D-3). The job asks the model, checks the answer, and in the same
transaction that marks the job succeeded it queues the Voice lab run that makes the sample
(`story_voices.queue_sample`). When that run's speech is stored, `lab_voice` calls
`story_voices.on_voice_finished`, which saves the voice and attaches it.

One job per voice, so voices are designed side by side when the pools allow
(`store.create_job` with `dedupe_key`). The model is the **story role**
(`llm_target.STORY_MODEL_KEY`), like every story stage (D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by pressing the button again.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the facts or the answer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import dispatcher, llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, story_voices
from app.services import voice_design_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 300.0

_BAD_INPUT = "This job has no voice to design."


def _read_answer(result: llm.ChatResult, warnings: list[str]) -> tuple[str | None, str | None]:
    """Reads one answer: `(None, description)` when it can be used, else `(why not, None)`.
    What had to be cut from a usable answer is put in `warnings` (replacing earlier ones).
    """
    if result.finish_reason == "length":
        return "The model's answer was cut off because it reached the token limit.", None
    found: list[str] = []
    try:
        instruction = writer.check_instruction(writer.parse_answer(result.content), found)
    except ValueError as exc:
        return str(exc), None
    warnings[:] = found
    return None, instruction


class DesignVoiceHandler(JobHandler):
    job_type = story_voices.JOB_TYPE
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

        subject = job_input.get("subject")
        facts = job_input.get("facts")
        if subject not in ("character", "narrator") or not isinstance(facts, dict):
            await self._fail(job_id, _BAD_INPUT)
            return
        name = str(job_input.get("name") or subject)

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = writer.build_request(subject, facts, model=target.model)
        job_input.update(
            instructions_sha256=llm_call.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        warnings: list[str] = []
        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            lambda result: _read_answer(result, warnings),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        instruction: str | None = outcome.value
        if instruction is None:
            await self._fail(
                job_id, f"The voice description of {name} could not be written: {outcome.failure}"
            )
            return

        await self._phase(job_id, phases.SAVING_VOICE_DESCRIPTION)
        async with SessionLocal() as session:
            try:
                run_id = await story_voices.queue_sample(session, job_id, job_input, instruction)
            except story_voices.StoryVoiceError as exc:
                await session.rollback()
                await self._fail(job_id, f"The sample of {name} could not be started: {exc}")
                return
            output = {
                **outcome.record(),
                "content": None,
                "warnings": warnings,
                "instruction": instruction,
                "run_id": run_id,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the sample is not started.
                await session.rollback()
                return
            await session.commit()
        dispatcher.nudge()

        _logger.info(
            "job %d: voice description written for %s: run=%d usage=%s",
            job_id,
            job_input.get("target"),
            run_id,
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
