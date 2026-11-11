"""Cleaning up the GPU server: what is left there when a job is done, and how to remove it.

Nothing here runs by itself after a job. The app never purges a job on its own: the server keeps
every job (output, logs and uploads) until its own retention (`job_retention_days`, see
`GET /v1/health`) deletes it, so the logs of a failed job can still be read there. A purge
(`DELETE /v1/jobs/{id}/purge`) happens in two cases, both chosen by the user:

- `purge_jobs`: the Activity page's "Purge on GPU server" action, for the jobs the user ticked.
  It answers per job and writes the server's answer to `job.output.purge`.
- `make_plan` and `purge`: the delete dialogs' optional checkbox ("also delete what is left on
  the GPU server"), for the jobs behind what is deleted.

The delete flow has two steps, because the rows are gone after the delete:
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
from typing import Any, Final, Literal

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


PurgeOutcome = Literal["purged", "already_gone", "skipped", "failed"]


@dataclass(frozen=True)
class JobPurgeResult:
    """What a manual purge did for one job."""

    job_id: int
    outcome: PurgeOutcome
    message: str


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


# --- the manual purge (Activity page) ---------------------------------------------------------


def can_purge(job: Job) -> bool:
    """Whether a purge would do something for this job: it is a GPU job that is not queued or
    running, it reached the server (it has a server job id), and its own purge has not worked
    yet.
    """
    return (
        job.provider == "gpu"
        and job.status not in store.ACTIVE_STATUSES
        and len(_server_ids_of(job.provider_job_id, job.input)) > 0
        and not _already_purged(job.output)
    )


def _server_url_of(job: Job, default: str) -> str:
    """The server a job was sent to (a transcription job may go to its own server), as the job
    recorded it when it submitted; the GPU server's address when it recorded none.
    """
    recorded = job.input.get("server_url") if isinstance(job.input, dict) else None
    return recorded if isinstance(recorded, str) and recorded.strip() else default


def _not_tried(job_id: int) -> JobPurgeResult:
    return JobPurgeResult(job_id, "failed", "Not tried: the server did not answer.")


async def _purge_one(
    job_id: int, base_url: str, server_ids: list[str]
) -> tuple[JobPurgeResult, list[dict[str, Any]], bool]:
    """Purges the server jobs of one job. Returns the result, one answer per server job (for
    `job.output.purge`), and whether the server did not answer (so the caller stops).
    """
    answers: list[dict[str, Any]] = []
    gone = 0
    first_error: str | None = None
    for server_id in server_ids:
        try:
            answers.append((await gpu_server.purge_job(base_url, server_id)).to_json())
        except GpuCallError as exc:
            if exc.kind == "not_found":
                # The server no longer has it. Recorded as a purge that worked, so the job
                # is not offered again.
                gone += 1
                answers.append(
                    {"removed_asset_ids": [], "kept_asset_ids": [], "already_gone": True}
                )
                continue
            _logger.warning("could not purge server job %s: %s", server_id, exc)
            answers.append({"error": str(exc)})
            first_error = first_error or str(exc)
            if exc.kind == "unreachable":
                return JobPurgeResult(job_id, "failed", str(exc)), answers, True
    if first_error is not None:
        return JobPurgeResult(job_id, "failed", first_error), answers, False
    if gone == len(server_ids):
        return (
            JobPurgeResult(job_id, "already_gone", "The server no longer had this job."),
            answers,
            False,
        )
    return JobPurgeResult(job_id, "purged", "Purged on the server."), answers, False


async def purge_jobs(session: AsyncSession, job_ids: Iterable[int]) -> list[JobPurgeResult]:
    """Purges these jobs on the GPU server, one after the other, and records each answer in
    `job.output.purge` (one answer for a job with one server job, a list for a speech job).

    A job that cannot be purged (not a GPU job, still running, never reached the server, already
    purged, or not found) is skipped with the reason. A server job the server does not know
    counts as already gone. When the server does not answer, the rest is not tried. The results
    are in the order of `job_ids`, without repeats.
    """
    wanted = list(dict.fromkeys(job_ids))
    default_url = await settings_service.get_str(session, GPU_URL_KEY)
    results: dict[int, JobPurgeResult] = {}
    work: list[tuple[int, str, list[str]]] = []
    for job_id in wanted:
        job = await store.get_job(session, job_id)
        if job is None:
            results[job_id] = JobPurgeResult(job_id, "skipped", "This job does not exist.")
        elif job.provider != "gpu":
            results[job_id] = JobPurgeResult(
                job_id, "skipped", "This job did not use the GPU server."
            )
        elif job.status in store.ACTIVE_STATUSES:
            results[job_id] = JobPurgeResult(
                job_id, "skipped", "The job is still queued or running."
            )
        elif not _server_ids_of(job.provider_job_id, job.input):
            results[job_id] = JobPurgeResult(job_id, "skipped", "The job never reached the server.")
        elif _already_purged(job.output):
            results[job_id] = JobPurgeResult(job_id, "skipped", "Already purged.")
        else:
            work.append(
                (
                    job_id,
                    _server_url_of(job, default_url),
                    _server_ids_of(job.provider_job_id, job.input),
                )
            )
    await session.commit()  # end the read before the calls to the server

    for position, (job_id, base_url, server_ids) in enumerate(work):
        result, answers, unreachable = await _purge_one(job_id, base_url, server_ids)
        results[job_id] = result
        recorded: Any = answers[0] if len(answers) == 1 else answers
        await store.merge_output(session, job_id, {"purge": recorded})
        if unreachable:
            for later_id, _url, _ids in work[position + 1 :]:
                results[later_id] = _not_tried(later_id)
            break
    return [results[job_id] for job_id in wanted]
