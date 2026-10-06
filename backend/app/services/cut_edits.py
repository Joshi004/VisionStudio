"""Editing cuts by hand (ANALYSIS.md Section 5.2, "Review step in the UI"). Pure functions.

A cut is named by the number of the last word of the scene it ends (`scene_cuts.Cut`), so a
cut "after word k" sits in the gap between word k and word k+1. There are three edits:

- add a cut in a gap that has none, which splits one scene in two;
- remove a cut, which merges the two scenes beside it;
- move a cut to another gap, within the two scenes beside it.

The end of the script is not a cut a person can place: the last scene always ends with the
last word. A cut the user adds or moves is a `manual` cut. The cut at the other end of each
rebuilt scene keeps its source. Every rebuilt scene loses its note, because a note such as
"longer than the maximum" described the scene as it was.

Each function returns the new list of cuts and says which scenes it changed, so the caller
rebuilds those and leaves the rest alone. Nothing here limits how long a scene may be: a
scene outside the project's limits only shows a warning (Phase 7 decision).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.services.scene_cuts import Cut, Word


class CutEditError(ValueError):
    """An edit that cannot be made. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class CutEdit:
    # Every cut after the edit.
    cuts: list[Cut]
    # Position of the first scene the edit changes.
    first: int
    # How many scenes there were in the changed range before the edit...
    old_count: int
    # ...and how many replace them.
    new_count: int


def _quoted(words: Sequence[Word], k: int) -> str:
    return f"\u201c{words[k].text}\u201d"


def _check_word(words: Sequence[Word], k: int) -> None:
    if not 0 <= k < len(words):
        raise CutEditError(f"The script has no word number {k}.")


def _position_of_cut(cuts: Sequence[Cut], k: int) -> int | None:
    for position, cut in enumerate(cuts):
        if cut.last_word == k:
            return position
    return None


def _without_note(cut: Cut) -> Cut:
    return replace(cut, note=None)


def add_cut(words: Sequence[Word], cuts: Sequence[Cut], after_word: int) -> CutEdit:
    """Splits the scene that holds the gap after word `after_word` in two.

    The left part is ended by the new manual cut. The right part keeps the cut that ended
    the scene before.
    """
    _check_word(words, after_word)
    if after_word == len(words) - 1:
        raise CutEditError("There is no gap after the last word of the script.")
    if _position_of_cut(cuts, after_word) is not None:
        raise CutEditError(f"There is already a cut after {_quoted(words, after_word)}.")

    # The scene that holds the gap is ended by the first cut after it. Because there is no
    # cut after `after_word` itself, both parts of the split have at least one word.
    position = next(i for i, cut in enumerate(cuts) if cut.last_word > after_word)
    result = list(cuts)
    result[position] = _without_note(result[position])
    result.insert(position, Cut(last_word=after_word, source="manual"))
    return CutEdit(cuts=result, first=position, old_count=1, new_count=2)


def remove_cut(words: Sequence[Word], cuts: Sequence[Cut], after_word: int) -> CutEdit:
    """Merges the two scenes beside the cut. The merged scene is ended by the later cut."""
    _check_word(words, after_word)
    if after_word == len(words) - 1:
        raise CutEditError("The end of the script is not a cut, so it cannot be removed.")
    position = _position_of_cut(cuts, after_word)
    if position is None:
        raise CutEditError(f"There is no cut after {_quoted(words, after_word)}.")

    result = list(cuts)
    del result[position]
    result[position] = _without_note(result[position])
    return CutEdit(cuts=result, first=position, old_count=2, new_count=1)


def move_cut(
    words: Sequence[Word], cuts: Sequence[Cut], after_word: int, to_after_word: int
) -> CutEdit:
    """Moves the cut after word `after_word` to the gap after word `to_after_word`.

    It can only move between the cuts on either side of it, so the two scenes beside it
    keep at least one word each. To go further, remove the cut and add another.
    """
    _check_word(words, after_word)
    _check_word(words, to_after_word)
    if after_word == len(words) - 1:
        raise CutEditError("The end of the script is not a cut, so it cannot be moved.")
    position = _position_of_cut(cuts, after_word)
    if position is None:
        raise CutEditError(f"There is no cut after {_quoted(words, after_word)}.")
    if to_after_word == after_word:
        raise CutEditError("The cut is already there.")

    earlier = cuts[position - 1].last_word if position > 0 else -1
    later = cuts[position + 1].last_word
    if not earlier < to_after_word < later:
        raise CutEditError(
            "A cut can only move within the two scenes beside it, which run from "
            f"{_quoted(words, earlier + 1)} to {_quoted(words, later)}. "
            "To go further, remove the cut and add another."
        )

    result = list(cuts)
    result[position] = Cut(last_word=to_after_word, source="manual")
    result[position + 1] = _without_note(result[position + 1])
    return CutEdit(cuts=result, first=position, old_count=2, new_count=2)
