"""The `assign_cast` job: a language model chooses, for every scene, the characters (none, one or
several) and the one place it shows, from the project's cast (ANALYSIS.md Section 6.2; project
cast).

It is a project job: one request for all the scenes, one job. It is a paid job, so the rules of
`write_image_prompt` hold here too (they are in `jobs/llm_call.py`): it only starts from a click
or from an automatic run, every answer is saved on the job the moment it arrives, at most 2
attempts, a refusal is never retried, and a restart never re-runs it (`never_rerun`).

The model can only choose from the cast's lists (a name that is not on them counts as none), and
a scene has room for as many characters as the image model takes pictures
(`cast.MAX_SCENE_CHARACTERS`) and one place. A choice the author made by hand is never
overwritten (`cast_assignment.plan_write`). A scene the model chose *nobody* for is still a
decision: its source is `ai`, it has no characters and its place is empty.

The save writes nothing when the scenes changed while the model was working: it checks that every
scene still has the words and the stretch of voiceover it was sent with, the same rule as the
image prompt's. A member deleted in the meantime counts as none.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the prompt or the answer.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import Project, Scene
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import cast as cast_service
from app.services import cast_assignment, llm_target
from app.services import image_prompts as image_prompts_service
from app.services import scenes as scenes_service
from app.services.cast import Cast
from app.services.cast_assignment import Assignments

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = cast_service.ASSIGN_JOB
# The cheap model of the scene cuts: choosing names from a list is not hard.
MODEL_KEY: Final = "llm_model"
REQUEST_TIMEOUT_S: Final = 600.0

_SCENES_CHANGED = (
    "The scenes changed while the choices were being made, so they were not saved. Choose again."
)


def _scene_record(scene: Scene) -> dict[str, Any]:
    return {
        "scene_id": scene.id,
        "index": scene.index,
        "start_s": scene.start_s,
        "end_s": scene.end_s,
        "text": scene.text,
    }


def _reader(scenes: list[Scene], cast: Cast) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, Assignments | None]:
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            return None, cast_assignment.parse_answer(result.content, scenes, cast)
        except ValueError as exc:
            return str(exc), None

    return read


class AssignCastHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            project = await session.get(Project, job.project_id)
            state = (
                await scenes_service.scenes_state(session, project) if project is not None else None
            )
            cast = (
                await cast_service.load_cast(session, project.id)
                if project is not None
                else Cast([], [])
            )
            target = await llm_target.resolve(session, MODEL_KEY)
            await session.commit()

        if project is None or state is None:
            await self._fail(job_id, "The project no longer exists.")
            return
        if not state.scenes:
            await self._fail(job_id, "There are no scenes yet. Propose scenes first.")
            return
        if state.stale_reasons:
            await self._fail(job_id, "The scenes are out of date. Propose scenes again first.")
            return
        if cast.is_empty:
            await self._fail(
                job_id, "The project has no characters or places. Find the cast first."
            )
            return
        scenes = state.scenes

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = cast_assignment.build_request(
            scenes, cast, model=target.model, instructions=project.description_instructions
        )
        scenes_sent = [_scene_record(scene) for scene in scenes]
        job_input.update(
            scenes_sent=scenes_sent,
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, _reader(scenes, cast), timeout_s=REQUEST_TIMEOUT_S
        )
        assignments: Assignments | None = outcome.value
        if assignments is None:
            await self._fail(job_id, f"The scenes' cast could not be chosen: {outcome.failure}")
            return

        await self._save(job_id, project.id, scenes_sent, assignments, outcome)

    # --- Saving the choices ---------------------------------------------------------

    async def _save(
        self,
        job_id: int,
        project_id: int,
        scenes_sent: list[dict[str, Any]],
        assignments: Assignments,
        outcome: llm_call.Outcome,
    ) -> None:
        """Writes the choices into the scenes and finishes the job in one transaction."""
        await self._phase(job_id, phases.SAVING_CAST_ASSIGNMENT)
        output = {
            **outcome.record(),
            "content": None,
            "unknown_names": assignments.unknown_names,
            "missing_scenes": assignments.missing_scenes,
        }
        problem: str | None = None
        kept = 0
        async with SessionLocal() as session:
            # Taking the database's write lock first means no cut edit can change the scenes
            # between the check below and the write.
            await scenes_service.lock_scenes(session, project_id)
            current = await scenes_service.list_scenes(session, project_id)
            if len(current) != len(scenes_sent) or not all(
                image_prompts_service.unchanged(scene, sent)
                for scene, sent in zip(current, scenes_sent, strict=True)
            ):
                problem = _SCENES_CHANGED
                await session.rollback()
            else:
                cast = await cast_service.load_cast(session, project_id)
                characters = {member.id for member in cast.characters}
                locations = {member.id for member in cast.locations}
                by_scene = {item.scene_id: item for item in assignments.scenes}
                for scene in current:
                    item = by_scene[scene.id]
                    # A member deleted in the meantime counts as none.
                    present = cast_assignment.Assignment(
                        scene.id,
                        tuple(i for i in item.character_ids if i in characters),
                        item.location_id if item.location_id in locations else None,
                    )
                    values = cast_assignment.plan_write(scene, present, job_id)
                    if values is None:
                        kept += 1
                        continue
                    for column, value in values.items():
                        setattr(scene, column, value)
                    await cast_service.set_scene_characters(
                        session, scene.id, present.character_ids
                    )
                output["kept_manual"] = kept
                if not await store.finish_job(session, job_id, output):
                    await session.rollback()
                    return
                await session.commit()
        if problem is not None:
            await self._fail(job_id, problem)
            return
        _logger.info(
            "job %d: cast assigned: scenes=%d kept_manual=%d unknown_names=%d missing=%d usage=%s",
            job_id,
            len(scenes_sent),
            kept,
            assignments.unknown_names,
            assignments.missing_scenes,
            outcome.usage,
        )

    # --- Small helpers --------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
