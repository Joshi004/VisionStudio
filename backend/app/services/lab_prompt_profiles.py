"""What depends on the video model when an AI writes a multi-shot prompt for the Video lab
(Phase 19).

LTX-2.5 can cut between two to four shots inside one clip, holding the character, the place,
the light and the voice. There is no parameter for it: the cuts are written into the prompt as
prose, and the model only cuts where a sentence names the cut. The rules below come from the
server's guide (`GET /v1/guide`, "Multi-shot prompts") and Lightricks' own prompting guide,
which agree on every point.

A *lab prompt profile* is the same idea as a prompt profile for scene descriptions
(`description_profiles.py`) and one for image prompts (`image_prompt_profiles.py`): what the
writer is told about the video model, one worked example, and the checks that tell whether a
written prompt breaks the rules. The job stores the profile's id and version next to the exact
request, so an earlier prompt can be compared with a later one. Raise `version` whenever any
text in a profile changes.

Pure data, no I/O.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final

from app.services.description_profiles import TextRule

# A numbered or labelled shot list: "Shot 2:", "1.", "2)" at the start of a line.
_SHOT_LIST = re.compile(r"(?im)^\s*(?:shot\s*\d+\b|\d+\s*[.):])")
# A screenplay slugline: "INT. KITCHEN - DAY".
_SLUGLINE = re.compile(r"\b(?:INT|EXT)\.\s")
# "0:03", "3 seconds", "2.5 sec". Not a bare "s", so "the 1920s" does not match.
_TIMESTAMP = re.compile(
    r"\b\d{1,2}:\d{2}\b|\b\d+(\.\d+)?\s?(sec|secs|second|seconds)\b", re.IGNORECASE
)
_VIDEO_STARTS_WITH = re.compile(r"\bthe video (starts|begins) with\b", re.IGNORECASE)


@dataclass(frozen=True)
class LabPromptProfile:
    id: str
    # Raised by hand whenever any text below changes.
    version: int
    # Named to the writer, so it knows what it is writing for.
    video_model: str
    # How to write the prompt for this model.
    prompt_rules: str
    # One worked request and its answer, from an unrelated video.
    example_inputs: dict[str, object]
    example_answer: str
    # Warnings only, never errors: a prompt outside this range is still saved.
    min_words: int
    max_words: int
    rules: tuple[TextRule, ...]


_EXAMPLE_INPUTS: Final[dict[str, object]] = {
    "idea": "An old fisherman mends his net on the pier at dawn, until something tugs the line.",
    "shots": 3,
    "duration_s": 9,
    "first_frame": None,
}

_EXAMPLE_PROMPT: Final = (
    "A wide shot establishes a grey harbour at dawn, a fisherman in a faded blue wool sweater "
    "sitting on an upturned crate at the end of a wooden pier, mending a green net spread "
    "across his knees while gulls call and water laps against the posts. A hard cut "
    "transitions to a close-up of the fisherman in the faded blue sweater, his weathered "
    "hands pulling a needle through the mesh, his breath misting in the cold air; the lapping "
    "water and the gulls continue across the cut. A moment later a match cut connects to a "
    "low-angle shot of the rope beside him tightening over the edge of the pier as the gulls "
    "fall silent and only a low creak of wood remains, while the fisherman in the faded blue "
    "sweater lifts his head from his net."
)

LTX_25_MULTI_SHOT: Final = LabPromptProfile(
    id="ltx-2.5-multi-shot",
    version=1,
    video_model="LTX-2.5",
    prompt_rules="\n".join(
        [
            "Rules for the prompt. LTX-2.5 can cut between several shots inside one clip, and "
            "it cuts only where the prompt says so, in words:",
            "1. One chronological paragraph in the present tense. No shot list, no numbered "
            'shots, no "Shot 2:" labels, no screenplay sluglines (INT. / EXT.), no bullet '
            "points. The model reads a flowing scene, not a list.",
            "2. Write exactly the number of shots the request asks for, so one cut fewer than "
            "that. Give each shot a clear job (establish, then detail, then reaction; or wide, "
            "then medium, then close-up). Each shot needs about three seconds to register.",
            "3. At every cut, do all four of these in the sentence that starts the new shot:",
            '   a. Name the transition in plain words ("A hard cut transitions to…", "The view '
            'cuts to a close-up of…", "A match cut connects to…", "The image dissolves into…"). '
            "Without those words the model reads a camera move and keeps one shot going.",
            "   b. Re-establish the new shot: its scale, its angle, who or what is in frame, "
            "and the light if it changed. The model does not carry the previous framing over.",
            "   c. Keep identity consistent: give each person, animal or object that returns "
            'the same short visual tag every time ("the fisherman in the faded blue sweater") '
            "and repeat the tag at every cut. Describe each one in full once, in the shot "
            "where it first appears.",
            "   d. Say what the sound does across the cut: whether music, dialogue or ambience "
            'continues, softens or changes ("the piano continues across the cut", "the '
            'dialogue drops and only wind remains").',
            '4. Keep the action chronological: use "initially", "a moment later", '
            '"simultaneously". Do not change place or clothing between cuts unless the cut is '
            "meant to jump in time or place, and then say so.",
            "5. The single-shot rules still apply inside every shot: concrete verbs that do "
            "something (walks, turns, exhales), feeling shown through physical cues (never a "
            'label such as "sad"), concrete camera language, one lighting logic per shot, '
            'plain adjectives ("red dress", not "vibrant crimson dress").',
            "6. Sound: describe it where it happens, inside the action it belongs to, and keep "
            "it specific. Add music, speech or singing only when the idea asks for it.",
            "7. Dialogue: put the exact words in double quotes, with a description of the "
            "voice, only when the idea contains words that must be spoken. The model lip-syncs "
            "every quoted word, so never quote anything else.",
            "8. When the request names a first frame, the first shot continues from that image: "
            "describe only what happens (motion, camera, sound), never again what the image "
            "shows. The cuts come after that opening shot.",
            "9. Never write times, seconds or shot numbers, on-screen text, or technical "
            "specs (focal lengths, resolutions, camera model names). About 40 to 200 words in "
            "all.",
        ]
    ),
    example_inputs=_EXAMPLE_INPUTS,
    example_answer=json.dumps({"prompt": _EXAMPLE_PROMPT}, ensure_ascii=False),
    min_words=40,
    max_words=200,
    rules=(
        TextRule(
            _SHOT_LIST,
            "A numbered or labelled shot list found. LTX-2.5 reads a flowing paragraph: "
            "describe each cut in a sentence.",
        ),
        TextRule(
            _SLUGLINE,
            "A screenplay slugline (INT. / EXT.) found. Describe the place in a sentence.",
        ),
        TextRule(
            _TIMESTAMP,
            "A time such as \u201c0:03\u201d or \u201c3 seconds\u201d found. The clip's length "
            "is set by the form, and the model reads no timings.",
        ),
        TextRule(
            _VIDEO_STARTS_WITH,
            "\u201cthe video starts with\u201d found. Describe the first shot directly.",
        ),
    ),
)

ACTIVE_LAB_PROFILE: Final = LTX_25_MULTI_SHOT
