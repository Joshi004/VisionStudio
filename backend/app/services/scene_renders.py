"""The scene render: one scene of a story rendered on its own (SCN-003, `S-5` and `S-6` of
`Scene_pipeline_implementation_phases.md`).

One press of **Render scene** makes one `render_scene` job (`jobs/render_scene.py`, a local job:
FFmpeg runs on this machine). The press gathers what the story workspace already knows, exactly
as `story_renders.start_render` does for the whole story, and
`story_render_plan.build_scene_plan` turns the scene's part of it into the **frozen timeline**
stored on the job (`job.input.timeline`). It is the full render's own timeline builder, so a scene
looks and sounds in its render as it will in the full video; the timeline is moved only so that
the scene's first frame is frame 0.

- **A shot with no clip yet** (no selected take, a missing file, a graphic with no video) gets a
  placeholder of its planned length, and a line of dialogue whose shots are all placeholders is
  played from its recorded speech, so the timing can be judged.
- **Music** is the current final placement when there is one (`render_music.gate`). Without it,
  a **provisional placement** is worked out when the render is started (SCN-011,
  `render_music.scene_gate`): the story's timing with a placeholder for every missing clip, no
  model call, and nothing stored but what it was made from (`timeline.music.provisional`). It is
  cut to the scene's window with short fades. Without either the scene render has no music, and
  says why (`SceneRenderState.no_music_reason`).
- **A scene render is stored only when it succeeds** (`save_scene_render`, called by the job in
  the transaction that finishes it) and renders never replace each other: they are numbered from
  1 for each scene. All of them are kept.
- **Out of date is worked out on every read** and never stored (D-3), as for the full render.
- A scene render never replaces, and is never read as, the full render: it has its own table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, SceneRender
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    caption_plan,
    music_placement,
    provenance,
    render_music,
    shot_graphics,
    shot_plans,
    shot_takes,
    shot_voice_sources,
    speech_synthesis,
    story_render_plan,
    story_renders,
)

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "render_scene"

# `current`: the render was made from the shots and plans as they are now. `out_of_date`: one of
# them has changed since (see the reasons).
STATUS_CURRENT: Final = "current"
STATUS_OUT_OF_DATE: Final = "out_of_date"

_ALREADY_RENDERING: Final = "A render of this scene is already being made."
_NO_SUCH_SCENE: Final = "The story has no such scene."
# The scene's place in the story may differ by this much before a render is out of date for it.
_START_TOLERANCE_S: Final = 0.0005


class SceneRendersError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class SceneRenderEntry:
    """One finished scene render and whether it still matches the story."""

    row: SceneRender
    job: Job | None
    status: str
    # Why the render is out of date, one sentence each. Empty when it is current.
    reasons: list[str]


@dataclass(frozen=True)
class SceneRenderState:
    """What the story workspace shows for one scene."""

    scene_id: str
    index: int
    title: str
    can_render: bool
    # Why Render scene may not be pressed, or None.
    blocked_reason: str | None
    # What the next render of the scene would warn about. Empty when it cannot be made.
    warnings: list[dict[str, Any]]
    # How long the next render would be, in frames, or None when it cannot be made.
    planned_frames: int | None
    # How many shots the next render would show as a placeholder.
    placeholders: int
    # The music placement version the next render would use, or None when it has no music or
    # its music is provisional.
    music_placement_version: int | None
    # The next render's music is placed provisionally, on the planned times of missing clips.
    music_provisional: bool
    # Why the next render has no music although the project wants it, or None.
    no_music_reason: str | None
    # The newest scene render job of this scene, whatever its status.
    job: Job | None
    # Every finished render of this scene, the newest first.
    renders: list[SceneRenderEntry]


@dataclass(frozen=True)
class SceneRendersState:
    fps: int
    # Every scene of the story, in story order.
    scenes: list[SceneRenderState]


# --- What a plan is made from ---------------------------------------------------------------


@dataclass(frozen=True)
class _Context:
    """What one read gathers once and every scene's plan is made from."""

    project: Project
    plans: shot_plans.ShotPlansState
    takes: shot_takes.ShotTakesState
    speech: dict[tuple[str, str], speech_synthesis.UnitEntry]
    mix: story_render_plan.MixSettings
    music: render_music.SceneMusicGate
    callouts: story_renders.CalloutGate
    switched: set[tuple[str, str]]
    graphics: dict[tuple[str, str], shot_graphics.UsedVideo | None]
    sources: list[story_render_plan.SceneSource]


async def _context(session: AsyncSession, project: Project, *, place: bool) -> _Context:
    """What one read gathers once. `place` is True only when a render is being started: the
    provisional music is placed then (it measures sounds); a read only checks that it can be.
    """
    plans = await shot_plans.state(session, project)
    takes = await shot_takes.state(session, project)
    speech = story_renders.speech_by_unit(await speech_synthesis.state(session, project))
    sources = (
        []
        if plans.blocked_reason is not None or takes.blocked_reason is not None
        else await story_renders.scene_sources(
            session,
            project,
            plans,
            takes,
            speech,
            await story_renders.caption_timings(session, project),
        )
    )
    return _Context(
        project=project,
        plans=plans,
        takes=takes,
        speech=speech,
        mix=await story_renders.mix_settings(session),
        music=await render_music.scene_gate(session, project, place=place),
        callouts=await story_renders.callout_gate(session, project),
        switched=await shot_voice_sources.clip_shots(session, project),
        graphics=await story_renders.graphic_videos(session, project),
        sources=sources,
    )


@dataclass(frozen=True)
class _ScenePlan:
    plan: story_render_plan.RenderPlan | None
    blocked_reason: str | None
    # The music placement version in the plan, or None.
    music_version: int | None
    no_music_reason: str | None
    # The plan's music is, or in a read would be, provisional.
    music_provisional: bool = False


def _plan_scene(context: _Context, scene: story_render_plan.SceneSource) -> _ScenePlan:
    """The plan of one scene's next render, or the reason it cannot be made. Music is left out,
    with the reason, when the project has no current placement or the placement cannot be cut.
    """
    project = context.project
    if context.callouts.blocked_reason is not None:
        return _ScenePlan(None, context.callouts.blocked_reason, None, None)
    callouts = context.callouts.source
    highlight = callouts.accent if callouts is not None else caption_plan.HIGHLIGHT_COLOUR
    captions = (
        caption_plan.style_for(project.out_width, project.out_height, highlight)
        if story_renders.captions_wanted(project)
        else None
    )

    def build(music: story_render_plan.MusicSource | None) -> story_render_plan.RenderPlan:
        return story_render_plan.build_scene_plan(
            scene,
            fps=project.fps,
            width=project.out_width,
            height=project.out_height,
            mix=context.mix,
            music=music,
            captions=captions,
            callouts=callouts,
        )

    source = context.music.source
    no_music_reason: str | None = context.music.blocked_reason
    try:
        plan = build(source)
        # A scene that starts at an unknown place gets no music at all (the plan says so).
        has_music = not any(
            warning["code"] == story_render_plan.SCENE_START_UNKNOWN for warning in plan.warnings
        )
        return _ScenePlan(
            plan,
            None,
            source.placement_version
            if source is not None and not context.music.provisional
            else None,
            no_music_reason,
            context.music.provisional and has_music,
        )
    except story_render_plan.RenderPlanError as exc:
        if source is None:
            return _ScenePlan(None, str(exc), None, no_music_reason)
        # The music could be what is wrong with it: try the scene without.
        try:
            plan = build(None)
        except story_render_plan.RenderPlanError:
            return _ScenePlan(None, str(exc), None, None)
        return _ScenePlan(plan, None, None, str(exc))


# --- Out of date ----------------------------------------------------------------------------


def _music_reasons(recorded: dict[str, Any], context: _Context) -> list[str]:
    """Why the music of a scene render, or its mix settings, no longer match. A render made with
    a provisional placement (SCN-011) is out of date when the final placement has been made since,
    when music cannot be placed now, or when what it was placed from has changed. Any other render
    is judged as the full render's is.
    """
    music = context.music
    used = recorded.get("music") if isinstance(recorded.get("music"), dict) else None
    then = used.get("provisional") if used is not None else None
    if not isinstance(used, dict) or not isinstance(then, dict):
        return story_renders.music_reasons(
            recorded,
            context.project,
            music.final.source,
            music.final.blocked_reason,
            context.mix,
        )
    reasons: list[str] = []
    if music.final_current:
        reasons.append("The final music placement was made since this video was made.")
    elif not context.project.music_enabled:
        reasons.append("Music has been switched off since this video was made.")
    elif music.provisional_inputs is None:
        reasons.append(
            music.blocked_reason or "The music of this video is no longer part of the story."
        )
    else:
        reasons.extend(music_placement.input_differences(then, music.provisional_inputs))
    if used.get("ambience") != context.project.ambience_enabled:
        reasons.append("The ambience switch has changed since this video was made.")
    reasons.extend(story_renders.mix_constant_reasons(recorded, with_music=True, mix=context.mix))
    return reasons


def _scene_reasons(
    row: SceneRender,
    entry: shot_plans.SceneEntry | None,
    context: _Context,
) -> list[str]:
    """Why a scene render no longer matches the story, one sentence each."""
    if entry is None:
        return ["The scene is no longer part of the story."]
    recorded = row.inputs if isinstance(row.inputs, dict) else {}
    reasons: list[str] = []
    label = f"scene {entry.item['index']}"

    scenes = [s for s in recorded.get("scenes") or [] if isinstance(s, dict)]
    then = scenes[0] if scenes else {}
    if not provenance.same_id(then.get("plan_id"), entry.row):
        reasons.append(f"The shots of {label} were planned again since this video was made.")
    elif entry.status == "out_of_date":
        reasons.append(f"The shot plan of {label} is out of date.")
    started = then.get("story_start_s")
    start_now = entry.story_start_s if entry.story_start_s is not None else 0.0
    if isinstance(started, int | float) and abs(started - start_now) > _START_TOLERANCE_S:
        reasons.append(f"The place of {label} in the story changed since this video was made.")

    shots_now = {
        (scene.item["id"], shot.shot["id"]): shot
        for scene in context.takes.entries
        for shot in scene.shots
    }
    for shot in recorded.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        key = (shot.get("scene_id"), shot.get("shot_id"))
        shot_label = f"The shot {shot.get('shot_id')} of {label}"
        if isinstance(shot.get("graphic"), dict):
            reasons.extend(story_renders.graphic_reasons(shot, context.graphics))
            continue
        now = shots_now.get(key)
        if now is None:
            continue  # the scene's own reason says so
        voice_then = shot.get("voice")
        if voice_then in (story_render_plan.VOICE_TAKE, story_render_plan.VOICE_CLIP):
            voice_now = (
                story_render_plan.VOICE_CLIP
                if key in context.switched
                else story_render_plan.VOICE_TAKE
            )
            if voice_now != voice_then:
                reasons.append(
                    f"{shot_label} was switched to the voice of its clip since this video was made."
                    if voice_now == story_render_plan.VOICE_CLIP
                    else f"{shot_label} was switched back to the voice take since this video "
                    "was made."
                )
        source = story_renders.take_source(now)
        if isinstance(shot.get("placeholder"), dict):
            if key in context.graphics:
                if context.graphics[key] is not None:
                    reasons.append(
                        f"{shot_label} has a graphic now where this video shows a placeholder."
                    )
            elif source is not None and source.file_exists:
                reasons.append(f"{shot_label} has a clip now where this video shows a placeholder.")
            continue
        selected = now.selected
        if selected is None:
            reasons.append(f"{shot_label} has no selected clip now.")
        elif selected.row.id != shot.get("take_id"):
            reasons.append(
                f"{shot_label} has another selected take now (take "
                f"{selected.row.take_number}; this video used take {shot.get('take_number')})."
            )
        elif selected.reasons:
            reasons.append(f"{shot_label} is out of date: {selected.reasons[0]}")

    # The recorded lines that stood in for a clip, against the speech made now.
    for unit in recorded.get("narration") or []:
        if not isinstance(unit, dict):
            continue
        made = context.speech.get((str(unit.get("scene_id")), str(unit.get("unit_id"))))
        if made is None:
            continue
        unit_label = f"The line {unit.get('unit_id')}"
        if made.status != "ready" or made.audio is None:
            reasons.append(f"{unit_label} is no longer ready.")
        elif made.audio.id != unit.get("audio_id"):
            reasons.append(f"{unit_label} was made again since this video was made.")

    reasons.extend(_music_reasons(recorded, context))
    if isinstance(recorded.get("captions"), dict) != story_renders.captions_wanted(context.project):
        reasons.append("The captions setting has changed since this video was made.")
    reasons.extend(
        story_renders.callout_reasons(
            recorded,
            context.callouts,
            wanted=story_renders.callouts_wanted(context.project),
        )
    )
    return reasons


# --- Reading the state ----------------------------------------------------------------------


async def _all_renders(session: AsyncSession, project_id: int) -> list[SceneRender]:
    statement = (
        select(SceneRender)
        .where(SceneRender.project_id == project_id)
        .order_by(SceneRender.scene_id, SceneRender.render_number.desc())
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars())


async def _jobs(session: AsyncSession, project_id: int) -> list[Job]:
    """Every scene render job of the project, the newest first."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == JOB_TYPE)
        .order_by(Job.id.desc())
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars())


def _scene_of_job(job: Job) -> str | None:
    value = job.input.get("scene_id") if isinstance(job.input, dict) else None
    return value if isinstance(value, str) else None


@memoized_state
async def state(session: AsyncSession, project: Project) -> SceneRendersState:
    """For every scene: whether it can be rendered now, what the render would warn about, its
    newest render job and every finished render. Worked out on every read; nothing is stored.
    """
    context = await _context(session, project, place=False)
    rows = await _all_renders(session, project.id)
    jobs = await _jobs(session, project.id)
    jobs_by_id = {job.id: job for job in jobs}
    newest_job: dict[str, Job] = {}
    for job in jobs:
        scene_id = _scene_of_job(job)
        if scene_id is not None:
            newest_job.setdefault(scene_id, job)

    entries = {entry.item["id"]: entry for entry in context.plans.entries}
    sources = {source.scene_id: source for source in context.sources}
    scenes: list[SceneRenderState] = []
    for plan_entry in context.plans.entries:
        scene_id = plan_entry.item["id"]
        job = newest_job.get(scene_id)
        source = sources.get(scene_id)
        planned = (
            _plan_scene(context, source)
            if source is not None
            else _ScenePlan(
                None,
                context.plans.blocked_reason
                or context.takes.blocked_reason
                or "This scene cannot be rendered now.",
                None,
                None,
            )
        )
        blocked = planned.blocked_reason
        if blocked is None and job is not None and job.status in store.ACTIVE_STATUSES:
            blocked = _ALREADY_RENDERING
        renders: list[SceneRenderEntry] = []
        for row in rows:
            if row.scene_id != scene_id:
                continue
            reasons = _scene_reasons(row, entries.get(scene_id), context)
            renders.append(
                SceneRenderEntry(
                    row=row,
                    job=jobs_by_id.get(row.job_id) if row.job_id is not None else None,
                    status=STATUS_OUT_OF_DATE if reasons else STATUS_CURRENT,
                    reasons=reasons,
                )
            )
        timeline = planned.plan.timeline if planned.plan is not None else None
        scenes.append(
            SceneRenderState(
                scene_id=scene_id,
                index=plan_entry.item["index"],
                title=plan_entry.item["title"],
                can_render=blocked is None,
                blocked_reason=blocked,
                warnings=planned.plan.warnings if planned.plan is not None else [],
                planned_frames=timeline["total_frames"] if timeline is not None else None,
                placeholders=(
                    sum(1 for shot in timeline["shots"] if shot.get("placeholder"))
                    if timeline is not None
                    else 0
                ),
                music_placement_version=planned.music_version,
                music_provisional=planned.music_provisional,
                no_music_reason=planned.no_music_reason,
                job=job,
                renders=renders,
            )
        )
    return SceneRendersState(fps=project.fps, scenes=scenes)


# --- Starting a render ----------------------------------------------------------------------


async def start_render(session: AsyncSession, project: Project, scene_id: str) -> Job:
    """Queues the job that renders one scene, with the timeline as it is now, and commits. If a
    render of this scene is already waiting or running, that job is returned. Raises
    SceneRendersError.
    """
    context = await _context(session, project, place=True)
    source = next((item for item in context.sources if item.scene_id == scene_id), None)
    if source is None:
        known = any(entry.item["id"] == scene_id for entry in context.plans.entries)
        if not known:
            raise SceneRendersError(_NO_SUCH_SCENE)
        raise SceneRendersError(
            context.plans.blocked_reason
            or context.takes.blocked_reason
            or "This scene cannot be rendered now."
        )
    planned = _plan_scene(context, source)
    if planned.plan is None:
        raise SceneRendersError(planned.blocked_reason or "This scene cannot be rendered now.")

    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input={
            "requested": JOB_TYPE,
            "scene_id": scene_id,
            "timeline": planned.plan.timeline,
            "no_music_reason": planned.no_music_reason,
        },
        dedupe_key="scene_id",
    )
    if created:
        _logger.info(
            "scene render of project %d, scene %s queued as job %d: %d shots, %d frames, "
            "%d placeholders",
            project.id,
            scene_id,
            job.id,
            len(planned.plan.timeline["shots"]),
            planned.plan.timeline["total_frames"],
            sum(1 for shot in planned.plan.timeline["shots"] if shot.get("placeholder")),
        )
    return job


# --- Storing a render -----------------------------------------------------------------------


async def save_scene_render(
    session: AsyncSession,
    *,
    project_id: int,
    scene_id: str,
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
) -> SceneRender:
    """Adds the next render of the scene and flushes. The job commits it together with finishing
    itself.
    """
    statement = select(func.max(SceneRender.render_number)).where(
        SceneRender.project_id == project_id, SceneRender.scene_id == scene_id
    )
    number = ((await session.execute(statement)).scalar_one_or_none() or 0) + 1
    row = SceneRender(
        project_id=project_id,
        scene_id=scene_id,
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
