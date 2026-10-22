"""The `compile_shot_prompt` job: a language model writes the creative pieces of one shot's final
H3 prompt, code puts the fixed parts around them and checks the result, and the checked prompt is
stored as a new version of that shot's prompt (PHASE-026, `Path_ahead.md` Section 30).

`services/shot_prompts._queue` creates the job with the id and version of the StoryBible, the id
and content of the shot's generation request (`generation_request`: the route, the ordered
pictures and the ordered dialogue audios), the scene (`scene`), the shot's stored specification
(`shot_definition`), the characters it shows or hears (`characters`), the environment
(`environment`) and the `inputs` that are written onto the version (D-3). The job loads the
StoryBible, works out the labels (`shot_prompt_writer.layout`), builds the request, asks the model
and saves the prompt (`services/shot_prompts.save_shot_prompt`) in the same transaction that
marks the job succeeded.

Code writes the headings, the label definitions, the retention lines, the audio lines, the start
time of each line, the sentences about who is not speaking, and `non_diegetic_music: N/A`
(D-10); the model's answer does not carry them (`shot_prompt_writer.check_answer`).

One job per shot, so shots are compiled side by side when the pools allow (`store.create_job`
with `dedupe_key`). The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every
story stage (D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by pressing Compile again. An unusable answer, among it a
prompt that fails a check, is asked for once more; after that the job fails with the reason and
nothing is stored.

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
from app.services import discovery, llm_target, shot_prompt_writer, shot_prompts
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 1200.0

_BAD_INPUT = "This job has no shot to compile."
_NO_BIBLE = "The Story Bible this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `_queue` put on the job, checked."""

    scene: dict[str, Any]
    scene_id: str
    shot_id: str
    generation_request_id: int
    shot_layout: shot_prompt_writer.Layout
    shot_definition: dict[str, Any]
    characters: list[dict[str, Any]]
    environment: dict[str, Any]
    inputs: dict[str, Any]
    bible_id: int


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `_queue` writes is missing or the wrong shape
    (a job made by hand, or by an older version of the code).
    """
    scene = job_input.get("scene")
    scene_id = job_input.get("scene_id")
    shot_id = job_input.get("shot_id")
    request_id = job_input.get("generation_request_id")
    request = job_input.get("generation_request")
    shot_definition = job_input.get("shot_definition")
    characters = job_input.get("characters")
    environment = job_input.get("environment")
    inputs = job_input.get("inputs")
    bible_id = job_input.get("story_bible_id")
    if (
        not isinstance(scene, dict)
        or not isinstance(scene_id, str)
        or not isinstance(shot_id, str)
        or not isinstance(request_id, int)
        or not isinstance(request, dict)
        or not isinstance(shot_definition, dict)
        or not isinstance(characters, list)
        or not isinstance(environment, dict)
        or not isinstance(inputs, dict)
        or not isinstance(bible_id, int)
    ):
        return None
    try:
        shot_layout = shot_prompt_writer.layout(request)
    except shot_prompt_writer.ShotPromptError:
        return None
    return _Input(
        scene=scene,
        scene_id=scene_id,
        shot_id=shot_id,
        generation_request_id=request_id,
        shot_layout=shot_layout,
        shot_definition=shot_definition,
        characters=characters,
        environment=environment,
        inputs=inputs,
        bible_id=bible_id,
    )


class CompileShotPromptHandler(JobHandler):
    job_type = shot_prompts.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(result: llm.ChatResult, read: _Input) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, content)` when it can be stored, else `(why not, None)`."""
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = shot_prompt_writer.parse_answer(result.content)
            return None, shot_prompt_writer.check_answer(answer, read.shot_layout)
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
        body = shot_prompt_writer.build_request(
            shot_layout=read.shot_layout,
            bible_content=bible_content,
            scene=read.scene,
            shot_definition=read.shot_definition,
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
                f"The prompt of the shot '{shot_id}' of the scene '{read.scene['title']}' could "
                f"not be compiled: {outcome.failure}",
            )
            return

        await self._phase(job_id, phases.SAVING_SHOT_PROMPT)
        async with SessionLocal() as session:
            row = await shot_prompts.save_shot_prompt(
                session,
                project_id=project_id,
                scene_id=read.scene_id,
                shot_id=shot_id,
                generation_request_id=read.generation_request_id,
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
                "format": content["format"],
                "warnings": len(content["warnings"]),
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the prompt is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: prompt of shot '%s' of scene '%s' compiled for project %d, version %d, "
            "usage=%s",
            job_id,
            shot_id,
            read.scene_id,
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
