"""The `rewrite_music_prompt` job: a language model rewrites the prompt of a music take the owner
rejected, from the owner's note, and a new take is made from it (MUSIC-010, MD-23,
`Music_implementation_phases.md` Section 4.2).

`services/music_takes.reject` creates the job with a copy of everything it needs, taken when the
owner pressed the button: the cue and its detail, the Music Bible, the lane around the cue, the
rejected prompt, what was measured from the rejected sound (as sentences: the model takes no
audio, MD-10), the owner's note, the GPU partition and the seed. One call writes one new wording.
The request is built and the answer checked in `services/music_cue_writer.py`.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold: at most 2 attempts (the second told what was wrong with the first
answer), a refusal never retried, every answer saved the moment it arrives, and a restart never
re-runs it (`never_rerun`): the owner rejects the take again with a fresh job. The new take (a
`lab_music` run) is queued in the same transaction that marks this job succeeded. It is a
local-style job: everything happens in `start`. Logs hold the job id and token counts, never the
story, the note or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import dispatcher, llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, music_cue_writer, music_takes
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = music_takes.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no rejected take to read."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."

_STRING_KEYS: Final = ("item_key", "cue_id", "item_id", "detail_sha256", "note", "partition")
_DICT_KEYS: Final = ("bible", "cue", "detail", "item", "rejected_fields")
_INT_KEYS: Final = ("take_id", "plan_id", "round", "seed")


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    values: dict[str, Any]

    @property
    def item(self) -> dict[str, Any]:
        item: dict[str, Any] = self.values["item"]
        return item


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    for key in _STRING_KEYS:
        if not isinstance(job_input.get(key), str):
            return None
    for key in _DICT_KEYS:
        if not isinstance(job_input.get(key), dict):
            return None
    for key in _INT_KEYS:
        if not _is_int(job_input.get(key)):
            return None
    cue_row_id = job_input.get("cue_row_id")
    facts = job_input.get("facts")
    joins = job_input.get("joins")
    if (
        not (cue_row_id is None or _is_int(cue_row_id))
        or not isinstance(job_input.get("claim"), bool)
        or not isinstance(facts, list)
        or not isinstance(joins, list)
        or not isinstance(job_input.get("avoid"), list)
        or not all(key in job_input.get("item", {}) for key in ("model", "role"))
    ):
        return None
    for key in ("previous", "following"):
        if not (job_input.get(key) is None or isinstance(job_input.get(key), dict)):
            return None
    return _Task(dict(job_input))


def _reader(task: _Task, warnings: list[str]) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            checked = music_cue_writer.check_feedback(
                music_cue_writer.parse_answer(result.content),
                task.item,
                avoid=[str(word) for word in task.values["avoid"]],
                rejected_fields=task.values["rejected_fields"],
            )
        except ValueError as exc:
            return str(exc), None
        warnings[:] = checked["warnings"]
        return None, checked["fields"]

    return read


class RewriteMusicPromptHandler(JobHandler):
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
        values = task.values
        body = music_cue_writer.build_feedback_request(
            task.item,
            bible=values["bible"],
            cue=values["cue"],
            detail=values["detail"],
            previous=values["previous"],
            following=values["following"],
            joins=values["joins"],
            rejected_fields=values["rejected_fields"],
            facts=[str(fact) for fact in values["facts"]],
            note=values["note"],
            model=target.model,
        )
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            instructions_sha256=llm_call.instructions_sha256(body),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        warnings: list[str] = []
        # `correct`: the second attempt is told why the first answer was refused.
        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            _reader(task, warnings),
            timeout_s=REQUEST_TIMEOUT_S,
            correct=True,
        )
        if outcome.value is None:
            await self._fail(job_id, f"The prompt could not be rewritten: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_MUSIC_TAKE)
        async with SessionLocal() as session:
            try:
                take = await music_takes.save_feedback_take(
                    session,
                    project_id=project_id,
                    job_id=job_id,
                    task_take_id=values["take_id"],
                    plan_id=values["plan_id"],
                    cue_id=values["cue_id"],
                    item_id=values["item_id"],
                    cue_row_id=values["cue_row_id"],
                    sha=values["detail_sha256"],
                    round_no=values["round"],
                    claim=values["claim"],
                    item=task.item,
                    cue=values["cue"],
                    detail=values["detail"],
                    fields=outcome.value,
                    seed=values["seed"],
                    partition=values["partition"],
                )
            except music_takes.MusicTakeError as exc:
                await session.rollback()
                await self._fail(job_id, str(exc))
                return
            take_id = take.id
            output = {
                "call": outcome.record(),
                "usage": outcome.usage,
                "warnings": warnings,
                "saved": {"music_take_id": take_id},
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: nothing is kept, and no recording starts.
                await session.rollback()
                return
            await session.commit()
        dispatcher.nudge()

        _logger.info(
            "job %d: music prompt rewritten for project %d (take %d), usage=%s",
            job_id,
            project_id,
            take_id,
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
