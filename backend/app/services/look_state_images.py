"""The pictures of the new looks and environment states of a story project (PHASE-017,
`Path_ahead.md` Sections 12 and 14).

PHASE-016 resolved every look and environment state the scenes asked for to `default` (the
canonical look or picture), to a named look or state that already existed, or to a new one. This
stage makes the pictures of the named ones, once each, by **editing the canonical picture**, so
the face or the layout stays fixed and only the wardrobe or the condition changes. The words of
the edit come from a template in code (`look_state_edit_prompts`): no language model and no job
type of its own are involved, only the Character lab's own picture jobs.

- A **look** is `character_looks.start_look(named_look_id=..., prompt=...)`: one candidate that
  is an edit of the front picture of the character's pinned version (D-5, so nobody chooses),
  then the four other angles. When the five pictures exist the named look points at the look
  and the character gets a new `ai` version that freezes them; the project's pin moves to it
  (`character_looks._finish_named_look`). The character's current look is never changed.
- A **state** is one edit run of the pinned environment version's canonical picture at 16:9.
  When the picture is stored (`on_state_image_stored`, called by the image job) it becomes the
  state's picture, and the environment gets a new `ai` version that freezes it, carrying the
  canonical picture forward, and the pin moves to it.
- Named looks and states belong to the library object, not to a project, so one that another
  project already made is `ready` here too and is not made again. The pin of this project holds
  such a picture only once this project makes or remakes one itself (a known limit).
- `state` is what the story workspace shows. **Everything is worked out on every read** and
  never stored (D-3): the status comes from the look or the run and its job.
- `start_look_record`, `start_state_record` and `start_all` start the pictures. A record that
  is being made or already has its pictures is not made again. A failed one is made again by
  pressing the button, which starts a fresh attempt.

A look needs the character's canonical images to be `ready`. A state needs the environment to
be defined, its pinned version to hold a picture, and that version to be the newest one: the
version written for the state is made from the environment as it is now, and would otherwise
lose the canonical picture to a newer version made in the lab.

This module creates rows and jobs. It never calls the GPU server or the language model itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import (
    CharacterLook,
    CharacterNamedLook,
    EnvironmentState,
    EnvironmentView,
    EnvironmentViewState,
    LabImage,
    LabRun,
    LibraryEnvironment,
    Project,
    ProjectEnvironmentLink,
)
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.jobs import store
from app.services import (
    character_images,
    character_looks,
    environment_definitions,
    environment_references,
    environment_versions,
    environment_views,
    image_lab,
    library_adoption,
    look_state_resolution,
)
from app.services import image_models as image_models_service
from app.services import look_state_edit_prompts as prompts
from app.services.character_images import FailedAngle
from app.services.image_lab import LabInputError, QwenEditForm, Ref
from app.services.image_models import IMAGE_MODE_KEY

_logger = logging.getLogger(__name__)

LOOK: Final = "look"
STATE: Final = "state"
VIEW_STATE: Final = "view_state"

# The statuses of a job that will not produce a picture any more.
_DEAD_JOB_STATUSES: Final = ("failed", "cancelled")
_NO_RESOLUTION: Final = (
    "Resolve the looks and states first: pictures are made for the ones it names."
)
_OUT_OF_DATE: Final = "The looks and states are out of date. Resolve them again first."
_BEING_MADE: Final = "The pictures are already being made."
_HAS_PICTURES: Final = "Already has its pictures."

Kind = Literal["look", "state", "view_state"]
# `unavailable`: no pictures yet, and none can be started (see `blocked_reason`).
# `none`: no pictures yet, and they can be started. `in_progress`: being made. `failed`: the
# last attempt did not work. `ready`: the pictures exist.
Status = Literal["unavailable", "none", "in_progress", "failed", "ready"]
# Where an `in_progress` item is: a state's picture is `drawing`; a look draws its master and
# then makes the other angles.
Stage = Literal["drawing", "making_master", "making_angles"]


class LookStateImageError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass
class ImageItem:
    """One new look or environment state of the newest resolution, and where its pictures
    stand. `source_image_id` is the canonical picture it is edited from (None when there is
    none), `source_version` the version of the library character or environment it comes from.
    """

    kind: Kind
    record_id: int
    slug: str
    name: str
    description: str
    # The discovered character's or environment's id in the project, and its name.
    subject_id: str
    subject_name: str
    # The titles of the scenes that use it, in story order.
    scenes: list[str]
    status: Status
    stage: Stage | None = None
    # A look only: how many of the five angles have a picture, and which failed.
    angles_ready: int = 0
    failed_angles: list[FailedAngle] = field(default_factory=list)
    error: str | None = None
    # A look's newest attempt, or None.
    look: CharacterLook | None = None
    # A state's picture, once it has one.
    image: LabImage | None = None
    can_run: bool = False
    blocked_reason: str | None = None
    source_image_id: int | None = None
    source_version: int | None = None
    # Why the pictures of a `ready` item are out of date (PHASE-039), one sentence each: they
    # were edited from a canonical picture that was replaced since. The status stays `ready` so
    # the one-click run does not count it as unfinished; making them again is PHASE-040.
    reasons: list[str] = field(default_factory=list)
    # A view in a state (PHASE-053) only: the view and the state it is made for. Its
    # `record_id` is the id of its record, or 0 while it has none.
    view_id: int | None = None
    state_id: int | None = None


@dataclass(frozen=True)
class ImagesState:
    """What the story workspace shows. `resolution_version` is None when the project has no
    resolution yet. `blocked_reason` is why nothing can be started at all, or None.
    """

    resolution_version: int | None
    items: list[ImageItem]
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    """An item that "Make pictures for all" did not start, and why."""

    kind: Kind
    record_id: int
    name: str
    reason: str


@dataclass(frozen=True)
class StartAllResult:
    look_ids: list[int]
    state_ids: list[int]
    view_state_ids: list[int]
    skipped: list[Skipped]


@dataclass
class _Use:
    kind: Kind
    record_id: int
    subject_id: str
    scenes: list[str]


# --- Reading the state --------------------------------------------------------------------


def _uses(content: dict[str, Any], titles: dict[str, str]) -> list[_Use]:
    """The distinct named looks and states the resolution points at, in story order, each with
    the titles of the scenes that use it. `default` entries have no record and are left out.
    """
    found: dict[tuple[str, int], _Use] = {}
    for scene in content["scenes"]:
        title = titles.get(scene["scene_id"], scene["scene_id"])
        wanted: list[tuple[Kind, int, str]] = []
        environment = scene["environment"]
        if environment["state_id"] is not None:
            wanted.append((STATE, environment["state_id"], environment["discovery_id"]))
        for look in scene["looks"]:
            if look["look_id"] is not None:
                wanted.append((LOOK, look["look_id"], look["character_id"]))
        for kind, record_id, subject_id in wanted:
            use = found.get((kind, record_id))
            if use is None:
                found[(kind, record_id)] = _Use(kind, record_id, subject_id, [title])
            elif title not in use.scenes:
                use.scenes.append(title)
    return list(found.values())


async def _newest_named_looks(
    session: AsyncSession, named_ids: list[int]
) -> dict[int, CharacterLook]:
    """The newest look made for each named look."""
    if not named_ids:
        return {}
    statement = (
        select(CharacterLook)
        .where(CharacterLook.named_look_id.in_(named_ids))
        .order_by(CharacterLook.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[int, CharacterLook] = {}
    for look in (await session.execute(statement)).scalars():
        if look.named_look_id is not None and look.named_look_id not in newest:
            newest[look.named_look_id] = look
    return newest


def _look_refusal(
    entry: character_images.EntryImages | None,
    named: CharacterNamedLook,
    subject_id: str,
    front: character_images.Front | None,
) -> str | None:
    """Why this look cannot be made now, or None when it can."""
    if entry is None:
        return f"'{subject_id}' is not in the newest list of characters."
    name = entry.definition.item["name"]
    info = entry.definition.entry.info
    if info is None:
        return f"'{name}' is not linked to a Character Lab character yet. Link it first."
    if info.character.id != named.character_id:
        return (
            f"{name} is linked to a different Character Lab character than this look was "
            "resolved for. Resolve the looks and states again."
        )
    if info.character.archived:
        return f"{info.character.name} is archived. Unarchive it in the Character Lab first."
    if entry.status == "in_progress":
        return f"The images of {name} are still being made."
    if entry.status == "out_of_date":
        return f"The images of {name} are out of date. Make them again first."
    if entry.status != "ready" or front is None:
        return f"Make images for {name} first: its new looks are drawn from its canonical picture."
    return None


async def _look_item(
    session: AsyncSession,
    use: _Use,
    named: CharacterNamedLook,
    entry: character_images.EntryImages | None,
    front: character_images.Front | None,
    look: CharacterLook | None,
) -> ImageItem:
    progress = await character_images.look_progress(session, look) if look is not None else None
    status: Status
    if look is None or progress is None:
        status = "none"
    elif look.status == "ready":
        status = "ready"
    elif progress.stage is None:
        status = "failed"
    else:
        status = "in_progress"

    refusal = _look_refusal(entry, named, use.subject_id, front)
    blocked = refusal
    if status == "ready":
        blocked = _HAS_PICTURES
    elif status == "in_progress":
        blocked = _BEING_MADE
    elif refusal is not None and status == "none":
        status = "unavailable"

    reasons: list[str] = []
    if (
        status == "ready"
        and look is not None
        and look.reference_image_id is not None
        and front is not None
        and look.reference_image_id != front.lab_image_id
    ):
        reasons.append(
            f"The canonical picture of {use.subject_id} was replaced since this look was made."
        )

    stage: Stage | None = None
    if progress is not None and progress.stage == "making_master":
        stage = "making_master"
    elif progress is not None and progress.stage == "making_angles":
        stage = "making_angles"
    return ImageItem(
        kind=LOOK,
        record_id=named.id,
        slug=named.slug,
        name=named.name,
        description=named.description,
        subject_id=use.subject_id,
        subject_name=entry.definition.item["name"] if entry is not None else use.subject_id,
        scenes=use.scenes,
        status=status,
        stage=stage,
        angles_ready=progress.angles_ready if progress is not None else 0,
        failed_angles=progress.failed_angles if progress is not None else [],
        error=progress.error if progress is not None else None,
        look=look,
        can_run=blocked is None,
        blocked_reason=blocked,
        source_image_id=front.lab_image_id if front is not None else None,
        source_version=front.version if front is not None else None,
        reasons=reasons,
    )


def _state_refusal(
    entry: environment_definitions.EntryDefinition | None,
    record: EnvironmentState,
    subject_id: str,
) -> str | None:
    """Why this state cannot be made now, or None when it can."""
    if entry is None:
        return f"'{subject_id}' is not in the newest list of environments."
    name = entry.item["name"]
    info = entry.entry.info
    if info is None:
        return f"'{name}' is not linked to a Character Lab environment yet. Link it first."
    if info.environment.id != record.environment_id:
        return (
            f"{name} is linked to a different Character Lab environment than this state was "
            "resolved for. Resolve the looks and states again."
        )
    if info.environment.archived:
        return f"{info.environment.name} is archived. Unarchive it in the Character Lab first."
    if entry.job is not None and entry.job.status in store.ACTIVE_STATUSES:
        return "A definition is being written. Wait for it to finish."
    if entry.status == "out_of_date":
        return f"The definition of {name} is out of date. Define the environment again first."
    if entry.status != "defined" or entry.version is None:
        return f"{name} has no definition yet. Define the environment first."
    if info.newer_version_available:
        return (
            f"The Character Lab has a newer version of {name} than the one this project pins, "
            "so a state cannot be added to the pinned one. Define the environment again to "
            "pin the newest version."
        )
    if entry.version.reference_image_id is None:
        return f"Make {name}'s canonical picture first: its states are drawn from it."
    return None


async def _state_progress(
    session: AsyncSession, record: EnvironmentState | EnvironmentViewState
) -> tuple[Status, Stage | None, str | None, LabImage | None]:
    """Where a state's picture stands: ready (its image), not started, still being drawn, or
    failed with the reason.
    """
    if record.reference_image_id is not None:
        image = await session.get(LabImage, record.reference_image_id)
        return "ready", None, None, image
    if record.lab_run_id is None:
        return "none", None, None, None
    run = await session.get(LabRun, record.lab_run_id)
    if run is None:
        return "failed", None, "The picture's run is gone. Make it again.", None
    images = await image_lab.images_by_run(session, [run.id])
    if images.get(run.id):
        return (
            "failed",
            None,
            "The picture was made but could not be attached to the state. Make it again.",
            None,
        )
    job = (await image_lab.jobs_for_runs(session, [run])).get(run.id)
    if job is None:
        return "failed", None, "The picture's job is gone. Make it again.", None
    if job.status in _DEAD_JOB_STATUSES:
        reason = job.error or (
            "The picture was cancelled." if job.status == "cancelled" else "The picture failed."
        )
        return "failed", None, f"The picture could not be drawn: {reason}", None
    return "in_progress", "drawing", None, None


async def _state_item(
    session: AsyncSession,
    use: _Use,
    record: EnvironmentState,
    entry: environment_definitions.EntryDefinition | None,
) -> ImageItem:
    status, stage, error, image = await _state_progress(session, record)
    refusal = _state_refusal(entry, record, use.subject_id)
    blocked = refusal
    if status == "ready":
        blocked = _HAS_PICTURES
    elif status == "in_progress":
        blocked = _BEING_MADE
    elif refusal is not None and status == "none":
        status = "unavailable"

    source = entry.version if entry is not None else None
    info = entry.entry.info if entry is not None else None
    made_from = record.inputs.get("source_image_id") if isinstance(record.inputs, dict) else None
    reasons: list[str] = []
    if (
        status == "ready"
        and isinstance(made_from, int)
        and source is not None
        and source.reference_image_id is not None
        and made_from != source.reference_image_id
    ):
        reasons.append(
            "The canonical picture of "
            f"{entry.item['name'] if entry is not None else use.subject_id} "
            "was replaced since this state's picture was made."
        )
    return ImageItem(
        kind=STATE,
        record_id=record.id,
        slug=record.slug,
        name=record.name,
        description=record.description,
        subject_id=use.subject_id,
        subject_name=entry.item["name"] if entry is not None else use.subject_id,
        scenes=use.scenes,
        status=status,
        stage=stage,
        error=error,
        image=image,
        can_run=blocked is None,
        blocked_reason=blocked,
        source_image_id=source.reference_image_id if source is not None else None,
        source_version=info.link.pinned_version if info is not None else None,
        reasons=reasons,
    )


@dataclass
class _ViewStateUse:
    view: EnvironmentView
    state: EnvironmentState
    subject_id: str
    scenes: list[str]


async def _view_state_uses(
    session: AsyncSession,
    content: dict[str, Any],
    titles: dict[str, str],
    plans: dict[str, Any],
    states: dict[int, EnvironmentState],
    by_environment: dict[str, environment_definitions.EntryDefinition],
) -> list[_ViewStateUse]:
    """The (view, state) pairs the scenes need (PHASE-053): for every scene whose environment
    is resolved to a named state, each view of the environment's plan that the scene uses.
    A pair is listed once, with the titles of the scenes that use it.
    """
    found: dict[tuple[int, int], _ViewStateUse] = {}
    rows_by_environment: dict[int, dict[str, EnvironmentView]] = {}
    for scene in content["scenes"]:
        environment = scene["environment"]
        record = states.get(environment["state_id"]) if environment["state_id"] else None
        discovery_id = environment["discovery_id"]
        plan = plans.get(discovery_id)
        entry = by_environment.get(discovery_id)
        if record is None or plan is None or entry is None or entry.entry.info is None:
            continue
        library_id = entry.entry.info.environment.id
        if library_id not in rows_by_environment:
            rows_by_environment[library_id] = {
                view.slug: view for view in await environment_views.views_of(session, library_id)
            }
        planned = next(
            (item for item in plan.content["scenes"] if item["scene_id"] == scene["scene_id"]),
            None,
        )
        if planned is None:
            continue
        slugs: list[str] = []
        for ids in [*planned["by_side"].values(), planned["group"]]:
            slugs += [slug for slug in ids if slug not in slugs]
        for slug in slugs:
            view = rows_by_environment[library_id].get(slug)
            if view is None:
                continue
            title = titles.get(scene["scene_id"], scene["scene_id"])
            use = found.setdefault(
                (view.id, record.id), _ViewStateUse(view, record, discovery_id, [])
            )
            if title not in use.scenes:
                use.scenes.append(title)
    return list(found.values())


def _view_state_refusal(use: _ViewStateUse) -> str | None:
    """Why this view in this state cannot be made now, or None when it can."""
    if use.view.reference_image_id is None:
        return f"Make the picture of the view '{use.view.name}' first (Environment views)."
    if use.state.reference_image_id is None:
        return f"Make the picture of the state '{use.state.name}' first."
    return None


async def _view_state_item(
    session: AsyncSession,
    use: _ViewStateUse,
    record: EnvironmentViewState | None,
    entry: environment_definitions.EntryDefinition | None,
) -> ImageItem:
    status: Status = "none"
    stage: Stage | None = None
    error: str | None = None
    image: LabImage | None = None
    if record is not None:
        status, stage, error, image = await _state_progress(session, record)
    refusal = _view_state_refusal(use)
    blocked = refusal
    if status == "ready":
        blocked = _HAS_PICTURES
    elif status == "in_progress":
        blocked = _BEING_MADE
    elif refusal is not None and status == "none":
        status = "unavailable"

    reasons: list[str] = []
    made_from = record.inputs if record is not None and isinstance(record.inputs, dict) else {}
    if status == "ready" and (
        made_from.get("view_image_id") != use.view.reference_image_id
        or made_from.get("state_image_id") != use.state.reference_image_id
    ):
        reasons.append("The picture of the view or of the state was replaced since this was made.")
    return ImageItem(
        kind=VIEW_STATE,
        record_id=record.id if record is not None else 0,
        slug=f"{use.view.slug}__{use.state.slug}",
        name=f"{use.view.name}, {use.state.name}",
        description=use.state.description,
        subject_id=use.subject_id,
        subject_name=entry.item["name"] if entry is not None else use.subject_id,
        scenes=use.scenes,
        status=status,
        stage=stage,
        error=error,
        image=image,
        can_run=blocked is None,
        blocked_reason=blocked,
        source_image_id=use.view.reference_image_id,
        reasons=reasons,
        view_id=use.view.id,
        state_id=use.state.id,
    )


async def state(session: AsyncSession, project: Project) -> ImagesState:
    """The new looks and states of the newest resolution, with where each one's pictures stand.
    Worked out on every read; nothing here is stored.
    """
    resolution = await look_state_resolution.state(session, project)
    row = resolution.version
    if row is None:
        return ImagesState(None, [], _NO_RESOLUTION)
    global_block = _OUT_OF_DATE if resolution.reasons else None

    titles = {scene.scene_id: scene.title for scene in resolution.scenes}
    uses = _uses(row.content, titles)
    look_ids = [use.record_id for use in uses if use.kind == LOOK]
    state_ids = [use.record_id for use in uses if use.kind == STATE]
    named_looks: dict[int, CharacterNamedLook] = {}
    if look_ids:
        found = await session.execute(
            select(CharacterNamedLook)
            .where(CharacterNamedLook.id.in_(look_ids))
            .execution_options(populate_existing=True)
        )
        named_looks = {record.id: record for record in found.scalars()}
    states: dict[int, EnvironmentState] = {}
    if state_ids:
        found_states = await session.execute(
            select(EnvironmentState)
            .where(EnvironmentState.id.in_(state_ids))
            .execution_options(populate_existing=True)
        )
        states = {record.id: record for record in found_states.scalars()}

    characters = await character_images.state(session, project)
    by_character = {entry.definition.item["id"]: entry for entry in characters.entries}
    environments = await environment_definitions.state(session, project)
    by_environment = {entry.item["id"]: entry for entry in environments.entries}
    newest_looks = await _newest_named_looks(session, look_ids)

    items: list[ImageItem] = []
    for use in uses:
        item: ImageItem | None = None
        if use.kind == LOOK and use.record_id in named_looks:
            item = await _look_item(
                session,
                use,
                named_looks[use.record_id],
                by_character.get(use.subject_id),
                characters.fronts.get(use.subject_id),
                newest_looks.get(use.record_id),
            )
        elif use.kind == STATE and use.record_id in states:
            item = await _state_item(
                session, use, states[use.record_id], by_environment.get(use.subject_id)
            )
        if item is None:
            continue
        if global_block is not None and item.can_run:
            item.can_run = False
            item.blocked_reason = global_block
        items.append(item)

    # The pictures of the views in those states (PHASE-053).
    plans = await environment_views.newest_plans(session, project.id)
    view_uses = await _view_state_uses(session, row.content, titles, plans, states, by_environment)
    if view_uses:
        found_records = await session.execute(
            select(EnvironmentViewState)
            .where(EnvironmentViewState.view_id.in_({use.view.id for use in view_uses}))
            .execution_options(populate_existing=True)
        )
        records = {(rec.view_id, rec.state_id): rec for rec in found_records.scalars()}
        for use in view_uses:
            item = await _view_state_item(
                session,
                use,
                records.get((use.view.id, use.state.id)),
                by_environment.get(use.subject_id),
            )
            if global_block is not None and item.can_run:
                item.can_run = False
                item.blocked_reason = global_block
            items.append(item)
    return ImagesState(row.version, items, global_block)


# --- Starting pictures --------------------------------------------------------------------


def _find(result: ImagesState, kind: Kind, record_id: int) -> ImageItem:
    for item in result.items:
        if item.kind == kind and item.record_id == record_id:
            return item
    word = "look" if kind == LOOK else "state"
    raise LookStateImageError(f"There is no new {word} {record_id} in the newest resolution.")


def _inputs(project: Project, item: ImageItem, resolution_version: int | None) -> dict[str, Any]:
    """The D-3 provenance of the pictures made for an item."""
    return {
        "project_id": project.id,
        "discovery_id": item.subject_id,
        "slug": item.slug,
        "source_version": item.source_version,
        "source_image_id": item.source_image_id,
        "resolution_version": resolution_version,
    }


async def _start_look(
    session: AsyncSession, project: Project, item: ImageItem, resolution_version: int | None
) -> CharacterLook:
    """Starts a fresh look for a look item that `can_run`, and commits."""
    named = await session.get(CharacterNamedLook, item.record_id)
    if named is None or item.source_image_id is None:
        raise LookStateImageError("This look has no picture to be drawn from.")
    inputs = {**_inputs(project, item, resolution_version), "named_look_id": item.record_id}
    try:
        prompt = prompts.look_edit_prompt(named.description)
        look = await character_looks.start_look(
            session,
            named.character_id,
            item.source_image_id,
            automatic=character_looks.AutomaticLook(
                project_id=project.id, discovery_id=item.subject_id, inputs=inputs
            ),
            prompt=prompt,
            named_look_id=named.id,
        )
    except (character_looks.CharacterLookError, ValueError) as exc:
        raise LookStateImageError(str(exc)) from exc
    _logger.info(
        "project %d: look '%s' started for '%s': look=%d",
        project.id,
        item.slug,
        item.subject_id,
        look.id,
    )
    return look


async def _start_state(
    session: AsyncSession, project: Project, item: ImageItem, resolution_version: int | None
) -> EnvironmentState:
    """Starts one edit run for a state item that `can_run`, and commits."""
    record = await session.get(EnvironmentState, item.record_id)
    if record is None or item.source_image_id is None:
        raise LookStateImageError("This state has no picture to be drawn from.")
    mode = image_models_service.resolve_mode(
        await settings_service.get_str(session, IMAGE_MODE_KEY)
    )
    try:
        form = QwenEditForm(
            prompt=prompts.state_edit_prompt(record.description),
            mode=mode,
            aspect_ratio=environment_references.REFERENCE_SHAPE,
            seed=None,
            steps=None,
            references=[Ref(source="lab", id=item.source_image_id)],
        )
        run, _job = await image_lab.create_qwen_edit_run(session, form, commit=False)
    except (LabInputError, ValueError) as exc:
        await session.rollback()
        raise LookStateImageError(str(exc)) from exc
    record.lab_run_id = run.id
    record.inputs = {
        **_inputs(project, item, resolution_version),
        "environment_version": item.source_version,
    }
    await session.commit()
    _logger.info(
        "project %d: state '%s' started for '%s': run=%d",
        project.id,
        item.slug,
        item.subject_id,
        run.id,
    )
    return record


async def _start_view_state(
    session: AsyncSession, project: Project, item: ImageItem, resolution_version: int | None
) -> EnvironmentViewState:
    """Starts one edit run for a view-in-a-state item that `can_run`, and commits. A record that
    failed earlier is used again.
    """
    view = await session.get(EnvironmentView, item.view_id or 0)
    state_record = await session.get(EnvironmentState, item.state_id or 0)
    if (
        view is None
        or state_record is None
        or view.reference_image_id is None
        or state_record.reference_image_id is None
    ):
        raise LookStateImageError("This view has no pictures to be drawn from.")
    record = (
        (
            await session.execute(
                select(EnvironmentViewState).where(
                    EnvironmentViewState.view_id == view.id,
                    EnvironmentViewState.state_id == state_record.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if record is None:
        record = EnvironmentViewState(view_id=view.id, state_id=state_record.id)
        session.add(record)
        await session.flush()
    mode = image_models_service.resolve_mode(
        await settings_service.get_str(session, IMAGE_MODE_KEY)
    )
    try:
        form = QwenEditForm(
            prompt=prompts.view_state_edit_prompt(state_record.description),
            mode=mode,
            aspect_ratio=environment_references.REFERENCE_SHAPE,
            seed=None,
            steps=None,
            references=[
                Ref(source="lab", id=view.reference_image_id),
                Ref(source="lab", id=state_record.reference_image_id),
            ],
        )
        run, _job = await image_lab.create_qwen_edit_run(session, form, commit=False)
    except (LabInputError, ValueError) as exc:
        await session.rollback()
        raise LookStateImageError(str(exc)) from exc
    record.reference_image_id = None
    record.lab_run_id = run.id
    record.inputs = {
        "project_id": project.id,
        "discovery_id": item.subject_id,
        "slug": item.slug,
        "resolution_version": resolution_version,
        "view_image_id": view.reference_image_id,
        "state_image_id": state_record.reference_image_id,
    }
    await session.commit()
    _logger.info(
        "project %d: view '%s' in state '%s' started for '%s': run=%d",
        project.id,
        view.slug,
        state_record.slug,
        item.subject_id,
        run.id,
    )
    return record


async def start_view_state_record(
    session: AsyncSession, project: Project, view_id: int, state_id: int
) -> tuple[int, bool]:
    """Starts the picture of one view in one state, and commits. Returns `(record id, created)`:
    when it is being made already, `created` is False. Raises LookStateImageError.
    """
    result = await state(session, project)
    item = next(
        (
            candidate
            for candidate in result.items
            if candidate.kind == VIEW_STATE
            and candidate.view_id == view_id
            and candidate.state_id == state_id
        ),
        None,
    )
    if item is None:
        raise LookStateImageError("This view is not used in this state by the newest resolution.")
    if item.status == "in_progress":
        return item.record_id, False
    if not item.can_run:
        raise LookStateImageError(item.blocked_reason or "This picture cannot be made now.")
    record = await _start_view_state(session, project, item, result.resolution_version)
    return record.id, True


async def start_look_record(
    session: AsyncSession, project: Project, record_id: int
) -> tuple[int, bool]:
    """Starts the pictures of one new look, and commits. Returns `(look id, created)`: when its
    pictures are being made already, that look is returned and `created` is False. Raises
    LookStateImageError.
    """
    result = await state(session, project)
    item = _find(result, LOOK, record_id)
    if item.status == "in_progress" and item.look is not None:
        return item.look.id, False
    if not item.can_run:
        raise LookStateImageError(item.blocked_reason or "This look cannot be made now.")
    look = await _start_look(session, project, item, result.resolution_version)
    return look.id, True


async def start_state_record(
    session: AsyncSession, project: Project, record_id: int
) -> tuple[int, bool]:
    """Starts the picture of one new state, and commits. Returns `(state id, created)`: when its
    picture is being made already, `created` is False. Raises LookStateImageError.
    """
    result = await state(session, project)
    item = _find(result, STATE, record_id)
    if item.status == "in_progress":
        return item.record_id, False
    if not item.can_run:
        raise LookStateImageError(item.blocked_reason or "This state cannot be made now.")
    record = await _start_state(session, project, item, result.resolution_version)
    return record.id, True


async def start_all(session: AsyncSession, project: Project) -> StartAllResult:
    """Starts the pictures of every new look and state that has none yet and can be made now,
    and commits each. Everything else is skipped, with the reason. Raises LookStateImageError
    when there is no resolution or it is out of date.
    """
    result = await state(session, project)
    if result.blocked_reason is not None:
        raise LookStateImageError(result.blocked_reason)
    look_ids: list[int] = []
    state_ids: list[int] = []
    view_state_ids: list[int] = []
    skipped: list[Skipped] = []
    for item in result.items:
        if not item.can_run:
            skipped.append(Skipped(item.kind, item.record_id, item.name, item.blocked_reason or ""))
            continue
        if item.kind == LOOK:
            look = await _start_look(session, project, item, result.resolution_version)
            look_ids.append(look.id)
        elif item.kind == VIEW_STATE:
            view_record = await _start_view_state(session, project, item, result.resolution_version)
            view_state_ids.append(view_record.id)
        else:
            record = await _start_state(session, project, item, result.resolution_version)
            state_ids.append(record.id)
    return StartAllResult(
        look_ids=look_ids, state_ids=state_ids, view_state_ids=view_state_ids, skipped=skipped
    )


# --- When a state's picture is stored -----------------------------------------------------


async def on_state_image_stored(run_id: int) -> bool:
    """Called (best effort) once a `lab_image` job has stored its picture. When the picture is
    the one a state was waiting for, it becomes the state's picture. When the project's link
    still points at the state's environment and the pinned version is the environment's newest,
    the environment's next version (`ai`) freezes the picture, carrying its canonical picture
    forward, and the project's pin moves to it. Otherwise the picture stays on the state and
    the pin is left alone (a newer version was made in the lab meanwhile). Returns True when the
    picture was attached. Does nothing (False) for any other picture.
    """
    async with SessionLocal() as session:
        record = (
            (
                await session.execute(
                    select(EnvironmentState).where(EnvironmentState.lab_run_id == run_id)
                )
            )
            .scalars()
            .first()
        )
        if record is None or record.reference_image_id is not None:
            await session.commit()
            return False
        image = (
            (await session.execute(select(LabImage).where(LabImage.run_id == run_id)))
            .scalars()
            .first()
        )
        if image is None:
            await session.commit()
            return False
        record.reference_image_id = image.id
        await session.flush()
        pinned = await _pin_state(session, record)
        await session.commit()
    _logger.info(
        "environment state %d: picture attached: image=%d pinned_version=%s",
        record.id,
        image.id,
        pinned,
    )
    return True


async def on_view_state_image_stored(run_id: int) -> bool:
    """Called (best effort) once a `lab_image` job has stored its picture. When the picture is
    the one a view in a state was waiting for (PHASE-053), it becomes that picture, and the
    environment's next version freezes it the way a view's own picture is frozen
    (`environment_views.pin_next_version`). Returns True when the picture was attached. Does
    nothing (False) for any other picture.
    """
    async with SessionLocal() as session:
        record = (
            (
                await session.execute(
                    select(EnvironmentViewState).where(EnvironmentViewState.lab_run_id == run_id)
                )
            )
            .scalars()
            .first()
        )
        if record is None or record.reference_image_id is not None:
            await session.commit()
            return False
        image = (
            (await session.execute(select(LabImage).where(LabImage.run_id == run_id)))
            .scalars()
            .first()
        )
        view = await session.get(EnvironmentView, record.view_id)
        if image is None or view is None:
            await session.commit()
            return False
        record.reference_image_id = image.id
        await session.flush()
        pinned = await environment_views.pin_next_version(
            session, view.environment_id, record.inputs
        )
        await session.commit()
    _logger.info(
        "environment view state %d: picture attached: image=%d pinned_version=%s",
        record.id,
        image.id,
        pinned,
    )
    return True


async def _pin_state(session: AsyncSession, record: EnvironmentState) -> int | None:
    """Writes the environment's next version, which freezes the state's picture, and moves the
    project's pin to it. Returns the version the pin now holds, or None, doing nothing, when the
    state has no recorded project, the link no longer points at this environment, or the pinned
    version is no longer the newest. Flushes but does not commit.
    """
    inputs = record.inputs if isinstance(record.inputs, dict) else {}
    project_id, discovery_id = inputs.get("project_id"), inputs.get("discovery_id")
    if not isinstance(project_id, int) or not isinstance(discovery_id, str):
        return None
    link = (
        (
            await session.execute(
                select(ProjectEnvironmentLink).where(
                    ProjectEnvironmentLink.project_id == project_id,
                    ProjectEnvironmentLink.discovery_id == discovery_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if link is None or link.environment_id != record.environment_id:
        return None
    newest = await environment_versions.latest_version(session, record.environment_id)
    environment = await session.get(LibraryEnvironment, record.environment_id)
    if newest is None or environment is None or newest.version != link.pinned_version:
        return None
    # The version records the same `inputs` as the one the project pinned, so the Environment
    # Definition stage still reads that definition as built from this story.
    # (A version the project adopted from the lab has none of its own: the link's provenance
    # supplies them, PHASE-042, and the new version then carries them.)
    inputs = await library_adoption.effective_inputs(session, "environment", link, newest)
    version = await environment_versions.record_version_if_changed(
        session,
        environment,
        source="ai",
        inputs=inputs,
        carry_picture=True,
    )
    link.pinned_version = (version if version is not None else newest).version
    if inputs is not None:
        link.provenance_version = None
    link.updated_at = utcnow()
    return link.pinned_version
