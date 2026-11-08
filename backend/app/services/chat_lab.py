"""The Text lab: chats with a language model chosen for every message.

A chat is a row of `lab_chat` and its messages are rows of `lab_chat_message` (revision 0095).
Sending a message saves the user's message, an empty assistant message and a `write_chat_reply`
job in one transaction. The job fills the assistant message while the answer streams in
(`jobs/write_chat_reply.py`), and the page follows it by polling the chat.

Rules this module keeps:

- One reply at a time per chat. A message is refused while the last reply is still queued or
  running, so the history the next reply is built from is always complete.
- The model must be one of `chat_models.MODELS`.
- A chat is not deleted while a reply is running: the job writes into its messages.
- Only the last reply can be tried again, and only after it failed or was cancelled.

Nothing here calls the model, and nothing here commits halfway: every function that changes
something commits once, at its end.
"""

from __future__ import annotations

import asyncio
from typing import Final

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, LabChat, LabChatMessage
from app.db.types import utcnow
from app.jobs import store
from app.jobs.store import JobRow
from app.services import chat_models

JOB_TYPE: Final = "write_chat_reply"
NEW_CHAT_TITLE: Final = "New chat"
TITLE_MAX_CHARS: Final = 120
# The title made from the first message.
AUTO_TITLE_CHARS: Final = 60
# The longest message the page may send. A model's own limit (`max_history_chars`) can be lower.
CONTENT_MAX_CHARS: Final = 100_000
CHAT_LIST_LIMIT: Final = 200

# Two sends at the same moment must not both pass the "no reply is running" check.
_send_lock = asyncio.Lock()


class ChatInputError(Exception):
    """The request breaks a rule. `str(error)` is readable by the user (HTTP 422)."""


class ChatNotFoundError(Exception):
    """No chat or message has this id (HTTP 404)."""


class ChatConflictError(Exception):
    """The chat is in a state that does not allow this (HTTP 409)."""


async def list_chats(session: AsyncSession) -> list[LabChat]:
    """The newest-used chats first."""
    statement = (
        select(LabChat)
        .order_by(LabChat.updated_at.desc(), LabChat.id.desc())
        .limit(CHAT_LIST_LIMIT)
    )
    return list((await session.execute(statement)).scalars().all())


async def create_chat(session: AsyncSession, model_id: str | None) -> LabChat:
    model = _model_or_error(model_id or chat_models.DEFAULT_MODEL_ID)
    chat = LabChat(title=NEW_CHAT_TITLE, model=model.id)
    session.add(chat)
    await session.commit()
    return chat


async def get_chat(session: AsyncSession, chat_id: int) -> LabChat:
    chat = await session.get(LabChat, chat_id)
    if chat is None:
        raise ChatNotFoundError(f"Chat {chat_id} does not exist.")
    return chat


async def messages_with_jobs(
    session: AsyncSession, chat_id: int
) -> list[tuple[LabChatMessage, JobRow | None]]:
    """The chat's messages, oldest first, each with the job that fills it (assistant only)."""
    statement = (
        select(LabChatMessage)
        .where(LabChatMessage.chat_id == chat_id)
        .order_by(LabChatMessage.id)
        .execution_options(populate_existing=True)
    )
    messages = list((await session.execute(statement)).scalars().all())
    job_ids = [message.job_id for message in messages if message.job_id is not None]
    jobs: dict[int, Job] = {}
    if job_ids:
        job_statement = (
            select(Job).where(Job.id.in_(job_ids)).execution_options(populate_existing=True)
        )
        jobs = {job.id: job for job in (await session.execute(job_statement)).scalars().all()}
    return [
        (
            message,
            None
            if message.job_id is None or message.job_id not in jobs
            else JobRow(
                job=jobs[message.job_id],
                project_name=store.owner_name(jobs[message.job_id], None),
            ),
        )
        for message in messages
    ]


async def rename_chat(session: AsyncSession, chat_id: int, title: str) -> LabChat:
    chat = await get_chat(session, chat_id)
    cleaned = " ".join(title.split())
    if not cleaned:
        raise ChatInputError("The title cannot be empty.")
    if len(cleaned) > TITLE_MAX_CHARS:
        raise ChatInputError(f"The title can have at most {TITLE_MAX_CHARS} characters.")
    chat.title = cleaned
    await session.commit()
    return chat


async def delete_chat(session: AsyncSession, chat_id: int) -> None:
    chat = await get_chat(session, chat_id)
    if await _reply_is_active(session, chat.id):
        raise ChatConflictError("A reply is still being written. Wait for it to finish first.")
    await session.execute(delete(LabChat).where(LabChat.id == chat.id))
    await session.commit()


async def send_message(
    session: AsyncSession, chat_id: int, content: str, model_id: str
) -> tuple[LabChat, Job]:
    """Saves the user's message, an empty assistant message and the job that will fill it.
    Returns the chat and the job (the caller wakes the dispatcher).
    """
    model = _model_or_error(model_id)
    text = content.strip()
    if not text:
        raise ChatInputError("The message is empty.")
    if len(text) > CONTENT_MAX_CHARS:
        raise ChatInputError(f"The message can have at most {CONTENT_MAX_CHARS:,} characters.")
    if len(text) > model.max_history_chars:
        raise ChatInputError(
            f"The message is too long for {model.label}: it accepts about "
            f"{model.max_history_chars:,} characters in all."
        )

    async with _send_lock:
        chat = await get_chat(session, chat_id)
        if await _reply_is_active(session, chat.id):
            raise ChatConflictError("The last reply is still being written. Wait for it.")

        first_message = (
            await session.execute(
                select(func.count(LabChatMessage.id)).where(LabChatMessage.chat_id == chat.id)
            )
        ).scalar_one() == 0
        session.add(LabChatMessage(chat_id=chat.id, role="user", content=text))
        reply = LabChatMessage(chat_id=chat.id, role="assistant", model=model.id)
        session.add(reply)
        await session.flush()  # the reply's id goes into the job

        job = await _create_reply_job(session, chat.id, reply.id, model)
        reply.job_id = job.id
        if first_message and chat.title == NEW_CHAT_TITLE:
            chat.title = _title_from(text)
        chat.model = model.id
        chat.updated_at = utcnow()
        await session.commit()
    return chat, job


async def retry_reply(
    session: AsyncSession, chat_id: int, message_id: int, model_id: str | None
) -> tuple[LabChat, Job]:
    """Asks again for the last reply of a chat, which failed or was cancelled. The same
    assistant message is used, emptied, and a new job fills it. `model_id` is another model to
    try, or None for the one the reply was asked of.
    """
    async with _send_lock:
        chat = await get_chat(session, chat_id)
        reply = await session.get(LabChatMessage, message_id)
        if reply is None or reply.chat_id != chat.id or reply.role != "assistant":
            raise ChatNotFoundError(f"Reply {message_id} does not exist in this chat.")
        last_id = (
            await session.execute(
                select(func.max(LabChatMessage.id)).where(LabChatMessage.chat_id == chat.id)
            )
        ).scalar_one()
        if reply.id != last_id:
            raise ChatConflictError("Only the last reply can be tried again.")
        old_job = await store.get_job(session, reply.job_id) if reply.job_id else None
        if old_job is not None and old_job.status not in ("failed", "cancelled"):
            raise ChatConflictError("Only a reply that failed or was cancelled can be tried again.")

        model = _model_or_error(model_id or reply.model or chat.model)
        reply.content = ""
        reply.reasoning = ""
        reply.finish_reason = None
        reply.usage = None
        reply.history_dropped = 0
        reply.model = model.id
        job = await _create_reply_job(session, chat.id, reply.id, model)
        reply.job_id = job.id
        chat.model = model.id
        chat.updated_at = utcnow()
        await session.commit()
    return chat, job


# --- Small helpers ----------------------------------------------------------------------


def _model_or_error(model_id: str) -> chat_models.ChatModel:
    model = chat_models.get(model_id)
    if model is None:
        raise ChatInputError("This model is not one the chat can use.")
    return model


async def _create_reply_job(
    session: AsyncSession, chat_id: int, message_id: int, model: chat_models.ChatModel
) -> Job:
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=JOB_TYPE,
        provider="llm",
        input={
            "requested": "lab_chat_reply",
            "chat_id": chat_id,
            "message_id": message_id,
            "model": model.id,
            # Which server the call goes to, so the pools count it in the right place while it
            # still waits in the queue.
            "endpoint": chat_models.endpoint_of(model),
        },
        commit=False,
        dedupe=False,  # every message is its own paid call
    )
    return job


async def _reply_is_active(session: AsyncSession, chat_id: int) -> bool:
    """Whether a reply of this chat is queued or running."""
    statement = (
        select(func.count(Job.id))
        .join(LabChatMessage, LabChatMessage.job_id == Job.id)
        .where(
            LabChatMessage.chat_id == chat_id,
            Job.status.in_(store.ACTIVE_STATUSES),
        )
    )
    return (await session.execute(statement)).scalar_one() > 0


def _title_from(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= AUTO_TITLE_CHARS:
        return one_line
    return one_line[: AUTO_TITLE_CHARS - 1].rstrip() + "…"
