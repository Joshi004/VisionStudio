"""The technical check of a generated take (PHASE-029, `Path_ahead.md` Section 32).

Pure rules, no I/O: what was measured on the clip and what was asked for go in, a `Validation`
comes out. The callers (`jobs/generate_shot.py` and `jobs/check_shot_takes.py`) measure the clip
with ffprobe and a full decode (`services/ffmpeg.py`) and store the result on the take.

Two kinds of problem, because they have different cures:

- `clip`: the clip itself is bad (it cannot be read or decoded, it has no sound, its size or its
  number of frames is not what was asked for, it is shorter than its shot's target). Another run
  with another seed can fix it, so it is retried automatically (`shot_takes.queue_retry`).
- `plan`: the shot's own target is outside the H3 hard bounds now. Another seed cannot fix that:
  the scene's shots have to be planned again (PHASE-021 already shows it), so nothing is retried.

H3 renders exactly the number of frames it is asked for (PHASE-001 V1), so the frame count must
match the request exactly. The duration policy is read at the moment of use, so a take made
under old settings is judged by the settings that apply now.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from app.services.duration_policy import DurationPolicy
from app.services.frame_counts import H3_FPS, H3_MAX_FRAMES

VERSION: Final = 1

Kind = Literal["clip", "plan"]

UNREADABLE: Final = "unreadable"
DECODE_ERROR: Final = "decode_error"
NO_AUDIO: Final = "no_audio"
WRONG_SIZE: Final = "wrong_size"
WRONG_FRAME_COUNT: Final = "wrong_frame_count"
TOO_SHORT: Final = "too_short"
OUTSIDE_HARD_BOUNDS: Final = "outside_hard_bounds"

# The problems that another seed cannot fix.
PLAN_CODES: Final = frozenset({OUTSIDE_HARD_BOUNDS})


@dataclass(frozen=True)
class Measured:
    """What was found on the clip. Every number is None when it could not be read."""

    frame_count: int | None
    width: int | None
    height: int | None
    duration_s: float | None
    has_audio: bool
    # False when ffprobe could not read the file at all.
    readable: bool = True
    # The first decoding error, or None when the clip decodes to the end.
    decode_problem: str | None = None


@dataclass(frozen=True)
class Expected:
    """What the take was asked for."""

    num_frames: int
    width: int
    height: int
    fps: int
    target_seconds: float


@dataclass(frozen=True)
class Problem:
    code: str
    message: str


@dataclass(frozen=True)
class Validation:
    passed: bool
    kind: Kind | None
    problems: list[Problem]

    def to_json(
        self, measured: Measured, expected: Expected, *, checked_at: datetime
    ) -> dict[str, Any]:
        """The value stored in `shot_take.validation`."""
        return {
            "version": VERSION,
            "passed": self.passed,
            "kind": self.kind,
            "checked_at": checked_at.isoformat(),
            "problems": [{"code": p.code, "message": p.message} for p in self.problems],
            "measured": {
                "frame_count": measured.frame_count,
                "width": measured.width,
                "height": measured.height,
                "duration_s": measured.duration_s,
                "has_audio": measured.has_audio,
            },
            "expected": {
                "num_frames": expected.num_frames,
                "width": expected.width,
                "height": expected.height,
                "fps": expected.fps,
                "target_seconds": expected.target_seconds,
            },
        }


def _plan_problems(expected: Expected, policy: DurationPolicy) -> list[Problem]:
    problems: list[Problem] = []
    target = expected.target_seconds
    if target < policy.hard_min_s:
        problems.append(
            Problem(
                OUTSIDE_HARD_BOUNDS,
                f"The shot's target of {target:g} s is shorter than the H3 minimum of "
                f"{policy.hard_min_s} s. Plan the scene's shots again.",
            )
        )
    elif target > policy.hard_max_s:
        problems.append(
            Problem(
                OUTSIDE_HARD_BOUNDS,
                f"The shot's target of {target:g} s is longer than the H3 maximum of "
                f"{policy.hard_max_s} s. Plan the scene's shots again.",
            )
        )
    elif expected.num_frames > H3_MAX_FRAMES:
        problems.append(
            Problem(
                OUTSIDE_HARD_BOUNDS,
                f"The request asked for {expected.num_frames} frames, more than the "
                f"{H3_MAX_FRAMES} the GPU server makes. Plan the scene's shots again.",
            )
        )
    return problems


def _clip_problems(measured: Measured, expected: Expected) -> list[Problem]:
    if not measured.readable:
        return [Problem(UNREADABLE, "The clip could not be read.")]
    problems: list[Problem] = []
    if measured.decode_problem is not None:
        problems.append(
            Problem(DECODE_ERROR, f"The clip does not decode to the end: {measured.decode_problem}")
        )
    if not measured.has_audio:
        problems.append(Problem(NO_AUDIO, "The clip has no sound."))
    if measured.width != expected.width or measured.height != expected.height:
        found = (
            f"{measured.width}x{measured.height}"
            if measured.width is not None and measured.height is not None
            else "an unknown size"
        )
        problems.append(
            Problem(
                WRONG_SIZE,
                f"The clip is {found}; {expected.width}x{expected.height} was requested.",
            )
        )
    if measured.frame_count != expected.num_frames:
        found = (
            "an unknown number of" if measured.frame_count is None else str(measured.frame_count)
        )
        problems.append(
            Problem(
                WRONG_FRAME_COUNT,
                f"The clip has {found} frames; {expected.num_frames} were requested.",
            )
        )
    needed = math.ceil(round(expected.target_seconds * expected.fps, 6))
    if measured.frame_count is not None and measured.frame_count < needed:
        problems.append(
            Problem(
                TOO_SHORT,
                f"The clip has {measured.frame_count} frames, fewer than the {needed} its "
                f"{expected.target_seconds:g} s shot needs.",
            )
        )
    return problems


def validate(measured: Measured, expected: Expected, policy: DurationPolicy) -> Validation:
    """Judges one clip. `kind` is `plan` when the shot's own length is out of bounds (no retry),
    else `clip` when the clip has a problem, else None (passed).
    """
    plan = _plan_problems(expected, policy)
    clip = _clip_problems(measured, expected)
    problems = plan + clip
    if plan:
        return Validation(passed=False, kind="plan", problems=problems)
    if clip:
        return Validation(passed=False, kind="clip", problems=problems)
    return Validation(passed=True, kind=None, problems=[])


def expected_of(
    *,
    take_inputs: dict[str, Any],
    request_body: dict[str, Any] | None,
    request_content: dict[str, Any] | None,
) -> Expected | None:
    """What a take was asked for. The numbers come from the body that was sent when it is still
    known, else from the generation request the take was made from. None when neither says.
    """
    body = request_body or {}
    content = request_content or {}

    def pick(key: str) -> Any:
        return body.get(key) if body.get(key) is not None else content.get(key)

    num_frames = pick("num_frames") or take_inputs.get("num_frames")
    width, height = pick("width"), pick("height")
    target = take_inputs.get("target_seconds")
    if target is None:
        target = content.get("target_seconds")
    if not all(isinstance(value, int) and value > 0 for value in (num_frames, width, height)):
        return None
    if isinstance(target, bool) or not isinstance(target, int | float):
        return None
    # H3 has no frame rate in its body: it always runs at 24 fps.
    return Expected(
        num_frames=num_frames,
        width=width,
        height=height,
        fps=H3_FPS,
        target_seconds=float(target),
    )


def passed(validation: Any) -> bool:
    """Whether a stored `shot_take.validation` says the take passed. False for NULL."""
    return isinstance(validation, dict) and validation.get("passed") is True
