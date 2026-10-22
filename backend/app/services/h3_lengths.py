"""Shot lengths on the lengths MiniMax H3 really makes (D-9). Pure functions: no I/O, no clock.

H3 makes clips of `17n + 5` frames at 24 fps: 0.916 s, 1.625 s, 2.333 s, 3.041 s, 3.75 s, ... A shot
planned at any other length used to be asked for at the next size up, and the render cut the
extra frames off the end of the clip, which could cut off spoken words. Instead, the plan itself is
moved onto H3's lengths when it is saved, so the timeline, the narration, the generation request
and the render all use the length the clip really has, and the render has nothing to cut.

A length is stored rounded **down** to a whole millisecond (`(frames * 1000) // 24`), so
converting it back to frames (`ceil(seconds * 24)`) gives exactly `17n + 5` again.

`fit_shots` moves every shot of one scene:

1. Each shot goes to the nearest H3 length. A shot inside the planning target range stays inside
   it; a shot outside the hard bounds is left as it is, so the timeline checks still report it
   and the scene is planned again as before.
2. If that creates a timeline problem the planned lengths did not have (for example a line of
   dialogue that no longer fits), every shot of the scene goes to the next H3 length **up**
   instead. Shots only get longer, so no line or narration loses room.
3. If rounding up creates new problems too, the nearest lengths are kept, and the usual checks
   and automatic re-plans deal with them.

This module calls `scene_timeline`, which is why it is not part of `duration_policy`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from app.services import scene_timeline
from app.services.duration_policy import DurationPolicy
from app.services.frame_counts import H3_FPS, H3_MAX_FRAMES

_FRAMES_PER_STEP: Final = 17
_BASE_FRAMES: Final = 5
_MS_PER_S: Final = 1000

Mode = Literal["planned", "nearest", "up"]


def _length_s(frames: int) -> float:
    """The stored length of a clip of `frames` frames: seconds, rounded down to a millisecond."""
    return (frames * _MS_PER_S // H3_FPS) / _MS_PER_S


def grid_lengths(policy: DurationPolicy) -> list[float]:
    """Every length H3 makes inside the hard bounds, shortest first, as they are stored."""
    longest_frames = min(policy.hard_max_s * H3_FPS, H3_MAX_FRAMES)
    shortest_frames = policy.hard_min_s * H3_FPS
    lengths: list[float] = []
    steps = 1
    while True:
        frames = _FRAMES_PER_STEP * steps + _BASE_FRAMES
        if frames > longest_frames:
            break
        if frames >= shortest_frames:
            lengths.append(_length_s(frames))
        steps += 1
    return lengths


def _candidates(
    requested_s: float, grid: list[float], policy: DurationPolicy
) -> list[float] | None:
    """The H3 lengths a shot of `requested_s` may take, or None when it is outside the hard
    bounds and so is left alone. A shot inside the planning target range stays inside it, unless
    no H3 length is inside it.
    """
    if requested_s < policy.hard_min_s or requested_s > policy.hard_max_s:
        return None
    if policy.target_min_s <= requested_s <= policy.target_max_s:
        inside = [length for length in grid if policy.target_min_s <= length <= policy.target_max_s]
        if inside:
            return inside
    return grid


def _nearest(requested_s: float, candidates: list[float]) -> float:
    """The candidate closest to the request; the longer one on a tie."""
    return min(candidates, key=lambda length: (abs(length - requested_s), -length))


def _up(requested_s: float, candidates: list[float]) -> float:
    """The shortest candidate that is at least the request, else the nearest."""
    longer = [length for length in candidates if length >= requested_s]
    return min(longer) if longer else _nearest(requested_s, candidates)


def _moved(
    shots: list[dict[str, Any]], grid: list[float], policy: DurationPolicy, mode: Mode
) -> list[dict[str, Any]]:
    moved: list[dict[str, Any]] = []
    for shot in shots:
        requested = float(shot["target_duration"])
        candidates = _candidates(requested, grid, policy)
        if candidates is None:
            length = requested
        elif mode == "up":
            length = _up(requested, candidates)
        else:
            length = _nearest(requested, candidates)
        moved.append({**shot, "target_duration": length})
    return moved


def _problem_keys(
    shots: list[dict[str, Any]], units: list[scene_timeline.UnitInfo], policy: DurationPolicy
) -> set[tuple[str, str | None, str | None]]:
    """What is wrong with a plan, as (code, shot, unit), so two plans can be compared even though
    the numbers in their messages differ.
    """
    timeline = scene_timeline.build_timeline(shots, units, policy)
    return {(problem.code, problem.shot_id, problem.unit_id) for problem in timeline.problems}


@dataclass(frozen=True)
class FitResult:
    shots: list[dict[str, Any]]
    # `nearest` or `up`: how the lengths were moved. `planned`: nothing could be moved (the policy
    # has no H3 length inside its bounds), so the shots are as they were.
    mode: Mode


def fit_shots(
    shots: list[dict[str, Any]],
    units: list[scene_timeline.UnitInfo],
    policy: DurationPolicy,
) -> FitResult:
    """The shots of one scene with their `target_duration` moved onto H3's lengths.

    `shots` is the checked list (each has `id`, `speech_unit_ids` and `target_duration`), `units`
    the scene's speech units with their measured lengths. The shots given are not changed.
    """
    grid = grid_lengths(policy)
    if not grid:
        return FitResult(shots=shots, mode="planned")

    known = _problem_keys(shots, units, policy)
    nearest = _moved(shots, grid, policy, "nearest")
    if _problem_keys(nearest, units, policy) <= known:
        return FitResult(shots=nearest, mode="nearest")
    up = _moved(shots, grid, policy, "up")
    if _problem_keys(up, units, policy) <= known:
        return FitResult(shots=up, mode="up")
    return FitResult(shots=nearest, mode="nearest")
