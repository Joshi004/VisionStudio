"""The look and environment-state resolution of a story project (PHASE-016, `Path_ahead.md`
Sections 14 and 16).

Scene definitions ask for looks and environment states in their own words (PHASE-014). After
**all** scenes are defined, one `resolve_looks_states` job per project settles every request: it
maps each to `default` (the canonical look or reference), to a named look or state that already
exists in the library, or to one new entry that equivalent requests share, so no picture is made
twice (`services/look_state_resolution_writer.py`).

- A **named look** (`CharacterNamedLook`) belongs to a library character and an **environment
  state** (`EnvironmentState`) to a library environment. Both are library-wide: they belong to
  the library object and not to one of its versions, so any project that uses it can reuse
  them, and creating one adds no version and moves no pin. They hold no pictures yet; PHASE-017
  makes them, adds the version and moves the pin.
- The resolution itself is a project artifact (D-3): one immutable `look_state_resolution` row
  per run, numbered per project, recording what it was built from.
- A resolution can only be run when everything it reads is ready: the saved story, an
  up-to-date StoryBible and list of scenes, and **every** scene defined and current. The reason
  says what is missing.
- `start_run` queues the job. A project has at most one at a time. Running again is always
  allowed; with nothing changed, the model sees the records the earlier run created and reuses
  them, so nothing new is made.
- `state` is what the story workspace shows. **Out of date is worked out on every read** and
  never stored: the story, the StoryBible or the list of scenes changed, a scene was defined
  again or added, or a character or environment is linked to another library object.
- `save_resolution` is called by the job and flushes without committing; the job commits it
  together with finishing itself.
- `resolved_for_scene` is what later phases read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CharacterNamedLook,
    EnvironmentState,
    Job,
    LookStateResolution,
    Project,
    SceneDiscovery,
    StoryBible,
)
from app.jobs import store
from app.services import (
    character_definitions,
    discovery,
    environment_definitions,
    scene_definitions,
    story_bible,
)
from app.services import look_state_resolution_writer as writer

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "resolve_looks_states"
SOURCE_AI: Final = "ai"

STORY_BIBLE_KIND: Final = "story_bible"
SCENE_DISCOVERY_KIND: Final = "scene_discovery"
SCENE_DEFINITION_KIND: Final = "scene_definition"
CHARACTER_KIND: Final = "character"
ENVIRONMENT_KIND: Final = "environment"

_STATUS_WORDS: Final = {"not_defined": "not defined", "out_of_date": "out of date"}


class LookStateResolutionError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class _Subject:
    """A discovered character or environment that is linked, as it stands now."""

    kind: str  # CHARACTER_KIND or ENVIRONMENT_KIND
    discovery_id: str
    name: str
    library_id: int
    # What the subject looks like by default, from the pinned version's profile.
    default: str


@dataclass(frozen=True)
class _Loaded:
    """Everything a run or a read of the state needs, loaded once."""

    story: str | None
    bible: StoryBible | None
    scenes: SceneDiscovery | None
    scene_entries: list[scene_definitions.SceneEntry]
    characters: dict[str, _Subject]
    environments: dict[str, _Subject]
    blocked_reason: str | None


@dataclass(frozen=True)
class ResolvedItem:
    """One request of a scene and what it resolved to. `how` is `default`, `reuse` or `new`;
    `id`, `name` and `description` are None for `default`.
    """

    subject_id: str
    subject_name: str
    request: str
    how: str
    id: str | None
    name: str | None
    description: str | None


@dataclass(frozen=True)
class SceneResolution:
    """One scene of the newest list of scenes and what its requests resolved to."""

    scene_id: str
    index: int
    title: str
    # Whether the newest version has this scene at all.
    resolved: bool
    # Whether the newest version was made from this scene's newest definition.
    current: bool
    environment: ResolvedItem | None
    looks: list[ResolvedItem]


@dataclass(frozen=True)
class ResolutionState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    version: LookStateResolution | None
    scenes: list[SceneResolution]
    # Why the newest version is out of date, one sentence each.
    reasons: list[str]
    # The newest `resolve_looks_states` job, whatever its status.
    job: Job | None
    can_run: bool
    blocked_reason: str | None


# --- Loading ------------------------------------------------------------------------------


def _blocked_reason(
    story: str | None,
    bible: StoryBible | None,
    scenes: SceneDiscovery | None,
    entries: list[scene_definitions.SceneEntry],
) -> str | None:
    """Why the looks and states cannot be resolved now, or None when they can."""
    if story is None or not story.strip():
        return "Save the story first: the looks and states are resolved from its scenes."
    if bible is None:
        return "Run the Story Bible first: the scenes are defined with its help."
    if story_bible.is_out_of_date(story, bible):
        return (
            "The Story Bible is out of date, because the story has changed since it was "
            "written. Re-run the Story Bible first, then define the scenes again."
        )
    if scenes is None:
        return "Find the scenes first: the looks and states are resolved from them."
    if discovery.is_out_of_date(story, scenes, bible.version):
        return (
            "The scenes are out of date, because the story or the Story Bible has changed since "
            "they were found. Find the scenes again first."
        )
    if not entries:
        return "The story has no scenes."
    not_ready = [
        f"{entry.item['title']} ({_STATUS_WORDS.get(entry.status, entry.status)})"
        for entry in entries
        if entry.status != "defined"
    ]
    if not_ready:
        return (
            "Every scene has to be defined first, because the looks and states are resolved "
            f"across all of them. Not ready: {', '.join(not_ready)}."
        )
    return None


def _default_look(profile: dict[str, Any]) -> str:
    outfit = profile.get("outfit")
    return outfit.strip() if isinstance(outfit, str) else ""


def _default_state(profile: dict[str, Any]) -> str:
    parts = [profile.get("description"), profile.get("atmosphere")]
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


async def _load(session: AsyncSession, project: Project) -> _Loaded:
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    scenes = cast(SceneDiscovery | None, await discovery.latest(session, "scenes", project.id))
    entries = (await scene_definitions.state(session, project)).entries

    characters: dict[str, _Subject] = {}
    for entry in (await character_definitions.state(session, project)).entries:
        if entry.entry.info is None:
            continue
        profile = entry.version.profile if entry.version is not None else {}
        characters[entry.item["id"]] = _Subject(
            kind=CHARACTER_KIND,
            discovery_id=entry.item["id"],
            name=entry.item["name"],
            library_id=entry.entry.info.link.character_id,
            default=_default_look(profile),
        )
    environments: dict[str, _Subject] = {}
    for env_entry in (await environment_definitions.state(session, project)).entries:
        if env_entry.entry.info is None:
            continue
        env_profile = env_entry.version.profile if env_entry.version is not None else {}
        environments[env_entry.item["id"]] = _Subject(
            kind=ENVIRONMENT_KIND,
            discovery_id=env_entry.item["id"],
            name=env_entry.item["name"],
            library_id=env_entry.entry.info.link.environment_id,
            default=_default_state(env_profile),
        )
    return _Loaded(
        story=story,
        bible=bible,
        scenes=scenes,
        scene_entries=entries,
        characters=characters,
        environments=environments,
        blocked_reason=_blocked_reason(story, bible, scenes, entries),
    )


def _scene_inputs(loaded: _Loaded) -> list[dict[str, Any]]:
    """The scenes in story order, each with its definition, as `collect_requests` takes them."""
    return [
        {
            "scene_id": entry.item["id"],
            "index": entry.item["index"],
            "title": entry.item["title"],
            "definition": entry.definition,
        }
        for entry in loaded.scene_entries
        if entry.definition is not None
    ]


async def _catalog(
    session: AsyncSession,
    loaded: _Loaded,
    requests: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """The catalog the model is shown: for each character and environment that has a request,
    its default and the named looks or states it already has. Each subject also carries its
    `library_id`, and each named entry its `record_id`; the model is not shown those.
    """
    looks: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    for kind, subjects, target in (
        (writer.LOOK, loaded.characters, looks),
        (writer.STATE, loaded.environments, states),
    ):
        wanted = list(dict.fromkeys(r["subject_id"] for r in requests if r["kind"] == kind))
        for subject_id in wanted:
            subject = subjects.get(subject_id)
            if subject is None:
                raise LookStateResolutionError(
                    f"'{subject_id}' is not linked to a library "
                    f"{'character' if kind == writer.LOOK else 'environment'} yet. Link it first."
                )
            target.append(
                {
                    "subject_id": subject_id,
                    "name": subject.name,
                    "library_id": subject.library_id,
                    "default": subject.default,
                    "named": await _named_records(session, kind, subject.library_id),
                }
            )
    return {"looks": looks, "states": states}


async def _named_records(session: AsyncSession, kind: str, library_id: int) -> list[dict[str, Any]]:
    """The named looks of a library character, or the states of a library environment, oldest
    first.
    """
    if kind == writer.LOOK:
        look_rows = (
            await session.execute(
                select(CharacterNamedLook)
                .where(CharacterNamedLook.character_id == library_id)
                .order_by(CharacterNamedLook.id)
            )
        ).scalars()
        return [
            {"id": r.slug, "record_id": r.id, "name": r.name, "description": r.description}
            for r in look_rows
        ]
    state_rows = (
        await session.execute(
            select(EnvironmentState)
            .where(EnvironmentState.environment_id == library_id)
            .order_by(EnvironmentState.id)
        )
    ).scalars()
    return [
        {"id": r.slug, "record_id": r.id, "name": r.name, "description": r.description}
        for r in state_rows
    ]


# --- Starting a run, saving a version -----------------------------------------------------


def _inputs(
    loaded: _Loaded,
    plan: list[dict[str, Any]],
    story: str,
    bible: StoryBible,
    scenes: SceneDiscovery,
) -> dict[str, Any]:
    """The D-3 provenance of a version made from this state: the story hash, the StoryBible, the
    list of scenes, the definition of every scene, and the library character or environment
    each character and environment the scenes use is linked to.
    """
    artifacts: list[dict[str, Any]] = [
        {"kind": STORY_BIBLE_KIND, "id": bible.id, "version": bible.version},
        {"kind": SCENE_DISCOVERY_KIND, "id": scenes.id, "version": scenes.version},
    ]
    for entry in loaded.scene_entries:
        if entry.row is not None:
            artifacts.append(
                {
                    "kind": SCENE_DEFINITION_KIND,
                    "id": entry.row.id,
                    "version": entry.row.version,
                    "scene_id": entry.item["id"],
                }
            )
    characters = dict.fromkeys(look["subject_id"] for item in plan for look in item["looks"])
    environments = dict.fromkeys(item["environment"]["subject_id"] for item in plan)
    for kind, ids, subjects in (
        (CHARACTER_KIND, characters, loaded.characters),
        (ENVIRONMENT_KIND, environments, loaded.environments),
    ):
        for discovery_id in ids:
            subject = subjects[discovery_id]
            artifacts.append(
                {
                    "kind": kind,
                    "id": subject.library_id,
                    "discovery_id": discovery_id,
                    "name": subject.name,
                }
            )
    return {"story_sha256": story_bible.story_sha256(story), "artifacts": artifacts}


async def start_run(session: AsyncSession, project: Project) -> Job:
    """Queues the job that resolves the looks and states, and commits. If one is already
    waiting or running for the project, that job is returned and no new one is made (two quick
    clicks make one paid call). Raises LookStateResolutionError.
    """
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise LookStateResolutionError(loaded.blocked_reason)
    story, bible, scenes = loaded.story, loaded.bible, loaded.scenes
    assert story is not None and bible is not None and scenes is not None  # blocked otherwise

    plan, requests = writer.collect_requests(_scene_inputs(loaded))
    for item in plan:
        for subject_id, subjects, word in [
            (item["environment"]["subject_id"], loaded.environments, "environment"),
            *((look["subject_id"], loaded.characters, "character") for look in item["looks"]),
        ]:
            if subject_id not in subjects:
                raise LookStateResolutionError(
                    f"'{subject_id}' is not linked to a library {word} yet. Link it first."
                )
    catalog = await _catalog(session, loaded, requests)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "story_bible_id": bible.id,
            "story_bible_version": bible.version,
            "plan": plan,
            "requests": requests,
            "catalog": catalog,
            # Written onto the version the job makes (D-3).
            "inputs": _inputs(loaded, plan, story, bible, scenes),
        },
    )
    return job


async def save_resolution(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    inputs: dict[str, Any],
    plan: list[dict[str, Any]],
    catalog: dict[str, list[dict[str, Any]]],
    checked: dict[str, Any],
) -> LookStateResolution:
    """Creates the new named looks and states of a checked answer and adds the project's next
    version of the resolution. Flushes but does not commit: the job commits it together with
    finishing itself, so a job is never "succeeded" without its result. Raises
    LookStateResolutionError when a new id was taken in the meantime.
    """
    record_ids: dict[tuple[str, str, str], int] = {}
    library_ids: dict[tuple[str, str], int] = {}
    for kind, key in ((writer.LOOK, "looks"), (writer.STATE, "states")):
        for subject in catalog[key]:
            library_ids[(kind, subject["subject_id"])] = subject["library_id"]
            for named in subject["named"]:
                record_ids[(kind, subject["subject_id"], named["id"])] = named["record_id"]

    for entry in checked["new_looks"]:
        library_id = library_ids[(writer.LOOK, entry["character_id"])]
        taken = await session.execute(
            select(CharacterNamedLook.id).where(
                CharacterNamedLook.character_id == library_id,
                CharacterNamedLook.slug == entry["id"],
            )
        )
        if taken.first() is not None:
            raise LookStateResolutionError(
                f"The look '{entry['id']}' was created for '{entry['character_id']}' while this "
                "ran. Resolve the looks and states again."
            )
        look = CharacterNamedLook(
            character_id=library_id,
            slug=entry["id"],
            name=entry["name"],
            description=entry["description"],
            source=SOURCE_AI,
            origin_project_id=project_id,
            job_id=job_id,
        )
        session.add(look)
        await session.flush()
        record_ids[(writer.LOOK, entry["character_id"], entry["id"])] = look.id
    for state_entry in checked["new_states"]:
        library_id = library_ids[(writer.STATE, state_entry["environment_id"])]
        taken = await session.execute(
            select(EnvironmentState.id).where(
                EnvironmentState.environment_id == library_id,
                EnvironmentState.slug == state_entry["id"],
            )
        )
        if taken.first() is not None:
            raise LookStateResolutionError(
                f"The state '{state_entry['id']}' was created for "
                f"'{state_entry['environment_id']}' while this ran. Resolve the looks and "
                "states again."
            )
        state = EnvironmentState(
            environment_id=library_id,
            slug=state_entry["id"],
            name=state_entry["name"],
            description=state_entry["description"],
            source=SOURCE_AI,
            origin_project_id=project_id,
            job_id=job_id,
        )
        session.add(state)
        await session.flush()
        record_ids[(writer.STATE, state_entry["environment_id"], state_entry["id"])] = state.id

    highest = (
        await session.execute(
            select(func.max(LookStateResolution.version)).where(
                LookStateResolution.project_id == project_id
            )
        )
    ).scalar_one_or_none()
    row = LookStateResolution(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=SOURCE_AI,
        job_id=job_id,
        inputs=inputs,
        content=writer.build_content(plan, checked, record_ids),
    )
    session.add(row)
    await session.flush()
    _logger.info(
        "job %d: looks and states resolved for project %d, version %d (%d new looks, %d new "
        "states)",
        job_id,
        project_id,
        row.version,
        len(checked["new_looks"]),
        len(checked["new_states"]),
    )
    return row


# --- Reading the state --------------------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> LookStateResolution | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(LookStateResolution)
        .where(LookStateResolution.project_id == project_id)
        .order_by(LookStateResolution.version.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def resolved_for_scene(
    session: AsyncSession, project_id: int, scene_id: str
) -> dict[str, Any] | None:
    """What the newest resolution says for one scene: `{"scene_id", "environment": {...},
    "looks": [...]}` as stored, or None when the project has no resolution or it does not
    cover the scene. It does not say whether the version is out of date; `state` does.
    """
    row = await latest(session, project_id)
    if row is None:
        return None
    for scene in row.content["scenes"]:
        if scene["scene_id"] == scene_id:
            return cast(dict[str, Any], scene)
    return None


def _recorded_version(inputs: dict[str, Any], kind: str) -> int | None:
    """The version of the artifact of this kind that `inputs` says the resolution read."""
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            version = artifact.get("version")
            return version if isinstance(version, int) else None
    return None


def _recorded_definitions(inputs: dict[str, Any]) -> dict[str, int]:
    """The version of each scene's definition the resolution read, by scene id."""
    recorded: dict[str, int] = {}
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == SCENE_DEFINITION_KIND:
            scene_id, version = artifact.get("scene_id"), artifact.get("version")
            if isinstance(scene_id, str) and isinstance(version, int):
                recorded[scene_id] = version
    return recorded


def _out_of_date_reasons(
    row: LookStateResolution, loaded: _Loaded, recorded: dict[str, int]
) -> list[str]:
    """Why the newest version is no longer current, one sentence each."""
    inputs = row.inputs if isinstance(row.inputs, dict) else {}
    reasons: list[str] = []
    story = loaded.story
    if story is None or not story.strip():
        reasons.append("The story is now empty.")
    elif inputs.get("story_sha256") != story_bible.story_sha256(story):
        reasons.append("The story has changed since the looks and states were resolved.")
    recorded_bible = _recorded_version(inputs, STORY_BIBLE_KIND)
    if recorded_bible is None or (
        loaded.bible is not None and loaded.bible.version > recorded_bible
    ):
        reasons.append("The Story Bible has been written again since they were resolved.")
    recorded_scenes = _recorded_version(inputs, SCENE_DISCOVERY_KIND)
    if recorded_scenes is None or (
        loaded.scenes is not None and loaded.scenes.version > recorded_scenes
    ):
        reasons.append("The scenes have been found again since they were resolved.")

    current_ids = {entry.item["id"] for entry in loaded.scene_entries}
    for entry in loaded.scene_entries:
        scene_id = entry.item["id"]
        title = entry.item["title"]
        if scene_id not in recorded:
            reasons.append(f"The scene '{title}' was not part of this resolution.")
        elif entry.row is None or entry.row.version != recorded[scene_id]:
            reasons.append(f"The scene '{title}' has been defined again since.")
    for scene_id in recorded:
        if scene_id not in current_ids:
            reasons.append(f"The scene '{scene_id}' is no longer in the list of scenes.")

    for artifact in inputs.get("artifacts") or []:
        if not isinstance(artifact, dict) or artifact.get("kind") not in (
            CHARACTER_KIND,
            ENVIRONMENT_KIND,
        ):
            continue
        is_character = artifact["kind"] == CHARACTER_KIND
        subjects = loaded.characters if is_character else loaded.environments
        subject = subjects.get(artifact.get("discovery_id", ""))
        name = artifact.get("name") or artifact.get("discovery_id")
        what = "character" if is_character else "environment"
        if subject is None or subject.library_id != artifact.get("id"):
            reasons.append(f"{name} is now linked to a different {what}, or not linked.")
    return reasons


async def _records(
    session: AsyncSession, content: dict[str, Any]
) -> tuple[dict[int, CharacterNamedLook], dict[int, EnvironmentState]]:
    """The named looks and states a version's content points at, by id."""
    look_ids = {
        look["look_id"]
        for scene in content["scenes"]
        for look in scene["looks"]
        if look["look_id"] is not None
    }
    state_ids = {
        scene["environment"]["state_id"]
        for scene in content["scenes"]
        if scene["environment"]["state_id"] is not None
    }
    looks: dict[int, CharacterNamedLook] = {}
    states: dict[int, EnvironmentState] = {}
    if look_ids:
        found = await session.execute(
            select(CharacterNamedLook).where(CharacterNamedLook.id.in_(look_ids))
        )
        looks = {record.id: record for record in found.scalars()}
    if state_ids:
        found_states = await session.execute(
            select(EnvironmentState).where(EnvironmentState.id.in_(state_ids))
        )
        states = {record.id: record for record in found_states.scalars()}
    return looks, states


def _item(
    subject: _Subject | None,
    subject_id: str,
    request: str,
    how: str,
    slug: str | None,
    record: CharacterNamedLook | EnvironmentState | None,
) -> ResolvedItem:
    return ResolvedItem(
        subject_id=subject_id,
        subject_name=subject.name if subject is not None else subject_id,
        request=request,
        how=how,
        id=slug,
        name=record.name if record is not None else None,
        description=record.description if record is not None else None,
    )


async def state(session: AsyncSession, project: Project) -> ResolutionState:
    """The newest list of scenes with what the newest resolution says for each. Worked out on
    every read; nothing here is stored.
    """
    loaded = await _load(session, project)
    row = await latest(session, project.id)
    job = await store.latest_job(session, project.id, JOB_TYPE)

    recorded: dict[str, int] = {}
    stored: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    looks: dict[int, CharacterNamedLook] = {}
    states: dict[int, EnvironmentState] = {}
    if row is not None and isinstance(row.inputs, dict):
        recorded = _recorded_definitions(row.inputs)
        stored = {scene["scene_id"]: scene for scene in row.content["scenes"]}
        reasons = _out_of_date_reasons(row, loaded, recorded)
        looks, states = await _records(session, row.content)

    scenes: list[SceneResolution] = []
    for entry in loaded.scene_entries:
        scene_id = entry.item["id"]
        content = stored.get(scene_id)
        environment: ResolvedItem | None = None
        resolved_looks: list[ResolvedItem] = []
        if content is not None:
            env = content["environment"]
            environment = _item(
                loaded.environments.get(env["discovery_id"]),
                env["discovery_id"],
                env["request"],
                env["how"],
                env["state"],
                states.get(env["state_id"]) if env["state_id"] is not None else None,
            )
            resolved_looks = [
                _item(
                    loaded.characters.get(look["character_id"]),
                    look["character_id"],
                    look["request"],
                    look["how"],
                    look["look"],
                    looks.get(look["look_id"]) if look["look_id"] is not None else None,
                )
                for look in content["looks"]
            ]
        scenes.append(
            SceneResolution(
                scene_id=scene_id,
                index=entry.item["index"],
                title=entry.item["title"],
                resolved=content is not None,
                current=(
                    content is not None
                    and entry.row is not None
                    and recorded.get(scene_id) == entry.row.version
                ),
                environment=environment,
                looks=resolved_looks,
            )
        )

    blocked = loaded.blocked_reason
    if blocked is None and job is not None and job.status in store.ACTIVE_STATUSES:
        blocked = "The looks and states are already being resolved."
    return ResolutionState(
        scenes_version=loaded.scenes.version if loaded.scenes is not None else None,
        version=row,
        scenes=scenes,
        reasons=reasons,
        job=job,
        can_run=blocked is None,
        blocked_reason=blocked,
    )
