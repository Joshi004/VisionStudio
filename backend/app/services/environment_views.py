"""The views of the environments of a story project (PHASE-052, `Path_ahead.md` Section 46).

A place's master picture shows it from one camera. Once every scene is staged
(`scene_staging`), each environment gets a **view plan**: a `plan_environment_views` job reads
the backgrounds the scenes need and answers which views to reuse, which to add and which views
cover each background of each scene. `save_plan` stores it as a new `environment_view_plan` row
(a project artifact, D-3) and adds a library `environment_view` row for every new view, which is
a view of the **library environment**, like a state: the plan reuses what the library has and
adds the rest.

**Pictures.** A view picture is an edit of the master picture, made in two steps:

1. A `write_environment_view_prompt` job writes the edit prompt (`environment_view_prompt_writer`)
   and calls `on_prompt_written`, which starts a Qwen edit run whose references are the master
   picture, and, for a `behind` view, the finished left and right views too (the edges of the
   space behind the master camera).
2. When the picture is stored (`on_view_image_stored`, called by the image job) it becomes the
   view's picture, and the environment gets a new version that freezes it (`views`), exactly as
   a state's picture does; the project's pin moves to it when it still pointed at the newest
   version (`pin_next_version`).

A `behind` view waits for the left and right views of its plan, and is started by
`on_view_image_stored` when they are ready. The pipeline makes one candidate per view (D-5);
`remake_view` makes a view again, from the lab or from the project.

`state` is what the story workspace shows. **Everything is worked out on every read** and never
stored (D-3): the plan is out of date when a staging row it was built from, the environment's
definition or the master picture changed; a view picture is out of date when its master picture
was replaced since.

This module creates rows and jobs. It never calls the GPU server or the language model itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import (
    EnvironmentState,
    EnvironmentView,
    EnvironmentViewPlan,
    EnvironmentViewState,
    Job,
    LabImage,
    LabRun,
    LibraryEnvironment,
    LibraryEnvironmentVersion,
    Project,
    ProjectEnvironmentLink,
    SceneStaging,
)
from app.db.session import SessionLocal
from app.db.state_memo import memoized_state
from app.db.types import utcnow
from app.jobs import store
from app.services import (
    environment_references,
    environment_versions,
    image_lab,
    library_adoption,
    provenance,
    scene_definition_writer,
    scene_definitions,
    scene_staging,
)
from app.services import environment_view_planner as planner
from app.services import image_models as image_models_service
from app.services.image_lab import LabInputError, QwenEditForm, Ref
from app.services.image_models import IMAGE_MODE_KEY

_logger = logging.getLogger(__name__)

PLAN_JOB: Final = "plan_environment_views"
PROMPT_JOB: Final = "write_environment_view_prompt"
# Two presses on one environment make one job; two environments run side by side.
PLAN_DEDUPE_KEY: Final = "discovery_id"
PROMPT_DEDUPE_KEY: Final = "view_id"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"

ENVIRONMENT_KIND: Final = scene_definitions.ENVIRONMENT_DEFINITION_KIND
STAGING_KIND: Final = "scene_staging"

# How many of a project's newest plan jobs are read to find each environment's newest one.
_JOB_LOOKBACK: Final = 500
_DEAD_JOB_STATUSES: Final = ("failed", "cancelled")

# `not_planned`: no plan was written for this environment. `planned`: written, and nothing it
# was built from has changed. `out_of_date`: written, and something it was built from changed.
PlanStatus = Literal["not_planned", "planned", "out_of_date"]
# `none`: no picture yet and none being made. `in_progress`: being made (`stage` says where).
# `failed`: the last attempt did not work. `ready`: the picture exists.
ViewStatus = Literal["none", "in_progress", "failed", "ready"]
Stage = Literal["writing_prompt", "drawing", "waiting"]


class EnvironmentViewError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class SceneNeed:
    """What one scene asks of the environment it is set in: the background sides behind its
    characters (at the start and after every move) and behind the group.
    """

    scene_id: str
    title: str
    background_sides: list[str]
    group_side: str
    characters: list[dict[str, Any]]
    # The newest staging, and whether it is current.
    staging: SceneStaging
    staged: bool

    def for_model(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "title": self.title,
            "background_sides": self.background_sides,
            "group_side": self.group_side,
            "characters": self.characters,
        }


@dataclass(frozen=True)
class StatePicture:
    """The picture of a view in one named state of its environment (PHASE-053)."""

    slug: str
    name: str
    image: LabImage


@dataclass
class ViewItem:
    """One view of an environment's plan (or of the lab) and where its picture stands."""

    view: EnvironmentView
    status: ViewStatus
    stage: Stage | None = None
    error: str | None = None
    image: LabImage | None = None
    # The titles of the scenes whose backgrounds it covers, in story order.
    scenes: list[str] = field(default_factory=list)
    # Why a ready picture is out of date, one sentence each.
    reasons: list[str] = field(default_factory=list)
    # A `behind` view waits for the left and right views of its plan.
    waiting: bool = False
    reused: bool = False
    # The view's pictures in the environment's states (PHASE-053) that exist.
    states: list[StatePicture] = field(default_factory=list)


@dataclass
class EnvironmentEntry:
    """One discovered environment that scenes are set in, and where its views stand."""

    discovery_id: str
    name: str
    library_id: int | None
    status: PlanStatus
    reasons: list[str]
    plan: EnvironmentViewPlan | None
    job: Job | None
    scenes: list[str]
    views: list[ViewItem]
    can_plan: bool
    plan_blocked_reason: str | None
    can_make_pictures: bool
    pictures_blocked_reason: str | None
    master_image_id: int | None
    # What the plan is made from: the scenes' needs and the environment as it stands now.
    needs: list[SceneNeed] = field(default_factory=list)
    current: scene_definitions.CurrentDefinition | None = None

    @property
    def pictures_status(self) -> ViewStatus:
        """The pictures of the plan's views taken together. A plan with no views besides the
        implicit `establishing` one (the master picture) has nothing to draw: it is ready.
        """
        if not self.views:
            if self.plan is not None and not self.plan.content["views"]:
                return "ready"
            return "none"
        statuses = {item.status for item in self.views}
        if statuses == {"ready"}:
            return "ready"
        if "in_progress" in statuses or any(item.waiting for item in self.views):
            return "in_progress"
        if "failed" in statuses:
            return "failed"
        return "none"


@dataclass(frozen=True)
class ViewsState:
    """What the story workspace shows. `blocked_reason` is why nothing can be planned at all."""

    entries: list[EnvironmentEntry]
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    discovery_id: str
    name: str
    reason: str


@dataclass(frozen=True)
class StartAllResult:
    job_ids: list[int]
    skipped: list[Skipped]


@dataclass(frozen=True)
class PicturesResult:
    """What `start_pictures` did: the views it started, and the ones that wait for others."""

    started: list[int]
    waiting: list[int]


# --- What the scenes need -----------------------------------------------------------------


def _need_for(entry: scene_staging.SceneEntry, characters: dict[str, str]) -> SceneNeed | None:
    """The background sides a scene's newest staging asks of its environment, or None when the
    scene has no staging.
    """
    row = entry.row
    if row is None:
        return None
    content = row.content
    placements = content.get("placements", [])
    moves = content.get("moves", [])
    sides = {item["background_side"] for item in placements}
    sides.update(item["background_side"] for item in moves)
    return SceneNeed(
        scene_id=entry.item["id"],
        title=str(entry.item.get("title", entry.item["id"])),
        background_sides=[side for side in planner.SIDES if side in sides],
        group_side=content["group_side"],
        characters=[
            {
                "character": characters.get(item["character_id"], item["character_id"]),
                "zone": item["zone"],
                "background_side": item["background_side"],
            }
            for item in placements
        ],
        staging=row,
        staged=entry.status == "staged",
    )


async def _needs_by_environment(
    session: AsyncSession, project: Project
) -> tuple[dict[str, list[SceneNeed]], dict[str, list[str]], str | None]:
    """The scenes' needs grouped by the discovered environment they are set in, in story order;
    the titles of the scenes of each environment that have no current staging; and why staging
    is blocked for the whole project (or None).
    """
    staging = await scene_staging.state(session, project)
    names = {item["id"]: item["name"] for item in staging.characters}
    grouped: dict[str, list[SceneNeed]] = {}
    missing: dict[str, list[str]] = {}
    for entry in staging.entries:
        if entry.environment_id is None:
            continue
        grouped.setdefault(entry.environment_id, [])
        need = _need_for(entry, names)
        if need is not None:
            grouped[entry.environment_id].append(need)
        if entry.status != "staged":
            missing.setdefault(entry.environment_id, []).append(
                str(entry.item.get("title", entry.item["id"]))
            )
    return grouped, missing, staging.blocked_reason


# --- Pictures of one view -----------------------------------------------------------------


async def _view_progress(
    session: AsyncSession, view: EnvironmentView
) -> tuple[ViewStatus, Stage | None, str | None, LabImage | None]:
    """Where a view's picture stands: ready (its image), not started, being written or drawn,
    or failed with the reason.
    """
    if view.reference_image_id is not None:
        return "ready", None, None, await session.get(LabImage, view.reference_image_id)
    if view.lab_run_id is None:
        job = await session.get(Job, view.prompt_job_id) if view.prompt_job_id else None
        if job is None:
            return "none", None, None, None
        if job.status in store.ACTIVE_STATUSES:
            return "in_progress", "writing_prompt", None, None
        if job.status in _DEAD_JOB_STATUSES:
            reason = job.error or (
                "The prompt was cancelled." if job.status == "cancelled" else "The prompt failed."
            )
            return "failed", None, f"The prompt could not be written: {reason}", None
        return "failed", None, "The prompt was written but the picture was not started.", None
    run = await session.get(LabRun, view.lab_run_id)
    if run is None:
        return "failed", None, "The picture's run is gone. Make it again.", None
    images = await image_lab.images_by_run(session, [run.id])
    if images.get(run.id):
        return (
            "failed",
            None,
            "The picture was made but could not be attached to the view. Make it again.",
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


def _waiting(view: EnvironmentView) -> bool:
    inputs = view.inputs if isinstance(view.inputs, dict) else {}
    return bool(inputs.get("waiting")) and view.reference_image_id is None


def _stale_reasons(view: EnvironmentView, master_image_id: int | None) -> list[str]:
    """Why a view's picture is out of date: it was edited from a master picture that was
    replaced since.
    """
    inputs = view.inputs if isinstance(view.inputs, dict) else {}
    made_from = inputs.get("source_image_id")
    if (
        view.reference_image_id is not None
        and isinstance(made_from, int)
        and master_image_id is not None
        and made_from != master_image_id
    ):
        return ["The master picture was replaced since this view's picture was made."]
    return []


async def _view_item(
    session: AsyncSession,
    view: EnvironmentView,
    master_image_id: int | None,
    *,
    scenes: list[str] | None = None,
    reused: bool = False,
) -> ViewItem:
    status, stage, error, image = await _view_progress(session, view)
    waiting = _waiting(view)
    if waiting and status == "none":
        status, stage = "in_progress", "waiting"
    pictures = await session.execute(
        select(EnvironmentState, LabImage)
        .join(EnvironmentViewState, EnvironmentViewState.state_id == EnvironmentState.id)
        .join(LabImage, LabImage.id == EnvironmentViewState.reference_image_id)
        .where(EnvironmentViewState.view_id == view.id)
        .order_by(EnvironmentState.slug)
    )
    return ViewItem(
        view=view,
        status=status,
        stage=stage,
        error=error,
        image=image,
        scenes=scenes or [],
        reasons=_stale_reasons(view, master_image_id),
        waiting=waiting,
        reused=reused,
        states=[
            StatePicture(slug=state.slug, name=state.name, image=picture)
            for state, picture in pictures.all()
        ],
    )


async def views_of(session: AsyncSession, environment_id: int) -> list[EnvironmentView]:
    """Every view of a library environment, oldest first."""
    statement = (
        select(EnvironmentView)
        .where(EnvironmentView.environment_id == environment_id)
        .order_by(EnvironmentView.id)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars())


async def lab_items(session: AsyncSession, environment_id: int) -> list[ViewItem]:
    """The views of a library environment as the lab shows them, each judged against the master
    picture of the environment's newest version.
    """
    newest = await environment_versions.latest_version(session, environment_id)
    master = newest.reference_image_id if newest is not None else None
    return [
        await _view_item(session, view, master) for view in await views_of(session, environment_id)
    ]


# --- Reading the state --------------------------------------------------------------------


def _recorded(
    inputs: dict[str, Any], kind: str, scene_id: str | None = None
) -> dict[str, Any] | None:
    for artifact in inputs.get("artifacts") or []:
        if (
            isinstance(artifact, dict)
            and artifact.get("kind") == kind
            and (scene_id is None or artifact.get("scene_id") == scene_id)
        ):
            return artifact
    return None


def _plan_reasons(
    row: EnvironmentViewPlan,
    needs: list[SceneNeed],
    current: scene_definitions.CurrentDefinition | None,
    master_image_id: int | None,
) -> list[str]:
    """Why a plan is no longer current, one sentence each."""
    inputs = row.inputs
    reasons: list[str] = []
    if sorted(inputs.get("scene_ids") or []) != sorted(need.scene_id for need in needs):
        reasons.append("The scenes set in this place have changed.")
    for need in needs:
        recorded = _recorded(inputs, STAGING_KIND, need.scene_id)
        if not need.staged:
            reasons.append(f"The staging of '{need.title}' is out of date.")
        elif not provenance.same_row(recorded, need.staging):
            reasons.append(f"'{need.title}' has been staged again since this plan was made.")
    recorded_environment = _recorded(inputs, ENVIRONMENT_KIND)
    if recorded_environment is not None:
        name = recorded_environment.get("name") or recorded_environment.get("discovery_id")
        if current is None:
            reasons.append(f"{name} is now not linked or not defined.")
        else:
            if current.library_id != recorded_environment.get("id"):
                reasons.append(f"{name} is now linked to a different environment.")
            elif scene_definition_writer.definition_sha256(
                current.definition
            ) != recorded_environment.get("definition_sha256"):
                reasons.append(f"The definition of {name} has changed since this plan was made.")
            if recorded_environment.get("master_image_id") != master_image_id:
                reasons.append(
                    f"The master picture of {name} was replaced since this plan was made."
                )
    return reasons


async def newest_plans(session: AsyncSession, project_id: int) -> dict[str, EnvironmentViewPlan]:
    statement = (
        select(EnvironmentViewPlan)
        .where(EnvironmentViewPlan.project_id == project_id)
        .order_by(EnvironmentViewPlan.version.desc(), EnvironmentViewPlan.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, EnvironmentViewPlan] = {}
    for row in (await session.execute(statement)).scalars():
        newest.setdefault(row.discovery_id, row)
    return newest


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == PLAN_JOB)
        .order_by(Job.id.desc())
        .limit(_JOB_LOOKBACK)
        .execution_options(populate_existing=True)
    )
    newest: dict[str, Job] = {}
    for job in (await session.execute(statement)).scalars():
        key = job.input.get(PLAN_DEDUPE_KEY) if isinstance(job.input, dict) else None
        if isinstance(key, str) and key not in newest:
            newest[key] = job
    return newest


def _plan_refusal(
    current: scene_definitions.CurrentDefinition | None,
    master_image_id: int | None,
    unstaged: list[str],
    needs: list[SceneNeed],
) -> str | None:
    """Why this environment cannot be planned now, or None."""
    if current is None or current.definition is None:
        return "Link and define this environment first."
    if not isinstance(current.definition.get("spatial_plan"), dict):
        return (
            f"The definition of {current.name} has no spatial plan yet. Define the environment "
            "again first: it was written before spatial plans existed."
        )
    if master_image_id is None:
        return f"Make the master picture of {current.name} first: its views are edits of it."
    if unstaged:
        return f"Stage {', '.join(repr(title) for title in unstaged)} first."
    if not needs:
        return "No scene is set in this place."
    return None


async def _master_image_id(
    session: AsyncSession, current: scene_definitions.CurrentDefinition | None
) -> int | None:
    if current is None:
        return None
    version = await environment_versions.get_version(session, current.library_id, current.version)
    return version.reference_image_id if version is not None else None


@memoized_state
async def state(session: AsyncSession, project: Project) -> ViewsState:
    """The environments scenes are set in, each with its view plan and where its views stand.
    Worked out on every read; nothing here is stored.
    """
    needs_by_env, unstaged, blocked = await _needs_by_environment(session, project)
    if blocked is not None and not needs_by_env:
        return ViewsState([], blocked)
    current = await scene_definitions.current_definitions(session, project)
    plans = await newest_plans(session, project.id)
    jobs = await _newest_jobs(session, project.id)

    entries: list[EnvironmentEntry] = []
    for discovery_id, needs in needs_by_env.items():
        defined = current.get((ENVIRONMENT_KIND, discovery_id))
        master = await _master_image_id(session, defined)
        plan = plans.get(discovery_id)
        job = jobs.get(discovery_id)
        active = job is not None and job.status in store.ACTIVE_STATUSES

        status: PlanStatus = "not_planned"
        reasons: list[str] = []
        if plan is not None and isinstance(plan.inputs, dict):
            reasons = _plan_reasons(plan, needs, defined, master)
            status = "out_of_date" if reasons else "planned"

        items: list[ViewItem] = []
        if plan is not None and defined is not None:
            rows = {view.slug: view for view in await views_of(session, defined.library_id)}
            titles = {need.scene_id: need.title for need in needs}
            for planned in plan.content["views"]:
                view = rows.get(planned["id"])
                if view is None:
                    continue
                used_by = [
                    titles[scene["scene_id"]]
                    for scene in plan.content["scenes"]
                    if scene["scene_id"] in titles
                    and (
                        planned["id"] in scene["group"]
                        or any(planned["id"] in ids for ids in scene["by_side"].values())
                    )
                ]
                items.append(
                    await _view_item(
                        session, view, master, scenes=used_by, reused=bool(planned.get("reused"))
                    )
                )

        refusal = _plan_refusal(defined, master, unstaged.get(discovery_id, []), needs)
        plan_blocked = blocked or refusal
        if plan_blocked is None and active:
            plan_blocked = "The views are already being planned."
        pictures_blocked: str | None = None
        if status == "not_planned":
            pictures_blocked = "Plan the views first."
        elif status == "out_of_date":
            pictures_blocked = "The view plan is out of date. Plan the views again first."
        elif not any(item.status in ("none", "failed") and not item.waiting for item in items):
            pictures_blocked = "Every view has its picture or is being made."
        entries.append(
            EnvironmentEntry(
                discovery_id=discovery_id,
                name=defined.name if defined is not None else discovery_id,
                library_id=defined.library_id if defined is not None else None,
                status=status,
                reasons=reasons,
                plan=plan,
                job=job,
                scenes=[need.title for need in needs],
                views=items,
                can_plan=plan_blocked is None,
                plan_blocked_reason=plan_blocked,
                can_make_pictures=pictures_blocked is None,
                pictures_blocked_reason=pictures_blocked,
                master_image_id=master,
                needs=needs,
                current=defined,
            )
        )
    return ViewsState(entries, blocked)


def _find(result: ViewsState, discovery_id: str) -> EnvironmentEntry:
    for entry in result.entries:
        if entry.discovery_id == discovery_id:
            return entry
    raise EnvironmentViewError(f"No scene is set in an environment '{discovery_id}'.")


# --- Planning -----------------------------------------------------------------------------


def _existing_view(view: EnvironmentView) -> dict[str, Any]:
    return {
        "id": view.slug,
        "name": view.name,
        "side": view.side,
        "framing": view.framing,
        "zone": view.zone,
        "description": view.description,
    }


async def _prompt_of_image(session: AsyncSession, image_id: int | None) -> str | None:
    """The prompt the run that made a picture was started with, or None."""
    if image_id is None:
        return None
    image = await session.get(LabImage, image_id)
    run = await session.get(LabRun, image.run_id) if image is not None and image.run_id else None
    return run.prompt if run is not None and run.prompt else None


async def _queue_plan(
    session: AsyncSession, project: Project, entry: EnvironmentEntry
) -> tuple[Job, bool]:
    """Queues the planning job of one environment that `can_plan`, and returns
    `(job, created)`. Does not commit when it makes a job beyond `store.create_job`'s own.
    """
    scene_needs = entry.needs
    current = entry.current
    assert current is not None and current.definition is not None
    assert entry.master_image_id is not None and entry.library_id is not None

    reusable: list[dict[str, Any]] = []
    unusable: list[str] = []
    for view in await views_of(session, entry.library_id):
        inputs = view.inputs if isinstance(view.inputs, dict) else {}
        usable = view.reference_image_id is None or (
            inputs.get("source_image_id") == entry.master_image_id
        )
        if usable:
            reusable.append(_existing_view(view))
        else:
            unusable.append(view.slug)

    inputs = {
        "project_id": project.id,
        "discovery_id": entry.discovery_id,
        "scene_ids": [need.scene_id for need in scene_needs],
        "artifacts": [
            *(
                {
                    "kind": STAGING_KIND,
                    "id": need.staging.id,
                    "version": need.staging.version,
                    "scene_id": need.scene_id,
                }
                for need in scene_needs
            ),
            {
                "kind": ENVIRONMENT_KIND,
                "id": current.library_id,
                "version": current.version,
                "discovery_id": entry.discovery_id,
                "name": current.name,
                "definition_sha256": scene_definition_writer.definition_sha256(current.definition),
                "master_image_id": entry.master_image_id,
            },
        ],
    }
    zones = current.definition["spatial_plan"]["zones"]
    return await store.create_job(
        session,
        project_id=project.id,
        type=PLAN_JOB,
        provider="llm",
        input={
            "discovery_id": entry.discovery_id,
            "environment_id": current.library_id,
            "environment": {
                "id": entry.discovery_id,
                "name": current.name,
                "description": current.description,
                "definition": current.definition,
            },
            "master_prompt": await _prompt_of_image(session, entry.master_image_id),
            "scenes": [need.for_model() for need in scene_needs],
            "existing_views": reusable,
            "unusable_slugs": unusable,
            "zone_ids": [zone["id"] for zone in zones],
            # Written onto the plan the job makes (D-3).
            "inputs": inputs,
        },
        dedupe_key=PLAN_DEDUPE_KEY,
    )


async def start_plan(session: AsyncSession, project: Project, discovery_id: str) -> Job:
    """Queues the job that plans one environment's views, and commits. If that environment
    already has a job waiting or running, that job is returned. Raises EnvironmentViewError.
    """
    entry = _find(await state(session, project), discovery_id)
    if entry.plan_blocked_reason is not None and not (
        entry.job is not None and entry.job.status in store.ACTIVE_STATUSES
    ):
        raise EnvironmentViewError(entry.plan_blocked_reason)
    job, _created = await _queue_plan(session, project, entry)
    return job


async def start_plan_all(session: AsyncSession, project: Project) -> StartAllResult:
    """Queues a plan for every environment that is not planned and current, can be planned and
    is not being planned, and commits each. Raises EnvironmentViewError when scenes cannot be
    read yet.
    """
    result = await state(session, project)
    if result.blocked_reason is not None and not result.entries:
        raise EnvironmentViewError(result.blocked_reason)
    job_ids: list[int] = []
    skipped: list[Skipped] = []
    for entry in result.entries:
        if entry.status == "planned":
            skipped.append(Skipped(entry.discovery_id, entry.name, "Already planned."))
        elif not entry.can_plan:
            skipped.append(Skipped(entry.discovery_id, entry.name, entry.plan_blocked_reason or ""))
        else:
            job, created = await _queue_plan(session, project, entry)
            if created:
                job_ids.append(job.id)
    return StartAllResult(job_ids, skipped)


async def save_plan(
    session: AsyncSession,
    *,
    project_id: int,
    discovery_id: str,
    library_id: int,
    content: dict[str, Any],
    job_id: int | None,
    inputs: dict[str, Any],
    source: str = SOURCE_AI,
) -> EnvironmentViewPlan:
    """Adds the environment's next plan, and a library view for every new view of it. Flushes
    but does not commit: the job commits it together with finishing itself. Raises
    EnvironmentViewError when a new view's slug is taken meanwhile.
    """
    newest = (
        await session.execute(
            select(func.max(EnvironmentViewPlan.version)).where(
                EnvironmentViewPlan.project_id == project_id,
                EnvironmentViewPlan.discovery_id == discovery_id,
            )
        )
    ).scalar()
    version = (newest or 0) + 1
    taken = {view.slug: view for view in await views_of(session, library_id)}
    stored: dict[str, Any] = {**content, "views": []}
    for planned in content["views"]:
        view = taken.get(planned["id"])
        if planned.get("reused"):
            if view is None:
                raise EnvironmentViewError(f"The view '{planned['id']}' no longer exists.")
        else:
            if view is not None:
                raise EnvironmentViewError(f"The view id '{planned['id']}' is taken meanwhile.")
            view = EnvironmentView(
                environment_id=library_id,
                slug=planned["id"],
                name=planned["name"],
                side=planned["side"],
                framing=planned["framing"],
                zone=planned["zone"],
                description=planned["description"],
                source=source,
                origin_project_id=project_id,
                job_id=job_id,
            )
            session.add(view)
            await session.flush()
        stored["views"].append({**planned, "view_id": view.id})
    row = EnvironmentViewPlan(
        project_id=project_id,
        discovery_id=discovery_id,
        version=version,
        source=source,
        job_id=job_id,
        inputs=inputs,
        content=stored,
    )
    session.add(row)
    await session.flush()
    return row


# --- Making pictures ----------------------------------------------------------------------


def _side_texts(
    definition: dict[str, Any] | None, view: EnvironmentView
) -> tuple[str | None, str | None]:
    """The text of the view's side of the spatial plan, and the text of its zone."""
    plan = definition.get("spatial_plan") if isinstance(definition, dict) else None
    if not isinstance(plan, dict):
        return None, None
    sides = plan.get("sides") if isinstance(plan.get("sides"), dict) else {}
    side_text = sides.get(view.side)
    zone_text = None
    for zone in plan.get("zones") or []:
        if isinstance(zone, dict) and zone.get("id") == view.zone:
            zone_text = f"{zone.get('name', '')}: {zone.get('description', '')}".strip(": ")
    return (side_text if isinstance(side_text, str) else None), zone_text


async def _neighbour_images(
    session: AsyncSession, environment_id: int, master_image_id: int
) -> tuple[int | None, int | None]:
    """The pictures of the first finished left view and right view made from this master."""
    found: dict[str, int | None] = {"left": None, "right": None}
    for view in await views_of(session, environment_id):
        inputs = view.inputs if isinstance(view.inputs, dict) else {}
        if (
            view.side in found
            and found[view.side] is None
            and view.reference_image_id is not None
            and inputs.get("source_image_id") == master_image_id
        ):
            found[view.side] = view.reference_image_id
    return found["left"], found["right"]


async def _queue_prompt(
    session: AsyncSession,
    view: EnvironmentView,
    *,
    version: LibraryEnvironmentVersion,
    provenance_inputs: dict[str, Any],
    project_id: int | None,
) -> Job:
    """Clears the view's picture, writes down what it will be made from and queues the job
    that writes its prompt, and commits. `version` is the environment version whose master
    picture and definition the view is made from.
    """
    master_id = version.reference_image_id
    if master_id is None:
        raise EnvironmentViewError("The environment has no master picture to edit.")
    left_id, right_id = await _neighbour_images(session, view.environment_id, master_id)
    side_text, zone_text = _side_texts(version.definition, view)
    view.reference_image_id = None
    view.lab_run_id = None
    view.prompt = None
    view.inputs = {
        **provenance_inputs,
        "master_version": version.version,
        "source_image_id": master_id,
    }
    await session.flush()
    job, _created = await store.create_job(
        session,
        project_id=project_id,
        type=PROMPT_JOB,
        provider="llm",
        input={
            "view_id": view.id,
            "environment_id": view.environment_id,
            "master_image_id": master_id,
            "left_image_id": left_id if view.side == "behind" else None,
            "right_image_id": right_id if view.side == "behind" else None,
            "side_text": side_text,
            "zone_text": zone_text,
        },
        commit=False,
        dedupe_key=PROMPT_DEDUPE_KEY,
    )
    view.prompt_job_id = job.id
    await session.commit()
    _logger.info("environment view %d: prompt job %d queued", view.id, job.id)
    return job


def _provenance(
    project: Project | None, discovery_id: str | None, plan_version: int | None
) -> dict[str, Any]:
    if project is None:
        return {}
    return {"project_id": project.id, "discovery_id": discovery_id, "plan_version": plan_version}


async def _siblings_ready(
    session: AsyncSession, environment_id: int, plan: EnvironmentViewPlan, master_image_id: int
) -> bool:
    """Whether every left and right view of the plan has its picture, made from this master."""
    rows = {view.slug: view for view in await views_of(session, environment_id)}
    for planned in plan.content["views"]:
        if planned["side"] not in ("left", "right"):
            continue
        view = rows.get(planned["id"])
        inputs = view.inputs if view is not None and isinstance(view.inputs, dict) else {}
        if (
            view is None
            or view.reference_image_id is None
            or inputs.get("source_image_id") != master_image_id
        ):
            return False
    return True


async def start_pictures(
    session: AsyncSession, project: Project, discovery_id: str
) -> PicturesResult:
    """Starts the picture of every view of the environment's plan that has none and is not being
    made, and commits. A `behind` view waits until the left and right views of the plan are
    ready (`on_view_image_stored` then starts it). Raises EnvironmentViewError.
    """
    entry = _find(await state(session, project), discovery_id)
    if not entry.can_make_pictures or entry.plan is None or entry.library_id is None:
        raise EnvironmentViewError(entry.pictures_blocked_reason or "Pictures cannot be made now.")
    link = await _link_of(session, project.id, discovery_id)
    version = await environment_versions.get_version(
        session, entry.library_id, link.pinned_version if link is not None else 0
    )
    if version is None or version.reference_image_id is None:
        raise EnvironmentViewError("The environment has no master picture to edit.")
    provenance_inputs = _provenance(project, discovery_id, entry.plan.version)
    started: list[int] = []
    waiting: list[int] = []
    for item in entry.views:
        if item.status not in ("none", "failed") or item.waiting:
            continue
        view = item.view
        if view.side == "behind" and not await _siblings_ready(
            session, entry.library_id, entry.plan, version.reference_image_id
        ):
            view.inputs = {
                **provenance_inputs,
                "master_version": version.version,
                "source_image_id": version.reference_image_id,
                "waiting": True,
            }
            waiting.append(view.id)
            continue
        await _queue_prompt(
            session,
            view,
            version=version,
            provenance_inputs=provenance_inputs,
            project_id=project.id,
        )
        started.append(view.id)
    await session.commit()
    return PicturesResult(started=started, waiting=waiting)


async def _link_of(
    session: AsyncSession, project_id: int, discovery_id: str
) -> ProjectEnvironmentLink | None:
    return (
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


async def remake_view(session: AsyncSession, view_id: int, project: Project | None = None) -> Job:
    """Makes one view's picture again, and commits. From the lab (`project` None) the view is
    edited from the master picture of the environment's newest version; from a project, from
    the version the project pins. Raises EnvironmentViewError.
    """
    view = await session.get(EnvironmentView, view_id)
    if view is None:
        raise EnvironmentViewError("There is no such view.")
    status, _stage, _error, _image = await _view_progress(session, view)
    if status == "in_progress":
        raise EnvironmentViewError("This view's picture is already being made.")
    provenance_inputs: dict[str, Any] = {}
    version: LibraryEnvironmentVersion | None
    if project is None:
        version = await environment_versions.latest_version(session, view.environment_id)
    else:
        inputs = view.inputs if isinstance(view.inputs, dict) else {}
        discovery_id = inputs.get("discovery_id")
        link = (
            await _link_of(session, project.id, discovery_id)
            if isinstance(discovery_id, str)
            else None
        )
        if link is None or link.environment_id != view.environment_id:
            raise EnvironmentViewError(
                "This view does not belong to an environment of the project."
            )
        version = await environment_versions.get_version(
            session, view.environment_id, link.pinned_version
        )
        provenance_inputs = {
            "project_id": project.id,
            "discovery_id": discovery_id,
            "plan_version": inputs.get("plan_version"),
        }
    if version is None or version.reference_image_id is None:
        raise EnvironmentViewError("The environment has no master picture to edit.")
    return await _queue_prompt(
        session,
        view,
        version=version,
        provenance_inputs=provenance_inputs,
        project_id=project.id if project is not None else None,
    )


async def on_prompt_written(job_id: int) -> bool:
    """Called by the prompt job once its prompt is saved: starts the edit run that makes the
    view's picture. Returns True when a run was started. Does nothing (False) when the view or
    its master picture is gone.
    """
    async with SessionLocal() as session:
        job = await store.get_job(session, job_id)
        recorded = job.input if job is not None and isinstance(job.input, dict) else {}
        output = job.output if job is not None and isinstance(job.output, dict) else {}
        view = await session.get(EnvironmentView, recorded.get("view_id", 0))
        prompt = output.get("image_prompt")
        if view is None or view.prompt_job_id != job_id or not isinstance(prompt, str):
            await session.commit()
            return False
        references = [Ref(source="lab", id=recorded["master_image_id"])]
        for key in ("left_image_id", "right_image_id"):
            if isinstance(recorded.get(key), int):
                references.append(Ref(source="lab", id=recorded[key]))
        mode = image_models_service.resolve_mode(
            await settings_service.get_str(session, IMAGE_MODE_KEY)
        )
        try:
            form = QwenEditForm(
                prompt=prompt,
                mode=mode,
                aspect_ratio=environment_references.REFERENCE_SHAPE,
                seed=None,
                steps=None,
                references=references,
            )
            run, _job = await image_lab.create_qwen_edit_run(session, form, commit=False)
        except (LabInputError, ValueError):
            await session.rollback()
            _logger.exception("environment view %d: the picture could not be started", view.id)
            return False
        view.prompt = prompt
        view.lab_run_id = run.id
        await session.commit()
    _logger.info("environment view %d: picture started: run=%d", view.id, run.id)
    return True


# --- When a view's picture is stored ------------------------------------------------------


async def pin_next_version(
    session: AsyncSession, environment_id: int, inputs: dict[str, Any] | None
) -> int | None:
    """Writes the environment's next version, which freezes the pictures that arrived since the
    newest one, and moves the project's pin to it. `inputs` is what a view records: the project
    and the discovered environment it was made for. Returns the version the pin now holds.

    With no project (a view made in the lab) the version is written and no pin moves. When the
    link no longer points at this environment, or the pinned version is no longer the newest,
    nothing is written: the picture stays on its view, and the next version freezes it. Flushes
    but does not commit.
    """
    environment = await session.get(LibraryEnvironment, environment_id)
    newest = await environment_versions.latest_version(session, environment_id)
    if environment is None or newest is None:
        return None
    recorded = inputs or {}
    project_id, discovery_id = recorded.get("project_id"), recorded.get("discovery_id")
    if not isinstance(project_id, int) or not isinstance(discovery_id, str):
        await environment_versions.record_version_if_changed(
            session, environment, source="manual", carry_picture=True
        )
        return None
    link = await _link_of(session, project_id, discovery_id)
    if (
        link is None
        or link.environment_id != environment_id
        or newest.version != link.pinned_version
    ):
        return None
    # The version records the same `inputs` as the one the project pinned, so the Environment
    # Definition stage still reads that definition as built from this story.
    effective = await library_adoption.effective_inputs(session, "environment", link, newest)
    version = await environment_versions.record_version_if_changed(
        session, environment, source="ai", inputs=effective, carry_picture=True
    )
    link.pinned_version = (version if version is not None else newest).version
    if effective is not None:
        link.provenance_version = None
    link.updated_at = utcnow()
    return link.pinned_version


async def on_view_image_stored(run_id: int) -> bool:
    """Called (best effort) once a `lab_image` job has stored its picture. When the picture is
    the one a view was waiting for, it becomes the view's picture and the environment's next
    version freezes it (`pin_next_version`). A `behind` view that waited for the left and right
    views is then started. Returns True when it started another job (so the caller nudges the
    dispatcher). Does nothing (False) for any other picture.
    """
    async with SessionLocal() as session:
        view = (
            (
                await session.execute(
                    select(EnvironmentView).where(EnvironmentView.lab_run_id == run_id)
                )
            )
            .scalars()
            .first()
        )
        if view is None or view.reference_image_id is not None:
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
        view.reference_image_id = image.id
        await session.flush()
        pinned = await pin_next_version(session, view.environment_id, view.inputs)
        released = await _release_waiting(session, view.environment_id)
        await session.commit()
    _logger.info(
        "environment view %d: picture attached: image=%d pinned_version=%s released=%d",
        view.id,
        image.id,
        pinned,
        released,
    )
    return released > 0


async def _release_waiting(session: AsyncSession, environment_id: int) -> int:
    """Starts the `behind` views of the environment that waited for their left and right views
    and whose plan is now ready for them. Returns how many it started. Commits per view.
    """
    started = 0
    for view in await views_of(session, environment_id):
        inputs = view.inputs if isinstance(view.inputs, dict) else {}
        project_id, discovery_id = inputs.get("project_id"), inputs.get("discovery_id")
        master_version = inputs.get("master_version")
        if not _waiting(view) or not isinstance(master_version, int):
            continue
        plan = None
        if isinstance(project_id, int) and isinstance(discovery_id, str):
            plan = (await newest_plans(session, project_id)).get(discovery_id)
        version = await environment_versions.get_version(session, environment_id, master_version)
        if (
            plan is None
            or version is None
            or version.reference_image_id is None
            or not await _siblings_ready(session, environment_id, plan, version.reference_image_id)
        ):
            continue
        carried = {key: value for key, value in inputs.items() if key != "waiting"}
        await _queue_prompt(
            session,
            view,
            version=version,
            provenance_inputs={
                key: carried[key]
                for key in ("project_id", "discovery_id", "plan_version")
                if key in carried
            },
            project_id=project_id if isinstance(project_id, int) else None,
        )
        started += 1
    return started
