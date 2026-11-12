"""Pressing Upload: the checks, the snapshot and the job (YT-004, `YouTube_publish_phases.md`
§4.6).

`start_upload` checks everything again on the server (the panel's checks are only a help), stores
a `youtube_upload` row whose `sent` is a snapshot of exactly what will be sent, and queues the
`publish_youtube` job, all in one transaction. A later edit of the draft never changes `sent`.

`sent`:

    {"channel": {"row_id", "channel_id", "title"}, "title", "description" (with the hashtags),
     "hashtags", "privacy", "made_for_kids", "synthetic_media", "default_language",
     "default_audio_language", "notify_subscribers", "captions",
     "thumbnail": {"id", "path", "sha256"},
     "render": {"id", "number", "path", "size_bytes", "sha256"}}

The input of the job is `{"upload_id", "target"}` (`target` is `<render id>:<channel row id>`, so
a second press for the same render and channel while one is waiting or running is the same
upload), and the job adds `next_check_at` and `waiting_since` while it waits for YouTube. A Try
again on one step (YT-005) adds `"steps": ["thumbnail"]` or `["captions"]`. Sending a step later
(`send_later`, YTF-001) adds `"later": true` next to `steps`: the step is done whatever its last
result was, and the result stored carries `"later": true`. `sent` is never changed by it.

After processing the job stores `thumbnail_result` and `captions_result`, each
`{"status": "done" | "skipped" | "failed", "message", "at"}`; the thumbnail's also has
`thumbnail_id`, `sha256` and `from_snapshot` (whether it is the one recorded in `sent`).

Nothing here calls Google; the job does (`jobs/publish_youtube`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, StoryRender, YouTubeChannel, YouTubeUpload
from app.jobs import store
from app.services import caption_plan, story_renders, youtube_auth, youtube_draft
from app.services import youtube_draft_writer as writer
from app.services.storage import StorageError, get_storage

JOB_TYPE: Final = "publish_youtube"
PRIVACY_VALUES: Final = ("private", "unlisted", "public")
LANGUAGE: Final = "en"

# `processing` values the job writes (the `youtube_upload.processing` CHECK).
PROCESSING_WAITING: Final = "waiting"
PROCESSING_PROCESSED: Final = "processed"
PROCESSING_FAILED: Final = "failed"
PROCESSING_GAVE_UP: Final = "gave_up"

# The steps after processing (YT-005) and the `status` of a step's result.
STEP_THUMBNAIL: Final = "thumbnail"
STEP_CAPTIONS: Final = "captions"
STEPS: Final = (STEP_THUMBNAIL, STEP_CAPTIONS)
RESULT_DONE: Final = "done"
RESULT_SKIPPED: Final = "skipped"
RESULT_FAILED: Final = "failed"

UploadStateName = Literal["uploading", "processing", "finishing", "processed", "gave_up", "failed"]

_STALE_DRAFT_MESSAGE: Final = (
    "The draft changed since the page loaded. Check it and press Upload again."
)
_NO_DRAFT_MESSAGE: Final = "There is no draft yet. Write the draft first."


class YouTubePublishError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


class NoSuchUploadError(YouTubePublishError):
    """No upload of this project has this id."""


@dataclass(frozen=True)
class UploadView:
    """Where an upload stands, worked out from its row and its job."""

    state: UploadStateName
    can_retry: bool
    # Finish the thumbnail and captions: the upload gave up waiting for YouTube, or is processed
    # and a step has no result yet.
    can_finish: bool = False
    # The steps whose last result is `failed`, each of which can be tried again on its own.
    retry_steps: tuple[str, ...] = ()
    # The steps that can be sent now on a processed upload (Send captions now, Set the thumbnail
    # again; YTF-001).
    send_steps: tuple[str, ...] = ()
    # The steps the job that is waiting or running will send: the ones in its `steps`, or both.
    sending_steps: tuple[str, ...] = ()


def result_status(result: object) -> str | None:
    """The `status` of a step's stored result, or None when there is no result."""
    status = result.get("status") if isinstance(result, dict) else None
    return status if isinstance(status, str) else None


def _sending_steps(row: YouTubeUpload, job: Job) -> tuple[str, ...]:
    """The steps an active job will (still) send, as the job decides it: with `later` every
    step in its `steps`; with `steps` only the ones not `done` or `skipped`; without `steps`
    only the ones with no result yet.
    """
    job_input = job.input if isinstance(job.input, dict) else {}
    steps = job_input.get("steps")
    results = {STEP_THUMBNAIL: row.thumbnail_result, STEP_CAPTIONS: row.captions_result}
    wanted = [step for step in STEPS if not isinstance(steps, list) or step in steps]
    if job_input.get("later") is True:
        return tuple(wanted)
    finished = (RESULT_DONE, RESULT_SKIPPED)
    if isinstance(steps, list):
        return tuple(step for step in wanted if result_status(results[step]) not in finished)
    return tuple(step for step in wanted if results[step] is None)


def upload_state(
    row: YouTubeUpload,
    job: Job | None,
    channel_connected: bool,
    *,
    render_has_captions: bool = False,
    thumbnail_chosen: bool = False,
) -> UploadView:
    """`uploading` is while the job is queued or running before the video id is stored,
    `processing` after it, and `finishing` once YouTube has processed the video (the thumbnail
    and the captions are being sent). Otherwise the job's result decides. A failed upload can be
    tried again unless YouTube itself failed or rejected the video. Finish, the Try again of
    one step and sending a step later (YTF-001) are only offered while the upload's channel is
    connected. Sending later is offered on a processed upload: the captions when their result
    is `skipped` or `failed` and the render has a caption track, the thumbnail whatever its
    result is when the project has a chosen thumbnail with a picture.
    """
    if job is not None and job.status in store.ACTIVE_STATUSES:
        sending = _sending_steps(row, job)
        if row.video_id is None:
            return UploadView("uploading", False, sending_steps=sending)
        if row.processing == PROCESSING_PROCESSED:
            return UploadView("finishing", False, sending_steps=sending)
        return UploadView("processing", False, sending_steps=sending)
    usable = channel_connected and row.channel_row_id is not None and row.video_id is not None
    if row.processing == PROCESSING_PROCESSED:
        results = (row.thumbnail_result, row.captions_result)
        failed = tuple(
            step
            for step, result in zip(STEPS, results, strict=True)
            if result_status(result) == RESULT_FAILED
        )
        unfinished = any(result is None for result in results)
        send: list[str] = []
        if usable and thumbnail_chosen:
            send.append(STEP_THUMBNAIL)
        if (
            usable
            and render_has_captions
            and result_status(row.captions_result) in (RESULT_SKIPPED, RESULT_FAILED)
        ):
            send.append(STEP_CAPTIONS)
        return UploadView(
            "processed",
            False,
            can_finish=usable and unfinished,
            retry_steps=failed if usable else (),
            send_steps=tuple(send),
        )
    if row.processing == PROCESSING_GAVE_UP:
        return UploadView("gave_up", False, can_finish=usable)
    can_retry = row.processing != PROCESSING_FAILED and row.channel_row_id is not None
    return UploadView("failed", can_retry)


def _target(render_id: int, channel_row_id: int) -> str:
    return f"{render_id}:{channel_row_id}"


def _job_input(upload_id: int, render_id: int, channel_row_id: int) -> dict[str, Any]:
    return {"upload_id": upload_id, "target": _target(render_id, channel_row_id)}


async def _entry(session: AsyncSession, row: YouTubeUpload) -> youtube_draft.UploadEntry:
    render = await session.get(StoryRender, row.render_id)
    job = await session.get(Job, row.job_id) if row.job_id is not None else None
    channel = (
        await session.get(YouTubeChannel, row.channel_row_id)
        if row.channel_row_id is not None
        else None
    )
    return youtube_draft.UploadEntry(
        row=row,
        render_number=render.render_number if render is not None else 0,
        job=job,
        channel_connected=channel is not None and channel.status == youtube_auth.STATUS_CONNECTED,
        render_has_captions=youtube_draft.captions_of(render)[0] if render is not None else False,
        thumbnail_chosen=await youtube_draft.has_chosen_thumbnail(session, row.project_id),
    )


async def _connected_channel(session: AsyncSession, channel_row_id: int) -> YouTubeChannel:
    channel = await session.get(YouTubeChannel, channel_row_id)
    if channel is None:
        raise YouTubePublishError(
            "That channel is not connected. Connect it in Settings, then choose it."
        )
    if channel.status != youtube_auth.STATUS_CONNECTED:
        raise YouTubePublishError(f"Reconnect {channel.title} in Settings first.")
    return channel


async def _hash(relative_path: str, what: str) -> tuple[int, str]:
    try:
        return await get_storage().hash_stored(relative_path)
    except (StorageError, FileNotFoundError, OSError) as exc:
        raise YouTubePublishError(f"The {what} file cannot be read, so it cannot be sent.") from exc


async def start_upload(
    session: AsyncSession,
    project: Project,
    *,
    render_number: int,
    channel_row_id: int,
    draft_version: int,
    privacy: str,
    made_for_kids: bool | None,
    synthetic_media: bool | None,
    notify_subscribers: bool,
    captions: bool,
) -> youtube_draft.UploadEntry:
    """Checks, stores the snapshot, queues the job and commits. Returns the upload, which is the
    one already waiting or running when there is one for this render and channel. Raises
    `youtube_draft.NoSuchRenderError` (no such render) or `YouTubePublishError` (a check failed).
    """
    if not youtube_auth.config_status().ready:
        raise YouTubePublishError(
            "YouTube is not set up. Fix the values listed in Settings, then try again."
        )
    channel = await _connected_channel(session, channel_row_id)
    if made_for_kids is None:
        raise YouTubePublishError('Answer "Made for kids" before uploading.')
    if synthetic_media is None:
        raise YouTubePublishError('Answer "Contains realistic AI content" before uploading.')
    if privacy not in PRIVACY_VALUES:
        raise YouTubePublishError("Choose private, unlisted or public.")

    draft = await youtube_draft.latest(session, project.id)
    if draft is None:
        raise YouTubePublishError(_NO_DRAFT_MESSAGE)
    if draft.version != draft_version:
        raise YouTubePublishError(_STALE_DRAFT_MESSAGE)
    content = draft.content
    try:
        title, description, hashtags = writer.check_fields(
            content["title"],
            content["description"],
            list(content["hashtags"]),
            min_hashtags=0,
            allow_empty_description=True,
        )
    except ValueError as exc:
        raise YouTubePublishError(f"The draft cannot be uploaded: {exc}") from exc

    render = await story_renders.find_render(session, project.id, render_number)
    if render is None:
        raise youtube_draft.NoSuchRenderError(youtube_draft.NO_SUCH_RENDER_MESSAGE)
    size_bytes, sha256 = await _hash(render.path, "video")
    if size_bytes != render.size_bytes or sha256 != render.sha256:
        raise YouTubePublishError(
            "The render's video file is not the one that was recorded, so it will not be sent."
        )

    situation = await youtube_draft.thumbnail_situation(session, project, render)
    if situation.status == "making":
        raise YouTubePublishError("The thumbnail is still being made.")
    thumbnail = situation.chosen
    if thumbnail is None or thumbnail.path is None:
        raise YouTubePublishError("There is no chosen thumbnail yet.")
    _, thumbnail_sha256 = await _hash(thumbnail.path, "thumbnail")

    if captions:
        try:
            track = caption_plan.parse_track(story_renders.recorded_captions(render))
        except caption_plan.CaptionError as exc:
            raise YouTubePublishError("The render's caption track cannot be read.") from exc
        if track is None:
            raise YouTubePublishError(
                "This render has no caption track, so captions cannot be uploaded."
            )

    sent: dict[str, Any] = {
        "channel": {
            "row_id": channel.id,
            "channel_id": channel.channel_id,
            "title": channel.title,
        },
        "title": title,
        "description": writer.description_with_hashtags(description, hashtags),
        "hashtags": hashtags,
        "privacy": privacy,
        "made_for_kids": made_for_kids,
        "synthetic_media": synthetic_media,
        "default_language": LANGUAGE,
        "default_audio_language": LANGUAGE,
        "notify_subscribers": notify_subscribers,
        "captions": captions,
        "thumbnail": {"id": thumbnail.id, "path": thumbnail.path, "sha256": thumbnail_sha256},
        "render": {
            "id": render.id,
            "number": render.render_number,
            "path": render.path,
            "size_bytes": render.size_bytes,
            "sha256": render.sha256,
        },
    }
    row = YouTubeUpload(
        project_id=project.id,
        render_id=render.id,
        channel_row_id=channel.id,
        draft_version=draft.version,
        sent=sent,
    )
    session.add(row)
    await session.flush()
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input=_job_input(row.id, render.id, channel.id),
        commit=False,
        dedupe_key="target",
    )
    if not created:
        # The same render is already going to this channel: this press is that upload.
        existing_id = job.input.get("upload_id") if isinstance(job.input, dict) else None
        await session.rollback()
        existing = (
            await session.get(YouTubeUpload, existing_id) if isinstance(existing_id, int) else None
        )
        if existing is None:
            raise YouTubePublishError("This render is already being uploaded to that channel.")
        return await _entry(session, existing)
    row.job_id = job.id
    await session.commit()
    return await _entry(session, row)


async def retry(
    session: AsyncSession, project: Project, upload_id: int, step: str | None = None
) -> youtube_draft.UploadEntry:
    """Queues a new job for an upload and commits. Without `step`: Try again for a failed
    upload, or Finish the thumbnail and captions for one that gave up waiting or has a step with
    no result. With `step` (`thumbnail` or `captions`): only that failed step, and the job input
    gets `steps: [step]`. What is done is never done again: with a video id stored, the job goes
    on with processing, and a step that worked is not sent again. An upload that is still waiting
    or running is returned as it is. Raises `NoSuchUploadError` or `YouTubePublishError`.
    """
    row = await session.get(YouTubeUpload, upload_id)
    if row is None or row.project_id != project.id:
        raise NoSuchUploadError("There is no such upload.")
    job = await session.get(Job, row.job_id) if row.job_id is not None else None
    # The channel is checked after the upload's own state, with its own sentence.
    view = upload_state(row, job, channel_connected=True)
    if job is not None and job.status in store.ACTIVE_STATUSES:
        return await _entry(session, row)
    if row.channel_row_id is None:
        raise YouTubePublishError(
            "The channel was disconnected. Connect it again and press Upload again."
        )
    job_input = _job_input(row.id, row.render_id, row.channel_row_id)
    if step is None:
        if not (view.can_retry or view.can_finish):
            raise YouTubePublishError("This upload cannot be tried again.")
    else:
        if step not in view.retry_steps:
            raise YouTubePublishError("That step cannot be tried again.")
        job_input["steps"] = [step]
        # A step that failed while sending later is tried again the same way.
        failed_result = row.thumbnail_result if step == STEP_THUMBNAIL else row.captions_result
        if isinstance(failed_result, dict) and failed_result.get("later") is True:
            job_input["later"] = True
    await _connected_channel(session, row.channel_row_id)

    new_job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input=job_input,
        commit=False,
        dedupe_key="target",
    )
    if created:
        row.job_id = new_job.id
        row.error = None
    await session.commit()
    return await _entry(session, row)


async def send_later(
    session: AsyncSession, project: Project, upload_id: int, step: str
) -> youtube_draft.UploadEntry:
    """Send captions now / Set the thumbnail again (YTF-001, F-7): queues a job that sends one
    step to a video YouTube has processed, and commits. The job input is
    `{"steps": [step], "later": true}`. The captions are the render's track, whatever was ticked
    at Upload; the thumbnail is the project's chosen one now. `sent` is never changed. An upload
    that is still waiting or running is returned as it is. Raises `NoSuchUploadError` or
    `YouTubePublishError`.
    """
    row = await session.get(YouTubeUpload, upload_id)
    if row is None or row.project_id != project.id:
        raise NoSuchUploadError("There is no such upload.")
    job = await session.get(Job, row.job_id) if row.job_id is not None else None
    if job is not None and job.status in store.ACTIVE_STATUSES:
        return await _entry(session, row)
    if step not in STEPS:
        raise YouTubePublishError("Choose the thumbnail or the captions.")
    if not youtube_auth.config_status().ready:
        raise YouTubePublishError(
            "YouTube is not set up. Fix the values listed in Settings, then try again."
        )
    if row.processing != PROCESSING_PROCESSED or not row.video_id:
        raise YouTubePublishError("YouTube has not finished processing this video yet.")
    if row.channel_row_id is None:
        raise YouTubePublishError(
            "The channel was disconnected. Connect it again, then send it from the upload."
        )
    await _connected_channel(session, row.channel_row_id)

    if step == STEP_CAPTIONS:
        if result_status(row.captions_result) == RESULT_DONE:
            raise YouTubePublishError("The captions were already sent.")
        render = await session.get(StoryRender, row.render_id)
        if render is None or not youtube_draft.captions_of(render)[0]:
            raise YouTubePublishError(
                "This render has no caption track, so captions cannot be uploaded."
            )
    elif not await youtube_draft.has_chosen_thumbnail(session, project.id):
        raise YouTubePublishError("There is no chosen thumbnail with a picture. Choose one first.")

    job_input = _job_input(row.id, row.render_id, row.channel_row_id)
    job_input["steps"] = [step]
    job_input["later"] = True
    new_job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input=job_input,
        commit=False,
        dedupe_key="target",
    )
    if created:
        row.job_id = new_job.id
    await session.commit()
    return await _entry(session, row)
