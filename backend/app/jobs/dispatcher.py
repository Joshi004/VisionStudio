"""The dispatcher: the one loop that moves background jobs forward
(ANALYSIS.md Section 3.3).

It starts with the app and does the scheduling only. It never does slow work itself:
uploads, downloads and the like run as separate tasks it starts. All job state lives in
the `job` table, so after a restart the loop simply continues from the database. Only the
task handles are in memory.

Each tick, which happens every poll interval (a setting) or sooner when something nudges
the loop:

1. Read the poll interval, the running and the queued jobs, and each job type's limit.
2. If any GPU job needs the server, check its health and store the result for the banner.
   If it does not answer, GPU jobs wait, and the loop backs off (the wait doubles up to
   120 s, or the poll interval if that is longer).
3. Ask each running remote job's handler to `poll`. A handler that says "ready" gets its
   `finish` started as a task.
4. Start queued jobs while their type (or concurrency group) has free slots. Before the
   first GPU job is started, the recorded GPU API is checked, and nothing starts unless it
   still matches the approved version (ANALYSIS.md Section 6.5).
5. Wait.

One uvicorn process runs one loop (Section 3.2). Run a second process and each would run
its own loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Coroutine
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job
from app.db.session import SessionLocal
from app.jobs import handlers, phases, register_handlers, store
from app.jobs.handlers import JobHandler
from app.providers import contract_guard
from app.services import gpu_status

POLL_INTERVAL_KEY: Final = "poll_interval_seconds"
MAX_BACKOFF_S: Final = 120.0
# How long to wait after a tick that failed unexpectedly.
FALLBACK_WAIT_S: Final = 15.0
# A job that a handler put back in the queue is left alone for at least this long.
MIN_RETRY_DELAY_S: Final = 5.0
INTERRUPTED_MESSAGE: Final = (
    "Interrupted by a restart. Paid calls never re-run by themselves; start it again."
)
UNEXPECTED_ERROR_MAX_CHARS: Final = 500

_logger = logging.getLogger(__name__)


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
        self._loop_task = asyncio.create_task(self._run(), name="dispatcher")
        _logger.info("dispatcher started")

    async def stop(self) -> None:
        tasks = [task for task in (self._loop_task, *self._tasks.values()) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._loop_task = None
        self._tasks.clear()
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
                await store.fail_job(session, job.id, INTERRUPTED_MESSAGE)
            elif handler.restart_rule == "start_again" or job.provider_job_id is None:
                await store.requeue(session, job.id, phases.RESTARTED)

    # --- The loop ---------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            try:
                wait_s = await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
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

        async with SessionLocal() as session:
            interval = await settings_service.get_int(session, POLL_INTERVAL_KEY)
            running = await self._jobs(session, "running")
            queued = await self._jobs(session, "queued")
            # By pool: job types of one concurrency group share their slots.
            limits = {
                handlers.slot_key(handler.job_type): await handler.concurrency_limit(session)
                for handler in handlers.all_handlers()
            }
            await session.commit()  # end the read before any network call
        self._interval_s = float(interval)

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
            pollable.append((job, handler))

        now = time.monotonic()
        waiting: list[tuple[Job, JobHandler]] = []
        for job in queued:
            handler = handlers.get_handler(job.type)
            if handler is None:
                self._warn_missing_handler(job.type)
            elif self._retry_after.get(job.id, 0.0) <= now:
                waiting.append((job, handler))

        gpu_blocked = False
        needs_gpu = any(h.provider == "gpu" for _job, h in pollable) or any(
            h.provider == "gpu" for _job, h in waiting
        )
        if needs_gpu:
            gpu_blocked = not await self._server_answers(interval, pollable, waiting)

        await self._poll_running(
            [(job, h) for job, h in pollable if not (gpu_blocked and h.provider == "gpu")]
        )
        await self._start_queued(waiting, running, limits, gpu_blocked)

        return self._backoff_s if self._backoff_s > 0 else float(interval)

    # --- Step 2: the server ------------------------------------------------------

    async def _server_answers(
        self,
        interval: int,
        pollable: list[tuple[Job, JobHandler]],
        waiting: list[tuple[Job, JobHandler]],
    ) -> bool:
        """Checks the GPU server and stores the result for the banner.

        When it does not answer, marks the GPU jobs that are waiting on it and backs off.
        """
        async with SessionLocal() as session:
            health = await gpu_status.record_health(session)
        if health.reachable:
            self._backoff_s = 0.0
            return True

        cap = max(MAX_BACKOFF_S, float(interval))
        self._backoff_s = float(interval) if self._backoff_s == 0 else min(self._backoff_s * 2, cap)
        async with SessionLocal() as session:
            for job, handler in pollable:
                if handler.provider == "gpu":
                    await store.record_poll(session, job.id, phases.SERVER_UNREACHABLE_CHECKING)
            for job, handler in waiting:
                if handler.provider == "gpu":
                    await store.set_phase(
                        session, job.id, phases.WAITING_SERVER_UNREACHABLE, status="queued"
                    )
        _logger.info("GPU server unreachable; checking again in %.0f s", self._backoff_s)
        return False

    # --- Step 3: running jobs ------------------------------------------------------

    async def _poll_running(self, pollable: list[tuple[Job, JobHandler]]) -> None:
        if not pollable:
            return
        ready = await asyncio.gather(*(self._poll_one(job, h) for job, h in pollable))
        for (job, handler), is_ready in zip(pollable, ready, strict=True):
            if is_ready:
                self._spawn(job.id, handler.finish(job.id))

    @staticmethod
    async def _poll_one(job: Job, handler: JobHandler) -> bool:
        try:
            return await handler.poll(job.id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Not fatal for the job: it is checked again at the next tick.
            _logger.exception("job %d: checking the server failed unexpectedly", job.id)
            return False

    # --- Step 4: queued jobs -------------------------------------------------------

    async def _start_queued(
        self,
        waiting: list[tuple[Job, JobHandler]],
        running: list[Job],
        limits: dict[str, int],
        gpu_blocked: bool,
    ) -> None:
        running_by_pool = Counter(handlers.slot_key(job.type) for job in running)
        free = {pool: limit - running_by_pool[pool] for pool, limit in limits.items()}
        contract: contract_guard.CheckResult | None = None

        for job, handler in waiting:
            if handler.provider == "gpu" and gpu_blocked:
                continue  # `_server_answers` already set the phase

            pool = handlers.slot_key(job.type)
            if free.get(pool, 0) <= 0:
                await self._set_queued_phase(job.id, phases.WAITING_FOR_SLOT)
                continue

            if handler.provider == "gpu":
                if contract is None:
                    async with SessionLocal() as session:
                        contract = await contract_guard.check(session)
                if not contract.is_ok:
                    await self._set_queued_phase(job.id, _paused_phase(contract.status))
                    continue

            async with SessionLocal() as session:
                claimed = await store.claim(session, job.id)
            if not claimed:
                continue  # cancelled in the meantime
            free[pool] -= 1
            self._retry_after.pop(job.id, None)
            self._spawn(job.id, handler.start(job.id))

    @staticmethod
    async def _set_queued_phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="queued")

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
            _logger.exception("job %d: unexpected error", job_id)
            await self._fail_unexpected(job_id, exc)
        await self._after_task(job_id)

    @staticmethod
    async def _fail_unexpected(job_id: int, exc: Exception) -> None:
        message = f"Unexpected error: {type(exc).__name__}: {exc}"
        try:
            async with SessionLocal() as session:
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
        """
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
        self.nudge()

    def _warn_missing_handler(self, job_type: str) -> None:
        if job_type not in self._warned_types:
            self._warned_types.add(job_type)
            _logger.warning("no handler is registered for job type %s; its jobs wait", job_type)


def _paused_phase(status: str) -> str:
    if status == "changed":
        return phases.PAUSED_API_CHANGED
    if status == "not_approved":
        return phases.PAUSED_API_NOT_APPROVED
    return phases.WAITING_API_UNCHECKED


_dispatcher = _Dispatcher()


async def start() -> None:
    """Registers the handlers, recovers jobs from before the restart, starts the loop."""
    await _dispatcher.start()


async def stop() -> None:
    await _dispatcher.stop()


def nudge() -> None:
    """Wakes the loop now. Call it after anything that could let a waiting job proceed."""
    _dispatcher.nudge()
