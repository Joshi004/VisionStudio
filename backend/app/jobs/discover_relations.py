"""The `discover_relations` job: a language model lists the relations between the story's
characters (PHASE-047).

`services/character_relations.start_run` creates the job with a copy of the saved story and its
hash, and the ids and versions of the StoryBible and of the list of characters it reads. The
job loads both, asks the model once for every relation of the project (one call, so the
relations agree with each other), checks the answer (`services/character_relation_writer.py`),
and saves it as the project's next version of the relations, in the same transaction that
marks the job succeeded.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every story stage (D-12).
A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again with the Find relations button.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the story or the answer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import CharacterDiscovery
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import character_relation_writer as writer
from app.services import character_relations, discovery, llm_target
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no story to read."
_NO_BIBLE = "The Story Bible this run was started with could not be found."
_NO_CHARACTERS = "The list of characters this run was started with could not be found."


class DiscoverRelationsHandler(JobHandler):
    job_type = character_relations.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(
        result: llm.ChatResult, character_ids: set[str]
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, content)` when it can be stored, else `(why not, None)`."""
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = writer.parse_answer(result.content)
            return None, writer.check_relations(answer, character_ids)
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
            list_id = job_input.get("discovery_id")
            characters_row = (
                await session.get(CharacterDiscovery, list_id) if isinstance(list_id, int) else None
            )
            if characters_row is not None and characters_row.project_id != project_id:
                characters_row = None
            await session.commit()

        story = job_input.get("story_text")
        story_sha256 = job_input.get("story_sha256")
        if project_id is None or not isinstance(story, str) or not isinstance(story_sha256, str):
            await self._fail(job_id, _BAD_INPUT)
            return
        if bible is None:
            await self._fail(job_id, _NO_BIBLE)
            return
        if characters_row is None:
            await self._fail(job_id, _NO_CHARACTERS)
            return
        bible_content = bible.content
        bible_row_id = bible.id
        bible_version = bible.version
        characters: list[dict[str, str]] = [
            {"id": item["id"], "name": item["name"], "description": item["description"]}
            for item in characters_row.content["characters"]
        ]
        list_row_id = characters_row.id
        list_version = characters_row.version
        character_ids = {item["id"] for item in characters}

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = writer.build_request(story, bible_content, characters, model=target.model)
        job_input.update(
            instructions_sha256=llm_call.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            lambda result: self._read(result, character_ids),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(job_id, f"The relations could not be found: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_RELATIONS)
        async with SessionLocal() as session:
            row = await character_relations.save_version(
                session,
                project_id=project_id,
                job_id=job_id,
                story_sha256=story_sha256,
                bible_id=bible_row_id,
                bible_version=bible_version,
                discovery_id=list_row_id,
                discovery_version=list_version,
                relations=content["relations"],
            )
            output = {
                **outcome.record(),
                "content": None,
                "relations_id": row.id,
                "version": row.version,
                "count": len(content["relations"]),
                "story_bible_version": bible_version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: relations version %d saved for project %d (%d relations), usage=%s",
            job_id,
            row.version,
            project_id,
            len(content["relations"]),
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
