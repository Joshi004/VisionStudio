"""The `write_sound_effect` job: a language model writes the prompt of one of a continuous
explainer's two sound effects, and the takes of the sound are made from it (EXM-006, XM-9,
MD-23).

`services/sound_effects` creates the job with a copy of everything it needs, taken when the
button was pressed: the Story Bible's tone and the Music Bible's palette (`material`), the sound
(`role`), the round, the GPU partition and one seed for each take (`seeds`). For the rewrite of a
rejected take it also holds `feedback`: the rejected fields, what was measured (as sentences, the
model takes no audio), the owner's note and whether the rejected take was the selected one.

There is one call. Its request is built and its answer checked in
`services/sound_effect_writer.py`: an answer that breaks a check makes the answer unusable, and
the corrected retry of `jobs/llm_call.py` tells the model what was wrong. The takes (a
`lab_music` run each) are queued in the same transaction that marks this job succeeded.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold: at most 2 attempts, a refusal never retried, every answer saved the
moment it arrives, and a restart queues it again (`never_rerun`): the owner asks again with a
fresh job. It is a local-style job: everything happens in `start`. Logs hold the job id and token
counts, never the story, the note or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import dispatcher, llm_call, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, sound_effects
from app.services import sound_effect_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = sound_effects.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no sound effect to write."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    role: str
    round_no: int
    material: dict[str, Any]
    partition: str
    seeds: list[int]
    # `{take_id, rejected_fields, facts, note, claim}` for the rewrite of a rejected take.
    feedback: dict[str, Any] | None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read_feedback(value: object) -> tuple[bool, dict[str, Any] | None]:
    """`(ok, feedback)`: a missing feedback is fine, a malformed one is not."""
    if value is None:
        return True, None
    if (
        isinstance(value, dict)
        and _is_int(value.get("take_id"))
        and isinstance(value.get("rejected_fields"), dict)
        and isinstance(value.get("facts"), list)
        and isinstance(value.get("note"), str)
        and isinstance(value.get("claim"), bool)
    ):
        return True, value
    return False, None


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    role = job_input.get("role")
    material = job_input.get("material")
    partition = job_input.get("partition")
    seeds = job_input.get("seeds")
    ok, feedback = _read_feedback(job_input.get("feedback"))
    if (
        role not in writer.ROLES
        or not isinstance(material, dict)
        or not isinstance(partition, str)
        or not _is_int(job_input.get("round"))
        or not isinstance(seeds, list)
        or not seeds
        or not all(_is_int(seed) for seed in seeds)
        or not ok
    ):
        return None
    return _Task(
        role=str(role),
        round_no=int(job_input["round"]),
        material=material,
        partition=partition,
        seeds=[int(seed) for seed in seeds],
        feedback=feedback,
    )


def _reader(task: _Task) -> llm_call.ReadAnswer:
    """Reads the model's answer: the prompt fields, or why the answer cannot be used."""
    rejected = task.feedback["rejected_fields"] if task.feedback is not None else None

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            fields = writer.check_answer(
                writer.parse_answer(result.content), rejected_fields=rejected
            )
        except ValueError as exc:
            return str(exc), None
        return None, fields

    return read


class WriteSoundEffectHandler(JobHandler):
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
        if task.feedback is None:
            body = writer.build_request(task.role, task.material, model=target.model)
        else:
            body = writer.build_feedback_request(
                task.role,
                task.material,
                rejected_fields=task.feedback["rejected_fields"],
                facts=[str(fact) for fact in task.feedback["facts"]],
                note=task.feedback["note"],
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

        # `correct`: the second attempt is told why the first answer was refused.
        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            _reader(task),
            timeout_s=REQUEST_TIMEOUT_S,
            correct=True,
        )
        if outcome.value is None:
            await self._fail(job_id, f"The prompt could not be written: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_SOUND_EFFECT)
        async with SessionLocal() as session:
            try:
                if task.feedback is None:
                    takes = await sound_effects.save_round(
                        session,
                        project_id=project_id,
                        job_id=job_id,
                        role=task.role,
                        round_no=task.round_no,
                        fields=outcome.value,
                        seeds=task.seeds,
                        partition=task.partition,
                    )
                else:
                    takes = [
                        await sound_effects.save_feedback_take(
                            session,
                            project_id=project_id,
                            job_id=job_id,
                            role=task.role,
                            task_take_id=int(task.feedback["take_id"]),
                            round_no=task.round_no,
                            claim=bool(task.feedback["claim"]),
                            fields=outcome.value,
                            seed=task.seeds[0],
                            partition=task.partition,
                        )
                    ]
            except sound_effects.SoundEffectError as exc:
                await session.rollback()
                await self._fail(job_id, str(exc))
                return
            output = {
                "call": outcome.record(),
                "usage": outcome.usage,
                "saved": {"sound_effect_take_ids": [take.id for take in takes]},
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: nothing is kept, and no recording starts.
                await session.rollback()
                return
            await session.commit()
        dispatcher.nudge()

        _logger.info(
            "job %d: sound effect '%s' written for project %d (%d take(s)), usage=%s",
            job_id,
            task.role,
            project_id,
            len(takes),
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
