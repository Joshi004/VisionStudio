"""How alike two spellings of the same speech are (SCN-001).

The dialogue check compares the words a clip was meant to say with the words a recogniser
heard. A recogniser writes "6" for "six", "tires" for "tyres" and "you two" for "you too", and none
of those is a wrong clip. These are the word lists and the small rules that make the comparison
fair. They are data and pure functions, with no I/O and no prompt text.

`services/dialogue_check.py` applies them in this order, and records the first step at which a
take passed, so a report can say what kind of difference was forgiven:

1. numbers: "fifteen percent" and "15%" are the same words (`prepare`, `fold_numbers`);
2. spelling: UK and US spellings are the same word (`to_us_spelling`);
3. homophones: words that sound the same are the same word (`fold_homophones`);
4. short lines: one word that is close in letters, on a line of four words or fewer
   (`short_line_matches`).

A line with nothing but an interjection ("oh", "hmm") may also be left unverified when nothing
was heard (`is_unverifiable`).

English only (S-12).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Final

from app.services.number_words import is_number_word, numbers_in

# A line of at most this many words gets the short-line rule.
SHORT_LINE_MAX_WORDS: Final = 4
# Two different words pass on a short line when their letters are at least this alike (0 to 1).
SHORT_LINE_LETTER_RATIO: Final = 0.6

# Words that carry no meaning a recogniser can be expected to catch.
INTERJECTIONS: Final = frozenset(
    {
        "ah",
        "aha",
        "eh",
        "er",
        "ew",
        "hey",
        "hm",
        "hmm",
        "hmmm",
        "huh",
        "mm",
        "mmm",
        "oh",
        "oi",
        "oops",
        "ow",
        "ugh",
        "uh",
        "um",
        "umm",
        "whoa",
        "wow",
        "yay",
    }
)

# Pairs of words that a speaker runs together: either may be heard for the other.
WEAK_FORM_PAIRS: Final = frozenset(
    frozenset(pair)
    for pair in (
        ("the", "a"),
        ("the", "an"),
        ("a", "an"),
        ("him", "em"),
        ("them", "em"),
        ("and", "n"),
    )
)

# UK spelling to US spelling. A trailing "s" ("tyres", "colours") is read as the plural.
_UK_TO_US: Final[dict[str, str]] = {
    "ageing": "aging",
    "aluminium": "aluminum",
    "amongst": "among",
    "analyse": "analyze",
    "apologise": "apologize",
    "behaviour": "behavior",
    "cancelled": "canceled",
    "catalogue": "catalog",
    "centre": "center",
    "cheque": "check",
    "colour": "color",
    "defence": "defense",
    "dialogue": "dialog",
    "draught": "draft",
    "favour": "favor",
    "fibre": "fiber",
    "flavour": "flavor",
    "grey": "gray",
    "harbour": "harbor",
    "honour": "honor",
    "humour": "humor",
    "jewellery": "jewelry",
    "judgement": "judgment",
    "kerb": "curb",
    "labour": "labor",
    "licence": "license",
    "litre": "liter",
    "metre": "meter",
    "mould": "mold",
    "mum": "mom",
    "mummy": "mommy",
    "neighbour": "neighbor",
    "offence": "offense",
    "ok": "okay",
    "organise": "organize",
    "plough": "plow",
    "practise": "practice",
    "programme": "program",
    "pyjamas": "pajamas",
    "realise": "realize",
    "recognise": "recognize",
    "sceptical": "skeptical",
    "storey": "story",
    "theatre": "theater",
    "towards": "toward",
    "travelled": "traveled",
    "travelling": "traveling",
    "tyre": "tire",
    "whilst": "while",
}

# Words that sound the same. The first word of a group stands for the whole group. The digit
# forms are listed too: numbers are folded to digits before this step.
_HOMOPHONE_GROUPS: Final = (
    ("to", "too", "two", "2"),
    ("for", "four", "fore", "4"),
    ("won", "1"),
    ("ate", "8"),
    ("by", "buy", "bye"),
    ("there", "their", "theyre"),
    ("your", "youre"),
    ("no", "know"),
    ("right", "write"),
    ("hear", "here"),
    ("see", "sea"),
    ("be", "bee"),
    ("i", "eye"),
    ("hi", "high"),
    ("new", "knew"),
    ("night", "knight"),
    ("meet", "meat"),
    ("peace", "piece"),
    ("plain", "plane"),
    ("tail", "tale"),
    ("sun", "son"),
    ("whole", "hole"),
    ("would", "wood"),
    ("weather", "whether"),
    ("wait", "weight"),
    ("way", "weigh"),
    ("waist", "waste"),
    ("where", "wear"),
    ("threw", "through"),
    ("seen", "scene"),
    ("steal", "steel"),
    ("sail", "sale"),
    ("rain", "reign"),
    ("pair", "pear"),
    ("mail", "male"),
    ("hour", "our"),
    ("heal", "heel"),
    ("flour", "flower"),
    ("die", "dye"),
    ("cent", "sent", "scent"),
    ("break", "brake"),
    ("bare", "bear"),
    ("aloud", "allowed"),
)
_HOMOPHONES: Final[dict[str, str]] = {
    word: group[0] for group in _HOMOPHONE_GROUPS for word in group
}

_COMMA_IN_DIGITS: Final = re.compile(r"(?<=\d),(?=\d)")


def prepare(text: str) -> str:
    """The text before it is split into words: "%" is said "percent", and the commas of "1,000"
    go, because the word splitter would turn both into a space.
    """
    return _COMMA_IN_DIGITS.sub("", text).replace("%", " percent ")


def fold_numbers(words: Sequence[str]) -> list[str]:
    """Each run of number words that says one whole number becomes its digits: "twenty five"
    and "25" are the same word. A run that says several numbers ("two three") is left alone.
    """
    folded: list[str] = []
    index = 0
    while index < len(words):
        if not is_number_word(words[index]):
            folded.append(words[index])
            index += 1
            continue
        end = index
        # "one hundred and five": "and" stays inside a run when a number word follows it.
        while end < len(words) and (
            is_number_word(words[end])
            or (words[end] == "and" and end + 1 < len(words) and is_number_word(words[end + 1]))
        ):
            end += 1
        run = words[index:end]
        values = numbers_in(" ".join(run))
        if len(values) == 1 and _is_whole(next(iter(values))):
            folded.append(str(int(next(iter(values)))))
        else:
            folded.extend(run)
        index = end
    return folded


def _is_whole(value: Decimal) -> bool:
    return value == value.to_integral_value()


def to_us_spelling(word: str) -> str:
    """The US spelling of a word, or the word itself."""
    if word in _UK_TO_US:
        return _UK_TO_US[word]
    if word.endswith("s") and word[:-1] in _UK_TO_US:
        return _UK_TO_US[word[:-1]] + "s"
    return word


def fold_homophones(word: str) -> str:
    """The word that stands for the group of words that sound like `word`, or the word itself."""
    return _HOMOPHONES.get(word, word)


def short_line_matches(expected: Sequence[str], heard: Sequence[str]) -> bool:
    """The short-line rule: a line of 1 to `SHORT_LINE_MAX_WORDS` words passes when it differs
    from what was heard in one place only, and that place is one word for one word that is close
    in letters (or a weak form such as "the" and "a"), or the same letters split differently
    ("it" and "i t"). A word that is missing or added never passes, so "Don't" heard as
    "Don't you think that's the first one" still fails.
    """
    if not 1 <= len(expected) <= SHORT_LINE_MAX_WORDS or not heard:
        return False
    changes = [
        op
        for op in SequenceMatcher(None, expected, heard, autojunk=False).get_opcodes()
        if op[0] != "equal"
    ]
    if len(changes) != 1 or changes[0][0] != "replace":
        return False
    _tag, e_start, e_end, h_start, h_end = changes[0]
    meant, said = expected[e_start:e_end], heard[h_start:h_end]
    if "".join(meant) == "".join(said):
        return True
    if len(meant) != 1 or len(said) != 1:
        return False
    if frozenset((meant[0], said[0])) in WEAK_FORM_PAIRS:
        return True
    return SequenceMatcher(None, meant[0], said[0]).ratio() >= SHORT_LINE_LETTER_RATIO


def is_unverifiable(expected: Sequence[str]) -> bool:
    """Whether a line is too slight for a recogniser to be held to: one word, or only
    interjections. An empty transcript for such a line does not fail the take.
    """
    return len(expected) == 1 or (bool(expected) and all(w in INTERJECTIONS for w in expected))
