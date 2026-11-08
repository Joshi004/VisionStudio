"""The `write_chat_reply` job: the chosen model answers the latest message of a Text lab chat.

It belongs to no project (`job.project_id` is NULL). `job.input` names the chat, the assistant
message the answer is written into and the chat model (`services/chat_models.py`). The job:

1. loads every earlier message of the chat and builds the request from them
   (`services/chat_history.py`), so the model gets the whole conversation every time;
2. sends it, and while a Bitdeer answer streams in, saves the answer so far into the assistant
   message about once a second, which is what the page shows by polling;
3. when the answer is complete, saves the final text, the thinking, the finish reason and the
   token counts, and finishes the job.

It is a paid call (ANALYSIS.md Section 6.2), so it only starts from a click, makes **one**
attempt (the user retries from the page, and every try is a new paid call on purpose), and is
`never_rerun`: a restart queues it again from the start, at most twice, and then fails it. An
answer that failed halfway keeps the text written so far, and the job shows the error.

A call to the model cannot be taken back, so a running reply cannot be cancelled. A reply that
still waits in the queue can.

Logs hold the job id, the sizes and token counts, never a message.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select, update

from app.db.models import LabChatMessage
from app.db.session import SessionLocal
from app.jobs import phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.providers.llm import LlmCallError
from app.services import chat_history, chat_models, llm_target
from app.services.chat_history import HistoryTooLongError, SavedMessage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "write_chat_reply"

# A reasoning model can think for minutes before it writes. These bound the whole call and the
# silence between two pieces (the Qwen3.8 call has its own, longer allowance).
REQUEST_TIMEOUT_S: Final = 1200.0
IDLE_TIMEOUT_S: Final = 180.0
# How often the answer so far is written to the database while it streams.
SAVE_INTERVAL_S: Final = 1.0
REASONING_EFFORT: Final = "high"


class _Buffer:
    """The answer so far. The provider calls `update` from the stream; a side task saves it."""

    def __init__(self) -> None:
        self.content = ""
        self.reasoning = ""
        self.dirty = False

    def update(self, content: str, reasoning: str) -> None:
        self.content = content
        self.reasoning = reasoning
        self.dirty = True


@dataclass
class _Prepared:
    """What `_prepare` made: everything the call and the finish need."""

    job_input: dict[str, Any]
    message_id: int
    model: chat_models.ChatModel
    target: llm_target.LlmTarget
    body: dict[str, Any]
    dropped: int


class WriteChatReplyHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    # No role: the model is chosen for every message and named in `job.input`, and so is the
    # server (`endpoint`), which is how the pools tell a GPU call from a paid one.
    model_key = None

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        prepared = await self._prepare(job_id)
        if prepared is None:
            return
        message_id = prepared.message_id
        target = prepared.target
        body = prepared.body

        await phase_writer.note(job_id, phases.asking_model(1, 1))
        buffer = _Buffer()
        saver = asyncio.create_task(self._save_while_streaming(message_id, buffer))
        try:
            result = await llm_target.complete(
                target,
                body,
                timeout_s=REQUEST_TIMEOUT_S,
                idle_timeout_s=IDLE_TIMEOUT_S,
                on_progress=buffer.update,
            )
        except LlmCallError as exc:
            await self._stop(saver)
            _logger.info(
                "job %d: chat reply failed: %s (HTTP %s)", job_id, exc.kind, exc.status_code
            )
            await self._fail_keeping_partial(job_id, message_id, buffer, _failure_text(exc))
            return
        except BaseException:
            # Anything unexpected (the dispatcher fails the job): stop the side task first.
            await self._stop(saver)
            raise
        await self._stop(saver)
        await self._finish(job_id, prepared, result, started)

    # --- Preparing ---------------------------------------------------------------------

    async def _prepare(self, job_id: int) -> _Prepared | None:
        """Builds the request and saves it on the job. None when the job cannot go on (it has
        already been failed, or it is no longer running).
        """
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return None
            job_input: dict[str, Any] = dict(job.input)
            model = chat_models.get(str(job_input.get("model")))
            message_id = job_input.get("message_id")
            reply = None
            if model is not None and isinstance(message_id, int):
                reply = await session.get(LabChatMessage, message_id)
            if model is None or reply is None or not isinstance(message_id, int):
                await session.commit()
                await self._fail(job_id, "The chat message or the model of this reply is missing.")
                return None

            target = await chat_models.target_for(session, model)
            # A run that starts again (after a restart) writes the answer from the beginning.
            reply.content = ""
            reply.reasoning = ""
            reply.finish_reason = None
            reply.usage = None
            rows = (
                (
                    await session.execute(
                        select(LabChatMessage)
                        .where(
                            LabChatMessage.chat_id == reply.chat_id,
                            LabChatMessage.id < message_id,
                        )
                        .order_by(LabChatMessage.id)
                    )
                )
                .scalars()
                .all()
            )
            saved = [SavedMessage(row.role, row.content, row.finish_reason) for row in rows]
            await session.commit()

        await phase_writer.note(job_id, phases.PREPARING_PROMPT)
        try:
            history = chat_history.build(saved, model.max_history_chars)
        except HistoryTooLongError as exc:
            await self._fail(job_id, str(exc))
            return None
        body: dict[str, Any] = {
            "model": target.model,
            "messages": history.messages,
            "max_tokens": model.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if model.reasoning_effort:
            body["reasoning_effort"] = REASONING_EFFORT
        # The messages are the chat's own rows, so the job keeps only their count and size.
        job_input.update(
            server_url=llm_target.call_url(target),
            endpoint=chat_models.endpoint_of(model),
            request={key: value for key, value in body.items() if key != "messages"},
            message_count=len(history.messages),
            history_chars=history.chars,
            history_dropped=history.dropped,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)
            await session.execute(
                update(LabChatMessage)
                .where(LabChatMessage.id == message_id)
                .values(history_dropped=history.dropped)
            )
            await session.commit()
        return _Prepared(
            job_input=job_input,
            message_id=message_id,
            model=model,
            target=target,
            body=body,
            dropped=history.dropped,
        )

    # --- Saving while the answer streams ------------------------------------------------

    @staticmethod
    async def _save_while_streaming(message_id: int, buffer: _Buffer) -> None:
        """Writes the answer so far to the message about once a second, while it has changed."""
        while True:
            await asyncio.sleep(SAVE_INTERVAL_S)
            if not buffer.dirty:
                continue
            buffer.dirty = False
            try:
                await _write_partial(message_id, buffer.content, buffer.reasoning)
            except Exception:  # a missed save is made up by the next one or the final save
                _logger.exception("chat reply: saving the answer so far failed")
                buffer.dirty = True

    @staticmethod
    async def _stop(saver: asyncio.Task[None]) -> None:
        saver.cancel()
        try:
            await saver
        except asyncio.CancelledError:
            pass

    # --- Finishing ----------------------------------------------------------------------

    async def _finish(
        self,
        job_id: int,
        prepared: _Prepared,
        result: llm.ChatResult,
        started: float,
    ) -> None:
        message_id = prepared.message_id
        model = prepared.model
        counts = llm.usage_counts(result.usage)
        _logger.info(
            "job %d: chat reply answered: model=%s finish=%s chars=%d tokens prompt=%s "
            "completion=%s reasoning=%s, %.1f s",
            job_id,
            model.id,
            result.finish_reason,
            len(result.content),
            counts["prompt_tokens"],
            counts["completion_tokens"],
            counts["reasoning_tokens"],
            time.monotonic() - started,
        )
        problem = None
        if not result.content.strip():
            if result.finish_reason == "length":
                problem = (
                    "The model used all of its tokens thinking and wrote no answer. "
                    "Try again, or ask a shorter question."
                )
            else:
                problem = "The model gave no answer."

        async with SessionLocal() as session:
            await session.execute(
                update(LabChatMessage)
                .where(LabChatMessage.id == message_id)
                .values(
                    content=result.content,
                    reasoning=result.reasoning,
                    finish_reason=result.finish_reason or "stop",
                    usage=counts,
                )
            )
            await session.commit()
        if problem is not None:
            await self._fail(job_id, problem)
            return

        output = {
            "model": model.id,
            "chat_id": prepared.job_input.get("chat_id"),
            "message_id": message_id,
            "finish_reason": result.finish_reason,
            "response_id": result.response_id,
            "usage": counts,
            "history_dropped": prepared.dropped,
            "seconds": round(time.monotonic() - started, 1),
        }
        async with SessionLocal() as session:
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            await session.commit()

    async def _fail_keeping_partial(
        self, job_id: int, message_id: int, buffer: _Buffer, error: str
    ) -> None:
        """Keeps the text written before the failure, then fails the job with the reason."""
        if buffer.content or buffer.reasoning:
            try:
                await _write_partial(message_id, buffer.content, buffer.reasoning)
            except Exception:
                _logger.exception("job %d: the partial answer could not be saved", job_id)
        await self._fail(job_id, error)

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)


async def _write_partial(message_id: int, content: str, reasoning: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(LabChatMessage)
            .where(LabChatMessage.id == message_id)
            .values(content=content, reasoning=reasoning)
        )
        await session.commit()


def _failure_text(exc: LlmCallError) -> str:
    """What to tell the user about a call that failed."""
    if exc.status_code is not None:
        return f"The language model answered HTTP {exc.status_code}: {exc.message}"
    return exc.message
