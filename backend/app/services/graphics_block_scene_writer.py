"""The block-scene call of the Graphics lab: the instructions to the model, and the request
(GFX-009, `Graphics_lab_implementation_phases.md` §4.5.2).

Pure functions, no I/O.

One call reads the brief of a run (GFX-003) and the library of ten building blocks, and designs
the scene freely: which blocks, in which regions of a 12 x 12 grid, entering on which beats and
with which effects. The answer is checked by `graphics_blocks.check_scene`, and the motion
service then measures the texts in the browser (`graphics_blocks.layout_problems`). When the
layout has problems, `layout_retry_request` asks once more with the scene and the list.

The model never writes a number: it refers to facts and derived values by id, and the text that
shows them is written by code (G-7). It never writes a time either: it names the beat at which
each part appears (G-9).
"""

from __future__ import annotations

import json
from typing import Any, Final

from app.services import graphics_blocks
from app.services.graphics_template_spec_writer import brief_for_model
from app.services.music_bible_writer import parse_answer as parse_answer
from app.services.text_limits import length_rule

# One call, and its largest answer. A scene is small; the cap only bounds the call (tokens are
# paid as used) and stays under the Qwen3.8 limit of 49,152.
MAX_TOKENS: Final = 32_000
REASONING_EFFORT: Final = "high"

_RULES: Final = """\
You are designing a short explainer graphic from building blocks. You are given one line of an \
explainer script and the brief of its graphic: what it should show, the numbers it uses (facts \
and derived values), and the beats (the moments of the line at which each part appears). Other \
programs draw the graphic from your answer. You never draw anything, you never write a number \
and you never write a time.

YOUR ANSWER is one JSON object: {"elements": [...]}, at most {max_elements} elements. Design \
the graphic freely: choose the blocks, where they go and how they move so that the picture \
suits the line. Vary the layout from one line to the next; do not always use a title, a chart \
and a badge.

THE GRID. The video is {size}. The graphic is placed on a grid of 12 columns and {rows} rows \
inside the safe area. A cell is {cell_w} x {cell_h} pixels. A region is [first column, first \
row, last column, last row], counted from 1, both ends included, for example [1, 1, 12, 2] is \
the top two rows across the whole width. Columns go from 1 to 12 and rows from 1 to {rows}: \
everything below row {rows} is kept free for the captions. Give every block with a region the \
room its content needs (a long text needs a wide region), and keep regions of different \
elements apart so that no two texts overlap. Leave at least one empty column (or row) between \
two elements that an arrow joins, so the arrow has room.

BLOCKS (every element has an "id" of 1 to 16 lowercase letters, digits or underscores \
starting with a letter, unique in the scene, a "block", a "region" unless the block follows \
other elements, an "enter" and an optional "exit")
{blocks}

REFS AND BEATS. A "ref" is the id of a fact or a derived value of the brief. Refer to numbers \
by id only. The text that shows them is written by code. Never type a number into a text. A \
"beat id" is the id of a beat of the brief. Never use a beat that is not in the brief.

ENTER. {"beat": beat id, "effect": effect} for a block that enters once. A series \
(bar_series, line_series) enters part by part: {"beats": [one beat id for each value], \
"effect": effect}, and the beats never go backwards in the line. An element appears at its \
beat, so give it the beat of the moment the line says what it shows. Several elements may \
share a beat. An arrow or a highlight must not enter before the elements it follows.

EXIT (optional). {"beat": beat id, "effect": effect}: the element leaves at that beat, which \
must come after its entrance. Exit effects: fade, slide_up, slide_left, pop. Use it to make \
room for what comes next, not on every element.

EFFECTS. fade, slide_up, slide_left and pop work on any block. "grow" is for bar_series and \
progress_ring, "draw" for line_series, arrow, highlight and progress_ring, "count_up" for \
counter, badge (with a value) and progress_ring, "typewriter" for text. A line_series takes \
only draw or fade; a bar_series takes grow, fade, slide_up, slide_left or pop.

TEXT. Texts (titles, labels, cell texts) are written by you, in plain words, and must be \
short. A text must not contain a number the line does not say. Never cut a word to make it \
fit: write a shorter text. Text is made smaller to fit its region, down to unreadable: if a \
text would be small, give it a larger region or use fewer words. No text may touch the caption \
area or another element's text.

{length_rule}"""

_BLOCKS: Final = """\
- "text": {"style": "title" | "label" | "body", "text": text, "align": "left" | "center" | \
"right" (optional, default left), "role": colour role (optional)}. A title is large and bold, \
a label is small and muted, a body is plain. At most 6 text elements.
- "counter": {"value": ref, "label": text (optional), "align": ..., "role": ...}. One big \
number with an optional label under it.
- "bar_series": {"values": 2 to 6 refs of one unit, "labels": one text for each, \
"orientation": "vertical" | "horizontal", "emphasis": refs to stress (optional)}. Bars always \
start at zero. A stressed bar is the accent colour and the others are muted.
- "line_series": {"values": 3 to 12 refs of one unit, "labels": one text for each, "area": \
true (optional)}. A line through the points with each value shown above its point.
- "node": {"label": text, "role": ...}. A rounded box with a label, for steps and ideas.
- "arrow": {"from": id, "to": id, "role": ...}: runs between two elements that have a region. \
It has no region.
- "table": {"header": 1 to 4 texts (optional), "rows": 1 to 5 rows of the same number of \
cells (at most 4), each cell a text or {"value": ref}}. Numbers are right aligned.
- "badge": {"value": ref} or {"text": text}, and "role": a small rounded label that has the \
size of its content and sits in the middle of its region.
- "highlight": {"target": id, "role": ...}: a box drawn around another element. It has no \
region.
- "progress_ring": {"value": ref to a percent from 0 to 100, "role": ...}: a ring filled as \
far as the value, with the value in the middle.
A colour "role" is one of text, muted, accent, positive, negative, number. positive is for \
good news and negative for bad news; accent stresses; number is for a number that must stand \
out."""

_SHAPE: Final = """{"elements": [{"id": "title", "block": "text", "style": "title", "text": \
"Hiring in spring", "region": [1, 1, 8, 2], "enter": {"beat": "b1", "effect": "slide_up"}}, \
{"id": "bars", "block": "bar_series", "values": ["f1", "f2"], "labels": ["March", "April"], \
"orientation": "vertical", "emphasis": ["f2"], "region": [1, 3, 8, 8], "enter": {"beats": \
["b2", "b3"], "effect": "grow"}}, {"id": "gain", "block": "badge", "value": "d1", "role": \
"positive", "region": [10, 4, 12, 6], "enter": {"beat": "b4", "effect": "pop"}}, {"id": \
"link", "block": "arrow", "from": "bars", "to": "gain", "enter": {"beat": "b4", "effect": \
"draw"}}]} (the ids, texts and regions here only show the form, never copy them)"""


def _instructions(resolved: dict[str, Any]) -> str:
    width, height = int(resolved["width"]), int(resolved["height"])
    area = resolved["safe_area"]
    shape = f"{'landscape' if width >= height else 'portrait'}, {width} x {height}"
    return (
        _RULES.replace("{max_elements}", str(graphics_blocks.MAX_ELEMENTS))
        .replace("{size}", shape)
        .replace("{rows}", str(graphics_blocks.grid_rows(resolved)))
        .replace("{cell_w}", str(round((int(area["right"]) - int(area["left"])) / 12)))
        .replace("{cell_h}", str(round((int(area["bottom"]) - int(area["top"])) / 12)))
        .replace("{blocks}", _BLOCKS)
        .replace("{length_rule}", length_rule(graphics_blocks.LIMIT_NAMES))
        + "\n\nAnswer with one JSON object only, in exactly this form: "
        + _SHAPE
    )


def build_request(
    line: str,
    orientation: str,
    brief: dict[str, Any],
    resolved: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    """The exact request body of the first call. It is stored on the job."""
    user = (
        f"LINE:\n{line}\n\nORIENTATION: {orientation}\n\nBRIEF:\n"
        f"{json.dumps(brief_for_model(brief, resolved), ensure_ascii=False, indent=1)}"
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


def layout_retry_request(
    body: dict[str, Any], scene: dict[str, Any], problems: list[str]
) -> dict[str, Any]:
    """`body` with a note added to its last user message: the scene the model wrote, which was
    valid, and the layout problems found when it was measured in the browser. `body` is not
    changed.
    """
    listed = "\n".join(f"- {problem}" for problem in problems)
    note = (
        "\n\nNOTE: An earlier answer to this request was valid, but when its scene was measured "
        f"in the browser these layout problems were found:\n{listed}\n\nThe earlier scene was:\n"
        f"{json.dumps({'elements': scene['elements']}, ensure_ascii=False)}\n\nWrite the whole "
        "scene again with these problems fixed (move or resize regions, shorten texts, or change "
        "beats) and everything else kept as it was."
    )
    messages = [dict(message) for message in body["messages"]]
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            message["content"] += note
            break
    return {**body, "messages": messages}
