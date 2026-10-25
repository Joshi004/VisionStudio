"""The `write_story_bible` job: a language model writes a story project's StoryBible
(PHASE-004, `Path_ahead.md` Section 6).

`services/story_bible.start_run` creates the job with a copy of the saved story and its hash
(`input.story_text`, `input.story_sha256`). This job builds the request
(`services/story_bible_writer.py`), asks the model, checks the answer, and saves it as the
project's next StoryBible version, in the same transaction that marks the job succeeded.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`): Bitdeer's GLM-5.3, or Qwen3.8 on
the GPU server when the Story provider setting says so. Which of the two shared pools the job
waits in follows that setting (`jobs/pools.py`).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by starting a fresh job with the Re-run button.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the story or the answer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, story_bible
from app.services import story_bible_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = story_bible.JOB_TYPE
# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no story to read."


def _read(result: llm.ChatResult, warnings: list[str]) -> tuple[str | None, dict[str, Any] | None]:
    """Reads one answer: `(None, content)` when it can be stored, else `(why not, None)`.
    What had to be cut from a usable answer is put in `warnings` (replacing earlier ones).
    """
    if result.finish_reason == "length":
        return "The model's answer was cut off because it reached the token limit.", None
    found: list[str] = []
    try:
        content = writer.check_bible(writer.parse_answer(result.content), found)
    except ValueError as exc:
        return str(exc), None
    warnings[:] = found
    return None, content


class WriteStoryBibleHandler(JobHandler):
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

        story = job_input.get("story_text")
        story_sha256 = job_input.get("story_sha256")
        if project_id is None or not isinstance(story, str) or not isinstance(story_sha256, str):
            await self._fail(job_id, _BAD_INPUT)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = writer.build_request(story, model=target.model)
        job_input.update(
            instructions_sha256=llm_call.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        warnings: list[str] = []
        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            lambda result: _read(result, warnings),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(job_id, f"The Story Bible could not be written: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_STORY_BIBLE)
        async with SessionLocal() as session:
            bible = await story_bible.save_version(
                session,
                project_id=project_id,
                job_id=job_id,
                story_sha256=story_sha256,
                content=content,
            )
            output = {
                **outcome.record(),
                "content": None,
                "warnings": warnings,
                "story_bible_id": bible.id,
                "version": bible.version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: story bible version %d saved for project %d, usage=%s",
            job_id,
            bible.version,
            project_id,
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
