"""The paid call to the language model that the LLM jobs share (the prompt writers of the
Video lab and the Character Lab, and the story stages that follow).

The rules are those of the first paid job of the narration pipeline (ANALYSIS.md Section 6.2;
retired in PHASE-046 and readable at the git tag `narration-final`), written once here
because every LLM job needs them:

- At most `MAX_ATTEMPTS` attempts, the second only for a rate limit, a server error, no answer,
  or an answer that cannot be used. A refusal (HTTP 400, 401, 403, 404, 422) is never retried.
  The second attempt is told why the first answer could not be used (`with_correction`), so
  the model fixes that instead of guessing again. A caller can pass `correct=False` to opt out.
- Every answer is saved on the job (`store.record_output`) the moment it arrives, so a crash
  after the paid call still leaves the answer behind.
- Logs hold the job id, what each attempt did and its token counts, never the prompt or the
  answer.

The caller says what a usable answer is by passing `read`, and does everything with the answer
afterwards (these jobs differ only there). Nothing here is a handler: the jobs are.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Final

from app.db.session import SessionLocal
from app.jobs import phases, store
from app.providers import llm
from app.providers.llm import LlmCallError
from app.services import llm_target

_logger = logging.getLogger(__name__)

# One call, and one more if it fails in a way that can pass (ANALYSIS.md Section 5.8, 6.2).
MAX_ATTEMPTS: Final = 2
RETRY_DELAY_S: Final = 5.0
# The longest wait for the first piece of the answer, or between two pieces.
IDLE_TIMEOUT_S: Final = 120.0
RAW_CONTENT_MAX_CHARS: Final = 20_000

# Reads one answer: `(None, value)` when it can be used, else `(why not, None)`. The reason is
# shown to the user and kept on the job. `value` is a dataclass or plain JSON, so it can be kept.
ReadAnswer = Callable[[llm.ChatResult], tuple[str | None, Any]]


def instructions_sha256(body: dict[str, Any]) -> str:
    """The SHA-256 of the request's system message: a name for the instruction set that was used."""
    system = body["messages"][0]["content"]
    return "sha256:" + hashlib.sha256(system.encode("utf-8")).hexdigest()


@dataclass
class Outcome:
    """What asking the model came to. `value` is None when no usable answer was got."""

    value: Any | None = None
    # Why the model could not be used, when `value` is None.
    failure: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    # The raw text of the last answer that could not be used, for the job record.
    unusable_content: str | None = None
    # Tokens summed over the attempts that were answered. None when none was.
    usage: dict[str, int] | None = None

    def answer_json(self) -> Any | None:
        return asdict(self.value) if is_dataclass(self.value) else self.value

    def record(self) -> dict[str, Any]:
        """What the job's output holds about the call: everything but what the job made of it."""
        return {
            "attempts": self.attempts,
            "answer": self.answer_json(),
            "answer_usable": self.value is not None,
            "content": self.unusable_content,
            "usage": self.usage,
        }


def with_correction(body: dict[str, Any], problem: str) -> dict[str, Any]:
    """`body` with a note added to its last user message: why the earlier answer to the same
    request was refused. The refused answer itself is not sent back, so the request grows by a
    sentence only. `body` is not changed.
    """
    messages = [dict(message) for message in body["messages"]]
    note = (
        f"\n\nNOTE: An earlier answer to this request was refused: {problem} Write the whole "
        "answer again with that fixed, every required field present and every length limit kept."
    )
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            message["content"] += note
            break
    return {**body, "messages": messages}


def failure_text(exc: LlmCallError) -> str:
    """What to tell the user about a call that failed."""
    if exc.status_code is not None:
        return f"The language model answered HTTP {exc.status_code}: {exc.message}"
    return exc.message


async def ask_model(
    job_id: int,
    target: llm_target.LlmTarget,
    body: dict[str, Any],
    read: ReadAnswer,
    *,
    timeout_s: float,
    keep: dict[str, Any] | None = None,
    correct: bool = True,
) -> Outcome:
    """Sends `body` to `target` (up to `MAX_ATTEMPTS` times) until `read` accepts an answer.

    `keep` is for a job that makes several calls in a row: what the earlier calls came to. It is
    saved on the job's output next to this call's own record, every time progress is saved, so
    the paid answers of the earlier calls are not lost while a later call runs.

    With `correct` (the default), an attempt that follows an unusable answer is sent
    `with_correction`, and its record holds the reason it was given (`correction`).
    """
    outcome = Outcome()
    correction: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        await _phase(job_id, phases.asking_model(attempt, MAX_ATTEMPTS))
        started = time.monotonic()
        sent = with_correction(body, correction) if correction is not None else body
        try:
            result = await llm_target.complete(
                target, sent, timeout_s=timeout_s, idle_timeout_s=IDLE_TIMEOUT_S
            )
        except LlmCallError as exc:
            outcome.failure = failure_text(exc)
            outcome.attempts.append(
                {
                    "outcome": exc.kind,
                    "http_status": exc.status_code,
                    "message": exc.message,
                    "finish_reason": None,
                    "response_id": None,
                    "elapsed_s": round(time.monotonic() - started, 1),
                    "usage": None,
                    "correction": correction,
                }
            )
            _logger.info(
                "job %d: language model attempt %d failed: %s (HTTP %s)",
                job_id,
                attempt,
                exc.kind,
                exc.status_code,
            )
            await _save_progress(job_id, outcome, keep)
            if exc.kind == "refused":
                break  # asking again cannot help
        else:
            counts = llm.usage_counts(result.usage)
            _add_usage(outcome, counts)
            problem, value = read(result)
            outcome.attempts.append(
                {
                    "outcome": "unusable" if problem else "answered",
                    "http_status": 200,
                    "message": problem,
                    "finish_reason": result.finish_reason,
                    "response_id": result.response_id,
                    "elapsed_s": round(time.monotonic() - started, 1),
                    "usage": counts,
                    "correction": correction,
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
                outcome.value = value
                outcome.failure = None
                # The paid answer is saved before anything else happens to it.
                await _save_progress(job_id, outcome, keep)
                return outcome
            outcome.failure = problem
            outcome.unusable_content = result.content[:RAW_CONTENT_MAX_CHARS]
            if correct:
                correction = problem
            await _save_progress(job_id, outcome, keep)

        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(RETRY_DELAY_S)
    return outcome


def _add_usage(outcome: Outcome, counts: dict[str, int | None]) -> None:
    total = outcome.usage or {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0}
    for key in total:
        total[key] += counts.get(key) or 0
    outcome.usage = total


async def _save_progress(job_id: int, outcome: Outcome, keep: dict[str, Any] | None = None) -> None:
    """Writes what is known so far to `job.output`. The final output replaces it."""
    async with SessionLocal() as session:
        await store.record_output(session, job_id, {**(keep or {}), **outcome.record()})


async def _phase(job_id: int, phase: str) -> None:
    async with SessionLocal() as session:
        await store.set_phase(session, job_id, phase, status="running")
