"""The dispatcher: the one loop that moves background jobs forward
(ANALYSIS.md Section 3.3).

It starts with the app and does the scheduling only. It never does slow work itself:
uploads, downloads and the like run as separate tasks it starts. All job state lives in
the `job` table, so after a restart the loop simply continues from the database. Only the
task handles are in memory.

Each tick, which happens every poll interval (a setting) or sooner when something nudges
the loop:

1. Read the poll interval and the upload and download limits (`gpu_server.set_transfer_limits`),
   the running and the queued jobs, and the limit of each pool. There
   are two shared pools, the GPU server and the paid inference API (`jobs/pools.py`): every
   kind of job counts in the pool of its provider, and has no limit of its own. A language-model
   job counts where its calls go, so one answered by Qwen3.8 is in the GPU server's. A local job
   type is a pool of its own.
2. If any GPU job needs the server, check its health and store the result for the banner.
   If it does not answer, GPU jobs wait, and the loop backs off (the wait doubles up to
   120 s, or the poll interval if that is longer).
3. Ask each running remote job's handler to `poll`. A handler that says "ready" gets its
   `finish` started as a task. The story pipeline run, whose poll takes many seconds, is polled
   in a task of its own, so the tick does not wait for it.
4. Start queued jobs while their pool has room and, for a remote server job, its model family is
   under its own limit (a family at its limit holds back only its own jobs): the jobs others
   wait for first (`input.priority`, the clips of shots that other shots continue), then oldest
   first. Before the first GPU job is started, the GPU API is read and recorded (ANALYSIS.md
   Section 6.5).
   A change in the API never stops a job: the app is updated to match the server, so
   nobody has to approve a new version to keep working.
5. Wait.

One uvicorn process runs one loop (Section 3.2). Run a second process and each would run
its own loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Coroutine
from typing import Any, Final

from sqlalchemy import exc as sa_exc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core import settings as settings_service
from app.db.models import Job
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.jobs import handlers, live_status, phase_writer, phases, pools, register_handlers, store
from app.jobs.handlers import MAX_AUTOMATIC_RERUNS, JobHandler
from app.providers import contract_guard, gpu_server
from app.services import gpu_status

POLL_INTERVAL_KEY: Final = "poll_interval_seconds"
MAX_PARALLEL_UPLOADS_KEY: Final = "max_parallel_uploads"
MAX_PARALLEL_DOWNLOADS_KEY: Final = "max_parallel_downloads"
GPU_URL_KEY: Final = "gpu_api_base_url"
TRANSCRIPTION_URL_KEY: Final = "transcription_url"
# How many running jobs are asked about at once in one tick. The rest wait for a free place, so
# hundreds of running jobs do not make hundreds of calls in the same instant.
MAX_PARALLEL_POLLS: Final = 20
MAX_BACKOFF_S: Final = 120.0
# How long to wait after a tick that failed unexpectedly.
FALLBACK_WAIT_S: Final = 15.0
# A job that a handler put back in the queue is left alone for at least this long.
MIN_RETRY_DELAY_S: Final = 5.0
INTERRUPTED_MESSAGE: Final = (
    f"Interrupted by a restart, and already tried {MAX_AUTOMATIC_RERUNS + 1} times. Start it again."
)
UNEXPECTED_ERROR_MAX_CHARS: Final = 500
# What a queued job shows while its pool is full.
_SLOT_PHASES: Final = {
    pools.GPU_POOL: phases.WAITING_FOR_GPU_SLOT,
    pools.PAID_API_POOL: phases.WAITING_FOR_PAID_API_SLOT,
}

_logger = logging.getLogger(__name__)


def _may_rerun(job: Job, handler: JobHandler) -> bool:
    """Whether a paid job that was cut short is queued again, rather than failed: its handler
    allows it and it has not been run `MAX_AUTOMATIC_RERUNS` times again already.
    """
    return (
        handler.restart_rule == "never_rerun"
        and handler.rerun_automatically
        and job.attempt <= MAX_AUTOMATIC_RERUNS
    )


def _is_transient_db_error(exc: BaseException) -> bool:
    """A database error that passes: no connection was free in time (pool timeout), or the file
    stayed locked by another writer longer than `busy_timeout`.
    """
    if isinstance(exc, sa_exc.TimeoutError):
        return True
    return isinstance(exc, sa_exc.OperationalError) and "database is locked" in str(exc).lower()


class _Dispatcher:
    def __init__(self) -> None:
        self._loop_task: asyncio.Task[None] | None = None
        # Job id -> the task doing that job's `start` or `finish`. At most one per job.
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._wakeup = asyncio.Event()
        self._backoff_s = 0.0
        self._interval_s = FALLBACK_WAIT_S
        # Job id -> monotonic time before which a queued job is not started again.
        self._retry_after: dict[int, float] = {}
        # Job id -> monotonic time before which a poll that runs in the background (the pipeline
        # run) is not started again. Without it, every nudge would start the next pass at once.
        self._poll_after: dict[int, float] = {}
        self._warned_types: set[str] = set()

    # --- Lifecycle --------------------------------------------------------------

    async def start(self) -> None:
        if self._loop_task is not None:
            return
        register_handlers()
        try:
            await self._recover()
        except Exception:
            # The tick also puts orphaned jobs right, so the app can still start.
            _logger.exception("dispatcher: recovery after the restart failed")
        phase_writer.start()
        metrics.start_loop_watch()
        self._loop_task = asyncio.create_task(self._run(), name="dispatcher")
        _logger.info("dispatcher started")

    async def stop(self) -> None:
        tasks = [task for task in (self._loop_task, *self._tasks.values()) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await phase_writer.stop()
        await metrics.stop_loop_watch()
        self._loop_task = None
        self._tasks.clear()
        self._poll_after.clear()
        _logger.info("dispatcher stopped")

    def nudge(self) -> None:
        """Wakes the loop now, and forgets any backoff, so the next tick checks the server."""
        self._backoff_s = 0.0
        self._wakeup.set()

    # --- Recovery ---------------------------------------------------------------

    async def _recover(self) -> None:
        """Applies each handler's restart rule to the jobs that were running at shutdown."""
        async with SessionLocal() as session:
            running = await self._jobs(session, "running")
            await session.commit()
        for job in running:
            handler = handlers.get_handler(job.type)
            if handler is None:
                _logger.warning("job %d has no handler for type %s", job.id, job.type)
                continue
            await self._apply_restart_rule(job, handler)

    async def _apply_restart_rule(self, job: Job, handler: JobHandler) -> None:
        """For a running job that nothing is working on.

        A remote job that has a server job id is left alone: it keeps being polled.
        """
        async with SessionLocal() as session:
            if handler.restart_rule == "never_rerun":
                if _may_rerun(job, handler):
                    await self._requeue_paid(session, job, "interrupted by a restart")
                else:
                    await store.fail_job(session, job.id, INTERRUPTED_MESSAGE)
            elif handler.restart_rule == "start_again" or job.provider_job_id is None:
                await store.requeue(session, job.id, phases.RESTARTED)

    @staticmethod
    async def _requeue_paid(session: AsyncSession, job: Job, reason: str) -> None:
        """Puts a paid job that was cut short back in the queue as its next attempt. It runs
        again from the start, and it is a paid call again.
        """
        phase = phases.queued_again(reason, job.attempt + 1, MAX_AUTOMATIC_RERUNS + 1)
        if await store.requeue(session, job.id, phase, next_attempt=True):
            metrics.incr("auto_reruns")

    # --- The loop ---------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            try:
                wait_s = await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                metrics.note_exception(exc)
                _logger.exception("dispatcher tick failed")
                wait_s = self._interval_s
            await self._sleep(wait_s)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._wakeup.wait(), timeout=seconds)
        except TimeoutError:
            pass
        self._wakeup.clear()

    @staticmethod
    async def _jobs(session: AsyncSession, status: str) -> list[Job]:
        statement = (
            select(Job)
            .where(Job.status == status)
            .order_by(Job.id)
            .execution_options(populate_existing=True)
        )
        return list((await session.execute(statement)).scalars().all())

    async def _tick(self) -> float:
        # Taken before the database is read: a job with no live task at this moment cannot
        # get one later in this tick, so what the database says about it is final.
        live = set(self._tasks)
        tick_began = time.monotonic()

        async with SessionLocal() as session:
            interval = await settings_service.get_int(session, POLL_INTERVAL_KEY)
            gpu_server.set_transfer_limits(
                await settings_service.get_int(session, MAX_PARALLEL_UPLOADS_KEY),
                await settings_service.get_int(session, MAX_PARALLEL_DOWNLOADS_KEY),
            )
            running = await self._jobs(session, "running")
            queued = await self._jobs(session, "queued")
            # By pool: every GPU job and Qwen3.8 call shares the GPU server's slots, every paid
            # call the paid API's, and a local job type has its own.
            limits = await pools.limits(session, handlers.all_handlers())
            # And by model family on the GPU server: a limit of its own, counted in jobs.
            model_limits = await pools.model_limits(session)
            qwen38_keys = await pools.qwen38_model_keys(session)
            # Read once here, so no poll opens a session just to learn them.
            poll_context = handlers.PollContext(
                gpu_url=await settings_service.get_str(session, GPU_URL_KEY),
                transcription_url=await settings_service.get_str(session, TRANSCRIPTION_URL_KEY),
            )
            await session.commit()  # end the read before any network call
        self._interval_s = float(interval)
        live_status.keep_only(job.id for job in (*running, *queued))

        pollable: list[tuple[Job, JobHandler]] = []
        for job in running:
            if job.id in live:
                continue
            handler = handlers.get_handler(job.type)
            if handler is None:
                self._warn_missing_handler(job.type)
                continue
            if job.provider_job_id is None:
                # Running, but nothing is working on it and it never reached the server.
                await self._apply_restart_rule(job, handler)
                continue
            if handler.poll_in_background:
                # A task of its own: this tick does not wait for the poll. A task still alive
                # is skipped above (`live`), so two polls of one job never overlap.
                if self._poll_after.get(job.id, 0.0) <= time.monotonic():
                    self._spawn(job.id, self._poll_in_task(job, handler, poll_context))
                continue
            pollable.append((job, handler))

        now = time.monotonic()
        waiting: list[tuple[Job, JobHandler]] = []
        for job in queued:
            handler = handlers.get_handler(job.type)
            if handler is None:
                self._warn_missing_handler(job.type)
            elif self._retry_after.get(job.id, 0.0) <= now:
                waiting.append((job, handler))

        # The jobs that others wait for (a shot that another shot continues) start first.
        waiting.sort(key=lambda pair: (-store.priority_of(pair[0]), pair[0].id))

        read_done = time.monotonic()
        gpu_blocked = False
        needs_gpu = any(h.provider == "gpu" for _job, h in pollable) or any(
            h.provider == "gpu" for _job, h in waiting
        )
        if needs_gpu:
            gpu_blocked = not await self._server_answers(interval)

        polls_began = time.monotonic()
        slowest_poll = await self._poll_running(
            [(job, h) for job, h in pollable if not (gpu_blocked and h.provider == "gpu")],
            poll_context,
        )
        start_began = time.monotonic()
        started = await self._start_queued(
            waiting, running, limits, model_limits, qwen38_keys, gpu_blocked
        )
        self._record_tick(
            tick_began, read_done, polls_began, start_began, started, len(waiting), slowest_poll
        )

        return self._backoff_s if self._backoff_s > 0 else float(interval)

    @staticmethod
    def _record_tick(
        began: float,
        read_done: float,
        polls_began: float,
        start_began: float,
        started: int,
        waiting: int,
        slowest_poll: tuple[str, float] | None,
    ) -> None:
        """Notes how long the parts of one tick took (`app/core/metrics.py`) and logs one line."""
        end = time.monotonic()
        read_s, health_s = read_done - began, polls_began - read_done
        polls_s, start_s, total_s = start_began - polls_began, end - start_began, end - began
        metrics.record("tick_s", total_s)
        metrics.record("tick_read_s", read_s)
        metrics.record("tick_polls_s", polls_s)
        metrics.record("tick_start_s", start_s)
        metrics.record("tick_started", started)
        slowest = f" (slowest {slowest_poll[0]} {slowest_poll[1]:.1f})" if slowest_poll else ""
        _logger.info(
            "dispatcher tick %.1f s: read %.1f, health %.1f, polls %.1f%s, start %.1f; "
            "started %d of %d waiting",
            total_s,
            read_s,
            health_s,
            polls_s,
            slowest,
            start_s,
            started,
            waiting,
        )

    # --- Step 2: the server ------------------------------------------------------

    async def _server_answers(self, interval: int) -> bool:
        """Checks the GPU server and stores the result for the banner.

        When it does not answer, notes it for the GPU jobs that are waiting on it (their phase is
        not changed: it is still the last thing the server told) and backs off. A busy
        server (no answer to the health check, but another call was answered a moment ago) is not
        waited for: holding every job back would not help a connection that is only full.
        """
        async with SessionLocal() as session:
            health = await gpu_status.record_health(session)
        if health.reachable or health.busy:
            self._backoff_s = 0.0
            live_status.clear_server_problem()
            return True

        cap = max(MAX_BACKOFF_S, float(interval))
        self._backoff_s = float(interval) if self._backoff_s == 0 else min(self._backoff_s * 2, cap)
        # The jobs keep the phase the server last confirmed. That the server does not answer is
        # kept in memory, for the info mark next to their badge, with when it began.
        live_status.note_server_problem(health.error or "The remote server did not answer.")
        _logger.info("Remote server unreachable; checking again in %.0f s", self._backoff_s)
        return False

    # --- Step 3: running jobs ------------------------------------------------------

    async def _poll_running(
        self, pollable: list[tuple[Job, JobHandler]], context: handlers.PollContext
    ) -> tuple[str, float] | None:
        """Polls every running job (at most `MAX_PARALLEL_POLLS` at once), then writes what the
        polls found in one session, and only then starts the `finish` of the jobs that are ready:
        a finishing phase (the job can no longer be cancelled) and the server's last answer
        are saved before `finish` reads the job.

        Returns the job type of the slowest poll and its seconds (for the tick's log line), or
        None when nothing was polled.
        """
        if not pollable:
            return None
        gate = asyncio.Semaphore(MAX_PARALLEL_POLLS)
        timings: dict[str, float] = {}
        ready = await asyncio.gather(
            *(self._poll_one(job, h, context, gate, timings) for job, h in pollable)
        )
        if context.records:
            try:
                async with SessionLocal() as session:
                    await store.record_polls(session, context.records)
            except Exception:
                # Not fatal: the phases are written again by the next tick's polls.
                _logger.exception("dispatcher: could not save what the polls found")
        for (job, handler), is_ready in zip(pollable, ready, strict=True):
            if is_ready:
                self._spawn(job.id, handler.finish(job.id))
        if not timings:
            return None
        slowest = max(timings, key=lambda job_type: timings[job_type])
        return slowest, timings[slowest]

    @staticmethod
    async def _poll_one(
        job: Job,
        handler: JobHandler,
        context: handlers.PollContext,
        gate: asyncio.Semaphore,
        timings: dict[str, float],
    ) -> bool:
        """One poll. Its seconds go to the diagnostics by job type, and into `timings` (the
        longest per type) for the tick's log line.
        """
        async with gate:
            began = time.monotonic()
            try:
                return await handler.poll(job, context)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Not fatal for the job: it is checked again at the next tick.
                metrics.note_exception(exc)
                _logger.exception("job %d: checking the server failed unexpectedly", job.id)
                return False
            finally:
                seconds = time.monotonic() - began
                metrics.record(f"poll_s:{job.type}", seconds)
                timings[job.type] = max(timings.get(job.type, 0.0), seconds)

    async def _poll_in_task(
        self, job: Job, handler: JobHandler, context: handlers.PollContext
    ) -> None:
        """One poll of a job whose handler is slow (`poll_in_background`), in a task of its own.
        An error is not fatal for the job: it is polled again later. When the job is ready,
        `finish` runs here, in the same task.
        """
        began = time.monotonic()
        ready = False
        try:
            ready = await handler.poll(job, context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            metrics.note_exception(exc)
            _logger.exception("job %d: checking the job failed unexpectedly", job.id)
        finally:
            metrics.record(f"poll_s:{job.type}", time.monotonic() - began)
            self._poll_after[job.id] = time.monotonic() + MIN_RETRY_DELAY_S
        if ready:
            await handler.finish(job.id)

    # --- Step 4: queued jobs -------------------------------------------------------

    async def _start_queued(
        self,
        waiting: list[tuple[Job, JobHandler]],
        running: list[Job],
        limits: dict[str, int],
        model_limits: dict[str, int],
        qwen38_keys: frozenset[str],
        gpu_blocked: bool,
    ) -> int:
        """Starts what the pools have room for and returns how many jobs it started. A GPU job
        also needs room under the limit of its model family (0 is no limit of its own).
        """
        started = 0
        # The limits count jobs: every job is one, whatever it is.
        running_with_handlers = [(job, handlers.get_handler(job.type)) for job in running]
        used_by_pool = pools.jobs_in_use(running_with_handlers, qwen38_keys)
        free = {pool: limit - used_by_pool[pool] for pool, limit in limits.items()}
        # A pool that is full lets no later job of that pool start in this tick.
        full_pools: set[str] = set()
        # The same for a model family at its own limit. It holds back only that family's later
        # jobs, and does not mark the GPU pool full, so the other models' jobs still start.
        used_by_model = pools.jobs_by_model(running_with_handlers, qwen38_keys)
        full_models: set[str] = set()
        checked_contract = False
        # What the jobs that must wait should show. Written once after the loop, in one session,
        # instead of one session for every waiting job.
        queued_phases: dict[int, str] = {}

        for job, handler in waiting:
            if handler.provider == "gpu" and gpu_blocked:
                continue  # `_server_answers` already set the phase

            model = pools.model_of(job, handler, qwen38_keys)
            model_limit = model_limits.get(model, 0) if model is not None else 0
            if (
                model is not None
                and model_limit > 0
                and (model in full_models or used_by_model[model] >= model_limit)
            ):
                full_models.add(model)
                model_phase = phases.waiting_for_model_slot(pools.MODEL_LABELS[model])
                if job.phase != model_phase:
                    queued_phases[job.id] = model_phase
                continue

            pool = pools.job_pool(job, handler, qwen38_keys)
            if pool in full_pools or free.get(pool, 0) <= 0:
                full_pools.add(pool)
                waiting_phase = _SLOT_PHASES.get(pool, phases.WAITING_FOR_SLOT)
                if job.phase != waiting_phase:  # the row was read at the start of the tick
                    queued_phases[job.id] = waiting_phase
                continue

            if handler.provider == "gpu" and not checked_contract:
                # Only records what the server says now (the banner and the stored copy of the
                # API that requests are checked against). A changed API never holds a job back.
                checked_contract = True
                async with SessionLocal() as session:
                    await contract_guard.check(session)

            async with SessionLocal() as session:
                claimed = await store.claim(session, job.id)
            if not claimed:
                continue  # cancelled in the meantime
            free[pool] -= 1
            if model is not None:
                used_by_model[model] += 1
            self._retry_after.pop(job.id, None)
            started += 1
            # From creation, so a job put back in the queue shows its whole wait.
            metrics.record(f"queue_wait_s:{pool}", (utcnow() - job.created_at).total_seconds())
            self._spawn(job.id, handler.start(job.id))

        if queued_phases:
            async with SessionLocal() as session:
                await store.set_phases(session, queued_phases, status="queued")
        return started

    # --- Tasks ---------------------------------------------------------------------

    def _spawn(self, job_id: int, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(self._guard(job_id, work), name=f"job-{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda done, job_id=job_id: self._forget(job_id, done))

    def _forget(self, job_id: int, done: asyncio.Task[None]) -> None:
        if self._tasks.get(job_id) is done:
            del self._tasks[job_id]

    async def _guard(self, job_id: int, work: Coroutine[Any, Any, None]) -> None:
        try:
            await work
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            metrics.note_exception(exc)
            _logger.exception("job %d: unexpected error", job_id)
            await self._fail_unexpected(job_id, exc)
        await self._after_task(job_id)

    async def _fail_unexpected(self, job_id: int, exc: Exception) -> None:
        """Ends a job whose task raised. A paid job that a passing database error cut short is
        queued again instead (`_may_rerun`); `requeue` only changes a job that is still running.
        """
        message = f"Unexpected error: {type(exc).__name__}: {exc}"
        try:
            async with SessionLocal() as session:
                if _is_transient_db_error(exc):
                    job = await store.get_job(session, job_id)
                    await session.commit()
                    handler = handlers.get_handler(job.type) if job is not None else None
                    if job is not None and handler is not None and _may_rerun(job, handler):
                        await self._requeue_paid(session, job, "database busy")
                        return
                await store.fail_job(session, job_id, message[:UNEXPECTED_ERROR_MAX_CHARS])
        except Exception:
            _logger.exception("job %d: could not record the failure", job_id)

    async def _after_task(self, job_id: int) -> None:
        """Decides what the loop should do now that a job's task has ended.

        - Queued again: the handler asked to wait. Leave it alone for a while. Waking the
          loop here would start it again at once, and loop at full speed against a server
          that is busy or down.
        - Still running: nothing to do until the next poll.
        - Finished (any way): a slot is free, so wake the loop.

        First, the last phase the task noted is written (`phase_writer.settle`), so it can never
        land later, on a job that was queued again and started again by then.
        """
        await phase_writer.settle(job_id)
        try:
            async with SessionLocal() as session:
                job = await store.get_job(session, job_id)
                await session.commit()
        except Exception:
            _logger.exception("job %d: could not read the job after its task", job_id)
            return

        if job is None or job.status == "running":
            return
        if job.status == "queued":
            self._retry_after[job_id] = time.monotonic() + max(self._interval_s, MIN_RETRY_DELAY_S)
            return
        self._retry_after.pop(job_id, None)
        self._poll_after.pop(job_id, None)
        self.nudge()

    def _warn_missing_handler(self, job_type: str) -> None:
        if job_type not in self._warned_types:
            self._warned_types.add(job_type)
            _logger.warning("no handler is registered for job type %s; its jobs wait", job_type)


_dispatcher = _Dispatcher()


async def start() -> None:
    """Registers the handlers, recovers jobs from before the restart, starts the loop."""
    await _dispatcher.start()


async def stop() -> None:
    await _dispatcher.stop()


def nudge() -> None:
    """Wakes the loop now. Call it after anything that could let a waiting job proceed."""
    _dispatcher.nudge()
