"""Finding the characters and the places of a script with a language model. Pure functions, no I/O.

The model reads the whole script once and lists who and what the story needs to show, each with
a description that an artist (and the image model) can draw from. The list becomes the project's
cast (`services/cast.py`): every character and place gets one reference picture, and every scene
that shows one is made from that picture, so it looks the same each time.

1. `build_request`: the rules, the author's style and instructions, and the script, as an
   OpenAI-style chat request.
2. `parse_answer`: the model's JSON, read defensively and cleaned.

The call is made by `providers/llm.py` and the job that drives it is `jobs/extract_cast.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from app.providers import llm

# Hidden reasoning tokens are billed as output (ANALYSIS.md Section 6.2, rule 4), so the answer
# is capped. Twenty entries of about 100 words are a few thousand tokens.
MAX_TOKENS: Final = 16000
REASONING_EFFORT: Final = "high"

MAX_CHARACTERS: Final = 12
MAX_LOCATIONS: Final = 10
NAME_MAX_CHARS: Final = 80
TEXT_MAX_CHARS: Final = 2000
NOTE_MAX_CHARS: Final = 400

_SYSTEM_PROMPT: Final = "\n".join(
    [
        "You read the script of a narrated video and list the characters and the places of its "
        "story. An artist then draws each of them once, and every scene that shows one is made "
        "from that picture, so every entry must say how its character or place looks, in a way "
        "that can be drawn.",
        "",
        "Rules:",
        "1. A character is a person, god, animal or creature that the story follows and that "
        "can be shown on screen. A place is a setting where the story happens, such as a "
        "palace, a forest or a city. Never list an idea, a crowd of unnamed people or an object.",
        "2. List only what the script names or clearly describes, and only the {max_characters} "
        "characters and the {max_locations} places that matter most. List each one once: merge "
        "the names, titles and nicknames of one character into one entry, under the name the "
        "script uses most.",
        '3. "appearance" is 40 to 90 words, in one paragraph and in the present tense, and says '
        "only what a picture shows. For a character: apparent age, build, skin tone, face, hair, "
        "clothing with its colours and materials, jewellery, and anything the character always "
        "carries. For a place: the kind of building or landscape, its materials and colours, the "
        "light and the time of day, the mood. A place is empty: no people in it. Use what the "
        "script says. Where it leaves the look open, choose a concrete look that fits the story, "
        "its setting and its period. Never name another character, and do not describe events.",
        '4. "personality" (characters only) is one or two sentences on how the character '
        "carries themselves: bearing, temperament, expression.",
        '5. "voice" (characters only) is a few words on how the character would sound. It is '
        "only a note: no character speaks in this video, because a narrator tells the whole "
        "story.",
        "6. Write everything in English, whatever language the script is in, but keep each name "
        "as the script writes it.",
        "7. If the story has no characters, or no places, return an empty list for it.",
        "",
        "Answer with a JSON object only, in exactly this form:",
        '{{"characters": [{{"name": "...", "appearance": "...", "personality": "...", '
        '"voice": "..."}}], "locations": [{{"name": "...", "appearance": "..."}}]}}',
    ]
)


@dataclass(frozen=True)
class CastCharacter:
    name: str
    appearance: str
    personality: str | None
    voice: str | None


@dataclass(frozen=True)
class CastLocation:
    name: str
    appearance: str


@dataclass(frozen=True)
class CastList:
    """What the model found, cleaned: no blank or repeated names, within the limits."""

    characters: list[CastCharacter]
    locations: list[CastLocation]


def build_request(
    script: str,
    *,
    model: str,
    style: str | None,
    instructions: str | None,
) -> dict[str, Any]:
    """The exact request body sent to the model. Nothing about the call is hidden from the
    job record: this body is stored on the job (`job.input.request`).
    """
    system = _SYSTEM_PROMPT.format(max_characters=MAX_CHARACTERS, max_locations=MAX_LOCATIONS)
    user = ""
    if style and style.strip():
        user += f"Style of the whole video (let it guide the looks): {style.strip()}\n\n"
    if instructions and instructions.strip():
        user += (
            "Author's instructions for the video (use what concerns the characters and "
            f"places):\n{instructions.strip()}\n\n"
        )
    user += f"Script:\n\n{script.strip()}"
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- Reading the answer ---------------------------------------------------------------


def _text(value: object, limit: int) -> str | None:
    """One line of text, cut at `limit`, or None when it is not text or is blank."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:limit].rstrip() or None


def _entries(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def parse_answer(content: str) -> CastList:
    """The cast in the model's answer. Raises ValueError, with a message fit for the user, when
    the answer is empty, is not JSON, or holds neither list. An answer with two empty lists is
    a usable answer: the story has no cast.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    if not isinstance(answer, dict) or not (
        isinstance(answer.get("characters"), list) or isinstance(answer.get("locations"), list)
    ):
        raise ValueError('The model\'s answer had no "characters" or "locations" list.')

    characters: list[CastCharacter] = []
    seen: set[str] = set()
    for item in _entries(answer.get("characters")):
        name = _text(item.get("name"), NAME_MAX_CHARS)
        appearance = _text(item.get("appearance"), TEXT_MAX_CHARS)
        if name is None or appearance is None or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        characters.append(
            CastCharacter(
                name=name,
                appearance=appearance,
                personality=_text(item.get("personality"), NOTE_MAX_CHARS),
                voice=_text(item.get("voice"), NOTE_MAX_CHARS),
            )
        )

    locations: list[CastLocation] = []
    seen = set()
    for item in _entries(answer.get("locations")):
        name = _text(item.get("name"), NAME_MAX_CHARS)
        appearance = _text(item.get("appearance"), TEXT_MAX_CHARS)
        if name is None or appearance is None or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        locations.append(CastLocation(name=name, appearance=appearance))

    had_entries = bool(_entries(answer.get("characters")) or _entries(answer.get("locations")))
    if had_entries and not characters and not locations:
        raise ValueError("None of the entries in the model's answer could be used.")
    return CastList(characters=characters[:MAX_CHARACTERS], locations=locations[:MAX_LOCATIONS])
