"""Helpers for ranges of the story text (`project.script_text`), shared by everything the owner
marks in the story: the graphic suggestions and the evidence claims.

Positions are character (code point) positions, `start` included and `end` not. Everything here
is pure.
"""

from __future__ import annotations


def snap_to_words(story: str, start: int, end: int) -> tuple[int, int]:
    """The range moved out to whole words: it never begins or ends in the middle of a word, and
    spaces at its ends are left out. Returns an empty range when it holds only spaces.
    """
    while start < end and story[start].isspace():
        start += 1
    while end > start and story[end - 1].isspace():
        end -= 1
    if start == end:
        return start, end
    while start > 0 and not story[start - 1].isspace():
        start -= 1
    while end < len(story) and not story[end].isspace():
        end += 1
    return start, end


def nearest_occurrence(story: str, text: str, near: int) -> int | None:
    """The start of the occurrence of `text` in `story` that is closest to `near`, or None."""
    if not text:
        return None
    best: int | None = None
    found = story.find(text)
    while found != -1:
        if best is None or abs(found - near) < abs(best - near):
            best = found
        found = story.find(text, found + 1)
    return best
