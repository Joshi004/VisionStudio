"""The "Sources" section of the YouTube description: a short note on what was checked, then a
plain list of the sources the owner accepted, each address once (publisher, title, link). The
claims they back and how each one relates to a claim stay in the stored entries but are not
written in the description.

The section is built by code from stored data only. The model never writes a link, a publisher or a
title. Two steps, both pure (no I/O):

- `entries_from_review` reads the owner's review and returns plain, cleaned entries. They are
  frozen on the `write_youtube_draft` job, like the rest of what the draft is made from:

      [{"claim": "the words of the script",
        "pieces": [{"publisher", "title", "published", "page", "relation", "url",
                    "archive_url"}]}]

- `block` turns the entries and the model's note into the text, within the number of UTF-8 bytes
  there is room for. `names` gives the model the publisher and title of each source.

The agent's text is untrusted (EV-7). Everything that is shown is cleaned here: no `<` or `>`
(YouTube refuses them), no control characters, and only http or https addresses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse

from app.services import soundbite_render

if TYPE_CHECKING:
    from app.services.evidence_review import ReviewView

HEADING: Final = "Sources"
CLAIM_MAX_CHARS: Final = 150
TITLE_MAX_CHARS: Final = 120
PUBLISHER_MAX_CHARS: Final = 60
URL_MAX_CHARS: Final = 500

_ACCEPTED: Final = "accepted"
_RELATION_LABELS: Final = {
    "partly_supports": "partly supports",
    "context": "context",
    "contradicts": "contradicts",
}


# --- Cleaning --------------------------------------------------------------------------------


def _clean(value: object, limit: int) -> str | None:
    """One line of printable text without `<` or `>`, cut to `limit` characters, or None."""
    if not isinstance(value, str):
        return None
    kept = "".join(
        char for char in value if (char.isprintable() or char.isspace()) and char not in "<>"
    )
    text = " ".join(kept.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "\u2026"
    return text or None


def _address(value: object) -> str | None:
    """An http or https address that is safe to put in the description, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > URL_MAX_CHARS:
        return None
    if any(char.isspace() or not char.isprintable() or char in "<>" for char in text):
        return None
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return text


def _watch_address(item: Any, details: dict[str, Any] | None) -> str | None:
    """The address of a video piece at the second that matters (SB-009), built from the video's
    11-character id: where the accepted clip's cut starts, or where the quote is said in a video
    that is only context. None for any other piece, and when the second is not known."""
    capture = item.capture if isinstance(item.capture, dict) else {}
    window = capture.get("window") if isinstance(capture.get("window"), dict) else {}
    quote_at = capture.get("quote_at_s") if isinstance(capture.get("quote_at_s"), dict) else {}
    if details is not None:
        second = soundbite_render.start_second(window.get("start_s"), details.get("in_s"))
    else:
        second = soundbite_render.start_second(quote_at.get("start"), 0)
    if second is None:
        return None
    return soundbite_render.watch_url(capture.get("video_id"), second)


def _piece_of(item: Any, details: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """One accepted piece as a cleaned entry, or None when it has no usable address. A video
    piece links to the second it is about (`_watch_address`); `details` are the owner's details
    of an accepted sound bite clip."""
    source = item.source if isinstance(item.source, dict) else {}
    url = _address(source.get("final_url")) or _address(source.get("url"))
    if item.kind == "video":
        url = _watch_address(item, details) or url
    if url is None:
        return None
    capture = item.capture if isinstance(item.capture, dict) else {}
    page = capture.get("page")
    return {
        "publisher": _clean(source.get("publisher"), PUBLISHER_MAX_CHARS),
        "title": _clean(source.get("title"), TITLE_MAX_CHARS),
        "published": _clean(source.get("published"), 20),
        "page": page if item.kind == "pdf" and isinstance(page, int) and page > 0 else None,
        "pdf": item.kind == "pdf",
        "relation": item.relation if item.relation in _RELATION_LABELS else None,
        "url": url,
        "archive_url": _address(source.get("archive_url")),
    }


def entries_from_review(view: ReviewView) -> list[dict[str, Any]]:
    """The claims that have accepted evidence, in the review's order, each with its accepted pieces
    in the import's order. A piece that is not usable, was not accepted, has no usable address or
    repeats an address of the same claim is left out, and so is a claim left with no piece. The
    result holds only text and numbers, so it can be stored on the job.
    """
    entries: list[dict[str, Any]] = []
    for claim in view.claims:
        text = _clean(claim.entry.get("text"), CLAIM_MAX_CHARS)
        if text is None:
            continue
        pieces: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in claim.items:
            if not item.usable or claim.decision.verdicts.get(item.item_key) != _ACCEPTED:
                continue
            piece = _piece_of(item, claim.decision.soundbites.get(item.item_key))
            if piece is None or piece["url"] in seen:
                continue
            seen.add(piece["url"])
            pieces.append(piece)
        if pieces:
            entries.append({"claim": text, "pieces": pieces})
    return entries


# --- The text --------------------------------------------------------------------------------


def _utf8_bytes(text: str) -> int:
    return len(text.encode("utf-8"))


def _read_piece(piece: object) -> dict[str, Any] | None:
    """A stored piece, checked again (the job input is read back from the database)."""
    if not isinstance(piece, dict):
        return None
    url = _address(piece.get("url"))
    if url is None:
        return None
    page = piece.get("page")
    return {
        "publisher": _clean(piece.get("publisher"), PUBLISHER_MAX_CHARS),
        "title": _clean(piece.get("title"), TITLE_MAX_CHARS),
        "published": _clean(piece.get("published"), 20),
        "page": page if isinstance(page, int) and not isinstance(page, bool) and page > 0 else None,
        "pdf": piece.get("pdf") is True,
        "relation": piece.get("relation") if piece.get("relation") in _RELATION_LABELS else None,
        "url": url,
        "archive_url": _address(piece.get("archive_url")),
    }


def _piece_line(piece: dict[str, Any]) -> str:
    """`- Publisher, "Title": https://...` (a piece with neither is `- Source: https://...`)."""
    name = ", ".join(
        part
        for part in (piece["publisher"], f'"{piece["title"]}"' if piece["title"] else None)
        if part
    )
    return f"- {name or 'Source'}: {piece['url']}"


def _unique_pieces(entries: object) -> list[dict[str, Any]]:
    """The usable pieces of every claim as one list, in the review's order, each address once."""
    pieces: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries if isinstance(entries, list) else []:
        raw = entry.get("pieces") if isinstance(entry, dict) else None
        for item in raw if isinstance(raw, list) else []:
            piece = _read_piece(item)
            if piece is None or piece["url"] in seen:
                continue
            seen.add(piece["url"])
            pieces.append(piece)
    return pieces


def names(entries: object) -> list[dict[str, str]]:
    """The publisher and title of each source, once, without an address: what the model is told
    so that its note on the sources is about the sources the video really has.
    """
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for piece in _unique_pieces(entries):
        key = (piece["publisher"] or "", piece["title"] or "")
        if key == ("", "") or key in seen:
            continue
        seen.add(key)
        found.append({"publisher": key[0], "title": key[1]})
    return found


def block(entries: object, budget_bytes: int, note: str = "") -> str:
    """The Sources section: the heading, the `note` (a sentence or two on what was checked, may be
    empty) and one line for every source, each address once. "" when there is no source to list
    or not even the first one fits in `budget_bytes` (UTF-8 bytes). Sources are added in order;
    when some are left out the section ends with a sentence that says how many are not listed.
    When the note is what stops it from fitting, the note is left out.
    """
    pieces = _unique_pieces(entries)
    clean_note = _clean(note, 400) or ""
    for with_note in (True, False) if clean_note else (False,):
        for count in range(len(pieces), 0, -1):
            parts = [HEADING]
            if with_note:
                parts.append(clean_note)
            parts.append("\n".join(_piece_line(piece) for piece in pieces[:count]))
            left_out = len(pieces) - count
            if left_out:
                noun = "source is" if left_out == 1 else "sources are"
                parts.append(f"{left_out} more {noun} not listed here for length.")
            text = parts[0] + "\n" + "\n\n".join(parts[1:])
            if _utf8_bytes(text) <= budget_bytes:
                return text
    return ""
