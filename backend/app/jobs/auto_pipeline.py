"""The `auto_pipeline` job: one run of the automatic flow of a project.

The run goes through the steps of `services/auto_pipeline.STEPS` (transcribe, propose scenes,
descriptions, image prompts, first frames, clips, final render). It makes the same jobs the
manual buttons make, and starts the next step only when every scene has finished the current
one. A scene (or the project) whose job fails is tried again, up to `MAX_TRIES` jobs in one
step; after that the run stops and says what is wrong.

How it fits the dispatcher (the loop itself is not touched):

- `start` saves a marker in `job.provider_job_id`, so the dispatcher asks the run `poll` at
  every tick, the way it asks a job on the GPU server. It is not an id on any server.
- `poll` is the whole run. Each call reads the database, finds the step the run is at, and
  makes the jobs that step still needs. When a step is complete it goes on to the next one in
  the same call. It returns True once the last step is complete, and then `finish` runs.
- The run keeps all its state in `job.output` (see `services/auto_pipeline.py`), including the
  ids of the jobs it made, so a restart continues where it was (`resume`). It holds no state in
  memory.

The jobs a run makes are saved in the same transaction as the run's output, so a crash
leaves either both or neither, and one job is never made twice.

**Paid calls are retried here, on purpose.** Every other paid job runs only from a click and is
never retried. A run is one click, and a failed scene is tried up to `MAX_TRIES` times, so the
page says so before it starts. A paid job that a restart interrupted still fails, as always
(`never_rerun` is its handler's), and the run then counts it as a try.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project
from app.db.session import SessionLocal
from app.jobs import dispatcher, phases, store
from app.jobs.handlers import JobHandler
from app.services import auto_pipeline as auto
from app.services import scenes as scenes_service

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = auto.JOB_TYPE
# At most this many runs at once (a constant, not a setting). A run is a slot it holds for as
# long as it goes on, and it does no heavy work itself.
CONCURRENCY_LIMIT: Final = 5


@dataclass
class _Evaluation:
    """Where the run is after reading the database."""

    # The run's output as it should be saved: every step it passed marked, and the progress of
    # the step it is at.
    output: dict[str, Any]
    # The step the run is at (the last one, once it has finished).
    index: int
    plan: auto.StepPlan
    finished: bool


async def _load_project(session: AsyncSession, project_id: int | None) -> Project | None:
    if project_id is None:
        return None
    statement = (
        select(Project).where(Project.id == project_id).execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


def _phase_of(index: int, plan: auto.StepPlan) -> str:
    step = auto.STEPS[index]
    return phases.auto_step(index + 1, len(auto.STEPS), step.label, plan.done, plan.total)


class AutoPipelineHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    # With its marker the dispatcher keeps polling the run after a restart. Without one the run
    # never got going, and starts again.
    restart_rule = "resume"

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return CONCURRENCY_LIMIT

    # --- Start: the marker that makes the dispatcher poll ------------------------------

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            project = await _load_project(session, job.project_id)
            if project is None:
                await store.fail_job(session, job_id, "The project no longer exists.")
                return

            # A run that starts again after a restart keeps what it had made.
            output = auto.read_output(job.output)
            index = auto.step_index(output["step"])
            saved = await store.save_progress(
                session,
                job_id,
                phase=phases.auto_step(index + 1, len(auto.STEPS), auto.STEPS[index].label, 0, 1),
                output=output,
                provider_job_id=auto.MARKER,
            )
            await session.commit()
        if not saved:
            return
        _logger.info("job %d: automatic run started: project=%d", job_id, project.id)

        # The first step is done now. The dispatcher skips a job while its `start` task is
        # alive, so waiting for its next tick would delay the first step by a whole interval.
        try:
            if await self.poll(job_id):
                await self.finish(job_id)
        except Exception:
            # Not fatal: the next tick checks the run again, as it does after any poll.
            _logger.exception("job %d: the first check of the automatic run failed", job_id)

    # --- Poll: one step of the run per tick ---------------------------------------------

    async def poll(self, job_id: int) -> bool:
        """Moves the run forward. True when every step is complete (then `finish` runs)."""
        async with SessionLocal() as session:
            run = await store.get_job(session, job_id)
            if run is None or run.status != "running":
                await session.commit()
                return False

            locked = False
            while True:
                project = await _load_project(session, run.project_id)
                if project is None:
                    await store.fail_job(session, job_id, "The project no longer exists.")
                    return False
                result = await self._evaluate(session, run, project)
                # Reading is free. Only a run that is about to make jobs takes the database's
                # write lock, like the buttons do (`scenes_service.lock_scenes`), and reads
                # again under it, so a cut edit cannot change a scene between the check and
                # the jobs.
                if locked or result.finished or not result.plan.creates:
                    break
                await scenes_service.lock_scenes(session, project.id)
                locked = True

            return await self._apply(session, run, project, result)

    @staticmethod
    async def _evaluate(session: AsyncSession, run: Job, project: Project) -> _Evaluation:
        """Reads the database, passes the steps that are complete, and stops at the first that
        is not. Writes nothing.
        """
        output = auto.read_output(run.output)
        options = auto.RunOptions.from_input(run.input)
        index = auto.step_index(output["step"])

        while True:
            step = auto.STEPS[index]
            run_jobs = await auto.load_run_jobs(session, output, step.key)
            view = await auto.evaluate(session, step, auto.RunContext(project, options, run_jobs))
            plan = auto.plan_step(step, view, run_jobs)
            output["step"] = step.key

            if not plan.complete:
                auto.record_progress(output, step.key, plan, status="running")
                return _Evaluation(output, index, plan, finished=False)

            # "Skipped": it was complete when the run got to it, so the run made no job for it.
            status = "skipped" if auto.made_no_jobs(output, step.key) else "done"
            auto.record_progress(output, step.key, plan, status=status)
            if index == len(auto.STEPS) - 1:
                output["problems"] = []
                return _Evaluation(output, index, plan, finished=True)
            index += 1

    @staticmethod
    async def _apply(
        session: AsyncSession, run: Job, project: Project, result: _Evaluation
    ) -> bool:
        """Makes the jobs the step needs, saves the run's progress with them in one transaction,
        and stops the run when a step cannot go on. True when the run has finished.
        """
        output = result.output
        plan = result.plan
        step = auto.STEPS[result.index]
        created = 0
        failure: str | None = None

        if not result.finished:
            for create in plan.creates:
                job, was_created = await auto.create_child(
                    session, project, step, create, run_id=run.id
                )
                if was_created:
                    auto.add_job_id(output, step.key, create.target.key, job.id)
                    created += 1
                # Not created: a job of this kind became active meanwhile. It is waited for.

            output["problems"] = [problem.as_json(step.key) for problem in plan.problems]
            in_progress = plan.waiting + len(plan.creates)
            # Other scenes of the step finish first: the run stops only when nothing is left
            # that could still succeed.
            if plan.problems and in_progress == 0:
                failure = auto.failure_message(
                    result.index + 1, len(auto.STEPS), step, plan.problems
                )
                output["steps"][step.key]["status"] = "failed"

        phase = _phase_of(result.index, plan)
        if created == 0 and failure is None and output == run.output and phase == run.phase:
            await session.commit()  # nothing changed: write nothing
            return result.finished

        if not await store.save_progress(session, run.id, phase=phase, output=output):
            # Cancelled in the meantime: the jobs just made go with this transaction.
            await session.rollback()
            return False

        if failure is not None:
            await store.fail_job(session, run.id, failure)  # commits the output with it
            _logger.info("job %d: automatic run stopped at step %s", run.id, step.key)
            return False

        await session.commit()
        if created:
            _logger.info(
                "job %d: step %s: made %d job(s), %d of %d done",
                run.id,
                step.key,
                created,
                plan.done,
                plan.total,
            )
            dispatcher.nudge()
        return result.finished

    # --- Finish: every step is complete --------------------------------------------------

    async def finish(self, job_id: int) -> None:
        async with SessionLocal() as session:
            run = await store.get_job(session, job_id)
            if run is None or run.status != "running":
                await session.commit()
                return
            if not await store.finish_job(session, job_id, auto.read_output(run.output)):
                await session.rollback()
                return
            await session.commit()
        _logger.info("job %d: automatic run finished", job_id)
