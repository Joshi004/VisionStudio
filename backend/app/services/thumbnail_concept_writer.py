"""The thumbnail concepts: the instructions to the model, and the checks of what it wrote.

Pure functions, no I/O.

One call per run reads the whole script of the video (the main source), the Story Bible's short
description of it, the scene titles, the people who may appear (with the looks each can wear) and,
for a story, the places that may appear. It never sees a picture: the model is the story role's
text model (YTF-006). It answers exactly four **different** thumbnail concepts. Each says what the
picture shows, where the empty area for the headline is, the headline itself, which person (none
or one) appears and how, and which place (none or one) is the setting. Code then draws the
picture from the concept (`services/thumbnails.py`, which gives the image model the person's look
picture and the place's picture as references) and draws the headline
(`services/thumbnail_compose.py`); the model never draws anything.

The stored content is `{"concepts": [...]}`; see `check_content`. The same checks run on a
version the owner edits by hand, so a manual version can never hold a concept the picture step
cannot draw.
"""

from __future__ import annotations

import json
from typing import Any, Final

from app.services import user_feedback
from app.services.graphic_theme_writer import bible_for_model
from app.services.music_bible_writer import parse_answer as parse_answer
from app.services.text_limits import fit_text, length_rule

CONCEPT_COUNT: Final = 4
MAX_PEOPLE: Final = 1

# Where the headline goes. The picture is asked to leave this area empty and plain.
TEXT_AREAS: Final[tuple[str, ...]] = (
    "left",
    "right",
    "top",
    "bottom",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
)

HEADLINE_MAX_WORDS: Final = 6
HEADLINE_MAX_CHARS: Final = 40

LABEL_MAX_CHARS: Final = 40
IDEA_MAX_CHARS: Final = 300
COMPOSITION_MAX_CHARS: Final = 300
BACKGROUND_MAX_CHARS: Final = 250
MOOD_MAX_CHARS: Final = 80
EXPRESSION_MAX_CHARS: Final = 100
POSE_MAX_CHARS: Final = 100
REASON_MAX_CHARS: Final = 200

LIMIT_NAMES: Final = {
    "label": LABEL_MAX_CHARS,
    "idea": IDEA_MAX_CHARS,
    "composition": COMPOSITION_MAX_CHARS,
    "background": BACKGROUND_MAX_CHARS,
    "mood": MOOD_MAX_CHARS,
    "headline": HEADLINE_MAX_CHARS,
    "people[].expression": EXPRESSION_MAX_CHARS,
    "people[].pose": POSE_MAX_CHARS,
    "people_reason": REASON_MAX_CHARS,
}

# Four concepts of about 100 words each. The model's reasoning counts against the cap.
MAX_TOKENS: Final = 12_000
REASONING_EFFORT: Final = "high"


# --- The instructions ------------------------------------------------------------------------

_RULES: Final = """\
You are the art director of a video channel. You design the thumbnail of one video: the still \
picture a viewer sees before they press play. You are given the script of the video, a short \
description of it, its scenes, the people who may appear and the places that may appear. Other \
programs draw the picture from your answer and write the headline on it. You never draw \
anything.

WHAT THE VIDEO IS ABOUT
The script is the main source: the thumbnail must show and promise what the script is really \
about. The description of the video (title, subject, tone, visual style) is background that \
tells you the style to keep. When the script is empty, work from the description and the scenes.

WHAT YOU WRITE
Exactly {count} concepts that are clearly DIFFERENT from each other: a different main idea, a \
different composition and a different mood. Do not write one idea four times. For example, one \
may be a close-up of a strong reaction, one a before and after, one the topic itself as the \
hero, one a bold design led by the headline.

Every concept has these fields:
- "label": a short name for the idea.
- "idea": what the thumbnail shows and why a viewer would click, in plain sentences.
- "composition": the shot and where things are: for example "tight close-up of the face on the \
right, subject object large on the left".
- "background": what is behind and around the main subject, with its colours. When a place is \
chosen, it must fit that place.
- "mood": a few words for the feeling and the colours.
- "headline": the words written on the thumbnail by a program. At most {headline_words} words \
and {headline_chars} characters, in the language of the video. Short, punchy and readable on a \
phone. It must not say anything the video does not deliver.
- "text_area": where the headline goes, one of "{areas}". The picture leaves that area empty \
and plain, so the composition must keep the main subject out of it.
- "people": the person who appears in the picture, as a list of at most {max_people} item, or \
an empty list when nobody appears. The item is {{"id", "look", "expression", "pose"}}. "id" is \
the id of a person from PEOPLE and "look" is one of the looks listed for that person. Only the \
people listed in PEOPLE may appear. "expression" is the face, "pose" is the body and the \
framing, in a few words.
- "environment": the id of the one place from PLACES that is the setting of the picture, or \
null when no place is used. Only the places listed in PLACES may be used.
- "people_reason": one short sentence on why this person and this place appear, or why nobody \
does.

DECIDING WHO AND WHAT APPEARS
Decide for each concept on its own what helps. A face with a clear emotion is often the \
strongest thumbnail, but a concept about an object, a place or a result can be stronger with \
nobody in it. Use at least one concept with nobody and one with a person when PEOPLE is not \
empty. Never use more than one person in a picture: faces get too small. Use a place when the \
setting is part of why a viewer would click, not in every concept. When PEOPLE is empty, every \
"people" list is empty, and when PLACES is empty, every "environment" is null. Use the look \
that fits the concept, from the looks listed for that person.

{feedback}

{length_rule}"""

_SHAPE: Final = """{"concepts": [{"label": "Reaction close-up", "idea": "...", \
"composition": "...", "background": "...", "mood": "...", "headline": "...", \
"text_area": "left", "people": [{"id": "...", "look": "default", "expression": "...", \
"pose": "..."}], "environment": null, "people_reason": "..."}, ... exactly four items ...]} \
(the values here only show the form, never copy them)"""


def _instructions() -> str:
    return (
        _RULES.format(
            count=CONCEPT_COUNT,
            headline_words=HEADLINE_MAX_WORDS,
            headline_chars=HEADLINE_MAX_CHARS,
            areas='", "'.join(TEXT_AREAS),
            max_people=MAX_PEOPLE,
            feedback=user_feedback.INSTRUCTION,
            length_rule=length_rule(LIMIT_NAMES),
        )
        + "\n\nAnswer with one JSON object only, in exactly this form: "
        + _SHAPE
    )


def context_for_model(
    bible: dict[str, Any],
    orientation: str,
    script_text: str,
    scene_titles: list[str],
    cast: list[dict[str, Any]],
    places: list[dict[str, Any]],
) -> dict[str, Any]:
    """What the model is told about the video, as one dict. `cast` is what
    `services/thumbnail_concepts.CastOption.for_model` gives for each person and `places` what
    `PlaceOption.for_model` gives for each place. The script is given whole.
    """
    return {
        "video": bible_for_model(bible),
        "orientation": orientation,
        "scenes": scene_titles,
        "people": cast,
        "places": places,
        "script": script_text.strip(),
    }


def build_request(
    context: dict[str, Any],
    *,
    model: str,
    feedback: user_feedback.Feedback | None = None,
) -> dict[str, Any]:
    """The exact request body of the one call. It holds text only and is stored on the job."""
    facts = {key: value for key, value in context.items() if key not in ("script", "scenes")}
    parts = [
        "VIDEO, PEOPLE AND PLACES (JSON):\n" + json.dumps(facts, ensure_ascii=False, indent=1),
        "SCENE TITLES (JSON):\n" + json.dumps(context.get("scenes", []), ensure_ascii=False),
        "SCRIPT:\n" + str(context.get("script", "")),
    ]
    if feedback is not None:
        parts += user_feedback.blocks(feedback, "PREVIOUS CONCEPTS")
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _instructions()},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- Checking what was written ---------------------------------------------------------------


def _text(value: object, path: str, max_chars: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f'The "{path}" was missing or was not text.')
    text = " ".join(value.split())
    if required and not text:
        raise ValueError(f'The "{path}" was empty.')
    return fit_text(text, path, max_chars, None)


def _headline(value: object, path: str, *, required: bool) -> str:
    if not isinstance(value, str):
        raise ValueError(f'The "{path}" was missing or was not text.')
    text = " ".join(value.split())
    if required and not text:
        raise ValueError(f'The "{path}" was empty.')
    if len(text) > HEADLINE_MAX_CHARS:
        raise ValueError(
            f'The "{path}" "{text}" was {len(text)} characters; the most allowed is '
            f"{HEADLINE_MAX_CHARS}."
        )
    if len(text.split()) > HEADLINE_MAX_WORDS:
        raise ValueError(
            f'The "{path}" "{text}" had {len(text.split())} words; the most allowed is '
            f"{HEADLINE_MAX_WORDS}."
        )
    return text


def check_headline(value: object, *, required: bool = False) -> str:
    """A headline the owner typed, on one line, or ValueError with a sentence for the user."""
    return _headline(value, "headline", required=required)


def _people(value: object, path: str, looks_of: dict[str, set[str]]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError(f'The "{path}" was missing or was not a list.')
    if len(value) > MAX_PEOPLE:
        raise ValueError(f'The "{path}" had {len(value)} people; the most allowed is {MAX_PEOPLE}.')
    people: list[dict[str, str]] = []
    seen: set[str] = set()
    for number, item in enumerate(value, start=1):
        where = f"{path}[{number}]"
        if not isinstance(item, dict):
            raise ValueError(f'The "{where}" was not an object.')
        person_id = item.get("id")
        if not isinstance(person_id, str) or person_id not in looks_of:
            raise ValueError(
                f'The "{where}.id" "{person_id}" is not one of the people listed in PEOPLE.'
            )
        if person_id in seen:
            raise ValueError(f'The person "{person_id}" appears twice in "{path}".')
        seen.add(person_id)
        look = item.get("look")
        if not isinstance(look, str) or look not in looks_of[person_id]:
            raise ValueError(
                f'The "{where}.look" "{look}" is not one of the looks listed for "{person_id}".'
            )
        people.append(
            {
                "id": person_id,
                "look": look,
                "expression": _text(
                    item.get("expression"), f"{where}.expression", EXPRESSION_MAX_CHARS
                ),
                "pose": _text(item.get("pose"), f"{where}.pose", POSE_MAX_CHARS),
            }
        )
    return people


def _environment(value: object, path: str, place_ids: set[str]) -> str | None:
    """The place of a concept: None (a missing key, null or an empty text) or the id of one of
    the places that may appear.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value not in place_ids:
        raise ValueError(f'The "{path}" "{value}" is not one of the places listed in PLACES.')
    return value


def check_content(
    answer: dict[str, Any],
    looks_of: dict[str, set[str]],
    place_ids: set[str],
    *,
    require_headline: bool = True,
) -> dict[str, Any]:
    """The concepts of `answer` as the stored content `{"concepts": [...]}`, or ValueError with
    a message fit for the user and for the model's corrected retry.

    `looks_of` maps each person who may appear to the look slugs they may wear, and `place_ids`
    holds the ids of the places that may appear. A manual edit
    passes `require_headline=False`: the owner may leave a headline empty (a thumbnail with no
    text), the model may not.
    """
    items = answer.get("concepts")
    if not isinstance(items, list):
        raise ValueError('The answer had no "concepts" list.')
    if len(items) != CONCEPT_COUNT:
        raise ValueError(f"The answer had {len(items)} concepts; it must have {CONCEPT_COUNT}.")
    concepts: list[dict[str, Any]] = []
    for number, item in enumerate(items, start=1):
        where = f"concepts[{number}]"
        if not isinstance(item, dict):
            raise ValueError(f'The "{where}" was not an object.')
        area = item.get("text_area")
        if not isinstance(area, str) or area not in TEXT_AREAS:
            raise ValueError(
                f'The "{where}.text_area" "{area}" must be one of "'
                + '", "'.join(TEXT_AREAS)
                + '".'
            )
        people = _people(item.get("people"), f"{where}.people", looks_of)
        concepts.append(
            {
                "label": _text(item.get("label"), f"{where}.label", LABEL_MAX_CHARS),
                "idea": _text(item.get("idea"), f"{where}.idea", IDEA_MAX_CHARS),
                "composition": _text(
                    item.get("composition"), f"{where}.composition", COMPOSITION_MAX_CHARS
                ),
                "background": _text(
                    item.get("background"), f"{where}.background", BACKGROUND_MAX_CHARS
                ),
                "mood": _text(item.get("mood"), f"{where}.mood", MOOD_MAX_CHARS),
                "headline": _headline(
                    item.get("headline"), f"{where}.headline", required=require_headline
                ),
                "text_area": area,
                "people": people,
                "environment": _environment(
                    item.get("environment"), f"{where}.environment", place_ids
                ),
                "people_reason": _text(
                    item.get("people_reason"), f"{where}.people_reason", REASON_MAX_CHARS
                ),
            }
        )
    return {"concepts": concepts}
