"""The `write_talk_prompts` job: a language model writes the two prompts of a take in the
Talking character lab (Phase 24): the instruction for the speech model and the prompt for the
lip-sync video model.

It belongs to no project (`job.project_id` is NULL). The texts are in `job.output`
(`voice_instruction`, `video_prompt`, `warnings`): the page puts them into the lab form, where
the author edits them before running anything, and a take that was started with this job has
them copied onto it when the job finishes (`talk_lab.on_prompts_written`), which also starts the
take's next step when it is set to continue by itself. It is a paid call (ANALYSIS.md Section
6.2), so the same rules as the Video lab's prompt job hold:

- It only starts from a click (`POST /api/lab/talk/prompt-drafts` or a take).
- Every answer is saved on the job (`record_output`) the moment it arrives, before anything
  is checked, so a crash after the paid call still leaves the answer behind.
- At most 2 attempts, the second only for a rate limit, a server error, no answer, or an
  answer that cannot be used. A refusal (HTTP 400, 401, 403, 404, 422) is never retried.
- A restart never re-runs it (`never_rerun`): the dispatcher fails it with a message.

There is no cache: each click is a new paid try on purpose (the lab is for trying ideas), and
there is no rule-based fallback, so two failed attempts fail the job.

The instructions are in `services/talk_prompt_writer.py` and `services/talk_prompt_profiles.py`.
This job stores the profile's id and version, a hash of the instructions and the exact request.

It is a local-style job: everything happens in `start`. There is no provider job id. Logs hold
the job id, what each attempt did and its token counts, never the dialogue or the answer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Final

from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import dispatcher, phases, store
from app.jobs.draft_descriptions import DESCRIPTION_MODEL_KEY
from app.jobs.handlers import JobHandler
from app.jobs.plan_scenes import LLM_URL_KEY
from app.jobs.write_lab_video_prompt import (
    IDLE_TIMEOUT_S,
    MAX_ATTEMPTS,
    RAW_CONTENT_MAX_CHARS,
    REQUEST_TIMEOUT_S,
    RETRY_DELAY_S,
)
from app.providers import llm
from app.providers.llm import LlmCallError
from app.services import description_writer, talk_lab
from app.services import talk_prompt_writer as writer
from app.services.talk_prompt_profiles import ACTIVE_TALK_PROFILE, TalkPromptProfile
from app.services.talk_prompt_writer import CheckedPrompts

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = talk_lab.PROMPT_JOB


@dataclass
class _Outcome:
    """What getting the prompts came to. `checked` is None when none could be used."""

    checked: CheckedPrompts | None = None
    # Set only when a call was paid for and its answer was usable.
    answer: dict[str, Any] | None = None
    # Why the model could not be used, when `checked` is None.
    failure: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    # The raw text of the last answer that could not be used, for the job record.
    unusable_content: str | None = None
    # Tokens summed over the attempts that were answered. None when none was.
    usage: dict[str, int] | None = None


def _failure_text(exc: LlmCallError) -> str:
    """What to tell the user about a call that failed."""
    if exc.status_code is not None:
        return f"The language model answered HTTP {exc.status_code}: {exc.message}"
    return exc.message


def _read_answer(
    result: llm.ChatResult, inputs: dict[str, Any], profile: TalkPromptProfile
) -> tuple[str | None, dict[str, Any] | None, CheckedPrompts | None]:
    """Whether an answer can be used: `(None, answer, checked)` if so, else `(why not, None,
    None)`. The first value is the reason, which is shown to the user and kept on the job.
    """
    if result.finish_reason == "length":
        return "The model's answer was cut off because it reached the token limit.", None, None
    try:
        answer = writer.parse_answer(result.content)
        checked = writer.check_prompts(answer, inputs, profile)
    except ValueError as exc:
        return str(exc), None, None
    return None, answer, checked


class WriteTalkPromptsHandler(JobHandler):
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
            base_url = await settings_service.get_str(session, LLM_URL_KEY)
            # The same model as the scene descriptions: it writes video prompts too.
            model = await settings_service.get_str(session, DESCRIPTION_MODEL_KEY)
            await session.commit()

        await self._phase(job_id, phases.PREPARING_PROMPT)
        profile = ACTIVE_TALK_PROFILE
        inputs = job_input.get("inputs")
        if not isinstance(inputs, dict):
            await self._fail(job_id, "The request for the prompts is missing.")
            return
        body = writer.build_request(inputs, model=model, profile=profile)
        job_input.update(
            profile={"id": profile.id, "version": profile.version},
            instructions_sha256=description_writer.instructions_sha256(body),
            server_url=docker_mapped(base_url),
            endpoint=llm.CHAT_PATH,
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await self._ask_model(job_id, inputs, profile, base_url, body)
        checked = outcome.checked
        if checked is None:
            await self._fail(job_id, f"The prompts could not be written: {outcome.failure}")
            return

        if await self._save(job_id, outcome, checked, started):
            await self._continue_take(job_id)

    # --- Asking the model -----------------------------------------------------------

    async def _ask_model(
        self,
        job_id: int,
        inputs: dict[str, Any],
        profile: TalkPromptProfile,
        base_url: str,
        body: dict[str, Any],
    ) -> _Outcome:
        outcome = _Outcome()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            await self._phase(job_id, phases.asking_model(attempt, MAX_ATTEMPTS))
            started = time.monotonic()
            try:
                result = await llm.complete(
                    base_url, body, timeout_s=REQUEST_TIMEOUT_S, idle_timeout_s=IDLE_TIMEOUT_S
                )
            except LlmCallError as exc:
                outcome.failure = _failure_text(exc)
                outcome.attempts.append(
                    {
                        "outcome": exc.kind,
                        "http_status": exc.status_code,
                        "message": exc.message,
                        "finish_reason": None,
                        "response_id": None,
                        "elapsed_s": round(time.monotonic() - started, 1),
                        "usage": None,
                    }
                )
                _logger.info(
                    "job %d: language model attempt %d failed: %s (HTTP %s)",
                    job_id,
                    attempt,
                    exc.kind,
                    exc.status_code,
                )
                await self._save_progress(job_id, outcome)
                if exc.kind == "refused":
                    break  # asking again cannot help
            else:
                counts = llm.usage_counts(result.usage)
                self._add_usage(outcome, counts)
                await self._phase(job_id, phases.CHECKING_TALK_PROMPTS)
                problem, answer, checked = _read_answer(result, inputs, profile)
                outcome.attempts.append(
                    {
                        "outcome": "unusable" if problem else "answered",
                        "http_status": 200,
                        "message": problem,
                        "finish_reason": result.finish_reason,
                        "response_id": result.response_id,
                        "elapsed_s": round(time.monotonic() - started, 1),
                        "usage": counts,
                    }
                )
                _logger.info(
                    "job %d: language model attempt %d: %s, finish=%s, tokens prompt=%s "
                    "completion=%s reasoning=%s, %.1f s",
                    job_id,
                    attempt,
                    "unusable" if problem else "answered",
                    result.finish_reason,
                    counts["prompt_tokens"],
                    counts["completion_tokens"],
                    counts["reasoning_tokens"],
                    time.monotonic() - started,
                )
                if problem is None:
                    outcome.checked = checked
                    outcome.answer = answer
                    outcome.failure = None
                    # The paid answer is saved before anything else happens to it.
                    await self._save_progress(job_id, outcome)
                    return outcome
                outcome.failure = problem
                outcome.unusable_content = result.content[:RAW_CONTENT_MAX_CHARS]
                await self._save_progress(job_id, outcome)

            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY_S)
        return outcome

    @staticmethod
    def _add_usage(outcome: _Outcome, counts: dict[str, int | None]) -> None:
        total = outcome.usage or {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0}
        for key in total:
            total[key] += counts.get(key) or 0
        outcome.usage = total

    @staticmethod
    async def _save_progress(job_id: int, outcome: _Outcome) -> None:
        """Writes what is known so far to `job.output`. The final output replaces it."""
        async with SessionLocal() as session:
            await store.record_output(
                session,
                job_id,
                {
                    "attempts": outcome.attempts,
                    "answer": outcome.answer,
                    "answer_usable": outcome.answer is not None,
                    "content": outcome.unusable_content,
                    "usage": outcome.usage,
                },
            )

    # --- Finishing --------------------------------------------------------------------

    async def _save(
        self, job_id: int, outcome: _Outcome, checked: CheckedPrompts, started: float
    ) -> bool:
        """Puts the prompts in the job's output and finishes the job. False when the job was no
        longer running (it was cancelled in the meantime).
        """
        output: dict[str, Any] = {
            "answer": outcome.answer,
            "answer_usable": outcome.answer is not None,
            "content": None,
            "attempts": outcome.attempts,
            "usage": outcome.usage,
            "voice_instruction": checked.voice_instruction,
            "video_prompt": checked.video_prompt,
            "word_count": checked.word_count,
            "warnings": list(checked.warnings),
            "seconds": round(time.monotonic() - started, 1),
        }
        async with SessionLocal() as session:
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return False
            await session.commit()
        _logger.info(
            "job %d: talk prompts written: words=%d warnings=%d usage=%s",
            job_id,
            checked.word_count,
            len(checked.warnings),
            outcome.usage,
        )
        return True

    @staticmethod
    async def _continue_take(job_id: int) -> None:
        """Copies the prompts onto the take this job was started for, and starts its next step
        when it is set to continue by itself. Best effort: a failure here never fails the job
        (the prompts are saved), and the take's next step can be started by hand.
        """
        try:
            started = await talk_lab.on_prompts_written(job_id)
        except Exception:
            _logger.exception("job %d: the take could not continue after its prompts", job_id)
            return
        if started:
            dispatcher.nudge()

    # --- Small helpers ----------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
