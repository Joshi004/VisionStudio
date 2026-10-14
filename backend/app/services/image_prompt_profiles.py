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
knows nothing about which image model it is. The profile in use is Qwen-Image-2.1, which makes
the first frames on the GPU server. The Seedream profile stays below for reference. To use
another image model, add a profile and point `ACTIVE_IMAGE_PROFILE` at it.

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
    # The image model is shown reference pictures next to the prompt (a scene that shows a cast
    # member). The instructions then say so, and the inputs list the pictures in their order.
    uses_references: bool = False


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

_QWEN_EXAMPLE_PROMPT: Final = (
    "A quiet, natural photograph of a small cream paper boat with a faded blue stripe along "
    "its edge, resting at the rim of a rain puddle with its bow pointing out across the "
    "still water, about to be nudged in. The scene is a narrow lane paved with dark, rounded "
    "cobblestones that glisten when wet, and a single yellow leaf floats on the puddle "
    "beyond the boat. In the tall portrait frame the boat sits in the foreground, just below "
    "the centre, the puddle fills the middle of the picture, and the lane recedes behind it "
    "into soft grey blur toward the top, with wet cobblestones running down to the bottom "
    "edge. The camera is close and low, at water level, looking straight along the surface "
    "so the boat is at eye level. The lens has a 35 mm look with shallow depth of field: the "
    "boat and the nearest stones are sharp, and the far end of the lane dissolves into "
    "blur. The light is flat, even overcast daylight from above, with soft reflections on the "
    "water and no hard shadows. The palette is muted, in slate grey, cool blue and cream, "
    "with the yellow leaf as the one warm accent. The finish is quiet natural photography, "
    "with the ordinary look of an unposed street photograph."
)

# Written from Qwen's own published guidance (the Qwen-Image-2.1 README and the QwenCloud
# prompt guide, read on 2026-10-10), not from tests of this model's output here. Qwen reads
# full sentences and favours long, specific, spatial descriptions; it draws any wording in
# the picture very readily; and it has no negative prompt. Check these rules against real
# frames and raise `version` when they change.
QWEN_IMAGE_21: Final = ImagePromptProfile(
    id="qwen-image-2.1",
    version=1,
    image_model="Qwen-Image-2.1",
    prompt_rules="\n".join(
        [
            'Rules for "image_prompt", the prompt for the image model:',
            "1. One paragraph of plain English prose, in complete sentences and the present "
            "tense, 150 to 300 words. No lists, no headings, no labels and no piles of "
            "comma-separated keywords. The model reads sentences, and does best with a long, "
            "specific description.",
            "2. Open with the kind of picture it is, taken from the style (for example 'A "
            "quiet natural photograph of', 'A soft watercolour illustration of' or 'A "
            "cinematic still of'), and go straight on to the subject and what it is doing at "
            "this instant.",
            "3. Then say, in this order: the setting; where things sit in the frame (the "
            "foreground, the middle and the background; left, centre and right; the upper and "
            "lower parts of the picture); the shot size and the angle (wide, medium or "
            "close-up; eye level, low or high); the lens look (for example '35 mm look, "
            "shallow depth of field'); the light (where it comes from, its direction and "
            "quality); the colour palette; and last the style.",
            "4. Keep everything the first frame description says, and add detail to it. Never "
            'change it. With no first frame description ("none"), picture the instant just '
            "before the motion in the video prompt begins. With no video prompt either, the "
            "first frame description is the whole picture.",
            "5. It is the instant just before the motion begins: the subject in place and "
            "ready to move, never in the middle of the action and never after it.",
            "6. When a subject or a place from the world appears in this scene, put its world "
            "description into the prompt word for word, and never give it another look. Describe "
            "anything that is not in the world in full.",
            "7. Compose for the frame shape you are given, and use the whole frame: say what "
            "fills each part of it, down to the edges. The picture is trimmed slightly to fit "
            "the exact size, so keep the main subject and every important detail clear of the "
            "outer edges.",
            "8. Nothing is written in the picture: no text, captions, letters, numbers, signs "
            "with words, labels, posters, screens, pages, logos, watermarks, borders or split "
            "panels. The model draws any wording it is given, so do not name any of these, not "
            "even to say there are none, and describe any surface that could carry words (a "
            "wall, a sign, a screen, a book cover) as plain or blank. Describe only what is "
            "there.",
            "9. Describe only what is visible. The model has no negative prompt, and naming a "
            "thing, even to rule it out ('no people', 'without fog'), can make it appear. Say "
            "what fills the space instead.",
            "10. Tell the story through places, objects, nature, animals, light and weather. A "
            "person appears only if the descriptions put one there, and then incidentally "
            "(hands at work, a distant figure, someone seen from behind). Never make a face "
            "the subject, and never name a person.",
            "11. Put the author's style into words as the last sentence. With none given, keep "
            "the look the first frame description already has. For a realistic look, describe "
            "ordinary, natural light and plain framing: glossy studio light and 'cinematic' "
            "polish pull the picture away from a natural one.",
            "12. Concrete nouns and plain adjectives. No quality tags (such as 8k, masterpiece "
            "or highly detailed) and no camera brand names.",
        ]
    ),
    # The same worked scene as the Seedream profile: the inputs do not depend on the model.
    example_inputs=SEEDREAM_50_LITE.example_inputs,
    example_answer=json.dumps({"image_prompt": _QWEN_EXAMPLE_PROMPT}, ensure_ascii=False),
    min_words=150,
    max_words=300,
    rules=SEEDREAM_50_LITE.rules,
)

# --- The edit that turns a first frame into a last frame (Phase 23) ----------------------------

# Words that rule something out. The image model has no negative prompt, and naming a thing,
# even to rule it out, can make it appear.
_NEGATIVE_WORDS: Final = re.compile(
    r"\b(no|not|without|never|nothing|don't|doesn't|isn't|aren't)\b", re.IGNORECASE
)
# Wording that changes the shot instead of the subject: the last frame must be the same shot.
_FRAMING_CHANGE: Final = re.compile(
    r"\b(zoom(?:ed|s)?|close-up|wide shot|wider|tighter|new angle|different angle|"
    r"from above|from below|camera (?:moves?|pans?|tilts?))\b",
    re.IGNORECASE,
)

# The inputs the edit prompt is written from (`last_frame_prompt_writer.prompt_inputs`): the
# first frame is never described again to the image model, which sees the picture, so what the
# writer needs is what the picture shows and what the last frame should show.
_EDIT_EXAMPLE_INPUTS: Final[dict[str, Any]] = {
    "style_prefix": "quiet natural photography",
    "description_instructions": None,
    "world": {
        "subjects": [
            {
                "name": "the snail",
                "description": "A small brown garden snail with a pale spiral shell.",
            }
        ],
        "places": [
            {
                "name": "the mossy stone",
                "description": "A flat grey stone covered in soft green moss.",
            }
        ],
    },
    "narration": "It took its time, as it always did.",
    "continuity": "new_place",
    "first_frame_description": (
        "Close-up at moss level, a 35 mm look with shallow depth of field. A small brown "
        "garden snail with a pale spiral shell sits at the left edge of a flat grey stone "
        "covered in soft green moss, its antennae raised towards the right. Dull overcast "
        "light, a muted palette of grey, moss green and brown. Portrait frame, the snail in "
        "the lower left, the stone filling the lower half and soft blurred ferns behind it."
    ),
    "image_prompt": (
        "A quiet, natural photograph of a small brown garden snail with a pale spiral shell, "
        "resting at the left edge of a flat grey stone covered in soft green moss, its "
        "antennae raised towards the right. In the tall portrait frame the snail sits in the "
        "lower left, the stone fills the lower half and soft blurred ferns rise behind it. The "
        "camera is close and low, at moss level, with a 35 mm look and shallow depth of field. "
        "The light is dull, even overcast daylight. The palette is muted grey, moss green and "
        "brown."
    ),
    "last_frame_description": (
        "The same shot, the same light and framing. The snail has crossed the stone and now "
        "sits at its centre, its antennae raised and bent towards the ferns. The moss, the "
        "stone and the blurred ferns are unchanged."
    ),
    "video_prompt": (
        "The snail glides slowly across the mossy stone, its antennae swaying, and climbs a "
        "small ridge with a faint wet slide against the moss. It pauses for a beat, antennae "
        "turning towards the ferns, then moves on until it rests at the centre of the stone "
        "with its antennae raised. Static camera. A distant bird calls once. No music, no "
        "voices."
    ),
}

_QWEN_EDIT_EXAMPLE_PROMPT: Final = (
    "Move the snail from the left edge of the mossy stone to the centre of the stone, with "
    "its pale spiral shell and its body now pointing towards the right, and keep its antennae "
    "raised and bent slightly towards the blurred ferns behind the stone. Keep the camera "
    "position, the framing, the 35 mm look with shallow depth of field, the dull overcast "
    "light, the muted grey, moss green and brown palette, the green moss on the stone and "
    "the blurred ferns exactly as they are."
)

# Written from Qwen's published guidance for image editing and the server's guide for the edit
# endpoint (read on 2026-10-11), not from tests of this model's output here. The edit endpoint
# sees the first frame as its reference picture, keeps identity well, and has no mask: a local
# change is put in words. Check these rules against real frames and raise `version` when they
# change.
QWEN_IMAGE_21_EDIT: Final = ImagePromptProfile(
    id="qwen-image-2.1-edit",
    version=1,
    image_model="Qwen-Image-2.1 (edit)",
    prompt_rules="\n".join(
        [
            'Rules for "edit_prompt", the instruction for the image-editing model. It is given '
            "the first frame's picture and your instruction, and returns the last frame: the "
            "same shot a moment later.",
            "1. 40 to 120 words of plain instruction sentences in English. The model SEES the "
            "picture, so never describe the whole scene again: say what changes.",
            "2. Open with the changes, concretely: where the subject moves to, its pose or "
            "state, where it looks, what appears or disappears. Name each subject by its "
            "world name with its identifying details, so the model finds it in the picture. "
            "Take the end state from the last frame description, and keep to it.",
            "3. End with one sentence that keeps everything else, naming it: the camera "
            "position, the framing, the lens look, the light, the colour palette, the "
            "background and the subject's looks, exactly as they are.",
            "4. Only changes that fit one continuous shot from the first frame: no new place, "
            "no change of angle, zoom or framing, no jump in time. One still moment, not a "
            "process.",
            "5. Say what is there, not what is not: the model has no negative prompt, and "
            "naming a thing, even to rule it out ('no', 'without'), can make it appear. "
            "Nothing is written in the picture: no text, captions, letters, numbers, signs "
            "with words, logos or watermarks, and describe any surface that could carry words "
            "(a wall, a sign, a screen, a book cover) as plain or blank.",
            "6. A person appears only if the first frame has one. Never change a face, and "
            "never name a person.",
            "7. Concrete nouns and plain adjectives. No quality tags (such as 8k or "
            "masterpiece), and no words about the style: the picture already has its style.",
        ]
    ),
    example_inputs=_EDIT_EXAMPLE_INPUTS,
    example_answer=json.dumps({"edit_prompt": _QWEN_EDIT_EXAMPLE_PROMPT}, ensure_ascii=False),
    min_words=40,
    max_words=120,
    rules=(
        *SEEDREAM_50_LITE.rules,
        TextRule(
            _NEGATIVE_WORDS,
            "A negative found (no, not, without, nothing). The image model has no negative "
            "prompt, and naming a thing can make it appear: say what is there instead.",
        ),
        TextRule(
            _FRAMING_CHANGE,
            "Wording that changes the shot found (a zoom, a new angle, a camera move). The last "
            "frame is the same shot: change the subject, not the framing.",
        ),
    ),
)

# --- The project's cast: reference pictures, and scenes made from them ---------------------------
#
# These profiles are written from the same published Qwen guidance as the ones above (which they
# follow in everything but their subject), not from tests of this model's output here. Check them
# against real pictures and raise `version` when they change.

# What the cast writer's inputs hold (`cast_reference_prompt_writer.prompt_inputs`): a character's
# or a place's description, and the style of the video.
_CHARACTER_SHEET_EXAMPLE_INPUTS: Final[dict[str, Any]] = {
    "kind": "character",
    "style_prefix": "soft watercolour illustration",
    "description_instructions": None,
    "appearance": (
        "An elderly lighthouse keeper of about seventy, lean and weathered, with deeply tanned "
        "skin, a short white beard, a lined, kind face and thinning white hair. He wears a thick "
        "navy wool fisherman's jumper with a high collar and patched elbows, loose charcoal "
        "trousers tucked into worn brown leather boots, and a brass-buttoned oilskin coat folded "
        "over his left forearm. In his right hand he carries a small brass lantern."
    ),
    "personality": "Patient and watchful, with the calm of a man who has spent his life alone.",
}

_CHARACTER_SHEET_EXAMPLE_PROMPT: Final = (
    "A soft watercolour illustration of an elderly lighthouse keeper standing alone and facing "
    "the viewer. He is a lean, weathered man of about seventy with deeply tanned skin, a short "
    "white beard, a lined, kind face and thinning white hair, and his expression is calm and "
    "watchful. He wears a thick navy wool fisherman's jumper with a high collar and patched "
    "elbows, loose charcoal trousers tucked into worn brown leather boots, and a brass-buttoned "
    "oilskin coat folded over his left forearm; in his right hand he holds a small brass "
    "lantern. He stands in a relaxed, neutral pose with his arms slightly away from his body, so "
    "the jumper, the coat and his hands can be seen, and his whole figure from boots to hair "
    "fills the tall frame, centred, with a little space around him. He is set against a plain, "
    "seamless white studio backdrop and lit by soft, even light from the front, so the white "
    "behind him stays clean and bright. The palette is muted navy, charcoal, brown and brass, "
    "drawn in fine ink linework with gentle watercolour washes, like a quiet storybook "
    "illustration."
)

# Written for a character who will be cut out of the picture afterwards (`background_removal`).
# The backdrop is plain white, never a key colour: a segmentation model finds the subject whatever
# its colours, while a green or blue key would cut into costumes and skin of that colour.
QWEN_IMAGE_21_CHARACTER_SHEET: Final = ImagePromptProfile(
    id="qwen-image-2.1-character-sheet",
    version=1,
    image_model="Qwen-Image-2.1",
    prompt_rules="\n".join(
        [
            'Rules for "image_prompt", the prompt for the image model. The picture is the '
            "reference of one character: a single figure on a plain white backdrop, which is "
            "cut out afterwards.",
            "1. One paragraph of plain English prose, in complete sentences and the present "
            "tense, 120 to 220 words. No lists, no headings, no labels and no piles of "
            "comma-separated keywords.",
            "2. Open with the kind of picture it is, taken from the style (for example 'A soft "
            "watercolour illustration of' or 'A natural studio photograph of'), and go straight "
            "to the character standing alone and facing the viewer.",
            "3. Then describe the character from the appearance you are given: apparent age, "
            "build, skin tone, face, hair and expression, then the clothing from head to foot "
            "with its colours and materials, the jewellery, and anything the character carries. "
            "Keep the words of the appearance where you can, and add nothing that changes who "
            "the character is. The personality only guides the bearing and the expression.",
            "4. Then the pose and the framing: a relaxed, neutral standing pose with the arms "
            "slightly away from the body so the clothes and the hands can be seen, the whole "
            "figure from head to feet in the frame, centred, with a little space around it.",
            "5. Then the backdrop and the light, in these words or close to them: the character "
            "is set against a plain, seamless white studio backdrop and lit by soft, even light "
            "from the front. The backdrop is the only thing around the character: say nothing "
            "about scenery, furniture, a floor or any other object.",
            "6. Put the author's style into words as the last sentence, in the style of the "
            "whole video. With none given, use a natural, realistic look.",
            "7. Nothing is written in the picture: no text, captions, letters, numbers, signs "
            "with words, labels, logos, watermarks, borders or split panels. The model draws any "
            "wording it is given, so do not name any of these, not even to say there are none.",
            "8. Describe only what is visible. The model has no negative prompt, and naming a "
            "thing, even to rule it out ('no', 'without'), can make it appear. Say what fills "
            "the space instead.",
            "9. Never write the character's name, and never name a real person or a famous "
            "figure: describe the looks only.",
            "10. Concrete nouns and plain adjectives. No quality tags (such as 8k, masterpiece "
            "or highly detailed) and no camera brand names.",
        ]
    ),
    example_inputs=_CHARACTER_SHEET_EXAMPLE_INPUTS,
    example_answer=json.dumps(
        {"image_prompt": _CHARACTER_SHEET_EXAMPLE_PROMPT}, ensure_ascii=False
    ),
    min_words=120,
    max_words=220,
    rules=(
        *SEEDREAM_50_LITE.rules,
        TextRule(
            _NEGATIVE_WORDS,
            "A negative found (no, not, without, nothing). The image model has no negative "
            "prompt, and naming a thing can make it appear: say what is there instead.",
        ),
    ),
)

# A library character's master picture made from the author's own picture of it (image 1): the
# inputs are the Character lab's card (`character_look_prompt_writer.prompt_inputs`).
_CHARACTER_SHEET_FROM_PICTURE_EXAMPLE_INPUTS: Final[dict[str, Any]] = {
    "card": (
        "Name: Mira.\n"
        "Age: 9 years old.\n"
        "Gender: female.\n"
        "Species: human.\n"
        "Time: set in the present day.\n"
        "Appearance: A small, wiry girl with a gap-toothed grin.\n"
        "Outfit: A yellow hooded raincoat over a striped navy-and-white jumper, rolled-up blue "
        "jeans and red rubber boots.\n"
        "Personality: Curious and fearless, always first to splash into a puddle.\n"
        "Has a visible mouth."
    ),
}

_CHARACTER_SHEET_FROM_PICTURE_EXAMPLE_PROMPT: Final = (
    "A natural studio photograph of the girl in image 1, standing alone and facing the viewer. "
    "She keeps her face, her hair, her skin and her build exactly as they are in image 1, and "
    "her expression is a bright, curious grin. She wears a yellow hooded raincoat, open at the "
    "front over a striped navy-and-white jumper, rolled-up blue jeans and shiny red rubber "
    "boots. She stands in a relaxed, neutral pose with her arms slightly away from her body, so "
    "the raincoat, the jumper and her hands can be seen, and her whole figure from boots to hair "
    "fills the tall frame, centred, with a little space around her. She is set against a plain, "
    "seamless white studio backdrop and lit by soft, even light from the front, so the white "
    "behind her stays clean and bright. The finish keeps the natural photographic look of "
    "image 1."
)

# The edit endpoint sees the author's picture as image 1. The picture decides who the character
# is (face, hair, skin, build, species): words about those can change them, so the prompt never
# describes them. The profile's outfit, and a style the profile describes, are applied on top.
QWEN_IMAGE_21_CHARACTER_SHEET_FROM_PICTURE: Final = ImagePromptProfile(
    id="qwen-image-2.1-character-sheet-from-picture",
    version=1,
    image_model="Qwen-Image-2.1 (edit, with the author's picture)",
    prompt_rules="\n".join(
        [
            'Rules for "image_prompt", the prompt for the image model. The model is shown the '
            "author's own picture of the character as image 1, and makes from it the reference "
            "of that character: a single figure on a plain white backdrop, which is cut out "
            "afterwards.",
            "1. One paragraph of plain English prose, in complete sentences and the present "
            "tense, 80 to 220 words. No lists, no headings, no labels and no piles of "
            "comma-separated keywords.",
            "2. Open with the kind of picture it is, taken from the style (rule 7), and go "
            "straight to the character of image 1, standing alone and facing the viewer. Call "
            "it 'the character in image 1', or 'the girl in image 1', 'the robot in image 1' "
            "and so on.",
            "3. The picture decides who the character is. Never describe its face, hair, skin, "
            "build or species in words: the picture shows them, and any words about them can "
            "change them. Say it once, in one sentence: the character keeps its face, hair, "
            "skin and build exactly as they are in image 1. Use the appearance on the card only "
            "for a part of the body the picture does not show, and never let it change what "
            "the picture does show. The personality only guides the bearing and the expression.",
            "4. The clothes: when the card gives an outfit, dress the character in it and "
            "describe it from head to foot, with its colours and materials. With no outfit on "
            "the card, say in one sentence that the character wears the same clothes as in "
            "image 1, and complete any part of them the picture does not show in keeping with "
            "the rest.",
            "5. Then the pose and the framing: a relaxed, neutral standing pose with the arms "
            "slightly away from the body so the clothes and the hands can be seen, the whole "
            "figure from head to feet in the frame, centred, with a little space around it.",
            "6. Then the backdrop and the light, in these words or close to them: the character "
            "is set against a plain, seamless white studio backdrop and lit by soft, even light "
            "from the front. The backdrop takes the place of whatever is around the character in "
            "image 1: never describe those surroundings, and say nothing about scenery, "
            "furniture, a floor or any other object.",
            "7. Put the style into words as the last sentence: the style the appearance or the "
            "notes describe (a cartoon, a puppet, a painting) when they describe one, otherwise "
            "the look of image 1 itself (a photograph stays a photograph, a drawing stays a "
            "drawing).",
            "8. Nothing is written in the picture: no text, captions, letters, numbers, signs "
            "with words, labels, logos, watermarks, borders or split panels. The model draws any "
            "wording it is given, so do not name any of these, not even to say there are none.",
            "9. Describe only what is visible. The model has no negative prompt, and naming a "
            "thing, even to rule it out ('no', 'without'), can make it appear. Say what fills "
            "the space instead.",
            "10. Never write the character's name, and never name a real person or a famous "
            "figure: refer to the character by its image number.",
            "11. Concrete nouns and plain adjectives. No quality tags (such as 8k, masterpiece "
            "or highly detailed) and no camera brand names.",
        ]
    ),
    example_inputs=_CHARACTER_SHEET_FROM_PICTURE_EXAMPLE_INPUTS,
    example_answer=json.dumps(
        {"image_prompt": _CHARACTER_SHEET_FROM_PICTURE_EXAMPLE_PROMPT}, ensure_ascii=False
    ),
    min_words=80,
    max_words=220,
    rules=(
        *SEEDREAM_50_LITE.rules,
        TextRule(
            _NEGATIVE_WORDS,
            "A negative found (no, not, without, nothing). The image model has no negative "
            "prompt, and naming a thing can make it appear: say what is there instead.",
        ),
    ),
    uses_references=True,
)

_LOCATION_SHEET_EXAMPLE_INPUTS: Final[dict[str, Any]] = {
    "kind": "location",
    "style_prefix": "soft watercolour illustration",
    "description_instructions": None,
    "appearance": (
        "A low wooden mountain tea house with a steep grey-slate roof and deep eaves, standing on "
        "a terrace of flat stone slabs beside a gnarled pine. Its sliding paper doors are closed "
        "and a row of round red paper lanterns hangs under the front eave. Pale blue mountain "
        "ridges rise behind it into morning mist."
    ),
}

_LOCATION_SHEET_EXAMPLE_PROMPT: Final = (
    "A soft watercolour illustration of an empty mountain tea house at dawn, seen as a wide "
    "establishing view. A low wooden building with a steep grey-slate roof and deep eaves "
    "stands on a terrace of flat stone slabs, its sliding paper doors closed and a row of round "
    "red paper lanterns hanging unlit under the front eave. In the foreground a stone path winds "
    "up from the lower left between clipped green shrubs; in the middle of the picture the tea "
    "house sits slightly right of centre beside a gnarled pine; behind it, pale blue mountain "
    "ridges rise one beyond the other into soft mist, filling the upper part of the frame. The "
    "camera is at eye level with a gentle 35 mm look and a calm, balanced composition. Cool, low "
    "light from the left runs across the roof and the stones, and a thin mist hangs in the "
    "valley. The palette is slate grey, soft green, pale blue and warm cedar brown, with the red "
    "lanterns as the one bright accent. The finish is fine ink linework with gentle watercolour "
    "washes, like a quiet storybook illustration."
)

# A place is kept whole: its picture is not cut out, because the place is the background.
QWEN_IMAGE_21_LOCATION_SHEET: Final = ImagePromptProfile(
    id="qwen-image-2.1-location-sheet",
    version=1,
    image_model="Qwen-Image-2.1",
    prompt_rules="\n".join(
        [
            'Rules for "image_prompt", the prompt for the image model. The picture is the '
            "reference of one place of the story: an empty establishing view that every scene "
            "set there is made from.",
            "1. One paragraph of plain English prose, in complete sentences and the present "
            "tense, 120 to 220 words. No lists, no headings, no labels and no piles of "
            "comma-separated keywords.",
            "2. Open with the kind of picture it is, taken from the style (for example 'A soft "
            "watercolour illustration of' or 'A natural photograph of'), and go straight to the "
            "place and its main features.",
            "3. Then describe the place from the description you are given: the buildings or "
            "the landscape, their materials and colours, and the details that make it this "
            "place and no other. Keep the words of the description where you can, and add "
            "nothing that changes what the place is.",
            "4. Then say where things sit in the frame (the foreground, the middle and the "
            "background; left, centre and right; the upper and lower parts of the picture), "
            "the angle (a wide establishing view at eye level) and the lens look (for example "
            "'35 mm look').",
            "5. Then the light (where it comes from, its direction and quality), the time of "
            "day, the weather, the colour palette and the mood.",
            "6. The place stands empty: put no person, animal or vehicle in it, and do not "
            "mention any.",
            "7. Put the author's style into words as the last sentence, in the style of the "
            "whole video. With none given, use a natural, realistic look.",
            "8. Nothing is written in the picture: no text, captions, letters, numbers, signs "
            "with words, labels, posters, screens, pages, logos, watermarks, borders or split "
            "panels. The model draws any wording it is given, so do not name any of these, not "
            "even to say there are none, and describe any surface that could carry words as "
            "plain or blank.",
            "9. Describe only what is visible. The model has no negative prompt, and naming a "
            "thing, even to rule it out ('no', 'without'), can make it appear. Say what fills "
            "the space instead.",
            "10. Concrete nouns and plain adjectives. No quality tags (such as 8k, masterpiece "
            "or highly detailed) and no camera brand names.",
        ]
    ),
    example_inputs=_LOCATION_SHEET_EXAMPLE_INPUTS,
    example_answer=json.dumps({"image_prompt": _LOCATION_SHEET_EXAMPLE_PROMPT}, ensure_ascii=False),
    min_words=120,
    max_words=220,
    rules=(
        *SEEDREAM_50_LITE.rules,
        TextRule(
            _NEGATIVE_WORDS,
            "A negative found (no, not, without, nothing). The image model has no negative "
            "prompt, and naming a thing can make it appear: say what is there instead.",
        ),
    ),
)

# The inputs of a scene made from reference pictures: the same as any scene's, plus the pictures
# in the order they are sent (`image_prompt_writer.prompt_inputs`, key `cast`).
_CHARACTER_EDIT_EXAMPLE_INPUTS: Final[dict[str, Any]] = {
    "orientation": "portrait",
    "width": 1088,
    "height": 1920,
    "style_prefix": "soft watercolour illustration",
    "description_instructions": None,
    "world": None,
    "cast": {
        "references": [
            {
                "image": 1,
                "kind": "character",
                "name": "Tomas",
                "appearance": _CHARACTER_SHEET_EXAMPLE_INPUTS["appearance"],
            },
            {
                "image": 2,
                "kind": "location",
                "appearance": (
                    "The circular glass lamp room at the top of a lighthouse: a large brass lamp "
                    "and lens at its centre, a narrow iron rail around it, and tall windows "
                    "showing the sea."
                ),
            },
        ]
    },
    "narration": "Every evening, he climbed the stairs to wake the lamp.",
    "continuity": "new_place",
    "first_frame_description": (
        "Medium shot in the lamp room at dusk. The keeper stands beside the great brass lamp, "
        "turned towards it, one hand on the iron rail, about to begin his evening work."
    ),
    "video_prompt": (
        "The keeper reaches out and lays his hand on the lamp, and its glow slowly warms the "
        "room. Slow push in. Distant waves, no music, no voices."
    ),
}

_CHARACTER_EDIT_EXAMPLE_PROMPT: Final = (
    "A soft watercolour illustration, made from the two reference pictures: the keeper in image "
    "1 stands in the lamp room of image 2, keeping his face, his hair and his clothes exactly as "
    "they are in image 1. He stands just left of the great brass lamp, turned three-quarters "
    "towards it, one hand resting on the iron rail and the other raised as if about to reach for "
    "the lamp, his expression calm and attentive. The lamp room of image 2 fills the picture "
    "around him: the circular room of tall glass windows, the large brass lamp and lens at its "
    "centre, and the dusk sea showing deep blue through the glass. In the tall portrait frame he "
    "fills the left half from the lower third up to the upper third, the lamp rises in the right "
    "half, and the windows behind them both reach the top edge. The camera is at chest height and "
    "level, a medium shot with a gentle 35 mm look and soft depth of field. The light is the "
    "warm amber of the brass lamp and the last cool blue of dusk through the windows. The "
    "palette is navy, brass amber and deep blue, drawn in fine ink linework with gentle "
    "watercolour washes, like a quiet storybook illustration."
)

# A scene that shows characters or a place of the cast: its first frame is made by the image
# model's edit, from the picture of each (the characters are images 1, 2 and so on, in the
# scene's order, and the place is the next). A scene may show any number of characters: nothing
# here asks for more than the narration puts in it.
QWEN_IMAGE_21_CHARACTER_EDIT: Final = ImagePromptProfile(
    id="qwen-image-2.1-character-edit",
    version=2,
    image_model="Qwen-Image-2.1 (edit, with reference pictures)",
    prompt_rules="\n".join(
        [
            'Rules for "image_prompt", the prompt for the image model. The model is shown the '
            "reference pictures listed under 'References', numbered in that order, and makes a "
            "new picture of this scene from them.",
            "1. One paragraph of plain English prose, in complete sentences and the present "
            "tense, 80 to 320 words. No lists, no headings, no labels and no piles of "
            "comma-separated keywords.",
            "2. Open with the kind of picture it is, taken from the style, and say which "
            "reference pictures it is made from. Name each by its number, a character by the "
            "number of its own picture: 'the character in image 1', 'the place in image 2'.",
            "3. Never describe a character's face, hair, build, skin or clothes: the picture "
            "shows them, and any words about them can change them. Say it once, in one "
            "sentence: each character keeps the face, hair and clothes exactly as they are in "
            "its own image. Then say only what each character does, where it stands or sits, "
            "which way it faces and what its expression is, naming each by its image number so "
            "that no two are mixed up.",
            "4. With a picture of the place, say where in that place the scene is and what part "
            "of it is seen, calling it 'the place in image 2' (use its number), and never "
            "describe the place again. With no picture of the place, describe the setting in "
            "full.",
            "5. Then say where things sit in the frame (the foreground, the middle and the "
            "background; left, centre and right; the upper and lower parts of the picture), the "
            "shot size and the angle, the lens look, the light, the colour palette and, last, "
            "the style.",
            "6. Keep everything the first frame description says, and add detail to it. Never "
            'change it. With no first frame description ("none"), picture the instant just '
            "before the motion in the video prompt begins. It is the instant just before the "
            "motion begins: each character in place and ready to move, never in the middle of "
            "the action and never after it.",
            "7. A scene with a picture of a place and none of a character shows the place alone, "
            "from the camera position the descriptions give. The only people who may be clearly "
            "seen are the characters of the reference pictures. Anyone else the narration "
            "mentions is left out, or is a small distant figure seen from behind.",
            "8. Compose for the frame shape you are given, and use the whole frame. The picture "
            "is trimmed slightly to fit the exact size, so keep the main subject and every "
            "important detail clear of the outer edges.",
            "9. Nothing is written in the picture: no text, captions, letters, numbers, signs "
            "with words, labels, posters, screens, pages, logos, watermarks, borders or split "
            "panels. The model draws any wording it is given, so do not name any of these, not "
            "even to say there are none, and describe any surface that could carry words as "
            "plain or blank.",
            "10. Describe only what is visible. The model has no negative prompt, and naming a "
            "thing, even to rule it out ('no', 'without'), can make it appear. Say what fills "
            "the space instead.",
            "11. When the world lists a character or a place of a reference picture, ignore its "
            "description and use the picture. Refer to a character by its image number, never "
            "by its name.",
            "12. Concrete nouns and plain adjectives. No quality tags (such as 8k, masterpiece "
            "or highly detailed) and no camera brand names.",
        ]
    ),
    example_inputs=_CHARACTER_EDIT_EXAMPLE_INPUTS,
    example_answer=json.dumps({"image_prompt": _CHARACTER_EDIT_EXAMPLE_PROMPT}, ensure_ascii=False),
    min_words=80,
    max_words=320,
    rules=(
        *SEEDREAM_50_LITE.rules,
        TextRule(
            _NEGATIVE_WORDS,
            "A negative found (no, not, without, nothing). The image model has no negative "
            "prompt, and naming a thing can make it appear: say what is there instead.",
        ),
    ),
    uses_references=True,
)

# The image adapter the job asks for.
ACTIVE_IMAGE_PROFILE: Final = QWEN_IMAGE_21
# The image adapter that edits the first frame into the last frame.
ACTIVE_EDIT_PROFILE: Final = QWEN_IMAGE_21_EDIT
# The reference pictures of the cast: a character on a white backdrop, a place as it is.
ACTIVE_CHARACTER_SHEET_PROFILE: Final = QWEN_IMAGE_21_CHARACTER_SHEET
# A library character's master picture made from the author's own picture of it.
ACTIVE_CHARACTER_SHEET_FROM_PICTURE_PROFILE: Final = QWEN_IMAGE_21_CHARACTER_SHEET_FROM_PICTURE
ACTIVE_LOCATION_SHEET_PROFILE: Final = QWEN_IMAGE_21_LOCATION_SHEET
# The image adapter that makes a first frame from the pictures of the scene's cast.
ACTIVE_CAST_SCENE_PROFILE: Final = QWEN_IMAGE_21_CHARACTER_EDIT


def scene_profile(*, has_references: bool) -> ImagePromptProfile:
    """The profile that writes a scene's first frame prompt: the one for reference pictures when
    the scene shows a character or a place of the cast, else the ordinary one.
    """
    return ACTIVE_CAST_SCENE_PROFILE if has_references else ACTIVE_IMAGE_PROFILE
