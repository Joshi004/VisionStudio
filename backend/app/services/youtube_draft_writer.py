"""The YouTube publish draft: the instructions to the model, and the checks of what it wrote
(YT-003, `YouTube_publish_phases.md` §4.5).

Pure functions, no I/O.

One call reads the Story Bible, the script, the scene titles and what the render is (story or
explainer, orientation, length, whether YouTube will show it as a Short), and answers the title,
the description (without hashtags), the hashtags (lowercase) and the tags. The two declarations
("made for kids", "contains realistic AI content") are not drafted: the panel has fixed defaults
(YTF-002).

The same checks (`check_fields`, `check_tags`) are used for the model's answer and for the
owner's edit, so a draft that is stored never breaks a YouTube limit. The stored content is
`{title, description, hashtags, tags}`; see `check_content`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Final

from app.services import graphic_theme_writer, user_feedback
from app.services.music_bible_writer import parse_answer as parse_answer
from app.services.project_kinds import KIND_EXPLAINER
from app.services.text_limits import cut_at_word, length_rule

# YouTube's limits (Data API, `videos.insert`). The title counts characters, the description
# counts UTF-8 bytes. Neither may hold `<` or `>`.
TITLE_MAX_CHARS: Final = 100
DESCRIPTION_MAX_BYTES: Final = 5000
# What the model is asked for, and what the owner may keep.
HASHTAGS_MIN_AI: Final = 3
HASHTAGS_MAX: Final = 5
# Tags (`snippet.tags`). YouTube's total is 500 characters, counted by `tags_length`. The model
# is held to a lower total so the owner has room to add some. One tag is limited to 100
# characters: Google's reference gives no limit per tag, so this is a safe assumption (YFQ-3).
TAGS_MIN_AI: Final = 5
TAGS_MAX_AI: Final = 15
TAGS_MAX_CHARS_AI: Final = 400
TAGS_MAX_CHARS: Final = 500
TAG_MAX_CHARS: Final = 100
# A short is a vertical or square video of up to three minutes.
SHORT_MAX_SECONDS: Final = 180

# The script is sent whole up to this many characters; a 10-minute story is about 9,000. Over it
# the script is cut at a whole word, the model is told, and the scene titles give the rest.
SCRIPT_MAX_CHARS: Final = 20_000

# One answer of moderate size. The model's reasoning counts against the cap.
MAX_TOKENS: Final = 12_000
REASONING_EFFORT: Final = "high"

# What the description should aim for, so it stays far under the byte limit.
DESCRIPTION_TARGET_CHARS: Final = 1500

LIMIT_NAMES: Final = {
    "title": TITLE_MAX_CHARS,
    "tags[]": TAG_MAX_CHARS,
}

_HASHTAG = re.compile(r"[A-Za-z0-9_]+")


# --- The instructions ------------------------------------------------------------------------

_RULES: Final = """\
You write the YouTube upload text for one finished video. You are given the Story Bible of the \
video, its script, the titles of its scenes, and facts about the finished video. The owner reads \
and edits everything you write before it goes anywhere. Write in English.

THE TITLE
- "title" is the title viewers see. It is at most {title_max} characters, with no "<" or ">". \
Make it clear, honest and curious, and put the most important words first. Do not use all \
capitals, clickbait that the video does not deliver, or quotation marks around the whole title. \
Do not put hashtags in the title.

THE DESCRIPTION
- "description" is plain text, with no "<" or ">" and no hashtags (they are added after it by a \
program). It starts with one or two sentences that say what the video is about, because those \
are what viewers see first, and then says a little more. Aim for under {description_target} \
characters. Do not invent facts, links, credits, timestamps or calls to subscribe that the \
inputs do not give.

THE HASHTAGS
- "hashtags" is a list of {min_tags} to {max_tags} words, each one word of letters, digits or \
underscores, with no "#" and no spaces. Write every hashtag in lowercase, and join the words of \
a phrase together (for example "spacehistory"). Each one must describe the video directly. Put \
the most important one first.

THE TAGS
- "tags" is a list of {min_tag_count} to {max_tag_count} search tags: the words and short phrases \
people would type into YouTube to find this video. Put the most important one first. A tag has \
no "#", no comma and no "<" or ">", and is at most {tag_max} characters. Do not repeat the title \
word for word, and do not repeat a tag. All the tags together, counting one comma between each \
two, must be at most {tags_total} characters.

THE FACTS OF THE VIDEO
- "kind" says whether it is a story or an explainer, and "orientation" and "duration_s" give its \
shape and length. When "is_short" is true YouTube will show it as a Short: keep the title short \
and punchy, and keep the description brief.
- When "script_cut" is true the script given is only the first part; rely on the scene titles \
for the rest, and do not say the video ends where the script given ends.

{feedback}

{length_rule}"""

_SHAPE: Final = """{"title": "The Day the Lighthouse Went Dark", "description": "A keeper \
finds the lamp has failed on the night of the worst storm in fifty years. A short story about \
duty and fear.", "hashtags": ["shortstory", "lighthouse", "storm"], "tags": ["short story", \
"lighthouse keeper", "storm at sea", "suspense", "duty and fear"]} (the values here only show \
the form, never copy them)"""


def _instructions() -> str:
    return (
        _RULES.format(
            title_max=TITLE_MAX_CHARS,
            description_target=DESCRIPTION_TARGET_CHARS,
            min_tags=HASHTAGS_MIN_AI,
            max_tags=HASHTAGS_MAX,
            min_tag_count=TAGS_MIN_AI,
            max_tag_count=TAGS_MAX_AI,
            tag_max=TAG_MAX_CHARS,
            tags_total=TAGS_MAX_CHARS_AI,
            feedback=user_feedback.INSTRUCTION,
            length_rule=length_rule(LIMIT_NAMES),
        )
        + "\n\nAnswer with one JSON object only, in exactly this form: "
        + _SHAPE
    )


def is_short(width: int | None, height: int | None, duration_s: float | None) -> bool:
    """Whether YouTube will show a video of this shape and length as a Short: vertical or
    square, and at most three minutes. False when the size or the length is not known.
    """
    if not width or not height or duration_s is None:
        return False
    return height >= width and duration_s <= SHORT_MAX_SECONDS


def context_for_model(
    bible: dict[str, Any],
    script_text: str,
    scene_titles: list[str],
    *,
    kind: str,
    orientation: str,
    duration_s: float | None,
    short: bool,
) -> dict[str, Any]:
    """Everything the model is told about the video. It is stored on the job."""
    script = script_text.strip()
    cut = len(script) > SCRIPT_MAX_CHARS
    return {
        "video": graphic_theme_writer.bible_for_model(bible),
        "kind": "explainer" if kind == KIND_EXPLAINER else "story",
        "orientation": orientation,
        "duration_s": round(duration_s) if duration_s is not None else None,
        "is_short": short,
        "scenes": scene_titles,
        "script": cut_at_word(script, SCRIPT_MAX_CHARS) if cut else script,
        "script_cut": cut,
    }


def build_request(
    context: dict[str, Any],
    *,
    model: str,
    feedback: user_feedback.Feedback | None = None,
) -> dict[str, Any]:
    """The exact request body of the one call. It is stored on the job."""
    facts = {key: value for key, value in context.items() if key not in ("script", "scenes")}
    parts = [
        "THE VIDEO (JSON):\n" + json.dumps(facts, ensure_ascii=False, indent=1),
        "SCENE TITLES (JSON):\n" + json.dumps(context.get("scenes", []), ensure_ascii=False),
        "SCRIPT:\n" + str(context.get("script", "")),
    ]
    if feedback is not None:
        parts += user_feedback.blocks(feedback, "PREVIOUS DRAFT")
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


# --- The text that is sent -------------------------------------------------------------------


def description_with_hashtags(description: str, hashtags: list[str]) -> str:
    """The description as it is sent to YouTube: the text, an empty line, then the hashtags on
    one line (`#one #two #three`). Hashtags have no field of their own; YouTube reads them from
    the description.
    """
    if not hashtags:
        return description
    line = " ".join(f"#{tag}" for tag in hashtags)
    return f"{description}\n\n{line}" if description else line


def utf8_bytes(text: str) -> int:
    return len(text.encode("utf-8"))


# --- Checking what was written ---------------------------------------------------------------


def _has_bad_control(text: str) -> bool:
    return any(
        unicodedata.category(character) == "Cc" and character not in "\n\t" for character in text
    )


def _title(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError('The "title" was missing or was not text.')
    text = " ".join(value.split())
    if not text:
        raise ValueError("The title is empty.")
    if len(text) > TITLE_MAX_CHARS:
        raise ValueError(
            f'The title "{text}" was {len(text)} characters; YouTube allows at most '
            f"{TITLE_MAX_CHARS}."
        )
    if "<" in text or ">" in text:
        raise ValueError("The title cannot hold the characters < or >.")
    return text


def _description(value: object, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValueError('The "description" was missing or was not text.')
    text = value.replace("\r\n", "\n").strip()
    if not text and not allow_empty:
        raise ValueError("The description is empty.")
    if "<" in text or ">" in text:
        raise ValueError("The description cannot hold the characters < or >.")
    if _has_bad_control(text):
        raise ValueError("The description has a character that cannot be sent to YouTube.")
    return text


def _hashtags(value: object, *, minimum: int) -> list[str]:
    if not isinstance(value, list):
        raise ValueError('The "hashtags" were missing or were not a list.')
    tags: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("A hashtag was not text.")
        word = item.strip().removeprefix("#")
        if not _HASHTAG.fullmatch(word):
            raise ValueError(
                f'The hashtag "{item}" must be one word of letters, digits or underscores, '
                "with no spaces."
            )
        # Hashtags are stored in lowercase (F-3), so an older CamelCase draft goes up lowercase.
        word = word.lower()
        if word in tags:
            raise ValueError(f'The hashtag "{word}" appears more than once.')
        tags.append(word)
    if len(tags) < minimum:
        raise ValueError(f"There must be at least {minimum} hashtags; there were {len(tags)}.")
    if len(tags) > HASHTAGS_MAX:
        raise ValueError(f"There can be at most {HASHTAGS_MAX} hashtags; there were {len(tags)}.")
    return tags


def check_fields(
    title: object,
    description: object,
    hashtags: object,
    *,
    min_hashtags: int,
    allow_empty_description: bool,
) -> tuple[str, str, list[str]]:
    """The title, description and hashtags as they will be stored, or ValueError with a
    sentence fit for the owner and for the model's corrected retry. The description, with the
    hashtags added to it, must fit YouTube's limit of 5,000 UTF-8 bytes.
    """
    checked_title = _title(title)
    checked_description = _description(description, allow_empty=allow_empty_description)
    checked_tags = _hashtags(hashtags, minimum=min_hashtags)
    sent = description_with_hashtags(checked_description, checked_tags)
    size = utf8_bytes(sent)
    if size > DESCRIPTION_MAX_BYTES:
        raise ValueError(
            f"The description with its hashtags is {size:,} bytes; YouTube allows at most "
            f"{DESCRIPTION_MAX_BYTES:,}."
        )
    return checked_title, checked_description, checked_tags


def tags_length(tags: list[str]) -> int:
    """The length of the tags as YouTube counts it (`snippet.tags`): the characters of every tag,
    one comma between each two, and two more for a tag that contains a space (it is counted as
    if it were in quotation marks).
    """
    quotes = sum(2 for tag in tags if " " in tag)
    commas = max(len(tags) - 1, 0)
    return sum(len(tag) for tag in tags) + quotes + commas


def check_tags(value: object, *, minimum: int, maximum: int | None, max_chars: int) -> list[str]:
    """The tags as they will be stored, or ValueError with a sentence fit for the owner and for
    the model's corrected retry. Each tag is trimmed with its spaces collapsed. `maximum` is the
    most tags (None: no limit) and `max_chars` the most `tags_length` allows.
    """
    if not isinstance(value, list):
        raise ValueError('The "tags" were missing or were not a list.')
    tags: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("A tag was not text.")
        tag = " ".join(item.split())
        if not tag:
            raise ValueError("A tag is empty.")
        if "<" in tag or ">" in tag or "," in tag:
            raise ValueError(f'The tag "{tag}" cannot hold the characters < > or a comma.')
        if _has_bad_control(tag):
            raise ValueError(f'The tag "{tag}" has a character that cannot be sent to YouTube.')
        if len(tag) > TAG_MAX_CHARS:
            raise ValueError(
                f'The tag "{tag}" was {len(tag)} characters; the most allowed is {TAG_MAX_CHARS}.'
            )
        if tag.lower() in (other.lower() for other in tags):
            raise ValueError(f'The tag "{tag}" appears more than once.')
        tags.append(tag)
    if len(tags) < minimum:
        raise ValueError(f"There must be at least {minimum} tags; there were {len(tags)}.")
    if maximum is not None and len(tags) > maximum:
        raise ValueError(f"There can be at most {maximum} tags; there were {len(tags)}.")
    size = tags_length(tags)
    if size > max_chars:
        raise ValueError(
            f"The tags are {size} characters as YouTube counts them (the commas count, and a tag "
            f"with a space counts two more); the most allowed is {max_chars}."
        )
    return tags


def check_content(answer: dict[str, Any], *, min_hashtags: int = HASHTAGS_MIN_AI) -> dict[str, Any]:
    """The model's answer as the stored content, or ValueError with a message fit for the
    owner and for the model's corrected retry. Keys that are not drafted any more (the two
    declarations) are ignored.
    """
    title, description, hashtags = check_fields(
        answer.get("title"),
        answer.get("description"),
        answer.get("hashtags"),
        min_hashtags=min_hashtags,
        allow_empty_description=False,
    )
    tags = check_tags(
        answer.get("tags"),
        minimum=TAGS_MIN_AI,
        maximum=TAGS_MAX_AI,
        max_chars=TAGS_MAX_CHARS_AI,
    )
    return {"title": title, "description": description, "hashtags": hashtags, "tags": tags}
