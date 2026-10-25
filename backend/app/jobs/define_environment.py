"""The `define_environment` job: a language model writes one story environment's structured
definition, and code stores it on the library environment, as a new version the project pins,
then starts the version's canonical picture (PHASE-013, `Path_ahead.md` Section 13).

`services/environment_definitions.start_run` creates the job with a copy of the saved story and
its hash, the id and version of the StoryBible, the environment to define (`entry`), the other
environments (`others`), the story's scenes (`scenes`), the library environment it is linked to
(`environment_id`) and the `inputs` that are written onto the version (D-3). The job loads the
StoryBible and the library environment, builds the request, asks the model, checks the answer,
and saves it (`services/environment_definitions.save_definition`) in the same transaction that
marks the job succeeded. That transaction also creates the picture's prompt job, which the
dispatcher is nudged to pick up afterwards.

One job per environment, so environments are defined side by side when the pools allow
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
from app.jobs import dispatcher, llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import (
    discovery,
    environment_definition_writer,
    environment_definitions,
    environment_library,
    llm_target,
)
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no environment to define."
_NO_BIBLE = "The Story Bible this run was started with could not be found."
_NO_ENVIRONMENT = "The Character Lab environment this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `start_run` put on the job, checked."""

    story: str
    entry: dict[str, str]
    others: list[dict[str, str]]
    scenes: list[dict[str, Any]]
    inputs: dict[str, Any]
    environment_id: int
    bible_id: int
    # A reused environment (PHASE-048): the model keeps to its current profile, and its
    # canonical picture is kept.
    keep_picture: bool


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `start_run` writes is missing or the wrong
    shape (a job made by hand, or by an older version of the code).
    """
    story = job_input.get("story_text")
    entry = job_input.get("entry")
    others = job_input.get("others")
    scenes = job_input.get("scenes")
    inputs = job_input.get("inputs")
    environment_id = job_input.get("environment_id")
    bible_id = job_input.get("story_bible_id")
    if (
        not isinstance(story, str)
        or not isinstance(entry, dict)
        or not isinstance(entry.get("id"), str)
        or not isinstance(entry.get("name"), str)
        or not isinstance(others, list)
        or not isinstance(scenes, list)
        or not isinstance(inputs, dict)
        or not isinstance(environment_id, int)
        or not isinstance(bible_id, int)
    ):
        return None
    return _Input(
        story=story,
        entry=entry,
        others=others,
        scenes=scenes,
        inputs=inputs,
        environment_id=environment_id,
        bible_id=bible_id,
        keep_picture=job_input.get("keep_picture") is True,
    )


class DefineEnvironmentHandler(JobHandler):
    job_type = environment_definitions.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(
        result: llm.ChatResult, discovery_id: str, warnings: list[str]
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, definition)` when it can be stored, else `(why not, None)`.
        What had to be cut from a usable answer is put in `warnings` (replacing earlier ones).
        """
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        found: list[str] = []
        try:
            answer = environment_definition_writer.parse_answer(result.content)
            definition = environment_definition_writer.check_definition(answer, discovery_id, found)
        except ValueError as exc:
            return str(exc), None
        warnings[:] = found
        return None, definition

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
            environment = (
                await environment_library.get_environment(session, read.environment_id)
                if read is not None
                else None
            )
            # The environment's profile as it is now, so the definition keeps to what a person
            # has written. An environment nobody has touched has nothing to keep to.
            card = (
                await environment_definitions.current_profile_card(session, environment)
                if environment is not None
                else None
            )
            picture_prompt = (
                await environment_definitions.current_picture_prompt(session, environment)
                if environment is not None and read is not None and read.keep_picture
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
        if environment is None:
            await self._fail(job_id, _NO_ENVIRONMENT)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = environment_definition_writer.build_request(
            story_text=read.story,
            bible_content=bible_content,
            entry=read.entry,
            others=read.others,
            scenes=read.scenes,
            current_profile=card,
            today_year=date.today().year,
            model=target.model,
            keep_picture=read.keep_picture,
            current_picture_prompt=picture_prompt,
        )
        job_input.update(
            instructions_sha256=llm_call.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
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
            lambda result: self._read(result, discovery_id, warnings),
            timeout_s=REQUEST_TIMEOUT_S,
            correct=True,
        )
        definition: dict[str, Any] | None = outcome.value
        if definition is None:
            await self._fail(
                job_id, f"The definition of {name} could not be written: {outcome.failure}"
            )
            return

        await self._phase(job_id, phases.SAVING_ENVIRONMENT_DEFINITION)
        async with SessionLocal() as session:
            try:
                version = await environment_definitions.save_definition(
                    session,
                    project_id=project_id,
                    discovery_id=discovery_id,
                    environment_id=read.environment_id,
                    definition=definition,
                    job_id=job_id,
                    inputs=read.inputs,
                    keep_picture=read.keep_picture,
                )
            except environment_definitions.EnvironmentDefinitionError as exc:
                await session.rollback()
                await self._fail(job_id, f"The definition of {name} could not be saved: {exc}")
                return
            output = {
                **outcome.record(),
                "content": None,
                "warnings": warnings,
                "environment_id": read.environment_id,
                "version": version.version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the definition is not kept.
                await session.rollback()
                return
            await session.commit()

        # The picture's prompt job was created in the same transaction: pick it up now.
        dispatcher.nudge()
        _logger.info(
            "job %d: environment %d defined as '%s' for project %d, version %d, usage=%s",
            job_id,
            read.environment_id,
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
