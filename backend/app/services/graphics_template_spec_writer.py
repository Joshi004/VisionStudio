"""The template-spec call of the Graphics lab: the instructions to the model, and the request
(GFX-006, `Graphics_lab_implementation_phases.md` §4.5.1).

Pure functions, no I/O.

One call reads the brief of a run (GFX-003) and the catalogue of five templates, and answers a
template spec, or `{"template": null, "reason": "..."}` when no template fits. The answer is
checked by `graphics_templates.check_spec`. The two template engines (Remotion and Python) draw
the same spec, so there is one call for both.

The model never writes a number: it refers to facts and derived values by id, and the text that
shows them is written by code (G-7). It never writes a time either: it names the beat at which
each part appears (G-9).
"""

from __future__ import annotations

import json
from typing import Any, Final

from app.services import graphics_templates
from app.services.music_bible_writer import parse_answer as parse_answer
from app.services.text_limits import length_rule

# One call, and its largest answer. A spec is small; the cap only bounds the call (tokens are
# paid as used) and stays under the Qwen3.8 limit of 49,152.
MAX_TOKENS: Final = 32_000
REASONING_EFFORT: Final = "high"

_RULES: Final = """\
You are choosing a template for a short explainer graphic. You are given one line of an \
explainer script and the brief of its graphic: what it should show, the numbers it uses (facts \
and derived values), and the beats (the moments of the line at which each part appears). Other \
programs draw the graphic from your answer. You never draw anything, you never write a number \
and you never write a time.

YOUR ANSWER is either one template spec, or a refusal when no template fits. Say that no \
template fits when the idea is not one of the templates below (for example an abstract concept \
with no numbers, steps or points to show). A refusal is a good answer when it is true: do not \
force a template that does not fit.

TEMPLATES
{templates}

HOW TO FILL A SPEC
- "variant" is optional; leave it out for the first variant listed.
- A "ref" is the id of a fact or a derived value of the brief. Refer to numbers by id only. The \
text that shows them is written by code. Never type a number into a text.
- A "beat id" is the id of a beat of the brief. Each part of the graphic appears at its beat. \
Give the parts of a list (bars, points, nodes, items) the beats that match the order of the \
line, and never an earlier beat after a later one. Several parts may share a beat.
- Texts (titles, labels, captions) are written by you, in plain words, and must be short. A text \
must not contain a number the line does not say. Never cut a word to make it fit: write a \
shorter text.
- A bar chart or a line shows values of one unit only.
- The video is {size}. Texts must fit their space: a label of a chart with many parts has less \
room than one with few.

{length_rule}"""

_SHAPE: Final = """{"template": "bar_comparison", "variant": "vertical", "fields": {"title": \
"Hiring in spring", "bars": [{"label": "March", "value": "f1"}, {"label": "April", "value": \
"f2", "emphasis": true}], "highlight": {"value": "d1", "beat": "b3"}}, "beats": {"title": \
"b1", "bars": ["b1", "b2"]}} \
or, when none fits: {"template": null, "reason": "One short sentence saying why."} \
(the ids and texts here only show the form, never copy them)"""


def _catalogue_text() -> str:
    lines: list[str] = []
    for template in graphics_templates.CATALOGUE:
        lines.append(
            f'- "{template.key}" ({template.purpose}) variants: '
            f"{', '.join(template.variants)}.\n"
            f"  fields: {template.fields}\n  rules: {template.rules}"
        )
    return "\n".join(lines)


def _instructions(width: int, height: int) -> str:
    shape = f"{'landscape' if width >= height else 'portrait'}, {width} x {height}"
    return (
        _RULES.replace("{templates}", _catalogue_text())
        .replace("{size}", shape)
        .replace("{length_rule}", length_rule(graphics_templates.LIMIT_NAMES))
        + "\n\nAnswer with one JSON object only, in exactly this form: "
        + _SHAPE
    )


def _brief_for_model(brief: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
    """What the model sees of the brief: the intent, the numbers with the text code shows for
    each, and the beats with the second at which each starts.
    """
    fps = int(resolved["fps"])
    return {
        "kind": brief["kind"],
        "intent": brief["intent"],
        "visual_brief": brief["visual_brief"],
        "mood": brief["theme"]["mood"],
        "facts": [
            {
                "id": fact["id"],
                "label": fact["label"],
                "unit": fact["unit"],
                "shown_as": resolved["facts"][fact["id"]]["display"],
            }
            for fact in brief["facts"]
        ],
        "derived": [
            {
                "id": item["id"],
                "label": item["label"],
                "op": item["op"],
                "of": item["of"],
                "shown_as": resolved["derived"][item["id"]]["display"],
            }
            for item in brief["derived"]
        ],
        "beats": [
            {
                "id": beat["id"],
                "phrase": beat["phrase"],
                "shows": beat["shows"],
                "refs": beat["refs"],
                "starts_at_s": round(resolved["beats"][beat["id"]]["frame"] / fps, 1),
            }
            for beat in brief["beats"]
        ],
    }


def build_request(
    line: str,
    orientation: str,
    brief: dict[str, Any],
    resolved: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    """The exact request body of the one call. It is stored on the job."""
    user = (
        f"LINE:\n{line}\n\nORIENTATION: {orientation}\n\nBRIEF:\n"
        f"{json.dumps(_brief_for_model(brief, resolved), ensure_ascii=False, indent=1)}"
    )
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": _instructions(int(resolved["width"]), int(resolved["height"])),
            },
            {"role": "user", "content": user},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }
