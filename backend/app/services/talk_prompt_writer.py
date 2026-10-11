"""Writing the prompts of a take in the Talking character lab with a language model (Phase 24).
Pure functions, no I/O.

The author gives a line of dialogue, what the character is like, and optionally how the line
should be delivered. The model answers with one JSON object of two texts:

- `voice_instruction`: what steers the speech model (Breeze TTS 2): who the voice sounds like and
  how the line is delivered. Left empty when the take's voice does not use an instruction.
- `video_prompt`: what the lip-sync video model (LTX-2.3 audio-to-video) shows: the speaker,
  the act of speaking, a steady camera.

The steps are the same as for the other language model jobs:

1. `build_request`: the instructions and the data, as an OpenAI-style chat request. What
   depends on the models comes from the profile (`talk_prompt_profiles.py`).
2. `parse_answer`: the model's JSON, read defensively.
3. `check_prompts`: the two texts are tidied and checked. Wording the profile dislikes gives a
   warning. Warnings never stop the prompts from being shown: the author edits them before
   running anything. A text that cannot be used at all raises ValueError, with a message for the
   user, so the job asks again.

The call is made by `providers/llm.py` and the job that drives it is
`jobs/write_talk_prompts.py`. The system message is the same for every request (only the
profile changes it), so `description_writer.instructions_sha256` names an instruction set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.providers import llm, speech_synthesizer
from app.services.talk_prompt_profiles import TalkPromptProfile

# Hidden reasoning is billed as output (ANALYSIS.md Section 6.2, rule 4). Two short texts are a
# few hundred tokens, so this leaves room to think.
MAX_TOKENS: Final = 8000
REASONING_EFFORT: Final = "high"
FIELD_MAX_CHARS: Final = 4000

# What the author may write. The dialogue is one request of the speech model.
DIALOGUE_MAX_CHARS: Final = speech_synthesizer.TEXT_MAX_CHARS
CHARACTER_MAX_CHARS: Final = 2000
DELIVERY_MAX_CHARS: Final = 500

VIDEO_PROMPT: Final = "video_prompt"
VOICE_INSTRUCTION: Final = "voice_instruction"

# What the take's voice needs from the writer:
# - design: the voice is made from the description, so the instruction describes voice and delivery.
# - direction: a saved voice reads the line, so the instruction describes only the delivery.
# - none: a saved voice clones without an instruction, or the speech already exists.
VoiceKind = Literal["design", "direction", "none"]
VOICE_KINDS: Final[tuple[VoiceKind, ...]] = ("design", "direction", "none")

_DOUBLE_QUOTES = re.compile(r"[\"\u201c\u201d\u201e]")


def _one_line(value: str) -> str:
    return " ".join(value.split())


# --- The request --------------------------------------------------------------------------


def prompt_inputs(
    dialogue: str, character: str | None, delivery: str | None, voice_kind: VoiceKind
) -> dict[str, Any]:
    """What the model is told, as one plain dict (the user message is rendered from it)."""
    return {
        "dialogue": _one_line(dialogue),
        "character": _one_line(character or "") or None,
        "delivery": _one_line(delivery or "") or None,
        "voice_kind": voice_kind,
    }


_VOICE_KIND_TEXT: Final[dict[str, str]] = {
    "design": (
        "The voice is made from your description: write a voice_instruction that describes "
        "the voice itself and how the line is delivered."
    ),
    "direction": (
        "A saved voice reads the line: write a voice_instruction that describes only how the "
        "line is delivered (tone, emotion, pace)."
    ),
    "none": 'No voice instruction is used: answer with "" for voice_instruction.',
}


def _render_inputs(inputs: dict[str, Any]) -> str:
    character = inputs.get("character")
    delivery = inputs.get("delivery")
    lines = [
        f"Spoken line: {inputs['dialogue']}",
        (
            f"Character: {character}"
            if character
            else "Character: not described. Describe a plain, neutral speaker."
        ),
        (
            f"Delivery note: {delivery}"
            if delivery
            else "Delivery note: none. Choose what fits the line and the character."
        ),
        f"Voice: {_VOICE_KIND_TEXT[inputs['voice_kind']]}",
    ]
    return "\n".join(lines)


def _system_prompt(profile: TalkPromptProfile) -> str:
    return "\n".join(
        [
            "You write two prompts for a short clip of a character speaking one line. The "
            "first steers a speech model that reads the line aloud. The second steers a video "
            "model that makes the character's face and body match the recorded speech (lip-sync). "
            "An author tries ideas by hand in a lab and edits what you write.",
            "",
            profile.voice_rules,
            "",
            profile.video_rules,
            "",
            "Example (from an unrelated video; do not reuse its content):",
            "Request:",
            _render_inputs(dict(profile.example_inputs)),
            "Answer:",
            profile.example_answer,
            "",
            "Answer with one JSON object only, in exactly this form: "
            '{"voice_instruction": "...", "video_prompt": "..."}',
        ]
    )


def build_request(
    inputs: dict[str, Any], *, model: str, profile: TalkPromptProfile
) -> dict[str, Any]:
    """The exact request body sent to the model. Nothing about the call is hidden from the
    job record: this body is stored on the job (`job.input.request`).
    """
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt(profile)},
            {
                "role": "user",
                "content": _render_inputs(inputs) + "\n\nWrite the two prompts now.",
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


def parse_answer(content: str) -> dict[str, Any]:
    """The model's answer as a dict. Raises ValueError, with a message fit for the user, when
    it is empty, not JSON, or has no `video_prompt` text.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    video = answer.get(VIDEO_PROMPT) if isinstance(answer, dict) else None
    if not isinstance(video, str) or not video.strip():
        raise ValueError('The model\'s answer had no "video_prompt" text.')
    return answer


@dataclass(frozen=True)
class CheckedPrompts:
    """The two texts after the checks: each on one line, with the warnings they earned.
    `voice_instruction` is empty when the take's voice uses none.
    """

    voice_instruction: str
    video_prompt: str
    word_count: int
    warnings: tuple[str, ...]


def check_prompts(
    answer: dict[str, Any], inputs: dict[str, Any], profile: TalkPromptProfile
) -> CheckedPrompts:
    """The answer's texts made into single lines and checked. Raises ValueError, with a message
    for the user, when they cannot be used: not text, empty, or longer than the limit.

    Warnings never block: a video prompt of an unusual length, one with quoted words, or one
    that breaks a wording rule is still returned.
    """
    video_value = answer.get(VIDEO_PROMPT)
    if not isinstance(video_value, str):
        raise ValueError('The model\'s "video_prompt" was not text.')
    video = _one_line(video_value)
    if not video or len(video) > FIELD_MAX_CHARS:
        raise ValueError(
            f"The model's video prompt was empty or longer than {FIELD_MAX_CHARS:,} characters."
        )

    voice_value = answer.get(VOICE_INSTRUCTION, "")
    if voice_value is None:
        voice_value = ""
    if not isinstance(voice_value, str):
        raise ValueError('The model\'s "voice_instruction" was not text.')
    voice = _one_line(voice_value)

    warnings: list[str] = []
    if inputs["voice_kind"] == "none":
        if voice:
            warnings.append(
                "The model wrote a voice instruction, but this take does not use one. It was "
                "left out."
            )
        voice = ""
    else:
        if not voice:
            raise ValueError("The model's voice instruction was empty.")
        if len(voice) > speech_synthesizer.INSTRUCTION_MAX_CHARS:
            raise ValueError(
                "The model's voice instruction was longer than "
                f"{speech_synthesizer.INSTRUCTION_MAX_CHARS} characters."
            )

    words = len(video.split())
    if words < profile.video_min_words or words > profile.video_max_words:
        warnings.append(
            f"The video prompt has {words} words. "
            f"{profile.video_min_words} to {profile.video_max_words} works best."
        )
    if _DOUBLE_QUOTES.search(video):
        warnings.append(
            "Double quotes found in the video prompt. The speech is given to the video model as "
            "audio, so the words are not needed in the prompt."
        )
    warnings += [rule.message for rule in profile.rules if rule.pattern.search(video)]
    return CheckedPrompts(
        voice_instruction=voice,
        video_prompt=video,
        word_count=words,
        warnings=tuple(warnings),
    )
