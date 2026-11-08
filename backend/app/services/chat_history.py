"""Turning the saved messages of a Text lab chat into the `messages` of one model request.

The server rebuilds the whole conversation from the database every time, so the page never
sends it. The rules:

- Every earlier user message is sent.
- An earlier answer is sent only when it finished (`finish_reason` is set) and has text. An answer
  that failed, was cut short by an error, or is still empty is left out, so the model never sees
  half an answer as if it had said it.
- When the whole is longer than the model accepts (`max_chars`, counted in message characters, the
  number the Qwen3.8 server limits), the oldest messages are left out, always starting again at a
  user message, and the number left out is returned so the page can say so.
- The last message must be the user message being answered, and it is never left out. If that
  message alone is longer than `max_chars`, `HistoryTooLongError` is raised.

Nothing here reads the database: `jobs/write_chat_reply.py` loads the rows and passes them in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

USER: Final = "user"
ASSISTANT: Final = "assistant"


class HistoryTooLongError(Exception):
    """The message being answered is longer than the model accepts. `str(error)` is readable."""


@dataclass(frozen=True)
class SavedMessage:
    """The part of a stored message that matters here."""

    role: str
    content: str
    finish_reason: str | None


@dataclass(frozen=True)
class History:
    messages: list[dict[str, Any]]  # the `messages` of the request
    dropped: int  # how many of the oldest messages were left out to fit
    chars: int  # the total length of the messages sent


def _usable(message: SavedMessage) -> bool:
    if message.role == USER:
        return bool(message.content.strip())
    return (
        message.role == ASSISTANT
        and message.finish_reason is not None
        and bool(message.content.strip())
    )


def build(saved: list[SavedMessage], max_chars: int) -> History:
    """The request messages for `saved`, which is every message before the reply being written,
    oldest first, and ends with the user message to answer.
    """
    usable = [message for message in saved if _usable(message)]
    if not usable or usable[-1].role != USER:
        raise HistoryTooLongError("There is no message to answer.")

    total = sum(len(message.content) for message in usable)
    start = 0
    while total > max_chars and start < len(usable) - 1:
        total -= len(usable[start].content)
        start += 1
        # Start again at a user message, so the first message the model sees is a question.
        while start < len(usable) - 1 and usable[start].role != USER:
            total -= len(usable[start].content)
            start += 1
    if total > max_chars:
        raise HistoryTooLongError(
            f"The message is too long for this model: it accepts about {max_chars:,} characters "
            "in all."
        )
    kept = usable[start:]
    return History(
        messages=[{"role": message.role, "content": message.content} for message in kept],
        dropped=start,
        chars=total,
    )
