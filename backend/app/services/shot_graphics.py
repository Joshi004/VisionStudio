"""The graphics of the graphic shots of a continuous explainer: both versions of each shot, the
jobs that make them, and where each stands (EXG-005,
`Explainer_graphics_implementation_phases.md` §3.5 and §3.6).

Every graphic shot gets two **versions** from one brief: a generated component
(`generated_component`) and a block scene (`remotion_blocks`). Each try at a version is a row of
`shot_graphic` (an **attempt**), and nothing is replaced. An attempt is made in two steps:

1. A paid job (`write_shot_graphic_component` or `write_shot_graphic_scene`) asks the model for
   the code or the scene and saves it as the row's `input`.
2. A local job (`render_shot_graphic`) has the motion service draw it, checks the file and stores
   the video as a project file.

**What an attempt is drawn from.** `resolve_for_shot` works out the resolved brief of a shot with
code: the shot's brief, the project's theme, the words of the take with their Parakeet times
measured from the start of the shot's clip, and the clip's exact length (the shot's frames plus
one spare frame, `ShotSpan.clip_frames`). It is recorded on the row (`inputs.resolved`) with its
hash, so an attempt is **current** when its hash is the one worked out now. A new theme changes
the hash and makes the videos out of date; they are then made again from the input they already
have, with no model call (§3.3).

**When the graphics of a shot can be made.** The project is a continuous explainer with graphics
on, its theme is current, and the shot's brief is current. Nothing here is stored but the rows.

**What a start does** (`start_shot`, the same for the pipeline and the button), for each version:
nothing while a job of it is waiting or running, nothing when its video is current, nothing when
a component failed outright; a new attempt with the input it already has when its video is out of
date; the render again when its input has no video; otherwise a new model call.

**The video of a shot** is, for now (EXG-007 adds the owner's choice), the newest component
attempt with a current video, or the newest block attempt with a current video when the component
failed outright. A shot is **done** when it has one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, ShotGraphic, ShotGraphicBrief
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    cut_planning_writer,
    graphic_theme,
    graphics_lab,
    graphics_resolve,
    scene_timeline,
    shot_graphic_briefs,
    shot_plans,
    take_timings,
)
from app.services.storage import media_url

COMPONENT: Final = "generated_component"
BLOCKS: Final = "remotion_blocks"
ENGINES: Final = (COMPONENT, BLOCKS)
ENGINE_LABELS: Final = {COMPONENT: "Generated component", BLOCKS: "Building blocks"}

WRITE_JOB_TYPES: Final = {
    COMPONENT: "write_shot_graphic_component",
    BLOCKS: "write_shot_graphic_scene",
}
RENDER_JOB_TYPE: Final = "render_shot_graphic"
# One write job of a kind per shot at a time; one render job per attempt.
WRITE_DEDUPE_KEY: Final = "graphic_key"
RENDER_DEDUPE_KEY: Final = "shot_graphic_id"

FPS: Final = graphics_lab.FPS
# What the motion service draws at most (`motion/src/server/schema.ts`).
MAX_FRAMES: Final = 720
# The `timing.source` of a resolved brief made from the take's own word times.
TIMING_TAKE: Final = "take"

# Engine and shot statuses. `none`: nothing was made. `writing`: the model call is waiting or
# running. `rendering`: the video is being drawn. `ready`: a current video. `out_of_date`: a video
# that is not current. `failed`: nothing usable and nothing running. (A shot adds `working`.)
Status = str

THEME_MISSING_MESSAGE: Final = "Design the graphics look first: every graphic uses it."
THEME_OUT_OF_DATE_MESSAGE: Final = "The graphics look is out of date. Write it again first."
BRIEF_MISSING_MESSAGE: Final = "Write this shot's brief first: the graphics are made from it."
BRIEF_OUT_OF_DATE_MESSAGE: Final = "This shot's brief is out of date. Write it again first."
BRIEF_WRITING_MESSAGE: Final = "This shot's brief is being written."
NO_TIMELINE_MESSAGE: Final = (
    "This scene's shots cannot be laid out in time. Plan the shots again first."
)
BEING_MADE_MESSAGE: Final = "The graphics of this shot are already being made."
ENGINE_BUSY_MESSAGE: Final = "This version is already being made."
STOPPED_MESSAGE: Final = "It stopped before a video was made."


class ShotGraphicsError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- The resolved brief of a shot ------------------------------------------------------------


def resolved_sha256(resolved: dict[str, Any]) -> str:
    """A hash of a resolved brief: two attempts with the same hash are drawn from the same."""
    text = json.dumps(resolved, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_for_shot(
    *,
    brief: dict[str, Any],
    words: list[dict[str, Any]],
    theme: dict[str, Any],
    span: scene_timeline.ShotSpan,
    shift_s: float,
    width: int,
    height: int,
) -> dict[str, Any]:
    """The resolved brief of one graphic shot (§3.5). Pure.

    `brief` is the stored brief (`content`) and `words` the shot's words as the brief saved them,
    `{text, start, end}` in seconds from the shot's start in the take (Parakeet's times, never
    estimated). `shift_s` moves them onto the clip's own clock: the clip starts at the shot's
    start, except for the first shot of a scene, which also holds the lead-in. `theme` is the
    video's theme (`graphic_theme` content, whose accent is already checked). The length is the
    clip's: `span.clip_frames`, the shot's frames plus one spare frame. Raises ShotGraphicsError.
    """
    frames = span.clip_frames
    if frames is None:
        raise ShotGraphicsError(NO_TIMELINE_MESSAGE)
    if frames > MAX_FRAMES:
        raise ShotGraphicsError(
            f"This graphic would last {frames} frames, and the motion service draws at most "
            f"{MAX_FRAMES}. Plan the shots again with a shorter graphic."
        )
    timing = {
        "source": TIMING_TAKE,
        "duration_s": round(frames / FPS, 3),
        "words": [
            {
                "text": str(word["text"]),
                "start": round(float(word["start"]) + shift_s, 3),
                "end": round(float(word["end"]) + shift_s, 3),
            }
            for word in words
        ],
    }
    try:
        return graphics_resolve.resolve(
            brief,
            timing,
            width,
            height,
            FPS,
            graphics_lab.FONTS,
            frames=frames,
            theme=theme,
        )
    except (ValueError, KeyError) as exc:
        raise ShotGraphicsError(f"The graphic cannot be worked out from this brief: {exc}") from exc


# --- What the state reads --------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptEntry:
    """One attempt of one version, with its jobs."""

    row: ShotGraphic
    input_job: Job | None
    render_job: Job | None
    # `writing` or `rendering` while a job of the attempt is waiting or running, else None.
    stage: str | None
    # Its video is drawn from the resolved brief worked out now.
    current: bool
    # Why it has no video, or None.
    error: str | None

    @property
    def has_video(self) -> bool:
        return self.row.media_path is not None


@dataclass(frozen=True)
class EngineEntry:
    """One version of a shot: its attempts, newest first, and where it stands."""

    key: str
    status: Status
    attempts: list[AttemptEntry]
    # The newest attempt that has a video drawn from what is current now.
    best: AttemptEntry | None
    # Nothing more will be tried for this component and it has no current video (§3.7).
    failed_outright: bool
    # Why the newest attempt has no video, when it has none.
    last_error: str | None

    @property
    def label(self) -> str:
        return ENGINE_LABELS[self.key]

    @property
    def newest(self) -> AttemptEntry | None:
        return self.attempts[0] if self.attempts else None


@dataclass(frozen=True)
class ShotEntry:
    """One graphic shot of a scene's newest plan and where its graphics stand."""

    # The shot as the plan stores it.
    shot: dict[str, Any]
    status: Status
    # Why the videos are out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The shot's newest brief, when it has one, and its own status (`ready`, `out_of_date`, ...).
    brief: ShotGraphicBrief | None
    brief_status: str
    # The resolved brief worked out now and its hash, or None when it cannot be.
    resolved: dict[str, Any] | None
    resolved_sha256: str | None
    # The voice take of the scene and the take's time at the clip's first frame, in seconds
    # (negative inside the lead-in), for the panel.
    voice_path: str | None
    voice_offset_s: float
    engines: list[EngineEntry]
    # The shot has the video the rule picks and it is current.
    done: bool
    last_error: str | None
    # Why nothing can be made for this shot now (a missing theme or brief, ...), or None.
    refusal: str | None
    # `refusal`, or that a version is being made. `can_run` is whether Make may be pressed.
    can_run: bool
    blocked_reason: str | None
    # What the model is told about the shot: its words, the context, the mood of the theme. None
    # when the graphics cannot be made now.
    material: dict[str, Any] | None
    theme: Any


@dataclass(frozen=True)
class SceneEntry:
    """One scene of the newest list of scenes and its graphic shots."""

    item: dict[str, Any]
    shots: list[ShotEntry]
    blocked_reason: str | None


@dataclass(frozen=True)
class ShotGraphicsState:
    """What the board panel shows."""

    entries: list[SceneEntry]
    blocked_reason: str | None
    wanted: bool
    # The project's current theme: its id and version, and whether it is current.
    theme_version: int | None
    theme_current: bool


def _failure(job: Job | None) -> str | None:
    if job is None:
        return None
    if job.status == "failed":
        return job.error or "the job failed"
    if job.status == "cancelled":
        return "the job was cancelled"
    return None


def _attempt(row: ShotGraphic, jobs: dict[int, Job], current_sha: str | None) -> AttemptEntry:
    input_job = jobs.get(row.input_job_id) if row.input_job_id is not None else None
    render_job = jobs.get(row.render_job_id) if row.render_job_id is not None else None
    stage: str | None = None
    if input_job is not None and input_job.status in store.ACTIVE_STATUSES:
        stage = "writing"
    elif render_job is not None and render_job.status in store.ACTIVE_STATUSES:
        stage = "rendering"
    recorded = row.inputs.get("resolved_sha256") if isinstance(row.inputs, dict) else None
    error: str | None = None
    if row.media_path is None and stage is None:
        error = row.last_error or _failure(render_job) or _failure(input_job) or STOPPED_MESSAGE
    return AttemptEntry(
        row=row,
        input_job=input_job,
        render_job=render_job,
        stage=stage,
        current=current_sha is not None and recorded == current_sha,
        error=error,
    )


def _engine(
    key: str, rows: list[ShotGraphic], jobs: dict[int, Job], sha: str | None
) -> EngineEntry:
    attempts = [
        _attempt(row, jobs, sha) for row in sorted(rows, key=lambda row: row.attempt, reverse=True)
    ]
    best = next((a for a in attempts if a.has_video and a.current), None)
    newest = attempts[0] if attempts else None
    outright = newest is not None and newest.row.failed_outright and best is None
    status: Status
    if any(a.stage is not None for a in attempts):
        status = "writing" if any(a.stage == "writing" for a in attempts) else "rendering"
    elif best is not None:
        status = "ready"
    elif outright:
        status = "failed"
    elif any(a.has_video for a in attempts):
        status = "out_of_date"
    elif newest is not None:
        status = "failed"
    else:
        status = "none"
    return EngineEntry(
        key=key,
        status=status,
        attempts=attempts,
        best=best,
        failed_outright=outright,
        last_error=newest.error if newest is not None and best is None else None,
    )


def _span_of(entry: shot_plans.SceneEntry, shot_id: str) -> scene_timeline.ShotSpan | None:
    if entry.timeline is None:
        return None
    return next((span for span in entry.timeline.shots if span.shot_id == shot_id), None)


@dataclass(frozen=True)
class _Prepared:
    resolved: dict[str, Any]
    sha256: str
    voice_path: str | None
    voice_offset_s: float
    material: dict[str, Any]


def _prepare(
    project: Project,
    plan: shot_plans.SceneEntry,
    shot: dict[str, Any],
    brief: ShotGraphicBrief,
    theme: Any,
    clock: take_timings.TakeClock | None,
) -> tuple[_Prepared | None, str | None]:
    """The resolved brief of a shot and what the jobs need, or why it cannot be worked out."""
    span = _span_of(plan, shot["id"])
    if span is None or plan.content is None:
        return None, NO_TIMELINE_MESSAGE
    inputs = brief.inputs if isinstance(brief.inputs, dict) else {}
    words = inputs.get("words")
    context = inputs.get("context")
    if not isinstance(words, list) or not words or not isinstance(context, dict):
        return None, "This shot's brief did not record its words. Write it again."
    lead_in_s = float(plan.content[cut_planning_writer.CUT_PLAN_KEY]["lead_in_s"])
    shift_s = round(lead_in_s + float(shot["start_s"]) - span.start_s, 3)
    try:
        resolved = resolve_for_shot(
            brief=brief.content,
            words=words,
            theme=theme.content["theme"],
            span=span,
            shift_s=shift_s,
            width=project.out_width,
            height=project.out_height,
        )
    except ShotGraphicsError as exc:
        return None, str(exc)
    audio = clock.audio if clock is not None else None
    return (
        _Prepared(
            resolved=resolved,
            sha256=resolved_sha256(resolved),
            voice_path=audio.path if audio is not None and audio.path else None,
            voice_offset_s=round(span.start_s - lead_in_s, 3),
            material={
                "line": " ".join(str(word["text"]) for word in words),
                "context": str(context.get("text") or ""),
                "mood": str(theme.content["theme"]["mood"]),
            },
        ),
        None,
    )


def _refusal(
    theme_state: graphic_theme.GraphicThemeState,
    brief: ShotGraphicBrief | None,
    brief_status: str,
    prepare_problem: str | None,
) -> str | None:
    """Why the graphics of this shot cannot be made now, or None."""
    if theme_state.latest is None:
        return THEME_MISSING_MESSAGE
    if theme_state.out_of_date:
        return THEME_OUT_OF_DATE_MESSAGE
    if brief is None:
        return BRIEF_MISSING_MESSAGE
    if brief_status == "writing":
        return BRIEF_WRITING_MESSAGE
    if brief_status != "ready":
        return BRIEF_OUT_OF_DATE_MESSAGE
    return prepare_problem


def _out_of_date_reasons(engines: list[EngineEntry], theme: Any) -> list[str]:
    stale = [e.newest.row for e in engines if e.status == "out_of_date" and e.newest is not None]
    reasons: list[str] = []
    for row in stale:
        recorded = row.inputs.get("theme") if isinstance(row.inputs, dict) else None
        recorded_id = recorded.get("id") if isinstance(recorded, dict) else None
        if theme is not None and recorded_id != theme.id:
            reason = "The graphics look was written again since this graphic was made."
        else:
            reason = "The timing, the size or the colours this graphic was drawn for have changed."
        if reason not in reasons:
            reasons.append(reason)
    return reasons


async def _rows_by_shot(
    session: AsyncSession, project_id: int
) -> dict[tuple[str, str, int, str], list[ShotGraphic]]:
    statement = (
        select(ShotGraphic)
        .where(ShotGraphic.project_id == project_id)
        .order_by(ShotGraphic.id)
        .execution_options(populate_existing=True)
    )
    grouped: dict[tuple[str, str, int, str], list[ShotGraphic]] = {}
    for row in (await session.execute(statement)).scalars():
        grouped.setdefault((row.scene_id, row.shot_id, row.brief_id, row.engine), []).append(row)
    return grouped


async def _jobs_of(session: AsyncSession, rows: list[ShotGraphic]) -> dict[int, Job]:
    ids = {
        job_id
        for row in rows
        for job_id in (row.input_job_id, row.render_job_id)
        if job_id is not None
    }
    if not ids:
        return {}
    statement = select(Job).where(Job.id.in_(ids)).execution_options(populate_existing=True)
    return {job.id: job for job in (await session.execute(statement)).scalars()}


async def _build(session: AsyncSession, project: Project) -> ShotGraphicsState:
    if not graphic_theme.wanted(project):
        return ShotGraphicsState(
            entries=[],
            blocked_reason=graphic_theme.OFF_MESSAGE,
            wanted=False,
            theme_version=None,
            theme_current=False,
        )
    theme_state = await graphic_theme.state(session, project)
    theme = theme_state.latest
    briefs = await shot_graphic_briefs.state(session, project)
    plans = {
        entry.item["id"]: entry for entry in (await shot_plans.state(session, project)).entries
    }
    clocks = await take_timings.scene_clocks(session, project)
    grouped = await _rows_by_shot(session, project.id)
    jobs = await _jobs_of(session, [row for rows in grouped.values() for row in rows])

    scenes: list[SceneEntry] = []
    for scene in briefs.entries:
        scene_id = scene.item["id"]
        plan = plans.get(scene_id)
        shots: list[ShotEntry] = []
        for brief_shot in scene.shots:
            shot = brief_shot.shot
            brief = brief_shot.row
            prepared: _Prepared | None = None
            problem: str | None = None
            if brief is not None and theme is not None and plan is not None:
                prepared, problem = _prepare(
                    project, plan, shot, brief, theme, clocks.get(scene_id)
                )
            sha = prepared.sha256 if prepared is not None else None
            engines = [
                _engine(
                    key,
                    grouped.get((scene_id, shot["id"], brief.id, key), [])
                    if brief is not None
                    else [],
                    jobs,
                    sha,
                )
                for key in ENGINES
            ]
            shots.append(
                _shot_entry(
                    shot, brief, brief_shot.status, theme_state, prepared, problem, engines, theme
                )
            )
        scenes.append(SceneEntry(item=scene.item, shots=shots, blocked_reason=scene.blocked_reason))
    return ShotGraphicsState(
        entries=scenes,
        blocked_reason=None,
        wanted=True,
        theme_version=theme.version if theme is not None else None,
        theme_current=theme is not None and not theme_state.out_of_date,
    )


def _shot_entry(
    shot: dict[str, Any],
    brief: ShotGraphicBrief | None,
    brief_status: str,
    theme_state: graphic_theme.GraphicThemeState,
    prepared: _Prepared | None,
    problem: str | None,
    engines: list[EngineEntry],
    theme: Any,
) -> ShotEntry:
    component, blocks = engines
    done = component.best is not None or (component.failed_outright and blocks.best is not None)
    working = any(e.status in ("writing", "rendering") for e in engines)
    refusal = _refusal(theme_state, brief, brief_status, problem)
    reasons: list[str] = []
    errors: list[str] = []
    status: Status
    if working:
        status = "working"
    elif done:
        status = "ready"
    else:
        reasons = _out_of_date_reasons(engines, theme)
        errors = [
            f"{e.label}: {e.last_error}"
            for e in engines
            if e.status == "failed" and e.last_error is not None
        ]
        if any(e.status == "out_of_date" for e in engines):
            status = "out_of_date"
        elif errors:
            status = "failed"
        else:
            status = "none"
    blocked = refusal if refusal is not None else (BEING_MADE_MESSAGE if working else None)
    return ShotEntry(
        shot=shot,
        status=status,
        reasons=reasons,
        brief=brief,
        brief_status=brief_status,
        resolved=prepared.resolved if prepared is not None else None,
        resolved_sha256=prepared.sha256 if prepared is not None else None,
        voice_path=prepared.voice_path if prepared is not None else None,
        voice_offset_s=prepared.voice_offset_s if prepared is not None else 0.0,
        engines=engines,
        done=done,
        last_error="; ".join(errors) if errors else None,
        refusal=refusal,
        can_run=blocked is None,
        blocked_reason=blocked,
        material=prepared.material if prepared is not None and refusal is None else None,
        theme=theme,
    )


@memoized_state
async def state(session: AsyncSession, project: Project) -> ShotGraphicsState:
    """The graphic shots of the newest plans with where the graphics of each stand. Worked out
    on every read; nothing here is stored but the attempts.
    """
    return await _build(session, project)


def voice_url(entry: ShotEntry) -> str | None:
    """Where the panel plays the scene's take from, or None."""
    return media_url(entry.voice_path) if entry.voice_path is not None else None


# --- Starting ---------------------------------------------------------------------------------


def graphic_key(scene_id: str, shot_id: str) -> str:
    return f"{scene_id}/{shot_id}"


def _attempt_inputs(shot: ShotEntry, rerender_of: int | None = None) -> dict[str, Any]:
    assert shot.resolved is not None and shot.brief is not None and shot.theme is not None
    inputs: dict[str, Any] = {
        "resolved": shot.resolved,
        "resolved_sha256": shot.resolved_sha256,
        "brief": {"id": shot.brief.id, "version": shot.brief.version},
        "theme": {"id": shot.theme.id, "version": shot.theme.version},
    }
    if rerender_of is not None:
        inputs["rerender_of"] = rerender_of
    return inputs


async def queue_render(session: AsyncSession, row: ShotGraphic) -> Job:
    """Queues the job that draws the video of an attempt from the input it holds and links it as
    the attempt's `render_job_id`. No commit: the caller commits it together with the row. Two
    presses on one attempt make one job.
    """
    job, _created = await store.create_job(
        session,
        project_id=row.project_id,
        type=RENDER_JOB_TYPE,
        provider="local",
        input={RENDER_DEDUPE_KEY: row.id},
        commit=False,
        dedupe_key=RENDER_DEDUPE_KEY,
    )
    row.render_job_id = job.id
    row.last_error = None
    return job


async def _next_attempt(session: AsyncSession, brief_id: int, engine: str) -> int:
    statement = select(func.max(ShotGraphic.attempt)).where(
        ShotGraphic.brief_id == brief_id, ShotGraphic.engine == engine
    )
    return ((await session.execute(statement)).scalar_one_or_none() or 0) + 1


async def _new_row(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    shot: ShotEntry,
    engine: str,
    *,
    input: Any = None,
    rerender_of: int | None = None,
) -> ShotGraphic:
    assert shot.brief is not None
    row = ShotGraphic(
        project_id=project.id,
        scene_id=scene_id,
        shot_id=shot.shot["id"],
        brief_id=shot.brief.id,
        engine=engine,
        attempt=await _next_attempt(session, shot.brief.id, engine),
        input=input,
        inputs=_attempt_inputs(shot, rerender_of),
    )
    session.add(row)
    await session.flush()
    return row


async def _write(
    session: AsyncSession, project: Project, scene_id: str, shot: ShotEntry, engine: str
) -> Job | None:
    """A new attempt that asks the model for the code or the scene. None when a job of this kind
    is already waiting or running for the shot.
    """
    assert shot.material is not None and shot.brief is not None and shot.resolved is not None
    row = await _new_row(session, project, scene_id, shot, engine)
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=WRITE_JOB_TYPES[engine],
        provider="llm",
        input={
            WRITE_DEDUPE_KEY: graphic_key(scene_id, shot.shot["id"]),
            RENDER_DEDUPE_KEY: row.id,
            "scene_id": scene_id,
            "shot_id": shot.shot["id"],
            "line": shot.material["line"],
            "context": shot.material["context"],
            "mood": shot.material["mood"],
            "orientation": project.orientation,
            "brief": shot.brief.content,
            "resolved": shot.resolved,
        },
        commit=False,
        dedupe_key=WRITE_DEDUPE_KEY,
    )
    if not created:
        await session.delete(row)
        await session.flush()
        return None
    row.input_job_id = job.id
    return job


async def _again_from(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    shot: ShotEntry,
    engine: str,
    source: ShotGraphic,
) -> Job:
    """A new attempt that has the input of `source` and no model call: its render checks the
    input again and draws it from what is current now.
    """
    row = await _new_row(
        session, project, scene_id, shot, engine, input=source.input, rerender_of=source.id
    )
    return await queue_render(session, row)


async def _start_engine(
    session: AsyncSession, project: Project, scene_id: str, shot: ShotEntry, engine: EngineEntry
) -> Job | None:
    if engine.status in ("writing", "rendering", "ready") or engine.failed_outright:
        return None
    source = next((a for a in engine.attempts if a.row.input is not None), None)
    if source is None:
        return await _write(session, project, scene_id, shot, engine.key)
    if not source.current:
        return await _again_from(session, project, scene_id, shot, engine.key, source.row)
    if source.has_video:
        return None
    return await queue_render(session, source.row)


def _find(state_: ShotGraphicsState, scene_id: str, shot_id: str) -> ShotEntry:
    for scene in state_.entries:
        if scene.item["id"] != scene_id:
            continue
        for shot in scene.shots:
            if shot.shot["id"] == shot_id:
                return shot
    raise ShotGraphicsError(f"There is no graphic shot '{shot_id}' in the scene '{scene_id}'.")


async def start_shot(
    session: AsyncSession, project: Project, scene_id: str, shot_id: str
) -> list[Job]:
    """Makes what is missing for one graphic shot (see the module note): the jobs it queued, in
    one transaction, committed. A shot that has everything makes none. Raises ShotGraphicsError
    when the graphics cannot be made now.
    """
    shot = _find(await _build(session, project), scene_id, shot_id)
    if not shot.can_run:
        raise ShotGraphicsError(shot.blocked_reason or BEING_MADE_MESSAGE)
    jobs: list[Job] = []
    for engine in shot.engines:
        job = await _start_engine(session, project, scene_id, shot, engine)
        if job is not None:
            jobs.append(job)
    await session.commit()
    return jobs


async def ask_again(
    session: AsyncSession, project: Project, scene_id: str, shot_id: str, engine: str
) -> Job:
    """A paid model call for one version, as a new attempt with the same brief. Commits. Raises
    ShotGraphicsError when it cannot be asked now.
    """
    if engine not in ENGINES:
        raise ShotGraphicsError(f"'{engine}' is not one of the versions of a graphic.")
    shot = _find(await _build(session, project), scene_id, shot_id)
    if shot.refusal is not None:
        raise ShotGraphicsError(shot.refusal)
    if next(e for e in shot.engines if e.key == engine).status in ("writing", "rendering"):
        raise ShotGraphicsError(ENGINE_BUSY_MESSAGE)
    job = await _write(session, project, scene_id, shot, engine)
    if job is None:
        raise ShotGraphicsError(ENGINE_BUSY_MESSAGE)
    await session.commit()
    return job
