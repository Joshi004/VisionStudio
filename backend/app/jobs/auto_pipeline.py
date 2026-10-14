"""The `auto_pipeline` job: one run of the automatic flow of a project.

The run works through the steps of `services/auto_pipeline.STEPS` (make the voiceover when
there is none, transcribe, propose scenes, find the cast and draw it, choose who is in each
scene, descriptions, image prompts, first frames, last frame prompts, last frames, clips, final
render). It makes the same jobs the manual buttons make. The steps are a graph: a step starts
when the steps it needs are complete, and a scene (or a character, or a place) goes on to the
next step as soon as its own input is ready, without waiting for the others. A scene (or the
project) whose job fails is tried again, up to `MAX_TRIES` jobs in one step; after that the run
stops, once nothing else can go on, and says what is wrong.

How many of those jobs run at once is not the run's business: it makes every job that is ready
and the dispatcher starts them as the GPU server's and the paid API's slots free up.

How it fits the dispatcher (the loop itself is not touched):

- `start` saves a marker in `job.provider_job_id`, so the dispatcher asks the run `poll` at
  every tick, the way it asks a job on the GPU server. It is not an id on any server.
- `poll` is the whole run. Each call reads the database, looks at every step that is not
  complete and whose `needs` are, and makes the jobs those steps still need. A step that
  completes lets the steps after it be looked at in the same call. It returns True once the
  last step is complete, and then `finish` runs.
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
from app.services import last_frames as last_frames_service
from app.services import scenes as scenes_service

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = auto.JOB_TYPE
# At most this many runs at once (a constant, not a setting). A run is a slot it holds for as
# long as it goes on, and it does no heavy work itself.
CONCURRENCY_LIMIT: Final = 5


@dataclass
class _Going:
    """A step that is not complete and whose `needs` are: what to do about it now."""

    step: auto.Step
    plan: auto.StepPlan


@dataclass
class _Evaluation:
    """Where the run is after reading the database."""

    # The run's output as it should be saved: every step that is complete marked, and the
    # progress of every step that is going on.
    output: dict[str, Any]
    # The steps that are going on, in the order of `STEPS`.
    going: list[_Going]
    finished: bool

    @property
    def creates(self) -> bool:
        return any(item.plan.creates for item in self.going)


def _complete_keys(output: dict[str, Any]) -> set[str]:
    """The steps the run has passed: complete, or complete when it got to them."""
    return {
        key for key in auto.STEP_KEYS if output["steps"][key].get("status") in ("done", "skipped")
    }


async def _load_project(session: AsyncSession, project_id: int | None) -> Project | None:
    if project_id is None:
        return None
    statement = (
        select(Project).where(Project.id == project_id).execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


def _stop_reason(output: dict[str, Any], problems: list[auto.Problem], result: _Evaluation) -> str:
    """What the run says when it stops. Nothing is running and nothing can be started, so either
    something is reported (a scene that failed every try, a block), or, which should not happen,
    nothing is, and the run says so instead of waiting for ever.
    """
    done = len(_complete_keys(output))
    if problems:
        return auto.failure_message(done, len(auto.STEPS), problems)
    return auto.idle_message(done, len(auto.STEPS), [item.step for item in result.going])


def _phase_of(output: dict[str, Any], going: list[_Going]) -> str:
    running = [(item.step.label, item.plan.done, item.plan.total) for item in going]
    return phases.auto_progress(len(_complete_keys(output)), len(auto.STEPS), running)


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
            saved = await store.save_progress(
                session,
                job_id,
                phase=_phase_of(output, []),
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

    # --- Poll: every step that can go on, once per tick ----------------------------------

    async def poll(self, job_id: int) -> bool:
        """Moves the run forward. True when every step is complete (then `finish` runs)."""
        async with SessionLocal() as session:
            run = await store.get_job(session, job_id)
            if run is None or run.status != "running":
                await session.commit()
                return False

            await self._apply_chains(session, run)

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
                if locked or result.finished or not result.creates:
                    break
                await scenes_service.lock_scenes(session, project.id)
                locked = True

            return await self._apply(session, run, project, result)

    @staticmethod
    async def _apply_chains(session: AsyncSession, run: Job) -> None:
        """Gives a scene that continues the previous scene's action the last frame that scene
        ends on, when that frame was made before this run: no job of this run will attach it, so
        nothing else would. Reading is free; the write lock is taken (like the buttons do) only
        when there is something to move, and the check is made again under it.
        """
        if run.project_id is None:
            return
        if not await last_frames_service.pending_chains(session, run.project_id):
            return
        await scenes_service.lock_scenes(session, run.project_id)
        moved = await last_frames_service.apply_chains(session, run.project_id)
        await session.commit()
        if moved:
            _logger.info("job %d: last frames used as the first frame of scenes %s", run.id, moved)

    @staticmethod
    async def _evaluate(session: AsyncSession, run: Job, project: Project) -> _Evaluation:
        """Reads the database and looks at the steps in the order of `STEPS`, which is an order in
        which a step comes after the steps it needs and follows. Writes nothing.

        - A step the run has passed (`done`, `skipped`) is not looked at again.
        - A step whose `needs` are not all complete is not reached: it makes no job yet.
        - Any other step is evaluated, and planned with what the steps before it found in this
          same call (`Standing`), so a scene waits for its own earlier step, not for all of it.
        - A step that turns out complete, and whose `follows` are complete, is passed. The steps
          after it are then looked at in this same call, so the run never loses a tick.
        """
        output = auto.read_output(run.output)
        options = auto.RunOptions.from_input(run.input)
        complete = _complete_keys(output)
        standing = auto.Standing()
        going: list[_Going] = []

        for step in auto.STEPS:
            if step.key in complete:
                continue
            if not all(key in complete for key in step.needs):
                standing = standing.with_unreached(step.key)
                continue

            run_jobs = await auto.load_run_jobs(session, output, step.key)
            view = await auto.evaluate(session, step, auto.RunContext(project, options, run_jobs))
            plan = auto.plan_step(step, view, run_jobs, standing)
            standing = standing.after_step(step.key, plan)

            if plan.complete and all(key in complete for key in step.follows):
                # "Skipped": it was complete when the run got to it, so the run made no job.
                status = "skipped" if auto.made_no_jobs(output, step.key) else "done"
                auto.record_progress(output, step.key, plan, status=status)
                complete.add(step.key)
            else:
                auto.record_progress(output, step.key, plan, status="running")
                going.append(_Going(step, plan))

        finished = len(complete) == len(auto.STEPS)
        if finished:
            output["problems"] = []
        return _Evaluation(output, going, finished)

    @staticmethod
    async def _apply(
        session: AsyncSession, run: Job, project: Project, result: _Evaluation
    ) -> bool:
        """Makes the jobs every step that is going on needs, saves the run's progress with them in
        one transaction, and stops the run when nothing can go on. True when it has finished.
        """
        output = result.output
        created: dict[str, int] = {}
        problems: list[auto.Problem] = []
        # Targets with a job in progress, or about to get one, in every step.
        in_progress = 0
        failure: str | None = None

        if not result.finished:
            for item in result.going:
                for create in item.plan.creates:
                    job, was_created = await auto.create_child(
                        session, project, item.step, create, run_id=run.id
                    )
                    if was_created:
                        auto.add_job_id(output, item.step.key, create.target.key, job.id)
                        created[item.step.key] = created.get(item.step.key, 0) + 1
                    # Not created: a job of this kind became active meanwhile. It is waited for.
                problems.extend(item.plan.problems)
                in_progress += item.plan.waiting + len(item.plan.creates)

            output["problems"] = [problem.as_json() for problem in problems]
            # Other scenes (and other steps) go on first: the run stops only when nothing is
            # left that could still succeed.
            if in_progress == 0:
                failure = _stop_reason(output, problems, result)
                for key in {problem.step_key for problem in problems}:
                    if key in output["steps"]:
                        output["steps"][key]["status"] = "failed"

        phase = _phase_of(output, result.going)
        total_created = sum(created.values())
        if total_created == 0 and failure is None and output == run.output and phase == run.phase:
            await session.commit()  # nothing changed: write nothing
            return result.finished

        if not await store.save_progress(session, run.id, phase=phase, output=output):
            # Cancelled in the meantime: the jobs just made go with this transaction.
            await session.rollback()
            return False

        if failure is not None:
            await store.fail_job(session, run.id, failure)  # commits the output with it
            _logger.info(
                "job %d: automatic run stopped: %s",
                run.id,
                ", ".join(item.step.key for item in result.going),
            )
            return False

        await session.commit()
        if created:
            _logger.info(
                "job %d: made %d job(s): %s",
                run.id,
                total_created,
                ", ".join(f"{key} {count}" for key, count in created.items()),
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
