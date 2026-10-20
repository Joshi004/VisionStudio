"""A story project's discovered characters, environments and scenes: starting the jobs that
find them, saving their versions, and reading them back (PHASE-005, PHASE-006).

The three kinds work the same way and differ only in their job type and their table, so one set
of functions serves all of them and takes the `kind` (`"characters"`, `"environments"` or
`"scenes"`). The three jobs read the same inputs (the saved story and its up-to-date StoryBible)
and do not wait for each other (D-15).

Every version is a new row and a stored row is never changed (the artifact provenance
convention, DATABASE_STRUCTURE.md Section 2.1). Each row records the SHA-256 of the exact story
it was made from and the StoryBible version it read (`inputs`), so whether it is out of date is
worked out when it is read (`is_out_of_date`) and never stored.

The request to the model is built in `services/discovery_writer.py` (characters and
environments) or `services/scene_discovery_writer.py` (scenes), and the jobs that make the call
and save the result are `jobs/discover_characters.py`, `jobs/discover_environments.py` and
`jobs/discover_scenes.py`. This module only creates the jobs and the rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CharacterDiscovery,
    EnvironmentDiscovery,
    Job,
    Project,
    SceneDiscovery,
    StoryBible,
)
from app.jobs import store
from app.services import story_bible

SOURCE_AI: Final = "ai"
BIBLE_KIND: Final = "story_bible"

# The three discovery stages. `services/discovery_writer.Kind` is the two of them whose answer
# is a list of `{id, name, description}`; scenes have their own writer.
StageKind = Literal["characters", "environments", "scenes"]

Discovery = CharacterDiscovery | EnvironmentDiscovery | SceneDiscovery


@dataclass(frozen=True)
class KindSpec:
    """What differs between the kinds."""

    job_type: str
    model: type[Discovery]


SPECS: Final[dict[StageKind, KindSpec]] = {
    "characters": KindSpec(job_type="discover_characters", model=CharacterDiscovery),
    "environments": KindSpec(job_type="discover_environments", model=EnvironmentDiscovery),
    "scenes": KindSpec(job_type="discover_scenes", model=SceneDiscovery),
}


class DiscoveryError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


async def start_run(session: AsyncSession, project: Project, kind: StageKind) -> Job:
    """Queues the job that finds the project's characters (or environments, or scenes) from
    its saved story and its newest StoryBible, and commits.

    The story is copied onto the job (with its hash), and the StoryBible is named by id and
    version, so the version made is tied to what was current when the button was pressed. A
    StoryBible is needed, and it must be up to date with the saved story: a list made from an
    old bible would be out of date as soon as it was made. If a job of this kind is already
    waiting or running for the project, that job is returned and no new one is made (two quick
    clicks make one paid call). The two kinds have different job types, so one never waits for
    the other.
    """
    story = project.script_text
    if story is None or not story.strip():
        raise DiscoveryError(f"Save the story first: the {kind} are found in the story.")
    bible = await story_bible.latest(session, project.id)
    if bible is None:
        raise DiscoveryError(f"Run the Story Bible first: the {kind} are found with its help.")
    if story_bible.is_out_of_date(story, bible):
        raise DiscoveryError(
            "The Story Bible is out of date, because the story has changed since it was "
            f"written. Re-run the Story Bible first, then find the {kind}."
        )
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=SPECS[kind].job_type,
        provider="llm",
        input={
            "story_text": story,
            "story_sha256": story_bible.story_sha256(story),
            "story_bible_id": bible.id,
            "story_bible_version": bible.version,
        },
    )
    return job


async def get_bible(session: AsyncSession, project_id: int, bible_id: int) -> StoryBible | None:
    """The StoryBible row a job was started with, or None when it is not this project's."""
    bible = await session.get(StoryBible, bible_id)
    if bible is None or bible.project_id != project_id:
        return None
    return bible


async def latest(session: AsyncSession, kind: StageKind, project_id: int) -> Discovery | None:
    """The project's newest version, or None when it has none."""
    model = SPECS[kind].model
    statement = (
        select(model).where(model.project_id == project_id).order_by(model.version.desc()).limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def list_versions(session: AsyncSession, kind: StageKind, project_id: int) -> list[Discovery]:
    """Every version of the project, newest first."""
    model = SPECS[kind].model
    statement = select(model).where(model.project_id == project_id).order_by(model.version.desc())
    return list((await session.execute(statement)).scalars())


async def get_version(
    session: AsyncSession, kind: StageKind, project_id: int, version: int
) -> Discovery | None:
    """One version of the project, or None when there is no such version."""
    model = SPECS[kind].model
    statement = select(model).where(model.project_id == project_id, model.version == version)
    return (await session.execute(statement)).scalars().first()


async def save_version(
    session: AsyncSession,
    kind: StageKind,
    *,
    project_id: int,
    job_id: int,
    story_sha256: str,
    bible_id: int,
    bible_version: int,
    content: dict[str, Any],
) -> Discovery:
    """Adds the next version, made by the model (`source` is `ai`), recording the story hash
    and the StoryBible it was made from. Flushes but does not commit: the job commits it
    together with finishing itself, so a job is never "succeeded" without its result.
    """
    model = SPECS[kind].model
    statement = select(func.max(model.version)).where(model.project_id == project_id)
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = model(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=SOURCE_AI,
        job_id=job_id,
        inputs={
            "story_sha256": story_sha256,
            "artifacts": [{"kind": BIBLE_KIND, "id": bible_id, "version": bible_version}],
        },
        content=content,
    )
    session.add(row)
    await session.flush()
    return row


def recorded_bible_version(row: Discovery) -> int | None:
    """The StoryBible version the row was made from, or None when it does not say."""
    if not isinstance(row.inputs, dict):
        return None
    for artifact in row.inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == BIBLE_KIND:
            version = artifact.get("version")
            return version if isinstance(version, int) else None
    return None


def is_out_of_date(
    story_text: str | None, row: Discovery, newest_bible_version: int | None
) -> bool:
    """Whether the story is no longer the text this version was made from, or the project has a
    newer StoryBible than the one it read. Worked out on every read. A story that is now empty
    counts as out of date.
    """
    if story_text is None or not story_text.strip():
        return True
    recorded_story = row.inputs.get("story_sha256") if isinstance(row.inputs, dict) else None
    if recorded_story != story_bible.story_sha256(story_text):
        return True
    recorded_bible = recorded_bible_version(row)
    if recorded_bible is None:
        return True
    return newest_bible_version is not None and newest_bible_version > recorded_bible
