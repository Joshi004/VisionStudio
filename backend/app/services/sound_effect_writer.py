"""Writing the prompt of one of a continuous explainer's two sound effects with a language model
(EXM-006, XM-9). Pure functions, no I/O.

A project has two sounds, one for graphic shots (`graphic`) and one for evidence (`evidence`),
made by Stable Audio 3 (kind `sfx`). The model writes one prompt for one sound from the Story
Bible's tone and, when music is on, the palette of the Music Bible, so the sound does not clash
with the score. Code holds the rest: the sound must be short and soft, and the answer is checked
here.

1. `build_request`: the instructions and the context, as an OpenAI-style chat request.
2. `build_feedback_request`: the same, with a rejected prompt, what was measured and the owner's
   note (MD-23). It asks for one new prompt.
3. `check_answer`: the model's JSON, read defensively. Raises ValueError with a message fit for
   the user (the corrected retry of `jobs/llm_call.py` sends it back to the model).

The call is made by `providers/llm.py` and the job that drives it is
`jobs/write_sound_effect.py`.
"""

from __future__ import annotations

import json
from typing import Any, Final

from app.providers import llm
from app.services import music_models
from app.services.music_plan_writer import request_body
from app.services.music_prompt_profiles import (
    MUSIC_WORDS,
    STABLE_AUDIO_3,
    VOCAL_WORDS,
)

ROLE_GRAPHIC: Final = "graphic"
ROLE_EVIDENCE: Final = "evidence"
ROLES: Final[tuple[str, ...]] = (ROLE_GRAPHIC, ROLE_EVIDENCE)

LABELS: Final[dict[str, str]] = {
    ROLE_GRAPHIC: "Graphic sound",
    ROLE_EVIDENCE: "Evidence sound",
}

MODEL: Final[music_models.MusicModel] = "stable-audio-3"
LAB_KIND: Final[music_models.MusicKind] = "sfx"

# A sound effect is short (XM-10, subtle). The length asked for is held to this range.
MIN_DURATION_S: Final = 0.5
MAX_DURATION_S: Final = 1.5

PROMPT_START: Final = "TrackType: SFX"
NOTE_MAX_CHARS: Final = 1000

_WHAT: Final[dict[str, str]] = {
    ROLE_GRAPHIC: (
        "a soft, short whoosh that plays as an animated graphic (a chart, a diagram or a title "
        "card) appears on the screen"
    ),
    ROLE_EVIDENCE: (
        "a soft, light paper-like swish that plays as a document, a screenshot or a source "
        "appears on the screen"
    ),
}

_RULES: Final = f"""Rules:
1. The sound is subtle. It plays well under a speaking voice, so it must be soft, short and \
clean. It is heard without being noticed.
2. Length: {MIN_DURATION_S:g} to {MAX_DURATION_S:g} seconds. The sound starts at once (no \
silence at the start), has one clear loudest moment in its first half, and dies away naturally \
(it is not cut off while loud).
3. It has no tonal content: no pitched notes, no melody, no chord, no drone, no musical \
rhythm. It must not clash with any key or tempo the music plays in. It has no voice.
4. Write the prompt for Stable Audio 3, in English, at most 2,000 characters. It starts with \
"{PROMPT_START}", then says what makes the sound, how it is triggered and how it sounds (its \
texture, softness and movement), in concrete physical words. Never ask for music. The \
"duration" is the length in seconds.
5. The story's tone and the music's palette (when given) tell you how bright or dark the room \
is. Use them for the texture of the sound only, never to add notes or rhythm."""

_ANSWER: Final = (
    'Answer with one JSON object only, in exactly this form: {"prompt": "...", "duration": 1.0}'
)

_FEEDBACK_RULES: Final = """

The owner rejected a take made from an earlier prompt. You are given that prompt, what was \
measured in the rejected sound (as sentences, because you cannot hear it) and the owner's note. \
Write one new prompt that fixes what the note says and keeps every rule above. It must not be \
the rejected prompt."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def _system_prompt(role: str, *, feedback: bool) -> str:
    profile = STABLE_AUDIO_3
    text = "\n".join(
        [
            f"You write the prompt for one sound effect of a video explainer, for "
            f"{profile.model_name}. {profile.intro}",
            "",
            f"The sound wanted: {_WHAT[role]}.",
            "",
            _RULES,
            "",
            _ANSWER,
        ]
    )
    return text + _FEEDBACK_RULES if feedback else text


def context(story_bible: dict[str, Any], music_bible: dict[str, Any] | None) -> dict[str, Any]:
    """What the model reads: the Story Bible's genre, tone and visual style, and the palette of
    the Music Bible (its instruments, tempo and key, and what it avoids) when music is on. Pure.
    """
    result: dict[str, Any] = {
        "story": {
            "genre": story_bible.get("genre"),
            "tone": story_bible.get("tone"),
            "visual_style": story_bible.get("visual_style"),
        }
    }
    if isinstance(music_bible, dict):
        world = music_bible.get("sound_world")
        feel = music_bible.get("musical_feel")
        palette: dict[str, Any] = {}
        if isinstance(world, dict):
            palette["instruments"] = world.get("instruments")
            palette["avoid"] = world.get("avoid")
        if isinstance(feel, dict):
            palette["tempo"] = feel.get("tempo")
            palette["mode_leaning"] = feel.get("mode_leaning")
        if palette:
            result["music_palette"] = palette
    return result


def build_request(role: str, material: dict[str, Any], *, model: str) -> dict[str, Any]:
    """The exact request body of the call that writes a sound's prompt. It is stored on the
    job (`job.input.request`).
    """
    user = "CONTEXT:\n" + _json(material) + "\n\nWrite the prompt now."
    return request_body(_system_prompt(role, feedback=False), user, model)


def build_feedback_request(
    role: str,
    material: dict[str, Any],
    *,
    rejected_fields: dict[str, Any],
    facts: list[str],
    note: str,
    model: str,
) -> dict[str, Any]:
    """The exact request body of the call that rewrites a rejected take's prompt. It asks for
    one prompt.
    """
    rejected = {key: rejected_fields.get(key) for key in ("prompt", "duration")}
    user = (
        "CONTEXT:\n"
        + _json(material)
        + "\n\nTHE REJECTED TAKE:\n"
        + _json({"prompt_fields": rejected, "measured_facts": facts, "owner_note": note})
        + "\n\nWrite the new prompt now."
    )
    return request_body(_system_prompt(role, feedback=True), user, model)


def parse_answer(content: str) -> dict[str, Any]:
    """The model's answer as a dict. Raises ValueError when it is empty or not a JSON object."""
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    if not isinstance(answer, dict):
        raise ValueError("The model's answer was not a JSON object.")
    return answer


def _normal(text: str) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in text).split())


def check_answer(
    answer: dict[str, Any], *, rejected_fields: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The prompt fields to send, `{prompt, duration}`. The prompt starts with the SFX tag,
    does not ask for music or a voice, and fits the model's limit; the duration is within the
    sound's range; a rewrite is not the rejected prompt once case and punctuation are ignored.
    Raises ValueError, with a message fit for the user.
    """
    fields = music_models.coerce_fields(MODEL, answer)
    prompt = str(fields.get("prompt") or "")
    duration = fields.get("duration")
    if not prompt:
        raise ValueError('The model\'s answer had no "prompt" text.')
    if not prompt.startswith(PROMPT_START):
        raise ValueError(f'The prompt must start with "{PROMPT_START}".')
    if MUSIC_WORDS.search(prompt):
        raise ValueError(
            "The prompt mentions music (music, melody, song, beat, soundtrack or score). "
            "A sound effect must not ask for music."
        )
    if VOCAL_WORDS.search(prompt):
        raise ValueError("The prompt asks for a voice. A sound effect has no voice.")
    if duration is None:
        raise ValueError('The model\'s answer had no "duration".')
    if not MIN_DURATION_S <= duration <= MAX_DURATION_S:
        raise ValueError(
            f"The duration must be between {MIN_DURATION_S:g} and {MAX_DURATION_S:g} seconds."
        )
    problems = music_models.field_problems(MODEL, fields)
    if problems:
        raise ValueError(" ".join(problems))
    if rejected_fields is not None and _normal(prompt) == _normal(
        str(rejected_fields.get("prompt") or "")
    ):
        raise ValueError(
            "The new prompt is the rejected one: write one that changes what the note asks."
        )
    return {"prompt": prompt, "duration": round(float(duration), 2)}
