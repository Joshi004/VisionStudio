"""Writing scene descriptions with a language model (Phase 12). Pure functions, no I/O.

One request carries the whole script and every scene, and the model answers with the
characters and places of the video (`world`) and, for each scene, three texts:

- `video_prompt`: the motion prompt for the video model (it becomes `scene_description`);
- `first_frame` and `last_frame`: what the two anchor frames should show, to guide making
  them by hand now and with an image model later.

The steps are the same as for the scene proposal (`scene_planner.py`):

1. `build_request`: the instructions and the data, as an OpenAI-style chat request. What
   depends on the video model comes from the prompt profile (`description_profiles.py`).
2. `parse_answer`: the model's JSON, read defensively.
3. `check_drafts`: each scene's texts are checked, and wording the profile forbids gives a
   warning. Warnings never stop a draft from being saved.

The call is made by `providers/llm.py` and the job that drives it is
`jobs/draft_descriptions.py`. The instructions are the only lever on quality, so the system
message is the same for every project (only the profile changes it): the project's own
details are in the user message. That makes `instructions_sha256` a stable name for an
instruction set.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.db.models import Project, Scene
from app.providers import llm
from app.services.description_profiles import PromptProfile

# One request holds every scene, so a long project is refused rather than cut off.
MAX_SCENES: Final = 40
# The answer carries hidden reasoning, which is billed as output (ANALYSIS.md Section 6.2,
# rule 4). 15 scenes take a few thousand tokens to write, so this leaves room to think.
MAX_TOKENS: Final = 32000
REASONING_EFFORT: Final = "high"
# Longer than any description the page accepts (`scene_inputs.DESCRIPTION_MAX_CHARS`).
FIELD_MAX_CHARS: Final = 4000

CONTINUITY_VALUES: Final = ("new_place", "same_place_new_angle", "continues_shot")

# The three texts the model writes for a scene.
VIDEO_PROMPT: Final = "video_prompt"
FIRST_FRAME: Final = "first_frame"
LAST_FRAME: Final = "last_frame"
FIELDS: Final = (VIDEO_PROMPT, FIRST_FRAME, LAST_FRAME)


def _system_prompt(profile: PromptProfile) -> str:
    return "\n".join(
        [
            "You write the pictures and the motion for a narrated video, scene by scene.",
            "",
            "How the video is made",
            "- A voiceover reads a script. The video shows pictures that illustrate the "
            "narration. Nobody on screen speaks, the narrator is never seen, and there is no "
            "on-screen text.",
            "- The script is cut into scenes. Each scene becomes one short clip, made by "
            f"{profile.video_model} from three things that you write: a first frame (a still "
            "image), a last frame (a still image) and a motion prompt. The video model fills "
            "in the movement between the two frames.",
            "- Scenes are joined with hard cuts. Each scene must work on its own, and all "
            "scenes together must look like one film.",
            "",
            "What you write for every scene",
            '- "first_frame": the still image the clip starts on.',
            '- "last_frame": the still image the clip ends on: the same shot after one clear '
            "change that fits the scene's length.",
            '- "video_prompt": the motion prompt.',
            '- "continuity": "new_place" (a new place or time), "same_place_new_angle" (the '
            "previous scene's place and people, seen from a new angle or distance) or "
            '"continues_shot" (the previous scene\'s last frame carries straight on).',
            "",
            "The pictures follow the narration",
            "- Show what the narrator says in this scene: literally when it is concrete, and "
            "through a concrete visual when it is abstract. Read the scenes before and after, "
            "so the story reads in order.",
            "- Never show the narrator, and never put the narration's words on screen.",
            "",
            "Consistency across the whole video",
            '- First fill in "world": every recurring character and every recurring place, '
            'defined once. A character gets a short visual name (for example "the keeper") '
            "and a fixed description: age, build, hair, clothing, distinguishing features. A "
            "place gets a fixed description: what it is, its materials, its colours, its light.",
            "- In every scene, call a character or a place by exactly that name, and repeat "
            "its identifying details in the frames, word for word where you can. Never invent a "
            "new look for something that has already appeared.",
            "- One lighting logic per place: the same time of day and the same light sources "
            "whenever the video returns to it.",
            "- One visual style for the whole video: the style the author gives.",
            "",
            'Rules for "first_frame" and "last_frame" (a frame is one still photograph)',
            "- Say what the frame shows at this instant: the subject and what it is doing, the "
            "setting, the shot size and angle (wide, medium or close-up; eye level, low or "
            'high), the lens look (for example "35 mm look, shallow depth of field"), the '
            "light, the colour palette, and where things sit in the frame. 40 to 90 words.",
            '- No motion words ("starts to", "begins to") and no sound. Plain photographic '
            "language.",
            "- Fit the frame shape the author gives (portrait or landscape).",
            "- No text, captions, logos or watermarks in the picture.",
            "- Apply the author's style to the frames in words, because an image model does "
            "not get it any other way.",
            "- The last frame is complete on its own (write out the setting and the people "
            "again), but it keeps everything from the first frame the same except the "
            "change: the same place, light, people and shot size. The one exception is a "
            "camera move that changes the framing: then the last frame is framed where the "
            "move ends.",
            "- The change must fit the scene's length. A 2 to 3 second scene allows one small "
            "action. A 5 to 6 second scene allows one action and a reaction. Never a journey, "
            "never a different place.",
            "",
            profile.video_prompt_rules,
            "",
            "Example of one scene (from an unrelated video; do not reuse its content):",
            profile.example,
            "",
            "Fixed fields",
            "- In the scene list, a field marked FIXED was written by the author. Do not "
            "change it and do not write it again: answer null for that field. Write the other "
            "fields so that they fit with it.",
            "",
            "Answer with one JSON object only, in exactly this form:",
            '{"world": {"characters": [{"name": "...", "description": "..."}], '
            '"places": [{"name": "...", "description": "..."}]}, '
            '"scenes": [{"scene": 1, "continuity": "new_place", "first_frame": "...", '
            '"last_frame": "...", "video_prompt": "..."}]}',
            '- "scenes" has exactly one entry for each scene in the scene list, in order, '
            "numbered as in the list.",
            '- "world" lists only the characters and places that appear in more than one '
            "scene or that need a fixed look. It can be empty.",
        ]
    )


# --- The scenes the request is about ----------------------------------------------------


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


@dataclass(frozen=True)
class SceneToDraft:
    """A scene as the request was built from it, and which of its texts the author wrote.

    A text the author wrote is carried here (`fixed_*`), sent to the model as context, and
    never overwritten. Text the AI wrote earlier, or none, may be written again.
    """

    scene_id: int
    index: int  # 0-based; the model numbers the scenes from 1
    start_s: float
    end_s: float
    text: str
    fixed_video_prompt: str | None
    fixed_first_frame: str | None
    fixed_last_frame: str | None

    @property
    def number(self) -> int:
        return self.index + 1

    @property
    def length_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def all_fixed(self) -> bool:
        return (
            self.fixed_video_prompt is not None
            and self.fixed_first_frame is not None
            and self.fixed_last_frame is not None
        )

    def fixed_text(self, field: str) -> str | None:
        return {
            VIDEO_PROMPT: self.fixed_video_prompt,
            FIRST_FRAME: self.fixed_first_frame,
            LAST_FRAME: self.fixed_last_frame,
        }[field]


def to_draft(scene: Scene) -> SceneToDraft:
    """The scene as a drafting request sees it. Pure: it reads the scene's columns only.

    A text is the author's unless it was written by the AI (`source = 'ai'`). A text of an
    unknown source counts as the author's: nothing is overwritten by guessing.
    """
    video = None
    if not _blank(scene.scene_description) and scene.scene_description_source != "ai":
        video = (scene.scene_description or "").strip()
    frames_are_ai = scene.frame_descriptions_source == "ai"
    first = None
    if not _blank(scene.first_frame_description) and not frames_are_ai:
        first = (scene.first_frame_description or "").strip()
    last = None
    if not _blank(scene.last_frame_description) and not frames_are_ai:
        last = (scene.last_frame_description or "").strip()
    return SceneToDraft(
        scene_id=scene.id,
        index=scene.index,
        start_s=scene.start_s,
        end_s=scene.end_s,
        text=scene.text,
        fixed_video_prompt=video,
        fixed_first_frame=first,
        fixed_last_frame=last,
    )


def draftable_count(scenes: Sequence[Scene]) -> int:
    """How many scenes have at least one text the AI may write."""
    return sum(1 for scene in scenes if not to_draft(scene).all_fixed)


def script_paragraphs(script_text: str) -> list[str]:
    """The script's paragraphs (blank lines separate them), each on one line."""
    paragraphs = (" ".join(part.split()) for part in re.split(r"\n\s*\n", script_text.strip()))
    return [paragraph for paragraph in paragraphs if paragraph]


# --- The request --------------------------------------------------------------------------


def _quoted(value: str | None, none: str) -> str:
    text = " ".join((value or "").split())
    return text if text else none


def _user_message(
    project: Project, scenes: Sequence[SceneToDraft], paragraphs: Sequence[str]
) -> str:
    style = _quoted(project.style_prefix, "")
    lines = [
        f"Project: a {project.orientation} video. The frames are {project.gen_width} x "
        f"{project.gen_height} pixels (width x height) at {project.fps} frames per second. "
        f"Scenes last {project.min_scene_seconds:g} to {project.max_scene_seconds:g} seconds.",
        "",
    ]
    if style:
        lines.append(
            f'Style of the whole video: {style}. The app writes "Style: {style}." in front '
            "of every video prompt, so do not repeat the style there. Use it in the frame "
            "descriptions."
        )
    else:
        lines.append(
            "Style of the whole video: none given. Choose one natural look that suits the "
            "script and keep it for every scene."
        )
    lines.append(
        "Added by the app to the end of every video prompt (do not repeat it, and do not "
        f"contradict it): {_quoted(project.prompt_suffix, 'nothing')}"
    )
    lines.append(
        f"Sent to the video model as things to avoid: {_quoted(project.negative_prompt, 'nothing')}"
    )
    instructions = (project.description_instructions or "").strip()
    if instructions:
        lines += [
            "",
            "Author's instructions (they come before the rules above wherever they differ):",
            instructions,
        ]
    lines += ["", "Script (paragraphs are separated by blank lines):", "\n\n".join(paragraphs)]
    lines += ["", f"Scenes ({len(scenes)}):"]
    for scene in scenes:
        lines.append(
            f"[Scene {scene.number}] {scene.start_s:.2f} to {scene.end_s:.2f} s "
            f"({scene.length_s:.1f} seconds)"
        )
        lines.append(f"Narration: {scene.text}")
        for field in FIELDS:
            fixed = scene.fixed_text(field)
            if fixed is not None:
                lines.append(f"FIXED {field}: {fixed}")
        lines.append("")
    lines.append(f"Write all {len(scenes)} scenes now.")
    return "\n".join(lines)


def build_request(
    project: Project,
    scenes: Sequence[SceneToDraft],
    paragraphs: Sequence[str],
    *,
    model: str,
    profile: PromptProfile,
) -> dict[str, Any]:
    """The exact request body sent to the model. Nothing about the call is hidden from the
    job record: this body is stored on the job (`job.input.request`).
    """
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt(profile)},
            {"role": "user", "content": _user_message(project, scenes, paragraphs)},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": False,
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


def instructions_sha256(body: dict[str, Any]) -> str:
    """The SHA-256 of the system message: a name for the instruction set that was used."""
    system = body["messages"][0]["content"]
    return "sha256:" + hashlib.sha256(system.encode("utf-8")).hexdigest()


# --- Reading the answer ---------------------------------------------------------------


def parse_answer(content: str) -> dict[str, Any]:
    """The model's answer as a dict with a non-empty `scenes` list. Raises ValueError, with a
    message fit for the user, when there is none.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    scenes = answer.get("scenes") if isinstance(answer, dict) else None
    if not isinstance(scenes, list):
        raise ValueError('The model\'s answer had no "scenes" list.')
    if not scenes:
        raise ValueError("The model's answer had no scenes.")
    return answer


@dataclass(frozen=True)
class SceneDraft:
    """What the model wrote for one scene, after the checks. A text is None where the model
    gave none, gave an unusable one, or the field is fixed.
    """

    scene_id: int
    index: int
    continuity: str | None
    video_prompt: str | None
    first_frame: str | None
    last_frame: str | None
    warnings: tuple[str, ...]

    def text(self, field: str) -> str | None:
        return {
            VIDEO_PROMPT: self.video_prompt,
            FIRST_FRAME: self.first_frame,
            LAST_FRAME: self.last_frame,
        }[field]

    @property
    def has_text(self) -> bool:
        return any(self.text(field) is not None for field in FIELDS)


@dataclass(frozen=True)
class CheckedDrafts:
    # At most one per scene, in scene order.
    drafts: list[SceneDraft]
    # Entries that named a scene that does not exist, or one that was already answered.
    dropped_entries: int

    @property
    def usable(self) -> bool:
        return any(draft.has_text for draft in self.drafts)


def _as_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _clean_text(value: object, field: str, warnings: list[str]) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > FIELD_MAX_CHARS:
        warnings.append(
            f"The {field.replace('_', ' ')} was longer than {FIELD_MAX_CHARS:,} characters "
            "and was not used."
        )
        return None
    return cleaned


def check_drafts(
    answer: dict[str, Any], scenes: Sequence[SceneToDraft], profile: PromptProfile
) -> CheckedDrafts:
    """Turns the model's entries into one draft per scene, checking each.

    - An entry must name a scene of the request, by its number from 1, and only the first
      entry for a scene counts.
    - A text that is empty, not text, or over the limit is dropped. A text for a field that
      is fixed is dropped too: the author's own text is never replaced.
    - The video prompt is checked against the profile's wording rules and word limit. That
      gives warnings, which never stop a draft from being saved.
    """
    by_number = {scene.number: scene for scene in scenes}
    entries = answer.get("scenes")
    drafts: dict[int, SceneDraft] = {}
    dropped = 0

    for entry in entries if isinstance(entries, list) else []:
        number = _as_number(entry.get("scene")) if isinstance(entry, dict) else None
        scene = by_number.get(number) if number is not None else None
        if scene is None or scene.number in drafts:
            dropped += 1
            continue

        warnings: list[str] = []
        texts: dict[str, str | None] = {}
        for field in FIELDS:
            if scene.fixed_text(field) is not None:
                texts[field] = None
            else:
                texts[field] = _clean_text(entry.get(field), field, warnings)

        video_prompt = texts[VIDEO_PROMPT]
        if video_prompt is not None:
            words = len(video_prompt.split())
            if words > profile.max_video_words:
                warnings.append(
                    f"The video prompt has {words} words. About {profile.max_video_words} or "
                    "fewer works best."
                )
            warnings += [
                rule.message for rule in profile.rules if rule.pattern.search(video_prompt)
            ]

        continuity = entry.get("continuity")
        drafts[scene.number] = SceneDraft(
            scene_id=scene.scene_id,
            index=scene.index,
            continuity=continuity if continuity in CONTINUITY_VALUES else None,
            video_prompt=video_prompt,
            first_frame=texts[FIRST_FRAME],
            last_frame=texts[LAST_FRAME],
            warnings=tuple(warnings),
        )

    ordered = [drafts[scene.number] for scene in scenes if scene.number in drafts]
    return CheckedDrafts(drafts=ordered, dropped_entries=dropped)
