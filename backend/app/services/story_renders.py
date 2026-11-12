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
- **Music (MUSIC-012).** With music on, a render uses the project's current music placement and is
  refused without one (`render_music.gate`); the placement is read by id and recorded on the
  render, and a newer placement makes the render out of date. The mix and loudness settings are
  recorded on the render too.
- **Callouts (EXPLAINER-010).** An explainer with `callouts` on is rendered with the callouts
  that are turned on in its current callout plan, and is refused without one (`callout_gate`):
  the plan must exist, be current and not be written just now. The plan's accent colour is the
  caption highlight then. A newer callout plan makes the render out of date.
- **Voice (FLOW-008).** A continuous explainer has no speech file per unit: each scene's voice
  take (its `take_timings` clock) is the voice, its units sit at their spans in it, and a
  presenter shot the owner switched to its clip's own voice (`shot_voice_sources`) is heard with
  the clip's sound instead. A scene whose take is not ready and timed, or was not the one its
  shots were planned on, cannot be rendered. Switching a shot makes a render out of date.
- **Captions (EXPLAINER-008).** An explainer with `captions` on reads the word timing of each
  speech (`speech_word_timing`) and its render has word-synced captions. A speech with no stored
  timing gets estimated times, which the plan warns about. A story never reads the timings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, Project, SpeechUnitAudio, SpeechWordTiming, StoryRender
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    callout_graphics,
    callout_plan,
    callout_plan_writer,
    callout_render,
    caption_plan,
    cut_planning_writer,
    graphic_theme,
    projects,
    provenance,
    scene_timeline,
    shot_graphics,
    shot_plans,
    shot_takes,
    shot_voice_sources,
    speech_synthesis,
    story_render_plan,
    take_timings,
    word_timings,
)
from app.services.project_kinds import KIND_EXPLAINER
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "render_story"

# `current`: the render was made from the shots and plans as they are now. `out_of_date`: one of
# them has changed since (see the reasons).
Status = Literal["current", "out_of_date"]

_ALREADY_RENDERING: Final = "A render is already being made."
# SCN-013: the reason of a render made with no music, once the music has been placed. A scene
# render of a full run that has only this reason is kept (the full render has the final music).
MUSIC_PLACED_SINCE: Final = "Music has been placed since this video was made."


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
    # The music placement version the next render would use, or None when it has no music.
    music_placement_version: int | None
    # Whether the next render leaves the beds and point sounds out (ambience switch).
    ambience_enabled: bool
    fps: int
    # The newest render job, whatever its status.
    job: Job | None
    # Every finished render, the newest first.
    renders: list[RenderEntry]


# --- Gathering what the plan is made from ---------------------------------------------------


def file_exists(relative_path: str | None) -> bool:
    if not relative_path:
        return False
    try:
        return get_storage().get_path(relative_path).is_file()
    except StorageError:
        return False


def recorded_captions(row: StoryRender) -> dict[str, Any] | None:
    """The caption track the render recorded, as stored (not read), or None."""
    timeline = row.inputs if isinstance(row.inputs, dict) else {}
    captions = timeline.get("captions")
    return captions if isinstance(captions, dict) else None


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


def captions_built(project: Project) -> bool:
    """Whether the render has a caption track: every explainer does, whatever its caption mode
    (CAP-001, C-2). A story never does (E-10).
    """
    return project.kind == KIND_EXPLAINER


def captions_burned(project: Project) -> bool:
    """Whether the render draws the caption track on the picture: an explainer in `burned` mode.
    In `ytt` mode the track is only frozen, for the caption files.
    """
    return captions_built(project) and project.caption_mode == projects.CAPTION_BURNED


def callouts_wanted(project: Project) -> bool:
    """Whether the render draws callouts: an explainer with its callouts switch on."""
    return callout_plan.wanted(project)


async def caption_timings(
    session: AsyncSession, project: Project
) -> dict[int, SpeechWordTiming] | None:
    """The stored word timing of every speech of the project, by the speech's audio id, or None
    when the project is not an explainer (a story is never read for timings).
    """
    if not captions_built(project) and not callouts_wanted(project):
        return None
    rows = await session.execute(
        select(SpeechWordTiming)
        .where(SpeechWordTiming.project_id == project.id)
        .execution_options(populate_existing=True)
    )
    return {row.speech_unit_audio_id: row for row in rows.scalars()}


def _timing_words(row: SpeechWordTiming) -> tuple[tuple[str, float, float], ...] | None:
    """The words of a stored timing as `(text, start_s, end_s)`, or None when it is unreadable."""
    words: list[tuple[str, float, float]] = []
    for word in row.words if isinstance(row.words, list) else []:
        if not isinstance(word, dict):
            return None
        text, start, end = word.get("text"), word.get("start"), word.get("end")
        if (
            not isinstance(text, str)
            or not isinstance(start, int | float)
            or not isinstance(end, int | float)
        ):
            return None
        words.append((text, float(start), float(end)))
    return tuple(words)


def _caption_timing(
    audio: SpeechUnitAudio | None,
    text: str | None,
    timings: dict[int, SpeechWordTiming],
) -> story_render_plan.WordTimingSource | None:
    """The word timing the captions use for a speech: the stored one, or else times estimated
    now from the script text (by character count, as `word_timings.align` does when nothing was
    heard). None when the speech has no text or no length to share out.
    """
    if audio is None:
        return None
    stored = timings.get(audio.id)
    words = _timing_words(stored) if stored is not None else None
    if words is not None:
        return story_render_plan.WordTimingSource(words)
    if not text or not text.strip() or audio.duration_s is None or audio.duration_s <= 0:
        return None
    estimated = word_timings.align(text, [], audio.duration_s, 0)
    return story_render_plan.WordTimingSource(
        tuple((word["text"], word["start"], word["end"]) for word in estimated.words),
        estimated_now=True,
    )


async def _unit_sources(
    session: AsyncSession,
    entry: shot_plans.SceneEntry,
    speech: dict[tuple[str, str], speech_synthesis.UnitEntry],
    timings: dict[int, SpeechWordTiming] | None = None,
) -> list[story_render_plan.UnitSource]:
    """The narration the render uses: the speech made now for each unit when there is some, or
    else the speech the shot plan was measured from (PHASE-039: making a line again does not
    make the plan out of date, so the plan's record can be older than the speech). With
    `timings` (an explainer's captions), each unit also gets its word timing.
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
                shot_ids=tuple(span.shot_ids),
                file_exists=audio is not None and file_exists(audio.path),
                timing=(
                    _caption_timing(
                        audio, made.unit.get("text") if made is not None else None, timings
                    )
                    if timings is not None
                    else None
                ),
            )
        )
    return units


def _voice_units(
    entry: shot_plans.SceneEntry, clock: take_timings.TakeClock
) -> list[story_render_plan.UnitSource]:
    """The speech units of a continuous scene: each at its place on the scene's timeline, with
    the words of its span in the scene's take (times from the unit's own start). Every unit shares
    the take as its audio.
    """
    timeline = entry.timeline
    audio = clock.audio
    if timeline is None or audio is None:
        return []
    spans = {span.unit_id: span for span in clock.spans}
    exists = file_exists(audio.path)
    units: list[story_render_plan.UnitSource] = []
    for placed in timeline.units:
        span = spans.get(placed.unit_id)
        if span is None:
            continue
        words = tuple(
            (str(word["text"]), float(word["start"]) - span.start, float(word["end"]) - span.start)
            for word in clock.words[span.first_word : span.last_word + 1]
        )
        units.append(
            story_render_plan.UnitSource(
                unit_id=placed.unit_id,
                kind=placed.kind,
                start_s=placed.start_s,
                end_s=placed.end_s,
                seconds=placed.end_s - placed.start_s,
                audio_id=audio.id,
                path=audio.path,
                file_exists=exists,
                timing=story_render_plan.WordTimingSource(words),
            )
        )
    return units


def _voice_blocked_reason(
    entry: shot_plans.SceneEntry, clock: take_timings.TakeClock | None
) -> str | None:
    """Why a scene of a continuous explainer has no voice to render with, or None."""
    if clock is None:
        return "This scene has no voice take."
    if clock.blocked_reason is not None:
        return clock.blocked_reason
    if (
        entry.row is None
        or not cut_planning_writer.is_cut_plan(entry.row.content)
        or entry.timeline is None
        or not entry.timeline.units
    ):
        return (
            "The shots of this scene were not planned on its current voice take. Plan them again."
        )
    return None


def _shot_descriptions(entry: shot_plans.SceneEntry) -> dict[str, str]:
    """The plan's one-sentence description of each shot, by shot id (shown on a placeholder)."""
    content = entry.row.content if entry.row is not None else None
    shots = content.get("shots") if isinstance(content, dict) else None
    return {
        str(shot["id"]): shot["description"]
        for shot in shots or []
        if isinstance(shot, dict) and isinstance(shot.get("description"), str)
    }


def take_source(entry: shot_takes.ShotEntry | None) -> story_render_plan.TakeSource | None:
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
        file_exists=file_exists(row.path),
        reasons=tuple(selected.reasons),
    )


def speech_by_unit(
    audio: speech_synthesis.AudioState,
) -> dict[tuple[str, str], speech_synthesis.UnitEntry]:
    """Where each unit's speech stands now, by `(scene id, unit id)`."""
    return {
        (scene.scene.item["id"], unit.unit["id"]): unit
        for scene in audio.scenes
        for unit in scene.units
    }


async def graphic_videos(
    session: AsyncSession, project: Project
) -> dict[tuple[str, str], shot_graphics.UsedVideo | None]:
    """The video each graphic shot of a continuous explainer with graphics on uses now (§3.8), by
    `(scene id, shot id)`. Empty for every other project, which reads nothing of the graphics.
    """
    if not graphic_theme.wanted(project):
        return {}
    state = await shot_graphics.state(session, project)
    return {
        (scene.item["id"], shot.shot["id"]): shot.used
        for scene in state.entries
        for shot in scene.shots
    }


def _graphic_source(used: shot_graphics.UsedVideo | None) -> story_render_plan.GraphicSource | None:
    row = used.attempt.row if used is not None else None
    if used is None or row is None or row.media_path is None:
        return None
    return story_render_plan.GraphicSource(
        graphic_id=row.id,
        engine=used.engine,
        attempt=row.attempt,
        path=row.media_path,
        frame_count=row.frame_count,
        file_exists=file_exists(row.media_path),
    )


async def scene_sources(
    session: AsyncSession,
    project: Project,
    plans: shot_plans.ShotPlansState,
    takes: shot_takes.ShotTakesState,
    speech: dict[tuple[str, str], speech_synthesis.UnitEntry],
    timings: dict[int, SpeechWordTiming] | None = None,
) -> list[story_render_plan.SceneSource]:
    shots_by_scene = {
        scene.item["id"]: {shot.shot["id"]: shot for shot in scene.shots} for scene in takes.entries
    }
    # A continuous explainer (FLOW-008): the take of each scene is the voice.
    clocks = await take_timings.scene_clocks(session, project)
    switched = await shot_voice_sources.clip_shots(session, project)
    continuous = word_timings.times_takes(project)
    graphics = await graphic_videos(session, project)
    scenes: list[story_render_plan.SceneSource] = []
    for entry in plans.entries:
        scene_id = entry.item["id"]
        blocked = entry.generation_blocked_reason
        shots: list[story_render_plan.ShotSource] = []
        units: list[story_render_plan.UnitSource] = []
        voice: story_render_plan.VoiceSource | None = None
        clock = clocks.get(scene_id)
        if continuous and blocked is None:
            blocked = _voice_blocked_reason(entry, clock)
        if blocked is None and entry.timeline is not None:
            presenter_ids: set[str] = set()
            graphic_ids: set[str] = set()
            descriptions = _shot_descriptions(entry)
            if continuous and entry.row is not None:
                presenter_ids = {
                    str(shot["id"])
                    for shot in entry.row.content["shots"]
                    if shot.get("type") == shot_voice_sources.PRESENTER_TYPE
                }
                graphic_ids = {
                    str(shot["id"])
                    for shot in entry.row.content["shots"]
                    if shot.get("type") == scene_timeline.GRAPHIC_SHOT_TYPE
                }
            for span in entry.timeline.shots:
                if span.shot_id in graphic_ids:
                    # No take (EXG-007): the video is the one the graphic rule picks.
                    shots.append(
                        story_render_plan.ShotSource(
                            shot_id=span.shot_id,
                            start_s=span.start_s,
                            end_s=span.end_s,
                            take=None,
                            is_graphic=True,
                            graphic=_graphic_source(graphics.get((scene_id, span.shot_id))),
                            description=descriptions.get(span.shot_id),
                        )
                    )
                    continue
                take_entry = shots_by_scene.get(scene_id, {}).get(span.shot_id)
                shots.append(
                    story_render_plan.ShotSource(
                        shot_id=span.shot_id,
                        start_s=span.start_s,
                        end_s=span.end_s,
                        take=take_source(take_entry),
                        presenter=span.shot_id in presenter_ids,
                        clip_voice=(scene_id, span.shot_id) in switched,
                        description=descriptions.get(span.shot_id),
                    )
                )
            if continuous:
                assert clock is not None and clock.audio is not None and entry.row is not None
                units = _voice_units(entry, clock)
                voice = story_render_plan.VoiceSource(
                    audio_id=clock.audio.id,
                    path=clock.audio.path,
                    seconds=float(clock.audio.duration_s or 0.0),
                    file_exists=file_exists(clock.audio.path),
                    lead_in_s=float(
                        entry.row.content[cut_planning_writer.CUT_PLAN_KEY]["lead_in_s"]
                    ),
                )
            else:
                units = await _unit_sources(session, entry, speech, timings)
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
                voice=voice,
            )
        )
    return scenes


async def mix_settings(session: AsyncSession) -> story_render_plan.MixSettings:
    """The settings of the mix and the finished loudness, as the next render would use them."""
    return story_render_plan.MixSettings(
        loudness_lufs=await settings_service.get_int(session, settings_service.RENDER_LOUDNESS_KEY),
        true_peak_db=await settings_service.get_int(session, settings_service.RENDER_TRUE_PEAK_KEY),
        duck_low_db=await settings_service.get_int(session, settings_service.MUSIC_DUCK_LOW_KEY),
        duck_medium_db=await settings_service.get_int(
            session, settings_service.MUSIC_DUCK_MEDIUM_KEY
        ),
        bed_shot_duck_db=await settings_service.get_int(
            session, settings_service.MUSIC_BED_SHOT_DUCK_KEY
        ),
    )


async def music_gate(session: AsyncSession, project: Project) -> Any:
    """What the next render does about music (`render_music.gate`). Imported here because
    `music_placement` imports this module.
    """
    from app.services import render_music

    return await render_music.gate(session, project)


def _plan_of(
    project: Project,
    scenes: list[story_render_plan.SceneSource],
    mix: story_render_plan.MixSettings,
    music: story_render_plan.MusicSource | None = None,
    captions: bool = True,
    callouts: callout_render.CalloutSource | None = None,
) -> tuple[story_render_plan.RenderPlan | None, str | None]:
    """The plan of the next render, or the reason it cannot be made. `captions` is False for a
    plan that only needs where things sit (the music placement): the scenes then need no word
    timings. `callouts` is the callout plan the render is made with, if any: its accent is the
    caption highlight.
    """
    highlight = callouts.accent if callouts is not None else caption_plan.HIGHLIGHT_COLOUR
    try:
        plan = story_render_plan.build_plan(
            scenes,
            fps=project.fps,
            width=project.out_width,
            height=project.out_height,
            mix=mix,
            music=music,
            captions=(
                caption_plan.style_for(project.out_width, project.out_height, highlight)
                if captions and captions_built(project)
                else None
            ),
            captions_burned=captions_burned(project),
            callouts=callouts,
        )
    except story_render_plan.RenderPlanError as exc:
        return None, str(exc)
    return plan, None


# --- The callout plan ------------------------------------------------------------------------

_CALLOUT_WAY_OUT: Final = (
    "Plan the callouts again, or switch callouts off in the project's settings."
)


@dataclass(frozen=True)
class CalloutGate:
    """What the next render does about callouts: a source, a reason it cannot be made, or
    neither (no callouts in this render).
    """

    source: callout_render.CalloutSource | None
    blocked_reason: str | None
    # The project's `callout_style` now (`boxes` when it has no callouts).
    callout_style: str = callout_render.STYLE_BOXES


_MOTION_WAY_OUT: Final = "Make the callout graphics first, or switch callouts to simple boxes."
_MOTION_BEING_MADE: Final = (
    "The callout graphics are being made. Wait for them to finish, or switch callouts to "
    "simple boxes."
)


def _motion_pick(entry: callout_graphics.CalloutEntry) -> callout_render.MotionPick:
    """How the render draws one callout of a motion project: the version the rule gives
    (`callout_graphics.UsedGraphic`), and the other version's current attempt to fall back to.
    A callout the rule gives a box has no version (CMO-005).
    """
    used = entry.used
    if used is None or used.attempt is None or used.engine == callout_graphics.USED_BOX:
        return callout_render.MotionPick(use=None)
    other: callout_render.MotionRef | None = None
    for engine in entry.engines:
        if engine.key != used.engine and engine.best is not None:
            other = callout_render.MotionRef(engine.best.row.id, engine.key)
    return callout_render.MotionPick(
        use=callout_render.MotionRef(used.attempt.row.id, used.engine), other=other
    )


async def _motion_source(
    session: AsyncSession, project: Project, source: callout_render.CalloutSource
) -> CalloutGate:
    """The source of a motion project's render: every enabled callout must have its graphic (or
    be a box because both versions failed outright, which does not block), and none may be being
    made now. The picks go with the source.
    """
    graphics = await callout_graphics.state(session, project)
    style = callout_render.STYLE_MOTION
    if graphics.blocked_reason is not None:
        return CalloutGate(None, f"{graphics.blocked_reason} {_MOTION_WAY_OUT}", style)
    enabled = [entry for entry in graphics.entries if entry.enabled]
    if any(entry.status == "working" for entry in enabled):
        return CalloutGate(None, _MOTION_BEING_MADE, style)
    if any(not entry.done for entry in enabled):
        return CalloutGate(None, _MOTION_WAY_OUT, style)
    if graphics.look is None or graphics.theme is None:
        return CalloutGate(None, _MOTION_WAY_OUT, style)
    picks = {str(entry.callout["id"]): _motion_pick(entry) for entry in enabled}
    return CalloutGate(
        replace(
            source,
            callout_style=style,
            look=(graphics.look.id, graphics.look.version),
            theme=(graphics.theme.id, graphics.theme.version),
            motion=picks,
        ),
        None,
        style,
    )


async def callout_gate(session: AsyncSession, project: Project) -> CalloutGate:
    """Whether the next render has callouts, and if it must, whether it can. It must have the
    current callout plan (the owner's choice): a render is refused, never made without them. In a
    `motion` project it must also have the graphics of every callout (CMO-005).
    """
    if not callouts_wanted(project):
        return CalloutGate(None, None)
    style = (
        callout_render.STYLE_MOTION
        if project.callout_style == projects.CALLOUT_MOTION
        else callout_render.STYLE_BOXES
    )
    state = await callout_plan.state(session, project)
    if state.job is not None and state.job.status in store.ACTIVE_STATUSES:
        return CalloutGate(
            None,
            f"The callout plan is being written. Wait for it to finish. {_CALLOUT_WAY_OUT}",
            style,
        )
    if state.latest is None:
        return CalloutGate(None, f"There is no callout plan yet. {_CALLOUT_WAY_OUT}", style)
    if state.blocked_reason is not None:
        return CalloutGate(None, f"{state.blocked_reason} {_CALLOUT_WAY_OUT}", style)
    if state.out_of_date:
        return CalloutGate(
            None,
            f"The callout plan is out of date: {state.reasons[0]} {_CALLOUT_WAY_OUT}",
            style,
        )
    content = state.latest.content
    source = callout_render.CalloutSource(
        plan_id=state.latest.id,
        plan_version=state.latest.version,
        accent=str(content["accent"]["colour"]),
        callouts=tuple(callout_plan_writer.enabled_callouts(content)),
    )
    if style == callout_render.STYLE_MOTION:
        return await _motion_source(session, project, source)
    return CalloutGate(source, None, style)


# --- Reading the state ----------------------------------------------------------------------


_MIX_CONSTANTS: Final = (
    "music_duck_low_db",
    "music_duck_medium_db",
    "bed_shot_duck_db",
)
_MASTER_CONSTANTS: Final = ("master_lufs", "master_true_peak_db")


def music_reasons(
    recorded: dict[str, Any],
    project: Project,
    source: story_render_plan.MusicSource | None,
    music_blocked: str | None,
    mix: story_render_plan.MixSettings,
) -> list[str]:
    """Why the music of a render, or its mix settings, no longer match."""
    reasons: list[str] = []
    used = recorded.get("music") if isinstance(recorded.get("music"), dict) else None
    if used is not None and source is None:
        if not project.music_enabled:
            reasons.append("Music has been switched off since this video was made.")
        elif music_blocked is not None:
            reasons.append("The music of this video is out of date or no longer ready.")
        else:
            reasons.append("The music of this video is no longer part of the story.")
    elif used is None and source is not None:
        reasons.append(MUSIC_PLACED_SINCE)
    elif used is not None and source is not None:
        if used.get("placement_id") != source.placement_id:
            reasons.append(
                f"The music was placed again since this video was made (version "
                f"{source.placement_version}; this video used version "
                f"{used.get('placement_version')})."
            )
        if used.get("ambience") != source.ambience:
            reasons.append("The ambience switch has changed since this video was made.")

    reasons.extend(mix_constant_reasons(recorded, with_music=used is not None, mix=mix))
    return reasons


def mix_constant_reasons(
    recorded: dict[str, Any], *, with_music: bool, mix: story_render_plan.MixSettings
) -> list[str]:
    """Whether a mix or loudness setting has changed since a render was made. `with_music` is
    whether the render had music (its mix settings only matter then).
    """
    # A video made before the final loudness (timeline version 1) has no recorded settings.
    constants = recorded.get("constants") if isinstance(recorded.get("constants"), dict) else {}
    now = story_render_plan.constants(mix)
    keys = (*_MIX_CONSTANTS, *_MASTER_CONSTANTS) if with_music else _MASTER_CONSTANTS
    if any(key in constants and constants[key] != now[key] for key in keys):
        return ["A mix or loudness setting has changed since this video was made."]
    return []


def _render_reasons(
    row: StoryRender,
    plans: shot_plans.ShotPlansState,
    takes: shot_takes.ShotTakesState,
    speech: dict[tuple[str, str], speech_synthesis.UnitEntry],
    music: tuple[
        Project, story_render_plan.MusicSource | None, str | None, story_render_plan.MixSettings
    ],
    callouts: CalloutGate,
    switched: set[tuple[str, str]],
    graphics: dict[tuple[str, str], shot_graphics.UsedVideo | None] | None = None,
) -> list[str]:
    """Why a render no longer matches the story, one sentence each. `music` is the project, the
    music source and refusal of the next render (`render_music.gate`) and the mix settings.
    `switched` is every presenter shot now on its clip's own voice (`shot_voice_sources`).
    `graphics` is the video each graphic shot uses now (`graphic_videos`).
    """
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
        if isinstance(shot.get("graphic"), dict):
            reasons.extend(graphic_reasons(shot, graphics or {}))
            continue
        now = shots.get((shot.get("scene_id"), shot.get("shot_id")))
        selected = now.selected if now is not None else None
        label = f"The shot {shot.get('shot_id')} of scene {shot.get('scene_index')}"
        if now is None:
            continue  # the scenes' own reason says so
        # FLOW-008: which voice a presenter shot was heard with, against the switch now.
        voice_then = shot.get("voice")
        if voice_then in (story_render_plan.VOICE_TAKE, story_render_plan.VOICE_CLIP):
            voice_now = (
                story_render_plan.VOICE_CLIP
                if (shot.get("scene_id"), shot.get("shot_id")) in switched
                else story_render_plan.VOICE_TAKE
            )
            if voice_now != voice_then:
                reasons.append(
                    f"{label} was switched to the voice of its clip since this video was made."
                    if voice_now == story_render_plan.VOICE_CLIP
                    else f"{label} was switched back to the voice take since this video was made."
                )
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
    reasons.extend(music_reasons(recorded, *music))
    reasons.extend(caption_reasons(recorded, music[0]))
    reasons.extend(callout_reasons(recorded, callouts, wanted=callouts_wanted(music[0])))
    return reasons


def _version_text(engine: object, attempt: object) -> str:
    return f"{shot_graphics.ENGINE_LABELS.get(str(engine), engine)}, attempt {attempt}"


def caption_reasons(recorded: dict[str, Any], project: Project) -> list[str]:
    """Why the captions of a render no longer fit the project's caption mode (CAP-001). Only the
    picture matters: a render is wrong when it burned captions the project no longer wants, or
    has none burned where the project now wants them. A render with no track, in `ytt` mode, is
    right (it just has no caption files).
    """
    track = recorded.get("captions")
    was_burned = isinstance(track, dict) and track.get("burned") is not False
    if was_burned and project.caption_mode == projects.CAPTION_YTT:
        return ["Captions are burned into this video, but the project now uses a caption file."]
    if not was_burned and captions_burned(project):
        return ["The project now burns captions into the video."]
    return []


def graphic_reasons(
    shot: dict[str, Any], graphics: dict[tuple[str, str], shot_graphics.UsedVideo | None]
) -> list[str]:
    """Why the graphic a render used for a shot is not the one the shot uses now (EXG-007)."""
    key = (shot.get("scene_id"), shot.get("shot_id"))
    if key not in graphics:
        return []  # the scenes' own reason says so
    label = f"The graphic of shot {shot.get('shot_id')} of scene {shot.get('scene_index')}"
    used = graphics[key]
    then = shot["graphic"]
    if used is None:
        return [f"{label} has no current video now."]
    if used.attempt.row.id == then.get("id"):
        return []
    return [
        f"{label} changed since this video was made (now "
        f"{_version_text(used.engine, used.attempt.row.attempt)}; this video used "
        f"{_version_text(then.get('engine'), then.get('attempt'))})."
    ]


_LOOK_AGAIN: Final = "The callout look was written again since this video was made."
_THEME_AGAIN: Final = "The graphics look was written again since this video was made."
# How many callouts a render names when their graphics changed (the rest are counted).
_CALLOUTS_NAMED: Final = 5


def _uses(engine: str | None) -> str:
    """How a reason names what a callout is drawn with."""
    if engine is None:
        return "a simple box"
    return f"its {callout_graphics.ENGINE_LABELS.get(engine, engine).lower()} version"


def _same_id(recorded: object, now: int | None) -> bool:
    then = recorded.get("id") if isinstance(recorded, dict) else None
    return then == now


def _motion_reasons(used: dict[str, Any], source: callout_render.CalloutSource) -> list[str]:
    """Why the motion graphics of a render no longer match (§4.8): the callout look or the
    graphics look was written again, or a callout is drawn with another version, or with a newer
    attempt of its version. A render is compared with what it meant to draw (its timeline), not
    with a fallback that happened while it was made (that is a warning on the render).
    """
    reasons: list[str] = []
    if not _same_id(used.get("look"), source.look[0] if source.look else None):
        reasons.append(_LOOK_AGAIN)
    if not _same_id(used.get("theme"), source.theme[0] if source.theme else None):
        reasons.append(_THEME_AGAIN)
    if reasons or source.motion is None:
        # Every graphic is made again then: naming each callout would only repeat it.
        return reasons
    changed: list[str] = []
    for entry in used.get("entries") or []:
        pick = source.motion.get(str(entry.get("id"))) if isinstance(entry, dict) else None
        if pick is None:
            continue  # the plan's own reason says so
        then = entry.get("motion") if isinstance(entry.get("motion"), dict) else None
        then_engine = then.get("engine") if then is not None else None
        parts = entry.get("parts")
        first = parts[0].get("text") if isinstance(parts, list) and parts else entry.get("id")
        label = f'"{first}"'
        now = pick.use
        if then_engine != (now.engine if now is not None else None):
            changed.append(
                f"Callout {label} now uses {_uses(now.engine if now else None)} "
                f"(this video used {_uses(then_engine)})."
            )
        elif now is not None and then is not None and then.get("graphic_id") != now.graphic_id:
            changed.append(
                f"The graphic of callout {label} was made again since this video was made."
            )
    reasons.extend(changed[:_CALLOUTS_NAMED])
    if len(changed) > _CALLOUTS_NAMED:
        reasons.append(f"{len(changed) - _CALLOUTS_NAMED} more callouts changed their graphic.")
    return reasons


def callout_reasons(recorded: dict[str, Any], gate: CalloutGate, *, wanted: bool) -> list[str]:
    """Why the callouts of a render, which are laid over or burned into the picture, no longer
    match (§4.8). The first of the style, the plan and the graphics' own reasons that applies.
    """
    used = recorded.get("callouts") if isinstance(recorded.get("callouts"), dict) else None
    if used is not None and not wanted:
        return ["Callouts have been switched off since this video was made."]
    if used is None and wanted:
        return ["Callouts have been switched on since this video was made."]
    if used is None:
        return []
    if used.get("callout_style", callout_render.STYLE_BOXES) != gate.callout_style:
        return [
            "Callouts are now drawn as motion graphics."
            if gate.callout_style == callout_render.STYLE_MOTION
            else "Callouts are now drawn as simple boxes."
        ]
    if gate.source is None:
        if gate.callout_style == callout_render.STYLE_MOTION:
            return ["The callout plan or the callout graphics of this video are out of date."]
        return ["The callout plan of this video is out of date or no longer ready."]
    if used.get("plan_id") != gate.source.plan_id:
        return [
            f"The callout plan was changed since this video was made (version "
            f"{gate.source.plan_version}; this video used version {used.get('plan_version')})."
        ]
    if gate.callout_style == callout_render.STYLE_MOTION:
        return _motion_reasons(used, gate.source)
    return []


async def _all_renders(session: AsyncSession, project_id: int) -> list[StoryRender]:
    statement = (
        select(StoryRender)
        .where(StoryRender.project_id == project_id)
        .order_by(StoryRender.render_number.desc())
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars())


async def find_render(
    session: AsyncSession, project_id: int, render_number: int
) -> StoryRender | None:
    """The finished render of a project with this number, or None."""
    statement = select(StoryRender).where(
        StoryRender.project_id == project_id, StoryRender.render_number == render_number
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def _jobs_of(session: AsyncSession, rows: list[StoryRender]) -> dict[int, Job]:
    ids = {row.job_id for row in rows if row.job_id is not None}
    if not ids:
        return {}
    statement = select(Job).where(Job.id.in_(ids)).execution_options(populate_existing=True)
    return {job.id: job for job in (await session.execute(statement)).scalars()}


@memoized_state
async def state(session: AsyncSession, project: Project) -> StoryRendersState:
    """Whether the story can be rendered now, what the render would warn about, the newest
    render job and every finished render. Worked out on every read; nothing here is stored.
    """
    plans = await shot_plans.state(session, project)
    takes = await shot_takes.state(session, project)
    speech = speech_by_unit(await speech_synthesis.state(session, project))
    job = await store.latest_job(session, project.id, JOB_TYPE)
    renders = await _all_renders(session, project.id)
    jobs = await _jobs_of(session, renders)

    mix = await mix_settings(session)
    gate = await music_gate(session, project)
    callouts = await callout_gate(session, project)
    switched = await shot_voice_sources.clip_shots(session, project)
    graphics = await graphic_videos(session, project)
    blocked = plans.blocked_reason or takes.blocked_reason
    plan: story_render_plan.RenderPlan | None = None
    if blocked is None and callouts.blocked_reason is not None:
        blocked = callouts.blocked_reason
    if blocked is None:
        plan, blocked = _plan_of(
            project,
            await scene_sources(
                session, project, plans, takes, speech, await caption_timings(session, project)
            ),
            mix,
            gate.source,
            callouts=callouts.source,
        )
    if blocked is None and gate.blocked_reason is not None:
        plan, blocked = None, gate.blocked_reason
    if blocked is None and job is not None and job.status in store.ACTIVE_STATUSES:
        blocked = _ALREADY_RENDERING

    entries: list[RenderEntry] = []
    for row in renders:
        reasons = _render_reasons(
            row,
            plans,
            takes,
            speech,
            (project, gate.source, gate.blocked_reason, mix),
            callouts,
            switched,
            graphics,
        )
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
        music_placement_version=(
            gate.source.placement_version if gate.source is not None else None
        ),
        ambience_enabled=project.ambience_enabled,
        fps=project.fps,
        job=job,
        renders=entries,
    )


@dataclass(frozen=True)
class RenderSources:
    """What the next render would be made from, for a stage that must agree with the render's
    own timeline (music placement, MUSIC-011).
    """

    # The scenes with their shots, speech units and selected takes. Empty when blocked.
    scenes: list[story_render_plan.SceneSource]
    # The frozen timeline the next render would use, or None when it cannot be made.
    plan: story_render_plan.RenderPlan | None
    # Why there is no plan, or None.
    blocked_reason: str | None
    takes: shot_takes.ShotTakesState


async def next_render_sources(session: AsyncSession, project: Project) -> RenderSources:
    """The sources and the frozen timeline of the render that would start now. Reads only; the
    render itself uses the same functions, so the two cannot disagree about where a shot or a
    narration line is.
    """
    plans = await shot_plans.state(session, project)
    takes = await shot_takes.state(session, project)
    blocked = plans.blocked_reason or takes.blocked_reason
    if blocked is not None:
        return RenderSources([], None, blocked, takes)
    speech = speech_by_unit(await speech_synthesis.state(session, project))
    scenes = await scene_sources(session, project, plans, takes, speech)
    # Where the shots and the speech sit does not depend on the music, so the plan is made
    # without it (the placement itself is made from this timeline).
    # ... nor on the captions, which are drawn over the finished picture.
    plan, blocked = _plan_of(project, scenes, story_render_plan.MixSettings(), captions=False)
    return RenderSources(scenes, plan, blocked, takes)


async def timing_sources(session: AsyncSession, project: Project) -> RenderSources:
    """The same as `next_render_sources`, but the timeline lets shots with no clip (or a clip
    that is too short) stand as placeholders of their planned length, so the story's timing is
    known before every clip exists (the provisional music placement, SCN-011). Every second of
    it is the one the full render will have. Reads only.
    """
    plans = await shot_plans.state(session, project)
    takes = await shot_takes.state(session, project)
    blocked = plans.blocked_reason or takes.blocked_reason
    if blocked is not None:
        return RenderSources([], None, blocked, takes)
    speech = speech_by_unit(await speech_synthesis.state(session, project))
    scenes = await scene_sources(session, project, plans, takes, speech)
    try:
        plan = story_render_plan.build_timing_plan(
            scenes, fps=project.fps, width=project.out_width, height=project.out_height
        )
    except story_render_plan.RenderPlanError as exc:
        return RenderSources(scenes, None, str(exc), takes)
    return RenderSources(scenes, plan, None, takes)


# --- Starting a render ----------------------------------------------------------------------


async def start_render(session: AsyncSession, project: Project) -> Job:
    """Queues the job that renders the story, with the timeline as it is now, and commits. If a
    render is already waiting or running, that job is returned. For a new job it also starts the
    YouTube draft and thumbnails, best effort (`_start_youtube_draft`). Raises StoryRendersError.
    """
    active = await store.latest_job(session, project.id, JOB_TYPE)
    if active is not None and active.status in store.ACTIVE_STATUSES:
        await session.commit()
        return active

    plans = await shot_plans.state(session, project)
    takes = await shot_takes.state(session, project)
    speech = speech_by_unit(await speech_synthesis.state(session, project))
    blocked = plans.blocked_reason or takes.blocked_reason
    if blocked is not None:
        raise StoryRendersError(blocked)
    gate = await music_gate(session, project)
    callouts = await callout_gate(session, project)
    if callouts.blocked_reason is not None:
        raise StoryRendersError(callouts.blocked_reason)
    plan, blocked = _plan_of(
        project,
        await scene_sources(
            session, project, plans, takes, speech, await caption_timings(session, project)
        ),
        await mix_settings(session),
        gate.source,
        callouts=callouts.source,
    )
    if plan is None:
        raise StoryRendersError(blocked or "The story cannot be rendered now.")
    if gate.blocked_reason is not None:
        raise StoryRendersError(gate.blocked_reason)

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
        await _start_youtube_draft(session, project, job)
    return job


async def _start_youtube_draft(session: AsyncSession, project: Project, job: Job) -> None:
    """Starts the YouTube draft and the thumbnail work for the render job just queued (F-1,
    YTF-004), so they are ready about when the video is. Best effort: the render job is already
    committed, and any error here is logged and changes nothing about it or about the answer of
    the route or the pipeline. Uploads nothing.
    """
    project_id, job_id = project.id, job.id
    try:
        # Imported here: `youtube_draft` imports this module. The dispatcher imports the
        # handlers, which import the services.
        from app.jobs import dispatcher
        from app.services import youtube_draft

        draft_job_id = await youtube_draft.start_for_render_job(session, project, job)
        if draft_job_id is not None:
            _logger.info(
                "render job %d of project %d: YouTube draft job %d started",
                job_id,
                project_id,
                draft_job_id,
            )
            dispatcher.nudge()
    except Exception:
        _logger.exception(
            "render job %d of project %d: the YouTube draft could not be started",
            job_id,
            project_id,
        )
        # Whatever the draft had begun is dropped; the caller's objects are read again, since a
        # rollback expires them.
        await session.rollback()
        await session.refresh(job)
        await session.refresh(project)


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
