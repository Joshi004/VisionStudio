"""The one place the backend makes outbound HTTP calls.

Every later phase calls out through `request()` (or `upload()`, added in Phase 5,
`download_to_file()`, added in Phase 9, and `post_form()`, added in Phase 13): the GPU
server, the transcription API, the LLM and the image API. All of them share one call path
(`_call`) and so the checks below. Do not create another httpx client anywhere else.

What `request()` enforces (ANALYSIS.md Section 3.6 and 3.7):

- `localhost` and `127.0.0.1` are mapped to `host.docker.internal`.
- Only `http` and `https`, and no user name or password in the URL.
- A time limit for the whole call and a limit on the size of the answer.
- Optionally, a limit on the silence: the longest wait for the first byte, or between two
  pieces of a streamed answer (`idle_timeout_s`). It lets a long answer take as long as it
  needs while a call that has stopped sending is given up on early.
- Redirects are never followed, not even to the same host.
- An explicit User-Agent, because Cloudflare rejects Python's default one
  with error 1010 (Section 3.6).
- The Bitdeer key is attached only for `https://api-inference.bitdeer.ai`.
  It is read from the environment for each call, and is never stored, logged
  or returned. Callers cannot pass headers, so no other code can set
  `Authorization`. The only other headers are the ones this module builds itself for a
  resumed download (`Range`, `If-Range`, `Accept-Encoding`).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from json import loads
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import anyio
import httpx

from app.core.config import env_value
from app.core.urls import UrlError, check_request_url, docker_mapped

USER_AGENT = "VisioStudio/0.1"
BITDEER_HOST = "api-inference.bitdeer.ai"
BITDEER_KEY_ENV = "BITDEEP_API_KEY"

# Small, for JSON answers. Media downloads (`download_to_file`, Phase 9) have their own,
# larger limits.
JSON_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT_S = 10.0
MEDIA_MAX_BYTES = 1024 * 1024 * 1024
DOWNLOAD_TIMEOUT_S = 600.0

_READ_CHUNK_BYTES = 64 * 1024
_DOWNLOAD_CHUNK_BYTES = 256 * 1024
_MAX_LOCATION_CHARS = 200

_logger = logging.getLogger(__name__)
_client: httpx.AsyncClient | None = None
# The client of the file uploads. It keeps no idle connection, so every upload opens its own:
# an upload that reused the connection of the one before was cut by the server's idle timeout
# (about 5 s) while its bytes still waited in the SSH tunnel behind the other uploads.
_upload_client: httpx.AsyncClient | None = None

# When each server last gave an answer (`host:port` -> `time.monotonic()`), so a caller can tell
# a server that answers slowly, because the connection to it is full, from one that does not
# answer at all. Only an answer that is not a server error counts.
_last_answer: dict[str, float] = {}

# Files of a multipart form: `{field: (filename, content, mime)}`, or a list of
# `(field, (filename, content, mime))` when a field repeats (Phase 13).
FileParts = (
    Mapping[str, tuple[str, bytes | io.BytesIO, str]] | Sequence[tuple[str, tuple[str, bytes, str]]]
)

# Told how many bytes of an upload have been handed to the connection, and how many there are.
UploadProgress = Callable[[int, int], None]


class _CountingBytes(io.BytesIO):
    """The bytes of an upload, reporting how many have been read so far. httpx reads a file in
    pieces as it sends it, so the count follows what was handed to the connection. It starts
    again from zero when httpx rewinds the file to send it (a retry makes a new object).
    """

    def __init__(self, content: bytes, on_read: UploadProgress) -> None:
        super().__init__(content)
        self._total = len(content)
        self._on_read = on_read

    def seek(self, offset: int, whence: int = 0, /) -> int:
        position = super().seek(offset, whence)
        if offset == 0 and whence == 0:
            self._on_read(0, self._total)
        return position

    def read(self, size: int | None = -1, /) -> bytes:
        chunk = super().read(size)
        self._on_read(self.tell(), self._total)
        return chunk


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


def _new_client(**options: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=False,
        # Ignore proxy environment variables and ~/.netrc: they could add
        # credentials or send traffic somewhere unexpected.
        trust_env=False,
        headers={"User-Agent": USER_AGENT},
        **options,
    )


def start() -> None:
    """Creates the shared clients. Called once at app start (`app/main.py`)."""
    global _client, _upload_client
    if _client is None:
        _client = _new_client()
    if _upload_client is None:
        _upload_client = _new_client(limits=httpx.Limits(max_keepalive_connections=0))


async def close() -> None:
    """Closes the shared clients. Called once at app shutdown."""
    global _client, _upload_client
    if _client is not None:
        await _client.aclose()
        _client = None
    if _upload_client is not None:
        await _upload_client.aclose()
        _upload_client = None


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


def _get_upload_client() -> httpx.AsyncClient:
    if _upload_client is None:
        raise RuntimeError("outbound.start() has not been called")
    return _upload_client


async def _read_limited(
    response: httpx.Response,
    max_bytes: int,
    on_chunk: Callable[[bytes], None] | None = None,
) -> bytes:
    """Reads the body, refusing to read past `max_bytes` (counted after decompression).

    `on_chunk`, when given, is told each piece as it arrives, so a caller can follow a streamed
    answer while it is still being written. The whole body is still returned at the end.
    """
    too_large = OutboundError("too_large", f"The answer is larger than {max_bytes:,} bytes.")

    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise too_large

    chunks: list[bytes] = []
    size = 0
    # httpx collects pieces until it has `chunk_size` bytes. A caller that follows the answer as
    # it arrives needs each piece as it comes (None), or a short answer would only show up at
    # the end.
    chunk_size = None if on_chunk is not None else _READ_CHUNK_BYTES
    async for chunk in response.aiter_bytes(chunk_size):
        size += len(chunk)
        if size > max_bytes:
            raise too_large
        chunks.append(chunk)
        if on_chunk is not None:
            on_chunk(chunk)
    return b"".join(chunks)


async def request(
    method: str,
    url: str,
    *,
    json: Any = None,
    params: Mapping[str, str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    idle_timeout_s: float | None = None,
    max_bytes: int = JSON_MAX_BYTES,
    on_chunk: Callable[[bytes], None] | None = None,
) -> OutboundResponse:
    """Calls `url` and returns the answer, whatever its status code.

    `timeout_s` limits the whole call. `idle_timeout_s`, when given, also limits each wait
    for more data (the first byte included), so a streamed answer can run for `timeout_s`
    as long as it keeps arriving. The answer is read to its end before it is returned.
    `on_chunk`, when given, is told each piece of the answer as it arrives.

    A non-2xx answer is returned, not raised: the caller decides what it means.
    Raises `OutboundError` when there is no usable answer at all.
    """
    return await _send(
        method,
        url,
        json=json,
        params=params,
        files=None,
        timeout_s=timeout_s,
        idle_timeout_s=idle_timeout_s,
        max_bytes=max_bytes,
        on_chunk=on_chunk,
    )


async def upload(
    url: str,
    *,
    filename: str,
    content: bytes,
    mime: str,
    timeout_s: float,
    max_bytes: int = JSON_MAX_BYTES,
    on_sent: UploadProgress | None = None,
) -> OutboundResponse:
    """POSTs one file as multipart/form-data in the field `file`, as the GPU API's
    `POST /v1/uploads` expects (Phase 5). Every check of `request()` applies.

    The file is held in memory, which is fine for the 1-minute voiceovers of
    iteration 1. `filename` matters: the GPU server decides the file type from
    its extension.

    The call is made on a connection of its own (`_upload_client`). `on_sent`, when given, is
    told `(bytes sent, total bytes)` as the file goes out.
    """
    body: bytes | io.BytesIO = content if on_sent is None else _CountingBytes(content, on_sent)
    return await _send(
        "POST",
        url,
        json=None,
        params=None,
        files={"file": (filename, body, mime)},
        timeout_s=timeout_s,
        max_bytes=max_bytes,
        fresh_connection=True,
    )


async def post_form(
    url: str,
    *,
    data: Mapping[str, str],
    files: Sequence[tuple[str, tuple[str, bytes, str]]],
    timeout_s: float,
    max_bytes: int = JSON_MAX_BYTES,
) -> OutboundResponse:
    """POSTs a multipart/form-data body: text fields, and files that may share a field name
    (Phase 13, the image edit call). Every check of `request()` applies.

    Everything is held in memory, which is fine for the few images of a lab run.
    """
    return await _send(
        "POST",
        url,
        json=None,
        params=None,
        data=data,
        files=files,
        timeout_s=timeout_s,
        max_bytes=max_bytes,
    )


async def _send(
    method: str,
    url: str,
    *,
    json: Any,
    params: Mapping[str, str] | None,
    files: FileParts | None,
    timeout_s: float,
    max_bytes: int,
    data: Mapping[str, str] | None = None,
    idle_timeout_s: float | None = None,
    fresh_connection: bool = False,
    on_chunk: Callable[[bytes], None] | None = None,
) -> OutboundResponse:
    async def read_body(response: httpx.Response, final_url: str) -> OutboundResponse:
        body = await _read_limited(response, max_bytes, on_chunk)
        return OutboundResponse(
            url=final_url,
            status_code=response.status_code,
            headers=response.headers,
            body=body,
        )

    result, _status = await _call(
        method,
        url,
        json=json,
        params=params,
        data=data,
        files=files,
        timeout_s=timeout_s,
        idle_timeout_s=idle_timeout_s,
        handle=read_body,
        fresh_connection=fresh_connection,
    )
    return result


async def _call[T](
    method: str,
    url: str,
    *,
    json: Any,
    params: Mapping[str, str] | None,
    files: FileParts | None,
    timeout_s: float,
    handle: Callable[[httpx.Response, str], Awaitable[T]],
    data: Mapping[str, str] | None = None,
    idle_timeout_s: float | None = None,
    fresh_connection: bool = False,
    extra_headers: Mapping[str, str] | None = None,
) -> tuple[T, int]:
    """Makes one call with every check of this module, and lets `handle` read the answer.

    Everything that applies to a call lives here once: the URL rules, the Docker mapping,
    the time limit, no redirects, the key only for Bitdeer, and the mapping of transport
    problems to `OutboundError`. Returns what `handle` returned and the HTTP status.

    `timeout_s` limits the whole call. `idle_timeout_s`, when given, limits every single wait
    for more data from the server (httpx's read timeout), the wait for the first byte
    included. A stall is then reported differently from a call that took too long.

    `fresh_connection` makes the call on a new connection that is closed afterwards, never on
    one that an earlier call left open. `extra_headers` is only for headers this module builds
    itself (see the module note); `Authorization` is always the one decided here.
    """
    final_url = docker_mapped(url)
    try:
        check_request_url(final_url)
    except UrlError as exc:
        raise OutboundError("url", str(exc)) from exc

    client = _get_upload_client() if fresh_connection else _get_client()
    headers = auth_headers_for(final_url)
    if extra_headers:
        headers.update({k: v for k, v in extra_headers.items() if k.lower() != "authorization"})
    if fresh_connection:
        headers["Connection"] = "close"
    netloc = urlsplit(final_url).netloc
    started = time.monotonic()
    timeout = timeout_s if idle_timeout_s is None else httpx.Timeout(timeout_s, read=idle_timeout_s)

    try:
        async with asyncio.timeout(timeout_s):
            async with client.stream(
                method,
                final_url,
                json=json,
                params=params,
                data=data,
                files=files,
                headers=headers,
                timeout=timeout,
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "")[:_MAX_LOCATION_CHARS]
                    raise OutboundError(
                        "redirect",
                        f"The server answered with a redirect to {location}. "
                        "Redirects are not followed.",
                    )
                result = await handle(response, final_url)
                status_code = response.status_code
    except OutboundError as exc:
        _log_call(method, final_url, started, f"refused ({exc.reason})")
        raise
    except (TimeoutError, httpx.TimeoutException) as exc:
        if idle_timeout_s is not None and isinstance(exc, httpx.ReadTimeout):
            _log_call(method, final_url, started, "stalled")
            raise OutboundError(
                "timeout", f"{netloc} stopped sending for {idle_timeout_s:g} s."
            ) from None
        _log_call(method, final_url, started, "timeout")
        raise OutboundError("timeout", f"No answer from {netloc} within {timeout_s:g} s.") from None
    except httpx.TransportError as exc:
        _log_call(method, final_url, started, "connection error")
        detail = str(exc) or type(exc).__name__
        raise OutboundError("connection", f"Could not reach {netloc} ({detail}).") from exc

    _log_call(method, final_url, started, str(status_code))
    if status_code < 500:
        _last_answer[netloc] = time.monotonic()
    return result, status_code


def seconds_since_answer(url: str) -> float | None:
    """How long ago the server behind `url` last answered a call, or None if it has not since
    the app started. Any call counts, whoever made it, so a busy upload connection that still
    completes calls shows as alive.
    """
    answered = _last_answer.get(urlsplit(docker_mapped(url)).netloc)
    return None if answered is None else time.monotonic() - answered


@dataclass(frozen=True)
class DownloadResult:
    """A finished download: the file at `dest`, or the server's error answer."""

    url: str  # the address actually called, after Docker mapping
    status_code: int
    # Set only for a 200: the size and SHA-256 of the whole file that was written, a part kept
    # from an earlier try included.
    size_bytes: int
    sha256: str
    # Set only for any other status: the answer, up to `JSON_MAX_BYTES`. No file is written.
    error_body: bytes


@dataclass(frozen=True)
class DownloadProgress:
    """Told to `download_to_file`'s `on_progress` as a file arrives.

    `received_bytes` counts the file on disk, the part kept from an earlier try included, and
    `resumed_from` is how many bytes that part was (0 for a download from the start).
    `total_bytes` is 0 when the server did not say. `etag` is the server's strong ETag of the
    file, which a later try needs to resume (None when the server sent none, or a weak one).
    """

    etag: str | None
    total_bytes: int
    received_bytes: int
    resumed_from: int


# A strong ETag as the server writes it: quoted, with no `W/` prefix, no control characters
# and nothing that could end the header line.
_STRONG_ETAG = re.compile(r'"[\x21\x23-\x7e]{1,128}"')
_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")


class _RestartFull(Exception):
    """The answer to a resumed download cannot be used to resume: start again from byte 0."""


class _FileState:
    """Whether `download_to_file` has put anything in `dest` that it must clean up on failure."""

    def __init__(self, touched: bool) -> None:
        self.touched = touched


def _strong_etag(headers: httpx.Headers) -> str | None:
    value = headers.get("etag", "")
    return value if _STRONG_ETAG.fullmatch(value) else None


def _is_encoded(headers: httpx.Headers) -> bool:
    return headers.get("content-encoding", "identity").strip().lower() not in ("", "identity")


def _hash_prefix(path: Path, length: int) -> hashlib._Hash | None:
    """The SHA-256 state after the first `length` bytes of `path`, or None when the file is
    shorter than that. Blocking: call it from a thread.
    """
    digest = hashlib.sha256()
    remaining = length
    with path.open("rb") as file:
        while remaining > 0:
            chunk = file.read(min(_DOWNLOAD_CHUNK_BYTES, remaining))
            if not chunk:
                return None
            digest.update(chunk)
            remaining -= len(chunk)
    return digest


async def download_to_file(
    url: str,
    dest: Path,
    *,
    timeout_s: float = DOWNLOAD_TIMEOUT_S,
    max_bytes: int = MEDIA_MAX_BYTES,
    resume_from: int = 0,
    if_range: str | None = None,
    keep_partial: bool = False,
    on_progress: Callable[[DownloadProgress], None] | None = None,
) -> DownloadResult:
    """GETs `url` and streams a 200 answer into the file `dest`, counting bytes and
    hashing as it goes. Every check of `request()` applies (Phase 2).

    Without `resume_from`, `dest` must not exist: it is created with "xb", and removed again on
    any failure, so a half-written file never stays behind. Any status other than 200 is
    returned with its body in `error_body` and nothing is written. Raises `OutboundError` when
    there is no usable answer, or the file is larger than `max_bytes`.

    Resuming: when `resume_from` is above 0, `dest` is the start of the same file from an
    earlier try, exactly that many bytes long, and `if_range` is the server's strong ETag from
    that try. The request then asks for the rest (`Range` and `If-Range`; the server's
    `GET /v1/jobs/{job_id}/result` answers 206 for it). A 206 is appended to `dest`.
    A 200 means the file changed on the server: `dest` is written again from the start. Any
    answer that cannot be used to continue (416, a 206 for other bytes, an encoded body) starts
    the download again from byte 0. The returned size and SHA-256 are always those of the
    whole file, and the status is 200.

    With `keep_partial`, a download that was cut off (no answer, a stall, a lost connection)
    leaves what was written in `dest`, for the next try to continue. Every other failure still
    removes `dest`. `on_progress` is told as bytes arrive.
    """
    if resume_from > 0 and not _can_resume(dest, resume_from, if_range):
        dest.unlink(missing_ok=True)
        resume_from = 0
    state = _FileState(touched=resume_from > 0)
    try:
        try:
            return await _download_attempt(
                url, dest, timeout_s, max_bytes, resume_from, if_range, on_progress, state
            )
        except _RestartFull:
            dest.unlink(missing_ok=True)
            state.touched = False
            return await _download_attempt(
                url, dest, timeout_s, max_bytes, 0, None, on_progress, state
            )
    except BaseException as exc:
        interrupted = isinstance(exc, OutboundError) and exc.reason in ("connection", "timeout")
        if state.touched and not (keep_partial and interrupted):
            dest.unlink(missing_ok=True)
        raise


def _can_resume(dest: Path, resume_from: int, if_range: str | None) -> bool:
    return (
        if_range is not None
        and _STRONG_ETAG.fullmatch(if_range) is not None
        and dest.is_file()
        and dest.stat().st_size == resume_from
    )


async def _download_attempt(
    url: str,
    dest: Path,
    timeout_s: float,
    max_bytes: int,
    resume_from: int,
    if_range: str | None,
    on_progress: Callable[[DownloadProgress], None] | None,
    state: _FileState,
) -> DownloadResult:
    """One request of `download_to_file`: the whole file, or the rest of it after `resume_from`
    bytes. Raises `_RestartFull` when the answer to a resumed request cannot be used.
    """
    resuming = resume_from > 0
    # Bytes are counted on disk, so the server must not compress them: a range of the encoded
    # body is not a range of the file that is written.
    headers = {"Accept-Encoding": "identity"}
    if resuming and if_range is not None:
        headers["Range"] = f"bytes={resume_from}-"
        headers["If-Range"] = if_range

    async def write_file(response: httpx.Response, final_url: str) -> DownloadResult:
        status = response.status_code
        is_partial = resuming and status == 206
        if status == 416 and resuming:
            raise _RestartFull
        if status != 200 and not is_partial:
            error_body = await _read_limited(response, JSON_MAX_BYTES)
            return DownloadResult(
                url=final_url,
                status_code=status,
                size_bytes=0,
                sha256="",
                error_body=error_body,
            )

        too_large = OutboundError("too_large", f"The file is larger than {max_bytes:,} bytes.")
        encoded = _is_encoded(response.headers)
        etag = None if encoded else _strong_etag(response.headers)
        if is_partial:
            match = _CONTENT_RANGE.fullmatch(response.headers.get("content-range", ""))
            if match is None or encoded or etag != if_range:
                raise _RestartFull
            first, last, total = (int(group) for group in match.groups())
            if first != resume_from or last != total - 1:
                raise _RestartFull
            if total > max_bytes:
                raise too_large
            kept = await anyio.to_thread.run_sync(_hash_prefix, dest, resume_from)
            if kept is None:
                raise _RestartFull
            digest, size, mode, start = kept, resume_from, "ab", resume_from
        else:
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise too_large
            total = int(declared) if declared.isdigit() and not encoded else 0
            digest, size, mode, start = hashlib.sha256(), 0, "wb" if resuming else "xb", 0

        def report() -> None:
            if on_progress is not None:
                on_progress(DownloadProgress(etag, total, size, start))

        async with await anyio.open_file(dest, mode) as file:
            state.touched = True
            report()
            async for chunk in response.aiter_bytes(_DOWNLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > max_bytes:
                    raise too_large
                digest.update(chunk)
                await file.write(chunk)
                report()
        if total and size != total:
            # The connection ended early without an error: what arrived is kept for a resume.
            raise OutboundError("connection", f"The file ended after {size:,} of {total:,} bytes.")
        return DownloadResult(
            url=final_url,
            status_code=200,
            size_bytes=size,
            sha256=digest.hexdigest(),
            error_body=b"",
        )

    result, _status = await _call(
        "GET",
        url,
        json=None,
        params=None,
        files=None,
        timeout_s=timeout_s,
        handle=write_file,
        extra_headers=headers,
    )
    return result


def _log_call(method: str, url: str, started: float, outcome: str) -> None:
    # Method, URL, outcome and time only. Never headers or bodies, which can hold secrets.
    elapsed_ms = round((time.monotonic() - started) * 1000)
    _logger.info("outbound %s %s -> %s in %d ms", method, url, outcome, elapsed_ms)
