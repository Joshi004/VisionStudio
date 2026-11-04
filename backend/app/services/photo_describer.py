"""Describing a photo with a vision model (the `describe_photo` job).

The owner gives a reference photo of a character or of an outfit, and the model writes the text
boxes the owner would otherwise type:

- mode `character`: `appearance` (the features that never change), `outfit` (what is worn) and
  `personality` (only what the photo shows, such as posture and expression), for a new
  character in the Character Lab;
- mode `outfit`: `description` (what is worn), and a suggested `name` and short `note`, for a
  new outfit of a character.

The model is the Bitdeer one of the `vision_llm_model` setting. The photo is sent as a data URL
in an `image_url` part of the user message (the OpenAI chat format Bitdeer follows). Nothing
here reads the database: `jobs/describe_photo.py` loads the picture and saves the answer.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any, Final

from PIL import Image

from app.providers import llm

MODE_CHARACTER: Final = "character"
MODE_OUTFIT: Final = "outfit"
MODES: Final = (MODE_CHARACTER, MODE_OUTFIT)

# The longest side the photo is sent at, and the most bytes of JPEG before base64. A 1 MB
# request body is the largest the Bitdeer endpoint is known to accept for an image.
MAX_SIDE_PX: Final = 1024
MAX_JPEG_BYTES: Final = 700_000
_JPEG_QUALITIES: Final = (85, 75, 65, 55, 45)

MAX_TOKENS: Final = 4000

# The same limits as the boxes the answer fills (`character_library`, `character_outfits`).
APPEARANCE_MAX_CHARS: Final = 2000
CHARACTER_OUTFIT_MAX_CHARS: Final = 500
PERSONALITY_MAX_CHARS: Final = 1000
OUTFIT_DESCRIPTION_MAX_CHARS: Final = 300
OUTFIT_NAME_MAX_CHARS: Final = 60
OUTFIT_NOTE_MAX_CHARS: Final = 120

_COMMON_RULES = """\
Describe only what is visible in the photo. Do not say who the person is, do not guess a name, \
and do not describe the background. Write plain sentences, no lists and no markdown. Answer \
with one JSON object only."""

_CHARACTER_PROMPT = f"""\
You read a reference photo of a person or character and fill in a character card for a video \
studio.

{_COMMON_RULES}

Fields:
- "appearance" (required, at most {APPEARANCE_MAX_CHARS} characters): the features that never \
change: face, hair, skin, build, height impression, age impression. Not the clothes.
- "outfit" (at most {CHARACTER_OUTFIT_MAX_CHARS} characters): what the character wears in the \
photo, item by item, with colours and materials. An empty string when no clothes are visible.
- "personality" (at most {PERSONALITY_MAX_CHARS} characters): only what the photo shows, such \
as posture, expression and manner. An empty string when the photo shows nothing of it.

Answer in exactly this form: {{"appearance": "...", "outfit": "...", "personality": "..."}}"""

_OUTFIT_PROMPT = f"""\
You read a reference photo and describe the outfit worn in it, for a video studio that draws \
the same character in different clothes.

{_COMMON_RULES}

Fields:
- "description" (required, at most {OUTFIT_DESCRIPTION_MAX_CHARS} characters): what is worn, \
item by item, with colours and materials, including shoes and accessories when visible. Do \
not describe the person's face, hair or body.
- "name" (required, at most {OUTFIT_NAME_MAX_CHARS} characters): a short title, such as \
"Navy blazer".
- "note" (at most {OUTFIT_NOTE_MAX_CHARS} characters): a few words on when it suits, such as \
"formal, for news segments". An empty string when nothing fits.

Answer in exactly this form: {{"description": "...", "name": "...", "note": "..."}}"""


class PhotoError(ValueError):
    """A photo that cannot be sent, or an answer that cannot be used. The message is fit for
    the user.
    """


def prepare_photo(path: Path) -> bytes:
    """The photo at `path` as JPEG bytes, flattened onto white and shrunk to fit the request.

    Raises PhotoError when the file cannot be read or cannot be made small enough.
    """
    try:
        with Image.open(path) as image:
            image.load()
            rgba = image.convert("RGBA")
    except (OSError, ValueError) as exc:
        raise PhotoError(f"The photo could not be read: {exc}") from None
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    picture = Image.alpha_composite(white, rgba).convert("RGB")
    picture.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    for quality in _JPEG_QUALITIES:
        buffer = io.BytesIO()
        picture.save(buffer, "JPEG", quality=quality)
        if buffer.tell() <= MAX_JPEG_BYTES:
            return buffer.getvalue()
    raise PhotoError("The photo is too detailed to send. Use a smaller or simpler photo.")


def build_request(jpeg: bytes, mode: str, *, model: str) -> dict[str, Any]:
    """The request body sent to the model, photo included."""
    if mode not in MODES:
        raise PhotoError(f"Unknown mode '{mode}'.")
    encoded = base64.b64encode(jpeg).decode("ascii")
    system = _CHARACTER_PROMPT if mode == MODE_CHARACTER else _OUTFIT_PROMPT
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                    },
                    {"type": "text", "text": "Describe this photo as instructed."},
                ],
            },
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def without_photo(body: dict[str, Any]) -> dict[str, Any]:
    """`body` with the photo's bytes replaced by a note, to keep on the job record: the photo
    itself is a lab image, so it is not copied into the job.
    """
    messages: list[dict[str, Any]] = []
    for message in body["messages"]:
        content = message.get("content")
        if isinstance(content, list):
            content = [
                {"type": "image_url", "image_url": {"url": "(the photo, left out)"}}
                if part.get("type") == "image_url"
                else part
                for part in content
            ]
        messages.append({**message, "content": content})
    return {**body, "messages": messages}


def _cut(text: str, limit: int) -> str:
    """`text` cut at a word boundary to at most `limit` characters."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip()


def _text(answer: dict[str, Any], key: str, limit: int, *, required: bool) -> str:
    value = answer.get(key)
    text = " ".join(value.split()) if isinstance(value, str) else ""
    if required and text == "":
        raise PhotoError(f'The model\'s answer has no "{key}".')
    return _cut(text, limit)


def check_answer(content: str, mode: str) -> dict[str, str]:
    """The model's answer as the fields of `mode`, each cut to its limit. Raises PhotoError."""
    try:
        answer = llm.parse_json_object(content)
    except ValueError as exc:
        raise PhotoError(str(exc)) from None
    if not isinstance(answer, dict):
        raise PhotoError("The model's answer was not a JSON object.")
    if mode == MODE_CHARACTER:
        return {
            "appearance": _text(answer, "appearance", APPEARANCE_MAX_CHARS, required=True),
            "outfit": _text(answer, "outfit", CHARACTER_OUTFIT_MAX_CHARS, required=False),
            "personality": _text(answer, "personality", PERSONALITY_MAX_CHARS, required=False),
        }
    return {
        "description": _text(answer, "description", OUTFIT_DESCRIPTION_MAX_CHARS, required=True),
        "name": _text(answer, "name", OUTFIT_NAME_MAX_CHARS, required=True),
        "note": _text(answer, "note", OUTFIT_NOTE_MAX_CHARS, required=False),
    }
