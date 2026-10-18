"""The Qwen3.8 text model on the GPU server (guide 0.16.0, `POST /v1/qwen38/generate`).

Unlike Bitdeer, it does not speak the OpenAI chat protocol. It is a normal GPU server job:
submit the messages, poll `GET /v1/jobs/{id}`, then download the JSON result. `complete` hides
those three steps and returns the same `llm.ChatResult` as `llm.complete`, so a job can use
either one and read the answer the same way.

The jobs build one OpenAI-style request body (model, messages, max_tokens, stream,
response_format, reasoning_effort). `to_request` keeps the messages and the token limit and
drops what only Bitdeer understands. Reasoning is always on ("thinking" mode), which is the
setting the server recommends for planning and writing.

`complete` makes **one** attempt, like `llm.complete`: the retry belongs to the job.

The server starts on demand and stops after idle minutes. A request that arrives while it is
stopped stays `queued` for 3 to 10 minutes, so the wait allows for that on top of the time
the caller gives the model itself.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Final

from app.providers import gpu_server, llm
from app.providers.gpu_server import GpuCallError
from app.providers.llm import ChatResult, LlmCallError

_logger = logging.getLogger(__name__)

GENERATE_PATH: Final = "/v1/qwen38/generate"
MODEL_ID: Final = "Qwen/Qwen3.8-27B-FP8"
# The server refuses more than this, and the limit includes the reasoning tokens.
MAX_TOKENS_CAP: Final = 16384
# The server refuses messages longer than this in total.
MESSAGES_MAX_CHARS: Final = 32000
# A stopped server takes 3 to 10 minutes to start, and the job waits `queued` meanwhile.
COLD_START_ALLOWANCE_S: Final = 600.0
# The guide: every 2-3 s once the server is up, every 10-15 s while it starts.
POLL_RUNNING_S: Final = 3.0
POLL_QUEUED_S: Final = 10.0


def prompt_chars(body: dict[str, Any]) -> int:
    """The total length of the message texts, the number the server limits."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return 0
    total = 0
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            total += len(content)
    return total


def to_request(body: dict[str, Any]) -> dict[str, Any]:
    """The Qwen3.8 request for an OpenAI-style body."""
    max_tokens = body.get("max_tokens")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        max_tokens = MAX_TOKENS_CAP
    return {
        "messages": body["messages"],
        "thinking": True,
        "include_reasoning": False,
        "max_tokens": min(max_tokens, MAX_TOKENS_CAP),
    }


def _to_llm_error(exc: GpuCallError) -> LlmCallError:
    """What a GPU server error means for a language model call."""
    kind: llm.LlmErrorKind
    if exc.kind == "unreachable":
        kind = "unreachable"
    elif exc.kind == "busy":
        kind = "rate_limited"
    elif exc.kind == "server_error":
        kind = "server_error"
    elif exc.kind == "rejected":
        kind = "refused"
    else:
        kind = "bad_answer"
    return LlmCallError(kind, exc.message, exc.status_code)


async def _cancel_quietly(base_url: str, job_id: str) -> None:
    """Asks the server to drop a request nobody waits for any more. Never raises."""
    try:
        await gpu_server.cancel_job(base_url, job_id)
    except GpuCallError:
        _logger.info("qwen38 job %s could not be cancelled", job_id)


async def _wait_for_job(base_url: str, job_id: str, deadline: float) -> None:
    """Polls until the job has succeeded. Raises `LlmCallError` if it failed or ran out of time."""
    delay = POLL_QUEUED_S
    while True:
        if time.monotonic() >= deadline:
            await _cancel_quietly(base_url, job_id)
            raise LlmCallError("unreachable", "The Qwen3.8 model did not answer in time.")
        try:
            status = await gpu_server.job_status(base_url, job_id)
        except GpuCallError as exc:
            if exc.kind != "unreachable":
                raise _to_llm_error(exc) from exc
            delay = POLL_QUEUED_S  # a short outage: keep waiting, the deadline still applies
        else:
            if status.status == "succeeded":
                return
            if status.status == "failed":
                message = status.error or "The Qwen3.8 request failed on the GPU server."
                raise LlmCallError("server_error", message)
            delay = POLL_QUEUED_S if status.status == "queued" else POLL_RUNNING_S
        await asyncio.sleep(min(delay, max(0.0, deadline - time.monotonic())))


def _read_result(job_id: str, result: dict[str, Any]) -> ChatResult:
    content = result.get("content")
    finish_reason = result.get("finish_reason")
    usage = result.get("usage")
    return ChatResult(
        content=content if isinstance(content, str) else "",
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        usage=usage if isinstance(usage, dict) else None,
        response_id=job_id,
    )


async def complete(base_url: str, body: dict[str, Any], *, timeout_s: float) -> ChatResult:
    """Asks Qwen3.8 on the GPU server and returns its text.

    `timeout_s` is the time the model may take. The wait also allows for a cold server start.
    Raises `LlmCallError` for anything that is not a usable answer. An answer with no text is
    returned with `content == ""` so the caller can record its `finish_reason`.
    """
    chars = prompt_chars(body)
    if chars > MESSAGES_MAX_CHARS:
        raise LlmCallError(
            "refused",
            f"The prompt is {chars:,} characters long, and the Qwen3.8 model accepts at most "
            f"{MESSAGES_MAX_CHARS:,}. Use Bitdeer for this one, or shorten the script.",
        )

    deadline = time.monotonic() + timeout_s + COLD_START_ALLOWANCE_S
    try:
        job_id = await gpu_server.submit_job(base_url, GENERATE_PATH, to_request(body))
    except GpuCallError as exc:
        raise _to_llm_error(exc) from exc

    try:
        await _wait_for_job(base_url, job_id, deadline)
        result = await gpu_server.job_result_json(base_url, job_id)
    except GpuCallError as exc:
        raise _to_llm_error(exc) from exc
    except asyncio.CancelledError:
        await _cancel_quietly(base_url, job_id)
        raise
    return _read_result(job_id, result)
