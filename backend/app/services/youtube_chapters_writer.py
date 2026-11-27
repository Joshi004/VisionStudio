"""The chapters of a YouTube description: what the model is asked, the checks of what it wrote,
and the text that is added to the description.

Pure functions, no I/O.

Chapters are for explainers only. An explainer's render freezes a caption track in its timeline
(`caption_plan`): every spoken word with the millisecond it starts. `timed_lines` turns that
track into numbered sentences, each with its start time. The model never sees or writes a time:
it reads the numbered sentences and answers with the number of the sentence each chapter starts
at. The time of a chapter is then the time of that sentence, so a timestamp is exact whatever the
model does. The chapters do not have to match the scenes of the video.

YouTube's rules for chapters (the Help Center, "Video Chapters"): the first timestamp is 0:00,
there are at least three timestamps in ascending order, and each chapter lasts at least ten
seconds. `check_chapters` holds the model to them, and the same checks decide the stored result.

The stored chapters are `[{"title", "start_ms"}]`; `block` is the text added to the description.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from app.services import caption_plan, user_feedback
from app.services.music_bible_writer import parse_answer as parse_answer

# YouTube's limits.
CHAPTERS_MIN: Final = 3
MIN_CHAPTER_S: Final = 10
# What the model is asked for. More than this is too much to read in a description.
CHAPTERS_MAX: Final = 12
TITLE_MAX_CHARS: Final = 60
# A video shorter than this gets no chapters.
MIN_VIDEO_S: Final = 60

# One answer of moderate size. The model's reasoning counts against the cap.
MAX_TOKENS: Final = 8_000
REASONING_EFFORT: Final = "high"

# A sentence is cut to this many characters when it is shown to the model.
_LINE_SHOWN_CHARS: Final = 240
_HEADING: Final = "Chapters"

_SENTENCE_END = re.compile(r"[.!?…]['\"”’)\]]*$")
_TIMESTAMP = re.compile(r"\d{1,2}:\d{2}")

_RULES: Final = """\
You split one finished video into chapters for its YouTube description. You are given the length \
of the video and its spoken text as numbered sentences, each with the time it starts. A program \
turns the sentence numbers you choose into timestamps, so you never write a time.

HOW TO CHOOSE
- Start a new chapter where the subject really changes for a viewer, such as a new question, a \
new claim, a new comparison, the verdict or the wrap-up. Do not follow the scenes or any \
other division: you are not told them, and a chapter may start in the middle of anything.
- Aim for about one chapter for every one to two minutes of video, but at least {min_count} and \
at most {max_count}. Keep the chapters roughly balanced: no chapter is shorter than \
{min_seconds} seconds.
- The first chapter starts at sentence 1. Give it a title about what it covers, not just \
"Intro".
- Sentences marked (clip) are a recorded clip of someone else speaking; a chapter may include \
them but should be named for what they show, not for the clip.

THE TITLES
- Each "title" is plain English, in sentence case, at most {title_max} characters, and tells a \
viewer what that part is about. No numbering, no timestamps, no emoji, no quotation marks around \
the whole title, no "<" or ">". All titles are different. Do not invent anything the text does \
not say.

{feedback}"""

_SHAPE: Final = """{"chapters": [{"title": "Why the lamp failed", "starts_at": 1}, \
{"title": "The keeper climbs the tower", "starts_at": 14}, {"title": "What the log book shows", \
"starts_at": 31}]} (the values here only show the form, never copy them; "starts_at" is the \
number of the sentence the chapter starts at)"""


def _instructions() -> str:
    return (
        _RULES.format(
            min_count=CHAPTERS_MIN,
            max_count=CHAPTERS_MAX,
            min_seconds=MIN_CHAPTER_S,
            title_max=TITLE_MAX_CHARS,
            feedback=user_feedback.INSTRUCTION,
        )
        + "\n\nAnswer with one JSON object only, in exactly this form: "
        + _SHAPE
    )


# --- The numbered sentences ------------------------------------------------------------------


def clock(milliseconds: int, *, with_hours: bool) -> str:
    """`m:ss`, or `h:mm:ss` when `with_hours`, of a time rounded down to the second."""
    total = max(milliseconds, 0) // 1000
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if with_hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{hours * 60 + minutes}:{seconds:02d}"


def timed_lines(captions_raw: object) -> list[dict[str, Any]]:
    """The spoken sentences of a render, from its frozen caption track: `[{"n", "start_ms",
    "text", "clip"}]`, numbered from 1 in the order they are heard. A sentence ends at `.`, `!` or
    `?`, and never holds words of two speeches. It starts when its first word does. `clip` is true
    for a sound bite (someone else speaking). Empty when there is no track or it cannot be read.
    """
    try:
        track = caption_plan.parse_track(captions_raw)
    except caption_plan.CaptionError:
        return []
    if track is None:
        return []
    sentences: list[dict[str, Any]] = []
    words: list[str] = []
    start_ms = 0
    unit_id: str | None = None
    clip = False

    def flush() -> None:
        nonlocal words
        text = " ".join(words).strip()
        if text:
            sentences.append({"start_ms": start_ms, "text": text, "clip": clip})
        words = []

    for group in sorted(track.groups, key=lambda item: item.start_ms):
        if group.unit_id != unit_id:
            flush()
            unit_id = group.unit_id
        for word in group.words:
            if not words:
                start_ms = word.start_ms
                clip = group.colour is not None
            words.append(word.raw if word.raw is not None else word.text)
            if _SENTENCE_END.search(words[-1]):
                flush()
    flush()
    return [{"n": index, **sentence} for index, sentence in enumerate(sentences, start=1)]


def _shown(lines: list[dict[str, Any]], with_hours: bool) -> str:
    rows: list[str] = []
    for line in lines:
        text = line["text"]
        if len(text) > _LINE_SHOWN_CHARS:
            text = text[: _LINE_SHOWN_CHARS - 1].rstrip() + "\u2026"
        mark = " (clip)" if line["clip"] else ""
        rows.append(
            f"{line['n']} | {clock(line['start_ms'], with_hours=with_hours)} |{mark} {text}"
        )
    return "\n".join(rows)


# --- The request -----------------------------------------------------------------------------


def titles_of(description: str) -> list[str]:
    """The chapter titles in a stored description (what `block` wrote), without their times."""
    start = description.find(f"\n\n{_HEADING}\n")
    if start < 0:
        return []
    titles: list[str] = []
    for row in description[start + len(_HEADING) + 3 :].split("\n"):
        match = re.fullmatch(r"(?:\d{1,2}:)?\d{1,2}:\d{2} (.+)", row.strip())
        if match is None:
            break  # the block ends at the first row that is not a chapter
        titles.append(match.group(1))
    return titles


def build_request(
    lines: list[dict[str, Any]],
    duration_s: float,
    *,
    model: str,
    feedback: user_feedback.Feedback | None = None,
    previous_titles: list[str] | None = None,
) -> dict[str, Any]:
    """The exact request body of the chapters call. It is stored on the job. With a note from the
    owner, the titles of the earlier chapters (`previous_titles`, see `titles_of`) go with it."""
    with_hours = duration_s >= 3600
    parts = [
        f"VIDEO LENGTH: {clock(round(duration_s * 1000), with_hours=with_hours)}",
        "SENTENCES (number | start time | text):\n" + _shown(lines, with_hours),
    ]
    if feedback is not None:
        if previous_titles:
            parts.append(
                "PREVIOUS CHAPTERS (JSON):\n" + json.dumps(previous_titles, ensure_ascii=False)
            )
        parts += user_feedback.blocks(feedback, "PREVIOUS CHAPTERS", with_previous=False)
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


def _title(value: object, position: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"The title of chapter {position} was missing or was not text.")
    text = " ".join(value.split())
    if not text:
        raise ValueError(f"The title of chapter {position} is empty.")
    if len(text) > TITLE_MAX_CHARS:
        raise ValueError(
            f'The title "{text}" was {len(text)} characters; the most allowed is {TITLE_MAX_CHARS}.'
        )
    if "<" in text or ">" in text:
        raise ValueError(f'The title "{text}" cannot hold the characters < or >.')
    if _TIMESTAMP.search(text):
        raise ValueError(
            f'The title "{text}" holds a time. Do not write times: a program adds them.'
        )
    return text


def check_chapters(
    answer: dict[str, Any], lines: list[dict[str, Any]], duration_s: float
) -> list[dict[str, Any]]:
    """The model's chapters as they will be stored, `[{"title", "start_ms"}]`, or ValueError with
    a sentence fit for the model's corrected retry. The first chapter is at 0:00 whatever the
    first sentence's time is; the others start where the sentence they name starts.
    """
    raw = answer.get("chapters")
    if not isinstance(raw, list):
        raise ValueError('The "chapters" were missing or were not a list.')
    if len(raw) < CHAPTERS_MIN or len(raw) > CHAPTERS_MAX:
        raise ValueError(
            f"There must be {CHAPTERS_MIN} to {CHAPTERS_MAX} chapters; there were {len(raw)}."
        )
    chapters: list[dict[str, Any]] = []
    previous_number = 0
    seen: set[str] = set()
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Chapter {position} was not an object with a title and starts_at.")
        title = _title(item.get("title"), position)
        if title.lower() in seen:
            raise ValueError(f'The title "{title}" appears more than once.')
        seen.add(title.lower())
        number = item.get("starts_at")
        if isinstance(number, bool) or not isinstance(number, int):
            raise ValueError(f"The starts_at of chapter {position} was not a whole number.")
        if number < 1 or number > len(lines):
            raise ValueError(
                f"The starts_at of chapter {position} was {number}; the sentences are numbered "
                f"1 to {len(lines)}."
            )
        if position == 1 and number != 1:
            raise ValueError("The first chapter must start at sentence 1.")
        if number <= previous_number:
            raise ValueError(f"Chapter {position} must start after the one before it.")
        previous_number = number
        start_ms = 0 if position == 1 else int(lines[number - 1]["start_ms"])
        chapters.append({"title": title, "start_ms": start_ms})
    ends = [chapter["start_ms"] for chapter in chapters[1:]] + [round(duration_s * 1000)]
    for position, (chapter, end_ms) in enumerate(zip(chapters, ends, strict=True), start=1):
        if end_ms // 1000 - chapter["start_ms"] // 1000 < MIN_CHAPTER_S:
            raise ValueError(
                f'Chapter {position} ("{chapter["title"]}") lasts less than {MIN_CHAPTER_S} '
                "seconds. Start the chapters further apart or use fewer."
            )
    return chapters


# --- The text that is added ------------------------------------------------------------------


def block(chapters: list[dict[str, Any]], duration_s: float) -> str:
    """The Chapters block: the heading and one `0:00 Title` row per chapter. `h:mm:ss` is used
    for every time when the video is an hour or longer."""
    if not chapters:
        return ""
    with_hours = duration_s >= 3600
    rows = [f"{clock(c['start_ms'], with_hours=with_hours)} {c['title']}" for c in chapters]
    return _HEADING + "\n" + "\n".join(rows)
