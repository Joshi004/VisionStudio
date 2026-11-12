"""The YouTube publish draft of a project: starting the job that writes it, saving the owner's
edits, the thumbnail that goes with it, and what the Publish panel shows (YT-003,
`YouTube_publish_phases.md` §4.5 and §4.7).

Every version is a new `youtube_draft` row and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). `content` is
`{title, description, hashtags, tags}` (`services/youtube_draft_writer`). An older version may also
carry `made_for_kids` and `synthetic_media`; they are ignored, and a missing `tags` reads as `[]`.
`inputs` records what the draft was written from, so whether it is out of date is worked out when
it is read and never stored:

    {"story_bible": {"id", "version"}, "script_sha256", "scenes": {"id", "version"} | None,
     "render_id" | "render_job_id", "started_at_render"?, "feedback"?, "edited_from"?}

A draft is written for a finished render (`render_id`) or, when it is started while the video is
still being made (YTF-004), for the render job (`render_job_id`; the `render_id` column is then
NULL). It counts as for render R when it recorded R's id or R's `job_id`. `started_at_render` is
true when the draft was started by pressing Render rather than by the Publish panel.

Three ways make a version:

- `start_run` queues the `write_youtube_draft` job: one call to the language model writes the
  text, and code checks it. It also makes sure the render has a thumbnail (`_start_thumbnail`).
- `start_for_render_job` is the same, started by `story_renders.start_render` for the render job
  it has just queued (F-1). It is best effort and sends nothing to YouTube.
- `save_manual` stores the owner's edit of the newest version, checked by the same rules.

Nothing here sends anything to YouTube.
"""

from __future__ import annotations

import logging
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

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "write_youtube_draft"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"

NO_BIBLE_MESSAGE: Final = "Write the Story Bible first: the YouTube text follows its tone."
NO_RENDER_MESSAGE: Final = "Render the video first: the draft is written for a render."
NO_SUCH_RENDER_MESSAGE: Final = "There is no such render."
NO_RENDERING_MESSAGE: Final = "There is no render being made now."
BAD_TIMELINE_MESSAGE: Final = "The render being made has no usable length, so it cannot be drafted."
NO_DRAFT_MESSAGE: Final = "There is no draft yet, so there is nothing to change."
BEING_WRITTEN_MESSAGE: Final = "The YouTube draft is already being written."
_ALL_PICTURES_MADE_MESSAGE: Final = "Every idea already has a picture. Choose one below."

ThumbnailStatus = Literal["ready", "out_of_date", "making", "none"]
# Where the render a draft was written for stands: `made` (a finished render), `rendering` (the
# render job is still running) or `not_made` (the job failed or was cancelled).
DraftRenderState = Literal["made", "rendering", "not_made"]


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
    render_id: int | None,
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
    render_id: int | None,
    inputs: dict[str, Any],
    content: dict[str, Any],
) -> YouTubeDraft:
    """Adds the next version, made by the model (`source` is `ai`). `render_id` is None for a
    draft written while its render was still being made (`inputs.render_job_id` names it).
    Flushes but does not commit: the job commits it together with finishing itself, so a job is
    never "succeeded" without its result.
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


async def active_render_job(session: AsyncSession, project_id: int) -> Job | None:
    """The project's story render job that is waiting or running, or None."""
    job = await store.latest_job(session, project_id, story_renders.JOB_TYPE)
    return job if _job_active(job) else None


@dataclass(frozen=True)
class _Target:
    """The render a draft is written for: a finished render, or the render job still being made
    (then only its frozen timeline is known: the length and the shape).
    """

    render: StoryRender | None
    job: Job | None
    duration_s: float | None
    width: int | None
    height: int | None


def _render_target(render: StoryRender) -> _Target:
    return _Target(
        render=render,
        job=None,
        duration_s=render.duration_s,
        width=render.width,
        height=render.height,
    )


def _whole(value: object) -> int | None:
    """`value` when it is a positive whole number (not a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _job_target(job: Job) -> _Target:
    """The target made from a render job's frozen timeline: `total_frames / fps`, `width` and
    `height`, exactly what the finished video will have. Raises YouTubeDraftError.
    """
    timeline = job.input.get("timeline") if isinstance(job.input, dict) else None
    if not isinstance(timeline, dict):
        raise YouTubeDraftError(BAD_TIMELINE_MESSAGE)
    frames, fps = _whole(timeline.get("total_frames")), _whole(timeline.get("fps"))
    width, height = _whole(timeline.get("width")), _whole(timeline.get("height"))
    if frames is None or fps is None or width is None or height is None:
        raise YouTubeDraftError(BAD_TIMELINE_MESSAGE)
    return _Target(render=None, job=job, duration_s=frames / fps, width=width, height=height)


async def _target_of(session: AsyncSession, project_id: int, render_number: int | None) -> _Target:
    """What a draft is written for: the finished render with this number, or (`None`) the render
    being made now. Raises NoSuchRenderError or YouTubeDraftError.
    """
    # The same order as the panel's `blocked_reason`: the render first, then the Story Bible.
    if render_number is None:
        job = await active_render_job(session, project_id)
        if job is not None:
            return _job_target(job)
        if await thumbnail_concepts.newest_render(session, project_id) is None:
            raise YouTubeDraftError(NO_RENDER_MESSAGE)
        raise YouTubeDraftError(NO_RENDERING_MESSAGE)
    if await thumbnail_concepts.newest_render(session, project_id) is None:
        raise YouTubeDraftError(NO_RENDER_MESSAGE)
    return _render_target(await _find_render(session, project_id, render_number))


# --- What a draft is made from ---------------------------------------------------------------


async def _scenes_row(session: AsyncSession, project_id: int) -> Any:
    """The project's newest scene discovery, or None."""
    return await discovery.latest(session, "scenes", project_id)


def _record(row: Any) -> dict[str, int] | None:
    return {"id": row.id, "version": row.version} if row is not None else None


def _render_keys(target: _Target) -> dict[str, int]:
    """Exactly one of `render_id` (a finished render) and `render_job_id` (a render being made),
    for the draft job's input and for the version's `inputs`.
    """
    if target.render is not None:
        return {"render_id": target.render.id}
    assert target.job is not None
    return {"render_job_id": target.job.id}


def _saved_inputs(
    bible: Any,
    script: str,
    scenes: Any,
    target: _Target,
    feedback: user_feedback.Feedback | None,
    *,
    started_at_render: bool = False,
) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "story_bible": _record(bible),
        "script_sha256": story_bible.story_sha256(script),
        "scenes": _record(scenes),
    }
    inputs.update(_render_keys(target))
    if started_at_render:
        inputs["started_at_render"] = True
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
    # Only the fields that are still drafted: an older version may carry the two suggestions.
    previous = {
        key: newest.content.get(key, [] if key == "tags" else "")
        for key in ("title", "description", "hashtags", "tags")
    }
    return user_feedback.Feedback(text=note, previous=previous, base_version=newest.version)


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
    # Whether a picture of the newest thumbnail ideas is still being made (YTF-003). Upload waits
    # for it even when a thumbnail is already chosen.
    pictures_making: bool = False


async def thumbnail_situation(session: AsyncSession, project: Project) -> ThumbnailSituation:
    """The chosen thumbnail and whether it is current (its ideas were written from the present
    Story Bible and script; a render does not matter), and whether a thumbnail is being made
    now. Worked out on every read; nothing is stored.
    """
    state = await thumbnails.state(session, project)
    bible = await story_bible.latest(session, project.id)
    chosen_entry = next((e for e in state.thumbnails if e.row.chosen and e.row.path), None)
    reasons: list[str] = []
    if chosen_entry is not None:
        version = next(
            (v for v in state.concepts.versions if v.version == chosen_entry.row.concept_version),
            None,
        )
        if version is not None:
            reasons = thumbnail_concepts.out_of_date_reasons(
                version, bible, project.script_text or ""
            )
    making = _job_active(state.concepts.job) or any(_job_active(e.job) for e in state.thumbnails)
    newest_ideas = state.concepts.latest
    pictures_making = newest_ideas is not None and any(
        e.row.concept_version == newest_ideas.version and _job_active(e.job)
        for e in state.thumbnails
    )
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
    return ThumbnailSituation(
        status=status,
        chosen=chosen,
        reasons=reasons,
        error=error,
        pictures_making=pictures_making,
    )


async def _start_thumbnail(session: AsyncSession, project: Project) -> str | None:
    """Makes sure the project has a chosen thumbnail (§4.5). Nothing is done when the chosen
    thumbnail is current, or when thumbnail work is already running. Otherwise, when the newest
    ideas are current, a picture is started for every idea that has none; or the thumbnail
    concepts are written from the script and, when they are stored, the pictures of all of them
    are made (YTF-003). The first picture to finish is chosen, unless the owner chooses one
    meanwhile. A render takes no part (YTF-006). Commits. Returns a sentence when the thumbnail
    could not be started (the draft is not affected), else None.
    """
    situation = await thumbnail_situation(session, project)
    if situation.status in ("ready", "making"):
        return None
    marker = {"chosen_before": situation.chosen.id if situation.chosen is not None else None}
    bible = await story_bible.latest(session, project.id)
    newest = await thumbnail_concepts.latest(session, project.id)
    try:
        if newest is not None and not thumbnail_concepts.out_of_date_reasons(
            newest, bible, project.script_text or ""
        ):
            missing = await thumbnails.indexes_without_picture(session, project.id, newest)
            if not missing:
                return _ALL_PICTURES_MADE_MESSAGE
            await thumbnails.start_images(
                session, project, newest.version, missing, choose_when_ready=marker
            )
        else:
            await thumbnail_concepts.start_run(session, project, then_picture=marker)
    except (thumbnails.ThumbnailError, thumbnail_concepts.ThumbnailConceptsError) as exc:
        return str(exc)
    return None


# --- Starting a run --------------------------------------------------------------------------


async def _queue_draft(
    session: AsyncSession,
    project: Project,
    target: _Target,
    *,
    feedback: str | None,
    started_at_render: bool,
) -> tuple[int, str | None]:
    """The part of every start that is the same: copies what the draft is made from into a job,
    queues it, and makes sure the project has a thumbnail. Commits. Raises YouTubeDraftError.
    """
    project_id = project.id
    bible = await story_bible.latest(session, project_id)
    if bible is None:
        raise YouTubeDraftError(NO_BIBLE_MESSAGE)
    note = _feedback_on(feedback, await latest(session, project_id)) if feedback else None
    script = project.script_text or ""
    scenes = await _scenes_row(session, project_id)
    cast = await thumbnail_concepts.cast_options(session, project)
    context = writer.context_for_model(
        bible.content,
        script,
        await thumbnail_concepts.scene_titles(session, project_id),
        [option.name for option in cast],
        kind=project.kind,
        orientation=project.orientation,
        duration_s=target.duration_s,
        short=writer.is_short(target.width, target.height, target.duration_s),
    )
    job_input: dict[str, Any] = {
        **_render_keys(target),
        "context": context,
        "saved_inputs": _saved_inputs(
            bible, script, scenes, target, note, started_at_render=started_at_render
        ),
    }
    if note is not None:
        job_input["feedback"] = note.for_job()
    job, created = await store.create_job(
        session, project_id=project_id, type=JOB_TYPE, provider="llm", input=job_input
    )
    job_id = job.id
    if note is not None and not created:
        raise YouTubeDraftError(BEING_WRITTEN_MESSAGE)
    thumbnail_note = await _start_thumbnail(session, project)
    return job_id, thumbnail_note


async def start_run(
    session: AsyncSession,
    project: Project,
    render_number: int | None,
    *,
    feedback: str | None = None,
) -> tuple[int, str | None]:
    """Queues the job that writes the draft for a render, from a copy of what it is made from,
    makes sure the render has a thumbnail, and commits. Returns the job's id and a sentence
    about the thumbnail when it could not be started. If a job is already waiting or running
    for the project, that job is used and no new one is made; a note is never dropped silently,
    so a note is refused in that case.

    `render_number` is a finished render, or None for the render being made now (YTF-004: then
    the length and shape come from the render job's frozen timeline).
    `feedback` is the owner's note on the newest draft. Raises NoSuchRenderError or
    YouTubeDraftError.
    """
    target = await _target_of(session, project.id, render_number)
    return await _queue_draft(session, project, target, feedback=feedback, started_at_render=False)


async def start_for_render_job(
    session: AsyncSession, project: Project, render_job: Job
) -> int | None:
    """The automatic start (F-1): called by `story_renders.start_render` for the render job it
    has just queued. Does nothing (returns None) when the setting `youtube_auto_draft` is off or
    the project has no Story Bible. Otherwise queues the draft for that job and the thumbnail
    work (`_start_thumbnail`: nothing when the chosen thumbnail is current, which settles YFQ-1)
    and returns the draft job's id; a draft job already waiting or running is returned as it is.
    Commits. Nothing is sent to YouTube. The caller catches every error.
    """
    mode = await settings_service.get_str(session, settings_service.YOUTUBE_AUTO_DRAFT_KEY)
    if mode != settings_service.YOUTUBE_AUTO_DRAFT_ON:
        return None
    if await story_bible.latest(session, project.id) is None:
        return None
    job_id, thumbnail_note = await _queue_draft(
        session, project, _job_target(render_job), feedback=None, started_at_render=True
    )
    if thumbnail_note is not None:
        _logger.info(
            "project %d: thumbnail not started with render job %d: %s",
            project.id,
            render_job.id,
            thumbnail_note,
        )
    return job_id


# --- The owner's edit ------------------------------------------------------------------------


async def save_manual(
    session: AsyncSession,
    project: Project,
    render_number: int | None,
    *,
    title: str,
    description: str,
    hashtags: list[str],
    tags: list[str],
) -> YouTubeDraft:
    """Stores the owner's edit of the newest draft as the next version (`source` is `manual`),
    and commits. The checks are the model's, except that the description may be empty and there
    may be no hashtags or tags (and tags may fill YouTube's whole limit). What the draft was
    written from is copied from the version that was edited, so an edit never makes an old draft
    look new.
    `render_number` is the render being published, or None for the render being made now
    (YTF-004). Refused while a job is writing the draft. Raises YouTubeDraftError.
    """
    project_id = project.id
    newest = await latest(session, project_id)
    if newest is None:
        raise YouTubeDraftError(NO_DRAFT_MESSAGE)
    if _job_active(await store.latest_job(session, project_id, JOB_TYPE)):
        raise YouTubeDraftError(BEING_WRITTEN_MESSAGE)
    if render_number is None:
        rendering = await active_render_job(session, project_id)
        if rendering is None:
            raise YouTubeDraftError(NO_RENDERING_MESSAGE)
        target = _Target(render=None, job=rendering, duration_s=None, width=None, height=None)
    else:
        target = _render_target(await _find_render(session, project_id, render_number))
    try:
        checked_title, checked_description, checked_tags = writer.check_fields(
            title,
            description,
            hashtags,
            min_hashtags=0,
            allow_empty_description=True,
        )
        checked_search_tags = writer.check_tags(
            tags, minimum=0, maximum=None, max_chars=writer.TAGS_MAX_CHARS
        )
    except ValueError as exc:
        raise YouTubeDraftError(str(exc)) from exc
    inputs: dict[str, Any] = {
        key: value
        for key, value in (newest.inputs if isinstance(newest.inputs, dict) else {}).items()
        if key not in ("feedback", "edited_from", "render_id", "render_job_id", "started_at_render")
    }
    inputs.update(_render_keys(target))
    inputs["edited_from"] = {"id": newest.id, "version": newest.version}
    content = {
        "title": checked_title,
        "description": checked_description,
        "hashtags": checked_tags,
        "tags": checked_search_tags,
    }
    row = await _add_version(
        session,
        project_id=project_id,
        source=SOURCE_MANUAL,
        job_id=None,
        render_id=target.render.id if target.render is not None else None,
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


def drafted_for(
    row: YouTubeDraft, renders: list[RenderChoice], rendering: Job | None
) -> tuple[DraftRenderState | None, int | None]:
    """Where the render a draft was written for stands, and its number when it is made.
    A draft is for render R when it recorded R's id or R's `job_id` (YTF-004). `(None, None)`
    means the draft names a render that is no longer listed.
    """
    if row.render_id is not None:
        found = next((r for r in renders if r.row.id == row.render_id), None)
        return ("made", found.row.render_number) if found is not None else (None, None)
    inputs = row.inputs if isinstance(row.inputs, dict) else {}
    job_id = _whole(inputs.get("render_job_id"))
    if job_id is None:
        return None, None
    made = next((r for r in renders if r.row.job_id == job_id), None)
    if made is not None:
        return "made", made.row.render_number
    if rendering is not None and rendering.id == job_id:
        return "rendering", None
    return "not_made", None


def _render_reasons(
    state: DraftRenderState | None,
    number: int | None,
    selected: RenderChoice | None,
) -> list[str]:
    """Why a draft is not for the render being published (`selected`, or None for the render
    being made now).
    """
    if state == "not_made":
        return ["This draft was written for a render that was not made."]
    if selected is None:
        if state == "rendering":
            return []
        which = f"render {number}" if number is not None else "a render that is no longer listed"
        return [f"This draft was written for {which}, not the render being made now."]
    if state == "rendering":
        return [
            "This draft was written for the render being made now, "
            f"not render {selected.row.render_number}."
        ]
    if number == selected.row.render_number:
        return []
    which = f"render {number}" if number is not None else "a render that is no longer listed"
    return [f"This draft was written for {which}, not render {selected.row.render_number}."]


async def out_of_date_reasons(
    session: AsyncSession,
    row: YouTubeDraft,
    project: Project,
    selected: RenderChoice | None,
    renders: list[RenderChoice],
    rendering: Job | None,
) -> list[str]:
    """Why a draft is no longer current for the render being published (`selected`, or None
    for the render being made now), one sentence each. Out of date only shows a reason; the
    owner can still upload the draft.
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
    state, number = drafted_for(row, renders, rendering)
    reasons.extend(_render_reasons(state, number, selected))
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
    # The render number the draft was written for, once that render is made.
    render_number: int | None
    reasons: list[str]
    # Where that render stands (None when it is no longer listed), and whether the draft was
    # started by pressing Render (YTF-004).
    render_state: DraftRenderState | None = None
    started_at_render: bool = False


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
    # The finished render being published, or None when the render being made now is.
    selected: RenderChoice | None
    # The story render job that is waiting or running, or None.
    rendering: Job | None
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
    earlier uploads. `render_number` is the render being published: the render being made now
    when None and one is waiting or running (YTF-004), else the newest finished one.
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
    rendering = await active_render_job(session, project.id)
    selected: RenderChoice | None
    if render_number is None:
        selected = renders[0] if renders and rendering is None else None
    else:
        selected = next((r for r in renders if r.row.render_number == render_number), None)
        if selected is None:
            raise NoSuchRenderError(NO_SUCH_RENDER_MESSAGE)

    bible = await story_bible.latest(session, project.id)
    blocked: str | None = None
    if selected is None and rendering is None:
        blocked = NO_RENDER_MESSAGE
    elif bible is None:
        blocked = NO_BIBLE_MESSAGE

    newest = await latest(session, project.id)
    draft: DraftEntry | None = None
    if newest is not None:
        render_state, drafted_number = drafted_for(newest, renders, rendering)
        newest_inputs = newest.inputs if isinstance(newest.inputs, dict) else {}
        draft = DraftEntry(
            row=newest,
            render_number=drafted_number,
            reasons=await out_of_date_reasons(
                session, newest, project, selected, renders, rendering
            ),
            render_state=render_state,
            started_at_render=newest_inputs.get("started_at_render") is True,
        )
    channels = await youtube_auth.list_channels(session)
    return PanelState(
        renders=renders,
        selected=selected,
        rendering=rendering,
        blocked_reason=blocked,
        draft=draft,
        job=await store.latest_job(session, project.id, JOB_TYPE),
        thumbnail=await thumbnail_situation(session, project),
        channels=channels,
        default_channel_row_id=default_channel(channels),
        default_privacy=await settings_service.get_str(
            session, settings_service.YOUTUBE_DEFAULT_PRIVACY_KEY
        ),
        uploads=await _uploads(session, project.id),
    )
