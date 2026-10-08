"""First frames made by the image model: when one may be made, which ones are out of date, what
the earlier frames of a scene are, and when a new frame may become the scene's first frame
(Phase 17; ANALYSIS.md Section 4.2 and 6.2; DATABASE_STRUCTURE.md Section 4.2, 4.5 and 7).

The request is `jobs/generate_frame.py`'s, the call is `providers/image_api.py`'s and the size
and the crop are `services/frame_geometry.py`'s and `services/frame_images.py`'s. This module
holds the rules around them:

- `scene_block`, `is_candidate`, `all_block`: why a frame cannot be made for a scene now, and
  which scenes "Generate first frames" covers. The project-level reasons (no scenes, a
  proposal or a draft running, out-of-date scenes) are `image_prompts.project_block`'s.
- `needs_upload_confirmation`: a first frame that is not the AI's (one the author uploaded) is
  replaced only after the author confirmed it. The upload stays among the earlier frames.
- `frame_out_of_date`: **computed**. An AI frame records the image prompt it was made from in
  its provenance, and the page compares it with the scene's prompt now. Nothing is stored as
  a flag.
- `frame_choices`, `select_first_frame`: the earlier frames of a scene and switching back to
  one. There is no table for them: they are the result frames of the scene's succeeded
  `generate_frame` jobs, plus the first frame each of those jobs replaced.
- `attach_block`: whether a frame that has just been made may become the scene's first frame
  as the scene is *now*. The author's frame is never replaced behind their back.

Pure functions, except the ones that take a session.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Final, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, Job, Scene
from app.jobs import store
from app.services import image_prompts as image_prompts_service

_logger = logging.getLogger(__name__)

FRAME_JOB: Final = "generate_frame"

_PROMPT_WRITING = "The image prompt is being written. Wait for it to finish."
_NO_PROMPT = "Write an image prompt first: the first frame is made from it."
_PROMPT_OUT_OF_DATE = "The image prompt is out of date. Write it again, or edit it, first."
_NOTHING_TO_MAKE = (
    "No scene needs a first frame now: each has a current one, one you uploaded, or no "
    "current image prompt."
)
_ALREADY_MAKING = "First frames are already being made. Wait for them to finish."

CUT_CHANGED: Final = (
    "The scene's cut changed while the image was being made, so the frame was not attached. "
    "It is kept in the list of earlier frames."
)
FRAME_CHANGED: Final = (
    "The scene's first frame was changed while the image was being made, so this one was not "
    "attached. It is kept in the list of earlier frames."
)


class SceneGone(Exception):
    """The scene no longer exists, or belongs to another project."""


class FrameNotChoosable(Exception):
    """The asset is not one of the scene's earlier frames."""


def _text(value: str | None) -> str:
    return (value or "").strip()


# --- When a frame may be made ---------------------------------------------------------------


def is_ai_frame(asset: Asset | None) -> bool:
    """A frame the image model made. Anything else in the slot (an upload) is the author's."""
    return asset is not None and asset.source == "ai"


def needs_upload_confirmation(scene: Scene, asset: Asset | None) -> bool:
    """The scene's first frame is not the AI's, so replacing it asks first. A frame that is
    set but cannot be read back counts as the author's: nothing is replaced by guessing.
    """
    return scene.first_frame_asset_id is not None and not is_ai_frame(asset)


def scene_block(scene: Scene, *, prompt_out_of_date: bool, prompt_job_active: bool) -> str | None:
    """Why this scene's first frame cannot be made now, or None when it can. The upload
    confirmation is not a block: the page asks, and the endpoint answers 409.

    `prompt_out_of_date` is about an AI prompt (`image_prompts.prompt_states`): the author's
    prompt is never out of date.
    """
    if prompt_job_active:
        return _PROMPT_WRITING
    if not _text(scene.image_prompt):
        return _NO_PROMPT
    if prompt_out_of_date:
        return _PROMPT_OUT_OF_DATE
    return None


def frame_out_of_date(scene: Scene, asset: Asset | None) -> bool:
    """Whether an AI frame was made from an image prompt that differs from the scene's now
    (both trimmed). A cleared prompt counts as changed, and so does a frame that recorded no
    prompt, because nothing says what it was made from. An upload is never out of date.
    """
    if not is_ai_frame(asset):
        return False
    provenance: Any = asset.provenance if asset is not None else None
    made_from = provenance.get("prompt") if isinstance(provenance, dict) else None
    if not isinstance(made_from, str):
        return True
    return _text(made_from) != _text(scene.image_prompt)


def is_candidate(
    scene: Scene,
    asset: Asset | None,
    *,
    prompt_out_of_date: bool,
    prompt_job_active: bool,
    frame_job_active: bool,
) -> bool:
    """ "Generate first frames" covers a scene with a current image prompt and nothing running
    that has no first frame, or an AI first frame that is out of date. An uploaded first
    frame is never replaced by it.
    """
    if frame_job_active:
        return False
    if (
        scene_block(
            scene, prompt_out_of_date=prompt_out_of_date, prompt_job_active=prompt_job_active
        )
        is not None
    ):
        return False
    if scene.first_frame_asset_id is None:
        return True
    return is_ai_frame(asset) and frame_out_of_date(scene, asset)


def all_block(candidate_count: int, active_count: int) -> str | None:
    """Why "Generate first frames" has nothing to start, or None when it has. Only asked
    after `image_prompts.project_block` found no reason.
    """
    if candidate_count > 0:
        return None
    return _ALREADY_MAKING if active_count > 0 else _NOTHING_TO_MAKE


def attach_block(
    scene: Scene, sent: Mapping[str, Any], replacing_asset_id: int | None
) -> str | None:
    """Why a frame that was just made may not become the scene's first frame, or None when it
    may. The scene is as it is *now*: its cut must still be the one the request was made for,
    and its first frame must still be the one the job started from (`replacing_asset_id`, None
    for an empty slot). Otherwise the frame is kept, listed among the earlier frames, and not
    attached.
    """
    if not image_prompts_service.unchanged(scene, sent):
        return CUT_CHANGED
    if scene.first_frame_asset_id != replacing_asset_id:
        return FRAME_CHANGED
    return None


def not_attached_note(job: Job | None) -> str | None:
    """What a succeeded frame job says about why its frame was not attached, if it was not."""
    output: Any = job.output if job is not None and isinstance(job.output, dict) else {}
    reason = output.get("not_attached_reason")
    if job is not None and job.status == "succeeded" and isinstance(reason, str):
        return reason
    return None


# --- Jobs -----------------------------------------------------------------------------------


async def active_frame_jobs(session: AsyncSession, project_id: int) -> dict[int, Job]:
    """The queued or running first frame jobs of a project, by scene id."""
    statement = (
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.type == FRAME_JOB,
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


# --- The earlier frames ---------------------------------------------------------------------


def _replaced_asset_id(job: Job) -> int | None:
    output: Any = job.output if isinstance(job.output, dict) else {}
    value = output.get("replaced_asset_id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def frame_choices(
    session: AsyncSession, project_id: int, scene_id: int | None = None
) -> dict[int, list[Asset]]:
    """The frames a scene can go back to, by scene id, newest first: the result frames of its
    succeeded `generate_frame` jobs, and the first frame each of them replaced (an upload, say).
    The frame the scene uses now is among them when it came from one of these jobs.

    One query for the jobs and their frames, and one for the replaced frames.
    """
    statement = (
        select(Job, Asset)
        .join(Asset, Asset.id == Job.result_asset_id)
        .where(
            Job.project_id == project_id,
            Job.type == FRAME_JOB,
            Job.status == "succeeded",
            Job.scene_id.is_not(None),
            Asset.kind == "frame",
        )
        .order_by(Job.id.desc())
        .execution_options(populate_existing=True)
    )
    if scene_id is not None:
        statement = statement.where(Job.scene_id == scene_id)

    by_scene: dict[int, dict[int, Asset]] = {}
    replaced: dict[int, set[int]] = {}
    for job, asset in (await session.execute(statement)).all():
        if job.scene_id is None:
            continue
        by_scene.setdefault(job.scene_id, {})[asset.id] = asset
        replaced_id = _replaced_asset_id(job)
        if replaced_id is not None:
            replaced.setdefault(job.scene_id, set()).add(replaced_id)

    wanted = {asset_id for ids in replaced.values() for asset_id in ids}
    if wanted:
        found = await session.execute(
            select(Asset)
            .where(Asset.id.in_(wanted), Asset.kind == "frame", Asset.project_id == project_id)
            .execution_options(populate_existing=True)
        )
        loaded = {asset.id: asset for asset in found.scalars()}
        for scene, ids in replaced.items():
            for asset_id in ids:
                if asset_id in loaded:
                    by_scene[scene][asset_id] = loaded[asset_id]

    return {
        scene: sorted(assets.values(), key=lambda asset: asset.id, reverse=True)
        for scene, assets in by_scene.items()
    }


def _was_updated(result: object) -> bool:
    return cast(CursorResult[Any], result).rowcount == 1


async def select_first_frame(
    session: AsyncSession, project_id: int, scene_id: int, asset_id: int
) -> None:
    """Makes one of the scene's earlier frames its first frame again. Commits.

    Raises SceneGone, or FrameNotChoosable when the asset is not one of the scene's frames.
    """
    scene = await session.get(Scene, scene_id)
    if scene is None or scene.project_id != project_id:
        await session.commit()
        raise SceneGone

    choices = await frame_choices(session, project_id, scene_id)
    if asset_id not in {asset.id for asset in choices.get(scene_id, [])}:
        await session.commit()
        raise FrameNotChoosable

    result = await session.execute(
        update(Scene)
        .where(Scene.id == scene_id, Scene.project_id == project_id)
        .values(first_frame_asset_id=asset_id)
        .execution_options(synchronize_session=False)
    )
    if not _was_updated(result):
        await session.rollback()
        raise SceneGone
    await session.commit()
    _logger.info("scene %d: first frame %d selected", scene_id, asset_id)
