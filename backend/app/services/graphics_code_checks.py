"""The static checks of a generated component, and its warnings (GFX-010,
`Graphics_lab_implementation_phases.md` §4.5.3).

Pure functions, no I/O.

The model writes one TSX file. Before anything renders, `check_code` refuses code that breaks a
rule that can be read from the text: too long, an import that is not allowed, not exactly one
default export, a call or an object that reaches outside the page (`fetch`, `eval`, `navigator`,
...) or an address. A refusal lists every reason, and the corrected retry of `jobs/llm_call.py`
tells the model what was wrong.

**These checks are not the security boundary.** They keep an honest component honest and give
the model a reason it can act on. A determined program can write `window["fe" + "tch"]`. The
boundary is the motion container (G-8): no internet, no volume, no secrets.

Two warnings (never a refusal) count against the "every number traced" metric (G-7):

- `code_warnings`: a number written in the code that is the value of a fact or a derived value.
  A whole number under 10 is not reported: it is too common as a size, a count or an opacity.
- `text_warnings`: a number in the text the browser shows at the checked frames that is neither in
  the line nor the on-screen text of a fact or a derived value.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from app.services.callout_plan_writer import format_number
from app.services.number_words import numbers_in

MAX_CODE_CHARS: Final = 40_000
# The modules the component may import (`motion/src/generated/modules.ts` is the second guard).
ALLOWED_IMPORTS: Final = ("react", "remotion", "@remotion/shapes", "@remotion/paths")
# At most this many warnings of each kind are kept.
MAX_WARNINGS: Final = 6
# A whole number below this is a layout constant, not a fact.
MIN_LITERAL: Final = Decimal(10)

# Each pattern with the name the model is told. Word boundaries keep `prefetch` out of `fetch`.
_BANNED: Final = (
    (r"\bfetch\b", "fetch"),
    (r"\bXMLHttpRequest\b", "XMLHttpRequest"),
    (r"\bWebSocket\b", "WebSocket"),
    (r"\bEventSource\b", "EventSource"),
    (r"\beval\b", "eval"),
    (r"\bFunction\s*\(", "Function("),
    (r"\bimport\s*\(", "import("),
    (r"\brequire\s*\(", "require("),
    (r"\blocalStorage\b", "localStorage"),
    (r"\bsessionStorage\b", "sessionStorage"),
    (r"\bindexedDB\b", "indexedDB"),
    (r"\bdocument\s*\.\s*cookie\b", "document.cookie"),
    (r"\bwindow\s*\.\s*open\b", "window.open"),
    (r"\bnavigator\b", "navigator"),
    (r"<\s*iframe\b", "<iframe"),
    (r"<\s*script\b", "<script"),
)
_BANNED_COMPILED: Final = tuple((re.compile(pattern), name) for pattern, name in _BANNED)

_IMPORT_FROM: Final = re.compile(r"""\bfrom\s*(['"])([^'"\n]*)\1""")
_IMPORT_BARE: Final = re.compile(r"""\bimport\s*(['"])([^'"\n]*)\1""")
_DEFAULT_EXPORTS: Final = re.compile(r"\bexport\s+default\b|\bas\s+default\b")
_HTTP_ADDRESS: Final = re.compile(r"\bhttps?\s*:", re.IGNORECASE)
_NUMBER_LITERAL: Final = re.compile(r"(?<![\w.$])\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])")


def strip_comments(code: str) -> str:
    """`code` without its `//` and `/* */` comments. Strings and template literals are kept as
    they are, so an address inside a string is still seen. A quote that is not closed on its line
    is not a string (a JavaScript string cannot span lines): it is an apostrophe in JSX text.
    """
    out: list[str] = []
    index, size = 0, len(code)
    while index < size:
        char = code[index]
        pair = code[index : index + 2]
        if pair == "//":
            while index < size and code[index] != "\n":
                index += 1
        elif pair == "/*":
            end = code.find("*/", index + 2)
            index = size if end == -1 else end + 2
            out.append(" ")
        elif char in "'\"`" and (end := _string_end(code, index)) is not None:
            out.append(code[index:end])
            index = end
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _string_end(code: str, start: int) -> int | None:
    """The index just after the string that starts at `start`, or None when a quoted string is not
    closed on its line.
    """
    quote = code[start]
    index = start + 1
    while index < len(code):
        char = code[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        if char == "\n" and quote != "`":
            return None
        index += 1
    return None if quote != "`" else len(code)


def check_code(code: str, *, max_chars: int = MAX_CODE_CHARS) -> str:
    """The component's code, or ValueError listing every rule it breaks (the reasons are fit for
    the user and for the model's corrected retry). `max_chars` is the longest code allowed (a
    callout's component is shorter than a graphic shot's).
    """
    if not code.strip():
        raise ValueError("The component code is empty.")
    reasons: list[str] = []
    if len(code) > max_chars:
        reasons.append(
            f"The code is {len(code):,} characters; the most allowed is {max_chars:,}. "
            "Write a shorter component."
        )
    text = strip_comments(code)

    imported = [match.group(2) for match in _IMPORT_FROM.finditer(text)]
    imported += [match.group(2) for match in _IMPORT_BARE.finditer(text)]
    for module in dict.fromkeys(imported):
        if module not in ALLOWED_IMPORTS:
            reasons.append(
                f'The code imports "{module}", which is not allowed. Import only from '
                f"{', '.join(ALLOWED_IMPORTS)}."
            )

    defaults = len(_DEFAULT_EXPORTS.findall(text))
    if defaults != 1:
        reasons.append(
            f"The code has {defaults} default exports; it needs exactly one, the component "
            "(`export default function Graphic(props) { ... }`)."
        )

    for pattern, name in _BANNED_COMPILED:
        if pattern.search(text):
            reasons.append(f"The code uses `{name}`, which is not allowed.")

    if _HTTP_ADDRESS.search(text):
        reasons.append("The code has an http: or https: address. No outside assets are allowed.")
    if "//" in text:
        reasons.append(
            "The code has a // address (or a // inside a string). No outside assets are allowed."
        )

    if reasons:
        raise ValueError(" ".join(reasons))
    return code


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace("_", ""))
    except InvalidOperation:
        return None


def _values_of(resolved: dict[str, Any], brief: dict[str, Any]) -> dict[Decimal, str]:
    """Every number a fact or a derived value is written as, with the id it belongs to: the full
    value, the value as the line says it (12 for 12 billion) and the numbers of its on-screen text.
    """
    written = {fact["id"]: fact["value"] for fact in brief.get("facts", [])}
    values: dict[Decimal, str] = {}
    for group in ("facts", "derived"):
        for key, item in resolved[group].items():
            candidates = {Decimal(str(item["value"])), *numbers_in(str(item["display"]))}
            if key in written:
                candidates.add(Decimal(str(written[key])))
            for number in candidates:
                values.setdefault(abs(number), key)
    return values


def code_warnings(code: str, resolved: dict[str, Any], brief: dict[str, Any]) -> list[str]:
    """A warning for each number in the code that is the value of a fact or a derived value: the
    component should use `facts[id].display` (or `.value`), never type the number. A whole number
    under 10 is skipped.
    """
    values = _values_of(resolved, brief)
    warnings: list[str] = []
    seen: set[Decimal] = set()
    for match in _NUMBER_LITERAL.finditer(strip_comments(code)):
        number = _decimal(match.group(0))
        if number is None or number in seen or number not in values:
            continue
        if number < MIN_LITERAL and number == number.to_integral_value():
            continue
        seen.add(number)
        key = values[number]
        label = (resolved["facts"].get(key) or resolved["derived"].get(key))["label"]
        warnings.append(
            f'The code has the number {format_number(number)}, the value of {key} ("{label}"). '
            f"Use facts.{key}.display or facts.{key}.value instead."
        )
    return warnings[:MAX_WARNINGS]


def text_warnings(texts: list[dict[str, Any]], line: str, resolved: dict[str, Any]) -> list[str]:
    """A warning for each number in the text on screen (as the browser reported it at the checked
    frames, `[{frame, text}]`) that the line does not say and no fact or derived value shows.
    """
    allowed = numbers_in(line)
    for group in ("facts", "derived"):
        for item in resolved[group].values():
            allowed |= numbers_in(str(item["display"]))
    fps = int(resolved["fps"])
    warnings: list[str] = []
    seen: set[Decimal] = set()
    for entry in texts:
        for number in sorted(numbers_in(str(entry["text"])) - allowed):
            if number in seen:
                continue
            seen.add(number)
            warnings.append(
                f"The text on screen at {int(entry['frame']) / fps:.1f} s shows the number "
                f"{format_number(number)}, which the line does not say and no fact shows."
            )
    return warnings[:MAX_WARNINGS]


def part_number_warnings(code: str, texts: list[str]) -> list[str]:
    """A warning for each number in the code that is also a number in the text of a callout's
    parts: the component should show the text it is given, never type the number. A whole number
    under 10 is skipped.
    """
    shown: set[Decimal] = set()
    for text in texts:
        shown |= {abs(number) for number in numbers_in(text)}
    warnings: list[str] = []
    seen: set[Decimal] = set()
    for match in _NUMBER_LITERAL.finditer(strip_comments(code)):
        number = _decimal(match.group(0))
        if number is None or number in seen or number not in shown:
            continue
        if number < MIN_LITERAL and number == number.to_integral_value():
            continue
        seen.add(number)
        warnings.append(
            f"The code has the number {format_number(number)}, which a callout text shows. "
            "Show the text of the part instead of typing the number."
        )
    return warnings[:MAX_WARNINGS]
