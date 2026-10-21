"""The `plan_shots` job: a language model plans the shots of one story scene, and code checks it
and stores it as a new version of that scene's shot plan (PHASE-020, `Path_ahead.md` Sections 22
and 25).

`services/shot_plans.start_run` creates the job with the id and version of the StoryBible, the
scene (`scene`), its definition (`scene_definition`), the definitions of the characters it chose
(`scene_characters`) and of its environment (`environment`), its events (`events`), its speech
units with the measured length of their audio (`units`), the planning target range and the
`inputs` that are written onto the version (D-3). The job loads the StoryBible, builds the
request, asks the model, checks the answer (the shape of each shot, that every event is shown in
story order, and that every speech unit is carried by the shots that show its event) and saves it
(`services/shot_plans.save_shot_plan`) in the same transaction that marks the job succeeded.

One job per scene, so scenes are planned side by side when the pools allow (`store.create_job`
with `dedupe_key`). The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every
story stage (D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by pressing Plan again. An answer that leaves an event
unshown or a unit uncarried is unusable, so it is asked for once more; after that the job fails
with the reason and nothing is stored.

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
from app.services import discovery, llm_target, shot_planning_writer, shot_plans
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no scene to plan."
_NO_BIBLE = "The Story Bible this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `start_run` put on the job, checked."""

    scene: dict[str, Any]
    scene_definition: dict[str, Any]
    scene_characters: list[dict[str, Any]]
    environment: dict[str, Any]
    events: list[dict[str, Any]]
    units: list[dict[str, Any]]
    target_min_seconds: int
    target_max_seconds: int
    inputs: dict[str, Any]
    bible_id: int


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `start_run` writes is missing or the wrong
    shape (a job made by hand, or by an older version of the code).
    """
    scene = job_input.get("scene")
    scene_definition = job_input.get("scene_definition")
    scene_characters = job_input.get("scene_characters")
    environment = job_input.get("environment")
    events = job_input.get("events")
    units = job_input.get("units")
    target_min = job_input.get("target_min_seconds")
    target_max = job_input.get("target_max_seconds")
    inputs = job_input.get("inputs")
    bible_id = job_input.get("story_bible_id")
    if (
        not isinstance(scene, dict)
        or not isinstance(scene.get("id"), str)
        or not isinstance(scene.get("title"), str)
        or not isinstance(scene_definition, dict)
        or not isinstance(scene_characters, list)
        or not isinstance(environment, dict)
        or not isinstance(events, list)
        or not events
        or not all(isinstance(event, dict) and isinstance(event.get("id"), str) for event in events)
        or not isinstance(units, list)
        or not all(
            isinstance(unit, dict)
            and isinstance(unit.get("id"), str)
            and isinstance(unit.get("event_id"), str)
            and unit.get("kind") in ("narration", "dialogue")
            for unit in units
        )
        or not isinstance(target_min, int)
        or not isinstance(target_max, int)
        or not isinstance(inputs, dict)
        or not isinstance(bible_id, int)
    ):
        return None
    return _Input(
        scene=scene,
        scene_definition=scene_definition,
        scene_characters=scene_characters,
        environment=environment,
        events=events,
        units=units,
        target_min_seconds=target_min,
        target_max_seconds=target_max,
        inputs=inputs,
        bible_id=bible_id,
    )


class PlanShotsHandler(JobHandler):
    job_type = shot_plans.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(
        result: llm.ChatResult,
        scene_id: str,
        events: list[dict[str, Any]],
        units: list[dict[str, Any]],
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, content)` when it can be stored, else `(why not, None)`."""
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = shot_planning_writer.parse_answer(result.content)
            return None, shot_planning_writer.check_answer(answer, scene_id, events, units)
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

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = shot_planning_writer.build_request(
            bible_content=bible_content,
            scene=read.scene,
            scene_definition=read.scene_definition,
            scene_characters=read.scene_characters,
            environment=read.environment,
            events=read.events,
            units=read.units,
            target_min_seconds=read.target_min_seconds,
            target_max_seconds=read.target_max_seconds,
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
            lambda result: self._read(result, scene_id, read.events, read.units),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(
                job_id,
                f"The shots of the scene '{title}' could not be planned: {outcome.failure}",
            )
            return

        await self._phase(job_id, phases.SAVING_SHOT_PLAN)
        async with SessionLocal() as session:
            row = await shot_plans.save_shot_plan(
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
                "scene_id": scene_id,
                "version": row.version,
                "shots": len(content["shots"]),
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the plan is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: shots of scene '%s' planned for project %d, version %d, %d shots, usage=%s",
            job_id,
            scene_id,
            project_id,
            row.version,
            len(content["shots"]),
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
