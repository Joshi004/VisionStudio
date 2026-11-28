"""Where the picture of a still footage clip goes, and where its camera looks (FTG-005,
`Footage_broll_implementation_phases.md` §4.10).

Pure functions, no I/O. The render job (`jobs/render_footage_clip.py`) uses this one module, so the
motion service's `Footage` composition only draws what is decided here. Three modes:

- **image**: a photo. A photo with the frame's shape fills it; any other shape is fitted over a
  blurred, darkened copy of itself (as a video is). A portrait frame may instead be filled by a
  crop from the left, the centre or the right (the owner's choice). A slow zoom of
  `IMAGE_ZOOM_END` over the whole clip. All boxes are `[x, y, width, height]` in output pixels
  at the start of the clip.
- **page**: a web page in a browser window (a title bar with the address, and the page below it).
  The page is a tall image from the top of the page. The camera starts on the top, then scrolls and
  zooms to the focus, where the highlight sweeps over the focus words. With no focus the camera
  scrolls slowly down the page. **World coordinates** are the pixels of the stored page image.
- **pdf**: one page of a PDF, whole, on the plain background; the camera zooms to the focus and the
  highlight sweeps over it. With no focus it zooms in a little. World coordinates again are the
  pixels of the stored page image.

A camera is a box of the world that has the shape of the **view**, the part of the frame the world
is drawn in: the window's page area for a page, the whole frame for a PDF.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlparse

from app.services import evidence_clip_layout, soundbite_render

Box = tuple[float, float, float, float]

MODE_IMAGE: Final = "image"
MODE_PAGE: Final = "page"
MODE_PDF: Final = "pdf"

# A photo drifts in by this much over the clip, about the middle of the frame.
IMAGE_ZOOM_END: Final = 1.05
# The blurred copy behind a fitted photo is drawn this much larger than a cover, so the blur has no
# soft edge inside the frame.
BACKDROP_GROW: Final = 1.1
# A PDF with no focus zooms in by this much.
PDF_IDLE_ZOOM: Final = 1.08
# The page is never shown larger than this many times the width of its first screen, however short
# the focus is (a short quote is not blown up into a blur).
PAGE_MAX_ZOOM: Final = 3.0
# A page with no focus scrolls down by this many screens, or to the end of the page.
PAGE_IDLE_SCROLL_SCREENS: Final = 0.8
# The title bar of the browser window and its corners, as shares of the frame's shorter side.
WINDOW_BAR_RATIO: Final = 0.055
WINDOW_RADIUS_RATIO: Final = 0.012
ADDRESS_MAX_CHARS: Final = 70
# What a page's first screen looks like when the capture does not say.
LANDSCAPE_VIEWPORT: Final = (1280.0, 720.0)
PORTRAIT_VIEWPORT: Final = (360.0, 640.0)
MAX_RECTS: Final = evidence_clip_layout.MAX_RECTS


@dataclass(frozen=True)
class Timeline:
    """Frames of the camera's move and the highlight. `sweep_*` are None with no focus. With no
    focus the camera moves over the whole clip."""

    zoom_start: int
    zoom_end: int
    sweep_start: int | None
    sweep_end: int | None


@dataclass(frozen=True)
class Window:
    """The browser window of a page: its box on the frame, the height of its title bar, its
    corner radius and the address shown in the bar."""

    box: tuple[int, int, int, int]
    bar_height: int
    radius: int
    address: str


@dataclass(frozen=True)
class ImageLook:
    """How a photo sits on the frame: the picture, the blurred copy behind it (or None when the
    picture fills the frame) and the zoom at the last frame."""

    picture: Box
    backdrop: Box | None
    zoom_end: float


@dataclass(frozen=True)
class StillPlan:
    mode: str
    width: int
    height: int
    fps: int
    frames: int
    image_px: tuple[int, int]
    # Only for an image.
    image: ImageLook | None
    # Only for a page or a PDF: the part of the frame the world is drawn in, the cameras, the focus
    # lines in the world and the moves.
    view: Box | None
    start: Box | None
    end: Box | None
    rects: tuple[Box, ...]
    timeline: Timeline | None
    window: Window | None

    @property
    def max_density(self) -> float:
        """The most output pixels that one pixel of the stored image ever covers. The picture sent
        to the motion service need not have more pixels than this gives."""
        if self.mode == MODE_IMAGE and self.image is not None:
            return self.image.picture[2] / self.image_px[0] * self.image.zoom_end
        assert self.view is not None and self.start is not None and self.end is not None
        return max(self.view[2] / self.start[2], self.view[2] / self.end[2])


def _even(value: float) -> int:
    return max(2, round(value / 2) * 2)


def _finite(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _pair(value: object) -> tuple[float, float] | None:
    if (
        isinstance(value, list | tuple)
        and len(value) == 2
        and all(_finite(n) and n > 0 for n in value)
    ):
        return float(value[0]), float(value[1])
    return None


def image_size(capture: Any) -> tuple[int, int] | None:
    """The stored picture's size from `capture.image_px`, or None when it has none."""
    size = _pair(capture.get("image_px")) if isinstance(capture, dict) else None
    if size is None or size[0] < 2 or size[1] < 2:
        return None
    return int(size[0]), int(size[1])


def focus_rects(capture: Any, image_w: int, image_h: int) -> list[Box]:
    """The focus lines of a page or PDF (`capture.focus_rects`, fractions of the image) in world
    pixels. A rectangle that is not inside the image is left out; at most `MAX_RECTS` are read."""
    raw = capture.get("focus_rects") if isinstance(capture, dict) else None
    found: list[Box] = []
    for entry in raw if isinstance(raw, list) else []:
        if not (isinstance(entry, list) and len(entry) == 4 and all(_finite(n) for n in entry)):
            continue
        x, y, w, h = (float(n) for n in entry)
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1.0001 or y + h > 1.0001:
            continue
        found.append((x * image_w, y * image_h, w * image_w, h * image_h))
    return found[:MAX_RECTS]


def viewport_of(capture: Any, frame: tuple[int, int]) -> tuple[float, float]:
    """The size of a page's first screen: `capture.viewport` as `[width, height]` when it has one,
    otherwise the evidence viewport of the frame's orientation."""
    given = _pair(capture.get("viewport")) if isinstance(capture, dict) else None
    if given is not None:
        return given
    return PORTRAIT_VIEWPORT if frame[1] > frame[0] else LANDSCAPE_VIEWPORT


def address_of(source: Any) -> str:
    """The page's address for the browser bar: the host and the path, without the scheme, cut to
    `ADDRESS_MAX_CHARS`. Empty when the source has no usable address."""
    if not isinstance(source, dict):
        return ""
    for key in ("final_url", "url"):
        value = source.get(key)
        if not isinstance(value, str):
            continue
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            continue
        text = parsed.hostname.removeprefix("www.") + parsed.path.rstrip("/")
        text = "".join(char for char in text if char.isprintable())
        if len(text) > ADDRESS_MAX_CHARS:
            text = text[: ADDRESS_MAX_CHARS - 1].rstrip() + "…"
        return text
    return ""


# --- Image -----------------------------------------------------------------------------------


def image_look(image_px: tuple[int, int], frame: tuple[int, int], crop: str | None) -> ImageLook:
    """The photo's boxes at the first frame. `crop` (`left`, `centre`, `right`) fills a portrait
    frame; it is ignored for a landscape one."""
    image_w, image_h = image_px
    width, height = frame
    cover = max(width / image_w, height / image_h)
    cover_w, cover_h = image_w * cover, image_h * cover
    centre_y = (height - cover_h) / 2
    if crop is not None and height > width:
        left = {"left": 0.0, "centre": (width - cover_w) / 2, "right": width - cover_w}[crop]
        return ImageLook((left, centre_y, cover_w, cover_h), None, IMAGE_ZOOM_END)
    same_shape = (
        abs((image_w / image_h) / (width / height) - 1) <= soundbite_render.ASPECT_TOLERANCE
    )
    if same_shape:
        return ImageLook(((width - cover_w) / 2, centre_y, cover_w, cover_h), None, IMAGE_ZOOM_END)
    fit = min(width / image_w, height / image_h)
    fit_w, fit_h = image_w * fit, image_h * fit
    grown_w, grown_h = cover_w * BACKDROP_GROW, cover_h * BACKDROP_GROW
    return ImageLook(
        picture=((width - fit_w) / 2, (height - fit_h) / 2, fit_w, fit_h),
        backdrop=((width - grown_w) / 2, (height - grown_h) / 2, grown_w, grown_h),
        zoom_end=IMAGE_ZOOM_END,
    )


# --- Camera modes ----------------------------------------------------------------------------


def _stage(frame: tuple[int, int]) -> Box:
    """The part of the frame a page or PDF may use: inside the safe area, above the captions."""
    width, height = frame
    safe, caption = evidence_clip_layout.safe_and_caption(width, height)
    gap = round(evidence_clip_layout.STAGE_GAP_RATIO * min(width, height))
    top = float(safe["top"])
    return (
        float(safe["left"]),
        top,
        float(safe["right"] - safe["left"]),
        float(max(2.0, caption["top"] - gap - top)),
    )


def _timeline(frames: int, fps: int, focused: bool) -> Timeline:
    if not focused:
        return Timeline(0, max(1, frames - 1), None, None)
    parts = evidence_clip_layout.timeline(frames, fps)
    return Timeline(parts.zoom_start, parts.zoom_end, parts.sweep_start, parts.sweep_end)


def _union(boxes: list[Box]) -> Box:
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return (left, top, right - left, bottom - top)


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), max(low, high))


def _page_window(frame: tuple[int, int], aspect: float, address: str) -> Window:
    width, height = frame
    unit = min(width, height)
    stage = _stage(frame)
    bar = _even(WINDOW_BAR_RATIO * unit)
    content_w = min(stage[2], max(2.0, stage[3] - bar) * aspect)
    content_w = min(_even(content_w), width // 2 * 2)
    content_h = _even(content_w / aspect)
    window_w, window_h = content_w, content_h + bar
    x = round(stage[0] + (stage[2] - window_w) / 2)
    y = round(stage[1] + (stage[3] - window_h) / 2)
    return Window(
        box=(max(0, x), max(0, y), window_w, window_h),
        bar_height=bar,
        radius=round(WINDOW_RADIUS_RATIO * unit),
        address=address,
    )


def page_plan(
    image_px: tuple[int, int],
    viewport: tuple[float, float],
    frame: tuple[int, int],
    rects: list[Box],
    *,
    fps: int,
    frames: int,
    address: str,
) -> StillPlan:
    """A web page in a browser window: the window, the cameras and the moves."""
    image_w, image_h = image_px
    window = _page_window(frame, viewport[0] / viewport[1], address)
    view: Box = (
        float(window.box[0]),
        float(window.box[1] + window.bar_height),
        float(window.box[2]),
        float(window.box[3] - window.bar_height),
    )
    aspect = view[2] / view[3]
    start: Box = (0.0, 0.0, float(image_w), image_w / aspect)
    if rects:
        pad = evidence_clip_layout.QUOTE_PAD_LINES * float(statistics.median(r[3] for r in rects))
        quote = _union(rects)
        wanted_w = max(quote[2] + 2 * pad, (quote[3] + 2 * pad) * aspect)
        cam_w = max(wanted_w, view[2] / evidence_clip_layout.MAX_ZOOM, image_w / PAGE_MAX_ZOOM)
        cam_w = min(cam_w, float(image_w))
        cam_h = cam_w / aspect
        centre_x, centre_y = quote[0] + quote[2] / 2, quote[1] + quote[3] / 2
        end: Box = (
            _clamp(centre_x - cam_w / 2, 0.0, image_w - cam_w),
            _clamp(centre_y - cam_h / 2, 0.0, image_h - cam_h),
            cam_w,
            cam_h,
        )
    else:
        scroll = min(start[3] * PAGE_IDLE_SCROLL_SCREENS, max(0.0, image_h - start[3]))
        end = (0.0, scroll, start[2], start[3])
    return StillPlan(
        mode=MODE_PAGE,
        width=frame[0],
        height=frame[1],
        fps=fps,
        frames=frames,
        image_px=image_px,
        image=None,
        view=view,
        start=start,
        end=end,
        rects=tuple(rects),
        timeline=_timeline(frames, fps, bool(rects)),
        window=window,
    )


def pdf_plan(
    image_px: tuple[int, int],
    frame: tuple[int, int],
    rects: list[Box],
    *,
    fps: int,
    frames: int,
) -> StillPlan:
    """One page of a PDF, whole on the stage, with a zoom to the focus."""
    image_w, image_h = image_px
    width, height = frame
    stage = _stage(frame)
    stage_cx, stage_cy = stage[0] + stage[2] / 2, stage[1] + stage[3] / 2
    zoom0 = min(stage[2] / image_w, stage[3] / image_h)

    def camera(zoom: float, centre_x: float, centre_y: float) -> Box:
        return (centre_x - stage_cx / zoom, centre_y - stage_cy / zoom, width / zoom, height / zoom)

    start = camera(zoom0, image_w / 2, image_h / 2)
    if rects:
        geometry = evidence_clip_layout.Geometry(image_w, image_h, list(rects), None)
        end, zoom = evidence_clip_layout.end_camera(geometry, width, height, stage)
        if zoom <= zoom0:
            end = start
    else:
        end = camera(zoom0 * PDF_IDLE_ZOOM, image_w / 2, image_h / 2)
    return StillPlan(
        mode=MODE_PDF,
        width=width,
        height=height,
        fps=fps,
        frames=frames,
        image_px=image_px,
        image=None,
        view=(0.0, 0.0, float(width), float(height)),
        start=start,
        end=end,
        rects=tuple(rects),
        timeline=_timeline(frames, fps, bool(rects)),
        window=None,
    )


def image_plan(
    image_px: tuple[int, int],
    frame: tuple[int, int],
    crop: str | None,
    *,
    fps: int,
    frames: int,
) -> StillPlan:
    return StillPlan(
        mode=MODE_IMAGE,
        width=frame[0],
        height=frame[1],
        fps=fps,
        frames=frames,
        image_px=image_px,
        image=image_look(image_px, frame, crop),
        view=None,
        start=None,
        end=None,
        rects=(),
        timeline=None,
        window=None,
    )


def _list(box: Box) -> list[float]:
    return [round(value, 3) for value in box]


def resolved_for(
    plan: StillPlan,
    *,
    accent: str,
    background: str,
    fonts: dict[str, str],
    frame_size: tuple[int, int],
) -> dict[str, Any]:
    """The `resolved` of the motion service's `Footage` composition. Pure."""
    safe, caption = evidence_clip_layout.safe_and_caption(*frame_size)
    resolved: dict[str, Any] = {
        "mode": plan.mode,
        "accent": accent,
        "background": background,
        "fonts": dict(fonts),
        "safe_area": safe,
        "caption_zone": caption,
        "image_px": list(plan.image_px),
        "blur_sigma": soundbite_render.BLUR_SIGMA,
        "darken": round(1 + soundbite_render.BACKGROUND_BRIGHTNESS, 3),
    }
    if plan.mode == MODE_IMAGE and plan.image is not None:
        resolved["image"] = {
            "picture": _list(plan.image.picture),
            "backdrop": _list(plan.image.backdrop) if plan.image.backdrop is not None else None,
            "zoom_end": plan.image.zoom_end,
        }
        return resolved
    assert plan.view is not None and plan.start is not None and plan.end is not None
    assert plan.timeline is not None
    resolved["view"] = _list(plan.view)
    resolved["start"] = _list(plan.start)
    resolved["end"] = _list(plan.end)
    resolved["rects"] = [_list(rect) for rect in plan.rects]
    resolved["timeline"] = {
        "zoom_start": plan.timeline.zoom_start,
        "zoom_end": plan.timeline.zoom_end,
        "sweep_start": plan.timeline.sweep_start,
        "sweep_end": plan.timeline.sweep_end,
    }
    if plan.window is not None:
        resolved["window"] = {
            "box": list(plan.window.box),
            "bar_height": plan.window.bar_height,
            "radius": plan.window.radius,
            "address": plan.window.address,
        }
    return resolved
