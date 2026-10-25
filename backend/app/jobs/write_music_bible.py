"""The `write_music_bible` job: a language model writes a story project's Music Bible
(MUSIC-006, `Music_implementation_phases.md` Section 4.3, levels 0a to 0c).

`services/music_bible.start_run` or `start_choose` creates the job with a copy of everything it
needs, taken when the button was pressed: the story context the model reads, the scene ids and
the character and place ids the answer is checked against, the cap on themes, the story hash and
the upstream rows (`input.context`, `scene_ids`, `refs`, `max_themes`, `story_sha256`,
`artifacts`). `input.mode` says what to do:

- `full`: three calls in a row. 0a writes four directions, 0b chooses one with reasons, 0c
  expands the chosen one into the Bible.
- `expand`: one call. The owner chose a direction among the four of an earlier version
  (`input.directions`, `input.direction_id`), so only 0c runs, and the choice is the owner's.

Each call builds its request in `services/music_bible_writer.py`, asks the model and checks the
answer there. The result is saved as the project's next Music Bible version, in the same
transaction that marks the job succeeded.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold for every call: at most 2 attempts, a refusal never retried, every
answer saved the moment it arrives, and a restart never re-runs it (`never_rerun`): the owner
asks again with a fresh job. Because the later calls read the earlier answers, a failed call
stops the job, and the answers already paid for stay on the job's output.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the story or the answers.
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
from app.services import llm_target, music_bible
from app.services import music_bible_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = music_bible.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no story material to read."
OWNER_CHOICE_REASONS: Final = "Chosen by the owner."

_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    mode: str
    context: dict[str, Any]
    scene_ids: list[str]
    refs: dict[str, set[str]]
    max_themes: int
    saved_inputs: dict[str, Any]
    # For `expand` only.
    directions: list[dict[str, Any]] | None
    direction_id: str | None


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    mode = job_input.get("mode")
    context = job_input.get("context")
    scene_ids = job_input.get("scene_ids")
    refs = job_input.get("refs")
    max_themes = job_input.get("max_themes")
    story_sha256 = job_input.get("story_sha256")
    artifacts = job_input.get("artifacts")
    if (
        mode not in (music_bible.MODE_FULL, music_bible.MODE_EXPAND)
        or not isinstance(context, dict)
        or not isinstance(scene_ids, list)
        or not scene_ids
        or not isinstance(refs, dict)
        or not isinstance(max_themes, int)
        or isinstance(max_themes, bool)
        or not isinstance(story_sha256, str)
        or not isinstance(artifacts, list)
    ):
        return None
    saved_inputs: dict[str, Any] = {"story_sha256": story_sha256, "artifacts": artifacts}
    directions = None
    direction_id = None
    if mode == music_bible.MODE_EXPAND:
        directions = job_input.get("directions")
        direction_id = job_input.get("direction_id")
        if not isinstance(directions, list) or not isinstance(direction_id, str):
            return None
        if direction_id not in {direction.get("id") for direction in directions}:
            return None
        saved_inputs["directions_from"] = job_input.get("directions_from")
    return _Task(
        mode=mode,
        context=context,
        scene_ids=[str(scene_id) for scene_id in scene_ids],
        refs={kind: {str(item) for item in ids} for kind, ids in refs.items()},
        max_themes=max_themes,
        saved_inputs=saved_inputs,
        directions=directions,
        direction_id=direction_id,
    )


def _cut_off(result: llm.ChatResult) -> bool:
    return result.finish_reason == "length"


def _read_directions(result: llm.ChatResult) -> tuple[str | None, list[dict[str, Any]] | None]:
    if _cut_off(result):
        return _TOO_LONG, None
    try:
        return None, writer.check_directions(writer.parse_answer(result.content))
    except ValueError as exc:
        return str(exc), None


def _choice_reader(directions: list[dict[str, Any]]) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if _cut_off(result):
            return _TOO_LONG, None
        try:
            return None, writer.check_choice(writer.parse_answer(result.content), directions)
        except ValueError as exc:
            return str(exc), None

    return read


def _bible_reader(task: _Task) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if _cut_off(result):
            return _TOO_LONG, None
        try:
            return None, writer.check_bible(
                writer.parse_answer(result.content),
                scene_ids=task.scene_ids,
                refs=task.refs,
                max_themes=task.max_themes,
            )
        except ValueError as exc:
            return str(exc), None

    return read


def _add_usage(total: dict[str, int], usage: dict[str, int] | None) -> None:
    for key, value in (usage or {}).items():
        total[key] = total.get(key, 0) + (value or 0)


class WriteMusicBibleHandler(JobHandler):
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
        job_input.update(
            server_url=docker_mapped(target.base_url), endpoint=llm_target.endpoint(target)
        )
        sent: dict[str, Any] = {}
        calls: dict[str, Any] = {}
        usage: dict[str, int] = {}

        async def ask(
            name: str, body: dict[str, Any], read: llm_call.ReadAnswer
        ) -> llm_call.Outcome:
            """Records the request on the job, makes one call, and keeps what it came to."""
            sent[name] = {
                "instructions_sha256": llm_call.instructions_sha256(body),
                "request": body,
            }
            job_input["calls_sent"] = dict(sent)
            async with SessionLocal() as session:
                await store.update_input(session, job_id, job_input)
            outcome = await llm_call.ask_model(
                job_id, target, body, read, timeout_s=REQUEST_TIMEOUT_S, keep={"calls": dict(calls)}
            )
            calls[name] = outcome.record()
            _add_usage(usage, outcome.usage)
            return outcome

        if task.mode == music_bible.MODE_FULL:
            outcome = await ask(
                "directions",
                writer.build_directions_request(task.context, model=target.model),
                _read_directions,
            )
            directions: list[dict[str, Any]] | None = outcome.value
            if directions is None:
                await self._fail(
                    job_id, f"The four directions could not be written: {outcome.failure}"
                )
                return

            outcome = await ask(
                "choice",
                writer.build_choice_request(task.context, directions, model=target.model),
                _choice_reader(directions),
            )
            choice: dict[str, Any] | None = outcome.value
            if choice is None:
                await self._fail(job_id, f"The direction could not be chosen: {outcome.failure}")
                return
        else:
            assert task.directions is not None and task.direction_id is not None
            directions = task.directions
            choice = {
                "direction_id": task.direction_id,
                "by": music_bible.CHOICE_BY_OWNER,
                "reasons": OWNER_CHOICE_REASONS,
            }

        direction = next(item for item in directions if item["id"] == choice["direction_id"])
        outcome = await ask(
            "bible",
            writer.build_bible_request(
                task.context, direction, max_themes=task.max_themes, model=target.model
            ),
            _bible_reader(task),
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(job_id, f"The Music Bible could not be written: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_MUSIC_BIBLE)
        async with SessionLocal() as session:
            row = await music_bible.save_version(
                session,
                project_id=project_id,
                job_id=job_id,
                inputs=task.saved_inputs,
                directions=directions,
                choice=choice,
                content=content,
            )
            output = {
                "calls": calls,
                "usage": usage,
                "music_bible_id": row.id,
                "version": row.version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: music bible version %d saved for project %d (%s), usage=%s",
            job_id,
            row.version,
            project_id,
            task.mode,
            usage,
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
