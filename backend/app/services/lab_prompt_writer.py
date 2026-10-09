"""Writing a multi-shot video prompt for the Video lab with a language model (Phase 19). Pure
functions, no I/O.

The author gives a short idea, how many shots the clip should have (2 to 4), how long it
is, and optionally a note about the first frame it starts from. The model answers with one
paragraph (`{"prompt": ...}`) that names every cut in prose, which is the only way LTX-2.5
cuts between shots.

The steps are the same as for the other language model jobs:

1. `build_request`: the instructions and the data, as an OpenAI-style chat request. What
   depends on the video model comes from the profile (`lab_prompt_profiles.py`).
2. `parse_answer`: the model's JSON, read defensively.
3. `check_prompt`: the prompt is tidied and checked. Wording the profile dislikes, and a number
   of cuts that does not match the shots asked for, give a warning. Warnings never stop the
   prompt from being shown: the author edits it before running anything.

The call is made by `providers/llm.py` and the job that drives it is
`jobs/write_lab_video_prompt.py`. The system message is the same for every request (only the
profile changes it), so `description_writer.instructions_sha256` names an instruction set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from app.providers import llm
from app.services.lab_prompt_profiles import LabPromptProfile

# Hidden reasoning is billed as output (ANALYSIS.md Section 6.2, rule 4). One paragraph of
# about 200 words is a few hundred tokens, so this leaves room to think.
MAX_TOKENS: Final = 8000
REASONING_EFFORT: Final = "high"
FIELD_MAX_CHARS: Final = 4000

IDEA_MAX_CHARS: Final = 2000
FIRST_FRAME_NOTE_MAX_CHARS: Final = 1000
MIN_SHOTS: Final = 2
MAX_SHOTS: Final = 4
# What the server's guide says one shot needs to register.
SECONDS_PER_SHOT: Final = 3.0

PROMPT: Final = "prompt"

# A cut named in words. A sentence holding one of these counts as one cut, so "A hard cut
# transitions to a close-up" is one cut and not two.
_TRANSITION = re.compile(
    r"\b(?:hard|match|jump|smash) cuts?\b"
    r"|\bcuts? (?:away|to|into|back)\b"
    r"|\b(?:dissolves?|fades?|wipes?|transitions?) (?:in)?to\b"
    r"|\b(?:view|shot|image|camera|scene) (?:cuts|transitions|dissolves|jumps)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_DOUBLE_QUOTES = re.compile(r"[\"\u201c\u201d\u201e]")


def _one_line(value: str) -> str:
    return " ".join(value.split())


def count_named_cuts(text: str) -> int:
    """How many cuts the prompt names: the sentences that hold a named transition."""
    return sum(1 for sentence in _SENTENCE_END.split(text) if _TRANSITION.search(sentence))


# --- The request --------------------------------------------------------------------------


def prompt_inputs(
    idea: str, shots: int, duration_s: float, first_frame_note: str | None
) -> dict[str, Any]:
    """What the model is told, as one plain dict (the user message is rendered from it)."""
    note = _one_line(first_frame_note or "")
    return {
        "idea": _one_line(idea),
        "shots": shots,
        "duration_s": round(duration_s, 1),
        "first_frame": note or None,
    }


def _render_inputs(inputs: dict[str, Any]) -> str:
    shots = inputs["shots"]
    duration = float(inputs["duration_s"])
    note = inputs.get("first_frame")
    lines = [
        f"Idea: {inputs['idea']}",
        f"Shots: exactly {shots}, so {shots - 1} {'cut' if shots == 2 else 'cuts'}.",
        f"Clip length: about {duration:g} seconds, which is {duration / shots:.1f} seconds a shot.",
        (
            f"First frame (the clip starts on this image): {note}"
            if note
            else "First frame: none. The clip starts from your words alone."
        ),
    ]
    return "\n".join(lines)


def _system_prompt(profile: LabPromptProfile) -> str:
    return "\n".join(
        [
            f"You write prompts for {profile.video_model}, a video model that also makes the "
            "sound. An author tries ideas by hand in a lab and wants a clip that is cut "
            "between several shots. You write the prompt for one clip.",
            "",
            profile.prompt_rules,
            "",
            "Example (from an unrelated video; do not reuse its content):",
            "Request:",
            _render_inputs(dict(profile.example_inputs)),
            "Answer:",
            profile.example_answer,
            "",
            'Answer with one JSON object only, in exactly this form: {"prompt": "..."}',
        ]
    )


def build_request(
    inputs: dict[str, Any], *, model: str, profile: LabPromptProfile
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
                "content": _render_inputs(inputs) + "\n\nWrite the prompt now.",
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
    it is empty, not JSON, or has no `prompt` text.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    prompt = answer.get(PROMPT) if isinstance(answer, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('The model\'s answer had no "prompt" text.')
    return answer


@dataclass(frozen=True)
class CheckedPrompt:
    """The prompt after the checks: on one line, with the warnings it earned."""

    text: str
    word_count: int
    cuts: int
    warnings: tuple[str, ...]


def check_prompt(
    answer: dict[str, Any], inputs: dict[str, Any], profile: LabPromptProfile
) -> CheckedPrompt | None:
    """The answer's prompt made into one paragraph and checked, or None when it cannot be
    used: it is not text, is empty, or is longer than the limit.

    Warnings never block it: a prompt that names fewer cuts than the shots asked for, quotes
    words the idea did not give, or breaks a wording rule is still returned.
    """
    value = answer.get(PROMPT)
    if not isinstance(value, str):
        return None
    text = _one_line(value)
    if not text or len(text) > FIELD_MAX_CHARS:
        return None

    words = len(text.split())
    warnings: list[str] = []
    if words < profile.min_words or words > profile.max_words:
        warnings.append(
            f"The prompt has {words} words. {profile.min_words} to {profile.max_words} works best."
        )

    wanted = int(inputs["shots"]) - 1
    cuts = count_named_cuts(text)
    if cuts < wanted:
        warnings.append(
            f"The prompt names {cuts} {'cut' if cuts == 1 else 'cuts'}, but {inputs['shots']} "
            f"shots ({wanted} {'cut' if wanted == 1 else 'cuts'}) were asked for. The model "
            "only cuts where a sentence names the cut."
        )
    elif cuts > wanted:
        warnings.append(
            f"The prompt names {cuts} cuts, more than the {wanted} asked for. Two to four "
            "shots work best."
        )

    # Quoted words are spoken, with lip-sync. They are expected only when the idea has some.
    if _DOUBLE_QUOTES.search(text) and not _DOUBLE_QUOTES.search(str(inputs["idea"])):
        warnings.append(
            "Double quotes found, but the idea has no dialogue. The model lip-syncs and speaks "
            "every quoted word."
        )

    warnings += [rule.message for rule in profile.rules if rule.pattern.search(text)]
    return CheckedPrompt(text=text, word_count=words, cuts=cuts, warnings=tuple(warnings))
