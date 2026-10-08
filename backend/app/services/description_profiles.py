"""What depends on the video model when an AI writes scene descriptions (Phase 12).

A *prompt profile* holds the three things that change when the video model changes:

- the rules its motion prompt must follow (`video_prompt_rules`), with one worked example;
- the checks that tell whether a written prompt breaks them (`rules`, `max_video_words`);
- its name and version, which are stored on every drafting job.

Everything else about drafting (the task, the consistency rules, the frame rules, the JSON
answer, the job, the API and the page) knows nothing about LTX. To use another video model,
add a profile below and point `ACTIVE_PROFILE` at it.

Two profiles exist. `ltx-2.3-keyframe` (Phase 12) was written for clips made from a first and
a last frame, and stays here unchanged because earlier drafting jobs name it. `ltx-2.3-first-frame`
(Phase 15) is the active one: clips start from a first frame alone, so its video prompts say
what changes from that frame and where the action ends.

The text here is the lever for better prompts, so a change to it is a change to every future
draft. Raise `version` whenever any text in a profile changes: the job stores the profile's
id and version next to the exact request, so earlier drafts can be compared with later ones.
Pure data, no I/O.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final

# Straight and curly double quotes (LTX lip-syncs quoted speech).
_DOUBLE_QUOTES: Final = re.compile(r"[\"\u201c\u201d\u201e]")
_CUT_TO: Final = re.compile(r"\bcut to\b", re.IGNORECASE)
# "0:03", "3 seconds", "2.5 sec". Not a bare "s", so "the 1920s" does not match.
_TIMESTAMP: Final = re.compile(
    r"\b\d{1,2}:\d{2}\b|\b\d+(\.\d+)?\s?(sec|secs|second|seconds)\b", re.IGNORECASE
)
_VIDEO_STARTS_WITH: Final = re.compile(r"\bthe video (starts|begins) with\b", re.IGNORECASE)


@dataclass(frozen=True)
class TextRule:
    """A wording the video prompt must not contain. Breaking it is a warning, never an error."""

    pattern: re.Pattern[str]
    message: str


@dataclass(frozen=True)
class PromptProfile:
    id: str
    # Raised by hand whenever any text below changes.
    version: int
    # Named to the writer, so it knows what it is writing for.
    video_model: str
    # How to write `video_prompt` for this model.
    video_prompt_rules: str
    # One worked scene, as the JSON the writer must answer with. From an unrelated video.
    example: str
    max_video_words: int
    rules: tuple[TextRule, ...]


_LTX_EXAMPLE: Final = json.dumps(
    {
        "scene": 1,
        "continuity": "new_place",
        "first_frame": (
            "Medium shot at eye level, a 35 mm look with shallow depth of field. A woman in her "
            "sixties with short grey hair and a mustard-yellow cardigan sits at a worn oak kitchen "
            "table, holding an unopened cream envelope in both hands, her eyes lowered to it. "
            "Soft window light from the left, a warm, slightly faded colour palette, steam rising "
            "from a white cup beside her. Portrait frame, her face in the upper third."
        ),
        "last_frame": (
            "The same medium shot, the same light and framing. The envelope is now open and she "
            "holds the unfolded letter in one hand, her eyes lifted towards the window, her "
            "expression thoughtful. Steam still rises from the cup."
        ),
        "video_prompt": (
            "She slides a thumb under the flap and tears the envelope open, pulls out a folded "
            "sheet and lets the empty envelope drop to the table. Her gaze lifts slowly to the "
            "window as she exhales. Static camera with a very slight push-in towards her face. "
            "The window light brightens gently. Soft room tone, paper rustling, a faint clock "
            "ticking, no music, no voices."
        ),
    },
    ensure_ascii=False,
)

LTX_23_KEYFRAME: Final = PromptProfile(
    id="ltx-2.3-keyframe",
    version=1,
    video_model="LTX-2.3 in first-and-last-frame mode",
    video_prompt_rules="\n".join(
        [
            'Rules for "video_prompt", the motion prompt for LTX-2.3. LTX makes each clip from '
            "the first frame, the last frame and this prompt:",
            "1. The two frames already show how everything looks. Describe only the MOTION that "
            "carries the first frame to the last frame. Never describe again what the frames "
            "show (faces, clothes, colours, rooms): that pulls the video away from them.",
            "2. One flowing paragraph in the present tense, 4 to 8 sentences, at most 200 words. "
            "Keep it in proportion to the scene: about one action for every 2 to 3 seconds, so a "
            "short scene gets a short prompt.",
            "3. Order: the main action in one clear sentence; then the specific movements and "
            "gestures, as literal, chronological verbs (lifts, turns, drifts) and not mood "
            "words; then ONE camera move; then how the light changes, if it does; then the "
            "sound.",
            '4. Camera: name exactly one move in plain words, such as "static camera", "slow '
            'push-in", "slow pull-back", "slow pan left", "handheld, slightly drifting" or '
            '"slow tracking shot following her". Choose it from what the scene needs, and vary '
            "it across the video instead of repeating one move.",
            "5. Sound: end with one short sentence about what is heard in this place: ambience "
            "and small effects, concrete and specific. By default there is no music, no speech "
            'and no singing, and you say so ("no music, no voices"). The author\'s '
            "instructions can change this.",
            '6. Never use: double quotes (they make people speak), "cut to" or any scene '
            'change, times or seconds, "the video starts with", on-screen text.',
            "7. Plain film language only. No technical specs: no focal lengths, f-stops, "
            "resolutions or camera model names. The frames already set the look.",
        ]
    ),
    example=_LTX_EXAMPLE,
    max_video_words=200,
    rules=(
        TextRule(
            _DOUBLE_QUOTES,
            "Double quotes found. The video model lip-syncs quoted speech, and there is no "
            "dialogue here.",
        ),
        TextRule(
            _CUT_TO,
            "\u201ccut to\u201d found. Describe one continuous motion between the two frames "
            "instead.",
        ),
        TextRule(
            _TIMESTAMP,
            "A time such as \u201c0:03\u201d or \u201c3 seconds\u201d found. The clip's length "
            "is set by the scene.",
        ),
        TextRule(
            _VIDEO_STARTS_WITH,
            "\u201cthe video starts with\u201d found. The first frame already shows the start: "
            "describe the motion.",
        ),
    ),
)

# --- LTX-2.3 image-to-video from a first frame (Phase 15) -----------------------------------

_FIRST_FRAME_EXAMPLE: Final = json.dumps(
    {
        "scene": 1,
        "continuity": "new_place",
        "first_frame": (
            "Close-up at water level, a 35 mm look with shallow depth of field. A cream paper "
            "boat with a faded blue stripe along its edge sits at the rim of a rain puddle "
            "between dark, wet cobblestones, its bow pointing across the water. A single yellow "
            "leaf floats in the puddle beyond it. Flat overcast light, a muted palette of grey, "
            "slate blue and cream. Portrait frame, the boat near the centre, the puddle filling "
            "the lower half."
        ),
        "video_prompt": (
            "A gust of wind pushes the paper boat off the rim and into the puddle. It drifts "
            "slowly across the water, turning a quarter turn as ripples spread behind it, "
            "nudges the floating leaf aside and comes to rest against the far edge, rocking "
            "gently. Slow pan right, following the boat. Soft rain patter, water lapping "
            "against stone, a faint gust of wind, no music, no voices."
        ),
    },
    ensure_ascii=False,
)

_CUT_TO_FIRST_FRAME: Final = TextRule(
    _CUT_TO,
    "\u201ccut to\u201d found. Describe one continuous shot instead.",
)

LTX_23_FIRST_FRAME: Final = PromptProfile(
    id="ltx-2.3-first-frame",
    # 2: the generic "Fixed fields" text (description_writer.py) now says that only FIXED
    # fields are answered null. With version 1 the model also left out the first frame of a
    # scene whose video prompt the author had written (draft job 84).
    version=2,
    video_model="LTX-2.3 image-to-video from a first frame",
    video_prompt_rules="\n".join(
        [
            'Rules for "video_prompt", the motion prompt for LTX-2.3. LTX starts from the first '
            "frame and makes the clip from this prompt. Nothing else says where the clip ends:",
            "1. The first frame already shows how everything looks. Describe only what CHANGES "
            "from it. Never describe again its looks, colours, materials or setting: that makes "
            "the video drift away from the frame. Name a subject only as far as is needed to "
            "say what it does.",
            "2. The main action first, in one clear sentence. Then the specific movements and "
            "gestures, as literal, chronological verbs (lifts, turns, drifts) and not mood "
            "words.",
            "3. Say where the action ends: the final position or state, in plain words (for "
            'example "comes to rest against the far edge"). This is the only thing that fixes '
            "the end of the clip.",
            "4. Size the action to the scene: about one action for every 2 to 3 seconds, so a "
            "short scene gets a short prompt. One flowing paragraph in the present tense, at "
            "most 200 words.",
            '5. Camera: name exactly one move in plain words, such as "static camera", "slow '
            'push-in", "slow pull-back", "slow pan left", "handheld, slightly drifting" or '
            '"slow tracking shot following the boat". Choose it from what the scene needs, and '
            "vary it across the video instead of repeating one move.",
            "6. Light: say how the light changes, only if it does.",
            "7. Sound: end with one short sentence about what is heard in this place: ambience "
            "and small effects, concrete and specific, tied to the action. By default there is "
            'no music, no speech and no singing, and you say so ("no music, no voices"). The '
            "author's instructions can change this.",
            '8. Never use: double quotes (they make people speak), "cut to" or any scene '
            'change, times or seconds, "the video starts with", on-screen text.',
            "9. Plain film language and restrained adjectives. No technical specs: no focal "
            "lengths, f-stops, resolutions or camera model names. The frame already sets the "
            "look.",
        ]
    ),
    example=_FIRST_FRAME_EXAMPLE,
    max_video_words=200,
    rules=(
        TextRule(
            _DOUBLE_QUOTES,
            "Double quotes found. The video model lip-syncs quoted speech, and there is no "
            "dialogue here.",
        ),
        _CUT_TO_FIRST_FRAME,
        TextRule(
            _TIMESTAMP,
            "A time such as \u201c0:03\u201d or \u201c3 seconds\u201d found. The clip's length "
            "is set by the scene.",
        ),
        TextRule(
            _VIDEO_STARTS_WITH,
            "\u201cthe video starts with\u201d found. The first frame already shows the start: "
            "describe the motion.",
        ),
    ),
)

# The video adapter the job asks for. `LTX_23_KEYFRAME` stays above, unchanged, because jobs
# from Phase 12 name it.
ACTIVE_PROFILE: Final = LTX_23_FIRST_FRAME
