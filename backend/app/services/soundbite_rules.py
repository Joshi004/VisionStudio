"""The script rules of a sound bite (SB-005, `Sound_bite_implementation_phases.md` §4.2).

A sound bite replaces the narrator's reading of a quote with a clip of the person saying it, so
the script around the quote has to work both when the clip plays and when the narrator reads the
quote as the fallback. Everything here is pure: no database, no network, nothing stored. The
results are worked out every time the claims are read, as `words_changed` is.

- **The block** (`quote_problem`): the claim's words must be one or more whole sentences inside
  one pair of double quotation marks. The cut needs this, so a claim that breaks it cannot be
  made a sound bite, and a sound bite that comes to break it holds back the research brief.
- **The warnings** (`check`): the lead-in reads complete without the quote, the speaker is named
  before the quote, the lead-in does not repeat the quote's words, and no filler hand-off. They
  never block anything and cannot be dismissed.
- **The hints**: advice the owner judges alone (numbers and facts belong to the narrator).

The lead-in is the words of the quote's own sentence before the opening quotation mark; when the
quote starts its sentence, it is the sentence before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

from app.services.number_words import numbers_in
from app.services.speech_chunks import sentences

# The quotation marks that count: straight and curly double quotes. Single quotes do not.
OPENING_MARKS: Final = '"\u201c'
CLOSING_MARKS: Final = '"\u201d'
_ANY_MARK: Final = '"\u201c\u201d'
# What ends a sentence inside or right after the quotation marks.
SENTENCE_END_MARKS: Final = ".!?\u2026"

# How many content words a lead-in may share with the quote before the owner is warned.
PARROT_WORDS: Final = 3
# The shortest word that counts as a content word or as a part of a name.
MIN_WORD_LETTERS: Final = 3

CODE_LEAD_IN: Final = "lead_in_incomplete"
CODE_ATTRIBUTION: Final = "no_attribution"
CODE_PARROT: Final = "parroting"
CODE_FILLER: Final = "filler_hand_off"

HINT_NUMBERS: Final = (
    "Numbers and facts belong to the narrator. A sound bite works best for emotion, opinion or "
    "proof."
)

# Words that carry no meaning of their own, so sharing them is not parroting.
_STOP_WORDS: Final = frozenset(
    """
    the and but for nor yet not are was were been being has have had having can could would
    should may might must will shall did does done doing this that these those with from into
    onto upon over under than then them they their there here what when where which while who
    whom whose why how all any each few more most other some such only own same too very just
    also you your yours our ours his her hers its him she he we us me my mine out off about
    above after again against before below between both down during further once through until
    up once now said says say told tell tells
    """.split()
)

_TOKEN: Final = re.compile(r"[a-z]+(?:'[a-z]+)?")
_SUFFIXES: Final = ("ing", "ed", "es", "s")

# Phrases that hand over to a clip without saying anything. Matched in the lowercased lead-in
# with straight apostrophes.
_FILLER_PATTERNS: Final = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:had|has|have) this to say\b",
        r"\b(?:said|says|say) the following\b",
        r"\b(?:tells?|told) us more\b",
        r"\bhere(?: is|'s) what\b",
        r"\btake a listen\b",
        r"\blisten to this\b",
        r"\blet's hear\b",
    )
)


@dataclass(frozen=True)
class SoundbiteCheck:
    """What the rules say about one claim. `block` is a sentence for the owner, or None.
    `warnings` are `{code, message, words}`: `words` are the offending words, which may be none.
    """

    block: str | None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)


# --- The blocking rule ---------------------------------------------------------------------


def quote_problem(text: str) -> str | None:
    """Why the claim's words cannot be a sound bite, as a sentence for the owner, or None.

    They must start with an opening quotation mark, end with the closing one (a full stop,
    question mark or exclamation mark may follow it), hold no other double quotation mark, start
    with a capital letter or a digit, and end in a sentence end before the closing mark or right
    after it.
    """
    stripped = text.strip()
    if not stripped or stripped[0] not in OPENING_MARKS:
        return (
            "A sound bite must be whole sentences inside quotation marks, and these words do not "
            "start with an opening quotation mark."
        )
    core, after = stripped, ""
    if len(stripped) >= 2 and stripped[-1] in SENTENCE_END_MARKS and stripped[-2] in CLOSING_MARKS:
        core, after = stripped[:-1], stripped[-1]
    if len(core) < 3 or core[-1] not in CLOSING_MARKS:
        return (
            "A sound bite must be whole sentences inside quotation marks, and these words do not "
            "end with the closing quotation mark."
        )
    inner = core[1:-1].strip()
    if any(mark in _ANY_MARK for mark in inner):
        return (
            "A sound bite must be one quote. These words hold another quotation mark, so the "
            "quote is cut by words that are not the speaker's. Mark one quoted sentence."
        )
    first = next((char for char in inner if char.isalnum()), "")
    if not first or not (first.isdigit() or first.isupper()):
        return (
            "The quote does not start at the beginning of a sentence. Rewrite it as a whole "
            "sentence after the lead-in."
        )
    if not (inner.endswith(tuple(SENTENCE_END_MARKS)) or after):
        return (
            "The quote does not end at the end of a sentence (it ends in a comma or an open "
            "word). Rewrite it so the quoted words end with a full stop, a question mark or an "
            "exclamation mark."
        )
    return None


# --- The warnings --------------------------------------------------------------------------


def _straight(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'")


def _name_words(name: str) -> set[str]:
    """The words of a name that can be told apart: three letters or more, without a final 's."""
    words: set[str] = set()
    for token in _TOKEN.findall(_straight(name).lower()):
        word = token[:-2] if token.endswith("'s") else token
        word = word.replace("'", "")
        if len(word) >= MIN_WORD_LETTERS:
            words.add(word)
    return words


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_WORD_LETTERS:
            return word[: -len(suffix)]
    return word


def _content_words(text: str) -> dict[str, str]:
    """The content words of `text` as `{stem: the word as written}`, first occurrence kept."""
    found: dict[str, str] = {}
    for token in _TOKEN.findall(_straight(text).lower()):
        word = token[:-2] if token.endswith("'s") else token
        word = word.replace("'", "")
        if len(word) < MIN_WORD_LETTERS or word in _STOP_WORDS:
            continue
        found.setdefault(_stem(word), word)
    return found


def _lead_in(script: str, start: int) -> tuple[str, str]:
    """`(lead_in, earlier)` for a quote that starts at `start`: the words of its own sentence
    before it (else the sentence before), and the sentence before those.
    """
    pieces = sentences(script)
    position = 0
    index = len(pieces) - 1
    own = ""
    for number, piece in enumerate(pieces):
        if position + len(piece) > start:
            index = number
            own = script[position:start]
            break
        position += len(piece)
    before = [piece.strip() for piece in pieces[:index]]
    if own.strip():
        return own.strip(), before[-1] if before else ""
    if before:
        return before[-1], before[-2] if len(before) >= 2 else ""
    return "", ""


def _last_words(text: str, count: int = 3) -> list[str]:
    return text.split()[-count:]


def _lead_in_warning(lead_in: str) -> dict[str, Any] | None:
    if not lead_in:
        return None
    ending = lead_in.rstrip()
    if ending[-1] in ":" + SENTENCE_END_MARKS:
        return None
    last = ending.split()[-1].lower().strip(",;")
    if last == "that":
        message = (
            'The lead-in ends in "that", so it does not read complete when the clip replaces '
            "the quote. End it with a colon or a full stop."
        )
    elif ending[-1] in ",;":
        message = (
            "The lead-in ends in a comma, so it does not read complete when the clip replaces "
            "the quote. End it with a colon or a full stop."
        )
    else:
        message = (
            "The lead-in does not end in a colon or a full stop, so it does not read complete "
            "when the clip replaces the quote."
        )
    return {"code": CODE_LEAD_IN, "message": message, "words": _last_words(ending)}


def _attribution_warning(speaker: str | None, lead_in: str, earlier: str) -> dict[str, Any] | None:
    if speaker is None:
        return None
    names = _name_words(speaker)
    if not names:
        return None
    if names & _name_words(f"{earlier} {lead_in}"):
        return None
    return {
        "code": CODE_ATTRIBUTION,
        "message": (
            f"Name {speaker} before the quote (in the lead-in or the sentence before it), so the "
            "viewer knows who is speaking before the clip plays."
        ),
        "words": [],
    }


def _parrot_warning(lead_in: str, quote: str) -> dict[str, Any] | None:
    lead_words = _content_words(lead_in)
    quote_words = _content_words(quote)
    shared = [word for stem, word in lead_words.items() if stem in quote_words]
    if len(shared) < PARROT_WORDS:
        return None
    return {
        "code": CODE_PARROT,
        "message": (
            f"The lead-in already says {len(shared)} of the quote's words. Let the clip say "
            "them first and keep the lead-in to who, where and when."
        ),
        "words": shared,
    }


def _filler_warning(lead_in: str) -> dict[str, Any] | None:
    lowered = _straight(lead_in).lower()
    for pattern in _FILLER_PATTERNS:
        found = pattern.search(lowered)
        if found:
            return {
                "code": CODE_FILLER,
                "message": (
                    "The lead-in hands over to the clip without saying anything. Say who, where "
                    "and when instead."
                ),
                "words": [lead_in[found.start() : found.end()]],
            }
    return None


def check(script: str, claim: dict[str, Any]) -> SoundbiteCheck:
    """The block, warnings and hints for `claim` (`start`, `text`, `speaker`) in `script`. Pure.
    The warnings are worked out even when the claim is blocked, so the owner sees them all.
    """
    text = claim["text"]
    lead_in, earlier = _lead_in(script, claim["start"])
    candidates = (
        _lead_in_warning(lead_in),
        _attribution_warning(claim.get("speaker"), lead_in, earlier),
        _parrot_warning(lead_in, text),
        _filler_warning(lead_in),
    )
    hints = [HINT_NUMBERS] if numbers_in(text) else []
    return SoundbiteCheck(
        block=quote_problem(text),
        warnings=[warning for warning in candidates if warning is not None],
        hints=hints,
    )
