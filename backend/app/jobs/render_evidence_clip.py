"""The `render_evidence_clip` job: the video of one piece of evidence, zoomed to its quote (EVD-008,
`Evidence_layer_implementation_phases.md` §4.7).

The input is `{evidence_clip_id, preview_item_id}`. The `evidence_clip` row says what is drawn: the
piece (`item_id`), the size, frame rate and length (`inputs`) and the highlight's colour. EVD-009
makes the exact-length clips of evidence shots with this same job.

1. The camera, the stage and the timeline are worked out from the capture's rectangles
   (`services/evidence_clip_layout.py`), and the source badge from the piece's source.
2. The stored screenshot is sent as it is. The context image is sent only when the camera goes past
   the screenshot's edge, and then only the part of it that is ever on screen, shrunk to at most
   1.5 times the output size. Both go inside the request as base64 to the motion service's
   `/evidence-renders` route: the motion service gets no volume, no internet and no secrets.
3. The motion service draws the video, and it is downloaded.
4. `ffprobe` checks it: the exact frame count, the size, the frame rate, H.264 and `yuv420p`. Any
   difference fails the job. The file is not kept.
5. The file is stored, and the clip gets its path, its SHA-256, its frame count, its metrics (the
   quote's text height on the frame among them) and its warnings (`small_text` when the quote is
   too small to read).

A local job: nothing is paid for and no model is asked. A restart makes the clip again from the
start. Stored files, the screenshots included, are never deleted here. Logs hold the job id, never
the words.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import anyio.to_thread
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import EvidenceClip, EvidenceItem
from app.db.session import SessionLocal
from app.jobs import motion_draw, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.jobs.render_story import RenderFailed
from app.providers import motion_renderer
from app.services import (
    evidence_clip_layout,
    evidence_clips,
    ffmpeg,
    graphics_render,
)
from app.services.storage import Storage, StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = evidence_clips.JOB_TYPE
ENGINE: Final = "evidence_clip"
# The composition of `motion/src/Root.tsx` that draws it.
COMPOSITION: Final = "Evidence"

# The pictures of one request, as base64, at most. The motion service's own limit for the body is
# 32 MiB; the rest is the other fields.
MAX_PICTURES_BASE64_BYTES: Final = 30 * 1024 * 1024
# The context image is shrunk to this many times the output size, never enlarged.
CONTEXT_MAX_SCALE: Final = 1.5


class VideoMismatch(RenderFailed):
    """The drawn file is not the clip that was asked for. `metrics` says what it is."""

    def __init__(self, message: str, metrics: dict[str, Any]) -> None:
        super().__init__(message)
        self.metrics = metrics


@dataclass
class _Plan:
    """What one job draws: the clip's size and length, the piece and the colour."""

    clip_id: int
    project_id: int
    width: int
    height: int
    fps: int
    frames: int
    accent: str
    capture: Any
    badge: dict[str, Any]
    image_path: str
    context_path: str | None


class RenderEvidenceClipHandler(JobHandler):
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
            value = recorded.get(evidence_clips.CLIP_KEY)
            clip_id = value if isinstance(value, int) and not isinstance(value, bool) else None
            if clip_id is None:
                raise RenderFailed("The job names no evidence clip.")
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
        geometry = evidence_clip_layout.geometry_of(plan.capture)
        if geometry is None:
            raise RenderFailed("The piece of evidence has no usable position of its quote.")
        layout = evidence_clip_layout.plan(geometry, plan.width, plan.height, plan.fps, plan.frames)

        # The service's versions go with the metrics, and an unreachable service is reported
        # now, before anything else is done.
        async with SessionLocal() as session:
            base_url = await settings_service.get_str(session, settings_service.MOTION_URL_KEY)
        health = await motion_renderer.health(base_url)
        versions = {"remotion": health.get("remotion"), "chrome": health.get("chrome")}

        await phase_writer.note(job_id, phases.PREPARING_EVIDENCE)
        pictures = await anyio.to_thread.run_sync(_prepare_pictures, storage, plan, layout)
        resolved = evidence_clips.resolved_for(
            layout, accent=plan.accent, badge=plan.badge, context_box=pictures.context_box
        )

        video = storage.new_temp_path("mp4")
        temp_paths.append(video)
        body = graphics_render.render_body(
            ENGINE,
            width=plan.width,
            height=plan.height,
            fps=plan.fps,
            frames=plan.frames,
            resolved=resolved,
            input={"image": pictures.image, "context": pictures.context},
            code=None,
        )
        render_s = await motion_draw.draw_in_motion(
            job_id,
            base_url,
            body,
            video,
            path=motion_renderer.EVIDENCE_RENDERS_PATH,
            start_timeout_s=motion_renderer.EVIDENCE_START_TIMEOUT_S,
        )

        await phase_writer.note(job_id, phases.CHECKING_GRAPHIC)
        probe = await ffmpeg.probe_video(video)
        if probe is None or probe.frame_count is None:
            raise RenderFailed("The rendered video could not be read.")
        checks, mismatches = graphics_render.check_probe(
            probe, width=plan.width, height=plan.height, fps=plan.fps, frames=plan.frames
        )
        metrics: dict[str, Any] = {
            "engine": ENGINE,
            "composition": COMPOSITION,
            "text_height_px": layout.text_height_px,
            "min_text_height_px": layout.min_text_height_px,
            "zoom": round(layout.zoom, 4),
            "picture_bytes": pictures.base64_bytes,
            "context_sent": pictures.context is not None,
            "render_s": render_s,
            "job_s": round(time.monotonic() - started, 3),
            "size_bytes": video.stat().st_size,
            "frames": probe.frame_count,
            "width": probe.width,
            "height": probe.height,
            "fps": probe.fps,
            "codec": probe.codec_name,
            "pix_fmt": probe.pix_fmt,
            "checks": checks,
            "encoding": dict(graphics_render.ENCODING),
            "versions": versions,
        }
        if mismatches:
            raise VideoMismatch(" ".join(mismatches), metrics)

        warning = evidence_clips.small_text_warning(layout)
        warnings = [warning] if warning is not None else []
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


@dataclass(frozen=True)
class _Pictures:
    """The request's two pictures, and where the context's crop sits in the world."""

    image: dict[str, str]
    context: dict[str, str] | None
    context_box: evidence_clip_layout.Box | None
    base64_bytes: int


def _encode(data: bytes, mime: str) -> dict[str, str]:
    return {"mime": mime, "base64": base64.b64encode(data).decode("ascii")}


def _prepare_pictures(
    storage: Storage, plan: _Plan, layout: evidence_clip_layout.ClipPlan
) -> _Pictures:
    """Reads the stored screenshot, and cuts and shrinks the context image when the camera needs
    it. Blocking: run it in a thread. Raises RenderFailed when the request would be too large and
    StorageError for a path that is not a stored file's.
    """
    image = _encode(storage.get_path(plan.image_path).read_bytes(), "image/png")
    context: dict[str, str] | None = None
    context_box: evidence_clip_layout.Box | None = None
    world = layout.geometry.context
    if layout.context_crop is not None and plan.context_path is not None and world is not None:
        with Image.open(storage.get_path(plan.context_path)) as source:
            source.load()
            size = source.size
            pixels = evidence_clip_layout.context_crop_pixels(layout.context_crop, world, size)
            context_box = evidence_clip_layout.world_box_of_pixels(pixels, world, size)
            crop = source.crop(pixels).convert("RGB")
        # `thumbnail` only ever shrinks.
        crop.thumbnail(
            (round(CONTEXT_MAX_SCALE * plan.width), round(CONTEXT_MAX_SCALE * plan.height))
        )
        buffer = io.BytesIO()
        crop.save(buffer, "PNG")
        context = _encode(buffer.getvalue(), "image/png")
    total = len(image["base64"]) + (len(context["base64"]) if context is not None else 0)
    if total > MAX_PICTURES_BASE64_BYTES:
        raise RenderFailed(
            f"The pictures are too large to send to the motion service "
            f"({total // (1024 * 1024)} MB; the limit is "
            f"{MAX_PICTURES_BASE64_BYTES // (1024 * 1024)} MB)."
        )
    return _Pictures(image=image, context=context, context_box=context_box, base64_bytes=total)


async def _plan(clip_id: int) -> _Plan:
    """Reads what the job draws. Raises RenderFailed."""
    async with SessionLocal() as session:
        clip = await session.get(EvidenceClip, clip_id)
        if clip is None:
            raise RenderFailed("The evidence clip this job was made for is gone.")
        item = await session.get(EvidenceItem, clip.item_id) if clip.item_id is not None else None
        if item is None:
            raise RenderFailed("The piece of evidence this clip shows is gone.")
        inputs = clip.inputs if isinstance(clip.inputs, dict) else {}
        accent = inputs.get("accent")
        if not item.usable or not item.image_path:
            raise RenderFailed("The piece of evidence has no picture to draw.")
        try:
            plan = _Plan(
                clip_id=clip.id,
                project_id=clip.project_id,
                width=int(inputs["width"]),
                height=int(inputs["height"]),
                fps=int(inputs["fps"]),
                frames=int(inputs["frames"]),
                accent=accent if isinstance(accent, str) else "",
                capture=item.capture,
                badge=evidence_clips.badge_of(item),
                image_path=item.image_path,
                context_path=item.context_path,
            )
        except (KeyError, TypeError, ValueError):
            raise RenderFailed("The evidence clip does not say its size and length.") from None
        await session.commit()
    return plan


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
        clip = await session.get(EvidenceClip, clip_id)
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
            "evidence_clip_id": clip_id,
        }
        if not await store.finish_job(session, job_id, output):
            await session.rollback()
            # Stored files are never deleted here.
            _logger.warning("job %d: video stored but the job is gone: %s", job_id, path)
            return
        await session.commit()
    _logger.info("job %d: evidence clip rendered (%d frames)", job_id, frame_count)


async def _fail(
    job_id: int, clip_id: int | None, message: str, *, metrics: dict[str, Any] | None = None
) -> None:
    """Fails the job and puts the message on the clip, so the review screen shows it. A job that
    was cancelled meanwhile leaves the clip alone."""
    async with SessionLocal() as session:
        job = await store.get_job(session, job_id)
        clip = await session.get(EvidenceClip, clip_id) if clip_id is not None else None
        if job is not None and job.status == "running" and clip is not None:
            if metrics is not None:
                clip.metrics = metrics
            clip.last_error = message[: store.ERROR_MAX_CHARS]
        await store.fail_job(session, job_id, message)
