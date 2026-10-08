"""Image prompts for the first frame: when one may be written, which ones are out of date, and
what a job may write into a scene (Phase 16; ANALYSIS.md Section 4.2 and 6.2;
DATABASE_STRUCTURE.md Section 4.4, 4.5 and 7).

The request and the answer are `image_prompt_writer.py`'s, the call is `providers/llm.py`'s
and the job that drives them is `jobs/write_image_prompt.py`. This module holds the rules
around them:

- `project_block` and `scene_block`: why writing is refused now, or None. Shared by the
  endpoints (which refuse with the reason) and the buttons (which are disabled with it).
- `load_sources` and `prompt_states`: where each scene's `world` and `continuity` come from,
  and whether a prompt is out of date. Out of date is **computed** when it is read: the job
  that wrote a prompt keeps a hash of the inputs it was made from, and the page compares it
  with the hash of the scene's inputs now. Nothing is stored as a flag.
- `is_candidate`: which scenes "Write image prompts" covers.
- `write_values`: what a job may put into a scene as it is *now*. A prompt the author wrote is
  never overwritten.

Pure functions, except the ones that take a session.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, Scene
from app.jobs import store
from app.services import image_prompt_writer as writer
from app.services import scenes as scenes_service
from app.services.descriptions import DRAFT_JOB
from app.services.image_prompt_writer import SourceDraft

IMAGE_PROMPT_JOB: Final = "write_image_prompt"

_NO_SCENES = "There are no scenes yet. Propose scenes first."
_PROPOSAL_RUNNING = "A scene proposal is in progress. Wait for it to finish."
_SCENES_STALE = "The scenes are out of date. Propose scenes again first."
_DRAFT_RUNNING = "Descriptions are being drafted. Wait for the draft to finish."
_NO_TEXT = (
    "Write a description or a first frame description first: the image prompt is written from them."
)
_AUTHORS_PROMPT = (
    "This image prompt was written by you. Clear it and save to have the AI write one."
)
_NOTHING_TO_WRITE = (
    "No scene needs an image prompt now: each has a current one, one you wrote, or no text "
    "to work from."
)
_ALREADY_WRITING = "Image prompts are already being written. Wait for them to finish."


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


# --- When writing is allowed --------------------------------------------------------------


def project_block(
    scenes: Sequence[Scene],
    *,
    plan_job: Job | None,
    stale_reasons: Sequence[str],
    draft_job: Job | None,
) -> str | None:
    """Why image prompts cannot be written for this project now, or None when they can. The
    checks run in this order, and the first that applies is the reason shown.
    """
    if not scenes:
        return _NO_SCENES
    if plan_job is not None and plan_job.status in store.ACTIVE_STATUSES:
        return _PROPOSAL_RUNNING
    if stale_reasons:
        return _SCENES_STALE
    if draft_job is not None and draft_job.status in store.ACTIVE_STATUSES:
        return _DRAFT_RUNNING
    return None


def all_block(candidate_count: int, active_count: int) -> str | None:
    """Why "Write image prompts" has nothing to start, or None when it has. Only asked after
    `project_block` found no reason.
    """
    if candidate_count > 0:
        return None
    return _ALREADY_WRITING if active_count > 0 else _NOTHING_TO_WRITE


def has_source_text(scene: Scene) -> bool:
    """The image prompt is written from the first frame description and the video prompt: a
    scene needs at least one of them.
    """
    return not (_blank(scene.first_frame_description) and _blank(scene.scene_description))


def prompt_is_authors(scene: Scene) -> bool:
    """A prompt is the author's unless its source is `ai`. An unknown source counts as the
    author's: nothing is overwritten by guessing.
    """
    return not _blank(scene.image_prompt) and scene.image_prompt_source != "ai"


def scene_block(scene: Scene) -> str | None:
    """Why this scene's image prompt cannot be written now, or None when it can."""
    if not has_source_text(scene):
        return _NO_TEXT
    if prompt_is_authors(scene):
        return _AUTHORS_PROMPT
    return None


# --- Out of date, computed ------------------------------------------------------------


@dataclass(frozen=True)
class PromptState:
    """The hash of a scene's inputs now, and whether its AI prompt was made from others."""

    inputs_sha256: str
    out_of_date: bool


def is_out_of_date(scene: Scene, current_sha: str, prompt_job: Job | None) -> bool:
    """Whether the scene's AI prompt was written from inputs that differ from its inputs now.

    Only an AI prompt can be out of date: the author's is never touched. A prompt whose job
    is gone (or recorded no hash) counts as out of date, because nothing says what it was
    made from.
    """
    if _blank(scene.image_prompt) or scene.image_prompt_source != "ai":
        return False
    recorded: Any = prompt_job.input if prompt_job is not None else None
    recorded_sha = recorded.get("inputs_sha256") if isinstance(recorded, dict) else None
    return recorded_sha != current_sha


def is_candidate(scene: Scene, *, out_of_date: bool, active: Job | None) -> bool:
    """ "Write image prompts" covers a scene with text to work from and no prompt, or an AI
    prompt that is out of date, and nothing running. The author's prompts are skipped.
    """
    if active is not None or scene_block(scene) is not None:
        return False
    return _blank(scene.image_prompt) or out_of_date


# --- Where the world and the continuity come from ---------------------------------------


async def _jobs_by_id(session: AsyncSession, ids: Collection[int]) -> dict[int, Job]:
    if not ids:
        return {}
    statement = select(Job).where(Job.id.in_(ids)).execution_options(populate_existing=True)
    return {job.id: job for job in (await session.execute(statement)).scalars()}


async def _newest_successful_draft(session: AsyncSession, project_id: int) -> Job | None:
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == DRAFT_JOB, Job.status == "succeeded")
        .order_by(Job.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


def _answer_of(job: Job) -> object:
    output: Any = job.output if isinstance(job.output, dict) else {}
    return output.get("answer")


def _reused_from(job: Job) -> int | None:
    """The job that paid for this draft's answer, when this one reused it."""
    output: Any = job.output if isinstance(job.output, dict) else {}
    value = output.get("cache_hit_of_job_id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def load_sources(
    session: AsyncSession, project_id: int, scenes: Sequence[Scene]
) -> dict[int, SourceDraft]:
    """For each scene, the draft that wrote it: its `world` and its `continuity`.

    A scene's own draft job (`description_job_id`) comes first. A scene whose texts were all
    written by hand has none, and takes the project's newest successful draft, or nothing. A
    draft that reused an earlier answer holds no `answer`, so the world is read from the job
    that paid for it. Three queries at most, however many scenes there are.
    """
    jobs = await _jobs_by_id(
        session, {s.description_job_id for s in scenes if s.description_job_id is not None}
    )
    newest: Job | None = None
    if any(scene.description_job_id not in jobs for scene in scenes):
        newest = await _newest_successful_draft(session, project_id)

    drafts = [*jobs.values(), *([newest] if newest is not None else [])]
    payer_ids = {
        paid
        for job in drafts
        if _answer_of(job) is None and (paid := _reused_from(job)) is not None
    }
    payers = await _jobs_by_id(session, payer_ids)

    def world_of(job: Job) -> tuple[int | None, dict[str, list[dict[str, str]]] | None]:
        if isinstance(_answer_of(job), dict):
            return job.id, writer.world_from_answer(_answer_of(job))
        payer = payers.get(_reused_from(job) or 0)
        if payer is not None and isinstance(_answer_of(payer), dict):
            return payer.id, writer.world_from_answer(_answer_of(payer))
        return None, None

    sources: dict[int, SourceDraft] = {}
    for scene in scenes:
        job = jobs.get(scene.description_job_id or 0) or newest
        if job is None:
            sources[scene.id] = writer.NO_SOURCE
            continue
        world_job_id, world = world_of(job)
        output: Any = job.output if isinstance(job.output, dict) else {}
        sources[scene.id] = SourceDraft(
            job_id=job.id,
            world_job_id=world_job_id,
            world=world,
            continuity=writer.continuity_from_drafts(output.get("drafts"), scene.id),
        )
    return sources


async def prompt_states(
    session: AsyncSession, project: Project, scenes: Sequence[Scene]
) -> dict[int, PromptState]:
    """The state of every scene that holds an AI image prompt, by scene id. Scenes with no
    prompt, or one the author wrote, are not in the answer: they cannot be out of date.
    """
    holding = [
        scene
        for scene in scenes
        if not _blank(scene.image_prompt) and scene.image_prompt_source == "ai"
    ]
    if not holding:
        return {}
    sources = await load_sources(session, project.id, holding)
    prompt_jobs = await _jobs_by_id(
        session,
        {s.image_prompt_job_id for s in holding if s.image_prompt_job_id is not None},
    )
    states: dict[int, PromptState] = {}
    for scene in holding:
        inputs = writer.prompt_inputs(scene, project, sources[scene.id])
        sha = writer.inputs_sha256(inputs)
        job = prompt_jobs.get(scene.image_prompt_job_id or 0)
        states[scene.id] = PromptState(
            inputs_sha256=sha, out_of_date=is_out_of_date(scene, sha, job)
        )
    return states


# --- Jobs -----------------------------------------------------------------------------


async def active_prompt_jobs(session: AsyncSession, project_id: int) -> dict[int, Job]:
    """The queued or running image prompt jobs of a project, by scene id."""
    statement = (
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.type == IMAGE_PROMPT_JOB,
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
        job_type=IMAGE_PROMPT_JOB,
        scene_id=scene_id,
    )


# --- What a job may write -----------------------------------------------------------------


def unchanged(scene: Scene, sent: Mapping[str, Any]) -> bool:
    """Whether the scene is still the one the request was built from: the same words over the
    same stretch of the voiceover. (Its number may differ, because a cut before it moved.)
    """
    return (
        scene.id == sent.get("scene_id")
        and scene.start_s == sent.get("start_s")
        and scene.end_s == sent.get("end_s")
        and scene.text == sent.get("text")
    )


def write_values(scene: Scene, prompt: str, job_id: int) -> dict[str, Any] | None:
    """The columns a job sets on the scene as it is now, or None when the author has written
    a prompt since: it is never overwritten. A blank prompt, or one the AI wrote, may be.
    """
    if prompt_is_authors(scene):
        return None
    return {
        "image_prompt": prompt,
        "image_prompt_source": "ai",
        "image_prompt_job_id": job_id,
    }
