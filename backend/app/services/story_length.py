"""How long a story will be as a finished video, estimated from its words (PHASE-003, D-13).

The estimate is the story's word count divided by a speaking pace, both set on the Settings page
(group "Story"). A story estimated above the limit is flagged, never refused: it can still be
saved. Later stages that read the story use `story_length` to decide whether to warn.

The project page works the same estimate out in the browser while the user types, with the same
rule (`frontend/src/components/story/storyLength.ts`), so keep the two in step.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service

SECONDS_PER_MINUTE = 60


@dataclass(frozen=True)
class StoryLengthPolicy:
    words_per_minute: int
    max_minutes: int


@dataclass(frozen=True)
class StoryLength:
    word_count: int
    estimated_seconds: int
    words_per_minute: int
    limit_seconds: int
    over_limit: bool


async def read_story_length_policy(session: AsyncSession) -> StoryLengthPolicy:
    """The pace and the limit that apply now, read at the moment of use."""
    return StoryLengthPolicy(
        words_per_minute=await settings_service.get_int(session, settings_service.STORY_WPM_KEY),
        max_minutes=await settings_service.get_int(session, settings_service.STORY_MAX_MINUTES_KEY),
    )


def count_words(text: str | None) -> int:
    """The number of words: runs of text between whitespace. No story gives zero."""
    if text is None:
        return 0
    return len(text.split())


def story_length(text: str | None, policy: StoryLengthPolicy) -> StoryLength:
    """The word count, the estimated length in whole seconds, and whether it is over the limit."""
    words = count_words(text)
    # Rounded half up, in whole numbers, so it matches the browser's Math.round. Python's round()
    # rounds halves to the even number, which would differ by a second in rare cases.
    pace = policy.words_per_minute
    estimated_seconds = (2 * words * SECONDS_PER_MINUTE + pace) // (2 * pace)
    limit_seconds = policy.max_minutes * SECONDS_PER_MINUTE
    return StoryLength(
        word_count=words,
        estimated_seconds=estimated_seconds,
        words_per_minute=policy.words_per_minute,
        limit_seconds=limit_seconds,
        over_limit=estimated_seconds > limit_seconds,
    )
