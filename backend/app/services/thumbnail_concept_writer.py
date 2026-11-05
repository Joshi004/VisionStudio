"""The thumbnail concepts: the instructions to the vision model, and the checks of what it wrote.

Pure functions, no I/O.

One call per run reads the Story Bible's description of the video, the scene titles, the people
who may appear (with the looks each can wear) and, when a render exists, a few frames of it. It
answers exactly four **different** thumbnail concepts. Each says what the picture shows, where
the empty area for the headline is, the headline itself, and which people (none, or one or two)
appear and how. Code then draws the picture from the concept (`services/thumbnails.py`) and
draws the headline (`services/thumbnail_compose.py`); the model never draws anything.

The stored content is `{"concepts": [...]}`; see `check_content`. The same checks run on a
version the owner edits by hand, so a manual version can never hold a concept the picture step
cannot draw.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Final

from app.services import user_feedback
from app.services.graphic_theme_writer import bible_for_model
from app.services.music_bible_writer import parse_answer as parse_answer
from app.services.text_limits import fit_text, length_rule

CONCEPT_COUNT: Final = 4
MAX_PEOPLE: Final = 2

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

# Four concepts of about 100 words each, and a vision model's own thinking.
MAX_TOKENS: Final = 6000


# --- The instructions ------------------------------------------------------------------------

_RULES: Final = """\
You are the art director of a video channel. You design the thumbnail of one video: the still \
picture a viewer sees before they press play. You are given a description of the video, its \
scenes, the people who may appear, and sometimes a few frames from the finished video. Other \
programs draw the picture from your answer and write the headline on it. You never draw \
anything.

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
- "background": what is behind and around the main subject, with its colours.
- "mood": a few words for the feeling and the colours.
- "headline": the words written on the thumbnail by a program. At most {headline_words} words \
and {headline_chars} characters, in the language of the video. Short, punchy and readable on a \
phone. It must not say anything the video does not deliver.
- "text_area": where the headline goes, one of "{areas}". The picture leaves that area empty \
and plain, so the composition must keep the main subject out of it.
- "people": the people who appear in the picture, as a list of at most {max_people} items, or \
an empty list when nobody appears. Each item is {{"id", "look", "expression", "pose"}}. "id" is \
the id of a person from PEOPLE and "look" is one of the looks listed for that person. Only the \
people listed in PEOPLE may appear, and each person at most once. "expression" is the face, \
"pose" is the body and the framing, in a few words.
- "people_reason": one short sentence on why these people appear, or why nobody does.

DECIDING WHO APPEARS
Decide for each concept on its own whether a person helps. A face with a clear emotion is often \
the strongest thumbnail, but a concept about an object, a place or a result can be stronger with \
nobody in it. Use at least one concept with nobody and one with a person when PEOPLE is not \
empty. Never use more than {max_people} people in a picture: faces get too small. When PEOPLE is \
empty, every "people" list is empty. Use the look that fits the concept, from the looks listed \
for that person.

The frames, when given, show what the video really looks like. Match its style and what it \
really shows, and do not copy a frame as it is.

{feedback}

{length_rule}"""

_SHAPE: Final = """{"concepts": [{"label": "Reaction close-up", "idea": "...", \
"composition": "...", "background": "...", "mood": "...", "headline": "...", \
"text_area": "left", "people": [{"id": "...", "look": "default", "expression": "...", \
"pose": "..."}], "people_reason": "..."}, ... exactly four items ...]} (the values here only \
show the form, never copy them)"""


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
    scene_titles: list[str],
    cast: list[dict[str, Any]],
) -> dict[str, Any]:
    """What the model is told about the video, as one dict. `cast` is what
    `services/thumbnail_concepts.CastOption.for_model` gives for each person."""
    return {
        "video": bible_for_model(bible),
        "orientation": orientation,
        "scenes": scene_titles,
        "people": cast,
    }


def build_request(
    context: dict[str, Any],
    frame_jpegs: list[bytes],
    *,
    model: str,
    feedback: user_feedback.Feedback | None = None,
) -> dict[str, Any]:
    """The exact request body of the one call. The frames are sent as `image_url` parts of the
    user message (the OpenAI chat format Bitdeer follows); use `without_frames` for the copy
    that is stored on the job.
    """
    parts = [
        "VIDEO AND PEOPLE (JSON):\n" + json.dumps(context, ensure_ascii=False, indent=1),
    ]
    if frame_jpegs:
        parts.append(
            f"The next {len(frame_jpegs)} pictures are frames of the finished video, "
            "in order of time."
        )
    else:
        parts.append("There are no frames of the video yet. Work from the description.")
    if feedback is not None:
        parts += user_feedback.blocks(feedback, "PREVIOUS CONCEPTS")
    content: list[dict[str, Any]] = [{"type": "text", "text": "\n\n".join(parts)}]
    for jpeg in frame_jpegs:
        encoded = base64.b64encode(jpeg).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}
        )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _instructions()},
            {"role": "user", "content": content},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
    }


def without_frames(body: dict[str, Any]) -> dict[str, Any]:
    """`body` with the frames' bytes replaced by a note, to keep on the job record."""
    messages: list[dict[str, Any]] = []
    for message in body["messages"]:
        content = message.get("content")
        if isinstance(content, list):
            content = [
                {"type": "image_url", "image_url": {"url": "(a frame, left out)"}}
                if part.get("type") == "image_url"
                else part
                for part in content
            ]
        messages.append({**message, "content": content})
    return {**body, "messages": messages}


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


def check_content(
    answer: dict[str, Any],
    looks_of: dict[str, set[str]],
    *,
    require_headline: bool = True,
) -> dict[str, Any]:
    """The concepts of `answer` as the stored content `{"concepts": [...]}`, or ValueError with
    a message fit for the user and for the model's corrected retry.

    `looks_of` maps each person who may appear to the look slugs they may wear. A manual edit
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
                "people_reason": _text(
                    item.get("people_reason"), f"{where}.people_reason", REASON_MAX_CHARS
                ),
            }
        )
    return {"concepts": concepts}
