"""The `write_shot_graphic_brief` job: a language model reads the words of one graphic shot of a
continuous explainer, and the sentences around them, and writes the brief of the graphic; code
checks it (EXG-004, `Explainer_graphics_implementation_phases.md` §3.2 and §3.4).

`services/shot_graphic_briefs.start_shot` creates the job with a copy of everything it needs,
taken when the button was pressed: the shot's words, the words before and after it, the planner's
description, the shot's length, the orientation, the Story Bible's title and tone, the upstream
rows the version is built from, and the owner's note with the earlier brief when there is one
(`input.shot_words`, `before`, `after`, `description`, `shot_seconds`, `orientation`, `bible`,
`saved_inputs`, `feedback`).

There is one call. Its request is built in `services/shot_graphic_brief_writer.py`, and its answer
is checked there: a fact must be said in the shot's words or the sentences around them, a beat on
the shot's own words. An answer that breaks a check is unusable, and the corrected retry of
`jobs/llm_call.py` tells the model what was wrong. The result is saved as the shot's next version,
in the same transaction that marks the job succeeded.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold: at most 2 attempts, a refusal never retried, every answer saved the
moment it arrives, and a restart queues it again (`never_rerun`): the owner asks again with a
fresh job.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the words, the note or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import llm_call, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, shot_graphic_briefs, user_feedback
from app.services import shot_graphic_brief_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = shot_graphic_briefs.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no shot to read."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    scene_id: str
    shot_id: str
    shot_plan_id: int
    shot_words: str
    before: str
    after: str
    description: str
    shot_seconds: float
    orientation: str
    bible: dict[str, Any]
    saved_inputs: dict[str, Any]
    feedback: user_feedback.Feedback | None

    @property
    def context_text(self) -> str:
        """The shot's words with the sentences around them, in order."""
        return " ".join(part for part in (self.before, self.shot_words, self.after) if part)


def _text(value: Any, *, required: bool) -> str | None:
    if not isinstance(value, str) or (required and not value.strip()):
        return None
    return value


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    scene_id = _text(job_input.get("scene_id"), required=True)
    shot_id = _text(job_input.get("shot_id"), required=True)
    shot_words = _text(job_input.get("shot_words"), required=True)
    before = _text(job_input.get("before"), required=False)
    after = _text(job_input.get("after"), required=False)
    description = _text(job_input.get("description"), required=True)
    orientation = _text(job_input.get("orientation"), required=True)
    plan_id = job_input.get("shot_plan_id")
    seconds = job_input.get("shot_seconds")
    bible = job_input.get("bible")
    saved_inputs = job_input.get("saved_inputs")
    if (
        scene_id is None
        or shot_id is None
        or shot_words is None
        or before is None
        or after is None
        or description is None
        or orientation is None
        or not isinstance(plan_id, int)
        or isinstance(plan_id, bool)
        or not isinstance(seconds, int | float)
        or isinstance(seconds, bool)
        or not isinstance(bible, dict)
        or not isinstance(saved_inputs, dict)
    ):
        return None
    ok, feedback = user_feedback.read(job_input.get("feedback"))
    if not ok:
        return None
    return _Task(
        scene_id=scene_id,
        shot_id=shot_id,
        shot_plan_id=plan_id,
        shot_words=shot_words,
        before=before,
        after=after,
        description=description,
        shot_seconds=float(seconds),
        orientation=orientation,
        bible=bible,
        saved_inputs=saved_inputs,
        feedback=feedback,
    )


def _brief_reader(task: _Task) -> llm_call.ReadAnswer:
    """Reads the model's answer: the stored brief, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = writer.parse_answer(result.content)
            brief = writer.check_answer(answer, task.shot_words, task.context_text)
        except ValueError as exc:
            return str(exc), None
        return None, brief

    return read


class WriteShotGraphicBriefHandler(JobHandler):
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
            shot_words=task.shot_words,
            before=task.before,
            after=task.after,
            description=task.description,
            shot_seconds=task.shot_seconds,
            orientation=task.orientation,
            bible=task.bible,
            model=target.model,
            feedback=task.feedback,
        )
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            calls_sent={
                "brief": {
                    "instructions_sha256": llm_call.instructions_sha256(body),
                    "request": body,
                }
            },
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, _brief_reader(task), timeout_s=REQUEST_TIMEOUT_S
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(job_id, f"The brief could not be written: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_GRAPHIC_BRIEF)
        async with SessionLocal() as session:
            row = await shot_graphic_briefs.save_version(
                session,
                project_id=project_id,
                scene_id=task.scene_id,
                shot_id=task.shot_id,
                shot_plan_id=task.shot_plan_id,
                job_id=job_id,
                inputs=task.saved_inputs,
                content=content,
            )
            output = {
                "calls": {"brief": outcome.record()},
                "usage": outcome.usage or {},
                "shot_graphic_brief_id": row.id,
                "scene_id": task.scene_id,
                "shot_id": task.shot_id,
                "version": row.version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: graphic brief version %d saved for project %d (%d facts, %d beats), usage=%s",
            job_id,
            row.version,
            project_id,
            len(content["facts"]),
            len(content["beats"]),
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
