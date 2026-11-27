"""The `write_youtube_draft` job: a language model writes the title, the description, the
hashtags and the tags, and code checks them (YT-003, `YouTube_publish_phases.md` §4.5; the two
declarations are not drafted since YTF-002).

`services/youtube_draft.start_run` creates the job with a copy of everything it needs, taken when
the button was pressed: `render_id` (the finished render the draft is for) or `render_job_id` (the
render still being made, when the draft was started with it, YTF-004), `context` (what the model is
told about the video), `saved_inputs` (the provenance the version will carry) and the owner's note
with the earlier draft when there is one.

The first call writes the title, the description, the hashtags and the tags. For an explainer
that is long enough (`chapter_lines` on the job input), a second call chooses the chapters from
the numbered spoken sentences (`services/youtube_chapters_writer.py`); code turns the sentence
numbers into exact times. A chapters call that fails does not fail the job: the draft is saved
without chapters and `output.chapters_failure` says why. Code then adds the Chapters block and
the Sources section to the description.

The request of the first call is built in `services/youtube_draft_writer.py`, and its answer is
checked there: an answer that breaks a check (a title over 100 characters, a hashtag with a space,
a description over YouTube's limit) makes the answer unusable, and the corrected retry of
`jobs/llm_call.py` tells the model what was wrong. The result is saved as the project's next
version, in the same transaction that marks the job succeeded.

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
from app.jobs import llm_call, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, user_feedback, youtube_draft
from app.services import youtube_chapters_writer as chapters_writer
from app.services import youtube_draft_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = youtube_draft.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no description of the video to read."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    # The finished render the draft is for, or None when it is for a render still being made
    # (`saved_inputs.render_job_id` names that render's job).
    render_id: int | None
    context: dict[str, Any]
    saved_inputs: dict[str, Any]
    feedback: user_feedback.Feedback | None
    # The accepted evidence for the Sources section (`youtube_sources`). Empty for a job queued
    # before the section existed, or for a project without evidence.
    sources: list[Any]
    # The numbered spoken sentences the chapters are chosen from, the video's length, and the
    # titles of the chapters of the draft a note is about. Empty for a video with no chapters
    # (a story, a Short, a short video) and for a job queued before chapters existed.
    chapter_lines: list[dict[str, Any]]
    duration_s: float | None
    previous_chapters: list[str]


def _is_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read_chapter_lines(value: object) -> list[dict[str, Any]]:
    """The job's `chapter_lines` as they are, or `[]` when they are missing or not well formed
    (the draft is then written without chapters)."""
    if not isinstance(value, list):
        return []
    for position, line in enumerate(value, start=1):
        if (
            not isinstance(line, dict)
            or line.get("n") != position
            or not _is_id(line.get("start_ms"))
            or not isinstance(line.get("text"), str)
            or not isinstance(line.get("clip"), bool)
        ):
            return []
    return value


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    render_id = job_input.get("render_id")
    render_job_id = job_input.get("render_job_id")
    context = job_input.get("context")
    saved_inputs = job_input.get("saved_inputs")
    if not isinstance(context, dict) or not isinstance(saved_inputs, dict):
        return None
    # Exactly one of the two says which render the draft is for, and it is a whole number.
    if render_id is not None and render_job_id is None:
        if not _is_id(render_id):
            return None
    elif render_id is not None or not _is_id(render_job_id):
        return None
    ok, feedback = user_feedback.read(job_input.get("feedback"))
    if not ok:
        return None
    sources = job_input.get("sources", [])
    if not isinstance(sources, list):
        return None
    duration = job_input.get("chapter_duration_s")
    chapter_lines = _read_chapter_lines(job_input.get("chapter_lines"))
    if isinstance(duration, bool) or not isinstance(duration, int | float) or duration <= 0:
        chapter_lines, duration = [], None
    earlier = job_input.get("previous_chapters")
    previous_chapters = (
        [title for title in earlier if isinstance(title, str)] if isinstance(earlier, list) else []
    )
    return _Task(
        render_id=render_id,
        context=context,
        saved_inputs=saved_inputs,
        feedback=feedback,
        sources=sources,
        chapter_lines=chapter_lines,
        duration_s=float(duration) if duration is not None else None,
        previous_chapters=previous_chapters,
    )


def _draft_reader() -> llm_call.ReadAnswer:
    """Reads the model's answer: the stored content, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = writer.parse_answer(result.content)
            content = writer.check_content(answer, min_hashtags=writer.HASHTAGS_MIN_AI)
        except ValueError as exc:
            return str(exc), None
        return None, content

    return read


def _chapters_reader(lines: list[dict[str, Any]], duration_s: float) -> llm_call.ReadAnswer:
    """Reads the model's chapters: the stored list, or why the answer cannot be used."""

    def read(result: llm.ChatResult) -> tuple[str | None, list[dict[str, Any]] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = chapters_writer.parse_answer(result.content)
            chapters = chapters_writer.check_chapters(answer, lines, duration_s)
        except ValueError as exc:
            return str(exc), None
        return None, chapters

    return read


class WriteYouTubeDraftHandler(JobHandler):
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
        body = writer.build_request(
            task.context, model=target.model, feedback=task.feedback, sources=task.sources
        )
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            calls_sent={
                "draft": {
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
            _draft_reader(),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(job_id, f"The YouTube draft could not be written: {outcome.failure}")
            return
        calls: dict[str, Any] = {"draft": outcome.record()}
        usage: dict[str, int] = dict(outcome.usage or {})
        chapters_failure: str | None = None
        if task.chapter_lines and task.duration_s is not None:
            chapters_outcome = await self._ask_chapters(
                job_id, target, task, task.duration_s, job_input, calls
            )
            calls["chapters"] = chapters_outcome.record()
            for key, count in (chapters_outcome.usage or {}).items():
                usage[key] = usage.get(key, 0) + count
            if chapters_outcome.value is not None:
                content = writer.with_chapters(
                    content, chapters_writer.block(chapters_outcome.value, task.duration_s)
                )
            else:
                # The draft is still good: it goes out without chapters, and the owner can ask
                # again. The reason is on the job.
                chapters_failure = chapters_outcome.failure
        try:
            content = writer.with_sources(content, task.sources)
        except ValueError as exc:
            await self._fail(job_id, f"The sources could not be added to the description: {exc}")
            return

        await self._phase(job_id, phases.SAVING_YOUTUBE_DRAFT)
        async with SessionLocal() as session:
            row = await youtube_draft.save_version(
                session,
                project_id=project_id,
                job_id=job_id,
                render_id=task.render_id,
                inputs=task.saved_inputs,
                content=content,
            )
            output = {
                "calls": calls,
                "usage": usage,
                "youtube_draft_id": row.id,
                "version": row.version,
                "chapters_failure": chapters_failure,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: YouTube draft version %d saved for project %d, usage=%s",
            job_id,
            row.version,
            project_id,
            usage,
        )

    async def _ask_chapters(
        self,
        job_id: int,
        target: llm_target.LlmTarget,
        task: _Task,
        duration_s: float,
        job_input: dict[str, Any],
        calls: dict[str, Any],
    ) -> llm_call.Outcome:
        """The second call: the chapters. Its request is recorded on the job before it is sent,
        and the paid answer of the first call is kept on the job while this one runs."""
        body = chapters_writer.build_request(
            task.chapter_lines,
            duration_s,
            model=target.model,
            feedback=task.feedback,
            previous_titles=task.previous_chapters,
        )
        sent = dict(job_input["calls_sent"])
        sent["chapters"] = {
            "instructions_sha256": llm_call.instructions_sha256(body),
            "request": body,
        }
        job_input["calls_sent"] = sent
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)
        return await llm_call.ask_model(
            job_id,
            target,
            body,
            _chapters_reader(task.chapter_lines, duration_s),
            timeout_s=REQUEST_TIMEOUT_S,
            keep={"calls": dict(calls)},
        )

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        await phase_writer.note(job_id, phase)

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
