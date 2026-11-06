"""The component call of a motion callout: the instructions to the model and the request (CMO-003,
`Callouts_motion_implementation_phases.md` §4.4.1).

Pure functions, no I/O.

It is `graphics_component_writer` for a callout. One call reads the resolved callout (its kind,
its parts, the zones it is drawn in, its length, the video's colours and the callout look) and
writes one Remotion component as TSX. The differences from a graphic shot's component:

- the canvas is transparent and is the size of the callout's zone, so nothing may paint the whole
  canvas and everything is laid out from the props' `width` and `height`;
- the model never writes a word: it shows the text of each part exactly as given;
- every part appears at its own frame, and nothing starts at or after `exitFrame` (the
  composition fades the whole callout out from there).

The answer is code in one fenced block, read by `graphics_component_writer.parse_code`, checked by
`graphics_code_checks.check_code` (with this module's `MAX_CODE_CHARS`) and then in the browser
(`callout_component_checks`). A repair asks once more with the code and the errors
(`graphics_component_writer.repair_request`).
"""

from __future__ import annotations

import json
from typing import Any, Final

# A callout's component is smaller than a graphic shot's (40,000 characters).
MAX_CODE_CHARS: Final = 16_000
# The cap only bounds the call (tokens are paid as used).
MAX_TOKENS: Final = 32_000
REASONING_EFFORT: Final = "high"

_RULES: Final = """\
You are writing one small animated callout as a Remotion (React) component. A callout is a short \
piece of text (a key phrase, a number, a question, a comparison, a list or a section title) that \
appears over a video of a presenter at the moment the script says it. You are given the kind of \
callout, the exact texts to show (its parts), the colours of the video, the look every callout of \
the video shares, and the line of the script it appears in. Your component is drawn frame by \
frame into a transparent video that is laid over the picture, so make a callout that reads at a \
glance and belongs to the look.

YOUR ANSWER is one TSX file in one ```tsx code block, and nothing else of value outside it. Its \
default export is the component. It is at most {max_chars} characters.

THE PROPS. The component receives these props (the values are filled in when it is drawn):

```ts
type CalloutProps = {
  // The whole canvas in pixels, and the callout's length.
  width: number; height: number; fps: number; durationInFrames: number;
  // The height of the output video, for text size rules.
  frameHeight: number;
  kind: "emphasis" | "number" | "question" | "comparison" | "list" | "section_title";
  // Where the canvas is: beside the presenter, over B-roll, in portrait, or a centred title.
  placement: "presenter" | "broll" | "portrait" | "title";
  // One entry per text of the callout, in order: the text of an emphasis, number, question or
  // section title, each item of a list, each side of a comparison.
  parts: { id: string; text: string; role: string; colour: string; frame: number }[];
  theme: { surface: string; text: string; muted: string; accent: string; positive: string;
           negative: string; number: string; fontDisplay: string; fontText: string };
  look: Record<string, string>;
  // From this frame on the whole callout fades out. Nothing new may start at or after it.
  exitFrame: number;
};
```

THIS CALLOUT. It is a {kind}. The video is {fps} frames a second and the callout is {frames} \
frames long; it fades out from frame {exit_frame} by itself. The output video is {frame_height} \
pixels high. It is drawn on a canvas of one of these sizes (read the props, never type a size):
{zones}

THE RULES.
- The canvas is TRANSPARENT: the video under the callout must stay visible. Do not paint the \
whole canvas, and do not paint a background. Panels, shapes and text only, covering well under \
half of the canvas. There is no `theme.background`.
- Show each `parts[i].text` exactly as given, in full, with real spaces between the words, and \
no other words or numbers: do not rewrite, shorten, translate or add a label, a title or a \
caption, and do not type text out letter by letter. An icon or a plain shape is allowed. Never \
type a number that one of the texts shows.
- Time everything from the props: part `i` appears at `parts[i].frame` (visible in that frame, \
or starts to enter there and is complete about 0.4 seconds later). Never type a frame number. \
Nothing may start at or after `exitFrame`; every part must be fully visible before it.
- Lay everything out from `width` and `height`: the same code is drawn on canvases of different \
sizes. Size text from `frameHeight` (never smaller than {min_text} px high) and shrink it, or \
break it over lines, so that every text fits inside the canvas, is not cut by an edge or by \
`overflow`, and does not overlap another text. Keep a margin around everything.
- Follow `look`: `panel` (none: text alone, card: a solid box in `theme.surface`, glass: a \
translucent box, underline: a line under the text, ribbon: a band behind the text), `corners` \
(sharp, soft or round), `entrance` (fade_up, wipe, pop or draw), `emphasis` (how a number or a \
key word stands out) and `density`. `look.notes` says what makes the callouts belong together.
- Use `parts[i].colour` for the colour of each text and `theme` for every other colour, with \
`theme.fontDisplay` for titles and numbers and `theme.fontText` for other text, as `fontFamily`. \
Do not write a colour or a font of your own. Text over video needs a panel or a soft shadow to \
stay readable.
- Import only from "react", "remotion", "@remotion/shapes" and "@remotion/paths". No other \
module, no outside file, no image, no font file, no address of any kind (http:, https: or //).
- Animate only with Remotion's frame tools: `useCurrentFrame`, `interpolate` (use \
`extrapolateLeft` and `extrapolateRight: "clamp"`), `spring`, `Easing` and `Sequence`. Every \
frame must be a pure function of the current frame: no `Math.random`, no `Date`, no timers, no \
CSS transitions or animations, no state that changes over time.
- The component must not call `fetch`, `eval`, `Function(`, `import(`, `require(`, \
`XMLHttpRequest`, `WebSocket`, `EventSource`, use `localStorage`, `sessionStorage`, \
`indexedDB`, `document.cookie`, `window.open` or `navigator`, and must not contain `<iframe` \
or `<script`. Code that does is refused.
- Write exactly one `export default`. Plain TypeScript and JSX are fine; types are not checked.

USEFUL. `@remotion/shapes` has `Circle`, `Rect`, `Triangle`, `Pie`, `Star`, `Polygon` and \
`Ellipse` (SVG components). `@remotion/paths` has `evolvePath`, `getLength` and \
`getPointAtLength`, to draw a line that grows.

Keep it simple and quiet: a callout is a small accent over a video, not a scene."""


def _instructions(resolved: dict[str, Any]) -> str:
    zones = "\n".join(
        f"- {zone['placement']}: {zone['width']} x {zone['height']} pixels"
        for zone in resolved["zones"]
    )
    values = {
        "max_chars": f"{MAX_CODE_CHARS:,}",
        "kind": str(resolved["kind"]).replace("_", " "),
        "fps": str(int(resolved["fps"])),
        "frames": str(int(resolved["frames"])),
        "exit_frame": str(int(resolved["exit_frame"])),
        "frame_height": str(int(resolved["frame_height"])),
        "zones": zones,
        "min_text": str(round(0.02 * int(resolved["frame_height"]))),
    }
    text = _RULES
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def brief_for_model(resolved: dict[str, Any], line: str, mood: str) -> dict[str, Any]:
    """What the user message tells the model: the callout as the props will hold it (the sizes
    and the frames are in the instructions and the props), the line it appears in and the mood of
    the video.
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
        "reasoning_effort": REASONING_EFFORT,
    }
