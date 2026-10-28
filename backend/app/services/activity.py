"""What is going on in a project, cheaply: a revision that changes whenever something in the
project changes, and how many jobs are queued, running or paused.

Two small indexed queries on the `job` table and two in-memory counters. No stage `state()` is
computed, so a client can ask every few seconds and fetch the heavy answers only when the
revision is new.

The revision is a hash of:

- the boot id of this process (`db/activity.py`): a restart changes it;
- the write counters: of everything that belongs to no project, and of the project;
- the project's jobs: how many there are, the newest id and finish time, and the id, status
  and phase of each queued or running job. The phase is in it on purpose, so a progress label
  that changes is seen. `last_checked_at` is not: it is only a heartbeat.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import activity as writes
from app.db.models import Job
from app.jobs import phases, store

_REVISION_CHARS: Final = 16


@dataclass(frozen=True)
class Activity:
    revision: str
    # Jobs waiting to start, not counting the paused ones or a run of the story pipeline.
    queued: int
    running: int
    # Queued jobs that wait because the GPU API changed or is not approved (`paused:` phases).
    paused: int
    # A run of the whole story pipeline is waiting or running (it may be paused at a step).
    pipeline_active: bool


async def snapshot(session: AsyncSession, project_id: int) -> Activity:
    """The project's activity now. Reads two indexed queries and nothing else."""
    totals = (
        await session.execute(
            select(func.count(Job.id), func.max(Job.id), func.max(Job.finished_at)).where(
                Job.project_id == project_id
            )
        )
    ).one()
    active = (
        await session.execute(
            select(Job.id, Job.type, Job.status, Job.phase)
            .where(Job.project_id == project_id, Job.status.in_(store.ACTIVE_STATUSES))
            .order_by(Job.id)
        )
    ).all()

    queued = running = paused = 0
    pipeline_active = False
    for _job_id, job_type, status, phase in active:
        if job_type == store.PIPELINE_RUN_TYPE:
            pipeline_active = True
        elif status == "running":
            running += 1
        elif phase is not None and phase.startswith(phases.PAUSED_PREFIX):
            paused += 1
        else:
            queued += 1

    boot, global_writes, project_writes = writes.counters(project_id)
    jobs = ";".join(f"{job_id}:{status}:{phase}" for job_id, _type, status, phase in active)
    fingerprint = (
        f"{boot}|{global_writes}|{project_writes}|{totals[0]}|{totals[1]}|{totals[2]}|{jobs}"
    )
    digest = hashlib.sha1(fingerprint.encode(), usedforsecurity=False).hexdigest()
    return Activity(
        revision=digest[:_REVISION_CHARS],
        queued=queued,
        running=running,
        paused=paused,
        pipeline_active=pipeline_active,
    )
