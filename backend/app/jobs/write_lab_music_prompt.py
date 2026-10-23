"""The `write_lab_music_prompt` job: a language model turns a brief into the prompt fields of one
music model (`inputs.model`), for the Music lab.

It is `write_lab_video_prompt` for sound, and it follows the same rules. It belongs to no
project (`job.project_id` is NULL): the fields are in `job.output` (`fields`, `warnings`) and the
page puts them into the lab form, where the author edits them before running anything. It is a
paid call (ANALYSIS.md Section 6.2), so:

- It only starts from a click (`POST /api/lab/music/prompt-drafts`).
- Every answer is saved on the job (`record_output`) the moment it arrives, before anything is
  checked, so a crash after the paid call still leaves the answer behind.
- At most 2 attempts, the second only for a rate limit, a server error, no answer, or an answer
  that cannot be used. A refusal (HTTP 400, 401, 403, 404, 422) is never retried.
- A restart never re-runs it (`never_rerun`): the dispatcher fails it with a message.

There is no cache (each click is a new paid try on purpose, the lab is for trying ideas) and no
rule-based fallback, so two failed attempts fail the job.

The instructions, and everything that depends on the music model, are in
`services/music_prompt_writer.py` and `services/music_prompt_profiles.py`. This job stores the
profile's id and version, a hash of the instructions and the exact request. The model is the
same one that writes the scene descriptions (`DESCRIPTION_MODEL_KEY`, GLM-5.3 by default).

It is a local-style job: everything happens in `start`. There is no provider job id. Logs hold
the job id, what each attempt did and its token counts, never the brief or the answer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.providers.llm import LlmCallError
from app.services import llm_target, music_models
from app.services import music_prompt_writer as writer
from app.services.llm_target import DESCRIPTION_MODEL_KEY
from app.services.music_prompt_profiles import MusicPromptProfile, profile_for
from app.services.music_prompt_writer import CheckedFields

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "write_lab_music_prompt"

# One call, and one more if it fails in a way that can pass (ANALYSIS.md Section 5.8, 6.2).
MAX_ATTEMPTS: Final = 2
RETRY_DELAY_S: Final = 5.0
# The same limits as the other jobs that use this model: a call that times out is paid for and
# lost, and the answer is streamed, so these bound the whole call and the silences.
REQUEST_TIMEOUT_S: Final = 300.0
IDLE_TIMEOUT_S: Final = 120.0
RAW_CONTENT_MAX_CHARS: Final = 20_000


@dataclass
class _Outcome:
    """What getting the fields came to. `checked` is None when none could be used."""

    checked: CheckedFields | None = None
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
    result: llm.ChatResult, brief: dict[str, Any], profile: MusicPromptProfile
) -> tuple[str | None, dict[str, Any] | None, CheckedFields | None]:
    """Whether an answer can be used: `(None, answer, checked)` if so, else `(why not, None,
    None)`. The first value is the reason, which is shown to the user and kept on the job.
    """
    if result.finish_reason == "length":
        return "The model's answer was cut off because it reached the token limit.", None, None
    try:
        answer = writer.parse_answer(result.content, profile)
    except ValueError as exc:
        return str(exc), None, None
    return None, answer, writer.check_fields(answer, brief, profile)


class WriteLabMusicPromptHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = DESCRIPTION_MODEL_KEY

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            # The same model as the scene descriptions.
            target = await llm_target.resolve(session, DESCRIPTION_MODEL_KEY)
            await session.commit()

        await self._phase(job_id, phases.PREPARING_PROMPT)
        inputs = job_input.get("inputs")
        model = inputs.get("model") if isinstance(inputs, dict) else None
        brief = inputs.get("brief") if isinstance(inputs, dict) else None
        if not isinstance(inputs, dict) or not music_models.is_music_model(model):
            await self._fail(job_id, "The request for the prompt is missing.")
            return
        if not isinstance(brief, dict):
            await self._fail(job_id, "The brief for the prompt is missing.")
            return
        profile = profile_for(model)
        body = writer.build_request(inputs, model=target.model, profile=profile)
        job_input.update(
            profile={"id": profile.id, "version": profile.version},
            instructions_sha256=llm_call.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await self._ask_model(job_id, brief, profile, target, body)
        checked = outcome.checked
        if checked is None:
            await self._fail(job_id, f"The prompt could not be written: {outcome.failure}")
            return

        await self._save(job_id, model, outcome, checked, started)

    # --- Asking the model -----------------------------------------------------------

    async def _ask_model(
        self,
        job_id: int,
        brief: dict[str, Any],
        profile: MusicPromptProfile,
        target: llm_target.LlmTarget,
        body: dict[str, Any],
    ) -> _Outcome:
        outcome = _Outcome()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            await self._phase(job_id, phases.asking_model(attempt, MAX_ATTEMPTS))
            started = time.monotonic()
            try:
                result = await llm_target.complete(
                    target, body, timeout_s=REQUEST_TIMEOUT_S, idle_timeout_s=IDLE_TIMEOUT_S
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
                await self._phase(job_id, phases.CHECKING_MUSIC_PROMPT)
                problem, answer, checked = _read_answer(result, brief, profile)
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
        self,
        job_id: int,
        model: str,
        outcome: _Outcome,
        checked: CheckedFields,
        started: float,
    ) -> None:
        """Puts the fields in the job's output and finishes the job."""
        output: dict[str, Any] = {
            "model": model,
            "fields": checked.fields,
            "warnings": list(checked.warnings),
            "answer": outcome.answer,
            "answer_usable": outcome.answer is not None,
            "content": None,
            "attempts": outcome.attempts,
            "usage": outcome.usage,
            "seconds": round(time.monotonic() - started, 1),
        }
        async with SessionLocal() as session:
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            await session.commit()
        _logger.info(
            "job %d: lab music prompt written: model=%s warnings=%d usage=%s",
            job_id,
            model,
            len(checked.warnings),
            outcome.usage,
        )

    # --- Small helpers ----------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
