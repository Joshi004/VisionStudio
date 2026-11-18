"""Normalising a quote and finding it in a source's text (EVD-006).

**This repeats the rules of the capture tool exactly** (`tools/evidence-capture/src/
visio_evidence_capture/text.py` and `find_in_text`, `open_pdf`, `page_text` of `pdf.py`,
`Evidence_layer_implementation_phases.md` §4.5 and §4.6 check 3). The tool is not part of the
backend's image, so the code is copied here. A change to the rules must be made in both places.

- NFKC (applied to a letter and the marks after it together);
- curly quotes become straight quotes;
- soft hyphens and zero-width characters are removed;
- every run of white space becomes one space, and the ends are trimmed;
- letter case is kept;
- pdfium writes a hyphen at the end of a line as U+FFFE: it counts as a hyphen;
- for a PDF only, a line that ends in a hyphen and goes on with a letter may be joined. The text
  is searched in three ways: as it is (`keep`), with the hyphen and the line break dropped
  (`drop`, "trans-" and "former" give "transformer"), and with only the line break dropped
  (`glue`, "English-" and "to-German" give "English-to-German").

PDFs are read with pypdfium2, as the tool does, so the same text is seen.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

import pypdfium2 as pdfium

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


class PdfRefused(Exception):
    """A PDF that cannot be read. The message is meant to be shown to the owner."""


@dataclass(frozen=True)
class Normalised:
    """Normalised text, and for each of its characters the span of the source it came from."""

    text: str
    starts: list[int]
    ends: list[int]


def normalise(text: str) -> str:
    """The normalised form of a quote."""
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


def quote_in_text(text: str, wanted: str) -> bool:
    """Whether the normalised quote `wanted` is in a web page's text copy."""
    return bool(wanted) and wanted in normalise_with_map(text).text


def quote_in_pdf_text(raw: str, wanted: str) -> bool:
    """Whether the normalised quote `wanted` is in a PDF page's text, read the three ways."""
    if not wanted:
        return False
    return any(
        wanted in normalise_with_map(raw, line_hyphens=mode).text for mode in LINE_HYPHEN_MODES
    )


def open_pdf(data: bytes) -> pdfium.PdfDocument:
    """Opens PDF bytes. Refuses a damaged or password-protected file, or one with no pages."""
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        raise PdfRefused(
            "The PDF cannot be opened (it may be damaged or password-protected)."
        ) from error
    if len(document) == 0:
        document.close()
        raise PdfRefused("The PDF has no pages.")
    return document


def page_text(document: pdfium.PdfDocument, index: int) -> str:
    """The text of one page (0-based) as pdfium reads it."""
    page = document[index]
    text_page = page.get_textpage()
    try:
        return text_page.get_text_range()
    finally:
        text_page.close()
        page.close()
