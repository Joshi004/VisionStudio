"""The `suggest_footage_marks` job: a language model proposes places in the story where real
footage would help, and code finds each in the story (FTG-002,
`Footage_broll_implementation_phases.md` FT-4).

`services/footage_marks.start_suggest` creates the job with a copy of everything it needs, taken
when it was queued: `input.script`, `script_sha256`, `marks` (as they stood in the story),
`based_on_version` (the mark list version they are, or null) and `context` (`claims`,
`soundbites` and `graphics`: the words that already have something shown).

There is one call. Its request is built in `services/footage_marks_writer.py`, and its answer is
checked there: an answer of the wrong shape makes it unusable, and the corrected retry of
`jobs/llm_call.py` tells the model what was wrong. Code then finds each phrase in the story and
leaves out those it cannot place. The result is saved as the project's next mark list version
(`source` `ai`), in the same transaction that marks the job succeeded. When the story or the mark
list is no longer what the job started from, nothing is saved and the job fails.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold: at most 2 attempts, a refusal never retried, every answer saved the
moment it arrives, and a restart queues it again (`never_rerun`).

`job.output`: `{calls: {marks: <record of the call>}, usage, mark_list_id, version, proposed,
dropped, seconds}`. `proposed` is how many proposals were saved, and `dropped` is `[{phrase,
why}]`: what the model proposed that code left out. Logs hold the job id, what each attempt did
and its token counts, never the story or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import Project
from app.db.session import SessionLocal
from app.jobs import llm_call, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import footage_marks, llm_target
from app.services import footage_marks_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = footage_marks.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no story to read."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    script: str
    script_sha256: str
    marks: list[dict[str, Any]]
    based_on_version: int | None
    context: dict[str, Any]


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    script = job_input.get("script")
    script_hash = job_input.get("script_sha256")
    marks = job_input.get("marks")
    based_on = job_input.get("based_on_version")
    context = job_input.get("context")
    if (
        not isinstance(script, str)
        or not script.strip()
        or not isinstance(script_hash, str)
        or not isinstance(marks, list)
        or not all(isinstance(mark, dict) for mark in marks)
        or not (based_on is None or (isinstance(based_on, int) and not isinstance(based_on, bool)))
        or not isinstance(context, dict)
    ):
        return None
    return _Task(
        script=script,
        script_sha256=script_hash,
        marks=marks,
        based_on_version=based_on,
        context=context,
    )


def _stays(marks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The marks the proposals are placed around: all but the proposals the owner has not
    decided on, which this call replaces.
    """
    return [mark for mark in marks if not footage_marks.is_undecided(mark)]


def _soundbites(context: dict[str, Any]) -> list[dict[str, Any]]:
    """The sound bite quotes of the context, or none when it is not shaped as expected."""
    items = context.get("soundbites")
    if not isinstance(items, list):
        return []
    return [
        item
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("start"), int)
        and isinstance(item.get("end"), int)
    ]


def _answer_reader() -> llm_call.ReadAnswer:
    """Reads the model's answer: the proposals, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, writer.Answer | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            return None, writer.check_answer(writer.parse_answer(result.content))
        except ValueError as exc:
            return str(exc), None

    return read


class SuggestFootageMarksHandler(JobHandler):
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

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = writer.build_request(
            task.script, _stays(task.marks), task.context, model=target.model
        )
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            calls_sent={
                "marks": {
                    "instructions_sha256": llm_call.instructions_sha256(body),
                    "request": body,
                }
            },
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            _answer_reader(),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        answer: writer.Answer | None = outcome.value
        if answer is None:
            await self._fail(job_id, f"The footage could not be proposed: {outcome.failure}")
            return

        located, dropped = writer.locate_proposals(
            task.script,
            _stays(task.marks),
            _soundbites(task.context),
            answer.proposals,
            writer.proposal_limit(task.script),
        )

        await self._phase(job_id, phases.SAVING_FOOTAGE_MARKS)
        async with SessionLocal() as session:
            project = await session.get(Project, project_id)
            if project is None:
                await store.fail_job(session, job_id, "The project no longer exists.")
                return
            try:
                row = await footage_marks.save_ai_version(
                    session,
                    project,
                    job_id=job_id,
                    based_on_version=task.based_on_version,
                    script_hash=task.script_sha256,
                    proposals=located,
                )
            except footage_marks.FootageMarksError as exc:
                await session.rollback()
                await store.fail_job(session, job_id, str(exc))
                return
            output = {
                "calls": {"marks": outcome.record()},
                "usage": outcome.usage or {},
                "mark_list_id": row.id,
                "version": row.version,
                "proposed": len(located),
                "dropped": dropped,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: footage mark list version %d saved for project %d "
            "(%d proposed, %d left out), usage=%s",
            job_id,
            row.version,
            project_id,
            len(located),
            len(dropped),
            outcome.usage,
        )

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        await phase_writer.note(job_id, phase)

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
