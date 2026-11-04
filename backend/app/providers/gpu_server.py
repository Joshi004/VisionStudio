"""Talking to the GPU server: the health check (Phase 2) and the calls every backend shares
(Phase 5).

The contract guard (Phase 4) is `contract_guard.py` next to this module. The
transcription adapter is `transcriber.py`, and the video adapter is `video_generator.py`.

Upload, submit, status, result, cancel and purge work the same for every backend on the
server (ANALYSIS.md Section 6.1), so they live here once: `upload_file`, `submit` (the whole
answer, with the GPUs and estimate a MiniMax H3 job gets) and `submit_job` (only the job id),
`job_status`, `job_result_json`, `download_result` (a binary result), `cancel_job` and
`purge_job`. Each takes the base URL to call, which for
transcription is the transcription URL setting. They raise `GpuCallError` for
anything that is not a usable answer, with a `kind` the caller can act on.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

from app.core import outbound
from app.core.urls import docker_mapped, join_url
from app.db.types import utcnow
from app.jobs import live_status
from app.services.storage import get_storage

_logger = logging.getLogger(__name__)

HEALTH_PATH = "/v1/health"
HEALTH_TIMEOUT_S = 5.0
# A health check with no answer still counts as "busy", not "down", when the server answered
# some other call this recently. About one check interval at the longest back-off.
BUSY_WINDOW_S = 120.0

UPLOAD_PATH = "/v1/uploads"
# Version 0.22.0 of the server's guide: asks whether the server already holds a file, by its
# SHA-256. 200 gives the existing asset id, 404 says to upload the file as usual.
UPLOAD_BY_HASH_PATH = "/v1/uploads/by-hash"
BY_HASH_TIMEOUT_S = 15.0
# An upload answer that does not match the file sent (SHA-256 or size) is sent again this many
# times in all, then the connection is treated as unreliable.
UPLOAD_INTEGRITY_ATTEMPTS = 2
JOBS_PATH = "/v1/jobs"
UPLOAD_TIMEOUT_S = 600.0
# A file whose connection failed is sent again once, after this pause, before the caller is told
# the server is unreachable. A connection that fails twice in a row is a real outage.
UPLOAD_ATTEMPTS = 2
UPLOAD_RETRY_DELAY_S = 2.0
SUBMIT_TIMEOUT_S = 30.0
STATUS_TIMEOUT_S = 10.0
RESULT_TIMEOUT_S = 30.0
CANCEL_TIMEOUT_S = 15.0
PURGE_TIMEOUT_S = 30.0
DOWNLOAD_TIMEOUT_S = 600.0
MESSAGE_MAX_CHARS = 2000


class TransferSlots:
    """At most `limit` transfers at once. A rolling window: a transfer that has to wait gets
    the first place any transfer gives up, not a place in a later batch. Of the transfers
    waiting, the one with the lowest `order` gets it; for the same order, the one that asked
    first.

    The limit can change while transfers run. Lowering it stops none of them: no new one starts
    until fewer than the new limit are running.
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._in_use = 0
        self._waiting: set[tuple[float, int]] = set()
        self._asked = itertools.count()
        self._changed = asyncio.Event()

    @property
    def limit(self) -> int:
        return self._limit

    def set_limit(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("A transfer limit must be at least 1.")
        self._limit = limit
        self._changed.set()

    def locked(self) -> bool:
        """True when a transfer starting now would have to wait."""
        return self._in_use >= self._limit or bool(self._waiting)

    @asynccontextmanager
    async def place(self, order: float) -> AsyncIterator[None]:
        """Holds one place while the block runs, after waiting for one if none is free."""
        key = (order, next(self._asked))
        self._waiting.add(key)
        try:
            while self._in_use >= self._limit or min(self._waiting) != key:
                self._changed.clear()
                await self._changed.wait()
        finally:
            # Taken or given up (cancelled): either way the next in line may go now.
            self._waiting.discard(key)
            self._changed.set()
        self._in_use += 1
        try:
            yield
        finally:
            self._in_use -= 1
            self._changed.set()


# How many files are sent to the server at once, and how many results are fetched from it at
# once, however many jobs are running. The server queues the jobs, so waiting here costs nothing,
# while many large transfers at once choke the connection to it: through one SSH tunnel they
# share one connection, so more of them do not move more data, each just takes longer. The
# dispatcher sets both from the settings on every tick; these values hold until its first one.
DEFAULT_PARALLEL_UPLOADS = 2
DEFAULT_PARALLEL_DOWNLOADS = 2
_upload_slots = TransferSlots(DEFAULT_PARALLEL_UPLOADS)
_download_slots = TransferSlots(DEFAULT_PARALLEL_DOWNLOADS)


def set_transfer_limits(uploads: int, downloads: int) -> None:
    """Sets how many uploads and how many downloads may run at once, from now on."""
    _upload_slots.set_limit(uploads)
    _download_slots.set_limit(downloads)


# Told by `upload_file` when the upload has to wait for a free place (True) and when it got one
# (False), so a job can show "waiting to upload" apart from "uploading". It is set per task (a
# job's own task), so it is never mixed up between jobs. See `watch_uploads`.
UploadWatcher = Callable[[bool], Awaitable[None]]
_upload_watcher: ContextVar[UploadWatcher | None] = ContextVar("upload_watcher", default=None)


def watch_uploads(watcher: UploadWatcher | None) -> None:
    """Sets who is told about the uploads made by the current task from now on (None: nobody)."""
    _upload_watcher.set(watcher)


class UploadReporter(Protocol):
    """Told how each file of the current task's job goes (`watch_upload_progress`)."""

    def started(self, filename: str, total_bytes: int) -> None:
        """A file begins, or begins again after a failed try."""

    def sent(self, sent_bytes: int) -> None:
        """Bytes of the file handed to the connection so far."""

    def done(self) -> None:
        """The server accepted the file."""

    def reused(self, filename: str, total_bytes: int) -> None:
        """The server already had the file (found by its SHA-256), so nothing was sent."""


_upload_reporter: ContextVar[UploadReporter | None] = ContextVar("upload_reporter", default=None)


def watch_upload_progress(reporter: UploadReporter | None) -> None:
    """Sets who is told how the files uploaded by the current task go (None: nobody)."""
    _upload_reporter.set(reporter)


def is_watching_upload_progress() -> bool:
    """True when the current task already has an upload reporter."""
    return _upload_reporter.get() is not None


# When the current task's job began uploading (`time.monotonic()`), set per task like the
# watcher. A free upload place goes to the job that began first, so a job sends all its files
# and submits before later jobs take their turn. In plain arrival order every job would queue
# again behind all the others for each of its files: all jobs would advance together and none
# would submit for a long time, while the server deletes an upload that no submitted job uses
# 60 minutes after it arrived.
_upload_order: ContextVar[float | None] = ContextVar("upload_order", default=None)


def begin_uploads() -> None:
    """Marks the current task's job as beginning its uploads now, unless it already has."""
    if _upload_order.get() is None:
        _upload_order.set(time.monotonic())


# The server's own ids are 32 hex characters. Anything else never goes into a URL path.
_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
_REMOTE_STATUSES = ("queued", "running", "succeeded", "failed")
# Why a queued job is not running yet (`queue_state` of a job's status, guide 0.25.0).
QUEUE_STATES = (
    "scheduling",
    "model_limit",
    "gpu_limit",
    "priority",
    "slurm_pending",
    "model_loading",
)
# The server's own range for a job's priority.
PRIORITY_MOST_URGENT = 1
PRIORITY_LEAST_URGENT = 10

GpuErrorKind = Literal["unreachable", "not_found", "busy", "rejected", "server_error", "bad_answer"]
RemoteState = Literal["queued", "running", "succeeded", "failed"]


@dataclass(frozen=True)
class HealthResult:
    """The outcome of one health check. Unreachable is a normal outcome, not an error.

    `busy` is set when the health check got no answer in time but the server answered another
    call a moment ago: the connection to it is full, the server is not down. `reachable` is
    then still False, because the health check itself did not succeed.
    """

    reachable: bool
    called_url: str
    elapsed_ms: int
    http_status: int | None
    default_partition: str | None
    error: str | None
    checked_at: datetime
    busy: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "busy": self.busy,
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
                # Results stored before `busy` existed have no such key.
                busy=data.get("busy", False),
            )
        except (KeyError, TypeError, ValueError):
            return None

        types_ok = (
            isinstance(result.reachable, bool)
            and isinstance(result.busy, bool)
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

    "Reachable" means HTTP 200 with a JSON object whose `status` is "ok". A health check that
    got no answer in time, while the server answered another call within `BUSY_WINDOW_S`, is
    reported `busy`: a connection full of uploads answers a small request late, or not within
    the time limit. A refused or failed connection is never "busy".
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
        busy: bool = False,
    ) -> HealthResult:
        return HealthResult(
            reachable=reachable,
            called_url=called_url,
            elapsed_ms=round((time.monotonic() - started) * 1000),
            http_status=http_status,
            default_partition=default_partition,
            error=error,
            checked_at=checked_at,
            busy=busy,
        )

    try:
        response = await outbound.request(
            "GET", join_url(base_url, HEALTH_PATH), timeout_s=HEALTH_TIMEOUT_S
        )
    except outbound.OutboundError as exc:
        since_answer = outbound.seconds_since_answer(called_url)
        if exc.reason == "timeout" and since_answer is not None and since_answer <= BUSY_WINDOW_S:
            return result(
                reachable=False,
                busy=True,
                error=f"{exc} The server answered another request {since_answer:.0f} s ago.",
            )
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
            error="The answer is not the remote server API's health response.",
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
    # Only on an audio-to-video job that asked for `lip_sync: true` (version 0.12.0 of the
    # server's guide): {"requested": true, "applied": bool, "error": str | None}. Lip sync can
    # fail silently (the job still succeeds), so `applied` is how a caller finds out.
    lip_sync: dict[str, Any] | None = None
    # Version 0.15.0 of the server's guide: a backend that sizes each request before it queues
    # the job (MiniMax H3) says how many GPUs the job was given and about how long it will run
    # once it starts (the queue wait is not included). None for every other backend. Prefer
    # `estimated_run_seconds` over `typical_run_seconds` when it is there.
    gpus: int | None = None
    estimated_run_seconds: float | None = None
    # Version 0.23.0 and 0.25.0 of the server's guide: the job's priority (1 most urgent, 10
    # least) and, only while it is queued, why it is not running yet (one of `QUEUE_STATES`).
    priority: int | None = None
    queue_state: str | None = None

    def to_json(self) -> dict[str, Any]:
        """What a job stores as `output.remote` while it runs."""
        return {
            "priority": self.priority,
            "queue_state": self.queue_state,
            "status": self.status,
            "pipeline": self.pipeline,
            "partition": self.partition,
            "typical_run_seconds": self.typical_run_seconds,
            "typical_basis": self.typical_basis,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "lip_sync": self.lip_sync,
            "gpus": self.gpus,
            "estimated_run_seconds": self.estimated_run_seconds,
        }


@dataclass(frozen=True)
class SubmitAnswer:
    """The server's answer to a submit: the job id, and (MiniMax H3 only, version 0.15.0 of the
    server's guide) the GPUs the job was given and its estimated run time in seconds.
    """

    job_id: str
    gpus: int | None = None
    estimated_run_seconds: float | None = None

    def to_json(self) -> dict[str, Any]:
        """What a job stores on its input as `submit_answer`, next to the exact request."""
        return {"gpus": self.gpus, "estimated_run_seconds": self.estimated_run_seconds}


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
    """Gets a file onto the server and returns the server's asset id.

    First asks the server whether it already holds the file (`POST /v1/uploads/by-hash`, version
    0.22.0 of its guide). If it does, its asset id is used and nothing is sent: this is what
    makes a job that was put back in the queue skip the files it had already sent. Any other
    answer (404, an error, no answer, an older server) goes on to the upload itself.

    The upload is `POST /v1/uploads`. The file is read in a thread, so the event loop is never
    blocked. The server decides the file type from the extension of `filename`. The answer's
    SHA-256 and size are compared with the bytes sent; a file that arrived damaged is sent once
    more, and then reported as `unreachable` so the job is put back in the queue.

    At most the upload limit (`set_transfer_limits`) run at once; the others wait for a free
    place before the file is even read, so the files waiting are not held in memory. The job
    that began uploading first gets the next place (`begin_uploads`). The time limit starts
    when the upload does, not while it waits. Asking the server about a file needs no place.
    """
    reporter = _upload_reporter.get()
    sha256, size_bytes = await asyncio.to_thread(_hash_file, path)
    known_id = await _find_by_hash(base_url, sha256, size_bytes)
    if known_id is not None:
        _logger.info("upload of %s skipped: the server already has it (%s)", filename, known_id)
        if reporter is not None:
            reporter.reused(filename, size_bytes)
        return known_id

    watcher = _upload_watcher.get()
    order = _upload_order.get()
    waited = watcher is not None and _upload_slots.locked()
    if watcher is not None and waited:
        await watcher(True)
    async with _upload_slots.place(time.monotonic() if order is None else order):
        if watcher is not None and waited:
            await watcher(False)
        content = await asyncio.to_thread(path.read_bytes)
        sent_sha256 = await asyncio.to_thread(lambda: hashlib.sha256(content).hexdigest())
        for attempt in range(1, UPLOAD_INTEGRITY_ATTEMPTS + 1):
            response = await _send_file(base_url, content, filename, mime)
            body = _json_object(response, "upload answer")
            if _arrived_intact(body, sent_sha256, len(content)):
                break
            _logger.warning(
                "the server stored %s differently from what was sent (try %d of %d)",
                filename,
                attempt,
                UPLOAD_INTEGRITY_ATTEMPTS,
            )
        else:
            raise GpuCallError(
                "unreachable",
                "The server's copy of the uploaded file did not match what was sent, twice.",
            )
    if reporter is not None:
        reporter.done()
    return _remote_id(body, "asset_id", "upload answer")


def _hash_file(path: Path) -> tuple[str, int]:
    """The SHA-256 (hex) and size of a file, read in pieces so it is never held whole."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _arrived_intact(body: dict[str, Any], sha256: str, size_bytes: int) -> bool:
    """Does the server's upload answer describe the file that was sent? An answer without the
    field (a server older than 0.22.0) cannot be checked, and counts as fine.
    """
    stored_sha256 = body.get("sha256")
    if isinstance(stored_sha256, str) and stored_sha256.lower() != sha256:
        return False
    stored_size = body.get("size_bytes")
    if isinstance(stored_size, int) and not isinstance(stored_size, bool):
        return stored_size == size_bytes
    return True


async def _find_by_hash(base_url: str, sha256: str, size_bytes: int) -> str | None:
    """The asset id of a copy of the file the server already holds, or None when it has none or
    could not be asked. Never raises: not knowing means the file is uploaded.
    """
    try:
        response = await outbound.request(
            "POST",
            join_url(base_url, UPLOAD_BY_HASH_PATH),
            json={"sha256": sha256},
            timeout_s=BY_HASH_TIMEOUT_S,
        )
        body = _json_object(response, "by-hash answer")
        asset_id = _remote_id(body, "asset_id", "by-hash answer")
    except (outbound.OutboundError, GpuCallError) as exc:
        _logger.info("the server was not asked for a copy of the file (%s)", exc)
        return None
    # A copy that is not the file asked for is never used.
    if not _arrived_intact(body, sha256, size_bytes):
        return None
    return asset_id


async def _send_file(
    base_url: str, content: bytes, filename: str, mime: str
) -> outbound.OutboundResponse:
    """Sends one file, and once more if the connection failed (`UPLOAD_ATTEMPTS`). The progress
    reporter is told when a try begins and as the bytes go out.
    """
    reporter = _upload_reporter.get()
    on_sent = None if reporter is None else lambda sent, _total: reporter.sent(sent)
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        if reporter is not None:
            reporter.started(filename, len(content))
        try:
            return await outbound.upload(
                join_url(base_url, UPLOAD_PATH),
                filename=filename,
                content=content,
                mime=mime,
                timeout_s=UPLOAD_TIMEOUT_S,
                on_sent=on_sent,
            )
        except outbound.OutboundError as exc:
            if exc.reason == "connection" and attempt < UPLOAD_ATTEMPTS:
                _logger.warning(
                    "upload of %s failed (%s); sending it again in %.0f s",
                    filename,
                    exc,
                    UPLOAD_RETRY_DELAY_S,
                )
                await asyncio.sleep(UPLOAD_RETRY_DELAY_S)
                continue
            raise _transport_error(exc) from exc
    raise AssertionError("unreachable: the last attempt returns or raises")


async def submit(base_url: str, path: str, body: dict[str, Any]) -> SubmitAnswer:
    """POSTs a generation request and returns the server's whole answer.

    Every backend answers `{job_id, status: "queued"}` (ANALYSIS.md Section 6.1). A backend that
    sizes the request first (MiniMax H3) adds `gpus` and `estimated_run_seconds`, which are
    kept as the server said them and are None for every other backend.
    """
    try:
        response = await outbound.request(
            "POST", join_url(base_url, path), json=body, timeout_s=SUBMIT_TIMEOUT_S
        )
    except outbound.OutboundError as exc:
        raise _transport_error(exc) from exc
    answer = _json_object(response, "submit answer")
    return SubmitAnswer(
        job_id=_remote_id(answer, "job_id", "submit answer"),
        gpus=_count(answer.get("gpus")),
        estimated_run_seconds=_seconds(answer.get("estimated_run_seconds")),
    )


async def submit_job(base_url: str, path: str, body: dict[str, Any]) -> str:
    """POSTs a generation request and returns only the server's job id, for the callers that
    do not need the GPUs and the estimate (speech, transcription and images).
    """
    return (await submit(base_url, path, body)).job_id


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
        lip_sync=_lip_sync(body.get("lip_sync")),
        gpus=_count(body.get("gpus")),
        estimated_run_seconds=_seconds(body.get("estimated_run_seconds")),
        priority=_priority(body.get("priority")),
        queue_state=_queue_state(body.get("queue_state")),
    )


def _priority(value: object) -> int | None:
    """A priority the server's range allows, or None when it sent nothing usable."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if PRIORITY_MOST_URGENT <= value <= PRIORITY_LEAST_URGENT else None


def _queue_state(value: object) -> str | None:
    return value if isinstance(value, str) and value in QUEUE_STATES else None


def _lip_sync(value: object) -> dict[str, Any] | None:
    """Reads the job status's `lip_sync` object, or None when it is absent or not an object."""
    if not isinstance(value, dict):
        return None
    return {
        "requested": value.get("requested") is True,
        "applied": value.get("applied") is True,
        "error": _text(value.get("error")),
    }


def _text(value: object) -> str | None:
    return value[:MESSAGE_MAX_CHARS] if isinstance(value, str) and value else None


def _seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value >= 0 else None


def _count(value: object) -> int | None:
    """A whole number of GPUs of at least 1, or None when the server sent nothing usable."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 1 else None


async def job_result_json(base_url: str, job_id: str) -> dict[str, Any]:
    """Downloads a finished job's result when that result is JSON (a transcript).

    409 (not finished yet) and 410 (expired) arrive as GpuCallError("rejected")
    with that `status_code`. 404 arrives as "not_found".
    """
    url = join_url(base_url, f"{JOBS_PATH}/{_check_job_id(job_id)}/result")
    async with _download_slots.place(time.monotonic()):  # see `set_transfer_limits`
        try:
            response = await outbound.request("GET", url, timeout_s=RESULT_TIMEOUT_S)
        except outbound.OutboundError as exc:
            raise _transport_error(exc) from exc
    return _json_object(response, "result")


@dataclass(frozen=True)
class _PartialDownload:
    """What a cut-off download needs to continue: the server's ETag of the file it was fetching.
    The bytes themselves are the file `Storage.partial_download_path` names.
    """

    etag: str
    total_bytes: int


# Keyed by the server's job id. Memory only, like the temp folder the partial files are in,
# which is cleared when the app starts: after a restart there is neither, so they never
# disagree. A partial file without an entry here is never used.
_partial_downloads: dict[str, _PartialDownload] = {}


def _resume_point(job_id: str, partial: Path) -> tuple[int, str | None]:
    """How many bytes of this job's result are on disk from an earlier try, and the ETag to ask
    for the rest with. (0, None) when there is nothing usable: any leftover is removed.
    """
    known = _partial_downloads.get(job_id)
    size = partial.stat().st_size if partial.is_file() else 0
    if known is not None and size > 0:
        return size, known.etag
    _forget_partial(job_id, partial)
    return 0, None


def _forget_partial(job_id: str, partial: Path) -> None:
    partial.unlink(missing_ok=True)
    _partial_downloads.pop(job_id, None)


async def download_result(base_url: str, job_id: str, dest: Path) -> outbound.DownloadResult:
    """Downloads a finished job's result file (a video, an image, a sound) to the new file
    `dest`.

    Same errors as `job_result_json`: 409 (not finished yet) and 410 (expired) arrive as
    GpuCallError("rejected") with that `status_code`, and 404 as "not_found". Nothing is
    left at `dest` when this raises.

    A download that is cut off (no answer, a stall, a lost connection) keeps what it received,
    in a partial file of the temp folder. The next call for the same job asks the server for
    the rest only (`Range` with `If-Range`), so every try adds to the file instead of starting
    again. A server that changed the file in between sends it whole. The partial file is
    removed when the server says the result is gone (404, 410). `dest` only appears when the
    whole file is there.

    At most the download limit (`set_transfer_limits`) are fetched at once; the others wait for
    a free place, and the time limit starts when the download does.
    """
    url = join_url(base_url, f"{JOBS_PATH}/{_check_job_id(job_id)}/result")
    partial = get_storage().partial_download_path(job_id)
    resume_from, etag = _resume_point(job_id, partial)

    def on_progress(progress: outbound.DownloadProgress) -> None:
        if progress.etag is None:
            _partial_downloads.pop(job_id, None)  # without an ETag the file cannot be continued
        else:
            _partial_downloads[job_id] = _PartialDownload(progress.etag, progress.total_bytes)
        live_status.download_progress(
            job_id, progress.received_bytes, progress.total_bytes, progress.resumed_from
        )

    try:
        async with _download_slots.place(time.monotonic()):
            try:
                result = await outbound.download_to_file(
                    url,
                    partial,
                    timeout_s=DOWNLOAD_TIMEOUT_S,
                    resume_from=resume_from,
                    if_range=etag,
                    keep_partial=True,
                    on_progress=on_progress,
                )
            except outbound.OutboundError as exc:
                raise _transport_error(exc) from exc
    finally:
        live_status.download_ended(job_id)
        if not partial.exists():
            _partial_downloads.pop(job_id, None)  # the download removed it: nothing to continue

    if result.status_code != 200:
        if result.status_code in (404, 410):
            _forget_partial(job_id, partial)
        raise _error_for(
            outbound.OutboundResponse(
                url=result.url,
                status_code=result.status_code,
                headers=httpx.Headers(),
                body=result.error_body,
            )
        )
    await asyncio.to_thread(partial.replace, dest)
    _partial_downloads.pop(job_id, None)
    if resume_from > 0:
        _logger.info(
            "result of server job %s fetched in more than one try (%d bytes were kept)",
            job_id,
            resume_from,
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


async def set_priority(base_url: str, job_id: str, priority: int) -> None:
    """Changes the priority of a job that is still queued (`PUT /v1/jobs/{job_id}/priority`).

    409 (the job already runs or finished, or its backend does not order its queue by priority)
    arrives as GpuCallError("rejected") with that `status_code`, and 404 as "not_found". The
    caller decides whether either one matters.
    """
    if not PRIORITY_MOST_URGENT <= priority <= PRIORITY_LEAST_URGENT:
        raise ValueError("A priority is a whole number from 1 to 10.")
    url = join_url(base_url, f"{JOBS_PATH}/{_check_job_id(job_id)}/priority")
    try:
        response = await outbound.request(
            "PUT", url, json={"priority": priority}, timeout_s=SUBMIT_TIMEOUT_S
        )
    except outbound.OutboundError as exc:
        raise _transport_error(exc) from exc
    _json_object(response, "priority answer")


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
