"""What the AI is told when it writes the prompts of a take in the Talking character lab
(Phase 24): the instruction for the voice model and the prompt for the lip-sync video model.

A *talk prompt profile* is the same idea as the lab prompt profile for the Video lab
(`lab_prompt_profiles.py`): the rules the writer is told, one worked example, and the checks
that tell whether a written prompt breaks the rules. The job stores the profile's id and
version next to the exact request, so an earlier take can be compared with a later one. Raise
`version` whenever any text in a profile changes.

The video model is LTX-2.3's audio-to-video endpoint. Its prompt "describes the visible speaker
and the scene that should match the conditioning audio" (the server's OpenAPI document). The
speech itself is given to the model as audio, so the prompt describes the act of speaking and
never carries the words. (Whether quoting the words would help or hurt the lip-sync is not
known: the lab is the place to find out, by hand, in the video prompt.)

Pure data, no I/O.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final

from app.services.description_profiles import TextRule

# A cut or a transition named in words: the clip is one continuous shot.
_CUT = re.compile(
    r"\b(?:hard|match|jump|smash) cuts?\b"
    r"|\bcuts? (?:away|to|into|back)\b"
    r"|\b(?:dissolves?|fades?|wipes?|transitions?) (?:in)?to\b",
    re.IGNORECASE,
)
# "0:03", "3 seconds", "2.5 sec". Not a bare "s", so "the 1920s" does not match.
_TIMESTAMP = re.compile(
    r"\b\d{1,2}:\d{2}\b|\b\d+(\.\d+)?\s?(sec|secs|second|seconds)\b", re.IGNORECASE
)
# A screenplay slugline: "INT. KITCHEN - DAY".
_SLUGLINE = re.compile(r"\b(?:INT|EXT)\.\s")
# Text laid over the picture: the speech is audio, and nothing is to be written on screen.
_ON_SCREEN_TEXT = re.compile(
    r"\b(?:subtitles?|captions?|on-screen text|text overlay|title card)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class TalkPromptProfile:
    id: str
    # Raised by hand whenever any text below changes.
    version: int
    # How to write the instruction for the voice model (Breeze TTS 2).
    voice_rules: str
    # How to write the prompt for the lip-sync video model (LTX-2.3 audio-to-video).
    video_rules: str
    # One worked request and its answer, from an unrelated video.
    example_inputs: dict[str, object]
    example_answer: str
    # Warnings only, never errors: a video prompt outside this range is still saved.
    video_min_words: int
    video_max_words: int
    rules: tuple[TextRule, ...]


_EXAMPLE_INPUTS: Final[dict[str, object]] = {
    "dialogue": "You shouldn't be up here after dark. The rocks don't forgive mistakes.",
    "character": (
        "A lighthouse keeper in his sixties with a grey beard, a navy wool cap and a thick "
        "cable-knit sweater, standing in a small whitewashed lantern room at dusk."
    ),
    "delivery": "Gruff but quietly worried, speaking slowly.",
    "voice_kind": "design",
}

_EXAMPLE_VOICE: Final = (
    "An older man's voice, low and gravelly with a slight rasp and a coastal accent. He speaks "
    "slowly and gruffly, with a quiet undertone of worry, pausing briefly between the two "
    "sentences."
)

_EXAMPLE_VIDEO: Final = (
    "A lighthouse keeper in his sixties, with a grey beard, a navy wool cap and a thick "
    "cable-knit sweater, stands in a small whitewashed lantern room at dusk and speaks "
    "directly to the camera. His lips and jaw move naturally in time with each word, his brow "
    "draws together in quiet concern, and he gives a slow, small shake of the head between "
    "the sentences. Warm lamplight falls on one side of his face while the last blue light "
    "fades in the window behind him. The camera holds steady at chest height in one "
    "continuous shot, with a barely perceptible slow push-in."
)

TALK_PROFILE: Final = TalkPromptProfile(
    id="ltx-2.3-audio-to-video",
    version=1,
    voice_rules="\n".join(
        [
            "Rules for `voice_instruction`, the instruction for the speech model. It reads "
            "the spoken line aloud, and your words steer how it sounds:",
            "1. One or two plain sentences in English, at most 400 characters. No lists.",
            "2. Describe sound only: pitch, timbre, age impression, accent, pace, volume, "
            "emotion and where it pauses. Never describe the character's looks, the setting "
            "or what the face does.",
            "3. Use the delivery note when there is one. When there is none, choose a "
            "delivery that fits the line and the character.",
            "4. Never repeat or quote the spoken line in it.",
            "5. When the request says the voice is made from your description, describe the "
            "voice itself first (who it sounds like), then how the line is delivered. When "
            "it says a saved voice reads the line, describe only how the line is delivered "
            "(tone, emotion, pace): the voice itself is already chosen.",
            "6. When the request says no voice instruction is used, answer with an empty "
            'string ("") for `voice_instruction`.',
        ]
    ),
    video_rules="\n".join(
        [
            "Rules for `video_prompt`, the prompt for the video model. The video model is "
            "given the character's picture as the first frame and the recorded speech as "
            "audio, and it makes a clip in which the character speaks that speech. You write "
            "what is seen:",
            "1. One paragraph in the present tense, about 60 to 120 words. No lists, no "
            "headings, no labels, no screenplay sluglines (INT. / EXT.).",
            "2. Start with who is speaking: the character as described in the request, with "
            "the same short description of the face, hair and clothes, so the clip matches "
            "the picture. Never invent a different look. When the character is not "
            "described, describe a plain, neutral speaker.",
            "3. Describe the act of speaking: the lips and jaw moving naturally in time with "
            "the words, the expression that fits the delivery, and one or two small natural "
            "movements (a blink, a slight head tilt, a small hand gesture, a breath). Keep "
            "them small: big movements spoil the lip-sync.",
            "4. Say where the speaker looks (into the camera, or off to one side).",
            "5. One continuous shot with a simple camera: held steady, or a very slow push-in. "
            "No cuts, no transitions, no camera tricks.",
            "6. One lighting logic, in plain words, and the place the character stands in.",
            "7. Never put the spoken line, or any words, in the prompt: the speech is given "
            "as audio. Never use double quotes. Never describe music, voices or sound "
            "effects, and never write subtitles or on-screen text.",
            "8. Never write times, seconds or shot numbers, or technical specs (focal "
            "lengths, resolutions, camera model names).",
        ]
    ),
    example_inputs=_EXAMPLE_INPUTS,
    example_answer=json.dumps(
        {"voice_instruction": _EXAMPLE_VOICE, "video_prompt": _EXAMPLE_VIDEO},
        ensure_ascii=False,
    ),
    video_min_words=40,
    video_max_words=140,
    rules=(
        TextRule(
            _CUT,
            "A cut or a transition found. A lip-sync clip is one continuous shot: describe "
            "the speaker and a steady camera.",
        ),
        TextRule(
            _TIMESTAMP,
            "A time such as \u201c0:03\u201d or \u201c3 seconds\u201d found. The clip is as "
            "long as the speech, and the model reads no timings.",
        ),
        TextRule(
            _SLUGLINE,
            "A screenplay slugline (INT. / EXT.) found. Describe the place in a sentence.",
        ),
        TextRule(
            _ON_SCREEN_TEXT,
            "Subtitles or on-screen text found. The speech is audio: nothing is written on "
            "the picture.",
        ),
    ),
)

ACTIVE_TALK_PROFILE: Final = TALK_PROFILE
