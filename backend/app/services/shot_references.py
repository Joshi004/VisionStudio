"""The reference manifest of a shot (PHASE-024, `Path_ahead.md` Section 28).

The manifest is the minimum set of pictures one shot is generated from: its visible characters
(with the look the scene resolved to) and its environment (with the resolved state).
`services/reference_selection` holds the fixed rule, this module builds the catalog the choice is
made from, stores the result and says where each shot stands.

- **Two methods** (the setting `reference_selection_method`, PHASE-033). `deterministic`: code
  chooses inside the request, with no model and no job. `llm`: a `select_shot_references` job per
  shot asks the language model (`reference_selection_writer`), and falls back to the fixed rule
  when the answer cannot be used; `jobs/select_shot_references.py` stores the result with
  `save_from_job`. A manifest records its `method`, a `reason` for each picture the model chose
  and, when the model was not used, the `fallback_reason`.

- **The catalog** is read from what the project **pins**: for each character visible in the shot,
  the pictures of the pinned `library_character_version` (the default look in `look_references`,
  a named look in `named_looks`), and for the environment the pinned `library_environment_version`
  (the default picture, or a state's in `states`). Which look or state the scene uses comes from
  the look and state resolution (PHASE-016). Each picture's text description is the prompt it was
  made from (`lab_run.prompt`).
- A manifest is a **project artifact**: one immutable `shot_reference_manifest` row per selection,
  numbered per shot, with the provenance of the artifact convention (D-3). Nothing is written to
  the Character Lab.
- A shot can be selected only when its newest specification exists, is current and is not being
  defined again. A shot with a missing picture is refused with the reason and nothing is stored.
- **Out of date is worked out on every read** and never stored: the shot was defined again or its
  definition is out of date, the looks and states were resolved again, or the pinned version of a
  character or the environment it used has changed (new pictures, a remade look).
- `select_shot`, `select_scene` and `select_all` are the buttons. With the fixed rule they commit
  once; with the model they queue the jobs (each commits). `select_if_ready` is called by the
  `define_shot` job after it has committed, so a defined shot gets its manifest by itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import (
    Job,
    LabImage,
    LabRun,
    LibraryCharacterVersion,
    LibraryEnvironmentVersion,
    Project,
    ShotReferenceManifest,
)
from app.jobs import store
from app.services import (
    look_state_resolution,
    reference_selection,
    scene_definitions,
    shot_definitions,
)
from app.services.reference_selection import CatalogPicture

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "select_shot_references"
# Two presses on one shot make one job; two shots run side by side. The key is `scene/shot`.
DEDUPE_KEY: Final = "shot_key"
# How many of a project's newest selection jobs are read to find each shot's newest one.
_JOB_LOOKBACK: Final = 2000

SHOT_DEFINITION_KIND: Final = "shot_definition"
RESOLUTION_KIND: Final = shot_definitions.RESOLUTION_KIND
CHARACTER_KIND: Final = scene_definitions.CHARACTER_DEFINITION_KIND
ENVIRONMENT_KIND: Final = scene_definitions.ENVIRONMENT_DEFINITION_KIND

# `not_selected`: no manifest was made for this shot. `selected`: made, and nothing it was
# built from has changed. `out_of_date`: made, and something it was built from has changed (see
# the reasons).
Status = Literal["not_selected", "selected", "out_of_date"]


class ShotReferencesError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class ShotEntry:
    """One shot of the newest shot plan and where its reference manifest stands."""

    shot: dict[str, Any]
    duration_s: float
    # Where the shot's definition stands: `not_defined`, `defined` or `out_of_date`.
    definition_status: str
    status: Status
    # Why a selected manifest is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The newest manifest of this shot, when it has one.
    row: ShotReferenceManifest | None
    # The newest selection job of this shot, whatever its status (none when the fixed rule has
    # always chosen).
    job: Job | None
    can_run: bool
    blocked_reason: str | None


@dataclass(frozen=True)
class SceneEntry:
    item: dict[str, Any]
    shots: list[ShotEntry]


@dataclass(frozen=True)
class ShotReferencesState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    entries: list[SceneEntry]
    blocked_reason: str | None


@dataclass(frozen=True)
class Selected:
    scene_id: str
    shot_id: str
    version: int


@dataclass(frozen=True)
class Skipped:
    scene_id: str
    shot_id: str | None
    title: str
    reason: str


@dataclass(frozen=True)
class Queued:
    """A shot whose references the language model is to choose: the job that does it."""

    scene_id: str
    shot_id: str
    job_id: int


@dataclass(frozen=True)
class SelectResult:
    """`selected` were chosen by the fixed rule in the request; `queued` wait for the model."""

    selected: list[Selected]
    skipped: list[Skipped]
    queued: list[Queued] = field(default_factory=list)


@dataclass(frozen=True)
class _Context:
    """Everything a selection or a read of the state needs, loaded once."""

    definitions: shot_definitions.ShotDefinitionsState
    resolution: look_state_resolution.ResolutionState
    current: dict[tuple[str, str], scene_definitions.CurrentDefinition]


def _key(scene_id: str, shot_id: str) -> str:
    return f"{scene_id}/{shot_id}"


async def _load(session: AsyncSession, project: Project) -> _Context:
    return _Context(
        definitions=await shot_definitions.state(session, project),
        resolution=await look_state_resolution.state(session, project),
        current=await scene_definitions.current_definitions(session, project),
    )


# --- The catalog ---------------------------------------------------------------------------


def _is_default(slug: str | None) -> bool:
    return slug is None or slug == reference_selection.DEFAULT_VARIANT


def _angle_pictures(references: Any) -> dict[str, int]:
    """`{angle: lab image id}` of a frozen list of `{angle, lab_image_id, ...}`."""
    found: dict[str, int] = {}
    for entry in references if isinstance(references, list) else []:
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("angle"), str)
            and isinstance(entry.get("lab_image_id"), int)
        ):
            found[entry["angle"]] = entry["lab_image_id"]
    return found


async def _character_pictures(
    session: AsyncSession,
    current: scene_definitions.CurrentDefinition,
    look_slug: str | None,
    look_description: str | None,
) -> list[tuple[int, str, str, bool, str | None]]:
    """The pictures of one character's pinned version as
    `(lab image id, view, variant, is resolved, fallback description)`.
    """
    statement = select(LibraryCharacterVersion).where(
        LibraryCharacterVersion.character_id == current.library_id,
        LibraryCharacterVersion.version == current.version,
    )
    version = (await session.execute(statement)).scalars().first()
    if version is None:
        raise ShotReferencesError(
            f"The pinned version {current.version} of '{current.name}' was not found."
        )
    default = _is_default(look_slug)
    found = [
        (image_id, angle, reference_selection.DEFAULT_VARIANT, default, None)
        for angle, image_id in _angle_pictures(version.look_references).items()
    ]
    if not default:
        for named in version.named_looks or []:
            if isinstance(named, dict) and named.get("slug") == look_slug:
                found.extend(
                    (image_id, angle, str(look_slug), True, look_description)
                    for angle, image_id in _angle_pictures(named.get("references")).items()
                )
    return found


async def _environment_pictures(
    session: AsyncSession,
    current: scene_definitions.CurrentDefinition,
    state_slug: str | None,
    state_description: str | None,
) -> list[tuple[int, str, str, bool, str | None]]:
    statement = select(LibraryEnvironmentVersion).where(
        LibraryEnvironmentVersion.environment_id == current.library_id,
        LibraryEnvironmentVersion.version == current.version,
    )
    version = (await session.execute(statement)).scalars().first()
    if version is None:
        raise ShotReferencesError(
            f"The pinned version {current.version} of '{current.name}' was not found."
        )
    default = _is_default(state_slug)
    found: list[tuple[int, str, str, bool, str | None]] = []
    if version.reference_image_id is not None:
        found.append(
            (
                version.reference_image_id,
                reference_selection.ENVIRONMENT_VIEW,
                reference_selection.DEFAULT_VARIANT,
                default,
                None,
            )
        )
    if not default:
        for entry in version.states or []:
            if (
                isinstance(entry, dict)
                and entry.get("slug") == state_slug
                and isinstance(entry.get("reference_image_id"), int)
            ):
                found.append(
                    (
                        entry["reference_image_id"],
                        reference_selection.ENVIRONMENT_VIEW,
                        str(state_slug),
                        True,
                        state_description,
                    )
                )
    return found


async def _prompts(session: AsyncSession, image_ids: set[int]) -> dict[int, str | None]:
    """For each of these lab images that exists, the prompt it was made from (None for an
    upload). An image that does not exist is not in the answer.
    """
    if not image_ids:
        return {}
    images = (
        await session.execute(
            select(LabImage.id, LabImage.run_id).where(LabImage.id.in_(image_ids))
        )
    ).all()
    run_ids = {run_id for _image_id, run_id in images if run_id is not None}
    prompts: dict[int, str] = {}
    if run_ids:
        runs = (
            await session.execute(select(LabRun.id, LabRun.prompt).where(LabRun.id.in_(run_ids)))
        ).all()
        prompts = {run_id: prompt for run_id, prompt in runs}
    return {
        image_id: prompts.get(run_id) if run_id is not None else None for image_id, run_id in images
    }


async def _catalog(
    session: AsyncSession, ctx: _Context, scene_id: str, content: dict[str, Any]
) -> tuple[list[CatalogPicture], list[dict[str, Any]]]:
    """The candidate pictures of one shot and the artifacts they came from (for `inputs`).
    Raises ShotReferencesError.
    """
    resolved = next((scene for scene in ctx.resolution.scenes if scene.scene_id == scene_id), None)
    if resolved is None or not resolved.resolved:
        raise ShotReferencesError("The looks and states of this scene were not resolved.")
    looks = {look.subject_id: look for look in resolved.looks}

    # `(subject id, subject name, kind, pictures)`, the pictures as `_character_pictures` gives.
    raw: list[tuple[str, str, Literal["character", "environment"], list[Any]]] = []
    artifacts: list[dict[str, Any]] = []

    character_ids = [
        entry["id"]
        for entry in content.get("characters") or []
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    ]
    for character_id in character_ids:
        current = ctx.current.get((CHARACTER_KIND, character_id))
        if current is None:
            raise ShotReferencesError(f"The character '{character_id}' is not linked and defined.")
        item = looks.get(character_id)
        slug = item.id if item is not None and item.how != "default" else None
        pictures = await _character_pictures(
            session, current, slug, item.description if item is not None else None
        )
        raw.append((character_id, current.name, "character", pictures))
        artifacts.append(_artifact(CHARACTER_KIND, character_id, current))

    if resolved.environment is None:
        raise ShotReferencesError("The environment of this scene was not resolved.")
    environment_id = resolved.environment.subject_id
    environment = ctx.current.get((ENVIRONMENT_KIND, environment_id))
    if environment is None:
        raise ShotReferencesError(f"The environment '{environment_id}' is not linked and defined.")
    state_item = resolved.environment
    state_slug = state_item.id if state_item.how != "default" else None
    pictures = await _environment_pictures(session, environment, state_slug, state_item.description)
    raw.append((environment_id, environment.name, "environment", pictures))
    artifacts.append(_artifact(ENVIRONMENT_KIND, environment_id, environment))

    prompts = await _prompts(
        session, {picture[0] for _id, _name, _kind, group in raw for picture in group}
    )
    catalog: list[CatalogPicture] = []
    for subject_id, subject_name, kind, group in raw:
        for image_id, view, variant, is_resolved, fallback_text in group:
            if image_id not in prompts:
                continue  # the picture no longer exists
            where = "default" if variant == reference_selection.DEFAULT_VARIANT else variant
            description = (
                prompts[image_id]
                or fallback_text
                or f"{subject_name}, {view.replace('_', ' ')}, {where}"
            )
            catalog.append(
                CatalogPicture(
                    lab_image_id=image_id,
                    kind=kind,
                    subject_id=subject_id,
                    subject_name=subject_name,
                    view=view,
                    variant=variant,
                    is_resolved=is_resolved,
                    description=description,
                )
            )
    return catalog, artifacts


def _artifact(
    kind: str, discovery_id: str, current: scene_definitions.CurrentDefinition
) -> dict[str, Any]:
    """The record of the pinned definition a manifest was built from, in the artifact shape of
    D-3 (the same as a shot definition records).
    """
    return {
        "kind": kind,
        "id": current.library_id,
        "version": current.version,
        "discovery_id": discovery_id,
        "name": current.name,
    }


# --- Reading the state ---------------------------------------------------------------------


def _artifacts(inputs: Any) -> list[Any]:
    artifacts = inputs.get("artifacts") if isinstance(inputs, dict) else None
    return artifacts if isinstance(artifacts, list) else []


def _recorded(inputs: Any, kind: str) -> dict[str, Any] | None:
    for artifact in _artifacts(inputs):
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            return artifact
    return None


def _out_of_date_reasons(
    row: ShotReferenceManifest, entry: shot_definitions.ShotEntry, ctx: _Context
) -> list[str]:
    """Why a manifest made for this shot is no longer current, one sentence each."""
    reasons: list[str] = []
    recorded = _recorded(row.inputs, SHOT_DEFINITION_KIND)
    if entry.row is None:
        reasons.append("The shot has no definition now.")
    elif recorded is None or recorded.get("id") != entry.row.id:
        reasons.append("The shot was defined again since its references were chosen.")
    elif entry.status == "out_of_date":
        reasons.append("The definition of the shot is out of date.")

    newest = ctx.resolution.version
    recorded_resolution = _recorded(row.inputs, RESOLUTION_KIND)
    if newest is None:
        reasons.append("The looks and states are no longer resolved.")
    elif recorded_resolution is None or recorded_resolution.get("id") != newest.id:
        reasons.append("The looks and states were resolved again since the references were chosen.")

    for artifact in _artifacts(row.inputs):
        if not isinstance(artifact, dict) or artifact.get("kind") not in (
            CHARACTER_KIND,
            ENVIRONMENT_KIND,
        ):
            continue
        name = artifact.get("name") or artifact.get("discovery_id")
        current = ctx.current.get((artifact["kind"], artifact.get("discovery_id")))
        if current is None:
            reasons.append(f"'{name}' is no longer linked and defined.")
        elif current.library_id != artifact.get("id") or current.version != artifact.get("version"):
            reasons.append(
                f"'{name}' changed (its pictures may be new) since the references were chosen."
            )
    return reasons


def _refusal(entry: shot_definitions.ShotEntry) -> str | None:
    """Why this shot's references cannot be chosen now, or None."""
    if entry.row is None:
        return "Define this shot first: its references are chosen from its definition."
    if entry.job is not None and entry.job.status in store.ACTIVE_STATUSES:
        return "This shot is being defined."
    if entry.status != "defined":
        return "The definition of this shot is out of date. Define it again first."
    return None


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, ShotReferenceManifest]:
    """The newest manifest of each shot of the project, by its `scene/shot` key."""
    statement = (
        select(ShotReferenceManifest)
        .where(ShotReferenceManifest.project_id == project_id)
        .order_by(ShotReferenceManifest.version.desc(), ShotReferenceManifest.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, ShotReferenceManifest] = {}
    for row in (await session.execute(statement)).scalars():
        key = _key(row.scene_id, row.shot_id)
        if key not in newest:
            newest[key] = row
    return newest


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest selection job of each shot of the project, by its `scene/shot` key."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == JOB_TYPE)
        .order_by(Job.id.desc())
        .limit(_JOB_LOOKBACK)
        .execution_options(populate_existing=True)
    )
    newest: dict[str, Job] = {}
    for job in (await session.execute(statement)).scalars():
        key = job.input.get(DEDUPE_KEY) if isinstance(job.input, dict) else None
        if isinstance(key, str) and key not in newest:
            newest[key] = job
    return newest


async def _current(session: AsyncSession, project: Project, ctx: _Context) -> ShotReferencesState:
    return _build(
        ctx,
        await _newest_rows(session, project.id),
        await _newest_jobs(session, project.id),
    )


def _build(
    ctx: _Context, rows: dict[str, ShotReferenceManifest], jobs: dict[str, Job]
) -> ShotReferencesState:
    entries: list[SceneEntry] = []
    for scene in ctx.definitions.entries:
        shots: list[ShotEntry] = []
        for entry in scene.shots:
            key = _key(scene.item["id"], entry.shot["id"])
            row = rows.get(key)
            job = jobs.get(key)
            status: Status = "not_selected"
            reasons: list[str] = []
            if row is not None:
                reasons = _out_of_date_reasons(row, entry, ctx)
                status = "out_of_date" if reasons else "selected"
            blocked = _refusal(entry)
            if blocked is None and job is not None and job.status in store.ACTIVE_STATUSES:
                blocked = "The references of this shot are being chosen."
            shots.append(
                ShotEntry(
                    shot=entry.shot,
                    duration_s=entry.duration_s,
                    definition_status=entry.status,
                    status=status,
                    reasons=reasons,
                    row=row,
                    job=job,
                    can_run=blocked is None,
                    blocked_reason=blocked,
                )
            )
        entries.append(SceneEntry(item=scene.item, shots=shots))
    return ShotReferencesState(
        scenes_version=ctx.definitions.scenes_version,
        entries=entries,
        blocked_reason=ctx.definitions.blocked_reason,
    )


async def state(session: AsyncSession, project: Project) -> ShotReferencesState:
    """The newest list of scenes with where each shot's manifest stands. Worked out on every
    read; nothing here is stored.
    """
    ctx = await _load(session, project)
    return await _current(session, project, ctx)


# --- Selecting -----------------------------------------------------------------------------


async def _add(
    session: AsyncSession,
    project: Project,
    ctx: _Context,
    scene_id: str,
    entry: shot_definitions.ShotEntry,
) -> ShotReferenceManifest:
    """Chooses the shot's next manifest by the fixed rule and adds it. Flushes but does not
    commit. Raises ShotReferencesError.
    """
    definition = entry.row
    assert definition is not None  # the callers refused otherwise
    catalog, artifacts = await _catalog(session, ctx, scene_id, definition.content)
    try:
        selection = reference_selection.select(definition.content, catalog)
    except reference_selection.ReferenceSelectionError as exc:
        raise ShotReferencesError(str(exc)) from exc
    return await save_manifest(
        session,
        project_id=project.id,
        scene_id=scene_id,
        shot_id=entry.shot["id"],
        shot_definition_id=definition.id,
        selection=selection,
        catalog=catalog,
        method=reference_selection.METHOD_DETERMINISTIC,
        fallback_reason=None,
        job_id=None,
        inputs=_inputs(project.id, scene_id, entry.shot["id"], definition, ctx, artifacts),
    )


def _inputs(
    project_id: int,
    scene_id: str,
    shot_id: str,
    definition: Any,
    ctx: _Context,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """The `inputs` written onto a manifest (D-3): the shot definition and the look and state
    resolution it was chosen from, and the pinned character and environment definitions.
    """
    resolution = ctx.resolution.version
    assert resolution is not None  # the callers refused otherwise
    return {
        "project_id": project_id,
        "scene_id": scene_id,
        "shot_id": shot_id,
        "artifacts": [
            {"kind": SHOT_DEFINITION_KIND, "id": definition.id, "version": definition.version},
            {"kind": RESOLUTION_KIND, "id": resolution.id, "version": resolution.version},
            *artifacts,
        ],
    }


async def save_manifest(
    session: AsyncSession,
    *,
    project_id: int,
    scene_id: str,
    shot_id: str,
    shot_definition_id: int | None,
    selection: reference_selection.Selection,
    catalog: list[CatalogPicture],
    method: str,
    fallback_reason: str | None,
    job_id: int | None,
    inputs: dict[str, Any],
) -> ShotReferenceManifest:
    """Adds the shot's next manifest. Flushes but does not commit: the caller commits (a
    selection job together with finishing itself, so a job is never "succeeded" without its
    result).

    `method` is how the pictures were chosen (`deterministic` or `llm`). `fallback_reason` says
    why the fixed rule was used when the model was meant to choose, else None.
    """
    highest = (
        await session.execute(
            select(func.max(ShotReferenceManifest.version)).where(
                ShotReferenceManifest.project_id == project_id,
                ShotReferenceManifest.scene_id == scene_id,
                ShotReferenceManifest.shot_id == shot_id,
            )
        )
    ).scalar_one_or_none()
    references: list[dict[str, Any]] = []
    for order, (picture, fallback) in enumerate(
        zip(selection.pictures, selection.fallbacks, strict=True), start=1
    ):
        reference: dict[str, Any] = {"order": order, "fallback": fallback, **picture.as_dict()}
        if selection.reasons:
            reference["reason"] = selection.reasons[order - 1]
        references.append(reference)
    row = ShotReferenceManifest(
        project_id=project_id,
        scene_id=scene_id,
        shot_id=shot_id,
        shot_definition_id=shot_definition_id,
        version=(highest or 0) + 1,
        source="ai",
        job_id=job_id,
        inputs=inputs,
        content={
            "shot_id": shot_id,
            "scene_id": scene_id,
            "method": method,
            "fallback_reason": fallback_reason,
            "shot_size": selection.shot_size,
            "framing": selection.framing,
            "focus_character_id": selection.focus_character_id,
            "references": references,
            "catalog": [picture.as_dict() for picture in catalog],
            "notes": selection.notes,
        },
    )
    session.add(row)
    await session.flush()
    _logger.info(
        "references of shot '%s' of scene '%s' of project %d chosen by %s, version %d "
        "(%d pictures)",
        shot_id,
        scene_id,
        project_id,
        method,
        row.version,
        len(selection.pictures),
    )
    return row


async def _queue(
    session: AsyncSession,
    project: Project,
    ctx: _Context,
    scene_id: str,
    entry: shot_definitions.ShotEntry,
) -> tuple[Job, bool]:
    """Queues the job that makes the language model choose this shot's references and returns
    `(job, created)`; `created` is False when the shot already has a job waiting or running,
    which is returned instead. Commits (with the job). Raises ShotReferencesError, in the same
    cases as the fixed rule: nothing is queued, and no paid call made, for a shot that cannot be
    given its pictures.
    """
    definition = entry.row
    assert definition is not None  # the callers refused otherwise
    shot_id = entry.shot["id"]
    catalog, artifacts = await _catalog(session, ctx, scene_id, definition.content)
    try:
        # The fixed rule is the fallback of the job: when it would refuse now, so would the job.
        reference_selection.select(definition.content, catalog)
    except reference_selection.ReferenceSelectionError as exc:
        raise ShotReferencesError(str(exc)) from exc
    return await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            DEDUPE_KEY: _key(scene_id, shot_id),
            "scene_id": scene_id,
            "shot_id": shot_id,
            "shot_definition_id": definition.id,
            "shot_definition": definition.content,
            "catalog": [picture.as_dict() for picture in catalog],
            "inputs": _inputs(project.id, scene_id, shot_id, definition, ctx, artifacts),
        },
        dedupe_key=DEDUPE_KEY,
    )


async def _use_model(session: AsyncSession) -> bool:
    """Whether the setting says the language model chooses (else the fixed rule alone)."""
    method = await settings_service.get_str(
        session, settings_service.REFERENCE_SELECTION_METHOD_KEY
    )
    return method == settings_service.REFERENCE_METHOD_LLM


def _wake() -> None:
    """Wakes the dispatcher so a job just queued starts now."""
    # Imported here: the dispatcher imports the handlers, which import this module.
    from app.jobs import dispatcher

    dispatcher.nudge()


async def _commit(session: AsyncSession) -> None:
    """Commits, turning a clash of two selections of one shot into a readable refusal."""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ShotReferencesError(
            "The references of a shot were chosen at the same moment. Try again."
        ) from exc


async def _select_entries(
    session: AsyncSession,
    project: Project,
    ctx: _Context,
    state_entry: SceneEntry,
    result: SelectResult,
    use_model: bool,
) -> None:
    """Chooses the references of every shot of the scene that has none or an out of date
    manifest, adding to `result`: by the fixed rule now, or with `use_model` by queuing a job for
    the language model. A shot that cannot be done is skipped with the reason.
    """
    scene_id = state_entry.item["id"]
    title = state_entry.item["title"]
    definitions = next(entry for entry in ctx.definitions.entries if entry.item["id"] == scene_id)
    by_id = {entry.shot["id"]: entry for entry in definitions.shots}
    for shot in state_entry.shots:
        shot_id = shot.shot["id"]
        if shot.status == "selected":
            result.skipped.append(
                Skipped(scene_id, shot_id, title, "Already chosen and up to date.")
            )
        elif shot.blocked_reason is not None:
            result.skipped.append(Skipped(scene_id, shot_id, title, shot.blocked_reason))
        elif use_model:
            try:
                job, created = await _queue(session, project, ctx, scene_id, by_id[shot_id])
            except ShotReferencesError as exc:
                result.skipped.append(Skipped(scene_id, shot_id, title, str(exc)))
            else:
                if created:
                    result.queued.append(Queued(scene_id, shot_id, job.id))
                else:
                    result.skipped.append(
                        Skipped(scene_id, shot_id, title, "Already being chosen.")
                    )
        else:
            try:
                row = await _add(session, project, ctx, scene_id, by_id[shot_id])
            except ShotReferencesError as exc:
                result.skipped.append(Skipped(scene_id, shot_id, title, str(exc)))
            else:
                result.selected.append(Selected(scene_id, shot_id, row.version))


async def select_shot(
    session: AsyncSession, project: Project, scene_id: str, shot_id: str
) -> SelectResult:
    """Chooses the references of one shot and commits: by the fixed rule now, or, when the
    setting says the language model chooses, by queuing its job. A manifest that is current
    already is not made again (the answer says so). Raises ShotReferencesError when the shot
    cannot be done.
    """
    ctx = await _load(session, project)
    current = await _current(session, project, ctx)
    scene = next((entry for entry in current.entries if entry.item["id"] == scene_id), None)
    if scene is None:
        raise ShotReferencesError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    shot = next((entry for entry in scene.shots if entry.shot["id"] == shot_id), None)
    if shot is None:
        raise ShotReferencesError(
            f"There is no shot '{shot_id}' in the newest shot plan of the scene '{scene_id}'."
        )
    result = SelectResult(selected=[], skipped=[])
    if shot.status == "selected":
        result.skipped.append(
            Skipped(scene_id, shot_id, scene.item["title"], "Already chosen and up to date.")
        )
        return result
    if shot.blocked_reason is not None:
        raise ShotReferencesError(shot.blocked_reason)
    definitions = next(entry for entry in ctx.definitions.entries if entry.item["id"] == scene_id)
    definition = next(entry for entry in definitions.shots if entry.shot["id"] == shot_id)
    if await _use_model(session):
        job, created = await _queue(session, project, ctx, scene_id, definition)
        if created:
            result.queued.append(Queued(scene_id, shot_id, job.id))
        else:
            result.skipped.append(
                Skipped(scene_id, shot_id, scene.item["title"], "Already being chosen.")
            )
        return result
    row = await _add(session, project, ctx, scene_id, definition)
    await _commit(session)
    result.selected.append(Selected(scene_id, shot_id, row.version))
    return result


async def select_scene(session: AsyncSession, project: Project, scene_id: str) -> SelectResult:
    """Chooses the references of every shot of one scene that has none or an out of date
    manifest, and commits once (with the model, a job for each shot is queued instead). Raises
    ShotReferencesError for an unknown scene.
    """
    ctx = await _load(session, project)
    current = await _current(session, project, ctx)
    scene = next((entry for entry in current.entries if entry.item["id"] == scene_id), None)
    if scene is None:
        raise ShotReferencesError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    result = SelectResult(selected=[], skipped=[])
    await _select_entries(session, project, ctx, scene, result, await _use_model(session))
    await _commit(session)
    return result


async def select_all(session: AsyncSession, project: Project) -> SelectResult:
    """Chooses the references of every shot, in every scene, that has none or an out of date
    manifest, and commits once (with the model, a job for each shot is queued instead). A shot
    that cannot be done is skipped with the reason. Raises ShotReferencesError when nothing can
    be done yet.
    """
    ctx = await _load(session, project)
    if ctx.definitions.blocked_reason is not None:
        raise ShotReferencesError(ctx.definitions.blocked_reason)
    current = await _current(session, project, ctx)
    use_model = await _use_model(session)
    result = SelectResult(selected=[], skipped=[])
    for scene in current.entries:
        await _select_entries(session, project, ctx, scene, result, use_model)
    await _commit(session)
    return result


async def select_if_ready(
    session: AsyncSession, project_id: int, scene_id: str, shot_id: str
) -> bool:
    """Chooses the references of this shot when it is defined and has no current manifest;
    commits. Returns whether a manifest was made **now**: with the language model choosing, the
    job is queued and this returns False (the job plans the shot's request when it is done).
    Called after every `define_shot` job; a shot that cannot be done is logged and left for the
    user's **Select references**.
    """
    project = await session.get(Project, project_id)
    if project is None:
        return False
    try:
        result = await select_shot(session, project, scene_id, shot_id)
    except ShotReferencesError as exc:
        _logger.info(
            "shot '%s' of scene '%s' of project %d: references not chosen by themselves: %s",
            shot_id,
            scene_id,
            project_id,
            exc,
        )
        return False
    if result.queued:
        _wake()
    return bool(result.selected)
