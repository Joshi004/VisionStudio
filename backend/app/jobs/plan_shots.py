"""The `plan_shots` job: a language model plans the shots of one story scene, and code checks it
and stores it as a new version of that scene's shot plan (PHASE-020, `Path_ahead.md` Sections 22
and 25).

`services/shot_plans.start_run` creates the job with the id and version of the StoryBible, the
scene (`scene`), its definition (`scene_definition`), the definitions of the characters it chose
(`scene_characters`) and of its environment (`environment`), its events (`events`), its speech
units with the measured length of their audio (`units`), the planning target range and the
`inputs` that are written onto the version (D-3). The job loads the StoryBible, builds the
request, asks the model, checks the answer (the shape of each shot, that every event is shown in
story order, and that every speech unit is carried by the shots that show its event) and saves it
(`services/shot_plans.save_shot_plan`) in the same transaction that marks the job succeeded.

One job per scene, so scenes are planned side by side when the pools allow (`store.create_job`
with `dedupe_key`). The model is the **story role** (`llm_target.STORY_MODEL_KEY`), like every
story stage (D-12).

When the user wrote a note on the earlier plan (PHASE-038), the job also holds `feedback` (the text,
the number of the version it was about, and that plan's shots): the request gets them as data
blocks, and the plan the job saves records the note in its `inputs`.

A paid call, so the rules in `jobs/llm_call.py` hold here: at most 2 attempts, a refusal never
retried, every answer saved on the job the moment it arrives, and a restart never re-runs it
(`never_rerun`): the user asks again by pressing Plan again. An answer that leaves an event
unshown or a unit uncarried is unusable, so it is asked for once more; after that the job fails
with the reason and nothing is stored.

Before it is saved, code moves every shot's `target_duration` onto a length H3 makes
(`services/h3_lengths`, D-9), so the clips need no trimming.

After the plan is saved, its timeline is checked (`services/scene_timeline`, PHASE-021). A plan
with problems is planned again by a new job of the same type that carries `replan` (the attempt,
the problems and the shots that failed), up to `shot_replan_max_tries` times. The re-plan is
queued after this job has finished and committed, never inside it.

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
    duration_policy,
    h3_lengths,
    llm_target,
    scene_timeline,
    shot_planning_writer,
    shot_plans,
    user_feedback,
)
from app.services.llm_target import STORY_MODEL_KEY
from app.services.projects import SPEECH_BOTH, SPEECH_MODES

_logger = logging.getLogger(__name__)

# The longest the whole call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no scene to plan."
_NO_BIBLE = "The Story Bible this run was started with could not be found."


@dataclass(frozen=True)
class _Input:
    """What `start_run` put on the job, checked."""

    scene: dict[str, Any]
    scene_definition: dict[str, Any]
    scene_characters: list[dict[str, Any]]
    environment: dict[str, Any]
    events: list[dict[str, Any]]
    units: list[dict[str, Any]]
    target_min_seconds: int
    target_max_seconds: int
    inputs: dict[str, Any]
    bible_id: int
    # Set for an automatic re-plan (PHASE-021): `{attempt, problems, previous_shots}`.
    replan: dict[str, Any] | None = None
    # The project's speech mode (PHASE-049); a job queued before it is a `both` project.
    speech_mode: str = SPEECH_BOTH
    # The user's note on the earlier plan, when this plan is made from one (PHASE-038).
    feedback: user_feedback.Feedback | None = None
    # The scene's staging for the planner (PHASE-054); None on a job queued before it.
    staging: dict[str, Any] | None = None


def _read_replan(value: Any) -> tuple[bool, dict[str, Any] | None]:
    """`(True, replan)` when the job's `replan` is absent (None) or well formed, else `(False,
    None)`.
    """
    if value is None:
        return True, None
    if (
        isinstance(value, dict)
        and isinstance(value.get("attempt"), int)
        and not isinstance(value.get("attempt"), bool)
        and isinstance(value.get("problems"), list)
        and isinstance(value.get("previous_shots"), list)
    ):
        return True, value
    return False, None


def _read_input(job_input: dict[str, Any]) -> _Input | None:
    """The job's input, or None when something `start_run` writes is missing or the wrong
    shape (a job made by hand, or by an older version of the code).
    """
    scene = job_input.get("scene")
    scene_definition = job_input.get("scene_definition")
    scene_characters = job_input.get("scene_characters")
    environment = job_input.get("environment")
    events = job_input.get("events")
    units = job_input.get("units")
    target_min = job_input.get("target_min_seconds")
    target_max = job_input.get("target_max_seconds")
    inputs = job_input.get("inputs")
    bible_id = job_input.get("story_bible_id")
    replan_ok, replan = _read_replan(job_input.get("replan"))
    feedback_ok, feedback = user_feedback.read(job_input.get("feedback"))
    speech_mode = job_input.get("speech_mode", SPEECH_BOTH)
    staging = job_input.get("staging")
    if not replan_ok or not feedback_ok or not (staging is None or isinstance(staging, dict)):
        return None
    if (
        speech_mode not in SPEECH_MODES
        or not isinstance(scene, dict)
        or not isinstance(scene.get("id"), str)
        or not isinstance(scene.get("title"), str)
        or not isinstance(scene_definition, dict)
        or not isinstance(scene_characters, list)
        or not isinstance(environment, dict)
        or not isinstance(events, list)
        or not events
        or not all(isinstance(event, dict) and isinstance(event.get("id"), str) for event in events)
        or not isinstance(units, list)
        or not all(
            isinstance(unit, dict)
            and isinstance(unit.get("id"), str)
            and isinstance(unit.get("event_id"), str)
            and unit.get("kind") in ("narration", "dialogue")
            for unit in units
        )
        or not isinstance(target_min, int)
        or not isinstance(target_max, int)
        or not isinstance(inputs, dict)
        or not isinstance(bible_id, int)
    ):
        return None
    return _Input(
        scene=scene,
        scene_definition=scene_definition,
        scene_characters=scene_characters,
        environment=environment,
        events=events,
        units=units,
        target_min_seconds=target_min,
        target_max_seconds=target_max,
        inputs=inputs,
        bible_id=bible_id,
        replan=replan,
        speech_mode=speech_mode,
        feedback=feedback,
        staging=staging,
    )


def _unit_infos(
    units: list[dict[str, Any]], inputs: dict[str, Any]
) -> list[scene_timeline.UnitInfo]:
    """The scene's speech units with their kinds and lengths, as the timeline reads them. The
    length is the one recorded on the plan's inputs (the same the timeline uses later); the
    rounded `measured_seconds` the model saw is the fallback.
    """
    recorded: dict[str, float] = {}
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == shot_plans.SPEECH_AUDIO_KIND:
            seconds = artifact.get("duration_s")
            if isinstance(seconds, int | float) and not isinstance(seconds, bool):
                recorded[str(artifact.get("unit_id"))] = float(seconds)
    infos: list[scene_timeline.UnitInfo] = []
    for unit in units:
        seconds = recorded.get(unit["id"], unit.get("measured_seconds"))
        if isinstance(seconds, bool) or not isinstance(seconds, int | float):
            continue
        infos.append(scene_timeline.UnitInfo(unit["id"], unit["kind"], float(seconds)))
    return infos


class PlanShotsHandler(JobHandler):
    job_type = shot_plans.JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    @staticmethod
    def _read(
        result: llm.ChatResult,
        scene_id: str,
        events: list[dict[str, Any]],
        units: list[dict[str, Any]],
        warnings: list[str],
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Reads one answer: `(None, content)` when it can be stored, else `(why not, None)`.
        What had to be cut from a usable answer is put in `warnings` (replacing earlier ones).
        """
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        found: list[str] = []
        try:
            answer = shot_planning_writer.parse_answer(result.content)
            content = shot_planning_writer.check_answer(answer, scene_id, events, units, found)
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
            try:
                h3_lengths_seconds: list[float] | None = h3_lengths.grid_lengths(
                    await duration_policy.read_duration_policy(session)
                )
            except duration_policy.DurationPolicyError:
                h3_lengths_seconds = None
            await session.commit()

        if project_id is None or read is None:
            await self._fail(job_id, _BAD_INPUT)
            return
        if bible_content is None:
            await self._fail(job_id, _NO_BIBLE)
            return
        scene_id = read.scene["id"]
        title = read.scene["title"]

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = shot_planning_writer.build_request(
            bible_content=bible_content,
            scene=read.scene,
            scene_definition=read.scene_definition,
            scene_characters=read.scene_characters,
            environment=read.environment,
            events=read.events,
            units=read.units,
            target_min_seconds=read.target_min_seconds,
            target_max_seconds=read.target_max_seconds,
            model=target.model,
            h3_lengths_seconds=h3_lengths_seconds,
            replan=(
                {
                    "previous_shots": read.replan["previous_shots"],
                    "problems": read.replan["problems"],
                }
                if read.replan is not None
                else None
            ),
            feedback=read.feedback,
            speech_mode=read.speech_mode,
            staging=read.staging,
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
            lambda result: self._read(result, scene_id, read.events, read.units, warnings),
            timeout_s=REQUEST_TIMEOUT_S,
        )
        content: dict[str, Any] | None = outcome.value
        if content is None:
            await self._fail(
                job_id,
                f"The shots of the scene '{title}' could not be planned: {outcome.failure}",
            )
            return

        await self._phase(job_id, phases.SAVING_SHOT_PLAN)
        async with SessionLocal() as session:
            # The lengths are moved onto the lengths H3 makes (D-9), so the render cuts nothing.
            # With no usable policy the plan is saved as it came, like `timeline_of` allows.
            try:
                policy = await duration_policy.read_duration_policy(session)
            except duration_policy.DurationPolicyError:
                policy = None
            if policy is not None:
                fitted = h3_lengths.fit_shots(
                    content["shots"], _unit_infos(read.units, read.inputs), policy
                )
                content = {**content, "shots": fitted.shots}
                _logger.info(
                    "job %d: shot lengths of scene '%s' moved onto H3's lengths (%s)",
                    job_id,
                    scene_id,
                    fitted.mode,
                )
            row = await shot_plans.save_shot_plan(
                session,
                project_id=project_id,
                scene_id=scene_id,
                content=content,
                job_id=job_id,
                inputs=read.inputs,
            )
            # The timeline checks of PHASE-021: what is wrong with the plan, if anything.
            timeline = await shot_plans.timeline_of(session, row)
            problems = scene_timeline.problems_for_model(timeline) if timeline else []
            plan_id = row.id
            output = {
                **outcome.record(),
                "content": None,
                "warnings": warnings,
                "scene_id": scene_id,
                "version": row.version,
                "shots": len(content["shots"]),
                "timeline_problems": problems,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the plan is not kept.
                await session.rollback()
                return
            await session.commit()

        # A plan with problems is planned again by itself, up to the number of tries in the
        # settings. This is a separate step: the plan is stored and this job is finished first.
        if problems:
            async with SessionLocal() as session:
                replan = await shot_plans.queue_replan(session, project_id, plan_id, problems)
            if replan is not None:
                dispatcher.nudge()
                _logger.info(
                    "job %d: the plan of scene '%s' had %d timeline problems, re-plan job %d",
                    job_id,
                    scene_id,
                    len(problems),
                    replan.id,
                )

        _logger.info(
            "job %d: shots of scene '%s' planned for project %d, version %d, %d shots, usage=%s",
            job_id,
            scene_id,
            project_id,
            row.version,
            len(content["shots"]),
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
