"""The one place the backend makes outbound HTTP calls.

Every later phase calls out through `request()`: the GPU server, the
transcription API and the LLM. Phases 5 and 9 extend this module (uploads and
`download_to_file`) and reuse the checks below. Do not create another httpx
client anywhere else.

What `request()` enforces (ANALYSIS.md Section 3.6 and 3.7):

- `localhost` and `127.0.0.1` are mapped to `host.docker.internal`.
- Only `http` and `https`, and no user name or password in the URL.
- A time limit for the whole call and a limit on the size of the answer.
- Redirects are never followed, not even to the same host.
- An explicit User-Agent, because Cloudflare rejects Python's default one
  with error 1010 (Section 3.6).
- The Bitdeer key is attached only for `https://api-inference.bitdeer.ai`.
  It is read from the environment for each call, and is never stored, logged
  or returned. Callers cannot pass headers, so no other code can set
  `Authorization`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from json import loads
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from app.core.config import env_value
from app.core.urls import UrlError, check_request_url, docker_mapped

USER_AGENT = "VisioStudio/0.1"
BITDEER_HOST = "api-inference.bitdeer.ai"
BITDEER_KEY_ENV = "BITDEEP_API_KEY"

# Small, for JSON answers. The larger limit for media downloads arrives with the
# download method in the phase that needs it.
JSON_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT_S = 10.0

_READ_CHUNK_BYTES = 64 * 1024
_MAX_LOCATION_CHARS = 200

_logger = logging.getLogger(__name__)
_client: httpx.AsyncClient | None = None


class OutboundError(Exception):
    """A call that did not produce an answer. `str(error)` is readable by the user."""

    def __init__(
        self,
        reason: Literal["url", "connection", "timeout", "redirect", "too_large"],
        message: str,
    ) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class OutboundResponse:
    url: str  # the address actually called, after Docker mapping
    status_code: int
    headers: httpx.Headers
    body: bytes

    def json(self) -> Any:
        """Parses the body as JSON. Raises ValueError when it is not valid JSON."""
        return loads(self.body)


def start() -> None:
    """Creates the shared client. Called once at app start (`app/main.py`)."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            follow_redirects=False,
            # Ignore proxy environment variables and ~/.netrc: they could add
            # credentials or send traffic somewhere unexpected.
            trust_env=False,
            headers={"User-Agent": USER_AGENT},
        )


async def close() -> None:
    """Closes the shared client. Called once at app shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def auth_headers_for(url: str) -> dict[str, str]:
    """The Authorization header for `url`: the Bitdeer key for Bitdeer, nothing else.

    The match is exact: `https`, the host `api-inference.bitdeer.ai` and port
    443 (written or implied).
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return {}

    is_bitdeer = parts.scheme == "https" and parts.hostname == BITDEER_HOST and port in (None, 443)
    if not is_bitdeer:
        return {}

    key = env_value(BITDEER_KEY_ENV)
    return {"Authorization": f"Bearer {key}"} if key else {}


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("outbound.start() has not been called")
    return _client


async def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    """Reads the body, refusing to read past `max_bytes` (counted after decompression)."""
    too_large = OutboundError("too_large", f"The answer is larger than {max_bytes:,} bytes.")

    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise too_large

    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes(_READ_CHUNK_BYTES):
        size += len(chunk)
        if size > max_bytes:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


async def request(
    method: str,
    url: str,
    *,
    json: Any = None,
    params: Mapping[str, str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_bytes: int = JSON_MAX_BYTES,
) -> OutboundResponse:
    """Calls `url` and returns the answer, whatever its status code.

    A non-2xx answer is returned, not raised: the caller decides what it means.
    Raises `OutboundError` when there is no usable answer at all.
    """
    final_url = docker_mapped(url)
    try:
        check_request_url(final_url)
    except UrlError as exc:
        raise OutboundError("url", str(exc)) from exc

    client = _get_client()
    netloc = urlsplit(final_url).netloc
    started = time.monotonic()

    try:
        async with asyncio.timeout(timeout_s):
            async with client.stream(
                method,
                final_url,
                json=json,
                params=params,
                headers=auth_headers_for(final_url),
                timeout=timeout_s,
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "")[:_MAX_LOCATION_CHARS]
                    raise OutboundError(
                        "redirect",
                        f"The server answered with a redirect to {location}. "
                        "Redirects are not followed.",
                    )
                body = await _read_limited(response, max_bytes)
                result = OutboundResponse(
                    url=final_url,
                    status_code=response.status_code,
                    headers=response.headers,
                    body=body,
                )
    except OutboundError as exc:
        _log_call(method, final_url, started, f"refused ({exc.reason})")
        raise
    except (TimeoutError, httpx.TimeoutException):
        _log_call(method, final_url, started, "timeout")
        raise OutboundError("timeout", f"No answer from {netloc} within {timeout_s:g} s.") from None
    except httpx.TransportError as exc:
        _log_call(method, final_url, started, "connection error")
        detail = str(exc) or type(exc).__name__
        raise OutboundError("connection", f"Could not reach {netloc} ({detail}).") from exc

    _log_call(method, final_url, started, str(result.status_code))
    return result


def _log_call(method: str, url: str, started: float, outcome: str) -> None:
    # Method, URL, outcome and time only. Never headers or bodies, which can hold secrets.
    elapsed_ms = round((time.monotonic() - started) * 1000)
    _logger.info("outbound %s %s -> %s in %d ms", method, url, outcome, elapsed_ms)
