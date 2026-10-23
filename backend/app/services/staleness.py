"""What is out of date in a story project, in one place (PHASE-039).

Each stage works out its own `out_of_date` status and reasons on every read, from the provenance
its rows recorded (D-3), and passes staleness down by reading its upstream's status. This module
only **collects** them: it calls each stage's `state()` in the order of `story_pipeline.STEPS`,
keeps what is out of date and groups it by step. It stores nothing and decides nothing itself, so
the reasons functions stay the one source of truth.

`accept_as_is` is the one action: it keeps an artifact's content and records that it was made
from what is current now (the stage's `accept_as_is`). It starts no job and calls no model, and
whatever was made from the artifact stays as it is. Only the stages that already have a manual
edit can be accepted; for the others the answer is to make them again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, get_args

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project
from app.services import (
    character_definitions,
    character_images,
    character_relations,
    discovery,
    discovery_edits,
    environment_definitions,
    environment_views,
    generation_requests,
    look_state_images,
    look_state_resolution,
    project_cast,
    scene_definitions,
    scene_events,
    scene_staging,
    shot_definitions,
    shot_plans,
    shot_prompts,
    shot_references,
    shot_takes,
    speech_synthesis,
    speech_units,
    story_bible,
    story_pipeline,
    story_renders,
    story_voices,
)

AcceptStage = Literal[
    "story_bible",
    "character_discovery",
    "environment_discovery",
    "scene_discovery",
    "relations",
    "scene_definitions",
    "events",
    "scene_staging",
    "speech_units",
    "shot_plans",
    "shot_definitions",
    "references",
    "prompts",
]
ACCEPT_STAGES: Final = frozenset(get_args(AcceptStage))

_DISCOVERY_KINDS: Final[dict[str, discovery.StageKind]] = {
    "character_discovery": "characters",
    "environment_discovery": "environments",
    "scene_discovery": "scenes",
}

# Every error a stage's accept can raise. They are all `ValueError`s with a message for the user.
_STAGE_ERRORS: Final = (
    story_bible.StoryBibleError,
    discovery.DiscoveryError,
    character_relations.CharacterRelationError,
    scene_definitions.SceneDefinitionError,
    scene_events.SceneEventsError,
    scene_staging.SceneStagingError,
    speech_units.SpeechUnitsError,
    shot_plans.ShotPlansError,
    shot_definitions.ShotDefinitionsError,
    shot_references.ShotReferencesError,
    shot_prompts.ShotPromptsError,
)


class StalenessError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class Item:
    """One artifact that is out of date. The key fields say which one it is: `scene_id`,
    `shot_id`, `discovery_id` or `unit_id`, whichever the stage uses.
    """

    stage: str
    title: str
    reasons: list[str]
    acceptable: bool
    scene_id: str | None = None
    shot_id: str | None = None
    discovery_id: str | None = None
    unit_id: str | None = None


@dataclass(frozen=True)
class Group:
    """The out-of-date artifacts of one step of the story pipeline."""

    step: str
    label: str
    items: list[Item]


@dataclass(frozen=True)
class Overview:
    """Everything out of date in the project, by step, in the order of the pipeline."""

    groups: list[Group] = field(default_factory=list)

    @property
    def count(self) -> int:
        return sum(len(group.items) for group in self.groups)


# --- Titles -------------------------------------------------------------------------------


def _scene_title(item: dict[str, Any]) -> str:
    index = item.get("index")
    title = str(item.get("title", item.get("id", "")))
    return f"Scene {index}: {title}" if index is not None else title


def _shot_title(scene: dict[str, Any], shot: dict[str, Any]) -> str:
    number = str(shot["id"]).removeprefix("shot_")
    return f"{_scene_title(scene)}, shot {number}"


def _speaker(unit: dict[str, Any]) -> str:
    if unit.get("kind") == "narration":
        return "Narrator"
    return str(unit.get("speaker_id", "")).replace("_", " ").title()


# --- Collecting ---------------------------------------------------------------------------


class _Collected:
    """The items found so far, by step key."""

    def __init__(self) -> None:
        self.by_step: dict[str, list[Item]] = {}

    def add(self, step: str, item: Item) -> None:
        self.by_step.setdefault(step, []).append(item)

    def overview(self) -> Overview:
        return Overview(
            groups=[
                Group(step.key, step.label, self.by_step[step.key])
                for step in story_pipeline.STEPS
                if step.key in self.by_step
            ]
        )


def _list_reasons(
    story: str | None,
    row: discovery.Discovery,
    newest_bible_version: int | None,
    cast_sha256: str | None,
) -> list[str]:
    """Why a list of characters, environments or scenes is out of date, one sentence each."""
    inputs = row.inputs if isinstance(row.inputs, dict) else {}
    reasons: list[str] = []
    if story is None or not story.strip():
        return ["The story is empty."]
    if inputs.get("story_sha256") != story_bible.story_sha256(story):
        reasons.append("The story has changed since this list was found.")
    recorded = discovery.recorded_bible_version(row)
    if recorded is None or (newest_bible_version is not None and newest_bible_version > recorded):
        reasons.append("The Story Bible was written again since this list was found.")
    if cast_sha256 is not None:
        if inputs.get("cast_sha256", project_cast.EMPTY_CAST_SHA256) != cast_sha256:
            reasons.append("The library items of the project have changed since this list.")
    return reasons


async def _collect_roots(session: AsyncSession, project: Project, found: _Collected) -> None:
    """The Story Bible and the three lists. They are kept apart because these stages have no
    `state()`: each is a row and a comparison of hashes and versions.
    """
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    if bible is not None and story_bible.is_out_of_date(story, bible):
        found.add(
            "story_bible",
            Item(
                "story_bible",
                "Story Bible",
                ["The story has changed since the Story Bible was written."],
                acceptable=True,
            ),
        )
    newest_bible = bible.version if bible is not None else None
    for step, kind in _DISCOVERY_KINDS.items():
        row = await discovery.latest(session, kind, project.id)
        if row is None:
            continue
        cast = await discovery.current_cast_sha256(session, project.id, kind)
        if discovery.is_out_of_date(story, row, newest_bible, current_cast_sha256=cast):
            reasons = _list_reasons(story, row, newest_bible, cast)
            found.add(
                step,
                Item(
                    step,
                    f"The list of {kind}",
                    reasons or [f"The list of {kind} is out of date."],
                    acceptable=True,
                ),
            )


async def _collect_characters(session: AsyncSession, project: Project, found: _Collected) -> None:
    relations = await character_relations.state(session, project)
    if relations.version is not None and relations.reasons:
        found.add(
            "relations",
            Item("relations", "Character relations", relations.reasons, acceptable=True),
        )

    for entry in (await character_definitions.state(session, project)).entries:
        if entry.status == "out_of_date":
            found.add(
                "character_definitions",
                Item(
                    "character_definitions",
                    str(entry.item.get("name", entry.item["id"])),
                    entry.reasons,
                    acceptable=False,
                    discovery_id=entry.item["id"],
                ),
            )

    for definition in (await environment_definitions.state(session, project)).entries:
        if definition.status == "out_of_date":
            found.add(
                "environment_definitions",
                Item(
                    "environment_definitions",
                    str(definition.item.get("name", definition.item["id"])),
                    definition.reasons,
                    acceptable=False,
                    discovery_id=definition.item["id"],
                ),
            )

    for images in (await character_images.state(session, project)).entries:
        if images.status == "out_of_date":
            found.add(
                "character_images",
                Item(
                    "character_images",
                    str(images.definition.item.get("name", images.definition.item["id"])),
                    images.reasons,
                    acceptable=False,
                    discovery_id=images.definition.item["id"],
                ),
            )

    for voice in (await story_voices.state(session, project)).entries:
        if voice.status == "out_of_date":
            found.add(
                "voices",
                Item(
                    "voices",
                    str(voice.definition.item.get("name", voice.definition.item["id"])),
                    voice.reasons,
                    acceptable=False,
                    discovery_id=voice.definition.item["id"],
                ),
            )
    narrator = await story_voices.narrator_state(session, project)
    if narrator.status == "out_of_date":
        found.add("voices", Item("voices", "Narrator", narrator.reasons, acceptable=False))


async def _collect_scenes(session: AsyncSession, project: Project, found: _Collected) -> None:
    for definition in (await scene_definitions.state(session, project)).entries:
        if definition.status == "out_of_date":
            found.add(
                "scene_definitions",
                Item(
                    "scene_definitions",
                    _scene_title(definition.item),
                    definition.reasons,
                    acceptable=True,
                    scene_id=definition.item["id"],
                ),
            )

    for events in (await scene_events.state(session, project)).entries:
        if events.status == "out_of_date":
            found.add(
                "events",
                Item(
                    "events",
                    _scene_title(events.item),
                    events.reasons,
                    acceptable=True,
                    scene_id=events.item["id"],
                ),
            )

    for staging in (await scene_staging.state(session, project)).entries:
        if staging.status == "out_of_date":
            found.add(
                "scene_staging",
                Item(
                    "scene_staging",
                    _scene_title(staging.item),
                    staging.reasons,
                    acceptable=True,
                    scene_id=staging.item["id"],
                ),
            )

    for views in (await environment_views.state(session, project)).entries:
        reasons = [*views.reasons, *(reason for item in views.views for reason in item.reasons)]
        if views.status == "out_of_date" or reasons:
            found.add(
                "environment_views",
                Item(
                    "environment_views",
                    views.name,
                    reasons or ["The views of this place are out of date."],
                    acceptable=False,
                    discovery_id=views.discovery_id,
                ),
            )

    resolution = await look_state_resolution.state(session, project)
    if resolution.version is not None and resolution.reasons:
        found.add(
            "resolution",
            Item("resolution", "Looks and states", resolution.reasons, acceptable=False),
        )

    for picture in (await look_state_images.state(session, project)).items:
        if picture.reasons:
            found.add(
                "look_state_images",
                Item(
                    "look_state_images",
                    f"{picture.subject_name}: {picture.name}",
                    picture.reasons,
                    acceptable=False,
                    discovery_id=picture.subject_id,
                ),
            )

    for plan in (await speech_units.state(session, project)).entries:
        if plan.status == "out_of_date":
            found.add(
                "speech_units",
                Item(
                    "speech_units",
                    _scene_title(plan.item),
                    plan.reasons,
                    acceptable=True,
                    scene_id=plan.item["id"],
                ),
            )

    for scene in (await speech_synthesis.state(session, project)).scenes:
        for unit in scene.units:
            if unit.status == "out_of_date":
                found.add(
                    "speech_synthesis",
                    Item(
                        "speech_synthesis",
                        f"{_speaker(unit.unit)}, line {unit.unit['id']}",
                        unit.reasons,
                        acceptable=False,
                        scene_id=scene.scene.item["id"],
                        unit_id=unit.unit["id"],
                    ),
                )


async def _collect_shots(session: AsyncSession, project: Project, found: _Collected) -> None:
    for plan in (await shot_plans.state(session, project)).entries:
        if plan.status == "out_of_date":
            found.add(
                "shot_plans",
                Item(
                    "shot_plans",
                    _scene_title(plan.item),
                    plan.reasons,
                    acceptable=True,
                    scene_id=plan.item["id"],
                ),
            )

    def add_shots(step: str, scenes: Any, acceptable: bool) -> None:
        for scene in scenes:
            for shot in scene.shots:
                if shot.status == "out_of_date":
                    found.add(
                        step,
                        Item(
                            step,
                            _shot_title(scene.item, shot.shot),
                            shot.reasons,
                            acceptable=acceptable,
                            scene_id=scene.item["id"],
                            shot_id=shot.shot["id"],
                        ),
                    )

    add_shots("shot_definitions", (await shot_definitions.state(session, project)).entries, True)
    add_shots("references", (await shot_references.state(session, project)).entries, True)
    add_shots(
        "generation_requests",
        (await generation_requests.state(session, project)).entries,
        False,
    )
    add_shots("prompts", (await shot_prompts.state(session, project)).entries, True)
    add_shots("shot_generation", (await shot_takes.state(session, project)).entries, False)

    for render in (await story_renders.state(session, project)).renders:
        if render.status == "out_of_date":
            found.add(
                "render",
                Item(
                    "render",
                    f"Render {render.row.id}",
                    render.reasons,
                    acceptable=False,
                ),
            )


async def overview(session: AsyncSession, project: Project) -> Overview:
    """Everything out of date in the project, grouped by step in the order of the pipeline.
    Worked out on every read; nothing here is stored.
    """
    found = _Collected()
    await _collect_roots(session, project, found)
    await _collect_characters(session, project, found)
    await _collect_scenes(session, project, found)
    await _collect_shots(session, project, found)
    return found.overview()


# --- Accepting ----------------------------------------------------------------------------


def _same(item: Item, stage: str, scene_id: str | None, shot_id: str | None) -> bool:
    return item.stage == stage and item.scene_id == scene_id and item.shot_id == shot_id


async def accept_as_is(
    session: AsyncSession,
    project: Project,
    stage: AcceptStage,
    *,
    scene_id: str | None = None,
    shot_id: str | None = None,
) -> Overview:
    """Keeps one out-of-date artifact as it is and records that it was made from what is
    current now, then returns the new overview. It makes no job and calls no model.

    The artifact must be out of date now: accepting what is current does nothing but add a
    version. Raises StalenessError, with the stage's own reason when it refuses (for example
    when the stage before it is not ready yet: accept those first).
    """
    if stage not in ACCEPT_STAGES:
        raise StalenessError("This kind of artifact cannot be accepted as it is.")
    current = await overview(session, project)
    listed = any(
        _same(item, stage, scene_id, shot_id) for group in current.groups for item in group.items
    )
    if not listed:
        raise StalenessError("This is not out of date, so there is nothing to accept.")
    try:
        await _accept(session, project, stage, scene_id, shot_id)
    except _STAGE_ERRORS as exc:
        raise StalenessError(str(exc)) from exc
    return await overview(session, project)


def _need(value: str | None, what: str) -> str:
    if value is None:
        raise StalenessError(f"The {what} is needed.")
    return value


async def _accept(
    session: AsyncSession,
    project: Project,
    stage: AcceptStage,
    scene_id: str | None,
    shot_id: str | None,
) -> None:
    if stage == "story_bible":
        await story_bible.accept_as_is(session, project)
    elif stage in _DISCOVERY_KINDS:
        await discovery_edits.accept_as_is(session, project, _DISCOVERY_KINDS[stage])
    elif stage == "relations":
        await character_relations.accept_as_is(session, project)
    elif stage == "scene_definitions":
        await scene_definitions.accept_as_is(session, project, _need(scene_id, "scene"))
    elif stage == "events":
        await scene_events.accept_as_is(session, project, _need(scene_id, "scene"))
    elif stage == "scene_staging":
        await scene_staging.accept_as_is(session, project, _need(scene_id, "scene"))
    elif stage == "speech_units":
        await speech_units.accept_as_is(session, project, _need(scene_id, "scene"))
    elif stage == "shot_plans":
        await shot_plans.accept_as_is(session, project, _need(scene_id, "scene"))
    elif stage == "shot_definitions":
        await shot_definitions.accept_as_is(
            session, project, _need(scene_id, "scene"), _need(shot_id, "shot")
        )
    elif stage == "references":
        await shot_references.accept_as_is(
            session, project, _need(scene_id, "scene"), _need(shot_id, "shot")
        )
    else:
        await shot_prompts.accept_as_is(
            session, project, _need(scene_id, "scene"), _need(shot_id, "shot")
        )
