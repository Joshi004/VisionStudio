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

**Music** (timeline version 2, MUSIC-012). When the project has a current music placement
(`MusicSource`), the timeline also holds every placed sound with everything the mixer needs, in
the sound's own seconds (its time 0 is the first sample it plays):

- *Ducking*: the score and the ambience beds are lowered under narration and dialogue, by the
  depth of the cue's own mix note (`under_voice`: low or medium, two settings). Where a cue's mix
  lets the sound swell in the gaps between lines (`swell_in_gaps`), a gap of `MUSIC_GAP_RELEASE_S`
  releases the duck; otherwise only a gap of `MUSIC_GAP_HOLD_S` does, so the music holds steady.
- *Dips*: the score and the beds dip by `DIP_DB` around every placed hit, point sound and every
  sound the video model makes for a cue, so a swell never hides the thump the scene depends on.
- *Swells*: a placement's `mix_requests` (a bed swell that covers a join) raise the beds playing at
  that second by `SWELL_DB`.
- *The video model's sound under a bed* (MD-17): the shot audio is lowered by a setting wherever a
  bed plays, never during a line of dialogue. The setting is 0 (off) until the owner tunes it.

**Captions** (timeline version 3, EXPLAINER-008). For an explainer with captions on, `captions`
holds the style and the caption groups made by `caption_plan.build_captions` from each speech's
word timing (narration and dialogue alike), on the story's timeline. It is null otherwise.

`master` holds the loudness the finished mix is brought to. Every constant used is recorded.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from app.services import caption_plan, frame_counts, render_commands

# The shape of `job.input.timeline`. The job refuses a timeline it does not know. Version 2 adds
# the music layers, the dip of the shot audio under a bed and the master loudness (MUSIC-012).
# Version 3 adds `captions`: the word-synced captions of an explainer, or null (EXPLAINER-008).
TIMELINE_VERSION: Final = 3

SHOT_TARGET_LUFS: Final = -16.0
NARRATION_TARGET_LUFS: Final = -16.0
MAX_BOOST_DB: Final = 6.0
DUCK_DB: Final = -12.0
DUCK_RAMP_S: Final = 0.25
DUCK_MERGE_GAP_S: Final = 1.0

# --- The music in the mix (MUSIC-012). Starting values, untested by ear, to be tuned. ----------
# The ramps of the music's duck under a voice, longer than the shot audio's, so music breathes.
MUSIC_DUCK_RAMP_S: Final = 0.4
# A gap between two spoken stretches this long lets music that may swell come back up.
MUSIC_GAP_RELEASE_S: Final = 1.0
# ... and this long for music that must hold steady.
MUSIC_GAP_HOLD_S: Final = 4.0
# A short dip around a sound the scene depends on: from DIP_BEFORE_S before to DIP_AFTER_S after.
DIP_DB: Final = -6.0
DIP_BEFORE_S: Final = 0.15
DIP_AFTER_S: Final = 0.5
DIP_RAMP_S: Final = 0.08
# A bed's swell that covers a join.
SWELL_DB: Final = 4.0
SWELL_RAMP_S: Final = 0.5
# The ramps of the shot audio's lowering under a bed.
BED_SHOT_RAMP_S: Final = 1.0
# loudnorm's loudness range, wide so a quiet story keeps its dynamics (linear mode).
MASTER_LRA: Final = 20.0

LANE_SCORE: Final = "score"
LANE_BED: Final = "bed"
LANE_SOUNDS: Final = "sounds"
_LANES: Final = (LANE_SCORE, LANE_BED, LANE_SOUNDS)
_POINT_KIND: Final = "point"
UNDER_VOICE_LOW: Final = "low"

# How many shots a refusal names before it says "and n more".
_NAMED: Final = 5

_MS_PER_S: Final = 1000

# Warning codes.
TAKE_OUT_OF_DATE: Final = "take_out_of_date"
TAKE_WITHOUT_SOUND: Final = "take_without_sound"
# A speech has no stored word timing, so its captions use estimated times (EXPLAINER-008).
CAPTION_TIMING_ESTIMATED: Final = "caption_timing_estimated"


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
class WordTimingSource:
    """The time of each script word of a speech, for the captions (EXPLAINER-007's
    `speech_word_timing`): `(word, start_s, end_s)` in seconds from the start of the file.
    `estimated_now` is True when no timing was stored and the times were estimated for this
    render, which the plan warns about.
    """

    words: tuple[tuple[str, float, float], ...]
    estimated_now: bool = False


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
    # Only for an explainer whose captions are on: the word timing of the speech.
    timing: WordTimingSource | None = None


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
class MixSettings:
    """The settings of the mix, in whole dB and LUFS (`core/settings.py`, MUSIC-012)."""

    loudness_lufs: int = -14
    true_peak_db: int = -1
    duck_low_db: int = -18
    duck_medium_db: int = -10
    # 0 leaves the shot audio alone under a bed.
    bed_shot_duck_db: int = 0


@dataclass(frozen=True)
class MusicSource:
    """The current music placement a render is made with (MUSIC-011's `music_placement.content`)
    and what the cues' own mix notes say.
    """

    placement_id: int
    placement_version: int
    # `music_placement.content`: samples at 48 kHz on this render's own timeline.
    content: dict[str, Any]
    # By cue id: how far under the voice the cue sits (`low` or `medium`), and whether it may
    # swell in the gaps between lines.
    cue_mix: dict[str, tuple[str, bool]]
    # Whether beds and point sounds are in the render (the project's ambience switch).
    ambience: bool = True


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


def merge_spans(spans: Sequence[tuple[float, float]], gap_s: float) -> list[tuple[float, float]]:
    """The spans in order, with two made one when they overlap or are less than `gap_s` apart."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if merged and (start <= merged[-1][1] or start - merged[-1][1] < gap_s):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract_spans(
    spans: Sequence[tuple[float, float]], removed: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    """What is left of `spans` once every span of `removed` is taken out."""
    holes = merge_spans(removed, 0.0)
    left: list[tuple[float, float]] = []
    for start, end in merge_spans(spans, 0.0):
        cursor = start
        for hole_start, hole_end in holes:
            if hole_end <= cursor or hole_start >= end:
                continue
            if hole_start > cursor:
                left.append((cursor, hole_start))
            cursor = max(cursor, hole_end)
        if cursor < end:
            left.append((cursor, end))
    return left


def constants(mix: MixSettings | None = None) -> dict[str, float]:
    """The audio values a render used, recorded on it (D-3)."""
    mix = mix or MixSettings()
    return {
        "shot_target_lufs": SHOT_TARGET_LUFS,
        "narration_target_lufs": NARRATION_TARGET_LUFS,
        "max_boost_db": MAX_BOOST_DB,
        "duck_db": DUCK_DB,
        "duck_ramp_s": DUCK_RAMP_S,
        "duck_merge_gap_s": DUCK_MERGE_GAP_S,
        "music_duck_low_db": float(mix.duck_low_db),
        "music_duck_medium_db": float(mix.duck_medium_db),
        "music_duck_ramp_s": MUSIC_DUCK_RAMP_S,
        "music_gap_release_s": MUSIC_GAP_RELEASE_S,
        "music_gap_hold_s": MUSIC_GAP_HOLD_S,
        "dip_db": DIP_DB,
        "dip_before_s": DIP_BEFORE_S,
        "dip_after_s": DIP_AFTER_S,
        "dip_ramp_s": DIP_RAMP_S,
        "swell_db": SWELL_DB,
        "swell_ramp_s": SWELL_RAMP_S,
        "bed_shot_duck_db": float(mix.bed_shot_duck_db),
        "bed_shot_ramp_s": BED_SHOT_RAMP_S,
        "master_lufs": float(mix.loudness_lufs),
        "master_true_peak_db": float(mix.true_peak_db),
        "master_lra": MASTER_LRA,
    }


def master(mix: MixSettings) -> dict[str, float]:
    """The loudness the finished mix is brought to."""
    return {
        "target_lufs": float(mix.loudness_lufs),
        "true_peak_db": float(mix.true_peak_db),
        "lra": MASTER_LRA,
    }


# --- The music layers -----------------------------------------------------------------------


def _fade(raw: object, length: int) -> dict[str, Any]:
    """A placement's fade as the timeline records it, never longer than the sound."""
    fade = raw if isinstance(raw, dict) else {}
    samples = fade.get("samples")
    shape = fade.get("shape")
    return {
        "samples": max(0, min(samples if isinstance(samples, int) else 0, length)),
        "shape": shape if shape in ("linear", "equal_power") else "linear",
    }


def _windows_of(
    windows: Sequence[tuple[float, float]], start_s: float, end_s: float, ramp_s: float
) -> list[list[float]]:
    return slice_windows(list(windows), start_s, end_s, ramp_s)


def _music_timeline(
    music: MusicSource,
    mix: MixSettings,
    speech_spans: Sequence[tuple[float, float]],
    dialogue_spans: Sequence[tuple[float, float]],
    total_samples: int,
) -> tuple[dict[str, Any], list[tuple[float, float]]]:
    """The `music` part of the timeline, and the spans of the story (seconds) in which a bed
    plays. Raises RenderPlanError for a placement this version cannot read.
    """
    content = music.content
    rate = content.get("sample_rate")
    placements = content.get("placements")
    if rate != render_commands.SAMPLE_RATE or not isinstance(placements, list):
        raise RenderPlanError(
            "The music placement is not one this version can render. Place again."
        )
    rate_f = float(rate)

    kept: list[dict[str, Any]] = []
    left_out: list[dict[str, str]] = []
    for placed in placements:
        lane, kind = placed.get("lane"), placed.get("kind")
        if lane not in _LANES:
            raise RenderPlanError("The music placement is not one this version can render.")
        if not music.ambience and (lane == LANE_BED or kind == _POINT_KIND):
            left_out.append({"item_id": str(placed["item_id"]), "reason": "ambience is off"})
            continue
        start = int(placed["story_start_sample"])
        if start >= total_samples or int(placed["length_samples"]) < 1:
            left_out.append({"item_id": str(placed["item_id"]), "reason": "outside the video"})
            continue
        kept.append(placed)

    # The moments the music must make room for: placed hits and point sounds, and the sounds the
    # video model makes for a cue.
    moments = [
        int(placed["moment"]["moment_sample"]) / rate_f for placed in kept if placed.get("moment")
    ]
    moments += [float(item["chosen_s"]) for item in content.get("h3_sounds") or []]
    dips = merge_spans([(t - DIP_BEFORE_S, t + DIP_AFTER_S) for t in moments], 0.0)

    swells = [
        (float(item["second"]), float(item["second"]) + float(item["length_s"]))
        for item in content.get("mix_requests") or []
        if item.get("kind") == "swell"
    ]
    holds = {
        True: merge_spans(speech_spans, MUSIC_GAP_RELEASE_S),
        False: merge_spans(speech_spans, MUSIC_GAP_HOLD_S),
    }

    sounds: list[dict[str, Any]] = []
    bed_spans: list[tuple[float, float]] = []
    for placed in kept:
        lane = str(placed["lane"])
        start = int(placed["story_start_sample"])
        source_in = int(placed["source_in_sample"])
        length = min(int(placed["length_samples"]), total_samples - start)
        start_s, end_s = start / rate_f, (start + length) / rate_f
        musical = lane in (LANE_SCORE, LANE_BED)
        if lane == LANE_BED:
            bed_spans.append((start_s, end_s))

        duck: list[list[float]] = []
        duck_db: float | None = None
        dip: list[list[float]] = []
        bumps: list[list[float]] = []
        if musical:
            under, may_swell = music.cue_mix.get(str(placed["cue_id"]), (UNDER_VOICE_LOW, False))
            duck = _windows_of(holds[may_swell], start_s, end_s, MUSIC_DUCK_RAMP_S)
            if duck:
                duck_db = float(mix.duck_low_db if under == UNDER_VOICE_LOW else mix.duck_medium_db)
            dip = _windows_of(dips, start_s, end_s, DIP_RAMP_S)
        if lane == LANE_BED:
            bumps = _windows_of(
                [(a, b) for a, b in swells if start_s <= a <= end_s], start_s, end_s, SWELL_RAMP_S
            )
        sounds.append(
            {
                "item_id": str(placed["item_id"]),
                "cue_id": str(placed["cue_id"]),
                "lane": lane,
                "kind": str(placed["kind"]),
                "path": str(placed["path"]),
                "start_sample": start,
                "in_sample": source_in,
                "length_samples": length,
                "gain_db": float(placed.get("match_gain_db") or 0.0),
                "fade_in": _fade(placed.get("fade_in"), length),
                "fade_out": _fade(placed.get("fade_out"), length),
                "duck": duck,
                "duck_db": duck_db,
                "dips": dip,
                "bumps": bumps,
            }
        )

    timeline = {
        "placement_id": music.placement_id,
        "placement_version": music.placement_version,
        "ambience": music.ambience,
        "total_samples": total_samples,
        "sounds": sounds,
        "left_out": left_out,
    }
    return timeline, bed_spans


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


def build_plan(
    scenes: list[SceneSource],
    *,
    fps: int,
    width: int,
    height: int,
    mix: MixSettings | None = None,
    music: MusicSource | None = None,
    captions: caption_plan.CaptionStyle | None = None,
) -> RenderPlan:
    """The frozen timeline of a render and its warnings. Raises RenderPlanError with the reason
    when the story cannot be rendered now. `music` is None for a render without music, and
    `captions` is None for a render without captions (a story, or an explainer with them off).
    """
    mix = mix or MixSettings()
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
    timed_units: list[caption_plan.TimedUnit] = []
    estimated_units: list[str] = []
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
                    "bed_duck": [],  # and every bed
                }
            )
        for unit in scene.units:
            start_s = scene.story_start_s + unit.start_s
            end_s = scene.story_start_s + unit.end_s
            # Captions follow the speech of a narration and of a line of dialogue alike. A line
            # of dialogue is in its clip at the place its unit has on the timeline.
            if (
                captions is not None
                and unit.timing is not None
                and unit.audio_id is not None
                and unit.file_exists
            ):
                timed_units.append(
                    caption_plan.TimedUnit(
                        scene_id=scene.scene_id,
                        unit_id=unit.unit_id,
                        audio_id=unit.audio_id,
                        start_ms=_ms(start_s),
                        words=unit.timing.words,
                    )
                )
                if unit.timing.estimated_now:
                    estimated_units.append(f"{unit.unit_id} of scene {scene.index}")
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

    music_entry: dict[str, Any] | None = None
    if music is not None:
        music_entry, bed_spans = _music_timeline(
            music,
            mix,
            [*narration_spans, *dialogue_spans],
            dialogue_spans,
            render_commands.sample_count(cursor, fps),
        )
        if mix.bed_shot_duck_db < 0:
            # The video model's own sound is lowered under a bed, but never in a line of dialogue.
            lowered = subtract_spans(bed_spans, dialogue_spans)
            for shot_entry in shots:
                shot_entry["bed_duck"] = slice_windows(
                    lowered,
                    shot_entry["start_frame"] / fps,
                    (shot_entry["start_frame"] + shot_entry["frames"]) / fps,
                    BED_SHOT_RAMP_S,
                )

    captions_entry: dict[str, Any] | None = None
    if captions is not None:
        groups = caption_plan.build_captions(timed_units, captions, _ms(cursor / fps))
        captions_entry = caption_plan.track_dict(captions, groups)
        captions_entry["estimated_units"] = estimated_units
        if estimated_units:
            warnings.append(
                {
                    "code": CAPTION_TIMING_ESTIMATED,
                    "message": "The words of these speeches are not timed yet, so their captions "
                    f"use estimated times: {_named(estimated_units)}.",
                }
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
        "music": music_entry,
        "captions": captions_entry,
        "master": master(mix),
        "constants": constants(mix),
        "warnings": warnings,
    }
    return RenderPlan(timeline=timeline, warnings=warnings)
