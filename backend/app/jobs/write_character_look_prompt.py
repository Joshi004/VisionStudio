"""The `write_character_look_prompt` job: a language model writes one of two things for a
library character (ANALYSIS.md Phase 25), told apart by `job.input["requested"]`:

- `"master"`: the prompt for a look's master picture (`services/character_looks.start_look`),
  from the character's card, on the same profile the project's own cast reference uses
  (`image_prompt_profiles.ACTIVE_CHARACTER_SHEET_PROFILE`). Reuses `image_prompt_writer.py`'s
  reader and checks, like `write_character_reference_prompt.py` does. Once saved, the look's
  four candidate pictures are started (`character_looks.on_look_prompt_written`); if the model
  fails, the look is marked failed (`character_looks.on_look_prompt_failed`), so the drawer
  shows why instead of waiting forever. A look started from the author's own picture
  (`job.input["reference_image_id"]`) is written on the from-picture profile instead
  (`ACTIVE_CHARACTER_SHEET_FROM_PICTURE_PROFILE`): the image model is shown that picture.
- `"audition"`: a short line of dialogue to read aloud while auditioning a voice
  (`services/character_library.start_audition_line`). Only the job's own answer is saved: an
  author may edit the line before clicking to make the audition's samples
  (`character_library.start_auditions`), the same as any other step the author may edit first.

Both are a paid call to the language model, so the rules of `write_image_prompt` hold here too
(they are in `jobs/llm_call.py`): at most 2 attempts, a refusal never retried, every answer
saved the moment it arrives, and a restart never re-runs it (`never_rerun`). A click writes the
prompt or the line again even when one exists already (that is what "write again" is for): the
job type passes `dedupe=False` (`character_library.PROMPT_JOB`'s callers), so two clicks make
two jobs.

The instructions are in `services/character_look_prompt_writer.py`. It is a local-style job:
everything happens in `start`. Logs hold the job id, what each attempt did and its token
counts, never the prompt, the line or the answer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import dispatcher, llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.jobs.write_character_reference_prompt import MODEL_KEY
from app.providers import llm
from app.services import character_library, character_looks, description_writer, llm_target
from app.services import character_look_prompt_writer as writer
from app.services import image_prompt_writer as prompt_checks
from app.services.image_prompt_profiles import (
    ACTIVE_CHARACTER_SHEET_FROM_PICTURE_PROFILE,
    ACTIVE_CHARACTER_SHEET_PROFILE,
    ImagePromptProfile,
)
from app.services.image_prompt_writer import CheckedPrompt

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = character_library.PROMPT_JOB
REQUEST_TIMEOUT_S: Final = 300.0

_NO_CHARACTER = "The character no longer exists."
_NO_REQUEST = "This job does not say what to write."


def _master_reader(profile: ImagePromptProfile) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, CheckedPrompt | None]:
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = prompt_checks.parse_answer(result.content)
        except ValueError as exc:
            return str(exc), None
        checked = prompt_checks.check_prompt(answer, profile)
        if checked is None:
            return (
                "The model's image prompt was empty or longer than "
                f"{prompt_checks.FIELD_MAX_CHARS:,} characters.",
                None,
            )
        return None, checked

    return read


def _audition_reader(result: llm.ChatResult) -> tuple[str | None, writer.CheckedLine | None]:
    if result.finish_reason == "length":
        return "The model's answer was cut off because it reached the token limit.", None
    try:
        answer = writer.parse_audition_answer(result.content)
    except ValueError as exc:
        return str(exc), None
    checked = writer.check_audition_line(answer)
    if checked is None:
        return (
            "The model's audition line was empty or longer than "
            f"{writer.AUDITION_LINE_MAX_CHARS:,} characters.",
            None,
        )
    return None, checked


class WriteCharacterLookPromptHandler(JobHandler):
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
            requested = job_input.get("requested")
            character_id = job_input.get("character_id")
            character = (
                await character_library.get_character(session, character_id)
                if isinstance(character_id, int)
                else None
            )
            target = await llm_target.resolve(session, MODEL_KEY)
            await session.commit()

        if character is None:
            await self._fail(job_id, _NO_CHARACTER, requested=requested)
            return
        card = character_library.character_card(character)

        if requested == "master":
            await self._run_master(job_id, job_input, card, target, started)
        elif requested == "audition":
            await self._run_audition(job_id, job_input, card, target, started)
        else:
            await self._fail(job_id, _NO_REQUEST, requested=requested)

    # --- The look's master prompt ----------------------------------------------------

    async def _run_master(
        self,
        job_id: int,
        job_input: dict[str, Any],
        card: str,
        target: llm_target.LlmTarget,
        started: float,
    ) -> None:
        await self._phase(job_id, phases.PREPARING_PROMPT)
        profile = (
            ACTIVE_CHARACTER_SHEET_FROM_PICTURE_PROFILE
            if job_input.get("reference_image_id") is not None
            else ACTIVE_CHARACTER_SHEET_PROFILE
        )
        inputs = writer.prompt_inputs(card)
        body = writer.build_master_request(inputs, model=target.model, profile=profile)
        job_input.update(
            profile={"id": profile.id, "version": profile.version},
            instructions_sha256=description_writer.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, _master_reader(profile), timeout_s=REQUEST_TIMEOUT_S
        )
        checked: CheckedPrompt | None = outcome.value
        if checked is None:
            await self._fail(
                job_id,
                f"The look's master prompt could not be written: {outcome.failure}",
                requested="master",
            )
            return

        await self._phase(job_id, phases.SAVING_LOOK_PROMPT)
        output = {
            **outcome.record(),
            "content": None,
            "image_prompt": checked.text,
            "word_count": checked.word_count,
            "warnings": list(checked.warnings),
            "seconds": round(time.monotonic() - started, 1),
        }
        async with SessionLocal() as session:
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            await session.commit()

        started_candidates = await character_looks.on_look_prompt_written(job_id)
        if started_candidates:
            dispatcher.nudge()
        _logger.info(
            "job %d: look master prompt written: words=%d warnings=%d usage=%s",
            job_id,
            checked.word_count,
            len(checked.warnings),
            outcome.usage,
        )

    # --- The voice audition's sample line ---------------------------------------------

    async def _run_audition(
        self,
        job_id: int,
        job_input: dict[str, Any],
        card: str,
        target: llm_target.LlmTarget,
        started: float,
    ) -> None:
        await self._phase(job_id, phases.PREPARING_PROMPT)
        inputs = writer.prompt_inputs(card)
        body = writer.build_audition_request(inputs, model=target.model)
        job_input.update(
            instructions_sha256=description_writer.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, _audition_reader, timeout_s=REQUEST_TIMEOUT_S
        )
        checked: writer.CheckedLine | None = outcome.value
        if checked is None:
            await self._fail(
                job_id,
                f"The audition line could not be written: {outcome.failure}",
                requested="audition",
            )
            return

        await self._phase(job_id, phases.SAVING_AUDITION_LINE)
        output = {
            **outcome.record(),
            "content": None,
            "audition_line": checked.text,
            "word_count": checked.word_count,
            "warnings": list(checked.warnings),
            "seconds": round(time.monotonic() - started, 1),
        }
        async with SessionLocal() as session:
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            await session.commit()
        _logger.info(
            "job %d: audition line written: words=%d warnings=%d usage=%s",
            job_id,
            checked.word_count,
            len(checked.warnings),
            outcome.usage,
        )

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str, *, requested: str | None) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
        if requested == "master":
            await character_looks.on_look_prompt_failed(job_id, message)
