"""The ASS subtitle file of an explainer's captions and callouts (EXPLAINER-008, 010). Pure: no
I/O.

`ass_document` turns the frozen caption track (`caption_plan.CaptionTrack`) and the frozen callout
track (`callout_render.CalloutTrack`) into the text of one ASS file, which
`render_commands.final_encode_args` burns into the picture with libass. Either track may be
missing. Captions are on layer 0 and callouts on layer 1.

**Callouts.** Each part of a callout is one event, from the start of the part to the end of the
callout, in the `Callout` style: an opaque box (`BorderStyle 3`) behind the text, in the role
colour. The text is put at an exact place (`\\an8` and `\\pos`), with libass wrapping turned off
(`\\q2`), one line to a part, so it is drawn where `callout_render` laid it out. Every event
fades in and out. Then, by type:

- `emphasis`, `question`, a `list` item and a `comparison` side slide down into place;
- `number` pops: it grows from `NUMBER_POP_FROM` percent past full size and settles;
- `section_title` grows slightly as it fades in.

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

from app.services import callout_render
from app.services.callout_plan_writer import TYPE_NUMBER, TYPE_SECTION_TITLE
from app.services.callout_render import CalloutEntry, CalloutPart, CalloutStyle, CalloutTrack
from app.services.caption_plan import CaptionGroup, CaptionStyle, CaptionTrack

STYLE_NAME = "Caption"
CALLOUT_STYLE_NAME = "Callout"
_LAYER_CAPTION = 0
_LAYER_CALLOUT = 1
# ASS alignment 8: top, centred.
_ALIGN_TOP_CENTRE = 8
# Wrapping off: a line break is only where the text has one.
_WRAP_NONE = 2
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


def _style_lines(caption: CaptionStyle | None, callout: CalloutStyle | None) -> list[str]:
    lines: list[str] = []
    if caption is not None:
        lines.append(
            f"Style: {STYLE_NAME},{caption.font_name},{caption.font_size},"
            f"{_style_colour(caption.text_colour)},{_style_colour(caption.text_colour)},"
            f"{_style_colour(caption.outline_colour)},{_style_colour(caption.outline_colour)},"
            f"0,0,0,0,100,100,0,0,1,{caption.outline:.1f},0,{_ALIGN_BOTTOM_CENTRE},"
            f"{caption.margin_h},{caption.margin_h},{caption.margin_v},1"
        )
    if callout is not None:
        # The box of `BorderStyle 3` is drawn in the outline colour; each event sets its own
        # size, border width and transparency.
        lines.append(
            f"Style: {CALLOUT_STYLE_NAME},{callout.font_name},{callout.play_res_y // 20},"
            f"&H00FFFFFF,&H00FFFFFF,{_style_colour(callout.box_colour)},"
            f"{_style_colour(callout.box_colour)},"
            f"0,0,0,0,100,100,0,0,3,0,0,{_ALIGN_TOP_CENTRE},0,0,0,1"
        )
    return lines


def _header(
    play_res: tuple[int, int], caption: CaptionStyle | None, callout: CalloutStyle | None
) -> list[str]:
    return [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res[0]}",
        f"PlayResY: {play_res[1]}",
        f"WrapStyle: {_WRAP_SMART}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *_style_lines(caption, callout),
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
            f"Dialogue: {_LAYER_CAPTION},{_clock(start)},{_clock(end)},{STYLE_NAME},,0,0,0,,"
            f"{' '.join(shown)}"
        )
    return events


def _animation(entry: CalloutEntry, part: CalloutPart, style: CalloutStyle) -> str:
    """The position and the animation tags of one part: where it is and how it comes in. All
    times are in milliseconds from the start of the event.
    """
    shown_ms = entry.end_ms - part.start_ms
    if entry.type == TYPE_SECTION_TITLE:
        fade = min(callout_render.TITLE_FADE_MS, shown_ms // 2)
        grow = callout_render.TITLE_GROW_FROM
        return (
            f"\\pos({part.x},{part.y})\\fad({fade},{fade})"
            f"\\fscx{grow}\\fscy{grow}"
            f"\\t(0,{callout_render.TITLE_GROW_MS},\\fscx100\\fscy100)"
        )
    fade = min(style.fade_ms, shown_ms // 2)
    if entry.type == TYPE_NUMBER:
        start, peak = callout_render.NUMBER_POP_FROM, callout_render.NUMBER_POP_PEAK
        return (
            f"\\pos({part.x},{part.y})\\fad({fade},{fade})"
            f"\\fscx{start}\\fscy{start}"
            f"\\t(0,{callout_render.NUMBER_POP_PEAK_MS},\\fscx{peak}\\fscy{peak})"
            f"\\t({callout_render.NUMBER_POP_PEAK_MS},{callout_render.NUMBER_POP_END_MS},"
            "\\fscx100\\fscy100)"
        )
    slide = min(style.slide_ms, shown_ms)
    return (
        f"\\move({part.x},{part.y - style.slide_px},{part.x},{part.y},0,{slide})"
        f"\\fad({fade},{fade})"
    )


def _callout_events(entry: CalloutEntry, style: CalloutStyle) -> list[str]:
    end = _centiseconds(entry.end_ms)
    box = _bgr(style.box_colour)
    transparency = f"&H{style.box_transparency:02X}&"
    events: list[str] = []
    for part in entry.parts:
        start = _centiseconds(part.start_ms)
        if end <= start:
            continue
        tags = (
            f"\\an{_ALIGN_TOP_CENTRE}\\q{_WRAP_NONE}{_animation(entry, part, style)}"
            f"\\fs{part.font_size}\\bord{part.border}\\shad0"
            f"\\c{_bgr(part.colour)}\\3c{box}\\3a{transparency}"
        )
        text = _clean(part.text)
        events.append(
            f"Dialogue: {_LAYER_CALLOUT},{_clock(start)},{_clock(end)},{CALLOUT_STYLE_NAME},,"
            f"0,0,0,,{{{tags}}}{text}"
        )
    return events


def ass_document(captions: CaptionTrack | None, callouts: CalloutTrack | None = None) -> str:
    """The whole ASS file of the captions and the callouts. At least one must be given."""
    if captions is not None:
        play_res = (captions.style.play_res_x, captions.style.play_res_y)
    elif callouts is not None:
        play_res = (callouts.style.play_res_x, callouts.style.play_res_y)
    else:
        raise ValueError("There is nothing to write.")
    lines = _header(
        play_res,
        captions.style if captions is not None else None,
        callouts.style if callouts is not None else None,
    )
    if captions is not None:
        for group in captions.groups:
            lines.extend(_group_events(group, captions.style))
    if callouts is not None:
        for entry in callouts.entries:
            lines.extend(_callout_events(entry, callouts.style))
    return "\n".join(lines) + "\n"
