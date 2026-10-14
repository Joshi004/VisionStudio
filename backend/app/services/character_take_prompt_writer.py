"""Writing a take's prompts with a language model: up to three texts, depending on what the
take makes and whether it has dialogue (Phase 25). Pure functions, no I/O.

- `image_prompt`: for an image take, or a video take's first frame. The picture is made by
  editing the character's own reference pictures (already on a plain white backdrop), the same
  discipline as a project scene made from its cast's references
  (`image_prompt_profiles.QWEN_IMAGE_21_CHARACTER_EDIT`), adapted to one character and no scene
  cast or place.
- `video_prompt`: for a video take, what the clip shows over its length: the motion, the camera,
  and the character speaking (when there is dialogue) or not.
- `delivery_instruction`: for an audio take, or a video take with dialogue: how the character's
  saved voice reads the line aloud (Breeze TTS "direction" mode).

`needed_keys` says exactly which of the three a take's remaining steps still need (an image
take needs only `image_prompt`; a silent video needs `image_prompt` and `video_prompt`; a video
with dialogue needs all three; an audio take needs only `delivery_instruction`). The job
(`jobs/write_character_take_prompt.py`) asks the model for exactly that set, and nothing is
wasted writing a text no step will use.

The call is made by `providers/llm.py` through `jobs/llm_call.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.providers import llm, speech_synthesizer

# Hidden reasoning is billed as output. Three short texts are at most a few hundred tokens, so
# this leaves room to think.
MAX_TOKENS: Final = 8000
REASONING_EFFORT: Final = "high"
FIELD_MAX_CHARS: Final = 4000

IMAGE_PROMPT: Final = "image_prompt"
VIDEO_PROMPT: Final = "video_prompt"
DELIVERY_INSTRUCTION: Final = "delivery_instruction"
_KEYS: Final = (IMAGE_PROMPT, VIDEO_PROMPT, DELIVERY_INSTRUCTION)

Output = Literal["image", "audio", "video"]

IMAGE_MIN_WORDS: Final = 60
IMAGE_MAX_WORDS: Final = 200
VIDEO_MIN_WORDS: Final = 30
VIDEO_MAX_WORDS: Final = 120
DELIVERY_MAX_CHARS: Final = speech_synthesizer.INSTRUCTION_MAX_CHARS

ACTION_MAX_CHARS: Final = 1000
DIALOGUE_MAX_CHARS: Final = speech_synthesizer.TEXT_MAX_CHARS

_DOUBLE_QUOTES = re.compile(r"[\"\u201c\u201d\u201e]")
_NEGATIVE_WORDS = re.compile(r"\b(no|not|without|never|nothing)\b", re.IGNORECASE)


def _one_line(value: str) -> str:
    return " ".join(value.split())


def needed_keys(output: Output, dialogue: str | None) -> frozenset[str]:
    """Which of the three texts a take's remaining steps need, from what it makes and whether
    it has dialogue. Every video needs its own first-frame picture, so `image_prompt` is one
    of them for both "image" and "video".
    """
    has_dialogue = dialogue is not None and dialogue.strip() != ""
    if output == "image":
        return frozenset({IMAGE_PROMPT})
    if output == "audio":
        return frozenset({DELIVERY_INSTRUCTION})
    keys = {IMAGE_PROMPT, VIDEO_PROMPT}
    if has_dialogue:
        keys.add(DELIVERY_INSTRUCTION)
    return frozenset(keys)


def prompt_inputs(
    *, card: str, action: str | None, dialogue: str | None, needed: frozenset[str]
) -> dict[str, Any]:
    """What the model is told, as one plain dict (the user message is rendered from it)."""
    return {
        "card": card,
        "action": _one_line(action or "") or None,
        "dialogue": _one_line(dialogue or "") or None,
        "needed": sorted(needed),
    }


def _render_inputs(inputs: dict[str, Any]) -> str:
    action = inputs.get("action")
    dialogue = inputs.get("dialogue")
    lines = [
        f"Character card:\n{inputs['card']}",
        f"What happens: {action}" if action else "What happens: nothing in particular.",
        f"The character says: {dialogue}" if dialogue else "The character says nothing.",
        f"Write: {', '.join(inputs['needed'])}.",
    ]
    return "\n".join(lines)


_TASK_TEXT: Final[dict[str, str]] = {
    IMAGE_PROMPT: (
        'Rules for "image_prompt": the picture is made by editing one or two reference '
        "pictures of this one character, already standing on a plain white studio backdrop. "
        "Never describe the character's face, hair, build, skin or clothes: the reference "
        "pictures show them, and any words about them can change them. Say only what the "
        "character does in this new picture (its pose and its expression), where it is and "
        "what is around it, where things sit in the frame, the shot size and the angle, the "
        "lens look, the light, the colour palette and the style. If there is no setting, "
        "place the character against a plain, softly lit backdrop that suits the action. One "
        "paragraph of plain English prose, present tense, "
        f"{IMAGE_MIN_WORDS} to {IMAGE_MAX_WORDS} words. Nothing is written in the picture: no "
        "text, signs, labels or logos. The model has no negative prompt: say what fills the "
        "space instead of saying what is absent."
    ),
    VIDEO_PROMPT: (
        'Rules for "video_prompt": the clip starts from the picture `image_prompt` makes, and '
        "this describes what happens over the next few seconds: the motion, the camera "
        "(steady, a slow push, a pan), and the character's expression. When the character "
        "speaks a line, say that it speaks the line, naturally and clearly, without quoting "
        "the words (the clip's sound comes from a separate speech, not from this text). When "
        "it does not speak, describe only its motion and expression: never imply speech. One "
        f"paragraph of plain English prose, present tense, {VIDEO_MIN_WORDS} to "
        f"{VIDEO_MAX_WORDS} words."
    ),
    DELIVERY_INSTRUCTION: (
        'Rules for "delivery_instruction": how the character\'s own voice reads its line '
        "aloud, for a speech model that is steered by a short instruction (not the words "
        "themselves). Describe the tone, the emotion and the pace the personality and what is "
        "happening call for, in one or two short sentences, plain prose, up to "
        f"{DELIVERY_MAX_CHARS} characters."
    ),
}


def _system_prompt(needed: frozenset[str]) -> str:
    rules = "\n\n".join(_TASK_TEXT[key] for key in _KEYS if key in needed)
    answer_shape = ", ".join(f'"{key}": "..."' for key in _KEYS if key in needed)
    return "\n".join(
        [
            "You write the prompts for one thing made from a library character: a picture, a "
            "piece of speech, a video, or some of these together. An author tries ideas in a "
            "lab and may edit what you write before anything runs.",
            "",
            "- You are given a card describing the character (its appearance, personality and "
            "notes), what happens, and what it says, if anything.",
            "- Write only the texts asked for below. Do not write the character's name in any "
            "of them: a picture is made from reference pictures, not from the name, and a "
            "video or a speech names no one either.",
            "",
            rules,
            "",
            f"Answer with one JSON object only, in exactly this form: {{{answer_shape}}}",
        ]
    )


def build_request(inputs: dict[str, Any], *, model: str) -> dict[str, Any]:
    """The exact request body sent to the model. Nothing about the call is hidden from the job
    record: this body is stored on the job (`job.input.request`).
    """
    needed = frozenset(inputs["needed"])
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt(needed)},
            {
                "role": "user",
                "content": _render_inputs(inputs) + "\n\nWrite the prompts now.",
            },
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- Reading the answer -----------------------------------------------------------------


def parse_answer(content: str, needed: frozenset[str]) -> dict[str, Any]:
    """The model's answer as a dict. Raises ValueError, with a message fit for the user, when
    it is empty, not JSON, or is missing text for one of the keys asked for.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    if not isinstance(answer, dict):
        raise ValueError("The model's answer was not a JSON object.")
    for key in needed:
        value = answer.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'The model\'s answer had no "{key}" text.')
    return answer


@dataclass(frozen=True)
class CheckedTakePrompts:
    """The texts that were asked for, each on one line, with the warnings they earned. A text
    that was not asked for is None.
    """

    image_prompt: str | None
    video_prompt: str | None
    delivery_instruction: str | None
    warnings: tuple[str, ...]


def _checked_text(answer: dict[str, Any], key: str) -> str:
    value = answer.get(key)
    if not isinstance(value, str):
        raise ValueError(f'The model\'s "{key}" was not text.')
    text = _one_line(value)
    if not text or len(text) > FIELD_MAX_CHARS:
        raise ValueError(
            f'The model\'s "{key}" was empty or longer than {FIELD_MAX_CHARS:,} characters.'
        )
    return text


def check_prompts(answer: dict[str, Any], needed: frozenset[str]) -> CheckedTakePrompts:
    """The answer's texts made into single lines and checked. Raises ValueError, with a
    message for the user, when one that was asked for cannot be used: not text, empty, or
    longer than the limit.

    Warnings never block: a text of an unusual length, or one that breaks a wording rule, is
    still returned, so the author can edit it before anything runs.
    """
    warnings: list[str] = []
    image_prompt = _checked_text(answer, IMAGE_PROMPT) if IMAGE_PROMPT in needed else None
    video_prompt = _checked_text(answer, VIDEO_PROMPT) if VIDEO_PROMPT in needed else None
    delivery = (
        _checked_text(answer, DELIVERY_INSTRUCTION) if DELIVERY_INSTRUCTION in needed else None
    )

    if image_prompt is not None:
        words = len(image_prompt.split())
        if words < IMAGE_MIN_WORDS or words > IMAGE_MAX_WORDS:
            warnings.append(
                f"The image prompt has {words} words. {IMAGE_MIN_WORDS} to {IMAGE_MAX_WORDS} "
                "works best."
            )
        if _NEGATIVE_WORDS.search(image_prompt):
            warnings.append(
                "A negative found in the image prompt (no, not, without). The image model has "
                "no negative prompt, and naming a thing can make it appear: say what is there "
                "instead."
            )
    if video_prompt is not None:
        words = len(video_prompt.split())
        if words < VIDEO_MIN_WORDS or words > VIDEO_MAX_WORDS:
            warnings.append(
                f"The video prompt has {words} words. {VIDEO_MIN_WORDS} to {VIDEO_MAX_WORDS} "
                "works best."
            )
        if _DOUBLE_QUOTES.search(video_prompt):
            warnings.append(
                "Double quotes found in the video prompt. The speech is a separate sound, so "
                "the words are not needed in the prompt."
            )
    if delivery is not None and len(delivery) > DELIVERY_MAX_CHARS:
        raise ValueError(
            f'The model\'s "{DELIVERY_INSTRUCTION}" was longer than {DELIVERY_MAX_CHARS} '
            "characters."
        )

    return CheckedTakePrompts(
        image_prompt=image_prompt,
        video_prompt=video_prompt,
        delivery_instruction=delivery,
        warnings=tuple(warnings),
    )
