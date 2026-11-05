"""The `write_thumbnail_concepts` job: a vision model reads the description of the video, the
people who may appear and, when the video has been rendered, a few frames of it, and writes four
different thumbnail concepts. Code checks them (`services/thumbnail_concept_writer.py`).

`services/thumbnail_concepts.start_run` creates the job with a copy of everything it needs,
taken when the button was pressed: `context` (what the model is told about the video and the
people), `looks_of` (who may appear with which look, for the checks), `render_id` (the render the
frames are taken from, or None), `saved_inputs` (the provenance the version will carry) and the
owner's note with the earlier concepts when there is one.

There is one call. Frames are taken from the render with ffmpeg and sent as small JPEGs; a frame
that cannot be taken is left out, and with no frame at all the call is made from the text alone.
The job record keeps the request without the frames' bytes and says which frame numbers were
used. The result is saved as the project's next version, in the same transaction that marks the
job succeeded.

The model is the Bitdeer vision one (`llm_target.VISION_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold: at most 2 attempts, a refusal never retried, every answer saved the
moment it arrives, and a restart does not run it again (`never_rerun`): the owner asks again with
a fresh job. Logs hold the job id, what each attempt did and its token counts, never the Story
Bible, the note, the frames or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import StoryRender
from app.db.session import SessionLocal
from app.jobs import llm_call, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import ffmpeg, llm_target, thumbnail_compose, user_feedback
from app.services import thumbnail_concept_writer as writer
from app.services import thumbnail_concepts as concepts_service
from app.services.llm_target import VISION_MODEL_KEY
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = concepts_service.JOB_TYPE
# A vision model takes longer than a text one, and the frames are an upload.
REQUEST_TIMEOUT_S: Final = 300.0

# Where in the video the frames are taken, as shares of its length.
FRAME_POSITIONS: Final[tuple[float, ...]] = (0.15, 0.35, 0.55, 0.75)

_BAD_INPUT = "This job has no description of the video to read."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    context: dict[str, Any]
    looks_of: dict[str, set[str]]
    render_id: int | None
    saved_inputs: dict[str, Any]
    feedback: user_feedback.Feedback | None


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    context = job_input.get("context")
    looks = job_input.get("looks_of")
    render_id = job_input.get("render_id")
    saved_inputs = job_input.get("saved_inputs")
    if (
        not isinstance(context, dict)
        or not isinstance(looks, dict)
        or not isinstance(saved_inputs, dict)
        or not (
            render_id is None or (isinstance(render_id, int) and not isinstance(render_id, bool))
        )
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
        render_id=render_id,
        saved_inputs=saved_inputs,
        feedback=feedback,
    )


def _concepts_reader(looks_of: dict[str, set[str]]) -> llm_call.ReadAnswer:
    """Reads the model's answer: the stored content, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = writer.parse_answer(result.content)
            content = writer.check_content(answer, looks_of)
        except ValueError as exc:
            return str(exc), None
        return None, content

    return read


async def _frames(render_id: int | None) -> tuple[list[bytes], list[int]]:
    """Small JPEGs of the render's frames, and the frame numbers they are. Best effort: a frame
    that cannot be taken is left out, and a render that is gone gives none.
    """
    if render_id is None:
        return [], []
    async with SessionLocal() as session:
        render = await session.get(StoryRender, render_id)
        relative_path = render.path if render is not None else None
        frame_count = render.frame_count if render is not None else None
        await session.commit()
    if relative_path is None or not frame_count or frame_count < len(FRAME_POSITIONS):
        return [], []
    storage = get_storage()
    try:
        video = storage.get_path(relative_path)
    except StorageError:
        return [], []
    if not video.is_file():
        return [], []

    jpegs: list[bytes] = []
    numbers: list[int] = []
    for share in FRAME_POSITIONS:
        number = min(frame_count - 1, int(frame_count * share))
        temp = storage.new_temp_path("png")
        try:
            problem = await ffmpeg.extract_frame(video, number, temp)
            if problem is not None or not temp.is_file():
                _logger.info(
                    "render %d: frame %d could not be taken: %s", render_id, number, problem
                )
                continue
            jpegs.append(await thumbnail_compose.frame_jpeg(temp))
            numbers.append(number)
        except thumbnail_compose.ThumbnailPictureError as exc:
            _logger.info("render %d: frame %d could not be used: %s", render_id, number, exc)
        finally:
            storage.discard(temp)
    return jpegs, numbers


class WriteThumbnailConceptsHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = VISION_MODEL_KEY

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            project_id = job.project_id
            target = await llm_target.resolve(session, VISION_MODEL_KEY)
            await session.commit()

        task = _read_task(job_input)
        if project_id is None or task is None:
            await self._fail(job_id, _BAD_INPUT)
            return

        await self._phase(job_id, phases.TAKING_FRAMES)
        jpegs, frame_numbers = await _frames(task.render_id)

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = writer.build_request(task.context, jpegs, model=target.model, feedback=task.feedback)
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            frame_numbers=frame_numbers,
            calls_sent={
                "concepts": {
                    "instructions_sha256": llm_call.instructions_sha256(body),
                    "request": writer.without_frames(body),
                }
            },
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            _concepts_reader(task.looks_of),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(job_id, f"The thumbnail ideas could not be written: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_THUMBNAIL_CONCEPTS)
        # When no frame could be taken, the version must not say it was written from the render.
        saved_inputs = task.saved_inputs
        if not jpegs:
            saved_inputs = {
                **saved_inputs,
                "artifacts": [
                    artifact
                    for artifact in saved_inputs.get("artifacts", [])
                    if artifact.get("kind") != concepts_service.STORY_RENDER_KIND
                ],
            }
        async with SessionLocal() as session:
            row = await concepts_service.save_version(
                session,
                project_id=project_id,
                job_id=job_id,
                inputs=saved_inputs,
                content=content,
            )
            output = {
                "calls": {"concepts": outcome.record()},
                "usage": outcome.usage or {},
                "thumbnail_concepts_id": row.id,
                "version": row.version,
                "frames_used": len(jpegs),
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: thumbnail concepts version %d saved for project %d, frames=%d, usage=%s",
            job_id,
            row.version,
            project_id,
            len(jpegs),
            outcome.usage,
        )

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        await phase_writer.note(job_id, phase)

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
