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

MiniMax H3 is the other model the lab can write for (`H3_GENERATE`). It is written differently:
it was trained on a structured prompt (`[Shot N]` blocks with cut times, then a soundscape and a
score) that nothing on the server rewrites, so the writer answers with the three fields as JSON
strings (`answer_format="h3_fields"`) and `lab_prompt_writer.py` assembles them. The rules are the
short version in the GPU server's guide (`GET /v1/guide`, "MiniMax H3", "Writing the prompt"). The
first line that places a first or a last frame is not written here: it depends on the frame count,
so the code adds it when the clip is run (`video_generator.h3_prompt_prefix`).

Pure data, no I/O.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final, Literal

from app.services.description_profiles import TextRule
from app.services.video_models import H3_MODEL

# A numbered or labelled shot list: "Shot 2:", "1.", "2)" at the start of a line.
_SHOT_LIST = re.compile(r"(?im)^\s*(?:shot\s*\d+\b|\d+\s*[.):])")
# A screenplay slugline: "INT. KITCHEN - DAY".
_SLUGLINE = re.compile(r"\b(?:INT|EXT)\.\s")
# "0:03", "3 seconds", "2.5 sec". Not a bare "s", so "the 1920s" does not match.
_TIMESTAMP = re.compile(
    r"\b\d{1,2}:\d{2}\b|\b\d+(\.\d+)?\s?(sec|secs|second|seconds)\b", re.IGNORECASE
)
_VIDEO_STARTS_WITH = re.compile(r"\bthe video (starts|begins) with\b", re.IGNORECASE)
# Words that are spoken: in double quotes for LTX, inside <d>...</d> tags for MiniMax H3.
DOUBLE_QUOTES = re.compile(r"[\"\u201c\u201d\u201e]")
_H3_DIALOGUE = re.compile(r"<d>")
# `<d>` without the language tag that H3 needs: <d>[English] ...</d>.
_H3_UNTAGGED_SPEECH = re.compile(r"<d>(?!\[)")
# The line the code adds in front of a prompt that has frames. Written by the model it would be
# there twice, with the wrong times.
_H3_FRAME_LINE = re.compile(
    r"For the target video, at 0\.00 seconds|How the reference pictures align", re.IGNORECASE
)
# "[Shot 2]" (or a later shot) that is not followed by its cut time: "At 00:03.000".
_H3_SHOT_WITHOUT_TIME = re.compile(
    r"\[Shot\s+(?:[2-9]|\d{2,})\](?!\s+At\s+\d{2}:\d{2}\.\d{3})", re.IGNORECASE
)

# `prose`: the answer is `{"prompt": "..."}`, one paragraph. `h3_fields`: the answer is the three
# fields of a MiniMax H3 prompt, which the code joins.
AnswerFormat = Literal["prose", "h3_fields"]


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
    # What the writer is told the answer looks like (the last line of its instructions).
    answer_instruction: str = (
        'Answer with one JSON object only, in exactly this form: {"prompt": "..."}'
    )
    answer_format: AnswerFormat = "prose"
    # How many shots the request may ask for.
    min_shots: int = 2
    max_shots: int = 4
    # Spoken words in a prompt: only expected when the idea has some.
    dialogue_pattern: re.Pattern[str] = DOUBLE_QUOTES
    dialogue_warning: str = (
        "Double quotes found, but the idea has no dialogue. The model lip-syncs and speaks "
        "every quoted word."
    )


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

_H3_EXAMPLE_DESCRIPTION: Final = (
    "[Shot 1] Live-action, cinematic, a wide shot frames a grey harbour at dawn, a fisherman in "
    "a faded blue wool sweater sitting on an upturned crate at the end of a wooden pier, mending "
    "a green net spread across his knees. The camera pushes in with small amplitude at slow speed "
    "as gulls call over the water. "
    "[Shot 2] At 00:03.000, a close-up of the fisherman in the faded blue sweater, his weathered "
    "hands pulling a needle through the mesh, his breath misting in the cold air. The camera "
    "holds a static shot. "
    "[Shot 3] At 00:06.000, a low-angle shot of the rope beside him tightening over the edge of "
    "the pier. The camera tilts up slowly as the fisherman in the faded blue sweater lifts his "
    "head from his net."
)

H3_GENERATE: Final = LabPromptProfile(
    id="minimax-h3-generate",
    version=1,
    video_model="MiniMax H3",
    prompt_rules="\n".join(
        [
            "Rules for the prompt. MiniMax H3 was trained on a structured prompt and nothing "
            "rewrites yours, so you write that structure yourself. Everything is English, except "
            "the words people speak.",
            "1. The prompt has three fields, which are put together for you. Give each as its own "
            "JSON string, without the field's name inside it:",
            "   a. integrated_multimodal_description: the whole picture and action, as [Shot N] "
            "blocks (rule 3).",
            "   b. overall_soundscape: 1 to 4 sentences of ambience, physical sounds and "
            "non-verbal human sounds. No dialogue, and no music.",
            "   c. non_diegetic_music: 1 to 3 sentences about the instrumentation, tempo and "
            "dynamics of a score the characters cannot hear. Write exactly N/A when the idea "
            "asks for no music.",
            "2. Never write the line that places a first or a last frame on the clip's timeline "
            '("For the target video, at 0.00 seconds…" or "How the reference pictures align…"): '
            "it depends on the exact frame count, so the app adds it when the clip is run.",
            "3. Shots: write exactly the number of shots the request asks for, from [Shot 1]. "
            "[Shot 1] has no time. Every later shot starts with its cut time, as "
            '"[Shot 2] At 00:03.000, …" (MM:SS.mmm), with strictly increasing times that fall '
            "inside the clip's length, spaced about evenly. At the start of [Shot 1] name the "
            "overall style (live-action, cinematic, 2D-animated, …) and the opening composition. "
            "Give each person, animal or object that returns the same short visual tag at every "
            "shot, and describe it in full once, where it first appears.",
            "4. Camera: natural English with a motion type, and an amplitude and a speed when "
            'they matter ("The camera pushes in with small amplitude at slow speed toward the '
            'folded letter."). Motion types: zoom in/out, push in/pull out, pan left/right, '
            "truck left/right, tilt up/down, pedestal up/down, arc shot, tracking shot, static "
            "shot, shake slightly/strongly, POV, roll clockwise/counterclockwise.",
            "5. Concrete verbs in the present tense. Show feeling through physical cues, never a "
            'label such as "sad". One lighting logic per shot.',
            "6. Speech: only when the idea contains words that must be spoken. Give each voice a "
            "stable id, (S1), (S2), and describe it once (age, pitch, pace, accent). Put the "
            "words inside <d>[Language] …</d>, verbatim and in their own language, for example "
            "the young woman with a quiet, breathy voice (S1) says: <d>[English] I get off at the "
            "next station.</d>. For a voice-over write that the voice speaks in an off-screen "
            "voiceover and that the on-screen lips stay closed. Keep the amount of speech in "
            "proportion to the clip's length, and never invent words the idea does not give.",
            "7. When the request names a first frame, the clip starts on that image, which the "
            "model knows as <Picture 1>. In [Shot 1] refer to it as <Picture 1> (for example "
            '"the young woman shown in <Picture 1>"), say that her appearance, clothing and '
            "place are preserved, and describe only what happens: motion, camera and sound. "
            "When there is no first frame, describe the opening in full.",
            "8. Sound effects and ambience belong in overall_soundscape, not in the shots. The "
            "shots hold what is seen and said.",
        ]
    ),
    example_inputs=_EXAMPLE_INPUTS,
    example_answer=json.dumps(
        {
            "integrated_multimodal_description": _H3_EXAMPLE_DESCRIPTION,
            "overall_soundscape": (
                "Water laps against the wooden posts and gulls call over the harbour. The needle "
                "rasps through the mesh, and a low creak of wood rises as the rope tightens, "
                "while the gulls fall silent."
            ),
            "non_diegetic_music": "N/A",
        },
        ensure_ascii=False,
    ),
    # Wide on purpose: the guide gives no word count for text and frames, so these only catch a
    # prompt that is clearly too thin or runs away.
    min_words=40,
    max_words=500,
    rules=(
        TextRule(
            _H3_FRAME_LINE,
            "The line that places the frames was written into the prompt. Remove it: the app "
            "adds it, with the clip's exact length, when the clip is run.",
        ),
        TextRule(
            _H3_UNTAGGED_SPEECH,
            "Spoken words need a language tag: <d>[English] …</d>.",
        ),
        TextRule(
            _H3_SHOT_WITHOUT_TIME,
            "A shot after the first has no cut time. Start it as “[Shot 2] At 00:03.000, …”.",
        ),
    ),
    answer_instruction=(
        "Answer with one JSON object only, in exactly this form: "
        '{"integrated_multimodal_description": "...", "overall_soundscape": "...", '
        '"non_diegetic_music": "..."}'
    ),
    answer_format="h3_fields",
    min_shots=1,
    max_shots=4,
    dialogue_pattern=_H3_DIALOGUE,
    dialogue_warning=(
        "Spoken words (<d>…</d>) found, but the idea has no dialogue. MiniMax H3 speaks every "
        "word inside <d> tags."
    ),
)

ACTIVE_LAB_PROFILE: Final = LTX_25_MULTI_SHOT


def profile_for(target_model: object) -> LabPromptProfile:
    """The profile of the model the prompt is written for: `H3_GENERATE` for MiniMax H3, else the
    LTX-2.5 one (also what an older job, which names no model, was written with).
    """
    return H3_GENERATE if target_model == H3_MODEL else ACTIVE_LAB_PROFILE
