"""YouTube channels: what `.env` is missing, Google sign-in, and the connected channels
(YouTube_publish_phases.md, YT-002).

No answer here holds a token, a code, the client secret or the encryption key.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.errors import ErrorResponse
from app.db.models import YouTubeChannel
from app.db.session import SessionDep
from app.services import youtube_auth

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No connected channel has this id."}}
_NOT_CONFIGURED = {
    409: {"model": ErrorResponse, "description": "A YOUTUBE_* value is missing or invalid."}
}
_GOOGLE_DOWN = {502: {"model": ErrorResponse, "description": "Google could not be reached."}}

# Where the browser is sent after Google's callback, with a result code in `?youtube=`.
_SETTINGS_PAGE = "/settings"
_NOT_SET_UP = "YouTube is not set up. Fix the values listed in Settings, then try again."


class ConfigProblemOut(BaseModel):
    name: str
    reason: str


class YouTubeConfig(BaseModel):
    """Which `.env` values are missing or invalid. Names and reasons, never a value."""

    ready: bool
    missing: list[str]
    invalid: list[ConfigProblemOut]


class SignInStart(BaseModel):
    """Google's authorization address, for the browser to open."""

    url: str


class YouTubeChannelOut(BaseModel):
    id: int
    channel_id: str
    title: str
    thumbnail_url: str | None
    status: Literal["connected", "needs_reconnect"]
    connected_at: datetime
    last_used_at: datetime | None


class DisconnectOut(BaseModel):
    """`revoked`: whether Google was told to revoke the token. The channel is removed either way."""

    revoked: bool


def _channel_out(row: YouTubeChannel) -> YouTubeChannelOut:
    """The token and the scopes are left out on purpose."""
    return YouTubeChannelOut(
        id=row.id,
        channel_id=row.channel_id,
        title=row.title,
        thumbnail_url=row.thumbnail_url,
        status="connected" if row.status == youtube_auth.STATUS_CONNECTED else "needs_reconnect",
        connected_at=row.connected_at,
        last_used_at=row.last_used_at,
    )


@router.get("/youtube/config", response_model=YouTubeConfig)
async def youtube_config() -> YouTubeConfig:
    current = youtube_auth.config_status()
    return YouTubeConfig(
        ready=current.ready,
        missing=list(current.missing),
        invalid=[ConfigProblemOut(name=p.name, reason=p.reason) for p in current.invalid],
    )


@router.get("/youtube/oauth/start", response_model=SignInStart, responses=_NOT_CONFIGURED)
async def start_sign_in() -> SignInStart:
    try:
        return SignInStart(url=youtube_auth.start_sign_in())
    except youtube_auth.YouTubeNotConfiguredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_SET_UP) from exc


@router.get("/youtube/oauth/callback", include_in_schema=False)
async def sign_in_callback(
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Google sends the browser here. It always answers with a redirect to the Settings page and
    a result code; the page turns the code into a sentence.
    """
    result = await youtube_auth.finish_sign_in(session, code=code, state=state, error=error)
    return RedirectResponse(
        f"{_SETTINGS_PAGE}?youtube={result}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/youtube/channels", response_model=list[YouTubeChannelOut])
async def list_channels(session: SessionDep) -> list[YouTubeChannelOut]:
    return [_channel_out(row) for row in await youtube_auth.list_channels(session)]


@router.post(
    "/youtube/channels/{channel_row_id}/check",
    response_model=YouTubeChannelOut,
    responses={**_NOT_FOUND, **_NOT_CONFIGURED, **_GOOGLE_DOWN},
)
async def check_channel(channel_row_id: int, session: SessionDep) -> YouTubeChannelOut:
    """Uses the channel's token once (1 quota unit). A refused token makes it `needs_reconnect`."""
    try:
        row = await youtube_auth.check_channel(session, channel_row_id)
    except youtube_auth.ChannelNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except youtube_auth.YouTubeNotConfiguredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_SET_UP) from exc
    except youtube_auth.GoogleUnreachableError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"{exc} The channel was not changed. Try again in a moment.",
        ) from exc
    return _channel_out(row)


@router.delete(
    "/youtube/channels/{channel_row_id}",
    response_model=DisconnectOut,
    responses=_NOT_FOUND,
)
async def disconnect_channel(channel_row_id: int, session: SessionDep) -> DisconnectOut:
    try:
        revoked = await youtube_auth.disconnect(session, channel_row_id)
    except youtube_auth.ChannelNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return DisconnectOut(revoked=revoked)
