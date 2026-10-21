"""Splitting a script into pieces that Breeze TTS accepts (Phase 21). Pure: no I/O.

One request takes at most 1000 characters of text, and makes about two minutes of speech at
most; anything longer is cut off by the server, not refused. 1000 English characters measured
about 92 seconds, and Chinese is denser per character (the server's guide estimates about half
as many characters per request), so a Chinese, Japanese or Korean character counts double here.

`split_script` packs whole sentences into pieces, a piece as long as it can be. A sentence that
is longer than a piece is split at its commas, then at its spaces, and only then in the middle
of a word, so a piece breaks where a speaker would pause.
"""

from __future__ import annotations

import re
from typing import Final

MAX_CHUNK_COST: Final = 1000

# A sentence ends at . ! ? followed by a space, at a line break, or right after a CJK full stop.
_SENTENCE_END: Final = re.compile(r"(?<=[.!?\u2026])\s+|\n+|(?<=[\u3002\uff01\uff1f])")
# A clause ends after a comma, a semicolon or a colon (Latin or CJK).
_CLAUSE_END: Final = re.compile(r"(?<=[,;:\uff0c\uff1b\uff1a\u3001])\s*")
_WORD_BREAK: Final = re.compile(r"\s+")
# Han, Hiragana, Katakana and Hangul.
_WIDE: Final = re.compile(r"[\u1100-\u11ff\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def cost(text: str) -> int:
    """How much of a request's room the text uses: a character, or two for a wide one."""
    return len(text) + len(_WIDE.findall(text))


def split_script(text: str, max_cost: int = MAX_CHUNK_COST) -> list[str]:
    """The script as pieces of at most `max_cost`, in order. An empty script gives none."""
    chunks: list[str] = []
    current = ""
    for sentence in _pieces(text, _SENTENCE_END):
        for part in _fit(sentence, max_cost):
            if current and cost(current) + 1 + cost(part) <= max_cost:
                current = f"{current} {part}"
            else:
                if current:
                    chunks.append(current)
                current = part
    if current:
        chunks.append(current)
    return chunks


def sentences(text: str) -> list[str]:
    """The text cut after each sentence end (PHASE-018). Each piece keeps the whitespace that
    followed it, so the pieces joined with no separator are the text again.
    """
    return _slices(text, _SENTENCE_END)


def clauses(text: str) -> list[str]:
    """The text cut after each comma, semicolon or colon, in the same way as `sentences`."""
    return _slices(text, _CLAUSE_END)


def _slices(text: str, pattern: re.Pattern[str]) -> list[str]:
    """The text cut where `pattern` ends a match, with nothing lost: the pieces joined give the
    text. A piece made only of whitespace is attached to the piece before it.
    """
    cuts = sorted({match.end() for match in pattern.finditer(text) if 0 < match.end() < len(text)})
    pieces: list[str] = []
    start = 0
    for cut in [*cuts, len(text)]:
        piece = text[start:cut]
        start = cut
        if pieces and not piece.strip():
            pieces[-1] += piece
        else:
            pieces.append(piece)
    return pieces


def _pieces(text: str, pattern: re.Pattern[str]) -> list[str]:
    return [piece.strip() for piece in pattern.split(text) if piece and piece.strip()]


def _fit(piece: str, max_cost: int) -> list[str]:
    """The piece as parts of at most `max_cost`: itself when it fits."""
    if cost(piece) <= max_cost:
        return [piece]
    for pattern in (_CLAUSE_END, _WORD_BREAK):
        parts = _pieces(piece, pattern)
        if len(parts) > 1:
            return [fitted for part in parts for fitted in _fit(part, max_cost)]
    return _cut(piece, max_cost)


def _cut(piece: str, max_cost: int) -> list[str]:
    """A piece with no place to break, cut wherever the room runs out."""
    parts: list[str] = []
    current = ""
    for character in piece:
        if current and cost(current + character) > max_cost:
            parts.append(current)
            current = ""
        current += character
    if current:
        parts.append(current)
    return parts
