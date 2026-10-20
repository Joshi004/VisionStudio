"""Reading and checking an image prompt that a language model wrote (Phase 16). Pure functions,
no I/O.

The model answers with one detailed prompt for the image model (`{"image_prompt": ...}`). The
request that asks for it is built by the writer of each use (today
`character_look_prompt_writer.py`); what they share is here:

1. `MAX_TOKENS` and `REASONING_EFFORT`: the limits every image prompt request is sent with.
2. `parse_answer`: the model's JSON, read defensively.
3. `check_prompt`: the prompt is tidied and checked. Wording the profile
   (`image_prompt_profiles.py`) dislikes gives a warning, which never stops it from being saved.

The call is made by `providers/llm.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from app.providers import llm
from app.services.image_prompt_profiles import ImagePromptProfile

# Hidden reasoning is billed as output (ANALYSIS.md Section 6.2, rule 4). One paragraph of
# about 200 words is a few hundred tokens, so this leaves room to think.
MAX_TOKENS: Final = 8000
REASONING_EFFORT: Final = "high"
# Longer than any prompt the writers ask for.
FIELD_MAX_CHARS: Final = 4000

IMAGE_PROMPT: Final = "image_prompt"


def _one_line(value: str) -> str:
    return " ".join(value.split())


# --- Reading the answer ---------------------------------------------------------------


def parse_answer(content: str) -> dict[str, Any]:
    """The model's answer as a dict. Raises ValueError, with a message fit for the user, when
    it is empty, not JSON, or has no `image_prompt` text.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    prompt = answer.get(IMAGE_PROMPT) if isinstance(answer, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('The model\'s answer had no "image_prompt" text.')
    return answer


@dataclass(frozen=True)
class CheckedPrompt:
    """The prompt after the checks: on one line, with the warnings it earned."""

    text: str
    word_count: int
    warnings: tuple[str, ...]


def check_prompt(answer: dict[str, Any], profile: ImagePromptProfile) -> CheckedPrompt | None:
    """The answer's prompt made into one paragraph and checked, or None when it cannot be
    used: it is not text, is empty, or is longer than the limit.

    The profile's wording rules and word range give warnings, which never block saving.
    """
    value = answer.get(IMAGE_PROMPT)
    if not isinstance(value, str):
        return None
    text = _one_line(value)
    if not text or len(text) > FIELD_MAX_CHARS:
        return None
    words = len(text.split())
    warnings: list[str] = []
    if words < profile.min_words or words > profile.max_words:
        warnings.append(
            f"The image prompt has {words} words. {profile.min_words} to {profile.max_words} "
            "works best."
        )
    warnings += [rule.message for rule in profile.rules if rule.pattern.search(text)]
    return CheckedPrompt(text=text, word_count=words, warnings=tuple(warnings))
