"""What every remote GPU job handler shares: the settings it reads, its retry numbers, and the
small rules for pre-emption, a poll that got no answer, and a result that was already removed.

These lived in the narration pipeline's jobs until PHASE-046 retired them (they are readable
at the git tag `narration-final`). The image, voice and video handlers (`remote_image`,
`synthesize_speech`, `remote_video`) import them from here.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Literal

from app.db.session import SessionLocal
from app.jobs import live_status, phase_writer, phases, store
from app.providers import gpu_server
from app.providers.gpu_server import GpuCallError

if TYPE_CHECKING:
    from app.jobs.handlers import PollContext

GPU_URL_KEY: Final = "gpu_api_base_url"

SERVER_RETRY_DELAY_S: Final = 5.0
# How many ticks the download is tried again while the server answers 410 but still says the
# result is ready (about two minutes at the default poll interval).
MAX_RESULT_RETRIES: Final = 8

# ANALYSIS.md Section 5.8: a job killed by a higher-priority one is resubmitted unchanged.
_PREEMPTION: Final = re.compile(r"pre-?empt|sigterm|exit code:? ?(?:137|143)", re.IGNORECASE)


def is_preemption(error: str) -> bool:
    return _PREEMPTION.search(error) is not None


async def record_poll_error(job_id: int, exc: GpuCallError, ctx: PollContext | None = None) -> None:
    """What to do when the server could not be asked about a running job. None of this fails
    the job.

    Only a 404 changes what the job shows ("not found on this server", with Resubmit offered):
    it is an answer. Any other problem (no answer, an HTTP error, an unusable answer) leaves the
    job's phase and `last_checked_at` as the server last confirmed them, and is noted in
    `live_status` for the badge's info mark. With `ctx` the phase is collected for the
    dispatcher to write; without it, it is written here.
    """
    if exc.kind != "not_found":
        live_status.note_problem(job_id, str(exc))
        return
    if ctx is not None:
        ctx.record(job_id, phases.NOT_FOUND)
        return
    live_status.clear_problem(job_id)
    async with SessionLocal() as session:
        await store.record_poll(session, job_id, phases.NOT_FOUND)


async def requeue_after_no_answer(job_id: int, exc: GpuCallError) -> None:
    """Puts a job back in the queue because its uploads or its submit got no answer. The
    files it had sent are not kept on our side, but the server still holds them for a while, and
    the next try finds them again by their SHA-256 (`gpu_server.upload_file`) instead of
    sending them again.
    """
    live_status.note_problem(job_id, f"The upload or submit got no answer: {exc}")
    async with SessionLocal() as session:
        await store.requeue(session, job_id, phases.WAITING_TO_START_AGAIN)


def after_gone_result(
    remote_status: str, result_ready: bool, *, retries: int, attempt: int
) -> Literal["try_again", "resubmit", "fail"]:
    """What to do when the result download answered 410 and the status was asked again.

    The server still calls the job finished with its result ready: it has not released the
    file yet, so try the download again at the next tick (a limited number of times).
    Otherwise the result is gone: submit the same request again, up to `MAX_ATTEMPTS`.
    """
    if remote_status == "succeeded" and result_ready and retries < MAX_RESULT_RETRIES:
        return "try_again"
    return "resubmit" if attempt < phases.MAX_ATTEMPTS else "fail"


async def note_uploading(job_id: int, phase: str) -> None:
    """Notes that a job is uploading its files (`phase` says which), and has the uploads it makes
    next show `WAITING_TO_UPLOAD` while they wait for one of the upload places, and `phase`
    again once they have it. The first call also puts the job's uploads in line from now
    (`gpu_server.begin_uploads`), ahead of jobs that begin later. Call it in the job's own
    task, before the uploads. It also has the progress of each file kept for the job
    (`live_status`), starting afresh at the first call of a try.
    """

    async def watcher(waiting: bool) -> None:
        await phase_writer.note(job_id, phases.WAITING_TO_UPLOAD if waiting else phase)

    if not gpu_server.is_watching_upload_progress():
        live_status.reset_upload(job_id)
    gpu_server.watch_upload_progress(_UploadProgress(job_id))
    gpu_server.watch_uploads(watcher)
    gpu_server.begin_uploads()
    await phase_writer.note(job_id, phase)


class _UploadProgress:
    """Keeps the progress of one job's uploads in `live_status`."""

    def __init__(self, job_id: int) -> None:
        self._job_id = job_id

    def started(self, filename: str, total_bytes: int) -> None:
        live_status.upload_started(self._job_id, filename, total_bytes)

    def sent(self, sent_bytes: int) -> None:
        live_status.upload_sent(self._job_id, sent_bytes)

    def done(self) -> None:
        live_status.upload_done(self._job_id)

    def reused(self, filename: str, total_bytes: int) -> None:
        live_status.upload_reused(self._job_id, filename, total_bytes)
