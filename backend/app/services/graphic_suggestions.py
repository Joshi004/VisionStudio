"""Graphic suggestions: words of the story the owner would like to see as a graphic.

Only a continuous explainer with graphics on has them. A suggestion is a hint to the cut
planner, never an order: the planner may decline it, and gives a reason when it does.

A suggestion is `{id, start, end, text}`. `start` and `end` are character positions in the
project's `script_text` (`start` included, `end` not), and `text` is `script_text[start:end]`.
The ranges are whole words, never overlap, and are in story order. Ids are `g1`, `g2`, ... in
that order.

- `normalise` checks what the owner sent and gives the list that is stored.
- `reanchor` keeps the list correct when the story text is edited.
- `take_suggestions` finds which words of a scene's voice take each suggestion covers.

Everything here is pure, so nothing is read from or written to the database.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any, Final

# The most suggestions a project may have.
MAX_SUGGESTIONS: Final = 100

# How far ahead in the scene's text a word of the take is looked for. The scene's text may hold
# words no speech event covers (a heading, for instance), which are skipped over.
_LOOKAHEAD_WORDS: Final = 30

_WORD = re.compile(r"\S+")
_NOT_ALNUM = re.compile(r"[\W_]+")

NOT_FOR_PROJECT_MESSAGE: Final = (
    "Graphic suggestions are only for an explainer with a continuous voice and graphics on."
)
NO_STORY_MESSAGE: Final = "Save the story before suggesting graphics."


class GraphicSuggestionError(ValueError):
    """A list of suggestions that breaks a rule. The message is meant to be shown to the user."""


# --- Checking what the owner sent ---------------------------------------------------------


def _snap(story: str, start: int, end: int) -> tuple[int, int]:
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


def _merge(story: str, ranges: list[tuple[int, int]]) -> list[dict[str, Any]]:
    """The ranges in story order, those that overlap or touch joined, as suggestions with ids."""
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [
        {"id": f"g{number}", "start": start, "end": end, "text": story[start:end]}
        for number, (start, end) in enumerate(merged, start=1)
    ]


def normalise(story: str, entries: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The suggestions to store, from what the owner sent: `[{start, end, text}]`.

    Each range must lie inside the story and must hold the text that was sent with it, which
    catches a story that changed under the owner's feet. Ranges are moved out to whole words,
    then those that overlap or touch are joined. Raises GraphicSuggestionError.
    """
    if len(entries) > MAX_SUGGESTIONS:
        raise GraphicSuggestionError(f"There can be at most {MAX_SUGGESTIONS} suggestions.")
    ranges: list[tuple[int, int]] = []
    for position, entry in enumerate(entries, start=1):
        start, end, text = entry.get("start"), entry.get("end"), entry.get("text")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or not isinstance(text, str)
        ):
            raise GraphicSuggestionError(f"Suggestion {position} is not a range with its text.")
        if not 0 <= start < end <= len(story):
            raise GraphicSuggestionError(f"Suggestion {position} is outside the story.")
        if story[start:end] != text:
            raise GraphicSuggestionError(
                f"Suggestion {position} does not match the story. The story may have changed: "
                "reload it and mark the words again."
            )
        snapped = _snap(story, start, end)
        if snapped[0] < snapped[1]:
            ranges.append(snapped)
    return _merge(story, ranges)


# --- Keeping the suggestions right when the story is edited -------------------------------


def _nearest(story: str, text: str, near: int) -> int | None:
    """The start of the occurrence of `text` in `story` that is closest to `near`, or None."""
    best: int | None = None
    found = story.find(text)
    while found != -1:
        if best is None or abs(found - near) < abs(best - near):
            best = found
        found = story.find(text, found + 1)
    return best


def reanchor(
    new_story: str | None, entries: Sequence[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """The suggestions after the story changed to `new_story`, and how many were dropped.

    A suggestion whose text is still at its place stays. Otherwise it moves to the occurrence of
    its text closest to the old place, and when the text is gone it is dropped. Suggestions that
    end up overlapping are joined, which is not counted as a drop.
    """
    if not new_story or not entries:
        return [], len(entries)
    ranges: list[tuple[int, int]] = []
    dropped = 0
    for entry in entries:
        start, end, text = int(entry["start"]), int(entry["end"]), str(entry["text"])
        if new_story[start:end] != text:
            found = _nearest(new_story, text, start)
            if found is None:
                dropped += 1
                continue
            start, end = found, found + len(text)
        snapped = _snap(new_story, start, end)
        if snapped[0] < snapped[1]:
            ranges.append(snapped)
        else:
            dropped += 1
    return _merge(new_story, ranges), dropped


# --- Finding the words of a scene's take --------------------------------------------------


def _key(word: str) -> str:
    """A word compared the way the event stage compares them: case, punctuation and quote style
    are ignored.
    """
    return _NOT_ALNUM.sub("", word.casefold())


def take_suggestions(
    scene_text: str,
    scene_start: int,
    take_words: Sequence[dict[str, Any]],
    entries: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The suggestions that cover words of a scene's voice take, as `[{id, text, words}]`.

    `scene_text` is the scene's slice of the story and `scene_start` where that slice begins
    in it. `take_words` are the take's words in order (`{text, ...}`), and `words` of a result
    are positions (from 0) in them.

    The take's words are the scene's words, but a heading or similar text may be missing from
    them, and case and punctuation may differ. So the two are walked forward together, and a
    take word that is not found is left out; nothing is raised. A suggestion that covers no
    word of the take is not returned.
    """
    if not entries or not take_words:
        return []
    tokens = [
        (match.start(), match.end(), _key(match.group())) for match in _WORD.finditer(scene_text)
    ]
    covered: dict[str, list[int]] = {}
    cursor = 0
    for position, word in enumerate(take_words):
        wanted = _key(str(word["text"]))
        if not wanted:
            continue
        for index in range(cursor, min(cursor + _LOOKAHEAD_WORDS, len(tokens))):
            begin, stop, key = tokens[index]
            if key != wanted:
                continue
            cursor = index + 1
            for entry in entries:
                if scene_start + begin < entry["end"] and scene_start + stop > entry["start"]:
                    covered.setdefault(entry["id"], []).append(position)
                    break
            break
    return [
        {"id": entry["id"], "text": entry["text"], "words": covered[entry["id"]]}
        for entry in entries
        if entry["id"] in covered
    ]


def fingerprint(suggestions: Sequence[dict[str, Any]]) -> str | None:
    """A short hash of a scene's `take_suggestions`, or None when it has none. A change of the
    words marked, or of the words they cover, changes it.
    """
    if not suggestions:
        return None
    text = json.dumps(list(suggestions), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
