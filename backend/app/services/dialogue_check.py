"""The dialogue check of a generated take (PHASE-031, `Path_ahead.md` Sections 21 and 32).

The audio that comes back from H3 is used as it is, so this is how the app finds out that a
dialogue shot really contains its lines. Parakeet transcribes the take's clip, and the words it
heard are compared with the words of the shot's dialogue lines.

Pure rules, no I/O: the lines, the heard words and the threshold go in, a `DialogueResult` comes
out. `jobs/check_take_dialogue.py` calls Parakeet and stores the result on the take
(`shot_take.dialogue_check`).

How the comparison works:

- Both sides are **normalized**: Unicode NFKC, lower case, apostrophes dropped, every other
  punctuation mark and symbol turned into a space. "Don't go upstairs!" and "dont go upstairs"
  are the same words.
- The words of every line, in the order of the shot, are joined and compared with every word that
  was heard, with `difflib.SequenceMatcher`. The **similarity** is its ratio in percent: a missing
  word, a wrong word and extra speech all lower it.
- The check passes when the similarity is at least the `dialogue_match_threshold` setting. A clip
  where nothing was heard always fails (`no_speech`), whatever the threshold is.

Only the words are judged: when a line starts, and which voice says it, are not (PHASE-045).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Final

from app.providers.transcriber import SpokenWord

VERSION: Final = 1

NO_SPEECH: Final = "no_speech"
DIALOGUE_MISMATCH: Final = "dialogue_mismatch"

# Marks that are dropped, not turned into a space, so "don't" becomes "dont".
_APOSTROPHES: Final = frozenset("'\u2019\u2018\u02bc\u0060")


@dataclass(frozen=True)
class DialogueLine:
    """One dialogue line the shot carries, as its generation request names it."""

    unit_id: str
    label: str
    text: str
    starts_in_shot_seconds: float


@dataclass(frozen=True)
class Problem:
    code: str
    message: str


@dataclass(frozen=True)
class DialogueResult:
    passed: bool
    # In percent, 0 to 100, one decimal.
    similarity: float
    problems: list[Problem]
    expected_words: list[str]
    heard_words: list[str]

    def to_json(
        self,
        lines: Sequence[DialogueLine],
        spoken: Sequence[SpokenWord],
        *,
        threshold: int,
        checked_at: datetime,
    ) -> dict[str, Any]:
        """The value stored in `shot_take.dialogue_check`. `kind` is `clip` when it failed: a
        new take can fix it, so it is retried like any failed clip.
        """
        return {
            "version": VERSION,
            "passed": self.passed,
            "kind": None if self.passed else "clip",
            "similarity": self.similarity,
            "threshold": threshold,
            "checked_at": checked_at.isoformat(),
            "problems": [{"code": p.code, "message": p.message} for p in self.problems],
            "lines": [
                {
                    "unit_id": line.unit_id,
                    "label": line.label,
                    "text": line.text,
                    "starts_in_shot_seconds": line.starts_in_shot_seconds,
                }
                for line in lines
            ],
            "expected_text": " ".join(self.expected_words),
            "heard_text": " ".join(self.heard_words),
            "heard_words": [
                {"word": word.word, "start": word.start, "end": word.end} for word in spoken
            ],
        }


def normalize_words(text: str) -> list[str]:
    """The words of a text for comparison: NFKC, lower case, apostrophes dropped, any other
    character that is not a letter, a digit or a combining mark turned into a space.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    kept: list[str] = []
    for char in folded:
        if char in _APOSTROPHES:
            continue
        if char.isalnum() or unicodedata.category(char).startswith("M"):
            kept.append(char)
        else:
            kept.append(" ")
    return "".join(kept).split()


def lines_of(audios: object) -> list[DialogueLine]:
    """The dialogue lines in a generation request's `audios` (or in the `lines_as_json` form that
    a take records), in the order they are sent. An entry without text is skipped. Anything that
    is not a list gives no lines.
    """
    if not isinstance(audios, list):
        return []
    lines: list[DialogueLine] = []
    for audio in audios:
        if not isinstance(audio, dict):
            continue
        text = audio.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        start = audio.get("starts_in_shot_seconds")
        lines.append(
            DialogueLine(
                unit_id=str(audio.get("unit_id", "")),
                label=str(audio.get("label", "")),
                text=text.strip(),
                starts_in_shot_seconds=(
                    float(start)
                    if isinstance(start, int | float) and not isinstance(start, bool)
                    else 0.0
                ),
            )
        )
    return lines


def lines_as_json(lines: Sequence[DialogueLine]) -> list[dict[str, Any]]:
    """What `shot_take.inputs.dialogue` records, so a take knows what it was meant to say."""
    return [
        {
            "unit_id": line.unit_id,
            "label": line.label,
            "text": line.text,
            "starts_in_shot_seconds": line.starts_in_shot_seconds,
        }
        for line in lines
    ]


def compare(
    lines: Sequence[DialogueLine], spoken: Sequence[SpokenWord], threshold: int
) -> DialogueResult:
    """Judges what was heard against the lines. `threshold` is a percent, 0 to 100.

    Lines with no words at all (only punctuation) leave nothing to check, so the take passes.
    """
    expected: list[str] = []
    for line in lines:
        expected.extend(normalize_words(line.text))
    heard: list[str] = []
    for word in spoken:
        heard.extend(normalize_words(word.word))

    if not expected:
        return DialogueResult(True, 100.0, [], expected, heard)
    if not heard:
        return DialogueResult(
            False,
            0.0,
            [Problem(NO_SPEECH, "No speech was heard in the clip.")],
            expected,
            heard,
        )

    ratio = SequenceMatcher(None, expected, heard, autojunk=False).ratio()
    similarity = round(ratio * 100, 1)
    if similarity >= threshold:
        return DialogueResult(True, similarity, [], expected, heard)
    return DialogueResult(
        False,
        similarity,
        [
            Problem(
                DIALOGUE_MISMATCH,
                f"The speech in the clip matches the dialogue by {similarity:g}%; "
                f"{threshold}% is needed. Heard: \u201c{' '.join(heard)}\u201d. "
                f"Expected: \u201c{' '.join(expected)}\u201d.",
            )
        ],
        expected,
        heard,
    )


def passed(dialogue_check: Any) -> bool:
    """Whether a stored `shot_take.dialogue_check` says the dialogue passed. False for NULL."""
    return isinstance(dialogue_check, dict) and dialogue_check.get("passed") is True
