"""What every render of the Graphics lab shares (GFX-005): how a video is encoded, how long a render
may take, which composition draws which engine, the test card, and the checks of a finished file.

Pure functions and constants, no I/O. `jobs/render_lab_graphic.py` runs the render and
`services/graphics_lab.py` makes the jobs. This module imports neither, so both can import it.

**Encoding.** Every engine's video is H.264 (`libx264`), CRF 18, preset `medium`, `yuv420p`, with
BT.709 colour tags and no audio from the renderer. These are the settings of the explainer render
(`jobs/render_story.VIDEO_SETTINGS`) and of the Audio video lab (`av_lab_render.VIDEO_CRF`), so a
graphic looks the same next to them. The motion service takes them in the request, and the Python
renderer (GFX-008) must use the same `ENCODING`, so the engines are compared on equal terms (G-4).

**The Python renderer hook.** `python_renderer` is an async function `(body, dest)` that draws the
render described by `body` (the same dictionary the motion service gets: `engine`, `width`,
`height`, `fps`, `frames`, `resolved`, `input`, `encoding`) into the new file `dest`, as an H.264
MP4 with no audio, and raises `PythonRenderFailed` when it cannot. GFX-008's
`services/graphics_python.render` is set by `jobs/render_lab_graphic.py`, the hook's only reader
(this module cannot import it: the renderer imports this one). The job then checks the file and
adds the voice exactly as for a Remotion render.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final

from app.services import graphics_resolve, projects
from app.services.ffmpeg import VideoProbe

REQUESTED_RENDER: Final = "lab_graphic_render"
REQUESTED_TEST_CARD: Final = "lab_graphic_test_card"
# Two presses on one render make one job (`dedupe_key`), and so do two on the test card.
RENDER_DEDUPE_KEY: Final = "render_id"
TEST_CARD_DEDUPE_KEY: Final = "requested"

ENCODING: Final[dict[str, Any]] = {
    "codec": "h264",
    "crf": 18,
    "preset": "medium",
    "pixel_format": "yuv420p",
    "color_space": "bt709",
}

# How long the motion service may spend on one render before it stops it. The backend waits this
# long plus a minute, then gives up on the service.
RENDER_TIME_LIMIT_S: Final = 300
BACKEND_EXTRA_WAIT_S: Final = 60

# The engine key the motion service uses for the test card, and for each engine the composition of
# `motion/src/Root.tsx` that draws it.
TEST_CARD_ENGINE: Final = "test_card"
COMPOSITION_OF: Final[dict[str, str]] = {
    TEST_CARD_ENGINE: "TestCard",
    "remotion_templates": "Templates",
    "remotion_blocks": "Blocks",
    "generated_component": "Generated",
}
# The engine that is drawn in the backend, not in the motion service.
PYTHON_ENGINE: Final = "python_templates"

# The test card's length: as short as a real graphic can be (3 s) up to as long (15 s).
TEST_CARD_MIN_FRAMES: Final = graphics_resolve.MIN_FRAMES
TEST_CARD_MAX_FRAMES: Final = graphics_resolve.MAX_FRAMES
TEST_CARD_DEFAULT_FRAMES: Final = 101


class PythonRenderFailed(Exception):
    """The Python renderer could not draw the video. The message is for the owner."""


PythonRenderFn = Callable[[dict[str, Any], Path], Awaitable[None]]
python_renderer: PythonRenderFn | None = None


def render_body(
    engine: str,
    *,
    width: int,
    height: int,
    fps: int,
    frames: int,
    resolved: dict[str, Any],
    input: Any,
    code: str | None,
) -> dict[str, Any]:
    """The request every renderer gets: the motion service's `POST /renders` body."""
    return {
        "engine": engine,
        "width": width,
        "height": height,
        "fps": fps,
        "frames": frames,
        "resolved": resolved,
        "input": input,
        "code": code,
        "encoding": dict(ENCODING),
        "time_limit_s": RENDER_TIME_LIMIT_S,
    }


def code_of(input: Any) -> str | None:
    """The component code of a `generated_component` render's input (`{"code": "..."}`, GFX-010),
    or None. The other engines have no code.
    """
    if isinstance(input, dict) and isinstance(input.get("code"), str):
        return input["code"]
    return None


def card_size(orientation: str) -> tuple[int, int]:
    """The width and height of a test card of this orientation, as of every graphic."""
    sizes = projects.ORIENTATION_DEFAULTS[orientation]
    return sizes.out_width, sizes.out_height


def card_resolved(
    width: int, height: int, fps: int, frames: int, fonts: dict[str, str]
) -> dict[str, Any]:
    """The resolved brief the test card is drawn from: the dark palette and the zones every
    graphic gets (§4.4), and no facts, derived values or beats.
    """
    theme, _notes = graphics_resolve.theme_for(
        {
            "palette": "dark",
            "accent": graphics_resolve.COLOURS["dark"]["accent"],
            "background": "solid",
            "motion": "snappy",
        }
    )
    return {
        "width": width,
        "height": height,
        "fps": fps,
        "frames": frames,
        "timing_source": "none",
        "facts": {},
        "derived": {},
        "beats": {},
        "theme": theme,
        "fonts": dict(fonts),
        "safe_area": graphics_resolve.safe_area(width, height),
        "caption_zone": graphics_resolve.caption_zone(width, height),
        "notes": [],
    }


def input_warnings(input: Any) -> list[str]:
    """The warnings an engine's saved input carries into its render (GFX-009): the layout problems
    of a block scene, or that its layout was not checked. Other engines' inputs have none.
    """
    layout = input.get("layout") if isinstance(input, dict) else None
    if not isinstance(layout, dict):
        return []
    if layout.get("checked") is False:
        return [f"The layout was not checked: {layout.get('reason') or 'no reason given'}"]
    problems = layout.get("problems")
    return [str(problem) for problem in problems] if isinstance(problems, list) else []


def component_warnings(input: Any) -> list[str]:
    """The warnings a generated component's saved input carries into its render (GFX-010): that
    it was not checked in the browser, and the numbers that are not traced to a fact (a fact's
    value typed in the code, a number on screen that the line does not say). Other engines'
    inputs have none.
    """
    checks = input.get("checks") if isinstance(input, dict) else None
    if not isinstance(checks, dict):
        return []
    warnings: list[str] = []
    if checks.get("checked") is False:
        warnings.append(
            f"The component was not checked: {checks.get('reason') or 'no reason given'}"
        )
    listed = input.get("warnings")
    if isinstance(listed, list):
        warnings.extend(str(warning) for warning in listed)
    return warnings


def frame_difference(first: list[str], second: list[str]) -> dict[str, int]:
    """How two videos' frame hashes (`ffmpeg.frame_md5s`) differ (§4.7): `frames` is the length of
    the longer list and `differing` the number of positions where the hashes are not equal or one
    video has no frame. Equal lists give `differing` 0, which the card shows as "identical".
    """
    frames = max(len(first), len(second))
    differing = sum(
        1
        for index in range(frames)
        if index >= len(first) or index >= len(second) or first[index] != second[index]
    )
    return {"frames": frames, "differing": differing}


def check_probe(
    probe: VideoProbe, *, width: int, height: int, fps: int, frames: int
) -> tuple[dict[str, bool], list[str]]:
    """Compares a rendered file with what was asked for (§4.7): the exact frame count, the size,
    the frame rate, the codec and the pixel format. Returns whether each check passed, and a
    sentence for each one that did not.
    """
    checks = {
        "frames": probe.frame_count == frames,
        "size": probe.width == width and probe.height == height,
        "fps": probe.fps is not None and abs(probe.fps - fps) <= 0.001,
        "codec": probe.codec_name == ENCODING["codec"],
        "pix_fmt": probe.pix_fmt == ENCODING["pixel_format"],
    }
    warnings: list[str] = []
    if not checks["frames"]:
        warnings.append(f"The video has {probe.frame_count} frames; it should have {frames}.")
    if not checks["size"]:
        warnings.append(
            f"The video is {probe.width} x {probe.height}; it should be {width} x {height}."
        )
    if not checks["fps"]:
        warnings.append(f"The video is {probe.fps} frames a second; it should be {fps}.")
    if not checks["codec"]:
        warnings.append(f"The video's codec is {probe.codec_name}; it should be h264.")
    if not checks["pix_fmt"]:
        warnings.append(f"The video's pixel format is {probe.pix_fmt}; it should be yuv420p.")
    return checks, warnings
