"""The pools of running slots the dispatcher counts jobs in.

Only two things limit how much work can run at once, so only two numbers are enforced, and every
kind of job shares them:

- **`gpu`**: the in-house GPU server (video, images, reference pictures, speech, and the
  language-model calls answered by Qwen3.8). Its limit is the `max_parallel_gpu_jobs`
  setting.
- **`paid_api`**: the paid inference API (the language-model calls of every role set to
  Bitdeer). Its limit is the `max_parallel_paid_api_calls` setting.

A job type has no limit of its own. Which pool a job counts in comes from its handler's
`provider`, so a new job type joins the right pool without anything else being written. An
`llm` job is the exception: it counts where its calls go (`on_qwen38`).

A job whose provider is neither (a `local` one, such as a render on this machine) is its own
pool, counted under its job type, and its handler says how many may run at once. No job type
is local today.

A job takes one slot of its pool, except a MiniMax H3 clip, which holds 4 or 8 GPUs on one node
as the server decides from the request's size. It takes the number of GPUs the server reported
(`server_gpus`), and `H3_MIN_GPUS` until the server has said (`slot_cost`). The Qwen3.8 calls
answer from one GPU however many run at once, so together they hold `QWEN38_GPUS` slots
(`slots_in_use`). The limit counts slots, not jobs.

Both settings are read at every tick, so a change on the Settings page applies at once. Running
jobs are never stopped by a lower number.

This module does not import the handler registry: the dispatcher and the capacity endpoint pass
the handlers in.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import TYPE_CHECKING, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.providers import qwen38, video_generator
from app.services import llm_target

if TYPE_CHECKING:
    from app.db.models import Job
    from app.jobs.handlers import JobHandler

GPU_POOL: Final = "gpu"
PAID_API_POOL: Final = "paid_api"

MAX_PARALLEL_GPU_KEY: Final = "max_parallel_gpu_jobs"
MAX_PARALLEL_PAID_API_KEY: Final = "max_parallel_paid_api_calls"

# What the page calls each shared pool.
POOL_LABELS: Final[dict[str, str]] = {
    GPU_POOL: "GPU server",
    PAID_API_POOL: "Paid inference API",
}

_SETTING_OF_POOL: Final[dict[str, str]] = {
    GPU_POOL: MAX_PARALLEL_GPU_KEY,
    PAID_API_POOL: MAX_PARALLEL_PAID_API_KEY,
}


# A MiniMax H3 job reserves 4 or 8 H100s on one node, chosen by the server from the request's
# size (GPU API 0.15.0). It says which only when it accepts the job, so until it does a clip is
# counted at the smaller of the two.
H3_MIN_GPUS: Final = 4
# The Qwen3.8 text model answers every call at once from the same GPU.
QWEN38_GPUS: Final = 1


def _server_value(job: Job, field: str) -> object:
    """A number the server said about a job: from its last status answer (`output.remote`), else
    from its submit answer (`input.submit_answer`). None until the server has said.
    """
    for container, key in ((job.output, "remote"), (job.input, "submit_answer")):
        answer = container.get(key) if isinstance(container, dict) else None
        value = answer.get(field) if isinstance(answer, dict) else None
        if value is not None:
            return value
    return None


def server_gpus(job: Job) -> int | None:
    """How many GPUs the server said it gave a job. None until the server has said, and for
    every backend that does not size its jobs.
    """
    gpus = _server_value(job, "gpus")
    return gpus if isinstance(gpus, int) and not isinstance(gpus, bool) and gpus >= 1 else None


def server_estimate_seconds(job: Job) -> float | None:
    """About how long the server said a job will run once it starts (the queue wait is not
    included). None until the server has said, and for every backend that does not size its jobs.
    """
    seconds = _server_value(job, "estimated_run_seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int | float):
        return None
    return float(seconds) if seconds >= 0 else None


def slot_cost(job: Job) -> int:
    """How many slots of its pool a job takes: the GPUs the server gave it when it said so, else
    `H3_MIN_GPUS` for a MiniMax H3 clip (its endpoint is recorded on the job's input), else 1.
    """
    recorded = job.input if isinstance(job.input, dict) else {}
    if not video_generator.is_h3_endpoint(recorded.get("endpoint")):
        return 1
    return server_gpus(job) or H3_MIN_GPUS


def fits(free: int, limit: int, cost: int) -> bool:
    """Whether a job that takes `cost` slots may start when `free` of the pool's `limit` slots
    are free. A job that costs more than the whole pool (an H3 clip with a limit of 1) would
    never start, so it may start when nothing else is running in the pool. A limit of 0 still
    stops everything.
    """
    return free >= cost or (limit > 0 and free == limit)


def pool_of(handler: JobHandler) -> str:
    """The pool a handler's jobs are counted in when nothing about the job itself changes it
    (see `job_pool`). A local handler is its own pool.
    """
    if handler.provider == "gpu":
        return GPU_POOL
    if handler.provider in ("llm", "image"):
        return PAID_API_POOL
    return handler.job_type


async def qwen38_model_keys(session: AsyncSession) -> frozenset[str]:
    """The model settings of the language-model roles whose provider is Qwen3.8 now."""
    keys: set[str] = set()
    for model_key in llm_target.MODEL_KEYS:
        if await llm_target.provider_of(session, model_key) == settings_service.PROVIDER_QWEN38:
            keys.add(model_key)
    return frozenset(keys)


def on_qwen38(job: Job, handler: JobHandler, qwen38_keys: frozenset[str]) -> bool:
    """Whether a language-model job's calls go to Qwen3.8 on the GPU server. A running job that
    has recorded its `endpoint` went where it says, whatever the setting is now. Any other job
    goes where its role's provider setting says (`qwen38_keys`).
    """
    if handler.provider != "llm":
        return False
    recorded = job.input if isinstance(job.input, dict) else {}
    endpoint = recorded.get("endpoint")
    if job.status == "running" and isinstance(endpoint, str):
        return endpoint == qwen38.GENERATE_PATH
    return handler.model_key in qwen38_keys


def job_pool(job: Job, handler: JobHandler, qwen38_keys: frozenset[str]) -> str:
    """The pool one job is counted in: the GPU server's for a Qwen3.8 call, else its handler's."""
    return GPU_POOL if on_qwen38(job, handler, qwen38_keys) else pool_of(handler)


def slots_in_use(
    running: Iterable[tuple[Job, JobHandler | None]], qwen38_keys: frozenset[str]
) -> Counter[str]:
    """The slots the running jobs hold, by pool. Every running Qwen3.8 call together holds
    `QWEN38_GPUS` of the GPU server's. A job with no handler counts under its job type.
    """
    used: Counter[str] = Counter()
    qwen38_running = False
    for job, handler in running:
        if handler is None:
            used[job.type] += slot_cost(job)
        elif on_qwen38(job, handler, qwen38_keys):
            qwen38_running = True
        else:
            used[pool_of(handler)] += slot_cost(job)
    if qwen38_running:
        used[GPU_POOL] += QWEN38_GPUS
    return used


async def shared_limits(session: AsyncSession) -> dict[str, int]:
    """How many jobs may be running in each of the two shared pools right now."""
    return {
        pool: await settings_service.get_int(session, key) for pool, key in _SETTING_OF_POOL.items()
    }


async def limits(session: AsyncSession, all_handlers: Iterable[JobHandler]) -> dict[str, int]:
    """How many jobs may be running in each pool right now, by pool name: the two shared pools
    and the pool of each local job type.
    """
    result = await shared_limits(session)
    for handler in all_handlers:
        pool = pool_of(handler)
        if pool not in result:
            result[pool] = await handler.concurrency_limit(session)
    return result
