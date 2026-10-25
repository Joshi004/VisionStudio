"""The `extract_events` job: a language model lists what happens in one story scene, and code
checks it and stores it as a new version of that scene's events (PHASE-015, `Path_ahead.md`
Section 17).

`services/scene_events.start_run` creates the job with the id and version of the StoryBible, the
scene to extract (`scene`, with its exact text), the scene's definition (`scene_definition`),
the definitions of the characters the scene chose (`scene_characters`), the list of all the
story's characters (`characters`) and the `inputs` that are written onto the version (D-3). The
job loads the StoryBible, builds the request, asks the model, checks the answer (the shape, the
speakers, and that the speech comes from the scene's text, in order) and saves it
(`services/scene_events.save_events`) in the same transaction that marks the job succeeded.

One job per scene, so scenes are extracted side by side when the pools allow
(`store.create_job` with `dedupe_key`). The model is the **story role**
(`llm_target.STORY_MODEL_KEY`), like every story stage (D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by pressing Extract again. An answer whose speech cannot
be found in the scene is unusable, so it is asked for once more; after that the job fails with
the reason and nothing is stored.

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
from app.services import discovery, event_extraction_writer, llm_target, scene_events
from app.services.llm_target import STORY_MODEL_KEY
from app.services.projects import SPEECH_BOTH, SPEECH_MODES

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no scene to extract."
_NO_BIBLE = "The Story Bible this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `start_run` put on the job, checked."""

    scene: dict[str, Any]
    scene_definition: dict[str, Any]
    scene_characters: list[dict[str, Any]]
    characters: list[dict[str, Any]]
    inputs: dict[str, Any]
    bible_id: int
    speech_mode: str


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `start_run` writes is missing or the wrong
    shape (a job made by hand, or by an older version of the code).
    """
    scene = job_input.get("scene")
    scene_definition = job_input.get("scene_definition")
    scene_characters = job_input.get("scene_characters")
    characters = job_input.get("characters")
    inputs = job_input.get("inputs")
    bible_id = job_input.get("story_bible_id")
    # A job queued before PHASE-049 has no speech mode: it is a `both` project.
    speech_mode = job_input.get("speech_mode", SPEECH_BOTH)
    if (
        speech_mode not in SPEECH_MODES
        or not isinstance(scene, dict)
        or not isinstance(scene.get("id"), str)
        or not isinstance(scene.get("title"), str)
        or not isinstance(scene.get("text"), str)
        or not isinstance(scene_definition, dict)
        or not isinstance(scene_characters, list)
        or not isinstance(characters, list)
        or not isinstance(inputs, dict)
        or not isinstance(bible_id, int)
    ):
        return None
    return _Input(
        scene=scene,
        scene_definition=scene_definition,
        scene_characters=scene_characters,
        characters=characters,
        inputs=inputs,
        bible_id=bible_id,
        speech_mode=speech_mode,
    )


def _ids(items: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in items if isinstance(item.get("id"), str)}


class ExtractEventsHandler(JobHandler):
    job_type = scene_events.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(
        result: llm.ChatResult,
        scene_id: str,
        scene_text: str,
        character_ids: set[str],
        speech_mode: str,
        warnings: list[str],
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, content)` when it can be stored, else `(why not, None)`.
        What had to be cut from a usable answer is put in `warnings` (replacing earlier ones).
        """
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        found: list[str] = []
        try:
            answer = event_extraction_writer.parse_answer(result.content)
            content = event_extraction_writer.check_answer(
                answer, scene_id, scene_text, character_ids, speech_mode, found
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
        scene_text = read.scene["text"]
        character_ids = _ids(read.characters)
        speech_mode = read.speech_mode

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = event_extraction_writer.build_request(
            bible_content=bible_content,
            scene=read.scene,
            scene_definition=read.scene_definition,
            scene_characters=read.scene_characters,
            all_characters=read.characters,
            model=target.model,
            speech_mode=speech_mode,
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
                result, scene_id, scene_text, character_ids, speech_mode, warnings
            ),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(
                job_id,
                f"The events of the scene '{title}' could not be extracted: {outcome.failure}",
            )
            return

        await self._phase(job_id, phases.SAVING_SCENE_EVENTS)
        async with SessionLocal() as session:
            row = await scene_events.save_events(
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
                "events": len(content["events"]),
                "uncovered": len(content["uncovered"]),
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the events are not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: events of scene '%s' extracted for project %d, version %d, %d events, "
            "%d uncovered, usage=%s",
            job_id,
            scene_id,
            project_id,
            row.version,
            len(content["events"]),
            len(content["uncovered"]),
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
