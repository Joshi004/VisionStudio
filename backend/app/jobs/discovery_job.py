"""The steps the two discovery jobs share (PHASE-005): `discover_characters` and
`discover_environments`.

`services/discovery.start_run` creates the job with a copy of the saved story and its hash
(`input.story_text`, `input.story_sha256`) and the id and version of the StoryBible the run
reads (`input.story_bible_id`, `input.story_bible_version`). The job loads that StoryBible,
builds the request (`services/discovery_writer.py`), asks the model, checks the answer, and
saves it as the project's next version of the list, in the same transaction that marks the job
succeeded.

The two jobs differ only in their `kind`, so each is a few lines in its own module
(`jobs/discover_characters.py`, `jobs/discover_environments.py`). They have different job
types on purpose: a project may have one job of each type waiting or running at the same time
(`store.create_job` merges two clicks of one type), so the two calls run side by side, and
beside scene discovery (D-15), when the pools allow.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every story stage (D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by starting a fresh job with the Re-run button.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the story or the answer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, ClassVar, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import discovery, llm_target
from app.services import discovery_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no story to read."
_NO_BIBLE = "The Story Bible this run was started with could not be found."


class DiscoveryHandler(JobHandler):
    """The shared job. A subclass sets `job_type`, `kind` and `saving_phase`."""

    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    kind: ClassVar[writer.Kind]
    saving_phase: ClassVar[str]

    def _read(self, result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, content)` when it can be stored, else `(why not, None)`."""
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            return None, writer.check_items(self.kind, writer.parse_answer(result.content))
        except ValueError as exc:
            return str(exc), None

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
            bible_id = job_input.get("story_bible_id")
            bible = (
                await discovery.get_bible(session, project_id, bible_id)
                if project_id is not None and isinstance(bible_id, int)
                else None
            )
            await session.commit()

        story = job_input.get("story_text")
        story_sha256 = job_input.get("story_sha256")
        if project_id is None or not isinstance(story, str) or not isinstance(story_sha256, str):
            await self._fail(job_id, _BAD_INPUT)
            return
        if bible is None:
            await self._fail(job_id, _NO_BIBLE)
            return
        bible_content = bible.content
        bible_row_id = bible.id
        bible_version = bible.version

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = writer.build_request(self.kind, story, bible_content, model=target.model)
        job_input.update(
            instructions_sha256=llm_call.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, self._read, timeout_s=REQUEST_TIMEOUT_S
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(job_id, f"The {self.kind} could not be found: {outcome.failure}")
            return

        await self._phase(job_id, self.saving_phase)
        async with SessionLocal() as session:
            row = await discovery.save_version(
                session,
                self.kind,
                project_id=project_id,
                job_id=job_id,
                story_sha256=story_sha256,
                bible_id=bible_row_id,
                bible_version=bible_version,
                content=content,
            )
            output = {
                **outcome.record(),
                "content": None,
                "discovery_id": row.id,
                "version": row.version,
                "count": len(content[self.kind]),
                "story_bible_version": bible_version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: %s version %d saved for project %d (%d items), usage=%s",
            job_id,
            self.kind,
            row.version,
            project_id,
            len(content[self.kind]),
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
