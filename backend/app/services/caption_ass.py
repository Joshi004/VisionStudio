"""The ASS subtitle file of an explainer's captions (EXPLAINER-008). Pure: no I/O.

`ass_document` turns the frozen caption track (`caption_plan.CaptionTrack`) into the text of one
ASS file, which `render_commands.final_encode_args` burns into the picture with libass.

**Highlight.** Each word of a group gets its own `Dialogue` event. The event shows the whole group
with that one word coloured, and lasts from the word's start to the next word's start (the last
word lasts to the end of the group). The events of a group follow each other with no gap, so the
colour steps from word to word and only the word being spoken is highlighted.

**Times** are whole centiseconds, as ASS keeps them. Every boundary is rounded by the same
function, so two events that meet share one exact boundary, and an event that rounds to nothing
is left out.

**Text** comes from the script. It is cleaned again here: braces and backslashes are removed, so
no script word can become an override tag, and a line break cannot enter an event.
"""

from __future__ import annotations

import re

from app.services.caption_plan import CaptionGroup, CaptionStyle, CaptionTrack

STYLE_NAME = "Caption"
# ASS alignment 2: bottom, centred.
_ALIGN_BOTTOM_CENTRE = 2
# Smart wrapping: a group too wide for its lines is broken into two of about the same width.
_WRAP_SMART = 0
_UNSAFE_TEXT = re.compile(r"[{}\\\r\n]")


def _bgr(colour: str) -> str:
    """`#RRGGBB` as the `&HBBGGRR&` of an override tag."""
    return f"&H{colour[5:7]}{colour[3:5]}{colour[1:3]}&".upper()


def _style_colour(colour: str) -> str:
    """`#RRGGBB` as the `&HAABBGGRR` of a style line (opaque)."""
    return f"&H00{colour[5:7]}{colour[3:5]}{colour[1:3]}".upper()


def _centiseconds(ms: int) -> int:
    return (ms + 5) // 10


def _clock(centiseconds: int) -> str:
    hours, rest = divmod(centiseconds, 360000)
    minutes, rest = divmod(rest, 6000)
    seconds, hundredths = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{hundredths:02d}"


def _clean(text: str) -> str:
    return " ".join(_UNSAFE_TEXT.sub("", text).split())


def _header(style: CaptionStyle) -> list[str]:
    return [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {style.play_res_x}",
        f"PlayResY: {style.play_res_y}",
        f"WrapStyle: {_WRAP_SMART}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: {STYLE_NAME},{style.font_name},{style.font_size},"
        f"{_style_colour(style.text_colour)},{_style_colour(style.text_colour)},"
        f"{_style_colour(style.outline_colour)},{_style_colour(style.outline_colour)},"
        f"0,0,0,0,100,100,0,0,1,{style.outline:.1f},0,{_ALIGN_BOTTOM_CENTRE},"
        f"{style.margin_h},{style.margin_h},{style.margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]


def _group_events(group: CaptionGroup, style: CaptionStyle) -> list[str]:
    words = [_clean(word.text) for word in group.words]
    highlight, normal = _bgr(style.highlight_colour), _bgr(style.text_colour)
    events: list[str] = []
    for position, word in enumerate(group.words):
        start = _centiseconds(word.start_ms)
        end = _centiseconds(word.end_ms)
        if end <= start:
            continue
        shown = [
            f"{{\\c{highlight}}}{text}{{\\c{normal}}}" if index == position else text
            for index, text in enumerate(words)
        ]
        events.append(
            f"Dialogue: 0,{_clock(start)},{_clock(end)},{STYLE_NAME},,0,0,0,,{' '.join(shown)}"
        )
    return events


def ass_document(track: CaptionTrack) -> str:
    """The whole ASS file of the track."""
    lines = _header(track.style)
    for group in track.groups:
        lines.extend(_group_events(group, track.style))
    return "\n".join(lines) + "\n"
