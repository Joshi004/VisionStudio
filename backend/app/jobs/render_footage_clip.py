"""The `render_footage_clip` job: the video of one piece of footage at its exact length (FTG-005,
`Footage_broll_implementation_phases.md` §4.10).

The input is `{footage_clip_id, preview_item_id}` for a preview and `{footage_clip_id, piece_ref}`
for a placed piece. The `footage_clip` row says what is drawn: the piece (`item_id`) and, in
`inputs`, the size, frame rate and length, the portrait crop, the part of a video to use and the
highlight's colour. Every clip is an H.264 `yuv420p` MP4 of exactly `frames` frames, with **no
audio stream**.

- **A video** is cut by FFmpeg from the stored, muted copy. `services/footage_cut.py` chooses the
  start by the cut rules (no cut in the first or last 0.5 s, the agent's moment in the middle),
  `services/footage_video.py` fits it to the frame.
- **An image, a page or a PDF** is drawn by the motion service's `Footage` composition. The layout
  (`services/footage_clip_layout.py`) decides every box and camera; the picture goes in the
  request as base64 to `/evidence-renders` (the large-body route), shrunk to what the clip's
  largest zoom can show, and sent as JPEG when its PNG would be too large.

`ffprobe` then checks the file: the exact frame count, the size, the frame rate, H.264, `yuv420p`
and no audio. Any difference fails the job and the file is not kept.

A local job: nothing is paid for and no model is asked. A restart makes the clip again from the
start. Stored files are never deleted here. Logs hold the job id, never the words.
"""

from __future__ import annotations

import base64
import io
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import anyio.to_thread
from PIL import Image, ImageOps
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import FootageClip, FootageItem
from app.db.session import SessionLocal
from app.jobs import motion_draw, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.jobs.render_story import TRIM_TIMEOUT_S, RenderFailed, run_ffmpeg
from app.providers import motion_renderer
from app.services import (
    caption_plan,
    evidence_clips,
    ffmpeg,
    footage_clip_layout,
    footage_clips,
    footage_cut,
    footage_video,
    graphics_lab,
    graphics_render,
)
from app.services.storage import Storage, StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = footage_clips.JOB_TYPE
ENGINE: Final = "footage_clip"
# The composition of `motion/src/Root.tsx` that draws it.
COMPOSITION: Final = "Footage"

# One picture of a request, as base64, at most: the motion service refuses more than 28 MiB for
# an image, and the whole body may not pass 32 MiB.
MAX_PICTURE_BASE64_BYTES: Final = 28 * 1024 * 1024
JPEG_QUALITY: Final = 90
_EXIF_ORIENTATION: Final = 0x0112
_PICTURE_MIMES: Final = {"PNG": "image/png", "JPEG": "image/jpeg"}


class VideoMismatch(RenderFailed):
    """The drawn file is not the clip that was asked for. `metrics` says what it is."""

    def __init__(self, message: str, metrics: dict[str, Any]) -> None:
        super().__init__(message)
        self.metrics = metrics


@dataclass
class _Plan:
    """What one job draws: the clip's size and length, the piece and what the clip is made with."""

    clip_id: int
    project_id: int
    kind: str
    width: int
    height: int
    fps: int
    frames: int
    framing: str | None
    accent: str
    # Where a video's part to use starts and ends, and the agent's moment in it (seconds of the
    # stored video), as the look recorded them.
    use: tuple[float, float] | None
    moment_s: float | None
    media_path: str
    cuts: list[float]
    capture: Any
    source: Any


class RenderFootageClipHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return await settings_service.get_int(session, settings_service.GRAPHICS_MAX_RENDERS_KEY)

    async def start(self, job_id: int) -> None:
        storage = get_storage()
        temp_paths: list[Path] = []
        clip_id: int | None = None
        try:
            async with SessionLocal() as session:
                job = await store.get_job(session, job_id)
                await session.commit()
            if job is None or job.status != "running":
                return
            recorded = job.input if isinstance(job.input, dict) else {}
            value = recorded.get(footage_clips.CLIP_KEY)
            clip_id = value if isinstance(value, int) and not isinstance(value, bool) else None
            if clip_id is None:
                raise RenderFailed("The job names no footage clip.")
            await self._render(job_id, clip_id, storage, temp_paths)
        except VideoMismatch as exc:
            await _fail(job_id, clip_id, str(exc), metrics=exc.metrics)
        except (
            RenderFailed,
            motion_draw.MotionRenderFailed,
            motion_renderer.MotionServiceError,
        ) as exc:
            await _fail(job_id, clip_id, str(exc))
        except StorageError as exc:
            await _fail(job_id, clip_id, f"A file could not be stored: {exc}")
        finally:
            for path in temp_paths:
                storage.discard(path)

    async def _render(
        self, job_id: int, clip_id: int, storage: Storage, temp_paths: list[Path]
    ) -> None:
        started = time.monotonic()
        plan = await _plan(clip_id)
        video = storage.new_temp_path("mp4")
        temp_paths.append(video)
        if plan.kind == footage_clips.KIND_VIDEO:
            metrics, warnings = await _cut_video(job_id, plan, storage, video)
        else:
            metrics, warnings = await _draw_still(job_id, plan, storage, video)

        await phase_writer.note(job_id, phases.CHECKING_GRAPHIC)
        probe = await ffmpeg.probe_video(video)
        if probe is None or probe.frame_count is None:
            raise RenderFailed("The rendered video could not be read.")
        checks, mismatches = graphics_render.check_probe(
            probe, width=plan.width, height=plan.height, fps=plan.fps, frames=plan.frames
        )
        checks["audio"] = probe.audio is None
        if probe.audio is not None:
            mismatches.append("The footage clip has a sound track; footage is always muted.")
        metrics.update(
            {
                "job_s": round(time.monotonic() - started, 3),
                "size_bytes": video.stat().st_size,
                "frames": probe.frame_count,
                "width": probe.width,
                "height": probe.height,
                "fps": probe.fps,
                "codec": probe.codec_name,
                "pix_fmt": probe.pix_fmt,
                "checks": checks,
            }
        )
        if mismatches:
            raise VideoMismatch(" ".join(mismatches), metrics)

        await phase_writer.note(job_id, phases.SAVING_GRAPHIC)
        temp = await storage.describe_temp(video)
        stored = await storage.save(temp, plan.project_id, "mp4")
        await _save(
            job_id,
            plan.clip_id,
            stored.relative_path,
            temp.sha256,
            probe.frame_count,
            metrics,
            warnings,
        )


# --- A video ----------------------------------------------------------------------------------


async def _cut_video(
    job_id: int, plan: _Plan, storage: Storage, dest: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Cuts the clip from the stored video. Returns its metrics and warnings."""
    if plan.use is None:
        raise RenderFailed("The part of the video to show is not known.")
    source = storage.get_path(plan.media_path)
    probe = await ffmpeg.probe_video(source)
    if probe is None or probe.width is None or probe.height is None:
        raise RenderFailed("The stored video could not be read.")
    if probe.audio is not None:
        raise RenderFailed("The stored video has a sound track; footage is always muted.")
    length_s = plan.frames / plan.fps
    try:
        start = footage_cut.choose_start(
            plan.use[0], plan.use[1], length_s, plan.moment_s, plan.cuts, plan.fps
        )
        graph = footage_video.clip_graph(
            (probe.width, probe.height),
            width=plan.width,
            height=plan.height,
            fps=plan.fps,
            frames=plan.frames,
            crop=plan.framing,
        )
    except ValueError as exc:
        raise RenderFailed(str(exc)) from exc
    await phase_writer.note(job_id, phases.CUTTING_FOOTAGE_CLIP)
    await run_ffmpeg(
        footage_video.clip_args(
            source, dest, start_s=start.start_s, graph=graph, frames=plan.frames, fps=plan.fps
        ),
        TRIM_TIMEOUT_S,
        "cutting the footage clip",
    )
    warnings: list[dict[str, str]] = []
    if start.cut_in_clip:
        warnings.append(
            {
                "code": "cut_in_clip",
                "message": (
                    "A cut falls close to the first or last frame of this clip, and no other "
                    "start avoids it. Move the start or end of the video to fix it."
                ),
            }
        )
    metrics: dict[str, Any] = {
        "engine": "ffmpeg",
        "source_px": [probe.width, probe.height],
        "start_s": start.start_s,
        "use": list(plan.use),
        "moment_s": plan.moment_s,
        "cuts": plan.cuts,
        "cut_in_clip": start.cut_in_clip,
        "framing": plan.framing,
    }
    return metrics, warnings


# --- An image, a page or a PDF ----------------------------------------------------------------


@dataclass(frozen=True)
class _Picture:
    """The request's picture: its encoding, its size in the world of the layout and the size it
    is sent at."""

    encoded: dict[str, str]
    world_px: tuple[int, int]
    sent_px: tuple[int, int]


def _encode(data: bytes, mime: str) -> dict[str, str]:
    return {"mime": mime, "base64": base64.b64encode(data).decode("ascii")}


def _world_size(path: Path) -> tuple[int, int]:
    """The picture's size as a browser shows it: with its EXIF turn applied."""
    with Image.open(path) as image:
        width, height = image.size
        if image.getexif().get(_EXIF_ORIENTATION, 1) in (5, 6, 7, 8):
            width, height = height, width
    return width, height


def _prepare_picture(path: Path, density: float) -> _Picture:
    """Reads the stored picture and makes the request's: shrunk when `density` (output pixels
    for one pixel of the picture, at most) says it has more pixels than the clip can show, turned
    upright, and as JPEG when its PNG would be over `MAX_PICTURE_BASE64_BYTES`. Blocking: run it
    in a thread. Raises RenderFailed when it cannot be made small enough."""
    with Image.open(path) as opened:
        opened.load()
        original_format = opened.format
        turned = opened.getexif().get(_EXIF_ORIENTATION, 1) != 1
        image = ImageOps.exif_transpose(opened) if turned else opened.copy()
    world = image.size
    target_w = max(2, math.ceil(world[0] * min(1.0, density)))
    resized = target_w < world[0]
    if resized:
        target_h = max(2, round(world[1] * target_w / world[0]))
        image = image.resize((target_w, target_h), Image.Resampling.LANCZOS)
    mime = _PICTURE_MIMES.get(original_format or "")
    if mime is not None and not resized and not turned:
        encoded = _encode(path.read_bytes(), mime)
    else:
        buffer = io.BytesIO()
        if original_format == "JPEG":
            image.convert("RGB").save(buffer, "JPEG", quality=JPEG_QUALITY)
            mime = "image/jpeg"
        else:
            image.save(buffer, "PNG")
            mime = "image/png"
        encoded = _encode(buffer.getvalue(), mime)
    if len(encoded["base64"]) > MAX_PICTURE_BASE64_BYTES:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "JPEG", quality=JPEG_QUALITY)
        encoded = _encode(buffer.getvalue(), "image/jpeg")
    if len(encoded["base64"]) > MAX_PICTURE_BASE64_BYTES:
        raise RenderFailed(
            f"The picture is too large to send to the motion service "
            f"({len(encoded['base64']) // (1024 * 1024)} MB; the limit is "
            f"{MAX_PICTURE_BASE64_BYTES // (1024 * 1024)} MB)."
        )
    return _Picture(encoded=encoded, world_px=world, sent_px=image.size)


def _still_plan(plan: _Plan, world: tuple[int, int]) -> footage_clip_layout.StillPlan:
    frame = (plan.width, plan.height)
    if plan.kind == footage_clips.KIND_IMAGE:
        return footage_clip_layout.image_plan(
            world, frame, plan.framing, fps=plan.fps, frames=plan.frames
        )
    rects = footage_clip_layout.focus_rects(plan.capture, world[0], world[1])
    if plan.kind == footage_clips.KIND_PAGE:
        return footage_clip_layout.page_plan(
            world,
            footage_clip_layout.viewport_of(plan.capture, frame),
            frame,
            rects,
            fps=plan.fps,
            frames=plan.frames,
            address=footage_clip_layout.address_of(plan.source),
        )
    return footage_clip_layout.pdf_plan(world, frame, rects, fps=plan.fps, frames=plan.frames)


async def _draw_still(
    job_id: int, plan: _Plan, storage: Storage, dest: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Draws the clip of an image, a page or a PDF in the motion service."""
    path = storage.get_path(plan.media_path)
    world = await anyio.to_thread.run_sync(_world_size, path)
    layout = _still_plan(plan, world)

    # The service's versions go with the metrics, and an unreachable service is reported
    # now, before anything else is done.
    async with SessionLocal() as session:
        base_url = await settings_service.get_str(session, settings_service.MOTION_URL_KEY)
    health = await motion_renderer.health(base_url)

    await phase_writer.note(job_id, phases.PREPARING_FOOTAGE_PICTURE)
    picture = await anyio.to_thread.run_sync(_prepare_picture, path, layout.max_density)
    resolved = footage_clip_layout.resolved_for(
        layout,
        accent=plan.accent,
        background=evidence_clips.BACKGROUND,
        fonts=dict(graphics_lab.FONTS),
        frame_size=(plan.width, plan.height),
    )
    body = graphics_render.render_body(
        ENGINE,
        width=plan.width,
        height=plan.height,
        fps=plan.fps,
        frames=plan.frames,
        resolved=resolved,
        input={"image": picture.encoded, "context": None},
        code=None,
    )
    render_s = await motion_draw.draw_in_motion(
        job_id,
        base_url,
        body,
        dest,
        path=motion_renderer.EVIDENCE_RENDERS_PATH,
        start_timeout_s=motion_renderer.EVIDENCE_START_TIMEOUT_S,
    )
    metrics: dict[str, Any] = {
        "engine": ENGINE,
        "composition": COMPOSITION,
        "mode": layout.mode,
        "image_px": list(world),
        "sent_px": list(picture.sent_px),
        "picture_bytes": len(picture.encoded["base64"]),
        "picture_mime": picture.encoded["mime"],
        "density": round(layout.max_density, 4),
        "focus_lines": len(layout.rects),
        "render_s": render_s,
        "encoding": dict(graphics_render.ENCODING),
        "versions": {"remotion": health.get("remotion"), "chrome": health.get("chrome")},
    }
    return metrics, []


# --- The row ----------------------------------------------------------------------------------


def _use_of(value: object) -> tuple[float, float] | None:
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(n, int | float) and not isinstance(n, bool) for n in value)
    ):
        return float(value[0]), float(value[1])
    return None


def _whole(value: object, what: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    raise RenderFailed(f"The footage clip does not say its {what}.")


async def _plan(clip_id: int) -> _Plan:
    """Reads what the job draws. Raises RenderFailed."""
    async with SessionLocal() as session:
        clip = await session.get(FootageClip, clip_id)
        if clip is None:
            raise RenderFailed("The footage clip this job was made for is gone.")
        item = await session.get(FootageItem, clip.item_id)
        if item is None:
            raise RenderFailed("The piece of footage this clip shows is gone.")
        inputs = clip.inputs if isinstance(clip.inputs, dict) else {}
        media = footage_clips.media_of(item)
        if not item.usable or media is None or item.kind is None:
            raise RenderFailed("The file of this piece of footage is not ready.")
        accent = inputs.get("accent")
        framing = inputs.get("framing")
        moment = inputs.get("moment_s")
        cuts = item.cuts if isinstance(item.cuts, list) else []
        return _Plan(
            clip_id=clip.id,
            project_id=clip.project_id,
            kind=item.kind,
            width=_whole(inputs.get("width"), "size"),
            height=_whole(inputs.get("height"), "size"),
            fps=_whole(inputs.get("fps"), "frame rate"),
            frames=_whole(inputs.get("frames"), "length"),
            framing=footage_video.crop_of(framing),
            accent=accent if isinstance(accent, str) else caption_plan.HIGHLIGHT_COLOUR,
            use=_use_of(inputs.get("use")),
            moment_s=float(moment) if isinstance(moment, int | float) else None,
            media_path=media[0],
            cuts=[float(cut) for cut in cuts if isinstance(cut, int | float)],
            capture=item.capture,
            source=item.source,
        )


async def _save(
    job_id: int,
    clip_id: int,
    path: str,
    sha256: str,
    frame_count: int,
    metrics: dict[str, Any],
    warnings: list[dict[str, str]],
) -> None:
    """Saves the video on the clip and finishes the job in one transaction."""
    async with SessionLocal() as session:
        clip = await session.get(FootageClip, clip_id)
        if clip is None:
            await session.rollback()
            _logger.warning("job %d: video stored but the clip is gone: %s", job_id, path)
            return
        clip.media_path = path
        clip.sha256 = sha256
        clip.frame_count = frame_count
        clip.metrics = metrics
        clip.warnings = warnings
        clip.last_error = None
        output = {
            "path": path,
            "size_bytes": metrics["size_bytes"],
            "metrics": metrics,
            "warnings": warnings,
            "footage_clip_id": clip_id,
        }
        if not await store.finish_job(session, job_id, output):
            await session.rollback()
            # Stored files are never deleted here.
            _logger.warning("job %d: video stored but the job is gone: %s", job_id, path)
            return
        await session.commit()
    _logger.info("job %d: footage clip rendered (%d frames)", job_id, frame_count)


async def _fail(
    job_id: int, clip_id: int | None, message: str, *, metrics: dict[str, Any] | None = None
) -> None:
    """Fails the job and puts the message on the clip, so the card shows it. A job that was
    cancelled meanwhile leaves the clip alone."""
    async with SessionLocal() as session:
        job = await store.get_job(session, job_id)
        clip = await session.get(FootageClip, clip_id) if clip_id is not None else None
        if job is not None and job.status == "running" and clip is not None:
            if metrics is not None:
                clip.metrics = metrics
            clip.last_error = message[: store.ERROR_MAX_CHARS]
        await store.fail_job(session, job_id, message)
