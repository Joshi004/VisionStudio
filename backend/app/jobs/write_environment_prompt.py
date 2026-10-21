"""The `write_environment_prompt` job (PHASE-012): a language model writes the prompt for a
library environment's canonical reference picture, from the card of the version the picture is
for, on the environment sheet profile (`image_prompt_profiles.ACTIVE_ENVIRONMENT_SHEET_PROFILE`).

Once the prompt is saved, the candidate pictures are started (four for a lab attempt, one for
an attempt the story pipeline made: `environment_references.on_prompt_written`); if the model
fails, the attempt is marked failed
(`on_prompt_failed`), so the page shows why instead of waiting forever. Reuses
`image_prompt_writer.py`'s reader and checks.

It is a paid call to the language model, so the rules in `jobs/llm_call.py` hold: at most 2
attempts, a refusal never retried, every answer saved the moment it arrives, and a restart
never re-runs it (`never_rerun`). A click writes the prompt again even when one exists
already: the job is created with `dedupe=False`, so two clicks make two jobs.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the prompt or the answer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import EnvironmentReference, LibraryEnvironmentVersion
from app.db.session import SessionLocal
from app.jobs import dispatcher, llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import environment_library, environment_references, llm_target
from app.services import environment_prompt_writer as writer
from app.services import image_prompt_writer as prompt_checks
from app.services.image_prompt_profiles import ACTIVE_ENVIRONMENT_SHEET_PROFILE
from app.services.image_prompt_writer import CheckedPrompt
from app.services.llm_target import IMAGE_PROMPT_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = environment_library.PROMPT_JOB
REQUEST_TIMEOUT_S: Final = 300.0

_NO_ENVIRONMENT = "The environment no longer exists."


def _reader(result: llm.ChatResult) -> tuple[str | None, CheckedPrompt | None]:
    if result.finish_reason == "length":
        return "The model's answer was cut off because it reached the token limit.", None
    try:
        answer = prompt_checks.parse_answer(result.content)
    except ValueError as exc:
        return str(exc), None
    checked = prompt_checks.check_prompt(answer, ACTIVE_ENVIRONMENT_SHEET_PROFILE)
    if checked is None:
        return (
            "The model's image prompt was empty or longer than "
            f"{prompt_checks.FIELD_MAX_CHARS:,} characters.",
            None,
        )
    return None, checked


class WriteEnvironmentPromptHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = IMAGE_PROMPT_MODEL_KEY

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            environment_id = job_input.get("environment_id")
            environment = (
                await environment_library.get_environment(session, environment_id)
                if isinstance(environment_id, int)
                else None
            )
            # The picture is made for one version, so the prompt describes that version as it
            # was frozen, never a later edit of the head (PHASE-013). An attempt with no
            # version (cannot happen: `start_reference` always sets one) falls back to the head.
            reference_id = job_input.get("reference_id")
            attempt = (
                await session.get(EnvironmentReference, reference_id)
                if isinstance(reference_id, int)
                else None
            )
            version = (
                await session.get(LibraryEnvironmentVersion, attempt.version_id)
                if attempt is not None
                else None
            )
            version_profile = dict(version.profile) if version is not None else None
            target = await llm_target.resolve(session, IMAGE_PROMPT_MODEL_KEY)
            await session.commit()

        if environment is None:
            await self._fail(job_id, _NO_ENVIRONMENT)
            return
        card = (
            environment_library.card_from_profile(version_profile)
            if version_profile is not None
            else environment_library.environment_card(environment)
        )

        await self._phase(job_id, phases.PREPARING_PROMPT)
        profile = ACTIVE_ENVIRONMENT_SHEET_PROFILE
        body = writer.build_request(writer.prompt_inputs(card), model=target.model, profile=profile)
        job_input.update(
            profile={"id": profile.id, "version": profile.version},
            instructions_sha256=llm_call.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, _reader, timeout_s=REQUEST_TIMEOUT_S
        )
        checked: CheckedPrompt | None = outcome.value
        if checked is None:
            await self._fail(
                job_id, f"The reference prompt could not be written: {outcome.failure}"
            )
            return

        await self._phase(job_id, phases.SAVING_ENVIRONMENT_PROMPT)
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

        if await environment_references.on_prompt_written(job_id):
            dispatcher.nudge()
        _logger.info(
            "job %d: environment prompt written: words=%d warnings=%d usage=%s",
            job_id,
            checked.word_count,
            len(checked.warnings),
            outcome.usage,
        )

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
        await environment_references.on_prompt_failed(job_id, message)
