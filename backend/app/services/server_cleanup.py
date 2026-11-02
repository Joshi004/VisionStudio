"""Cleaning up the GPU server when something is deleted (the delete dialogs' optional checkbox).

Every remote job is purged on the server as soon as it finishes (`DELETE /v1/jobs/{id}/purge`),
so most of the time nothing is left there. Some jobs are not purged: the purge call failed
(`job.output.purge` holds an error), a lip-sync clip was kept on purpose for a re-sync, or the
job was cancelled. This module finds those jobs and purges them when the user ticked "also delete
what is left on the GPU server".

Two steps, because the rows are gone after the delete:

1. `make_plan` runs *before* the delete. It reads the server's job ids from the job rows and the
   server's address from the settings.
2. `purge` runs *after* the commit, in a background task, so a slow or offline server never
   delays or fails the delete. It is best effort: it only logs what happened.

Only jobs of the GPU server (`provider = 'gpu'`) that are not queued or running are looked at.
Seedream pictures and the language model have nothing to purge.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job
from app.jobs import store
from app.providers import gpu_server
from app.providers.gpu_server import GpuCallError

_logger = logging.getLogger(__name__)

GPU_URL_KEY: Final = "gpu_api_base_url"

# How many job ids go into one query, so a large project stays under SQLite's variable limit.
_QUERY_BATCH: Final = 500


@dataclass(frozen=True)
class PurgePlan:
    """What to purge and where. Made before the delete, used after it."""

    base_url: str
    server_job_ids: list[str]


def _batches(values: list[int]) -> Iterator[list[int]]:
    for start in range(0, len(values), _QUERY_BATCH):
        yield values[start : start + _QUERY_BATCH]


def _already_purged(output: Any) -> bool:
    """Whether the job's own purge succeeded. A speech job keeps one answer per piece."""
    purge = output.get("purge") if isinstance(output, dict) else None
    answers = purge if isinstance(purge, list) else [purge]
    return len(answers) > 0 and all(
        isinstance(answer, dict) and isinstance(answer.get("removed_asset_ids"), list)
        for answer in answers
    )


def _server_ids_of(provider_job_id: str | None, job_input: Any) -> list[str]:
    """The server's job ids of one job: its current one, and for a speech job the finished
    pieces (`input.done`).
    """
    ids: list[str] = []
    if provider_job_id:
        ids.append(provider_job_id)
    done = job_input.get("done") if isinstance(job_input, dict) else None
    if isinstance(done, list):
        ids.extend(item for item in done if isinstance(item, str) and item)
    return ids


async def server_job_ids(session: AsyncSession, job_ids: Iterable[int]) -> list[str]:
    """The server job ids worth purging among these jobs (no repeats, in job order).

    A job is skipped when it is not a GPU job, is still queued or running, never reached the
    server, or its own purge already worked.
    """
    wanted = sorted(set(job_ids))
    found: list[str] = []
    for batch in _batches(wanted):
        rows = await session.execute(
            select(Job.provider_job_id, Job.input, Job.output)
            .where(
                Job.id.in_(batch),
                Job.provider == "gpu",
                Job.status.not_in(store.ACTIVE_STATUSES),
            )
            .order_by(Job.id)
        )
        for provider_job_id, job_input, output in rows.all():
            if not _already_purged(output):
                found.extend(_server_ids_of(provider_job_id, job_input))
    return list(dict.fromkeys(found))


async def make_plan(session: AsyncSession, job_ids: Iterable[int]) -> PurgePlan:
    """Reads what a purge needs. Call it before the rows are deleted."""
    return PurgePlan(
        base_url=await settings_service.get_str(session, GPU_URL_KEY),
        server_job_ids=await server_job_ids(session, job_ids),
    )


def merge(*plans: PurgePlan | None) -> PurgePlan | None:
    """One plan from several (a project and the library items deleted with it). None when there
    is nothing to merge.
    """
    given = [plan for plan in plans if plan is not None]
    if not given:
        return None
    ids = [server_id for plan in given for server_id in plan.server_job_ids]
    return PurgePlan(base_url=given[0].base_url, server_job_ids=list(dict.fromkeys(ids)))


async def purge(plan: PurgePlan) -> None:
    """Purges each job on the server, one after the other. Never raises for a server problem.

    A job the server does not know counts as already gone. When the server does not answer, the
    rest is not tried: it would only wait for the same timeout again.
    """
    removed = 0
    gone = 0
    failed = 0
    for position, server_id in enumerate(plan.server_job_ids):
        try:
            await gpu_server.purge_job(plan.base_url, server_id)
            removed += 1
        except GpuCallError as exc:
            if exc.kind == "not_found":
                gone += 1
                continue
            failed += 1
            _logger.warning("could not purge server job %s: %s", server_id, exc)
            if exc.kind == "unreachable":
                failed += len(plan.server_job_ids) - position - 1
                break
    _logger.info("server cleanup: %d purged, %d already gone, %d not purged", removed, gone, failed)
