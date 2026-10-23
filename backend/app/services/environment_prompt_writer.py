"""Writing the prompt for a library environment's canonical reference picture with a language
model (PHASE-012). Pure functions, no I/O.

The input is the environment card (`environment_library.environment_card`). The answer is one
prompt for the image model, in the shape `image_prompt_writer.py`'s answer already has
(`{"image_prompt": ...}`), on the environment sheet profile
(`image_prompt_profiles.ACTIVE_ENVIRONMENT_SHEET_PROFILE`: an empty, wide establishing view of
the place). The generic reader and checks of `image_prompt_writer.py` are reused; only the
request is built here. The job that drives this is `jobs/write_environment_prompt.py`.

The call is made by `providers/llm.py` through `jobs/llm_call.py`.
"""

from __future__ import annotations

from typing import Any, Final

from app.services.image_prompt_profiles import ImagePromptProfile
from app.services.image_prompt_writer import MAX_TOKENS, REASONING_EFFORT

_TASK: Final = "Write the image prompt for this environment's reference picture."


def spatial_text(definition: dict[str, Any] | None) -> str | None:
    """The part of a definition's spatial plan the master picture is drawn from (PHASE-050), as
    plain lines: where the camera stands and what fills the back of the frame and its two
    edges. What is behind the camera is left out, because the picture never shows it. None when
    the definition has no plan (a definition written before PHASE-050, or none at all).
    """
    plan = definition.get("spatial_plan") if isinstance(definition, dict) else None
    if not isinstance(plan, dict):
        return None
    sides = plan.get("sides")
    master_view = plan.get("master_view")
    if not isinstance(sides, dict) or not isinstance(master_view, str):
        return None
    lines = [f"Camera: {master_view}"]
    for key, label in (
        ("ahead", "Ahead, filling the back of the frame"),
        ("left", "At the left edge of the frame"),
        ("right", "At the right edge of the frame"),
    ):
        text = sides.get(key)
        if isinstance(text, str) and text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines) if len(lines) > 1 else None


def prompt_inputs(card: str, spatial: str | None = None) -> dict[str, Any]:
    """What the model is told: the environment card and, when the definition has a spatial plan,
    the lines `spatial_text` gives, as one plain dict (the user message is rendered from it
    alone).
    """
    inputs: dict[str, Any] = {"card": card}
    if spatial:
        inputs["spatial"] = spatial
    return inputs


def _render_inputs(inputs: dict[str, Any]) -> str:
    text = f"Environment card:\n{inputs['card']}"
    spatial = inputs.get("spatial")
    if isinstance(spatial, str) and spatial:
        text += f"\n\nSpatial plan of the picture:\n{spatial}"
    return text


def _system_prompt(profile: ImagePromptProfile) -> str:
    return "\n".join(
        [
            "You write one prompt for a text-to-image model. The picture it makes is the "
            "reference picture of one environment of a library of environments: every "
            "picture and clip set in the place later is made to match it, so it must show "
            "clearly how the place looks.",
            "",
            f"- The image model ({profile.image_model}) sees only the prompt you write.",
            "- You are given a card describing the environment: its name, the time it is set "
            "in, what it looks like, its atmosphere and any other notes. Use what concerns "
            "the looks and the mood.",
            "- There is no author's style for this picture, so rule 7 below always applies "
            "as 'none given' (a natural, realistic look), unless the description itself "
            "describes a stylised look (a cartoon, a painting).",
            "- A spatial plan may follow the card. It says where the camera stands and what "
            "is ahead of it and at the left and right edges of the frame: the picture must "
            "show exactly that.",
            "- Never write the environment's name in the prompt.",
            "",
            profile.prompt_rules,
            "",
            "Example (an unrelated place; do not reuse its content):",
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
    """The exact request body sent to the model. Nothing about the call is hidden from the job
    record: this body is stored on the job (`job.input.request`).
    """
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt(profile)},
            {
                "role": "user",
                "content": "\n".join(
                    [_TASK, "", _render_inputs(inputs), "", "Write the image prompt now."]
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
