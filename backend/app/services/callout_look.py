"""The callout look of a motion explainer: starting the job that writes it, saving its versions,
and reading them back (CMO-002, `Callouts_motion_implementation_phases.md` §4.3).

Every version is a new `callout_look` row and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). `content` is `{look, reason}`
(`services/callout_look_writer`). `inputs` records the graphics look and the Story Bible the
version was built from (and the owner's note, when there was one), so whether it is out of date
is worked out when it is read and never stored.

One job makes a version: `start_run` queues it, and one model call writes the look. There is no
manual edit.

**When a look can be made.** The project must be a continuous explainer with `graphics` and
`callouts` on and `callout_style` set to `motion`, and its graphics look must exist and be
current.

A look is out of date when the newest graphics look is not the one it was written from. A new
look does not write any callout again: that is for the phases that make them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CalloutLook, Job, Project
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    graphic_theme,
    graphics_resolve,
    projects,
    provenance,
    story_bible,
    user_feedback,
)

JOB_TYPE: Final = "write_callout_look"
SOURCE_AI: Final = "ai"

GRAPHIC_THEME_KIND: Final = "graphic_theme"
STORY_BIBLE_KIND: Final = "story_bible"

OFF_MESSAGE: Final = (
    "The callout look is only for a continuous explainer with graphics and callouts on and the "
    "callout style set to Motion graphics in the settings."
)
NO_BIBLE_MESSAGE: Final = "Write the Story Bible first: the callout look follows its tone."
NO_THEME_MESSAGE: Final = "Write the graphics look first: the callout look follows it."
THEME_OUT_OF_DATE_MESSAGE: Final = (
    "The graphics look is out of date. Write it again first: the callout look follows it."
)
NO_LOOK_MESSAGE: Final = "There is no callout look yet, so there is nothing to comment on."
BEING_WRITTEN_MESSAGE: Final = "The callout look is already being written."

NEWER_THEME_REASON: Final = "The graphics look was written again since this callout look was made."
THEME_STALE_REASON: Final = "The graphics look is out of date: write it again first."


class CalloutLookError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


def wanted(project: Project) -> bool:
    """Whether the project has a callout look at all: a continuous explainer with graphics and
    callouts on, drawn as motion graphics.
    """
    return (
        graphic_theme.wanted(project)
        and project.callouts
        and project.callout_style == projects.CALLOUT_MOTION
    )


def blocked_reason(
    project: Project, bible: Any, theme_state: graphic_theme.GraphicThemeState | None
) -> str | None:
    """Why no look can be written now (or at all for this project), or None."""
    if not wanted(project):
        return OFF_MESSAGE
    if bible is None:
        return NO_BIBLE_MESSAGE
    if theme_state is None or theme_state.latest is None:
        return NO_THEME_MESSAGE
    if theme_state.out_of_date:
        return THEME_OUT_OF_DATE_MESSAGE
    return None


# --- Versions ------------------------------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> CalloutLook | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(CalloutLook)
        .where(CalloutLook.project_id == project_id)
        .order_by(CalloutLook.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def list_versions(session: AsyncSession, project_id: int) -> list[CalloutLook]:
    """Every version of the project, newest first."""
    statement = (
        select(CalloutLook)
        .where(CalloutLook.project_id == project_id)
        .order_by(CalloutLook.version.desc())
    )
    return list((await session.execute(statement)).scalars())


async def save_version(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    inputs: dict[str, Any],
    content: dict[str, Any],
) -> CalloutLook:
    """Adds the next version, made by the model (`source` is `ai`). Flushes but does not
    commit: the job commits it together with finishing itself, so a job is never "succeeded"
    without its result.
    """
    statement = select(func.max(CalloutLook.version)).where(CalloutLook.project_id == project_id)
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = CalloutLook(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=SOURCE_AI,
        job_id=job_id,
        inputs=inputs,
        content=content,
    )
    session.add(row)
    await session.flush()
    return row


# --- Starting a run ------------------------------------------------------------------------


def _saved_inputs(
    theme: Any, bible: Any, feedback: user_feedback.Feedback | None
) -> dict[str, Any]:
    """What a version is built from, in the artifact shape of D-3."""
    inputs: dict[str, Any] = {
        "artifacts": [
            {"kind": GRAPHIC_THEME_KIND, "id": theme.id, "version": theme.version},
            {"kind": STORY_BIBLE_KIND, "id": bible.id, "version": bible.version},
        ]
    }
    if feedback is not None:
        inputs["feedback"] = feedback.for_version()
    return inputs


def _feedback_on(text: str, newest: CalloutLook | None) -> user_feedback.Feedback:
    """The user's note on the newest look, with that look as what it is about. Raises
    CalloutLookError when the note is not usable or there is no look to talk about.
    """
    try:
        note = user_feedback.clean(text)
    except ValueError as exc:
        raise CalloutLookError(str(exc)) from exc
    if newest is None:
        raise CalloutLookError(NO_LOOK_MESSAGE)
    previous = {key: newest.content[key] for key in ("look", "reason")}
    return user_feedback.Feedback(text=note, previous=previous, base_version=newest.version)


async def start_run(session: AsyncSession, project: Project, *, feedback: str | None = None) -> Job:
    """Queues the job that writes the look, from a copy of what it is made from, and commits.
    If a job is already waiting or running for the project, that job is returned and no new one
    is made; a note is never dropped silently, so a note is refused in that case.

    `feedback` is the owner's note on the newest look: the model writes the look again with
    the note and that look in its request. Raises CalloutLookError when it cannot be written.
    """
    bible = await story_bible.latest(session, project.id)
    theme_state = await graphic_theme.state(session, project)
    reason = blocked_reason(project, bible, theme_state)
    if reason is not None:
        raise CalloutLookError(reason)
    theme = theme_state.latest
    assert theme is not None  # checked by `blocked_reason`
    note = _feedback_on(feedback, await latest(session, project.id)) if feedback else None
    colours, _notes = graphics_resolve.theme_for(theme.content["theme"])
    job_input: dict[str, Any] = {
        "bible": bible.content,
        "graphic_theme": theme.content["theme"],
        "colours": colours,
        "orientation": project.orientation,
        "saved_inputs": _saved_inputs(theme, bible, note),
    }
    if note is not None:
        job_input["feedback"] = note.for_job()
    job, created = await store.create_job(
        session, project_id=project.id, type=JOB_TYPE, provider="llm", input=job_input
    )
    if note is not None and not created:
        raise CalloutLookError(BEING_WRITTEN_MESSAGE)
    return job


# --- Reading the state ---------------------------------------------------------------------


def _recorded_theme(inputs: Any) -> dict[str, Any] | None:
    """The graphics look record that `inputs` says the version was built from."""
    if not isinstance(inputs, dict):
        return None
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == GRAPHIC_THEME_KIND:
            return artifact
    return None


def _out_of_date_reasons(
    row: CalloutLook, theme_state: graphic_theme.GraphicThemeState
) -> list[str]:
    """Why a version is no longer current, one sentence each."""
    reasons: list[str] = []
    if not provenance.same_row(_recorded_theme(row.inputs), theme_state.latest):
        reasons.append(NEWER_THEME_REASON)
    if theme_state.out_of_date:
        reasons.append(THEME_STALE_REASON)
    return reasons


@dataclass(frozen=True)
class CalloutLookState:
    """What the callout panel shows."""

    latest: CalloutLook | None
    versions: list[CalloutLook]
    # The newest job, whatever its status.
    job: Job | None
    out_of_date: bool
    reasons: list[str]
    # Why no look can be written yet (or at all for this project), or None.
    blocked_reason: str | None
    # Whether the project has a callout look at all (motion callouts on a continuous explainer).
    wanted: bool


@memoized_state
async def state(session: AsyncSession, project: Project) -> CalloutLookState:
    """The project's callout look with where it stands. Worked out on every read; nothing here
    is stored.
    """
    newest = await latest(session, project.id)
    versions = await list_versions(session, project.id)
    job = await store.latest_job(session, project.id, JOB_TYPE)
    bible = await story_bible.latest(session, project.id)
    theme_state = await graphic_theme.state(session, project)
    is_wanted = wanted(project)
    reasons = _out_of_date_reasons(newest, theme_state) if newest is not None and is_wanted else []
    return CalloutLookState(
        latest=newest,
        versions=versions,
        job=job,
        out_of_date=bool(reasons),
        reasons=reasons,
        blocked_reason=blocked_reason(project, bible, theme_state),
        wanted=is_wanted,
    )
