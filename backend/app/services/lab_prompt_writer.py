"""Writing a multi-shot video prompt for the Video lab with a language model (Phase 19). Pure
functions, no I/O.

The author gives a short idea, how many shots the clip should have (2 to 4, or 1 to 4 for
MiniMax H3), how long it is, and optionally a note about the first frame it starts from. For
LTX-2.5 the model answers with one paragraph (`{"prompt": ...}`) that names every cut in prose,
which is the only way LTX-2.5 cuts between shots. For MiniMax H3 it answers with the three fields
of H3's own structured prompt (`integrated_multimodal_description`, `overall_soundscape` and
`non_diegetic_music`) and `parse_answer` joins them into the one prompt text. Which of the two is
decided by the profile (`lab_prompt_profiles.profile_for`).

The steps are the same as for the other language model jobs:

1. `build_request`: the instructions and the data, as an OpenAI-style chat request. What
   depends on the video model comes from the profile (`lab_prompt_profiles.py`).
2. `parse_answer`: the model's JSON, read defensively.
3. `check_prompt`: the prompt is tidied and checked. Wording the profile dislikes, and a number
   of cuts that does not match the shots asked for, give a warning. Warnings never stop the
   prompt from being shown: the author edits it before running anything.

The call is made by `providers/llm.py` and the job that drives it is
`jobs/write_lab_video_prompt.py`. The system message is the same for every request (only the
profile changes it), so `llm_call.instructions_sha256` names an instruction set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from app.providers import llm
from app.services.lab_prompt_profiles import DOUBLE_QUOTES, LabPromptProfile

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

# The three fields of a MiniMax H3 prompt, in the order they are written. The first two are
# required in the model's answer; a missing score is `N/A`, what H3's format says for "no music".
H3_DESCRIPTION: Final = "integrated_multimodal_description"
H3_SOUNDSCAPE: Final = "overall_soundscape"
H3_MUSIC: Final = "non_diegetic_music"
H3_NO_MUSIC: Final = "N/A"
# "[Shot 2]": how a MiniMax H3 prompt names its shots.
_SHOT_BLOCK = re.compile(r"\[Shot\s+\d+\]", re.IGNORECASE)

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


def _one_line(value: str) -> str:
    return " ".join(value.split())


def count_named_cuts(text: str) -> int:
    """How many cuts the prompt names: the sentences that hold a named transition."""
    return sum(1 for sentence in _SENTENCE_END.split(text) if _TRANSITION.search(sentence))


def count_shot_blocks(text: str) -> int:
    """How many `[Shot N]` blocks a MiniMax H3 prompt has."""
    return len(_SHOT_BLOCK.findall(text))


# --- The request --------------------------------------------------------------------------


def prompt_inputs(
    idea: str,
    shots: int,
    duration_s: float,
    first_frame_note: str | None,
    target_model: str | None = None,
) -> dict[str, Any]:
    """What the model is told, as one plain dict (the user message is rendered from it).
    `target_model` is the model the prompt is for (`lab_prompt_profiles.profile_for` picks the
    profile from it); an older job, which has none, was written for LTX-2.5.
    """
    note = _one_line(first_frame_note or "")
    return {
        "idea": _one_line(idea),
        "shots": shots,
        "duration_s": round(duration_s, 1),
        "first_frame": note or None,
        "target_model": target_model,
    }


def _render_inputs(inputs: dict[str, Any], profile: LabPromptProfile) -> str:
    shots = inputs["shots"]
    duration = float(inputs["duration_s"])
    note = inputs.get("first_frame")
    if profile.answer_format == "h3_fields":
        last_shot = "[Shot 1]" if shots == 1 else f"[Shot 1] to [Shot {shots}]"
        lines = [
            f"Idea: {inputs['idea']}",
            f"Shots: exactly {shots} ({last_shot}).",
            f"Clip length: about {duration:g} seconds, which is {duration / shots:.1f} seconds "
            "a shot. Every cut time falls inside it.",
            (
                f"First frame (the clip starts on this image, <Picture 1>): {note}"
                if note
                else "First frame: none. The clip starts from your words alone."
            ),
        ]
        return "\n".join(lines)
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


def _intro(profile: LabPromptProfile) -> str:
    if profile.answer_format == "h3_fields":
        return (
            f"You write prompts for {profile.video_model}, a video model that also makes the "
            "sound. An author tries ideas by hand in a lab and asks for a clip with a number of "
            "shots, which can be just one. You write the prompt for one clip."
        )
    return (
        f"You write prompts for {profile.video_model}, a video model that also makes the "
        "sound. An author tries ideas by hand in a lab and wants a clip that is cut "
        "between several shots. You write the prompt for one clip."
    )


def _system_prompt(profile: LabPromptProfile) -> str:
    return "\n".join(
        [
            _intro(profile),
            "",
            profile.prompt_rules,
            "",
            "Example (from an unrelated video; do not reuse its content):",
            "Request:",
            _render_inputs(dict(profile.example_inputs), profile),
            "Answer:",
            profile.example_answer,
            "",
            profile.answer_instruction,
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
                "content": _render_inputs(inputs, profile) + "\n\nWrite the prompt now.",
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


def _h3_field(answer: dict[str, Any], key: str) -> str:
    """One field of a MiniMax H3 answer on one line, or "" when it is missing or not text. A
    field that begins with its own name ("overall_soundscape: ...") has the name removed, because
    `assemble_h3_prompt` writes it.
    """
    value = answer.get(key)
    if not isinstance(value, str):
        return ""
    return re.sub(rf"^{key}\s*:\s*", "", _one_line(value), flags=re.IGNORECASE)


def assemble_h3_prompt(answer: dict[str, Any]) -> str | None:
    """The three fields of a MiniMax H3 answer joined the way the model was trained on them: each
    field named, with a blank line between. None when the description or the soundscape is
    missing. A missing score is `N/A`.
    """
    description = _h3_field(answer, H3_DESCRIPTION)
    soundscape = _h3_field(answer, H3_SOUNDSCAPE)
    if not description or not soundscape:
        return None
    music = _h3_field(answer, H3_MUSIC) or H3_NO_MUSIC
    return (
        f"{H3_DESCRIPTION}: {description}\n\n{H3_SOUNDSCAPE}: {soundscape}\n\n{H3_MUSIC}: {music}"
    )


def parse_answer(content: str, profile: LabPromptProfile | None = None) -> dict[str, Any]:
    """The model's answer as a dict, with the finished prompt text under `prompt`. Raises
    ValueError, with a message fit for the user, when it is empty, not JSON, or has no prompt.

    For an LTX profile the model's own `prompt` is used. For a MiniMax H3 profile the three
    fields are joined (`assemble_h3_prompt`) and the result is added as `prompt`; the fields stay
    in the dict, so the job keeps exactly what the model said.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    if profile is not None and profile.answer_format == "h3_fields":
        text = assemble_h3_prompt(answer) if isinstance(answer, dict) else None
        if text is None:
            raise ValueError(
                f'The model\'s answer had no "{H3_DESCRIPTION}" and "{H3_SOUNDSCAPE}" text.'
            )
        return {**answer, PROMPT: text}
    prompt = answer.get(PROMPT) if isinstance(answer, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('The model\'s answer had no "prompt" text.')
    return answer


@dataclass(frozen=True)
class CheckedPrompt:
    """The prompt after the checks, with the warnings it earned: on one line for LTX, or as the
    three blank-line-separated fields for MiniMax H3. `cuts` is the cuts between shots.
    """

    text: str
    word_count: int
    cuts: int
    warnings: tuple[str, ...]


def check_prompt(
    answer: dict[str, Any], inputs: dict[str, Any], profile: LabPromptProfile
) -> CheckedPrompt | None:
    """The answer's prompt made into one paragraph (LTX) or kept as its three fields (MiniMax
    H3) and checked, or None when it cannot be used: it is not text, is empty, or is longer
    than the limit.

    Warnings never block it: a prompt that names fewer cuts (or `[Shot N]` blocks) than the shots
    asked for, speaks words the idea did not give, or breaks a wording rule is still returned.
    """
    value = answer.get(PROMPT)
    if not isinstance(value, str):
        return None
    is_h3 = profile.answer_format == "h3_fields"
    # The H3 fields are separated by blank lines, which are part of the format.
    text = value.strip() if is_h3 else _one_line(value)
    if not text or len(text) > FIELD_MAX_CHARS:
        return None

    words = len(text.split())
    warnings: list[str] = []
    if words < profile.min_words or words > profile.max_words:
        warnings.append(
            f"The prompt has {words} words. {profile.min_words} to {profile.max_words} works best."
        )

    shots = int(inputs["shots"])
    if is_h3:
        blocks = count_shot_blocks(text)
        cuts = max(blocks - 1, 0)
        if blocks != shots:
            warnings.append(
                f"The prompt has {blocks} [Shot N] {'block' if blocks == 1 else 'blocks'}, but "
                f"{shots} {'shot was' if shots == 1 else 'shots were'} asked for."
            )
    else:
        wanted = shots - 1
        cuts = count_named_cuts(text)
        if cuts < wanted:
            warnings.append(
                f"The prompt names {cuts} {'cut' if cuts == 1 else 'cuts'}, but {shots} "
                f"shots ({wanted} {'cut' if wanted == 1 else 'cuts'}) were asked for. The model "
                "only cuts where a sentence names the cut."
            )
        elif cuts > wanted:
            warnings.append(
                f"The prompt names {cuts} cuts, more than the {wanted} asked for. Two to four "
                "shots work best."
            )

    # Spoken words are expected only when the idea has some: quoted words are lip-synced by LTX,
    # and everything inside <d> tags is spoken by MiniMax H3.
    if profile.dialogue_pattern.search(text) and not DOUBLE_QUOTES.search(str(inputs["idea"])):
        warnings.append(profile.dialogue_warning)

    warnings += [rule.message for rule in profile.rules if rule.pattern.search(text)]
    return CheckedPrompt(text=text, word_count=words, cuts=cuts, warnings=tuple(warnings))
