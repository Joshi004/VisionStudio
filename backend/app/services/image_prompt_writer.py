"""Writing the prompt for a scene's first frame with a language model (Phase 16). Pure
functions, no I/O.

One request is made for one scene. The model gets what is known about the scene (the
*inputs*) and answers with one detailed prompt for the image model (`{"image_prompt": ...}`).
Phase 17 sends that prompt to Seedream.

The inputs are one plain dict (`prompt_inputs`), and the user message is rendered from it
alone. That makes `inputs_sha256` a name for exactly what the model was told about the scene:
a prompt is *out of date* when the scene's inputs now hash differently from the inputs it was
written from (`services/image_prompts.py`). The project's frame shape, style and instructions,
the draft's `world` and `continuity`, and the scene's narration, first frame description and
video prompt are all part of it.

The steps are the same as for the other language model jobs:

1. `build_request`: the instructions and the data, as an OpenAI-style chat request. What
   depends on the image model comes from the profile (`image_prompt_profiles.py`).
2. `parse_answer`: the model's JSON, read defensively.
3. `check_prompt`: the prompt is tidied and checked. Wording the profile dislikes gives a
   warning, which never stops it from being saved.

The call is made by `providers/llm.py` and the job that drives it is
`jobs/write_image_prompt.py`. The system message is the same for every scene (only the profile
changes it), so `instructions_sha256` (in `description_writer.py`) names an instruction set.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final

from app.db.models import Project, Scene
from app.providers import llm
from app.services.image_prompt_profiles import ImagePromptProfile

# Hidden reasoning is billed as output (ANALYSIS.md Section 6.2, rule 4). One paragraph of
# about 200 words is a few hundred tokens, so this leaves room to think.
MAX_TOKENS: Final = 8000
REASONING_EFFORT: Final = "high"
# Longer than any text the page accepts (`scene_inputs.DESCRIPTION_MAX_CHARS`).
FIELD_MAX_CHARS: Final = 4000

IMAGE_PROMPT: Final = "image_prompt"

# What each value of a draft's `continuity` means. `continues_shot` is the value the old
# keyframe profile wrote (Phase 12 to 14), so earlier drafts still read.
_CONTINUITY_MEANINGS: Final = {
    "new_place": "a new place or time",
    "same_place_new_angle": "the previous scene's place and subjects, seen from a new angle "
    "or distance",
    "continues_action": "the same place, subject and framing as the previous scene, with this "
    "first frame showing where the previous scene's motion ended",
    "continues_shot": "the same shot as the previous scene",
}


def _text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _one_line(value: str) -> str:
    return " ".join(value.split())


# --- Where `world` and `continuity` come from -------------------------------------------


@dataclass(frozen=True)
class SourceDraft:
    """What a scene's draft job said about the video as a whole.

    `job_id` is the draft job the scene's texts came from (or, for texts written by hand, the
    project's newest successful draft). `world_job_id` is the job that paid for `world`: a draft
    that reused an earlier answer holds none, so it points at the job that did.
    """

    job_id: int | None = None
    world_job_id: int | None = None
    world: dict[str, list[dict[str, str]]] | None = None
    continuity: str | None = None


NO_SOURCE: Final = SourceDraft()


def _world_entries(value: object) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name, description = item.get("name"), item.get("description")
        if (
            isinstance(name, str)
            and isinstance(description, str)
            and name.strip()
            and description.strip()
        ):
            entries.append({"name": _one_line(name), "description": _one_line(description)})
    return entries


def world_from_answer(answer: object) -> dict[str, list[dict[str, str]]] | None:
    """The recurring subjects and places of a draft's answer, cleaned. None when there are
    none. Drafts from the old keyframe profile (Phase 12 to 14) call the subjects
    `characters`.
    """
    world = answer.get("world") if isinstance(answer, dict) else None
    if not isinstance(world, dict):
        return None
    raw_subjects = world.get("subjects") if "subjects" in world else world.get("characters")
    subjects = _world_entries(raw_subjects)
    places = _world_entries(world.get("places"))
    if not subjects and not places:
        return None
    return {"subjects": subjects, "places": places}


def continuity_from_drafts(drafts: object, scene_id: int) -> str | None:
    """The `continuity` a draft job recorded for a scene (`job.output.drafts`), if it is a
    value this module can explain.
    """
    for draft in drafts if isinstance(drafts, list) else []:
        if isinstance(draft, dict) and draft.get("scene_id") == scene_id:
            value = draft.get("continuity")
            return value if value in _CONTINUITY_MEANINGS else None
    return None


# --- The inputs ---------------------------------------------------------------------------


def prompt_inputs(scene: Scene, project: Project, source: SourceDraft) -> dict[str, Any]:
    """Everything the request is built from, as plain JSON values. Pure: it reads columns only.

    The scene's texts are the current ones, whoever wrote them. A text that is blank is None.
    """
    return {
        "orientation": project.orientation,
        "width": project.gen_width,
        "height": project.gen_height,
        "style_prefix": _text(project.style_prefix),
        "description_instructions": _text(project.description_instructions),
        "world": source.world,
        "narration": _one_line(scene.text),
        "continuity": source.continuity,
        "first_frame_description": _text(scene.first_frame_description),
        "video_prompt": _text(scene.scene_description),
    }


def inputs_sha256(inputs: dict[str, Any]) -> str:
    """The SHA-256 of the inputs. Two scenes, or one scene at two times, with the same hash
    were described to the model in exactly the same way.
    """
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- The request --------------------------------------------------------------------------


def _render_inputs(inputs: dict[str, Any]) -> str:
    """The inputs as the lines of the user message. The worked example is rendered the same
    way, so the model sees one layout.
    """
    lines = [
        f"The frame: a {inputs['orientation']} frame, {inputs['width']} x {inputs['height']} "
        "pixels (width x height).",
    ]
    style = inputs["style_prefix"]
    lines.append(
        f"Style of the whole video: {_one_line(style)}."
        if style
        else "Style of the whole video: none given."
    )
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
    if continuity in _CONTINUITY_MEANINGS:
        lines.append(
            f"How this scene follows the previous one: {_CONTINUITY_MEANINGS[continuity]}."
        )
    else:
        lines.append("How this scene follows the previous one: not given.")
    first_frame = inputs["first_frame_description"]
    video_prompt = inputs["video_prompt"]
    lines += [
        f"First frame description: {_one_line(first_frame) if first_frame else 'none'}",
        f"Video prompt: {_one_line(video_prompt) if video_prompt else 'none'}",
    ]
    return "\n".join(lines)


def _system_prompt(profile: ImagePromptProfile) -> str:
    return "\n".join(
        [
            "You write one prompt for a text-to-image model. The picture it makes is the "
            "first frame of one scene of a narrated video.",
            "",
            "How the picture is used",
            "- A voiceover reads a script, and the video shows pictures that illustrate the "
            "narration. Each scene becomes one short clip.",
            "- A video model starts the clip from your picture and animates it, so the "
            "picture is the instant just before the scene's motion begins.",
            f"- The image model ({profile.image_model}) sees only the prompt you write. It "
            "does not see the script, the other scenes or any earlier picture, so everything "
            "it needs must be in the prompt.",
            "",
            "What you are given",
            "- The frame: its shape and size.",
            "- The style of the whole video, and the author's instructions if there are any.",
            "- The world: the recurring subjects and places of the video, each with a fixed "
            "description.",
            "- The narration of this scene, and how the scene follows the previous one.",
            "- The first frame description: a short plan for the picture, written earlier.",
            "- The video prompt: the motion the video model will make from the picture.",
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
            '{"image_prompt": "..."}',
        ]
    )


def _user_message(inputs: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Write the image prompt for this scene.",
            "",
            _render_inputs(inputs),
            "",
            "Write the image prompt now.",
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
