"""Drafting scene descriptions with AI: when it is allowed, and what it may write
(Phase 12; ANALYSIS.md Section 4.2; DATABASE_STRUCTURE.md Section 4.4, 4.5 and 7).

The request and the answer are `description_writer.py`'s, the call is `providers/llm.py`'s
and the job that drives them is `jobs/draft_descriptions.py`. This module holds the rules
around them:

- `draft_block`: why drafting is refused now, or None. Shared by the endpoint (which refuses
  with the reason) and the button (which is disabled with it).
- `plan_write`: what a draft may put into a scene as it is *now*. A text the author wrote is
  never overwritten. Text the AI wrote earlier, or none, may be written again.
- `unchanged`: whether a scene is still the one the request was built from.

Pure functions, except `find_cached_answer`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Scene
from app.jobs import store
from app.services import scenes as scenes_service
from app.services.description_writer import (
    FIRST_FRAME,
    LAST_FRAME,
    MAX_SCENES,
    VIDEO_PROMPT,
    SceneDraft,
    SceneToDraft,
    draftable_count,
)

DRAFT_JOB: Final = "draft_descriptions"

_NO_SCENES = "There are no scenes yet. Propose scenes first."
_PROPOSAL_RUNNING = "A scene proposal is in progress. Wait for it to finish."
_SCENES_STALE = "The scenes are out of date. Propose scenes again first."
_NOTHING_TO_DRAFT = (
    "Nothing to draft: every scene's description and first frame description were written by you."
)


def draft_block(
    scenes: Sequence[Scene],
    *,
    plan_job: Job | None,
    stale_reasons: Sequence[str],
) -> str | None:
    """Why the descriptions cannot be drafted now, or None when they can. The checks run in
    this order, and the first that applies is the reason shown.
    """
    if not scenes:
        return _NO_SCENES
    if plan_job is not None and plan_job.status in store.ACTIVE_STATUSES:
        return _PROPOSAL_RUNNING
    if stale_reasons:
        return _SCENES_STALE
    if len(scenes) > MAX_SCENES:
        return (
            f"This project has {len(scenes)} scenes; drafting handles up to {MAX_SCENES} "
            "in one call."
        )
    if draftable_count(scenes) == 0:
        return _NOTHING_TO_DRAFT
    return None


async def find_cached_answer(
    session: AsyncSession, project_id: int, input_hash: str, exclude_job_id: int
) -> Job | None:
    """The newest earlier draft job that sent exactly this request and kept a usable answer
    (ANALYSIS.md Section 6.2, rule 3), so the same request is never paid for twice.
    """
    return await scenes_service.find_cached_answer(
        session, project_id, input_hash, exclude_job_id, job_type=DRAFT_JOB
    )


def unchanged(scene: Scene, sent: SceneToDraft) -> bool:
    """Whether the scene is still the one the request was built from: the same words over the
    same stretch of the voiceover. (Its number may differ, because a cut before it moved.)
    """
    return (
        scene.id == sent.scene_id
        and scene.start_s == sent.start_s
        and scene.end_s == sent.end_s
        and scene.text == sent.text
    )


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


@dataclass(frozen=True)
class SceneWrite:
    """The columns a draft sets on a scene, which of its texts they carry, and which old AI
    text the draft cleared. `detached_last_frame_asset_id` is the AI-made last frame the draft
    took off the scene, because it decided the scene has no last frame (the file stays).
    """

    values: dict[str, Any] = field(default_factory=dict)
    written: list[str] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)
    detached_last_frame_asset_id: int | None = None


def plan_write(
    scene: Scene,
    draft: SceneDraft,
    job_id: int,
    *,
    writes_last_frame: bool = False,
    last_frame_is_ai: bool = False,
) -> SceneWrite:
    """What this draft may write into the scene as it is now.

    A text is written only if the scene's own is blank or was written by the AI. So a
    description typed after the request was built is not overwritten either. Each text has
    its own source (Phase 15), so the author's first-frame description does not lock the
    video prompt, and the other way round.

    The last-frame description is written like the other two when the profile writes last
    frames (`writes_last_frame`, Phase 23) and the model gave one. A scene this draft writes
    into whose AI last-frame description the model did not repeat (it decided the scene has
    no last frame, or the profile never writes them) loses it, because it would no longer fit
    the new texts. That also clears the AI-written edit prompt, and takes an AI-made last
    frame (`last_frame_is_ai`: the asset's source is `ai`) off the scene, so the clip mode
    matches the new video prompt. What the author wrote or uploaded is never touched.
    """
    values: dict[str, Any] = {}
    written: list[str] = []
    cleared: list[str] = []
    detached: int | None = None

    description_is_ai = scene.scene_description_source == "ai"
    if draft.video_prompt is not None and (_blank(scene.scene_description) or description_is_ai):
        values["scene_description"] = draft.video_prompt
        values["scene_description_source"] = "ai"
        written.append(VIDEO_PROMPT)

    first_is_ai = scene.first_frame_description_source == "ai"
    if draft.first_frame is not None and (_blank(scene.first_frame_description) or first_is_ai):
        values["first_frame_description"] = draft.first_frame
        values["first_frame_description_source"] = "ai"
        written.append(FIRST_FRAME)

    last_is_ai_text = (
        not _blank(scene.last_frame_description) and scene.last_frame_description_source == "ai"
    )
    last_is_writable = _blank(scene.last_frame_description) or last_is_ai_text
    scene_written_into = bool(written)
    if writes_last_frame and draft.last_frame is not None and last_is_writable:
        values["last_frame_description"] = draft.last_frame
        values["last_frame_description_source"] = "ai"
        written.append(LAST_FRAME)
    elif scene_written_into and last_is_ai_text:
        values["last_frame_description"] = None
        values["last_frame_description_source"] = None
        cleared.append(LAST_FRAME)
        if scene.last_frame_prompt_source == "ai":
            values["last_frame_prompt"] = None
            values["last_frame_prompt_source"] = None
            values["last_frame_prompt_job_id"] = None
        if last_frame_is_ai and scene.last_frame_asset_id is not None:
            detached = scene.last_frame_asset_id
            values["last_frame_asset_id"] = None

    if written:
        values["description_job_id"] = job_id
    return SceneWrite(
        values=values, written=written, cleared=cleared, detached_last_frame_asset_id=detached
    )
