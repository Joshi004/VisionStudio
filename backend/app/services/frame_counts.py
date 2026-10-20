"""Frame counts for clips (ANALYSIS.md Section 5.3 and 5.5). Pure functions, no I/O.

A clip must cover the stretch of the video it is for exactly. Two numbers come out of that:

- the *target*: how many frames the stretch lasts on the fps grid;
- the *request*: how many frames a model is asked for. LTX is asked for the smallest `8k + 1`
  at or above the target, and MiniMax H3 for the smallest `17n + 5`. The tail is trimmed away
  at render time.

Boundaries are rounded to frame indices first, and a stretch's frame count is the difference
between its two boundaries. Rounding every length on its own would let the errors add up over
a long video, so the render and the generation both use `target_frames`.
"""

from __future__ import annotations

import math
from typing import Final

# The smallest frame count both clip endpoints accept (the approved OpenAPI spec says
# `minimum: 9` for each). `video_generator.frame_limits` reads the real minimum from the spec.
MIN_NUM_FRAMES: Final = 9

_FRAMES_PER_STEP: Final = 8

# MiniMax H3 runs at a fixed 24 fps and only decodes `17n + 5` frames. The GPU server's guide
# documents 124 (5.17 s) to 345 (14.4 s) frames and clamps to that range itself, but PHASE-001
# showed shorter clips work. The labs do not enforce a minimum, so the server's real answer
# shows; the shot-duration policy (`duration_policy`) sets the minimum the story pipeline uses.
# The maximum is the longest clip the server makes.
H3_FPS: Final = 24
H3_MAX_FRAMES: Final = 345
_H3_FRAMES_PER_STEP: Final = 17
_H3_BASE_FRAMES: Final = 5


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


def h3_num_frames(target: int) -> int:
    """The frame count to ask MiniMax H3 for: the smallest `17n + 5` (n at least 1) that is at
    least `target`.

    H3 rounds any other count up on its own, so asking for the exact grid keeps the stored
    request equal to what runs. There is no minimum or maximum here: a count the GPU server
    does not accept is refused by the server, and its message is shown on the run.
    """
    steps = max(1, -(-(target - _H3_BASE_FRAMES) // _H3_FRAMES_PER_STEP))  # ceil without floats
    return _H3_FRAMES_PER_STEP * steps + _H3_BASE_FRAMES
