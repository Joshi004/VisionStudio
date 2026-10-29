"""The numbers a text says, in digits or in English words (EXPLAINER-009).

A `number` callout may show "10 LAKH" while the script says "ten lakh" or "1,000,000". To check
that the callout's number is said in the script, both are turned into values and compared.

Pure functions, no I/O. Covered forms:

- digits: `1,000`, `3.5`, `73%`, `$5`, and a scale glued on (`5k`, `2m`, `5bn`, `3cr`) or spoken
  after them (`2.5 million`, `10 lakh`);
- English words: "twenty five", "twenty-five", "one hundred and five", "ten lakh", "three
  crore", "two thousand", "three point five".

Not covered, so they are never found: ordinals ("fifth"), fractions ("half"), ranges, and years
said in two parts ("twenty twenty four" is read as 44). The caller treats a missing number as a
warning, never a refusal.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Final

_ONES: Final[dict[str, int]] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS: Final[dict[str, int]] = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_HUNDRED: Final = "hundred"
# A word that closes a group ("ten lakh", "three thousand").
_SCALES: Final[dict[str, int]] = {
    "thousand": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "billion": 1_000_000_000,
    "billions": 1_000_000_000,
}
# A scale glued to digits: "5k", "2m", "5bn", "3cr".
_SUFFIXES: Final[dict[str, int]] = {
    "k": 1_000,
    "m": 1_000_000,
    "mn": 1_000_000,
    "b": 1_000_000_000,
    "bn": 1_000_000_000,
    "cr": 10_000_000,
}

# A digit token (with an optional glued scale), or a word.
_TOKEN: Final = re.compile(r"\d[\d,]*(?:\.\d+)?(?:(?:k|mn|m|bn|b|cr)(?![a-z]))?|[a-z]+")
_DIGITS: Final = re.compile(r"(\d[\d,]*(?:\.\d+)?)([a-z]*)")


def _digit_value(token: str) -> Decimal | None:
    match = _DIGITS.fullmatch(token)
    if match is None:
        return None
    try:
        value = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    suffix = match.group(2)
    return value * _SUFFIXES[suffix] if suffix else value


def _is_number_word(word: str) -> bool:
    return word in _ONES or word in _TENS or word == _HUNDRED or word in _SCALES


def numbers_in(text: str) -> set[Decimal]:
    """Every number `text` says, as values. "ten lakh" and "1,000,000" give the same value."""
    tokens = _TOKEN.findall(text.lower().replace("-", " "))
    found: set[Decimal] = set()
    total = 0  # the groups already closed by a scale word
    current = 0  # the group being built
    in_run = False  # a number word was read in the current run

    def flush() -> None:
        nonlocal total, current, in_run
        if in_run:
            found.add(Decimal(total + current))
        total = current = 0
        in_run = False

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token[0].isdigit():
            flush()
            value = _digit_value(token)
            if value is not None:
                following = tokens[index + 1] if index + 1 < len(tokens) else ""
                if following in _SCALES:
                    value *= _SCALES[following]
                    index += 1
                elif following == _HUNDRED:
                    value *= 100
                    index += 1
                found.add(value)
        elif token in _ONES or token in _TENS:
            value = _ONES[token] if token in _ONES else _TENS[token]
            # "twenty five" is one number, but "two three" and "twenty ten" are two.
            fits = current % 100 == 0 if value >= 10 else current % 10 == 0
            if in_run and not fits:
                flush()
            current += value
            in_run = True
        elif token == _HUNDRED:
            current = max(current, 1) * 100
            in_run = True
        elif token in _SCALES:
            if in_run:
                total += max(current, 1) * _SCALES[token]
                current = 0
            else:
                flush()
        elif (
            token == "and"
            and in_run
            and index + 1 < len(tokens)
            and _is_number_word(tokens[index + 1])
            and (tokens[index - 1] == _HUNDRED or tokens[index - 1] in _SCALES)
        ):
            pass  # "one hundred and five", but not "five and ten"
        elif token == "point" and in_run:
            digits = []
            lookahead = index + 1
            while lookahead < len(tokens) and tokens[lookahead] in _ONES:
                digits.append(str(_ONES[tokens[lookahead]]))
                lookahead += 1
            if digits and all(len(digit) == 1 for digit in digits):
                found.add(Decimal(total + current) + Decimal("0." + "".join(digits)))
                total = current = 0
                in_run = False
                index = lookahead - 1
            else:
                flush()
        else:
            flush()
        index += 1
    flush()
    return found
