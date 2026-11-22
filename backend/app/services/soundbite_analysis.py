"""What the app knows about a sound bite clip once Parakeet has heard it (SB-006,
`Sound_bite_implementation_phases.md` §4.6 and §4.7).

Pure: heard words, samples and details go in, the fidelity class, the proposed trim and the flags
come out. Nothing here reads a file or the database; `services/soundbite_clips.py` decodes the
audio and stores the result.

The agent's quote and YouTube's captions only found the moment (SB-6). **The words are proved
here**, by comparing what Parakeet heard in the clip with the claim's words:

- `find_quote` finds the stretch of heard words that best matches the quote;
- `fidelity_of` names how well it matches: `exact`, `near`, `paraphrase` or `mismatch` (only the
  first two can be shown);
- `propose_trim` puts the in and out points in the quietest place of the gap next to the first and
  last quote word, using the audio itself and not only the word times (Parakeet's times are on an
  ~80 ms grid);
- `flags` lists what the owner must acknowledge before accepting the clip (never a refusal).

Every number that decides a result is a constant below. They are starting values, checked on real
clips in SB-006 and tuned by ear later; `ANALYSIS_VERSION` goes up when a rule changes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from app.services.dialogue_check import normalize_words

ANALYSIS_VERSION: Final = 1

FIDELITIES: Final = ("exact", "near", "paraphrase", "mismatch")

# --- finding the quote -------------------------------------------------------------------------

# Words that are not part of what a person means (SB-6 "after normalising filler words").
FILLER_WORDS: Final = frozenset({"um", "uh", "er", "erm", "ah", "hmm", "mm", "mhm", "uhm", "umm"})
# Short forms written out, so "don't" and "do not" are the same words. Apostrophes are already
# dropped by `normalize_words`, so the keys have none.
_CONTRACTIONS: Final[dict[str, tuple[str, ...]]] = {
    "dont": ("do", "not"),
    "doesnt": ("does", "not"),
    "didnt": ("did", "not"),
    "cant": ("can", "not"),
    "cannot": ("can", "not"),
    "wont": ("will", "not"),
    "isnt": ("is", "not"),
    "arent": ("are", "not"),
    "wasnt": ("was", "not"),
    "werent": ("were", "not"),
    "havent": ("have", "not"),
    "hasnt": ("has", "not"),
    "hadnt": ("had", "not"),
    "wouldnt": ("would", "not"),
    "couldnt": ("could", "not"),
    "shouldnt": ("should", "not"),
    "im": ("i", "am"),
    "ive": ("i", "have"),
    "id": ("i", "would"),
    "ill": ("i", "will"),
    "youre": ("you", "are"),
    "youve": ("you", "have"),
    "youll": ("you", "will"),
    "theyre": ("they", "are"),
    "theyve": ("they", "have"),
    "weve": ("we", "have"),
    "thats": ("that", "is"),
    "whats": ("what", "is"),
    "theres": ("there", "is"),
    "lets": ("let", "us"),
    "gonna": ("going", "to"),
    "wanna": ("want", "to"),
}
# A stretch of heard words is tried from 0.7 to 1.3 times the quote's length.
MIN_LENGTH_RATIO: Final = 0.7
MAX_LENGTH_RATIO: Final = 1.3

# --- fidelity classes --------------------------------------------------------------------------

# `near`: at least this share of the quote's words matched, and no more than
# max(NEAR_MIN_DIFFERENCES, NEAR_SHARE of the quote's words) words differ (missing or extra).
NEAR_MATCH_SHARE: Final = 0.85
NEAR_MIN_DIFFERENCES: Final = 2
NEAR_DIFFERENCE_SHARE: Final = 0.15
# `paraphrase`: at least this share matched. Less is a `mismatch`.
PARAPHRASE_MATCH_SHARE: Final = 0.5

# --- the trim ----------------------------------------------------------------------------------

FRAME_S: Final = 0.010
# "Quiet" is the higher of two limits, so a pause in a noisy room still counts and a pause in a
# silent studio is not asked to be quieter than it is (checked on five real clips, SB-006):
# this far under the median level over the quote's words, or this far over the clip's room tone
# (the 10th percentile of its frame levels). It is never less than QUIET_MIN_BELOW_SPEECH_DB
# under the speech.
QUIET_BELOW_SPEECH_DB: Final = 20.0
QUIET_ABOVE_ROOM_TONE_DB: Final = 6.0
QUIET_MIN_BELOW_SPEECH_DB: Final = 10.0
ROOM_TONE_PERCENTILE: Final = 10
# The in point is looked for from this long before the first word to MIN_EDGE_GAP_S before it.
IN_REACH_S: Final = 0.5
# The out point from OUT_NEAR_S to OUT_REACH_S after the last word (never into the next word); in
# a gap too short for that, from MIN_EDGE_GAP_S.
OUT_NEAR_S: Final = 0.15
OUT_REACH_S: Final = 0.4
# The cut must stay this far from the next or the previous word.
MIN_EDGE_GAP_S: Final = 0.08
# Among frames within this many dB of the quietest, the one nearest the preferred place wins.
TIE_DB: Final = 1.0
PREFERRED_IN_BEFORE_S: Final = 0.1
# Frames of the level are averaged over this many frames, so one click is not "the quietest".
SMOOTH_FRAMES: Final = 3

# --- flags -------------------------------------------------------------------------------------

TURN_AFTER_WORDS: Final = 30
CONTEXT_BEFORE_WORDS: Final = 10
LAUGHTER_REACH_S: Final = 5.0
MIN_CLIP_S: Final = 3.0
MAX_CLIP_S: Final = 15.0
# Above this the review warns (it still accepts up to MAX_CLIP_S): §4.7 "warn above 12 s".
WARN_CLIP_S: Final = 12.0

TURN_PHRASES: Final = (
    "but",
    "however",
    "although",
    "though",
    "that said",
    "on the other hand",
    "i was wrong",
    "not really",
)
REPORTED_PHRASES: Final = (
    "he said",
    "she said",
    "they said",
    "they say",
    "people say",
    "told me",
)
HYPOTHETICAL_PHRASES: Final = ("imagine", "suppose", "what if", "pretend")
SENSITIVE_WORDS: Final = frozenset(
    {
        "resign",
        "resigns",
        "resigned",
        "resigning",
        "resignation",
        "allegation",
        "allegations",
        "alleged",
        "allegedly",
        "investigation",
        "investigations",
        "investigated",
        "lawsuit",
        "lawsuits",
        "fraud",
        "scandal",
        "accused",
        "misconduct",
        "charged",
        "arrested",
    }
)
ADMISSION_PHRASES: Final = (
    "mistake",
    "mistakes",
    "sorry",
    "apologise",
    "apologize",
    "apologised",
    "apologized",
    "regret",
    "regrets",
    "wrong",
    "my fault",
    "i admit",
)
_LAUGH_LABEL: Final = re.compile(r"[\[(][^\])]*laugh[^\])]*[\])]", re.IGNORECASE)


@dataclass(frozen=True)
class HeardWord:
    """One word Parakeet heard, in seconds from the start of the clip."""

    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Match:
    """Where the quote is among the heard words. `first` and `last` are positions in the list of
    heard words (both included)."""

    first: int
    last: int
    matched: int
    quote_tokens: int
    missing: int
    extra: int
    diff: list[dict[str, str]]

    @property
    def share(self) -> float:
        return self.matched / self.quote_tokens if self.quote_tokens else 0.0


@dataclass(frozen=True)
class Analysis:
    """What `analyse` finds."""

    fidelity: str
    heard_words: dict[str, Any]
    proposed_trim: dict[str, Any] | None
    flags: list[dict[str, str]]


# --- words -------------------------------------------------------------------------------------


def tokens_of(text: str) -> list[str]:
    """The words of a text for comparison: `normalize_words`, without filler words, with short
    forms written out. Pure."""
    tokens: list[str] = []
    for word in normalize_words(text):
        if word in FILLER_WORDS:
            continue
        tokens.extend(_CONTRACTIONS.get(word, (word,)))
    return tokens


def _heard_tokens(words: list[HeardWord]) -> list[tuple[str, int]]:
    """The heard words as tokens, each with the position of the heard word it comes from."""
    found: list[tuple[str, int]] = []
    for position, word in enumerate(words):
        for token in tokens_of(word.text):
            found.append((token, position))
    return found


# --- finding the quote -------------------------------------------------------------------------


def _matching_pairs(quote: list[str], heard: list[str]) -> list[tuple[int, int]]:
    """The tokens of `quote` and `heard` that match, in order, as (quote index, heard index)."""
    pairs: list[tuple[int, int]] = []
    matcher = SequenceMatcher(None, quote, heard, autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            pairs.append((block.a + offset, block.b + offset))
    return pairs


def find_quote(quote: str, words: list[HeardWord], near_s: float | None = None) -> Match | None:
    """The stretch of heard words that best matches `quote`, or None when no word matches.

    Stretches of 0.7 to 1.3 times the quote's length are tried from every heard word that is in
    the quote. The best share of the quote's words wins; then the fewer extra words; then the one
    nearest `near_s` (seconds from the clip's start, where the captions put the quote).
    """
    wanted = tokens_of(quote)
    heard = _heard_tokens(words)
    if not wanted or not heard:
        return None
    wanted_set = set(wanted)
    count = len(wanted)
    shortest = max(1, math.ceil(count * MIN_LENGTH_RATIO))
    longest = max(shortest, math.floor(count * MAX_LENGTH_RATIO))
    step = max(1, count // 20)
    heard_tokens = [token for token, _position in heard]

    best: tuple[tuple[float, int, float], Match] | None = None
    for begin, token in enumerate(heard_tokens):
        if token not in wanted_set:
            continue
        for length in sorted({*range(shortest, longest + 1, step), longest}):
            stretch = heard_tokens[begin : begin + length]
            pairs = _matching_pairs(wanted, stretch)
            if not pairs:
                continue
            matched = len(pairs)
            first_in_stretch, last_in_stretch = pairs[0][1], pairs[-1][1]
            span_first = begin + first_in_stretch
            span_last = begin + last_in_stretch
            span_length = last_in_stretch - first_in_stretch + 1
            extra = span_length - matched
            first_word = heard[span_first][1]
            distance = abs(words[first_word].start - near_s) if near_s is not None else 0.0
            # Higher share is better, then fewer extra words, then nearer the captions' time.
            key = (-matched / count, extra, distance)
            if best is not None and key >= best[0]:
                continue
            best = (
                key,
                Match(
                    first=first_word,
                    last=heard[span_last][1],
                    matched=matched,
                    quote_tokens=count,
                    missing=count - matched,
                    extra=extra,
                    diff=_diff(wanted, heard_tokens[span_first : span_last + 1]),
                ),
            )
    return best[1] if best is not None else None


def _diff(quote: list[str], heard: list[str]) -> list[dict[str, str]]:
    """What differs between the quote and the heard stretch: `{op, script, heard}` where op is
    `replace`, `delete` (said in the script, not heard) or `insert` (heard, not in the script)."""
    changes: list[dict[str, str]] = []
    matcher = SequenceMatcher(None, quote, heard, autojunk=False)
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.append(
            {"op": tag, "script": " ".join(quote[a1:a2]), "heard": " ".join(heard[b1:b2])}
        )
    return changes


def fidelity_of(match: Match | None) -> str:
    """`exact`, `near`, `paraphrase` or `mismatch` for a match (see the constants)."""
    if match is None:
        return "mismatch"
    if match.missing == 0 and match.extra == 0:
        return "exact"
    allowed = max(NEAR_MIN_DIFFERENCES, math.ceil(NEAR_DIFFERENCE_SHARE * match.quote_tokens))
    if match.share >= NEAR_MATCH_SHARE and match.missing + match.extra <= allowed:
        return "near"
    if match.share >= PARAPHRASE_MATCH_SHARE:
        return "paraphrase"
    return "mismatch"


# --- the trim ----------------------------------------------------------------------------------


def _levels_db(samples: NDArray[np.float32], rate: int) -> NDArray[np.float64]:
    """The level of each 10 ms frame in dB (mean square, relative to full scale), lightly
    smoothed. Silence reads -120, never -inf."""
    size = max(1, round(rate * FRAME_S))
    count = len(samples) // size
    if count < 1:
        return np.zeros(0, dtype=np.float64)
    frames = samples[: count * size].reshape(count, size).astype(np.float64)
    energy = np.mean(np.square(frames), axis=1)
    level = 10.0 * np.log10(np.maximum(energy, 1e-12))
    if count >= SMOOTH_FRAMES:
        kernel = np.full(SMOOTH_FRAMES, 1.0 / SMOOTH_FRAMES)
        level = np.convolve(np.pad(level, SMOOTH_FRAMES // 2, mode="edge"), kernel, mode="valid")
    return level


def _quietest(level: NDArray[np.float64], low_s: float, high_s: float, prefer_s: float) -> int:
    """The frame in `low_s` to `high_s` with the lowest level; among frames within TIE_DB of it,
    the one nearest `prefer_s`. The range must hold at least one frame."""
    first = max(0, math.ceil(low_s / FRAME_S))
    last = min(len(level) - 1, math.floor(high_s / FRAME_S))
    window = level[first : last + 1]
    lowest = float(np.min(window))
    candidates = [first + i for i, value in enumerate(window) if value <= lowest + TIE_DB]
    return min(candidates, key=lambda frame: abs(frame * FRAME_S - prefer_s))


def propose_trim(
    samples: NDArray[np.float32],
    rate: int,
    words: list[HeardWord],
    first: int,
    last: int,
    duration_s: float,
) -> dict[str, Any] | None:
    """The proposed in and out points, in seconds from the clip's start, for the quote that runs
    from heard word `first` to heard word `last`: `{in_s, out_s, in_clean, out_clean}`.

    Each point is the quietest frame of the gap next to the quote's edge word. A point is
    **clean** when the neighbouring word is at least MIN_EDGE_GAP_S away and the chosen frame is
    quiet (see QUIET_BELOW_SPEECH_DB). When there is no such gap the point is the middle of
    what gap there is, and not clean. None when the audio is too short to measure.
    """
    level = _levels_db(samples, rate)
    if len(level) < 2:
        return None
    onset, offset = words[first].start, words[last].end
    # The speech level: the median over the frames of the quote's words.
    speech = level[
        max(0, math.floor(onset / FRAME_S)) : min(len(level), math.ceil(offset / FRAME_S))
    ]
    if len(speech) == 0:
        return None
    speech_level = float(np.median(speech))
    room_tone = float(np.percentile(level, ROOM_TONE_PERCENTILE))
    quiet_limit = min(
        max(speech_level - QUIET_BELOW_SPEECH_DB, room_tone + QUIET_ABOVE_ROOM_TONE_DB),
        speech_level - QUIET_MIN_BELOW_SPEECH_DB,
    )

    previous_end = words[first - 1].end if first > 0 else 0.0
    # In point.
    low = max(previous_end, onset - IN_REACH_S, 0.0)
    high = onset - MIN_EDGE_GAP_S
    if high >= low:
        frame = _quietest(level, low, high, onset - PREFERRED_IN_BEFORE_S)
        in_s = frame * FRAME_S
        in_clean = bool(level[frame] <= quiet_limit)
    else:
        in_s = max(0.0, (previous_end + onset) / 2) if first > 0 else max(0.0, onset - 0.05)
        in_clean = False

    # Out point.
    next_start = words[last + 1].start if last + 1 < len(words) else None
    low = offset + OUT_NEAR_S
    high = offset + OUT_REACH_S
    if next_start is not None:
        high = min(high, next_start - MIN_EDGE_GAP_S)
    high = min(high, duration_s)
    if high < low:
        # A short gap: the cut may sit as near the last word as the first one allows.
        low = offset + MIN_EDGE_GAP_S
    if high >= low:
        frame = _quietest(level, low, high, (low + high) / 2)
        out_s = frame * FRAME_S
        out_clean = bool(level[frame] <= quiet_limit)
    else:
        ceiling = next_start if next_start is not None else duration_s
        out_s = min((offset + ceiling) / 2, duration_s)
        out_clean = False
    in_s = min(max(in_s, 0.0), duration_s)
    out_s = min(max(out_s, in_s), duration_s)
    return {
        "in_s": round(in_s, 3),
        "out_s": round(out_s, 3),
        "in_clean": in_clean,
        "out_clean": out_clean,
    }


# --- flags -------------------------------------------------------------------------------------


def _has_phrase(tokens: list[str], phrases: tuple[str, ...]) -> str | None:
    """The first phrase (words in a row) of `phrases` that is in `tokens`, or None."""
    for phrase in phrases:
        parts = phrase.split()
        for start in range(len(tokens) - len(parts) + 1):
            if tokens[start : start + len(parts)] == parts:
                return phrase
    return None


def _normalised_name(text: object) -> str:
    return "".join(normalize_words(text)) if isinstance(text, str) else ""


def _laughter_times(captions: Any) -> list[float]:
    """The times (seconds in the video) of caption lines that are a sound label for laughter."""
    events = captions.get("events") if isinstance(captions, dict) else None
    times: list[float] = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or not isinstance(event.get("tStartMs"), int | float):
            continue
        segments = event.get("segs")
        text = "".join(
            part.get("utf8", "")
            for part in (segments if isinstance(segments, list) else [])
            if isinstance(part, dict) and isinstance(part.get("utf8"), str)
        )
        if _LAUGH_LABEL.search(text):
            times.append(event["tStartMs"] / 1000)
    return times


def flags(
    *,
    words: list[HeardWord],
    match: Match | None,
    trim: dict[str, Any] | None,
    brief_entry: dict[str, Any],
    source: dict[str, Any],
    capture: dict[str, Any],
    captions: Any,
) -> list[dict[str, str]]:
    """What the owner must acknowledge before accepting the clip (§4.6, check 5; SB-12). Never a
    refusal. Each is `{code, message}`."""
    found: list[dict[str, str]] = []

    def add(code: str, message: str) -> None:
        found.append({"code": code, "message": message})

    if not words:
        add("no_speech", "Nothing was heard in the clip.")

    if match is not None:
        heard_tokens = _heard_tokens(words)
        before = [t for t, position in heard_tokens if position < match.first]
        inside = [t for t, position in heard_tokens if match.first <= position <= match.last]
        after = [t for t, position in heard_tokens if position > match.last]

        turn = _has_phrase(after[:TURN_AFTER_WORDS], TURN_PHRASES)
        if turn is not None:
            add(
                "turn_after",
                f'"{turn}" is said soon after the quote: the speaker may turn the point. '
                "Listen to what follows.",
            )
        nearby = before[-CONTEXT_BEFORE_WORDS:] + inside
        reported = _has_phrase(nearby, REPORTED_PHRASES)
        if reported is not None:
            add(
                "reported_speech",
                f'"{reported}" is said near the quote: the speaker may be quoting someone else.',
            )
        hypothetical = _has_phrase(nearby, HYPOTHETICAL_PHRASES)
        if hypothetical is not None:
            add(
                "hypothetical",
                f'"{hypothetical}" is said near the quote: it may be a hypothetical, not a view.',
            )

        window_start = _number(_get(capture, "window", "start_s"))
        if window_start is not None:
            begin = window_start + words[match.first].start
            end = window_start + words[match.last].end
            for time in _laughter_times(captions):
                if begin - LAUGHTER_REACH_S <= time <= end + LAUGHTER_REACH_S:
                    add("laughter", "The captions mark laughter near the quote: it may be a joke.")
                    break

    published = source.get("published")
    upload = capture.get("upload_date")
    if not published:
        add("date_missing", "The recording date is not known. Confirm it before accepting.")
    elif isinstance(upload, str) and published > upload:
        add(
            "date_after_upload",
            f"The recording date ({published}) is later than the upload date ({upload}).",
        )

    channel = _normalised_name(capture.get("channel"))
    publisher = _normalised_name(source.get("publisher"))
    if not channel:
        add("channel_not_publisher", "The video's channel is not known.")
    elif publisher and channel not in publisher and publisher not in channel:
        add(
            "channel_not_publisher",
            f"The channel ({capture.get('channel')}) does not look like the publisher "
            f"({source.get('publisher')}). Check that this is the original upload.",
        )

    if trim is not None:
        flag = length_flag(trim)
        if flag is not None:
            found.append(flag)

    sensitive = _sensitive_words(brief_entry)
    if sensitive:
        add(
            "sensitive_context",
            f"The script around the quote has sensitive words ({', '.join(sensitive)}). "
            "Check that the clip cannot read as an admission or as the wrong side of the story.",
        )
        if trim is not None:
            flag = admission_flag(words, trim, brief_entry)
            if flag is not None:
                found.append(flag)
    return found


def _sensitive_words(brief_entry: dict[str, Any]) -> list[str]:
    context_tokens = tokens_of(
        f"{brief_entry.get('sentence', '')} {brief_entry.get('context', '')}"
    )
    return sorted(SENSITIVE_WORDS.intersection(context_tokens))


def length_flag(trim: dict[str, Any]) -> dict[str, str] | None:
    """The `length` flag for a trim (`{in_s, out_s, ...}`), or None when it is 3 to 15 s. Pure."""
    length = trim["out_s"] - trim["in_s"]
    if MIN_CLIP_S <= length <= MAX_CLIP_S:
        return None
    return {
        "code": "length",
        "message": (
            f"The clip is {length:.1f} s long; a sound bite is {MIN_CLIP_S:.0f} to "
            f"{MAX_CLIP_S:.0f} s."
        ),
    }


def admission_flag(
    words: list[HeardWord], trim: dict[str, Any], brief_entry: dict[str, Any]
) -> dict[str, str] | None:
    """The `admission_words` flag: an admission-like phrase is said inside the trim while the
    script around the quote has sensitive words. None otherwise. Pure."""
    if not _sensitive_words(brief_entry):
        return None
    inside_clip = [
        token
        for word in words
        if trim["in_s"] <= word.start and word.end <= trim["out_s"]
        for token in tokens_of(word.text)
    ]
    admission = _has_phrase(inside_clip, ADMISSION_PHRASES)
    if admission is None:
        return None
    return {
        "code": "admission_words",
        "message": (
            f'"{admission}" is said in the clip, which sits near sensitive words in '
            "the script. It may read as an admission."
        ),
    }


def trim_flags(
    words: list[HeardWord], trim: dict[str, Any], brief_entry: dict[str, Any]
) -> list[dict[str, str]]:
    """The flags that depend on the owner's trim: `length` and `admission_words`. Pure."""
    found = [length_flag(trim), admission_flag(words, trim, brief_entry)]
    return [flag for flag in found if flag is not None]


# The flag codes `trim_flags` can give. The review works these out again for the owner's trim
# and does not ask for the stored ones to be acknowledged (the length is checked on its own).
TRIM_FLAG_CODES: Final = ("length", "admission_words")


def _get(value: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


# --- everything -------------------------------------------------------------------------------


def heard_json(words: list[HeardWord], match: Match | None) -> dict[str, Any]:
    """The `heard_words` column: the heard words with their times and where the quote is."""
    return {
        "text": " ".join(word.text for word in words),
        "words": [
            {"text": word.text, "start": round(word.start, 3), "end": round(word.end, 3)}
            for word in words
        ],
        "match": (
            {
                "first": match.first,
                "last": match.last,
                "percent": round(100 * match.share, 1),
                "missing": match.missing,
                "extra": match.extra,
                "diff": match.diff,
            }
            if match is not None
            else None
        ),
    }


def analyse(
    *,
    quote: str,
    words: list[HeardWord],
    samples: NDArray[np.float32],
    rate: int,
    duration_s: float,
    near_s: float | None,
    brief_entry: dict[str, Any],
    source: dict[str, Any],
    capture: dict[str, Any],
    captions: Any,
) -> Analysis:
    """The fidelity class, the proposed trim and the flags of one clip. `quote` is the claim's
    words; `near_s` is where the captions put the quote, in seconds from the clip's start."""
    match = find_quote(quote, words, near_s)
    trim = (
        propose_trim(samples, rate, words, match.first, match.last, duration_s)
        if match is not None
        else None
    )
    return Analysis(
        fidelity=fidelity_of(match),
        heard_words=heard_json(words, match),
        proposed_trim=trim,
        flags=flags(
            words=words,
            match=match,
            trim=trim,
            brief_entry=brief_entry,
            source=source,
            capture=capture,
            captions=captions,
        ),
    )
