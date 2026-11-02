"""The interface every job type implements, and the registry the dispatcher reads
(ANALYSIS.md Section 3.3 and 6.4).

The dispatcher loop knows nothing about any one job type. A new job type is added by writing
a `JobHandler` subclass and registering it in `app/jobs/__init__.py`; the loop is not touched.

Two kinds of handler share the interface:

- **Remote** handlers (the job runs on the GPU server): `start` uploads and submits, then
  ends after saving the server's job id. The dispatcher then calls `poll` every tick, and
  when it returns True, starts `finish` as a task to download and store the result.
- **Local and LLM** handlers do all their work in `start` and leave `poll` and `finish`
  alone.

Each handler declares its `restart_rule`, applied to jobs that were `running` when the
backend stopped (ANALYSIS.md Section 3.3, "On backend start"):

- `resume`: a remote job. With a provider job id it keeps being polled. Without one the
  submit never completed, so it is queued again.
- `start_again`: a local job. It is queued again.
- `never_rerun`: a paid LLM job. It is not resumed: a paid call is not continued from where it
  stopped (ANALYSIS.md Section 6.2, rule 1). The dispatcher queues it again from the start, at
  most `MAX_AUTOMATIC_RERUNS` times (the handler can opt out with `rerun_automatically`), and
  after that it is failed. The same applies when a passing database error (a pool timeout,
  "database is locked") ended its task.

`start` and `finish` open their own database session (`SessionLocal()`), keep transactions
short, and never hold one across a network call. `poll` is given the job and a `PollContext`
instead, so a tick with hundreds of running jobs uses a handful of sessions. An unexpected exception
from `start` or `finish` is logged and fails the job; the dispatcher does that.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs import live_status

if TYPE_CHECKING:
    from app.db.models import Job

RestartRule = Literal["resume", "start_again", "never_rerun"]
Provider = Literal["gpu", "llm", "image", "local"]

# How many times a `never_rerun` job is queued again by itself (after a restart or a passing
# database error) before it is failed. With the first run, a job has this many plus one attempts.
MAX_AUTOMATIC_RERUNS: Final = 2

# The model families on the GPU server. Each has its own limit on how many of its jobs run at
# once (`jobs/pools.py`), on top of the limit all GPU jobs share. They live here, not in
# `pools.py`, so a handler can name its family without importing the pools.
MODEL_H3: Final = "h3"
MODEL_LTX: Final = "ltx"
MODEL_IMAGE: Final = "qwen_image"
MODEL_TTS: Final = "breeze_tts"
MODEL_TRANSCRIPTION: Final = "parakeet"
MODEL_MUSIC: Final = "music"
MODEL_QWEN38: Final = "qwen38"


@dataclass(frozen=True)
class PollRecord:
    """What one poll found: the phase to show and, when it changed, the job's new output."""

    job_id: int
    phase: str
    output: dict[str, Any] | None = None


@dataclass
class PollContext:
    """What a tick gives every `poll`, so a poll opens no database session of its own.

    The URLs are read once per tick. `record` only collects: the dispatcher writes every record of
    the tick in one session, after all the polls have answered, and before any `finish` starts.
    """

    gpu_url: str
    transcription_url: str
    records: list[PollRecord] = field(default_factory=list)

    def record(self, job_id: int, phase: str, output: dict[str, Any] | None = None) -> None:
        # A record is always what the server answered, so no problem reaching it is left.
        live_status.clear_problem(job_id)
        self.records.append(PollRecord(job_id, phase, output))


class JobHandler(ABC):
    job_type: ClassVar[str]
    provider: ClassVar[Provider]
    restart_rule: ClassVar[RestartRule]
    # An `llm` handler only: the model setting of its role (`services/llm_target.py`). Its
    # provider setting says, before a job starts, whether the job's calls go to the paid API or
    # to Qwen3.8 on the GPU server, and so which pool the job waits in.
    model_key: ClassVar[str | None] = None
    # A slow local poll (the story pipeline run) runs in a task of its own, so the tick does not
    # wait for it before starting queued jobs.
    poll_in_background: ClassVar[bool] = False
    # A `never_rerun` job that a restart or a passing database error cut short is queued again
    # by itself, up to `MAX_AUTOMATIC_RERUNS` times. False for a job that would repeat something
    # already saved if it ran again from the start.
    rerun_automatically: ClassVar[bool] = True
    # A `gpu` handler only: the model family its jobs run on (`MODEL_*` above). Each family has
    # its own limit on top of the GPU server's. None means the jobs have no family limit.
    gpu_model: ClassVar[str | None] = None

    def gpu_model_of(self, job: Job) -> str | None:
        """The model family one job runs on. A handler whose jobs can run on different models
        (video: MiniMax H3 or LTX) overrides this and looks at the job.
        """
        return self.gpu_model

    async def concurrency_limit(self, session: AsyncSession) -> int:
        """How many jobs of this type may be running at once. Only a `local` handler is asked:
        a job that calls the GPU server or the paid inference API has no limit of its own, it
        counts in the shared pool of its provider (`jobs/pools.py`). Read at every tick, so a
        change in Settings applies at once.
        """
        return 1

    @abstractmethod
    async def start(self, job_id: int) -> None:
        """Runs in its own task after the dispatcher moved the job to `running`."""

    async def poll(self, job: Job, ctx: PollContext) -> bool:
        """Remote handlers only: checks the server. True means the result is ready and
        `finish` should run. Called once per tick, for jobs that have a provider job id.

        `job` is the row the dispatcher read at the start of the tick: do not open a session to
        read it again. Say what was found with `ctx.record` (written later, in one session).
        A rare change of state (a failure, a requeue) may still use a session of its own.
        """
        return False

    async def finish(self, job_id: int) -> None:
        """Remote handlers only: downloads and stores the result. Runs in its own task."""
        return None


_registry: dict[str, JobHandler] = {}


def register(handler: JobHandler) -> None:
    _registry[handler.job_type] = handler


def get_handler(job_type: str) -> JobHandler | None:
    return _registry.get(job_type)


def all_handlers() -> list[JobHandler]:
    return list(_registry.values())
