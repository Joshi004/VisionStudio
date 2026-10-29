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
  that are turned on in its current callout plan, and is refused without one (`_callout_gate`):
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
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, Project, SpeechUnitAudio, SpeechWordTiming, StoryRender
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    callout_plan,
    callout_plan_writer,
    callout_render,
    caption_plan,
    cut_planning_writer,
    provenance,
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


def captions_wanted(project: Project) -> bool:
    """Whether the render draws captions: an explainer with its captions switch on. A story
    never does (E-10).
    """
    return project.kind == KIND_EXPLAINER and project.captions


def callouts_wanted(project: Project) -> bool:
    """Whether the render draws callouts: an explainer with its callouts switch on."""
    return callout_plan.wanted(project)


async def _caption_timings(
    session: AsyncSession, project: Project
) -> dict[int, SpeechWordTiming] | None:
    """The stored word timing of every speech of the project, by the speech's audio id, or None
    when the render has neither captions nor callouts (a story is never read for timings).
    """
    if not captions_wanted(project) and not callouts_wanted(project):
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
                file_exists=audio is not None and _file_exists(audio.path),
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
    exists = _file_exists(audio.path)
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
            if continuous and entry.row is not None:
                presenter_ids = {
                    str(shot["id"])
                    for shot in entry.row.content["shots"]
                    if shot.get("type") == shot_voice_sources.PRESENTER_TYPE
                }
            for span in entry.timeline.shots:
                take_entry = shots_by_scene.get(scene_id, {}).get(span.shot_id)
                shots.append(
                    story_render_plan.ShotSource(
                        shot_id=span.shot_id,
                        start_s=span.start_s,
                        end_s=span.end_s,
                        take=_take_source(take_entry),
                        presenter=span.shot_id in presenter_ids,
                        clip_voice=(scene_id, span.shot_id) in switched,
                    )
                )
            if continuous:
                assert clock is not None and clock.audio is not None and entry.row is not None
                units = _voice_units(entry, clock)
                voice = story_render_plan.VoiceSource(
                    audio_id=clock.audio.id,
                    path=clock.audio.path,
                    seconds=float(clock.audio.duration_s or 0.0),
                    file_exists=_file_exists(clock.audio.path),
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


async def _music_gate(session: AsyncSession, project: Project) -> Any:
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
                if captions and captions_wanted(project)
                else None
            ),
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


async def _callout_gate(session: AsyncSession, project: Project) -> CalloutGate:
    """Whether the next render has callouts, and if it must, whether it can. It must have the
    current callout plan (the owner's choice): a render is refused, never made without them.
    """
    if not callouts_wanted(project):
        return CalloutGate(None, None)
    state = await callout_plan.state(session, project)
    if state.job is not None and state.job.status in store.ACTIVE_STATUSES:
        return CalloutGate(
            None, f"The callout plan is being written. Wait for it to finish. {_CALLOUT_WAY_OUT}"
        )
    if state.latest is None:
        return CalloutGate(None, f"There is no callout plan yet. {_CALLOUT_WAY_OUT}")
    if state.blocked_reason is not None:
        return CalloutGate(None, f"{state.blocked_reason} {_CALLOUT_WAY_OUT}")
    if state.out_of_date:
        return CalloutGate(
            None, f"The callout plan is out of date: {state.reasons[0]} {_CALLOUT_WAY_OUT}"
        )
    content = state.latest.content
    return CalloutGate(
        callout_render.CalloutSource(
            plan_id=state.latest.id,
            plan_version=state.latest.version,
            accent=str(content["accent"]["colour"]),
            callouts=tuple(callout_plan_writer.enabled_callouts(content)),
        ),
        None,
    )


# --- Reading the state ----------------------------------------------------------------------


_MIX_CONSTANTS: Final = (
    "music_duck_low_db",
    "music_duck_medium_db",
    "bed_shot_duck_db",
)
_MASTER_CONSTANTS: Final = ("master_lufs", "master_true_peak_db")


def _music_reasons(
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
        reasons.append("Music has been placed since this video was made.")
    elif used is not None and source is not None:
        if used.get("placement_id") != source.placement_id:
            reasons.append(
                f"The music was placed again since this video was made (version "
                f"{source.placement_version}; this video used version "
                f"{used.get('placement_version')})."
            )
        if used.get("ambience") != source.ambience:
            reasons.append("The ambience switch has changed since this video was made.")

    # A video made before the final loudness (timeline version 1) has no recorded settings.
    constants = recorded.get("constants") if isinstance(recorded.get("constants"), dict) else {}
    now = story_render_plan.constants(mix)
    keys = _MASTER_CONSTANTS if used is None else (*_MIX_CONSTANTS, *_MASTER_CONSTANTS)
    if any(key in constants and constants[key] != now[key] for key in keys):
        reasons.append("A mix or loudness setting has changed since this video was made.")
    return reasons


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
) -> list[str]:
    """Why a render no longer matches the story, one sentence each. `music` is the project, the
    music source and refusal of the next render (`render_music.gate`) and the mix settings.
    `switched` is every presenter shot now on its clip's own voice (`shot_voice_sources`).
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
    reasons.extend(_music_reasons(recorded, *music))
    # The captions are burned into the picture, so a changed switch needs a new render.
    if isinstance(recorded.get("captions"), dict) != captions_wanted(music[0]):
        reasons.append("The captions setting has changed since this video was made.")
    reasons.extend(_callout_reasons(recorded, callouts, wanted=callouts_wanted(music[0])))
    return reasons


def _callout_reasons(recorded: dict[str, Any], gate: CalloutGate, *, wanted: bool) -> list[str]:
    """Why the callouts of a render, which are burned into the picture, no longer match."""
    used = recorded.get("callouts") if isinstance(recorded.get("callouts"), dict) else None
    if used is not None and not wanted:
        return ["Callouts have been switched off since this video was made."]
    if used is None and wanted:
        return ["Callouts have been switched on since this video was made."]
    if used is None:
        return []
    if gate.source is None:
        return ["The callout plan of this video is out of date or no longer ready."]
    if used.get("plan_id") != gate.source.plan_id:
        return [
            f"The callout plan was changed since this video was made (version "
            f"{gate.source.plan_version}; this video used version {used.get('plan_version')})."
        ]
    return []


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


@memoized_state
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

    mix = await mix_settings(session)
    gate = await _music_gate(session, project)
    callouts = await _callout_gate(session, project)
    switched = await shot_voice_sources.clip_shots(session, project)
    blocked = plans.blocked_reason or takes.blocked_reason
    plan: story_render_plan.RenderPlan | None = None
    if blocked is None and callouts.blocked_reason is not None:
        blocked = callouts.blocked_reason
    if blocked is None:
        plan, blocked = _plan_of(
            project,
            await _scene_sources(
                session, project, plans, takes, speech, await _caption_timings(session, project)
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
    speech = _speech_by_unit(await speech_synthesis.state(session, project))
    scenes = await _scene_sources(session, project, plans, takes, speech)
    # Where the shots and the speech sit does not depend on the music, so the plan is made
    # without it (the placement itself is made from this timeline).
    # ... nor on the captions, which are drawn over the finished picture.
    plan, blocked = _plan_of(project, scenes, story_render_plan.MixSettings(), captions=False)
    return RenderSources(scenes, plan, blocked, takes)


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
    gate = await _music_gate(session, project)
    callouts = await _callout_gate(session, project)
    if callouts.blocked_reason is not None:
        raise StoryRendersError(callouts.blocked_reason)
    plan, blocked = _plan_of(
        project,
        await _scene_sources(
            session, project, plans, takes, speech, await _caption_timings(session, project)
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
