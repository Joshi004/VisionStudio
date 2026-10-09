"""The language model client (ANALYSIS.md Section 6.4, `LLM.complete`).

It speaks the OpenAI-compatible chat completions protocol, so any such server works: the
default is Bitdeer, and the address and model come from Settings. The call goes through
`outbound.request`, which maps `localhost`, enforces the URL, size and time rules, never
follows a redirect, and attaches the Bitdeer key only for `api-inference.bitdeer.ai`
(Section 3.7). The `openai` SDK is deliberately not used: it would set `Authorization`
itself and so get around those rules.

`complete` makes **one** attempt. The retries (at most one, Section 6.2 rule 4) belong to
the job, because a paid call must be recorded on the job after every attempt.

The request asks for a streamed answer (`"stream": true`, server-sent events). A reasoning
model can take minutes over a long answer, and an answer that is sent in one piece cannot
tell "still working" from "stuck". Streamed, it arrives as it is written, so there are two
limits: `timeout_s` for the whole call and `idle_timeout_s` for the silence between two
pieces. The stream is read to its end and returned as one `ChatResult`, so callers do not
see the difference. A server that ignores `"stream": true` and answers with one JSON object
is still understood.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.core import outbound
from app.core.urls import docker_mapped, join_url

CHAT_PATH: Final = "/chat/completions"
MESSAGE_MAX_CHARS: Final = 500
# A streamed answer carries the model's reasoning too, and every piece is wrapped in about
# 250 bytes of JSON for roughly one token (measured on Bitdeer). The largest request asks for
# 32,000 tokens, which is about 8 MB, so this leaves room to spare.
ANSWER_MAX_BYTES: Final = 24 * 1024 * 1024

LlmErrorKind = Literal["unreachable", "rate_limited", "server_error", "refused", "bad_answer"]


class LlmCallError(Exception):
    """A call that did not give an answer. `kind` says whether trying again can help:

    - `unreachable`, `rate_limited`, `server_error`, `bad_answer`: it can.
    - `refused`: it cannot. The server rejected the request (HTTP 400, 401, 403, 404, 422
      and the other 4xx), or the address itself breaks a rule (a redirect, a bad URL).

    `str(error)` is readable by the user.
    """

    def __init__(self, kind: LlmErrorKind, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.kind: LlmErrorKind = kind
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class ChatResult:
    content: str  # may be empty, for example when the answer was cut off
    finish_reason: str | None
    usage: dict[str, Any] | None
    response_id: str | None


def chat_url(base_url: str) -> str:
    """The address a chat call goes to, after Docker mapping."""
    return docker_mapped(join_url(base_url, CHAT_PATH))


def _error_message(response: outbound.OutboundResponse) -> str:
    """The server's explanation of an error, in whichever form it came, or a plain fallback."""
    text = ""
    try:
        body = response.json()
    except (ValueError, RecursionError):
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        candidates = [
            error.get("message") if isinstance(error, dict) else error,
            body.get("detail"),
            body.get("message"),
        ]
        text = next((item for item in candidates if isinstance(item, str) and item.strip()), "")
    text = text.strip() or f"The server answered HTTP {response.status_code}."
    return text[:MESSAGE_MAX_CHARS]


def _error_for(response: outbound.OutboundResponse) -> LlmCallError:
    status = response.status_code
    message = _error_message(response)
    if status == 429:
        return LlmCallError("rate_limited", message, status)
    if status >= 500:
        return LlmCallError("server_error", message, status)
    if status >= 400:
        return LlmCallError("refused", message, status)
    return LlmCallError(
        "bad_answer", f"The server answered HTTP {status}, which was not expected.", status
    )


def _transport_error(exc: outbound.OutboundError) -> LlmCallError:
    if exc.reason in ("connection", "timeout"):
        return LlmCallError("unreachable", str(exc))
    if exc.reason == "too_large":
        return LlmCallError("bad_answer", str(exc))
    return LlmCallError("refused", str(exc))  # a bad address, or a redirect


async def complete(
    base_url: str, body: dict[str, Any], *, timeout_s: float, idle_timeout_s: float
) -> ChatResult:
    """Sends one chat completion request and returns the model's text.

    `timeout_s` limits the whole call and `idle_timeout_s` the wait for the first piece of
    the answer and the silence between two pieces after it.

    Raises `LlmCallError` for anything that is not a usable answer. An answer with no text
    is returned with `content == ""` so the caller can record its `finish_reason`.
    """
    try:
        response = await outbound.request(
            "POST",
            join_url(base_url, CHAT_PATH),
            json=body,
            timeout_s=timeout_s,
            idle_timeout_s=idle_timeout_s,
            max_bytes=ANSWER_MAX_BYTES,
        )
    except outbound.OutboundError as exc:
        raise _transport_error(exc) from exc

    if response.status_code != 200:
        raise _error_for(response)
    text = response.body.decode("utf-8", errors="replace")
    if text.lstrip().startswith("{"):
        return _read_whole_answer(response)  # the server ignored "stream": true
    return _read_stream(text)


def _stream_error_message(error: object) -> str:
    """The explanation inside an error piece of a stream, or a plain fallback."""
    message = error.get("message") if isinstance(error, dict) else error
    if isinstance(message, str) and message.strip():
        text = message.strip()
    else:
        text = "The server reported an error while it was answering."
    return text[:MESSAGE_MAX_CHARS]


def _read_stream(text: str) -> ChatResult:
    """Joins a streamed answer (server-sent events) into one `ChatResult`.

    Each piece is a line `data: {json}`. Its `choices[0].delta.content` is a piece of the
    answer, and `delta.reasoning_content` (the model thinking aloud) is left out. The piece
    with the `finish_reason` and the last one, which has the token counts and no choices,
    are read the same way. The stream ends with `data: [DONE]`. Blank lines and `:` comment
    lines (keep-alives) are skipped.

    Raises `LlmCallError` for an error piece, a piece that is not JSON, an answer that is not
    a stream at all, and a stream that ended before the model finished.
    """
    parts: list[str] = []
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    response_id: str | None = None
    pieces = 0

    for raw_line in text.split("\n"):
        line = raw_line.rstrip("\r")
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except (ValueError, RecursionError):
            chunk = None
        if not isinstance(chunk, dict):
            raise LlmCallError("bad_answer", "The server's answer held a piece that was not JSON.")
        if chunk.get("error"):
            raise LlmCallError("server_error", _stream_error_message(chunk["error"]))
        pieces += 1

        if response_id is None and isinstance(chunk.get("id"), str):
            response_id = chunk["id"]
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        choices = chunk.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else None
        if not isinstance(choice, dict):
            continue  # the last piece carries the token counts and no choice
        delta = choice.get("delta")
        piece = delta.get("content") if isinstance(delta, dict) else None
        if isinstance(piece, str):
            parts.append(piece)
        if isinstance(choice.get("finish_reason"), str):
            finish_reason = choice["finish_reason"]

    if pieces == 0:
        raise LlmCallError("bad_answer", "The server's answer was not a stream of answer pieces.")
    if finish_reason is None:
        raise LlmCallError("bad_answer", "The server's answer ended before the model had finished.")
    return ChatResult(
        content="".join(parts),
        finish_reason=finish_reason,
        usage=usage,
        response_id=response_id,
    )


def _read_whole_answer(response: outbound.OutboundResponse) -> ChatResult:
    """Reads an answer that came as one JSON object instead of a stream."""
    try:
        data = response.json()
    except (ValueError, RecursionError):
        raise LlmCallError("bad_answer", "The server's answer was not valid JSON.") from None

    choices = data.get("choices") if isinstance(data, dict) else None
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict):
        raise LlmCallError("bad_answer", "The server's answer had no message.")

    content = message.get("content")
    finish_reason = first.get("finish_reason") if isinstance(first, dict) else None
    usage = data.get("usage")
    response_id = data.get("id")
    return ChatResult(
        content=content if isinstance(content, str) else "",
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        usage=usage if isinstance(usage, dict) else None,
        response_id=response_id if isinstance(response_id, str) else None,
    )


def parse_json_object(content: str) -> Any:
    """Parses the model's text as JSON. Models sometimes wrap JSON in a code fence or add a
    sentence around it, so a plain parse is followed by a search for the outer braces.

    Raises ValueError, with a message fit for the user, when there is no JSON in the text.
    """
    text = content.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except ValueError:
            pass
    raise ValueError("The model's answer was not valid JSON.")


def usage_counts(usage: object) -> dict[str, int | None]:
    """Prompt, completion and reasoning tokens from a `usage` block.

    Bitdeer puts `reasoning_tokens` at the top level of `usage`; OpenAI-style servers put
    it under `completion_tokens_details`. Reasoning tokens are part of `completion_tokens`.
    """
    counts: dict[str, int | None] = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,
    }
    if not isinstance(usage, dict):
        return counts

    def number(value: object) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    counts["prompt_tokens"] = number(usage.get("prompt_tokens"))
    counts["completion_tokens"] = number(usage.get("completion_tokens"))
    reasoning = number(usage.get("reasoning_tokens"))
    if reasoning is None:
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict):
            reasoning = number(details.get("reasoning_tokens"))
    counts["reasoning_tokens"] = reasoning
    return counts
