"""Matching a transcript to the script (ANALYSIS.md Section 5.1). Pure functions, no I/O.

The recogniser tells us when each word was *spoken*. The script is what was *meant*.
Everything downstream (scene cuts, prompts) uses the script's own words, so each script
word takes the time of the spoken word it lines up with:

1. Both lists are normalised (case, punctuation and apostrophes ignored).
2. They are aligned with `difflib.SequenceMatcher`. Only words that line up exactly count
   as matched.
3. A script word nobody heard gets a time interpolated between its matched neighbours.
4. A spoken word that is not in the script is ignored, but counted.

Numbers are a known limit: a script that says "13.8" and a recording that says "thirteen
point eight" do not match, because no word list is consulted. Such words are interpolated
and counted, and the mismatch warning tells you when there are many.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Final

from app.providers.transcriber import SpokenWord

# Tuned on the Phase 5 sample (a clean recording of its script): 4.4% of the script was not
# heard and the recording had 8.8% extra words, all of it "we're" spoken as "we are" and
# "travelling" heard as "traveling". Words that are not heard hurt the times of the script,
# so that threshold is tight. Extra spoken words are only ignored, so that one is looser.
NOT_HEARD_THRESHOLD: Final = 0.10
EXTRA_SPOKEN_THRESHOLD: Final = 0.20

_PARAGRAPH_BREAK: Final = re.compile(r"\n\s*\n")
_TIME_DECIMALS: Final = 3


@dataclass(frozen=True)
class ScriptToken:
    index: int  # 0-based, over every word of the script
    text: str  # as written, with its punctuation
    paragraph: int  # 0-based, over paragraphs that contain at least one word


@dataclass(frozen=True)
class MatchCounts:
    script_words: int
    matched: int
    interpolated: int  # script words nobody heard (script_words - matched)
    spoken_words: int  # words the recogniser heard, not counting empty ones
    extra_spoken: int  # spoken words that are not in the script (spoken_words - matched)


@dataclass(frozen=True)
class MatchResult:
    # [{index, word, start, end, matched, paragraph}], in script order
    script_words: list[dict[str, Any]]
    counts: MatchCounts


def normalise(word: str) -> str:
    """Lower case, with only letters and digits kept.

    "couldn’t" and "couldn't" both become "couldnt", and "13.8" becomes "138".
    """
    folded = unicodedata.normalize("NFKC", word).casefold()
    return "".join(char for char in folded if char.isalnum())


def script_sha256(script: str) -> str:
    """The hash stored with a transcript, to tell later that the script has changed."""
    return hashlib.sha256(script.encode("utf-8")).hexdigest()


def tokenise_script(script: str) -> list[ScriptToken]:
    """Splits the script into words, keeping the paragraphs (blank lines).

    Words are separated by whitespace. A piece with no letter or digit (a dash, "...")
    is not a word: it is joined to the word before it, or to the word after it at the
    very start of the script.
    """
    text = script.replace("\r\n", "\n").replace("\r", "\n")

    pieces: list[tuple[str, int]] = []  # (text, paragraph)
    leading = ""  # punctuation seen before the first word of the script
    paragraph = -1

    for block in _PARAGRAPH_BREAK.split(text):
        started = False
        for raw in block.split():
            if not normalise(raw):
                if pieces:
                    last_text, last_paragraph = pieces[-1]
                    pieces[-1] = (f"{last_text} {raw}", last_paragraph)
                else:
                    leading = f"{leading} {raw}".strip()
                continue
            if not started:
                paragraph += 1
                started = True
            word = f"{leading} {raw}" if leading else raw
            leading = ""
            pieces.append((word, paragraph))

    return [
        ScriptToken(index=index, text=word, paragraph=para)
        for index, (word, para) in enumerate(pieces)
    ]


def _interpolate(
    entries: list[dict[str, Any]], first: int, stop: int, low: float, high: float
) -> None:
    """Spreads entries[first:stop] evenly over [low, high]. Times never go backwards."""
    high = max(high, low)
    count = stop - first
    for position in range(count):
        start = low + (high - low) * position / count
        end = low + (high - low) * (position + 1) / count
        entry = entries[first + position]
        entry["start"] = round(start, _TIME_DECIMALS)
        entry["end"] = round(end, _TIME_DECIMALS)


def match_transcript(script: str, spoken: Sequence[SpokenWord], audio_end_s: float) -> MatchResult:
    """Gives every script word a start and an end time.

    `audio_end_s` is the length of the voiceover. It ends any run of script words that
    comes after the last matched word.
    """
    tokens = tokenise_script(script)
    script_norm = [normalise(token.text) for token in tokens]

    heard = [(word, normalise(word.word)) for word in spoken]
    heard = [(word, norm) for word, norm in heard if norm]
    spoken_norm = [norm for _word, norm in heard]

    entries: list[dict[str, Any]] = [
        {
            "index": token.index,
            "word": token.text,
            "start": 0.0,
            "end": 0.0,
            "matched": False,
            "paragraph": token.paragraph,
        }
        for token in tokens
    ]

    # autojunk=False: with 200 or more items, difflib treats very common words ("the",
    # "and") as junk by default, which breaks the alignment of long scripts.
    matcher = SequenceMatcher(None, script_norm, spoken_norm, autojunk=False)
    matched = 0
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            word = heard[block.b + offset][0]
            entry = entries[block.a + offset]
            entry["start"] = word.start
            entry["end"] = word.end
            entry["matched"] = True
            matched += 1

    run_start: int | None = None
    for position in range(len(entries) + 1):
        is_gap = position < len(entries) and not entries[position]["matched"]
        if is_gap:
            if run_start is None:
                run_start = position
            continue
        if run_start is not None:
            low = entries[run_start - 1]["end"] if run_start > 0 else 0.0
            high = entries[position]["start"] if position < len(entries) else audio_end_s
            _interpolate(entries, run_start, position, low, high)
            run_start = None

    counts = MatchCounts(
        script_words=len(tokens),
        matched=matched,
        interpolated=len(tokens) - matched,
        spoken_words=len(heard),
        extra_spoken=len(heard) - matched,
    )
    return MatchResult(script_words=entries, counts=counts)


def mismatch_warnings(counts: MatchCounts) -> list[str]:
    """Plain-language warnings when the recording differs a lot from the script."""
    if counts.script_words == 0:
        return []

    warnings: list[str] = []
    not_heard_share = counts.interpolated / counts.script_words
    if not_heard_share > NOT_HEARD_THRESHOLD:
        warnings.append(
            f"{counts.interpolated} of {counts.script_words} script words "
            f"({not_heard_share:.0%}) were not heard in the recording."
        )
    extra_share = counts.extra_spoken / counts.script_words
    if extra_share > EXTRA_SPOKEN_THRESHOLD:
        warnings.append(
            f"The recording has {counts.extra_spoken} spoken words that are not in the script "
            f"({extra_share:.0%} of the script's length)."
        )
    return warnings
