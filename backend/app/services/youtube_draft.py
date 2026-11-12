"""The YouTube publish draft of a project: starting the job that writes it, saving the owner's
edits, the thumbnail that goes with it, and what the Publish panel shows (YT-003,
`YouTube_publish_phases.md` §4.5 and §4.7).

Every version is a new `youtube_draft` row and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). `content` is
`{title, description, hashtags, made_for_kids, synthetic_media}` (`services/youtube_draft_writer`).
`inputs` records what the draft was written from, so whether it is out of date is worked out when
it is read and never stored:

    {"story_bible": {"id", "version"}, "script_sha256", "scenes": {"id", "version"} | None,
     "render_id", "feedback"?, "edited_from"?}

Two ways make a version:

- `start_run` queues the `write_youtube_draft` job: one call to the language model writes the
  text, and code checks it. It also makes sure the render has a thumbnail (`_start_thumbnail`).
- `save_manual` stores the owner's edit of the newest version, checked by the same rules.

Nothing here sends anything to YouTube.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import (
    Job,
    Project,
    StoryRender,
    Thumbnail,
    YouTubeChannel,
    YouTubeDraft,
    YouTubeUpload,
)
from app.jobs import store
from app.services import (
    caption_plan,
    discovery,
    provenance,
    story_bible,
    story_renders,
    thumbnail_concepts,
    thumbnails,
    user_feedback,
    youtube_auth,
)
from app.services import youtube_draft_writer as writer

JOB_TYPE: Final = "write_youtube_draft"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"

NO_BIBLE_MESSAGE: Final = "Write the Story Bible first: the YouTube text follows its tone."
NO_RENDER_MESSAGE: Final = "Render the video first: the draft is written for a finished render."
NO_SUCH_RENDER_MESSAGE: Final = "There is no such render."
NO_DRAFT_MESSAGE: Final = "There is no draft yet, so there is nothing to change."
BEING_WRITTEN_MESSAGE: Final = "The YouTube draft is already being written."

ThumbnailStatus = Literal["ready", "out_of_date", "making", "none"]


class YouTubeDraftError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


class NoSuchRenderError(YouTubeDraftError):
    """The render number is not one of the project's renders."""


# --- Versions --------------------------------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> YouTubeDraft | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(YouTubeDraft)
        .where(YouTubeDraft.project_id == project_id)
        .order_by(YouTubeDraft.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def _add_version(
    session: AsyncSession,
    *,
    project_id: int,
    source: str,
    job_id: int | None,
    render_id: int,
    inputs: dict[str, Any],
    content: dict[str, Any],
) -> YouTubeDraft:
    statement = select(func.max(YouTubeDraft.version)).where(YouTubeDraft.project_id == project_id)
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = YouTubeDraft(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=source,
        job_id=job_id,
        render_id=render_id,
        inputs=inputs,
        content=content,
    )
    session.add(row)
    await session.flush()
    return row


async def save_version(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    render_id: int,
    inputs: dict[str, Any],
    content: dict[str, Any],
) -> YouTubeDraft:
    """Adds the next version, made by the model (`source` is `ai`). Flushes but does not
    commit: the job commits it together with finishing itself, so a job is never "succeeded"
    without its result.
    """
    return await _add_version(
        session,
        project_id=project_id,
        source=SOURCE_AI,
        job_id=job_id,
        render_id=render_id,
        inputs=inputs,
        content=content,
    )


async def _find_render(session: AsyncSession, project_id: int, render_number: int) -> StoryRender:
    render = await story_renders.find_render(session, project_id, render_number)
    if render is None:
        raise NoSuchRenderError(NO_SUCH_RENDER_MESSAGE)
    return render


def _job_active(job: Job | None) -> bool:
    return job is not None and job.status in store.ACTIVE_STATUSES


# --- What a draft is made from ---------------------------------------------------------------


async def _scenes_row(session: AsyncSession, project_id: int) -> Any:
    """The project's newest scene discovery, or None."""
    return await discovery.latest(session, "scenes", project_id)


def _record(row: Any) -> dict[str, int] | None:
    return {"id": row.id, "version": row.version} if row is not None else None


def _saved_inputs(
    bible: Any,
    script: str,
    scenes: Any,
    render: StoryRender,
    feedback: user_feedback.Feedback | None,
) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "story_bible": _record(bible),
        "script_sha256": story_bible.story_sha256(script),
        "scenes": _record(scenes),
        "render_id": render.id,
    }
    if feedback is not None:
        inputs["feedback"] = feedback.for_version()
    return inputs


def _feedback_on(text: str, newest: YouTubeDraft | None) -> user_feedback.Feedback:
    """The user's note on the newest draft, with that draft as what it is about. Raises
    YouTubeDraftError when the note is not usable or there is no draft to talk about.
    """
    try:
        note = user_feedback.clean(text)
    except ValueError as exc:
        raise YouTubeDraftError(str(exc)) from exc
    if newest is None:
        raise YouTubeDraftError(NO_DRAFT_MESSAGE)
    return user_feedback.Feedback(text=note, previous=newest.content, base_version=newest.version)


# --- The thumbnail ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThumbnailSituation:
    """Where the thumbnail of the render being published stands."""

    status: ThumbnailStatus
    # The project's chosen thumbnail with a finished picture, or None.
    chosen: Thumbnail | None
    # Why the chosen thumbnail is out of date for this render. Empty otherwise.
    reasons: list[str]
    # The last failure when no usable thumbnail is being made, or None.
    error: str | None


async def thumbnail_situation(
    session: AsyncSession, project: Project, render: StoryRender | None
) -> ThumbnailSituation:
    """The chosen thumbnail and whether it is current for `render`, and whether a thumbnail is
    being made now. Worked out on every read; nothing is stored.
    """
    state = await thumbnails.state(session, project)
    bible = await story_bible.latest(session, project.id)
    chosen_entry = next((e for e in state.thumbnails if e.row.chosen and e.row.path), None)
    reasons: list[str] = []
    if chosen_entry is not None and render is not None:
        version = next(
            (v for v in state.concepts.versions if v.version == chosen_entry.row.concept_version),
            None,
        )
        if version is not None:
            reasons = thumbnail_concepts.out_of_date_reasons(version, bible, render)
    making = _job_active(state.concepts.job) or any(_job_active(e.job) for e in state.thumbnails)
    error: str | None = None
    if state.concepts.job is not None and state.concepts.job.status == "failed":
        error = state.concepts.job.error
    elif state.thumbnails and state.thumbnails[0].error:
        error = state.thumbnails[0].error

    chosen = chosen_entry.row if chosen_entry is not None else None
    status: ThumbnailStatus
    if chosen is not None and not reasons:
        status, error = "ready", None
    elif making:
        status, error = "making", None
    elif chosen is not None:
        status = "out_of_date"
    else:
        status = "none"
    return ThumbnailSituation(status=status, chosen=chosen, reasons=reasons, error=error)


async def _start_thumbnail(
    session: AsyncSession, project: Project, render: StoryRender
) -> str | None:
    """Makes sure the render being published gets a chosen thumbnail (§4.5). Nothing is done
    when the chosen thumbnail is current for this render, or when thumbnail work is already
    running. Otherwise the thumbnail concepts are written from this render's frames and, when
    they are stored, the picture of the first concept is made and chosen, unless the owner
    chooses one meanwhile. Commits. Returns a sentence when the thumbnail could not be started
    (the draft is not affected), else None.
    """
    situation = await thumbnail_situation(session, project, render)
    if situation.status in ("ready", "making"):
        return None
    marker = {"chosen_before": situation.chosen.id if situation.chosen is not None else None}
    bible = await story_bible.latest(session, project.id)
    newest = await thumbnail_concepts.latest(session, project.id)
    try:
        if newest is not None and not thumbnail_concepts.out_of_date_reasons(newest, bible, render):
            await thumbnails.start_images(
                session, project, newest.version, [0], choose_when_ready=marker
            )
        else:
            await thumbnail_concepts.start_run(session, project, render=render, then_picture=marker)
    except (thumbnails.ThumbnailError, thumbnail_concepts.ThumbnailConceptsError) as exc:
        return str(exc)
    return None


# --- Starting a run --------------------------------------------------------------------------


async def start_run(
    session: AsyncSession,
    project: Project,
    render_number: int,
    *,
    feedback: str | None = None,
) -> tuple[int, str | None]:
    """Queues the job that writes the draft for a render, from a copy of what it is made from,
    makes sure the render has a thumbnail, and commits. Returns the job's id and a sentence
    about the thumbnail when it could not be started. If a job is already waiting or running
    for the project, that job is used and no new one is made; a note is never dropped silently,
    so a note is refused in that case.

    `feedback` is the owner's note on the newest draft. Raises YouTubeDraftError.
    """
    project_id = project.id
    # The same order as the panel's `blocked_reason`: the render first, then the Story Bible.
    if await thumbnail_concepts.newest_render(session, project_id) is None:
        raise YouTubeDraftError(NO_RENDER_MESSAGE)
    render = await _find_render(session, project_id, render_number)
    bible = await story_bible.latest(session, project_id)
    if bible is None:
        raise YouTubeDraftError(NO_BIBLE_MESSAGE)
    note = _feedback_on(feedback, await latest(session, project_id)) if feedback else None
    script = project.script_text or ""
    scenes = await _scenes_row(session, project_id)
    context = writer.context_for_model(
        bible.content,
        script,
        await thumbnail_concepts.scene_titles(session, project_id),
        kind=project.kind,
        orientation=project.orientation,
        duration_s=render.duration_s,
        short=writer.is_short(render.width, render.height, render.duration_s),
    )
    job_input: dict[str, Any] = {
        "render_id": render.id,
        "context": context,
        "saved_inputs": _saved_inputs(bible, script, scenes, render, note),
    }
    if note is not None:
        job_input["feedback"] = note.for_job()
    job, created = await store.create_job(
        session, project_id=project_id, type=JOB_TYPE, provider="llm", input=job_input
    )
    job_id = job.id
    if note is not None and not created:
        raise YouTubeDraftError(BEING_WRITTEN_MESSAGE)
    thumbnail_note = await _start_thumbnail(session, project, render)
    return job_id, thumbnail_note


# --- The owner's edit ------------------------------------------------------------------------


async def save_manual(
    session: AsyncSession,
    project: Project,
    render_number: int,
    *,
    title: str,
    description: str,
    hashtags: list[str],
) -> YouTubeDraft:
    """Stores the owner's edit of the newest draft as the next version (`source` is `manual`),
    and commits. The checks are the model's, except that the description may be empty and there
    may be no hashtags. What the draft was written from is copied from the version that was
    edited, so an edit never makes an old draft look new; the two suggestions are copied too.
    `render_number` is the render being published. Refused while a job is writing the draft.
    Raises YouTubeDraftError.
    """
    project_id = project.id
    newest = await latest(session, project_id)
    if newest is None:
        raise YouTubeDraftError(NO_DRAFT_MESSAGE)
    if _job_active(await store.latest_job(session, project_id, JOB_TYPE)):
        raise YouTubeDraftError(BEING_WRITTEN_MESSAGE)
    render = await _find_render(session, project_id, render_number)
    try:
        checked_title, checked_description, checked_tags = writer.check_fields(
            title,
            description,
            hashtags,
            min_hashtags=0,
            allow_empty_description=True,
        )
    except ValueError as exc:
        raise YouTubeDraftError(str(exc)) from exc
    inputs: dict[str, Any] = {
        key: value
        for key, value in (newest.inputs if isinstance(newest.inputs, dict) else {}).items()
        if key not in ("feedback", "edited_from")
    }
    inputs["render_id"] = render.id
    inputs["edited_from"] = {"id": newest.id, "version": newest.version}
    content = {
        "title": checked_title,
        "description": checked_description,
        "hashtags": checked_tags,
        "made_for_kids": newest.content["made_for_kids"],
        "synthetic_media": newest.content["synthetic_media"],
    }
    row = await _add_version(
        session,
        project_id=project_id,
        source=SOURCE_MANUAL,
        job_id=None,
        render_id=render.id,
        inputs=inputs,
        content=content,
    )
    await session.commit()
    return row


# --- Reading the state -----------------------------------------------------------------------


def _same_record(recorded: Any, newest: Any) -> bool:
    """Whether `recorded` (`{"id", "version"}` or None) is `newest` (a row or None)."""
    if recorded is None or newest is None:
        return recorded is None and newest is None
    return provenance.same_row(recorded, newest)


async def out_of_date_reasons(
    session: AsyncSession, row: YouTubeDraft, project: Project, render: StoryRender | None
) -> list[str]:
    """Why a draft is no longer current for the render being published, one sentence each.
    Out of date only shows a reason; the owner can still upload the draft.
    """
    inputs = row.inputs if isinstance(row.inputs, dict) else {}
    reasons: list[str] = []
    bible = await story_bible.latest(session, project.id)
    if not provenance.same_row(inputs.get("story_bible"), bible):
        reasons.append("The Story Bible was written again since this draft was made.")
    script = project.script_text or ""
    if inputs.get("script_sha256") != story_bible.story_sha256(script):
        reasons.append("The story text was changed since this draft was made.")
    scenes = await _scenes_row(session, project.id)
    if not _same_record(inputs.get("scenes"), scenes):
        reasons.append("The scenes were changed since this draft was made.")
    if render is not None and row.render_id != render.id:
        drafted_for = await session.get(StoryRender, row.render_id)
        number = drafted_for.render_number if drafted_for is not None else "another"
        reasons.append(
            f"This draft was written for render {number}, not render {render.render_number}."
        )
    return reasons


@dataclass(frozen=True)
class RenderChoice:
    """One finished render the owner may publish."""

    row: StoryRender
    status: Literal["current", "out_of_date"]
    reasons: list[str]
    is_short: bool
    # Whether the render has a caption track that can be read, and whether that track is drawn on
    # the picture (Y-8: burned captions are not uploaded by default).
    has_captions: bool = False
    captions_burned: bool = False


def captions_of(row: StoryRender) -> tuple[bool, bool]:
    """`(has_captions, captions_burned)` from the render's frozen caption track. A track that
    cannot be read counts as no track.
    """
    try:
        track = caption_plan.parse_track(story_renders.recorded_captions(row))
    except caption_plan.CaptionError:
        return False, False
    if track is None:
        return False, False
    return True, track.burned


@dataclass(frozen=True)
class DraftEntry:
    """The newest draft and where it stands."""

    row: YouTubeDraft
    # The render number the draft was written for.
    render_number: int | None
    reasons: list[str]


@dataclass(frozen=True)
class UploadEntry:
    """An earlier press of Upload, with the job that does it (None once the job is deleted)."""

    row: YouTubeUpload
    render_number: int
    job: Job | None
    # Whether the upload's channel is still connected (and usable), for Try again and Finish.
    channel_connected: bool = False
    # For Send captions now and Set the thumbnail again (YTF-001): whether the render has a
    # readable caption track, and whether the project has a chosen thumbnail with a picture.
    render_has_captions: bool = False
    thumbnail_chosen: bool = False


@dataclass(frozen=True)
class PanelState:
    """What the Publish panel shows."""

    renders: list[RenderChoice]
    selected: RenderChoice | None
    # Why a draft cannot be written yet, or None.
    blocked_reason: str | None
    draft: DraftEntry | None
    # The newest draft job, whatever its status.
    job: Job | None
    thumbnail: ThumbnailSituation
    channels: list[YouTubeChannel]
    default_channel_row_id: int | None
    default_privacy: str
    uploads: list[UploadEntry]


def default_channel(channels: list[YouTubeChannel]) -> int | None:
    """The connected channel used last, else the first connected one, else None."""
    connected = [c for c in channels if c.status == youtube_auth.STATUS_CONNECTED]
    if not connected:
        return None
    best = connected[0]
    for channel in connected:
        used = channel.last_used_at
        if used is not None and (best.last_used_at is None or used > best.last_used_at):
            best = channel
    return best.id


async def has_chosen_thumbnail(session: AsyncSession, project_id: int) -> bool:
    """Whether the project has a chosen thumbnail with a picture (what Set the thumbnail again
    would send).
    """
    found = await session.scalar(
        select(Thumbnail.id)
        .where(
            Thumbnail.project_id == project_id,
            Thumbnail.chosen.is_(True),
            Thumbnail.path.is_not(None),
        )
        .limit(1)
    )
    return found is not None


async def _uploads(session: AsyncSession, project_id: int) -> list[UploadEntry]:
    thumbnail_chosen = await has_chosen_thumbnail(session, project_id)
    statement = (
        select(YouTubeUpload, StoryRender, Job, YouTubeChannel.status)
        .join(StoryRender, StoryRender.id == YouTubeUpload.render_id)
        .outerjoin(Job, Job.id == YouTubeUpload.job_id)
        .outerjoin(YouTubeChannel, YouTubeChannel.id == YouTubeUpload.channel_row_id)
        .where(YouTubeUpload.project_id == project_id)
        .order_by(YouTubeUpload.id.desc())
        # The job moves while an upload runs, so a copy kept from an earlier read is not used.
        .execution_options(populate_existing=True)
    )
    return [
        UploadEntry(
            row=row,
            render_number=render.render_number,
            job=job,
            channel_connected=channel_status == youtube_auth.STATUS_CONNECTED,
            render_has_captions=captions_of(render)[0],
            thumbnail_chosen=thumbnail_chosen,
        )
        for row, render, job, channel_status in await session.execute(statement)
    ]


async def panel_state(
    session: AsyncSession, project: Project, render_number: int | None
) -> PanelState:
    """The renders, the newest draft with where it stands, the thumbnail, the channels and the
    earlier uploads. `render_number` is the render being published (the newest when None).
    Worked out on every read; nothing here is stored. Raises NoSuchRenderError.
    """
    state = await story_renders.state(session, project)
    renders: list[RenderChoice] = []
    for entry in state.renders:
        has_captions, captions_burned = captions_of(entry.row)
        renders.append(
            RenderChoice(
                row=entry.row,
                status=entry.status,
                reasons=entry.reasons,
                is_short=writer.is_short(entry.row.width, entry.row.height, entry.row.duration_s),
                has_captions=has_captions,
                captions_burned=captions_burned,
            )
        )
    selected: RenderChoice | None
    if render_number is None:
        selected = renders[0] if renders else None
    else:
        selected = next((r for r in renders if r.row.render_number == render_number), None)
        if selected is None:
            raise NoSuchRenderError(NO_SUCH_RENDER_MESSAGE)

    bible = await story_bible.latest(session, project.id)
    blocked: str | None = None
    if selected is None:
        blocked = NO_RENDER_MESSAGE
    elif bible is None:
        blocked = NO_BIBLE_MESSAGE

    newest = await latest(session, project.id)
    draft: DraftEntry | None = None
    if newest is not None:
        selected_row = selected.row if selected is not None else None
        drafted_for = next((r for r in renders if r.row.id == newest.render_id), None)
        draft = DraftEntry(
            row=newest,
            render_number=drafted_for.row.render_number if drafted_for is not None else None,
            reasons=await out_of_date_reasons(session, newest, project, selected_row),
        )
    channels = await youtube_auth.list_channels(session)
    return PanelState(
        renders=renders,
        selected=selected,
        blocked_reason=blocked,
        draft=draft,
        job=await store.latest_job(session, project.id, JOB_TYPE),
        thumbnail=await thumbnail_situation(
            session, project, selected.row if selected is not None else None
        ),
        channels=channels,
        default_channel_row_id=default_channel(channels),
        default_privacy=await settings_service.get_str(
            session, settings_service.YOUTUBE_DEFAULT_PRIVACY_KEY
        ),
        uploads=await _uploads(session, project.id),
    )
