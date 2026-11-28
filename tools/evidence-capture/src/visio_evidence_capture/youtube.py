"""YouTube helpers that need no network: addresses, caption tracks, and finding a quote.

A caption track (YouTube's `json3` format) is a list of events, each with a start, a duration and
segments of text. A segment may carry its own offset from the event's start (automatic captions
do, about 86 % of the words); a segment without one starts with its event. No word has an end
time, so the end of a quote is the start of the word after it (or the end of its line): a first
guess only. The app's own transcription (SB-006) proves the words and the edges.

Finding a quote is a loose match: the quote and the captions are normalised the way `text.py`
does, casefolded and cut into words without punctuation. A stretch of the captions matches when
at least `QUOTE_MATCH_SHARE` of the quote's words are in it, in order.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

from . import QUOTE_MATCH_SHARE, YOUTUBE_HOSTS
from .rounds import Refused
from .text import normalise

VIDEO_ID: Final = re.compile(r"^[A-Za-z0-9_-]{11}$")
TIME_TEXT: Final = re.compile(r"^\d{1,5}(?::\d{1,2}){0,2}$", re.ASCII)
UPLOAD_DATE: Final = re.compile(r"^(\d{4})(\d{2})(\d{2})$")

# Sound labels in the captions, such as [Music] or [Applause], are not words.
_SOUND_LABEL = re.compile(r"\[[^\]]*\]")
_TOKEN = re.compile(r"\w+(?:'\w+)*")
# A quote needs at least this many words to be found by its words.
MIN_QUOTE_WORDS: Final = 4
# The least time a quote's last word is given when the captions give it no room.
MIN_LAST_WORD_S: Final = 0.3


# --- Addresses and small values ------------------------------------------------------------


def video_id_from_url(
    url: str, *, command: str = "video", other_command: str = "the web command"
) -> str:
    """The 11-character id of a YouTube video, from a watch, youtu.be, shorts or embed address.
    Anything else is refused. `command` and `other_command` name, in the refusal, the command
    that was run and the one to use for any other page.
    """
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname or ""
        parts.port  # noqa: B018 - reading it raises for a bad port
    except ValueError as error:
        raise Refused(f"{url!r} is not a valid address.") from error
    if parts.scheme not in ("http", "https"):
        raise Refused("Only http and https addresses are allowed.")
    if parts.username or parts.password:
        raise Refused("An address with a user name or password is refused (no logins).")
    if host not in YOUTUBE_HOSTS:
        raise Refused(
            f"The {command} command only takes YouTube addresses (youtube.com or youtu.be). "
            f"For another page, use {other_command}."
        )
    segments = [part for part in parts.path.split("/") if part]
    candidate: str | None = None
    if host == "youtu.be":
        candidate = segments[0] if segments else None
    elif segments[:1] == ["watch"]:
        candidate = (parse_qs(parts.query).get("v") or [None])[0]
    elif len(segments) >= 2 and segments[0] in ("shorts", "embed"):
        candidate = segments[1]
    if candidate is None or not VIDEO_ID.match(candidate):
        raise Refused(
            "That address is not a link to one YouTube video. Use the video's own address, for "
            "example https://www.youtube.com/watch?v=XXXXXXXXXXX."
        )
    return candidate


def watch_url(video_id: str) -> str:
    """The only address the tool hands to yt-dlp."""
    return f"https://www.youtube.com/watch?v={video_id}"


def parse_time(text: str) -> float:
    """`37:58`, `1:02:03` or plain seconds, as seconds."""
    if not TIME_TEXT.match(text.strip()):
        raise Refused("A time must look like 37:58 or 1:02:03 (or be plain seconds).")
    seconds = 0
    for piece in text.strip().split(":"):
        seconds = seconds * 60 + int(piece)
    return float(seconds)


def parse_time_tenths(text: str) -> float:
    """`2:21.5`, `1:02:03.5`, `141.5` or `141` as seconds. Used by the footage commands, which
    work to a tenth of a second. `parse_time` is unchanged."""
    cleaned = text.strip()
    whole, _, fraction = cleaned.partition(".")
    if fraction and not re.fullmatch(r"\d{1,3}", fraction, re.ASCII):
        raise Refused(
            "A time must look like 2:21.5, 1:02:03 or 141.5 (seconds, at most 3 decimals)."
        )
    seconds = parse_time(whole)
    return round(seconds + (float(f"0.{fraction}") if fraction else 0.0), 3)


def format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def upload_date_of(info: dict[str, Any]) -> str | None:
    """`YYYY-MM-DD` from yt-dlp's `YYYYMMDD`, or None."""
    found = UPLOAD_DATE.match(str(info.get("upload_date") or ""))
    return "-".join(found.groups()) if found else None


def format_time_tenths(seconds: float) -> str:
    """`2:21.5` or `1:02:03.5`: the time to a tenth of a second."""
    tenths = max(0, round(seconds * 10))
    whole, tenth = divmod(tenths, 10)
    return f"{format_time(whole)}.{tenth}"


def licence_of(info: dict[str, Any]) -> str:
    """`creative_commons`, `standard` or `unknown`.

    yt-dlp reports a licence only when the video has a Creative Commons one, so no licence
    means YouTube's standard licence. That is the stricter answer: the review then asks for a
    rights note. Any other licence text is `unknown`.
    """
    text = str(info.get("license") or "").strip().casefold()
    if not text:
        return "standard"
    if "creative commons" in text:
        return "creative_commons"
    return "unknown"


# --- Caption tracks ------------------------------------------------------------------------


def pick_caption_track(info: dict[str, Any]) -> tuple[str, str, str] | None:
    """`(source, language, address)` of the English `json3` track to use, or None.

    A track the uploader made comes first. Then YouTube's own recognition of the spoken
    language: `en-orig`, or `en` only when the video is in English. A machine translation into
    English is never used, because its words are not the speaker's.
    """

    def json3(tracks: object) -> str | None:
        for item in tracks if isinstance(tracks, list) else []:
            if isinstance(item, dict) and item.get("ext") == "json3" and item.get("url"):
                return str(item["url"])
        return None

    manual = info.get("subtitles") or {}
    for language in sorted(manual, key=lambda code: (code != "en", code)):
        if language == "en" or language.startswith("en-"):
            address = json3(manual[language])
            if address:
                return "manual", language, address
    automatic = info.get("automatic_captions") or {}
    video_language = str(info.get("language") or "").casefold()
    for language in ("en-orig", "en"):
        if language == "en" and not (video_language == "en" or video_language.startswith("en-")):
            continue
        address = json3(automatic.get(language))
        if address:
            return "automatic", language, address
    return None


@dataclass(frozen=True)
class CaptionWord:
    text: str
    start_s: float
    line: int  # index into Captions.lines


@dataclass(frozen=True)
class CaptionLine:
    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class Captions:
    lines: list[CaptionLine]
    words: list[CaptionWord]


def parse_json3(data: object) -> Captions:
    """The lines and words of a `json3` track. Events that are not text are skipped."""
    events = data.get("events") if isinstance(data, dict) else None
    if not isinstance(events, list):
        return Captions([], [])
    lines: list[CaptionLine] = []
    words: list[CaptionWord] = []
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("segs"), list):
            continue
        start = event.get("tStartMs")
        if not isinstance(start, int | float) or isinstance(start, bool):
            continue
        duration = event.get("dDurationMs")
        duration = duration if isinstance(duration, int | float) else 0
        found: list[tuple[str, float]] = []
        for seg in event["segs"]:
            if not isinstance(seg, dict) or not isinstance(seg.get("utf8"), str):
                continue
            offset = seg.get("tOffsetMs")
            offset = offset if isinstance(offset, int | float) and offset > 0 else 0
            for word in _SOUND_LABEL.sub(" ", seg["utf8"]).split():
                found.append((word, (start + offset) / 1000))
        if not found:
            continue
        line = len(lines)
        lines.append(
            CaptionLine(
                start_s=start / 1000,
                end_s=(start + duration) / 1000,
                text=" ".join(word for word, _ in found),
            )
        )
        words.extend(CaptionWord(word, at, line) for word, at in found)
    words.sort(key=lambda word: word.start_s)  # stable: equal times keep their order
    return Captions(lines, words)


# --- Finding a quote -----------------------------------------------------------------------


def _tokens_of(text: str) -> list[str]:
    return _TOKEN.findall(normalise(text).casefold())


def quote_word_count(quote: str) -> int:
    return len(_tokens_of(quote))


def _caption_tokens(words: list[CaptionWord]) -> tuple[list[str], list[int]]:
    """The caption words as tokens, and for each token the index of the word it came from."""
    tokens: list[str] = []
    owner: list[int] = []
    for index, word in enumerate(words):
        for token in _tokens_of(word.text):
            tokens.append(token)
            owner.append(index)
    return tokens, owner


def _candidates(
    tokens: list[str], wanted: list[str], min_hits: int
) -> list[tuple[float, int, int]]:
    """`(share, first token, last token)` for every stretch of the captions that has at least
    `min_hits` of the quote's words. The share is the part of the quote found in order.
    """
    if not wanted or not tokens:
        return []
    size = min(len(tokens), math.ceil(len(wanted) * 1.3) + 1)
    in_quote = set(wanted)
    hits = [0]
    for token in tokens:
        hits.append(hits[-1] + (1 if token in in_quote else 0))
    found: list[tuple[float, int, int]] = []
    for start in range(len(tokens) - size + 1):
        if hits[start + size] - hits[start] < min_hits:
            continue
        blocks = [
            block
            for block in SequenceMatcher(
                None, wanted, tokens[start : start + size], autojunk=False
            ).get_matching_blocks()
            if block.size
        ]
        if not blocks:
            continue
        matched = sum(block.size for block in blocks)
        first = start + min(block.b for block in blocks)
        last = start + max(block.b + block.size for block in blocks) - 1
        found.append((matched / len(wanted), first, last))
    return found


def _best_apart(
    candidates: list[tuple[float, int, int]],
) -> list[tuple[float, int, int]]:
    """Best share first, then the tighter stretch; a stretch that overlaps a better one is
    dropped.
    """
    ordered = sorted(candidates, key=lambda c: (-c[0], c[2] - c[1], c[1]))
    chosen: list[tuple[float, int, int]] = []
    for candidate in ordered:
        if all(candidate[2] < other[1] or candidate[1] > other[2] for other in chosen):
            chosen.append(candidate)
    return chosen


@dataclass(frozen=True)
class QuoteMatch:
    share: float
    start_s: float
    end_s: float
    text: str  # the caption words, as the captions have them


def _span_of(captions: Captions, first_word: int, last_word: int) -> tuple[float, float, str]:
    words = captions.words
    last = words[last_word]
    line_end = captions.lines[last.line].end_s
    following = words[last_word + 1].start_s if last_word + 1 < len(words) else None
    end = line_end if following is None else min(following, line_end)
    end = max(end, last.start_s + MIN_LAST_WORD_S)
    text = " ".join(word.text for word in words[first_word : last_word + 1])
    return words[first_word].start_s, end, text


def find_quote_in_captions(
    captions: Captions, quote: str, near_s: float | None = None
) -> list[QuoteMatch]:
    """Where the captions have the quote. The best match is first; with `near_s` the match
    closest to that time is first.
    """
    wanted = _tokens_of(quote)
    tokens, owner = _caption_tokens(captions.words)
    min_hits = math.ceil(QUOTE_MATCH_SHARE * len(wanted))
    good = [c for c in _candidates(tokens, wanted, min_hits) if c[0] >= QUOTE_MATCH_SHARE]
    matches: list[QuoteMatch] = []
    for share, first, last in _best_apart(good):
        start_s, end_s, text = _span_of(captions, owner[first], owner[last])
        matches.append(QuoteMatch(round(share, 3), start_s, end_s, text))
    if near_s is not None:
        matches.sort(key=lambda match: abs(match.start_s - near_s))
    return matches


def nearest_caption_lines(captions: Captions, quote: str, *, limit: int = 3) -> list[str]:
    """Up to `limit` stretches of the captions that look most like the quote, each with its
    time, for the agent to read the right words from.
    """
    wanted = _tokens_of(quote)
    tokens, owner = _caption_tokens(captions.words)
    candidates = _candidates(tokens, wanted, max(2, len(wanted) // 2))
    lines: list[str] = []
    for _, first, last in _best_apart(candidates)[:limit]:
        start_s, _, text = _span_of(captions, owner[first], owner[last])
        lines.append(f"{format_time(start_s)}  {text}")
    return lines
