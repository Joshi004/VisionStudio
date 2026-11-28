"""Where in a stored video a footage clip starts (FTG-005,
`Footage_broll_implementation_phases.md` §4.7, "The cut rules code applies").

A video piece is cut to the length it has on screen. The part of the stored video it may use is
`use` (seconds of that video). The rules, starting values to tune by eye:

- A clip never shows a cut in its first or last `EDGE_S` seconds: a flash of the previous shot is
  the worst mistake.
- A clip starts at least `CUT_SETTLE_FRAMES` frames after a cut and ends at least that many frames
  before the next one, because some cuts are short dissolves.
- Inside `use`, the clip is placed so that the agent's `moment_s` is as near its middle as these
  rules allow. A video with no moment (an owner's own video) starts at the start of `use`, moved
  only as far as the rules need.
- The clip is never slowed down, sped up or looped.

Pure: no I/O. Every candidate start is on the output frame grid, counted from the start of `use`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

EDGE_S: Final = 0.5
CUT_SETTLE_FRAMES: Final = 3
# Float noise allowed when times are compared.
_EPSILON: Final = 1e-6
_DECIMALS: Final = 3


@dataclass(frozen=True)
class Start:
    """The chosen start in seconds of the stored video. `cut_in_clip` is true when no start
    satisfied every rule, so the clip may show a cut near its first or last frame."""

    start_s: float
    cut_in_clip: bool


def _valid(start_s: float, length_s: float, cuts: Sequence[float], fps: int) -> bool:
    """No cut in the first or last `EDGE_S` of the clip, none within `CUT_SETTLE_FRAMES` frames
    before the start or after the end."""
    settle = CUT_SETTLE_FRAMES / fps
    edge = max(EDGE_S, settle)
    end_s = start_s + length_s
    for cut in cuts:
        if start_s - settle < cut < start_s + edge - _EPSILON:
            return False
        if end_s - edge + _EPSILON < cut < end_s + settle:
            return False
    return True


def choose_start(
    use_start_s: float,
    use_end_s: float,
    length_s: float,
    moment_s: float | None,
    cuts: Sequence[float],
    fps: int,
) -> Start:
    """The start of a clip of `length_s` seconds inside `use_start_s` to `use_end_s`.

    The target is the start that puts `moment_s` in the middle of the clip, or `use_start_s` when
    there is no moment, kept inside `use`. The nearest start on the frame grid that satisfies the
    rules wins; the earlier one when two are as near. When `use` is not longer than the clip, the
    clip starts at `use_start_s` (the cut rules cannot move it). Raises ValueError for a use that
    has no length or a clip with no length.
    """
    if fps < 1 or length_s <= 0 or use_end_s <= use_start_s:
        raise ValueError("A clip needs a length and a part of the video to use.")
    last_start = use_end_s - length_s
    if last_start <= use_start_s + _EPSILON:
        start = use_start_s
        return Start(round(start, _DECIMALS), not _valid(start, length_s, cuts, fps))

    target = use_start_s if moment_s is None else moment_s - length_s / 2
    target = min(max(target, use_start_s), last_start)
    count = math.floor((last_start - use_start_s) * fps + _EPSILON)
    best: float | None = None
    best_gap = math.inf
    for step in range(count + 1):
        candidate = use_start_s + step / fps
        if not _valid(candidate, length_s, cuts, fps):
            continue
        gap = abs(candidate - target)
        if gap < best_gap - _EPSILON:
            best, best_gap = candidate, gap
    if best is None:
        # No start follows every rule: the grid start nearest the target, flagged.
        step = min(count, max(0, round((target - use_start_s) * fps)))
        return Start(round(use_start_s + step / fps, _DECIMALS), True)
    return Start(round(best, _DECIMALS), False)
