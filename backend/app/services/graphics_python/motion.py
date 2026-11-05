"""The motion of the templates, ported from `motion/src/templates/motion.ts` (§4.5.1, "The look
rules"): when a part enters, how it eases, and how a number counts up. Everything depends only on
the frame number, so two renders of the same input are identical.
"""

from __future__ import annotations

import math
import re
from typing import Final

# Frames an element takes to arrive, for each `motion` of the theme.
_DURATION: Final = {"snappy": 12, "smooth": 18, "calm": 24}


def js_round(value: float) -> int:
    """`Math.round` of JavaScript: halves go up. Python's `round` sends halves to the even number,
    so a layout that must match the Remotion one never uses it.
    """
    return math.floor(value + 0.5)


def duration_of(motion: str) -> int:
    return _DURATION.get(motion, 12)


def ease(t: float) -> float:
    """Ease-out cubic: `1 - (1 - t)^3`."""
    return 1 - (1 - t) ** 3


def progress_at(frame: int, beat_frame: int, motion: str) -> float:
    """How far an element that enters on `beat_frame` has come at `frame`, from 0 to 1, eased. It
    is 0 on the frame before its beat, above 0 on the beat's frame, and 1 `duration - 1` frames
    after it.
    """
    t = (frame - beat_frame + 1) / duration_of(motion)
    return ease(min(1.0, max(0.0, t)))


# sign, dollar sign, digits (with commas and decimals), K/M/B/T, suffix: the forms `display_text`
# of `graphics_resolve` writes.
_NUMBER: Final = re.compile(r"([+-]?)(\$?)(\d[\d,]*(?:\.\d+)?)([KMBT]?)(%| pts|x)?")
_COMMAS: Final = re.compile(r"\B(?=(\d{3})+(?!\d))")


def counted_text(display: str, progress: float, count: bool) -> str:
    """The text of a number that is counting up: only its digits count, from 0 up to the target
    with the target's decimals. The sign, the dollar sign, the letter and the suffix stay. At the
    end (and for a text that is not a number) it is `display` exactly.
    """
    if not count or progress >= 1:
        return display
    match = _NUMBER.fullmatch(display)
    if match is None:
        return display
    sign, dollar, digits, letter, suffix = (group or "" for group in match.groups())
    places = len(digits) - digits.index(".") - 1 if "." in digits else 0
    target = float(digits.replace(",", ""))
    scale = 10**places
    shown = f"{js_round(target * progress * scale) / scale:.{places}f}"
    whole, _, fraction = shown.partition(".")
    grouped = _COMMAS.sub(",", whole) if "," in digits else whole
    body = f"{grouped}.{fraction}" if fraction else grouped
    return f"{sign}{dollar}{body}{letter}{suffix}"
