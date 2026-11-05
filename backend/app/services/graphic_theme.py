"""The graphics theme of a continuous explainer: starting the job that writes it, saving its
versions, and reading them back (EXG-002, `Explainer_graphics_implementation_phases.md` §3.3).

Every version is a new `graphic_theme` row and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). `content` is `{theme, reason, notes}`
(`services/graphic_theme_writer`). `inputs` records the Story Bible the version was built from
(and the owner's note, when there was one), so whether it is out of date is worked out when it is
read and never stored.

One job makes a version: `start_run` queues it, and one model call writes the theme. There is no
manual edit.

**When a theme can be made.** The project must be a continuous explainer with `graphics` on, and
its Story Bible must exist.

A theme is out of date when the newest Story Bible is not the one it was written from. A new
theme does not ask the model to write the graphics again (§3.3): that is for the phases that
make them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GraphicTheme, Job, Project
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import explainer, projects, provenance, story_bible, user_feedback

JOB_TYPE: Final = "write_graphic_theme"
SOURCE_AI: Final = "ai"

STORY_BIBLE_KIND: Final = "story_bible"

OFF_MESSAGE: Final = (
    "Graphics are only for a continuous explainer with graphics switched on, and this project "
    "has them off."
)
NO_BIBLE_MESSAGE: Final = "Write the Story Bible first: the graphics look follows its tone."
NO_THEME_MESSAGE: Final = "There is no graphics look yet, so there is nothing to comment on."
BEING_WRITTEN_MESSAGE: Final = "The graphics look is already being written."


class GraphicThemeError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


def wanted(project: Project) -> bool:
    """Whether the project has a graphics theme at all: a continuous explainer with graphics on."""
    return (
        explainer.is_explainer(project)
        and project.voice_track == projects.VOICE_CONTINUOUS
        and project.graphics
    )


def blocked_reason(project: Project, bible: Any) -> str | None:
    """Why no theme can be written now (or at all for this project), or None."""
    if not wanted(project):
        return OFF_MESSAGE
    if bible is None:
        return NO_BIBLE_MESSAGE
    return None


# --- Versions ------------------------------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> GraphicTheme | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(GraphicTheme)
        .where(GraphicTheme.project_id == project_id)
        .order_by(GraphicTheme.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def list_versions(session: AsyncSession, project_id: int) -> list[GraphicTheme]:
    """Every version of the project, newest first."""
    statement = (
        select(GraphicTheme)
        .where(GraphicTheme.project_id == project_id)
        .order_by(GraphicTheme.version.desc())
    )
    return list((await session.execute(statement)).scalars())


async def get_version(session: AsyncSession, project_id: int, version: int) -> GraphicTheme | None:
    """One version of the project, or None when there is no such version."""
    statement = select(GraphicTheme).where(
        GraphicTheme.project_id == project_id, GraphicTheme.version == version
    )
    return (await session.execute(statement)).scalars().first()


async def save_version(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    inputs: dict[str, Any],
    content: dict[str, Any],
) -> GraphicTheme:
    """Adds the next version, made by the model (`source` is `ai`). Flushes but does not
    commit: the job commits it together with finishing itself, so a job is never "succeeded"
    without its result.
    """
    statement = select(func.max(GraphicTheme.version)).where(GraphicTheme.project_id == project_id)
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = GraphicTheme(
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


def _saved_inputs(bible: Any, feedback: user_feedback.Feedback | None) -> dict[str, Any]:
    """What a version is built from, in the artifact shape of D-3."""
    inputs: dict[str, Any] = {
        "artifacts": [{"kind": STORY_BIBLE_KIND, "id": bible.id, "version": bible.version}]
    }
    if feedback is not None:
        inputs["feedback"] = feedback.for_version()
    return inputs


def _feedback_on(text: str, newest: GraphicTheme | None) -> user_feedback.Feedback:
    """The user's note on the newest theme, with that theme as what it is about. Raises
    GraphicThemeError when the note is not usable or there is no theme to talk about.
    """
    try:
        note = user_feedback.clean(text)
    except ValueError as exc:
        raise GraphicThemeError(str(exc)) from exc
    if newest is None:
        raise GraphicThemeError(NO_THEME_MESSAGE)
    previous = {key: newest.content[key] for key in ("theme", "reason")}
    return user_feedback.Feedback(text=note, previous=previous, base_version=newest.version)


async def start_run(session: AsyncSession, project: Project, *, feedback: str | None = None) -> Job:
    """Queues the job that writes the theme, from a copy of what it is made from, and commits.
    If a job is already waiting or running for the project, that job is returned and no new one
    is made; a note is never dropped silently, so a note is refused in that case.

    `feedback` is the owner's note on the newest theme: the model writes the theme again with
    the note and that theme in its request. Raises GraphicThemeError when it cannot be written.
    """
    bible = await story_bible.latest(session, project.id)
    reason = blocked_reason(project, bible)
    if reason is not None:
        raise GraphicThemeError(reason)
    note = _feedback_on(feedback, await latest(session, project.id)) if feedback else None
    job_input: dict[str, Any] = {
        "bible": bible.content,
        "orientation": project.orientation,
        "saved_inputs": _saved_inputs(bible, note),
    }
    if note is not None:
        job_input["feedback"] = note.for_job()
    job, created = await store.create_job(
        session, project_id=project.id, type=JOB_TYPE, provider="llm", input=job_input
    )
    if note is not None and not created:
        raise GraphicThemeError(BEING_WRITTEN_MESSAGE)
    return job


# --- Reading the state ---------------------------------------------------------------------


def _recorded_bible(inputs: Any) -> dict[str, Any] | None:
    """The Story Bible record that `inputs` says the version was built from."""
    if not isinstance(inputs, dict):
        return None
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == STORY_BIBLE_KIND:
            return artifact
    return None


def _out_of_date_reasons(row: GraphicTheme, bible: Any) -> list[str]:
    """Why a version is no longer current, one sentence each."""
    if provenance.same_row(_recorded_bible(row.inputs), bible):
        return []
    return ["The Story Bible was written again since this graphics look was made."]


@dataclass(frozen=True)
class GraphicThemeState:
    """What the board panel shows."""

    latest: GraphicTheme | None
    versions: list[GraphicTheme]
    # The newest job, whatever its status.
    job: Job | None
    out_of_date: bool
    reasons: list[str]
    # Why no theme can be written yet (or at all for this project), or None.
    blocked_reason: str | None
    # Whether the project has a graphics theme at all (a continuous explainer with graphics on).
    wanted: bool


@memoized_state
async def state(session: AsyncSession, project: Project) -> GraphicThemeState:
    """The project's graphics theme with where it stands. Worked out on every read; nothing
    here is stored.
    """
    newest = await latest(session, project.id)
    versions = await list_versions(session, project.id)
    job = await store.latest_job(session, project.id, JOB_TYPE)
    bible = await story_bible.latest(session, project.id)
    reasons = _out_of_date_reasons(newest, bible) if newest is not None and wanted(project) else []
    return GraphicThemeState(
        latest=newest,
        versions=versions,
        job=job,
        out_of_date=bool(reasons),
        reasons=reasons,
        blocked_reason=blocked_reason(project, bible),
        wanted=wanted(project),
    )
