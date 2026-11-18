"""Normalising, and finding a quote in a source's text.

The rules here are the contract that the import (EVD-006) must repeat exactly:

- NFKC (applied to a letter and the marks after it together);
- curly quotes become straight quotes;
- soft hyphens and zero-width characters are removed;
- every run of white space becomes one space, and the ends are trimmed;
- letter case is kept;
- pdfium writes a hyphen at the end of a line as U+FFFE: it counts as a hyphen;
- for a PDF only, a line that ends in a hyphen and goes on with a letter may be joined. The text
  is searched in three ways: as it is, with the hyphen and the line break dropped ("trans-" and
  "former" give "transformer"), and with only the line break dropped ("English-" and "to-German"
  give "English-to-German").
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

_QUOTE_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2033": '"',
        "\ufffe": "-",
    }
)
_REMOVED = frozenset("\u00ad\u200b\u200c\u200d\u2060\ufeff")
_LINE_BREAK_AFTER_HYPHEN = re.compile(r"(?:\r\n|\r|\n)")
_HYPHENS = frozenset("-\u2010\ufffe")

LineHyphens = Literal["keep", "drop", "glue"]
LINE_HYPHEN_MODES: Final[tuple[LineHyphens, ...]] = ("keep", "drop", "glue")


@dataclass(frozen=True)
class Normalised:
    """Normalised text, and for each of its characters the span of the source it came from."""

    text: str
    starts: list[int]
    ends: list[int]

    def source_span(self, start: int, end: int) -> tuple[int, int]:
        """The source span `[a, b)` of the normalised span `[start, end)`."""
        return self.starts[start], self.ends[end - 1]


def normalise(text: str) -> str:
    """The normalised form of a quote (no map needed)."""
    return normalise_with_map(text).text


def normalise_with_map(text: str, *, line_hyphens: LineHyphens = "keep") -> Normalised:
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    pending_space: tuple[int, int] | None = None
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if line_hyphens != "keep" and char in _HYPHENS:
            line_break = _LINE_BREAK_AFTER_HYPHEN.match(text, index + 1)
            if line_break and line_break.end() < length and text[line_break.end()].isalpha():
                if line_hyphens == "glue":
                    # Keep the hyphen, drop the line break.
                    if pending_space is not None:
                        out.append(" ")
                        starts.append(pending_space[0])
                        ends.append(pending_space[1])
                        pending_space = None
                    out.append("-")
                    starts.append(index)
                    ends.append(index + 1)
                index = line_break.end()
                continue
        # A letter and the marks after it are normalised together.
        stop = index + 1
        while stop < length and unicodedata.combining(text[stop]):
            stop += 1
        for piece in unicodedata.normalize("NFKC", text[index:stop]).translate(_QUOTE_MAP):
            if piece in _REMOVED:
                continue
            if piece.isspace():
                if out and pending_space is None:
                    pending_space = (index, stop)
                continue
            if pending_space is not None:
                out.append(" ")
                starts.append(pending_space[0])
                ends.append(pending_space[1])
                pending_space = None
            out.append(piece)
            starts.append(index)
            ends.append(stop)
        index = stop
    return Normalised("".join(out), starts, ends)


def compact_copy(raw_text: str) -> str:
    """The text copy that is kept: the source's text without runs of blank lines. Normalising
    treats every run of white space alike, so a quote is found in this copy exactly where it is
    in the raw text.
    """
    text = re.sub(r"[ \t\r\f\v]+", " ", raw_text)
    text = re.sub(r" ?\n[ \n]*", "\n", text)
    return text.strip() + "\n"


@dataclass(frozen=True)
class Match:
    """Where a quote is: the source span of its first match, and how many matches there are."""

    start: int
    end: int
    count: int


def find_quote(source: Normalised, quote: str) -> Match | None:
    """Find a normalised `quote` in `source`. The first match is the one used."""
    if not quote:
        return None
    first = source.text.find(quote)
    if first < 0:
        return None
    count = 0
    position = first
    while position >= 0:
        count += 1
        position = source.text.find(quote, position + len(quote))
    start, end = source.source_span(first, first + len(quote))
    return Match(start, end, count)


def nearest_text(page_text: str, quote: str, *, limit: int = 3) -> list[str]:
    """Up to `limit` stretches of the page that look most like `quote`, for the agent to read
    the exact words from. `page_text` and `quote` are normalised.
    """
    suggestions: list[str] = []
    folded = page_text.casefold().find(quote.casefold()) if quote else -1
    if folded >= 0:
        suggestions.append(page_text[folded : folded + len(quote)])

    quote_words = quote.split()
    page_words = page_text.split()
    if not quote_words or not page_words:
        return suggestions
    wanted = {word.casefold() for word in quote_words}
    size = min(len(quote_words) + 2, len(page_words))
    # `hits[i]` counts the words before i that are in the quote, so a window's score is a
    # difference of two entries.
    hits = [0]
    for word in page_words:
        hits.append(hits[-1] + (1 if word.casefold() in wanted else 0))
    scored = sorted(
        ((hits[i + size] - hits[i], i) for i in range(len(page_words) - size + 1)),
        reverse=True,
    )
    chosen: list[int] = []
    for score, position in scored:
        if score == 0 or len(chosen) >= 40:
            break
        if all(abs(position - other) > size for other in chosen):
            chosen.append(position)
    ranked = sorted(
        (
            (
                difflib.SequenceMatcher(
                    None, quote, " ".join(page_words[p : p + size]), autojunk=False
                ).ratio(),
                p,
            )
            for p in chosen[:12]
        ),
        reverse=True,
    )
    for _, position in ranked:
        piece = " ".join(page_words[position : position + size])
        if piece not in suggestions:
            suggestions.append(piece)
        if len(suggestions) >= limit:
            break
    return suggestions[:limit]
