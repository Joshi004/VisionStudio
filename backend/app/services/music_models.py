"""The models of the Music lab and what each one takes. Pure data and pure functions, no I/O.

The lab tries five GPU server backends by hand, so that a person can hear which one suits which
kind of sound before anything is added to the story pipeline:

- `ace-step-1.5`: ACE-Step 1.5, songs with vocals or instrumentals, with exact tempo and key.
- `yue2`: YuE2, full sung songs in English or Chinese.
- `stable-audio-3`: Stable Audio 3, instrumental music, stems, solo instruments, sound effects.
- `stable-audio-open`: Stable Audio Open 1.0, short sound effects, loops and ambience.
- `ltx-audio`: LTX text-to-audio, sound effects and ambience as a WAV.

The ids are what the database and the API store, so a new model means a new id here, in the
database CHECK (a migration), in `providers/music_generator.py` and in
`services/music_prompt_profiles.py`.

Each model has *fields*: the few values that make its request (a caption and lyrics for ACE-Step,
a style and lyrics for YuE2, one prompt for the Stable Audio models). The language model writes
them, the person edits them, and `providers/music_generator.build_body` turns them into the
request. Their limits are the ones the server's OpenAPI document declares (API 0.18.0).

Editing (MUSIC-004) starts from a recording instead of text: `repaint` and `cover` (ACE-Step),
`inpaint` and `transform` (Stable Audio 3), and `transform` (Stable Audio Open). Each has its own
fields (`EDIT_FIELDS`) and its own rules (`edit_problems`), at the end of this module.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Final, Literal, TypeGuard, get_args

MusicModel = Literal["ace-step-1.5", "yue2", "stable-audio-3", "stable-audio-open", "ltx-audio"]
# What a person asks for: the pipeline will need all five (a score under the narration, a title
# song, a solo instrument, a sound effect and a room's ambience).
MusicKind = Literal["score", "song", "stem", "sfx", "ambience"]
# How far a model's licence reaches, for the warning the lab shows next to it.
LicenseLevel = Literal["open", "community", "non_commercial", "unknown"]
FieldType = Literal["text", "int", "number", "flag"]

MODEL_IDS: Final[tuple[MusicModel, ...]] = get_args(MusicModel)
KIND_IDS: Final[tuple[MusicKind, ...]] = get_args(MusicKind)

LABELS: Final[dict[MusicModel, str]] = {
    "ace-step-1.5": "ACE-Step 1.5",
    "yue2": "YuE2",
    "stable-audio-3": "Stable Audio 3",
    "stable-audio-open": "Stable Audio Open",
    "ltx-audio": "LTX audio",
}

KIND_LABELS: Final[dict[MusicKind, str]] = {
    "score": "Score / music bed",
    "song": "Song with vocals",
    "stem": "Stem / solo instrument",
    "sfx": "Sound effect",
    "ambience": "Ambience / room tone",
}

# The models that can make each kind, best first. The lab only offers these for a kind.
KIND_MODELS: Final[dict[MusicKind, tuple[MusicModel, ...]]] = {
    "score": ("ace-step-1.5", "stable-audio-3"),
    "song": ("ace-step-1.5", "yue2"),
    "stem": ("ace-step-1.5", "stable-audio-3"),
    "sfx": ("stable-audio-3", "stable-audio-open", "ltx-audio"),
    "ambience": ("stable-audio-3", "stable-audio-open", "ltx-audio"),
}


@dataclass(frozen=True)
class LicenseNote:
    level: LicenseLevel
    # The warning shown next to the model. It states what the server's own documentation says.
    text: str


LICENSES: Final[dict[MusicModel, LicenseNote]] = {
    "ace-step-1.5": LicenseNote(
        "open",
        "The ACE-Step code is MIT and its authors state that generated music may be used "
        "commercially. Generated music can resemble existing works: check originality and "
        "disclose AI involvement where required.",
    ),
    "yue2": LicenseNote(
        "non_commercial",
        "NON-COMMERCIAL ONLY. The YuE2 weights are CC BY-NC 4.0, with creator permission "
        "required and a commercial licence required for companies. Do not use its songs in "
        "anything published or sold. Generated music can resemble existing works.",
    ),
    "stable-audio-3": LicenseNote(
        "community",
        "Stability AI Community License: free for individuals and organisations below USD 1M "
        "annual revenue; above that a separate licence is needed. The server does not enforce "
        "this: whoever runs this deployment is responsible.",
    ),
    "stable-audio-open": LicenseNote(
        "community",
        "Stability AI Community License: free for individuals and organisations below USD 1M "
        "annual revenue; above that a separate licence is needed. The server does not enforce "
        "this: whoever runs this deployment is responsible.",
    ),
    "ltx-audio": LicenseNote(
        "unknown",
        "The GPU server's documentation states no licence for LTX audio. Check the LTX-2 "
        "licence before using its output commercially.",
    ),
}

# The seed. The servers accept up to 2**31 - 1 (YuE2 and LTX accept more, which a lab does not
# need), so one range serves every model.
SEED_MAX: Final = 2_147_483_647

# The longest piece each model makes, in seconds (None: the length follows the lyrics). LTX
# audio documents no maximum: the lab holds it to a minute, which is a guard, not a model limit.
MAX_DURATION_S: Final[dict[MusicModel, float | None]] = {
    "ace-step-1.5": 600.0,
    "yue2": None,
    "stable-audio-3": 285.0,
    "stable-audio-open": 47.0,
    "ltx-audio": 60.0,
}
MIN_DURATION_S: Final[dict[MusicModel, float | None]] = {
    "ace-step-1.5": 10.0,
    "yue2": None,
    "stable-audio-3": 0.5,
    "stable-audio-open": 0.5,
    "ltx-audio": 0.5,
}
# What is sent when the duration is left empty, for the models that need one. ACE-Step plans its
# own length, and YuE2 follows its lyrics.
DEFAULT_DURATION_S: Final[dict[MusicModel, float | None]] = {
    "ace-step-1.5": None,
    "yue2": None,
    "stable-audio-3": 30.0,
    "stable-audio-open": 30.0,
    "ltx-audio": 10.0,
}


def is_music_model(value: object) -> TypeGuard[MusicModel]:
    return isinstance(value, str) and value in MODEL_IDS


def is_music_kind(value: object) -> TypeGuard[MusicKind]:
    return isinstance(value, str) and value in KIND_IDS


def label(model: object) -> str:
    """The name to show for a model id. An unknown value is shown as it is."""
    return LABELS[model] if is_music_model(model) else str(model)


# --- The fields of each model -------------------------------------------------------------

_KEYSCALE = re.compile(r"[A-Za-z0-9#\u266d ]{0,20}")
_VOCAL_LANGUAGE = re.compile(r"unknown|[a-z]{2,3}(-[A-Za-z0-9]{2,8})?")
_TIME_SIGNATURES: Final = ("2", "3", "4", "6")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    type: FieldType
    required: bool = False
    max_chars: int | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None
    pattern: re.Pattern[str] | None = None
    pattern_hint: str = ""


FIELDS: Final[dict[MusicModel, tuple[FieldSpec, ...]]] = {
    "ace-step-1.5": (
        FieldSpec("caption", "Caption", "text", required=True, max_chars=512),
        FieldSpec("lyrics", "Lyrics", "text", max_chars=4096),
        FieldSpec("instrumental", "Instrumental (no vocals)", "flag"),
        FieldSpec(
            "vocal_language",
            "Vocal language",
            "text",
            pattern=_VOCAL_LANGUAGE,
            pattern_hint="a short code such as en, zh, ja, es, or unknown",
        ),
        FieldSpec("bpm", "BPM", "int", minimum=30, maximum=300),
        FieldSpec(
            "keyscale",
            "Key",
            "text",
            max_chars=20,
            pattern=_KEYSCALE,
            pattern_hint="letters, digits, # and spaces, such as A minor",
        ),
        FieldSpec("time_signature", "Time signature", "text", choices=_TIME_SIGNATURES),
        FieldSpec("duration", "Duration (s)", "number", minimum=10, maximum=600),
    ),
    "yue2": (
        FieldSpec("style", "Style", "text", required=True, max_chars=1000),
        FieldSpec("lyrics", "Lyrics", "text", required=True, max_chars=6000),
    ),
    "stable-audio-3": (
        FieldSpec("prompt", "Prompt", "text", required=True, max_chars=2000),
        FieldSpec("duration", "Duration (s)", "number", minimum=0.5, maximum=285),
    ),
    "stable-audio-open": (
        FieldSpec("prompt", "Prompt", "text", required=True, max_chars=1000),
        FieldSpec("negative_prompt", "Negative prompt", "text", max_chars=1000),
        FieldSpec("duration", "Duration (s)", "number", minimum=0.5, maximum=47),
    ),
    "ltx-audio": (
        FieldSpec("prompt", "Prompt", "text", required=True, max_chars=4000),
        FieldSpec("negative_prompt", "Negative prompt", "text", max_chars=1000),
        FieldSpec("duration", "Duration (s)", "number", minimum=0.5, maximum=60),
    ),
}


def field_specs(model: MusicModel) -> tuple[FieldSpec, ...]:
    return FIELDS[model]


def _text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int | float):
        return f"{value:g}"
    return ""


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, int | float) and math.isfinite(value):
        return float(value)
    return None


def _flag(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def _coerce(specs: tuple[FieldSpec, ...], raw: object) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    fields: dict[str, Any] = {}
    for spec in specs:
        value = source.get(spec.name)
        if spec.type == "text":
            fields[spec.name] = _text(value)
        elif spec.type == "flag":
            fields[spec.name] = _flag(value)
        else:
            number = _number(value)
            fields[spec.name] = (
                round(number) if number is not None and spec.type == "int" else number
            )
    return fields


def coerce_fields(model: MusicModel, raw: object) -> dict[str, Any]:
    """The fields of `model` read from `raw` (a dict from a language model or from the page),
    with the right types. It never raises and never judges: text is stripped (a missing field is
    ""), a number that is not one is None, and fields the model does not have are dropped. A
    whole number the server wants as an integer (the BPM) is rounded.
    `field_problems` says what is wrong with the result.
    """
    return _coerce(FIELDS[model], raw)


def _problems(specs: tuple[FieldSpec, ...], fields: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for spec in specs:
        value = fields.get(spec.name)
        if spec.type == "text":
            text = value if isinstance(value, str) else ""
            if spec.required and not text:
                problems.append(f"{spec.label} is empty.")
            if spec.max_chars is not None and len(text) > spec.max_chars:
                problems.append(
                    f"{spec.label} is {len(text):,} characters; the limit is {spec.max_chars:,}."
                )
            if text and spec.choices is not None and text not in spec.choices:
                problems.append(f"{spec.label} must be one of {', '.join(spec.choices)}.")
            if text and spec.pattern is not None and not spec.pattern.fullmatch(text):
                problems.append(f"{spec.label} must be {spec.pattern_hint}.")
        elif spec.type in ("int", "number"):
            if value is None:
                if spec.required:
                    problems.append(f"{spec.label} is empty.")
                continue
            if spec.minimum is not None and value < spec.minimum:
                problems.append(f"{spec.label} must be at least {spec.minimum:g}.")
            if spec.maximum is not None and value > spec.maximum:
                problems.append(f"{spec.label} must be at most {spec.maximum:g}.")
    return problems


def _ace_step_lyrics_problem(model: MusicModel, fields: dict[str, Any]) -> list[str]:
    # ACE-Step sings whatever the lyrics say: without lyrics it must be told there are no vocals.
    if model == "ace-step-1.5" and not fields.get("instrumental") and not fields.get("lyrics"):
        return ["There are no lyrics: write some, or tick Instrumental."]
    return []


def field_problems(model: MusicModel, fields: dict[str, Any]) -> list[str]:
    """What stops these fields from being sent to `model`, as sentences for the user, in the
    order of the fields. Empty when they can be sent. `fields` come from `coerce_fields`.
    """
    return _problems(FIELDS[model], fields) + _ace_step_lyrics_problem(model, fields)


# --- Editing (MUSIC-004) ------------------------------------------------------------------
#
# An edit starts from a recording (the source) and has the fields of its operation: a window, a
# strength or a noise level next to the prompt. The limits are the ones the server's OpenAPI
# document declares (API 0.18.0).

EditOperation = Literal["repaint", "cover", "inpaint", "transform"]
EDIT_OPERATION_IDS: Final[tuple[EditOperation, ...]] = get_args(EditOperation)

EDIT_LABELS: Final[dict[EditOperation, str]] = {
    "repaint": "Repaint a window",
    "cover": "Cover (restyle)",
    "inpaint": "Inpaint or extend",
    "transform": "Transform",
}

EDIT_HELP: Final[dict[EditOperation, str]] = {
    "repaint": (
        "Regenerates one window of the recording and keeps the rest. Give the start and, "
        "optionally, the end of the window (the end cannot pass the end of the source)."
    ),
    "cover": (
        "Restyles the whole recording and keeps its structure. The strength runs from 1 (very "
        "close to the source) through 0.5 (balanced) to about 0.2 (a loose style transfer). "
        "The result is as long as the source."
    ),
    "inpaint": (
        "Regenerates a window, or extends the recording: start the window at (or just before) "
        "the end of the source and end it where the new audio should end. The audio around the "
        "window matters more than the prompt."
    ),
    "transform": (
        "Makes new audio from the recording and a prompt. The noise level says how much of the "
        "source is kept: low stays close, high ignores it. Keep the seed fixed while you try "
        "values."
    ),
}

# The models that make each operation, in the order the lab offers them.
EDIT_MODELS: Final[dict[EditOperation, tuple[MusicModel, ...]]] = {
    "repaint": ("ace-step-1.5",),
    "cover": ("ace-step-1.5",),
    "inpaint": ("stable-audio-3",),
    "transform": ("stable-audio-3", "stable-audio-open"),
}

# The longest source each (operation, model) takes, in seconds.
MAX_SOURCE_S: Final[dict[tuple[EditOperation, MusicModel], float]] = {
    ("repaint", "ace-step-1.5"): 600.0,
    ("cover", "ace-step-1.5"): 600.0,
    ("inpaint", "stable-audio-3"): 380.0,
    ("transform", "stable-audio-3"): 380.0,
    ("transform", "stable-audio-open"): 120.0,
}

# A window may end this far past the source's length (the length is rounded when it is shown).
EDGE_TOLERANCE_S: Final = 0.1

_ACE_TEXT_FIELDS: Final = (
    FieldSpec("caption", "Caption", "text", required=True, max_chars=512),
    FieldSpec("lyrics", "Lyrics", "text", max_chars=4096),
    FieldSpec("instrumental", "Instrumental (no vocals)", "flag"),
    FieldSpec(
        "vocal_language",
        "Vocal language",
        "text",
        pattern=_VOCAL_LANGUAGE,
        pattern_hint="a short code such as en, zh, ja, es, or unknown",
    ),
)

EDIT_FIELDS: Final[dict[tuple[EditOperation, MusicModel], tuple[FieldSpec, ...]]] = {
    ("repaint", "ace-step-1.5"): (
        *_ACE_TEXT_FIELDS,
        FieldSpec("repaint_start", "Window start (s)", "number", required=True, minimum=0),
        FieldSpec("repaint_end", "Window end (s)", "number", minimum=0),
    ),
    ("cover", "ace-step-1.5"): (
        *_ACE_TEXT_FIELDS,
        FieldSpec("cover_strength", "Strength", "number", required=True, minimum=0, maximum=1),
    ),
    ("inpaint", "stable-audio-3"): (
        FieldSpec("prompt", "Prompt", "text", required=True, max_chars=2000),
        FieldSpec("mask_start", "Window start (s)", "number", required=True, minimum=0),
        FieldSpec("mask_end", "Window end (s)", "number", required=True, minimum=0),
        FieldSpec("duration", "Length of the result (s)", "number", minimum=0.5, maximum=380),
    ),
    ("transform", "stable-audio-3"): (
        FieldSpec("prompt", "Prompt", "text", required=True, max_chars=2000),
        FieldSpec("init_noise_level", "Noise level", "number", required=True, minimum=0, maximum=1),
        FieldSpec("duration", "Length of the result (s)", "number", minimum=0.5, maximum=380),
    ),
    ("transform", "stable-audio-open"): (
        FieldSpec("prompt", "Prompt", "text", required=True, max_chars=1000),
        FieldSpec("negative_prompt", "Negative prompt", "text", max_chars=1000),
        FieldSpec(
            "init_noise_level", "Noise level", "number", required=True, minimum=0.05, maximum=20
        ),
        FieldSpec("duration", "Length of the result (s)", "number", minimum=0.5, maximum=47),
    ),
}


def is_edit_operation(value: object) -> TypeGuard[EditOperation]:
    return isinstance(value, str) and value in EDIT_OPERATION_IDS


def edit_supported(operation: EditOperation, model: object) -> bool:
    """Whether `model` makes `operation`."""
    return is_music_model(model) and model in EDIT_MODELS[operation]


def edit_field_specs(operation: EditOperation, model: MusicModel) -> tuple[FieldSpec, ...]:
    return EDIT_FIELDS[(operation, model)]


def coerce_edit_fields(operation: EditOperation, model: MusicModel, raw: object) -> dict[str, Any]:
    """Like `coerce_fields`, for the fields of an editing operation."""
    return _coerce(EDIT_FIELDS[(operation, model)], raw)


def edit_problems(
    operation: EditOperation,
    model: MusicModel,
    fields: dict[str, Any],
    source_duration_s: float,
) -> list[str]:
    """What stops this edit from being sent, as sentences for the user: the fields' own limits,
    then the rules that need the source's length (it must fit the model, the window must start
    inside it, and so on). Empty when it can be sent. `fields` come from `coerce_edit_fields`.
    """
    problems = _problems(EDIT_FIELDS[(operation, model)], fields)
    problems += _ace_step_lyrics_problem(model, fields)

    longest = MAX_SOURCE_S[(operation, model)]
    if source_duration_s > longest:
        problems.append(
            f"The source is {source_duration_s:.1f} s long; {label(model)} takes at most "
            f"{longest:g} s for this."
        )

    if operation == "repaint":
        start, end = fields.get("repaint_start"), fields.get("repaint_end")
        if start is not None and start >= source_duration_s:
            problems.append(
                f"The window must start inside the source (it is {source_duration_s:.1f} s long)."
            )
        if start is not None and end is not None:
            if end <= start:
                problems.append("The window must end after it starts.")
            if end > source_duration_s + EDGE_TOLERANCE_S:
                problems.append(
                    f"The window cannot end after the source does ({source_duration_s:.1f} s). "
                    "To repaint past the end, join a silent tail to the source first."
                )
    elif operation == "inpaint":
        start, end = fields.get("mask_start"), fields.get("mask_end")
        length = fields.get("duration")
        if start is not None and start > source_duration_s + EDGE_TOLERANCE_S:
            problems.append(
                "The window must start inside the source, or at its end to extend it "
                f"(it is {source_duration_s:.1f} s long)."
            )
        if start is not None and end is not None and end <= start:
            problems.append("The window must end after it starts.")
        if end is not None and end > 380:
            problems.append("The window cannot end after 380 s.")
        if end is not None and length is not None and length < end:
            problems.append("The length of the result must be at least the end of the window.")
    return problems
