"""The brief of the Graphics lab: the instructions to the director model, and the checks of what
it wrote (GFX-003, `Graphics_lab_implementation_phases.md` §4.3).

Pure functions, no I/O.

One call reads one line of an explainer script and answers an engine-neutral **brief**: the kind
of graphic, what it should show, the numbers it uses (`facts`), the values code derives from
them (`derived`), the `beats` (each tied to a phrase of the line) and a `theme`. The model never
writes a time, a frame, an on-screen text or a derived value: code does (G-7, G-9).

**Words and tokens.** The line is split on whitespace into *words* (`line_words`). Each word is
turned into the tokens `dialogue_check.normalize_words` makes, and each token remembers its word
(`line_tokens`). A phrase is found among the tokens with `callout_plan_writer.locate_phrase`.

**A fact is said in the line.** `said_as` must be found. The number of the fact must then be one
that `number_words.numbers_in` reads in the *original words* behind the found tokens (not in the
tokens, because normalising turns `6.5` into `6 5`): either the value as written (`12`) or the
value with its scale applied (`12,000,000,000`). The sign is ignored, so a fall said as
"down 6.5 percent" is a fact with the value -6.5.

**Beats follow the line.** Each beat phrase is searched from the start of the beat before it. A
phrase found there is placed there. A phrase found only earlier is refused as out of order, and
one not found anywhere is refused as not in the line. Two beats may start on the same word.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from app.services.callout_plan_writer import format_number, locate_phrase
from app.services.dialogue_check import normalize_words
from app.services.music_bible_writer import parse_answer as parse_answer
from app.services.number_words import numbers_in
from app.services.text_limits import length_rule

# How the messages call the words a brief is checked against, when it is a lab line.
LINE: Final = "the line"

KINDS: Final = ("kpi", "comparison", "trend", "process", "list", "statement", "concept")
UNITS: Final = ("usd", "inr", "percent", "points", "multiple", "count", "none")
# The units that may carry a scale ("12 billion dollars", "₹5 lakh", "2.5 million users").
SCALED_UNITS: Final = ("usd", "inr", "count")
SCALE_FACTORS: Final[dict[str, Decimal]] = {
    "none": Decimal(1),
    "thousand": Decimal(10) ** 3,
    "lakh": Decimal(10) ** 5,
    "million": Decimal(10) ** 6,
    "crore": Decimal(10) ** 7,
    "billion": Decimal(10) ** 9,
    "trillion": Decimal(10) ** 12,
}
OPS: Final = ("pct_change", "difference", "ratio", "sum")
PALETTES: Final = ("dark", "light")
BACKGROUNDS: Final = ("solid", "gradient", "grid", "glow")
MOTIONS: Final = ("snappy", "smooth", "calm")

MAX_FACTS: Final = 12
MAX_DERIVED: Final = 4
MIN_BEATS: Final = 1
MAX_BEATS: Final = 8
INTENT_MAX_CHARS: Final = 160
VISUAL_BRIEF_MAX_CHARS: Final = 600
LABEL_MAX_CHARS: Final = 60
SAID_AS_MAX_CHARS: Final = 120
PHRASE_MAX_CHARS: Final = 120
SHOWS_MAX_CHARS: Final = 120
MOOD_MAX_CHARS: Final = 40
# A value this large is not a number a line says.
VALUE_LIMIT: Final = Decimal(10) ** 15

# One call, and its largest answer. The brief is about 2,000 tokens; the cap only bounds the
# call (tokens are paid as used) and stays under the Qwen3.8 limit of 49,152.
MAX_TOKENS: Final = 32_000
REASONING_EFFORT: Final = "high"

_ID: Final = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,15}")
_HEX: Final = re.compile(r"#[0-9A-Fa-f]{6}")

LIMIT_NAMES: Final = {
    "intent": INTENT_MAX_CHARS,
    "visual_brief": VISUAL_BRIEF_MAX_CHARS,
    "facts[].label": LABEL_MAX_CHARS,
    "facts[].said_as": SAID_AS_MAX_CHARS,
    "derived[].label": LABEL_MAX_CHARS,
    "beats[].phrase": PHRASE_MAX_CHARS,
    "beats[].shows": SHOWS_MAX_CHARS,
    "theme.mood": MOOD_MAX_CHARS,
}


# --- The instructions ------------------------------------------------------------------------

# The KIND and DERIVED VALUES sections are shared with the director of an explainer shot
# (`shot_graphic_brief_writer`, EXG-004).
KIND_RULES: Final = """\
KIND (choose one)
- "kpi": one big number, with or without a change.
- "comparison": two or more values set side by side.
- "trend": values over time.
- "process": steps in a chain.
- "list": a few points that build up one by one.
- "statement": one short sentence shown large.
- "concept": an idea that no data chart fits.

"""

DERIVED_RULES: Final = """\
DERIVED VALUES (worked out by code, never by you)
- Ask for one only when it helps the graphic. "op" is one of:
  - "pct_change": the percent change from the first fact to the second ("of": [from, to]);
  - "difference": the second fact minus the first;
  - "ratio": the first fact divided by the second;
  - "sum": all the facts added up (two or more).
- "of" lists fact ids only, and all of them have the same unit. Never write the value.

"""


_RULES: Final = """\
You are the director of a short explainer graphic. You are given one line of an explainer \
script. You decide what graphic should be drawn while the line is spoken: what it shows, which \
numbers it uses, and at which words each part appears. Other programs draw it from your \
brief. You never draw anything and you never write any time.

{kind_rules}FACTS (the numbers on screen)
- Every number on screen must come from the line. A fact is a number the line says.
- "value" is the number as the line says it and "scale" is the word after it. "12 billion \
dollars": value 12, unit "usd", scale "billion". "₹5 lakhs": value 5, unit "inr", scale "lakh". \
"6.5 percent": value 6.5, unit "percent", scale "none". When the line says a number fell, give a \
negative value ("down 6.5 percent" is -6.5).
- "unit" is one of usd, inr, percent, points, multiple, count, none. "usd" is for dollars and \
"inr" for rupees. Use "none" for a plain number such as a year. "scale" is one of none, \
thousand, lakh, million, crore, billion, trillion, and a scale other than "none" is only for the \
units usd, inr and count.
- "said_as" is the words of the line where the fact is said, copied exactly as written, with \
the number in them.
- Never invent, round, add up or work out a number yourself. Never use a number the line does \
not say. A line with no numbers has no facts.

{derived_rules}BEATS (when each part appears)
- A beat is a moment of the line. "phrase" is a few words of the line, copied exactly as \
written, at which the part appears. The beats follow the order of the line: a later beat never \
starts before an earlier one.
- "shows" says in words what appears or moves at that moment. "refs" lists the ids of the facts \
or derived values the beat shows.
- Use between 1 and 8 beats. Fewer, clearer beats are better.

THEME
- "palette" is "dark" or "light". "accent" is one colour as "#RRGGBB" that can be read on the \
palette's background. "background" is one of solid, gradient, grid, glow. "motion" is one of \
snappy, smooth, calm. "mood" is a few words.

DO NOT write any text that appears on screen (titles, labels, captions). Other programs write \
it. "visual_brief" describes in plain words what the viewer sees and how it moves. The graphic \
lasts as long as the line is spoken.

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
in.", "refs": ["d1"]}], "theme": {"palette": "dark", "accent": "#2ED573", "background": \
"grid", "motion": "snappy", "mood": "confident"}} (the values here only show the form, never \
copy them)"""


def _instructions() -> str:
    return (
        _RULES.replace("{kind_rules}", KIND_RULES)
        .replace("{derived_rules}", DERIVED_RULES)
        .replace("{length_rule}", length_rule(LIMIT_NAMES))
        + "\n\nAnswer with one JSON object only, in exactly this form: "
        + _SHAPE
    )


def build_request(
    line: str, orientation: str, speech_seconds: float, *, model: str
) -> dict[str, Any]:
    """The exact request body of the one call. It is stored on the job."""
    user = (
        f"LINE:\n{line}\n\nORIENTATION: {orientation}\n"
        f"ABOUT HOW LONG THE LINE TAKES TO SAY: {speech_seconds:.1f} seconds"
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _instructions()},
            {"role": "user", "content": user},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- Words, tokens and phrases ---------------------------------------------------------------


def line_words(line: str) -> list[str]:
    """The words of the line: split on whitespace. The timing of the run has one entry for each."""
    return line.split()


def line_tokens(words: Sequence[str]) -> list[tuple[str, int]]:
    """The tokens of the words as `normalize_words` makes them, each with the index of its word."""
    return [(token, index) for index, word in enumerate(words) for token in normalize_words(word)]


def phrase_starts(
    tokens: Sequence[tuple[str, int]],
    beats: Sequence[tuple[str, str]],
    *,
    place: str = LINE,
) -> list[int]:
    """The word index where each beat starts. `beats` are `(id, phrase)` in beat order. Raises
    ValueError, with a message fit for the model's corrected retry, for a phrase that is not in
    the line or that comes before the beat before it. `place` is how the messages call the
    words (the shot's words, for a shot of an explainer).
    """
    texts = [token for token, _ in tokens]
    previous = 0
    starts: list[int] = []
    for beat_id, phrase in beats:
        span = locate_phrase(texts[previous:], phrase)
        if span is None:
            if locate_phrase(texts, phrase) is None:
                raise ValueError(f'The phrase of beat {beat_id} ("{phrase}") is not in {place}.')
            raise ValueError(
                f'The phrase of beat {beat_id} ("{phrase}") comes earlier in {place} than the '
                f"beat before it. The beats must follow the order of {place}."
            )
        previous += span[0]
        starts.append(tokens[previous][1])
    return starts


# --- Checking what was written ---------------------------------------------------------------


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"The {name} was not an object.")
    return value


def _list(value: object, name: str, least: int, most: int) -> list[Any]:
    if value is None and least == 0:
        return []
    if not isinstance(value, list):
        raise ValueError(f'The "{name}" were not a list.')
    if not least <= len(value) <= most:
        raise ValueError(f'There were {len(value)} "{name}"; it must be {least} to {most}.')
    return value


def _text(value: object, name: str, max_chars: int) -> str:
    """One piece of text on one line. Refused when it is not text, is empty or is too long: a
    text that does not fit is not cut behind anyone's back.
    """
    if not isinstance(value, str):
        raise ValueError(f'The "{name}" was missing or was not text.')
    text = " ".join(value.split())
    if not text:
        raise ValueError(f'The "{name}" was empty.')
    if len(text) > max_chars:
        raise ValueError(
            f'The "{name}" "{text}" was {len(text)} characters; the most allowed is {max_chars}.'
        )
    return text


def _choice(value: object, name: str, allowed: Sequence[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f'The "{name}" was {value!r}; it must be one of {", ".join(allowed)}.')
    return value


def _id(value: object, name: str, seen: set[str]) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(
            f"The id {value!r} of {name} must be 1 to 16 letters, digits or underscores, "
            "starting with a letter."
        )
    if value in seen:
        raise ValueError(f'The id "{value}" was used twice.')
    seen.add(value)
    return value


def fact_value(value: object, name: str) -> Decimal:
    """The value of a fact as a Decimal. Raises ValueError when it is not a plain number."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"The value of {name} was missing or was not a number.")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"The value of {name} was not a number.") from None
    if not number.is_finite() or abs(number) >= VALUE_LIMIT:
        raise ValueError(f"The value of {name} was not a usable number.")
    return number


def _check_fact(
    raw: object,
    position: int,
    seen: set[str],
    words: Sequence[str],
    tokens: Sequence[tuple[str, int]],
    place: str,
) -> dict[str, Any]:
    label = f"fact {position}"
    item = _object(raw, label)
    fact_id = _id(item.get("id"), label, seen)
    name = f"fact {fact_id}"
    text = _text(item.get("label"), f"label of {name}", LABEL_MAX_CHARS)
    value = fact_value(item.get("value"), name)
    unit = _choice(item.get("unit"), f"unit of {name}", UNITS)
    scale = _choice(item.get("scale", "none"), f"scale of {name}", tuple(SCALE_FACTORS))
    if scale != "none" and unit not in SCALED_UNITS:
        raise ValueError(
            f'The {name} has the scale "{scale}" with the unit "{unit}". A scale goes only with '
            'the units "usd", "inr" and "count".'
        )
    said_as = _text(item.get("said_as"), f"said_as of {name}", SAID_AS_MAX_CHARS)
    _check_said(name, value, scale, said_as, words, tokens, place)
    return {
        "id": fact_id,
        "label": text,
        "value": item["value"],
        "unit": unit,
        "scale": scale,
        "said_as": said_as,
    }


def _check_said(
    name: str,
    value: Decimal,
    scale: str,
    said_as: str,
    words: Sequence[str],
    tokens: Sequence[tuple[str, int]],
    place: str = LINE,
) -> None:
    """The fact is said in the line: `said_as` is found there, and the number read in those
    words is the value as written or the value with its scale applied.
    """
    span = locate_phrase([token for token, _ in tokens], said_as)
    if span is None:
        raise ValueError(f'The words "{said_as}" of {name} are not in {place}.')
    first, last = tokens[span[0]][1], tokens[span[1] - 1][1]
    said = numbers_in(" ".join(words[first : last + 1]))
    if abs(value) in said or abs(value) * SCALE_FACTORS[scale] in said:
        return
    reads = ", ".join(format_number(number) for number in sorted(said)) or "no number"
    raise ValueError(
        f"The {name} has the value {format_number(value)}"
        f'{"" if scale == "none" else " " + scale}, but the words "{said_as}" say {reads}. '
        + (
            "A fact must be a number the line says."
            if place == LINE
            else f"A fact must be a number said in {place}."
        )
    )


def _check_derived(
    raw: object, position: int, seen: set[str], facts: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    label = f"derived value {position}"
    item = _object(raw, label)
    derived_id = _id(item.get("id"), label, seen)
    name = f"derived value {derived_id}"
    text = _text(item.get("label"), f"label of {name}", LABEL_MAX_CHARS)
    op = _choice(item.get("op"), f"op of {name}", OPS)
    of = item.get("of")
    if not isinstance(of, list) or not all(isinstance(fact_id, str) for fact_id in of):
        raise ValueError(f'The "of" of {name} was not a list of fact ids.')
    least, most = (2, MAX_FACTS) if op == "sum" else (2, 2)
    if not least <= len(of) <= most:
        raise ValueError(
            f'The {name} ("{op}") needs {"two or more facts" if op == "sum" else "two facts"}.'
        )
    unknown = [fact_id for fact_id in of if fact_id not in facts]
    if unknown:
        raise ValueError(f'The {name} names "{unknown[0]}", which is not a fact id.')
    if len(set(of)) != len(of):
        raise ValueError(f"The {name} names one fact twice.")
    if len({facts[fact_id]["unit"] for fact_id in of}) != 1:
        raise ValueError(f"The facts of {name} must all have the same unit.")
    if op == "pct_change" and fact_value(facts[of[0]]["value"], name) == 0:
        raise ValueError(f"The {name} is a change from zero, which cannot be worked out.")
    if op == "ratio" and fact_value(facts[of[1]]["value"], name) == 0:
        raise ValueError(f"The {name} divides by zero, which cannot be worked out.")
    return {"id": derived_id, "label": text, "op": op, "of": list(of)}


def _check_beats(
    raw: object, refs: set[str], tokens: Sequence[tuple[str, int]], place: str = LINE
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    beats: list[dict[str, Any]] = []
    for position, entry in enumerate(_list(raw, "beats", MIN_BEATS, MAX_BEATS), start=1):
        label = f"beat {position}"
        item = _object(entry, label)
        beat_id = _id(item.get("id"), label, seen)
        name = f"beat {beat_id}"
        beat_refs = item.get("refs", [])
        if beat_refs is None:
            beat_refs = []
        if not isinstance(beat_refs, list) or not all(isinstance(ref, str) for ref in beat_refs):
            raise ValueError(f'The "refs" of {name} were not a list of ids.')
        unknown = [ref for ref in beat_refs if ref not in refs]
        if unknown:
            raise ValueError(f'The {name} names "{unknown[0]}", which is not a fact or derived id.')
        beats.append(
            {
                "id": beat_id,
                "phrase": _text(item.get("phrase"), f"phrase of {name}", PHRASE_MAX_CHARS),
                "shows": _text(item.get("shows"), f"shows of {name}", SHOWS_MAX_CHARS),
                "refs": list(beat_refs),
            }
        )
    # Raises when a phrase is not in the line or the beats are out of order.
    phrase_starts(tokens, [(beat["id"], beat["phrase"]) for beat in beats], place=place)
    return beats


def check_theme(raw: object) -> dict[str, Any]:
    """The theme of an answer, checked: the lab's brief theme, and the explainer's graphics theme
    (EXG-002), which reuses it. A colour that cannot be read is kept and replaced later by
    `graphics_resolve.theme_for`.
    """
    item = _object(raw, "theme")
    accent = item.get("accent")
    if isinstance(accent, str) and _HEX.fullmatch(accent):
        accent = accent.upper()
    elif not isinstance(accent, str):
        accent = None
    return {
        "palette": _choice(item.get("palette"), "palette", PALETTES),
        # A colour that cannot be read is replaced by the resolver, with a note: not refused.
        "accent": accent,
        "background": _choice(item.get("background"), "background", BACKGROUNDS),
        "motion": _choice(item.get("motion"), "motion", MOTIONS),
        "mood": _text(item.get("mood"), "mood", MOOD_MAX_CHARS),
    }


def check_brief(
    answer: dict[str, Any],
    line: str,
    *,
    context: str | None = None,
    with_theme: bool = True,
) -> dict[str, Any]:
    """The model's answer as the stored brief, or ValueError with a message fit for the user and
    for the model's corrected retry (§4.3).

    With no `context` (the lab), the line is the reference for the facts and for the beats. For
    a graphic shot of an explainer (EXG-004) `line` is the shot's own words, which the beats
    must fall on, and `context` is the text of the sentences around them, in which a fact may be
    said (the soft number rule, EXG-004). With `with_theme` false, the brief has no theme.
    """
    words = line_words(line)
    tokens = line_tokens(words)
    if context is None:
        fact_words, fact_tokens, fact_place, beat_place = words, tokens, LINE, LINE
    else:
        fact_words = line_words(context)
        fact_tokens = line_tokens(fact_words)
        fact_place = "the shot's words or the sentences around them"
        beat_place = "the shot's words"

    kind = _choice(answer.get("kind"), "kind", KINDS)
    intent = _text(answer.get("intent"), "intent", INTENT_MAX_CHARS)
    visual_brief = _text(answer.get("visual_brief"), "visual_brief", VISUAL_BRIEF_MAX_CHARS)

    seen: set[str] = set()
    facts = [
        _check_fact(raw, position, seen, fact_words, fact_tokens, fact_place)
        for position, raw in enumerate(_list(answer.get("facts"), "facts", 0, MAX_FACTS), start=1)
    ]
    by_id = {fact["id"]: fact for fact in facts}
    derived = [
        _check_derived(raw, position, seen, by_id)
        for position, raw in enumerate(
            _list(answer.get("derived"), "derived", 0, MAX_DERIVED), start=1
        )
    ]
    beats = _check_beats(answer.get("beats"), seen, tokens, beat_place)
    brief: dict[str, Any] = {
        "kind": kind,
        "intent": intent,
        "visual_brief": visual_brief,
        "facts": facts,
        "derived": derived,
        "beats": beats,
    }
    if with_theme:
        brief["theme"] = check_theme(answer.get("theme"))
    return brief
