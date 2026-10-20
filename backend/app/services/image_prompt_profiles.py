"""What depends on the image model when an AI writes an image prompt (Phase 16). Today the
Character Lab uses it to write a look's master picture prompt.

An *image prompt profile* is the counterpart of the video prompt profile
(`lab_prompt_profiles.py`). It holds the three things that change when the image model
changes:

- the rules its prompt must follow (`prompt_rules`), with one worked example;
- the checks that tell whether a written prompt breaks them (`rules`, `min_words`,
  `max_words`);
- its name and version, which are stored on every job that wrote a prompt.

Everything else (the task, the data sent, the JSON answer, the job, the API and the page)
knows nothing about which image model it is. The profiles in use are for Qwen-Image-2.1, which
makes the pictures on the GPU server. The Seedream profile stays below for reference. To use
another image model, add a profile and point the `ACTIVE_...` name at it.

The text here is the lever for better prompts, so a change to it is a change to every future
prompt. Raise `version` whenever any text in a profile, or in the generic instructions in
`image_prompt_writer.py`, changes: the job stores the profile's id and version next to the
exact request, so earlier prompts can be compared with later ones.
Pure data, no I/O.

The profiles for a scene's first frame, a last-frame edit and a place's reference sheet were
retired with the narration pipeline (PHASE-046). They are readable at the git tag
`narration-final`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any, Final

from app.services.text_rules import TextRule

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


# Words that rule something out. The image model has no negative prompt, and naming a thing,
# even to rule it out, can make it appear.
_NEGATIVE_WORDS: Final = re.compile(
    r"\b(no|not|without|never|nothing|don't|doesn't|isn't|aren't)\b", re.IGNORECASE
)


# --- Character reference pictures ------------------------------------------------------------
#
# These profiles are written from the same published Qwen guidance as the one above (which they
# follow in everything but their subject), not from tests of this model's output here. Check them
# against real pictures and raise `version` when they change.

# A character's description and the style of the video, as the first writers of this profile
# were given them.
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


# A library character's master picture made from the picture of the SAME PERSON at another age,
# or of an identical twin (PHASE-047): image 1 is the base character's picture, and the card
# is the character to make. `inputs` hold one more line, `relation_line`, that says how the two
# are related (written by code from the two definitions, never by a model).
_CHARACTER_SHEET_SAME_PERSON_EXAMPLE_INPUTS: Final[dict[str, Any]] = {
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
    "relation_line": (
        "Image 1 shows this same person at 41 years old. The picture to make shows them at 9 "
        "years old."
    ),
}

_CHARACTER_SHEET_SAME_PERSON_EXAMPLE_PROMPT: Final = (
    "A natural studio photograph of the same person as in image 1 at nine years old, a small, "
    "wiry girl standing alone and facing the viewer. She keeps the face shape, the shape and "
    "colour of the eyes, the nose, the mouth and the skin tone of image 1, with the smooth, "
    "round cheeks, the small frame and the thin dark hair of a child, and her expression is a "
    "bright, gap-toothed grin. She wears a yellow hooded raincoat, open at the front over a "
    "striped navy-and-white jumper, rolled-up blue jeans and shiny red rubber boots. She "
    "stands in a relaxed, neutral pose with her arms slightly away from her body, so the "
    "raincoat, the jumper and her hands can be seen, and her whole figure from boots to hair "
    "fills the tall frame, centred, with a little space around her. She is set against a "
    "plain, seamless white studio backdrop and lit by soft, even light from the front, so the "
    "white behind her stays clean and bright. The finish keeps the natural photographic look "
    "of image 1."
)

_SAME_PERSON_RULES: Final = "\n".join(
    [
        'Rules for "image_prompt", the prompt for the image model. The model is shown a '
        "picture of the SAME PERSON as the character on the card (image 1), or of the "
        "character's identical twin, and makes from it the reference of the character on the "
        "card: a single figure on a plain white backdrop, which is cut out afterwards. The "
        "line 'Relation to image 1' says which of the two it is.",
        "1. One paragraph of plain English prose, in complete sentences and the present "
        "tense, 80 to 220 words. No lists, no headings, no labels and no piles of "
        "comma-separated keywords.",
        "2. Open with the kind of picture it is, taken from the style (rule 8), and go "
        "straight to the character: 'the same person as in image 1 at nine years old' for a "
        "younger or older self, or 'the identical twin of the character in image 1' for a "
        "twin, standing alone and facing the viewer.",
        "3. The face stays. Say once, in one sentence, that the character keeps the face "
        "shape, the shape and colour of the eyes, the nose, the mouth and the skin tone of "
        "image 1. Never describe those features in other words: words about them can change "
        "them.",
        "4. For a younger or older self, then say what the age changes, and only that: the "
        "skin (smooth or lined), the cheeks, the hair (its fullness and colour, from the "
        "card), the build and the height (from the card), and the bearing. Give the age in "
        "years once. For a twin the age does not change: say what the card gives for the "
        "hair and the bearing, and keep it to that.",
        "5. The clothes: dress the character in the outfit on the card, head to foot, with "
        "its colours and materials. The clothes of image 1 are never used. With no outfit on "
        "the card, choose clothes that fit the character's age and time.",
        "6. Then the pose and the framing: a relaxed, neutral standing pose with the arms "
        "slightly away from the body so the clothes and the hands can be seen, the whole "
        "figure from head to feet in the frame, centred, with a little space around it.",
        "7. Then the backdrop and the light, in these words or close to them: the character "
        "is set against a plain, seamless white studio backdrop and lit by soft, even light "
        "from the front. The backdrop takes the place of whatever is around the character in "
        "image 1: never describe those surroundings, and say nothing about scenery, "
        "furniture, a floor or any other object.",
        "8. Put the style into words as the last sentence: the style the appearance or the "
        "notes describe (a cartoon, a puppet, a painting) when they describe one, otherwise "
        "the look of image 1 itself (a photograph stays a photograph, a drawing stays a "
        "drawing).",
        "9. Nothing is written in the picture: no text, captions, letters, numbers, signs "
        "with words, labels, logos, watermarks, borders or split panels. The model draws any "
        "wording it is given, so do not name any of these, not even to say there are none.",
        "10. Describe only what is visible. The model has no negative prompt, and naming a "
        "thing, even to rule it out ('no', 'without'), can make it appear. Say what fills "
        "the space instead.",
        "11. Never write the character's name, and never name a real person or a famous "
        "figure: refer to the character by its image number.",
        "12. Concrete nouns and plain adjectives. No quality tags (such as 8k, masterpiece "
        "or highly detailed) and no camera brand names.",
    ]
)

QWEN_IMAGE_21_CHARACTER_SHEET_SAME_PERSON: Final = replace(
    QWEN_IMAGE_21_CHARACTER_SHEET_FROM_PICTURE,
    id="qwen-image-2.1-character-sheet-same-person",
    version=1,
    image_model="Qwen-Image-2.1 (edit, with the same person's picture)",
    prompt_rules=_SAME_PERSON_RULES,
    example_inputs=_CHARACTER_SHEET_SAME_PERSON_EXAMPLE_INPUTS,
    example_answer=json.dumps(
        {"image_prompt": _CHARACTER_SHEET_SAME_PERSON_EXAMPLE_PROMPT}, ensure_ascii=False
    ),
)


# The reference pictures of the cast: a character on a white backdrop, a place as it is.
ACTIVE_CHARACTER_SHEET_PROFILE: Final = QWEN_IMAGE_21_CHARACTER_SHEET
# A library character's master picture made from the author's own picture of it.
ACTIVE_CHARACTER_SHEET_FROM_PICTURE_PROFILE: Final = QWEN_IMAGE_21_CHARACTER_SHEET_FROM_PICTURE
# A library character's master picture made from a picture of the same person (PHASE-047).
ACTIVE_CHARACTER_SHEET_SAME_PERSON_PROFILE: Final = QWEN_IMAGE_21_CHARACTER_SHEET_SAME_PERSON
