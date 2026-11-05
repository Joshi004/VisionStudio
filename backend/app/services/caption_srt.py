"""The SRT file of an explainer's captions (CAP-003, `Captions_ytt_implementation_phases.md` 4.5).
Pure: no I/O.

`srt_document` turns a frozen caption track (`caption_plan.CaptionTrack`) into plain SubRip text
for platforms other than YouTube. SRT has no styling, so the file is made to read well:

- **Text.** The script's own casing and punctuation (`CaptionWord.raw`). A track from before
  CAP-003 has none, and its caption text (upper case, no punctuation) is used instead.
- **Cues.** The words are joined into sentence-sized cues, not the 4-word groups of the picture.
  A cue ends after a word that ends a sentence (`.`, `!`, `?`, `…`), at a pause of
  `caption_plan.PAUSE_BREAK_S` or more (which also covers a stretch hidden by a section title),
  where the speech changes, or before the word that would make it too long.
- **Limits.** At most `MAX_LINES` lines of `MAX_LINE_CHARS` characters, and at most
  `MAX_CUE_MS` on screen. A cue shorter than `MIN_CUE_MS` is held up to that long, but never into
  the next cue and never past the last caption of the track, so cues never overlap.
- **Lines.** A cue that does not fit one line is split in two at the word boundary that makes
  the longer line shortest (the earlier one on a tie). A single word is never split.

Characters that cannot be in the file and line breaks are removed, and `-->` is replaced, so no
word can end a cue or be read as a time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.services.caption_plan import PAUSE_BREAK_S, CaptionTrack, CaptionWord

MAX_LINE_CHARS: Final = 42
MAX_LINES: Final = 2
MIN_CUE_MS: Final = 1000
MAX_CUE_MS: Final = 7000

_PAUSE_BREAK_MS: Final = round(PAUSE_BREAK_S * 1000)
# A cue ends after a word with one of these (and any closing quote or bracket after it). Commas,
# semicolons and colons do not end a cue, so a cue stays about a sentence long.
_SENTENCE_END: Final = re.compile(r"[.!?…]['\"”’)\]]*$")
# Control characters, line separators and the two non-characters.
_UNSAFE_TEXT: Final = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029\ufffe\uffff]")
_ARROW: Final = re.compile(r"-{2,}>")


@dataclass(frozen=True)
class _Word:
    text: str
    start_ms: int
    end_ms: int
    ends_sentence: bool
    unit_id: str
    audio_id: int


@dataclass(frozen=True)
class _Cue:
    words: tuple[_Word, ...]
    lines: tuple[str, ...]


def _clean(text: str) -> str:
    return " ".join(_ARROW.sub("->", _UNSAFE_TEXT.sub(" ", text)).split())


def _words_of(track: CaptionTrack) -> list[_Word]:
    """Every word of the track in order, with the text the SRT shows. Words with no text are
    dropped.
    """
    words: list[_Word] = []
    for group in track.groups:
        for word in group.words:
            text = _clean(_shown(word))
            if not text:
                continue
            words.append(
                _Word(
                    text=text,
                    start_ms=word.start_ms,
                    end_ms=word.end_ms,
                    ends_sentence=word.raw is not None
                    and _SENTENCE_END.search(word.raw.rstrip()) is not None,
                    unit_id=group.unit_id,
                    audio_id=group.audio_id,
                )
            )
    return words


def _shown(word: CaptionWord) -> str:
    return word.raw if word.raw is not None else word.text


# --- Lines ----------------------------------------------------------------------------------


def _lines_of(texts: list[str]) -> tuple[str, ...] | None:
    """The lines of a cue, or None when its words do not fit `MAX_LINES` lines of
    `MAX_LINE_CHARS`. A cue of one word always fits, however long.
    """
    whole = " ".join(texts)
    if len(texts) == 1 or len(whole) <= MAX_LINE_CHARS:
        return (whole,)
    # The place that makes the longer of the two lines as short as it can be (the first one on
    # a tie). `MAX_LINES` is 2, so two lines is the most a cue can have.
    place = min(
        range(1, len(texts)),
        key=lambda at: max(len(" ".join(texts[:at])), len(" ".join(texts[at:]))),
    )
    lines = (" ".join(texts[:place]), " ".join(texts[place:]))
    if len(lines) > MAX_LINES or any(len(line) > MAX_LINE_CHARS for line in lines):
        return None
    return lines


# --- Cues -----------------------------------------------------------------------------------


def _ends_before(previous: _Word, following: _Word) -> bool:
    """Whether a cue must end after `previous`, whatever its length."""
    return (
        previous.ends_sentence
        or following.start_ms - previous.end_ms >= _PAUSE_BREAK_MS
        or previous.unit_id != following.unit_id
        or previous.audio_id != following.audio_id
    )


def _cues_of(words: list[_Word]) -> list[_Cue]:
    cues: list[_Cue] = []
    current: list[_Word] = []

    def close() -> None:
        lines = _lines_of([word.text for word in current])
        if lines is not None:  # a cue is only ever built from words that fit
            cues.append(_Cue(tuple(current), lines))

    for word in words:
        if current and _ends_before(current[-1], word):
            close()
            current = []
        if current:
            candidate = [*current, word]
            fits = _lines_of([item.text for item in candidate]) is not None
            if not fits or word.end_ms - current[0].start_ms > MAX_CUE_MS:
                close()
                current = []
        current.append(word)
    if current:
        close()
    return cues


# --- Text -----------------------------------------------------------------------------------


def _timestamp(milliseconds: int) -> str:
    seconds, millis = divmod(max(0, milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def srt_document(track: CaptionTrack) -> str:
    """The whole SRT file of a caption track, as text (UTF-8 when written)."""
    cues = _cues_of(_words_of(track))
    last_end = max((group.end_ms for group in track.groups), default=0)
    blocks: list[str] = []
    number = 0
    for position, cue in enumerate(cues):
        start = cue.words[0].start_ms
        limit = cues[position + 1].words[0].start_ms if position + 1 < len(cues) else last_end
        # The cue lasts as long as its words, is held to `MIN_CUE_MS` where there is room, and
        # never runs into the next cue.
        end = min(max(cue.words[-1].end_ms, start + MIN_CUE_MS), limit)
        end = min(end, start + MAX_CUE_MS)
        if end <= start:
            continue
        number += 1
        blocks.append(
            f"{number}\n{_timestamp(start)} --> {_timestamp(end)}\n" + "\n".join(cue.lines) + "\n"
        )
    return "\n".join(blocks)
