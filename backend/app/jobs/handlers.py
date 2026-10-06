"""The interface every job type implements, and the registry the dispatcher reads
(ANALYSIS.md Section 3.3 and 6.4).

The dispatcher loop knows nothing about any one job type. Phases 6, 9 and 10 add a handler
for `plan_scenes`, `generate_clip` and `render_final` by writing a `JobHandler` subclass
and registering it in `app/jobs/__init__.py`; the loop is not touched.

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
- `never_rerun`: a paid LLM job. It is failed, because a paid call never repeats by itself
  (ANALYSIS.md Section 6.2, rule 1).

`start`, `poll` and `finish` open their own database session (`SessionLocal()`), keep
transactions short, and never hold one across a network call. An unexpected exception
from `start` or `finish` is logged and fails the job; the dispatcher does that.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Literal

from sqlalchemy.ext.asyncio import AsyncSession

RestartRule = Literal["resume", "start_again", "never_rerun"]
Provider = Literal["gpu", "llm", "local"]


class JobHandler(ABC):
    job_type: ClassVar[str]
    provider: ClassVar[Provider]
    restart_rule: ClassVar[RestartRule]

    @abstractmethod
    async def concurrency_limit(self, session: AsyncSession) -> int:
        """How many jobs of this type may be running at once. Read at every tick, so a
        change in Settings applies at once.
        """

    @abstractmethod
    async def start(self, job_id: int) -> None:
        """Runs in its own task after the dispatcher moved the job to `running`."""

    async def poll(self, job_id: int) -> bool:
        """Remote handlers only: checks the server. True means the result is ready and
        `finish` should run. Called once per tick, for jobs that have a provider job id.
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
