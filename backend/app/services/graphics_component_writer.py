"""The component call of the Graphics lab: the instructions to the model, and the requests
(GFX-010, `Graphics_lab_implementation_phases.md` §4.5.3).

Pure functions, no I/O.

One call reads the brief of a run (GFX-003) and writes one Remotion component as TSX: free code,
where the block engine (GFX-009) is checked blocks and the template engines (GFX-006) are a fixed
catalogue. The code is checked by `graphics_code_checks.check_code`, and the motion service then
compiles it and draws three still frames (`POST /checks`). When that fails, `repair_request` asks
once more with the code and the error.

The model never types a number: the props give it every fact and derived value with the text that
shows it (G-7). It never types a time either: the props give it the frame of every beat (G-9).
The answer is code, not JSON, so the request asks for one fenced block and the reader takes the
code out of it.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from app.services import graphics_code_checks
from app.services.graphics_template_spec_writer import brief_for_model

# A component is long. The cap only bounds the call (tokens are paid as used) and stays under the
# Qwen3.8 limit of 49,152.
MAX_TOKENS: Final = 48_000
REASONING_EFFORT: Final = "high"

# The first fenced block of the answer that holds a default export, else the first fenced block.
_FENCE: Final = re.compile(
    r"```[ \t]*(?:tsx|ts|jsx|js|typescript|javascript)?[ \t]*\n(.*?)```", re.DOTALL
)

_RULES: Final = """\
You are writing one animated explainer graphic as a Remotion (React) component. You are given one \
line of an explainer script and the brief of its graphic: what it should show, the numbers it \
uses (facts and derived values, each with the exact text to show), and the beats (the moments of \
the line at which each part should appear). Your component is drawn frame by frame into a video, \
and the video is compared with graphics made by other methods, so make a graphic that is clear, \
well designed and fits the line.

YOUR ANSWER is one TSX file in one ```tsx code block, and nothing else of value outside it. Its \
default export is the component. It is at most {max_chars} characters.

THE PROPS. The component receives these props (the values are filled in when it is drawn):

```ts
type GraphicProps = {
  width: number; height: number; fps: number; durationInFrames: number;
  theme: { background: string; surface: string; text: string; muted: string;
           accent: string; positive: string; negative: string; number: string;
           fontDisplay: string; fontText: string };
  facts: Record<string, { label: string; value: number; display: string }>;
  beats: Record<string, { frame: number; shows: string }>;
  safeArea: { left: number; top: number; right: number; bottom: number };
  captionZone: { top: number; bottom: number };
};
```

THIS GRAPHIC. The video is {size}, {fps} frames a second, {frames} frames long. The safe area is \
left {left}, top {top}, right {right}, bottom {bottom} (pixels). The caption area, which must \
stay empty, is from y = {caption_top} to y = {caption_bottom}. Everything you draw must stay \
inside the safe area and above the caption area. The theme background ({background_style}, \
{motion} motion) is already painted under your component as a flat colour; paint the brief's \
background style yourself if you want it.

THE RULES.
- Import only from "react", "remotion", "@remotion/shapes" and "@remotion/paths". No other \
module, no outside file, no image, no font file, no address of any kind (http:, https: or //).
- Animate only with Remotion's frame tools: `useCurrentFrame`, `interpolate` (use \
`extrapolateLeft` and `extrapolateRight: "clamp"`), `spring`, `Easing` and `Sequence`. Every \
frame must be a pure function of the current frame: no `Math.random`, no `Date`, no timers, no \
CSS transitions or animations, no state that changes over time.
- Show a number only as `facts[id].display` (derived values are in `facts` too). Never type a \
number that is on the screen as text, and never type a fact's value into the code: read it from \
`facts[id].value` when you need it to size a bar or a ring. Texts that are not numbers are yours \
to write, and must not contain a number that the line does not say.
- Time everything from `beats[id].frame`: a part should be visible in its first frame at the \
beat, or start to enter there and be complete about half a second later. Never type a frame \
number from the line. Use `beats[id].shows` to see what the beat is for. Ease the movement: a \
fade plus a short slide, a bar that grows, a line that draws.
- Use `theme` for every colour and `theme.fontDisplay` for titles and numbers and \
`theme.fontText` for other text, as `fontFamily`. Do not write a colour or font of your own. \
`positive` is good news, `negative` bad news, `accent` stresses, `number` is for a number that \
must stand out.
- Text must be large enough to read in a video (at least {min_text} px high), must not overlap \
other text, and must not be cut: write short texts and size boxes so that they fit.
- The component must not call `fetch`, `eval`, `Function(`, `import(`, `require(`, \
`XMLHttpRequest`, `WebSocket`, `EventSource`, use `localStorage`, `sessionStorage`, \
`indexedDB`, `document.cookie`, `window.open` or `navigator`, and must not contain `<iframe` \
or `<script`. Code that does is refused.
- Write exactly one `export default`. Plain TypeScript and JSX are fine; types are not checked.

USEFUL. `@remotion/shapes` has `Circle`, `Rect`, `Triangle`, `Pie`, `Star`, `Polygon` and \
`Ellipse` (SVG components). `@remotion/paths` has `evolvePath`, `getLength` and \
`getPointAtLength`, to draw a line that grows. `AbsoluteFill` is a full-size positioned box.

Design freely: choose the layout, the shapes and the motion so that the picture suits the line. \
Do not reuse a fixed template. Vary the layout from one line to the next."""


def _instructions(resolved: dict[str, Any]) -> str:
    width, height = int(resolved["width"]), int(resolved["height"])
    area, caption = resolved["safe_area"], resolved["caption_zone"]
    theme = resolved["theme"]
    values = {
        "max_chars": f"{graphics_code_checks.MAX_CODE_CHARS:,}",
        "size": f"{'landscape' if width >= height else 'portrait'}, {width} x {height}",
        "fps": str(int(resolved["fps"])),
        "frames": str(int(resolved["frames"])),
        "left": str(int(area["left"])),
        "top": str(int(area["top"])),
        "right": str(int(area["right"])),
        "bottom": str(int(area["bottom"])),
        "caption_top": str(int(caption["top"])),
        "caption_bottom": str(int(caption["bottom"])),
        "background_style": str(theme["background_style"]),
        "motion": str(theme["motion"]),
        "min_text": str(round(0.02 * height)),
    }
    text = _RULES
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def build_request(
    line: str,
    orientation: str,
    brief: dict[str, Any],
    resolved: dict[str, Any],
    *,
    model: str,
    mood: str | None = None,
) -> dict[str, Any]:
    """The exact request body of the first call. It is stored on the job. `mood` is the video's
    mood for a graphic shot (EXG-005); the lab's brief carries its own.
    """
    user = (
        f"LINE:\n{line}\n\nORIENTATION: {orientation}\n\nBRIEF:\n"
        f"{json.dumps(brief_for_model(brief, resolved, mood=mood), ensure_ascii=False, indent=1)}"
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
        "reasoning_effort": REASONING_EFFORT,
    }


def parse_code(content: str) -> str:
    """The component's code out of the model's answer: the first fenced block that has a default
    export, else the first fenced block, else the whole answer. Raises ValueError, with a message
    fit for the user, when the answer is empty.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    blocks = [match.group(1).strip("\n") for match in _FENCE.finditer(content)]
    if not blocks:
        return content.strip("\n")
    for block in blocks:
        if "export default" in block or " as default" in block:
            return block
    return blocks[0]


def repair_request(
    body: dict[str, Any], code: str, errors: list[str], *, rendered: bool = False
) -> dict[str, Any]:
    """`body` with a note added to its last user message: the code the model wrote, which passed
    the static checks, and the errors found when it was compiled and drawn in the browser, or,
    with `rendered`, when it was drawn frame by frame into the video (EXG-006). `body` is not
    changed.
    """
    listed = "\n".join(f"- {error}" for error in errors)
    where = "drawn into the video" if rendered else "compiled and drawn in the browser"
    note = (
        "\n\nNOTE: An earlier answer to this request passed the static checks, but when it was "
        f"{where} it failed:\n{listed}\n\nThe earlier code was:\n"
        f"```tsx\n{code}\n```\n\nWrite the whole component again with these errors fixed and "
        "everything else kept as it was, in one ```tsx code block."
    )
    messages = [dict(message) for message in body["messages"]]
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            message["content"] += note
            break
    return {**body, "messages": messages}
