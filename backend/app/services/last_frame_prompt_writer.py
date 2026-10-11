"""Writing the edit prompt for a scene's last frame with a language model (Phase 23). Pure
functions, no I/O.

A last frame is made by *editing* the scene's first frame: the image model (Qwen-Image-2.1's
edit endpoint) is given the first frame's picture and one instruction, and returns the same
shot a moment later. This module writes that instruction. It is the counterpart of
`image_prompt_writer.py`, which writes the prompt that makes the first frame from nothing, and
it works the same way: one request for one scene, and an answer of one text
(`{"edit_prompt": ...}`).

The inputs are one plain dict (`prompt_inputs`), and the user message is rendered from it alone,
so `inputs_sha256` (the one in `image_prompt_writer.py`) names exactly what the model was told.
An edit prompt is *out of date* when the scene's inputs now hash differently from the inputs it
was written from (`services/last_frame_prompts.py`). The inputs are kept apart from the first
frame's prompt on purpose: rewriting this prompt never makes the first frame's prompt out of
date. They hold the picture the edit starts from (the first frame description and the image
prompt it was made from), what the last frame must show, and the video prompt.

The steps are the same as for the first frame's prompt:

1. `build_request`: the instructions and the data, as an OpenAI-style chat request. What
   depends on the image model comes from the profile (`image_prompt_profiles.py`).
2. `parse_answer`: the model's JSON, read defensively.
3. `check_prompt`: the prompt is tidied and checked. Wording the profile dislikes gives a
   warning, which never stops it from being saved.

The call is made by `providers/llm.py` and the job that drives it is
`jobs/write_last_frame_prompt.py`.
"""

from __future__ import annotations

from typing import Any, Final

from app.db.models import Project, Scene
from app.providers import llm
from app.services.image_prompt_profiles import ImagePromptProfile
from app.services.image_prompt_writer import (
    CONTINUITY_MEANINGS,
    FIELD_MAX_CHARS,
    MAX_TOKENS,
    REASONING_EFFORT,
    CheckedPrompt,
    SourceDraft,
)

EDIT_PROMPT: Final = "edit_prompt"


def _text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _one_line(value: str) -> str:
    return " ".join(value.split())


# --- The inputs ---------------------------------------------------------------------------


def prompt_inputs(scene: Scene, project: Project, source: SourceDraft) -> dict[str, Any]:
    """Everything the request is built from, as plain JSON values. Pure: it reads columns only.

    The scene's texts are the current ones, whoever wrote them. A text that is blank is None.
    The frame's size is not part of it: the edit keeps the first frame's shape.
    """
    return {
        "style_prefix": _text(project.style_prefix),
        "description_instructions": _text(project.description_instructions),
        "world": source.world,
        "narration": _one_line(scene.text),
        "continuity": source.continuity,
        "first_frame_description": _text(scene.first_frame_description),
        "image_prompt": _text(scene.image_prompt),
        "last_frame_description": _text(scene.last_frame_description),
        "video_prompt": _text(scene.scene_description),
    }


# --- The request --------------------------------------------------------------------------


def _render_inputs(inputs: dict[str, Any]) -> str:
    """The inputs as the lines of the user message. The worked example is rendered the same
    way, so the model sees one layout.
    """
    style = inputs["style_prefix"]
    lines = [
        (
            f"Style of the whole video (the first frame's picture already has it, so do not "
            f"restate it): {_one_line(style)}."
            if style
            else "Style of the whole video: none given."
        )
    ]
    instructions = inputs["description_instructions"]
    if instructions:
        lines += [
            "Author's instructions for the video (use what concerns the picture):",
            instructions,
        ]
    lines += ["", "World (the recurring subjects and places, each with a fixed description):"]
    world = inputs["world"]
    if world:
        lines += [f"- Subject, {item['name']}: {item['description']}" for item in world["subjects"]]
        lines += [f"- Place, {item['name']}: {item['description']}" for item in world["places"]]
    else:
        lines.append("none given")
    lines += ["", f"Narration of this scene: {inputs['narration']}"]
    continuity = inputs["continuity"]
    if continuity in CONTINUITY_MEANINGS:
        lines.append(f"How this scene follows the previous one: {CONTINUITY_MEANINGS[continuity]}.")
    else:
        lines.append("How this scene follows the previous one: not given.")
    first_frame = inputs["first_frame_description"]
    image_prompt = inputs["image_prompt"]
    last_frame = inputs["last_frame_description"]
    video_prompt = inputs["video_prompt"]
    lines += [
        "",
        "The picture the edit starts from (the first frame):",
        f"- First frame description: {_one_line(first_frame) if first_frame else 'none'}",
        f"- Image prompt it was made from: {_one_line(image_prompt) if image_prompt else 'none'}",
        "",
        f"Last frame description (what the edited picture must show): "
        f"{_one_line(last_frame) if last_frame else 'none'}",
        f"Video prompt (the motion between the two pictures): "
        f"{_one_line(video_prompt) if video_prompt else 'none'}",
    ]
    return "\n".join(lines)


def _system_prompt(profile: ImagePromptProfile) -> str:
    return "\n".join(
        [
            "You write one instruction for an image-editing model. The picture it returns is "
            "the last frame of one scene of a narrated video.",
            "",
            "How the picture is used",
            "- A voiceover reads a script, and the video shows pictures that illustrate the "
            "narration. Each scene becomes one short clip.",
            "- A video model makes the clip move from the scene's first frame to its last "
            "frame. The last frame is made by editing the first frame's picture: the image "
            f"model ({profile.image_model}) is given that picture and your instruction, and "
            "nothing else. It does not see the script, the other scenes or any description.",
            "- So the last frame must be the same shot as the first frame, one moment after "
            "the scene's motion ends. If the two pictures differ in place, light or framing, "
            "the video model dissolves from one to the other instead of moving.",
            "",
            "What you are given",
            "- The style of the whole video, and the author's instructions if there are any.",
            "- The world: the recurring subjects and places of the video, each with a fixed "
            "description.",
            "- The narration of this scene, and how the scene follows the previous one.",
            "- The picture the edit starts from: the first frame description, and the image "
            "prompt the first frame was made from.",
            "- The last frame description: what the edited picture must show.",
            "- The video prompt: the motion between the two pictures.",
            "",
            profile.prompt_rules,
            "",
            "Example of one scene (from an unrelated video; do not reuse its content):",
            "Input:",
            _render_inputs(profile.example_inputs),
            "Answer:",
            profile.example_answer,
            "",
            "Answer with one JSON object only, in exactly this form:",
            '{"edit_prompt": "..."}',
        ]
    )


def _user_message(inputs: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Write the edit prompt for this scene.",
            "",
            _render_inputs(inputs),
            "",
            "Write the edit prompt now.",
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
            {"role": "system", "content": _system_prompt(profile)},
            {"role": "user", "content": _user_message(inputs)},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- Reading the answer ---------------------------------------------------------------


def parse_answer(content: str) -> dict[str, Any]:
    """The model's answer as a dict. Raises ValueError, with a message fit for the user, when
    it is empty, not JSON, or has no `edit_prompt` text.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    prompt = answer.get(EDIT_PROMPT) if isinstance(answer, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('The model\'s answer had no "edit_prompt" text.')
    return answer


def check_prompt(answer: dict[str, Any], profile: ImagePromptProfile) -> CheckedPrompt | None:
    """The answer's prompt made into one paragraph and checked, or None when it cannot be
    used: it is not text, is empty, or is longer than the limit.

    The profile's wording rules and word range give warnings, which never block saving.
    """
    value = answer.get(EDIT_PROMPT)
    if not isinstance(value, str):
        return None
    text = _one_line(value)
    if not text or len(text) > FIELD_MAX_CHARS:
        return None
    words = len(text.split())
    warnings: list[str] = []
    if words < profile.min_words or words > profile.max_words:
        warnings.append(
            f"The edit prompt has {words} words. {profile.min_words} to {profile.max_words} "
            "works best."
        )
    warnings += [rule.message for rule in profile.rules if rule.pattern.search(text)]
    return CheckedPrompt(text=text, word_count=words, warnings=tuple(warnings))
