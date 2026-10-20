"""The `define_character` job: a language model writes one story character's structured
definition, and code stores it on the library character, as a new version the project pins
(PHASE-009, `Path_ahead.md` Section 11).

`services/character_definitions.start_run` creates the job with a copy of the saved story and
its hash, the id and version of the StoryBible, the character to define (`entry`), the other
characters (`others`), the library character it is linked to (`character_id`) and the `inputs`
that are written onto the version (D-3). The job loads the StoryBible and the library character,
builds the request, asks the model, checks the answer, and saves it
(`services/character_definitions.save_definition`) in the same transaction that marks the job
succeeded.

One job per character, so characters are defined side by side when the pools allow
(`store.create_job` with `dedupe_key`). The model is the **story role**
(`llm_target.STORY_MODEL_KEY`), like every story stage (D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by pressing Define again.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the story or the answer.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import (
    character_definition_writer,
    character_definitions,
    character_library,
    discovery,
    llm_target,
)
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no character to define."
_NO_BIBLE = "The Story Bible this run was started with could not be found."
_NO_CHARACTER = "The Character Lab character this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `start_run` put on the job, checked."""

    story: str
    entry: dict[str, str]
    others: list[dict[str, str]]
    inputs: dict[str, Any]
    character_id: int
    bible_id: int


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `start_run` writes is missing or the wrong
    shape (a job made by hand, or by an older version of the code).
    """
    story = job_input.get("story_text")
    entry = job_input.get("entry")
    others = job_input.get("others")
    inputs = job_input.get("inputs")
    character_id = job_input.get("character_id")
    bible_id = job_input.get("story_bible_id")
    if (
        not isinstance(story, str)
        or not isinstance(entry, dict)
        or not isinstance(entry.get("id"), str)
        or not isinstance(entry.get("name"), str)
        or not isinstance(others, list)
        or not isinstance(inputs, dict)
        or not isinstance(character_id, int)
        or not isinstance(bible_id, int)
    ):
        return None
    return _Input(
        story=story,
        entry=entry,
        others=others,
        inputs=inputs,
        character_id=character_id,
        bible_id=bible_id,
    )


class DefineCharacterHandler(JobHandler):
    job_type = character_definitions.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(
        result: llm.ChatResult, discovery_id: str
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, definition)` when it can be stored, else `(why not, None)`."""
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = character_definition_writer.parse_answer(result.content)
            return None, character_definition_writer.check_definition(answer, discovery_id)
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
            read = _read_input(job_input)
            bible = (
                await discovery.get_bible(session, project_id, read.bible_id)
                if project_id is not None and read is not None
                else None
            )
            character = (
                await character_library.get_character(session, read.character_id)
                if read is not None
                else None
            )
            # The character's profile as it is now, so the definition keeps to what a person
            # has written. A character with no appearance yet has nothing to keep to.
            card = (
                character_library.character_card(character)
                if character is not None and character.appearance
                else None
            )
            bible_content = bible.content if bible is not None else None
            await session.commit()

        if project_id is None or read is None:
            await self._fail(job_id, _BAD_INPUT)
            return
        name = read.entry["name"]
        discovery_id = read.entry["id"]
        if bible_content is None:
            await self._fail(job_id, _NO_BIBLE)
            return
        if character is None:
            await self._fail(job_id, _NO_CHARACTER)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = character_definition_writer.build_request(
            story_text=read.story,
            bible_content=bible_content,
            entry=read.entry,
            others=read.others,
            current_profile=card,
            today_year=date.today().year,
            model=target.model,
        )
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
            lambda result: self._read(result, discovery_id),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        definition: dict[str, Any] | None = outcome.value
        if definition is None:
            await self._fail(
                job_id, f"The definition of {name} could not be written: {outcome.failure}"
            )
            return

        await self._phase(job_id, phases.SAVING_DEFINITION)
        async with SessionLocal() as session:
            try:
                version = await character_definitions.save_definition(
                    session,
                    project_id=project_id,
                    discovery_id=discovery_id,
                    character_id=read.character_id,
                    definition=definition,
                    job_id=job_id,
                    inputs=read.inputs,
                )
            except character_definitions.CharacterDefinitionError as exc:
                await session.rollback()
                await self._fail(job_id, f"The definition of {name} could not be saved: {exc}")
                return
            output = {
                **outcome.record(),
                "content": None,
                "character_id": read.character_id,
                "version": version.version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the definition is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: character %d defined as '%s' for project %d, version %d, usage=%s",
            job_id,
            read.character_id,
            discovery_id,
            project_id,
            version.version,
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
