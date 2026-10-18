"""The `write_character_take_prompt` job: a language model writes the texts a take of a library
character still needs (ANALYSIS.md Phase 25): an image prompt, a video prompt, a delivery
instruction, or several of these together, exactly the set `character_take_prompt_writer.
needed_keys` says the take's remaining steps need (`services/character_takes._start_prompts`
already works this out and renders the character's card, so this job only has to ask the
model and save what it writes).

For a MiniMax H3 take the model gives the pieces of H3's structured prompt and the writer
assembles them, so `output.video_prompt` is the finished text. A take of H3 may also need a
`last_frame_prompt`, the instruction that edits its first frame into its last.

A paid call, so the rules of `write_image_prompt` hold here too (they are in
`jobs/llm_call.py`): at most 2 attempts, a refusal never retried, every answer saved the moment
it arrives, and a restart never re-runs it (`never_rerun`): the take's own "continue" step asks
again by starting a fresh job, never by resuming this one.

Once saved, the take's next step is started if it is set to continue by itself
(`character_takes.on_prompts_written`). A text the model could not write at all fails the job;
the take's own job (shown on it) tells the author why, and "continue" starts a new prompt job.

The instructions are in `services/character_take_prompt_writer.py`. It is a local-style job:
everything happens in `start`. Logs hold the job id, what each attempt did and its token
counts, never the prompts, the dialogue or the answer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import dispatcher, llm_call, phases, store
from app.jobs.draft_descriptions import DESCRIPTION_MODEL_KEY
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import character_take_prompt_writer as writer
from app.services import character_takes, description_writer, llm_target

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = character_takes.TAKE_PROMPT_JOB
REQUEST_TIMEOUT_S: Final = 300.0

_BAD_INPUT = "This job has no texts to write."


def _reader(inputs: dict[str, Any]) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, writer.CheckedTakePrompts | None]:
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = writer.parse_answer(result.content, inputs)
        except ValueError as exc:
            return str(exc), None
        try:
            checked = writer.check_prompts(answer, inputs)
        except ValueError as exc:
            return str(exc), None
        return None, checked

    return read


class WriteCharacterTakePromptHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            inputs = job_input.get("inputs")
            target = await llm_target.resolve(session, DESCRIPTION_MODEL_KEY)
            await session.commit()

        if not isinstance(inputs, dict) or not isinstance(inputs.get("needed"), list):
            await self._fail(job_id, _BAD_INPUT)
            return
        needed = frozenset(inputs["needed"])

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = writer.build_request(inputs, model=target.model)
        job_input.update(
            instructions_sha256=description_writer.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, _reader(inputs), timeout_s=REQUEST_TIMEOUT_S
        )
        checked: writer.CheckedTakePrompts | None = outcome.value
        if checked is None:
            await self._fail(job_id, f"The take's prompts could not be written: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_TAKE_PROMPTS)
        output = {
            **outcome.record(),
            "content": None,
            "image_prompt": checked.image_prompt,
            "last_frame_prompt": checked.last_frame_prompt,
            "video_prompt": checked.video_prompt,
            "delivery_instruction": checked.delivery_instruction,
            "warnings": list(checked.warnings),
            "seconds": round(time.monotonic() - started, 1),
        }
        async with SessionLocal() as session:
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            await session.commit()

        started_next = await character_takes.on_prompts_written(job_id)
        if started_next:
            dispatcher.nudge()
        _logger.info(
            "job %d: take prompts written: keys=%s warnings=%d usage=%s",
            job_id,
            sorted(needed),
            len(checked.warnings),
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
