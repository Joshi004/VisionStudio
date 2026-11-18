"""Source lines on graphic shots (EVD-012, `Evidence_layer_implementation_phases.md` §4.7).

A graphic shot is always kept whole, so a claim whose first word falls on a graphic shot and that
has no evidence shot of its own and no card cannot show its screenshot. It gets a short text line
instead ("Source: Reuters, 3 Oct 2026") while the claim is spoken. The line is drawn as subtitle
text in the top margin, outside the safe area, so it never covers the graphic (the render does
that, `caption_ass`).

Pure: no I/O. Times are seconds on the scene's timeline, like `evidence_cards`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.services.evidence_cards import (
    EVIDENCE,
    GAP_S,
    GRAPHIC,
    MIN_CARD_S,
    TAIL_S,
    ClaimTime,
    Slot,
    drawn_around,
)

# A source line is on screen for at least this long (the same floor as a card).
MIN_LINE_S: Final = MIN_CARD_S

_DECIMALS: Final = 3


@dataclass(frozen=True)
class SourceLine:
    """One line: the first piece of a claim's evidence, from `start_s` to `end_s`, on the graphic
    shot `shot_id`."""

    claim_id: str
    item_key: str
    shot_id: str
    start_s: float
    end_s: float


def _r(value: float) -> float:
    return round(value, _DECIMALS)


def place_lines(
    claims: list[ClaimTime], slots: list[Slot], carded: set[str]
) -> tuple[SourceLine, ...]:
    """The source lines of one scene. `carded` holds the claims that got a card. A claim gets a
    line when it has pieces to show, none of them is shown by an evidence shot, none got a card,
    and its first word is on a graphic shot. The line stays inside the graphic, ends `GAP_S` before
    it does when there is room, and is moved earlier (never before the graphic) to last
    `MIN_LINE_S`. A line that would overlap the one before it in the same graphic, or that cannot
    last `MIN_LINE_S`, is left out. Pure.
    """
    with_shots = {slot.claim_id for slot in slots if slot.type == EVIDENCE}
    lines: list[SourceLine] = []
    for claim in sorted(claims, key=lambda found: (found.first_s, found.claim_id)):
        if not claim.pieces or claim.claim_id in with_shots or claim.claim_id in carded:
            continue
        graphic = drawn_around(slots, max(0.0, claim.first_s))
        if graphic is None or graphic.type != GRAPHIC:
            continue
        floor = graphic.start_s
        for line in lines:
            if line.shot_id == graphic.shot_id:
                floor = max(floor, line.end_s)
        ceiling = graphic.end_s - GAP_S
        if ceiling - floor < MIN_LINE_S:
            ceiling = graphic.end_s  # a short graphic: the line may last until its end
        end = min(ceiling, max(claim.first_s + MIN_LINE_S, claim.last_s + TAIL_S))
        start = max(floor, min(claim.first_s, end - MIN_LINE_S))
        if end - start < MIN_LINE_S - 1e-9:
            continue
        lines.append(
            SourceLine(claim.claim_id, claim.pieces[0], graphic.shot_id, _r(start), _r(end))
        )
    return tuple(lines)
