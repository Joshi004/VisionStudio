"""Edit prompts for the last frame: when one may be written, which ones are out of date, and
what a job may write into a scene (Phase 23; ANALYSIS.md Section 4.2 and 6.2;
DATABASE_STRUCTURE.md Section 4.4, 4.5 and 7).

It is the counterpart of `image_prompts.py`, for the instruction that edits a scene's first
frame into its last frame. The request and the answer are `last_frame_prompt_writer.py`'s, the
call is `providers/llm.py`'s and the job that drives them is `jobs/write_last_frame_prompt.py`.
This module holds the rules around them:

- `scene_block`, `all_block`: why writing is refused now, or None. The project-level reasons
  (no scenes, a proposal or a draft running, out-of-date scenes) are
  `image_prompts.project_block`'s.
- `prompt_states`: whether an AI prompt is out of date. **Computed** when it is read: the job
  that wrote it keeps a hash of the inputs it was made from, and the page compares it with the
  hash of the scene's inputs now. Nothing is stored as a flag.
- `is_candidate`: which scenes "Write last frame prompts" covers.
- `write_values`: what a job may put into a scene as it is *now*. A prompt the author wrote is
  never overwritten.

Pure functions, except the ones that take a session.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, Scene
from app.jobs import store
from app.services import image_prompt_writer
from app.services import image_prompts as image_prompts_service
from app.services import last_frame_prompt_writer as writer
from app.services import scenes as scenes_service
from app.services.image_prompts import PromptState

LAST_FRAME_PROMPT_JOB: Final = "write_last_frame_prompt"

_NO_TEXT = (
    "This scene has no last frame description. The AI writes one when it drafts the "
    "descriptions, or you can write it: the edit prompt is written from it."
)
_AUTHORS_PROMPT = (
    "This last frame prompt was written by you. Clear it and save to have the AI write one."
)
_NOTHING_TO_WRITE = (
    "No scene needs a last frame prompt now: each has a current one, one you wrote, or no last "
    "frame description."
)
_ALREADY_WRITING = "Last frame prompts are already being written. Wait for them to finish."


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


# --- When writing is allowed --------------------------------------------------------------


def all_block(candidate_count: int, active_count: int) -> str | None:
    """Why "Write last frame prompts" has nothing to start, or None when it has. Only asked
    after `image_prompts.project_block` found no reason.
    """
    if candidate_count > 0:
        return None
    return _ALREADY_WRITING if active_count > 0 else _NOTHING_TO_WRITE


def has_source_text(scene: Scene) -> bool:
    """The edit prompt is written from the last frame description: a scene needs one."""
    return not _blank(scene.last_frame_description)


def prompt_is_authors(scene: Scene) -> bool:
    """A prompt is the author's unless its source is `ai`. An unknown source counts as the
    author's: nothing is overwritten by guessing.
    """
    return not _blank(scene.last_frame_prompt) and scene.last_frame_prompt_source != "ai"


def scene_block(scene: Scene) -> str | None:
    """Why this scene's last frame prompt cannot be written now, or None when it can."""
    if not has_source_text(scene):
        return _NO_TEXT
    if prompt_is_authors(scene):
        return _AUTHORS_PROMPT
    return None


# --- Out of date, computed ------------------------------------------------------------


def is_out_of_date(scene: Scene, current_sha: str, prompt_job: Job | None) -> bool:
    """Whether the scene's AI prompt was written from inputs that differ from its inputs now.

    Only an AI prompt can be out of date: the author's is never touched. A prompt whose job
    is gone (or recorded no hash) counts as out of date, because nothing says what it was
    made from.
    """
    if _blank(scene.last_frame_prompt) or scene.last_frame_prompt_source != "ai":
        return False
    recorded: Any = prompt_job.input if prompt_job is not None else None
    recorded_sha = recorded.get("inputs_sha256") if isinstance(recorded, dict) else None
    return recorded_sha != current_sha


def is_candidate(scene: Scene, *, out_of_date: bool, active: Job | None) -> bool:
    """ "Write last frame prompts" covers a scene with a last frame description and no prompt,
    or an AI prompt that is out of date, and nothing running. The author's prompts are skipped.
    """
    if active is not None or scene_block(scene) is not None:
        return False
    return _blank(scene.last_frame_prompt) or out_of_date


async def prompt_states(
    session: AsyncSession, project: Project, scenes: Sequence[Scene]
) -> dict[int, PromptState]:
    """The state of every scene that holds an AI last frame prompt, by scene id. Scenes with no
    prompt, or one the author wrote, are not in the answer: they cannot be out of date.
    """
    holding = [
        scene
        for scene in scenes
        if not _blank(scene.last_frame_prompt) and scene.last_frame_prompt_source == "ai"
    ]
    if not holding:
        return {}
    sources = await image_prompts_service.load_sources(session, project.id, holding)
    prompt_jobs = await image_prompts_service.jobs_by_id(
        session,
        {s.last_frame_prompt_job_id for s in holding if s.last_frame_prompt_job_id is not None},
    )
    states: dict[int, PromptState] = {}
    for scene in holding:
        inputs = writer.prompt_inputs(scene, project, sources[scene.id])
        sha = image_prompt_writer.inputs_sha256(inputs)
        job = prompt_jobs.get(scene.last_frame_prompt_job_id or 0)
        states[scene.id] = PromptState(
            inputs_sha256=sha, out_of_date=is_out_of_date(scene, sha, job)
        )
    return states


# --- Jobs -----------------------------------------------------------------------------


async def active_prompt_jobs(session: AsyncSession, project_id: int) -> dict[int, Job]:
    """The queued or running last frame prompt jobs of a project, by scene id."""
    statement = (
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.type == LAST_FRAME_PROMPT_JOB,
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


async def find_cached_answer(
    session: AsyncSession, project_id: int, scene_id: int, input_hash: str, exclude_job_id: int
) -> Job | None:
    """The newest earlier job for this scene that sent exactly this request and kept a usable
    answer (ANALYSIS.md Section 6.2, rule 3), so the same request is never paid for twice.
    """
    return await scenes_service.find_cached_answer(
        session,
        project_id,
        input_hash,
        exclude_job_id,
        job_type=LAST_FRAME_PROMPT_JOB,
        scene_id=scene_id,
    )


# --- What a job may write -----------------------------------------------------------------


def write_values(scene: Scene, prompt: str, job_id: int) -> dict[str, Any] | None:
    """The columns a job sets on the scene as it is now, or None when the author has written
    a prompt since: it is never overwritten. A blank prompt, or one the AI wrote, may be.
    """
    if prompt_is_authors(scene):
        return None
    return {
        "last_frame_prompt": prompt,
        "last_frame_prompt_source": "ai",
        "last_frame_prompt_job_id": job_id,
    }
