"""What the user may read about the prompt behind an artifact (PHASE-038).

Every job that asks a language model something stores the exact request on `job.input.request`
(the system and user messages and the call's settings) before the paid call, and the answer on
`job.output`. A video job stores the body sent to the video model (the prompt, the seed, the
frame count). An image job stores the body sent to the image model. This module only reads those
records and keeps the parts that are fit to show: it never invents a prompt and never returns
the other things a job's input holds (server addresses, uploaded file names, paths).

Pure functions on JSON values: no database and no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

PromptKind = Literal["llm", "video", "image", "none"]

# What the model call sends besides the messages that is not worth showing.
_HIDDEN_REQUEST_KEYS: Final = frozenset({"messages", "model", "stream", "stream_options"})

Setting = str | int | float | bool


@dataclass(frozen=True)
class PromptMessage:
    role: str
    content: str


@dataclass(frozen=True)
class MediaRequest:
    """The body sent to a video or an image model, without the uploaded files."""

    endpoint: str | None
    prompt: str
    seed: int | None
    width: int | None
    height: int | None
    num_frames: int | None
    # How many reference pictures and audios went with it.
    pictures: int
    audios: int


@dataclass(frozen=True)
class PromptView:
    kind: PromptKind
    model: str | None = None
    settings: dict[str, Setting] = field(default_factory=dict)
    messages: list[PromptMessage] = field(default_factory=list)
    # The model's answer after the stage's checks (what was stored), when there is one.
    answer: Any | None = None
    # The raw text of the last answer that could not be used, when the job kept one.
    unusable_answer: str | None = None
    # The user's own words that were part of the request (PHASE-038), when there were any.
    feedback: str | None = None
    media: MediaRequest | None = None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _settings(request: dict[str, Any]) -> dict[str, Setting]:
    found: dict[str, Setting] = {}
    for key, value in request.items():
        if key in _HIDDEN_REQUEST_KEYS:
            continue
        if isinstance(value, dict) and isinstance(value.get("type"), str):
            found[key] = value["type"]
        elif isinstance(value, str | int | float | bool):
            found[key] = value
    return found


def _messages(request: dict[str, Any]) -> list[PromptMessage] | None:
    raw = request.get("messages")
    if not isinstance(raw, list):
        return None
    messages: list[PromptMessage] = []
    for item in raw:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("role"), str)
            or not isinstance(item.get("content"), str)
        ):
            return None
        messages.append(PromptMessage(role=item["role"], content=item["content"]))
    return messages


def _count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _feedback(job_input: dict[str, Any]) -> str | None:
    feedback = job_input.get("feedback")
    if isinstance(feedback, dict) and isinstance(feedback.get("text"), str):
        return feedback["text"]
    return None


def view_of(job_input: Any, job_output: Any) -> PromptView:
    """The prompt view of one job from its stored `input` and `output`. A job that sent nothing
    to a model (or one this module does not know) gives `kind="none"`.
    """
    if not isinstance(job_input, dict):
        return PromptView(kind="none")
    request = job_input.get("request")
    if not isinstance(request, dict):
        return PromptView(kind="none")
    output = job_output if isinstance(job_output, dict) else {}

    messages = _messages(request)
    if messages is not None:
        unusable = output.get("content")
        model = request.get("model")
        return PromptView(
            kind="llm",
            model=model if isinstance(model, str) else None,
            settings=_settings(request),
            messages=messages,
            answer=output.get("answer"),
            unusable_answer=unusable if isinstance(unusable, str) else None,
            feedback=_feedback(job_input),
        )

    prompt = request.get("prompt")
    if isinstance(prompt, str):
        endpoint = job_input.get("endpoint")
        has_frames = _int(request.get("num_frames")) is not None
        pictures = _count(job_input.get("references")) + (
            1 if isinstance(job_input.get("first_frame"), dict) else 0
        )
        return PromptView(
            kind="video" if has_frames else "image",
            feedback=_feedback(job_input),
            media=MediaRequest(
                endpoint=endpoint if isinstance(endpoint, str) else None,
                prompt=prompt,
                seed=_int(request.get("seed")),
                width=_int(request.get("width")),
                height=_int(request.get("height")),
                num_frames=_int(request.get("num_frames")),
                pictures=pictures,
                audios=_count(job_input.get("audios")),
            ),
        )
    return PromptView(kind="none")
