"""The callout plan of an explainer: the instructions to the model, and the checks of what it
(or the owner) wrote (EXPLAINER-009, `Explainer_implementation_phases.md` E-14 to E-18).

Pure functions, no I/O.

A callout is a short piece of text shown over the picture to keep the viewer watching. One model
call reads the Story Bible and the script, and returns an accent colour and the callouts. Code
checks the callouts for **display rules only** (E-16): the length of the text per type, the gap
between two callouts, no two on the same stretch of speech, a most-per-minute limit, and that the
presenter's name is never shown. The phrase of a callout is never checked word for word (E-15):
it only tells where in its unit the callout belongs. One check never refuses, it warns: a
`number` callout whose number the script does not say.

**Times.** Before anything is rendered the checks need a time for each callout. Each speech
unit's `estimated_seconds` are laid end to end in story order, and a callout sits where its
phrase is in its unit (by the share of words before it). A phrase that does not match well sits at
the start of its unit. Pauses are not counted, so the gaps here are a little shorter than the real
ones. EXPLAINER-010 places each callout exactly at Render.

**The stored content** is `{accent, callouts}`; see `check_plan`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Final

from app.services.caption_plan import HIGHLIGHT_COLOUR, OUTLINE_COLOUR
from app.services.dialogue_check import normalize_words
from app.services.music_bible_writer import MAX_TOKENS, REASONING_EFFORT
from app.services.music_bible_writer import parse_answer as parse_answer
from app.services.number_words import numbers_in
from app.services.text_limits import cut_at_word, length_rule

TYPE_EMPHASIS: Final = "emphasis"
TYPE_NUMBER: Final = "number"
TYPE_QUESTION: Final = "question"
TYPE_COMPARISON: Final = "comparison"
TYPE_LIST: Final = "list"
TYPE_SECTION_TITLE: Final = "section_title"
TYPES: Final = (
    TYPE_EMPHASIS,
    TYPE_NUMBER,
    TYPE_QUESTION,
    TYPE_COMPARISON,
    TYPE_LIST,
    TYPE_SECTION_TITLE,
)
ROLES: Final = ("accent", "number", "negative", "positive")
_DEFAULT_ROLE: Final = {
    TYPE_EMPHASIS: "accent",
    TYPE_NUMBER: "number",
    TYPE_QUESTION: "accent",
    TYPE_LIST: "accent",
    TYPE_SECTION_TITLE: "accent",
}

# The most characters of the text of a callout, per type (a starting value).
TEXT_MAX_CHARS: Final = {
    TYPE_EMPHASIS: 32,
    TYPE_NUMBER: 20,
    TYPE_QUESTION: 48,
    TYPE_SECTION_TITLE: 32,
}
LIST_ITEM_MAX_CHARS: Final = 24
LIST_MIN_ITEMS: Final = 2
LIST_MAX_ITEMS: Final = 3
COMPARISON_SIDE_MAX_CHARS: Final = 24
COMPARISON_SIDES: Final = 2

MAX_CALLOUTS: Final = 60
PHRASE_MAX_CHARS: Final = 120
ACCENT_REASON_MAX_CHARS: Final = 200
MAX_WARNINGS_PER_CALLOUT: Final = 5

# A phrase matches a stretch of its unit when this share of its words is found there.
PHRASE_MATCH_MIN: Final = 0.6
# The accent must have at least this WCAG contrast ratio against the caption outline.
ACCENT_MIN_CONTRAST: Final = 4.5

_WINDOW_S: Final = 60.0
# Two starts closer than the gap by less than this are still counted as far enough apart.
_GAP_TOLERANCE_S: Final = 0.05
_MIN_UNIT_SECONDS: Final = 0.5
_MIN_NAME_PART_LETTERS: Final = 3

LIMIT_NAMES: Final = {
    f"callouts[].text ({kind})": limit for kind, limit in TEXT_MAX_CHARS.items()
} | {
    "callouts[].items[].text (list)": LIST_ITEM_MAX_CHARS,
    "callouts[].sides[].text (comparison)": COMPARISON_SIDE_MAX_CHARS,
}


@dataclass(frozen=True)
class CalloutRules:
    """The display limits the plan is checked against. Recorded on every version."""

    min_gap_ms: int
    per_minute_max: int

    def as_dict(self) -> dict[str, int]:
        return {"min_gap_ms": self.min_gap_ms, "per_minute_max": self.per_minute_max}


@dataclass(frozen=True)
class ScriptUnit:
    """One speech unit of the script, placed on the story's estimated timeline."""

    scene_id: str
    scene_title: str
    unit_id: str
    text: str
    # Seconds from the start of the story, and how long the unit lasts (both estimated).
    start_s: float
    seconds: float
    words: tuple[str, ...]
    order: int

    @property
    def ref(self) -> str:
        """How the model and the checks name this unit: `scene_id/unit_id`."""
        return f"{self.scene_id}/{self.unit_id}"


def script_units(scenes: list[dict[str, Any]]) -> list[ScriptUnit]:
    """The script as units laid end to end. `scenes` is in story order; each is
    `{"id", "title", "units": [speech unit, ...]}` with the units in order, each with its
    `id`, `text` and `estimated_seconds` (`services/speech_unit_planner`).
    """
    found: list[ScriptUnit] = []
    clock = 0.0
    for scene in scenes:
        for unit in scene["units"]:
            seconds = max(float(unit.get("estimated_seconds") or 0), _MIN_UNIT_SECONDS)
            text = str(unit["text"])
            found.append(
                ScriptUnit(
                    scene_id=str(scene["id"]),
                    scene_title=str(scene["title"]),
                    unit_id=str(unit["id"]),
                    text=text,
                    start_s=clock,
                    seconds=seconds,
                    words=tuple(normalize_words(text)),
                    order=len(found),
                )
            )
            clock += seconds
    return found


# --- The instructions ----------------------------------------------------------------------

_ROLE_RULES: Final = """\
CALLOUT TYPES
- "emphasis": the key idea of a passage in a few words.
- "number": the one big number of a passage, as the viewer should read it ("10 lakh", "73%", \
"3x"). Use the number as the script says it. Never invent or round a number the script does not \
give.
- "question": a hook question that makes the viewer want the answer. Best near the start of a \
part.
- "comparison": two things set against each other. Give exactly two "sides", each with its own \
short "text", the "phrase" of the script where it is spoken, and its "role".
- "list": two or three items that build up as the presenter says them. Give "items", each with \
its own short "text" and the "phrase" of the script where it is spoken.
- "section_title": the name of a new part of the explainer, shown alone in the middle of the \
screen. Use very few, and only where the explainer clearly moves to a new part.

ROLES (the colour of a callout)
- "number": a neutral number.
- "negative": a loss, a risk, a warning, the weaker side of a comparison.
- "positive": a gain, growth, the stronger side of a comparison.
- "accent": everything else.
A "comparison" has no role of its own: its two sides each have one. Every other callout has one \
"role"."""

_PLAN_RULES: Final = """\
You plan the callouts of an explainer video: short pieces of text shown on the picture, over \
the presenter or over the B-roll, while the presenter speaks. A viewer who sees the right \
words at the right moment keeps watching.

You are given the Story Bible (the tone and the style), the presenter's name, and the whole \
script in order. The script is a list of lines; each line has a reference \
(`scene_id/unit_id`), about how many seconds into the video it starts, and what the presenter \
says.

WHAT TO MAKE
- Callouts keep the viewer watching: a hook question, the key idea in a few words, the big \
number, a clear comparison, a list that builds up.
- Fewer, stronger callouts beat many. Leave most of the script without one. Do not put a \
callout on every line.
- Never show the presenter's name, not even a part of it.
- Never repeat a whole sentence of the script. A callout is a few words, in your own words if \
that is shorter or stronger than the script's.
- Write in the language of the script, in plain sentence case, with no emoji and no quotation \
marks.

WHERE EACH ONE GOES
- "unit" is the reference of the line the callout belongs to, copied exactly as given.
- "phrase" is a few words of that line, near where the callout should appear. It does not have \
to be exact, it only tells where in the line the callout belongs.

{types}

ACCENT COLOUR
Pick one "accent" colour for the whole video, as a hex value like "#2EC4B6", that suits the \
tone and the visual style. It is drawn on dark outlines and over video, so it must be bright and \
readable. Give a short "reason".

DISPLAY RULES (an answer that breaks one is sent back)
- At least {gap_s} seconds between the start of two callouts. The seconds in the script are \
estimates, so leave some room.
- At most {per_minute} callouts in any one minute of the video.
- No two callouts on the same stretch of speech.
- Every text fits its maximum number of characters.

{length_rule}"""

_PLAN_SHAPE: Final = """{"accent": {"colour": "#2EC4B6", "reason": "bright teal that suits the \
calm, clear tone"}, "callouts": [{"type": "question", "role": "accent", \
"unit": "scene_id/su_1", "phrase": "a few words of the line", "text": "Where does your \
money go?"}, {"type": "number", "role": "number", "unit": "scene_id/su_4", \
"phrase": "ten lakh rupees", "text": "10 lakh"}, {"type": "comparison", \
"unit": "scene_id/su_6", "phrase": "savings account", "sides": [{"text": "Savings account", \
"phrase": "savings account", "role": "negative"}, {"text": "Index fund", \
"phrase": "index fund", "role": "positive"}]}, {"type": "list", "role": "accent", \
"unit": "scene_id/su_8", "phrase": "three things", "items": [{"text": "Start early", \
"phrase": "start early"}, {"text": "Stay invested", "phrase": "stay invested"}]}]} \
(the values here only show the form, never copy them)"""


def _instructions(rules: CalloutRules) -> str:
    seconds = rules.min_gap_ms / 1000
    return (
        _PLAN_RULES.format(
            types=_ROLE_RULES,
            gap_s=f"{seconds:g}",
            per_minute=rules.per_minute_max,
            length_rule=length_rule(LIMIT_NAMES),
        )
        + "\n\nAnswer with one JSON object only, in exactly this form: "
        + _PLAN_SHAPE
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def _bible_for_model(bible: dict[str, Any]) -> dict[str, Any]:
    """The fields of the Story Bible that say how the explainer sounds and looks."""
    narration = (bible.get("storytelling_style") or {}).get("narration")
    return {
        "title": bible.get("title"),
        "subject_and_format": bible.get("genre"),
        "tone": bible.get("tone"),
        "visual_style": bible.get("visual_style"),
        "how_the_presenter_speaks": narration,
    }


def script_text(units: list[ScriptUnit]) -> str:
    """The script as the model reads it: scene headings, then one line per unit."""
    lines: list[str] = []
    scene_id: str | None = None
    for unit in units:
        if unit.scene_id != scene_id:
            scene_id = unit.scene_id
            lines.append(f"\nSCENE: {unit.scene_title}")
        lines.append(f"[{unit.ref}] (starts at about {unit.start_s:.0f} s) {unit.text}")
    return "\n".join(lines).strip()


def build_request(
    bible: dict[str, Any],
    presenter_name: str,
    units: list[ScriptUnit],
    rules: CalloutRules,
    *,
    model: str,
) -> dict[str, Any]:
    """The exact request body of the one call. It is stored on the job."""
    user = (
        "STORY BIBLE:\n"
        + _json(_bible_for_model(bible))
        + f"\n\nPRESENTER (never show this name): {presenter_name}"
        + "\n\nSCRIPT:\n"
        + script_text(units)
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _instructions(rules)},
            {"role": "user", "content": user},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- Where a phrase is -----------------------------------------------------------------------


def locate_phrase(words: tuple[str, ...] | list[str], phrase: str) -> tuple[int, int] | None:
    """Where `phrase` is in `words` (both as `normalize_words` writes them): the first word and
    one past the last, or None when no stretch of the words matches it well enough
    (`PHRASE_MATCH_MIN`). The phrase is never checked word for word: this is the closest stretch.
    It only needs the words, so Render can use it on a unit's timed words as well.
    """
    wanted = normalize_words(phrase)
    if not wanted or not words:
        return None
    size = min(len(wanted), len(words))
    best_ratio = 0.0
    best_start = 0
    for start in range(len(words) - size + 1):
        ratio = SequenceMatcher(None, words[start : start + size], wanted, autojunk=False).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = start
    if best_ratio < PHRASE_MATCH_MIN:
        return None
    return best_start, best_start + size


# --- Checking what was written -------------------------------------------------------------


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"The {name} was not an object.")
    return value


def _text(value: object, name: str, max_chars: int) -> str:
    """One piece of text on one line. Refused when it is not text, is empty, or is over
    `max_chars`: a callout that does not fit is not cut behind anyone's back.
    """
    if not isinstance(value, str):
        raise ValueError(f"The {name} was missing or was not text.")
    text = " ".join(value.split())
    if not text:
        raise ValueError(f"The {name} was empty.")
    if len(text) > max_chars:
        raise ValueError(
            f'The {name} "{text}" was {len(text)} characters; the most allowed is {max_chars}.'
        )
    return text


def _role(value: object, name: str, default: str | None) -> str:
    if value is None or value == "":
        if default is None:
            raise ValueError(f"The {name} has no role.")
        return default
    if not isinstance(value, str) or value not in ROLES:
        allowed = ", ".join(ROLES)
        raise ValueError(f'The {name} has the role "{value}"; it must be one of {allowed}.')
    return value


def _phrase(value: object, name: str) -> str:
    if not isinstance(value, str) or not " ".join(value.split()):
        raise ValueError(f"The {name} has no phrase.")
    return cut_at_word(" ".join(value.split()), PHRASE_MAX_CHARS)


def name_parts(presenter_name: str) -> tuple[str, ...]:
    """The words of the presenter's name that no callout may show: every part of 3 letters or
    more (or all the parts of a name that has none), as `normalize_words` writes them.
    """
    parts = normalize_words(presenter_name)
    long_parts = [part for part in parts if len(part) >= _MIN_NAME_PART_LETTERS]
    return tuple(long_parts or parts)


def _shown_texts(callout: dict[str, Any]) -> list[str]:
    texts = [callout["text"]] if callout["text"] else []
    texts += [item["text"] for item in callout["items"] or []]
    texts += [side["text"] for side in callout["sides"] or []]
    return texts


def _first_text(callout: dict[str, Any]) -> str:
    texts = _shown_texts(callout)
    return texts[0] if texts else ""


def _check_name_not_shown(callout: dict[str, Any], label: str, names: tuple[str, ...]) -> None:
    if not names:
        return
    shown = {word for text in _shown_texts(callout) for word in normalize_words(text)}
    for part in names:
        if part in shown:
            raise ValueError(
                f"{label} shows the presenter's name (\"{part}\"). Never show the presenter's name."
            )


def _number_warnings(callout: dict[str, Any], unit: ScriptUnit) -> list[str]:
    """Warnings for a `number` callout: its number is not said in its unit. Never a refusal."""
    if callout["type"] != TYPE_NUMBER:
        return []
    shown = numbers_in(callout["text"])
    if not shown:
        return [f'The text "{callout["text"]}" has no number in it.']
    missing = sorted(shown - numbers_in(unit.text))
    if not missing:
        return []
    listed = ", ".join(format_number(value) for value in missing)
    return [f"The number {listed} is not said in this line of the script."]


def _check_shape(
    raw: dict[str, Any], label: str, kind: str
) -> tuple[str | None, list[dict[str, str]] | None, list[dict[str, str]] | None, str | None]:
    """The text, the items and the sides of a callout of this type, and its role."""
    text: str | None = None
    items: list[dict[str, str]] | None = None
    sides: list[dict[str, str]] | None = None
    role: str | None = None
    if kind == TYPE_COMPARISON:
        raw_sides = raw.get("sides")
        if not isinstance(raw_sides, list) or len(raw_sides) != COMPARISON_SIDES:
            raise ValueError(f"{label} is a comparison, so it needs exactly two sides.")
        sides = []
        for number, side in enumerate(raw_sides, start=1):
            name = f"side {number} of {label}"
            side = _object(side, name)
            sides.append(
                {
                    "text": _text(side.get("text"), f"text of {name}", COMPARISON_SIDE_MAX_CHARS),
                    "phrase": _phrase(side.get("phrase") or raw.get("phrase"), name),
                    "role": _role(side.get("role"), name, None),
                }
            )
    elif kind == TYPE_LIST:
        raw_items = raw.get("items")
        if (
            not isinstance(raw_items, list)
            or not LIST_MIN_ITEMS <= len(raw_items) <= LIST_MAX_ITEMS
        ):
            raise ValueError(
                f"{label} is a list, so it needs {LIST_MIN_ITEMS} to {LIST_MAX_ITEMS} items."
            )
        items = []
        for number, item in enumerate(raw_items, start=1):
            name = f"item {number} of {label}"
            item = _object(item, name)
            items.append(
                {
                    "text": _text(item.get("text"), f"text of {name}", LIST_ITEM_MAX_CHARS),
                    "phrase": _phrase(item.get("phrase") or raw.get("phrase"), name),
                }
            )
        role = _role(raw.get("role"), label, _DEFAULT_ROLE[kind])
    else:
        text = _text(raw.get("text"), f"text of {label}", TEXT_MAX_CHARS[kind])
        role = _role(raw.get("role"), label, _DEFAULT_ROLE[kind])
    return text, items, sides, role


def _check_callout(
    raw: object,
    position: int,
    *,
    by_ref: dict[str, ScriptUnit],
    names: tuple[str, ...],
    manual: bool,
) -> tuple[dict[str, Any], ScriptUnit, tuple[int, int]]:
    """One callout, checked and in its stored form, with its unit and the stretch of the unit's
    words it sits on. Raises ValueError.
    """
    label = f"Callout {position}"
    item = _object(raw, label)
    kind = item.get("type")
    if not isinstance(kind, str) or kind not in TYPES:
        raise ValueError(f'{label} has the type "{kind}"; it must be one of {", ".join(TYPES)}.')
    unit = by_ref.get(str(item.get("unit")))
    if unit is None:
        raise ValueError(
            f'{label} names the unit "{item.get("unit")}", which is not a line of the script. '
            "Copy a reference exactly as given."
        )
    phrase = _phrase(item.get("phrase"), label)
    text, items, sides, role = _check_shape(item, label, kind)

    callout: dict[str, Any] = {
        "id": "",
        "type": kind,
        "role": role,
        "enabled": bool(item.get("enabled", True)) if manual else True,
        "scene_id": unit.scene_id,
        "unit_id": unit.unit_id,
        "phrase": phrase,
        "text": text,
        "items": items,
        "sides": sides,
        "estimated_start_s": 0.0,
        "warnings": [],
    }
    _check_name_not_shown(callout, label, names)

    span = locate_phrase(unit.words, phrase)
    warnings = _number_warnings(callout, unit)
    if span is None:
        warnings.append("The phrase was not found in the line; the callout shows at its start.")
        span = (0, 1)
    callout["warnings"] = warnings[:MAX_WARNINGS_PER_CALLOUT]
    share = span[0] / len(unit.words) if unit.words else 0.0
    callout["estimated_start_s"] = round(unit.start_s + unit.seconds * share, 1)
    return callout, unit, span


def _check_display_rules(
    placed: list[tuple[int, dict[str, Any], ScriptUnit, tuple[int, int]]], rules: CalloutRules
) -> None:
    """The display rules (E-16) over the callouts that are turned on. Each entry is
    `(position, callout, unit, span)`. Raises ValueError naming the callouts at fault.
    """
    on = sorted(
        (entry for entry in placed if entry[1]["enabled"]),
        key=lambda entry: (entry[1]["estimated_start_s"], entry[0]),
    )

    def name(entry: tuple[int, dict[str, Any], ScriptUnit, tuple[int, int]]) -> str:
        return f'callout {entry[0]} ("{_first_text(entry[1])}")'

    for first, second in zip(on, on[1:], strict=False):
        gap = second[1]["estimated_start_s"] - first[1]["estimated_start_s"]
        if gap + _GAP_TOLERANCE_S < rules.min_gap_ms / 1000:
            raise ValueError(
                f"The {name(first)} and the {name(second)} start only about {gap:.1f} s apart; "
                f"at least {rules.min_gap_ms / 1000:g} s is needed. Remove one of them."
            )
    for index, first in enumerate(on):
        for second in on[index + 1 :]:
            if second[2].order != first[2].order:
                continue
            if first[3][0] < second[3][1] and second[3][0] < first[3][1]:
                raise ValueError(
                    f"The {name(first)} and the {name(second)} are on the same stretch of "
                    "speech. Keep one of them."
                )
    for index, first in enumerate(on):
        start = first[1]["estimated_start_s"]
        inside = [
            entry for entry in on[index:] if entry[1]["estimated_start_s"] < start + _WINDOW_S
        ]
        if len(inside) > rules.per_minute_max:
            raise ValueError(
                f"There are {len(inside)} callouts within one minute from the {name(first)}; "
                f"at most {rules.per_minute_max} are allowed. Remove some."
            )


def check_callouts(
    raw: object,
    *,
    units: list[ScriptUnit],
    presenter_name: str,
    rules: CalloutRules,
    manual: bool,
) -> list[dict[str, Any]]:
    """The callouts in their stored form, or ValueError with a message fit for the user and for
    the model's corrected retry.

    From the model (`manual` False) every callout is turned on and gets an id `co_1`, `co_2`
    ... in time order. From a person (`manual` True) each keeps its `id` and its `enabled`, and
    the order they were given in.
    """
    if not isinstance(raw, list):
        raise ValueError('The "callouts" were not a list.')
    if len(raw) > MAX_CALLOUTS:
        raise ValueError(f"There were {len(raw)} callouts; the most allowed is {MAX_CALLOUTS}.")
    by_ref = {unit.ref: unit for unit in units}
    names = name_parts(presenter_name)
    placed = []
    for position, item in enumerate(raw, start=1):
        callout, unit, span = _check_callout(
            item, position, by_ref=by_ref, names=names, manual=manual
        )
        if manual:
            callout["id"] = _manual_id(item, position)
        placed.append((position, callout, unit, span))
    if manual:
        ids = [entry[1]["id"] for entry in placed]
        if len(set(ids)) != len(ids):
            raise ValueError("Two callouts have the same id.")
    _check_display_rules(placed, rules)
    if manual:
        return [entry[1] for entry in placed]
    in_time = sorted(placed, key=lambda entry: (entry[1]["estimated_start_s"], entry[0]))
    for number, entry in enumerate(in_time, start=1):
        entry[1]["id"] = f"co_{number}"
    return [entry[1] for entry in in_time]


def _manual_id(item: object, position: int) -> str:
    value = item.get("id") if isinstance(item, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Callout {position} has no id.")
    return value.strip()


# --- The accent colour ---------------------------------------------------------------------


def _luminance(colour: str) -> float:
    """The WCAG relative luminance of `#RRGGBB`."""
    channels = []
    for start in (1, 3, 5):
        value = int(colour[start : start + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: str, second: str) -> float:
    """The WCAG contrast ratio of two `#RRGGBB` colours, from 1 to 21."""
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _is_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 7
        and value[0] == "#"
        and all(char in "0123456789abcdefABCDEF" for char in value[1:])
    )


def check_accent(value: object) -> dict[str, Any]:
    """`{colour, reason, note}`. Never raises: a colour that is not a hex value, or is not
    readable over the caption outline, is replaced by the default and `note` says why.
    """
    answer = value if isinstance(value, dict) else {}
    reason = answer.get("reason")
    reason_text = (
        cut_at_word(" ".join(reason.split()), ACCENT_REASON_MAX_CHARS)
        if isinstance(reason, str) and reason.strip()
        else ""
    )
    colour = answer.get("colour")
    note: str | None = None
    if not _is_hex(colour):
        note = f"The accent colour {colour!r} was not a hex value like #RRGGBB."
    else:
        ratio = contrast_ratio(str(colour), OUTLINE_COLOUR)
        if ratio < ACCENT_MIN_CONTRAST:
            note = (
                f"The accent colour {str(colour).upper()} is not readable over the caption "
                f"outline (contrast {ratio:.1f}, at least {ACCENT_MIN_CONTRAST:g} is needed)."
            )
    if note is not None:
        return {
            "colour": HIGHLIGHT_COLOUR,
            "reason": reason_text,
            "note": f"{note} The default {HIGHLIGHT_COLOUR} was used.",
        }
    return {"colour": str(colour).upper(), "reason": reason_text, "note": None}


# --- The whole plan --------------------------------------------------------------------------


def check_plan(
    answer: dict[str, Any],
    *,
    units: list[ScriptUnit],
    presenter_name: str,
    rules: CalloutRules,
) -> dict[str, Any]:
    """The model's answer as the stored content `{accent, callouts}`. Raises ValueError when a
    callout breaks a display rule (the job retries with the message). A bad accent never raises.
    """
    callouts = check_callouts(
        answer.get("callouts", []),
        units=units,
        presenter_name=presenter_name,
        rules=rules,
        manual=False,
    )
    return {"accent": check_accent(answer.get("accent")), "callouts": callouts}


def enabled_callouts(content: dict[str, Any]) -> list[dict[str, Any]]:
    """The callouts that go to the render (E-17): only the ones turned on, in order."""
    return [callout for callout in content["callouts"] if callout.get("enabled")]


def format_number(value: Decimal) -> str:
    """A number as plain digits, for messages."""
    return format(value.normalize(), "f")
