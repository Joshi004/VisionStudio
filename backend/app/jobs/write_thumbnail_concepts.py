"""The `write_thumbnail_concepts` job: a language model reads the script of the video, a short
description of it, the people who may appear and the places that may appear, and writes four
different thumbnail concepts. Code checks them (`services/thumbnail_concept_writer.py`). The model
reads text only: no frame of a render and no photo is sent (YTF-006).

`services/thumbnail_concepts.start_run` creates the job with a copy of everything it needs,
taken when the button was pressed: `context` (what the model is told about the video, the people
and the places), `looks_of` (who may appear with which look, for the checks), `place_ids` (the
places that may appear, for the checks), `saved_inputs` (the provenance the version will carry)
and the owner's note with the earlier concepts when there is one.

There is one call. The result is saved as the project's next version, in the same transaction
that marks the job succeeded.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold: at most 2 attempts, a refusal never retried, every answer saved the
moment it arrives, and a restart does not run it again (`never_rerun`): the owner asks again with
a fresh job. Logs hold the job id, what each attempt did and its token counts, never the Story
Bible, the script, the note or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import dispatcher, llm_call, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, thumbnails, user_feedback
from app.services import thumbnail_concept_writer as writer
from app.services import thumbnail_concepts as concepts_service
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = concepts_service.JOB_TYPE
# The longest one call may take: the whole script goes in, and the model thinks before it writes.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no description of the video to read."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    context: dict[str, Any]
    looks_of: dict[str, set[str]]
    place_ids: set[str]
    saved_inputs: dict[str, Any]
    feedback: user_feedback.Feedback | None


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    context = job_input.get("context")
    looks = job_input.get("looks_of")
    places = job_input.get("place_ids", [])
    saved_inputs = job_input.get("saved_inputs")
    if (
        not isinstance(context, dict)
        or not isinstance(looks, dict)
        or not isinstance(places, list)
        or not isinstance(saved_inputs, dict)
    ):
        return None
    looks_of: dict[str, set[str]] = {}
    for person, slugs in looks.items():
        if not isinstance(person, str) or not isinstance(slugs, list):
            return None
        looks_of[person] = {slug for slug in slugs if isinstance(slug, str)}
    ok, feedback = user_feedback.read(job_input.get("feedback"))
    if not ok:
        return None
    return _Task(
        context=context,
        looks_of=looks_of,
        place_ids={place for place in places if isinstance(place, str)},
        saved_inputs=saved_inputs,
        feedback=feedback,
    )


def _concepts_reader(looks_of: dict[str, set[str]], place_ids: set[str]) -> llm_call.ReadAnswer:
    """Reads the model's answer: the stored content, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = writer.parse_answer(result.content)
            content = writer.check_content(answer, looks_of, place_ids)
        except ValueError as exc:
            return str(exc), None
        return None, content

    return read


class WriteThumbnailConceptsHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

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
            await session.commit()

        task = _read_task(job_input)
        if project_id is None or task is None:
            await self._fail(job_id, _BAD_INPUT)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = writer.build_request(task.context, model=target.model, feedback=task.feedback)
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            calls_sent={
                "concepts": {
                    "instructions_sha256": llm_call.instructions_sha256(body),
                    "request": body,
                }
            },
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            _concepts_reader(task.looks_of, task.place_ids),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(job_id, f"The thumbnail ideas could not be written: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_THUMBNAIL_CONCEPTS)
        async with SessionLocal() as session:
            row = await concepts_service.save_version(
                session,
                project_id=project_id,
                job_id=job_id,
                inputs=task.saved_inputs,
                content=content,
            )
            output = {
                "calls": {"concepts": outcome.record()},
                "usage": outcome.usage or {},
                "thumbnail_concepts_id": row.id,
                "version": row.version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: thumbnail concepts version %d saved for project %d, usage=%s",
            job_id,
            row.version,
            project_id,
            outcome.usage,
        )
        await self._start_follow_up_picture(job_id, project_id, row.version, job_input)

    @staticmethod
    async def _start_follow_up_picture(
        job_id: int, project_id: int, version: int, job_input: dict[str, Any]
    ) -> None:
        """When the job was started for a YouTube draft (`then_picture`), starts the pictures of
        every concept (the first one finished is chosen). Best effort: a failure never fails the
        concepts (they are stored), and the owner can make a picture in the Thumbnails panel.
        """
        then_picture = job_input.get("then_picture")
        if not isinstance(then_picture, dict):
            return
        try:
            started = await thumbnails.start_follow_up_picture(project_id, version, then_picture)
        except Exception:
            _logger.exception("job %d: the thumbnail picture could not be started", job_id)
            return
        if started:
            dispatcher.nudge()

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        await phase_writer.note(job_id, phase)

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
