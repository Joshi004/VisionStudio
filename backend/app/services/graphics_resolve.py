"""The resolved brief of the Graphics lab: everything code works out from the director's brief
(GFX-003, `Graphics_lab_implementation_phases.md` §4.4).

Pure functions, no I/O.

**Timing.** Without a voice, each word of the line gets an estimated time (`estimated_timing`):
the speech lasts `words x 60 / words per minute`, shared out by character count. The timing is
`{source, words_per_minute, duration_s, words: [{text, start, end}]}` with one entry for each
word of `graphics_brief_writer.line_words`. With a voice (GFX-004) the same shape holds the
Parakeet times, so `resolve` works for both.

**Length.** The graphic starts with the speech and lasts until the end of the last word plus
0.5 s, at least 3 s (72 frames) and at most 15 s (360 frames). A line whose speech would be
longer than 15 s is refused before any call (`ensure_fits`).

**Beat frames.** A beat's frame is the frame of the first word of its phrase,
`round(start_s x fps)`, at most the last frame. `resolve` finds the phrases again in the timing's
words, so it can be run again when a voice's timing arrives, with no new model call.

**Number text** (G-7, `display_text`), US style: `$` before dollars, `%`, `x` and ` pts` after
percents, multiples and points; `K`, `M`, `B` and `T` for dollars and counts from 1,000 up; a
minus sign for a negative number. Rupees are Indian style: `₹` before them, and ` lakh` and
` crore` from 1,00,000 up (`₹5 lakh`, `₹1000 crore`). A fact shows at most two decimals, a
derived value none at 10 or more and one below 10. Trailing zeros are dropped. A change
(`pct_change`, `difference`) always shows its sign: `+158%`, `-6.5%`. A plain number (a year)
stays plain digits.

**Colours.** The palettes below are all readable on their background (contrast at least 4.5).
The director's accent must reach a contrast of 3.0 with the background (the WCAG minimum for
large text and graphics), otherwise the palette's default accent is used and `notes` says so.

**Zones.** The safe area is 5 percent from each edge. The caption area is the band the
explainer's one-line captions take (`caption_plan.style_for`), so a graphic leaves room for them.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from app.services import caption_plan
from app.services.callout_plan_writer import contrast_ratio
from app.services.graphics_brief_writer import (
    SCALE_FACTORS,
    SCALED_UNITS,
    line_tokens,
    line_words,
    phrase_starts,
)

SOURCE_ESTIMATED: Final = "estimated"

MAX_SPEECH_S: Final = 15.0
MIN_FRAMES: Final = 72
MAX_FRAMES: Final = 360
TAIL_S: Final = 0.5

SAFE_MARGIN: Final = 0.05
ACCENT_MIN_CONTRAST: Final = 3.0

COLOURS: Final[dict[str, dict[str, str]]] = {
    "dark": {
        "background": "#0B0F17",
        "surface": "#161C28",
        "text": "#FFFFFF",
        "muted": "#9AA4B2",
        "positive": "#2ED573",
        "negative": "#FF4D4D",
        "number": "#FFB000",
        "accent": "#4DA3FF",
    },
    "light": {
        "background": "#F7F8FA",
        "surface": "#E6E9EF",
        "text": "#0B0F17",
        "muted": "#5B6472",
        "positive": "#15803D",
        "negative": "#C62828",
        "number": "#B45309",
        "accent": "#1D4ED8",
    },
}

_PREFIX: Final = {"usd": "$", "inr": "₹"}
_SUFFIX: Final = {"percent": "%", "multiple": "x", "points": " pts"}
# The letters of a number from 1,000 up, smallest first.
_LADDER: Final = (
    (Decimal(1), ""),
    (Decimal(10) ** 3, "K"),
    (Decimal(10) ** 6, "M"),
    (Decimal(10) ** 9, "B"),
    (Decimal(10) ** 12, "T"),
)
# The words of a rupee amount from 1,00,000 up, smallest first.
_INR_LADDER: Final = (
    (Decimal(1), ""),
    (Decimal(10) ** 5, " lakh"),
    (Decimal(10) ** 7, " crore"),
)
_FACT_PLACES: Final = 2
_COMMAS_FROM: Final = Decimal(10_000)
_VALUE_PLACES: Final = Decimal("0.01")
_SIGNED_OPS: Final = ("pct_change", "difference")


# --- Timing -----------------------------------------------------------------------------------


def speech_seconds(words: Sequence[str], words_per_minute: int) -> float:
    """About how long the words take to say at the given pace."""
    return len(words) * 60 / words_per_minute


def estimated_timing(line: str, words_per_minute: int) -> dict[str, Any]:
    """The estimated time of every word of the line, from the start of the speech."""
    words = line_words(line)
    duration = speech_seconds(words, words_per_minute)
    total = sum(len(word) for word in words)
    entries: list[dict[str, Any]] = []
    used = 0
    for word in words:
        start = duration * used / total
        used += len(word)
        entries.append(
            {"text": word, "start": round(start, 3), "end": round(duration * used / total, 3)}
        )
    return {
        "source": SOURCE_ESTIMATED,
        "words_per_minute": words_per_minute,
        "duration_s": round(duration, 3),
        "words": entries,
    }


def ensure_fits(timing: dict[str, Any]) -> None:
    """Raises ValueError when the speech is longer than one graphic can be. The message is meant
    for the user.
    """
    duration = float(timing["duration_s"])
    if duration > MAX_SPEECH_S:
        raise ValueError(
            f"The line is too long for one graphic: its speech takes about {duration:.0f} s, "
            f"and the most is {MAX_SPEECH_S:.0f} s. Shorten the line."
        )


def frames_of(timing: dict[str, Any], fps: int) -> int:
    """The number of frames of the graphic: the end of the last word plus the tail, kept between
    3 s and 15 s.
    """
    last_end = max((float(word["end"]) for word in timing["words"]), default=0.0)
    return max(MIN_FRAMES, min(MAX_FRAMES, round((last_end + TAIL_S) * fps)))


# --- Numbers ----------------------------------------------------------------------------------


def derived_value(op: str, values: Sequence[Decimal]) -> Decimal:
    """What a derived value comes to. `values` are the full values of its facts, in order.
    Raises ValueError for a division by zero.
    """
    if op == "sum":
        return sum(values, Decimal(0))
    first, second = values
    if op == "difference":
        return second - first
    if op == "pct_change":
        if first == 0:
            raise ValueError("A change from zero cannot be worked out.")
        return (second - first) / abs(first) * 100
    if op == "ratio":
        if second == 0:
            raise ValueError("A division by zero cannot be worked out.")
        return first / second
    raise ValueError(f"Unknown operation {op!r}.")


def derived_unit(op: str, unit: str) -> str:
    """The unit of a derived value, from the unit of its facts."""
    if op == "pct_change":
        return "percent"
    if op == "ratio":
        return "multiple"
    if op == "difference" and unit == "percent":
        return "points"
    return unit


def _rounded(mantissa: Decimal, derived: bool) -> Decimal:
    places = (0 if abs(mantissa) >= 10 else 1) if derived else _FACT_PLACES
    return mantissa.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def display_text(value: Decimal, unit: str, *, signed: bool, derived: bool) -> str:
    """The on-screen text of a number. `value` is the full value (the scale applied)."""
    if unit == "inr":
        ladder = _INR_LADDER
    elif unit in SCALED_UNITS:
        ladder = _LADDER
    else:
        ladder = _LADDER[:1]
    position = max((i for i, (size, _) in enumerate(ladder) if abs(value) >= size), default=0)
    while True:
        size, letter = ladder[position]
        rounded = _rounded(value / size, derived)
        # 999,999 rounds to 1000K: that is 1M. 99.999 lakh rounds to 100 lakh: that is 1 crore.
        if position + 1 < len(ladder) and abs(rounded) * size >= ladder[position + 1][0]:
            position += 1
            continue
        break
    digits = f"{abs(rounded):,f}" if abs(rounded) >= _COMMAS_FROM else f"{abs(rounded):f}"
    if "." in digits:
        digits = digits.rstrip("0").rstrip(".")
    if rounded < 0:
        sign = "-"
    elif rounded > 0 and signed:
        sign = "+"
    else:
        sign = ""
    return f"{sign}{_PREFIX.get(unit, '')}{digits}{letter}{_SUFFIX.get(unit, '')}"


def _json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


# --- Colours and zones ------------------------------------------------------------------------


def theme_for(theme: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """The colours and styles of the resolved theme, and the notes about what was replaced."""
    colours = COLOURS[theme["palette"]]
    accent = theme.get("accent")
    notes: list[str] = []
    chosen = colours["accent"]
    if not isinstance(accent, str) or len(accent) != 7 or accent[0] != "#":
        notes.append(
            f"The accent colour {accent!r} was not a #RRGGBB colour. The default {chosen} was used."
        )
    else:
        try:
            ratio = contrast_ratio(accent, colours["background"])
        except ValueError:
            notes.append(
                f"The accent colour {accent!r} was not a #RRGGBB colour. "
                f"The default {chosen} was used."
            )
        else:
            if ratio < ACCENT_MIN_CONTRAST:
                notes.append(
                    f"The accent colour {accent} is not readable on the {theme['palette']} "
                    f"background (contrast {ratio:.1f}, at least {ACCENT_MIN_CONTRAST:g} is "
                    f"needed). The default {chosen} was used."
                )
            else:
                chosen = accent.upper()
    return (
        {
            "background": colours["background"],
            "surface": colours["surface"],
            "text": colours["text"],
            "muted": colours["muted"],
            "accent": chosen,
            "positive": colours["positive"],
            "negative": colours["negative"],
            "number": colours["number"],
            "background_style": theme["background"],
            "motion": theme["motion"],
        },
        notes,
    )


def safe_area(width: int, height: int) -> dict[str, int]:
    """The box everything stays inside: 5 percent from each edge."""
    left, top = round(width * SAFE_MARGIN), round(height * SAFE_MARGIN)
    return {"left": left, "top": top, "right": width - left, "bottom": height - top}


def caption_zone(width: int, height: int) -> dict[str, int]:
    """The band the explainer's captions take, from `caption_plan.style_for`: one line, at the
    bottom centre, `margin_v` up from the bottom.
    """
    style = caption_plan.style_for(width, height)
    half = round(style.font_size / 2)
    return {
        "top": height - style.margin_v - style.font_size - half,
        "bottom": min(height, height - style.margin_v + half),
    }


# --- The resolved brief -----------------------------------------------------------------------


def resolve(
    brief: dict[str, Any],
    timing: dict[str, Any],
    width: int,
    height: int,
    fps: int,
    fonts: dict[str, str],
    *,
    frames: int | None = None,
    theme: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The resolved brief (§4.4) of a checked brief and a timing. Raises ValueError when a beat's
    phrase is not found in the timing's words (it was checked against the line, so only a timing
    of other words can cause that).

    A graphic shot of an explainer (EXG-005) gives the two keywords: `frames`, the exact length
    of the shot's clip (the lab works it out from the timing), and `theme`, the video's theme
    (the shot's brief has none). Without them this is the lab's resolve.
    """
    frames = frames if frames is not None else frames_of(timing, fps)
    words = timing["words"]
    tokens = line_tokens([str(word["text"]) for word in words])
    starts = phrase_starts(tokens, [(beat["id"], beat["phrase"]) for beat in brief["beats"]])

    full: dict[str, Decimal] = {}
    units: dict[str, str] = {}
    facts: dict[str, Any] = {}
    for fact in brief["facts"]:
        value = Decimal(str(fact["value"])) * SCALE_FACTORS[fact["scale"]]
        full[fact["id"]] = value
        units[fact["id"]] = fact["unit"]
        facts[fact["id"]] = {
            "label": fact["label"],
            "value": _json_number(value),
            "unit": fact["unit"],
            "display": display_text(value, fact["unit"], signed=False, derived=False),
        }

    derived: dict[str, Any] = {}
    for item in brief["derived"]:
        op = item["op"]
        value = derived_value(op, [full[fact_id] for fact_id in item["of"]])
        unit = derived_unit(op, units[item["of"][0]])
        derived[item["id"]] = {
            "label": item["label"],
            "value": float(value.quantize(_VALUE_PLACES, rounding=ROUND_HALF_UP)),
            "unit": unit,
            "display": display_text(value, unit, signed=op in _SIGNED_OPS, derived=True),
        }

    beats = {
        beat["id"]: {
            "frame": min(round(float(words[start]["start"]) * fps), frames - 1),
            "shows": beat["shows"],
        }
        for beat, start in zip(brief["beats"], starts, strict=True)
    }
    colours, notes = theme_for(theme if theme is not None else brief["theme"])
    return {
        "width": width,
        "height": height,
        "fps": fps,
        "frames": frames,
        "timing_source": timing["source"],
        "facts": facts,
        "derived": derived,
        "beats": beats,
        "theme": colours,
        "fonts": dict(fonts),
        "safe_area": safe_area(width, height),
        "caption_zone": caption_zone(width, height),
        "notes": notes,
    }
