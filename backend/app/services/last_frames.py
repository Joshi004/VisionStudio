"""Last frames made by the image model: when one may be made, which ones are out of date, what the
earlier last frames of a scene are, and when a new frame may become the scene's last frame
(Phase 23; ANALYSIS.md Section 4.2 and 6.2; DATABASE_STRUCTURE.md Section 4.2, 4.5 and 7).

A last frame is made by **editing the scene's first frame** with the instruction in
`scene.last_frame_prompt` (`services/last_frame_prompts.py`). It is the counterpart of
`first_frames.py`, and this module holds the same kind of rules around the job
(`jobs/generate_last_frame.py`), the call (`providers/image_generator.py`) and the fitting of the
image to the frame size (`services/frame_images.py`):

- `scene_block`, `is_candidate`, `all_block`: why a last frame cannot be made for a scene now, and
  which scenes "Generate last frames" covers. The project-level reasons (no scenes, a proposal or
  a draft running, out-of-date scenes) are `image_prompts.project_block`'s.
- `needs_upload_confirmation`: a last frame that is not the AI's (one the author uploaded) is
  replaced only after the author confirmed it. The upload stays among the earlier frames.
- `frame_out_of_date`: **computed**. An AI last frame records the edit prompt it was made from and
  the first frame it was made by editing (`reference_asset_id`) in its provenance, and the page
  compares both with the scene now. So a new first frame makes the last frame out of date, and
  nothing is stored as a flag.
- `attach_block`: whether a frame that has just been made may become the scene's last frame as the
  scene is *now*. The author's frame is never replaced behind their back.
- `active_last_frame_jobs`, `last_frame_choices`, `select_last_frame`: the earlier last frames of a
  scene and switching back to one. There is no table for them: they are the result frames of the
  scene's succeeded `generate_last_frame` jobs, plus the last frame each of those jobs replaced.
- `is_chained`, `chain_sources`, `apply_chains`: a scene that *continues the action* of the scene
  before it (the draft's `continuity`) starts on the picture that scene ends on. When the previous
  scene has a last frame, the app uses it as this scene's first frame, so the cut is seamless.
  `apply_chains` does that, and is safe to run again: it is called when a last frame is attached
  or chosen, and by the automatic run.

Pure functions, except the ones that take a session.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, Job, Scene
from app.jobs import store
from app.services import first_frames as first_frames_service
from app.services import image_prompts as image_prompts_service
from app.services import scene_inputs
from app.services import scenes as scenes_service

LAST_FRAME_JOB: Final = "generate_last_frame"
# The draft's `continuity` value that chains a scene to the one before it.
CONTINUES_ACTION: Final = "continues_action"

_PROMPT_WRITING = "The last frame prompt is being written. Wait for it to finish."
_NO_PROMPT = "Write a last frame prompt first: the last frame is made from it."
_PROMPT_OUT_OF_DATE = "The last frame prompt is out of date. Write it again, or edit it, first."
_NO_FIRST_FRAME = "Make the first frame first: the last frame is made by editing it."
_FIRST_FRAME_MAKING = "The first frame is being made. Wait for it to finish."
_NOTHING_TO_MAKE = (
    "No scene needs a last frame now: each has a current one, one you uploaded, or no current "
    "last frame prompt and first frame."
)
_ALREADY_MAKING = "Last frames are already being made. Wait for them to finish."

CUT_CHANGED: Final = first_frames_service.CUT_CHANGED
FRAME_CHANGED: Final = (
    "The scene's last frame was changed while the image was being made, so this one was not "
    "attached. It is kept in the list of earlier frames."
)
FIRST_FRAME_CHANGED: Final = (
    "The scene's first frame was changed while the image was being made, so this last frame no "
    "longer fits it and was not attached. It is kept in the list of earlier frames."
)


def _text(value: str | None) -> str:
    return (value or "").strip()


# --- When a frame may be made ---------------------------------------------------------------


def needs_upload_confirmation(scene: Scene, asset: Asset | None) -> bool:
    """The scene's last frame is not the AI's, so replacing it asks first. A frame that is set
    but cannot be read back counts as the author's: nothing is replaced by guessing.
    """
    return scene.last_frame_asset_id is not None and not first_frames_service.is_ai_frame(asset)


def scene_block(
    scene: Scene,
    first_frame: Asset | None,
    *,
    prompt_out_of_date: bool,
    prompt_job_active: bool,
    first_frame_job_active: bool,
) -> str | None:
    """Why this scene's last frame cannot be made now, or None when it can. The upload
    confirmation is not a block: the page asks, and the endpoint answers 409.

    `prompt_out_of_date` is about an AI last frame prompt (`last_frame_prompts.prompt_states`):
    the author's prompt is never out of date.
    """
    if prompt_job_active:
        return _PROMPT_WRITING
    if not _text(scene.last_frame_prompt):
        return _NO_PROMPT
    if prompt_out_of_date:
        return _PROMPT_OUT_OF_DATE
    if first_frame is None:
        return _NO_FIRST_FRAME
    if first_frame_job_active:
        return _FIRST_FRAME_MAKING
    return None


def frame_out_of_date(scene: Scene, asset: Asset | None) -> bool:
    """Whether an AI last frame was made from a prompt that differs from the scene's now (both
    trimmed), or by editing a first frame that is not the scene's first frame now. A cleared
    prompt counts as changed, and so does a frame that recorded no prompt or no first frame,
    because nothing says what it was made from. An upload is never out of date.
    """
    if not first_frames_service.is_ai_frame(asset):
        return False
    provenance: Any = asset.provenance if asset is not None else None
    if not isinstance(provenance, dict):
        return True
    made_from = provenance.get("prompt")
    if not isinstance(made_from, str):
        return True
    if _text(made_from) != _text(scene.last_frame_prompt):
        return True
    return provenance.get("reference_asset_id") != scene.first_frame_asset_id


def is_candidate(
    scene: Scene,
    first_frame: Asset | None,
    last_frame: Asset | None,
    *,
    prompt_out_of_date: bool,
    prompt_job_active: bool,
    first_frame_job_active: bool,
    last_frame_job_active: bool,
) -> bool:
    """ "Generate last frames" covers a scene with a current last frame prompt and a first frame,
    and nothing running, that has no last frame, or an AI last frame that is out of date. An
    uploaded last frame is never replaced by it.
    """
    if last_frame_job_active:
        return False
    blocked = scene_block(
        scene,
        first_frame,
        prompt_out_of_date=prompt_out_of_date,
        prompt_job_active=prompt_job_active,
        first_frame_job_active=first_frame_job_active,
    )
    if blocked is not None:
        return False
    if scene.last_frame_asset_id is None:
        return True
    return first_frames_service.is_ai_frame(last_frame) and frame_out_of_date(scene, last_frame)


def all_block(candidate_count: int, active_count: int) -> str | None:
    """Why "Generate last frames" has nothing to start, or None when it has. Only asked after
    `image_prompts.project_block` found no reason.
    """
    if candidate_count > 0:
        return None
    return _ALREADY_MAKING if active_count > 0 else _NOTHING_TO_MAKE


def attach_block(
    scene: Scene,
    sent: Mapping[str, Any],
    replacing_asset_id: int | None,
    reference_asset_id: int | None,
) -> str | None:
    """Why a frame that was just made may not become the scene's last frame, or None when it
    may. The scene is as it is *now*: its cut must still be the one the request was made for,
    its last frame must still be the one the job started from (`replacing_asset_id`, None for an
    empty slot), and its first frame must still be the one that was edited
    (`reference_asset_id`). Otherwise the frame is kept, listed among the earlier frames, and
    not attached.
    """
    if not image_prompts_service.unchanged(scene, sent):
        return CUT_CHANGED
    if scene.last_frame_asset_id != replacing_asset_id:
        return FRAME_CHANGED
    if scene.first_frame_asset_id != reference_asset_id:
        return FIRST_FRAME_CHANGED
    return None


# --- Jobs -----------------------------------------------------------------------------------


async def active_last_frame_jobs(session: AsyncSession, project_id: int) -> dict[int, Job]:
    """The queued or running last frame jobs of a project, by scene id."""
    statement = (
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.type == LAST_FRAME_JOB,
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


async def last_frame_choices(
    session: AsyncSession, project_id: int, scene_id: int | None = None
) -> dict[int, list[Asset]]:
    """The last frames a scene can go back to, by scene id, newest first: the result frames of
    its succeeded `generate_last_frame` jobs, and the last frame each of them replaced (an
    upload, say).
    """
    return await first_frames_service.frame_choices(
        session, project_id, scene_id, job_type=LAST_FRAME_JOB
    )


async def select_last_frame(
    session: AsyncSession, project_id: int, scene_id: int, asset_id: int
) -> None:
    """Makes one of the scene's earlier last frames its last frame again. Commits.

    Raises `first_frames.SceneGone`, or `first_frames.FrameNotChoosable` when the asset is not
    one of the scene's last frames.
    """
    await first_frames_service.select_frame(
        session,
        project_id,
        scene_id,
        asset_id,
        job_type=LAST_FRAME_JOB,
        column="last_frame_asset_id",
    )
    # The chosen frame flows on to a scene that continues this one's action.
    await apply_chains(session, project_id)
    await session.commit()


# --- Chaining: a scene that continues the action starts on the previous last frame ----------


def is_chained(previous: Scene | None, continuity: str | None) -> bool:
    """Whether a scene's first frame is meant to be the previous scene's last frame: the scene
    continues the previous scene's action (`continuity`), and that scene has a last frame. A
    description of one is enough: the frame itself may not be made yet.
    """
    return (
        previous is not None
        and continuity == CONTINUES_ACTION
        and bool(_text(previous.last_frame_description))
    )


async def chain_sources(
    session: AsyncSession, project_id: int, scenes: Sequence[Scene]
) -> dict[int, int | None]:
    """For each scene whose first frame is chained, by scene id, the previous scene's last frame
    now (None while it has none). A scene that is not chained is not in the answer. `scenes` are
    the project's scenes, in order. Three queries at most, however many scenes there are.
    """
    if len(scenes) < 2:
        return {}
    drafts = await image_prompts_service.load_sources(session, project_id, scenes[1:])
    return {
        scene.id: previous.last_frame_asset_id
        for previous, scene in zip(scenes, scenes[1:], strict=False)
        if is_chained(previous, drafts[scene.id].continuity)
    }


async def pending_chains(session: AsyncSession, project_id: int) -> list[tuple[Scene, int]]:
    """The chained scenes that do not yet start on the previous scene's last frame, each with
    the asset that should become its first frame. Reads only.

    A scene is listed only when:

    - the previous scene's last frame is current. An AI last frame that is out of date is made
      again first (`frame_out_of_date`), and the new one is chained when it is attached;
    - the scene's own first frame is empty or the AI's. A first frame the author uploaded is
      never replaced.
    """
    scenes = await scenes_service.list_scenes(session, project_id)
    chained = await chain_sources(session, project_id, scenes)
    if not chained:
        return []
    frames = await scene_inputs.load_frames(session, scenes)

    pending: list[tuple[Scene, int]] = []
    for previous, scene in zip(scenes, scenes[1:], strict=False):
        if scene.id not in chained:
            continue
        source_id = chained[scene.id]
        if source_id is None or scene.first_frame_asset_id == source_id:
            continue
        source = frames.get(source_id)
        if first_frames_service.is_ai_frame(source) and frame_out_of_date(previous, source):
            continue
        own = frames.get(scene.first_frame_asset_id or 0)
        if scene.first_frame_asset_id is not None and not first_frames_service.is_ai_frame(own):
            continue
        pending.append((scene, source_id))
    return pending


async def apply_chains(session: AsyncSession, project_id: int) -> list[int]:
    """Makes the previous scene's last frame the first frame of every chained scene that is
    waiting for it (`pending_chains`), and returns the ids of the scenes it changed. It changes
    nothing in the session's transaction beyond those scenes' `first_frame_asset_id`, and the
    caller commits. Safe to run again: it then finds nothing to change.
    """
    moved: list[int] = []
    for scene, source_id in await pending_chains(session, project_id):
        scene.first_frame_asset_id = source_id
        moved.append(scene.id)
    return moved
