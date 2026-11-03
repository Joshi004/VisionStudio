"""The motion service adapter: Remotion and headless Chrome in the `motion` container (GFX-005).

The service draws a composition to an MP4 and keeps the file until it is fetched and deleted. The
calls are the ones of §4.6 of `Graphics_lab_implementation_phases.md`:

- `start_render`: `POST /renders`, answers the service's `render_id` at once (202);
- `render_status`: `GET /renders/{id}`: `queued`, `rendering`, `done` or `failed`, with progress;
- `download_render`: `GET /renders/{id}/file`, streamed to a file;
- `delete_render`: `DELETE /renders/{id}`;
- `layout`: `POST /layout`, the boxes of the texts of a block scene as the browser lays them out
  (GFX-009);
- `health`: `GET /health`, the versions of Remotion and Chrome.

Every call goes through `core/outbound.py`, so the URL rules and the time limits apply. Every
failure is a `MotionServiceError` whose message names the motion service, so the job (and the
card of the engine) can say what to do: the service being down is the common case.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Final

from app.core import outbound
from app.core.urls import join_url

_logger = logging.getLogger(__name__)

HEALTH_TIMEOUT_S: Final = 5.0
START_TIMEOUT_S: Final = 30.0
STATUS_TIMEOUT_S: Final = 10.0
DELETE_TIMEOUT_S: Final = 10.0
# The service starts a browser for each layout and gives up after 60 s.
LAYOUT_TIMEOUT_S: Final = 90.0
DOWNLOAD_TIMEOUT_S: Final = 300.0
# A graphic is at most 15 s long; a file this large means something is wrong.
DOWNLOAD_MAX_BYTES: Final = 500 * 1024 * 1024

_RENDER_ID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_MESSAGE_MAX_CHARS: Final = 500


class MotionServiceError(Exception):
    """The motion service did not do what was asked. The message is meant for the user."""


def _problem(base_url: str, reason: str) -> MotionServiceError:
    return MotionServiceError(f"The motion service ({base_url}) {reason}")


def _unreachable(base_url: str, exc: outbound.OutboundError) -> MotionServiceError:
    return _problem(
        base_url,
        f"did not answer: {exc} Check that it is running (`docker compose up -d motion`).",
    )


def _check_render_id(render_id: str) -> str:
    if not _RENDER_ID.fullmatch(render_id):
        raise MotionServiceError(f"Not a render id: {render_id!r}")
    return render_id


def _answer_text(body: bytes) -> str:
    """What the service said about a refusal, shortened."""
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict):
        for key in ("message", "error"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value[:_MESSAGE_MAX_CHARS]
    return body.decode("utf-8", errors="replace")[:_MESSAGE_MAX_CHARS] or "no message"


def _json(base_url: str, response: outbound.OutboundResponse, expected: int) -> dict[str, Any]:
    """The JSON object of an answer with the expected status, else a MotionServiceError."""
    if response.status_code != expected:
        raise _problem(
            base_url,
            f"answered {response.status_code}: {_answer_text(response.body)}",
        )
    try:
        data = response.json()
    except ValueError:
        raise _problem(base_url, "answered something that is not JSON.") from None
    if not isinstance(data, dict):
        raise _problem(base_url, "answered something that is not a JSON object.")
    return data


async def health(base_url: str) -> dict[str, Any]:
    """The service's versions: `remotion`, `chrome`, `node`, `templates`, `blocks`."""
    try:
        response = await outbound.request(
            "GET", join_url(base_url, "/health"), timeout_s=HEALTH_TIMEOUT_S
        )
    except outbound.OutboundError as exc:
        raise _unreachable(base_url, exc) from exc
    return _json(base_url, response, 200)


async def start_render(base_url: str, body: dict[str, Any]) -> str:
    """Asks the service to render. Returns its render id."""
    try:
        response = await outbound.request(
            "POST", join_url(base_url, "/renders"), json=body, timeout_s=START_TIMEOUT_S
        )
    except outbound.OutboundError as exc:
        raise _unreachable(base_url, exc) from exc
    render_id = _json(base_url, response, 202).get("render_id")
    if not isinstance(render_id, str):
        raise _problem(base_url, "did not give a render id.")
    return _check_render_id(render_id)


async def layout(base_url: str, body: dict[str, Any]) -> dict[str, Any]:
    """The layout report of a block scene (`{frames: [{frame, texts}], issues}`): the body is
    `{width, height, fps, frames, resolved, input, at_frames}`.
    """
    try:
        response = await outbound.request(
            "POST", join_url(base_url, "/layout"), json=body, timeout_s=LAYOUT_TIMEOUT_S
        )
    except outbound.OutboundError as exc:
        raise _unreachable(base_url, exc) from exc
    return _json(base_url, response, 200)


async def render_status(base_url: str, render_id: str) -> dict[str, Any]:
    """`{state, progress, error, created_at, started_at, finished_at, render_s}`."""
    url = join_url(base_url, f"/renders/{_check_render_id(render_id)}")
    try:
        response = await outbound.request("GET", url, timeout_s=STATUS_TIMEOUT_S)
    except outbound.OutboundError as exc:
        raise _unreachable(base_url, exc) from exc
    if response.status_code == 404:
        raise _problem(
            base_url,
            "does not know this render any more. It was probably restarted while the render ran.",
        )
    return _json(base_url, response, 200)


async def download_render(base_url: str, render_id: str, dest: Path) -> int:
    """Downloads the finished MP4 to the new file `dest` and returns its size in bytes.
    Nothing is left at `dest` when this raises.
    """
    url = join_url(base_url, f"/renders/{_check_render_id(render_id)}/file")
    try:
        result = await outbound.download_to_file(
            url, dest, timeout_s=DOWNLOAD_TIMEOUT_S, max_bytes=DOWNLOAD_MAX_BYTES
        )
    except outbound.OutboundError as exc:
        raise _unreachable(base_url, exc) from exc
    if result.status_code != 200:
        raise _problem(
            base_url,
            f"could not give the video (answered {result.status_code}: "
            f"{_answer_text(result.error_body)}).",
        )
    return result.size_bytes


async def delete_render(base_url: str, render_id: str) -> None:
    """Removes a render from the service. Best effort: it never raises, because the service
    also forgets a render by itself after 30 minutes.
    """
    try:
        url = join_url(base_url, f"/renders/{_check_render_id(render_id)}")
        await outbound.request("DELETE", url, timeout_s=DELETE_TIMEOUT_S)
    except (MotionServiceError, outbound.OutboundError) as exc:
        _logger.info("motion render %s could not be deleted: %s", render_id, exc)
