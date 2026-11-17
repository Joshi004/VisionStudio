"""Where the camera of an evidence clip looks, and whether the quote can be read (EVD-008,
`Evidence_layer_implementation_phases.md` §4.7).

Pure functions, no I/O. The render job (`jobs/render_evidence_clip.py`), the review screen
(readability, worked out on read) and, later, the exact-length clips of EVD-009 all use this one
module, so the motion service only draws what is decided here.

**World coordinates** are the pixels of the stored screenshot (`image`): the image is the box
`[0, 0, image_w, image_h]`. The taller context image sits around it. The capture records where the
image sits inside the context as fractions (`context_box`), so the context's own box in the world is
`[-x * image_w / w, -y * image_h / h, image_w / w, image_h / h]`. The quote's rectangles are
fractions of the image, so they are `[x * image_w, y * image_h, w * image_w, h * image_h]` here.

**The camera** is a box of the world that has the output frame's shape: what is on screen. It starts
wide (the image, grown a little when the context allows it) and ends on the quote, which is put in
the middle of the **stage**: the part of the frame inside the safe area, below the source badge and
above the caption zone. So the highlight is never in the caption zone.

**Readability.** After the zoom the quote's lines have a height in output pixels. A line must be at
least `MIN_TEXT_HEIGHT_RATIO` of the frame's shorter side (38 px at 1080), or the clip carries a
warning.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Final

from app.services import graphics_resolve

Box = tuple[float, float, float, float]

# The median height of a line of the quote on the output frame, as a share of the shorter side.
MIN_TEXT_HEIGHT_RATIO: Final = 0.035
# Output pixels for one pixel of the screenshot, at most: a short quote is not blown up into a blur.
MAX_ZOOM: Final = 2.0
# How much the wide framing grows beyond the image, when the context has room for it.
START_GROW: Final = 1.25
# Room around the quote, in lines' heights, on every side.
QUOTE_PAD_LINES: Final = 0.5
MAX_RECTS: Final = 12

# The badge strip at the top of the safe area, and the gaps around the stage, as shares of the
# shorter side of the frame.
BADGE_HEIGHT_RATIO: Final = 0.075
STAGE_GAP_RATIO: Final = 0.02

# The parts of the clip, in seconds. The hold after the sweep is at least `MIN_HOLD_S`; when the
# clip is too short for all of them, the other three shrink together.
WIDE_S: Final = 0.6
ZOOM_S: Final = 1.4
SWEEP_S: Final = 1.2
MIN_HOLD_S: Final = 1.0
# The length of a preview from the review screen (EVD-008).
PREVIEW_S: Final = 6.0


@dataclass(frozen=True)
class Geometry:
    """What a capture says about the picture, in world coordinates."""

    image_w: int
    image_h: int
    # The quote's lines, one box each, in world pixels.
    rects: list[Box]
    # The context image's box in the world, or None when the capture has no context box.
    context: Box | None


@dataclass(frozen=True)
class Timeline:
    """The frames at which the camera starts and stops zooming and the highlight starts and stops
    sweeping. The clip holds on the quote from `sweep_end` to its last frame."""

    zoom_start: int
    zoom_end: int
    sweep_start: int
    sweep_end: int


@dataclass(frozen=True)
class ClipPlan:
    """Everything the motion service needs besides the images and the words."""

    width: int
    height: int
    fps: int
    frames: int
    geometry: Geometry
    start: Box
    end: Box
    # Output pixels for one world pixel at the end of the zoom.
    zoom: float
    stage: Box
    badge: Box
    timeline: Timeline
    # The part of the context image that is ever on screen and that the image does not cover, in
    # world coordinates, or None when the image alone covers every frame.
    context_crop: Box | None
    text_height_px: float
    min_text_height_px: float

    @property
    def readable(self) -> bool:
        return self.text_height_px >= self.min_text_height_px


def _finite(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _numbers(value: object, length: int) -> list[float] | None:
    if isinstance(value, list) and len(value) == length and all(_finite(n) for n in value):
        return [float(n) for n in value]
    return None


def geometry_of(capture: Any) -> Geometry | None:
    """The geometry of a stored capture (`evidence_item.capture`), or None when it has no usable
    image size or no usable rectangle. Pure.
    """
    if not isinstance(capture, dict):
        return None
    size = _numbers(capture.get("image_px"), 2)
    if size is None or size[0] < 1 or size[1] < 1:
        return None
    image_w, image_h = int(size[0]), int(size[1])
    rects: list[Box] = []
    raw = capture.get("rects")
    for entry in raw if isinstance(raw, list) else []:
        values = _numbers(entry, 4)
        if values is None:
            continue
        x, y, w, h = values
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1.0001 or y + h > 1.0001:
            continue
        rects.append((x * image_w, y * image_h, w * image_w, h * image_h))
    if not rects or len(rects) > MAX_RECTS:
        return None
    context: Box | None = None
    box = _numbers(capture.get("context_box"), 4)
    if box is not None and box[2] > 0 and box[3] > 0:
        cx, cy, cw, ch = box
        context = (-cx * image_w / cw, -cy * image_h / ch, image_w / cw, image_h / ch)
    return Geometry(image_w=image_w, image_h=image_h, rects=rects, context=context)


def safe_and_caption(width: int, height: int) -> tuple[dict[str, int], dict[str, int]]:
    """The safe area and the caption zone of a frame, as every graphic gets them."""
    return graphics_resolve.safe_area(width, height), graphics_resolve.caption_zone(width, height)


def badge_box(width: int, height: int, safe: dict[str, int]) -> Box:
    """The strip for the source badge, at the top of the safe area: `[x, y, width, height]`."""
    unit = min(width, height)
    return (
        float(safe["left"]),
        float(safe["top"]),
        float(safe["right"] - safe["left"]),
        float(round(BADGE_HEIGHT_RATIO * unit)),
    )


def stage_box(width: int, height: int, safe: dict[str, int], caption: dict[str, int]) -> Box:
    """Where the quote ends up: inside the safe area, below the badge, above the captions."""
    unit = min(width, height)
    gap = round(STAGE_GAP_RATIO * unit)
    badge = badge_box(width, height, safe)
    top = badge[1] + badge[3] + gap
    bottom = caption["top"] - gap
    return (
        float(safe["left"]),
        float(top),
        float(safe["right"] - safe["left"]),
        float(max(1.0, bottom - top)),
    )


def _union(boxes: list[Box]) -> Box:
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return (left, top, right - left, bottom - top)


def _median_line_height(rects: list[Box]) -> float:
    return float(statistics.median(rect[3] for rect in rects))


def end_camera(geometry: Geometry, width: int, height: int, stage: Box) -> tuple[Box, float]:
    """The camera at the end of the zoom and its zoom (output pixels per world pixel): the quote's
    lines, with a little room, fill the stage as far as the zoom limit allows, and its middle is
    the stage's middle. Pure.
    """
    pad = QUOTE_PAD_LINES * _median_line_height(geometry.rects)
    quote = _union(geometry.rects)
    quote_w, quote_h = quote[2] + 2 * pad, quote[3] + 2 * pad
    zoom = min(stage[2] / quote_w, stage[3] / quote_h, MAX_ZOOM)
    centre_x = quote[0] + quote[2] / 2
    centre_y = quote[1] + quote[3] / 2
    stage_cx = stage[0] + stage[2] / 2
    stage_cy = stage[1] + stage[3] / 2
    cam_w, cam_h = width / zoom, height / zoom
    return (centre_x - stage_cx / zoom, centre_y - stage_cy / zoom, cam_w, cam_h), zoom


def start_camera(geometry: Geometry, width: int, height: int, end: Box) -> Box:
    """The wide framing: the image, grown by `START_GROW` when the context has room, in the
    frame's shape, inside the context (or inside the image when there is no context). It is never
    narrower than the end camera, so the camera only ever moves in. Pure.
    """
    aspect = width / height
    bounds: Box = geometry.context or (0.0, 0.0, float(geometry.image_w), float(geometry.image_h))
    cover_w = max(float(geometry.image_w), geometry.image_h * aspect)
    cam_w = cover_w * START_GROW
    cam_h = cam_w / aspect
    shrink = min(1.0, bounds[2] / cam_w, bounds[3] / cam_h)
    cam_w, cam_h = cam_w * shrink, cam_h * shrink
    centre_x = geometry.image_w / 2
    centre_y = geometry.image_h / 2
    left = min(max(centre_x - cam_w / 2, bounds[0]), bounds[0] + bounds[2] - cam_w)
    top = min(max(centre_y - cam_h / 2, bounds[1]), bounds[1] + bounds[3] - cam_h)
    start = (left, top, cam_w, cam_h)
    return end if end[2] > start[2] else start


def timeline(frames: int, fps: int) -> Timeline:
    """The parts of a clip of `frames` frames (see the module's constants). The wide framing, the
    zoom and the sweep shrink together when the clip leaves less than `MIN_HOLD_S` of hold. Pure.
    """
    wide, zoom, sweep = WIDE_S * fps, ZOOM_S * fps, SWEEP_S * fps
    available = max(1.0, frames - MIN_HOLD_S * fps)
    scale = min(1.0, available / (wide + zoom + sweep))
    zoom_start = round(wide * scale)
    zoom_end = zoom_start + max(1, round(zoom * scale))
    sweep_start = zoom_end
    sweep_end = sweep_start + max(1, round(sweep * scale))
    return Timeline(zoom_start, zoom_end, sweep_start, min(sweep_end, frames - 1))


def plan(geometry: Geometry, width: int, height: int, fps: int, frames: int) -> ClipPlan:
    """The camera, the stage, the timeline and the readability of a clip of this size. Pure."""
    safe, caption = safe_and_caption(width, height)
    stage = stage_box(width, height, safe, caption)
    end, zoom = end_camera(geometry, width, height, stage)
    start = start_camera(geometry, width, height, end)

    crop: Box | None = None
    if geometry.context is not None:
        ctx = geometry.context
        wanted = _union([start, end])
        left, top = max(wanted[0], ctx[0]), max(wanted[1], ctx[1])
        right = min(wanted[0] + wanted[2], ctx[0] + ctx[2])
        bottom = min(wanted[1] + wanted[3], ctx[1] + ctx[3])
        inside = (0.0, 0.0, float(geometry.image_w), float(geometry.image_h))
        covered = (
            left >= inside[0] - 0.5
            and top >= inside[1] - 0.5
            and right <= inside[0] + inside[2] + 0.5
            and bottom <= inside[1] + inside[3] + 0.5
        )
        if right > left and bottom > top and not covered:
            crop = (left, top, right - left, bottom - top)

    return ClipPlan(
        width=width,
        height=height,
        fps=fps,
        frames=frames,
        geometry=geometry,
        start=start,
        end=end,
        zoom=zoom,
        stage=stage,
        badge=badge_box(width, height, safe),
        timeline=timeline(frames, fps),
        context_crop=crop,
        text_height_px=round(_median_line_height(geometry.rects) * zoom, 1),
        min_text_height_px=round(MIN_TEXT_HEIGHT_RATIO * min(width, height), 1),
    )


def readability(capture: Any, width: int, height: int) -> dict[str, Any] | None:
    """`{text_height_px, min_px, ok}` for a stored capture shown on a frame of this size, or None
    when the capture has no usable geometry. It needs no render. Pure.
    """
    geometry = geometry_of(capture)
    if geometry is None:
        return None
    safe, caption = safe_and_caption(width, height)
    stage = stage_box(width, height, safe, caption)
    _, zoom = end_camera(geometry, width, height, stage)
    text_height = round(_median_line_height(geometry.rects) * zoom, 1)
    minimum = round(MIN_TEXT_HEIGHT_RATIO * min(width, height), 1)
    return {"text_height_px": text_height, "min_px": minimum, "ok": text_height >= minimum}


def context_crop_pixels(
    crop: Box, context: Box, context_size: tuple[int, int]
) -> tuple[int, int, int, int]:
    """The pixels of the context image (`left, top, right, bottom`) that a crop box of the world
    covers, rounded outwards and kept inside the image. Pure.
    """
    scale_x = context_size[0] / context[2]
    scale_y = context_size[1] / context[3]
    left = max(0, math.floor((crop[0] - context[0]) * scale_x))
    top = max(0, math.floor((crop[1] - context[1]) * scale_y))
    right = min(context_size[0], math.ceil((crop[0] + crop[2] - context[0]) * scale_x))
    bottom = min(context_size[1], math.ceil((crop[1] + crop[3] - context[1]) * scale_y))
    return left, top, max(right, left + 1), max(bottom, top + 1)


def world_box_of_pixels(
    pixels: tuple[int, int, int, int], context: Box, context_size: tuple[int, int]
) -> Box:
    """The world box that a pixel box of the context image covers: the inverse of
    `context_crop_pixels`, so the crop is drawn exactly where it was cut from. Pure.
    """
    unit_x = context[2] / context_size[0]
    unit_y = context[3] / context_size[1]
    return (
        context[0] + pixels[0] * unit_x,
        context[1] + pixels[1] * unit_y,
        (pixels[2] - pixels[0]) * unit_x,
        (pixels[3] - pixels[1]) * unit_y,
    )
