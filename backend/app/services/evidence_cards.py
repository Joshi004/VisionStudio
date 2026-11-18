"""Where evidence cards go (EVD-011, `Evidence_layer_implementation_phases.md` §4.7).

An evidence card is a small picture of a piece of evidence laid over a presenter or B-roll shot,
while the words it proves are spoken. The cut planner plans a full-screen evidence shot for every
claim it can; a claim or a piece of evidence it gave no shot (a claim it left out, or the pieces
after the ones it planned) is shown as a card instead. Code decides, on read, from the plan and the
words of the take: the planner's prompt is not touched.

Pure: no I/O, no clock. Times are seconds on the scene's timeline (`scene_timeline`), the same
numbers as `ShotSpan.start_s` and `end_s`.

**Rules** (`place_cards`):

- A card starts on the claim's first word, or, for a claim that has evidence shots, where its last
  shot ends. Pieces follow one another in the owner's order.
- A card is at least `MIN_CARD_S` long, and at most `MAX_CARD_S`, and runs `TAIL_S` past the claim's
  last word when there is room. With less than `MIN_CARD_S` of room after the first word, it
  starts up to `MAX_LEAD_S` before it.
- A card is only over shots that are not drawn: never over a graphic or an evidence shot. It ends
  `GAP_S` before the next one, and at the end of the scene. It may cross a cut between two other
  shots.
- A claim whose first word is on a graphic shot and that has no evidence shot of its own gets a
  source line (`evidence_source_lines`), not a card.
- A piece that has no room gets no card, and the board says why (`Unplaced`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# A card is on screen for at least this long, like an evidence shot (`SHORTEST_EVIDENCE_S`).
MIN_CARD_S: Final = 3.0
# A card is never longer than this, however long the claim is.
MAX_CARD_S: Final = 8.0
# A card runs this long past the last word of its claim, when there is room.
TAIL_S: Final = 0.5
# A card ends this long before a graphic or an evidence shot starts (`CUT_BEFORE_NEXT_MS`).
GAP_S: Final = 0.15
# A claim whose card could only start later than this after its last word gets none.
MAX_LATE_S: Final = 1.0
# A card may start up to this long before the claim's first word, when it has no room after it.
MAX_LEAD_S: Final = 1.0

GRAPHIC: Final = "graphic"
EVIDENCE: Final = "evidence"

NO_ROOM: Final = "no_room"
TOO_LATE: Final = "too_late"
UNPLACED_TEXT: Final = {
    NO_ROOM: (
        "There is less than 3 seconds of room for a card before the next graphic or evidence "
        "shot, or before the end of the scene."
    ),
    TOO_LATE: "The words are over before there is room to start a card.",
}

_DECIMALS: Final = 3


@dataclass(frozen=True)
class ClaimTime:
    """A claim with evidence to show, placed on its scene's timeline: `first_s` is where its first
    word starts and `last_s` where its last word ends. `pieces` are the item keys in the owner's
    order.
    """

    claim_id: str
    text: str
    pieces: tuple[str, ...]
    first_s: float
    last_s: float


@dataclass(frozen=True)
class Slot:
    """A shot of the scene's timeline as the placement needs it. `claim_id` and `item_key` are set
    only for an evidence shot."""

    shot_id: str
    type: str
    start_s: float
    end_s: float
    claim_id: str | None = None
    item_key: str | None = None

    @property
    def drawn(self) -> bool:
        return self.type in (GRAPHIC, EVIDENCE)


@dataclass(frozen=True)
class Card:
    """One card: the piece `item_key` (the `piece`-th of its claim, from 1) from `start_s` to
    `end_s`, over the shots in `shot_ids`."""

    claim_id: str
    item_key: str
    piece: int
    start_s: float
    end_s: float
    shot_ids: tuple[str, ...]

    @property
    def card_id(self) -> str:
        return f"{self.claim_id}.{self.piece}"

    @property
    def length_s(self) -> float:
        return round(self.end_s - self.start_s, _DECIMALS)


@dataclass(frozen=True)
class Unplaced:
    """A piece of evidence that got no card, and why (`NO_ROOM` or `TOO_LATE`)."""

    claim_id: str
    text: str
    item_key: str
    piece: int
    code: str

    @property
    def message(self) -> str:
        return UNPLACED_TEXT[self.code]


@dataclass(frozen=True)
class Placement:
    cards: tuple[Card, ...]
    unplaced: tuple[Unplaced, ...]


def _r(value: float) -> float:
    return round(value, _DECIMALS)


def drawn_around(slots: list[Slot], time_s: float) -> Slot | None:
    """The graphic or evidence shot that is on screen at `time_s`, or None."""
    for slot in slots:
        if slot.drawn and slot.start_s <= time_s < slot.end_s:
            return slot
    return None


def _next_drawn_start(slots: list[Slot], after_s: float, total_s: float) -> float:
    starts = [slot.start_s for slot in slots if slot.drawn and slot.start_s > after_s]
    return min(starts) if starts else total_s


def place_cards(claims: list[ClaimTime], slots: list[Slot], total_s: float) -> Placement:
    """The cards of one scene, claim by claim in story order. Pure."""
    shown: dict[str, set[str]] = {}
    last_shot_end: dict[str, float] = {}
    for slot in slots:
        if slot.type == EVIDENCE and slot.claim_id is not None and slot.item_key is not None:
            shown.setdefault(slot.claim_id, set()).add(slot.item_key)
            last_shot_end[slot.claim_id] = max(last_shot_end.get(slot.claim_id, 0.0), slot.end_s)

    cards: list[Card] = []
    unplaced: list[Unplaced] = []
    previous_end = 0.0
    for claim in sorted(claims, key=lambda found: (found.first_s, found.claim_id)):
        done = shown.get(claim.claim_id, set())
        pending = [
            (number, key) for number, key in enumerate(claim.pieces, start=1) if key not in done
        ]
        if not pending:
            continue
        own_shots = claim.claim_id in last_shot_end
        if not own_shots:
            around = drawn_around(slots, claim.first_s)
            if around is not None and around.type == GRAPHIC:
                continue  # a source line goes on the graphic instead
        start = last_shot_end[claim.claim_id] if own_shots else max(0.0, claim.first_s)
        start = max(start, previous_end)
        # The claim's first word may fall in another claim's shot: the card follows that shot.
        while (around := drawn_around(slots, start)) is not None:
            start = around.end_s
        late = start > claim.last_s + MAX_LATE_S
        limit = _next_drawn_start(slots, start, total_s)
        if limit < total_s:
            limit -= GAP_S
        if limit - start < MIN_CARD_S and not own_shots:
            # Not enough room after the first word: start a little before it instead.
            earliest = max(previous_end, claim.first_s - MAX_LEAD_S)
            start = max(earliest, min(start, limit - MIN_CARD_S))
            if drawn_around(slots, start) is not None:
                start = max(claim.first_s, previous_end)
        available = limit - start
        if late or available < MIN_CARD_S:
            code = TOO_LATE if late else NO_ROOM
            unplaced.extend(
                Unplaced(claim.claim_id, claim.text, key, number, code) for number, key in pending
            )
            continue
        wanted = min(
            max(len(pending) * MIN_CARD_S, claim.last_s + TAIL_S - start),
            len(pending) * MAX_CARD_S,
        )
        total = min(wanted, available)
        count = max(1, min(len(pending), int(total // MIN_CARD_S)))
        each = total / count
        cursor = start
        for number, key in pending[:count]:
            end = _r(cursor + each)
            cards.append(
                Card(
                    claim_id=claim.claim_id,
                    item_key=key,
                    piece=number,
                    start_s=_r(cursor),
                    end_s=end,
                    shot_ids=tuple(
                        slot.shot_id
                        for slot in slots
                        if not slot.drawn and slot.start_s < end and slot.end_s > cursor
                    ),
                )
            )
            cursor = end
        unplaced.extend(
            Unplaced(claim.claim_id, claim.text, key, number, NO_ROOM)
            for number, key in pending[count:]
        )
        previous_end = cursor
    return Placement(cards=tuple(cards), unplaced=tuple(unplaced))
