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

JOB_TYPE: Final = "write_story_bible"
SOURCE_AI: Final = "ai"


class StoryBibleError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


def story_sha256(story_text: str) -> str:
    """The SHA-256 (hex) of the story text exactly as it is stored."""
    return hashlib.sha256(story_text.encode("utf-8")).hexdigest()


async def start_run(session: AsyncSession, project: Project) -> Job:
    """Queues the job that writes the StoryBible from the project's saved story, and commits.

    The story is copied onto the job (with its hash), so the version made is tied to the text
    that was saved when the button was pressed, even if the story is edited while the job
    waits. If a job of this kind is already waiting or running for the project, that job is
    returned and no new one is made (two quick clicks make one paid call).
    """
    story = project.script_text
    if story is None or not story.strip():
        raise StoryBibleError("Save the story first: the Story Bible is made from the story.")
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
    statement = select(func.max(StoryBible.version)).where(StoryBible.project_id == project_id)
    highest = (await session.execute(statement)).scalar_one_or_none()
    bible = StoryBible(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=SOURCE_AI,
        job_id=job_id,
        inputs={"story_sha256": story_sha256, "artifacts": []},
        content=content,
    )
    session.add(bible)
    await session.flush()
    return bible


def is_out_of_date(story_text: str | None, bible: StoryBible) -> bool:
    """Whether the story is no longer the text this version was made from. Worked out on every
    read. A story that is now empty counts as out of date.
    """
    if story_text is None or not story_text.strip():
        return True
    recorded = bible.inputs.get("story_sha256") if isinstance(bible.inputs, dict) else None
    return recorded != story_sha256(story_text)
