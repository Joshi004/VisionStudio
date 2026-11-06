"""The block-scene call of a motion callout: the instructions to the model and the request (CMO-004,
`Callouts_motion_implementation_phases.md` §4.4.2).

Pure functions, no I/O.

It is `graphics_block_scene_writer` for a callout. One call reads the resolved callout (its kind,
its parts, the zones it is drawn in, the video's colours and the callout look) and designs a scene
from six blocks (`text`, `badge`, `node`, `arrow`, `highlight` and `panel`) on a 12 x 12 grid. The
differences from a graphic shot's scene:

- the model never writes a word: an element that shows text names the part of the callout it shows
  (`"part": "p1"`), and every part is shown exactly once, so an edit of the words keeps the scene;
- the canvas is transparent and is the size of the callout's zone (less a small margin), with no
  caption area, so nothing may fill it;
- an element enters on the beat of the part it shows, and nothing leaves: the composition fades the
  whole callout out at its end;
- the callout look limits the panel, the corners and the entrance effects.

The answer is checked by `graphics_blocks.check_callout_scene`, and the motion service then
measures the texts in the browser at every zone (`graphics_blocks.callout_layout_problems`). When
the layout has problems, `graphics_block_scene_writer.layout_retry_request` asks once more with
the scene and the list.
"""

from __future__ import annotations

import json
from typing import Any, Final

from app.services import graphics_blocks
from app.services.graphics_block_scene_writer import (
    layout_retry_request as layout_retry_request,
)
from app.services.graphics_block_scene_writer import parse_answer as parse_answer

# One call, and its largest answer. A scene is small; the cap only bounds the call (tokens are
# paid as used).
MAX_TOKENS: Final = 32_000
REASONING_EFFORT: Final = "high"

_RULES: Final = """\
You are designing a small animated callout from building blocks. A callout is a short piece of \
text (a key phrase, a number, a question, a comparison, a list or a section title) that appears \
over a video of a presenter at the moment the script says it. You are given the kind of callout, \
its parts (the exact texts to show, each with an id and the moment it appears), the colours of \
the video, the look every callout of the video shares, and the line of the script it appears \
in. Other programs draw the callout from your answer. You never draw anything, you never write a \
word and you never write a time.

YOUR ANSWER is one JSON object: {"elements": [...]}, at most {max_elements} elements. Keep it \
simple and quiet: a callout is a small accent over a video, not a scene.

THE CANVAS. The callout is drawn on a TRANSPARENT canvas, and the video under it must stay \
visible: do not fill the canvas. The canvas has one of these sizes (the same scene is drawn at \
each, so it must work at all of them), on a grid of 12 columns and 12 rows inside a small \
margin. The video is {size}.
{zones}
A region is [first column, first row, last column, last row], counted from 1, both ends \
included, for example [1, 1, 12, 6] is the top half across the whole width. Columns and rows go \
from 1 to 12. Give every element with a region the room its text needs: text is made smaller to \
fit its region, down to unreadable, so a long text needs a wide region and several rows (a \
title is at most about {title_size} px high and body text about {body_size} px; a text must stay \
at least {min_text} px high). Keep regions of different elements apart so that no two texts \
overlap. Leave at least one empty column (or row) between two elements that an arrow joins.

BLOCKS (every element has an "id" of 1 to 16 lowercase letters, digits or underscores \
starting with a letter, unique in the scene, a "block", a "region" unless the block follows \
other elements, and an "enter"). The words are never yours: an element that shows text has \
"part", the id of the part it shows, and no text of its own.
{blocks}

PARTS. Every part of the callout is shown by exactly one element (a text, a badge or a node). \
Never write a "text", "label" or "value" key. An element that shows a part enters on that \
part's beat, which is the part's id: {"beat": "p1", "effect": effect}.

ENTER. {"beat": part id, "effect": effect}. The effects allowed are limited by the look: \
{effects}. A panel, an arrow or a highlight takes the beat of any part: a panel usually the \
beat of the first part it sits under, and an arrow or a highlight the beat of the later of the \
elements it follows (it must not enter before them). There is no exit: the whole callout fades \
out by itself at the end.

THE LOOK. {look}
Follow it: {panel_rule} The corners ({corners}) and the entrance effects are applied for you; \
choose blocks and regions that suit them. `look.notes` says what makes the callouts of this video \
belong together; `look.emphasis` says how a number or a key word stands out; `look.density` says \
how much room to leave.

COLOURS. Text takes the colour of its part, and arrows and highlights take an optional "role" \
(text, muted, accent, positive, negative, number). Do not choose any other colour."""

_BLOCKS: Final = """\
- "text": {"style": "title" | "label" | "body", "part": part id, "align": "left" | "center" | \
"right" (optional, default left)}. A title is large and bold, a label is small, a body is plain. \
Its text is the part's text, in the part's colour.
- "badge": {"part": part id}: a small rounded label in the part's colour that has the size of \
its text and sits in the middle of its region.
- "node": {"part": part id}: a rounded box in the surface colour with a border in the part's \
colour and the part's text inside, for steps and ideas.
- "arrow": {"from": id, "to": id, "role": colour role (optional)}: runs between two elements \
that have a region. It has no region.
- "highlight": {"target": id, "role": colour role (optional)}: a box drawn around another \
element. It has no region.
- "panel": {}: a box in the surface colour, with no text, drawn under the elements that overlap \
it so that their text stays readable over the video. Give it a region that covers the text it \
sits under, and no more. Panels and nodes together may fill at most {max_cover} percent of the \
canvas."""

_PANEL_ALLOWED: Final = (
    'the panel is "{panel}", so the block panel is available (a node is a box too).'
)
_PANEL_FORBIDDEN: Final = (
    'the panel is "{panel}", which has no box behind the text, so do not use the block panel '
    "(use text on its own, and a highlight or an arrow for a line)."
)

_SHAPE: Final = """{"elements": [{"id": "back", "block": "panel", "region": [1, 2, 12, 11], \
"enter": {"beat": "p1", "effect": "fade"}}, {"id": "words", "block": "text", "style": "title", \
"part": "p1", "region": [2, 3, 11, 10], "enter": {"beat": "p1", "effect": "fade"}}]} (the ids \
and regions here only show the form, never copy them)"""


def _zone_lines(resolved: dict[str, Any]) -> str:
    inset = graphics_blocks.callout_inset(resolved)
    lines: list[str] = []
    for zone in resolved["zones"]:
        cell_w = round((int(zone["width"]) - 2 * inset) / graphics_blocks.GRID)
        cell_h = round((int(zone["height"]) - 2 * inset) / graphics_blocks.GRID)
        lines.append(
            f"- {zone['placement']}: {zone['width']} x {zone['height']} pixels "
            f"(a cell is {cell_w} x {cell_h} pixels)"
        )
    return "\n".join(lines)


def _text_sizes(resolved: dict[str, Any]) -> tuple[int, int]:
    """The title size and the body size, in pixels: those of the blocks, from the output frame."""
    landscape = int(resolved["frame_width"]) >= int(resolved["frame_height"])
    height = int(resolved["frame_height"])
    return (
        round((0.06 if landscape else 0.036) * height),
        round((0.032 if landscape else 0.024) * height),
    )


def _instructions(resolved: dict[str, Any]) -> str:
    look = resolved["look"]
    panel = str(look.get("panel"))
    panel_rule = (
        _PANEL_FORBIDDEN if panel in graphics_blocks.NO_PANEL_LOOKS else _PANEL_ALLOWED
    ).replace("{panel}", panel)
    effects = "; ".join(
        f"{block}: {', '.join(graphics_blocks.callout_effects(block, look))}"
        for block in graphics_blocks.CALLOUT_BLOCKS
        if not (block == "panel" and panel in graphics_blocks.NO_PANEL_LOOKS)
    )
    title_size, body_size = _text_sizes(resolved)
    width, height = int(resolved["frame_width"]), int(resolved["frame_height"])
    shape = f"{'landscape' if width >= height else 'portrait'}, {width} x {height}"
    from app.services.callout_component_checks import MAX_COVER

    values = {
        "max_elements": str(graphics_blocks.MAX_CALLOUT_ELEMENTS),
        "size": shape,
        "zones": _zone_lines(resolved),
        "title_size": str(title_size),
        "body_size": str(body_size),
        "min_text": str(round(graphics_blocks.MIN_TEXT_SHARE * height)),
        "effects": effects,
        "look": json.dumps(look, ensure_ascii=False),
        "panel_rule": panel_rule,
        "corners": str(look.get("corners")),
    }
    text = _RULES.replace("{blocks}", _BLOCKS.replace("{max_cover}", str(round(MAX_COVER * 100))))
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text + "\n\nAnswer with one JSON object only, in exactly this form: " + _SHAPE


def brief_for_model(resolved: dict[str, Any], line: str, mood: str) -> dict[str, Any]:
    """What the user message tells the model: the callout's kind, its parts with the frame each
    appears at, the colours, the look, the line it appears in and the mood of the video.
    """
    return {
        "kind": resolved["kind"],
        "parts": resolved["parts"],
        "theme": resolved["theme"],
        "look": resolved["look"],
        "line_of_the_script": line,
        "mood_of_the_video": mood,
    }


def build_request(
    resolved: dict[str, Any], line: str, mood: str, orientation: str, *, model: str
) -> dict[str, Any]:
    """The exact request body of the first call. It is stored on the job."""
    user = (
        f"ORIENTATION: {orientation}\n\nCALLOUT:\n"
        f"{json.dumps(brief_for_model(resolved, line, mood), ensure_ascii=False, indent=1)}"
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _instructions(resolved)},
            {"role": "user", "content": user},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }
