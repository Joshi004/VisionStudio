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
  where nothing was heard fails (`no_speech`), whatever the threshold is, except for a line that
  is one word or only interjections: that take passes as "speech not verifiable" (SCN-001).

**Fair matching (SCN-001, version 2).** The similarity is worked out again after each step of
`services/dialogue_matching.py`, and the take passes at the first step that reaches the
threshold: `exact`, `numbers` ("six", "6", "fifteen percent", "15%"), `spelling` ("tyre",
"tire") and `homophones` ("too", "two"). A line of four words or fewer also passes under the
short-line rule (`short_line`): one word for one word that is close in letters. The step that
passed is stored as `rule`, and the kind of result as `outcome`.

Only the words are judged: when a line starts, and which voice says it, are not (PHASE-045).

**A presenter shot of a continuous explainer (FLOW-007)** has one line, the words of the shot
itself, and its clip was made from a window of the scene's take that runs past the shot's end
(the render trims that tail, so it is never shown). The line then has `heard_until_s`, the shot's
length, and only the heard words whose middle (start plus end, halved) is before it are compared:
a word that straddles the end counts when most of it is inside the shot.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Final

from app.providers.transcriber import SpokenWord
from app.services import dialogue_matching

VERSION: Final = 3

NO_SPEECH: Final = "no_speech"
DIALOGUE_MISMATCH: Final = "dialogue_mismatch"
SPEECH_NOT_VERIFIABLE: Final = "speech_not_verifiable"
EXTRA_SPEECH: Final = "extra_speech"
SPEECH_IN_SILENT_SHOT: Final = "speech_in_silent_shot"

# What kind of answer a check gave.
MATCHED: Final = "matched"
CLOSE_MATCH: Final = "close_match"
NOT_VERIFIABLE: Final = "not_verifiable"
MISMATCH: Final = "mismatch"
# SCN-009: the lines were said but more words were heard outside their time.
EXTRA_SPEECH_OUTCOME: Final = "extra_speech"
# SCN-009: a silent shot with no words heard (passed), or with words heard (failed).
SILENT: Final = "silent"
SPEECH_HEARD: Final = "speech_heard"

# What was checked: the words of the shot's lines, or the silence of a shot with no lines.
MODE_DIALOGUE: Final = "dialogue"
MODE_SILENT: Final = "silent"

# SCN-009: a line's own time in the clip runs from its start minus the lead to its end plus the
# tail. Words heard outside every line's time are "extra speech" once there are enough of them
# (filler sounds are not counted, `dialogue_matching.FILLERS`).
LINE_LEAD_S: Final = 0.3
LINE_TAIL_S: Final = 0.7
EXTRA_SPEECH_MIN_WORDS: Final = 2
# Words (not fillers) a silent shot may have before it fails.
SILENT_WORDS_ALLOWED: Final = 0
# Why it passed, in the order the steps are tried. `short_line` and `not_verifiable` follow them.
RULES: Final = ("exact", "numbers", "spelling", "homophones")
SHORT_LINE_RULE: Final = "short_line"
NOT_VERIFIABLE_RULE: Final = "not_verifiable"

# Marks that are dropped, not turned into a space, so "don't" becomes "dont".
_APOSTROPHES: Final = frozenset("'\u2019\u2018\u02bc\u0060")


@dataclass(frozen=True)
class DialogueLine:
    """One dialogue line the shot carries, as its generation request names it."""

    unit_id: str
    label: str
    text: str
    starts_in_shot_seconds: float
    # FLOW-007: the end of the part of the clip that is shown, in seconds from the clip's start.
    # Words heard after it are not compared. None: the whole clip counts.
    heard_until_s: float | None = None
    # SCN-009: how long the line's audio lasts, in seconds. None (a take made before this phase,
    # or a window of a scene's take): the line has no time window of its own.
    duration_s: float | None = None


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
    # SCN-001: `matched`, `close_match`, `not_verifiable`, `mismatch` or `no_speech`.
    outcome: str = MATCHED
    # The step at which the take passed (`RULES`, `short_line`, `not_verifiable`); None if failed.
    rule: str | None = None
    # Both sides after every matching step, which is what the same-answer test compares.
    matched_expected: list[str] = field(default_factory=list)
    matched_heard: list[str] = field(default_factory=list)
    # SCN-009: `dialogue` or `silent`; the words heard outside every line's time (not fillers);
    # and the time window used for each line, `(unit_id, from_s, to_s)`.
    mode: str = MODE_DIALOGUE
    extra_words: list[str] = field(default_factory=list)
    windows: list[tuple[str, float, float]] = field(default_factory=list)

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
            "lines": [_line_json(line) for line in lines],
            "expected_text": " ".join(self.expected_words),
            "heard_text": " ".join(self.heard_words),
            "outcome": self.outcome,
            "rule": self.rule,
            "matched_expected": " ".join(self.matched_expected),
            "matched_heard": " ".join(self.matched_heard),
            "mode": self.mode,
            "extra_text": " ".join(self.extra_words),
            "windows": [
                {"unit_id": unit_id, "from_s": from_s, "to_s": to_s}
                for unit_id, from_s, to_s in self.windows
            ],
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


def _number(value: object) -> float | None:
    """`value` as a float when it is a number (not a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def lines_of(audios: object) -> list[DialogueLine]:
    """The dialogue lines in a generation request's `audios` (or in the `lines_as_json` form that
    a take records), in the order they are sent. An entry without text is skipped. Anything that
    is not a list gives no lines.

    An audio that is the window of a scene's take (`window`, FLOW-007) is one line with the
    shot's own words, whatever words the window holds, and `heard_until_s` set to the shot's
    length.
    """
    if not isinstance(audios, list):
        return []
    lines: list[DialogueLine] = []
    for audio in audios:
        if not isinstance(audio, dict):
            continue
        window = audio.get("window")
        text = window.get("shown_text") if isinstance(window, dict) else audio.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        heard_until = (
            _number(window.get("shot_seconds"))
            if isinstance(window, dict)
            else _number(audio.get("heard_until_s"))
        )
        start = _number(audio.get("starts_in_shot_seconds"))
        lines.append(
            DialogueLine(
                unit_id=str(audio.get("unit_id", "")),
                label=str(audio.get("label", "")),
                text=text.strip(),
                starts_in_shot_seconds=start if start is not None else 0.0,
                heard_until_s=heard_until,
                duration_s=_number(audio.get("duration_s")),
            )
        )
    return lines


def _line_json(line: DialogueLine) -> dict[str, Any]:
    """One line as a take records it. `heard_until_s` is written only when it is set, so the
    record of any other take is what it was.
    """
    stored: dict[str, Any] = {
        "unit_id": line.unit_id,
        "label": line.label,
        "text": line.text,
        "starts_in_shot_seconds": line.starts_in_shot_seconds,
    }
    if line.heard_until_s is not None:
        stored["heard_until_s"] = line.heard_until_s
    if line.duration_s is not None:
        stored["duration_s"] = line.duration_s
    return stored


def lines_as_json(lines: Sequence[DialogueLine]) -> list[dict[str, Any]]:
    """What `shot_take.inputs.dialogue` records, so a take knows what it was meant to say."""
    return [_line_json(line) for line in lines]


def _line_windows(lines: Sequence[DialogueLine]) -> list[tuple[str, float, float]] | None:
    """The time window of each line, `(unit_id, from_s, to_s)`, or None when the lines have no
    windows: a line with no length (a take made before SCN-009), a window of a scene's take
    (FLOW-007, `heard_until_s`), or no line at all.
    """
    if not lines or any(
        line.duration_s is None or line.heard_until_s is not None for line in lines
    ):
        return None
    return [
        (
            line.unit_id,
            round(line.starts_in_shot_seconds - LINE_LEAD_S, 3),
            round(line.starts_in_shot_seconds + (line.duration_s or 0.0) + LINE_TAIL_S, 3),
        )
        for line in lines
    ]


def _inside(word: SpokenWord, windows: Sequence[tuple[str, float, float]]) -> bool:
    """Whether the middle of a heard word is inside the time of some line."""
    middle = (word.start + word.end) / 2
    return any(start <= middle <= end for _unit, start, end in windows)


def _extra_words(outside: Sequence[SpokenWord], lines: Sequence[DialogueLine]) -> list[str]:
    """The words heard outside every line's time that are not part of the speech: filler sounds
    are left out, and so is a word of the lines themselves (every matching step applied). A line
    that H3 says slowly runs past its window, and its last words are not extra speech.
    """
    own = set(_words_at([line.text for line in lines], len(RULES) - 1))
    words: list[str] = []
    for word in outside:
        for token in normalize_words(word.word):
            if token in dialogue_matching.FILLERS:
                continue
            if own.intersection(_words_at([token], len(RULES) - 1)):
                continue
            words.append(token)
    return words


def compare(
    lines: Sequence[DialogueLine], spoken: Sequence[SpokenWord], threshold: int
) -> DialogueResult:
    """Judges what was heard against the lines. `threshold` is a percent, 0 to 100.

    Lines with no words at all (only punctuation) leave nothing to check, so the take passes.

    **Line windows (SCN-009).** When every line has its own time window, only the words heard in
    those windows are compared with the lines (`_judge`), and the words heard outside every window
    are "extra speech": two or more of them (filler sounds and the line's own words are not
    counted) fail a take that otherwise passed (`extra_speech`). H3 may place a line at another
    time than planned, so a take that fails inside the windows still passes when the whole clip
    matches the lines; no verdict on extra speech is given then. Without windows the whole clip
    is compared, as before.
    """
    windows = _line_windows(lines)
    if windows is None or not _words_at([line.text for line in lines], 0):
        return _judge(lines, spoken, threshold)

    inside = [word for word in spoken if _inside(word, windows)]
    extra = _extra_words([word for word in spoken if not _inside(word, windows)], lines)
    in_windows = _judge(lines, inside, threshold)
    # "Nothing heard" on a line too slight to check only counts when nothing else was heard
    # either: a word outside the windows is judged like the whole clip, as before SCN-009.
    unheard = in_windows.outcome == NOT_VERIFIABLE and bool(extra)
    if not in_windows.passed or unheard:
        whole = _judge(lines, spoken, threshold)
        if whole.passed:
            return replace(whole, windows=windows)
        if len(extra) >= EXTRA_SPEECH_MIN_WORDS:
            whole.problems.append(_extra_problem(extra))
        return replace(whole, windows=windows, extra_words=extra)
    if len(extra) >= EXTRA_SPEECH_MIN_WORDS:
        return replace(
            in_windows,
            passed=False,
            problems=[_extra_problem(extra)],
            outcome=EXTRA_SPEECH_OUTCOME,
            rule=None,
            heard_words=_words_at([word.word for word in spoken], 0),
            # The extra words count in the same-answer test: two takes with other extra words
            # did not hear the same thing.
            matched_heard=[*in_windows.matched_heard, *extra],
            windows=windows,
            extra_words=extra,
        )
    return replace(in_windows, windows=windows, extra_words=extra)


def _extra_problem(extra: Sequence[str]) -> Problem:
    return Problem(
        EXTRA_SPEECH,
        f"Words were heard outside the time of the lines: \u201c{' '.join(extra)}\u201d. "
        "The clip has speech that is not in the dialogue.",
    )


def compare_silent(spoken: Sequence[SpokenWord]) -> DialogueResult:
    """Judges a shot that carries no dialogue (SCN-009): it passes when no words were heard.
    Filler sounds (`dialogue_matching.FILLERS`) are not counted. The words kept are stored as
    `matched_heard`, so two takes that heard the same words are told apart from two that did not
    (the same-answer stop of `shot_takes._repeated_answer` works for silent shots too).
    """
    heard = [w for word in spoken for w in normalize_words(word.word)]
    kept = [w for w in heard if w not in dialogue_matching.FILLERS]
    if len(kept) <= SILENT_WORDS_ALLOWED:
        return DialogueResult(
            True, 100.0, [], [], heard, outcome=SILENT, mode=MODE_SILENT, matched_heard=kept
        )
    return DialogueResult(
        False,
        0.0,
        [
            Problem(
                SPEECH_IN_SILENT_SHOT,
                f"Words were heard in a shot where nobody speaks: \u201c{' '.join(kept)}\u201d.",
            )
        ],
        [],
        heard,
        outcome=SPEECH_HEARD,
        mode=MODE_SILENT,
        matched_heard=kept,
    )


def _judge(
    lines: Sequence[DialogueLine], spoken: Sequence[SpokenWord], threshold: int
) -> DialogueResult:
    """Compares all that was heard with the lines (the check before SCN-009's windows)."""
    line_texts = [line.text for line in lines]
    # FLOW-007: the part of the clip after the shot's end is never shown, so what is said there
    # is not compared. A word counts when its middle is before the end.
    ends = [line.heard_until_s for line in lines if line.heard_until_s is not None]
    until = min(ends) if ends else None
    heard_texts = [
        word.word for word in spoken if until is None or (word.start + word.end) / 2 < until
    ]

    expected = _words_at(line_texts, 0)
    heard = _words_at(heard_texts, 0)

    if not expected:
        return DialogueResult(True, 100.0, [], expected, heard, rule="exact")
    if not heard:
        if dialogue_matching.is_unverifiable(expected):
            return DialogueResult(
                True,
                0.0,
                [
                    Problem(
                        SPEECH_NOT_VERIFIABLE,
                        "Nothing was heard, but this line is too short for the check to tell "
                        "whether it was said, so the take is not failed.",
                    )
                ],
                expected,
                heard,
                outcome=NOT_VERIFIABLE,
                rule=NOT_VERIFIABLE_RULE,
            )
        return DialogueResult(
            False,
            0.0,
            [Problem(NO_SPEECH, "No speech was heard in the clip.")],
            expected,
            heard,
            outcome=NO_SPEECH,
        )

    similarity = 0.0
    matched_expected = expected
    matched_heard = heard
    for stage, rule in enumerate(RULES):
        matched_expected = _words_at(line_texts, stage)
        matched_heard = _words_at(heard_texts, stage)
        similarity = _similarity(matched_expected, matched_heard)
        if similarity >= threshold:
            return DialogueResult(
                True,
                similarity,
                [],
                expected,
                heard,
                outcome=MATCHED,
                rule=rule,
                matched_expected=matched_expected,
                matched_heard=matched_heard,
            )
    # The last step is the most forgiving one, so its words are the ones the retry rule compares.
    if dialogue_matching.short_line_matches(matched_expected, matched_heard):
        return DialogueResult(
            True,
            similarity,
            [],
            expected,
            heard,
            outcome=CLOSE_MATCH,
            rule=SHORT_LINE_RULE,
            matched_expected=matched_expected,
            matched_heard=matched_heard,
        )
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
        outcome=MISMATCH,
        matched_expected=matched_expected,
        matched_heard=matched_heard,
    )


def _similarity(expected: Sequence[str], heard: Sequence[str]) -> float:
    """The ratio of `SequenceMatcher` over two word lists, in percent, one decimal."""
    return round(SequenceMatcher(None, expected, heard, autojunk=False).ratio() * 100, 1)


def _words_at(texts: Sequence[str], stage: int) -> list[str]:
    """The words of these texts, normalized, then made alike step by step: stage 0 is only
    normalized (`exact`), 1 adds numbers, 2 adds spelling and 3 adds homophones (see `RULES`).
    """
    words: list[str] = []
    for text in texts:
        words.extend(normalize_words(dialogue_matching.prepare(text) if stage >= 1 else text))
    if stage >= 1:
        words = dialogue_matching.fold_numbers(words)
    if stage >= 2:
        words = [dialogue_matching.to_us_spelling(word) for word in words]
    if stage >= 3:
        words = [dialogue_matching.fold_homophones(word) for word in words]
    return words


def spoken_of(check: Any) -> list[SpokenWord]:
    """The words a stored `shot_take.dialogue_check` recorded as heard, with their times, so a
    take can be judged again with no new transcription. Empty for anything that is not a check.
    """
    stored = check.get("heard_words") if isinstance(check, dict) else None
    spoken: list[SpokenWord] = []
    for item in stored if isinstance(stored, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("word"), str):
            continue
        start, end = _number(item.get("start")), _number(item.get("end"))
        spoken.append(SpokenWord(item["word"], start or 0.0, end or 0.0))
    return spoken


def heard_key(check: Any) -> str | None:
    """What a stored check heard, in the form two takes are compared in (every matching step
    applied). None when it is not a check. A version 1 check is read from its `heard_words`.
    """
    if not isinstance(check, dict):
        return None
    stored = check.get("matched_heard")
    if isinstance(stored, str):
        return stored
    return " ".join(_words_at([word.word for word in spoken_of(check)], len(RULES) - 1))


def passed(dialogue_check: Any) -> bool:
    """Whether a stored `shot_take.dialogue_check` says the dialogue passed. False for NULL."""
    return isinstance(dialogue_check, dict) and dialogue_check.get("passed") is True


def is_report_only(dialogue_check: Any) -> bool:
    """Whether a stored check was made as a report on an older take (SCN-009): it is shown, but
    it never decides which take is selected and never starts a retry.
    """
    return isinstance(dialogue_check, dict) and dialogue_check.get("report_only") is True


def blocks(dialogue_check: Any) -> bool:
    """Whether a stored check keeps its take from being used: it failed, the user has not
    accepted it, and it is not a report. False for NULL (not checked: see the caller).
    """
    return (
        isinstance(dialogue_check, dict)
        and dialogue_check.get("passed") is False
        and dialogue_check.get("accepted_at") is None
        and not is_report_only(dialogue_check)
    )


def is_silent(dialogue_check: Any) -> bool:
    """Whether a stored check is the check of a shot with no dialogue."""
    return isinstance(dialogue_check, dict) and dialogue_check.get("mode") == MODE_SILENT
