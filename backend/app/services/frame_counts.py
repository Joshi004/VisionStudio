"""Frame counts for clips (ANALYSIS.md Section 5.3 and 5.5). Pure functions, no I/O.

A scene is a stretch of the voiceover, and its clip must cover it exactly. Two numbers
come out of that:

- the *target*: how many frames the scene lasts on the project's fps grid;
- the *request*: how many frames LTX is asked for, the smallest `8k + 1` at or above the
  target. The tail is trimmed away at render time (Phase 10), at most 7 frames of it.

Scene boundaries are rounded to frame indices first, and a scene's frame count is the
difference between its two boundaries. Rounding every scene's length on its own would let
the errors add up over a long video. Phase 10 uses `target_frames` as well, so the render
and the generation agree on how long a scene is.
"""

from __future__ import annotations

import math
from typing import Final

# The smallest frame count both clip endpoints accept (the approved OpenAPI spec says
# `minimum: 9` for each). `video_generator.frame_limits` reads the real minimum from the spec.
MIN_NUM_FRAMES: Final = 9

_FRAMES_PER_STEP: Final = 8


def boundary_frame(time_s: float, fps: int) -> int:
    """The index of the frame a boundary at `time_s` falls on: the nearest, halves up."""
    return math.floor(time_s * fps + 0.5)


def target_frames(start_s: float, end_s: float, fps: int) -> int:
    """How many frames the scene from `start_s` to `end_s` lasts on the fps grid.

    Consecutive scenes share a boundary, so their frame counts add up to the boundary
    of the last one: the video is as long as the audio to within one frame.
    """
    return boundary_frame(end_s, fps) - boundary_frame(start_s, fps)


def request_num_frames(target: int) -> int:
    """The frame count to ask LTX for: the smallest `8k + 1` that is at least `target`.

    LTX only makes `8k + 1` frames, and rounds anything else to the nearest valid count,
    which could be shorter than the scene. Never below `MIN_NUM_FRAMES`.
    """
    steps = -(-(target - 1) // _FRAMES_PER_STEP)  # ceil without floats
    return max(MIN_NUM_FRAMES, _FRAMES_PER_STEP * steps + 1)
