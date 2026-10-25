"""The `stage_scene` job: a language model works out where each character of one story scene
stands, and code checks it and stores it as a new version of that scene's staging (PHASE-051,
`Path_ahead.md` Section 46).

`services/scene_staging.start_run` creates the job with the id and version of the StoryBible,
the scene, its definition, its events (`events`, with their ids in `event_ids`), the characters
of the scene (`characters`, in the order the placements must follow), the scene's environment
and its spatial plan, and the `inputs` that are written onto the version (D-3). The job loads
the StoryBible, builds the request, asks the model, checks the answer
(`scene_staging_writer.check_answer`) and saves it (`services/scene_staging.save_staging`) in
the same transaction that marks the job succeeded.

One job per scene, so scenes are staged side by side when the pools allow (`store.create_job`
with `dedupe_key`). The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every
story stage (D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by pressing Stage again.

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
from app.services import discovery, llm_target, scene_staging, scene_staging_writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no scene to stage."
_NO_BIBLE = "The Story Bible this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `start_run` put on the job, checked."""

    scene: dict[str, Any]
    scene_definition: dict[str, Any]
    events: list[dict[str, Any]]
    event_ids: list[str]
    characters: list[dict[str, Any]]
    character_ids: list[str]
    environment: dict[str, Any]
    spatial_plan: dict[str, Any]
    inputs: dict[str, Any]
    bible_id: int


def _is_text_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `start_run` writes is missing or the wrong
    shape (a job made by hand, or by an older version of the code).
    """
    scene = job_input.get("scene")
    scene_definition = job_input.get("scene_definition")
    events = job_input.get("events")
    event_ids = job_input.get("event_ids")
    characters = job_input.get("characters")
    character_ids = job_input.get("character_ids")
    environment = job_input.get("environment")
    spatial_plan = job_input.get("spatial_plan")
    inputs = job_input.get("inputs")
    bible_id = job_input.get("story_bible_id")
    if (
        not isinstance(scene, dict)
        or not isinstance(scene.get("id"), str)
        or not isinstance(scene.get("title"), str)
        or not isinstance(scene_definition, dict)
        or not isinstance(events, list)
        or not _is_text_list(event_ids)
        or not isinstance(characters, list)
        or not _is_text_list(character_ids)
        or not isinstance(environment, dict)
        or not isinstance(spatial_plan, dict)
        or not isinstance(inputs, dict)
        or not isinstance(bible_id, int)
    ):
        return None
    return _Input(
        scene=scene,
        scene_definition=scene_definition,
        events=events,
        event_ids=event_ids,
        characters=characters,
        character_ids=character_ids,
        environment=environment,
        spatial_plan=spatial_plan,
        inputs=inputs,
        bible_id=bible_id,
    )


class StageSceneHandler(JobHandler):
    job_type = scene_staging.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(
        result: llm.ChatResult,
        scene_id: str,
        character_ids: list[str],
        event_ids: list[str],
        spatial_plan: dict[str, Any],
        off_screen: list[str],
        warnings: list[str],
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, content)` when it can be stored, else `(why not, None)`.
        What had to be cut from a usable answer is put in `warnings` (replacing earlier ones).
        """
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        found: list[str] = []
        try:
            answer = scene_staging_writer.parse_answer(result.content)
            content = scene_staging_writer.check_answer(
                answer,
                scene_id,
                character_ids=character_ids,
                event_ids=event_ids,
                spatial_plan=spatial_plan,
                fixed_off_screen=off_screen,
                warnings=found,
            )
        except ValueError as exc:
            return str(exc), None
        warnings[:] = found
        return None, content

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

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = scene_staging_writer.build_request(
            bible_content=bible_content,
            scene=read.scene,
            scene_definition=read.scene_definition,
            events=read.events,
            characters=read.characters,
            environment=read.environment,
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

        warnings: list[str] = []
        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            lambda result: self._read(
                result,
                scene_id,
                read.character_ids,
                read.event_ids,
                read.spatial_plan,
                scene_staging.off_screen_of(read.scene_definition),
                warnings,
            ),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(job_id, f"The scene '{title}' could not be staged: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_SCENE_STAGING)
        async with SessionLocal() as session:
            row = await scene_staging.save_staging(
                session,
                project_id=project_id,
                scene_id=scene_id,
                content=content,
                job_id=job_id,
                inputs=read.inputs,
            )
            output = {
                **outcome.record(),
                "content": None,
                "warnings": warnings,
                "scene_id": scene_id,
                "version": row.version,
                "placements": len(content["placements"]),
                "moves": len(content["moves"]),
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the staging is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: scene '%s' staged for project %d, version %d, %d placements, %d moves, "
            "usage=%s",
            job_id,
            scene_id,
            project_id,
            row.version,
            len(content["placements"]),
            len(content["moves"]),
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
