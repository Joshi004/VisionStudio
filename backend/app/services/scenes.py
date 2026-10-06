"""Scenes in the database (ANALYSIS.md Section 5.2; DATABASE_STRUCTURE.md Section 4.4).

A proposal replaces all the scenes of a project in one transaction (`replace_scenes`). The
scenes belong to the newest `plan_scenes` job that succeeded. That job's input records the
voiceover and the script it was made from, so the scenes are *out of date* when either has
changed since, the same way a transcript is (`services/transcripts.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, Scene
from app.jobs import store
from app.services import transcript_matching
from app.services.scene_cuts import SceneSpec, has_inputs

PLAN_JOB: Final = "plan_scenes"

StaleReason = Literal["script_changed", "voiceover_changed"]

# How many of a project's newest proposal jobs the cache looks through.
_CACHE_LOOKBACK: Final = 100


async def list_scenes(session: AsyncSession, project_id: int) -> list[Scene]:
    statement = (
        select(Scene)
        .where(Scene.project_id == project_id)
        .order_by(Scene.index)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars().all())


async def scenes_with_inputs(session: AsyncSession, project_id: int) -> int:
    """How many of the project's scenes hold a description, a frame or a clip."""
    return sum(1 for scene in await list_scenes(session, project_id) if has_inputs(scene))


async def replace_scenes(
    session: AsyncSession, project_id: int, specs: Sequence[SceneSpec]
) -> list[Scene]:
    """Deletes the project's scenes and inserts the new ones. Flushes, does not commit: the
    caller commits it together with the job that made them.

    Stored files are never deleted. Deleting a scene also deletes the jobs that point at it
    (ON DELETE CASCADE): none exist before Phase 9's clip jobs.
    """
    await session.execute(delete(Scene).where(Scene.project_id == project_id))
    scenes = [
        Scene(
            project_id=project_id,
            index=spec.index,
            start_s=spec.start_s,
            end_s=spec.end_s,
            text=spec.text,
            cut_source=spec.cut_source,
            cut_note=spec.cut_note,
        )
        for spec in specs
    ]
    session.add_all(scenes)
    await session.flush()
    return scenes


async def proposal_job(session: AsyncSession, project_id: int) -> Job | None:
    """The newest proposal that succeeded: the one the project's scenes came from."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == PLAN_JOB, Job.status == "succeeded")
        .order_by(Job.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


def stale_reasons(job: Job, project: Project) -> list[StaleReason]:
    """Why the scenes of this proposal no longer fit the project's voiceover or script."""
    recorded: Any = job.input if isinstance(job.input, dict) else {}
    reasons: list[StaleReason] = []
    if recorded.get("voiceover_asset_id") != project.voiceover_asset_id:
        reasons.append("voiceover_changed")
    if recorded.get("script_sha256") != transcript_matching.script_sha256(
        project.script_text or ""
    ):
        reasons.append("script_changed")
    return reasons


async def find_cached_answer(
    session: AsyncSession, project_id: int, input_hash: str, exclude_job_id: int
) -> Job | None:
    """The newest earlier proposal that sent exactly this request and kept a usable answer.

    Any status counts: a job that failed after the paid call (interrupted by a restart,
    say) still holds the answer it paid for (ANALYSIS.md Section 6.2, rule 3). A job that
    itself reused an answer holds none, so a hit always points at the job that paid.
    """
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == PLAN_JOB, Job.id != exclude_job_id)
        .order_by(Job.id.desc())
        .limit(_CACHE_LOOKBACK)
        .execution_options(populate_existing=True)
    )
    for job in (await session.execute(statement)).scalars():
        if not isinstance(job.input, dict) or job.input.get("input_hash") != input_hash:
            continue
        output = job.output
        if (
            isinstance(output, dict)
            and output.get("answer_usable") is True
            and isinstance(output.get("answer"), dict)
        ):
            return job
    return None


@dataclass(frozen=True)
class ScenesState:
    # The newest plan_scenes job, whatever its status. None if there never was one.
    job: Job | None
    # The newest one that succeeded: where the scenes came from.
    proposal: Job | None
    scenes: list[Scene]
    stale_reasons: list[StaleReason]


async def scenes_state(session: AsyncSession, project: Project) -> ScenesState:
    job = await store.latest_job(session, project.id, PLAN_JOB)
    proposal = await proposal_job(session, project.id)
    scenes = await list_scenes(session, project.id)
    reasons = stale_reasons(proposal, project) if proposal is not None and scenes else []
    return ScenesState(job=job, proposal=proposal, scenes=scenes, stale_reasons=reasons)
