"""The "Sources" section of the YouTube description: a link for every piece of evidence the owner
accepted, with the words of the script it is evidence for.

The section is built by code from stored data only. The model never writes a link, a publisher or a
title. Two steps, both pure (no I/O):

- `entries_from_review` reads the owner's review and returns plain, cleaned entries. They are
  frozen on the `write_youtube_draft` job, like the rest of what the draft is made from:

      [{"claim": "the words of the script",
        "pieces": [{"publisher", "title", "published", "page", "relation", "url",
                    "archive_url"}]}]

- `block` turns the entries into the text, within the number of UTF-8 bytes there is room for.

The agent's text is untrusted (EV-7). Everything that is shown is cleaned here: no `<` or `>`
(YouTube refuses them), no control characters, and only http or https addresses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse

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


def _piece_of(item: Any) -> dict[str, Any] | None:
    """One accepted piece as a cleaned entry, or None when it has no usable address."""
    source = item.source if isinstance(item.source, dict) else {}
    url = _address(source.get("final_url")) or _address(source.get("url"))
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
            piece = _piece_of(item)
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
    """`- Publisher, "Title" (PDF, page 12, 2025-10-08, partly supports): https://...`"""
    name = ", ".join(
        part
        for part in (piece["publisher"], f'"{piece["title"]}"' if piece["title"] else None)
        if part
    )
    details: list[str] = []
    if piece["pdf"]:
        details.append("PDF")
    if piece["page"] is not None:
        details.append(f"page {piece['page']}")
    if piece["published"]:
        details.append(piece["published"])
    if piece["relation"]:
        details.append(_RELATION_LABELS[piece["relation"]])
    head = name or "Source"
    if details:
        head += f" ({', '.join(details)})"
    line = f"- {head}: {piece['url']}"
    if piece["archive_url"]:
        line += f" (archived: {piece['archive_url']})"
    return line


def _chunks(entries: object) -> list[tuple[str, int]]:
    """One text per claim, with the number of pieces in it."""
    chunks: list[tuple[str, int]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        claim = _clean(entry.get("claim"), CLAIM_MAX_CHARS)
        raw = entry.get("pieces")
        read = [_read_piece(piece) for piece in raw] if isinstance(raw, list) else []
        pieces = [piece for piece in read if piece is not None]
        if claim is None or not pieces:
            continue
        lines = [f'"{claim}"'] + [_piece_line(piece) for piece in pieces]
        chunks.append(("\n".join(lines), len(pieces)))
    return chunks


def block(entries: object, budget_bytes: int) -> str:
    """The Sources section, or "" when there is nothing to list or not even the first claim fits in
    `budget_bytes` (UTF-8 bytes). Claims are added whole, in order. When some are left out the
    section ends with a sentence that says how many sources are not listed.
    """
    chunks = _chunks(entries)
    for count in range(len(chunks), 0, -1):
        parts = [HEADING] + [text for text, _ in chunks[:count]]
        left_out = sum(pieces for _, pieces in chunks[count:])
        if left_out:
            noun = "source is" if left_out == 1 else "sources are"
            parts.append(f"{left_out} more {noun} not listed here for length.")
        text = "\n\n".join(parts)
        if _utf8_bytes(text) <= budget_bytes:
            return text
    return ""
