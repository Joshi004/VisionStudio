"""Talking to the GPU server: the health check (Phase 2) and the calls every backend shares
(Phase 5).

The contract guard (Phase 4) is `contract_guard.py` next to this module. The
transcription adapter is `transcriber.py`, and the video adapter is `video_generator.py`.

Upload, submit, status, result, cancel and purge work the same for every backend on the
server (ANALYSIS.md Section 6.1), so they live here once: `upload_file`, `submit_job`,
`job_status`, `job_result_json`, `download_result` (a binary result), `cancel_job` and
`purge_job`. Each takes the base URL to call, which for
transcription is the transcription URL setting. They raise `GpuCallError` for
anything that is not a usable answer, with a `kind` the caller can act on.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from app.core import outbound
from app.core.urls import docker_mapped, join_url
from app.db.types import utcnow

HEALTH_PATH = "/v1/health"
HEALTH_TIMEOUT_S = 5.0

UPLOAD_PATH = "/v1/uploads"
JOBS_PATH = "/v1/jobs"
UPLOAD_TIMEOUT_S = 600.0
SUBMIT_TIMEOUT_S = 30.0
STATUS_TIMEOUT_S = 10.0
RESULT_TIMEOUT_S = 30.0
CANCEL_TIMEOUT_S = 15.0
PURGE_TIMEOUT_S = 30.0
DOWNLOAD_TIMEOUT_S = 600.0
MESSAGE_MAX_CHARS = 2000

# The server's own ids are 32 hex characters. Anything else never goes into a URL path.
_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
_REMOTE_STATUSES = ("queued", "running", "succeeded", "failed")

GpuErrorKind = Literal["unreachable", "not_found", "busy", "rejected", "server_error", "bad_answer"]
RemoteState = Literal["queued", "running", "succeeded", "failed"]


@dataclass(frozen=True)
class HealthResult:
    """The outcome of one health check. Unreachable is a normal outcome, not an error."""

    reachable: bool
    called_url: str
    elapsed_ms: int
    http_status: int | None
    default_partition: str | None
    error: str | None
    checked_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "called_url": self.called_url,
            "elapsed_ms": self.elapsed_ms,
            "http_status": self.http_status,
            "default_partition": self.default_partition,
            "error": self.error,
            "checked_at": self.checked_at.isoformat(),
        }

    @classmethod
    def from_json(cls, data: object) -> HealthResult | None:
        """Rebuilds a stored result. Returns None when the data is missing or malformed."""
        if not isinstance(data, dict):
            return None
        try:
            checked_at = datetime.fromisoformat(data["checked_at"])
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=UTC)
            result = cls(
                reachable=data["reachable"],
                called_url=data["called_url"],
                elapsed_ms=data["elapsed_ms"],
                http_status=data["http_status"],
                default_partition=data["default_partition"],
                error=data["error"],
                checked_at=checked_at,
            )
        except (KeyError, TypeError, ValueError):
            return None

        types_ok = (
            isinstance(result.reachable, bool)
            and isinstance(result.called_url, str)
            and isinstance(result.elapsed_ms, int)
            and (result.http_status is None or isinstance(result.http_status, int))
            and (result.default_partition is None or isinstance(result.default_partition, str))
            and (result.error is None or isinstance(result.error, str))
        )
        return result if types_ok else None


def health_url(base_url: str) -> str:
    """The address a health check calls for this base URL, after Docker mapping."""
    return docker_mapped(join_url(base_url, HEALTH_PATH))


async def check_health(base_url: str) -> HealthResult:
    """Calls `GET /v1/health` on the GPU server. Never raises for a network problem.

    "Reachable" means HTTP 200 with a JSON object whose `status` is "ok".
    """
    called_url = health_url(base_url)
    checked_at = utcnow()
    started = time.monotonic()

    def result(
        *,
        reachable: bool,
        http_status: int | None = None,
        default_partition: str | None = None,
        error: str | None = None,
    ) -> HealthResult:
        return HealthResult(
            reachable=reachable,
            called_url=called_url,
            elapsed_ms=round((time.monotonic() - started) * 1000),
            http_status=http_status,
            default_partition=default_partition,
            error=error,
            checked_at=checked_at,
        )

    try:
        response = await outbound.request(
            "GET", join_url(base_url, HEALTH_PATH), timeout_s=HEALTH_TIMEOUT_S
        )
    except outbound.OutboundError as exc:
        return result(reachable=False, error=str(exc))

    status = response.status_code
    if status != 200:
        return result(
            reachable=False, http_status=status, error=f"The server answered HTTP {status}."
        )

    try:
        body = response.json()
    except ValueError:
        return result(reachable=False, http_status=status, error="The answer was not valid JSON.")

    if not isinstance(body, dict) or body.get("status") != "ok":
        return result(
            reachable=False,
            http_status=status,
            error="The answer is not the GPU API's health response.",
        )

    partition = body.get("default_partition")
    return result(
        reachable=True,
        http_status=status,
        default_partition=partition if isinstance(partition, str) else None,
    )


# --- Calls shared by every backend (Phase 5) ---------------------------------------


class GpuCallError(Exception):
    """A call to the GPU server that did not give a usable answer.

    `kind` says what the caller should do:

    - `unreachable`: no answer (connection, timeout). Never a reason to fail a job.
    - `not_found`: HTTP 404. For a job id, the server does not know it.
    - `busy`: HTTP 429. Wait and try again.
    - `rejected`: any other HTTP 4xx. `status_code` tells 400, 409, 410 and the rest apart.
    - `server_error`: HTTP 5xx.
    - `bad_answer`: a success answer that cannot be used, or one the helper refuses
      (a redirect, a too large answer, a bad address).

    `str(error)` is readable by the user.
    """

    def __init__(self, kind: GpuErrorKind, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.kind: GpuErrorKind = kind
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class RemoteStatus:
    status: RemoteState
    error: str | None
    result_ready: bool
    # Context the server adds (Phase 9 shows it next to the elapsed time). All optional.
    pipeline: str | None = None
    partition: str | None = None
    typical_run_seconds: float | None = None
    typical_basis: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_json(self) -> dict[str, Any]:
        """What a job stores as `output.remote` while it runs."""
        return {
            "status": self.status,
            "pipeline": self.pipeline,
            "partition": self.partition,
            "typical_run_seconds": self.typical_run_seconds,
            "typical_basis": self.typical_basis,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class CancelAnswer:
    """The server's answer to a cancel. `cancelled` is False for a job that had finished."""

    cancelled: bool
    reason: str | None

    def to_json(self) -> dict[str, Any]:
        return {"cancelled": self.cancelled, "reason": self.reason}


@dataclass(frozen=True)
class PurgeAnswer:
    removed_asset_ids: list[str]
    kept_asset_ids: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "removed_asset_ids": self.removed_asset_ids,
            "kept_asset_ids": self.kept_asset_ids,
        }


def server_message(response: outbound.OutboundResponse) -> str:
    """The server's explanation of an error answer: its `detail` text, or a plain fallback."""
    try:
        body = response.json()
    except (ValueError, RecursionError):
        body = None

    detail = body.get("detail") if isinstance(body, dict) else None
    text = ""
    if isinstance(detail, str):
        text = detail
    elif isinstance(detail, list):
        # FastAPI's own validation errors: a list of {"loc", "msg", ...}.
        messages = [
            item["msg"]
            for item in detail
            if isinstance(item, dict) and isinstance(item.get("msg"), str)
        ]
        text = "; ".join(messages)

    text = text.strip() or f"The server answered HTTP {response.status_code}."
    return text[:MESSAGE_MAX_CHARS]


def _check_job_id(job_id: str) -> str:
    if not _JOB_ID.fullmatch(job_id):
        raise GpuCallError("bad_answer", "The job id is not in the form the server uses.")
    return job_id


def _error_for(response: outbound.OutboundResponse) -> GpuCallError:
    status = response.status_code
    message = server_message(response)
    if status == 404:
        return GpuCallError("not_found", message, status)
    if status == 429:
        return GpuCallError("busy", message, status)
    if status >= 500:
        return GpuCallError("server_error", message, status)
    if status >= 400:
        return GpuCallError("rejected", message, status)
    return GpuCallError(
        "bad_answer", f"The server answered HTTP {status}, which was not expected.", status
    )


def _transport_error(exc: outbound.OutboundError) -> GpuCallError:
    if exc.reason in ("connection", "timeout"):
        return GpuCallError("unreachable", str(exc))
    return GpuCallError("bad_answer", str(exc))


def _json_object(response: outbound.OutboundResponse, what: str) -> dict[str, Any]:
    """The body of a 200 answer as a JSON object, or GpuCallError("bad_answer")."""
    if response.status_code != 200:
        raise _error_for(response)
    try:
        body = response.json()
    except (ValueError, RecursionError):
        raise GpuCallError("bad_answer", f"The server's {what} was not valid JSON.") from None
    if not isinstance(body, dict):
        raise GpuCallError("bad_answer", f"The server's {what} was not a JSON object.")
    return body


def _remote_id(body: dict[str, Any], field: str, what: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise GpuCallError("bad_answer", f"The server's {what} had no usable {field}.")
    return value


async def upload_file(base_url: str, path: Path, filename: str, mime: str) -> str:
    """Uploads a file with `POST /v1/uploads` and returns the server's asset id.

    The file is read in a thread, so the event loop is never blocked. The server
    decides the file type from the extension of `filename`.
    """
    content = await asyncio.to_thread(path.read_bytes)
    try:
        response = await outbound.upload(
            join_url(base_url, UPLOAD_PATH),
            filename=filename,
            content=content,
            mime=mime,
            timeout_s=UPLOAD_TIMEOUT_S,
        )
    except outbound.OutboundError as exc:
        raise _transport_error(exc) from exc
    body = _json_object(response, "upload answer")
    return _remote_id(body, "asset_id", "upload answer")


async def submit_job(base_url: str, path: str, body: dict[str, Any]) -> str:
    """POSTs a generation request and returns the server's job id.

    Every backend answers `{job_id, status: "queued"}` (ANALYSIS.md Section 6.1).
    """
    try:
        response = await outbound.request(
            "POST", join_url(base_url, path), json=body, timeout_s=SUBMIT_TIMEOUT_S
        )
    except outbound.OutboundError as exc:
        raise _transport_error(exc) from exc
    answer = _json_object(response, "submit answer")
    return _remote_id(answer, "job_id", "submit answer")


async def job_status(base_url: str, job_id: str) -> RemoteStatus:
    """Asks the server about one job with `GET /v1/jobs/{job_id}`."""
    url = join_url(base_url, f"{JOBS_PATH}/{_check_job_id(job_id)}")
    try:
        response = await outbound.request("GET", url, timeout_s=STATUS_TIMEOUT_S)
    except outbound.OutboundError as exc:
        raise _transport_error(exc) from exc
    body = _json_object(response, "job status")

    status = body.get("status")
    if status not in _REMOTE_STATUSES:
        raise GpuCallError("bad_answer", "The server's job status had an unknown status value.")
    error = body.get("error")
    return RemoteStatus(
        status=status,
        error=error if isinstance(error, str) and error else None,
        result_ready=body.get("result_ready") is True,
        pipeline=_text(body.get("pipeline")),
        partition=_text(body.get("partition")),
        typical_run_seconds=_seconds(body.get("typical_run_seconds")),
        typical_basis=_text(body.get("typical_basis")),
        created_at=_text(body.get("created_at")),
        started_at=_text(body.get("started_at")),
        finished_at=_text(body.get("finished_at")),
    )


def _text(value: object) -> str | None:
    return value[:MESSAGE_MAX_CHARS] if isinstance(value, str) and value else None


def _seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value >= 0 else None


async def job_result_json(base_url: str, job_id: str) -> dict[str, Any]:
    """Downloads a finished job's result when that result is JSON (a transcript).

    409 (not finished yet) and 410 (expired) arrive as GpuCallError("rejected")
    with that `status_code`. 404 arrives as "not_found".
    """
    url = join_url(base_url, f"{JOBS_PATH}/{_check_job_id(job_id)}/result")
    try:
        response = await outbound.request("GET", url, timeout_s=RESULT_TIMEOUT_S)
    except outbound.OutboundError as exc:
        raise _transport_error(exc) from exc
    return _json_object(response, "result")


async def download_result(base_url: str, job_id: str, dest: Path) -> outbound.DownloadResult:
    """Downloads a finished job's result file (a video) into the new file `dest`.

    Same errors as `job_result_json`: 409 (not finished yet) and 410 (expired) arrive as
    GpuCallError("rejected") with that `status_code`, and 404 as "not_found". Nothing is
    left at `dest` when this raises.
    """
    url = join_url(base_url, f"{JOBS_PATH}/{_check_job_id(job_id)}/result")
    try:
        result = await outbound.download_to_file(url, dest, timeout_s=DOWNLOAD_TIMEOUT_S)
    except outbound.OutboundError as exc:
        raise _transport_error(exc) from exc
    if result.status_code != 200:
        dest.unlink(missing_ok=True)
        raise _error_for(
            outbound.OutboundResponse(
                url=result.url,
                status_code=result.status_code,
                headers=httpx.Headers(),
                body=result.error_body,
            )
        )
    return result


async def cancel_job(base_url: str, job_id: str) -> CancelAnswer:
    """Cancels a job that has not finished (`DELETE /v1/jobs/{job_id}`).

    Best effort on the server's side: a job that already finished answers
    `cancelled: false`, which is not an error. A cancelled job later reports `failed`.
    """
    url = join_url(base_url, f"{JOBS_PATH}/{_check_job_id(job_id)}")
    try:
        response = await outbound.request("DELETE", url, timeout_s=CANCEL_TIMEOUT_S)
    except outbound.OutboundError as exc:
        raise _transport_error(exc) from exc
    body = _json_object(response, "cancel answer")
    return CancelAnswer(cancelled=body.get("cancelled") is True, reason=_text(body.get("reason")))


async def purge_job(base_url: str, job_id: str) -> PurgeAnswer:
    """Deletes a finished job from the server, with its output and the uploads no other job
    uses (`DELETE /v1/jobs/{job_id}/purge`). This cannot be undone. The server answers 409
    for a job that is still queued or running.
    """
    url = join_url(base_url, f"{JOBS_PATH}/{_check_job_id(job_id)}/purge")
    try:
        response = await outbound.request("DELETE", url, timeout_s=PURGE_TIMEOUT_S)
    except outbound.OutboundError as exc:
        raise _transport_error(exc) from exc
    body = _json_object(response, "purge answer")
    return PurgeAnswer(
        removed_asset_ids=_id_list(body.get("removed_asset_ids")),
        kept_asset_ids=_id_list(body.get("kept_asset_ids")),
    )


def _id_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item[:200] for item in value if isinstance(item, str)][:50]
