"""YouTube channels: what `.env` is missing, Google sign-in, and the connected channels
(YouTube_publish_phases.md, YT-002); and the publish draft of a project (YT-003).

No answer here holds a token, a code, the client secret or the encryption key.

The project's draft, all under `/projects/{project_id}/youtube`:

1. `GET` answers everything the Publish panel shows in one call: the renders, the newest draft
   and whether it is out of date, the thumbnail, the connected channels and the earlier uploads.
2. `POST .../draft` starts the `write_youtube_draft` job for a render (and makes sure the render
   has a thumbnail). The body may hold `feedback`, the owner's note on the newest draft.
3. `PUT .../draft` saves the owner's edit of the title, description and hashtags as a new version.
4. `POST .../uploads` (YT-004) checks everything again, stores a snapshot of what will be sent and
   queues the `publish_youtube` job; `POST .../uploads/{upload_id}/retry` tries a failed upload
   again, finishes the thumbnail and captions of one that gave up waiting (YT-005), or, with
   `step` in the body, tries one failed step again; `POST .../uploads/{upload_id}/send` (YTF-001)
   sends the captions or the chosen thumbnail again to a video YouTube has processed. The
   upload itself is done by the job, never by a route.

The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.discovery import DiscoveryJobOut
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Job, Project, YouTubeChannel
from app.db.session import SessionDep
from app.jobs import dispatcher, live_status
from app.services import user_feedback, youtube_auth, youtube_draft, youtube_publish
from app.services import youtube_draft_writer as draft_writer
from app.services.storage import media_url

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NO_PROJECT = {404: {"model": ErrorResponse, "description": "No such project or render."}}
_DRAFT_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The Story Bible or the render is missing, the note or the edit cannot "
        "be used, or a draft is being written.",
    }
}

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No connected channel has this id."}}
_NOT_CONFIGURED = {
    409: {"model": ErrorResponse, "description": "A YOUTUBE_* value is missing or invalid."}
}
_GOOGLE_DOWN = {502: {"model": ErrorResponse, "description": "Google could not be reached."}}

# Where the browser is sent after Google's callback, with a result code in `?youtube=`.
_SETTINGS_PAGE = "/settings"
_NOT_SET_UP = "YouTube is not set up. Fix the values listed in Settings, then try again."


class ConfigProblemOut(BaseModel):
    name: str
    reason: str


class YouTubeConfig(BaseModel):
    """Which `.env` values are missing or invalid. Names and reasons, never a value."""

    ready: bool
    missing: list[str]
    invalid: list[ConfigProblemOut]


class SignInStart(BaseModel):
    """Google's authorization address, for the browser to open."""

    url: str


class YouTubeChannelOut(BaseModel):
    id: int
    channel_id: str
    title: str
    thumbnail_url: str | None
    status: Literal["connected", "needs_reconnect"]
    connected_at: datetime
    last_used_at: datetime | None


class DisconnectOut(BaseModel):
    """`revoked`: whether Google was told to revoke the token. The channel is removed either way."""

    revoked: bool


def _channel_out(row: YouTubeChannel) -> YouTubeChannelOut:
    """The token and the scopes are left out on purpose."""
    return YouTubeChannelOut(
        id=row.id,
        channel_id=row.channel_id,
        title=row.title,
        thumbnail_url=row.thumbnail_url,
        status="connected" if row.status == youtube_auth.STATUS_CONNECTED else "needs_reconnect",
        connected_at=row.connected_at,
        last_used_at=row.last_used_at,
    )


@router.get("/youtube/config", response_model=YouTubeConfig)
async def youtube_config() -> YouTubeConfig:
    current = youtube_auth.config_status()
    return YouTubeConfig(
        ready=current.ready,
        missing=list(current.missing),
        invalid=[ConfigProblemOut(name=p.name, reason=p.reason) for p in current.invalid],
    )


@router.get("/youtube/oauth/start", response_model=SignInStart, responses=_NOT_CONFIGURED)
async def start_sign_in() -> SignInStart:
    try:
        return SignInStart(url=youtube_auth.start_sign_in())
    except youtube_auth.YouTubeNotConfiguredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_SET_UP) from exc


@router.get("/youtube/oauth/callback", include_in_schema=False)
async def sign_in_callback(
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Google sends the browser here. It always answers with a redirect to the Settings page and
    a result code; the page turns the code into a sentence.
    """
    result = await youtube_auth.finish_sign_in(session, code=code, state=state, error=error)
    return RedirectResponse(
        f"{_SETTINGS_PAGE}?youtube={result}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/youtube/channels", response_model=list[YouTubeChannelOut])
async def list_channels(session: SessionDep) -> list[YouTubeChannelOut]:
    return [_channel_out(row) for row in await youtube_auth.list_channels(session)]


@router.post(
    "/youtube/channels/{channel_row_id}/check",
    response_model=YouTubeChannelOut,
    responses={**_NOT_FOUND, **_NOT_CONFIGURED, **_GOOGLE_DOWN},
)
async def check_channel(channel_row_id: int, session: SessionDep) -> YouTubeChannelOut:
    """Uses the channel's token once (1 quota unit). A refused token makes it `needs_reconnect`."""
    try:
        row = await youtube_auth.check_channel(session, channel_row_id)
    except youtube_auth.ChannelNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except youtube_auth.YouTubeNotConfiguredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_SET_UP) from exc
    except youtube_auth.GoogleUnreachableError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"{exc} The channel was not changed. Try again in a moment.",
        ) from exc
    return _channel_out(row)


@router.delete(
    "/youtube/channels/{channel_row_id}",
    response_model=DisconnectOut,
    responses=_NOT_FOUND,
)
async def disconnect_channel(channel_row_id: int, session: SessionDep) -> DisconnectOut:
    try:
        revoked = await youtube_auth.disconnect(session, channel_row_id)
    except youtube_auth.ChannelNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return DisconnectOut(revoked=revoked)


# --- The publish draft of a project (YT-003) -------------------------------------------------

Privacy = Literal["private", "unlisted", "public"]
ThumbnailStatus = Literal["ready", "out_of_date", "making", "none"]


class YouTubeRenderOut(BaseModel):
    """A finished render that can be published."""

    render_number: int
    status: Literal["current", "out_of_date"]
    # Why the render is out of date, one sentence each. Empty when it is current.
    reasons: list[str]
    created_at: datetime
    duration_s: float | None
    width: int | None
    height: int | None
    # Whether YouTube will show it as a Short (vertical or square, at most three minutes).
    is_short: bool
    # Whether the render has a caption track, and whether it is drawn on the picture. Captions
    # are uploaded by default only for a track that is not burned (Y-8).
    has_captions: bool
    captions_burned: bool


class YouTubeSuggestionOut(BaseModel):
    """The model's suggested answer to a declaration. The owner confirms it before uploading."""

    value: bool
    reason: str


class YouTubeDraftOut(BaseModel):
    """One version of the draft."""

    version: int
    source: Literal["ai", "manual"]
    job_id: int | None
    # The render the draft was written for; None when that render is no longer listed.
    render_number: int | None
    title: str
    description: str
    # Words without the `#`.
    hashtags: list[str]
    # The description as YouTube will get it: the text, then the hashtags on one line.
    description_sent: str
    made_for_kids: YouTubeSuggestionOut
    synthetic_media: YouTubeSuggestionOut
    out_of_date: bool
    reasons: list[str]
    # The owner's note this version was made with, or None.
    feedback: str | None
    created_at: datetime


class YouTubeThumbnailOut(BaseModel):
    """The thumbnail that would be uploaded: the project's chosen one."""

    status: ThumbnailStatus
    thumbnail_id: int | None
    url: str | None
    headline: str | None
    width: int | None
    height: int | None
    # Why the chosen thumbnail is out of date for the render being published.
    reasons: list[str]
    # The last failure when no usable thumbnail is being made.
    error: str | None


UploadState = Literal["uploading", "processing", "finishing", "processed", "gave_up", "failed"]
UploadStep = Literal["thumbnail", "captions"]


class YouTubeStepResultOut(BaseModel):
    """How the thumbnail or the captions step ended."""

    status: Literal["done", "skipped", "failed"]
    # The sentence for a failed step (or why it was skipped), or None.
    message: str | None
    at: datetime | None
    # Thumbnail only: which picture was set, and whether it is the one recorded when Upload was
    # pressed (false: that file had changed, so the chosen thumbnail of the project was sent).
    thumbnail_id: int | None = None
    from_snapshot: bool | None = None
    # True when the result comes from Send captions now / Set the thumbnail again (YTF-001).
    later: bool = False


class YouTubeUploadProgressOut(BaseModel):
    """The bytes of the video sent so far. Kept in memory, so it is None after a restart."""

    sent_bytes: int
    total_bytes: int


class YouTubeUploadOut(BaseModel):
    """A press of Upload and how it is going."""

    id: int
    render_number: int
    # None once the channel is disconnected; `channel_title` (from the snapshot) stays.
    channel_row_id: int | None
    channel_title: str | None
    # The title that was sent, from the snapshot.
    title: str | None
    created_at: datetime
    finished_at: datetime | None
    video_id: str | None
    # The visibility that was asked for, and the one YouTube applied when it was read back.
    privacy_sent: Privacy | None
    privacy_applied: Privacy | None
    state: UploadState
    # YouTube's processing: `waiting`, `processed`, `failed` or `gave_up`; None before the video
    # is sent.
    processing: str | None
    error: str | None
    can_retry: bool
    # The thumbnail and the captions steps; None before the step has run.
    thumbnail_result: YouTubeStepResultOut | None
    captions_result: YouTubeStepResultOut | None
    # Whether captions were ticked when Upload was pressed, from the snapshot.
    captions_sent: bool
    # Finish the thumbnail and captions is possible.
    can_finish: bool
    # The steps that failed and can each be tried again on their own.
    retry_steps: list[UploadStep]
    # The steps that can be sent now to the processed video (Send captions now, Set the
    # thumbnail again), and the steps the job that is running will send.
    send_steps: list[UploadStep]
    sending_steps: list[UploadStep]
    job: DiscoveryJobOut | None
    progress: YouTubeUploadProgressOut | None


class YouTubePanelOut(BaseModel):
    renders: list[YouTubeRenderOut]
    # The render being published; None when the project has no render.
    render_number: int | None
    # Why a draft cannot be written yet, or None.
    blocked_reason: str | None
    draft: YouTubeDraftOut | None
    # The newest draft job, whatever its status.
    job: DiscoveryJobOut | None
    thumbnail: YouTubeThumbnailOut
    channels: list[YouTubeChannelOut]
    default_channel_row_id: int | None
    default_privacy: Privacy
    uploads: list[YouTubeUploadOut]


class YouTubeDraftRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    render_number: int = Field(ge=1, le=_MAX_INT)
    # The owner's note on the newest draft. `user_feedback.clean` checks it again.
    feedback: str | None = Field(default=None, max_length=user_feedback.MAX_CHARS)


class YouTubeDraftRunOut(BaseModel):
    job_id: int
    # Why the thumbnail could not be started, or None. The draft is written either way.
    thumbnail_note: str | None


class YouTubeUploadIn(BaseModel):
    """Pressing Upload. The server checks all of it again, and the draft is the newest version
    (`draft_version` is the one the page showed).
    """

    model_config = ConfigDict(extra="forbid")

    render_number: int = Field(ge=1, le=_MAX_INT)
    channel_row_id: int = Field(ge=1, le=_MAX_INT)
    draft_version: int = Field(ge=1, le=_MAX_INT)
    privacy: Privacy
    # None means not answered, which is refused: the owner must choose yes or no.
    made_for_kids: bool | None = None
    synthetic_media: bool | None = None
    notify_subscribers: bool = True
    # Send the render's SRT captions after processing. The server checks the render has a caption
    # track when true.
    captions: bool = False


class YouTubeRetryIn(BaseModel):
    """Try again on one failed step. No body (or no step) tries the whole upload again, or
    finishes the thumbnail and captions.
    """

    model_config = ConfigDict(extra="forbid")

    step: UploadStep | None = None


class YouTubeSendIn(BaseModel):
    """Send one step again to a video that YouTube has processed (YTF-001)."""

    model_config = ConfigDict(extra="forbid")

    step: UploadStep


class YouTubeDraftEditIn(BaseModel):
    """The owner's edit. The service checks it again with the model's rules."""

    model_config = ConfigDict(extra="forbid")

    render_number: int = Field(ge=1, le=_MAX_INT)
    title: str = Field(max_length=1000)
    description: str = Field(max_length=20_000)
    hashtags: list[str] = Field(max_length=50)


def _job_out(job: Job | None) -> DiscoveryJobOut | None:
    if job is None:
        return None
    return DiscoveryJobOut(
        id=job.id, status=cast(JobStatus, job.status), phase=job.phase, error=job.error
    )


def _draft_out(entry: youtube_draft.DraftEntry) -> YouTubeDraftOut:
    row = entry.row
    content = row.content
    hashtags = list(content["hashtags"])
    return YouTubeDraftOut(
        version=row.version,
        source=cast(Literal["ai", "manual"], row.source),
        job_id=row.job_id,
        render_number=entry.render_number,
        title=content["title"],
        description=content["description"],
        hashtags=hashtags,
        description_sent=draft_writer.description_with_hashtags(content["description"], hashtags),
        made_for_kids=YouTubeSuggestionOut.model_validate(content["made_for_kids"]),
        synthetic_media=YouTubeSuggestionOut.model_validate(content["synthetic_media"]),
        out_of_date=bool(entry.reasons),
        reasons=entry.reasons,
        feedback=user_feedback.text_of(row.inputs),
        created_at=row.created_at,
    )


def _thumbnail_out(situation: youtube_draft.ThumbnailSituation) -> YouTubeThumbnailOut:
    chosen = situation.chosen
    return YouTubeThumbnailOut(
        status=situation.status,
        thumbnail_id=chosen.id if chosen is not None else None,
        url=media_url(chosen.path) if chosen is not None and chosen.path is not None else None,
        headline=chosen.headline if chosen is not None else None,
        width=chosen.width if chosen is not None else None,
        height=chosen.height if chosen is not None else None,
        reasons=situation.reasons,
        error=situation.error,
    )


def _sent_text(sent: object, *keys: str) -> str | None:
    """A string of the upload's snapshot, found by following `keys`, or None."""
    value: object = sent
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, str) else None


def _step_out(result: object) -> YouTubeStepResultOut | None:
    """A stored step result, or None when there is none or it cannot be read."""
    if not isinstance(result, dict):
        return None
    step_status = result.get("status")
    if step_status not in ("done", "skipped", "failed"):
        return None
    at: datetime | None = None
    if isinstance(result.get("at"), str):
        try:
            at = datetime.fromisoformat(result["at"])
        except ValueError:
            at = None
    message = result.get("message")
    thumbnail_id = result.get("thumbnail_id")
    from_snapshot = result.get("from_snapshot")
    return YouTubeStepResultOut(
        status=step_status,
        message=message if isinstance(message, str) else None,
        at=at,
        thumbnail_id=thumbnail_id
        if isinstance(thumbnail_id, int) and not isinstance(thumbnail_id, bool)
        else None,
        from_snapshot=from_snapshot if isinstance(from_snapshot, bool) else None,
        later=result.get("later") is True,
    )


def _upload_out(entry: youtube_draft.UploadEntry) -> YouTubeUploadOut:
    row = entry.row
    view = youtube_publish.upload_state(
        row,
        entry.job,
        entry.channel_connected,
        render_has_captions=entry.render_has_captions,
        thumbnail_chosen=entry.thumbnail_chosen,
    )
    live = live_status.upload_of(entry.job.id) if entry.job is not None else None
    privacy_sent = _sent_text(row.sent, "privacy")
    return YouTubeUploadOut(
        id=row.id,
        render_number=entry.render_number,
        channel_row_id=row.channel_row_id,
        channel_title=_sent_text(row.sent, "channel", "title"),
        title=_sent_text(row.sent, "title"),
        created_at=row.created_at,
        finished_at=row.finished_at,
        video_id=row.video_id,
        privacy_sent=(
            cast(Privacy, privacy_sent) if privacy_sent in youtube_publish.PRIVACY_VALUES else None
        ),
        privacy_applied=cast(Privacy | None, row.privacy_applied),
        state=view.state,
        processing=row.processing,
        error=(row.error or (entry.job.error if entry.job is not None else None))
        if view.state == "failed"
        else None,
        can_retry=view.can_retry,
        thumbnail_result=_step_out(row.thumbnail_result),
        captions_result=_step_out(row.captions_result),
        captions_sent=bool(row.sent.get("captions")) if isinstance(row.sent, dict) else False,
        can_finish=view.can_finish,
        retry_steps=[cast(UploadStep, step) for step in view.retry_steps],
        send_steps=[cast(UploadStep, step) for step in view.send_steps],
        sending_steps=[cast(UploadStep, step) for step in view.sending_steps],
        job=_job_out(entry.job),
        progress=(
            YouTubeUploadProgressOut(sent_bytes=live.sent_bytes, total_bytes=live.total_bytes)
            if live is not None and view.state == "uploading"
            else None
        ),
    )


async def _panel(
    session: AsyncSession, project: Project, render_number: int | None
) -> YouTubePanelOut:
    try:
        state = await youtube_draft.panel_state(session, project, render_number)
    except youtube_draft.NoSuchRenderError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return YouTubePanelOut(
        renders=[
            YouTubeRenderOut(
                render_number=choice.row.render_number,
                status=choice.status,
                reasons=choice.reasons,
                created_at=choice.row.created_at,
                duration_s=choice.row.duration_s,
                width=choice.row.width,
                height=choice.row.height,
                is_short=choice.is_short,
                has_captions=choice.has_captions,
                captions_burned=choice.captions_burned,
            )
            for choice in state.renders
        ],
        render_number=state.selected.row.render_number if state.selected is not None else None,
        blocked_reason=state.blocked_reason,
        draft=_draft_out(state.draft) if state.draft is not None else None,
        job=_job_out(state.job),
        thumbnail=_thumbnail_out(state.thumbnail),
        channels=[_channel_out(row) for row in state.channels],
        default_channel_row_id=state.default_channel_row_id,
        default_privacy=cast(Privacy, state.default_privacy),
        uploads=[_upload_out(entry) for entry in state.uploads],
    )


@router.get(
    "/projects/{project_id}/youtube",
    response_model=YouTubePanelOut,
    responses=_NO_PROJECT,
)
async def get_youtube_panel(
    project_id: int, session: SessionDep, render_number: int | None = None
) -> YouTubePanelOut:
    """What the Publish panel shows. `render_number` is the render being published (the newest
    when left out).
    """
    if render_number is not None and not 1 <= render_number <= _MAX_INT:
        raise HTTPException(status.HTTP_404_NOT_FOUND, youtube_draft.NO_SUCH_RENDER_MESSAGE)
    return await _panel(session, await load_project(session, project_id), render_number)


@router.post(
    "/projects/{project_id}/youtube/draft",
    response_model=YouTubeDraftRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NO_PROJECT, **_DRAFT_INVALID},
)
async def run_youtube_draft(
    project_id: int, body: YouTubeDraftRunIn, session: SessionDep
) -> YouTubeDraftRunOut:
    """Starts the job that writes the draft for a render, and makes sure the render has a
    thumbnail. If a draft is already being written, its job is returned and no second job is
    made.
    """
    project = await load_project(session, project_id)
    try:
        job_id, thumbnail_note = await youtube_draft.start_run(
            session, project, body.render_number, feedback=body.feedback
        )
    except youtube_draft.NoSuchRenderError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except youtube_draft.YouTubeDraftError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return YouTubeDraftRunOut(job_id=job_id, thumbnail_note=thumbnail_note)


@router.put(
    "/projects/{project_id}/youtube/draft",
    response_model=YouTubePanelOut,
    responses={**_NO_PROJECT, **_DRAFT_INVALID},
)
async def save_youtube_draft(
    project_id: int, body: YouTubeDraftEditIn, session: SessionDep
) -> YouTubePanelOut:
    """Saves the owner's edit of the title, description and hashtags as the next version."""
    project = await load_project(session, project_id)
    try:
        await youtube_draft.save_manual(
            session,
            project,
            body.render_number,
            title=body.title,
            description=body.description,
            hashtags=body.hashtags,
        )
    except youtube_draft.NoSuchRenderError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except youtube_draft.YouTubeDraftError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _panel(session, project, body.render_number)


_UPLOAD_REFUSED = {
    404: {"model": ErrorResponse, "description": "No such project, render or upload."},
    409: _NOT_CONFIGURED[409],
    422: {"model": ErrorResponse, "description": "A check before uploading failed."},
}


@router.post(
    "/projects/{project_id}/youtube/uploads",
    response_model=YouTubeUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_UPLOAD_REFUSED,
)
async def start_youtube_upload(
    project_id: int, body: YouTubeUploadIn, session: SessionDep
) -> YouTubeUploadOut:
    """Checks everything again, stores what will be sent and starts the upload. If this render
    is already being sent to this channel, that upload is returned and no second one is made.
    """
    project = await load_project(session, project_id)
    try:
        entry = await youtube_publish.start_upload(
            session,
            project,
            render_number=body.render_number,
            channel_row_id=body.channel_row_id,
            draft_version=body.draft_version,
            privacy=body.privacy,
            made_for_kids=body.made_for_kids,
            synthetic_media=body.synthetic_media,
            notify_subscribers=body.notify_subscribers,
            captions=body.captions,
        )
    except youtube_draft.NoSuchRenderError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except youtube_publish.YouTubePublishError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return _upload_out(entry)


@router.post(
    "/projects/{project_id}/youtube/uploads/{upload_id}/retry",
    response_model=YouTubeUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_UPLOAD_REFUSED,
)
async def retry_youtube_upload(
    project_id: int,
    upload_id: int,
    session: SessionDep,
    body: YouTubeRetryIn | None = None,
) -> YouTubeUploadOut:
    """Tries a failed upload again, finishes the thumbnail and captions of one that gave up
    waiting, or (with `step` in the body) tries one failed step again. What was done is not done
    again: a video that was sent is not sent a second time, nor a step that worked.
    """
    if not 1 <= upload_id <= _MAX_INT:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no such upload.")
    project = await load_project(session, project_id)
    try:
        entry = await youtube_publish.retry(
            session, project, upload_id, step=body.step if body is not None else None
        )
    except youtube_publish.NoSuchUploadError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except youtube_publish.YouTubePublishError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return _upload_out(entry)


@router.post(
    "/projects/{project_id}/youtube/uploads/{upload_id}/send",
    response_model=YouTubeUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_UPLOAD_REFUSED,
)
async def send_youtube_step(
    project_id: int, upload_id: int, body: YouTubeSendIn, session: SessionDep
) -> YouTubeUploadOut:
    """Send captions now / Set the thumbnail again: sends the render's captions, or the
    project's chosen thumbnail, to a video YouTube has processed. Nothing else is sent and the
    upload's snapshot is not changed. If a job for this upload is waiting or running, it is
    returned and no second job is made.
    """
    if not 1 <= upload_id <= _MAX_INT:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no such upload.")
    project = await load_project(session, project_id)
    try:
        entry = await youtube_publish.send_later(session, project, upload_id, body.step)
    except youtube_publish.NoSuchUploadError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except youtube_publish.YouTubePublishError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return _upload_out(entry)
