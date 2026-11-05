"""The YTT file of an explainer's captions (CAP-002, `Captions_ytt_implementation_phases.md` 4.4).
Pure: no I/O.

`ytt_document` turns a frozen caption track (`caption_plan.CaptionTrack`) into YouTube Timed Text
format 3 (also called SRV3), which YouTube Studio accepts as an uploaded caption file. The format
is not documented by Google: the values here come from what YouTube Studio exports and from
community references, and are starting values until the owner has checked them on YouTube
(CAP-004).

**Look.** The same as the burned-in captions as far as YouTube allows: groups of the frozen
track, the spoken word in the highlight colour, bold white text with a dark glow edge (YTT has no
outline), at the height of the burned-in captions. Custom fonts are not possible, so the default
font is used.

**Highlight.** Each word of a group is one `<p>`, as `caption_ass` makes one event per word. A
`<p>` shows the whole group with that word in the second pen, from the word's start to the
word's end. The words of a group follow each other with no gap, so the colour steps from word to
word.

**Quirks.** No `<p>` starts at 0 (the Android app drops it). Pure white (`#FFFFFF`) is written
`#FEFEFE`, and opacity is 254, because YouTube drops the extreme values. A zero-width space
separates the styled segments of a `<p>` so YouTube does not strip the first segment's pen.

**Safety.** The XML is built with `xml.etree.ElementTree`, so every word is escaped, and
characters that XML 1.0 cannot hold are removed first.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Final

from app.services.caption_plan import CaptionGroup, CaptionStyle, CaptionTrack

# The size of the pens. YouTube's scale is not documented; 100 is its own default size. The
# final value is set from the owner's check on YouTube (CAP-004).
PEN_SIZE: Final = 100

_PEN_TEXT: Final = "1"
_PEN_HIGHLIGHT: Final = "2"
_WINDOW: Final = "1"
_WINDOW_STYLE: Final = "1"
# Window position: bottom centre (anchor point 7 of YouTube's grid), centred horizontally.
_ANCHOR_BOTTOM_CENTRE: Final = "7"
_HORIZONTAL_CENTRE: Final = "50"
_JUSTIFY_CENTRE: Final = "2"
# A glow edge, which stands in for the outline (YTT has no outline type).
_EDGE_GLOW: Final = "3"
_OPACITY: Final = "254"
_ZERO_WIDTH_SPACE: Final = "\u200b"
# YouTube draws a position `v` at `2 + 0.96 * v` percent of the height.
_SAFE_TOP_PERCENT: Final = 2.0
_SAFE_SCALE: Final = 0.96
# Characters XML 1.0 cannot hold, and line breaks.
_UNSAFE_TEXT: Final = re.compile(r"[\x00-\x08\x0b-\x1f\ufffe\uffff\u2028\u2029\x85]")
_PURE_WHITE: Final = "#FFFFFF"
_NEARLY_WHITE: Final = "#FEFEFE"


def _clean(text: str) -> str:
    return " ".join(_UNSAFE_TEXT.sub(" ", text).split())


def _colour(colour: str) -> str:
    """`#RRGGBB` in capitals, with pure white as the nearly white YouTube keeps."""
    upper = colour.upper()
    return _NEARLY_WHITE if upper == _PURE_WHITE else upper


def _vertical_position(style: CaptionStyle) -> int:
    """YouTube's `av` for the bottom edge of the captions: where the burned-in captions' bottom
    edge is, from the top, as a percent, taken back through YouTube's safe area.
    """
    screen = (style.play_res_y - style.margin_v) / style.play_res_y * 100
    value = round((screen - _SAFE_TOP_PERCENT) / _SAFE_SCALE)
    return min(100, max(0, value))


def _pen(pen_id: str, colour: str, edge_colour: str) -> ET.Element:
    return ET.Element(
        "pen",
        {
            "id": pen_id,
            "sz": str(PEN_SIZE),
            "b": "1",
            "fc": _colour(colour),
            "fo": _OPACITY,
            "bo": "0",
            "et": _EDGE_GLOW,
            "ec": _colour(edge_colour),
        },
    )


def _head(style: CaptionStyle) -> ET.Element:
    head = ET.Element("head")
    head.append(_pen(_PEN_TEXT, style.text_colour, style.outline_colour))
    head.append(_pen(_PEN_HIGHLIGHT, style.highlight_colour, style.outline_colour))
    head.append(
        ET.Element(
            "wp",
            {
                "id": _WINDOW,
                "ap": _ANCHOR_BOTTOM_CENTRE,
                "ah": _HORIZONTAL_CENTRE,
                "av": str(_vertical_position(style)),
            },
        )
    )
    head.append(ET.Element("ws", {"id": _WINDOW_STYLE, "ju": _JUSTIFY_CENTRE}))
    return head


def _segment(pen: str, text: str) -> ET.Element:
    segment = ET.Element("s", {"p": pen})
    segment.text = text
    return segment


def _paragraph(words: list[str], highlighted: int, start_ms: int, duration_ms: int) -> ET.Element:
    """One `<p>`: the whole group, with the word at `highlighted` in the highlight pen. The
    words before it and after it are one segment each, in the text pen. Between two segments is
    a zero-width space.
    """
    paragraph = ET.Element(
        "p",
        {
            "t": str(start_ms),
            "d": str(duration_ms),
            "wp": _WINDOW,
            "ws": _WINDOW_STYLE,
            "p": _PEN_TEXT,
        },
    )
    segments: list[ET.Element] = []
    if highlighted > 0:
        segments.append(_segment(_PEN_TEXT, " ".join(words[:highlighted]) + " "))
    segments.append(_segment(_PEN_HIGHLIGHT, words[highlighted]))
    if highlighted + 1 < len(words):
        segments.append(_segment(_PEN_TEXT, " " + " ".join(words[highlighted + 1 :])))
    paragraph.text = _ZERO_WIDTH_SPACE
    for position, segment in enumerate(segments):
        if position + 1 < len(segments):
            segment.tail = _ZERO_WIDTH_SPACE
        paragraph.append(segment)
    return paragraph


def _group_paragraphs(group: CaptionGroup) -> list[ET.Element]:
    texts = [_clean(word.text) for word in group.words]
    paragraphs: list[ET.Element] = []
    for position, word in enumerate(group.words):
        if not texts[position]:
            continue
        # Inside the group's own time, and never at 0.
        start = max(word.start_ms, group.start_ms, 1)
        end = min(word.end_ms, group.end_ms)
        if end <= start:
            continue
        shown = [text for text in texts if text]
        highlighted = sum(1 for text in texts[:position] if text)
        paragraphs.append(_paragraph(shown, highlighted, start, end - start))
    return paragraphs


def ytt_document(track: CaptionTrack) -> str:
    """The whole YTT file of a caption track, as text (UTF-8 when written)."""
    root = ET.Element("timedtext", {"format": "3"})
    root.append(_head(track.style))
    body = ET.SubElement(root, "body")
    for group in track.groups:
        body.extend(_group_paragraphs(group))
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")
