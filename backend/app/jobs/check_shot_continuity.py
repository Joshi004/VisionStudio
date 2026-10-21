"""The `check_shot_continuity` job: a language model judges whether the shots of one scene line up
at every boundary, and code checks the verdict and stores it as a new continuity check of that
scene (PHASE-023, `Path_ahead.md` Section 26, "Shot continuity").

`services/shot_continuity._queue_check` creates the job with the id and version of the StoryBible,
the scene (`scene`), its characters (`characters`), the shots' specifications as the model reads
them (`shots`), the boundaries to judge (`boundaries`, with ids written by code), the `round` and
the `inputs` that are written onto the check (D-3). The job loads the StoryBible, builds the
request, asks the model, checks the answer and saves it
(`services/shot_continuity.save_check`) in the same transaction that marks the job succeeded.

When it has finished and committed, the shots that do not line up are defined again by
themselves, up to `shot_continuity_max_rounds` rounds
(`services/shot_continuity.queue_redefinitions`).

One job per scene, so scenes are checked side by side when the pools allow
(`store.create_job` with `dedupe_key`). The model is the **story role**
(`llm_target.STORY_MODEL_KEY`), like every story stage (D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by pressing Check continuity. An unusable answer is asked
for once more; after that the job fails with the reason and nothing is stored.

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
from app.jobs import dispatcher, llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import (
    discovery,
    llm_target,
    shot_continuity,
    shot_continuity_writer,
)
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 1200.0

_BAD_INPUT = "This job has no scene to check."
_NO_BIBLE = "The Story Bible this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `_queue_check` put on the job, checked."""

    scene: dict[str, Any]
    scene_id: str
    shot_plan_id: int
    round: int
    characters: list[dict[str, Any]]
    shots: list[dict[str, Any]]
    boundaries: list[dict[str, Any]]
    inputs: dict[str, Any]
    bible_id: int


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `_queue_check` writes is missing or the wrong
    shape (a job made by hand, or by an older version of the code).
    """
    scene = job_input.get("scene")
    scene_id = job_input.get("scene_id")
    shot_plan_id = job_input.get("shot_plan_id")
    round_ = job_input.get("round")
    characters = job_input.get("characters")
    shots = job_input.get("shots")
    boundaries = job_input.get("boundaries")
    inputs = job_input.get("inputs")
    bible_id = job_input.get("story_bible_id")
    if (
        not isinstance(scene, dict)
        or not isinstance(scene_id, str)
        or not isinstance(shot_plan_id, int)
        or not isinstance(round_, int)
        or isinstance(round_, bool)
        or not isinstance(characters, list)
        or not isinstance(shots, list)
        or not isinstance(boundaries, list)
        or not boundaries
        or not all(isinstance(boundary, dict) for boundary in boundaries)
        or not isinstance(inputs, dict)
        or not isinstance(bible_id, int)
    ):
        return None
    return _Input(
        scene=scene,
        scene_id=scene_id,
        shot_plan_id=shot_plan_id,
        round=round_,
        characters=characters,
        shots=shots,
        boundaries=boundaries,
        inputs=inputs,
        bible_id=bible_id,
    )


class CheckShotContinuityHandler(JobHandler):
    job_type = shot_continuity.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(result: llm.ChatResult, read: _Input) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, content)` when it can be stored, else `(why not, None)`."""
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = shot_continuity_writer.parse_answer(result.content)
            return None, shot_continuity_writer.check_answer(answer, read.boundaries)
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

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = shot_continuity_writer.build_request(
            bible_content=bible_content,
            scene=read.scene,
            characters=read.characters,
            shots=read.shots,
            boundary_list=read.boundaries,
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
                f"The continuity of the scene '{read.scene['title']}' could not be checked: "
                f"{outcome.failure}",
            )
            return

        await self._phase(job_id, phases.SAVING_CONTINUITY_CHECK)
        async with SessionLocal() as session:
            row = await shot_continuity.save_check(
                session,
                project_id=project_id,
                scene_id=read.scene_id,
                shot_plan_id=read.shot_plan_id,
                round_=read.round,
                content=content,
                job_id=job_id,
                inputs=read.inputs,
            )
            check_id = row.id
            output = {
                **outcome.record(),
                "content": None,
                "scene_id": read.scene_id,
                "version": row.version,
                "round": read.round,
                "mismatch_count": content["mismatch_count"],
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the check is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: continuity of scene '%s' checked for project %d, version %d, round %d, "
            "%d mismatches, usage=%s",
            job_id,
            read.scene_id,
            project_id,
            row.version,
            read.round,
            content["mismatch_count"],
            outcome.usage,
        )

        # The shots that do not line up are defined again by themselves, up to the number of
        # rounds in the settings. A separate step: the check is stored and this job is finished
        # first. A failure here must not fail a job that has already succeeded.
        try:
            async with SessionLocal() as session:
                queued = await shot_continuity.queue_redefinitions(session, project_id, check_id)
        except Exception:
            _logger.exception("job %d: the shots could not be defined again", job_id)
            return
        if queued:
            dispatcher.nudge()
            _logger.info(
                "job %d: %d shots of scene '%s' defined again for continuity, jobs %s",
                job_id,
                len(queued),
                read.scene_id,
                [job.id for job in queued],
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
