"""The `select_shot_references` job: a language model chooses the reference pictures of one shot
from the catalog of the pictures that could matter to it, code checks the choice, and the checked
manifest is stored as a new version of that shot's reference manifest (PHASE-033,
`Path_ahead.md` Section 28).

`services/shot_references._queue` creates the job with the shot's stored specification
(`shot_definition`, and the id of its row), the catalog (`catalog`: every candidate picture with
its text description) and the `inputs` that are written onto the manifest (D-3). The job builds
the request (`reference_selection_writer.build_request`), asks the model and checks the answer
(`reference_selection_writer.check_answer`: ids that exist, the counts, the minimum-sufficient
rule). The manifest is saved in the same transaction that marks the job succeeded.

**The fixed rule is the fallback.** When the model's answer cannot be used after the second
attempt, or the call fails (a timeout, a refusal, no network), the pictures are chosen by the
fixed rule of PHASE-024 (`reference_selection.select`) from the same catalog, and the manifest
says so (`method` `deterministic`, with the `fallback_reason`). The job fails only when the fixed
rule refuses too, which `_queue` rules out beforehand for the catalog it stored.

One job per shot, so shots are chosen side by side when the pools allow (`store.create_job` with
`dedupe_key`). The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every story
stage (D-12).

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by pressing Select references again.

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
    generation_requests,
    llm_target,
    reference_selection,
    reference_selection_writer,
    shot_prompts,
    shot_references,
)
from app.services.llm_target import STORY_MODEL_KEY
from app.services.reference_selection import CatalogPicture, Selection

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 1200.0

_BAD_INPUT = "This job has no shot to choose references for."


@dataclass(frozen=True)
class _Input:
    """What `_queue` put on the job, checked."""

    scene_id: str
    shot_id: str
    shot_definition_id: int
    shot_definition: dict[str, Any]
    catalog: list[CatalogPicture]
    inputs: dict[str, Any]


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `_queue` writes is missing or the wrong shape
    (a job made by hand, or by an older version of the code).
    """
    scene_id = job_input.get("scene_id")
    shot_id = job_input.get("shot_id")
    definition_id = job_input.get("shot_definition_id")
    definition = job_input.get("shot_definition")
    raw_catalog = job_input.get("catalog")
    inputs = job_input.get("inputs")
    if (
        not isinstance(scene_id, str)
        or not isinstance(shot_id, str)
        or not isinstance(definition_id, int)
        or isinstance(definition_id, bool)
        or not isinstance(definition, dict)
        or not isinstance(raw_catalog, list)
        or not isinstance(inputs, dict)
    ):
        return None
    catalog = [CatalogPicture.from_dict(item) for item in raw_catalog]
    if any(picture is None for picture in catalog):
        return None
    return _Input(
        scene_id=scene_id,
        shot_id=shot_id,
        shot_definition_id=definition_id,
        shot_definition=definition,
        catalog=[picture for picture in catalog if picture is not None],
        inputs=inputs,
    )


class SelectShotReferencesHandler(JobHandler):
    job_type = shot_references.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(result: llm.ChatResult, read: _Input) -> tuple[str | None, Selection | None]:
        """Reads one answer: `(None, selection)` when it can be stored, else `(why not, None)`."""
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = reference_selection_writer.parse_answer(result.content)
            return None, reference_selection_writer.check_answer(
                answer, read.shot_definition, read.catalog
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
            await session.commit()

        if project_id is None or read is None:
            await self._fail(job_id, _BAD_INPUT)
            return
        shot_id = read.shot_id

        await self._phase(job_id, phases.PREPARING_PROMPT)
        try:
            body = reference_selection_writer.build_request(
                shot_definition=read.shot_definition, catalog=read.catalog, model=target.model
            )
        except reference_selection.ReferenceSelectionError as exc:
            await self._fail(job_id, f"The references of the shot '{shot_id}': {exc}")
            return
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
        selection: Selection | None = outcome.value
        method = reference_selection.METHOD_LLM
        fallback_reason: str | None = None
        if selection is None:
            # The model could not be used: the fixed rule chooses, and the manifest says why.
            method = reference_selection.METHOD_DETERMINISTIC
            fallback_reason = outcome.failure or "The model gave no usable answer."
            await self._phase(job_id, phases.USING_FIXED_RULE)
            _logger.info("job %d: the model was not used, the fixed rule chooses", job_id)
            try:
                selection = reference_selection.select(read.shot_definition, read.catalog)
            except reference_selection.ReferenceSelectionError as exc:
                await self._fail(
                    job_id,
                    f"The references of the shot '{shot_id}' could not be chosen. The model: "
                    f"{fallback_reason} The fixed rule: {exc}",
                )
                return

        await self._phase(job_id, phases.SAVING_SHOT_REFERENCES)
        async with SessionLocal() as session:
            row = await shot_references.save_manifest(
                session,
                project_id=project_id,
                scene_id=read.scene_id,
                shot_id=shot_id,
                shot_definition_id=read.shot_definition_id,
                selection=selection,
                catalog=read.catalog,
                method=method,
                fallback_reason=fallback_reason,
                job_id=job_id,
                inputs=read.inputs,
            )
            output = {
                **outcome.record(),
                "content": None,
                "scene_id": read.scene_id,
                "shot_id": shot_id,
                "version": row.version,
                "method": method,
                "fallback_reason": fallback_reason,
                "pictures": len(selection.pictures),
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the manifest is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: references of shot '%s' of scene '%s' chosen for project %d by %s, "
            "version %d, usage=%s",
            job_id,
            shot_id,
            read.scene_id,
            project_id,
            method,
            row.version,
            outcome.usage,
        )
        await self._chain(job_id, project_id, read.scene_id, shot_id)

    # --- What follows a stored manifest ---------------------------------------------------

    @staticmethod
    async def _chain(job_id: int, project_id: int, scene_id: str, shot_id: str) -> None:
        """The steps that follow, exactly as after the fixed rule chose (PHASE-024 to PHASE-026):
        the shot's generation request is planned, then its prompt compiled. Each is a separate
        step: a failure in one must not fail a job that has succeeded.
        """
        planned = False
        try:
            async with SessionLocal() as session:
                planned = await generation_requests.plan_if_ready(
                    session, project_id, scene_id, shot_id
                )
        except Exception:
            _logger.exception("job %d: the generation request could not be planned", job_id)
        if planned:
            await shot_prompts.queue_after_planning(project_id, scene_id, shot_id)
        # The shot may have been defined again while the model chose: this manifest then reads
        # out of date, and the references are chosen again (a no-op when it is current).
        try:
            async with SessionLocal() as session:
                await shot_references.select_if_ready(session, project_id, scene_id, shot_id)
        except Exception:
            _logger.exception("job %d: the references could not be chosen again", job_id)

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
