"""The start of the two template engines of the Graphics lab (GFX-006).

`remotion_templates` and `python_templates` draw the same template spec, so one model call
(the job `write_lab_graphic_template_spec`) makes the spec for both, and each engine has a render
row of its own that shares that spec and the job that wrote it (`input` and `input_job_id`).
That is what makes the two videos comparable: the renderer is the only difference (G-5).

`start` is the `start` function of both entries of the engine registry
(`services/graphics_engines.py`). Whichever engine starts first adds the rows of both engines and
the job; the other finds them and starts nothing, so **Make all** makes one call. Like every
`start`, it adds rows and a job and leaves the commit to its caller.

This module imports no model, no renderer and no GPU code.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, LabGraphicRender, LabGraphicRun
from app.jobs import store

SPEC_JOB_TYPE: Final = "write_lab_graphic_template_spec"
SPEC_DEDUPE_KEY: Final = "run_id"
REQUESTED_SPEC: Final = "lab_graphic_template_spec"

TEMPLATE_ENGINE_KEYS: Final = ("remotion_templates", "python_templates")


async def start(session: AsyncSession, run: LabGraphicRun) -> Job:
    """Starts the template engines for a run whose brief is ready: one spec job, and a render row
    for each of the two engines that waits for it. Returns the job. No commit. When a spec job
    already exists for the run's template engines, it is returned and nothing is added.
    """
    if run.brief is None or run.resolved is None:
        raise ValueError("The brief is not written yet.")

    existing = await _existing_spec_job(session, run.id)
    if existing is not None:
        return existing

    job, created = await store.create_job(
        session,
        project_id=None,
        type=SPEC_JOB_TYPE,
        provider="llm",
        input={"requested": REQUESTED_SPEC, SPEC_DEDUPE_KEY: run.id},
        commit=False,
        dedupe_key=SPEC_DEDUPE_KEY,
    )
    if created:
        for key in TEMPLATE_ENGINE_KEYS:
            session.add(
                LabGraphicRender(
                    run_id=run.id,
                    engine=key,
                    attempt=await _next_attempt(session, run.id, key),
                    input_job_id=job.id,
                )
            )
    return job


async def _existing_spec_job(session: AsyncSession, run_id: int) -> Job | None:
    """The job of the newest template-engine render of the run that has one, or None."""
    statement = (
        select(Job)
        .join(LabGraphicRender, LabGraphicRender.input_job_id == Job.id)
        .where(
            LabGraphicRender.run_id == run_id,
            LabGraphicRender.engine.in_(TEMPLATE_ENGINE_KEYS),
            Job.type == SPEC_JOB_TYPE,
        )
        .order_by(Job.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def _next_attempt(session: AsyncSession, run_id: int, engine: str) -> int:
    attempts = await session.execute(
        select(LabGraphicRender.attempt).where(
            LabGraphicRender.run_id == run_id, LabGraphicRender.engine == engine
        )
    )
    return max(attempts.scalars(), default=0) + 1
