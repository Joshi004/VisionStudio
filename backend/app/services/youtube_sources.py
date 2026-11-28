"""The "Sources" section of the YouTube description: a short note on what was checked, then a
short list of the sources the owner accepted, in groups (articles and websites, documents, videos,
footage and images). Each publisher is listed once with one plain link (a YouTube link has no
time in it); the title is not written. The claims the sources back and how each one relates to a
claim stay in the stored entries but are not written in the description.

The section is built by code from stored data only. The model never writes a link, a publisher or a
title. Two steps, both pure (no I/O):

- `entries_from_review` reads the owner's review and returns plain, cleaned entries. They are
  frozen on the `write_youtube_draft` job, like the rest of what the draft is made from:

      [{"claim": "the words of the script",
        "pieces": [{"publisher", "title", "published", "page", "pdf", "video", "relation",
                    "url", "archive_url"}]}]

- `block` turns the entries and the model's note into the text, within the number of UTF-8 bytes
  there is room for. `names` gives the model the publisher and title of each source.

The agent's text is untrusted (EV-7). Everything that is shown is cleaned here: no `<` or `>`
(YouTube refuses them), no control characters, and only http or https addresses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from app.services import soundbite_render

if TYPE_CHECKING:
    from app.services.evidence_review import ReviewView

HEADING: Final = "Sources"
CLAIM_MAX_CHARS: Final = 150
TITLE_MAX_CHARS: Final = 120
PUBLISHER_MAX_CHARS: Final = 60
URL_MAX_CHARS: Final = 500

# The groups of the list, in the order they are shown.
GROUP_ARTICLES: Final = "Articles and websites"
GROUP_DOCUMENTS: Final = "Documents"
GROUP_VIDEOS: Final = "Videos"
GROUP_FOOTAGE: Final = "Footage and images"
GROUP_ORDER: Final = (GROUP_ARTICLES, GROUP_DOCUMENTS, GROUP_VIDEOS, GROUP_FOOTAGE)

_YOUTUBE_HOSTS: Final = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
_YOUTUBE_TIME_PARAMETERS: Final = frozenset({"t", "start"})

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
        "video": item.kind == "video",
        "relation": item.relation if item.relation in _RELATION_LABELS else None,
        "url": url,
        "archive_url": _address(source.get("archive_url")),
    }


def footage_piece(
    item: Any, credit: str | None, use_start_s: float | None
) -> dict[str, Any] | None:
    """One piece of footage that is in the video (FTG-006) as a cleaned entry, or None when it has
    nothing to list. An agent's piece gives its publisher, title and address; a video's address
    is built from its 11-character id at the second `use_start_s` of the stored video (the
    capture's window moves it back to the source video). An owner's file, or a piece with no
    address, is listed by its `credit` line alone. Pure.
    """
    source = item.source if isinstance(item.source, dict) else {}
    capture = item.capture if isinstance(item.capture, dict) else {}
    url = None
    if item.origin != "owner":
        url = _address(source.get("final_url")) or _address(source.get("url"))
        if item.kind == "video":
            window = capture.get("window") if isinstance(capture.get("window"), dict) else {}
            second = soundbite_render.start_second(window.get("start_s"), use_start_s)
            url = soundbite_render.watch_url(capture.get("video_id"), second) or url
    credit_text = _clean(credit, 160)
    publisher = _clean(source.get("publisher"), PUBLISHER_MAX_CHARS) if url else None
    title = _clean(source.get("title"), TITLE_MAX_CHARS) if url else None
    if url is None and credit_text is None:
        return None
    return {"publisher": publisher, "title": title, "url": url, "credit": credit_text}


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
        # Entries stored before this flag existed have none; `_group_of` also checks the address.
        "video": piece.get("video") is True,
        "relation": piece.get("relation") if piece.get("relation") in _RELATION_LABELS else None,
        "url": url,
        "archive_url": _address(piece.get("archive_url")),
    }


def _is_youtube(url: str) -> bool:
    return (urlparse(url).hostname or "") in _YOUTUBE_HOSTS


def _plain_address(url: str) -> str:
    """The address as it is listed: a YouTube address loses its time (`t`, `start`) and its
    fragment, so one video cited at several moments has one link. Any other address is as it is."""
    if not _is_youtube(url):
        return url
    parts = urlsplit(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _YOUTUBE_TIME_PARAMETERS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))


def _domain(url: str) -> str:
    """The website of an address without `www.`, or "" when it has none."""
    return (urlparse(url).hostname or "").removeprefix("www.")


def _group_of(piece: dict[str, Any]) -> str:
    """The group of an accepted piece of evidence: a PDF is a document, a video (by its kind, or
    by its address for an entry stored before the kind was kept) is a video, the rest are
    articles and websites."""
    if piece["pdf"]:
        return GROUP_DOCUMENTS
    if piece["video"] or _is_youtube(piece["url"]):
        return GROUP_VIDEOS
    return GROUP_ARTICLES


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


def _read_footage(entry: object) -> dict[str, Any] | None:
    """A stored footage entry (`footage_piece`), checked again (the job input is read back from the
    database): an address that is safe, or a credit line, or both."""
    if not isinstance(entry, dict):
        return None
    url = _address(entry.get("url"))
    credit = _clean(entry.get("credit"), 160)
    if url is None and credit is None:
        return None
    return {
        "publisher": _clean(entry.get("publisher"), PUBLISHER_MAX_CHARS),
        "title": _clean(entry.get("title"), TITLE_MAX_CHARS),
        "url": url,
        "credit": credit,
    }


def _listed_sources(entries: object, footage: object) -> list[dict[str, Any]]:
    """The sources to list, each publisher once: `{"group", "name", "url"}`, ordered by group
    (see `GROUP_ORDER`), then as they came. A source is its publisher, or its website when it has
    no publisher, or the credit line of an owner's file that has no address (then `url` is None).
    The first address of a publisher is its link, and the group of its first appearance is its
    group. The evidence comes first, so a publisher of footage who is already a source of the
    evidence is not listed again. A YouTube link has no time in it.
    """
    listed: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(group: str, name: str, url: str | None) -> None:
        key = name.casefold()
        if key in seen:
            return
        seen.add(key)
        listed.append({"group": group, "name": name, "url": url})

    for piece in _unique_pieces(entries):
        name = piece["publisher"] or _domain(piece["url"]) or "Source"
        add(_group_of(piece), name, _plain_address(piece["url"]))
    for raw in footage if isinstance(footage, list | tuple) else []:
        entry = _read_footage(raw)
        if entry is None:
            continue
        if entry["url"] is None:
            add(GROUP_FOOTAGE, entry["credit"], None)
        else:
            name = entry["publisher"] or _domain(entry["url"]) or "Source"
            add(GROUP_FOOTAGE, name, _plain_address(entry["url"]))
    listed.sort(key=lambda source: GROUP_ORDER.index(source["group"]))
    return listed


def _group_blocks(listed: list[dict[str, Any]], names_only: int) -> list[str]:
    """One block of text for every group that has a source: the group's name, then `- Name: link`
    for each of its sources (`- Name` for one that has no link, or one of the last `names_only`
    sources of `listed`, which go without their link to save room)."""
    first_without_link = len(listed) - names_only
    blocks: list[str] = []
    for group in GROUP_ORDER:
        lines = [
            f"- {source['name']}: {source['url']}"
            if source["url"] and index < first_without_link
            else f"- {source['name']}"
            for index, source in enumerate(listed)
            if source["group"] == group
        ]
        if lines:
            blocks.append(group + "\n" + "\n".join(lines))
    return blocks


def block(entries: object, budget_bytes: int, note: str = "", footage: object = ()) -> str:
    """The Sources section: the heading, the `note` (a sentence or two on what was checked, may be
    empty) and the sources in groups (articles and websites, documents, videos, footage and
    images), each publisher once with one plain link. The sources of the footage in the video
    (FTG-006) follow those of the evidence. "" when there is no source to list or the section does
    not fit in `budget_bytes` (UTF-8 bytes). When it does not fit, the note is left out first;
    then more and more of the last sources are listed by name only, without their link. No source
    is ever left out of the list.
    """
    listed = _listed_sources(entries, footage)
    if not listed:
        return ""
    clean_note = _clean(note, 400) or ""
    # (whether the note is kept, how many of the last sources have no link), most complete first.
    attempts = [(True, 0)] if clean_note else []
    attempts += [(False, names_only) for names_only in range(len(listed) + 1)]
    for with_note, names_only in attempts:
        parts = [clean_note] if with_note else []
        parts += _group_blocks(listed, names_only)
        text = HEADING + "\n" + "\n\n".join(parts)
        if _utf8_bytes(text) <= budget_bytes:
            return text
    return ""
