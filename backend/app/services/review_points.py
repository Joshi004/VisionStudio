"""Review points (PHASE-041): the places a project can ask the pipeline to stop and wait.

A review point is a group of the pipeline's steps (`services/story_pipeline.STEPS`). When a
project enables one, a run stops once every step of the group is complete and the run made
something in at least one of them, and goes on when the user presses Continue. Nothing else
changes: the stages make the same artifacts whether or not a point is enabled (Path_ahead.md
Section 40).

This module is pure and imports nothing from the app, so the project rules can use it. The
check that every step named here exists is in `services/story_pipeline.py`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

ReviewPointKey = Literal["story_structure", "images", "scenes", "shot_plans", "shots"]


@dataclass(frozen=True)
class ReviewPoint:
    key: ReviewPointKey
    label: str
    # The keys of the pipeline steps the point waits for. A step is in at most one point.
    steps: tuple[str, ...]


# In the order of the pipeline. None is enabled by default.
REVIEW_POINTS: Final[tuple[ReviewPoint, ...]] = (
    ReviewPoint(
        "story_structure",
        "After story structure",
        ("character_discovery", "environment_discovery", "scene_discovery"),
    ),
    ReviewPoint(
        "images",
        "After character and environment images",
        ("character_images", "environment_definitions"),
    ),
    ReviewPoint("scenes", "After scene definition and events", ("scene_definitions", "events")),
    ReviewPoint("shot_plans", "After shot planning", ("shot_plans",)),
    ReviewPoint("shots", "After generated shots", ("shot_generation",)),
)

REVIEW_POINT_KEYS: Final[tuple[ReviewPointKey, ...]] = tuple(point.key for point in REVIEW_POINTS)
POINTS_BY_KEY: Final[dict[str, ReviewPoint]] = {point.key: point for point in REVIEW_POINTS}
_POINT_OF_STEP: Final[dict[str, ReviewPoint]] = {
    step: point for point in REVIEW_POINTS for step in point.steps
}


def point_of(step_key: str) -> ReviewPoint | None:
    """The review point a step belongs to, or None."""
    return _POINT_OF_STEP.get(step_key)


def normalize(keys: Iterable[object]) -> list[str]:
    """The known keys, in the order of the pipeline, without repeats. Anything else is dropped."""
    wanted = {key for key in keys if isinstance(key, str)}
    return [key for key in REVIEW_POINT_KEYS if key in wanted]


def unknown_keys(keys: Iterable[str]) -> list[str]:
    """The keys that are not review points, in the order given."""
    return [key for key in keys if key not in POINTS_BY_KEY]
