"""The `publish_youtube` job: send a render to YouTube and wait until YouTube has processed it
(YT-004, `YouTube_publish_phases.md` §4.6, steps 1 and 2).

A local job, one at a time. Its input is `{upload_id, target}` (`services/youtube_publish`), and
everything it sends is read from the `youtube_upload` row's `sent` snapshot, never from the draft.

1. **The video.** Only when the upload has no `video_id`: a resumable `videos.insert`, sent in
   chunks in a worker thread, with the bytes sent kept for the panel in `live_status`. The video
   id is stored the moment the insert returns, in its own transaction. A restart during this step
   starts it again from the beginning (`start_again`): YouTube makes the video only when an upload
   is complete.
2. **Processing.** `videos.list` says whether YouTube has processed the video: `uploadStatus` is
   `processed` **and** `processingDetails.processingStatus` is `succeeded` (a Short's thumbnail
   is only applied after that, YTF-001; an answer with no `processingDetails` goes by
   `uploadStatus` alone). `processingStatus` `failed` or `terminated` fails the upload. The job
   does not hold its place while it waits: between two checks it is queued again
   (`store.requeue`), with `next_check_at` and `waiting_since` kept in its input (clock times,
   so they survive a restart). A start before `next_check_at` queues it again at once without
   asking Google. When the video is processed it goes on to steps 3 and 4; when YouTube fails
   or rejects it, the job fails; after `MAX_WAIT_S` it records `gave_up` and succeeds, keeping
   the video.
3. **The thumbnail** (`thumbnails.set`) and 4. **the captions** (`captions.insert`, the render's
   SRT sent from memory, or `skipped` when not ticked), only after processing. Each result is
   stored in `thumbnail_result` or `captions_result` the moment it ends. An error in either is
   recorded on its step and never fails the upload. The thumbnail sent is the one recorded at
   Upload when its file is unchanged, otherwise the project's chosen one. A job whose upload is
   already `processed` goes straight to these steps; `steps` in its input (Try again on one step)
   limits it to those steps. With `later: true` as well (YTF-001, Send captions now / Set the
   thumbnail again) the step is done whatever its last result was, the thumbnail sent is the
   project's chosen one now, the captions are sent whether or not they were ticked, and the
   result stored carries `later: true`. The upload's `sent` snapshot is never changed.
   A 409 `captionExists` is stored as `done` with a message.

A step already done is never done again: a stored `video_id` skips step 1, `processed` skips
step 2, and a step whose result is `done` or `skipped` is skipped. A failed job is tried again
with a new job for the same upload row (`youtube_publish.retry`).

Logs hold the job id, the step, the video id, the
HTTP status and the class of an error; never a token, the title, the description or the file.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

import anyio.to_thread
from sqlalchemy import select

from app.db.models import StoryRender, Thumbnail, YouTubeChannel, YouTubeUpload
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.jobs import live_status, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.services import caption_plan, story_renders, youtube_api, youtube_auth, youtube_publish
from app.services.caption_srt import srt_document
from app.services.storage import StorageError, get_storage
from app.services.youtube_publish import RESULT_DONE, RESULT_FAILED, RESULT_SKIPPED

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
        if upload.processing == youtube_publish.PROCESSING_PROCESSED and upload.video_id:
            # The video is on YouTube and processed: only the thumbnail and the captions are left
            # (a retry of one step, a finish of both, or a restart during them). A channel that
            # cannot be used is recorded on the steps, not as a failure of the job.
            await self._run_steps(
                job_id, upload.id, channel, upload.video_id, upload.sent, job_input
            )
            await self._end_succeeded(
                job_id, upload.id, upload.video_id, youtube_publish.PROCESSING_PROCESSED
            )
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
            if status.upload_status in (youtube_api.UPLOAD_FAILED, youtube_api.UPLOAD_REJECTED):
                detail = f" ({status.problem})" if status.problem else ""
                await self._end_failed(
                    job_id, upload_id, f"YouTube {status.upload_status} the video{detail}."
                )
                return
            if status.upload_status == youtube_api.UPLOAD_PROCESSED:
                # `processed` is not enough: a Short's thumbnail is only applied once
                # `processingStatus` is `succeeded` (F-6).
                if status.processing_status in youtube_api.PROCESSING_FAILED_STATUSES:
                    reason = f" ({status.processing_problem})" if status.processing_problem else ""
                    await self._end_failed(
                        job_id, upload_id, f"YouTube could not process the video{reason}."
                    )
                    return
                if status.processing_status is None:
                    _logger.info(
                        "job %d: no processingDetails for video %s, going by uploadStatus",
                        job_id,
                        video_id,
                    )
                if (
                    status.processing_status is None
                    or status.processing_status == youtube_api.PROCESSING_SUCCEEDED
                ):
                    await self._store_processing(upload_id, youtube_publish.PROCESSING_PROCESSED)
                    await self._run_steps(job_id, upload_id, channel, video_id, sent, job_input)
                    await self._end_succeeded(
                        job_id, upload_id, video_id, youtube_publish.PROCESSING_PROCESSED
                    )
                    return
                # Still `processing`: keep waiting under the same rules as for `uploaded`.

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

    # --- Steps 3 and 4: the thumbnail and the captions -----------------------------------

    async def _run_steps(
        self,
        job_id: int,
        upload_id: int,
        channel: YouTubeChannel | None,
        video_id: str,
        sent: dict[str, Any],
        job_input: dict[str, Any],
    ) -> None:
        """Does the thumbnail and the captions that are still to do, in that order. A step's
        result is stored the moment it ends. No error here fails the upload: it is recorded on
        its step, so one failed step never stops the other.

        With `steps` in the job's input (Try again on one step) only those steps are done, when
        they have no result or a failed one. Without it (the upload itself, or Finish) every
        step with no result is done. A step that is `done` or `skipped` is never done again.
        """
        async with SessionLocal() as session:
            row = await session.get(YouTubeUpload, upload_id)
            if row is None:
                return
            project_id = row.project_id
            results = {
                youtube_publish.STEP_THUMBNAIL: row.thumbnail_result,
                youtube_publish.STEP_CAPTIONS: row.captions_result,
            }
            await session.commit()
        wanted = job_input.get("steps")
        # Sending later (F-7): the step is done again whatever its last result was.
        later = job_input.get("later") is True
        todo: list[str] = []
        for step, result in results.items():
            if isinstance(wanted, list):
                if step in wanted and (
                    later
                    or youtube_publish.result_status(result)
                    not in (youtube_publish.RESULT_DONE, youtube_publish.RESULT_SKIPPED)
                ):
                    todo.append(step)
            elif result is None:
                todo.append(step)
        if not todo:
            return

        service: Any = None
        blocked = await self._channel_problem(channel)
        if blocked is None and channel is not None:
            try:
                credentials = youtube_auth.credentials_for(channel)
                service = await anyio.to_thread.run_sync(youtube_api.build_service, credentials)
            except youtube_auth.TokenUnusableError:
                async with SessionLocal() as session:
                    await youtube_auth.mark_needs_reconnect(session, channel.id)
                blocked = _step_reconnect_message(channel.title)
            except youtube_auth.YouTubeNotConfiguredError:
                blocked = _NOT_SET_UP_MESSAGE

        for step in todo:
            if blocked is not None:
                await self._store_result(
                    upload_id, step, _result(RESULT_FAILED, blocked, **_later_mark(later))
                )
                continue
            assert channel is not None
            try:
                if step == youtube_publish.STEP_THUMBNAIL:
                    await phase_writer.note(job_id, phases.SETTING_YOUTUBE_THUMBNAIL)
                    result = await self._thumbnail_step(
                        service, video_id, project_id, sent, later=later
                    )
                else:
                    await phase_writer.note(job_id, phases.SENDING_YOUTUBE_CAPTIONS)
                    result = await self._captions_step(service, video_id, sent, later=later)
            except Exception as exc:
                failure = youtube_api.classify(exc)
                _logger.warning(
                    "job %d: the %s step failed: %s (HTTP %s, %s)",
                    job_id,
                    step,
                    failure.kind if failure is not None else "unexpected",
                    failure.status if failure is not None else None,
                    type(exc).__name__,
                )
                if failure is None:
                    message = f"The {step} could not be sent to YouTube. Press Try again on it."
                elif failure.kind == "needs_reconnect":
                    async with SessionLocal() as session:
                        await youtube_auth.mark_needs_reconnect(session, channel.id)
                    blocked = _step_reconnect_message(channel.title)
                    message = blocked
                else:
                    message = youtube_api.step_failure_message(failure, channel.title, step)
                result = _result(RESULT_FAILED, message)
            if later:
                result["later"] = True
            await self._store_result(upload_id, step, result)
            _logger.info(
                "job %d: the %s step ended: %s (video %s)",
                job_id,
                step,
                result["status"],
                video_id,
            )

    @staticmethod
    async def _channel_problem(channel: YouTubeChannel | None) -> str | None:
        if channel is None:
            return "The channel was disconnected. Connect it and press Try again on this step."
        if channel.status != youtube_auth.STATUS_CONNECTED:
            return _step_reconnect_message(channel.title)
        return None

    @staticmethod
    async def _store_result(upload_id: int, step: str, result: dict[str, Any]) -> None:
        async with SessionLocal() as session:
            row = await session.get(YouTubeUpload, upload_id)
            if row is not None:
                if step == youtube_publish.STEP_THUMBNAIL:
                    row.thumbnail_result = result
                else:
                    row.captions_result = result
            await session.commit()

    @staticmethod
    async def _thumbnail_file(
        project_id: int, sent: dict[str, Any], *, later: bool = False
    ) -> tuple[str, int, str, bool] | None:
        """The thumbnail to send: the one recorded at Upload when its file is still there with
        the recorded hash, otherwise the project's chosen thumbnail; when sending later, always
        the project's chosen thumbnail now. Returns its stored path, id, SHA-256 and whether it
        is the recorded one; None when there is no usable thumbnail.
        """
        recorded = None if later else sent.get("thumbnail")
        storage = get_storage()
        if isinstance(recorded, dict):
            path, sha256 = recorded.get("path"), recorded.get("sha256")
            if isinstance(path, str) and isinstance(sha256, str):
                try:
                    _, actual = await storage.hash_stored(path)
                except (StorageError, FileNotFoundError, OSError):
                    actual = None
                if actual == sha256 and isinstance(recorded.get("id"), int):
                    return path, recorded["id"], sha256, True
        async with SessionLocal() as session:
            chosen = (
                await session.execute(
                    select(Thumbnail).where(
                        Thumbnail.project_id == project_id,
                        Thumbnail.chosen.is_(True),
                        Thumbnail.path.is_not(None),
                    )
                )
            ).scalar_one_or_none()
            if chosen is None or chosen.path is None:
                return None
            chosen_id, chosen_path = chosen.id, chosen.path
        try:
            _, actual = await storage.hash_stored(chosen_path)
        except (StorageError, FileNotFoundError, OSError):
            return None
        return chosen_path, chosen_id, actual, False

    async def _thumbnail_step(
        self,
        service: Any,
        video_id: str,
        project_id: int,
        sent: dict[str, Any],
        *,
        later: bool = False,
    ) -> dict[str, Any]:
        found = await self._thumbnail_file(project_id, sent, later=later)
        if found is None:
            return _result(
                RESULT_FAILED,
                "There is no chosen thumbnail with a picture, so none was set. Choose one in "
                "the Thumbnails panel, then press Try again on the thumbnail.",
            )
        path, thumbnail_id, sha256, from_snapshot = found
        extra = {"thumbnail_id": thumbnail_id, "sha256": sha256, "from_snapshot": from_snapshot}
        await anyio.to_thread.run_sync(
            youtube_api.set_thumbnail, service, video_id, get_storage().get_path(path)
        )
        return _result(RESULT_DONE, None, **extra)

    async def _captions_step(
        self, service: Any, video_id: str, sent: dict[str, Any], *, later: bool = False
    ) -> dict[str, Any]:
        # Sending later ignores what was ticked at Upload: the owner asked for it now.
        if not sent.get("captions") and not later:
            return _result(RESULT_SKIPPED, "Captions were not ticked for this upload.")
        render_id = sent["render"]["id"]
        async with SessionLocal() as session:
            render = await session.get(StoryRender, render_id)
            recorded = story_renders.recorded_captions(render) if render is not None else None
            await session.commit()
        if render is None:
            return _result(RESULT_FAILED, "The render is gone, so its captions cannot be sent.")
        try:
            track = caption_plan.parse_track(recorded)
        except caption_plan.CaptionError:
            return _result(RESULT_FAILED, "The render's caption track cannot be read.")
        if track is None:
            return _result(RESULT_FAILED, "This render has no caption track.")
        srt = srt_document(track).encode("utf-8")
        try:
            await anyio.to_thread.run_sync(youtube_api.insert_captions, service, video_id, srt)
        except Exception as exc:
            failure = youtube_api.classify(exc)
            if (
                failure is not None
                and failure.status == 409
                and failure.reason == youtube_api.CAPTION_EXISTS_REASON
            ):
                # The track is already there (sent before a restart, or added by hand): it is
                # not sent twice.
                return _result(RESULT_DONE, youtube_api.CAPTION_EXISTS_MESSAGE)
            raise
        return _result(RESULT_DONE, None)

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

    @staticmethod
    async def _store_processing(upload_id: int, processing: str) -> None:
        async with SessionLocal() as session:
            row = await session.get(YouTubeUpload, upload_id)
            if row is not None:
                row.processing = processing
                row.error = None
            await session.commit()

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


def _later_mark(later: bool) -> dict[str, Any]:
    """The `later` key of a result written by a send-later job (F-7)."""
    return {"later": True} if later else {}


def _step_reconnect_message(title: str) -> str:
    return f"Reconnect {title} in Settings, then press Try again on this step."


def _result(status: str, message: str | None, **extra: Any) -> dict[str, Any]:
    """What a step stores in `thumbnail_result` or `captions_result`."""
    return {"status": status, "message": message, "at": utcnow().isoformat(), **extra}
