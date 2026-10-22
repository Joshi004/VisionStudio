"""A story project's StoryBible: starting the job that writes it, saving its versions, and
reading them back (PHASE-004).

Every version is a new `story_bible` row and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). Each row records the SHA-256 of the
exact story text it was made from (`inputs.story_sha256`), so whether it is out of date is
worked out when it is read (`is_out_of_date`) and never stored.

The request to the model is built in `services/story_bible_writer.py`, and the job that makes
the call and saves the result is `jobs/write_story_bible.py`. This module only creates the job
and the rows.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, StoryBible
from app.jobs import store
from app.services import story_bible_writer

JOB_TYPE: Final = "write_story_bible"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"

MANUAL_REPLACE_MESSAGE: Final = (
    "The newest Story Bible was written by you. Running the model adds a new version from "
    "the model, so it has to be confirmed."
)


class StoryBibleError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


def story_sha256(story_text: str) -> str:
    """The SHA-256 (hex) of the story text exactly as it is stored."""
    return hashlib.sha256(story_text.encode("utf-8")).hexdigest()


async def start_run(
    session: AsyncSession, project: Project, *, confirm_replace_manual: bool = False
) -> Job:
    """Queues the job that writes the StoryBible from the project's saved story, and commits.

    The story is copied onto the job (with its hash), so the version made is tied to the text
    that was saved when the button was pressed, even if the story is edited while the job
    waits. If a job of this kind is already waiting or running for the project, that job is
    returned and no new one is made (two quick clicks make one paid call).

    When the newest version was written by the user, the run replaces it only when
    `confirm_replace_manual` is true (PHASE-037).
    """
    story = project.script_text
    if story is None or not story.strip():
        raise StoryBibleError("Save the story first: the Story Bible is made from the story.")
    newest = await latest(session, project.id)
    if newest is not None and newest.source == SOURCE_MANUAL and not confirm_replace_manual:
        raise StoryBibleError(MANUAL_REPLACE_MESSAGE)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={"story_text": story, "story_sha256": story_sha256(story)},
    )
    return job


async def latest(session: AsyncSession, project_id: int) -> StoryBible | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(StoryBible)
        .where(StoryBible.project_id == project_id)
        .order_by(StoryBible.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def list_versions(session: AsyncSession, project_id: int) -> list[StoryBible]:
    """Every version of the project, newest first."""
    statement = (
        select(StoryBible)
        .where(StoryBible.project_id == project_id)
        .order_by(StoryBible.version.desc())
    )
    return list((await session.execute(statement)).scalars())


async def get_version(session: AsyncSession, project_id: int, version: int) -> StoryBible | None:
    """One version of the project, or None when there is no such version."""
    statement = select(StoryBible).where(
        StoryBible.project_id == project_id, StoryBible.version == version
    )
    return (await session.execute(statement)).scalars().first()


async def save_version(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    story_sha256: str,
    content: dict[str, Any],
) -> StoryBible:
    """Adds the next version, made by the model (`source` is `ai`). Flushes but does not
    commit: the job commits it together with finishing itself, so a job is never "succeeded"
    without its result.
    """
    return await _add_version(
        session,
        project_id,
        source=SOURCE_AI,
        job_id=job_id,
        story_sha256=story_sha256,
        content=content,
    )


async def _add_version(
    session: AsyncSession,
    project_id: int,
    *,
    source: str,
    job_id: int | None,
    story_sha256: str,
    content: dict[str, Any],
) -> StoryBible:
    statement = select(func.max(StoryBible.version)).where(StoryBible.project_id == project_id)
    highest = (await session.execute(statement)).scalar_one_or_none()
    bible = StoryBible(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=source,
        job_id=job_id,
        inputs={"story_sha256": story_sha256, "artifacts": []},
        content=content,
    )
    session.add(bible)
    await session.flush()
    return bible


async def save_manual(
    session: AsyncSession, project: Project, content: dict[str, Any]
) -> StoryBible:
    """Stores the user's edited StoryBible as the next version (`source` is `manual`), and
    commits (PHASE-037). The content is checked the way the model's answer is
    (`story_bible_writer.check_bible`), so `language` stays `en` and the limits hold. The
    version records the hash of the story as saved now. Raises StoryBibleError.
    """
    story = project.script_text
    if story is None or not story.strip():
        raise StoryBibleError("Save the story first: the Story Bible is made from the story.")
    job = await store.latest_job(session, project.id, JOB_TYPE)
    if job is not None and job.status in store.ACTIVE_STATUSES:
        raise StoryBibleError("The Story Bible is being written. Wait for it to finish first.")
    try:
        checked = story_bible_writer.check_bible(content)
    except ValueError as exc:
        raise StoryBibleError(str(exc)) from exc
    bible = await _add_version(
        session,
        project.id,
        source=SOURCE_MANUAL,
        job_id=None,
        story_sha256=story_sha256(story),
        content=checked,
    )
    await session.commit()
    return bible


def is_out_of_date(story_text: str | None, bible: StoryBible) -> bool:
    """Whether the story is no longer the text this version was made from. Worked out on every
    read. A story that is now empty counts as out of date.
    """
    if story_text is None or not story_text.strip():
        return True
    recorded = bible.inputs.get("story_sha256") if isinstance(bible.inputs, dict) else None
    return recorded != story_sha256(story_text)
