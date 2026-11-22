"""The one mapping from a scene take's time to the scene's time (SB-002).

Section 4.7 of `Sound_bite_implementation_phases.md` has the design. Pure functions and values:
no I/O, no clock, no import from the rest of the app.

A continuous explainer speaks each scene as one take (`take_timings`). Everything that is placed
on the scene's timeline is placed by the take's word times, so every place that turns "seconds
from the start of the take" into "seconds from the start of the scene" (or back) asks this map
and nothing else.

The map is a fixed offset, the lead-in the take sits after (`lead_in_s`), and a list of
**replaced spans**. The list was always empty in SB-002; SB-008 fills it from the plan's sound bite
shots. A replaced span is a stretch `[take_start_s, take_end_s]` of the take that does not play in
the scene: a sound bite's clip plays in its place for `scene_seconds`. With spans `i` (each `s_i`,
`e_i`, `L_i`):

    scene_time(t) = lead_in + t + sum over spans with e_i <= t of (L_i - (e_i - s_i))

A take time strictly inside a replaced span has no scene time, and `TakeMapError` says so. The
callers that must not fail on such a time (the words of a quote, the edge of a unit) ask
`place_s`, which puts it at the same share of the clip's window.

**Rounding.** `to_scene` and `to_take` round to a thousandth of a second, as every copy of the
clock did before. The terms added for replaced spans are `0.0` while there are none, and adding
`0.0` leaves a float exactly as it was, so results are bit for bit what they were.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

_DECIMALS: Final = 3


class TakeMapError(ValueError):
    """A time that the map cannot give: inside a replaced span, or a list of spans that is not
    in order."""


@dataclass(frozen=True)
class ReplacedSpan:
    """A stretch of the take that does not play: a clip plays in its place."""

    # The cut before the quote's first word and the cut after its last, in take seconds.
    take_start_s: float
    take_end_s: float
    # How long the clip plays in the scene.
    scene_seconds: float

    @property
    def shift_s(self) -> float:
        """How much later everything after the span comes: the clip's length less the take's."""
        return self.scene_seconds - (self.take_end_s - self.take_start_s)


@dataclass(frozen=True)
class TakeMap:
    """Take time to scene time for one scene's take."""

    # The take starts this long after the start of the scene.
    lead_in_s: float
    # In order of the take and never overlapping: one for each sound bite shot (SB-008).
    replaced: tuple[ReplacedSpan, ...] = ()

    def __post_init__(self) -> None:
        previous_end = float("-inf")
        for span in self.replaced:
            if span.take_end_s < span.take_start_s or span.scene_seconds < 0:
                raise TakeMapError("A replaced span must have a start before its end.")
            if span.take_start_s < previous_end:
                raise TakeMapError("The replaced spans must be in order and must not overlap.")
            previous_end = span.take_end_s

    # --- Take to scene -------------------------------------------------------------------

    def bite_shift_at(self, take_s: float) -> float:
        """How much later than the plain take time the take's second `take_s` plays, because of
        the replaced spans that end at or before it (0.0 with none)."""
        shift = 0.0
        for span in self.replaced:
            if span.take_end_s <= take_s:
                shift += span.shift_s
        return shift

    def shift_at(self, take_s: float) -> float:
        """The whole offset of the take's second `take_s`: the lead-in and the spans before it."""
        return self.lead_in_s + self.bite_shift_at(take_s)

    def is_replaced(self, take_s: float) -> bool:
        """Whether nothing of the take plays at `take_s`: it is strictly inside a replaced span."""
        return any(span.take_start_s < take_s < span.take_end_s for span in self.replaced)

    def to_scene(self, take_s: float) -> float:
        """The scene time at which the take's second `take_s` plays. Raises TakeMapError for a
        time inside a replaced span."""
        if self.is_replaced(take_s):
            raise TakeMapError(f"Nothing of the take plays at {take_s:g} s: a clip replaces it.")
        return round(self.shift_at(take_s) + take_s, _DECIMALS)

    def place_s(self, take_s: float) -> float:
        """The scene time of the take's second `take_s`, and never an error. Outside the replaced
        spans it is `to_scene`. Inside a span nothing of the take plays, so the second is put at
        the same share of the clip's window as it has of the span: the words of a quote, and the
        edges of a speech unit that holds them, land inside the clip's window, where captions and
        callouts can be told from the rest."""
        span = self._span_around(take_s)
        if span is None:
            return self.to_scene(take_s)
        return round(self._inside(span, take_s) + self.lead_in_s, _DECIMALS)

    def is_word_replaced(self, start_s: float, end_s: float) -> bool:
        """Whether a word of the take, given by its start and end, is in a replaced span (its
        middle is strictly inside one). A word that touches the edge of a span is not."""
        return self.is_replaced((start_s + end_s) / 2)

    def _span_around(self, take_s: float) -> ReplacedSpan | None:
        for span in self.replaced:
            if span.take_start_s < take_s < span.take_end_s:
                return span
        return None

    def _inside(self, span: ReplacedSpan, take_s: float) -> float:
        """The offset from the start of the scene's take (the lead-in not counted) at which the
        second `take_s`, strictly inside `span`, is placed."""
        share = (take_s - span.take_start_s) / (span.take_end_s - span.take_start_s)
        return (
            span.take_start_s + self.bite_shift_at(span.take_start_s) + share * span.scene_seconds
        )

    def _plain_offset(self, take_s: float) -> float:
        """How far from the start of the take (lead-in not counted) the second plays."""
        span = self._span_around(take_s)
        if span is not None:
            return self._inside(span, take_s)
        return take_s + self.bite_shift_at(take_s)

    def elapsed_s(self, from_take_s: float, to_take_s: float) -> float:
        """The scene time that passes between two seconds of the take, not rounded. Used for the
        offset of a word from the start of its unit, so a clip between them counts. A second
        inside a replaced span is placed as `place_s` does."""
        if self._span_around(from_take_s) is None and self._span_around(to_take_s) is None:
            return (to_take_s - from_take_s) + (
                self.bite_shift_at(to_take_s) - self.bite_shift_at(from_take_s)
            )
        return self._plain_offset(to_take_s) - self._plain_offset(from_take_s)

    # --- Scene to take -------------------------------------------------------------------

    def to_take(self, scene_s: float) -> float:
        """The second of the take that plays at scene time `scene_s` (negative inside the
        lead-in). Raises TakeMapError for a time while a clip plays."""
        shift = 0.0
        for span in self.replaced:
            start = self.lead_in_s + span.take_start_s + shift
            end = start + span.scene_seconds
            if start < scene_s < end:
                raise TakeMapError(f"A clip plays at {scene_s:g} s: no part of the take does.")
            if scene_s >= end:
                shift += span.shift_s
        return round(scene_s - (self.lead_in_s + shift), _DECIMALS)

    # --- The same in samples (the voice of the render) ------------------------------------

    def _samples(self, seconds: float, rate: int) -> int:
        return round(seconds * rate)

    def bite_shift_samples_at(self, take_sample: int, rate: int) -> int:
        """`bite_shift_at` for a place in the take given in samples at `rate` (0 with none)."""
        shift = 0
        for span in self.replaced:
            if self._samples(span.take_end_s, rate) <= take_sample:
                shift += self._span_shift_samples(span, rate)
        return shift

    def _span_shift_samples(self, span: ReplacedSpan, rate: int) -> int:
        return self._samples(span.scene_seconds, rate) - (
            self._samples(span.take_end_s, rate) - self._samples(span.take_start_s, rate)
        )

    def replaced_take_samples(self, rate: int) -> list[tuple[int, int]]:
        """The replaced spans as `(start, end)` places in the take, in samples at `rate` (the same
        rounding as `bite_shift_samples_at` and `take_sample_at`). Empty with none."""
        return [
            (self._samples(span.take_start_s, rate), self._samples(span.take_end_s, rate))
            for span in self.replaced
        ]

    def take_sample_at(self, offset_sample: int, rate: int) -> int:
        """The place in the take, in samples, that plays `offset_sample` samples after the take's
        start on the timeline (the lead-in is not part of it). Raises TakeMapError while a clip
        plays."""
        shift = 0
        for span in self.replaced:
            start = self._samples(span.take_start_s, rate) + shift
            end = start + self._samples(span.scene_seconds, rate)
            if start < offset_sample < end:
                raise TakeMapError("A clip plays there: no part of the take does.")
            if offset_sample >= end:
                shift += self._span_shift_samples(span, rate)
        return offset_sample - shift


# A map with no lead-in and no replaced span, for the caller that has no timeline to take one from
# and only needs `elapsed_s` (which does not depend on the lead-in).
NO_REPLACED: Final = TakeMap(lead_in_s=0.0)


def unit_words(
    words: Sequence[dict[str, Any]],
    first_word: int,
    last_word: int,
    unit_take_start_s: float,
    take_map: TakeMap,
) -> tuple[tuple[str, float, float], ...]:
    """The words `first_word` to `last_word` of the take as `(text, start, end)`, each time in
    seconds from the start of the unit (`unit_take_start_s`, in take seconds) as the scene plays
    it. Captions and callouts add these to the unit's place on the timeline."""
    return tuple(
        (
            str(word["text"]),
            take_map.elapsed_s(unit_take_start_s, float(word["start"])),
            take_map.elapsed_s(unit_take_start_s, float(word["end"])),
        )
        for word in words[first_word : last_word + 1]
    )
