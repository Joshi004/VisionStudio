"""The `define_scene` job: a language model writes one story scene's definition, and code checks
it and stores it as a new version of that scene (PHASE-014, `Path_ahead.md` Section 16).

`services/scene_definitions.start_run` creates the job with a copy of the saved story and its
hash, the id and version of the StoryBible, the scene to define (`scene`) and its neighbours'
summaries (`previous`, `next`), every character and environment definition the model is shown
(`characters`, `environments`), a record of each of them (`shown`) and the `inputs` that are
written onto the version (D-3). The job loads the StoryBible, builds the request, asks the
model, checks the answer (the chosen environment and characters must be among the story's), and
saves it (`services/scene_definitions.save_definition`) in the same transaction that marks the
job succeeded.

One job per scene, so scenes are defined side by side when the pools allow (`store.create_job`
with `dedupe_key`). The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every
story stage (D-12).

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
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import discovery, llm_target, scene_definition_writer, scene_definitions
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no scene to define."
_NO_BIBLE = "The Story Bible this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `start_run` put on the job, checked."""

    story: str
    scene: dict[str, Any]
    previous: dict[str, Any] | None
    next_: dict[str, Any] | None
    characters: list[dict[str, Any]]
    environments: list[dict[str, Any]]
    shown: list[dict[str, Any]]
    inputs: dict[str, Any]
    bible_id: int


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `start_run` writes is missing or the wrong
    shape (a job made by hand, or by an older version of the code).
    """
    story = job_input.get("story_text")
    scene = job_input.get("scene")
    previous = job_input.get("previous")
    next_ = job_input.get("next")
    characters = job_input.get("characters")
    environments = job_input.get("environments")
    shown = job_input.get("shown")
    inputs = job_input.get("inputs")
    bible_id = job_input.get("story_bible_id")
    if (
        not isinstance(story, str)
        or not isinstance(scene, dict)
        or not isinstance(scene.get("id"), str)
        or not isinstance(scene.get("title"), str)
        or not (previous is None or isinstance(previous, dict))
        or not (next_ is None or isinstance(next_, dict))
        or not isinstance(characters, list)
        or not isinstance(environments, list)
        or not isinstance(shown, list)
        or not isinstance(inputs, dict)
        or not isinstance(bible_id, int)
    ):
        return None
    return _Input(
        story=story,
        scene=scene,
        previous=previous,
        next_=next_,
        characters=characters,
        environments=environments,
        shown=shown,
        inputs=inputs,
        bible_id=bible_id,
    )


def _ids(items: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in items if isinstance(item.get("id"), str)}


class DefineSceneHandler(JobHandler):
    job_type = scene_definitions.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(
        result: llm.ChatResult,
        scene_id: str,
        character_ids: set[str],
        environment_ids: set[str],
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, definition)` when it can be stored, else `(why not, None)`."""
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = scene_definition_writer.parse_answer(result.content)
            return None, scene_definition_writer.check_definition(
                answer, scene_id, character_ids, environment_ids
            )
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
            bible_content = bible.content if bible is not None else None
            await session.commit()

        if project_id is None or read is None:
            await self._fail(job_id, _BAD_INPUT)
            return
        if bible_content is None:
            await self._fail(job_id, _NO_BIBLE)
            return
        scene_id = read.scene["id"]
        title = read.scene["title"]
        character_ids = _ids(read.characters)
        environment_ids = _ids(read.environments)

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = scene_definition_writer.build_request(
            story_text=read.story,
            bible_content=bible_content,
            scene=read.scene,
            previous=read.previous,
            next_=read.next_,
            characters=read.characters,
            environments=read.environments,
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
            lambda result: self._read(result, scene_id, character_ids, environment_ids),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        definition: dict[str, Any] | None = outcome.value
        if definition is None:
            await self._fail(
                job_id,
                f"The definition of the scene '{title}' could not be written: {outcome.failure}",
            )
            return

        await self._phase(job_id, phases.SAVING_SCENE_DEFINITION)
        async with SessionLocal() as session:
            row = await scene_definitions.save_definition(
                session,
                project_id=project_id,
                scene_id=scene_id,
                definition=definition,
                job_id=job_id,
                inputs=read.inputs,
                shown=read.shown,
            )
            output = {
                **outcome.record(),
                "content": None,
                "scene_id": scene_id,
                "version": row.version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the definition is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: scene '%s' defined for project %d, version %d, usage=%s",
            job_id,
            scene_id,
            project_id,
            row.version,
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
