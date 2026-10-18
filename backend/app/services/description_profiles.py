"""What depends on the video model when an AI writes scene descriptions (Phase 12).

A *prompt profile* holds the three things that change when the video model changes:

- the rules its motion prompt must follow (`video_prompt_rules`), with one worked example;
- the checks that tell whether a written prompt breaks them (`rules`, `max_video_words`);
- its name and version, which are stored on every drafting job.

Everything else about drafting (the task, the consistency rules, the frame rules, the JSON
answer, the job, the API and the page) knows nothing about LTX. To use another video model,
add a profile below and choose it in `profile_for_model`.

Five profiles exist. `ltx-2.3-keyframe` (Phase 12) was written for clips made from a first and
a last frame, and stays here unchanged because earlier drafting jobs name it. `ltx-2.3-first-frame`
(Phase 15) was written for clips that start from a first frame alone, and stays unchanged for the
same reason. `ltx-first-frame` (Phase 19) writes for LTX-2.3 and LTX-2.5 alike, so a scene's
prompt can be made with either model and the takes compared, and also stays unchanged. Both
models read a first-frame prompt the same way (the server's guide and Lightricks' prompting
guide agree on it), so only the request differs between them, never the prompt.
`ltx-first-last` (Phase 23) writes for the same two models, and the model also decides which
scenes get a last frame, and writes it (`writes_last_frame`). A scene with a last frame gets the
keyframe rules for its video prompt, one without keeps the first-frame rules. It is the profile
of every project whose video model is an LTX model (`ACTIVE_PROFILE`).
`minimax-h3-scene` writes for MiniMax H3, which reads a different kind of prompt: three named
fields (`answer_format = "h3_fields"`) instead of one paragraph. It is the profile of every
project whose video model is MiniMax H3 (`profile_for_model`).

The text here is the lever for better prompts, so a change to it is a change to every future
draft. Raise `version` whenever any text in a profile changes: the job stores the profile's
id and version next to the exact request, so earlier drafts can be compared with later ones.
Pure data, no I/O.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final, Literal

from app.services.video_models import H3_MODEL, VideoModel

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
    # --- Phase 23: a profile whose model also decides on, and writes, a last frame ----------
    # False for the three profiles that came before: their instructions are unchanged, and
    # they never ask for a last frame. When True, `video_prompt_rules` is for a scene WITHOUT a
    # last frame and `video_prompt_rules_with_last_frame` for one with it.
    writes_last_frame: bool = False
    # When to write a last frame, and how (what the system message says about the field).
    last_frame_rules: str = ""
    video_prompt_rules_with_last_frame: str = ""
    # A second worked scene, one that has a last frame (`example` has none).
    example_with_last_frame: str = ""
    # Checks on the written last frame (a warning, never an error), and about how long it is.
    last_frame_checks: tuple[TextRule, ...] = ()
    max_last_frame_words: int = 0
    # Extra checks on the video prompt of a scene that has a last frame.
    rules_with_last_frame: tuple[TextRule, ...] = ()
    # How the model answers with the video prompt: one text ("prose"), or an object with the
    # three fields MiniMax H3 reads ("h3_fields"), which the app joins into one text.
    answer_format: Literal["prose", "h3_fields"] = "prose"


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

# --- LTX-2.3 and LTX-2.5 image-to-video from a first frame (Phase 19) ------------------------

# What differs from `ltx-2.3-first-frame`, from the server's guide and Lightricks' prompting
# guide for LTX-2.5 (the LTX-2.3 section of the server's guide agrees on every point):
# - sound is written where it happens, inside the sentence of the action it belongs to, not as a
#   closing sentence;
# - 4 to 8 sentences, each with a verb that does something;
# - pauses are written in (the model adds none by itself), and the camera says where the subject
#   ends up after it moves;
# - one lighting logic, and feeling shown through physical cues;
# - a named cut ("a hard cut transitions to") is a real edit for LTX-2.5, so it is warned about.
_LTX_FIRST_FRAME_EXAMPLE: Final = json.dumps(
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
            "A gust of wind pushes the paper boat off the rim and into the puddle with a soft "
            "splash. It drifts slowly across the water, turning a quarter turn as ripples "
            "spread behind it and the water laps against the stone. It nudges the floating "
            "leaf aside, pauses for a beat, then comes to rest against the far edge, rocking "
            "gently as the last ripples fade. Slow pan right, following the boat until it sits "
            "near the centre of the frame, with a faint rain patter and a low gust of wind "
            "underneath. No music, no voices."
        ),
    },
    ensure_ascii=False,
)

# A transition named in words is an edit for LTX-2.5. A clip made from one first frame is one
# continuous shot, so these are warned about (the Video lab is where cuts are tried).
_NAMED_CUT: Final = re.compile(
    r"\b(hard|match|jump|smash) cut\b|\bcuts? away\b|\bcuts? (?:to|into)\b", re.IGNORECASE
)

LTX_FIRST_FRAME: Final = PromptProfile(
    id="ltx-first-frame",
    version=1,
    video_model="LTX-2.3 or LTX-2.5 image-to-video from a first frame (one continuous shot)",
    video_prompt_rules="\n".join(
        [
            'Rules for "video_prompt", the motion prompt for LTX. LTX starts from the first '
            "frame and makes the clip as one continuous shot from this prompt. Nothing else "
            "says where the clip ends:",
            "1. The first frame already shows how everything looks. Describe only what CHANGES "
            "from it. Never describe again its looks, colours, materials or setting: that makes "
            "the video drift away from the frame. Name a subject only as far as is needed to "
            "say what it does.",
            "2. One flowing paragraph in the present tense, 4 to 8 short sentences in all "
            "(action, camera, light and sound count), at most 200 words. A scene of 2 to 3 "
            "seconds sits at the low end and one of 6 seconds at the high end: about one "
            "action for every 2 to 3 seconds.",
            "3. The main action first, in one clear sentence. Then the specific movements and "
            "gestures, as literal, chronological verbs (lifts, turns, drifts). Every sentence "
            "has a verb that does something: appearance alone gives the video model nothing "
            "to animate. Show feeling through physical cues (a breath, a lowered gaze, "
            'slumped shoulders), never with a label such as "sad".',
            "4. Write the pace in. The video model adds no pause you do not ask for, so put "
            'the beats into the action ("it pauses for a beat", "a moment of stillness").',
            "5. Say where the action ends: the final position or state, in plain words (for "
            'example "comes to rest against the far edge"). This is the only thing that fixes '
            "the end of the clip.",
            '6. Camera: name exactly one move in plain words, such as "static camera", "slow '
            'push-in", "slow pull-back", "slow pan left", "handheld, slightly drifting" or '
            '"slow tracking shot following the boat", and say where the subject ends up '
            'after it ("until the cup fills the lower third"). Choose it from what the scene '
            "needs, and vary it across the video instead of repeating one move.",
            "7. Light: one lighting logic for the whole shot. Say how the light changes, only "
            "if it does.",
            "8. Sound: write it where it happens, inside the sentence of the action it belongs "
            'to ("the broom scrapes over the stone as it sweeps"), concrete and specific, not '
            "as a closing sentence of its own. By default there is no music, no speech and no "
            'singing, and you say so once, briefly, at the very end ("No music, no voices."). '
            "The author's instructions can change this.",
            '9. Never use: double quotes (they make people speak), "cut to" or any scene '
            "change or named transition (hard cut, match cut, dissolve), times or seconds, "
            '"the video starts with", on-screen text.',
            '10. Plain film language and restrained adjectives ("red dress", not "vibrant '
            'crimson dress"). No technical specs: no focal lengths, f-stops, resolutions or '
            "camera model names. The frame already sets the look.",
        ]
    ),
    example=_LTX_FIRST_FRAME_EXAMPLE,
    max_video_words=200,
    rules=(
        TextRule(
            _DOUBLE_QUOTES,
            "Double quotes found. The video model lip-syncs quoted speech, and there is no "
            "dialogue here.",
        ),
        _CUT_TO_FIRST_FRAME,
        TextRule(
            _NAMED_CUT,
            "A named cut (\u201chard cut\u201d, \u201cmatch cut\u201d, \u201ccuts away\u201d) "
            "found. LTX-2.5 treats it as a real edit, but a clip made from one first frame is "
            "one continuous shot. Try cuts in the Video lab.",
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

# --- LTX-2.3 and LTX-2.5 from a first frame, or from a first and a last frame (Phase 23) -----

# What differs from `ltx-first-frame`:
# - the model also decides, scene by scene, whether the clip gets a last frame, and writes it. The
#   image model makes that frame later by EDITING the first frame, so it is written as "the same
#   shot, one moment later";
# - a scene with a last frame gets the keyframe rules (describe only the motion between the two
#   frames, and a camera that does not change the framing), a scene without one keeps the
#   first-frame rules of `ltx-first-frame`;
# - a scene whose next scene "continues_action" ends on the picture that scene starts from.
_FIRST_FRAME_ONLY: Final = json.loads(_LTX_FIRST_FRAME_EXAMPLE)
# The paper boat is followed by a pan, so it is a scene that has no last frame.
_LTX_FIRST_LAST_EXAMPLE_NONE: Final = json.dumps(
    {
        "scene": _FIRST_FRAME_ONLY["scene"],
        "continuity": _FIRST_FRAME_ONLY["continuity"],
        "first_frame": _FIRST_FRAME_ONLY["first_frame"],
        "last_frame": None,
        "video_prompt": _FIRST_FRAME_ONLY["video_prompt"],
    },
    ensure_ascii=False,
)
_LTX_FIRST_LAST_EXAMPLE_WITH: Final = json.dumps(
    {
        "scene": 2,
        "continuity": "new_place",
        "first_frame": (
            "Close-up at moss level, a 35 mm look with shallow depth of field. A small brown "
            "garden snail with a pale spiral shell sits at the left edge of a flat grey stone "
            "covered in soft green moss, its antennae raised towards the right. Dull overcast "
            "light, a muted palette of grey, moss green and brown. Portrait frame, the snail "
            "in the lower left, the stone filling the lower half and soft blurred ferns behind "
            "it."
        ),
        "last_frame": (
            "The same shot, the same light and framing. The snail has crossed the stone and "
            "now sits at its centre, its antennae raised and bent towards the ferns. The moss, "
            "the stone and the blurred ferns are unchanged."
        ),
        "video_prompt": (
            "The snail glides slowly across the mossy stone, its antennae swaying, and climbs "
            "a small ridge with a faint wet slide against the moss. It pauses for a beat, "
            "antennae turning towards the ferns, then moves on until it rests at the centre "
            "of the stone with its antennae raised. Static camera. A distant bird calls "
            "once. No music, no voices."
        ),
    },
    ensure_ascii=False,
)

# "The same shot..." is how a written last frame begins. A text that does not is warned about.
_NOT_THE_SAME_SHOT: Final = re.compile(r"^(?!\s*the same\b)", re.IGNORECASE)
# A last frame is a still: no motion in progress.
_MOTION_UNDER_WAY: Final = re.compile(
    r"\b(starts? to|begins? to|about to|in the middle of|is (?:moving|walking|turning|rising))\b",
    re.IGNORECASE,
)
# A move that changes the framing between the first and the last frame.
_FRAMING_MOVE: Final = re.compile(
    r"\b(pan(?:s|ning)? (?:left|right|up|down|across)|pulls? back|pull-back|tracking shot|"
    r"zooms?|dolly|crane shot|orbits?)\b",
    re.IGNORECASE,
)

LTX_FIRST_LAST: Final = PromptProfile(
    id="ltx-first-last",
    version=1,
    video_model=(
        "LTX-2.3 or LTX-2.5, from a first frame alone or from a first and a last frame "
        "(one continuous shot)"
    ),
    # For a scene WITHOUT a last frame: the same rules as `ltx-first-frame`.
    video_prompt_rules=LTX_FIRST_FRAME.video_prompt_rules.replace(
        'Rules for "video_prompt", the motion prompt for LTX.',
        'Rules for "video_prompt" in a scene WITHOUT a last frame, the motion prompt for LTX.',
    ),
    example=_LTX_FIRST_LAST_EXAMPLE_NONE,
    max_video_words=200,
    rules=LTX_FIRST_FRAME.rules,
    writes_last_frame=True,
    last_frame_rules="\n".join(
        [
            "When to write a last frame",
            "- A last frame is made later by EDITING the first frame's picture, so it can only "
            "show the SAME shot a moment later: the same place, light, framing and camera "
            "position, with the subject changed. Each one costs extra picture-making time, so "
            "write one only where it makes the clip clearly more controlled. Not every scene "
            "needs one.",
            "- Write one when the scene's ending is a visible change of the subject inside the "
            "same shot and where the clip ends matters: a thing opens, fills, lands, lights up "
            "or moves to a new spot; a subject turns or looks somewhere new; a hand reaches "
            "for something and takes it.",
            '- Write one when the next scene is "continues_action" and this scene\'s motion can '
            "end inside the same shot. The app uses this scene's last frame as the next "
            "scene's first frame, so the cut is seamless.",
            "- Write one when a recurring subject must look exactly the same at the end as at "
            "the start through a clear movement (a close-up of a face or of an object that "
            "moves).",
            '- Answer null for "last_frame" when the scene is ambient or atmospheric with no '
            "clear end state (rain, drifting fog, a still landscape, light slowly changing); "
            "when the camera makes a large move (a pan that reveals a new place, a change from "
            "wide to close); when the scene is shorter than 3 seconds; or when the end would "
            "show a different place, different light or a different time.",
            "",
            'Rules for "last_frame" (a still picture made by editing the first frame)',
            "- It is the SAME shot as the first frame, one moment after the scene's motion "
            "ends: the same place, light, framing, camera position and lens look. Only the "
            "subject changes (its position, state, pose or gaze), or something small enters or "
            "leaves the frame.",
            '- 30 to 70 words. Begin with "The same shot", say what is different in concrete '
            "terms (positions, states, gaze, objects), and end by saying what is unchanged.",
            "- Name a subject by its world name and keep its identifying details from the "
            "world description. Never give it another look.",
            "- It shows where the video prompt's motion ENDS, as a still: the subject in place, "
            'at rest or in a pause. No motion words ("starts to", "is moving") and no sound.',
            "- Never change the camera: no zoom, no new angle, no wider or tighter view. If "
            'the end needs a different framing, answer null for "last_frame" instead.',
            "- No text, captions, logos or watermarks in the picture.",
            "",
            "Scenes that follow each other",
            '- When scene N has a last frame and scene N+1 is "continues_action", the '
            "first_frame of scene N+1 must describe exactly the picture of scene N's "
            "last_frame (word for word where you can, written as a whole picture again), "
            "because that last frame becomes scene N+1's first frame. Scene N+1's video prompt "
            "starts from that picture.",
        ]
    ),
    # For a scene WITH a last frame: only the motion between the two frames.
    video_prompt_rules_with_last_frame="\n".join(
        [
            'Rules for "video_prompt" in a scene WITH a last frame, the motion prompt for LTX. '
            "LTX makes the clip as one continuous shot from the first frame, the last frame and "
            "this prompt:",
            "1. The two frames already show how everything looks. Describe only the MOTION that "
            "carries the first frame to the last frame. Never describe again what the frames "
            "show (faces, clothes, colours, materials, rooms): that pulls the video away from "
            "them.",
            "2. One flowing paragraph in the present tense, 4 to 8 short sentences in all "
            "(action, camera and sound count), at most 200 words. About one action for every "
            "2 to 3 seconds, so a short scene gets a short prompt.",
            "3. The main action first, in one clear sentence. Then the specific movements and "
            "gestures, as literal, chronological verbs (lifts, turns, drifts). Every sentence "
            "has a verb that does something. Show feeling through physical cues, never with a "
            'label such as "sad".',
            "4. Write the pace in. The video model adds no pause you do not ask for, so put "
            'the beats into the action ("it pauses for a beat").',
            "5. The motion ends in the state the last frame shows: say so in plain words taken "
            "from the last frame. Never describe anything that would happen after it.",
            '6. Camera: name one move. The two frames are framed alike, so use "static camera" '
            'or at most "a very slight push-in". Never a pan, a pull-back, a tracking move or '
            "any other change of framing: it makes the whole picture slide between the frames.",
            "7. Light: the light is the same in both frames, so do not describe a change of light.",
            "8. Sound: write it where it happens, inside the sentence of the action it belongs "
            "to, concrete and specific. By default there is no music, no speech and no "
            'singing, and you say so once, briefly, at the very end ("No music, no voices."). '
            "The author's instructions can change this.",
            '9. Never use: double quotes (they make people speak), "cut to" or any scene '
            "change or named transition (hard cut, match cut, dissolve), times or seconds, "
            '"the video starts with", on-screen text.',
            "10. Plain film language and restrained adjectives. No technical specs: no focal "
            "lengths, f-stops, resolutions or camera model names. The frames already set the "
            "look.",
        ]
    ),
    example_with_last_frame=_LTX_FIRST_LAST_EXAMPLE_WITH,
    last_frame_checks=(
        TextRule(
            _NOT_THE_SAME_SHOT,
            "The last frame does not begin with \u201cThe same shot\u201d. It is made by "
            "editing the first frame, so it should say what changes in that same shot.",
        ),
        TextRule(
            _MOTION_UNDER_WAY,
            "The last frame describes a motion under way. A last frame is a still: show where "
            "the motion ends.",
        ),
    ),
    max_last_frame_words=70,
    rules_with_last_frame=(
        TextRule(
            _FRAMING_MOVE,
            "A camera move that changes the framing found (a pan, a pull-back, a zoom). With a "
            "last frame both frames are framed alike: use a static camera.",
        ),
    ),
)

# --- MiniMax H3, from a first frame alone or from a first and a last frame -------------------

# Written from the guide the GPU server gives (`GET /v1/guide`) and MiniMax's own "Video Prompt
# Writing Guide" (github.com/MiniMax-AI/MiniMax-H3, skills/h3-prompt-writing), whose I2VA and
# FL2VA cases are the model for the two examples below. What differs from the LTX profiles:
# - the video prompt is three named fields, not one paragraph. `integrated_multimodal_description`
#   is a timeline of `[Shot N]` blocks; a scene's clip is always ONE shot, because the app makes
#   the cuts between scenes and lets the system divide a script into shots;
# - the line that places the frames on the clip (with the clip's own length) is written by the
#   app (`scene_prompt.py`), never by the model;
# - the style goes at the start of `[Shot 1]`, and the app writes it there when the project has
#   one;
# - the camera is a motion type with an amplitude and a speed, written as an action;
# - there is no speech: the voiceover is the sound of a narrated video, so no `<d>` tags and no
#   score (`non_diegetic_music` is `N/A`);
# - a clip is never shorter than 5.17 s and reaches its last frame at the very end, so a last
#   frame is only for scenes of 5.2 s or more;
# - a first-and-last clip names the pictures "Picture 1" and "Picture 2" without angle brackets
#   (the guide's FL2VA case), a first-frame clip names its picture "<Picture 1>" (I2VA).
_H3_FRAME_LINE: Final = re.compile(
    r"For the target video,|How the reference pictures align", re.IGNORECASE
)
_H3_SPEECH: Final = re.compile(r"</?d>", re.IGNORECASE)
_H3_LATER_SHOT: Final = re.compile(r"\[Shot\s+(?:[2-9]|\d{2,})\]", re.IGNORECASE)
# The joined prompt starts with the field name, then `[Shot 1]`.
_H3_NOT_SHOT_ONE: Final = re.compile(
    r"^integrated_multimodal_description:(?!\s*\[Shot 1\])", re.IGNORECASE
)
_H3_NO_FIRST_PICTURE: Final = re.compile(r"^(?![\s\S]*\bPicture 1\b)", re.IGNORECASE)
_H3_NO_LAST_PICTURE: Final = re.compile(r"^(?![\s\S]*\bPicture 2\b)", re.IGNORECASE)
_H3_OWN_MUSIC: Final = re.compile(r"non_diegetic_music:(?!\s*N/A\b)\s*\S", re.IGNORECASE)

# The two worked scenes are the ones the LTX profile uses, with the same pictures.
_H3_LAST_FRAME_SCENE: Final = json.loads(_LTX_FIRST_LAST_EXAMPLE_WITH)
_H3_EXAMPLE_NONE: Final = json.dumps(
    {
        "scene": _FIRST_FRAME_ONLY["scene"],
        "continuity": _FIRST_FRAME_ONLY["continuity"],
        "first_frame": _FIRST_FRAME_ONLY["first_frame"],
        "last_frame": None,
        "video_prompt": {
            "integrated_multimodal_description": (
                "[Shot 1] Live-action, cinematic, a close-up at water level frames the cream "
                "paper boat with the faded blue stripe shown in <Picture 1> at the rim of the "
                "rain puddle, keeping its look, the wet cobblestones and the flat overcast "
                "light. A gust of wind pushes the boat off the rim and into the water with a "
                "soft splash, and it drifts slowly across the puddle, turning a quarter turn as "
                "ripples spread behind it. It nudges the floating yellow leaf aside, pauses for "
                "a beat, then comes to rest against the far edge, rocking gently as the last "
                "ripples fade. The camera pans right with small amplitude at slow speed, "
                "following the boat until it sits near the centre of the frame."
            ),
            "overall_soundscape": (
                "A faint rain patter on stone and water, with a low gust of wind. The boat "
                "enters the puddle with a soft splash, and water laps gently against the "
                "cobblestones."
            ),
            "non_diegetic_music": "N/A",
        },
    },
    ensure_ascii=False,
)
_H3_EXAMPLE_WITH: Final = json.dumps(
    {
        "scene": _H3_LAST_FRAME_SCENE["scene"],
        "continuity": _H3_LAST_FRAME_SCENE["continuity"],
        "first_frame": _H3_LAST_FRAME_SCENE["first_frame"],
        "last_frame": _H3_LAST_FRAME_SCENE["last_frame"],
        "video_prompt": {
            "integrated_multimodal_description": (
                "[Shot 1] Live-action, cinematic, a close-up at moss level begins in the "
                "position and framing established by Picture 1, with the small brown garden "
                "snail at the left edge of the flat mossy stone, its antennae raised towards the "
                "right. The camera holds a static shot as the snail glides slowly across the "
                "stone, its antennae swaying, and climbs a small ridge. It pauses for a beat, "
                "antennae turning towards the ferns, then moves on until it settles at the "
                "centre of the stone, antennae raised and bent towards the ferns, in the pose, "
                "spacing, and composition established by Picture 2 at the end of the shot."
            ),
            "overall_soundscape": (
                "A faint wet slide of the snail against the moss under a still, damp ambience. "
                "A distant bird calls once."
            ),
            "non_diegetic_music": "N/A",
        },
    },
    ensure_ascii=False,
)

# The rules both kinds of scene share about the two fields that are not the description.
_H3_SOUND_RULES: Final = [
    '"overall_soundscape": 1 to 4 English sentences in one paragraph: the ambience of the '
    "place, the physical sounds of the actions (footsteps, fabric, water, impacts) and "
    "non-verbal sounds (wind, rain, breathing). Concrete sources, no speech, no music. Keep it "
    "natural and quiet: a voiceover is laid over it.",
    '"non_diegetic_music": exactly "N/A". The video has a voiceover and no score of its own. '
    "The author's instructions can change this: then 1 to 3 sentences on instruments, tempo "
    "and volume, never on mood.",
]

_H3_CAMERA_RULE: Final = (
    "the camera is written as an action inside the shot, with a motion type, and an amplitude "
    "and a speed only when they matter. Motion types: static shot, push in, pull out, pan "
    "left, pan right, truck left, truck right, tilt up, tilt down, pedestal up, pedestal "
    "down, arc shot, tracking shot, shake slightly. Amplitude: with small amplitude, with "
    "large amplitude. Speed: at slow speed, at fast speed. For example \u201cThe camera "
    "pushes in with small amplitude at slow speed toward the folded letter.\u201d, never a "
    "list of labels."
)

MINIMAX_H3_SCENE: Final = PromptProfile(
    id="minimax-h3-scene",
    version=1,
    video_model=(
        "MiniMax H3, from a first frame alone or from a first and a last frame "
        "(one continuous shot)"
    ),
    answer_format="h3_fields",
    # For a scene WITHOUT a last frame: the guide's I2VA case.
    video_prompt_rules="\n".join(
        [
            'Rules for "video_prompt" in a scene WITHOUT a last frame, the prompt for MiniMax '
            "H3. H3 was trained on one structured prompt and nothing rewrites yours, so write "
            "it in that structure. The first frame is given to the model as <Picture 1> and "
            'the clip starts on it. "video_prompt" is an object with exactly three text '
            'fields: "integrated_multimodal_description", "overall_soundscape" and '
            '"non_diegetic_music". The app adds the line that places the picture on the '
            "clip, with the clip's own length: never write that line.",
            "",
            '"integrated_multimodal_description": the main body, 80 to 180 words, in the '
            "present tense, one paragraph:",
            '1. One shot. Begin with "[Shot 1]" and never write another shot: no "[Shot 2]", '
            'no "the camera cuts to", no fade or dissolve, no times. The clip of a scene is '
            "one continuous shot, and the app makes the cuts between scenes.",
            '2. Right after "[Shot 1]" come the overall style (for example "Live-action, '
            'cinematic,") and then the opening composition ("a medium-wide shot frames..."). '
            "The user message says whether the app writes the style for you. The examples "
            "below are for a project with no style given, so their [Shot 1] states it.",
            "3. Anchor, then move: first-frame anchor, then the onset of the action, then its "
            "continuous development, then the result. Name the main subject as shown in "
            '<Picture 1> ("the paper boat shown in <Picture 1>") and say in a few words that '
            "its look, colours and place stay as they are. Never describe the picture again "
            "in detail: the model sees it, and a second description pulls the video away from "
            "it. Then say only what happens.",
            "4. Every sentence has a verb that does something, chronological and literal "
            "(lifts, turns, drifts). Show feeling through physical cues, never with a label "
            'such as "sad". Write the pace in: the model adds no pause you do not ask for '
            '("it pauses for a beat"). About one action for every 2 to 3 seconds of the scene.',
            "5. Fit the scene's length (the scene list gives its seconds). A clip is never "
            "shorter than 5.2 seconds, but only as much of it as the scene lasts is shown. "
            "The main action starts within the first second or two and is finished inside "
            "the scene's length, so a short scene gets one simple action. Say where the "
            "action ends, in plain words.",
            f"6. Camera: one move for the shot, {_H3_CAMERA_RULE} For a calm scene, hold a "
            "static shot. Vary the move across the video instead of repeating one.",
            "7. Light: one lighting logic. Say how the light changes only if it does.",
            "8. No speech. Nobody on screen speaks and the narrator is never seen: no <d> "
            "tags, no speaker ids such as (S1), no singing, no voiceover lines. A person who "
            "appears keeps the lips closed. No on-screen text and no double quotes.",
            "9. A sound that belongs to one action may be written in its sentence (\u201cthe "
            "broom scrapes over the stone as it sweeps\u201d). The soundscape sums up the rest.",
            "10. Plain film language and restrained adjectives. No technical specs: no focal "
            "lengths, f-stops, resolutions or camera model names. The first frame already sets "
            "the look.",
            "",
            *[f"- {rule}" for rule in _H3_SOUND_RULES],
        ]
    ),
    example=_H3_EXAMPLE_NONE,
    max_video_words=260,
    rules=(
        TextRule(
            _H3_FRAME_LINE,
            "A line that places the pictures on the clip found. The app writes that line, "
            "with the clip's own length: leave it out.",
        ),
        TextRule(
            _H3_NOT_SHOT_ONE,
            "The description does not begin with \u201c[Shot 1]\u201d.",
        ),
        TextRule(
            _H3_LATER_SHOT,
            "A second shot found. The clip of a scene is one continuous shot: the app makes "
            "the cuts between scenes.",
        ),
        TextRule(
            _NAMED_CUT,
            "A cut found (\u201cthe camera cuts to\u201d). The clip of a scene is one "
            "continuous shot. Use a camera move to change the view.",
        ),
        TextRule(
            _H3_NO_FIRST_PICTURE,
            "The description does not name the first frame (<Picture 1>). It should start "
            "from the picture the clip begins on.",
        ),
        TextRule(
            _H3_SPEECH,
            "Spoken words (<d> tags) found. Nobody on screen speaks: the voiceover is the "
            "narration.",
        ),
        TextRule(
            _DOUBLE_QUOTES,
            "Double quotes found. Nobody speaks here and there is no on-screen text.",
        ),
        TextRule(
            _TIMESTAMP,
            "A time such as \u201c0:03\u201d or \u201c3 seconds\u201d found. A single shot "
            "has no times, and the clip's length is set by the scene.",
        ),
        TextRule(
            _H3_OWN_MUSIC,
            "The music field is not \u201cN/A\u201d. The video has a voiceover and no score "
            "of its own.",
        ),
    ),
    writes_last_frame=True,
    last_frame_rules="\n".join(
        [
            "When to write a last frame",
            "- A last frame is made later by EDITING the first frame's picture, so it can only "
            "show the SAME shot a moment later: the same place, light, framing and camera "
            "position, with the subject changed. Each one costs extra picture-making time, so "
            "write one only where it makes the clip clearly more controlled. Not every scene "
            "needs one.",
            "- MiniMax H3 reaches the last frame at the very end of its clip, and a clip is "
            "never shorter than 5.2 seconds. Write a last frame only for a scene that lasts "
            "5.2 seconds or more (the scene list gives the length): a shorter scene would be "
            "cut off before it reached the last frame.",
            "- Write one when the scene's ending is a visible change of the subject inside the "
            "same shot and where the clip ends matters: a thing opens, fills, lands, lights up "
            "or moves to a new spot; a subject turns or looks somewhere new; a hand reaches "
            "for something and takes it.",
            '- Write one when the next scene is "continues_action" and this scene\'s motion can '
            "end inside the same shot. The app uses this scene's last frame as the next "
            "scene's first frame, so the cut is seamless.",
            "- Write one when a recurring subject must look exactly the same at the end as at "
            "the start through a clear movement (a close-up of a face or of an object that "
            "moves).",
            '- Answer null for "last_frame" when the scene is ambient or atmospheric with no '
            "clear end state (rain, drifting fog, a still landscape, light slowly changing); "
            "when the camera makes a large move (a pan that reveals a new place, a change from "
            "wide to close); when the scene is shorter than 5.2 seconds; or when the end would "
            "show a different place, different light or a different time.",
            "",
            'Rules for "last_frame" (a still picture made by editing the first frame)',
            "- It is the SAME shot as the first frame, one moment after the scene's motion "
            "ends: the same place, light, framing, camera position and lens look. Only the "
            "subject changes (its position, state, pose or gaze), or something small enters or "
            "leaves the frame.",
            '- 30 to 70 words. Begin with "The same shot", say what is different in concrete '
            "terms (positions, states, gaze, objects), and end by saying what is unchanged.",
            "- Name a subject by its world name and keep its identifying details from the "
            "world description. Never give it another look.",
            "- It shows where the video prompt's motion ENDS, as a still: the subject in place, "
            'at rest or in a pause. No motion words ("starts to", "is moving") and no sound.',
            "- Never change the camera: no zoom, no new angle, no wider or tighter view. If "
            'the end needs a different framing, answer null for "last_frame" instead.',
            "- No text, captions, logos or watermarks in the picture.",
            "",
            "Scenes that follow each other",
            '- When scene N has a last frame and scene N+1 is "continues_action", the '
            "first_frame of scene N+1 must describe exactly the picture of scene N's "
            "last_frame (word for word where you can, written as a whole picture again), "
            "because that last frame becomes scene N+1's first frame. Scene N+1's video prompt "
            "starts from that picture.",
        ]
    ),
    # For a scene WITH a last frame: the guide's FL2VA case.
    video_prompt_rules_with_last_frame="\n".join(
        [
            'Rules for "video_prompt" in a scene WITH a last frame, the prompt for MiniMax '
            "H3. The clip starts on the first frame (Picture 1, at 0.00 seconds) and ends on "
            "the last frame (Picture 2, at the very end of the clip). The three fields, the "
            "style and the rules for sound and music are the same as for a scene without a "
            "last frame. Never write the line that places the pictures on the clip: the app "
            "writes it. Only the description differs:",
            "",
            '"integrated_multimodal_description": 70 to 160 words, in the present tense, one '
            "paragraph:",
            '1. One shot. Begin with "[Shot 1]" and never write another shot, a cut or a '
            "fade: one continuous shot lets the model move from one picture to the other "
            "without a break.",
            '2. Right after "[Shot 1]" come the overall style and the opening composition, '
            "as for a scene without a last frame.",
            "3. Describe the PATH between the two pictures, never the two pictures: the state "
            "of the first frame, then the changes you can see on the way, then the "
            "differences narrowing, then the state of the last frame. Say that the subject "
            '"begins in the position and framing established by Picture 1", and end by saying '
            'it "settles into the pose, spacing, and composition established by Picture 2 at '
            'the end of the shot". Write them as plain "Picture 1" and "Picture 2", without '
            "angle brackets. Never describe again what the pictures show.",
            "4. The last frame is reached at the very end of the clip: the motion carries on "
            "steadily until then, and nothing happens after it. Every sentence has a verb "
            "that does something. Write the pace in (\u201cit pauses for a beat\u201d).",
            "5. Camera: the two pictures are framed alike, so use a static shot or at most one "
            "very gentle move (a push in or a pull out with small amplitude at slow speed). "
            "Never a pan, a truck, a tilt, an arc, a tracking shot or a zoom: it makes the "
            "whole picture slide between the pictures. Write it as an action inside the "
            "shot.",
            "6. Light: it is the same in both pictures, so do not describe a change of light.",
            "7. No speech, no <d> tags, no speaker ids, no singing, no on-screen text and no "
            "double quotes. Plain film language, no technical specs.",
        ]
    ),
    example_with_last_frame=_H3_EXAMPLE_WITH,
    last_frame_checks=LTX_FIRST_LAST.last_frame_checks,
    max_last_frame_words=70,
    rules_with_last_frame=(
        TextRule(
            _H3_NO_LAST_PICTURE,
            "The description does not name the last frame (Picture 2). With a last frame it "
            "should end by settling into the pose, spacing and composition of Picture 2.",
        ),
        TextRule(
            _FRAMING_MOVE,
            "A camera move that changes the framing found (a pan, a pull-back, a zoom). With a "
            "last frame both pictures are framed alike: use a static shot.",
        ),
    ),
)

# The profile of the LTX models. `LTX_23_KEYFRAME`, `LTX_23_FIRST_FRAME` and `LTX_FIRST_FRAME`
# stay above, unchanged, because jobs from Phase 12, 15 and 19 name them.
ACTIVE_PROFILE: Final = LTX_FIRST_LAST


def profile_for_model(model: VideoModel) -> PromptProfile:
    """The profile that writes the descriptions of a project made with `model`."""
    return MINIMAX_H3_SCENE if model == H3_MODEL else ACTIVE_PROFILE
