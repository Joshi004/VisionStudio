"""What is known about a job right now, kept in memory, never in the database.

Two things change too often to be written to the `job` row, and are worth nothing after a
restart:

- Upload progress: which file a job is sending, and how many bytes of it have gone out.
- Connection problems: the GPU server did not answer. This is not a state of the job. A job that
  was "queued on cluster" still is, we just cannot see it for now. So the job's `phase` is left
  as it was, and the problem is kept here, with when it began and when it last failed. The
  job's `last_checked_at` still says when the server last confirmed the phase.

Everything runs in the one event loop of the backend, so plain dictionaries are enough. A job
that is no longer active is dropped by `keep_only`, which the dispatcher calls on every tick.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.db.types import utcnow


@dataclass
class UploadState:
    """The file a job is sending now, and how many files it has sent before."""

    filename: str
    sent_bytes: int
    total_bytes: int
    files_done: int


@dataclass
class ConnectionProblem:
    """The server did not answer. `since` is the first failure of this run of failures."""

    message: str
    since: datetime
    last_failed_at: datetime


_uploads: dict[int, UploadState] = {}
_job_problems: dict[int, ConnectionProblem] = {}
# The GPU server did not answer the health check. It applies to every job that needs the server.
_server_problem: ConnectionProblem | None = None


# --- Upload progress ----------------------------------------------------------------------


def reset_upload(job_id: int) -> None:
    """Forgets the uploads of an earlier try. Called when a job begins its uploads."""
    _uploads.pop(job_id, None)


def upload_started(job_id: int, filename: str, total_bytes: int) -> None:
    """A file begins (or begins again after a retry). The files sent before stay counted."""
    previous = _uploads.get(job_id)
    _uploads[job_id] = UploadState(
        filename=filename,
        sent_bytes=0,
        total_bytes=total_bytes,
        files_done=previous.files_done if previous else 0,
    )


def upload_sent(job_id: int, sent_bytes: int) -> None:
    state = _uploads.get(job_id)
    if state is not None:
        state.sent_bytes = min(sent_bytes, state.total_bytes)


def upload_done(job_id: int) -> None:
    """The server accepted the file."""
    state = _uploads.get(job_id)
    if state is not None:
        state.sent_bytes = state.total_bytes
        state.files_done += 1
    # The server answered, so whatever stopped this job before is over.
    clear_problem(job_id)


def upload_of(job_id: int) -> UploadState | None:
    return _uploads.get(job_id)


# --- Connection problems ------------------------------------------------------------------


def _noted(current: ConnectionProblem | None, message: str) -> ConnectionProblem:
    now = utcnow()
    return ConnectionProblem(
        message=message,
        since=current.since if current else now,
        last_failed_at=now,
    )


def note_problem(job_id: int, message: str) -> None:
    """A call about this job got no answer."""
    _job_problems[job_id] = _noted(_job_problems.get(job_id), message)


def clear_problem(job_id: int) -> None:
    _job_problems.pop(job_id, None)


def note_server_problem(message: str) -> None:
    """The health check got no answer: every job that needs the GPU server is affected."""
    global _server_problem
    _server_problem = _noted(_server_problem, message)


def clear_server_problem() -> None:
    global _server_problem
    _server_problem = None


def problem_of(job_id: int, *, needs_gpu: bool) -> ConnectionProblem | None:
    """The problem to show for a job: its own, or the server's when the job needs the server.
    The one that began first wins, so the time shown is how long the job has not been seen.
    """
    own = _job_problems.get(job_id)
    server = _server_problem if needs_gpu else None
    if own is None or server is None:
        return own or server
    return own if own.since <= server.since else server


# --- Cleanup ------------------------------------------------------------------------------


def keep_only(active_job_ids: Iterable[int]) -> None:
    """Drops what is kept for every job that is not in `active_job_ids` (queued or running)."""
    keep = set(active_job_ids)
    for table in (_uploads, _job_problems):
        for job_id in [job_id for job_id in table if job_id not in keep]:
            del table[job_id]
