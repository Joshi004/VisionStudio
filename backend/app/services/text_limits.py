"""The length limits of what a language model writes, in one place. Pure functions, no I/O.

Every writer (`services/*_writer.py`) tells the model how long each field may be and then checks
the answer. A model counts characters badly, so two things are shared here:

- **What the model is told**: `length_rule` is a strict block added to the instructions. It
  states that the limits are hard, how to stay under them, and lists every limited field with
  its number, so the limit is never mentioned only in passing.
- **What happens to an answer that is still too long**: it is not worth a failed job (a second
  paid call) when the text is a description. `fit_text` keeps a text up to its limit with
  `LIMIT_SLACK` allowed on top, and cuts a longer one at the last whole word, with a warning
  the job saves. `keep_first` does the same for a list with too many items.

Text that must stay as the model wrote it (an id, spoken words, a quotation) is not cut: its
writer raises ValueError instead, and the job's corrected retry tells the model what was wrong.
"""

from __future__ import annotations

from typing import Final

# The model often misses a stated length by a few characters: up to this many times the limit
# is kept as it is.
LIMIT_SLACK: Final = 1.25

_LENGTH_RULE: Final = """LENGTH LIMITS (hard). Every text field has a maximum number of \
characters. Count the characters while you write. Aim for about two thirds of the maximum and \
never go over it: a value over its maximum is cut off, so a long one loses its ending. Write \
a short complete phrase that fits, with the most important thing first, and do not add \
clauses to explain or to list more. This holds for every character, place or thing, however \
much there is to say about it."""


def length_rule(limits: dict[str, int] | None = None) -> str:
    """The strict length block for the instructions. `limits` are the limited fields by the
    name the model sees in the answer (`placements[].posture`) and their maximum characters.
    """
    if not limits:
        return _LENGTH_RULE
    lines = "\n".join(f'  - "{name}": {limit}' for name, limit in limits.items())
    return f"{_LENGTH_RULE}\nMaximum characters of each field:\n{lines}"


def cut_at_word(text: str, max_chars: int) -> str:
    """`text` cut to at most `max_chars` characters at the last whole word, without a dangling
    comma or dash. A text with no space in it is cut at `max_chars`.
    """
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    if text[max_chars] != " " and " " in window:
        window = window[: window.rfind(" ")]
    return window.rstrip(" ,;:-")


def fit_text(text: str, path: str, max_chars: int, warnings: list[str] | None) -> str:
    """`text` (already on one line) as it is up to `max_chars` with `LIMIT_SLACK` allowed on
    top. Longer than that it is cut at the last whole word that fits `max_chars`, and a warning
    naming `path` is added to `warnings`. With `warnings` None (text a person wrote, which is
    not cut behind their back) it raises ValueError instead.
    """
    accepted = int(max_chars * LIMIT_SLACK)
    if len(text) <= accepted:
        return text
    if warnings is None:
        raise ValueError(f'The "{path}" was longer than {accepted} characters.')
    warnings.append(f'The "{path}" was {len(text)} characters; it was cut to fit {max_chars}.')
    return cut_at_word(text, max_chars)


def keep_first[T](items: list[T], max_items: int, path: str, warnings: list[str] | None) -> list[T]:
    """The first `max_items` of `items`. When there were more, a warning naming `path` is added
    to `warnings`, or with `warnings` None ValueError is raised.
    """
    if len(items) <= max_items:
        return items
    if warnings is None:
        raise ValueError(f'The "{path}" had more than {max_items} items.')
    warnings.append(f'The "{path}" had {len(items)} items; only the first {max_items} were kept.')
    return items[:max_items]
