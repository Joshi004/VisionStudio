"""Connecting YouTube channels: Google sign-in, encrypted refresh tokens, checking and disconnecting
(YouTube_publish_phases.md, YT-002).

This is the only module that builds Google credentials. The Google libraries are the recorded
exception to the `core/outbound.py` rule (Y-4): they make their own HTTP calls, they are
synchronous, so every call here runs in a worker thread, and they call only Google's fixed
endpoints.

How a channel is connected:

1. `start_sign_in` builds Google's authorization address with a random single-use `state` and a
   PKCE verifier. Both are kept in memory for ten minutes (the backend is one process, so memory
   is shared by every request; a restart only loses a sign-in that is under way).
2. Google sends the browser to the callback with `code` and `state`; `finish_sign_in` checks and
   removes the `state`, exchanges the code, reads the channel (`channels.list(mine=true)`) and
   stores the channel with its refresh token encrypted by `YOUTUBE_TOKEN_KEY` (Fernet).

Secrets: a token, a code, the client secret and the key are never returned, shown or logged. The
logs hold the channel's row id and a result code only. The access token is never stored.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlencode, urlsplit

import anyio.to_thread
import httplib2
from cryptography.fernet import Fernet, InvalidToken
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import env_value
from app.db.models import YouTubeChannel
from app.db.types import utcnow

_logger = logging.getLogger(__name__)

# `requests_oauthlib` and `oauthlib` log the token response at DEBUG. Keep them quiet whatever
# LOG_LEVEL is, so a token can never reach the logs.
for _noisy in ("oauthlib", "requests_oauthlib"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# The one scope. `captions.insert` needs it and it also covers `channels.list`, `videos.insert`,
# `videos.list` and `thumbnails.set`; `youtube.upload` alone is not enough.
FORCE_SSL_SCOPE: Final = "https://www.googleapis.com/auth/youtube.force-ssl"
_AUTH_URI: Final = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URI: Final = "https://oauth2.googleapis.com/token"
_REVOKE_URI: Final = "https://oauth2.googleapis.com/revoke"

CALLBACK_PATH: Final = "/api/youtube/oauth/callback"
_LOOPBACK_HOSTS: Final = ("127.0.0.1", "localhost")

CLIENT_ID_ENV: Final = "YOUTUBE_CLIENT_ID"
CLIENT_SECRET_ENV: Final = "YOUTUBE_CLIENT_SECRET"
REDIRECT_URI_ENV: Final = "YOUTUBE_REDIRECT_URI"
TOKEN_KEY_ENV: Final = "YOUTUBE_TOKEN_KEY"
_ENV_NAMES: Final = (CLIENT_ID_ENV, CLIENT_SECRET_ENV, REDIRECT_URI_ENV, TOKEN_KEY_ENV)

STATUS_CONNECTED: Final = "connected"
STATUS_NEEDS_RECONNECT: Final = "needs_reconnect"

# The results `finish_sign_in` gives. The callback sends one of these in `?youtube=`; the Settings
# page turns it into a sentence, so no free text travels in the address.
RESULT_CONNECTED: Final = "connected"
RESULT_DENIED: Final = "denied"
RESULT_EXPIRED: Final = "expired"
RESULT_NO_CHANNEL: Final = "no_channel"
RESULT_MISSING_SCOPE: Final = "missing_scope"
RESULT_NO_REFRESH_TOKEN: Final = "no_refresh_token"
RESULT_NOT_CONFIGURED: Final = "not_configured"
RESULT_FAILED: Final = "failed"
RESULTS: Final = (
    RESULT_CONNECTED,
    RESULT_DENIED,
    RESULT_EXPIRED,
    RESULT_NO_CHANNEL,
    RESULT_MISSING_SCOPE,
    RESULT_NO_REFRESH_TOKEN,
    RESULT_NOT_CONFIGURED,
    RESULT_FAILED,
)

_SIGN_IN_LIFETIME_S: Final = 600
_MAX_PENDING_SIGN_INS: Final = 50
_GOOGLE_TIMEOUT_S: Final = 10

# Errors that mean "Google could not be reached", not "Google refused".
_NETWORK_ERRORS: Final = (TransportError, OSError, httplib2.HttpLib2Error)


class YouTubeNotConfiguredError(Exception):
    """A `YOUTUBE_*` value is missing or invalid."""


class ChannelNotFoundError(Exception):
    """No connected channel has this row id."""


class GoogleUnreachableError(Exception):
    """Google could not be reached, or answered with an error that is not a refusal."""


class TokenUnusableError(Exception):
    """A stored token cannot be decrypted (the key changed or the value is damaged)."""


@dataclass(frozen=True)
class ConfigProblem:
    name: str
    reason: str


@dataclass(frozen=True)
class ConfigStatus:
    """Which `.env` values are missing or invalid. Names and reasons only, never a value."""

    missing: tuple[str, ...]
    invalid: tuple[ConfigProblem, ...]

    @property
    def ready(self) -> bool:
        return not self.missing and not self.invalid


def config_status() -> ConfigStatus:
    """Checks the four `YOUTUBE_*` values without ever returning one."""
    missing = tuple(name for name in _ENV_NAMES if env_value(name) is None)
    invalid: list[ConfigProblem] = []

    redirect = env_value(REDIRECT_URI_ENV)
    if redirect is not None:
        problem = _redirect_problem(redirect)
        if problem is not None:
            invalid.append(ConfigProblem(REDIRECT_URI_ENV, problem))

    key = env_value(TOKEN_KEY_ENV)
    if key is not None:
        try:
            Fernet(key.encode())
        except (ValueError, TypeError):
            invalid.append(
                ConfigProblem(
                    TOKEN_KEY_ENV,
                    "It is not a valid key. Make one as .env.example describes.",
                )
            )
    return ConfigStatus(missing=missing, invalid=tuple(invalid))


def _redirect_problem(address: str) -> str | None:
    try:
        parts = urlsplit(address)
    except ValueError:
        return "It is not a web address."
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "It must start with http:// or https:// and name a host."
    if parts.hostname not in _LOOPBACK_HOSTS:
        return "The host must be 127.0.0.1 or localhost."
    if parts.path != CALLBACK_PATH:
        return f"The path must be {CALLBACK_PATH}."
    return None


def _require_ready() -> None:
    if not config_status().ready:
        raise YouTubeNotConfiguredError("YouTube is not set up in .env.")


# -- tokens -------------------------------------------------------------------------------------


def _fernet() -> Fernet:
    key = env_value(TOKEN_KEY_ENV)
    if key is None:
        raise YouTubeNotConfiguredError("YouTube is not set up in .env.")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise YouTubeNotConfiguredError("YouTube is not set up in .env.") from exc


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        raise TokenUnusableError("The stored token cannot be read.") from exc


def credentials_for(channel: YouTubeChannel) -> Credentials:
    """Google credentials for a stored channel, to hand to `build("youtube", "v3", ...)`.

    Only the refresh token is stored; the library gets an access token from it when a call needs
    one. Raises `TokenUnusableError` when the stored token cannot be decrypted.
    """
    client_id = env_value(CLIENT_ID_ENV)
    client_secret = env_value(CLIENT_SECRET_ENV)
    if client_id is None or client_secret is None:
        raise YouTubeNotConfiguredError("YouTube is not set up in .env.")
    return Credentials(
        token=None,
        refresh_token=decrypt_token(channel.token_encrypted),
        token_uri=_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=list(channel.scopes),
    )


# -- sign-in ------------------------------------------------------------------------------------

# `state` -> (PKCE verifier, when it expires on the monotonic clock). Only the event loop uses it.
_pending: dict[str, tuple[str, float]] = {}


def _forget_old_sign_ins() -> None:
    now = time.monotonic()
    for state in [s for s, (_, expires) in _pending.items() if expires <= now]:
        del _pending[state]
    while len(_pending) >= _MAX_PENDING_SIGN_INS:
        del _pending[next(iter(_pending))]


def _flow(code_verifier: str | None) -> Flow:
    client_id = env_value(CLIENT_ID_ENV)
    client_secret = env_value(CLIENT_SECRET_ENV)
    redirect = env_value(REDIRECT_URI_ENV)
    if client_id is None or client_secret is None or redirect is None:
        raise YouTubeNotConfiguredError("YouTube is not set up in .env.")
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=[FORCE_SSL_SCOPE],
        redirect_uri=redirect,
        code_verifier=code_verifier,
        autogenerate_code_verifier=code_verifier is None,
    )


def start_sign_in() -> str:
    """Google's authorization address for one sign-in. Raises `YouTubeNotConfiguredError`.

    `access_type=offline` with `prompt=consent select_account` makes Google issue a refresh token
    every time and let the owner pick the account and the channel.
    """
    _require_ready()
    _forget_old_sign_ins()
    flow = _flow(code_verifier=None)
    state = secrets.token_urlsafe(32)
    url, _ = flow.authorization_url(
        access_type="offline", prompt="consent select_account", state=state
    )
    verifier = flow.code_verifier
    if verifier is None:
        raise RuntimeError("The sign-in has no PKCE verifier.")
    _pending[state] = (verifier, time.monotonic() + _SIGN_IN_LIFETIME_S)
    return url


@dataclass(frozen=True)
class _ChannelInfo:
    channel_id: str
    title: str
    thumbnail_url: str | None


@dataclass(frozen=True)
class _Exchange:
    refresh_token: str | None
    scopes: list[str]
    channel: _ChannelInfo | None


def _read_channel(credentials: Credentials) -> _ChannelInfo | None:
    """`channels.list(mine=true)`: the channel the credentials belong to. Runs in a thread."""
    youtube = build("youtube", "v3", credentials=credentials, static_discovery=True)
    answer = youtube.channels().list(part="snippet", mine=True).execute()
    items = answer.get("items") or []
    if not items:
        return None
    item = items[0]
    snippet = item.get("snippet") or {}
    picture = None
    thumbnails = snippet.get("thumbnails") or {}
    for size in ("default", "medium", "high"):
        url = (thumbnails.get(size) or {}).get("url")
        # The picture is shown in the Settings page, so only a secure address is kept.
        if isinstance(url, str) and url.startswith("https://"):
            picture = url
            break
    return _ChannelInfo(
        channel_id=str(item["id"]),
        title=str(snippet.get("title") or item["id"]),
        thumbnail_url=picture,
    )


def _exchange(code: str, verifier: str) -> _Exchange:
    """The code for tokens, then the channel. Runs in a thread."""
    flow = _flow(code_verifier=verifier)
    token = flow.fetch_token(code=code)
    scopes = list(token.get("scope") or [])
    refresh_token = token.get("refresh_token")
    if not refresh_token or FORCE_SSL_SCOPE not in scopes:
        return _Exchange(refresh_token=refresh_token, scopes=scopes, channel=None)
    return _Exchange(
        refresh_token=refresh_token,
        scopes=scopes,
        channel=_read_channel(flow.credentials),
    )


async def finish_sign_in(
    session: AsyncSession, *, code: str | None, state: str | None, error: str | None
) -> str:
    """Completes a sign-in from Google's callback and returns one of `RESULTS`.

    The `state` is removed first, so it works once, whatever happens next.
    """
    if not config_status().ready:
        return RESULT_NOT_CONFIGURED
    entry = _pending.pop(state, None) if state else None
    if entry is None or entry[1] <= time.monotonic():
        return RESULT_EXPIRED
    if error is not None:
        return RESULT_DENIED if error == "access_denied" else RESULT_FAILED
    if not code:
        return RESULT_FAILED

    try:
        outcome = await anyio.to_thread.run_sync(_exchange, code, entry[0])
    except Warning:
        # oauthlib raises a Warning when Google granted other scopes than were asked for.
        return RESULT_MISSING_SCOPE
    except Exception as exc:  # noqa: BLE001 - the Google libraries raise many kinds of error
        # Only the class name is logged: a message can hold part of a request.
        _logger.warning("YouTube sign-in failed: %s", type(exc).__name__)
        return RESULT_FAILED

    if FORCE_SSL_SCOPE not in outcome.scopes:
        return RESULT_MISSING_SCOPE
    if not outcome.refresh_token:
        return RESULT_NO_REFRESH_TOKEN
    if outcome.channel is None:
        return RESULT_NO_CHANNEL

    encrypted = encrypt_token(outcome.refresh_token)
    channel = outcome.channel
    now = utcnow()
    row = (
        await session.execute(
            select(YouTubeChannel).where(YouTubeChannel.channel_id == channel.channel_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = YouTubeChannel(
            channel_id=channel.channel_id,
            title=channel.title,
            thumbnail_url=channel.thumbnail_url,
            token_encrypted=encrypted,
            scopes=outcome.scopes,
            status=STATUS_CONNECTED,
            connected_at=now,
        )
        session.add(row)
    else:
        # The same channel again (Reconnect): the token is replaced, still one row.
        row.title = channel.title
        row.thumbnail_url = channel.thumbnail_url
        row.token_encrypted = encrypted
        row.scopes = outcome.scopes
        row.status = STATUS_CONNECTED
        row.connected_at = now
    await session.commit()
    _logger.info("YouTube channel %s connected", row.id)
    return RESULT_CONNECTED


# -- connected channels -------------------------------------------------------------------------


async def list_channels(session: AsyncSession) -> list[YouTubeChannel]:
    rows = await session.execute(select(YouTubeChannel).order_by(YouTubeChannel.id))
    return list(rows.scalars())


async def _channel_row(session: AsyncSession, row_id: int) -> YouTubeChannel:
    row = await session.get(YouTubeChannel, row_id)
    if row is None:
        raise ChannelNotFoundError("No connected channel has this id.")
    return row


async def mark_needs_reconnect(session: AsyncSession, row_id: int) -> None:
    """Google refused the channel's token (or it cannot be read): ask the owner to reconnect."""
    row = await session.get(YouTubeChannel, row_id)
    if row is not None and row.status != STATUS_NEEDS_RECONNECT:
        row.status = STATUS_NEEDS_RECONNECT
        await session.commit()
        _logger.warning("YouTube channel %s needs reconnecting", row_id)


async def check_channel(session: AsyncSession, row_id: int) -> YouTubeChannel:
    """Uses the channel's token once: renews the access token and reads the channel again.

    Costs one quota unit. A refused or unreadable token makes the channel `needs_reconnect`; a
    working one makes it `connected` again and refreshes its title and picture. Raises
    `GoogleUnreachableError` (status unchanged) when Google cannot be reached.
    """
    _require_ready()
    row = await _channel_row(session, row_id)
    try:
        credentials = credentials_for(row)
    except TokenUnusableError:
        await mark_needs_reconnect(session, row_id)
        return row

    try:
        info = await anyio.to_thread.run_sync(_read_channel, credentials)
    except RefreshError:
        await mark_needs_reconnect(session, row_id)
        return row
    except HttpError as exc:
        if exc.resp.status == 401:
            await mark_needs_reconnect(session, row_id)
            return row
        _logger.warning("YouTube channel %s check: HTTP %s", row_id, exc.resp.status)
        raise GoogleUnreachableError("YouTube answered with an error.") from exc
    except _NETWORK_ERRORS as exc:
        _logger.warning("YouTube channel %s check: %s", row_id, type(exc).__name__)
        raise GoogleUnreachableError("Google could not be reached.") from exc

    if info is None or info.channel_id != row.channel_id:
        # The token now belongs to no channel, or to another one: it cannot be used for this row.
        await mark_needs_reconnect(session, row_id)
        return row
    row.title = info.title
    row.thumbnail_url = info.thumbnail_url
    row.status = STATUS_CONNECTED
    row.last_used_at = utcnow()
    await session.commit()
    return row


def _revoke(token: str) -> bool:
    """Tells Google to revoke a token. Runs in a thread. True when Google no longer honours it."""
    body = urlencode({"token": token}).encode()
    answer: Any = Request()(
        _REVOKE_URI,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=body,
        timeout=_GOOGLE_TIMEOUT_S,
    )
    # 400 is "invalid token": already revoked at Google, so there is nothing left to revoke.
    return answer.status in (200, 400)


async def disconnect(session: AsyncSession, row_id: int) -> bool:
    """Revokes the channel's token at Google (best effort) and deletes the row.

    Returns whether Google was told. The row is deleted either way; the uploads that used it keep
    their snapshot (`youtube_upload.channel_row_id` becomes NULL).
    """
    row = await _channel_row(session, row_id)
    revoked = False
    try:
        token = decrypt_token(row.token_encrypted)
        revoked = await anyio.to_thread.run_sync(_revoke, token)
    except (TokenUnusableError, YouTubeNotConfiguredError):
        pass
    except Exception as exc:  # noqa: BLE001 - never let a failed revoke keep the channel
        _logger.warning("YouTube channel %s revoke failed: %s", row_id, type(exc).__name__)
    await session.delete(row)
    await session.commit()
    _logger.info("YouTube channel %s disconnected (revoked: %s)", row_id, revoked)
    return revoked
