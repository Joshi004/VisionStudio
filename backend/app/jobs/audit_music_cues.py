"""The `audit_music_cues` job: a language model reads every prompt of a story project's music
plan together, checks them against the Music Bible and against each other, and fixes what does
not fit (MUSIC-009, `Music_implementation_phases.md` Section 4.3).

`services/music_cues.start_audit` creates the job with the plan's id, the ids of the cue rows to
audit (each cue's newest row), the Music Bible's content and what the Bible says to avoid
(`input.plan_id`, `row_ids`, `bible`, `avoid`). The job reads the rows themselves, so the
wordings are not copied into its input.

One call. The audit says `ok`, or `change` with fixes: a fix names an item and one of its
wordings and gives the fields to change. The answer is checked like new wordings
(`music_cue_writer.check_audit`): the fields must be ones the music model's server accepts, a
theme cue's tempo, key and time signature never change, and no two wordings of an item may become
the same text. A call that cannot be used fails the job.

The result is saved with its fixes applied as new rows of the cues they touch
(`music_cues.save_audit`), in the same transaction that marks the job succeeded.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold: at most 2 attempts (the second told what was wrong with the first answer),
a refusal never retried, every answer saved the moment it arrives, and a restart never re-runs
it (`never_rerun`).

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the story or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, music_cue_writer, music_cues
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = music_cues.AUDIT_JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no prompts to audit."
_ROWS_GONE = "The cue details to audit could not be found."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    plan_id: int
    row_ids: list[int]
    bible: dict[str, Any]
    avoid: list[str]


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    plan_id = job_input.get("plan_id")
    row_ids = job_input.get("row_ids")
    bible = job_input.get("bible")
    avoid = job_input.get("avoid")
    if (
        isinstance(plan_id, bool)
        or not isinstance(plan_id, int)
        or not isinstance(row_ids, list)
        or not row_ids
        or not all(isinstance(item, int) and not isinstance(item, bool) for item in row_ids)
        or not isinstance(bible, dict)
        or not isinstance(avoid, list)
    ):
        return None
    return _Task(
        plan_id=plan_id, row_ids=list(row_ids), bible=bible, avoid=[str(item) for item in avoid]
    )


def _audit_reader(items: list[dict[str, Any]], avoid: list[str]) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, Any]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = music_cue_writer.parse_answer(result.content)
            return None, music_cue_writer.check_audit(answer, items, avoid=avoid)
        except ValueError as exc:
            return str(exc), None

    return read


class AuditMusicCuesHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            project_id = job.project_id
            target = await llm_target.resolve(session, STORY_MODEL_KEY)
            await session.commit()

        task = _read_task(job_input)
        if project_id is None or task is None:
            await self._fail(job_id, _BAD_INPUT)
            return

        async with SessionLocal() as session:
            plan_row = await music_cues.get_plan(session, task.plan_id)
            rows = await music_cues.rows_by_ids(session, task.row_ids)
            await session.commit()
        if (
            plan_row is None
            or plan_row.project_id != project_id
            or len(rows) != len(task.row_ids)
            or any(row.plan_id != task.plan_id for row in rows)
        ):
            await self._fail(job_id, _ROWS_GONE)
            return
        items = [item for row in rows for item in row.items]
        cues_by_id = {cue["id"]: cue for cue in plan_row.content["cues"]}
        cue_lines = [
            music_cue_writer.cue_line(cues_by_id[row.cue_id])
            for row in sorted(
                rows, key=lambda row: music_cue_writer.cue_start(cues_by_id[row.cue_id])
            )
        ]

        await self._phase(job_id, phases.PREPARING_PROMPT)
        job_input.update(
            server_url=docker_mapped(target.base_url), endpoint=llm_target.endpoint(target)
        )
        body = music_cue_writer.build_audit_request(
            task.bible, cue_lines, items, model=target.model
        )
        job_input["calls_sent"] = {
            "audit": {
                "instructions_sha256": llm_call.instructions_sha256(body),
                "request": body,
            }
        }
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            _audit_reader(items, task.avoid),
            timeout_s=REQUEST_TIMEOUT_S,
            correct=True,
        )
        if outcome.value is None:
            await self._fail(job_id, f"The prompts could not be audited: {outcome.failure}")
            return
        findings: dict[str, Any] = outcome.value

        await self._phase(job_id, phases.SAVING_MUSIC_CUES)
        async with SessionLocal() as session:
            audit = await music_cues.save_audit(
                session,
                project_id=project_id,
                plan_id=task.plan_id,
                job_id=job_id,
                audited=rows,
                findings=findings,
            )
            output = {
                "calls": {"audit": outcome.record()},
                "usage": outcome.usage or {},
                "music_cue_audit_id": audit.id,
                "verdict": findings["verdict"],
                "fixes": len(findings["fixes"]),
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the audit and its fixes are not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: music cues audited for project %d (%s, %d fixes), usage=%s",
            job_id,
            project_id,
            findings["verdict"],
            len(findings["fixes"]),
            outcome.usage,
        )

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
