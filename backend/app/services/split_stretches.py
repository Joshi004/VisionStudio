"""Where a graphic overlay and evidence share the screen (OVL-007,
`Graphic_overlays_implementation_phases.md` section 4.5).

A graphic overlay **meets** evidence when its span overlaps a full-screen evidence shot or an
evidence card. Both are then drawn side by side for one **split stretch**: from the start of the
first of them to the end of the last, so the layout never changes in the middle of a sentence
(OV-7). Members that overlap one another (an overlay over two evidence shots in a row, two
overlays over one evidence shot) join the same stretch.

Each side of a stretch is a list of **segments**: the overlays on the graphic side, the evidence
shots and cards on the evidence side. A segment is drawn from its own start (the stretch's start
for the first of its side) up to where the next one on its side starts (the stretch's end for the
last), so a panel is never empty and an overlay's beats stay on its words (a segment only grows).

Pure: no I/O, no clock. Times are seconds on the scene's timeline, the same numbers as
`ShotSpan.start_s` and `end_s`.

A stretch is refused, and its overlays stay full screen over the evidence as in OVL-005, when a
graphic segment would need more than `graphic_overlays.MAX_FRAMES` frames, or when it would touch a
sound bite shot (no overlay or evidence member ever does, so this is a guard).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.services import evidence_cards, graphic_overlays

KIND_OVERLAY: Final = "overlay"
KIND_SHOT: Final = "shot"
KIND_CARD: Final = "card"

TOO_LONG: Final = "too_long"
SOUNDBITE: Final = "soundbite"
REFUSED_TEXT: Final = {
    TOO_LONG: (
        "Shown beside the evidence, this graphic would have to be drawn for about 30 seconds or "
        "more, so it covers the evidence full screen instead."
    ),
    SOUNDBITE: "A sound bite is in the way, so this graphic covers the evidence full screen.",
}

_DECIMALS: Final = 3


@dataclass(frozen=True)
class Segment:
    """One thing drawn in a panel of a stretch, from `draw_start_s` to `draw_end_s`. `source_id` is
    the overlay's id (`{first}-{last}`), the evidence shot's id or the card's id. `item_key` is the
    piece of an evidence segment."""

    kind: str
    source_id: str
    draw_start_s: float
    draw_end_s: float
    item_key: str | None = None
    claim_id: str | None = None
    piece: int | None = None

    @property
    def length_s(self) -> float:
        return round(self.draw_end_s - self.draw_start_s, _DECIMALS)


@dataclass(frozen=True)
class Stretch:
    """One split stretch of a scene: the graphic side and the evidence side."""

    scene_id: str
    start_s: float
    end_s: float
    graphics: tuple[Segment, ...]
    evidence: tuple[Segment, ...]

    @property
    def stretch_id(self) -> str:
        return self.graphics[0].source_id

    def segment_id(self, segment: Segment) -> str:
        """The key of an evidence segment's clip within its scene."""
        return f"{self.stretch_id}:{segment.source_id}"

    def graphic_of(self, overlay_id: str) -> Segment | None:
        return next((seg for seg in self.graphics if seg.source_id == overlay_id), None)

    @property
    def card_ids(self) -> tuple[str, ...]:
        return tuple(seg.source_id for seg in self.evidence if seg.kind == KIND_CARD)

    @property
    def shot_ids(self) -> tuple[str, ...]:
        return tuple(seg.source_id for seg in self.evidence if seg.kind == KIND_SHOT)


@dataclass(frozen=True)
class Refused:
    """An overlay that meets evidence but is not drawn beside it, and why."""

    scene_id: str
    overlay_key: str
    text: str
    code: str

    @property
    def message(self) -> str:
        return REFUSED_TEXT[self.code]


@dataclass(frozen=True)
class Found:
    stretches: tuple[Stretch, ...]
    refused: tuple[Refused, ...]


@dataclass(frozen=True)
class _Member:
    kind: str
    source_id: str
    start_s: float
    end_s: float
    item_key: str | None = None
    claim_id: str | None = None
    piece: int | None = None


def _meets(first: _Member, second: _Member) -> bool:
    return first.start_s < second.end_s and second.start_s < first.end_s


def _segments(members: list[_Member], start_s: float, end_s: float) -> tuple[Segment, ...]:
    """The segments of one side: each from its own start (the stretch's for the first) to the next
    one's start (the stretch's end for the last)."""
    ordered = sorted(members, key=lambda member: (member.start_s, member.source_id))
    found: list[Segment] = []
    for number, member in enumerate(ordered):
        begin = start_s if number == 0 else member.start_s
        finish = end_s if number == len(ordered) - 1 else ordered[number + 1].start_s
        found.append(
            Segment(
                kind=member.kind,
                source_id=member.source_id,
                draw_start_s=round(begin, _DECIMALS),
                draw_end_s=round(finish, _DECIMALS),
                item_key=member.item_key,
                claim_id=member.claim_id,
                piece=member.piece,
            )
        )
    return tuple(found)


def find(
    scene_id: str,
    overlays: tuple[graphic_overlays.Overlay, ...],
    evidence_shots: list[evidence_cards.Slot],
    cards: tuple[evidence_cards.Card, ...],
    bites: list[evidence_cards.Slot],
) -> Found:
    """The split stretches of a scene and the overlays that meet evidence but got none.
    `evidence_shots` are the scene's full-screen evidence shots (`item_key` set), `bites` its sound
    bite shots."""
    graphics = [
        _Member(KIND_OVERLAY, overlay.overlay_id, overlay.start_s, overlay.end_s)
        for overlay in overlays
    ]
    proof = [
        _Member(
            KIND_SHOT, slot.shot_id, slot.start_s, slot.end_s, slot.item_key, slot.claim_id, None
        )
        for slot in evidence_shots
    ] + [
        _Member(
            KIND_CARD,
            card.card_id,
            card.start_s,
            card.end_s,
            card.item_key,
            card.claim_id,
            card.piece,
        )
        for card in cards
    ]
    members = graphics + proof
    parent = list(range(len(members)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for low, mine in enumerate(graphics):
        for offset, theirs in enumerate(proof):
            if _meets(mine, theirs):
                parent[root(low)] = root(len(graphics) + offset)

    groups: dict[int, list[int]] = {}
    for index in range(len(members)):
        groups.setdefault(root(index), []).append(index)

    stretches: list[Stretch] = []
    refused: list[Refused] = []
    texts = {overlay.overlay_id: overlay for overlay in overlays}
    for indexes in groups.values():
        side_graphics = [members[i] for i in indexes if i < len(graphics)]
        side_proof = [members[i] for i in indexes if i >= len(graphics)]
        if not side_graphics or not side_proof:
            continue
        start = min(member.start_s for member in side_graphics + side_proof)
        end = max(member.end_s for member in side_graphics + side_proof)
        graphic_segments = _segments(side_graphics, start, end)
        code = _refusal(graphic_segments, start, end, bites)
        if code is not None:
            refused.extend(
                Refused(scene_id, texts[seg.source_id].key, texts[seg.source_id].text, code)
                for seg in graphic_segments
            )
            continue
        stretches.append(
            Stretch(
                scene_id=scene_id,
                start_s=round(start, _DECIMALS),
                end_s=round(end, _DECIMALS),
                graphics=graphic_segments,
                evidence=_segments(side_proof, start, end),
            )
        )
    stretches.sort(key=lambda found: found.start_s)
    return Found(stretches=tuple(stretches), refused=tuple(refused))


def _refusal(
    graphic_segments: tuple[Segment, ...],
    start_s: float,
    end_s: float,
    bites: list[evidence_cards.Slot],
) -> str | None:
    if any(bite.start_s < end_s and bite.end_s > start_s for bite in bites):
        return SOUNDBITE
    for segment in graphic_segments:
        frames = graphic_overlays.clip_frames(segment.draw_start_s, segment.draw_end_s)
        if frames > graphic_overlays.MAX_FRAMES:
            return TOO_LONG
    return None
