"""The `repair_shot_cut` job: a language model repairs one cut between two shots that do not line
up, and code checks the answer and stores a new version of each shot that changed (PHASE-023,
`Path_ahead.md` Section 26, "Shot continuity").

`services/shot_continuity._queue_repair` creates the job with the id and version of the
StoryBible, the scene (`scene`) and its definition (`scene_definition`), the cut (`cut`: the two
states, the problem, the shots that may change and the edges that are frozen), the shots on its
sides (`shots`, each with its skeleton, events, speech, newest specification and the `inputs`
its new version records), the characters and the environment. The job loads the StoryBible,
builds the request, asks the model, checks the answer and saves one new `shot_definition`
version per changed shot (`services/shot_definitions.save_shot_definition`) in the same
transaction that marks the job succeeded.

A shot that has a newer version than the one the repair read (the user defined it again
meanwhile) is never saved over: nothing is stored and the job fails with the reason.

When it has finished and committed, the references of each changed shot are chosen again, its
generation request is planned again and the scene is checked again once no repair of the scene
is left running (`services/shot_continuity.queue_check_if_ready`), which starts the next wave if
cuts still do not line up.

One job per cut (`cut_key`), so cuts that share no shot are repaired side by side when the pools
allow. The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every story stage
(D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by pressing Fix this cut. An unusable answer is asked for
once more; after that the job fails with the reason and nothing is stored.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the story or the answer.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import dispatcher, llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import (
    discovery,
    generation_requests,
    llm_target,
    shot_continuity,
    shot_cut_repair_writer,
    shot_definitions,
    shot_prompts,
    shot_references,
)
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 1200.0

_BAD_INPUT = "This job has no cut to repair."
_NO_BIBLE = "The Story Bible this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `_queue_repair` put on the job, checked."""

    scene: dict[str, Any]
    scene_id: str
    boundary_id: str
    shot_plan_id: int
    scene_definition: dict[str, Any]
    scene_character_ids: list[str]
    cut: dict[str, Any]
    shots: list[dict[str, Any]]
    characters: list[dict[str, Any]]
    environment: dict[str, Any]
    bible_id: int

    @property
    def editable(self) -> list[dict[str, Any]]:
        """The shots the repair may change, as `check_answer` reads them."""
        return [
            {"shot_id": shot["shot_id"], "duration": shot["duration"], "dialogue": shot["dialogue"]}
            for shot in self.shots
            if shot["shot_id"] in self.cut["editable_shots"]
        ]


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _valid_shot(shot: Any) -> bool:
    return (
        isinstance(shot, dict)
        and isinstance(shot.get("shot_id"), str)
        and isinstance(shot.get("shot"), dict)
        and isinstance(shot.get("events"), list)
        and isinstance(shot.get("speech"), list)
        and isinstance(shot.get("dialogue"), list)
        and _is_number(shot.get("duration"))
        and isinstance(shot.get("specification"), dict)
        and isinstance(shot.get("read_definition_id"), int)
        and isinstance(shot.get("inputs"), dict)
    )


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `_queue_repair` writes is missing or the wrong
    shape (a job made by hand, or by an older version of the code).
    """
    scene = job_input.get("scene")
    scene_id = job_input.get("scene_id")
    boundary_id = job_input.get("boundary_id")
    shot_plan_id = job_input.get("shot_plan_id")
    scene_definition = job_input.get("scene_definition")
    scene_character_ids = job_input.get("scene_character_ids")
    cut = job_input.get("cut")
    shots = job_input.get("shots")
    characters = job_input.get("characters")
    environment = job_input.get("environment")
    bible_id = job_input.get("story_bible_id")
    if (
        not isinstance(scene, dict)
        or not isinstance(scene_id, str)
        or not isinstance(boundary_id, str)
        or not isinstance(shot_plan_id, int)
        or not isinstance(scene_definition, dict)
        or not isinstance(scene_character_ids, list)
        or not all(isinstance(item, str) for item in scene_character_ids)
        or not isinstance(cut, dict)
        or not isinstance(cut.get("editable_shots"), list)
        or not cut["editable_shots"]
        or not isinstance(shots, list)
        or not shots
        or not all(_valid_shot(shot) for shot in shots)
        or not all(
            any(shot["shot_id"] == editable for shot in shots) for editable in cut["editable_shots"]
        )
        or not isinstance(characters, list)
        or not isinstance(environment, dict)
        or not isinstance(bible_id, int)
    ):
        return None
    return _Input(
        scene=scene,
        scene_id=scene_id,
        boundary_id=boundary_id,
        shot_plan_id=shot_plan_id,
        scene_definition=scene_definition,
        scene_character_ids=scene_character_ids,
        cut=cut,
        shots=shots,
        characters=characters,
        environment=environment,
        bible_id=bible_id,
    )


class RepairShotCutHandler(JobHandler):
    job_type = shot_definitions.REPAIR_JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(
        result: llm.ChatResult, read: _Input
    ) -> tuple[str | None, list[dict[str, Any]] | None]:
        """Reads one answer: `(None, shots)` when it can be stored, else `(why not, None)`."""
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = shot_cut_repair_writer.parse_answer(result.content)
            return None, shot_cut_repair_writer.check_answer(
                answer,
                scene_id=read.scene_id,
                scene_character_ids=read.scene_character_ids,
                editable=read.editable,
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
        scene_id = read.scene_id
        if bible_content is None:
            await self._fail(job_id, _NO_BIBLE)
            await self._check_again(job_id, project_id, scene_id)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = shot_cut_repair_writer.build_request(
            bible_content=bible_content,
            scene=read.scene,
            scene_definition=read.scene_definition,
            cut=read.cut,
            shots=[
                {
                    "shot": shot["shot"],
                    "events": shot["events"],
                    "speech": shot["speech"],
                    "specification": shot["specification"],
                }
                for shot in read.shots
            ],
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
        answer: list[dict[str, Any]] | None = outcome.value
        if answer is None:
            await self._fail(
                job_id,
                f"The cut {read.boundary_id} of the scene '{read.scene['title']}' could not be "
                f"repaired: {outcome.failure}",
            )
            await self._check_again(job_id, project_id, scene_id)
            return

        await self._phase(job_id, phases.SAVING_CUT_REPAIR)
        changed = [item for item in answer if item["content"] is not None]
        saved: list[dict[str, Any]] = []
        async with SessionLocal() as session:
            stale = await self._stale_shot(session, project_id, read)
            if stale is not None:
                await session.rollback()
            else:
                for item in changed:
                    shot = next(shot for shot in read.shots if shot["shot_id"] == item["shot_id"])
                    row = await shot_definitions.save_shot_definition(
                        session,
                        project_id=project_id,
                        scene_id=scene_id,
                        shot_id=item["shot_id"],
                        shot_plan_id=read.shot_plan_id,
                        content=item["content"],
                        job_id=job_id,
                        inputs=shot["inputs"],
                    )
                    saved.append({"shot_id": item["shot_id"], "version": row.version})
                output = {
                    **outcome.record(),
                    "content": None,
                    "scene_id": scene_id,
                    "boundary_id": read.boundary_id,
                    "changed": saved,
                    "unchanged": [item["shot_id"] for item in answer if item["content"] is None],
                    "seconds": round(time.monotonic() - started, 1),
                }
                if not await store.finish_job(session, job_id, output):
                    # The job was cancelled meanwhile: the repair is not kept.
                    await session.rollback()
                    return
                await session.commit()
        if stale is not None:
            await self._fail(job_id, stale)
            await self._check_again(job_id, project_id, scene_id)
            return

        _logger.info(
            "job %d: cut %s of scene '%s' repaired for project %d, changed %s, usage=%s",
            job_id,
            read.boundary_id,
            scene_id,
            project_id,
            [(item["shot_id"], item["version"]) for item in saved],
            outcome.usage,
        )

        # The references of a shot are chosen from its specification: by the fixed rule here
        # (PHASE-024), or by a job of the language model that does the steps below itself when
        # it is done (PHASE-033). A separate step: a failure here must not fail a job that has
        # succeeded.
        for item in saved:
            try:
                async with SessionLocal() as session:
                    await shot_references.select_if_ready(
                        session, project_id, scene_id, item["shot_id"]
                    )
            except Exception:
                _logger.exception("job %d: the references of the shot could not be chosen", job_id)
            # With the references chosen, the shot's generation request is planned by code too
            # (PHASE-025), exactly as after `define_shot`.
            planned = False
            try:
                async with SessionLocal() as session:
                    planned = await generation_requests.plan_if_ready(
                        session, project_id, scene_id, item["shot_id"]
                    )
            except Exception:
                _logger.exception("job %d: the generation request could not be planned", job_id)
            # And with the request planned, the shot's prompt is compiled (PHASE-026).
            if planned:
                await shot_prompts.queue_after_planning(project_id, scene_id, item["shot_id"])
        await self._check_again(job_id, project_id, scene_id)

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _stale_shot(session: AsyncSession, project_id: int, read: _Input) -> str | None:
        """A readable reason when a shot of the cut has a newer version than the one this
        repair read, else None. Then the repair is not saved: it was made from a shot that no
        longer exists in that form.
        """
        for shot in read.shots:
            newest = await shot_definitions.newest_row(
                session, project_id, read.scene_id, shot["shot_id"]
            )
            if newest is None or newest.id != shot["read_definition_id"]:
                return (
                    f"The shot '{shot['shot_id']}' was defined again while the cut "
                    f"{read.boundary_id} was being repaired, so the repair was not saved."
                )
        return None

    @staticmethod
    async def _check_again(job_id: int, project_id: int, scene_id: str) -> None:
        """Checks the scene's continuity again when no repair of the scene is left running. A
        separate step after the job's commit: a failure here must not fail a job that has
        already succeeded.
        """
        try:
            async with SessionLocal() as session:
                check = await shot_continuity.queue_check_if_ready(session, project_id, scene_id)
        except Exception:
            _logger.exception("job %d: the continuity check could not be queued", job_id)
            return
        if check is not None:
            dispatcher.nudge()

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
