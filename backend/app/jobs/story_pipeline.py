"""The `story_pipeline` job: one run of the whole story pipeline of a project (PHASE-030).

The run works through the steps of `services/story_pipeline.STEPS` (Story Bible, the three
discoveries, definitions, images, voices, speech, shots, clips, render). It makes the same jobs
the stage buttons make, with each stage's own start function, and skips whatever is up to date.
A step starts when the steps it needs are complete. A target (a character, a scene, a shot) whose
job fails is tried again, up to `MAX_TRIES` jobs per step in one run; after that the run stops,
once nothing else can go on, and says what is wrong.

How many of those jobs run at once is not the run's business: it makes every job that is ready
and the dispatcher starts them as the GPU server's and the paid API's slots free up.

How it fits the dispatcher (the loop itself is not touched):

- `start` saves a marker in `job.provider_job_id`, so the dispatcher asks the run `poll` at
  every tick, the way it asks a job on the GPU server. It is not an id on any server.
- `poll` is the whole run. Each call reads the database, looks at every step that is not
  complete and whose `needs` are, and makes the jobs those steps still need. A step that
  completes lets the steps after it be looked at in the same call. It returns True once the last
  step is complete, and then `finish` runs.
- The run keeps all its state in `job.output` (see `services/story_pipeline.py`), so a restart
  continues where it was (`resume`). It holds no state in memory.
- When the user ticked a step to pause after, the run pauses once that step is complete and the
  run made jobs in it: it saves `paused_at` and makes nothing more until Continue.

**The stages commit on their own.** Each stage start function commits the job it makes, so the
run cannot save its jobs and its progress in one transaction (the old narration run could). After
a crash between the two, the stage's own dedupe stops one job being made twice; at worst one try
goes uncounted. If the run was cancelled meanwhile, the jobs it has just made are cancelled.

**Paid calls are retried here, on purpose.** Every other paid job runs only from a click and is
never retried. A run is one click, and a failed target is tried up to `MAX_TRIES` times, so the
page says so before it starts. A paid job that a restart interrupted still fails, as always
(`never_rerun` is its handler's), and the run then counts it as a try.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import state_memo
from app.db.models import Job, Project
from app.db.session import SessionLocal
from app.jobs import dispatcher, phases, store
from app.jobs.handlers import JobHandler
from app.services import review_points as review_rules
from app.services import story_pipeline as pipeline
from app.services.story_pipeline_targets import ADAPTERS

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = pipeline.JOB_TYPE
# At most this many runs at once (a constant, not a setting). A run is a slot it holds for as
# long as it goes on, and it does no heavy work itself.
CONCURRENCY_LIMIT: Final = 5
# One poll starts jobs for at most this long. A story of hundreds of shots must not hold the
# dispatcher's tick: the rest is started on the next tick, which a nudge brings at once.
START_SECONDS: Final = 5.0
# A poll goes on to the steps after an inline step that did its work, at most this many times.
MAX_PASSES: Final = 6
# A poll that raises is tried again at the next tick. A run whose poll raises this many times
# in a row stops, instead of looking as if it were going on for ever.
MAX_POLL_FAILURES: Final = 5


@dataclass
class _Going:
    """A step that is not complete and whose `needs` are: what to do about it now."""

    step: pipeline.Step
    plan: pipeline.StepPlan


@dataclass
class _Evaluation:
    """Where the run is after reading the database."""

    # The run's output as it should be saved: every step that is complete marked, and the
    # progress of every step that is going on.
    output: dict[str, Any]
    # The steps that are going on, in the order of `STEPS`.
    going: list[_Going]
    finished: bool
    # The ticked step that has just become complete, when the run must pause after it.
    paused_after: str | None
    # The review point whose steps are all complete now, when the run must wait for the user.
    paused_review: str | None = None


@dataclass
class _Outcome:
    finished: bool = False
    # The run stopped (failed, was cancelled, or paused): nothing more to do in this poll.
    stopped: bool = False
    # An inline step did its work: the steps after it may be ready now.
    again: bool = False


def _needs_are_ready(
    step: pipeline.Step,
    complete: set[str],
    options: pipeline.RunOptions,
    output: dict[str, Any],
) -> bool:
    """Whether the steps `step` needs are complete and, for a step of a review point the user
    has not passed yet, not held back by one (PHASE-041). A step waits for the review of the
    steps it needs, but not for the steps of its own review point.
    """
    own = review_rules.point_of(step.key)
    own_steps = set(own.steps) if own is not None else set()
    held = {
        key
        for point in review_rules.REVIEW_POINTS
        if point.key in options.review_points and point.key not in output["reviewed"]
        for key in point.steps
    } - own_steps
    return all(key in complete and key not in held for key in step.needs)


def _review_stop(
    step_key: str,
    complete: set[str],
    options: pipeline.RunOptions,
    output: dict[str, Any],
) -> str | None:
    """The review point to wait at now that `step_key` is complete, or None.

    The point must be enabled, not passed yet, and all its steps complete. If the run made
    nothing in them (they were all up to date) the point is passed without waiting, as a step to
    pause after is.
    """
    point = review_rules.point_of(step_key)
    if (
        point is None
        or point.key not in options.review_points
        or point.key in output["reviewed"]
        or not all(key in complete for key in point.steps)
    ):
        return None
    if all(pipeline.made_no_jobs(output, key) for key in point.steps):
        output["reviewed"].append(point.key)
        return None
    return point.key


async def _load_project(session: AsyncSession, project_id: int | None) -> Project | None:
    if project_id is None:
        return None
    statement = (
        select(Project).where(Project.id == project_id).execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


def _stop_reason(
    output: dict[str, Any], problems: list[pipeline.Problem], going: list[_Going]
) -> str:
    """What the run says when it stops. Nothing is running and nothing can be started, so either
    something is reported (a target that failed every try, a block), or, which should not happen,
    nothing is, and the run says so instead of waiting for ever.
    """
    done = len(pipeline.complete_keys(output))
    if problems:
        return pipeline.failure_message(done, len(pipeline.STEPS), problems)
    return pipeline.idle_message(done, len(pipeline.STEPS), [item.step for item in going])


def _phase_of(output: dict[str, Any], going: list[_Going], scope: pipeline.Scope) -> str:
    running = [(item.step.label, item.plan.done, item.plan.total) for item in going]
    return pipeline.phase_of(output, running, scope)


async def _cancel_jobs(session: AsyncSession, job_ids: list[int]) -> None:
    """Cancels jobs this poll has just made, for a run that was cancelled meanwhile."""
    for job_id in job_ids:
        try:
            await store.cancel_job(session, job_id)
        except store.JobActionError:
            continue  # it started or finished already


class StoryPipelineHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    # With its marker the dispatcher keeps polling the run after a restart. Without one the run
    # never got going, and starts again.
    restart_rule = "resume"

    def __init__(self) -> None:
        # Polls of a run that raised in a row. Only to stop a run that cannot be read.
        self._poll_failures: dict[int, int] = {}

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
            output = pipeline.read_output(job.output)
            saved = await store.save_progress(
                session,
                job_id,
                phase=_phase_of(output, [], pipeline.RunOptions.from_input(job.input).scope),
                output=output,
                provider_job_id=pipeline.MARKER,
            )
            await session.commit()
        if not saved:
            return
        _logger.info("job %d: pipeline run started: project=%d", job_id, project.id)

        # The first step is done now. The dispatcher skips a job while its `start` task is
        # alive, so waiting for its next tick would delay the first step by a whole interval.
        try:
            if await self.poll(job_id):
                await self.finish(job_id)
        except Exception:
            # Not fatal: the next tick checks the run again, as it does after any poll.
            _logger.exception("job %d: the first check of the pipeline run failed", job_id)

    # --- Poll: every step that can go on, once per tick ----------------------------------

    async def poll(self, job_id: int) -> bool:
        """Moves the run forward. True when every step is complete (then `finish` runs)."""
        try:
            finished = await self._poll(job_id)
        except Exception as exc:
            failures = self._poll_failures.get(job_id, 0) + 1
            self._poll_failures[job_id] = failures
            _logger.exception("job %d: the pipeline run could not be checked", job_id)
            if failures >= MAX_POLL_FAILURES:
                self._poll_failures.pop(job_id, None)
                async with SessionLocal() as session:
                    await store.fail_job(
                        session,
                        job_id,
                        f"Stopped: the project could not be read {failures} times in a row "
                        f"({type(exc).__name__}: {exc}).",
                    )
            return False
        self._poll_failures.pop(job_id, None)
        return finished

    async def _poll(self, job_id: int) -> bool:
        for _ in range(MAX_PASSES):
            # A session of its own for every pass: what the stages read is never older than the
            # pass, even when the jobs they started have been working meanwhile.
            async with SessionLocal() as session:
                outcome = await self._pass(session, job_id)
            if outcome.finished:
                return True
            if outcome.stopped or not outcome.again:
                return False
        return False

    async def _pass(self, session: AsyncSession, job_id: int) -> _Outcome:
        run = await store.get_job(session, job_id)
        if run is None or run.status != "running":
            await session.commit()
            return _Outcome(stopped=True)
        project = await _load_project(session, run.project_id)
        if project is None:
            await store.fail_job(session, job_id, "The project no longer exists.")
            return _Outcome(stopped=True)
        waiting = pipeline.read_output(run.output)
        if waiting["paused_at"] is not None or waiting["review_at"] is not None:
            await session.commit()  # waiting for Continue: nothing to read or make
            return _Outcome(stopped=True)
        # Evaluating writes nothing, so each stage's state is worked out once. Starting jobs
        # (`_apply`) writes, and reads fresh data.
        async with state_memo.reading(session):
            result = await self._evaluate(session, run, project)
        return await self._apply(session, run, project, result)

    @staticmethod
    async def _evaluate(session: AsyncSession, run: Job, project: Project) -> _Evaluation:
        """Reads the database and looks at the steps in the order of `STEPS`. Writes nothing.

        - A step the run has passed (`done`, `skipped`) is not looked at again, except after a
          Continue (`recheck`): then it is read once more, so what the user edited during the
          pause is seen. A step that is no longer complete is going on again, and the steps
          that need it wait for it.
        - A step whose `needs` are not all complete is not reached: it makes no job yet. A step
          that needs a step of a review point the user has not passed yet waits for the review.
        - A step that turns out complete is passed. The steps after it are looked at in this same
          call, so the run never loses a tick. Unless it is a step to pause after, or the last
          step of a review point: the run made jobs there and the user asked to stop, so the
          evaluation stops there.
        """
        output = pipeline.read_output(run.output)
        options = pipeline.RunOptions.from_input(run.input)
        complete = pipeline.complete_keys(output)
        recheck: bool = output["recheck"]
        going: list[_Going] = []
        paused_after: str | None = None
        paused_review: str | None = None

        for step in pipeline.STEPS:
            was_complete = step.key in complete
            if was_complete:
                if not recheck:
                    continue
                if not all(key in complete for key in step.needs):
                    # Something it needs is being made again: it is looked at once that is done.
                    complete.discard(step.key)
                    output["steps"][step.key]["status"] = "pending"
                    continue
            elif not _needs_are_ready(step, complete, options, output):
                continue
            view = await ADAPTERS[step.key].evaluate(session, project, options)
            # Work this run has made in a step this one needs (scope `out_of_date` only).
            made_upstream = any(output["tries"][key] for key in step.needs)
            plan = pipeline.plan_step(
                step,
                view,
                output["tries"][step.key],
                output["errors"][step.key],
                options,
                made_upstream,
                output["rejected"].get(step.key, ()),
            )
            pipeline.add_warnings(output, plan.warnings)
            if plan.complete and was_complete:
                # Still complete after the Continue: only its counts are brought up to date.
                kept = cast(pipeline.StepStatus, output["steps"][step.key]["status"])
                pipeline.record_progress(output, step.key, plan, status=kept)
            elif plan.complete:
                # "Skipped": it was complete when the run got to it, so the run started nothing.
                status = "skipped" if pipeline.made_no_jobs(output, step.key) else "done"
                pipeline.record_progress(output, step.key, plan, status=status)
                complete.add(step.key)
                output["rejected"].pop(step.key, None)
                paused_review = _review_stop(step.key, complete, options, output)
                if paused_review is not None:
                    break
                if (
                    status == "done"
                    and step.key in options.pause_after
                    and step.key not in output["continued"]
                ):
                    paused_after = step.key
                    break
            else:
                complete.discard(step.key)
                pipeline.record_progress(output, step.key, plan, status="running")
                going.append(_Going(step, plan))
        else:
            output["recheck"] = False  # every step was looked at

        finished = len(complete) == len(pipeline.STEPS)
        if finished:
            output["problems"] = []
        return _Evaluation(output, going, finished, paused_after, paused_review)

    @staticmethod
    async def _apply(
        session: AsyncSession, run: Job, project: Project, result: _Evaluation
    ) -> _Outcome:
        """Starts what every step that is going on needs, saves the run's progress, and stops the
        run when nothing can go on or it is to pause.
        """
        output = result.output
        options = pipeline.RunOptions.from_input(run.input)
        outcome = _Outcome(finished=result.finished)
        made: list[int] = []
        problems: list[pipeline.Problem] = []
        # Targets with work in progress, or about to get some, in every step.
        in_progress = 0
        deferred = False
        started_any = False
        queued_any = False
        failure: str | None = None
        paused_phase: str | None = None

        if result.paused_review is not None:
            # Nothing more is made while the user reviews, in any step. Jobs that are running
            # finish.
            output["review_at"] = result.paused_review
            paused_phase = phases.pipeline_review(
                review_rules.POINTS_BY_KEY[result.paused_review].label
            )
            output["problems"] = []
            outcome.finished = False
        elif result.paused_after is not None:
            # Nothing more is made while paused, in any step. Jobs that are running finish.
            output["paused_at"] = result.paused_after
            paused_phase = phases.pipeline_paused(pipeline.STEP_LABELS[result.paused_after])
            output["problems"] = []
            outcome.finished = False  # even a ticked last step waits for Continue
        elif not result.finished:
            deadline = time.monotonic() + START_SECONDS
            for item in result.going:
                problems.extend(item.plan.problems)
                in_progress += item.plan.waiting + len(item.plan.creates)
                if not item.plan.creates:
                    continue
                if started_any and time.monotonic() > deadline:
                    deferred = True
                    continue
                started = await ADAPTERS[item.step.key].start(
                    session, project, item.plan.creates, options, deadline
                )
                started_any = True
                deferred = deferred or len(started) < len(item.plan.creates)
                for entry in started:
                    pipeline.record_try(output, item.step.key, entry.target.key, entry)
                    made.extend(entry.job_ids)
                    if entry.error is None:
                        queued_any = True
                        outcome.again = outcome.again or item.step.inline

            output["problems"] = [problem.as_json() for problem in problems]
            # Other targets (and other steps) go on first: the run stops only when nothing is
            # left that could still succeed.
            if in_progress == 0:
                failure = _stop_reason(output, problems, result.going)
                for key in {problem.step_key for problem in problems}:
                    if key in output["steps"]:
                        output["steps"][key]["status"] = "failed"

        phase = paused_phase or _phase_of(output, result.going, options.scope)
        nothing_new = (
            not started_any
            and failure is None
            and paused_phase is None
            and output == run.output
            and phase == run.phase
        )
        if nothing_new:
            await session.commit()  # nothing changed: write nothing
            return outcome

        if not await store.save_progress(session, run.id, phase=phase, output=output):
            # Cancelled in the meantime: the jobs just made are not wanted.
            await session.rollback()
            await _cancel_jobs(session, made)
            outcome.stopped = True
            outcome.finished = False
            return outcome

        if failure is not None:
            await store.fail_job(session, run.id, failure)  # commits the output with it
            _logger.info(
                "job %d: pipeline run stopped: %s",
                run.id,
                ", ".join(item.step.key for item in result.going),
            )
            outcome.stopped = True
            return outcome

        await session.commit()
        if paused_phase is not None:
            _logger.info(
                "job %d: pipeline run paused after '%s'",
                run.id,
                result.paused_review or result.paused_after,
            )
            outcome.stopped = True
            return outcome
        if queued_any:
            # What was started (jobs, looks, pictures) is for the dispatcher to run.
            _logger.info("job %d: pipeline run started work, %d job(s) made", run.id, len(made))
        if queued_any or deferred:
            dispatcher.nudge()  # a deferred rest is started on the next tick
        return outcome

    # --- Finish: every step is complete --------------------------------------------------

    async def finish(self, job_id: int) -> None:
        async with SessionLocal() as session:
            run = await store.get_job(session, job_id)
            if run is None or run.status != "running":
                await session.commit()
                return
            if not await store.finish_job(session, job_id, pipeline.read_output(run.output)):
                await session.rollback()
                return
            await session.commit()
        _logger.info("job %d: pipeline run finished", job_id)
