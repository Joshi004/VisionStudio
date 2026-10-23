"""Writing the prompt fields for one music model with a language model, for the Music lab. Pure
functions, no I/O.

The author gives a *brief*: the kind of sound wanted, a description, and whatever the story
pipeline will later supply by itself (the Story Bible's genre, tone and era, the scene's mood arc
and dramatic goal, the place, the length from the timeline, whether the piece sits under a
narration, a sound event from the scene's events, and for a song the lyrics or a theme). The
model answers with the fields of the chosen music model (`music_models.FIELDS`), written the way
that model wants them (`music_prompt_profiles.py`).

The steps are the same as for the other language model jobs:

1. `build_request`: the instructions and the brief, as an OpenAI-style chat request.
2. `parse_answer`: the model's JSON, read defensively.
3. `check_fields`: the fields are coerced to the right types and checked. Anything outside a
   limit, and wording the profile dislikes, gives a warning. Warnings never stop the fields from
   being shown: the author edits them before running anything, and the run itself refuses fields
   the server would refuse (`services/music_lab.py`).

The call is made by `providers/llm.py` and the job that drives it is
`jobs/write_lab_music_prompt.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from app.providers import llm
from app.services import music_models
from app.services.music_models import MusicKind, MusicModel
from app.services.music_prompt_profiles import (
    MUSIC_WORDS,
    STYLE_STARTS_WITH_LANGUAGE,
    UNDER_NARRATION_RULE,
    MusicPromptProfile,
)

# Hidden reasoning is billed as output (ANALYSIS.md Section 6.2, rule 4). The fields are a few
# hundred tokens (a song's lyrics are the longest), so this leaves room to think.
MAX_TOKENS: Final = 8000
REASONING_EFFORT: Final = "high"

# What each kind is, in a phrase for the request.
_KIND_PHRASES: Final[dict[MusicKind, str]] = {
    "score": "a background score (instrumental music that plays under a story)",
    "song": "a song with sung vocals",
    "stem": "a stem: one isolated instrument or part, played alone",
    "sfx": "a sound effect",
    "ambience": "an ambience: the continuous sound of a place",
}

# A tag in lyrics, "[Verse 1]" or "[Chorus - soft]".
_LYRIC_TAG = re.compile(r"^\s*\[[^\]\n]+\]\s*$", re.MULTILINE)
# A tag with two modifiers: "[Chorus - anthemic - loud]". ACE-Step takes at most one.
_TWO_MODIFIERS = re.compile(r"\[[^\]\n-]+(?:\s-\s[^\]\n-]+){2,}\]")
# How short "short and concrete" is for Stable Audio Open.
_SAO_MAX_WORDS: Final = 60


def _one_line(value: str) -> str:
    return " ".join(value.split())


# --- The request --------------------------------------------------------------------------


def prompt_inputs(model: MusicModel, brief: dict[str, Any]) -> dict[str, Any]:
    """What the model is told, as one plain dict (the user message is rendered from it). `brief`
    is the checked brief (`services/music_lab.clean_brief`).
    """
    return {"model": model, "brief": dict(brief)}


def _list_text(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip())
    return ""


def render_brief(brief: dict[str, Any]) -> str:
    """The brief as the lines of the user message. A field with no value has no line."""
    kind = brief.get("kind")
    lines = [f"Wanted: {_KIND_PHRASES.get(kind, str(kind))}." if isinstance(kind, str) else ""]
    description = str(brief.get("description") or "").strip()
    if description:
        lines.append(f"Description: {_one_line(description)}")
    if genre := _list_text(brief.get("genre")):
        lines.append(f"Story genre: {genre}")
    if tone := _list_text(brief.get("tone")):
        lines.append(f"Story tone: {tone}")
    if era := str(brief.get("era") or "").strip():
        lines.append(f"Era or time period: {_one_line(era)}")
    arc = [
        f"{label} {_one_line(str(brief[key]))}"
        for key, label in (
            ("mood_start", "starts"),
            ("mood_middle", "then"),
            ("mood_end", "ends"),
        )
        if str(brief.get(key) or "").strip()
    ]
    if arc:
        lines.append("Scene mood: " + "; ".join(arc))
    if goal := str(brief.get("dramatic_goal") or "").strip():
        lines.append(f"Dramatic goal of the scene: {_one_line(goal)}")
    if place := str(brief.get("place") or "").strip():
        lines.append(f"Place: {_one_line(place)}")
    if event := str(brief.get("sound_event") or "").strip():
        lines.append(f"Sound event: {_one_line(event)}")
    duration = brief.get("duration_s")
    lines.append(
        f"Length: about {duration:g} seconds."
        if isinstance(duration, int | float)
        else "Length: not specified."
    )
    if brief.get("under_narration") is True:
        lines.append("Under narration: yes. " + UNDER_NARRATION_RULE)
    language = str(brief.get("language") or "").strip()
    if kind == "song":
        lines.append(f"Sung language: {language or 'English'}")
        if voice := str(brief.get("voice_note") or "").strip():
            lines.append(f"Voice: {_one_line(voice)}")
        lyrics = str(brief.get("lyrics") or "").strip()
        theme = str(brief.get("lyrics_theme") or "").strip()
        if lyrics:
            lines.append("Lyrics supplied (keep these words):\n" + lyrics)
        elif theme:
            lines.append(f"Lyrics theme (write the lyrics): {_one_line(theme)}")
        else:
            lines.append("Lyrics: none given. Write them from the description.")
    return "\n".join(line for line in lines if line)


def _system_prompt(profile: MusicPromptProfile) -> str:
    return "\n".join(
        [
            f"You write the prompt fields for {profile.model_name}, a music and sound model. "
            f"{profile.intro} An author tries ideas by hand in a lab and gives you a brief. "
            "You write the fields for one piece of audio, in the form this model understands.",
            "",
            profile.prompt_rules,
            "",
            "Example (from an unrelated story; do not reuse its content):",
            "Request:",
            render_brief(dict(profile.example_inputs)),
            "Answer:",
            profile.example_answer,
            "",
            profile.answer_instruction,
        ]
    )


def build_request(
    inputs: dict[str, Any], *, model: str, profile: MusicPromptProfile
) -> dict[str, Any]:
    """The exact request body sent to the language model (`model` is its name). Nothing about
    the call is hidden from the job record: this body is stored on the job (`job.input.request`).
    """
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt(profile)},
            {
                "role": "user",
                "content": render_brief(inputs["brief"]) + "\n\nWrite the fields now.",
            },
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- Reading the answer -------------------------------------------------------------------


def parse_answer(content: str, profile: MusicPromptProfile) -> dict[str, Any]:
    """The model's answer as a dict. Raises ValueError, with a message fit for the user, when it
    is empty, not JSON, or leaves out a field the model cannot do without.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    if not isinstance(answer, dict):
        raise ValueError("The model's answer was not a JSON object.")
    fields = music_models.coerce_fields(profile.model, answer)
    for spec in music_models.field_specs(profile.model):
        if spec.required and not fields[spec.name]:
            raise ValueError(f'The model\'s answer had no "{spec.name}" text.')
    return answer


@dataclass(frozen=True)
class CheckedFields:
    """The fields after the checks, with the warnings they earned."""

    fields: dict[str, Any]
    warnings: tuple[str, ...]


def _main_text(model: MusicModel, fields: dict[str, Any]) -> str:
    """The field that describes the sound: the caption for ACE-Step, the style for YuE2."""
    name = {"ace-step-1.5": "caption", "yue2": "style"}.get(model, "prompt")
    return str(fields.get(name) or "")


def _duration_from_brief(model: MusicModel, brief: dict[str, Any]) -> float | None:
    """The brief's length, held to what the model can make, or None when the brief has none."""
    wanted = brief.get("duration_s")
    if isinstance(wanted, bool) or not isinstance(wanted, int | float):
        return None
    low, high = music_models.MIN_DURATION_S[model], music_models.MAX_DURATION_S[model]
    if low is not None:
        wanted = max(wanted, low)
    if high is not None:
        wanted = min(wanted, high)
    return float(wanted)


def check_fields(
    answer: dict[str, Any], brief: dict[str, Any], profile: MusicPromptProfile
) -> CheckedFields:
    """The answer's fields coerced and checked. Warnings never block them: a caption over the
    limit or a duration the model cannot make is still returned, and is refused only when a run
    is started with it.
    """
    model = profile.model
    fields = music_models.coerce_fields(model, answer)

    # What the code knows better than the model: whether the piece is sung, and its length.
    kind = brief.get("kind")
    if model == "ace-step-1.5":
        fields["instrumental"] = kind != "song"
        if fields["instrumental"] and not fields["lyrics"]:
            fields["lyrics"] = "[Instrumental]"
    if "duration" in fields and fields["duration"] is None:
        fields["duration"] = _duration_from_brief(model, brief)

    warnings = music_models.field_problems(model, fields)
    main = _main_text(model, fields)
    warnings += [rule.message for rule in profile.rules if rule.pattern.search(main)]

    lyrics = str(fields.get("lyrics") or "")
    if model == "ace-step-1.5":
        if _TWO_MODIFIERS.search(lyrics):
            warnings.append(
                "A lyrics tag has two modifiers. ACE-Step takes at most one, such as "
                "[Chorus - anthemic]."
            )
        if kind == "song" and lyrics and not _LYRIC_TAG.search(lyrics):
            warnings.append("The lyrics have no section tags such as [Verse 1] or [Chorus].")
    elif model == "yue2":
        if not STYLE_STARTS_WITH_LANGUAGE.search(main):
            warnings.append("The style does not start with a language (for example English, …).")
        if "\n" in main:
            warnings.append("The style has line breaks. YuE2 wants one line.")
        if not _LYRIC_TAG.search(lyrics):
            warnings.append("The lyrics have no section tags such as [Verse] or [Chorus].")
        elif len(_LYRIC_TAG.findall(lyrics)) > 1 and "\n\n" not in lyrics:
            warnings.append("The lyrics need a blank line between sections.")
    elif model == "stable-audio-3":
        if "TrackType:" not in main:
            warnings.append("The prompt has no TrackType tag (Music, Instrument or SFX).")
    elif model == "stable-audio-open" and len(main.split()) > _SAO_MAX_WORDS:
        warnings.append(
            f"The prompt has {len(main.split())} words. Stable Audio Open works best with a "
            "short, concrete one."
        )

    if kind in ("sfx", "ambience") and MUSIC_WORDS.search(main):
        warnings.append(
            "The prompt mentions music, but this is a sound effect or an ambience. It may "
            "come out musical."
        )
    return CheckedFields(fields=fields, warnings=tuple(warnings))
