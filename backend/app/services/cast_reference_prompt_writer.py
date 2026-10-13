"""Writing the prompt for a cast member's reference picture with a language model. Pure
functions, no I/O.

One request is made for one member (a character or a place). The model gets its description and
the style of the video, and answers with one detailed prompt for the image model
(`{"image_prompt": ...}`), the same answer a scene's image prompt is. What depends on the image
model, and on what the picture is (a character on a white backdrop, or a place as it is), comes
from the profile (`image_prompt_profiles.py`). The answer is read and checked by
`image_prompt_writer.parse_answer` and `check_prompt`, which the scene's prompt uses too.

The call is made by `providers/llm.py` and the job that drives it is
`jobs/write_character_reference_prompt.py`.
"""

from __future__ import annotations

from typing import Any

from app.db.models import Project
from app.services import cast as cast_service
from app.services.image_prompt_profiles import (
    ACTIVE_CHARACTER_SHEET_PROFILE,
    ACTIVE_LOCATION_SHEET_PROFILE,
    ImagePromptProfile,
)
from app.services.image_prompt_writer import MAX_TOKENS, REASONING_EFFORT


def profile_for(kind: str) -> ImagePromptProfile:
    return (
        ACTIVE_CHARACTER_SHEET_PROFILE
        if kind == cast_service.CHARACTER
        else ACTIVE_LOCATION_SHEET_PROFILE
    )


def _text(value: str | None) -> str | None:
    cleaned = " ".join((value or "").split())
    return cleaned or None


def prompt_inputs(kind: str, member: cast_service.Member, project: Project) -> dict[str, Any]:
    """Everything the request is built from, as plain JSON values. The member's name is left
    out on purpose: the prompt must never carry it.
    """
    inputs: dict[str, Any] = {
        "kind": kind,
        "style_prefix": _text(project.style_prefix),
        "description_instructions": _text(project.description_instructions),
        "appearance": _text(member.appearance_description),
    }
    if kind == cast_service.CHARACTER:
        inputs["personality"] = _text(getattr(member, "personality_description", None))
    return inputs


def _render_inputs(inputs: dict[str, Any]) -> str:
    """The inputs as the lines of the user message. The worked example is rendered the same way,
    so the model sees one layout.
    """
    is_character = inputs["kind"] == cast_service.CHARACTER
    style = inputs["style_prefix"]
    lines = [
        f"Style of the whole video: {style}." if style else "Style of the whole video: none given."
    ]
    instructions = inputs["description_instructions"]
    if instructions:
        lines += [
            "Author's instructions for the video (use what concerns the looks):",
            instructions,
        ]
    lines.append(f"{'Character' if is_character else 'Place'} description: {inputs['appearance']}")
    if is_character:
        personality = inputs.get("personality") or "none"
        lines.append(f"Personality (guides the bearing and the expression): {personality}")
    return "\n".join(lines)


def _system_prompt(inputs_kind: str, profile: ImagePromptProfile) -> str:
    what = "one character" if inputs_kind == cast_service.CHARACTER else "one place"
    return "\n".join(
        [
            "You write one prompt for a text-to-image model. The picture it makes is the "
            f"reference picture of {what} of a narrated video: every scene that shows it is "
            "made from this picture later, so it must show clearly how it looks.",
            "",
            f"- The image model ({profile.image_model}) sees only the prompt you write.",
            "- You are given the style of the whole video, the author's instructions if there "
            "are any, and the description of what is to be drawn.",
            "",
            profile.prompt_rules,
            "",
            "Example (from an unrelated video; do not reuse its content):",
            "Input:",
            _render_inputs(profile.example_inputs),
            "Answer:",
            profile.example_answer,
            "",
            "Answer with one JSON object only, in exactly this form:",
            '{"image_prompt": "..."}',
        ]
    )


def build_request(
    inputs: dict[str, Any], *, model: str, profile: ImagePromptProfile
) -> dict[str, Any]:
    """The exact request body sent to the model. Nothing about the call is hidden from the
    job record: this body is stored on the job (`job.input.request`).
    """
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt(inputs["kind"], profile)},
            {
                "role": "user",
                "content": "\n".join(
                    [
                        "Write the image prompt for this reference picture.",
                        "",
                        _render_inputs(inputs),
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
