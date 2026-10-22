"""The plan of a story render (PHASE-028, `Path_ahead.md` Section 33). Pure: no I/O, no clock.

`build_plan` takes what the story workspace already knows (each scene's timeline from PHASE-021
and each shot's selected take from PHASE-027) and turns it into the **frozen timeline** the
`render_story` job reads (`job.input.timeline`). The job reads nothing else, so what happens to
the shots afterwards does not change a render that has been started, and a restart renders the
same thing again.

**Frames.** Shot boundaries are rounded to the frame grid once, at story level, and a shot's frame
count is the difference of its two boundaries (`frame_counts`). The counts add up to the boundary
of the last shot, so the video is as long as the sum of the shot targets to within half a frame.
A shot's length is stored on H3's own length (`h3_lengths`, D-9), so the clip normally has exactly
the frames its shot needs and nothing is cut. At another frame rate than H3's 24 a clip can be one
source frame short; the render repeats its last frame then. The plan checks the clip's frames.

**Audio** (the starting values below are untested by ear and are meant to be tuned):

- *Shot audio*: the sound of each selected clip, over the part its shot uses, is brought toward
  `SHOT_TARGET_LUFS` (`gain_toward`), so a cut does not jump. A clip is boosted by at most
  `MAX_BOOST_DB`.
- *Ducking* (the planning decision, a fixed reduction): wherever narration plays on the story's
  timeline, the shot audio is lowered by `DUCK_DB`, with ramps of `DUCK_RAMP_S` on both sides.
  Two narration spans less than `DUCK_MERGE_GAP_S` apart are one window, unless a line of
  dialogue falls between them, so the sound does not pump between sentences.
- *Narration layer*: only narration units, each at its place on the timeline. Dialogue is only in
  the shot audio, so it is never heard twice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Final

from app.services import frame_counts

# The shape of `job.input.timeline`. The job refuses a timeline it does not know.
TIMELINE_VERSION: Final = 1

SHOT_TARGET_LUFS: Final = -16.0
NARRATION_TARGET_LUFS: Final = -16.0
MAX_BOOST_DB: Final = 6.0
DUCK_DB: Final = -12.0
DUCK_RAMP_S: Final = 0.25
DUCK_MERGE_GAP_S: Final = 1.0

# How many shots a refusal names before it says "and n more".
_NAMED: Final = 5

_MS_PER_S: Final = 1000

# Warning codes.
TAKE_OUT_OF_DATE: Final = "take_out_of_date"
TAKE_WITHOUT_SOUND: Final = "take_without_sound"


class RenderPlanError(ValueError):
    """The story cannot be rendered now. The message is meant to be shown to the user."""


# --- What the plan is made from -------------------------------------------------------------


@dataclass(frozen=True)
class TakeSource:
    """A shot's selected take."""

    take_id: int
    take_number: int
    path: str
    frame_count: int | None
    has_audio: bool
    file_exists: bool
    # Why the take is out of date, one sentence each. Empty when it is current.
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShotSource:
    shot_id: str
    # Where the shot sits in its scene's timeline.
    start_s: float
    end_s: float
    take: TakeSource | None


@dataclass(frozen=True)
class UnitSource:
    """A speech unit on its scene's timeline, and the file of its speech."""

    unit_id: str
    kind: str
    start_s: float
    end_s: float
    # The length that was measured when the shots were planned, and the speech it belongs to.
    seconds: float | None
    audio_id: int | None
    path: str | None
    file_exists: bool


@dataclass(frozen=True)
class SceneSource:
    scene_id: str
    index: int
    title: str
    # Where the scene starts in the story; None when a scene before it has no plan.
    story_start_s: float | None
    # Why the scene's shots cannot go to a render (PHASE-021's `generation_blocked_reason`).
    blocked_reason: str | None
    plan_id: int | None
    plan_version: int | None
    shots: list[ShotSource]
    units: list[UnitSource]


@dataclass(frozen=True)
class RenderPlan:
    timeline: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)


# --- Pure rules -----------------------------------------------------------------------------


def _ms(seconds: float) -> int:
    """Seconds as whole milliseconds. Timeline places are kept to a thousandth of a second, so
    this is exact for them.
    """
    return math.floor(seconds * _MS_PER_S + 0.5)


def frame_at(ms: int, fps: int) -> int:
    """The frame index a boundary at `ms` falls on: the nearest, halves up (`frame_counts`'
    rule, in whole numbers so a half is never lost to float noise).
    """
    return (ms * fps + _MS_PER_S // 2) // _MS_PER_S


def source_frames_needed(frames: int, fps: int) -> int:
    """How many frames of an H3 clip (at its own 24 fps) cover `frames` frames at `fps`."""
    return -(-frames * frame_counts.H3_FPS // fps)


def gain_toward(loudness_lufs: float | None, target_lufs: float, max_boost_db: float) -> float:
    """The gain that brings a sound to `target_lufs`, boosted by at most `max_boost_db` (a louder
    sound is lowered as far as it takes). A sound that could not be measured keeps its own
    level. The job passes the values the timeline recorded, so a render always uses its own.
    """
    if loudness_lufs is None:
        return 0.0
    return min(max_boost_db, target_lufs - loudness_lufs)


def duck_windows(
    narration: list[tuple[float, float]],
    dialogue: list[tuple[float, float]],
    merge_gap_s: float,
) -> list[tuple[float, float]]:
    """The stretches of the story in which the shot audio is lowered: the narration spans, with
    two of them made one when they are less than `merge_gap_s` apart and no line of dialogue is
    heard between them. Times are story seconds.
    """
    merged: list[tuple[float, float]] = []
    for start, end in sorted(narration):
        if merged:
            previous_start, previous_end = merged[-1]
            gap_has_dialogue = any(
                line_start < start and line_end > previous_end for line_start, line_end in dialogue
            )
            if start - previous_end < merge_gap_s and not gap_has_dialogue:
                merged[-1] = (previous_start, max(previous_end, end))
                continue
        merged.append((start, end))
    return merged


def slice_windows(
    windows: list[tuple[float, float]], start_s: float, end_s: float, ramp_s: float
) -> list[list[float]]:
    """The windows that touch a shot (a ramp counts), in the shot's own time, which starts at 0."""
    sliced: list[list[float]] = []
    for start, end in windows:
        if end + ramp_s <= start_s or start - ramp_s >= end_s:
            continue
        sliced.append([round(start - start_s, 3), round(end - start_s, 3)])
    return sliced


def constants() -> dict[str, float]:
    """The audio values a render used, recorded on it (D-3)."""
    return {
        "shot_target_lufs": SHOT_TARGET_LUFS,
        "narration_target_lufs": NARRATION_TARGET_LUFS,
        "max_boost_db": MAX_BOOST_DB,
        "duck_db": DUCK_DB,
        "duck_ramp_s": DUCK_RAMP_S,
        "duck_merge_gap_s": DUCK_MERGE_GAP_S,
    }


# --- The plan -------------------------------------------------------------------------------


def _named(items: list[str]) -> str:
    shown = ", ".join(items[:_NAMED])
    return shown if len(items) <= _NAMED else f"{shown} and {len(items) - _NAMED} more"


def _scene_label(scene: SceneSource) -> str:
    """The scene as a sentence starts with it. Not `str.capitalize`, which would lower the
    title's own capitals.
    """
    return f"Scene {scene.index} ({scene.title})"


def _check_scenes(scenes: list[SceneSource]) -> None:
    if not scenes:
        raise RenderPlanError("There are no scenes yet.")
    for scene in scenes:
        if scene.blocked_reason is not None:
            raise RenderPlanError(f"{_scene_label(scene)}: {scene.blocked_reason}")
        if scene.story_start_s is None or not scene.shots:
            raise RenderPlanError(f"{_scene_label(scene)} has no shots yet.")


def _check_takes(scenes: list[SceneSource]) -> None:
    """Every shot needs a selected take whose file is there."""
    without_clip: list[str] = []
    missing_file: list[str] = []
    for scene in scenes:
        for shot in scene.shots:
            label = f"{shot.shot_id} of scene {scene.index}"
            if shot.take is None:
                without_clip.append(label)
            elif not shot.take.file_exists:
                missing_file.append(label)
    if without_clip:
        raise RenderPlanError(
            f"These shots have no clip yet: {_named(without_clip)}. Generate them first."
        )
    if missing_file:
        raise RenderPlanError(
            f"The clip file of these shots is missing: {_named(missing_file)}. Generate them again."
        )


def build_plan(scenes: list[SceneSource], *, fps: int, width: int, height: int) -> RenderPlan:
    """The frozen timeline of a render and its warnings. Raises RenderPlanError with the reason
    when the story cannot be rendered now.
    """
    if fps < 1 or width < 2 or height < 2:
        raise RenderPlanError("The project's output size or frame rate is not usable.")
    _check_scenes(scenes)
    _check_takes(scenes)

    shots: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    too_short: list[str] = []
    narration: list[dict[str, Any]] = []
    narration_spans: list[tuple[float, float]] = []
    dialogue_spans: list[tuple[float, float]] = []
    unplaced: list[str] = []
    cursor = 0  # the frame the last shot ended on

    for scene in scenes:
        assert scene.story_start_s is not None  # `_check_scenes` made sure
        for shot in scene.shots:
            take = shot.take
            assert take is not None  # `_check_takes` made sure
            start_ms = _ms(scene.story_start_s + shot.start_s)
            end_ms = _ms(scene.story_start_s + shot.end_s)
            start_frame = cursor
            end_frame = frame_at(end_ms, fps)
            frames = end_frame - start_frame
            cursor = end_frame
            label = f"{shot.shot_id} of scene {scene.index}"
            if frames < 1:
                raise RenderPlanError(f"The shot {label} lasts less than one frame.")
            needed = source_frames_needed(frames, fps)
            # One source frame short is allowed: the render repeats the last frame (D-9).
            if take.frame_count is None or take.frame_count < needed - 1:
                have = "an unreadable number of" if take.frame_count is None else take.frame_count
                too_short.append(f"{label} has {have} frames, needs {needed}")
            if take.reasons:
                warnings.append(
                    {
                        "code": TAKE_OUT_OF_DATE,
                        "scene_id": scene.scene_id,
                        "shot_id": shot.shot_id,
                        "message": f"The shot {label} uses take {take.take_number}, which is "
                        f"out of date: {' '.join(take.reasons)}",
                    }
                )
            if not take.has_audio:
                warnings.append(
                    {
                        "code": TAKE_WITHOUT_SOUND,
                        "scene_id": scene.scene_id,
                        "shot_id": shot.shot_id,
                        "message": f"The clip of the shot {label} (take {take.take_number}) "
                        "has no sound, so the shot is silent.",
                    }
                )
            shots.append(
                {
                    "scene_id": scene.scene_id,
                    "shot_id": shot.shot_id,
                    "scene_index": scene.index,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "start_frame": start_frame,
                    "frames": frames,
                    "take_id": take.take_id,
                    "take_number": take.take_number,
                    "path": take.path,
                    "source_frames": needed,
                    "has_audio": take.has_audio,
                    "duck": [],  # filled in below, once every narration span is known
                }
            )
        for unit in scene.units:
            start_s = scene.story_start_s + unit.start_s
            end_s = scene.story_start_s + unit.end_s
            if unit.kind == "dialogue":
                dialogue_spans.append((start_s, end_s))
                continue
            if unit.audio_id is None or unit.path is None or unit.seconds is None:
                unplaced.append(f"{unit.unit_id} of scene {scene.index}")
                continue
            if not unit.file_exists:
                unplaced.append(f"{unit.unit_id} of scene {scene.index}")
                continue
            narration_spans.append((start_s, end_s))
            narration.append(
                {
                    "scene_id": scene.scene_id,
                    "unit_id": unit.unit_id,
                    "audio_id": unit.audio_id,
                    "path": unit.path,
                    "start_ms": _ms(start_s),
                    "seconds": unit.seconds,
                }
            )

    if too_short:
        raise RenderPlanError(
            f"A clip is shorter than its shot: {_named(too_short)}. Regenerate it, or select "
            "another take."
        )
    if unplaced:
        raise RenderPlanError(
            f"The speech of these narration units is missing: {_named(unplaced)}. Make it again."
        )

    windows = duck_windows(narration_spans, dialogue_spans, DUCK_MERGE_GAP_S)
    for shot_entry in shots:
        shot_entry["duck"] = slice_windows(
            windows,
            shot_entry["start_frame"] / fps,
            (shot_entry["start_frame"] + shot_entry["frames"]) / fps,
            DUCK_RAMP_S,
        )

    timeline: dict[str, Any] = {
        "version": TIMELINE_VERSION,
        "fps": fps,
        "width": width,
        "height": height,
        "total_frames": cursor,
        "scenes": [
            {
                "scene_id": scene.scene_id,
                "index": scene.index,
                "title": scene.title,
                "story_start_s": scene.story_start_s,
                "plan_id": scene.plan_id,
                "plan_version": scene.plan_version,
            }
            for scene in scenes
        ],
        "shots": shots,
        "narration": narration,
        "constants": constants(),
        "warnings": warnings,
    }
    return RenderPlan(timeline=timeline, warnings=warnings)
