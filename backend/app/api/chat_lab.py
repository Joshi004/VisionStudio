"""`/api/lab/chat` and `/api/lab/chats`: the Text lab, a chat with a model chosen for every message.

`GET /api/lab/chat/models` lists the models the chat can use and their limits.

`GET /api/lab/chats` lists the chats, newest first. `POST` makes an empty one. `GET .../{id}`
returns a chat with all its messages: each reply carries the job that fills it, and while that job
is queued or running the reply's text is the answer so far, so the page polls this route about once
a second. `PATCH` renames and `DELETE` deletes (refused while a reply is being written).

`POST .../{id}/messages` saves the message, makes the empty reply and starts the paid job, then
returns the chat at once with HTTP 202. The server builds the whole history from the saved
messages, so the page sends only the new message and the model. It is refused (409) while the
last reply is still being written. `POST .../{id}/messages/{message_id}/retry` asks again for the
last reply after it failed or was cancelled.

A reply that waits in the queue is cancelled with the job's own cancel; a running one cannot be.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.api.errors import ErrorResponse
from app.api.jobs import JobSummary, job_summary
from app.db.models import LabChat, LabChatMessage
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.jobs.store import JobRow
from app.services import chat_lab, chat_models

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
Id = Annotated[int, Path(ge=1, le=_MAX_ID)]

_INVALID = {422: {"model": ErrorResponse, "description": "The request breaks a rule."}}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No chat or message has this id."}}
_CONFLICT = {
    409: {"model": ErrorResponse, "description": "The chat is in a state that does not allow it."}
}


class ChatModelOut(BaseModel):
    id: str
    label: str
    provider: str
    # False when the answer arrives in one piece instead of appearing as it is written.
    streams: bool
    max_tokens: int
    max_history_chars: int
    note: str | None


class ChatModelCatalogOut(BaseModel):
    default_model: str
    models: list[ChatModelOut]


class ChatSummaryOut(BaseModel):
    id: int
    title: str
    model: str
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    reasoning: str
    model: str | None
    finish_reason: str | None
    usage: dict[str, int | None] | None
    history_dropped: int
    created_at: datetime
    # The job that writes a reply; its status says whether the reply is waiting, running, done or
    # failed. None for a user message.
    job: JobSummary | None


class ChatOut(ChatSummaryOut):
    messages: list[ChatMessageOut]


class ChatCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Left out: the default model.
    model: StrictStr | None = Field(default=None, max_length=200)


class ChatRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StrictStr = Field(max_length=chat_lab.TITLE_MAX_CHARS * 4)


class ChatMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: StrictStr = Field(max_length=chat_lab.CONTENT_MAX_CHARS * 2)
    model: StrictStr = Field(max_length=200)


class ChatRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Another model to try. Left out: the one the reply was asked of.
    model: StrictStr | None = Field(default=None, max_length=200)


def _summary(chat: LabChat) -> ChatSummaryOut:
    return ChatSummaryOut(
        id=chat.id,
        title=chat.title,
        model=chat.model,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def _message_out(message: LabChatMessage, row: JobRow | None) -> ChatMessageOut:
    usage = message.usage if isinstance(message.usage, dict) else None
    return ChatMessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        reasoning=message.reasoning,
        model=message.model,
        finish_reason=message.finish_reason,
        usage=usage,
        history_dropped=message.history_dropped,
        created_at=message.created_at,
        job=None if row is None else job_summary(row),
    )


async def _chat_out(session: SessionDep, chat: LabChat) -> ChatOut:
    rows = await chat_lab.messages_with_jobs(session, chat.id)
    return ChatOut(
        **_summary(chat).model_dump(),
        messages=[_message_out(message, row) for message, row in rows],
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, chat_lab.ChatNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, chat_lab.ChatConflictError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


_CHAT_ERRORS = (
    chat_lab.ChatInputError,
    chat_lab.ChatNotFoundError,
    chat_lab.ChatConflictError,
)


@router.get("/lab/chat/models", response_model=ChatModelCatalogOut)
async def list_models() -> ChatModelCatalogOut:
    return ChatModelCatalogOut(
        default_model=chat_models.DEFAULT_MODEL_ID,
        models=[
            ChatModelOut(
                id=model.id,
                label=model.label,
                provider=model.provider,
                streams=not model.is_qwen38,
                max_tokens=model.max_tokens,
                max_history_chars=model.max_history_chars,
                note=model.note,
            )
            for model in chat_models.MODELS
        ],
    )


@router.get("/lab/chats", response_model=list[ChatSummaryOut])
async def list_chats(session: SessionDep) -> list[ChatSummaryOut]:
    return [_summary(chat) for chat in await chat_lab.list_chats(session)]


@router.post(
    "/lab/chats",
    response_model=ChatSummaryOut,
    status_code=status.HTTP_201_CREATED,
    responses=_INVALID,
)
async def create_chat(body: ChatCreate, session: SessionDep) -> ChatSummaryOut:
    try:
        chat = await chat_lab.create_chat(session, body.model)
    except _CHAT_ERRORS as exc:
        raise _http_error(exc) from exc
    return _summary(chat)


@router.get("/lab/chats/{chat_id}", response_model=ChatOut, responses=_NOT_FOUND)
async def get_chat(chat_id: Id, session: SessionDep) -> ChatOut:
    try:
        chat = await chat_lab.get_chat(session, chat_id)
    except _CHAT_ERRORS as exc:
        raise _http_error(exc) from exc
    return await _chat_out(session, chat)


@router.patch(
    "/lab/chats/{chat_id}",
    response_model=ChatSummaryOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def rename_chat(chat_id: Id, body: ChatRename, session: SessionDep) -> ChatSummaryOut:
    try:
        chat = await chat_lab.rename_chat(session, chat_id, body.title)
    except _CHAT_ERRORS as exc:
        raise _http_error(exc) from exc
    return _summary(chat)


@router.delete(
    "/lab/chats/{chat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND, **_CONFLICT},
)
async def delete_chat(chat_id: Id, session: SessionDep) -> None:
    try:
        await chat_lab.delete_chat(session, chat_id)
    except _CHAT_ERRORS as exc:
        raise _http_error(exc) from exc


@router.post(
    "/lab/chats/{chat_id}/messages",
    response_model=ChatOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID, **_CONFLICT},
)
async def send_message(chat_id: Id, body: ChatMessageCreate, session: SessionDep) -> ChatOut:
    try:
        chat, _job = await chat_lab.send_message(session, chat_id, body.content, body.model)
    except _CHAT_ERRORS as exc:
        raise _http_error(exc) from exc
    dispatcher.nudge()
    return await _chat_out(session, chat)


@router.post(
    "/lab/chats/{chat_id}/messages/{message_id}/retry",
    response_model=ChatOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID, **_CONFLICT},
)
async def retry_reply(chat_id: Id, message_id: Id, body: ChatRetry, session: SessionDep) -> ChatOut:
    try:
        chat, _job = await chat_lab.retry_reply(session, chat_id, message_id, body.model)
    except _CHAT_ERRORS as exc:
        raise _http_error(exc) from exc
    dispatcher.nudge()
    return await _chat_out(session, chat)
