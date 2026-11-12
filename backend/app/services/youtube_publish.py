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
upload), and the job adds `next_check_at` and `waiting_since` while it waits for YouTube.

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

UploadStateName = Literal["uploading", "processing", "processed", "gave_up", "failed"]

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


def upload_state(row: YouTubeUpload, job: Job | None) -> UploadView:
    """`uploading` and `processing` are while the job is queued or running (before and after the
    video id is stored). Otherwise the job's result decides. A failed upload can be tried again
    unless YouTube itself failed or rejected the video, and only while its channel is connected.
    """
    if job is not None and job.status in store.ACTIVE_STATUSES:
        return UploadView("uploading" if row.video_id is None else "processing", False)
    if row.processing == PROCESSING_PROCESSED:
        return UploadView("processed", False)
    if row.processing == PROCESSING_GAVE_UP:
        return UploadView("gave_up", False)
    can_retry = row.processing != PROCESSING_FAILED and row.channel_row_id is not None
    return UploadView("failed", can_retry)


def _target(render_id: int, channel_row_id: int) -> str:
    return f"{render_id}:{channel_row_id}"


def _job_input(upload_id: int, render_id: int, channel_row_id: int) -> dict[str, Any]:
    return {"upload_id": upload_id, "target": _target(render_id, channel_row_id)}


async def _entry(session: AsyncSession, row: YouTubeUpload) -> youtube_draft.UploadEntry:
    render = await session.get(StoryRender, row.render_id)
    job = await session.get(Job, row.job_id) if row.job_id is not None else None
    return youtube_draft.UploadEntry(
        row=row, render_number=render.render_number if render is not None else 0, job=job
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
    session: AsyncSession, project: Project, upload_id: int
) -> youtube_draft.UploadEntry:
    """Queues a new job for an upload that failed or was cancelled, and commits. What is done is
    never done again: with a video id stored, the job goes on with processing. An upload that is
    still waiting or running is returned as it is. Raises `NoSuchUploadError` or
    `YouTubePublishError`.
    """
    row = await session.get(YouTubeUpload, upload_id)
    if row is None or row.project_id != project.id:
        raise NoSuchUploadError("There is no such upload.")
    job = await session.get(Job, row.job_id) if row.job_id is not None else None
    view = upload_state(row, job)
    if job is not None and job.status in store.ACTIVE_STATUSES:
        return await _entry(session, row)
    if row.channel_row_id is None:
        raise YouTubePublishError(
            "The channel was disconnected. Connect it again and press Upload again."
        )
    if not view.can_retry:
        raise YouTubePublishError("This upload cannot be tried again.")
    await _connected_channel(session, row.channel_row_id)

    new_job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input=_job_input(row.id, row.render_id, row.channel_row_id),
        commit=False,
        dedupe_key="target",
    )
    if created:
        row.job_id = new_job.id
        row.error = None
    await session.commit()
    return await _entry(session, row)
