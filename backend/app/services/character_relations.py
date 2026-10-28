"""The relations between a story project's characters (PHASE-047).

A relation says what one discovered character is to another (`services/character_relation_writer.py`
explains the kinds). The list of relations is a story artifact of its own, with the provenance
every artifact has (D-3, DATABASE_STRUCTURE.md Section 2.1): every run of the model, and every
edit by the user, is a new `character_relations` row with the next `version`, and a stored row is
never changed. `inputs` records the story hash and the StoryBible and character-list versions
the list was made from, so whether it is out of date is worked out when it is read and never
stored.

- `start_run` queues the `discover_relations` job. A project has at most one at a time. When the
  newest version was written by the user, the run replaces it only when the user confirmed.
- `save_manual` stores the user's edited list as the next version (`source` is `manual`).
- `save_version` is called by the job and flushes without committing.
- `state` is what the story workspace shows.
- The helpers at the end (`same_face_base`, `family_of`, `relations_text` and
  `entry_relations_sha256`) are what the definition and image stages read.

Relations belong to the project and name the discovered characters by their slug ids. They are
never written on a library character (D-14, amended by PHASE-047).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CharacterDiscovery, CharacterRelations, Job, Project, StoryBible
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import character_relation_writer as writer
from app.services import discovery, provenance, story_bible

JOB_TYPE: Final = "discover_relations"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"
BIBLE_KIND: Final = "story_bible"
CHARACTER_DISCOVERY_KIND: Final = "character_discovery"
RELATIONS_KIND: Final = "character_relations"

# Relations need two characters to be between.
MIN_CHARACTERS: Final = 2


class CharacterRelationError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class RelationsState:
    """What the story workspace shows. `version` is None when the project has no list yet."""

    # The version of the newest list of characters, or None when there is none.
    discovery_version: int | None
    # That list's items, `{id, name, description}`.
    characters: list[dict[str, Any]]
    version: CharacterRelations | None
    # The relations of the newest version whose two characters are both in the newest list,
    # and the ones that name a character that is no longer in it.
    relations: list[dict[str, str]]
    dropped: list[dict[str, str]]
    # Why the newest version is out of date, one sentence each.
    reasons: list[str]
    # The newest `discover_relations` job, whatever its status.
    job: Job | None
    can_run: bool
    blocked_reason: str | None
    # True when running again replaces a list the user wrote, so the user is asked first.
    needs_confirmation: bool


# --- Reading the inputs -------------------------------------------------------------------


def _blocked_reason(
    story: str | None,
    bible: StoryBible | None,
    newest: CharacterDiscovery | None,
) -> str | None:
    """Why relations cannot be found or saved now, or None when they can."""
    if story is None or not story.strip():
        return "Save the story first: the relations are found in the story."
    if bible is None:
        return "Run the Story Bible first: the relations are found with its help."
    if story_bible.is_out_of_date(story, bible):
        return (
            "The Story Bible is out of date, because the story has changed since it was "
            "written. Re-run the Story Bible first, then find the relations."
        )
    if newest is None:
        return "Find the characters first: relations are between the story's characters."
    if len(newest.content["characters"]) < MIN_CHARACTERS:
        return "The story has only one character, so there is nothing to relate."
    if discovery.is_out_of_date(story, newest, bible.version):
        return (
            "The list of characters is out of date. Find the characters again first, then "
            "find the relations."
        )
    return None


async def latest(session: AsyncSession, project_id: int) -> CharacterRelations | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(CharacterRelations)
        .where(CharacterRelations.project_id == project_id)
        .order_by(CharacterRelations.version.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def _require_inputs(
    session: AsyncSession, project: Project
) -> tuple[str, StoryBible, CharacterDiscovery]:
    """The saved story, its up-to-date StoryBible and the newest list of characters. Raises
    CharacterRelationError.
    """
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    newest = await discovery.latest(session, "characters", project.id)
    assert newest is None or isinstance(newest, CharacterDiscovery)
    reason = _blocked_reason(story, bible, newest)
    if reason is not None or story is None or bible is None or newest is None:
        raise CharacterRelationError(reason or "There is nothing to find relations in.")
    return story, bible, newest


def _inputs(story: str, bible: StoryBible, newest: CharacterDiscovery) -> dict[str, Any]:
    """The D-3 provenance of a version made from these."""
    return {
        "story_sha256": story_bible.story_sha256(story),
        "artifacts": [
            {"kind": BIBLE_KIND, "id": bible.id, "version": bible.version},
            {"kind": CHARACTER_DISCOVERY_KIND, "id": newest.id, "version": newest.version},
        ],
    }


# --- Starting a run, saving a version -----------------------------------------------------


async def start_run(
    session: AsyncSession, project: Project, *, confirm_replace_manual: bool = False
) -> Job:
    """Queues the job that finds the relations, and commits. If one is already waiting or
    running for the project, that job is returned and no new one is made (two quick clicks make
    one paid call).

    When the newest version is one the user wrote, it is replaced only when
    `confirm_replace_manual` is true. Raises CharacterRelationError.
    """
    story, bible, newest = await _require_inputs(session, project)
    current = await latest(session, project.id)
    if current is not None and current.source == SOURCE_MANUAL and not confirm_replace_manual:
        raise CharacterRelationError(
            "The newest relations were written by you. Finding them again adds a new version "
            "from the model, so it has to be confirmed."
        )
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "story_text": story,
            "story_sha256": story_bible.story_sha256(story),
            "story_bible_id": bible.id,
            "story_bible_version": bible.version,
            "discovery_id": newest.id,
            "discovery_version": newest.version,
        },
    )
    return job


async def _add_version(
    session: AsyncSession,
    project_id: int,
    *,
    source: str,
    job_id: int | None,
    inputs: dict[str, Any],
    relations: list[dict[str, str]],
) -> CharacterRelations:
    statement = select(func.max(CharacterRelations.version)).where(
        CharacterRelations.project_id == project_id
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = CharacterRelations(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=source,
        job_id=job_id,
        inputs=inputs,
        content={"relations": relations},
    )
    session.add(row)
    await session.flush()
    return row


async def save_version(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    story_sha256: str,
    bible_id: int,
    bible_version: int,
    discovery_id: int,
    discovery_version: int,
    relations: list[dict[str, str]],
) -> CharacterRelations:
    """Adds the next version, made by the model (`source` is `ai`). Flushes but does not
    commit: the job commits it together with finishing itself, so a job is never "succeeded"
    without its result.
    """
    return await _add_version(
        session,
        project_id,
        source=SOURCE_AI,
        job_id=job_id,
        inputs={
            "story_sha256": story_sha256,
            "artifacts": [
                {"kind": BIBLE_KIND, "id": bible_id, "version": bible_version},
                {
                    "kind": CHARACTER_DISCOVERY_KIND,
                    "id": discovery_id,
                    "version": discovery_version,
                },
            ],
        },
        relations=relations,
    )


async def accept_as_is(session: AsyncSession, project: Project) -> CharacterRelations:
    """Keeps the newest relations as they are and records that they were made from the story,
    StoryBible and characters as they are now (PHASE-039). Raises CharacterRelationError.
    """
    newest = await latest(session, project.id)
    if newest is None:
        raise CharacterRelationError("There are no relations to accept.")
    return await save_manual(session, project, newest.content["relations"], accepting=newest)


async def save_manual(
    session: AsyncSession,
    project: Project,
    relations: list[dict[str, Any]],
    *,
    accepting: CharacterRelations | None = None,
) -> CharacterRelations:
    """Stores the user's whole edited list as the next version (`source` is `manual`), and
    commits. The list is checked the same way the model's answer is. With `accepting`
    (PHASE-039) it also records which version the user accepted as it is. Raises
    CharacterRelationError.
    """
    story, bible, newest = await _require_inputs(session, project)
    ids = {item["id"] for item in newest.content["characters"]}
    try:
        checked = writer.check_relations({"relations": relations}, ids)
    except ValueError as exc:
        raise CharacterRelationError(str(exc)) from exc
    row = await _add_version(
        session,
        project.id,
        source=SOURCE_MANUAL,
        job_id=None,
        inputs=_inputs(story, bible, newest),
        relations=checked["relations"],
    )
    if accepting is not None:
        row.inputs = provenance.accepted_inputs(row.inputs, accepting, row.content)
    await session.commit()
    return row


# --- Reading the state --------------------------------------------------------------------


def _recorded_version(inputs: dict[str, Any], kind: str) -> int | None:
    """The version of the artifact of this kind that `inputs` says the list read."""
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            version = artifact.get("version")
            return version if isinstance(version, int) else None
    return None


def _out_of_date_reasons(
    row: CharacterRelations,
    story: str | None,
    newest_bible_version: int | None,
    newest_discovery_version: int | None,
    dropped: list[dict[str, str]],
) -> list[str]:
    """Why the newest version is no longer current, one sentence each."""
    inputs = row.inputs if isinstance(row.inputs, dict) else {}
    reasons: list[str] = []
    if story is None or not story.strip():
        reasons.append("The story is now empty.")
    elif inputs.get("story_sha256") != story_bible.story_sha256(story):
        reasons.append("The story has changed since these relations were made.")
    recorded_bible = _recorded_version(inputs, BIBLE_KIND)
    if recorded_bible is None or (
        newest_bible_version is not None and newest_bible_version > recorded_bible
    ):
        reasons.append("The Story Bible has been written again since these relations were made.")
    recorded_list = _recorded_version(inputs, CHARACTER_DISCOVERY_KIND)
    if recorded_list is None or (
        newest_discovery_version is not None and newest_discovery_version > recorded_list
    ):
        reasons.append("The list of characters has been found again since these were made.")
    if dropped:
        reasons.append("Some relations name a character that is no longer in the list.")
    return reasons


def _split(
    row: CharacterRelations | None, ids: set[str]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """The version's relations that stand (both characters are in `ids`), and those that do
    not.
    """
    if row is None:
        return [], []
    standing: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for relation in row.content["relations"]:
        if relation["character"] in ids and relation["of"] in ids:
            standing.append(relation)
        else:
            dropped.append(relation)
    return standing, dropped


@memoized_state
async def state(session: AsyncSession, project: Project) -> RelationsState:
    """The newest list of characters with the newest relations and where they stand. Worked out
    on every read; nothing here is stored.
    """
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    newest = await discovery.latest(session, "characters", project.id)
    assert newest is None or isinstance(newest, CharacterDiscovery)
    characters: list[dict[str, Any]] = newest.content["characters"] if newest is not None else []
    row = await latest(session, project.id)
    standing, dropped = _split(row, {item["id"] for item in characters})
    job = await store.latest_job(session, project.id, JOB_TYPE)

    reasons = (
        _out_of_date_reasons(
            row,
            story,
            bible.version if bible is not None else None,
            newest.version if newest is not None else None,
            dropped,
        )
        if row is not None
        else []
    )
    blocked = _blocked_reason(story, bible, newest)
    if blocked is None and job is not None and job.status in store.ACTIVE_STATUSES:
        blocked = "The relations are already being found."
    return RelationsState(
        discovery_version=newest.version if newest is not None else None,
        characters=characters,
        version=row,
        relations=standing,
        dropped=dropped,
        reasons=reasons,
        job=job,
        can_run=blocked is None,
        blocked_reason=blocked,
        needs_confirmation=row is not None and row.source == SOURCE_MANUAL,
    )


# --- What the definition and image stages read --------------------------------------------
#
# Each takes a list of relations as `state(...).relations` gives it: only relations between
# characters that are in the newest list.


def same_face_base(relations: list[dict[str, str]], character_id: str) -> dict[str, str] | None:
    """The relation that makes this character a same-face variant (`younger_self`,
    `older_self` or `twin`) of another, whose `of` is the base. None when it is not a variant.
    """
    for relation in relations:
        if relation["character"] == character_id and relation["kind"] in writer.SAME_FACE_KINDS:
            return relation
    return None


def is_base(relations: list[dict[str, str]], character_id: str) -> bool:
    """Whether another character is a same-face variant of this one."""
    return any(
        relation["of"] == character_id and relation["kind"] in writer.SAME_FACE_KINDS
        for relation in relations
    )


def family_of(relations: list[dict[str, str]], character_id: str) -> list[dict[str, str]]:
    """The family relations (`parent`, `sibling`, `grandparent`) this character is in, as
    stored.
    """
    return [
        relation
        for relation in relations
        if relation["kind"] in writer.FAMILY_KINDS
        and character_id in (relation["character"], relation["of"])
    ]


def relation_to(relations: list[dict[str, str]], this_id: str, other_id: str) -> str | None:
    """What `other_id` is to `this_id`, in words (for example "the older self of this
    character"), or None when they are not related.
    """
    for relation in relations:
        if relation["character"] == other_id and relation["of"] == this_id:
            return f"{writer.KIND_TEXT[relation['kind']]} this character"
        if relation["character"] == this_id and relation["of"] == other_id:
            return f"{writer.REVERSE_KIND_TEXT[relation['kind']]} this character"
    return None


def entry_relations_sha256(relations: list[dict[str, str]], character_id: str) -> str:
    """A name for the relations this character is in. A character in none has the hash of the
    empty list, which is also what a version made before relations existed counts as.
    """
    mine = sorted(
        (relation["character"], relation["kind"], relation["of"])
        for relation in relations
        if character_id in (relation["character"], relation["of"])
    )
    return hashlib.sha256(json.dumps(mine).encode("utf-8")).hexdigest()


EMPTY_RELATIONS_SHA256: Final = entry_relations_sha256([], "")


def relations_artifact(row: CharacterRelations | None) -> dict[str, Any] | None:
    """The `inputs.artifacts` entry that names the relations version a stage read, or None when
    the project has no relations.
    """
    if row is None:
        return None
    return {"kind": RELATIONS_KIND, "id": row.id, "version": row.version}
