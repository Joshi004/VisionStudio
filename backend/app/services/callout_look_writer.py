"""The callout look of a motion explainer: the instructions to the model, and the checks of what it
wrote (CMO-002, `Callouts_motion_implementation_phases.md` §4.3).

Pure functions, no I/O.

One call per project reads the graphics look and the Story Bible, and answers the one look every
motion callout of the video shares: the panel behind a callout, its corners, how it enters, how a
number or a key word stands out, how dense the callouts are, and a short note on what makes them
belong together. The enumerated values matter most: the building-blocks version of a callout can
only follow a value it has an option for.

The stored content is `{look, reason}`; see `check_answer`.
"""

from __future__ import annotations

import json
from typing import Any, Final

from app.services import user_feedback
from app.services.graphic_theme_writer import bible_for_model
from app.services.music_bible_writer import parse_answer as parse_answer
from app.services.text_limits import length_rule

PANELS: Final = ("none", "card", "glass", "underline", "ribbon")
CORNERS: Final = ("sharp", "soft", "round")
ENTRANCES: Final = ("fade_up", "wipe", "pop", "draw")
DENSITIES: Final = ("airy", "balanced", "compact")

EMPHASIS_MAX_CHARS: Final = 160
NOTES_MAX_CHARS: Final = 300
REASON_MAX_CHARS: Final = 200

# One short answer. The model's reasoning counts against the cap, so it is as large as the
# graphics look's. Tokens are paid as used.
MAX_TOKENS: Final = 12_000
REASONING_EFFORT: Final = "high"

LIMIT_NAMES: Final = {
    "look.emphasis": EMPHASIS_MAX_CHARS,
    "look.notes": NOTES_MAX_CHARS,
    "reason": REASON_MAX_CHARS,
}

# --- The instructions ------------------------------------------------------------------------

_RULES: Final = """\
You are the art director of an explainer video. A presenter speaks on camera, and now and then a \
callout appears over the picture: a short piece of text such as a hook question, a key idea or a \
big number, drawn as a small animated graphic on a transparent background, beside the presenter. \
The video already has a graphics look (palette, accent colour, background style and motion) for \
its charts and diagrams. You decide the one look every callout of this video shares, so the \
callouts feel like one family and belong to the same video. Other programs draw the callouts \
from your answer. You never draw anything and you never write the words of a callout.

THE LOOK
- "panel" is "{panels}": what sits behind a callout's text so it stays readable over live video. \
"none" is text only, "card" a solid rounded box, "glass" a soft translucent box, "underline" a \
line under the text, "ribbon" a bar on one side.
- "corners" is "{corners}": the corners of any box or bar.
- "entrance" is "{entrances}": how a callout appears. "fade_up" fades in while rising a little, \
"wipe" reveals it sideways, "pop" scales it in, "draw" draws its lines first.
- "density" is "{densities}": how much room a callout takes and how much padding it keeps.
- "emphasis" is one sentence on how a number or a key word is made to stand out, for example \
with the accent colour, a larger size or a heavier weight.
- "notes" is a short note on what makes these callouts belong together and with the graphics \
look.
- "reason" is one short sentence on why this look suits this video. It sits at the top level of \
the answer, beside "look", not inside it.

Use the graphics look you are given: the callouts keep its colours, fonts and pace. The video is \
watched on a phone as well as on a computer, so the callouts stay clear and simple, and they \
never hide the presenter.

{feedback}

{length_rule}"""

_SHAPE: Final = """{"reason": "A calm finance explainer: quiet cards that match its smooth \
motion.", "look": {"panel": "card", "corners": "soft", "entrance": "fade_up", \
"density": "balanced", "emphasis": "Numbers are larger and use the accent colour.", \
"notes": "Rounded cards in the dark palette, entering together with the same short rise."}} \
(the values here only show the form, never copy them)"""


def _instructions() -> str:
    return (
        _RULES.format(
            panels='", "'.join(PANELS),
            corners='", "'.join(CORNERS),
            entrances='", "'.join(ENTRANCES),
            densities='", "'.join(DENSITIES),
            feedback=user_feedback.INSTRUCTION,
            length_rule=length_rule(LIMIT_NAMES),
        )
        + "\n\nAnswer with one JSON object only, in exactly this form: "
        + _SHAPE
    )


def build_request(
    graphic_theme: dict[str, Any],
    colours: dict[str, str],
    bible: dict[str, Any],
    orientation: str,
    *,
    model: str,
    feedback: user_feedback.Feedback | None = None,
) -> dict[str, Any]:
    """The exact request body of the one call. It is stored on the job.

    `graphic_theme` is the stored `content["theme"]` of the graphics look and `colours` the
    colours it resolves to.
    """
    parts = [
        "GRAPHICS LOOK (JSON):\n"
        + json.dumps({"theme": graphic_theme, "colours": colours}, ensure_ascii=False, indent=1),
        "STORY BIBLE:\n" + json.dumps(bible_for_model(bible), ensure_ascii=False, indent=1),
        f"ORIENTATION: {orientation}",
    ]
    if feedback is not None:
        parts += user_feedback.blocks(feedback, "PREVIOUS CALLOUT LOOK")
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


def _choice(look: dict[str, Any], name: str, allowed: tuple[str, ...]) -> str:
    value = look.get(name)
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f'The "{name}" was {value!r}; it must be one of {", ".join(allowed)}.')
    return value


def _text(value: object, name: str, max_chars: int) -> str:
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


def check_answer(answer: dict[str, Any]) -> dict[str, Any]:
    """The model's answer as the stored content `{look, reason}`, or ValueError with a message
    fit for the user and for the model's corrected retry.
    """
    look = answer.get("look")
    if not isinstance(look, dict):
        raise ValueError('The "look" was missing or was not an object.')
    # The model often writes "reason" inside "look". The answer is the same, so it is accepted.
    reason = answer.get("reason", look.get("reason"))
    if not isinstance(reason, str):
        raise ValueError(
            'The "reason" was missing or was not text. It belongs at the top level of the '
            'answer, beside "look", not inside it.'
        )
    return {
        "look": {
            "panel": _choice(look, "panel", PANELS),
            "corners": _choice(look, "corners", CORNERS),
            "entrance": _choice(look, "entrance", ENTRANCES),
            "emphasis": _text(look.get("emphasis"), "emphasis", EMPHASIS_MAX_CHARS),
            "density": _choice(look, "density", DENSITIES),
            "notes": _text(look.get("notes"), "notes", NOTES_MAX_CHARS),
        },
        "reason": _text(reason, "reason", REASON_MAX_CHARS),
    }
