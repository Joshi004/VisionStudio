"""The `write_youtube_draft` job: a language model writes the title, the description, the
hashtags and the tags, and code checks them (YT-003, `YouTube_publish_phases.md` §4.5; the two
declarations are not drafted since YTF-002).

`services/youtube_draft.start_run` creates the job with a copy of everything it needs, taken when
the button was pressed: `render_id` (the render the draft is for), `context` (what the model is
told about the video), `saved_inputs` (the provenance the version will carry) and the owner's note
with the earlier draft when there is one.

There is one call. Its request is built in `services/youtube_draft_writer.py`, and its answer is
checked there: an answer that breaks a check (a title over 100 characters, a hashtag with a space,
a description over YouTube's limit) makes the answer unusable, and the corrected retry of
`jobs/llm_call.py` tells the model what was wrong. The result is saved as the project's next
version, in the same transaction that marks the job succeeded.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold: at most 2 attempts, a refusal never retried, every answer saved the
moment it arrives, and a restart does not run it again (`never_rerun`): the owner asks again with
a fresh job. Logs hold the job id, what each attempt did and its token counts, never the Story
Bible, the script, the note or the answers.
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
from app.services import llm_target, user_feedback, youtube_draft
from app.services import youtube_draft_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = youtube_draft.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no description of the video to read."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    render_id: int
    context: dict[str, Any]
    saved_inputs: dict[str, Any]
    feedback: user_feedback.Feedback | None


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    render_id = job_input.get("render_id")
    context = job_input.get("context")
    saved_inputs = job_input.get("saved_inputs")
    if (
        not isinstance(render_id, int)
        or isinstance(render_id, bool)
        or not isinstance(context, dict)
        or not isinstance(saved_inputs, dict)
    ):
        return None
    ok, feedback = user_feedback.read(job_input.get("feedback"))
    if not ok:
        return None
    return _Task(render_id=render_id, context=context, saved_inputs=saved_inputs, feedback=feedback)


def _draft_reader() -> llm_call.ReadAnswer:
    """Reads the model's answer: the stored content, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = writer.parse_answer(result.content)
            content = writer.check_content(answer, min_hashtags=writer.HASHTAGS_MIN_AI)
        except ValueError as exc:
            return str(exc), None
        return None, content

    return read


class WriteYouTubeDraftHandler(JobHandler):
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
        body = writer.build_request(task.context, model=target.model, feedback=task.feedback)
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            calls_sent={
                "draft": {
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
            _draft_reader(),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(job_id, f"The YouTube draft could not be written: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_YOUTUBE_DRAFT)
        async with SessionLocal() as session:
            row = await youtube_draft.save_version(
                session,
                project_id=project_id,
                job_id=job_id,
                render_id=task.render_id,
                inputs=task.saved_inputs,
                content=content,
            )
            output = {
                "calls": {"draft": outcome.record()},
                "usage": outcome.usage or {},
                "youtube_draft_id": row.id,
                "version": row.version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: YouTube draft version %d saved for project %d, usage=%s",
            job_id,
            row.version,
            project_id,
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
