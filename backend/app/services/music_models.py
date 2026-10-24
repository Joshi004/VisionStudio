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


def coerce_fields(model: MusicModel, raw: object) -> dict[str, Any]:
    """The fields of `model` read from `raw` (a dict from a language model or from the page),
    with the right types. It never raises and never judges: text is stripped (a missing field is
    ""), a number that is not one is None, and fields the model does not have are dropped. A
    whole number the server wants as an integer (the BPM) is rounded.
    `field_problems` says what is wrong with the result.
    """
    source = raw if isinstance(raw, dict) else {}
    fields: dict[str, Any] = {}
    for spec in FIELDS[model]:
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


def field_problems(model: MusicModel, fields: dict[str, Any]) -> list[str]:
    """What stops these fields from being sent to `model`, as sentences for the user, in the
    order of the fields. Empty when they can be sent. `fields` come from `coerce_fields`.
    """
    problems: list[str] = []
    for spec in FIELDS[model]:
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
                continue
            if spec.minimum is not None and value < spec.minimum:
                problems.append(f"{spec.label} must be at least {spec.minimum:g}.")
            if spec.maximum is not None and value > spec.maximum:
                problems.append(f"{spec.label} must be at most {spec.maximum:g}.")
    # ACE-Step sings whatever the lyrics say: without lyrics it must be told there are no vocals.
    if model == "ace-step-1.5" and not fields.get("instrumental") and not fields.get("lyrics"):
        problems.append("There are no lyrics: write some, or tick Instrumental.")
    return problems
