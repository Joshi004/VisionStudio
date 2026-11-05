"""The brief of one graphic shot of a continuous explainer: the context of the shot, the
instructions to the director model, and the checks of what it wrote (EXG-004,
`Explainer_graphics_implementation_phases.md` §3.2 and §3.4).

Pure functions, no I/O.

A graphic shot starts on a word of its scene's take and ends before the word where the next shot
starts (EXG-003). One call per shot answers the lab's brief (`graphics_brief_writer`): the kind of
graphic, what it shows, the numbers it uses (`facts`), the values code derives from them
(`derived`) and the `beats`. There is **no theme** in it: the whole video has one (EXG-002).

**The context and the soft number rule.** The *context* of a shot is the take's text from the
sentence before the shot's first sentence to the sentence after its last one (`context_of`). A
number on screen must be said in the context (a fact's `said_as` is searched there), but a beat
needs a frame inside the shot, so its phrase is searched in the shot's own words. The model is
shown the context as three blocks (before, the shot, after) and the checks are
`graphics_brief_writer.check_brief` with its `context`.

**The hashes** (`skeleton_sha256`, `context_sha256`) say whether a stored brief still fits: the
first changes only when this shot changes in its plan, the second when the sentences around it do.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final

from app.services import cut_planning_writer, user_feedback
from app.services.graphics_brief_writer import (
    DERIVED_RULES,
    INTENT_MAX_CHARS,
    KIND_RULES,
    LABEL_MAX_CHARS,
    MAX_TOKENS,
    PHRASE_MAX_CHARS,
    REASONING_EFFORT,
    SAID_AS_MAX_CHARS,
    SHOWS_MAX_CHARS,
    VISUAL_BRIEF_MAX_CHARS,
    check_brief,
    line_tokens,
    phrase_starts,
)
from app.services.music_bible_writer import parse_answer as parse_answer
from app.services.text_limits import length_rule

__all__ = [
    "MAX_TOKENS",
    "REASONING_EFFORT",
    "Context",
    "beat_times",
    "bible_for_model",
    "build_request",
    "check_answer",
    "context_of",
    "context_sha256",
    "parse_answer",
    "previous_brief",
    "skeleton_sha256",
    "timed_words",
]

LIMIT_NAMES: Final = {
    "intent": INTENT_MAX_CHARS,
    "visual_brief": VISUAL_BRIEF_MAX_CHARS,
    "facts[].label": LABEL_MAX_CHARS,
    "facts[].said_as": SAID_AS_MAX_CHARS,
    "derived[].label": LABEL_MAX_CHARS,
    "beats[].phrase": PHRASE_MAX_CHARS,
    "beats[].shows": SHOWS_MAX_CHARS,
}

# The fields of a stored cut shot that make up its skeleton for a brief.
_SKELETON_FIELDS: Final = (
    "type",
    "start_word",
    "last_word",
    "start_s",
    "end_s",
    "spoken_text",
    "description",
)
_TIME_DECIMALS: Final = 3


# --- The context -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Context:
    """The text around a graphic shot. `first_word` and `last_word` are the positions (counted
    from 1, as in the cut plan) of the first and last word of the context in the take.
    """

    first_word: int
    last_word: int
    before: str
    shot: str
    after: str

    @property
    def text(self) -> str:
        """The whole context: before, the shot and after, in order."""
        return " ".join(part for part in (self.before, self.shot, self.after) if part)


def context_of(
    words: list[dict[str, Any]], spans: list[dict[str, Any]], start_word: int, last_word: int
) -> Context:
    """The context of the shot whose words are `start_word` to `last_word` (counted from 1) of
    the take: from the sentence before the shot's first sentence to the sentence after its last
    sentence, cut off at the ends of the take. Sentences are those of the cut planner
    (`cut_planning_writer.sentence_ranges`). `words` are the take's timed words and `spans` the
    units' spans, as `take_timings` gives them (positions from 0).
    """
    first, last = start_word - 1, last_word - 1
    sentences = cut_planning_writer.sentence_ranges(words, spans)
    index_of_first = next(i for i, (_, low, high) in enumerate(sentences) if low <= first <= high)
    index_of_last = next(i for i, (_, low, high) in enumerate(sentences) if low <= last <= high)
    begin = sentences[max(index_of_first - 1, 0)][1]
    end = sentences[min(index_of_last + 1, len(sentences) - 1)][2]

    def text(low: int, high: int) -> str:
        return " ".join(str(word["text"]) for word in words[low : high + 1])

    return Context(
        first_word=begin + 1,
        last_word=end + 1,
        before=text(begin, first - 1),
        shot=text(first, last),
        after=text(last + 1, end),
    )


def timed_words(
    words: list[dict[str, Any]], start_word: int, last_word: int, start_s: float
) -> list[dict[str, Any]]:
    """The shot's words, each `{text, start, end}` with the times in seconds from the shot's
    start (`word time - start_s`, never below 0), from the take's timed words.
    """
    return [
        {
            "text": str(word["text"]),
            "start": round(max(0.0, float(word["start"]) - start_s), _TIME_DECIMALS),
            "end": round(max(0.0, float(word["end"]) - start_s), _TIME_DECIMALS),
        }
        for word in words[start_word - 1 : last_word]
    ]


def skeleton_sha256(shot: dict[str, Any]) -> str:
    """A hash of what the cut plan says about one graphic shot. It changes when this shot
    changes (its words, times, type or description) and not when another shot of the scene does.
    """
    payload = {name: shot.get(name) for name in _SKELETON_FIELDS}
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def context_sha256(text: str) -> str:
    """A hash of the context's text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- The instructions ------------------------------------------------------------------------

_RULES: Final = """\
You are the director of a short explainer graphic. The graphic is drawn on screen while a few \
words of an explainer script are spoken: the SHOT WORDS. You are also given the sentences around \
them, WORDS BEFORE THE SHOT and WORDS AFTER THE SHOT, and a DESCRIPTION of the graphic from the \
planner of the video. You decide what graphic should be drawn: what it shows, which numbers it \
uses, and at which words each part appears. Other programs draw it from your brief. You never \
draw anything and you never write any time.

The graphic is on screen only while the SHOT WORDS are spoken. Its look (colours, background and \
motion) is decided elsewhere, so you never write it. The DESCRIPTION is a hint: follow it unless \
the words say otherwise.

{kind_rules}FACTS (the numbers on screen)
- Every number on screen must come from the words you are given. A fact is a number that is said \
in the SHOT WORDS, the WORDS BEFORE THE SHOT or the WORDS AFTER THE SHOT. Prefer a number said in \
the SHOT WORDS.
- "value" is the number as the words say it and "scale" is the word after it. "12 billion \
dollars": value 12, unit "usd", scale "billion". "6.5 percent": value 6.5, unit "percent", scale \
"none". When the words say a number fell, give a negative value ("down 6.5 percent" is -6.5).
- "unit" is one of usd, percent, points, multiple, count, none. Use "none" for a plain number \
such as a year. A scale other than "none" is only for the units usd and count.
- "said_as" is the words where the fact is said, copied exactly as written, with the number in \
them.
- Never invent, round, add up or work out a number yourself. Never use a number that none of the \
three blocks of words says. When they say no number, there are no facts.

{derived_rules}BEATS (when each part appears)
- A beat is a moment of the SHOT WORDS. "phrase" is a few words of the SHOT WORDS, copied \
exactly as written, at which the part appears. A phrase is never taken from the WORDS BEFORE THE \
SHOT or the WORDS AFTER THE SHOT: nothing can appear before the graphic starts or after it ends. \
The beats follow the order of the words: a later beat never starts before an earlier one.
- "shows" says in words what appears or moves at that moment. "refs" lists the ids of the facts \
or derived values the beat shows.
- Use between 1 and 8 beats. Fewer, clearer beats are better.

DO NOT write any text that appears on screen (titles, labels, captions). Other programs write \
it. "visual_brief" describes in plain words what the viewer sees and how it moves.

{feedback}

{length_rule}"""

_SHAPE: Final = """{"kind": "comparison", "intent": "Show how hiring grew in one month.", \
"visual_brief": "Two bars, one for March and one for April, that grow as each month is said. \
The April bar is taller and green. A badge with the growth pops in at the end.", \
"facts": [{"id": "f1", "label": "March hires", "value": 400, "unit": "count", "scale": "none", \
"said_as": "400 engineers in March"}, {"id": "f2", "label": "April hires", "value": 650, \
"unit": "count", "scale": "none", "said_as": "650 in April"}], \
"derived": [{"id": "d1", "label": "Growth", "op": "pct_change", "of": ["f1", "f2"]}], \
"beats": [{"id": "b1", "phrase": "400 engineers in March", "shows": "The March bar grows.", \
"refs": ["f1"]}, {"id": "b2", "phrase": "650 in April", "shows": "The April bar grows, in \
green.", "refs": ["f2"]}, {"id": "b3", "phrase": "a rise of", "shows": "The growth badge pops \
in.", "refs": ["d1"]}]} (the values here only show the form, never copy them)"""


def _instructions() -> str:
    return (
        _RULES.replace("{kind_rules}", KIND_RULES)
        .replace("{derived_rules}", DERIVED_RULES)
        .replace("{feedback}", user_feedback.INSTRUCTION)
        .replace("{length_rule}", length_rule(LIMIT_NAMES))
        + "\n\nAnswer with one JSON object only, in exactly this form: "
        + _SHAPE
    )


def bible_for_model(bible: dict[str, Any]) -> dict[str, Any]:
    """The fields of the Story Bible the director reads: what the video is called and its tone,
    so the graphic suits it. The look belongs to the theme.
    """
    return {"title": bible.get("title"), "tone": bible.get("tone")}


def previous_brief(content: dict[str, Any]) -> dict[str, Any]:
    """A stored brief as the model is shown it when the owner writes a note on it."""
    return {
        name: content[name]
        for name in ("kind", "intent", "visual_brief", "facts", "derived", "beats")
    }


def build_request(
    *,
    shot_words: str,
    before: str,
    after: str,
    description: str,
    shot_seconds: float,
    orientation: str,
    bible: dict[str, Any],
    model: str,
    feedback: user_feedback.Feedback | None = None,
) -> dict[str, Any]:
    """The exact request body of the one call. It is stored on the job."""
    parts = [
        f"DESCRIPTION OF THE GRAPHIC (a hint from the planner):\n{description}",
        f"WORDS BEFORE THE SHOT (for the numbers only):\n{before or '(none)'}",
        f"SHOT WORDS (the graphic is on screen while these are spoken):\n{shot_words}",
        f"WORDS AFTER THE SHOT (for the numbers only):\n{after or '(none)'}",
        "VIDEO (JSON):\n" + json.dumps(bible_for_model(bible), ensure_ascii=False, indent=1),
        f"ORIENTATION: {orientation}",
        f"ABOUT HOW LONG THE SHOT WORDS TAKE TO SAY: {shot_seconds:.1f} seconds",
    ]
    if feedback is not None:
        parts += user_feedback.blocks(feedback, "PREVIOUS BRIEF")
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _instructions()},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- Checking what was written ---------------------------------------------------------------


def check_answer(answer: dict[str, Any], shot_words: str, context_text: str) -> dict[str, Any]:
    """The model's answer as the stored brief (no theme), or ValueError with a message fit for
    the user and for the model's corrected retry. Facts are checked against the context, beats
    against the shot's own words (§3.2).
    """
    return check_brief(answer, shot_words, context=context_text, with_theme=False)


def beat_times(brief: dict[str, Any], words: list[dict[str, Any]]) -> dict[str, float]:
    """The second each beat starts, from the start of the shot, by beat id. `words` are the
    shot's timed words (`timed_words`). Raises ValueError when a phrase is not in them.
    """
    tokens = line_tokens([str(word["text"]) for word in words])
    beats = [(beat["id"], beat["phrase"]) for beat in brief["beats"]]
    starts = phrase_starts(tokens, beats, place="the shot's words")
    return {
        beat_id: float(words[start]["start"])
        for (beat_id, _phrase), start in zip(beats, starts, strict=True)
    }
