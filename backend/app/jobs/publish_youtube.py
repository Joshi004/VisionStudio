"""The `publish_youtube` job: send a render to YouTube and wait until YouTube has processed it
(YT-004, `YouTube_publish_phases.md` §4.6, steps 1 and 2).

A local job, one at a time. Its input is `{upload_id, target}` (`services/youtube_publish`), and
everything it sends is read from the `youtube_upload` row's `sent` snapshot, never from the draft.

1. **The video.** Only when the upload has no `video_id`: a resumable `videos.insert`, sent in
   chunks in a worker thread, with the bytes sent kept for the panel in `live_status`. The video
   id is stored the moment the insert returns, in its own transaction. A restart during this step
   starts it again from the beginning (`start_again`): YouTube makes the video only when an upload
   is complete.
2. **Processing.** `videos.list` says whether YouTube has processed the video. The job does not
   hold its place while it waits: between two checks it is queued again (`store.requeue`), with
   `next_check_at` and `waiting_since` kept in its input (clock times, so they survive a
   restart). A start before `next_check_at` queues it again at once without asking Google. When
   the video is processed the job succeeds; when YouTube fails or rejects it, the job fails; after
   `MAX_WAIT_S` it records `gave_up` and succeeds, keeping the video.

A step already done is never done again: a stored `video_id` skips step 1. A failed job is tried
again with a new job for the same upload row (`youtube_publish.retry`).

The thumbnail and the captions are YT-005's. Logs hold the job id, the step, the video id, the
HTTP status and the class of an error; never a token, the title, the description or the file.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

import anyio.to_thread

from app.db.models import YouTubeChannel, YouTubeUpload
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.jobs import live_status, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.services import youtube_api, youtube_auth, youtube_publish
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = youtube_publish.JOB_TYPE
# Between two asks of YouTube, and the longest the job waits for the video to be processed.
CHECK_INTERVAL_S: Final = 30.0
MAX_WAIT_S: Final = 30 * 60.0

_GONE_MESSAGE = "The video is no longer on YouTube."
_NO_FILE_MESSAGE = "The render's video file is missing, so it cannot be sent."
_NOT_SET_UP_MESSAGE = "YouTube is not set up. Fix the values listed in Settings, then try again."


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class PublishYouTubeHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            upload_id = job_input.get("upload_id")
            upload = (
                await session.get(YouTubeUpload, upload_id) if isinstance(upload_id, int) else None
            )
            channel = (
                await session.get(YouTubeChannel, upload.channel_row_id)
                if upload is not None and upload.channel_row_id is not None
                else None
            )
            await session.commit()
        if upload is None:
            await self._fail(job_id, None, "The upload this job was queued for is gone.")
            return
        if channel is None:
            await self._fail(
                job_id, upload.id, "The channel was disconnected. Connect it and upload again."
            )
            return
        if channel.status != youtube_auth.STATUS_CONNECTED:
            await self._fail(job_id, upload.id, _reconnect_message(channel.title))
            return

        sent: dict[str, Any] = upload.sent
        video_id = upload.video_id
        if video_id is None:
            video_id = await self._send_video(job_id, upload.id, channel, sent, job_input)
            if video_id is None:
                return
        await self._check_processing(job_id, upload.id, channel, video_id, sent, job_input)

    # --- Step 1: the video ---------------------------------------------------------------

    async def _send_video(
        self,
        job_id: int,
        upload_id: int,
        channel: YouTubeChannel,
        sent: dict[str, Any],
        job_input: dict[str, Any],
    ) -> str | None:
        """Sends the video and stores its id. Returns the id, or None when the job has ended."""
        render = sent["render"]
        try:
            path = get_storage().get_path(render["path"])
            usable = path.is_file() and path.stat().st_size == render["size_bytes"]
        except (StorageError, OSError):
            usable = False
        if not usable:
            await self._fail(job_id, upload_id, _NO_FILE_MESSAGE)
            return None

        try:
            credentials = youtube_auth.credentials_for(channel)
        except youtube_auth.TokenUnusableError:
            await self._needs_reconnect(job_id, upload_id, channel)
            return None
        except youtube_auth.YouTubeNotConfiguredError:
            await self._fail(job_id, upload_id, _NOT_SET_UP_MESSAGE)
            return None

        await phase_writer.note(job_id, phases.UPLOADING_TO_YOUTUBE)
        live_status.reset_upload(job_id)
        try:
            service = await anyio.to_thread.run_sync(youtube_api.build_service, credentials)
            upload = await anyio.to_thread.run_sync(
                youtube_api.ResumableUpload, service, sent, path
            )
            live_status.upload_started(job_id, f"render {render['number']}.mp4", upload.total_bytes)
            video_id: str | None = None
            while video_id is None:
                sent_bytes, video_id = await anyio.to_thread.run_sync(upload.send_next)
                live_status.upload_sent(job_id, sent_bytes)
        except Exception as exc:
            await self._handle_failure(job_id, upload_id, channel, exc, sending=True)
            return None
        live_status.upload_done(job_id)
        _logger.info("job %d: the video was sent, video id %s", job_id, video_id)

        # The id is stored at once, before anything else can fail.
        async with SessionLocal() as session:
            row = await session.get(YouTubeUpload, upload_id)
            row_channel = await session.get(YouTubeChannel, channel.id)
            if row is not None:
                row.video_id = video_id
                row.processing = youtube_publish.PROCESSING_WAITING
                row.error = None
            if row_channel is not None:
                row_channel.last_used_at = utcnow()
            await session.commit()
        job_input["waiting_since"] = time.time()
        job_input.pop("next_check_at", None)
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)
        return video_id

    # --- Step 2: processing --------------------------------------------------------------

    async def _check_processing(
        self,
        job_id: int,
        upload_id: int,
        channel: YouTubeChannel,
        video_id: str,
        sent: dict[str, Any],
        job_input: dict[str, Any],
    ) -> None:
        now = time.time()
        waiting_since = _number(job_input.get("waiting_since"))
        if waiting_since is None:
            # A retry starts a new wait; so does a job whose input was lost.
            waiting_since = now
            job_input["waiting_since"] = now
        next_check_at = _number(job_input.get("next_check_at"))
        if next_check_at is not None and next_check_at > now:
            async with SessionLocal() as session:
                await store.requeue(session, job_id, phases.WAITING_FOR_YOUTUBE)
            return

        try:
            credentials = youtube_auth.credentials_for(channel)
        except youtube_auth.TokenUnusableError:
            await self._needs_reconnect(job_id, upload_id, channel)
            return
        except youtube_auth.YouTubeNotConfiguredError:
            await self._fail(job_id, upload_id, _NOT_SET_UP_MESSAGE)
            return

        await phase_writer.note(job_id, phases.CHECKING_YOUTUBE)
        status: youtube_api.VideoStatus | None = None
        reachable = True
        try:
            service = await anyio.to_thread.run_sync(youtube_api.build_service, credentials)
            status = await anyio.to_thread.run_sync(youtube_api.read_status, service, video_id)
        except Exception as exc:
            failure = youtube_api.classify(exc)
            if failure is None:
                raise
            if failure.kind not in ("unreachable", "server_error"):
                await self._handle_failure(job_id, upload_id, channel, exc, sending=False)
                return
            # Not an answer about the video: ask again at the next check.
            _logger.warning(
                "job %d: the processing check got %s (HTTP %s)",
                job_id,
                failure.kind,
                failure.status,
            )
            reachable = False

        if reachable:
            if status is None or status.upload_status == youtube_api.UPLOAD_DELETED:
                await self._end_failed(job_id, upload_id, _GONE_MESSAGE)
                return
            if status.privacy_status in youtube_publish.PRIVACY_VALUES:
                await self._store_privacy(upload_id, status.privacy_status)
            if status.upload_status == youtube_api.UPLOAD_PROCESSED:
                await self._end_processed(job_id, upload_id, video_id)
                return
            if status.upload_status in (youtube_api.UPLOAD_FAILED, youtube_api.UPLOAD_REJECTED):
                detail = f" ({status.problem})" if status.problem else ""
                await self._end_failed(
                    job_id, upload_id, f"YouTube {status.upload_status} the video{detail}."
                )
                return

        if now - waiting_since >= MAX_WAIT_S:
            _logger.info("job %d: gave up waiting for video %s to be processed", job_id, video_id)
            await self._end_succeeded(
                job_id, upload_id, video_id, youtube_publish.PROCESSING_GAVE_UP
            )
            return
        job_input["next_check_at"] = now + CHECK_INTERVAL_S
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)
        async with SessionLocal() as session:
            await store.requeue(session, job_id, phases.WAITING_FOR_YOUTUBE)

    # --- Ending --------------------------------------------------------------------------

    @staticmethod
    async def _store_privacy(upload_id: int, privacy: str) -> None:
        async with SessionLocal() as session:
            row = await session.get(YouTubeUpload, upload_id)
            if row is not None:
                row.privacy_applied = privacy
            await session.commit()

    @staticmethod
    async def _end_succeeded(job_id: int, upload_id: int, video_id: str, processing: str) -> None:
        async with SessionLocal() as session:
            row = await session.get(YouTubeUpload, upload_id)
            if row is not None:
                row.processing = processing
                row.error = None
                row.finished_at = utcnow()
            output = {"video_id": video_id, "processing": processing}
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            await session.commit()

    async def _end_processed(self, job_id: int, upload_id: int, video_id: str) -> None:
        await self._end_succeeded(job_id, upload_id, video_id, youtube_publish.PROCESSING_PROCESSED)

    @staticmethod
    async def _end_failed(job_id: int, upload_id: int, message: str) -> None:
        """YouTube itself failed or lost the video: the upload is over, and cannot be retried."""
        async with SessionLocal() as session:
            row = await session.get(YouTubeUpload, upload_id)
            if row is not None:
                row.processing = youtube_publish.PROCESSING_FAILED
                row.error = message
                row.finished_at = utcnow()
            await store.fail_job(session, job_id, message)

    @staticmethod
    async def _fail(job_id: int, upload_id: int | None, message: str) -> None:
        """The job failed. The upload stays as it is, so Try again can go on from here."""
        async with SessionLocal() as session:
            row = await session.get(YouTubeUpload, upload_id) if upload_id is not None else None
            if row is not None:
                row.error = message
            await store.fail_job(session, job_id, message)

    async def _needs_reconnect(self, job_id: int, upload_id: int, channel: YouTubeChannel) -> None:
        async with SessionLocal() as session:
            await youtube_auth.mark_needs_reconnect(session, channel.id)
        await self._fail(job_id, upload_id, _reconnect_message(channel.title))

    async def _handle_failure(
        self,
        job_id: int,
        upload_id: int,
        channel: YouTubeChannel,
        exc: Exception,
        *,
        sending: bool,
    ) -> None:
        """Ends the job for a failed Google call, or raises `exc` when it is not one this
        module knows. The log has the step, the kind and the HTTP status, never Google's text.
        """
        failure = youtube_api.classify(exc)
        if failure is None:
            raise exc
        _logger.warning(
            "job %d: %s failed: %s (HTTP %s, %s)",
            job_id,
            "sending the video" if sending else "checking the video",
            failure.kind,
            failure.status,
            type(exc).__name__,
        )
        if failure.kind == "needs_reconnect":
            await self._needs_reconnect(job_id, upload_id, channel)
            return
        await self._fail(
            job_id,
            upload_id,
            youtube_api.failure_message(failure, channel.title, sending=sending),
        )


def _reconnect_message(title: str) -> str:
    return f"Reconnect {title} in Settings, then press Try again."
