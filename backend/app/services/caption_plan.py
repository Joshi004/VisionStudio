"""The word-synced captions of an explainer render (EXPLAINER-008, decisions E-9 to E-13).

Pure: no I/O, no clock. `story_render_plan.build_plan` gives `build_captions` every speech of the
story with the time of each of its script words (`speech_word_timing`, EXPLAINER-007), and gets
back the **caption groups** that are frozen in the timeline (`timeline["captions"]`). The render
job reads them back with `parse_track` and `services/caption_ass.py` writes them as an ASS file.

**Text** (`caption_text`): upper case, with sentence punctuation removed. Apostrophes, hyphens
inside a word, `%`, `$` and the points of numbers such as "3.5" and "1,000" stay.

**Grouping** (`build_captions`):

- a group has at most `MAX_WORDS` words, and never more characters than the layout allows;
- a run of words is broken after sentence punctuation and at a pause of `PAUSE_BREAK_S` or more;
- a group never holds words of two speeches;
- a group stays up for at least `MIN_SHOW_MS`, but never past the start of the next group, and a
  gap shorter than `BRIDGE_GAP_MS` between two groups of one speech is closed so the caption does
  not flicker;
- nothing is shown where no speech is, so a pause between events has no caption.

**Highlight:** the groups hold each word's own time. The ASS file shows a group once for every
word, with that word coloured (`caption_ass`), so only the word being spoken is highlighted.

**Layout** (`style_for`): one style per orientation, taken from the output size, in pixels of the
output (the ASS file's play resolution is the output size). The values are starting values: the
portrait margin keeps the captions above the buttons of Shorts and Reels.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

LAYOUT_LANDSCAPE: Final = "landscape"
LAYOUT_PORTRAIT: Final = "portrait"
_LAYOUTS: Final = (LAYOUT_LANDSCAPE, LAYOUT_PORTRAIT)

# The family name of the bundled font file (`assets/fonts/Montserrat-ExtraBold.ttf`).
FONT_NAME: Final = "Montserrat ExtraBold"
TEXT_COLOUR: Final = "#FFFFFF"
OUTLINE_COLOUR: Final = "#000000"
# Fixed until EXPLAINER-010 gives the video its own accent colour.
HIGHLIGHT_COLOUR: Final = "#FFD60A"

MAX_WORDS: Final = 4
# A silence this long inside a speech ends a group.
PAUSE_BREAK_S: Final = 0.30
MIN_SHOW_MS: Final = 400
# Two groups of one speech with less than this between them are joined (the first one stays up).
BRIDGE_GAP_MS: Final = 250

_MS_PER_S: Final = 1000
_COLOUR: Final = re.compile(r"#[0-9A-Fa-f]{6}")
_FONT_NAME: Final = re.compile(r"[A-Za-z0-9 ]{1,60}")
_SENTENCE_END: Final = re.compile(r"[.,!?;:…—–]['\"”’)\]]*$")


class CaptionError(ValueError):
    """A recorded caption track this version cannot read."""


@dataclass(frozen=True)
class CaptionStyle:
    """How the captions look, in pixels of the output. Frozen in the timeline."""

    layout: str
    play_res_x: int
    play_res_y: int
    font_name: str
    font_size: int
    outline: float
    margin_v: int
    margin_h: int
    max_chars: int
    text_colour: str
    outline_colour: str
    highlight_colour: str


@dataclass(frozen=True)
class CaptionWord:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class CaptionGroup:
    scene_id: str
    unit_id: str
    audio_id: int
    start_ms: int
    end_ms: int
    words: tuple[CaptionWord, ...]


@dataclass(frozen=True)
class CaptionTrack:
    style: CaptionStyle
    groups: tuple[CaptionGroup, ...]


@dataclass(frozen=True)
class TimedUnit:
    """One speech of the story: where its file starts on the story's timeline, and its script
    words, each `(text, start_s, end_s)` in seconds from the start of the file.
    """

    scene_id: str
    unit_id: str
    audio_id: int
    start_ms: int
    words: Sequence[tuple[str, float, float]]


# --- The layout -----------------------------------------------------------------------------


def style_for(width: int, height: int, highlight_colour: str = HIGHLIGHT_COLOUR) -> CaptionStyle:
    """The caption style of an output size. A taller output is portrait. `highlight_colour` is
    the video's accent when the render has callouts (EXPLAINER-010), else the fixed default.
    """
    if height > width:
        return CaptionStyle(
            layout=LAYOUT_PORTRAIT,
            play_res_x=width,
            play_res_y=height,
            font_name=FONT_NAME,
            font_size=round(height * 0.042),
            outline=round(height * 0.0035, 1),
            # High enough to clear the buttons Shorts and Reels draw over the lower part.
            margin_v=round(height * 0.28),
            margin_h=round(width * 0.08),
            max_chars=14,
            text_colour=TEXT_COLOUR,
            outline_colour=OUTLINE_COLOUR,
            highlight_colour=highlight_colour,
        )
    return CaptionStyle(
        layout=LAYOUT_LANDSCAPE,
        play_res_x=width,
        play_res_y=height,
        font_name=FONT_NAME,
        font_size=round(height * 0.065),
        outline=round(height * 0.006, 1),
        margin_v=round(height * 0.09),
        margin_h=round(width * 0.10),
        max_chars=28,
        text_colour=TEXT_COLOUR,
        outline_colour=OUTLINE_COLOUR,
        highlight_colour=highlight_colour,
    )


# --- The text -------------------------------------------------------------------------------


def caption_text(word: str) -> str:
    """A script word as a caption shows it: upper case, with the sentence punctuation removed.
    An empty string means nothing is left to show (a dash on its own).
    """
    text = unicodedata.normalize("NFKC", word)
    # A dash inside a word ("well—known") is a space; one at its ends goes with the spaces.
    text = re.sub(r"[—–]", " ", text)
    text = re.sub(r"[\"“”‘«»()\[\]]", "", text)
    # A point or comma stays only between two digits ("3.5", "1,000").
    text = re.sub(r"(?<!\d)[.,]|[.,](?!\d)", "", text)
    text = re.sub(r"[!?;:]", "", text)
    # An apostrophe stays only inside a word ("don't").
    text = re.sub(r"(?<!\w)['’]|['’](?!\w)", "", text)
    # A hyphen stays inside a word, and in front of a number ("-5%").
    text = re.sub(r"^-+(?!\d)|-+$", "", text.strip())
    return " ".join(text.upper().split())


def _ends_sentence(word: str) -> bool:
    """Whether the script word ends with a punctuation mark a caption breaks at."""
    return _SENTENCE_END.search(unicodedata.normalize("NFKC", word).rstrip()) is not None


@dataclass
class _Word:
    text: str
    start_s: float
    end_s: float
    break_after: bool = False


def _clean_words(words: Sequence[tuple[str, float, float]]) -> list[_Word]:
    """The caption words of a speech. A word with nothing left is dropped, and counts as a
    break after the word before it.
    """
    cleaned: list[_Word] = []
    for raw, start_s, end_s in words:
        text = caption_text(raw)
        if not text:
            if cleaned:
                cleaned[-1].break_after = True
            continue
        cleaned.append(_Word(text, start_s, end_s, break_after=_ends_sentence(raw)))
    return cleaned


# --- The groups -----------------------------------------------------------------------------


def _runs(words: list[_Word]) -> list[list[_Word]]:
    """The words split where a sentence mark or a pause ends a run."""
    runs: list[list[_Word]] = []
    current: list[_Word] = []
    for word in words:
        if current and (
            current[-1].break_after or word.start_s - current[-1].end_s >= PAUSE_BREAK_S
        ):
            runs.append(current)
            current = []
        current.append(word)
    if current:
        runs.append(current)
    return runs


def _length(words: Sequence[_Word]) -> int:
    return len(" ".join(word.text for word in words))


def _split_to_fit(words: list[_Word], max_chars: int) -> list[list[_Word]]:
    """Splits a group that is too long into two parts of about the same width, and again until
    each part fits `max_chars` (a single word is never split).
    """
    if len(words) < 2 or _length(words) <= max_chars:
        return [words]
    # The place that makes the longer of the two parts as short as it can be.
    middle = min(
        range(1, len(words)),
        key=lambda place: max(_length(words[:place]), _length(words[place:])),
    )
    return _split_to_fit(words[:middle], max_chars) + _split_to_fit(words[middle:], max_chars)


def _groups_of(run: list[_Word], max_chars: int) -> list[list[_Word]]:
    """A run as groups of near-equal size, at most `MAX_WORDS` words each (5 words are 3 and 2,
    not 4 and 1), each short enough for the layout.
    """
    count = math.ceil(len(run) / MAX_WORDS)
    base, extra = divmod(len(run), count)
    groups: list[list[_Word]] = []
    position = 0
    for number in range(count):
        size = base + (1 if number < extra else 0)
        groups.extend(_split_to_fit(run[position : position + size], max_chars))
        position += size
    return groups


def _ms(seconds: float) -> int:
    return math.floor(seconds * _MS_PER_S + 0.5)


def build_captions(
    units: Sequence[TimedUnit], style: CaptionStyle, total_ms: int
) -> list[CaptionGroup]:
    """The caption groups of the story, in order, on the story's timeline (milliseconds).
    `total_ms` is the length of the video: nothing is shown after it.
    """
    # Every group in order, with whether another group of the same speech follows it.
    pending: list[tuple[CaptionGroup, bool]] = []
    for unit in sorted(units, key=lambda item: item.start_ms):
        words = _clean_words(unit.words)
        groups: list[CaptionGroup] = []
        for run in _runs(words):
            for part in _groups_of(run, style.max_chars):
                timed = tuple(
                    CaptionWord(
                        word.text,
                        unit.start_ms + _ms(word.start_s),
                        unit.start_ms + _ms(word.end_s),
                    )
                    for word in part
                )
                groups.append(
                    CaptionGroup(
                        scene_id=unit.scene_id,
                        unit_id=unit.unit_id,
                        audio_id=unit.audio_id,
                        start_ms=timed[0].start_ms,
                        end_ms=max(word.end_ms for word in timed),
                        words=timed,
                    )
                )
        for position, group in enumerate(groups):
            pending.append((group, position + 1 < len(groups)))

    finished: list[CaptionGroup] = []
    for position, (group, same_unit_follows) in enumerate(pending):
        next_start = pending[position + 1][0].start_ms if position + 1 < len(pending) else total_ms
        end = group.end_ms
        if same_unit_follows and 0 <= next_start - end < BRIDGE_GAP_MS:
            end = next_start
        end = max(end, group.start_ms + MIN_SHOW_MS)
        end = min(end, next_start, total_ms)
        if group.start_ms >= total_ms or end <= group.start_ms:
            continue
        words = _fit_words(group.words, group.start_ms, end)
        finished.append(
            CaptionGroup(
                scene_id=group.scene_id,
                unit_id=group.unit_id,
                audio_id=group.audio_id,
                start_ms=group.start_ms,
                end_ms=end,
                words=words,
            )
        )
    return finished


def _fit_words(
    words: tuple[CaptionWord, ...], start_ms: int, end_ms: int
) -> tuple[CaptionWord, ...]:
    """The words of a group inside its own time: each starts no earlier than the word before it
    and no later than the end of the group, and each one lasts until the next one starts.
    """
    starts: list[int] = []
    previous = start_ms
    for word in words:
        previous = min(max(word.start_ms, previous), end_ms)
        starts.append(previous)
    fitted: list[CaptionWord] = []
    for index, word in enumerate(words):
        following = starts[index + 1] if index + 1 < len(words) else end_ms
        fitted.append(CaptionWord(word.text, starts[index], following))
    return tuple(fitted)


def _cut_out(group: CaptionGroup, window_start: int, window_end: int) -> CaptionGroup | None:
    """The part of a group outside one window (milliseconds), or None when nothing is left.
    A group that starts before the window keeps the words before it and ends where it starts. A
    group that starts inside the window keeps the words after its end and starts where it ends.
    """
    if group.end_ms <= window_start or group.start_ms >= window_end:
        return group
    if group.start_ms < window_start:
        kept = tuple(word for word in group.words if word.start_ms < window_start)
        start, end = group.start_ms, window_start
    else:
        kept = tuple(word for word in group.words if word.start_ms >= window_end)
        start, end = window_end, group.end_ms
    if not kept or end <= start:
        return None
    return CaptionGroup(
        scene_id=group.scene_id,
        unit_id=group.unit_id,
        audio_id=group.audio_id,
        start_ms=start,
        end_ms=end,
        words=_fit_words(kept, start, end),
    )


def hide_during(
    groups: Sequence[CaptionGroup], windows: Sequence[tuple[int, int]]
) -> list[CaptionGroup]:
    """The caption groups with nothing shown inside the windows (milliseconds, `(start, end)`),
    which are the stretches a section title is on screen (EXPLAINER-010). A group that no window
    touches is returned as it was.
    """
    shown: list[CaptionGroup] = []
    for group in groups:
        current: CaptionGroup | None = group
        for window_start, window_end in sorted(windows):
            if current is None:
                break
            current = _cut_out(current, window_start, window_end)
        if current is not None:
            shown.append(current)
    return shown


# --- Recording and reading back -------------------------------------------------------------


def track_dict(style: CaptionStyle, groups: Sequence[CaptionGroup]) -> dict[str, Any]:
    """The caption track as it is frozen in the timeline (JSON)."""
    return {
        "style": {
            "layout": style.layout,
            "play_res_x": style.play_res_x,
            "play_res_y": style.play_res_y,
            "font_name": style.font_name,
            "font_size": style.font_size,
            "outline": style.outline,
            "margin_v": style.margin_v,
            "margin_h": style.margin_h,
            "max_chars": style.max_chars,
            "text_colour": style.text_colour,
            "outline_colour": style.outline_colour,
            "highlight_colour": style.highlight_colour,
        },
        "groups": [
            {
                "scene_id": group.scene_id,
                "unit_id": group.unit_id,
                "audio_id": group.audio_id,
                "start_ms": group.start_ms,
                "end_ms": group.end_ms,
                "words": [
                    {"text": word.text, "start_ms": word.start_ms, "end_ms": word.end_ms}
                    for word in group.words
                ],
            }
            for group in groups
        ],
    }


def _whole(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CaptionError("not a whole number")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise CaptionError("not text")
    return value


def _colour(value: object) -> str:
    text = _text(value)
    if not _COLOUR.fullmatch(text):
        raise CaptionError("not a colour")
    return text


def _style_of(raw: object) -> CaptionStyle:
    if not isinstance(raw, dict):
        raise CaptionError("no style")
    layout = _text(raw.get("layout"))
    font_name = _text(raw.get("font_name"))
    outline = raw.get("outline")
    if (
        layout not in _LAYOUTS
        or not _FONT_NAME.fullmatch(font_name)
        or isinstance(outline, bool)
        or not isinstance(outline, int | float)
        or outline < 0
    ):
        raise CaptionError("bad style")
    style = CaptionStyle(
        layout=layout,
        play_res_x=_whole(raw.get("play_res_x")),
        play_res_y=_whole(raw.get("play_res_y")),
        font_name=font_name,
        font_size=_whole(raw.get("font_size")),
        outline=float(outline),
        margin_v=_whole(raw.get("margin_v")),
        margin_h=_whole(raw.get("margin_h")),
        max_chars=_whole(raw.get("max_chars")),
        text_colour=_colour(raw.get("text_colour")),
        outline_colour=_colour(raw.get("outline_colour")),
        highlight_colour=_colour(raw.get("highlight_colour")),
    )
    if (
        style.play_res_x < 2
        or style.play_res_y < 2
        or style.font_size < 1
        or style.margin_v < 0
        or style.margin_h < 0
        or style.max_chars < 1
    ):
        raise CaptionError("bad style")
    return style


def _group_of(raw: object) -> CaptionGroup:
    if not isinstance(raw, dict) or not isinstance(raw.get("words"), list):
        raise CaptionError("bad group")
    words = tuple(
        CaptionWord(_text(w.get("text")), _whole(w.get("start_ms")), _whole(w.get("end_ms")))
        for w in raw["words"]
        if isinstance(w, dict)
    )
    group = CaptionGroup(
        scene_id=_text(raw.get("scene_id")),
        unit_id=_text(raw.get("unit_id")),
        audio_id=_whole(raw.get("audio_id")),
        start_ms=_whole(raw.get("start_ms")),
        end_ms=_whole(raw.get("end_ms")),
        words=words,
    )
    if (
        not words
        or len(words) != len(raw["words"])
        or group.start_ms < 0
        or group.end_ms <= group.start_ms
        or any(word.start_ms < 0 or word.end_ms < word.start_ms for word in words)
    ):
        raise CaptionError("bad group")
    return group


def parse_track(raw: object) -> CaptionTrack | None:
    """Reads the `captions` entry of a timeline back. None for a render without captions.
    Raises CaptionError for anything this version does not understand.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("groups"), list):
        raise CaptionError("bad track")
    return CaptionTrack(
        style=_style_of(raw.get("style")),
        groups=tuple(_group_of(group) for group in raw["groups"]),
    )
