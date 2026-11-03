"""The graphics theme of a continuous explainer: the instructions to the model, and the checks of
what it wrote (EXG-002, `Explainer_graphics_implementation_phases.md` §3.3).

Pure functions, no I/O.

One call per project reads the Story Bible and the project's orientation, and answers the look of
every graphic of the video: the palette (`dark` or `light`), the accent colour, the background
style, the motion and the mood, with a short reason. The checks are the lab's brief theme
(`graphics_brief_writer.check_theme`), plus the length of the reason.

**The accent is resolved here.** `graphics_resolve.theme_for` keeps the model's accent when it
has a contrast of at least 3.0 with the palette's background, and otherwise uses the palette's
default colour and says so in a note. The stored theme holds the accent that was kept, and the
notes are stored with it, so a later phase can pass the stored theme straight to `theme_for`
without a second note.

The stored content is `{theme, reason, notes}`; see `check_answer`.
"""

from __future__ import annotations

import json
from typing import Any, Final

from app.services import graphics_resolve, user_feedback
from app.services.graphics_brief_writer import (
    BACKGROUNDS,
    MOOD_MAX_CHARS,
    MOTIONS,
    PALETTES,
    check_theme,
)
from app.services.music_bible_writer import parse_answer as parse_answer
from app.services.text_limits import length_rule

REASON_MAX_CHARS: Final = 200

# One short answer. The model's reasoning counts against the cap, so it is as large as the Story
# Bible's. Tokens are paid as used, and Qwen3.8 uses its own limit.
MAX_TOKENS: Final = 12_000
REASONING_EFFORT: Final = "high"

LIMIT_NAMES: Final = {"mood": MOOD_MAX_CHARS, "reason": REASON_MAX_CHARS}


# --- The instructions ------------------------------------------------------------------------

_RULES: Final = """\
You are the art director of an explainer video. The video cuts between a presenter on camera, \
B-roll, and graphics: charts, diagrams and text cards that are drawn by a program. You are \
given the Story Bible of the video. You decide the one look that every graphic of this video \
shares, so the graphics feel like part of the same video. Other programs draw the graphics from \
your answer. You never draw anything.

THE LOOK
- "palette" is "{palettes}". "dark" is a near-black background with white text. "light" is a \
near-white background with dark text.
- "accent" is one colour as "#RRGGBB" for the key shapes and numbers of the graphics. It must be \
easy to see on the palette's background: on "dark" the background is {dark_background}, on \
"light" it is {light_background}. Pick a clear, saturated colour that suits the subject and the \
tone of the video.
- "background" is "{backgrounds}": a flat colour, a soft gradient, a faint grid or a soft glow \
behind the graphic.
- "motion" is "{motions}": "snappy" is fast and sharp, "smooth" is even, "calm" is slow and \
gentle. Match the pace and the tone of the presenter.
- "mood" is a few words that describe the look and feeling.
- "reason" is one short sentence on why this look suits this video.

The Story Bible describes a video where the presenter speaks over B-roll. Choose a look that \
suits the subject, the tone and the visual style, and that stays clear on a phone screen.

{feedback}

{length_rule}"""

_SHAPE: Final = """{"palette": "dark", "accent": "#2ED573", "background": "grid", \
"motion": "snappy", "mood": "confident, data-driven", "reason": "A finance explainer with a fast \
presenter: a dark, clean look with a green accent for growth."} (the values here only show the \
form, never copy them)"""


def _instructions() -> str:
    return (
        _RULES.format(
            palettes='" or "'.join(PALETTES),
            backgrounds='", "'.join(BACKGROUNDS),
            motions='", "'.join(MOTIONS),
            dark_background=graphics_resolve.COLOURS["dark"]["background"],
            light_background=graphics_resolve.COLOURS["light"]["background"],
            feedback=user_feedback.INSTRUCTION,
            length_rule=length_rule(LIMIT_NAMES),
        )
        + "\n\nAnswer with one JSON object only, in exactly this form: "
        + _SHAPE
    )


def bible_for_model(bible: dict[str, Any]) -> dict[str, Any]:
    """The fields of the Story Bible that say what the video is about and how it looks."""
    narration = (bible.get("storytelling_style") or {}).get("narration")
    return {
        "title": bible.get("title"),
        "subject_and_format": bible.get("genre"),
        "tone": bible.get("tone"),
        "visual_style": bible.get("visual_style"),
        "how_the_presenter_speaks": narration,
    }


def build_request(
    bible: dict[str, Any],
    orientation: str,
    *,
    model: str,
    feedback: user_feedback.Feedback | None = None,
) -> dict[str, Any]:
    """The exact request body of the one call. It is stored on the job."""
    parts = [
        "STORY BIBLE:\n" + json.dumps(bible_for_model(bible), ensure_ascii=False, indent=1),
        f"ORIENTATION: {orientation}",
    ]
    if feedback is not None:
        parts += user_feedback.blocks(feedback, "PREVIOUS THEME")
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


def _reason(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError('The "reason" was missing or was not text.')
    text = " ".join(value.split())
    if not text:
        raise ValueError('The "reason" was empty.')
    if len(text) > REASON_MAX_CHARS:
        raise ValueError(
            f'The "reason" "{text}" was {len(text)} characters; the most allowed is '
            f"{REASON_MAX_CHARS}."
        )
    return text


def check_answer(answer: dict[str, Any]) -> dict[str, Any]:
    """The model's answer as the stored content `{theme, reason, notes}`, or ValueError with a
    message fit for the user and for the model's corrected retry.

    `theme.accent` is the accent after the contrast rule (the model's, or the palette's default),
    and `notes` says when it was replaced.
    """
    theme = check_theme(answer)
    reason = _reason(answer.get("reason"))
    colours, notes = graphics_resolve.theme_for(theme)
    theme["accent"] = colours["accent"]
    return {"theme": theme, "reason": reason, "notes": notes}
