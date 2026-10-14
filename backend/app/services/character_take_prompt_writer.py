"""Writing a take's prompts with a language model: up to four texts, depending on what the
take makes, whether it has dialogue and which video model makes the clip (Phase 25). Pure
functions, no I/O.

- `image_prompt`: for an image take, or a video take's first frame. The picture is made by
  editing the character's own reference pictures (already on a plain white backdrop), the same
  discipline as a project scene made from its cast's references
  (`image_prompt_profiles.QWEN_IMAGE_21_CHARACTER_EDIT`), adapted to one character and no scene
  cast or place.
- `last_frame_prompt`: for a MiniMax H3 video take that makes a last frame. The picture is made
  by editing the first frame (the same way a project scene's last frame is,
  `last_frame_prompt_writer`), so this is an edit instruction, not a description.
- `video_prompt`: for a video take, what the clip shows over its length: the motion, the camera,
  and the character speaking (when there is dialogue) or not. For LTX it is one short paragraph.
  For MiniMax H3 it is the structured prompt that model was trained on (see below).
- `delivery_instruction`: for an audio take, or a video take with dialogue: how the character's
  saved voice reads the line aloud (Breeze TTS "direction" mode).

`needed_keys` says exactly which of these a take's remaining steps still need (an image take
needs only `image_prompt`; a silent LTX video needs `image_prompt` and `video_prompt`; a video
with dialogue needs `delivery_instruction` as well; a picture or a speech the author picked
instead of having it made needs no text). The job (`jobs/write_character_take_prompt.py`) asks
the model for exactly that set, and nothing is wasted writing a text no step will use.

**MiniMax H3.** The model was trained on a structured prompt and nothing on the GPU server
rewrites it, so the text sent must already have that structure. The structures are MiniMax's
own (`VIDEO_PROMPT_WRITING_GUIDE_base_en.md` and `..._ref_en.md` in the model's repository, and
its `h3-prompt-writing` skill, read on 2026-10-14). The language model gives the *pieces* (one JSON
string each) and the code writes the fixed parts around them, so a label or a marker can never
come out wrong:

- `target == "h3_reference"` (a take with dialogue: MiniMax's audio-to-video endpoint, with the
  first frame as `<Picture 1>`, an optional last frame as `<Picture 2>`, optional pictures of the
  character after them, and the speech as `<Audio 1>`): the six-part reference format,
  `assemble_h3_reference_prompt`. How `<Audio 1>` is used is the author's `marker`.
- `target == "h3_generate"` (a silent take: MiniMax's plain endpoint, which takes the frames
  itself): the three-field base format, `lab_prompt_writer.assemble_h3_prompt`. The line that
  places the frames on the timeline is added when the clip is run, like in the Video lab.

The call is made by `providers/llm.py` through `jobs/llm_call.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.providers import llm, speech_synthesizer
from app.services import lab_prompt_writer

# Hidden reasoning is billed as output. Three short texts are at most a few hundred tokens, so
# this leaves room to think. A MiniMax H3 prompt is a few thousand characters, so it gets more.
MAX_TOKENS: Final = 8000
H3_MAX_TOKENS: Final = 14000
REASONING_EFFORT: Final = "high"
FIELD_MAX_CHARS: Final = 4000
# A MiniMax H3 prompt holds six sections of 350 to 500 words in all. It has to fit the Video
# lab's prompt limit (`video_lab.MAX_PROMPT_CHARS`), which is what the clip is checked against.
H3_PROMPT_MAX_CHARS: Final = 8000

IMAGE_PROMPT: Final = "image_prompt"
LAST_FRAME_PROMPT: Final = "last_frame_prompt"
VIDEO_PROMPT: Final = "video_prompt"
DELIVERY_INSTRUCTION: Final = "delivery_instruction"
_KEYS: Final = (IMAGE_PROMPT, LAST_FRAME_PROMPT, VIDEO_PROMPT, DELIVERY_INSTRUCTION)

Output = Literal["image", "audio", "video"]
# What the take's video is written for. "ltx" is also what a job saved before MiniMax H3 was
# offered here (it has no target) was written for.
Target = Literal["ltx", "h3_reference", "h3_generate"]
TARGETS: Final[tuple[Target, ...]] = ("ltx", "h3_reference", "h3_generate")
# MiniMax's own words for how a reference audio is used (the reference guide, 4.2).
AudioMarker = Literal["fully_copy", "partially_copy", "reference", "weak_reference"]
AUDIO_MARKERS: Final[tuple[AudioMarker, ...]] = (
    "fully_copy",
    "partially_copy",
    "reference",
    "weak_reference",
)
COPY_MARKERS: Final[frozenset[str]] = frozenset({"fully_copy", "partially_copy"})
DEFAULT_MARKER: Final[AudioMarker] = "reference"

IMAGE_MIN_WORDS: Final = 60
IMAGE_MAX_WORDS: Final = 200
LAST_FRAME_MIN_WORDS: Final = 40
LAST_FRAME_MAX_WORDS: Final = 120
VIDEO_MIN_WORDS: Final = 30
VIDEO_MAX_WORDS: Final = 120
# The reference guide: "350-500 English words" for a generation task, counted over the style
# opening and the shots together.
H3_REFERENCE_MIN_WORDS: Final = 350
H3_REFERENCE_MAX_WORDS: Final = 500
# The base guide gives no count for text and frames; its examples are 100 to 130 words. This is
# a choice, not MiniMax's number: the prompt asks for 120 to 250 words, and only a text clearly
# outside 80 to 400 earns a warning.
H3_GENERATE_ASKED_WORDS: Final = (120, 250)
H3_GENERATE_MIN_WORDS: Final = 80
H3_GENERATE_MAX_WORDS: Final = 400
DELIVERY_MAX_CHARS: Final = speech_synthesizer.INSTRUCTION_MAX_CHARS

ACTION_MAX_CHARS: Final = 1000
DIALOGUE_MAX_CHARS: Final = speech_synthesizer.TEXT_MAX_CHARS

# The pieces the language model gives for the reference format. `picture_2` only with a last
# frame, and `soundscape` not when the whole speech is copied (then the code writes it).
STYLE: Final = "style"
SUBJECT: Final = "subject"
PICTURE_1: Final = "picture_1"
PICTURE_2: Final = "picture_2"
SUMMARY: Final = "summary"
SHOT: Final = "shot"
SOUNDSCAPE: Final = "soundscape"
MUSIC: Final = "music"
NO_MUSIC: Final = "N/A"

_DOUBLE_QUOTES = re.compile(r"[\"\u201c\u201d\u201e]")
_NEGATIVE_WORDS = re.compile(r"\b(no|not|without|never|nothing)\b", re.IGNORECASE)
_SPOKEN = re.compile(r"<d>\s*\[[^\]\n]+\]\s*(.*?)\s*</d>", re.DOTALL)
_ANY_SPOKEN = re.compile(r"<d>", re.IGNORECASE)
_PICTURE_LABEL = re.compile(r"<Picture\s+(\d+)>")
_OTHER_LABEL = re.compile(r"<(?:Video\s+\d+|Subject\s+(?:[2-9]|\d{2,})|Audio\s+(?:[2-9]|\d{2,}))>")
_ALIGNMENT_LINE = re.compile(
    r"^\s*(?:For the target video,|How the reference pictures align)", re.IGNORECASE
)
_BEGINS_FROM = re.compile(r"\b(?:begins?|starts?|opens?)\s+(?:from|on|with)\b", re.IGNORECASE)
_ENDS_ON = re.compile(r"\b(?:ends?|settles?|lands?|finish(?:es)?|conclud(?:es)?)\b", re.IGNORECASE)


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _target(inputs: dict[str, Any]) -> Target:
    target = inputs.get("target")
    return target if target in ("h3_reference", "h3_generate") else "ltx"


def _marker(inputs: dict[str, Any]) -> AudioMarker:
    marker = inputs.get("marker")
    return marker if marker in AUDIO_MARKERS else DEFAULT_MARKER


def needed_keys(
    output: Output,
    dialogue: str | None,
    *,
    first_frame_given: bool = False,
    audio_given: bool = False,
    last_frame: bool = False,
) -> frozenset[str]:
    """Which of the texts a take's remaining steps need, from what it makes and whether it has
    dialogue. Every video needs its own first-frame picture, so `image_prompt` is one of them
    for both "image" and "video", unless the author picked the first frame (`first_frame_given`).
    A speech the author picked (`audio_given`) needs no delivery instruction. `last_frame` is
    True when the take makes its last frame (a picked one needs no text).
    """
    has_dialogue = dialogue is not None and dialogue.strip() != ""
    if output == "image":
        return frozenset({IMAGE_PROMPT})
    if output == "audio":
        return frozenset({DELIVERY_INSTRUCTION})
    keys = {VIDEO_PROMPT}
    if not first_frame_given:
        keys.add(IMAGE_PROMPT)
    if last_frame:
        keys.add(LAST_FRAME_PROMPT)
    if has_dialogue and not audio_given:
        keys.add(DELIVERY_INSTRUCTION)
    return frozenset(keys)


def prompt_inputs(
    *,
    card: str,
    action: str | None,
    dialogue: str | None,
    needed: frozenset[str],
    target: Target = "ltx",
    marker: str | None = None,
    has_last_frame: bool = False,
    identity_pictures: int = 0,
    first_frame_note: str | None = None,
    last_frame_note: str | None = None,
) -> dict[str, Any]:
    """What the model is told, as one plain dict (the user message is rendered from it).

    The rest is for MiniMax H3 only. `marker` is how `<Audio 1>` is used. `has_last_frame` is
    whether the clip has a last frame at all, made or picked. `identity_pictures` is how many
    pictures of the character follow the frames as extra references. A picked picture the model
    cannot see is told to it as the prompt it was made from (`first_frame_note`,
    `last_frame_note`), when there is one.
    """
    return {
        "card": card,
        "action": _one_line(action or "") or None,
        "dialogue": _one_line(dialogue or "") or None,
        "needed": sorted(needed),
        "target": target,
        "marker": marker,
        "has_last_frame": has_last_frame,
        "identity_pictures": identity_pictures,
        "first_frame_note": _one_line(first_frame_note or "") or None,
        "last_frame_note": _one_line(last_frame_note or "") or None,
    }


def _picture_line(label: str, role: str, written: bool, note: str | None, prompt_key: str) -> str:
    if written:
        return f"{label}, {role}, is made from the {prompt_key} you write."
    if note:
        return (
            f"{label}, {role}, is a picture the author chose. It was made from this prompt: {note}"
        )
    return (
        f"{label}, {role}, is a picture the author chose. What it shows is not known to you: "
        'take it from "What happens" and the character card, and keep it general.'
    )


def _render_h3_inputs(inputs: dict[str, Any]) -> list[str]:
    needed = frozenset(inputs["needed"])
    reference = _target(inputs) == "h3_reference"
    lines = [
        "",
        "Video model: MiniMax H3"
        + (", reference mode (it is given the speech as <Audio 1>)." if reference else "."),
        _picture_line(
            "<Picture 1>",
            "the clip's first frame",
            IMAGE_PROMPT in needed,
            inputs.get("first_frame_note"),
            "image_prompt",
        ),
    ]
    if inputs.get("has_last_frame"):
        lines.append(
            _picture_line(
                "<Picture 2>",
                "the clip's last frame",
                LAST_FRAME_PROMPT in needed,
                inputs.get("last_frame_note"),
                "last_frame_prompt",
            )
        )
    else:
        lines.append("The clip has no last frame: it is free to end anywhere.")
    if reference:
        count = int(inputs.get("identity_pictures") or 0)
        first_extra = 3 if inputs.get("has_last_frame") else 2
        if count > 0:
            names = ", ".join(f"<Picture {first_extra + i}>" for i in range(count))
            lines.append(
                f"{names}: {count} more picture{'s' if count > 1 else ''} of the character "
                "(its look), sent as extra references."
            )
        marker = _marker(inputs)
        lines.append(f"<Audio 1> is the character's speech, used with the marker: {marker}.")
        lines.append(
            f"Words inside <d>, verbatim: {inputs['dialogue']}"
            if inputs.get("dialogue")
            else "Words inside <d>: none."
        )
    return lines


def _render_inputs(inputs: dict[str, Any]) -> str:
    action = inputs.get("action")
    dialogue = inputs.get("dialogue")
    target = _target(inputs)
    # A MiniMax H3 video prompt is not written as one text: the model gives its pieces.
    texts = [key for key in inputs["needed"] if not (target != "ltx" and key == VIDEO_PROMPT)]
    if target != "ltx":
        texts.append("the pieces of the video prompt")
    write = ", ".join(texts)
    lines = [
        f"Character card:\n{inputs['card']}",
        f"What happens: {action}" if action else "What happens: nothing in particular.",
        f"The character says: {dialogue}" if dialogue else "The character says nothing.",
        f"Write: {write}.",
    ]
    if target != "ltx":
        lines += _render_h3_inputs(inputs)
    return "\n".join(lines)


_TASK_TEXT: Final[dict[str, str]] = {
    IMAGE_PROMPT: (
        'Rules for "image_prompt": the picture is made by editing one or two reference '
        "pictures of this one character, already standing on a plain white studio backdrop. "
        "Never describe the character's face, hair, build, skin or clothes: the reference "
        "pictures show them, and any words about them can change them. Say only what the "
        "character does in this new picture (its pose and its expression), where it is and "
        "what is around it, where things sit in the frame, the shot size and the angle, the "
        "lens look, the light, the colour palette and the style. If there is no setting, "
        "place the character against a plain, softly lit backdrop that suits the action. One "
        "paragraph of plain English prose, present tense, "
        f"{IMAGE_MIN_WORDS} to {IMAGE_MAX_WORDS} words. Nothing is written in the picture: no "
        "text, signs, labels or logos. The model has no negative prompt: say what fills the "
        "space instead of saying what is absent."
    ),
    LAST_FRAME_PROMPT: (
        'Rules for "last_frame_prompt": the instruction for an image-editing model. It is '
        'given the clip\'s first frame (the picture "image_prompt" makes, or the one the author '
        "chose) and your instruction, and it returns the clip's last frame: the same shot a "
        "moment later, when the action has ended. It SEES the picture, so never describe the "
        "whole scene again: say what changes. "
        f"{LAST_FRAME_MIN_WORDS} to {LAST_FRAME_MAX_WORDS} words of plain instruction "
        "sentences in English. Open with the changes, concretely: the character's pose and "
        "expression at the end, where it looks, what its hands hold or do, what has moved. Take "
        'the end state from what you give for "picture_2" and keep to it. End with one '
        "sentence that keeps everything else, naming it: the camera position, the framing, "
        "the lens look, the light, the colour palette, the background, and the character's face, "
        "hair and clothes, exactly as they are. Only changes that fit one continuous shot: no "
        "new place, no change of angle, zoom or framing, no jump in time, one still moment and "
        "not a process. Say what is there, not what is not: the model has no negative prompt. "
        "Nothing is written in the picture: no text, signs or logos."
    ),
    VIDEO_PROMPT: (
        'Rules for "video_prompt": the clip starts from the picture `image_prompt` makes, and '
        "this describes what happens over the next few seconds: the motion, the camera "
        "(steady, a slow push, a pan), and the character's expression. When the character "
        "speaks a line, say that it speaks the line, naturally and clearly, without quoting "
        "the words (the clip's sound comes from a separate speech, not from this text). When "
        "it does not speak, describe only its motion and expression: never imply speech. One "
        f"paragraph of plain English prose, present tense, {VIDEO_MIN_WORDS} to "
        f"{VIDEO_MAX_WORDS} words."
    ),
    DELIVERY_INSTRUCTION: (
        'Rules for "delivery_instruction": how the character\'s own voice reads its line '
        "aloud, for a speech model that is steered by a short instruction (not the words "
        "themselves). Describe the tone, the emotion and the pace the personality and what is "
        "happening call for, in one or two short sentences, plain prose, up to "
        f"{DELIVERY_MAX_CHARS} characters."
    ),
}

# --- The MiniMax H3 rules ------------------------------------------------------------------

# What the shot says about <Audio 1>, for each marker (the reference guide, 4.2 and 5.4: the
# copy markers keep the exact words and timing, the reference markers take only the voice and
# never the words of the reference).
_MARKER_RULES: Final[dict[str, str]] = {
    "fully_copy": (
        "<Audio 1> is copied whole and is the clip's complete final soundtrack. In the shot "
        'say that the line is the speech copied from <Audio 1> ("the line copied from '
        '<Audio 1>"), that the lips follow its words, timing and pauses exactly, and that '
        "nothing else is heard."
    ),
    "partially_copy": (
        "The speech of <Audio 1> is copied (its words, its timing and its pauses) and other "
        "sound is added around it. In the shot say that the line is the speech copied from "
        '<Audio 1> ("the line copied from <Audio 1>") and that the lips follow it exactly. '
        'Ambience and action sounds go in "soundscape".'
    ),
    "reference": (
        "<Audio 1> is a reference for the voice only and is not copied. In the shot say that "
        "the character speaks in the voice timbre and measured delivery referenced from "
        '<Audio 1> (for example "using the clear, youthful voice timbre referenced from '
        "<Audio 1>\"), and give the line as the character's own words. Never write any words "
        "of the reference audio itself."
    ),
    "weak_reference": (
        "<Audio 1> is only a broad hint. In the shot say that the voice loosely follows "
        "<Audio 1> in gender, age and energy, and give the line as the character's own words."
    ),
}

_CAMERA_VOCABULARY = (
    "Motion types: zoom in, zoom out, push in, pull out, pan left, pan right, truck left, "
    "truck right, tilt up, tilt down, pedestal up, pedestal down, arc shot, tracking shot, "
    "static shot, shake slightly, POV."
)


def _label_list(labels: list[str]) -> str:
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def _h3_reference_rules(inputs: dict[str, Any]) -> str:
    marker = _marker(inputs)
    has_last = bool(inputs.get("has_last_frame"))
    identity = int(inputs.get("identity_pictures") or 0)
    copy_all = marker == "fully_copy"
    labels = "<Subject 1> (the character), <Picture 1> (the first frame)"
    if has_last:
        labels += ", <Picture 2> (the last frame)"
    if identity:
        first = 3 if has_last else 2
        last = first + identity - 1
        labels += f", <Picture {first}> to <Picture {last}> (looks of the character)"
    labels += " and <Audio 1> (the speech)"

    fields = [
        '   - "style": one or two sentences before the shot: the visual style, the light and '
        "the colour palette, read from the first frame (for example: The target video is in a "
        "warm, live-action, cinematic style with soft window light and a slightly desaturated "
        "palette).",
        '   - "subject": a noun phrase that completes "<Subject 1> is …": who the character is '
        "and what a viewer sees in <Picture 1>: age and gender, hair, face, build, clothes and "
        "anything worn or carried, taken from the character card. No label and no name in it.",
        '   - "picture_1": a phrase that completes "<Picture 1> is the first frame of '
        '[Shot 1], showing …": the shot size, the pose and expression, the place and its key '
        "objects, and where the light comes from.",
    ]
    if has_last:
        fields.append(
            '   - "picture_2": a phrase that completes "<Picture 2> is the last frame of '
            '[Shot 1], showing …", in the same terms, for the end of the action: what has '
            "changed (pose, expression, where the character looks, what its hands hold)."
        )
    fields.append(
        '   - "summary": one sentence on the target video: who does what, and that the '
        f"character speaks. Use only these labels where they apply: {labels}. No task tag and "
        "no other label: the app adds the tag."
    )
    fields.append('   - "shot": the whole shot (rule 3).')
    if copy_all:
        fields.append(
            '   - "soundscape": leave out. The speech is the whole soundtrack, so the app '
            "writes this section."
        )
    else:
        fields.append(
            '   - "soundscape": 1 to 4 sentences of ambience, physical sounds and non-verbal '
            "human sounds (breath, cloth, footsteps, a chair). No speech and no music: speech "
            "belongs to the shot."
        )
    fields.append(
        '   - "music": 1 to 3 sentences on the instrumentation, tempo and dynamics of a score '
        "the character cannot hear, or exactly N/A. Write N/A unless the action needs a score."
        if not copy_all
        else '   - "music": leave out. The app writes N/A.'
    )

    shot = [
        '3. The shot. "style" and "shot" together are 350 to 500 words of plain, present-tense '
        "English prose, and a short line of speech does not make the shot shorter: spread the "
        'detail over the clip. Build "shot" in this order:',
        '   a. Open with "The shot begins from <Picture 1>:" and restate what the picture '
        "shows: the composition, where the character sits in the frame, the place, the light, "
        "and that the character's face, hair and clothes stay exactly as in the picture.",
        "   b. Then the action, in order, with concrete verbs and physical cues: what the body "
        "does first and what changes after (head, eyes, shoulders, hands, breath). Show "
        'feeling through those cues, never through a label such as "sad".',
    ]
    if has_last:
        shot.append(
            "   c. Make the path to the last frame explicit: from the first frame's state, "
            "through visible intermediate changes that narrow the difference, to the last "
            "frame's state. Do not describe the two pictures again as still images: describe "
            'the movement between them. End the shot with "the shot ends on <Picture 2>" and '
            "the character settling into that pose, spacing and composition."
        )
    shot += [
        "   " + ("d" if has_last else "c") + ". Camera: keep it calm so the lips stay "
        "readable and the face stays in frame: one static shot, or one slow push in. Write it "
        'as natural English with a move type, an amplitude and a speed ("The camera pushes in '
        'with small amplitude at slow speed toward her face."). ' + _CAMERA_VOCABULARY,
        "   " + ("e" if has_last else "d") + ". Speech: introduce the speaker once, with "
        "age, gender, pitch, timbre, pace and accent (from the character card and the "
        'delivery you write), then write "<Subject 1> (S1) … says, <d>[Language] the words</d>", '
        "where [Language] is the language of the words, named in English. The words are exactly "
        'those given under "Words inside <d>": nothing added, nothing changed, nothing '
        "translated. The lips move in time with each word and close when the line ends.",
        "   " + ("f" if has_last else "e") + ". " + _MARKER_RULES[marker],
    ]
    rules = [
        "Rules for the video prompt (MiniMax H3, reference mode). H3 was trained on a "
        "structured prompt and nothing rewrites yours. You give the pieces below as separate "
        "JSON strings, and the app writes the fixed parts around them: the headings, the "
        "lines that define each label and the lines that say how each reference is used. So "
        'never write a heading, a "[Shot 1]" tag or a line such as "<Picture 1> is …". '
        "Everything is English, except the words people speak.",
        f"References: {labels}. Use these labels exactly as written and never another one "
        "(no <Subject 2>, no <Video 1>).",
        "1. The clip is one shot, [Shot 1], with no cut and no cut time: the camera stays with "
        "the character from the first frame to the end.",
        "2. Give these JSON strings, without the field's name inside them:",
        *fields,
        *shot,
        "4. Concrete over abstract: no quality tags and no mood words (such as cinematic or "
        "beautiful) on their own, no plot summary, no text, signs or captions in the scene, "
        "and never the character's name. Sound that belongs to a moment (a laugh, a breath "
        "before the line) may be in the shot; ambience goes in the soundscape.",
        '5. "subject", "picture_1"'
        + (' and "picture_2"' if has_last else "")
        + " are words for the video model, which has not seen the pictures: here you DO "
        "describe the character from the card. The rule against describing the character "
        'belongs to "image_prompt" and "last_frame_prompt" only.',
    ]
    return "\n".join(rules)


def _h3_generate_rules(inputs: dict[str, Any]) -> str:
    has_last = bool(inputs.get("has_last_frame"))
    low, high = H3_GENERATE_ASKED_WORDS
    rules = [
        "Rules for the video prompt (MiniMax H3, first frame"
        + (" and last frame" if has_last else "")
        + "). H3 was trained on a structured prompt and nothing rewrites yours, so you give "
        "its three fields as separate JSON strings, without the field's name inside them, and "
        "the app puts them together. Everything is English.",
        '1. "integrated_multimodal_description": the whole picture and action, as one shot that '
        f"starts with the tag [Shot 1], in {low} to {high} words. The clip is one shot: no "
        "cut, no cut time and no [Shot 2].",
        "2. At the start of [Shot 1] name the overall style (for example live-action, "
        "cinematic) and read the composition from the first frame. Then describe the first "
        'frame as <Picture 1> (for example "the young woman shown in <Picture 1> remains '
        'beside the window, keeping her appearance, her clothes and the room"), and go on '
        "forward from it: first-frame anchor, action onset, continuous development, result or "
        "reaction. Describe only what moves; do not describe the picture again.",
    ]
    if has_last:
        rules.append(
            "3. The clip ends on <Picture 2>. Do not describe the two pictures as still images: "
            "describe the movement that joins them: how the pose changes, how the hands and "
            "the head move, how the composition and the light shift, with the differences "
            "narrowing step by step, until the character settles into the pose, spacing and "
            'composition of <Picture 2> at the end of the shot ("the shot ends on '
            '<Picture 2>").'
        )
    else:
        rules.append(
            "3. The clip has no last frame. End on a clear result or a reaction, and do not "
            "mention <Picture 2>."
        )
    rules += [
        "4. Camera: natural English with a move type, an amplitude and a speed when they "
        'matter ("The camera pushes in with small amplitude at slow speed toward the folded '
        'letter."). ' + _CAMERA_VOCABULARY,
        "5. Concrete verbs in the present tense. Show feeling through physical cues, never "
        'through a label such as "sad". One lighting logic. Never the character\'s name.',
        "6. Nobody speaks in this clip: the lips stay closed or relaxed, and the character "
        "only breathes, looks and moves. Write no <d> tag and no speaker id.",
        '7. "overall_soundscape": 1 to 4 sentences of ambience, physical sounds and non-verbal '
        "human sounds (breath, cloth, footsteps). H3 makes the clip's sound itself, so be "
        "specific. No speech and no music.",
        '8. "non_diegetic_music": 1 to 3 sentences on the instrumentation, tempo and dynamics '
        "of a score the character cannot hear, or exactly N/A. Write N/A unless the action "
        "needs a score.",
        '9. Never write the line that places the frames on the timeline ("For the target '
        'video, at 0.00 seconds…" or "How the reference pictures align…"): it depends on the '
        "exact frame count, so the app adds it when the clip is run.",
    ]
    return "\n".join(rules)


def _answer_keys(inputs: dict[str, Any]) -> list[str]:
    """The keys of the model's JSON answer, in the order it writes them."""
    needed = frozenset(inputs["needed"])
    target = _target(inputs)
    keys = [key for key in _KEYS if key in needed and not (target != "ltx" and key == VIDEO_PROMPT)]
    if target == "h3_generate":
        keys += [
            lab_prompt_writer.H3_DESCRIPTION,
            lab_prompt_writer.H3_SOUNDSCAPE,
            lab_prompt_writer.H3_MUSIC,
        ]
    elif target == "h3_reference":
        copy_all = _marker(inputs) == "fully_copy"
        keys += [STYLE, SUBJECT, PICTURE_1]
        if inputs.get("has_last_frame"):
            keys.append(PICTURE_2)
        keys += [SUMMARY, SHOT]
        if not copy_all:
            keys += [SOUNDSCAPE, MUSIC]
    return keys


def _system_prompt(inputs: dict[str, Any]) -> str:
    needed = frozenset(inputs["needed"])
    target = _target(inputs)
    rule_texts = [
        _TASK_TEXT[key]
        for key in _KEYS
        if key in needed and not (target != "ltx" and key == VIDEO_PROMPT)
    ]
    if target == "h3_reference":
        rule_texts.append(_h3_reference_rules(inputs))
    elif target == "h3_generate":
        rule_texts.append(_h3_generate_rules(inputs))
    rules = "\n\n".join(rule_texts)
    answer_shape = ", ".join(f'"{key}": "..."' for key in _answer_keys(inputs))
    return "\n".join(
        [
            "You write the prompts for one thing made from a library character: a picture, a "
            "piece of speech, a video, or some of these together. An author tries ideas in a "
            "lab and may edit what you write before anything runs.",
            "",
            "- You are given a card describing the character (its appearance, personality and "
            "notes), what happens, and what it says, if anything.",
            "- Write only the texts asked for below. Do not write the character's name in any "
            "of them: a picture is made from reference pictures, not from the name, and a "
            "video or a speech names no one either.",
            "",
            rules,
            "",
            f"Answer with one JSON object only, in exactly this form: {{{answer_shape}}}",
        ]
    )


def build_request(inputs: dict[str, Any], *, model: str) -> dict[str, Any]:
    """The exact request body sent to the model. Nothing about the call is hidden from the job
    record: this body is stored on the job (`job.input.request`).
    """
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt(inputs)},
            {
                "role": "user",
                "content": _render_inputs(inputs) + "\n\nWrite the prompts now.",
            },
        ],
        "max_tokens": MAX_TOKENS if _target(inputs) == "ltx" else H3_MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- Assembling the MiniMax H3 prompt ------------------------------------------------------


def _piece(answer: dict[str, Any], key: str) -> str:
    """One piece of an H3 answer on one line, or "" when it is missing or not text."""
    value = answer.get(key)
    return _one_line(value) if isinstance(value, str) else ""


def _audio_definition(marker: str) -> str:
    """The `<Audio 1>` line of `subject_definitions`, in MiniMax's own wording (guide 2.4)."""
    if marker == "fully_copy":
        return (
            "<Audio 1> is the recorded speech of <Subject 1> (S1), which is copied as the "
            "complete audio track of the target video."
        )
    if marker == "partially_copy":
        return (
            "<Audio 1> is the recorded speech of <Subject 1> (S1), whose spoken layer is "
            "copied into the target video."
        )
    if marker == "reference":
        return "<Audio 1> is the voice-timbre and delivery reference for <Subject 1> (S1)."
    return "<Audio 1> is a broad voice reference (gender, age and energy) for <Subject 1> (S1)."


def _audio_retention(marker: str) -> str:
    """The `<Audio 1>` line of `retention_analysis` (guide 4.2)."""
    if marker == "fully_copy":
        return (
            "<Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the target video's complete "
            "final audio track."
        )
    if marker == "partially_copy":
        return (
            "<Audio 1>: partially_copy - the spoken layer of <Audio 1> is copied with its "
            "words, timing and pauses, and other sound is added around it."
        )
    if marker == "reference":
        return (
            "<Audio 1>: reference - <Subject 1> (S1) follows <Audio 1>'s voice timbre and "
            "measured delivery without copying the original signal."
        )
    return (
        "<Audio 1>: weak_reference - only the broad character of <Audio 1>'s voice (gender, "
        "age and energy) is kept."
    )


def _task_tag(marker: str) -> str:
    """The task types of the summary (guide 3): the first frame is a frame anchor, and the audio
    is either reused or referenced.
    """
    audio = "audio reuse" if marker in COPY_MARKERS else "audio reference"
    return f"[keyframe completion + {audio}]"


def _reference_pieces(answer: dict[str, Any], inputs: dict[str, Any]) -> dict[str, str]:
    """The pieces of a reference answer, cleaned. Raises ValueError, with a message for the
    user, naming the pieces that are missing.
    """
    pieces = {key: _piece(answer, key) for key in (STYLE, SUBJECT, PICTURE_1, SUMMARY, SHOT)}
    if inputs.get("has_last_frame"):
        pieces[PICTURE_2] = _piece(answer, PICTURE_2)
    if _marker(inputs) != "fully_copy":
        pieces[SOUNDSCAPE] = _piece(answer, SOUNDSCAPE)
    missing = [key for key, value in pieces.items() if not value]
    if missing:
        raise ValueError(
            "The model's answer had no text for: " + ", ".join(f'"{key}"' for key in missing) + "."
        )
    pieces[MUSIC] = _piece(answer, MUSIC) or NO_MUSIC
    # The model is asked not to repeat what the app writes. A repeat is removed, not refused.
    pieces[SUBJECT] = re.sub(
        r"^<Subject 1>\s+is\s+", "", pieces[SUBJECT], flags=re.IGNORECASE
    ).rstrip(". ")
    for key in (PICTURE_1, PICTURE_2):
        if key in pieces:
            pieces[key] = re.sub(r"^showing\s+", "", pieces[key], flags=re.IGNORECASE).rstrip(". ")
    pieces[SHOT] = re.sub(r"^\[Shot\s*1\]\s*", "", pieces[SHOT], flags=re.IGNORECASE)
    pieces[SUMMARY] = re.sub(r"^\[(?!Shot)[^\]]*\]\s*", "", pieces[SUMMARY])
    return pieces


def assemble_h3_reference_prompt(answer: dict[str, Any], inputs: dict[str, Any]) -> str:
    """The six sections of MiniMax's reference format (`subject_definitions`, `summary`,
    `retention_analysis`, `detailed_description`, `overall_soundscape`, `non_diegetic_music`),
    in that order, from the model's pieces. The headings, the label definitions, the task tag
    and the retention lines are written here, from the take's own settings, so they are always
    consistent with the pictures and the audio the clip is sent with. Raises ValueError.
    """
    marker = _marker(inputs)
    has_last = bool(inputs.get("has_last_frame"))
    identity = int(inputs.get("identity_pictures") or 0)
    pieces = _reference_pieces(answer, inputs)

    subject = f"<Subject 1> is {pieces[SUBJECT]}, as shown in <Picture 1>"
    if identity:
        first = 3 if has_last else 2
        extra = _label_list([f"<Picture {first + i}>" for i in range(identity)])
        subject += f", with the same character's look also shown in {extra}"
    definitions = [
        subject + ".",
        f"<Picture 1> is the first frame of [Shot 1], showing {pieces[PICTURE_1]}.",
    ]
    retention = [
        "<Subject 1> (appears in [Shot 1]): fully_preserved - the character's identity, face, "
        "hair, build and clothing defined above are retained.",
        "<Picture 1> ([Shot 1] first frame): fully_preserved - the shot begins from this exact "
        "composition, subject, clothing, place and light.",
    ]
    if has_last:
        definitions.append(
            f"<Picture 2> is the last frame of [Shot 1], showing {pieces[PICTURE_2]}."
        )
        retention.append(
            "<Picture 2> ([Shot 1] last frame): fully_preserved - the shot ends on this "
            "composition, pose, clothing, place and light."
        )
    definitions.append(_audio_definition(marker))
    retention.append(_audio_retention(marker))

    if marker == "fully_copy":
        soundscape = (
            "No ambience or effects are added: the only sound is the speech copied from <Audio 1>."
        )
        music = NO_MUSIC
    else:
        soundscape = pieces[SOUNDSCAPE]
        music = pieces[MUSIC]

    sections = [
        "subject_definitions:\n" + "\n".join(definitions),
        f"summary:\n{_task_tag(marker)} {pieces[SUMMARY]}",
        "retention_analysis:\n" + "\n".join(retention),
        f"detailed_description:\n{pieces[STYLE]}\n[Shot 1] {pieces[SHOT]}",
        f"overall_soundscape:\n{soundscape}",
        f"non_diegetic_music:\n{music}",
    ]
    return "\n\n".join(sections)


def _section(text: str, name: str) -> str:
    """The body of one section of an assembled reference prompt, or "" when it is not there."""
    match = re.search(rf"^{name}:\n(.*?)(?=\n\n[a-z_]+:\n|\Z)", text, re.DOTALL | re.MULTILINE)
    return match.group(1) if match else ""


# --- Reading the answer -----------------------------------------------------------------


def parse_answer(content: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """The model's answer as a dict, with the finished video prompt under `video_prompt` for a
    MiniMax H3 take (assembled from the model's pieces, which stay in the dict, so the job keeps
    exactly what the model said). Raises ValueError, with a message fit for the user, when it
    is empty, not JSON, or is missing text for one of the keys asked for.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    if not isinstance(answer, dict):
        raise ValueError("The model's answer was not a JSON object.")
    target = _target(inputs)
    for key in _KEYS:
        if key not in inputs["needed"] or (target != "ltx" and key == VIDEO_PROMPT):
            continue
        value = answer.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'The model\'s answer had no "{key}" text.')
    if target == "h3_reference":
        return {**answer, VIDEO_PROMPT: assemble_h3_reference_prompt(answer, inputs)}
    if target == "h3_generate":
        text = lab_prompt_writer.assemble_h3_prompt(answer)
        if text is None:
            raise ValueError(
                f'The model\'s answer had no "{lab_prompt_writer.H3_DESCRIPTION}" and '
                f'"{lab_prompt_writer.H3_SOUNDSCAPE}" text.'
            )
        return {**answer, VIDEO_PROMPT: text}
    return answer


@dataclass(frozen=True)
class CheckedTakePrompts:
    """The texts that were asked for, each on one line (a MiniMax H3 video prompt keeps its
    line breaks), with the warnings they earned. A text that was not asked for is None.
    """

    image_prompt: str | None
    last_frame_prompt: str | None
    video_prompt: str | None
    delivery_instruction: str | None
    warnings: tuple[str, ...]


def _checked_text(answer: dict[str, Any], key: str) -> str:
    value = answer.get(key)
    if not isinstance(value, str):
        raise ValueError(f'The model\'s "{key}" was not text.')
    text = _one_line(value)
    if not text or len(text) > FIELD_MAX_CHARS:
        raise ValueError(
            f'The model\'s "{key}" was empty or longer than {FIELD_MAX_CHARS:,} characters.'
        )
    return text


def _checked_block(answer: dict[str, Any], key: str) -> str:
    """A text that keeps its line breaks (a MiniMax H3 prompt is made of sections)."""
    value = answer.get(key)
    if not isinstance(value, str):
        raise ValueError(f'The model\'s "{key}" was not text.')
    text = value.strip()
    if not text or len(text) > H3_PROMPT_MAX_CHARS:
        raise ValueError(
            f'The model\'s "{key}" was empty or longer than {H3_PROMPT_MAX_CHARS:,} characters.'
        )
    return text


def _words_warning(what: str, words: int, low: int, high: int) -> str | None:
    if low <= words <= high:
        return None
    return f"The {what} has {words} words. {low} to {high} works best."


def _h3_reference_warnings(text: str, inputs: dict[str, Any]) -> list[str]:
    """What is off in an assembled reference prompt. None of it blocks: the author can edit."""
    warnings: list[str] = []
    detailed = _section(text, "detailed_description")
    shot = detailed.split("[Shot 1]", 1)[-1]
    has_last = bool(inputs.get("has_last_frame"))
    identity = int(inputs.get("identity_pictures") or 0)
    pictures = 1 + (1 if has_last else 0) + identity

    words = len(detailed.split())
    low, high = H3_REFERENCE_MIN_WORDS, H3_REFERENCE_MAX_WORDS
    if not low <= words <= high:
        warnings.append(
            f"The detailed description has {words} words. MiniMax's guide asks for {low} to "
            f"{high} for a new clip."
        )

    dialogue = inputs.get("dialogue")
    spoken = [_one_line(found) for found in _SPOKEN.findall(shot)]
    if dialogue and _one_line(str(dialogue)) not in spoken:
        warnings.append(
            "The exact dialogue was not found inside <d>[Language] …</d> in the shot. H3 "
            "speaks the words in that tag."
        )
    if "[Shot 2]" in text:
        warnings.append("The prompt has a second shot. One shot was asked for.")
    if "<Picture 1>" not in shot or not _BEGINS_FROM.search(shot):
        warnings.append("The shot does not say that it begins from <Picture 1>.")
    if has_last and ("<Picture 2>" not in shot or not _ENDS_ON.search(shot)):
        warnings.append("The shot does not say that it ends on <Picture 2>.")
    if "<Audio 1>" not in shot:
        warnings.append("The shot does not name <Audio 1> where the speech is.")
    too_high = sorted(
        {int(number) for number in _PICTURE_LABEL.findall(text) if int(number) > pictures}
    )
    if too_high or _OTHER_LABEL.search(text):
        warnings.append(
            f"A label that is not sent with the clip was found. Only <Picture 1> to "
            f"<Picture {pictures}>, <Subject 1> and <Audio 1> exist."
        )
    return warnings


def _h3_generate_warnings(text: str) -> list[str]:
    warnings: list[str] = []
    description = text.split("overall_soundscape:", 1)[0]
    words = len(description.split())
    warning = _words_warning("description", words, H3_GENERATE_MIN_WORDS, H3_GENERATE_MAX_WORDS)
    if warning:
        warnings.append(warning)
    blocks = lab_prompt_writer.count_shot_blocks(text)
    if blocks != 1:
        warnings.append(f"The prompt has {blocks} [Shot N] blocks. One shot was asked for.")
    if _ANY_SPOKEN.search(text):
        warnings.append("A <d> tag was found, but nobody speaks in this clip.")
    if _ALIGNMENT_LINE.search(text):
        warnings.append(
            "The line that places the frames was written into the prompt. Remove it: the app "
            "adds it, with the clip's exact length, when the clip is run."
        )
    return warnings


def check_prompts(answer: dict[str, Any], inputs: dict[str, Any]) -> CheckedTakePrompts:
    """The answer's texts made into single lines and checked. Raises ValueError, with a
    message for the user, when one that was asked for cannot be used: not text, empty, or
    longer than the limit.

    Warnings never block: a text of an unusual length, or one that breaks a wording rule, is
    still returned, so the author can edit it before anything runs.
    """
    needed = frozenset(inputs["needed"])
    target = _target(inputs)
    warnings: list[str] = []
    image_prompt = _checked_text(answer, IMAGE_PROMPT) if IMAGE_PROMPT in needed else None
    last_frame_prompt = (
        _checked_text(answer, LAST_FRAME_PROMPT) if LAST_FRAME_PROMPT in needed else None
    )
    video_prompt: str | None = None
    if VIDEO_PROMPT in needed:
        video_prompt = (
            _checked_text(answer, VIDEO_PROMPT)
            if target == "ltx"
            else _checked_block(answer, VIDEO_PROMPT)
        )
    delivery = (
        _checked_text(answer, DELIVERY_INSTRUCTION) if DELIVERY_INSTRUCTION in needed else None
    )

    if image_prompt is not None:
        words = len(image_prompt.split())
        if words < IMAGE_MIN_WORDS or words > IMAGE_MAX_WORDS:
            warnings.append(
                f"The image prompt has {words} words. {IMAGE_MIN_WORDS} to {IMAGE_MAX_WORDS} "
                "works best."
            )
        if _NEGATIVE_WORDS.search(image_prompt):
            warnings.append(
                "A negative found in the image prompt (no, not, without). The image model has "
                "no negative prompt, and naming a thing can make it appear: say what is there "
                "instead."
            )
    if last_frame_prompt is not None:
        words = len(last_frame_prompt.split())
        warning = _words_warning(
            "last frame prompt", words, LAST_FRAME_MIN_WORDS, LAST_FRAME_MAX_WORDS
        )
        if warning:
            warnings.append(warning)
        if _NEGATIVE_WORDS.search(last_frame_prompt):
            warnings.append(
                "A negative found in the last frame prompt (no, not, without). The image model "
                "has no negative prompt: say what is there instead."
            )
    if video_prompt is not None:
        if target == "h3_reference":
            warnings += _h3_reference_warnings(video_prompt, inputs)
        elif target == "h3_generate":
            warnings += _h3_generate_warnings(video_prompt)
        else:
            words = len(video_prompt.split())
            if words < VIDEO_MIN_WORDS or words > VIDEO_MAX_WORDS:
                warnings.append(
                    f"The video prompt has {words} words. {VIDEO_MIN_WORDS} to "
                    f"{VIDEO_MAX_WORDS} works best."
                )
            if _DOUBLE_QUOTES.search(video_prompt):
                warnings.append(
                    "Double quotes found in the video prompt. The speech is a separate sound, "
                    "so the words are not needed in the prompt."
                )
    if delivery is not None and len(delivery) > DELIVERY_MAX_CHARS:
        raise ValueError(
            f'The model\'s "{DELIVERY_INSTRUCTION}" was longer than {DELIVERY_MAX_CHARS} '
            "characters."
        )

    return CheckedTakePrompts(
        image_prompt=image_prompt,
        last_frame_prompt=last_frame_prompt,
        video_prompt=video_prompt,
        delivery_instruction=delivery,
        warnings=tuple(warnings),
    )
