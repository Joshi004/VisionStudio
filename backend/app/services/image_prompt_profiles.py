"""What depends on the image model when an AI writes the prompt for a scene's first frame
(Phase 16).

An *image prompt profile* is the counterpart of the video prompt profile
(`description_profiles.py`). It holds the three things that change when the image model
changes:

- the rules its prompt must follow (`prompt_rules`), with one worked example;
- the checks that tell whether a written prompt breaks them (`rules`, `min_words`,
  `max_words`);
- its name and version, which are stored on every job that wrote a prompt.

Everything else (the task, the data sent, the JSON answer, the job, the API and the page)
knows nothing about Seedream. To use another image model, add a profile below and point
`ACTIVE_IMAGE_PROFILE` at it.

The text here is the lever for better prompts, so a change to it is a change to every future
prompt. Raise `version` whenever any text in a profile, or in the generic instructions in
`image_prompt_writer.py`, changes: the job stores the profile's id and version next to the
exact request, so earlier prompts can be compared with later ones.
Pure data, no I/O.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final

from app.services.description_profiles import TextRule

# Wording about writing in the picture. Naming it can make an image model draw it, so the
# rules forbid even "no text" (the checks only warn).
_WRITING_TERMS: Final = re.compile(
    r"\b(text|captions?|subtitles?|lettering|letters|typography|logos?|watermarks?|"
    r"signatures?|split[- ]panels?)\b",
    re.IGNORECASE,
)
# Words that ask for a quality, not for a picture.
_QUALITY_TAGS: Final = re.compile(
    r"\b(8k|4k|masterpiece|highly detailed|ultra[- ]detailed|best quality)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class ImagePromptProfile:
    id: str
    # Raised by hand whenever any text changes.
    version: int
    # Named to the writer, so it knows what it is writing for.
    image_model: str
    # How to write `image_prompt` for this model.
    prompt_rules: str
    # One worked scene: the inputs it is given (the same shape as
    # `image_prompt_writer.prompt_inputs`) and the answer, as JSON. From an unrelated video.
    example_inputs: dict[str, Any]
    example_answer: str
    # About how long a prompt should be. Outside these gives a warning, never an error.
    min_words: int
    max_words: int
    rules: tuple[TextRule, ...]


_SEEDREAM_EXAMPLE_PROMPT: Final = (
    "A small cream paper boat with a faded blue stripe along its edge sits at the rim of a "
    "rain puddle, its bow pointing out across the still water, about to be nudged in. The "
    "setting is a narrow lane paved with dark, rounded cobblestones that glisten when wet, "
    "and a single yellow leaf floats on the puddle beyond the boat. The boat sits just above "
    "the centre of the tall portrait frame, the puddle spreads across the middle, and plain "
    "wet cobblestones fill the bottom edge of the picture. A close-up at water level, the "
    "camera low and level with the boat. A 35 mm look with shallow depth of field: the boat "
    "is sharp and the far cobblestones soften into blur. Flat, even overcast light with soft "
    "reflections on the water and no hard shadows. A muted palette of slate grey, cool blue "
    "and cream, with the leaf as the one warm accent. Quiet natural photography."
)

SEEDREAM_50_LITE: Final = ImagePromptProfile(
    id="seedream-5.0-lite",
    version=1,
    image_model="Seedream 5.0 lite",
    prompt_rules="\n".join(
        [
            'Rules for "image_prompt", the prompt for the image model:',
            "1. One paragraph of plain prose in the present tense, 120 to 220 words. No lists, "
            "no headings and no labels.",
            "2. Say, in this order: the subject and what it is doing at this instant; the "
            "setting; the composition and where things sit in the frame; the shot size and "
            "angle (wide, medium or close-up; eye level, low or high); the lens look (for "
            'example "35 mm look, shallow depth of field"); the light; the colour palette; '
            "the style.",
            "3. Keep everything the first frame description says, and add detail to it. Never "
            'change it. With no first frame description ("none"), picture the instant just '
            "before the motion in the video prompt begins. With no video prompt either, the "
            "first frame description is the whole picture.",
            "4. It is the instant just before the motion begins: the subject in place and "
            "ready to move, never in the middle of the action and never after it.",
            "5. When a subject or a place from the world appears in this scene, put its world "
            "description into the prompt word for word, and never give it another look. Describe "
            "anything that is not in the world in full.",
            "6. Compose for the frame shape you are given. Keep the main subject, and every "
            "important detail, out of the bottom tenth of the frame, because that strip is cut "
            "off later. Say what fills the bottom edge (ground, water, floor or a plain "
            "background).",
            "7. Nothing is written in the picture: no text, captions, letters, signs with "
            "words, logos, watermarks, borders or split panels. Do not name any of these in the "
            "prompt, not even to say there are none. Describe only what is there.",
            "8. Tell the story through places, objects, nature, animals, light and weather. A "
            "person appears only if the descriptions put one there, and then incidentally "
            "(hands at work, a distant figure, someone seen from behind). Never make a face "
            "the subject, and never name a person.",
            "9. Put the author's style into words as the last sentence. With none given, keep "
            "the look the first frame description already has.",
            "10. Concrete nouns and plain adjectives. No quality tags (such as 8k, masterpiece "
            "or highly detailed) and no camera brand names.",
        ]
    ),
    example_inputs={
        "orientation": "portrait",
        "width": 1088,
        "height": 1920,
        "style_prefix": "quiet natural photography",
        "description_instructions": None,
        "world": {
            "subjects": [
                {
                    "name": "the paper boat",
                    "description": "A small cream paper boat with a faded blue stripe along "
                    "its edge.",
                }
            ],
            "places": [
                {
                    "name": "the cobbled lane",
                    "description": "A narrow lane paved with dark, rounded cobblestones that "
                    "glisten when wet.",
                }
            ],
        },
        "narration": "A small thing set adrift on a rainy afternoon.",
        "continuity": "new_place",
        "first_frame_description": (
            "Close-up at water level, a 35 mm look with shallow depth of field. A cream paper "
            "boat with a faded blue stripe along its edge sits at the rim of a rain puddle "
            "between dark, wet cobblestones, its bow pointing across the water. A single "
            "yellow leaf floats in the puddle beyond it. Flat overcast light, a muted palette "
            "of grey, slate blue and cream. Portrait frame, the boat near the centre."
        ),
        "video_prompt": (
            "A gust of wind pushes the paper boat off the rim and into the puddle. It drifts "
            "slowly across the water, nudges the floating leaf aside and comes to rest against "
            "the far edge, rocking gently. Slow pan right, following the boat. Soft rain "
            "patter, no music, no voices."
        ),
    },
    example_answer=json.dumps({"image_prompt": _SEEDREAM_EXAMPLE_PROMPT}, ensure_ascii=False),
    min_words=120,
    max_words=220,
    rules=(
        TextRule(
            _WRITING_TERMS,
            "The prompt names text, a caption, a logo, a watermark or a split panel. Naming "
            "them can make the image model draw them: describe only what is there.",
        ),
        TextRule(
            _QUALITY_TAGS,
            "A quality tag such as 8k or masterpiece found. It adds nothing to the picture.",
        ),
    ),
)

# The image adapter the job asks for.
ACTIVE_IMAGE_PROFILE: Final = SEEDREAM_50_LITE
