"""Writing the prompt for a library character's master look picture, and the sample line for a
voice audition, with a language model. Pure functions, no I/O.

Both come from the same thing: the character card (`character_library.character_card`). The
job that drives this is `jobs/write_character_look_prompt.py`, with `requested` saying which of
the two answers it wants:

- `"master"`: one prompt for the image model, in the shape `image_prompt_writer.py`'s answer
  already has (`{"image_prompt": ...}`), using the Qwen character-sheet profile (a character
  alone on a white studio backdrop) that the project's own cast reference already uses
  (`image_prompt_profiles.ACTIVE_CHARACTER_SHEET_PROFILE`: the same picture that is cut out
  afterwards), with this module's own `_render_master_inputs` (the inputs are a character
  card, not a cast member's description, so the generic reader and checks of
  `image_prompt_writer.py` are reused, but the request is built here).
- `"audition"`: one short line of dialogue (`{"audition_line": ...}`) the character might say,
  written from its personality, for a Voice lab `design` run to speak while choosing a voice.

The call is made by `providers/llm.py` through `jobs/llm_call.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from app.providers import llm
from app.services.image_prompt_profiles import ImagePromptProfile
from app.services.image_prompt_writer import MAX_TOKENS, REASONING_EFFORT

AUDITION_LINE: Final = "audition_line"
AUDITION_LINE_MAX_CHARS: Final = 300
AUDITION_MIN_WORDS: Final = 6
AUDITION_MAX_WORDS: Final = 30


def _one_line(value: str) -> str:
    return " ".join(value.split())


# --- The master look picture's prompt (reuses image_prompt_writer's reader and checks) -----


def prompt_inputs(card: str) -> dict[str, Any]:
    """What the model is told: the character card, as one plain dict (the user message is
    rendered from it alone).
    """
    return {"card": card}


def _render_master_inputs(inputs: dict[str, Any]) -> str:
    return f"Character card:\n{inputs['card']}"


def _master_system_prompt(profile: ImagePromptProfile) -> str:
    return "\n".join(
        [
            "You write one prompt for a text-to-image model. The picture it makes is the "
            "reference picture of one character of a library of characters: every picture, "
            "scene and clip of the character later is made to match it, so it must show "
            "clearly how the character looks.",
            "",
            f"- The image model ({profile.image_model}) sees only the prompt you write.",
            "- You are given a card describing the character: its age, gender, species, "
            "time, appearance, outfit, personality and any other notes. Use what concerns "
            "the looks; the personality and the notes only guide the bearing and the "
            "expression.",
            "- There is no author's style for this picture, so rule 6 below always applies "
            "as 'none given' (a natural, realistic look), unless the appearance itself "
            "describes a stylised look (a cartoon, a puppet, a painting).",
            "- Never write the character's name in the prompt.",
            "",
            profile.prompt_rules,
            "",
            "Example (an unrelated character; do not reuse its content):",
            "Input:",
            _render_master_inputs({"card": _EXAMPLE_CARD}),
            "Answer:",
            json.dumps({"image_prompt": _EXAMPLE_MASTER_ANSWER}, ensure_ascii=False),
            "",
            "Answer with one JSON object only, in exactly this form:",
            '{"image_prompt": "..."}',
        ]
    )


_EXAMPLE_CARD: Final = (
    "Name: Tomas.\n"
    "Age: 70 years old.\n"
    "Gender: male.\n"
    "Species: human.\n"
    "Time: set in the present day.\n"
    "Appearance: An elderly lighthouse keeper, lean and weathered, with deeply tanned skin, a "
    "short white beard, a lined, kind face and thinning white hair.\n"
    "Outfit: A thick navy wool fisherman's jumper with a high collar and patched elbows, loose "
    "charcoal trousers tucked into worn brown leather boots, and a brass-buttoned oilskin coat.\n"
    "Personality: Patient and watchful, with the calm of a man who has spent his life alone.\n"
    "Has a visible mouth."
)

_EXAMPLE_MASTER_ANSWER: Final = (
    "A natural studio photograph of an elderly lighthouse keeper standing alone and facing "
    "the viewer. He is a lean, weathered man of about seventy with deeply tanned skin, a "
    "short white beard, a lined, kind face and thinning white hair, and his expression is "
    "calm and watchful. He wears a thick navy wool fisherman's jumper with a high collar and "
    "patched elbows, loose charcoal trousers tucked into worn brown leather boots, and a "
    "brass-buttoned oilskin coat. He stands in a relaxed, neutral pose with his arms "
    "slightly away from his body, so the jumper, the coat and his hands can be seen, and his "
    "whole figure from boots to hair fills the tall frame, centred, with a little space "
    "around him. He is set against a plain, seamless white studio backdrop and lit by soft, "
    "even light from the front, so the white behind him stays clean and bright. The palette "
    "is muted navy, charcoal and brown, rendered as a natural, realistic photograph."
)


def _master_from_picture_system_prompt(profile: ImagePromptProfile) -> str:
    return "\n".join(
        [
            "You write one prompt for an image-editing model. It is shown the author's own "
            "picture of a character (image 1), and makes from it the reference picture of that "
            "character for a library of characters: every picture, scene and clip of the "
            "character later is made to match it, so it must show clearly how the character "
            "looks.",
            "",
            f"- The image model ({profile.image_model}) sees image 1 and the prompt you write, "
            "nothing else.",
            "- You are given a card describing the character: its age, gender, species, time, "
            "appearance, outfit, personality and any other notes. The picture decides who the "
            "character is; the card adds the outfit and, when it describes one, the style. The "
            "personality and the notes only guide the bearing and the expression.",
            "- Never write the character's name in the prompt.",
            "",
            profile.prompt_rules,
            "",
            "Example (an unrelated character; do not reuse its content):",
            "Input:",
            _render_master_inputs(profile.example_inputs),
            "Answer:",
            profile.example_answer,
            "",
            "Answer with one JSON object only, in exactly this form:",
            '{"image_prompt": "..."}',
        ]
    )


def build_master_request(
    inputs: dict[str, Any], *, model: str, profile: ImagePromptProfile
) -> dict[str, Any]:
    """The exact request body sent to the model for the master look prompt. Nothing about the
    call is hidden from the job record: this body is stored on the job (`job.input.request`).

    A profile that `uses_references` is the one for a look started from the author's own
    picture: the image model is then shown that picture as image 1.
    """
    if profile.uses_references:
        system_prompt = _master_from_picture_system_prompt(profile)
        task = "Write the image prompt for this character's reference picture, made from image 1."
    else:
        system_prompt = _master_system_prompt(profile)
        task = "Write the image prompt for this character's reference picture."
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "\n".join(
                    [
                        task,
                        "",
                        _render_master_inputs(inputs),
                        "",
                        "Write the image prompt now.",
                    ]
                ),
            },
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- The voice audition's sample line -------------------------------------------------------


def _render_audition_inputs(inputs: dict[str, Any]) -> str:
    return f"Character card:\n{inputs['card']}"


def _audition_system_prompt() -> str:
    return "\n".join(
        [
            "You write one short line of dialogue that a character might plausibly say, so "
            "an author can hear a candidate voice speak it while choosing which voice suits "
            "the character.",
            "",
            "- You are given a card describing the character: its age, gender, species, "
            "time, appearance, personality and any other notes.",
            "- Write ONE sentence, or two short ones, in the character's own voice: what it "
            "would say, not a description of it. 6 to 30 words.",
            "- Fit the personality and the time it is from. Never write a stage direction, a "
            "narration or the character's name.",
            "- Plain, speakable English: no quotation marks around the whole line, no "
            "emoji, no stage directions in brackets or parentheses.",
            "",
            "Example (an unrelated character; do not reuse its content):",
            "Input:",
            _render_audition_inputs({"card": _EXAMPLE_CARD}),
            "Answer:",
            '{"audition_line": '
            '"The sea keeps its own hours, and I\'ve learned to keep mine beside it."}',
            "",
            "Answer with one JSON object only, in exactly this form:",
            '{"audition_line": "..."}',
        ]
    )


def build_audition_request(inputs: dict[str, Any], *, model: str) -> dict[str, Any]:
    """The exact request body sent to the model for an audition line. Nothing about the call
    is hidden from the job record: this body is stored on the job (`job.input.request`).
    """
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _audition_system_prompt()},
            {
                "role": "user",
                "content": "\n".join(
                    [
                        "Write the audition line for this character.",
                        "",
                        _render_audition_inputs(inputs),
                        "",
                        "Write the audition line now.",
                    ]
                ),
            },
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


def parse_audition_answer(content: str) -> dict[str, Any]:
    """The model's answer as a dict. Raises ValueError, with a message fit for the user, when
    it is empty, not JSON, or has no `audition_line` text.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    line = answer.get(AUDITION_LINE) if isinstance(answer, dict) else None
    if not isinstance(line, str) or not line.strip():
        raise ValueError('The model\'s answer had no "audition_line" text.')
    return answer


@dataclass(frozen=True)
class CheckedLine:
    text: str
    word_count: int
    warnings: tuple[str, ...]


def check_audition_line(answer: dict[str, Any]) -> CheckedLine | None:
    """The answer's line made into one sentence and checked, or None when it cannot be used:
    it is not text, is empty, or is longer than the limit. A line outside the word range
    earns a warning, which never blocks saving.
    """
    value = answer.get(AUDITION_LINE)
    if not isinstance(value, str):
        return None
    text = _one_line(value)
    if not text or len(text) > AUDITION_LINE_MAX_CHARS:
        return None
    words = len(text.split())
    warnings: list[str] = []
    if words < AUDITION_MIN_WORDS or words > AUDITION_MAX_WORDS:
        warnings.append(
            f"The audition line has {words} words. {AUDITION_MIN_WORDS} to "
            f"{AUDITION_MAX_WORDS} works best."
        )
    return CheckedLine(text=text, word_count=words, warnings=tuple(warnings))
