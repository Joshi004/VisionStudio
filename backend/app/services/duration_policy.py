"""The shot-duration policy (PHASE-002, Implementation_phases.md D-8).

Two ranges, both set on the Settings page in whole seconds:

- the *hard bounds*: the shortest and longest shot MiniMax H3 may be asked for. A shot outside
  them never reaches generation. The longest can never pass the GPU server's own limit
  (`frame_counts.H3_MAX_FRAMES`);
- the *planning target*: the range the planning stages are asked to stay inside. It keeps a
  margin inside the hard bounds, and is passed to prompts as parameters, never written into
  prompt text.

`shot_num_frames` is the pure rule that turns a shot length into the frame count to ask H3 for.
The shot lengths a plan stores are moved onto H3's own lengths first (`h3_lengths`, D-9), so for
them it returns exactly the length's frames.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.services.frame_counts import H3_FPS, H3_MAX_FRAMES, h3_num_frames


class DurationPolicyError(ValueError):
    """A shot length or a policy that cannot be used. The message is meant to be shown."""


@dataclass(frozen=True)
class DurationPolicy:
    hard_min_s: int
    hard_max_s: int
    target_min_s: int
    target_max_s: int


async def read_duration_policy(session: AsyncSession) -> DurationPolicy:
    """The policy that applies now, read at the moment of use.

    Raises `DurationPolicyError` when the saved values are out of order, which a reset of one
    setting can cause even though the Settings page refuses such a save.
    """
    values = await settings_service.read_duration_values(session)
    problem = settings_service.duration_order_problem(values)
    if problem is not None:
        raise DurationPolicyError(problem)
    return DurationPolicy(
        hard_min_s=values[settings_service.H3_MIN_SHOT_KEY],
        hard_max_s=values[settings_service.H3_MAX_SHOT_KEY],
        target_min_s=values[settings_service.SHOT_TARGET_MIN_KEY],
        target_max_s=values[settings_service.SHOT_TARGET_MAX_KEY],
    )


def longest_cut_shot_s(policy: DurationPolicy) -> float:
    """The longest a cut-based shot of a continuous explainer may be (FLOW-006): the H3 longest
    shot setting, but never more than the longest clip H3 makes (345 frames). It is also the
    longest window of the take a presenter clip is given.
    """
    return min(float(policy.hard_max_s), H3_MAX_FRAMES / H3_FPS)


def shot_num_frames(target_s: float, policy: DurationPolicy) -> int:
    """The frame count to ask H3 for a shot of `target_s` seconds: the smallest `17n + 5` that
    is at least the target.

    A shot outside the hard bounds is refused, with a message that names the limit.
    """
    if target_s < policy.hard_min_s:
        raise DurationPolicyError(
            f"A shot of {target_s:g} s is shorter than the H3 minimum of {policy.hard_min_s} s "
            "(Settings, Shot duration)."
        )
    if target_s > policy.hard_max_s:
        raise DurationPolicyError(
            f"A shot of {target_s:g} s is longer than the H3 maximum of {policy.hard_max_s} s "
            "(Settings, Shot duration)."
        )
    # Round away float noise first, so 3.0 s is 72 frames and not 72.00000001.
    target_frames = math.ceil(round(target_s * H3_FPS, 6))
    return h3_num_frames(target_frames)
