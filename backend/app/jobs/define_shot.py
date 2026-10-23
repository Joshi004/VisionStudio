"""The `define_shot` job: a language model defines one planned shot as a cinematic specification,
and code checks it and stores it as a new version of that shot's definition (PHASE-022,
`Path_ahead.md` Sections 26 and 27).

`services/shot_definitions._queue` creates the job with the id and version of the StoryBible, the
scene (`scene`) and its definition (`scene_definition`), the shot's skeleton with its length from
the timeline (`shot`), the shots before and after it, the events it shows (`events`), the speech
heard during it (`speech`), the characters of the scene with their resolved looks (`characters`),
the environment with its resolved state (`environment`) and the `inputs` that are written onto the
version (D-3). The job loads the StoryBible, builds the request, asks the model, checks the answer
and saves it (`services/shot_definitions.save_shot_definition`) in the same transaction that
marks the job succeeded.

Code writes the shot's id, its scene, its duration (`duration`) and the lines of dialogue
(`dialogue`); the model's answer does not carry them (`shot_definition_writer.check_answer`).

When the user wrote a note on the earlier specification (PHASE-038), the job also holds `feedback`
(the text, the number of the version it was about, and that specification): the request gets them
as data blocks, and the version the job saves records the note in its `inputs`.

One job per shot, so shots are defined side by side when the pools allow (`store.create_job`
with `dedupe_key`). The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every
story stage (D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by pressing Define again. An unusable answer is asked for
once more; after that the job fails with the reason and nothing is stored.

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
from app.services import (
    discovery,
    llm_target,
    shot_chain,
    shot_definition_writer,
    shot_definitions,
    user_feedback,
)
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 1200.0

_BAD_INPUT = "This job has no shot to define."
_NO_BIBLE = "The Story Bible this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `_queue` put on the job, checked."""

    scene: dict[str, Any]
    scene_id: str
    shot_id: str
    shot_plan_id: int
    scene_definition: dict[str, Any]
    scene_character_ids: list[str]
    shot: dict[str, Any]
    previous_shot: dict[str, Any] | None
    next_shot: dict[str, Any] | None
    events: list[dict[str, Any]]
    speech: list[dict[str, Any]]
    dialogue: list[dict[str, str]]
    duration: float
    characters: list[dict[str, Any]]
    environment: dict[str, Any]
    inputs: dict[str, Any]
    bible_id: int
    # The user's note on the earlier specification, when this one is made from one (PHASE-038).
    feedback: user_feedback.Feedback | None = None


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `_queue` writes is missing or the wrong shape
    (a job made by hand, or by an older version of the code).
    """
    scene = job_input.get("scene")
    scene_id = job_input.get("scene_id")
    shot_id = job_input.get("shot_id")
    shot_plan_id = job_input.get("shot_plan_id")
    scene_definition = job_input.get("scene_definition")
    scene_character_ids = job_input.get("scene_character_ids")
    shot = job_input.get("shot")
    previous_shot = job_input.get("previous_shot")
    next_shot = job_input.get("next_shot")
    events = job_input.get("events")
    speech = job_input.get("speech")
    dialogue = job_input.get("dialogue")
    duration = job_input.get("duration")
    characters = job_input.get("characters")
    environment = job_input.get("environment")
    inputs = job_input.get("inputs")
    bible_id = job_input.get("story_bible_id")
    feedback_ok, feedback = user_feedback.read(job_input.get("feedback"))
    if (
        not feedback_ok
        or not isinstance(scene, dict)
        or not isinstance(scene_id, str)
        or not isinstance(shot_id, str)
        or not isinstance(shot_plan_id, int)
        or not isinstance(scene_definition, dict)
        or not isinstance(scene_character_ids, list)
        or not all(isinstance(item, str) for item in scene_character_ids)
        or not isinstance(shot, dict)
        or not (previous_shot is None or isinstance(previous_shot, dict))
        or not (next_shot is None or isinstance(next_shot, dict))
        or not isinstance(events, list)
        or not isinstance(speech, list)
        or not isinstance(dialogue, list)
        or not all(
            isinstance(line, dict)
            and all(isinstance(line.get(key), str) for key in ("unit_id", "speaker_id", "text"))
            for line in dialogue
        )
        or not _is_number(duration)
        or not isinstance(characters, list)
        or not isinstance(environment, dict)
        or not isinstance(inputs, dict)
        or not isinstance(bible_id, int)
    ):
        return None
    return _Input(
        scene=scene,
        scene_id=scene_id,
        shot_id=shot_id,
        shot_plan_id=shot_plan_id,
        scene_definition=scene_definition,
        scene_character_ids=scene_character_ids,
        shot=shot,
        previous_shot=previous_shot,
        next_shot=next_shot,
        events=events,
        speech=speech,
        dialogue=dialogue,
        duration=float(duration),
        characters=characters,
        environment=environment,
        inputs=inputs,
        bible_id=bible_id,
        feedback=feedback,
    )


class DefineShotHandler(JobHandler):
    job_type = shot_definitions.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(result: llm.ChatResult, read: _Input) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, content)` when it can be stored, else `(why not, None)`."""
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = shot_definition_writer.parse_answer(result.content)
            return None, shot_definition_writer.check_answer(
                answer,
                scene_id=read.scene_id,
                shot_id=read.shot_id,
                duration=read.duration,
                scene_character_ids=read.scene_character_ids,
                dialogue=read.dialogue,
                exchange=read.shot.get("rapid_exchange") is True,
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
        shot_id = read.shot_id

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = shot_definition_writer.build_request(
            bible_content=bible_content,
            scene=read.scene,
            scene_definition=read.scene_definition,
            shot=read.shot,
            previous_shot=read.previous_shot,
            next_shot=read.next_shot,
            events=read.events,
            speech=read.speech,
            characters=read.characters,
            environment=read.environment,
            model=target.model,
            feedback=read.feedback,
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
            lambda result: self._read(result, read),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(
                job_id,
                f"The shot '{shot_id}' of the scene '{read.scene['title']}' could not be "
                f"defined: {outcome.failure}",
            )
            return

        await self._phase(job_id, phases.SAVING_SHOT_DEFINITION)
        async with SessionLocal() as session:
            row = await shot_definitions.save_shot_definition(
                session,
                project_id=project_id,
                scene_id=read.scene_id,
                shot_id=shot_id,
                shot_plan_id=read.shot_plan_id,
                content=content,
                job_id=job_id,
                inputs=read.inputs,
            )
            output = {
                **outcome.record(),
                "content": None,
                "scene_id": read.scene_id,
                "shot_id": shot_id,
                "version": row.version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the specification is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: shot '%s' of scene '%s' defined for project %d, version %d, usage=%s",
            job_id,
            shot_id,
            read.scene_id,
            project_id,
            row.version,
            outcome.usage,
        )

        # What follows a stored definition (references, generation request, prompt, continuity)
        # is separate: a failure there must not fail a job that has already succeeded.
        await shot_chain.after_definition_saved(project_id, read.scene_id, shot_id)

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
