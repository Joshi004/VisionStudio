"""Writing the edit prompt of one view of an environment with a language model (PHASE-052,
`Path_ahead.md` Section 46). Pure functions, no I/O.

A view picture is an edit of the environment's master picture. The model is told the view (its
name, side, framing and what it shows), the text of that side of the place from the spatial plan
and what the camera does relative to the master picture (worked out here by code, so the turn is
always exact), and writes one prompt on the view profile
(`image_prompt_profiles.ACTIVE_ENVIRONMENT_VIEW_PROFILE`). The generic reader and checks of
`image_prompt_writer.py` are reused.

The job that drives this is `jobs/write_environment_view_prompt.py`; the call is made through
`jobs/llm_call.py`.
"""

from __future__ import annotations

from typing import Any, Final

from app.services.image_prompt_profiles import ImagePromptProfile
from app.services.image_prompt_writer import MAX_TOKENS, REASONING_EFFORT

_TASK: Final = "Write the edit prompt for this view of the place."

_CAMERA: Final = {
    "ahead": (
        "Keep the camera in the same spot and pointing the same way as Picture 1; only the "
        "framing changes, as the framing says."
    ),
    "left": (
        "Turn the camera about 90 degrees to the left of the direction Picture 1 looks, and "
        "keep it at the same height and in the same spot."
    ),
    "right": (
        "Turn the camera about 90 degrees to the right of the direction Picture 1 looks, and "
        "keep it at the same height and in the same spot."
    ),
    "behind": (
        "Turn the camera all the way round, 180 degrees from the direction Picture 1 looks, "
        "and keep it at the same height and in the same spot, so that it now faces what "
        "stood behind the camera of Picture 1."
    ),
}


def camera_text(side: str) -> str:
    """What the camera does relative to the master picture for a view on this side."""
    return _CAMERA[side]


def pictures_text(side: str, *, has_left: bool, has_right: bool) -> str:
    """The pictures the image model is shown, in order. A `behind` view is also shown the
    finished left and right views, which hold the edges of the space it looks at.
    """
    lines = ["Picture 1: the master picture of the place."]
    if side == "behind":
        number = 2
        if has_left:
            lines.append(f"Picture {number}: the view to the left of the master picture.")
            number += 1
        if has_right:
            lines.append(f"Picture {number}: the view to the right of the master picture.")
    return "\n".join(lines)


def prompt_inputs(
    *,
    name: str,
    side: str,
    framing: str,
    description: str,
    side_text: str | None,
    zone_text: str | None,
    pictures: str,
) -> dict[str, Any]:
    """What the model is told, as one plain dict (the user message is rendered from it alone)."""
    view = (
        f"Name: {name}\n"
        f"Side: {side} (relative to Picture 1)\n"
        f"Framing: {framing}\n"
        f"What it shows: {description}"
    )
    if zone_text:
        view += f"\nThe part of the place it looks at: {zone_text}"
    inputs: dict[str, Any] = {"view": view, "camera": camera_text(side), "pictures": pictures}
    if side_text:
        inputs["side_text"] = side_text
    return inputs


def _render_inputs(inputs: dict[str, Any]) -> str:
    parts = [f"View:\n{inputs['view']}", f"Camera:\n{inputs['camera']}"]
    side_text = inputs.get("side_text")
    if isinstance(side_text, str) and side_text:
        parts.append(f"What the plan of the place says is on that side:\n{side_text}")
    parts.append(f"Pictures shown to the image model:\n{inputs['pictures']}")
    return "\n\n".join(parts)


def _system_prompt(profile: ImagePromptProfile) -> str:
    return "\n".join(
        [
            "You write one edit prompt for an image-editing model. The picture it makes is "
            "a view of one environment of a library of environments: the same place as its "
            "master picture, seen from another direction. Every shot set in that part of the "
            "place is later made to match it, so it must show clearly how that part looks.",
            "",
            f"- The image model ({profile.image_model}) sees only the prompt you write and "
            "the pictures listed, in that order.",
            "- You are given the view (its name, side, framing and what it shows), what the "
            "camera does relative to Picture 1, the text of that side of the place and the "
            "pictures the model is shown.",
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
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }
