"""The `write_music_theme_prompt` job: a language model writes the ACE-Step fields of one music
theme, or the captions of its emotional versions (MUSIC-007, `Music_implementation_phases.md`
Section 4.2, MD-6).

`services/music_themes` creates the job with a copy of everything it needs, taken when the button
was pressed (the context the model reads, the length and number of recordings, the GPU partition
and the seeds). `input.requested` says what to do:

- `theme`: one call writes the fields of the theme's canonical recording. The result is saved as
  the next `music_theme` row of the theme, and its candidate recordings (one `lab_music` run
  each) are queued in the same transaction that marks this job succeeded.
- `versions`: one call writes a caption for each emotion that is missing, from the fields of the
  chosen candidate (`input.canonical`). A recording of each (a `lab_music` run) is queued the
  same way.

Each call builds its request in `services/music_theme_writer.py`, asks the model and checks the
answer there. The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the
rules in `jobs/llm_call.py` hold: at most 2 attempts, a refusal never retried, every answer saved
the moment it arrives, and a restart never re-runs it (`never_rerun`): the owner asks again with a
fresh job. It is a local-style job: everything happens in `start`. Logs hold the job id, what each
attempt did and its token counts, never the story or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import dispatcher, llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, music_themes
from app.services import music_theme_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = music_themes.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no theme to write."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    requested: str
    theme_id: str
    theme_name: str
    context: dict[str, Any]
    partition: str
    # For `theme`.
    bible: dict[str, int] | None = None
    theme_sha256: str | None = None
    candidates: int = 0
    duration_s: float = 0.0
    seeds: list[int] | None = None
    # For `versions`.
    theme_row_id: int = 0
    candidate_id: int = 0
    seed: int = 0
    canonical: dict[str, Any] | None = None
    emotions: list[str] | None = None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    requested = job_input.get("requested")
    theme_id = job_input.get("theme_id")
    theme_name = job_input.get("theme_name")
    context = job_input.get("context")
    partition = job_input.get("partition")
    if (
        requested not in (music_themes.REQUESTED_THEME, music_themes.REQUESTED_VERSIONS)
        or not isinstance(theme_id, str)
        or not isinstance(theme_name, str)
        or not isinstance(context, dict)
        or not isinstance(partition, str)
    ):
        return None
    if requested == music_themes.REQUESTED_THEME:
        bible = job_input.get("bible")
        sha = job_input.get("theme_sha256")
        candidates = job_input.get("candidates")
        duration = job_input.get("duration_s")
        seeds = job_input.get("seeds")
        if (
            not isinstance(bible, dict)
            or not _is_int(bible.get("id"))
            or not _is_int(bible.get("version"))
            or not isinstance(sha, str)
            or not _is_int(candidates)
            or not isinstance(duration, int | float)
            or isinstance(duration, bool)
            or not isinstance(seeds, list)
            or not all(_is_int(seed) for seed in seeds)
            or not 1 <= candidates <= len(seeds)
        ):
            return None
        return _Task(
            requested=requested,
            theme_id=theme_id,
            theme_name=theme_name,
            context=context,
            partition=partition,
            bible={"id": bible["id"], "version": bible["version"]},
            theme_sha256=sha,
            candidates=candidates,
            duration_s=float(duration),
            seeds=[int(seed) for seed in seeds],
        )
    row_id = job_input.get("theme_row_id")
    candidate_id = job_input.get("candidate_id")
    seed = job_input.get("seed")
    canonical = job_input.get("canonical")
    emotions = job_input.get("emotions")
    if (
        not _is_int(row_id)
        or not _is_int(candidate_id)
        or not _is_int(seed)
        or not isinstance(canonical, dict)
        or not isinstance(emotions, list)
        or not emotions
        or not all(isinstance(emotion, str) for emotion in emotions)
    ):
        return None
    return _Task(
        requested=requested,
        theme_id=theme_id,
        theme_name=theme_name,
        context=context,
        partition=partition,
        theme_row_id=row_id,
        candidate_id=candidate_id,
        seed=seed,
        canonical=canonical,
        emotions=[str(emotion) for emotion in emotions],
    )


def _theme_reader(duration_s: float, warnings: list[str]) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            checked = writer.check_theme_answer(
                writer.parse_answer(result.content), duration_s=duration_s
            )
        except ValueError as exc:
            return str(exc), None
        warnings[:] = checked.warnings
        return None, checked.fields

    return read


def _versions_reader(task: _Task, warnings: list[str]) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        assert task.canonical is not None and task.emotions is not None
        try:
            checked = writer.check_versions_answer(
                writer.parse_answer(result.content),
                emotions=task.emotions,
                canonical=task.canonical,
            )
        except ValueError as exc:
            return str(exc), None
        warnings[:] = checked.warnings
        return None, checked.versions

    return read


class WriteMusicThemePromptHandler(JobHandler):
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
        warnings: list[str] = []
        if task.requested == music_themes.REQUESTED_THEME:
            body = writer.build_theme_request(task.context, model=target.model)
            read = _theme_reader(task.duration_s, warnings)
        else:
            assert task.canonical is not None and task.emotions is not None
            body = writer.build_versions_request(
                task.context, task.canonical, task.emotions, model=target.model
            )
            read = _versions_reader(task, warnings)

        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            instructions_sha256=llm_call.instructions_sha256(body),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)
        # `correct`: the second attempt is told why the first answer was refused.
        outcome = await llm_call.ask_model(
            job_id, target, body, read, timeout_s=REQUEST_TIMEOUT_S, correct=True
        )
        if outcome.value is None:
            what = "theme" if task.requested == music_themes.REQUESTED_THEME else "versions"
            await self._fail(job_id, f"The {what} could not be written: {outcome.failure}")
            return

        async with SessionLocal() as session:
            try:
                saved = await self._save(session, job_id, project_id, task, outcome.value)
            except music_themes.MusicThemeError as exc:
                await session.rollback()
                await self._fail(job_id, str(exc))
                return
            output = {
                "call": outcome.record(),
                "usage": outcome.usage,
                "warnings": warnings,
                "saved": saved,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: nothing is kept, and no recording starts.
                await session.rollback()
                return
            await session.commit()
        dispatcher.nudge()

        _logger.info(
            "job %d: music theme %s saved for project %d (%s), usage=%s",
            job_id,
            task.theme_id,
            project_id,
            task.requested,
            outcome.usage,
        )

    # --- Small helpers ------------------------------------------------------------------

    async def _save(
        self,
        session: Any,
        job_id: int,
        project_id: int,
        task: _Task,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        """Adds the rows and the recordings' jobs to the session (flushed, not committed) and
        says what was added.
        """
        if task.requested == music_themes.REQUESTED_THEME:
            await self._phase(job_id, phases.SAVING_MUSIC_THEME)
            assert task.bible is not None and task.theme_sha256 is not None
            assert task.seeds is not None
            row = await music_themes.save_theme(
                session,
                project_id=project_id,
                job_id=job_id,
                theme_id=task.theme_id,
                theme_name=task.theme_name,
                fields=value,
                bible=task.bible,
                theme_sha256=task.theme_sha256,
                candidates=task.candidates,
                seeds=task.seeds,
                partition=task.partition,
            )
            return {"music_theme_id": row.id, "version": row.version}
        await self._phase(job_id, phases.SAVING_MUSIC_THEME_VERSIONS)
        made = await music_themes.save_versions(
            session,
            project_id=project_id,
            job_id=job_id,
            theme_row_id=task.theme_row_id,
            candidate_id=task.candidate_id,
            theme_name=task.theme_name,
            seed=task.seed,
            versions=value,
            partition=task.partition,
        )
        return {"music_theme_version_ids": [version.id for version in made]}

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
