"""The image API adapter: Bitdeer's Seedream, over an OpenAI-style interface (Phase 13).

Two calls, both through `core/outbound.py` (so the Bitdeer key goes only to Bitdeer, there are
no redirects, and every call has a time limit):

- `generate`: `POST <base>/images/generations`, a JSON body. It makes an image from text, and
  is also where an `image` field (reference images) is sent.
- `edit`: `POST <base>/images/edits`, a multipart form with the reference images as files.

What was measured on 2026-10-08 (spikes/seedream): Bitdeer answers only `response_format
"b64_json"` (it refuses `url`), honours the `size` exactly, takes 25 to 36 s for one image,
and ignores `watermark`, `seed`, `sequential_image_generation` and, on `/generations`, `image`.
`/edits` is in front of a Cloudflare bot check that blocks any file part. This module does
not hide any of that: a call that fails or is ignored is returned as it happened, so the
Image lab can show it. Nothing here retries.

`generate` and `edit` never raise for a failed call. They return an `ImageCallResult` with a
readable `error`, because the lab keeps failed runs too.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from app.core import outbound
from app.core.urls import join_url

GENERATIONS_PATH: Final = "/images/generations"
EDITS_PATH: Final = "/images/edits"

# A 4K image set as Base64 is large, and the answer carries it all.
MAX_RESPONSE_BYTES: Final = 64 * 1024 * 1024
# One image takes 25 to 36 s, an image set longer. This leaves room for a slow day.
REQUEST_TIMEOUT_S: Final = 240.0

_ERROR_TEXT_CHARS: Final = 300


@dataclass(frozen=True)
class ImageCallResult:
    """What one call came to. `images` holds the decoded results of a 200 answer."""

    # None when there was no answer at all (a timeout, a refused connection).
    http_status: int | None
    images: list[bytes] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    # The answer as JSON, with every image replaced by its size. None when it was not JSON.
    response: Any | None = None
    # A readable message. None only for a 200 answer that held at least one image.
    error: str | None = None
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


# --- Making the data safe to keep and to show --------------------------------------------


def _base64_size(encoded: str) -> int:
    """The decoded size of a Base64 string, without decoding it."""
    return max(0, len(encoded) * 3 // 4 - encoded[-2:].count("="))


def sanitise(payload: Any) -> Any:
    """A copy of a request or an answer with every image replaced by `<image: N bytes>`:
    `b64_json` values, and `data:...;base64,...` strings. The rest is kept as it is.
    """
    if isinstance(payload, dict):
        return {
            key: (
                f"<image: {_base64_size(value):,} bytes>"
                if key == "b64_json" and isinstance(value, str)
                else sanitise(value)
            )
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [sanitise(item) for item in payload]
    if isinstance(payload, str) and payload.startswith("data:") and ";base64," in payload:
        return f"<image: {_base64_size(payload.split(';base64,', 1)[1]):,} bytes>"
    return payload


# --- Reading what came back --------------------------------------------------------------


def _looks_like_cloudflare_challenge(text: str) -> bool:
    lowered = text.lower()
    return "just a moment" in lowered or "challenges.cloudflare.com" in lowered


def describe_failure(status: int, body: bytes) -> str:
    """A readable explanation of an answer that is not a usable 200.

    Bitdeer's own error message is passed on. Cloudflare's two refusals, which come from in
    front of Bitdeer, are named, because their text is a page of HTML or a bare code.
    """
    text = body.decode("utf-8", errors="replace").strip()
    if _looks_like_cloudflare_challenge(text):
        return (
            f"Blocked by Cloudflare's bot check (HTTP {status}, 'Just a moment...'). "
            "The request never reached Bitdeer."
        )
    if "error code: 1010" in text:
        return (
            "Blocked by Cloudflare (error 1010): the request's User-Agent was refused. "
            "The request never reached Bitdeer."
        )
    message = ""
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error")
        candidates = [
            error.get("message") if isinstance(error, dict) else error,
            parsed.get("detail"),
            parsed.get("message"),
        ]
        message = next((c for c in candidates if isinstance(c, str) and c.strip()), "")
    if not message:
        message = text[:_ERROR_TEXT_CHARS] or "No explanation was given."
    return f"HTTP {status}: {message.strip()[:_ERROR_TEXT_CHARS]}"


def _read_answer(response: outbound.OutboundResponse, seconds: float) -> ImageCallResult:
    status = response.status_code
    try:
        parsed = response.json()
    except (ValueError, RecursionError):
        parsed = None

    if status != 200:
        return ImageCallResult(
            http_status=status,
            response=sanitise(parsed) if parsed is not None else _text_response(response.body),
            error=describe_failure(status, response.body),
            seconds=seconds,
        )

    if not isinstance(parsed, dict):
        return ImageCallResult(
            http_status=status,
            response=_text_response(response.body),
            error="HTTP 200, but the answer was not a JSON object.",
            seconds=seconds,
        )

    images: list[bytes] = []
    problems: list[str] = []
    items = parsed.get("data")
    for number, item in enumerate(items if isinstance(items, list) else [], start=1):
        encoded = item.get("b64_json") if isinstance(item, dict) else None
        if isinstance(encoded, str):
            try:
                images.append(base64.b64decode(encoded, validate=True))
            except (binascii.Error, ValueError):
                problems.append(f"image {number} was not valid Base64")
        elif isinstance(item, dict) and isinstance(item.get("url"), str):
            problems.append(f"image {number} came as a link, not as image data")
    usage = parsed.get("usage")
    error = None
    if problems:
        error = "The answer had a problem: " + "; ".join(problems) + "."
    elif not images:
        error = "HTTP 200, but the answer held no images."
    return ImageCallResult(
        http_status=status,
        images=images,
        usage=usage if isinstance(usage, dict) else None,
        response=sanitise(parsed),
        error=error,
        seconds=seconds,
    )


def _text_response(body: bytes) -> dict[str, str]:
    """An answer that is not JSON, kept short, so the run still shows what came back."""
    return {"body": body.decode("utf-8", errors="replace")[:500]}


# --- The two calls -----------------------------------------------------------------------


def _failed(exc: outbound.OutboundError, started: float) -> ImageCallResult:
    return ImageCallResult(http_status=None, error=str(exc), seconds=time.monotonic() - started)


async def generate(base_url: str, body: Mapping[str, Any]) -> ImageCallResult:
    """`POST <base>/images/generations` with a JSON body."""
    started = time.monotonic()
    try:
        response = await outbound.request(
            "POST",
            join_url(base_url, GENERATIONS_PATH),
            json=dict(body),
            timeout_s=REQUEST_TIMEOUT_S,
            max_bytes=MAX_RESPONSE_BYTES,
        )
    except outbound.OutboundError as exc:
        return _failed(exc, started)
    return _read_answer(response, time.monotonic() - started)


async def edit(
    base_url: str,
    fields: Mapping[str, str],
    files: Sequence[tuple[str, str, bytes, str]],
) -> ImageCallResult:
    """`POST <base>/images/edits` as a multipart form. `files` is `(field, filename, content,
    mime)`, and a field may repeat.
    """
    started = time.monotonic()
    try:
        response = await outbound.post_form(
            join_url(base_url, EDITS_PATH),
            data=fields,
            files=[(name, (filename, content, mime)) for name, filename, content, mime in files],
            timeout_s=REQUEST_TIMEOUT_S,
            max_bytes=MAX_RESPONSE_BYTES,
        )
    except outbound.OutboundError as exc:
        return _failed(exc, started)
    return _read_answer(response, time.monotonic() - started)
