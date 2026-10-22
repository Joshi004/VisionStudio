"""The story render of a project: the selected clips of the shots put together into one video
(PHASE-028, `Path_ahead.md` Section 33).

One press of **Render** makes one `render_story` job (`jobs/render_story.py`, a local job: FFmpeg
runs on this machine). The press gathers what the story workspace already knows, the timeline of
every scene (PHASE-021) and the selected take of every shot (PHASE-027), and
`story_render_plan.build_plan` turns it into the **frozen timeline** stored on the job
(`job.input.timeline`). The job reads nothing else, so a take selected or a plan made afterwards
changes nothing in a render that has started.

- **A render is stored only when it succeeds** (`save_story_render`, called by the job in the
  transaction that finishes it). Every row has its video; a failed render leaves its failed job.
  Renders never replace each other: they are numbered from 1.
- **Out of date is worked out on every read** and never stored (D-3): a shot has another selected
  take now, a scene was planned again, or its plan is out of date, or the list of scenes changed.
- **A selected take that is out of date still renders** when it has enough frames for its shot
  (the owner's decision); the render lists it as a warning.
- Two presses make one job (`store.create_job` finds the active job of the project).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, SpeechUnitAudio, StoryRender
from app.jobs import store
from app.services import provenance, shot_plans, shot_takes, speech_synthesis, story_render_plan
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "render_story"

# `current`: the render was made from the shots and plans as they are now. `out_of_date`: one of
# them has changed since (see the reasons).
Status = Literal["current", "out_of_date"]

_ALREADY_RENDERING: Final = "A render is already being made."


class StoryRendersError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class RenderEntry:
    """One finished render and whether it still matches the story."""

    row: StoryRender
    job: Job | None
    status: Status
    # Why the render is out of date, one sentence each. Empty when it is current.
    reasons: list[str]


@dataclass(frozen=True)
class StoryRendersState:
    """What the story workspace shows."""

    can_render: bool
    # Why Render may not be pressed, or None.
    blocked_reason: str | None
    # What the next render would warn about. Empty when it cannot be made.
    warnings: list[dict[str, Any]]
    # How long the next render would be, in frames, or None when it cannot be made.
    planned_frames: int | None
    fps: int
    # The newest render job, whatever its status.
    job: Job | None
    # Every finished render, the newest first.
    renders: list[RenderEntry]


# --- Gathering what the plan is made from ---------------------------------------------------


def _file_exists(relative_path: str | None) -> bool:
    if not relative_path:
        return False
    try:
        return get_storage().get_path(relative_path).is_file()
    except StorageError:
        return False


def _recorded_audio(plan_inputs: Any) -> dict[str, dict[str, Any]]:
    """The speech each unit of a shot plan was measured from, by unit id: the plan records the
    audio it used (`shot_plans.SPEECH_AUDIO_KIND`).
    """
    recorded: dict[str, dict[str, Any]] = {}
    artifacts = plan_inputs.get("artifacts") if isinstance(plan_inputs, dict) else None
    for artifact in artifacts or []:
        if isinstance(artifact, dict) and artifact.get("kind") == shot_plans.SPEECH_AUDIO_KIND:
            unit_id = artifact.get("unit_id")
            if isinstance(unit_id, str):
                recorded[unit_id] = artifact
    return recorded


async def _unit_sources(
    session: AsyncSession,
    entry: shot_plans.SceneEntry,
    speech: dict[tuple[str, str], speech_synthesis.UnitEntry],
) -> list[story_render_plan.UnitSource]:
    """The narration the render uses: the speech made now for each unit when there is some, or
    else the speech the shot plan was measured from (PHASE-039: making a line again does not
    make the plan out of date, so the plan's record can be older than the speech).
    """
    timeline = entry.timeline
    if timeline is None or entry.row is None:
        return []
    recorded = _recorded_audio(entry.row.inputs)
    units: list[story_render_plan.UnitSource] = []
    for span in timeline.units:
        made = speech.get((entry.item["id"], span.unit_id))
        if made is not None and made.status == "ready" and made.audio is not None:
            audio: SpeechUnitAudio | None = made.audio
        else:
            artifact = recorded.get(span.unit_id)
            audio_id = artifact.get("id") if artifact is not None else None
            audio = (
                await session.get(SpeechUnitAudio, audio_id) if isinstance(audio_id, int) else None
            )
        units.append(
            story_render_plan.UnitSource(
                unit_id=span.unit_id,
                kind=span.kind,
                start_s=span.start_s,
                end_s=span.end_s,
                seconds=audio.duration_s if audio is not None else None,
                audio_id=audio.id if audio is not None else None,
                path=audio.path if audio is not None else None,
                file_exists=audio is not None and _file_exists(audio.path),
            )
        )
    return units


def _take_source(entry: shot_takes.ShotEntry | None) -> story_render_plan.TakeSource | None:
    selected = entry.selected if entry is not None else None
    if selected is None or selected.row.path is None:
        return None
    row = selected.row
    return story_render_plan.TakeSource(
        take_id=row.id,
        take_number=row.take_number,
        path=row.path,
        frame_count=row.frame_count,
        has_audio=row.audio is not None,
        file_exists=_file_exists(row.path),
        reasons=tuple(selected.reasons),
    )


def _speech_by_unit(
    audio: speech_synthesis.AudioState,
) -> dict[tuple[str, str], speech_synthesis.UnitEntry]:
    """Where each unit's speech stands now, by `(scene id, unit id)`."""
    return {
        (scene.scene.item["id"], unit.unit["id"]): unit
        for scene in audio.scenes
        for unit in scene.units
    }


async def _scene_sources(
    session: AsyncSession,
    plans: shot_plans.ShotPlansState,
    takes: shot_takes.ShotTakesState,
    speech: dict[tuple[str, str], speech_synthesis.UnitEntry],
) -> list[story_render_plan.SceneSource]:
    shots_by_scene = {
        scene.item["id"]: {shot.shot["id"]: shot for shot in scene.shots} for scene in takes.entries
    }
    scenes: list[story_render_plan.SceneSource] = []
    for entry in plans.entries:
        scene_id = entry.item["id"]
        blocked = entry.generation_blocked_reason
        shots: list[story_render_plan.ShotSource] = []
        units: list[story_render_plan.UnitSource] = []
        if blocked is None and entry.timeline is not None:
            for span in entry.timeline.shots:
                take_entry = shots_by_scene.get(scene_id, {}).get(span.shot_id)
                shots.append(
                    story_render_plan.ShotSource(
                        shot_id=span.shot_id,
                        start_s=span.start_s,
                        end_s=span.end_s,
                        take=_take_source(take_entry),
                    )
                )
            units = await _unit_sources(session, entry, speech)
        scenes.append(
            story_render_plan.SceneSource(
                scene_id=scene_id,
                index=entry.item["index"],
                title=entry.item["title"],
                story_start_s=entry.story_start_s,
                blocked_reason=blocked,
                plan_id=entry.row.id if entry.row is not None else None,
                plan_version=entry.row.version if entry.row is not None else None,
                shots=shots,
                units=units,
            )
        )
    return scenes


def _plan_of(
    project: Project, scenes: list[story_render_plan.SceneSource]
) -> tuple[story_render_plan.RenderPlan | None, str | None]:
    """The plan of the next render, or the reason it cannot be made."""
    try:
        plan = story_render_plan.build_plan(
            scenes, fps=project.fps, width=project.out_width, height=project.out_height
        )
    except story_render_plan.RenderPlanError as exc:
        return None, str(exc)
    return plan, None


# --- Reading the state ----------------------------------------------------------------------


def _render_reasons(
    row: StoryRender,
    plans: shot_plans.ShotPlansState,
    takes: shot_takes.ShotTakesState,
    speech: dict[tuple[str, str], speech_synthesis.UnitEntry],
) -> list[str]:
    """Why a render no longer matches the story, one sentence each."""
    recorded = row.inputs if isinstance(row.inputs, dict) else {}
    current = {entry.item["id"]: entry for entry in plans.entries}
    reasons: list[str] = []

    recorded_scenes = [s for s in recorded.get("scenes") or [] if isinstance(s, dict)]
    if {s.get("scene_id") for s in recorded_scenes} != set(current):
        reasons.append("The list of scenes has changed since this video was made.")
    for scene in recorded_scenes:
        entry = current.get(scene.get("scene_id"))
        if entry is None:
            continue
        label = f"scene {scene.get('index')}"
        if not provenance.same_id(scene.get("plan_id"), entry.row):
            reasons.append(f"The shots of {label} were planned again since this video was made.")
        elif entry.status == "out_of_date":
            reasons.append(f"The shot plan of {label} is out of date.")

    shots = {
        (scene.item["id"], shot.shot["id"]): shot for scene in takes.entries for shot in scene.shots
    }
    for shot in recorded.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        now = shots.get((shot.get("scene_id"), shot.get("shot_id")))
        selected = now.selected if now is not None else None
        label = f"The shot {shot.get('shot_id')} of scene {shot.get('scene_index')}"
        if now is None:
            continue  # the scenes' own reason says so
        if selected is None:
            reasons.append(f"{label} has no selected clip now.")
        elif selected.row.id != shot.get("take_id"):
            reasons.append(
                f"{label} has another selected take now (take "
                f"{selected.row.take_number}; this video used take {shot.get('take_number')})."
            )
        elif selected.reasons:
            reasons.append(f"{label} is out of date: {selected.reasons[0]}")

    # The narration the video was made with, against the speech made now (PHASE-039).
    for unit in recorded.get("narration") or []:
        if not isinstance(unit, dict):
            continue
        made = speech.get((str(unit.get("scene_id")), str(unit.get("unit_id"))))
        if made is None:
            continue  # the scenes' own reason says so
        label = f"The narration {unit.get('unit_id')}"
        if made.status != "ready" or made.audio is None:
            reasons.append(f"{label} is no longer ready.")
        elif made.audio.id != unit.get("audio_id"):
            reasons.append(f"{label} was made again since this video was made.")
    return reasons


async def _all_renders(session: AsyncSession, project_id: int) -> list[StoryRender]:
    statement = (
        select(StoryRender)
        .where(StoryRender.project_id == project_id)
        .order_by(StoryRender.render_number.desc())
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars())


async def _jobs_of(session: AsyncSession, rows: list[StoryRender]) -> dict[int, Job]:
    ids = {row.job_id for row in rows if row.job_id is not None}
    if not ids:
        return {}
    statement = select(Job).where(Job.id.in_(ids)).execution_options(populate_existing=True)
    return {job.id: job for job in (await session.execute(statement)).scalars()}


async def state(session: AsyncSession, project: Project) -> StoryRendersState:
    """Whether the story can be rendered now, what the render would warn about, the newest
    render job and every finished render. Worked out on every read; nothing here is stored.
    """
    plans = await shot_plans.state(session, project)
    takes = await shot_takes.state(session, project)
    speech = _speech_by_unit(await speech_synthesis.state(session, project))
    job = await store.latest_job(session, project.id, JOB_TYPE)
    renders = await _all_renders(session, project.id)
    jobs = await _jobs_of(session, renders)

    blocked = plans.blocked_reason or takes.blocked_reason
    plan: story_render_plan.RenderPlan | None = None
    if blocked is None:
        plan, blocked = _plan_of(project, await _scene_sources(session, plans, takes, speech))
    if blocked is None and job is not None and job.status in store.ACTIVE_STATUSES:
        blocked = _ALREADY_RENDERING

    entries: list[RenderEntry] = []
    for row in renders:
        reasons = _render_reasons(row, plans, takes, speech)
        entries.append(
            RenderEntry(
                row=row,
                job=jobs.get(row.job_id) if row.job_id is not None else None,
                status="out_of_date" if reasons else "current",
                reasons=reasons,
            )
        )
    return StoryRendersState(
        can_render=blocked is None,
        blocked_reason=blocked,
        warnings=plan.warnings if plan is not None else [],
        planned_frames=plan.timeline["total_frames"] if plan is not None else None,
        fps=project.fps,
        job=job,
        renders=entries,
    )


# --- Starting a render ----------------------------------------------------------------------


async def start_render(session: AsyncSession, project: Project) -> Job:
    """Queues the job that renders the story, with the timeline as it is now, and commits. If a
    render is already waiting or running, that job is returned. Raises StoryRendersError.
    """
    active = await store.latest_job(session, project.id, JOB_TYPE)
    if active is not None and active.status in store.ACTIVE_STATUSES:
        await session.commit()
        return active

    plans = await shot_plans.state(session, project)
    takes = await shot_takes.state(session, project)
    speech = _speech_by_unit(await speech_synthesis.state(session, project))
    blocked = plans.blocked_reason or takes.blocked_reason
    if blocked is not None:
        raise StoryRendersError(blocked)
    plan, blocked = _plan_of(project, await _scene_sources(session, plans, takes, speech))
    if plan is None:
        raise StoryRendersError(blocked or "The story cannot be rendered now.")

    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input={"requested": JOB_TYPE, "timeline": plan.timeline},
    )
    if created:
        _logger.info(
            "story render of project %d queued as job %d: %d shots, %d frames",
            project.id,
            job.id,
            len(plan.timeline["shots"]),
            plan.timeline["total_frames"],
        )
    return job


# --- Storing a render -----------------------------------------------------------------------


async def save_story_render(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    inputs: dict[str, Any],
    levels: dict[str, Any],
    path: str,
    size_bytes: int,
    sha256: str,
    width: int | None,
    height: int | None,
    frame_count: int | None,
    duration_s: float | None,
    audio: dict[str, Any] | None,
) -> StoryRender:
    """Adds the next render of the project and flushes. The job commits it together with
    finishing itself.
    """
    statement = select(func.max(StoryRender.render_number)).where(
        StoryRender.project_id == project_id
    )
    number = ((await session.execute(statement)).scalar_one_or_none() or 0) + 1
    row = StoryRender(
        project_id=project_id,
        render_number=number,
        job_id=job_id,
        inputs=inputs,
        levels=levels,
        path=path,
        size_bytes=size_bytes,
        sha256=sha256,
        width=width,
        height=height,
        frame_count=frame_count,
        duration_s=duration_s,
        audio=audio,
    )
    session.add(row)
    await session.flush()
    return row
