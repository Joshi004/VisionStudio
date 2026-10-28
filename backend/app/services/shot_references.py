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

import hashlib
import json
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
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    look_state_resolution,
    provenance,
    reference_selection,
    scene_definitions,
    shot_definitions,
)
from app.services.project_kinds import KIND_EXPLAINER
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

# Who made a manifest: code or the language model (a manifest the fixed rule chose has no job),
# or the user's own choice (PHASE-038).
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"
MANUAL_REPLACE_MESSAGE: Final = (
    "The newest references of this shot were chosen by you. Choosing them again replaces them "
    "with the choice of the fixed rule or the model, so it has to be confirmed."
)
SKIPPED_MANUAL: Final = "Chosen by you: use this shot's own button to replace it."

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

    @property
    def needs_confirmation(self) -> bool:
        """The newest manifest was chosen by the user: the fixed rule or the model replaces it
        only when asked (PHASE-038).
        """
        return self.row is not None and self.row.source == SOURCE_MANUAL


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
    found.extend(_view_pictures(version.views, state_slug, state_description))
    return found


def _view_pictures(
    views: Any, state_slug: str | None, state_description: str | None
) -> list[tuple[int, str, str, bool, str | None]]:
    """The pictures of the environment's other views that the pinned version froze (PHASE-054):
    each view's own picture under the `view` of its slug, and its picture in the resolved state
    when the scene has one and the view has been made in it. The master picture stays the view
    `environment` (the `establishing` view).
    """
    default = _is_default(state_slug)
    found: list[tuple[int, str, str, bool, str | None]] = []
    for view in views or []:
        if not isinstance(view, dict) or not isinstance(view.get("slug"), str):
            continue
        slug = view["slug"]
        if isinstance(view.get("reference_image_id"), int):
            found.append(
                (
                    view["reference_image_id"],
                    slug,
                    reference_selection.DEFAULT_VARIANT,
                    default,
                    None,
                )
            )
        if default:
            continue
        for entry in view.get("states") or []:
            if (
                isinstance(entry, dict)
                and entry.get("slug") == state_slug
                and isinstance(entry.get("reference_image_id"), int)
            ):
                found.append(
                    (entry["reference_image_id"], slug, str(state_slug), True, state_description)
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
        artifacts.append(_artifact(CHARACTER_KIND, character_id, current, slug, pictures))

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
    artifacts.append(_artifact(ENVIRONMENT_KIND, environment_id, environment, state_slug, pictures))

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


def _signature(pictures: list[tuple[int, str, str, bool, str | None]]) -> str:
    """A hash of the pictures a subject offers for one look or state: which picture is there
    for each view and variant. It changes when one of them is made again and not when the pin
    moves for another reason (a new voice), which is what makes a manifest narrow (PHASE-039).
    """
    ids = sorted((variant, view, image_id) for image_id, view, variant, _r, _t in pictures)
    text = json.dumps(ids, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _artifact(
    kind: str,
    discovery_id: str,
    current: scene_definitions.CurrentDefinition,
    variant: str | None,
    pictures: list[tuple[int, str, str, bool, str | None]],
) -> dict[str, Any]:
    """The record of the pinned definition a manifest was built from, in the artifact shape of
    D-3. `variant` is the slug of the look or state the scene resolved to (None for the
    default) and `pictures_sha256` the hash of the pictures it offered (PHASE-039).
    """
    return {
        "kind": kind,
        "id": current.library_id,
        "version": current.version,
        "discovery_id": discovery_id,
        "name": current.name,
        "variant": variant,
        "pictures_sha256": _signature(pictures),
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


_Signatures = dict[tuple[str, str, str | None], str | None]


def _resolved_variants(ctx: _Context, scene_id: str) -> dict[tuple[str, str], str | None] | None:
    """The look or state the scene resolves to now, by `(kind, discovery id)`: the slug of the
    named look or state, None for the default. None when the scene is not resolved.
    """
    resolved = next((scene for scene in ctx.resolution.scenes if scene.scene_id == scene_id), None)
    if resolved is None or not resolved.resolved:
        return None
    variants: dict[tuple[str, str], str | None] = {
        (CHARACTER_KIND, look.subject_id): look.id if look.how != "default" else None
        for look in resolved.looks
    }
    if resolved.environment is not None:
        environment = resolved.environment
        variants[(ENVIRONMENT_KIND, environment.subject_id)] = (
            environment.id if environment.how != "default" else None
        )
    return variants


def _out_of_date_reasons(
    row: ShotReferenceManifest,
    entry: shot_definitions.ShotEntry,
    ctx: _Context,
    scene_id: str,
    signatures: _Signatures,
) -> list[str]:
    """Why a manifest made for this shot is no longer current, one sentence each.

    A manifest that recorded the look or state and the pictures of each subject it used
    (PHASE-039) is judged by those: only a change to the look or state the scene resolves to
    for this shot's subjects, or to the pictures they offer, makes it out of date. An older
    manifest is judged by the resolution row and the pinned version, as before.
    """
    reasons: list[str] = []
    recorded = _recorded(row.inputs, SHOT_DEFINITION_KIND)
    if entry.row is None:
        reasons.append("The shot has no definition now.")
    elif not provenance.same_row(recorded, entry.row):
        reasons.append("The shot was defined again since its references were chosen.")
    elif entry.status == "out_of_date":
        reasons.append("The definition of the shot is out of date.")

    subjects = [
        artifact
        for artifact in _artifacts(row.inputs)
        if isinstance(artifact, dict) and artifact.get("kind") in (CHARACTER_KIND, ENVIRONMENT_KIND)
    ]
    narrow = bool(subjects) and all("pictures_sha256" in artifact for artifact in subjects)

    newest = ctx.resolution.version
    recorded_resolution = _recorded(row.inputs, RESOLUTION_KIND)
    variants = _resolved_variants(ctx, scene_id) if narrow else None
    if newest is None:
        reasons.append("The looks and states are no longer resolved.")
    elif narrow:
        if variants is None:
            reasons.append("The scene is no longer part of the resolved looks and states.")
    elif not provenance.same_row(recorded_resolution, newest):
        reasons.append("The looks and states were resolved again since the references were chosen.")

    for artifact in subjects:
        kind = artifact["kind"]
        discovery_id = artifact.get("discovery_id")
        name = artifact.get("name") or discovery_id
        current = ctx.current.get((kind, discovery_id))
        if current is None:
            reasons.append(f"'{name}' is no longer linked and defined.")
        elif current.library_id != artifact.get("id"):
            reasons.append(f"'{name}' is now linked to something else.")
        elif not narrow:
            if current.version != artifact.get("version"):
                reasons.append(
                    f"'{name}' changed (its pictures may be new) since the references were chosen."
                )
        else:
            if variants is not None and variants.get((kind, discovery_id)) != artifact.get(
                "variant"
            ):
                reasons.append(
                    f"The look or state of '{name}' in this scene changed since the "
                    "references were chosen."
                )
            elif signatures.get((kind, discovery_id, artifact.get("variant"))) != artifact.get(
                "pictures_sha256"
            ):
                reasons.append(
                    f"The pictures of '{name}' changed since the references were chosen."
                )
    return reasons


async def _signatures(
    session: AsyncSession, ctx: _Context, rows: dict[str, ShotReferenceManifest]
) -> _Signatures:
    """The signature of the pictures each recorded subject offers now, by `(kind, discovery id,
    variant)`, for every manifest that recorded one. None for a subject that cannot be read.
    """
    found: _Signatures = {}
    for row in rows.values():
        for artifact in _artifacts(row.inputs):
            if (
                not isinstance(artifact, dict)
                or artifact.get("kind") not in (CHARACTER_KIND, ENVIRONMENT_KIND)
                or "pictures_sha256" not in artifact
            ):
                continue
            kind, discovery_id = artifact["kind"], artifact.get("discovery_id")
            variant = artifact.get("variant")
            key = (kind, discovery_id, variant)
            if key in found:
                continue
            current = ctx.current.get((kind, discovery_id))
            found[key] = None
            if current is None:
                continue
            try:
                if kind == CHARACTER_KIND:
                    group = await _character_pictures(session, current, variant, None)
                else:
                    group = await _environment_pictures(session, current, variant, None)
            except ShotReferencesError:
                continue
            found[key] = _signature(group)
    return found


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
    rows = await _newest_rows(session, project.id)
    return _build(
        ctx,
        rows,
        await _newest_jobs(session, project.id),
        await _signatures(session, ctx, rows),
    )


def _build(
    ctx: _Context,
    rows: dict[str, ShotReferenceManifest],
    jobs: dict[str, Job],
    signatures: _Signatures,
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
                reasons = _out_of_date_reasons(row, entry, ctx, scene.item["id"], signatures)
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


@memoized_state
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
    catalog: list[CatalogPicture] = []
    artifacts: list[dict[str, Any]] = []
    try:
        if _is_broll(project, definition.content):
            selection = reference_selection.broll(definition.content)
        else:
            catalog, artifacts = await _catalog(session, ctx, scene_id, definition.content)
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


def _is_broll(project: Project, definition_content: dict[str, Any]) -> bool:
    """Whether the shot is B-roll of an explainer (EXPLAINER-005): it shows no character, so it
    has no reference picture, not even the set's, and goes to the video model's text route.
    """
    return project.kind == KIND_EXPLAINER and not reference_selection.visible_characters(
        definition_content
    )


def _content_of(entry: shot_definitions.ShotEntry) -> dict[str, Any]:
    """The specification of a shot whose callers refused a missing one."""
    assert entry.row is not None
    return entry.row.content


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
    source: str = SOURCE_AI,
) -> ShotReferenceManifest:
    """Adds the shot's next manifest. Flushes but does not commit: the caller commits (a
    selection job together with finishing itself, so a job is never "succeeded" without its
    result).

    `method` is how the pictures were chosen (`deterministic`, `llm` or `manual`).
    `fallback_reason` says why the fixed rule was used when the model was meant to choose, else
    None. `source` is `manual` for the user's own choice (`save_manual`).
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
        source=source,
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
    confirm_replace_manual: bool = False,
) -> None:
    """Chooses the references of every shot of the scene that has none or an out of date
    manifest, adding to `result`: by the fixed rule now, or with `use_model` by queuing a job for
    the language model. A shot that cannot be done is skipped with the reason. A manifest the
    user chose is left as it is, with the reason, unless `confirm_replace_manual` is true
    (PHASE-038).
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
        elif shot.needs_confirmation and not confirm_replace_manual:
            result.skipped.append(Skipped(scene_id, shot_id, title, SKIPPED_MANUAL))
        elif shot.blocked_reason is not None:
            result.skipped.append(Skipped(scene_id, shot_id, title, shot.blocked_reason))
        elif use_model and not _is_broll(project, _content_of(by_id[shot_id])):
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


def _find_shot(
    current: ShotReferencesState, scene_id: str, shot_id: str
) -> tuple[SceneEntry, ShotEntry]:
    """The scene and the shot of the state. Raises ShotReferencesError for an unknown one."""
    scene = next((entry for entry in current.entries if entry.item["id"] == scene_id), None)
    if scene is None:
        raise ShotReferencesError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    shot = next((entry for entry in scene.shots if entry.shot["id"] == shot_id), None)
    if shot is None:
        raise ShotReferencesError(
            f"There is no shot '{shot_id}' in the newest shot plan of the scene '{scene_id}'."
        )
    return scene, shot


async def select_shot(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    shot_id: str,
    *,
    confirm_replace_manual: bool = False,
) -> SelectResult:
    """Chooses the references of one shot and commits: by the fixed rule now, or, when the
    setting says the language model chooses, by queuing its job. A manifest that is current
    already is not made again (the answer says so). A manifest the user chose is replaced only
    when `confirm_replace_manual` is true (PHASE-038). Raises ShotReferencesError when the shot
    cannot be done.
    """
    ctx = await _load(session, project)
    current = await _current(session, project, ctx)
    scene, shot = _find_shot(current, scene_id, shot_id)
    result = SelectResult(selected=[], skipped=[])
    if shot.status == "selected":
        result.skipped.append(
            Skipped(scene_id, shot_id, scene.item["title"], "Already chosen and up to date.")
        )
        return result
    if shot.blocked_reason is not None:
        raise ShotReferencesError(shot.blocked_reason)
    if shot.needs_confirmation and not confirm_replace_manual:
        raise ShotReferencesError(MANUAL_REPLACE_MESSAGE)
    definitions = next(entry for entry in ctx.definitions.entries if entry.item["id"] == scene_id)
    definition = next(entry for entry in definitions.shots if entry.shot["id"] == shot_id)
    if await _use_model(session) and not _is_broll(project, _content_of(definition)):
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
    manifest, and commits once (with the model, a job for each shot is queued instead). A
    manifest the user chose is left as it is. Raises ShotReferencesError for an unknown scene.
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


async def select_all(
    session: AsyncSession, project: Project, *, confirm_replace_manual: bool = False
) -> SelectResult:
    """Chooses the references of every shot, in every scene, that has none or an out of date
    manifest, and commits once (with the model, a job for each shot is queued instead). A shot
    that cannot be done is skipped with the reason. A manifest the user chose is left as it is,
    unless `confirm_replace_manual` is true (the pipeline's "Allow overwrite", PHASE-038). Raises
    ShotReferencesError when nothing can be done yet.
    """
    ctx = await _load(session, project)
    if ctx.definitions.blocked_reason is not None:
        raise ShotReferencesError(ctx.definitions.blocked_reason)
    current = await _current(session, project, ctx)
    use_model = await _use_model(session)
    result = SelectResult(selected=[], skipped=[])
    for scene in current.entries:
        await _select_entries(
            session, project, ctx, scene, result, use_model, confirm_replace_manual
        )
    await _commit(session)
    return result


async def accept_as_is(
    session: AsyncSession, project: Project, scene_id: str, shot_id: str
) -> ShotReferenceManifest:
    """Keeps the shot's newest choice of pictures as it is and records that it was made from
    what is current now (PHASE-039). Refused when one of the pictures is not one the shot can
    use now (choose the references again then). Raises ShotReferencesError.
    """
    newest = (await _newest_rows(session, project.id)).get(_key(scene_id, shot_id))
    if newest is None:
        raise ShotReferencesError(f"Shot '{shot_id}' has no references to accept.")
    image_ids = [reference["lab_image_id"] for reference in newest.content["references"]]
    return await save_manual(session, project, scene_id, shot_id, image_ids, accepting=newest)


async def save_manual(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    shot_id: str,
    image_ids: list[int],
    *,
    accepting: ShotReferenceManifest | None = None,
) -> ShotReferenceManifest:
    """Stores the user's choice of pictures for one shot, in the order given, as its next
    manifest (`source` is `manual`, `method` is `manual`), and commits (PHASE-038). It needs what
    a selection needs (the shot defined and current) and is refused while the references are
    being chosen. The pictures must be ones the shot can use now (`reference_selection.manual`)
    and the manifest records exactly what a selection would. With `accepting` (PHASE-039) it
    also records which version the user accepted as it is. Raises ShotReferencesError.

    What follows (the generation request, the prompt) is the caller's to start: see
    `services/shot_chain.py`.
    """
    ctx = await _load(session, project)
    current = await _current(session, project, ctx)
    _scene, shot = _find_shot(current, scene_id, shot_id)
    if shot.blocked_reason is not None:
        raise ShotReferencesError(shot.blocked_reason)
    definitions = next(entry for entry in ctx.definitions.entries if entry.item["id"] == scene_id)
    definition = next(entry for entry in definitions.shots if entry.shot["id"] == shot_id)
    definition_row = definition.row
    assert definition_row is not None  # a blocked shot was refused above
    catalog, artifacts = await _catalog(session, ctx, scene_id, definition_row.content)
    try:
        selection = reference_selection.manual(definition_row.content, catalog, image_ids)
    except reference_selection.ReferenceSelectionError as exc:
        raise ShotReferencesError(str(exc)) from exc
    row = await save_manifest(
        session,
        project_id=project.id,
        scene_id=scene_id,
        shot_id=shot_id,
        shot_definition_id=definition_row.id,
        selection=selection,
        catalog=catalog,
        method=reference_selection.METHOD_MANUAL,
        fallback_reason=None,
        job_id=None,
        inputs=_inputs(project.id, scene_id, shot_id, definition_row, ctx, artifacts),
        source=SOURCE_MANUAL,
    )
    if accepting is not None:
        row.inputs = provenance.accepted_inputs(row.inputs, accepting, row.content)
    await _commit(session)
    return row


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
