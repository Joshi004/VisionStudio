"""The start of the building-blocks engine of the Graphics lab (GFX-009).

`remotion_blocks` has one model call of its own (the job `write_lab_graphic_block_scene`) that
designs the scene, and one render row that waits for it (`input` and `input_job_id`). The job
saves the scene on the row and queues the render.

`start` is the `start` function of the engine's entry in the registry
(`services/graphics_engines.py`). Like every `start`, it adds rows and a job and leaves the
commit to its caller.

This module imports no model, no renderer and no GPU code.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, LabGraphicRender, LabGraphicRun
from app.jobs import store

SCENE_JOB_TYPE: Final = "write_lab_graphic_block_scene"
SCENE_DEDUPE_KEY: Final = "run_id"
REQUESTED_SCENE: Final = "lab_graphic_block_scene"

ENGINE_KEY: Final = "remotion_blocks"


async def start(session: AsyncSession, run: LabGraphicRun) -> Job:
    """Starts the building-blocks engine for a run whose brief is ready: one scene job, and a
    render row that waits for it. Returns the job. No commit. When the run already has a scene
    job, it is returned and nothing is added.
    """
    if run.brief is None or run.resolved is None:
        raise ValueError("The brief is not written yet.")

    existing = await _existing_scene_job(session, run.id)
    if existing is not None:
        return existing

    job, created = await store.create_job(
        session,
        project_id=None,
        type=SCENE_JOB_TYPE,
        provider="llm",
        input={"requested": REQUESTED_SCENE, SCENE_DEDUPE_KEY: run.id},
        commit=False,
        dedupe_key=SCENE_DEDUPE_KEY,
    )
    if created:
        session.add(
            LabGraphicRender(
                run_id=run.id,
                engine=ENGINE_KEY,
                attempt=await _next_attempt(session, run.id),
                input_job_id=job.id,
            )
        )
    return job


async def _existing_scene_job(session: AsyncSession, run_id: int) -> Job | None:
    """The job of the newest building-blocks render of the run that has one, or None."""
    statement = (
        select(Job)
        .join(LabGraphicRender, LabGraphicRender.input_job_id == Job.id)
        .where(
            LabGraphicRender.run_id == run_id,
            LabGraphicRender.engine == ENGINE_KEY,
            Job.type == SCENE_JOB_TYPE,
        )
        .order_by(Job.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def _next_attempt(session: AsyncSession, run_id: int) -> int:
    attempts = await session.execute(
        select(LabGraphicRender.attempt).where(
            LabGraphicRender.run_id == run_id, LabGraphicRender.engine == ENGINE_KEY
        )
    )
    return max(attempts.scalars(), default=0) + 1
