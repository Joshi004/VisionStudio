"""The pools the dispatcher counts running jobs in.

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

Every job counts as one in its pool (`jobs_in_use`), whatever it is: the remote server decides
by itself how many of its GPUs a job uses, and it queues what it cannot start yet. The limit is
how many jobs the app keeps at the remote server (or at the paid API) at once.

On top of the remote server's shared limit, each model family on it has a limit of its own, also
counted in jobs (`MODEL_LABELS`: MiniMax H3, LTX, Qwen-Image, Breeze TTS, Parakeet, music and
Qwen3.8). A family at its limit holds back only its own jobs: they do not mark the pool full,
so the jobs of the other families still start. A limit of 0 means the family has no limit of its
own. Without them, hundreds of clips fill the server's queue, and a short job made later (a
transcription a finished clip waits for) waits behind all of them.

The settings are read at every tick, so a change on the Settings page applies at once. Running
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
from app.jobs.handlers import (
    MODEL_H3,
    MODEL_IMAGE,
    MODEL_LTX,
    MODEL_MUSIC,
    MODEL_QWEN38,
    MODEL_TRANSCRIPTION,
    MODEL_TTS,
)
from app.providers import qwen38
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
    GPU_POOL: "Remote server",
    PAID_API_POOL: "Paid inference API",
}

_SETTING_OF_POOL: Final[dict[str, str]] = {
    GPU_POOL: MAX_PARALLEL_GPU_KEY,
    PAID_API_POOL: MAX_PARALLEL_PAID_API_KEY,
}

# What the page calls each model family of the GPU server, in the order the page lists them.
MODEL_LABELS: Final[dict[str, str]] = {
    MODEL_H3: "MiniMax H3 video",
    MODEL_LTX: "LTX video",
    MODEL_IMAGE: "Qwen-Image",
    MODEL_TTS: "Breeze TTS",
    MODEL_TRANSCRIPTION: "Parakeet transcription",
    MODEL_MUSIC: "Music models",
    MODEL_QWEN38: "Qwen3.8 text",
}

# The setting that limits each family. 0 means no limit of its own.
_SETTING_OF_MODEL: Final[dict[str, str]] = {
    MODEL_H3: "max_parallel_h3_jobs",
    MODEL_LTX: "max_parallel_ltx_jobs",
    MODEL_IMAGE: "max_parallel_image_jobs",
    MODEL_TTS: "max_parallel_tts_jobs",
    MODEL_TRANSCRIPTION: "max_parallel_transcription_jobs",
    MODEL_MUSIC: "max_parallel_music_jobs",
    MODEL_QWEN38: "max_parallel_qwen38_calls",
}


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


def model_of(job: Job, handler: JobHandler, qwen38_keys: frozenset[str]) -> str | None:
    """The model family of the GPU server one job runs on, or None when it does not run there
    (a paid API call, a local job) or its handler names no family.
    """
    if on_qwen38(job, handler, qwen38_keys):
        return MODEL_QWEN38
    if handler.provider != "gpu":
        return None
    return handler.gpu_model_of(job)


def jobs_by_model(
    running: Iterable[tuple[Job, JobHandler | None]], qwen38_keys: frozenset[str]
) -> Counter[str]:
    """How many of the running jobs each model family has. It counts jobs, not slots: an H3 clip
    is one, and so is each Qwen3.8 call.
    """
    used: Counter[str] = Counter()
    for job, handler in running:
        model = None if handler is None else model_of(job, handler, qwen38_keys)
        if model is not None:
            used[model] += 1
    return used


def jobs_in_use(
    running: Iterable[tuple[Job, JobHandler | None]], qwen38_keys: frozenset[str]
) -> Counter[str]:
    """How many of the running jobs each pool has: one for every job. A Qwen3.8 call counts in
    the remote server's pool, and a job with no handler counts under its job type.
    """
    used: Counter[str] = Counter()
    for job, handler in running:
        pool = job.type if handler is None else job_pool(job, handler, qwen38_keys)
        used[pool] += 1
    return used


async def shared_limits(session: AsyncSession) -> dict[str, int]:
    """How many jobs may be running in each of the two shared pools right now."""
    return {
        pool: await settings_service.get_int(session, key) for pool, key in _SETTING_OF_POOL.items()
    }


async def model_limits(session: AsyncSession) -> dict[str, int]:
    """How many jobs of each model family may be running right now. 0 means no limit of its own."""
    return {
        model: await settings_service.get_int(session, key)
        for model, key in _SETTING_OF_MODEL.items()
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
