"""The start of the generated-component engine of the Graphics lab (GFX-010).

`generated_component` has one model call of its own (the job `write_lab_graphic_component`) that
writes the component's code, and one render row that waits for it (`input` and `input_job_id`).
The job saves the code on the row and queues the render.

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

COMPONENT_JOB_TYPE: Final = "write_lab_graphic_component"
COMPONENT_DEDUPE_KEY: Final = "run_id"
REQUESTED_COMPONENT: Final = "lab_graphic_component"

ENGINE_KEY: Final = "generated_component"


async def start(session: AsyncSession, run: LabGraphicRun, *, again: bool = False) -> Job:
    """Starts the generated-component engine for a run whose brief is ready: one component job,
    and a render row that waits for it. Returns the job. No commit. When the run already has a
    component job, it is returned and nothing is added. With `again` (GFX-011) that check is
    skipped: a new component job and a new render row (the next attempt) are made.
    """
    if run.brief is None or run.resolved is None:
        raise ValueError("The brief is not written yet.")

    if not again:
        existing = await _existing_component_job(session, run.id)
        if existing is not None:
            return existing

    job, created = await store.create_job(
        session,
        project_id=None,
        type=COMPONENT_JOB_TYPE,
        provider="llm",
        input={"requested": REQUESTED_COMPONENT, COMPONENT_DEDUPE_KEY: run.id},
        commit=False,
        dedupe_key=COMPONENT_DEDUPE_KEY,
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


async def _existing_component_job(session: AsyncSession, run_id: int) -> Job | None:
    """The job of the newest generated-component render of the run that has one, or None."""
    statement = (
        select(Job)
        .join(LabGraphicRender, LabGraphicRender.input_job_id == Job.id)
        .where(
            LabGraphicRender.run_id == run_id,
            LabGraphicRender.engine == ENGINE_KEY,
            Job.type == COMPONENT_JOB_TYPE,
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
