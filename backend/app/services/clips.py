"""Clips in the database (ANALYSIS.md Section 4.2, 5.3 and 5.8; DATABASE_STRUCTURE.md
Section 4.4, 4.5 and 7).

There is no clip table. A generation attempt is a `generate_clip` job, its result is an
`asset` (`kind='clip'`), and the scene points at the chosen take with
`selected_clip_asset_id`. A *take* is therefore a succeeded job together with its asset.
Regenerating makes another job and another take; picking an older one repoints the scene.

This module holds the reads and the small writes the API needs, and the one rule that
decides whether a scene may be generated (`generation_block`). It never calls the GPU
server: `app/jobs/generate_clip.py` does that.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, Job, Project, Scene
from app.jobs import store
from app.services import frame_counts, scene_inputs, video_models

_logger = logging.getLogger(__name__)

GENERATE_JOB: Final = "generate_clip"

# The same tolerance the page uses to paint a scene length red.
_LIMIT_TOLERANCE_S: Final = 0.001
# How far a take's recorded scene times may differ from the scene's now.
_TIME_TOLERANCE_S: Final = 0.0005

_PART_NAMES: Final[dict[str, str]] = {
    "description": "a description",
    "first_frame": "a first frame",
}


class TakeNotFound(Exception):
    """The asset is not a take (a finished clip) of this scene."""


class SceneGone(Exception):
    """The scene no longer exists, or belongs to another project."""


@dataclass(frozen=True)
class Take:
    """One finished generation: the job that made it and the clip it produced."""

    job: Job
    asset: Asset

    @property
    def provenance(self) -> dict[str, Any]:
        recorded = self.asset.provenance
        return recorded if isinstance(recorded, dict) else {}


async def active_clip_jobs(session: AsyncSession, project_id: int) -> dict[int, Job]:
    """The queued or running clip jobs of a project, by scene id."""
    statement = (
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.type == GENERATE_JOB,
            Job.status.in_(store.ACTIVE_STATUSES),
            Job.scene_id.is_not(None),
        )
        .order_by(Job.id)
        .execution_options(populate_existing=True)
    )
    return {
        job.scene_id: job
        for job in (await session.execute(statement)).scalars()
        if job.scene_id is not None
    }


async def takes_by_scene(session: AsyncSession, project_id: int) -> dict[int, list[Take]]:
    """The finished clips of a project's scenes, newest first, in one query."""
    statement = (
        select(Job, Asset)
        .join(Asset, Asset.id == Job.result_asset_id)
        .where(
            Job.project_id == project_id,
            Job.type == GENERATE_JOB,
            Job.status == "succeeded",
            Job.scene_id.is_not(None),
            Asset.kind == "clip",
        )
        .order_by(Job.id.desc())
        .execution_options(populate_existing=True)
    )
    takes: dict[int, list[Take]] = {}
    for job, asset in (await session.execute(statement)).all():
        if job.scene_id is not None:
            takes.setdefault(job.scene_id, []).append(Take(job=job, asset=asset))
    return takes


def scenes_block_reason(plan_job: Job | None, stale_reasons: Sequence[str]) -> str | None:
    """Why no clip can be generated for any scene of the project right now, or None.

    A proposal replaces every scene (and deletes their jobs), so nothing starts while one is
    active. Scenes that no longer match the voiceover or the script are not generated either.
    """
    if plan_job is not None and plan_job.status in store.ACTIVE_STATUSES:
        return "A scene proposal is in progress. Wait for it to finish."
    if stale_reasons:
        return "The scenes are out of date. Propose scenes again before generating clips."
    return None


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def generation_block(
    scene: Scene,
    project: Project,
    *,
    scenes_blocked: str | None,
    active: Job | None,
) -> str | None:
    """Why this scene cannot be generated now, or None when it can. Pure.

    The one rule behind the Generate button, the endpoint, Generate all and the handler.
    """
    if scenes_blocked is not None:
        return scenes_blocked
    if active is not None:
        return "A clip is already being generated for this scene."

    missing = scene_inputs.missing_inputs(scene)
    if missing:
        needs = _join([_PART_NAMES[name] for name in missing])
        return f"This scene is not ready. It still needs {needs}."

    length = scene.end_s - scene.start_s
    if length > project.max_scene_seconds + _LIMIT_TOLERANCE_S:
        return (
            f"This scene is {length:.2f} s long, more than the project's maximum of "
            f"{project.max_scene_seconds:g} s. Change its cuts, or raise the maximum in "
            "Project settings."
        )
    if target_frames_for(scene, project) < 1:
        return "This scene is shorter than one frame at the project's frame rate."
    return None


def target_frames_for(scene: Scene, project: Project) -> int:
    return frame_counts.target_frames(scene.start_s, scene.end_s, project.fps)


def is_generate_all_candidate(
    scene: Scene, project: Project, *, scenes_blocked: str | None, active: Job | None
) -> bool:
    """Generate all starts the scenes that are ready and have no clip yet (no selected take)
    and nothing running.
    """
    return scene.selected_clip_asset_id is None and (
        generation_block(scene, project, scenes_blocked=scenes_blocked, active=active) is None
    )


def take_is_out_of_date(provenance: dict[str, Any], scene: Scene) -> bool:
    """The scene's range is no longer the one this take was made for (a cut was edited)."""
    start, end = provenance.get("scene_start_s"), provenance.get("scene_end_s")
    if not isinstance(start, int | float) or not isinstance(end, int | float):
        return False
    return (
        abs(start - scene.start_s) > _TIME_TOLERANCE_S or abs(end - scene.end_s) > _TIME_TOLERANCE_S
    )


def take_is_too_short(provenance: dict[str, Any], scene: Scene, project: Project) -> bool:
    """The take has fewer frames than the scene needs now (Phase 10 could not fill it)."""
    count = provenance.get("frame_count")
    if isinstance(count, bool) or not isinstance(count, int):
        return False
    return count < target_frames_for(scene, project)


def _was_updated(result: object) -> bool:
    return cast(CursorResult[Any], result).rowcount == 1


async def select_take(session: AsyncSession, project_id: int, scene_id: int, asset_id: int) -> None:
    """Makes a finished clip of this scene the one used in the final video. Commits.

    Raises SceneGone, or TakeNotFound when the asset is not a take of this scene.
    """
    scene = await session.get(Scene, scene_id)
    if scene is None or scene.project_id != project_id:
        await session.commit()
        raise SceneGone

    statement = select(Job.id).where(
        Job.project_id == project_id,
        Job.scene_id == scene_id,
        Job.type == GENERATE_JOB,
        Job.status == "succeeded",
        Job.result_asset_id == asset_id,
    )
    if (await session.execute(statement)).first() is None:
        await session.commit()
        raise TakeNotFound

    result = await session.execute(
        update(Scene)
        .where(Scene.id == scene_id, Scene.project_id == project_id)
        .values(selected_clip_asset_id=asset_id)
        .execution_options(synchronize_session=False)
    )
    if not _was_updated(result):
        await session.rollback()
        raise SceneGone
    await session.commit()
    _logger.info("scene %d: take %d selected", scene_id, asset_id)


async def set_clip_sound(
    session: AsyncSession, project_id: int, scene_id: int, use_clip_sound: bool
) -> None:
    """Switches the scene's own clip sound on or off for the final video. Commits.

    Raises SceneGone.
    """
    result = await session.execute(
        update(Scene)
        .where(Scene.id == scene_id, Scene.project_id == project_id)
        .values(use_clip_sound=use_clip_sound)
        .execution_options(synchronize_session=False)
    )
    if not _was_updated(result):
        await session.rollback()
        raise SceneGone
    await session.commit()
    _logger.info("scene %d: clip sound %s", scene_id, "on" if use_clip_sound else "off")


async def set_video_model(
    session: AsyncSession, project_id: int, scene_id: int, video_model: str | None
) -> None:
    """Sets the scene's own video model, or None to use the project's (and then the app's).
    Commits. It changes the clips generated from now on; clips already made keep the model
    they were made with.

    Raises SceneGone, and ValueError for a model that is not known.
    """
    if video_model is not None and not video_models.is_video_model(video_model):
        raise ValueError(f"{video_model} is not a known video model.")
    result = await session.execute(
        update(Scene)
        .where(Scene.id == scene_id, Scene.project_id == project_id)
        .values(video_model=video_model)
        .execution_options(synchronize_session=False)
    )
    if not _was_updated(result):
        await session.rollback()
        raise SceneGone
    await session.commit()
    _logger.info("scene %d: video model %s", scene_id, video_model or "inherited")
