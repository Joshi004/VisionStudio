"""The `render_evidence_clip` job: the video of one piece of evidence, zoomed to its quote (EVD-008,
`Evidence_layer_implementation_phases.md` §4.7).

The input is `{evidence_clip_id, preview_item_id}` (a shot clip: `shot_clip_ref`, a card:
`card_clip_ref`). The `evidence_clip` row says what is drawn: the
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
   difference fails the job. The file is not kept. An evidence card (EVD-011, `purpose` `card`) is
   drawn at the card's own size as a transparent ProRes 4444 clip instead, and checked for an
   alpha channel. A split evidence shot (EVD-016, `inputs.layout` `split`) is planned for its
   evidence panel (`inputs.panel`) and drawn inside it, on the full frame.
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
from app.jobs.render_story import TRIM_TIMEOUT_S, RenderFailed, run_ffmpeg
from app.providers import motion_renderer
from app.services import (
    evidence_clip_layout,
    evidence_clips,
    evidence_layout,
    ffmpeg,
    graphics_lab,
    graphics_render,
    render_commands,
    soundbite_clips,
    soundbite_render,
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
    # An evidence card (EVD-011): `width` and `height` are the card's own size, and `frame` is the
    # output frame it is laid on. None for a preview and a shot clip.
    frame: tuple[int, int] | None = None
    # A split evidence shot (EVD-016): the evidence panel on the output frame, `(x, y, width,
    # height)`. `width` and `height` stay the output frame's size, which the video has.
    panel: tuple[int, int, int, int] | None = None

    @property
    def card(self) -> bool:
        return self.frame is not None


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
        bite = await _soundbite_plan(clip_id)
        if bite is not None:
            await _render_soundbite(job_id, bite, storage, temp_paths, started)
            return
        plan = await _plan(clip_id)
        geometry = evidence_clip_layout.geometry_of(plan.capture)
        if geometry is None:
            raise RenderFailed("The piece of evidence has no usable position of its quote.")
        if plan.panel is not None:
            # The picture is planned for the evidence panel and drawn inside it (EVD-016).
            layout = evidence_clip_layout.plan(
                geometry,
                plan.panel[2],
                plan.panel[3],
                plan.fps,
                plan.frames,
                frame=(plan.width, plan.height),
                panel=plan.panel,
                panel_edge=evidence_layout.panels(plan.width, plan.height).edge,
            )
        else:
            layout = evidence_clip_layout.plan(
                geometry,
                plan.width,
                plan.height,
                plan.fps,
                plan.frames,
                card=plan.card,
                frame=plan.frame,
            )

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

        # A card is a transparent ProRes clip, like a callout; everything else is H.264.
        extension = "mov" if plan.card else "mp4"
        video = storage.new_temp_path(extension)
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
            encoding=graphics_render.CALLOUT_ENCODING if plan.card else None,
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
            probe,
            width=plan.width,
            height=plan.height,
            fps=plan.fps,
            frames=plan.frames,
            transparent=plan.card,
        )
        metrics: dict[str, Any] = {
            "engine": ENGINE,
            "composition": COMPOSITION,
            "text_height_px": layout.text_height_px,
            "min_text_height_px": layout.min_text_height_px,
            "layout": evidence_clips.LAYOUT_SPLIT if plan.panel is not None else "full",
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
            "encoding": dict(
                graphics_render.CALLOUT_ENCODING if plan.card else graphics_render.ENCODING
            ),
            "versions": versions,
        }
        if mismatches:
            raise VideoMismatch(" ".join(mismatches), metrics)

        warning = evidence_clips.small_text_warning(layout)
        warnings = [warning] if warning is not None else []
        await phase_writer.note(job_id, phases.SAVING_GRAPHIC)
        temp = await storage.describe_temp(video)
        stored = await storage.save(temp, plan.project_id, extension)
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
        frame: tuple[int, int] | None = None
        if clip.purpose == evidence_clips.PURPOSE_CARD:
            size = inputs.get("frame")
            if (
                not isinstance(size, list)
                or len(size) != 2
                or not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in size)
            ):
                raise RenderFailed("The evidence card does not say the frame it is laid on.")
            frame = (size[0], size[1])
        panel: tuple[int, int, int, int] | None = None
        if inputs.get("layout") == evidence_clips.LAYOUT_SPLIT:
            raw_panel = inputs.get("panel")
            if (
                not isinstance(raw_panel, list)
                or len(raw_panel) != 4
                or not all(
                    isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in raw_panel
                )
                or raw_panel[2] < 1
                or raw_panel[3] < 1
            ):
                raise RenderFailed("The split evidence shot does not say its panel.")
            panel = (raw_panel[0], raw_panel[1], raw_panel[2], raw_panel[3])
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
                frame=frame,
                panel=panel,
            )
        except (KeyError, TypeError, ValueError):
            raise RenderFailed("The evidence clip does not say its size and length.") from None
        await session.commit()
    return plan


# --- A sound bite clip (SB-009) ---------------------------------------------------------------

OVERLAY_ENGINE: Final = "soundbite_overlay"
OVERLAY_COMPOSITION: Final = "SoundbiteOverlay"


@dataclass
class _BitePlan:
    """What one job makes of a sound bite: the owner's cut of the downloaded video at the output
    size, with the lower third and the credit over it. `purpose` is `soundbite` (the clip the
    render plays: a MOV with PCM sound) or `preview` (the review's copy: an MP4 a browser plays)."""

    clip_id: int
    project_id: int
    purpose: str
    width: int
    height: int
    fps: int
    frames: int
    accent: str
    video_path: str
    in_s: float
    out_s: float
    speaker: str
    role: str
    venue: str
    recorded: str
    channel: object
    first_word: int
    last_word: int
    heard: list[tuple[str, float, float]]


async def _soundbite_plan(clip_id: int) -> _BitePlan | None:
    """Reads what the job makes when the clip shows a `video` piece, or None for any other clip.
    Raises RenderFailed for a sound bite clip whose record is not complete."""
    async with SessionLocal() as session:
        clip = await session.get(EvidenceClip, clip_id)
        if clip is None:
            raise RenderFailed("The evidence clip this job was made for is gone.")
        item = await session.get(EvidenceItem, clip.item_id) if clip.item_id is not None else None
        if item is None:
            raise RenderFailed("The piece of evidence this clip shows is gone.")
        await session.commit()
        if item.kind != "video":
            return None
        inputs = clip.inputs if isinstance(clip.inputs, dict) else {}
        if not item.video_path:
            raise RenderFailed("The sound bite clip has no video file.")
        accent = inputs.get("accent")
        try:
            return _BitePlan(
                clip_id=clip.id,
                project_id=clip.project_id,
                purpose=clip.purpose,
                width=int(inputs["width"]),
                height=int(inputs["height"]),
                fps=int(inputs["fps"]),
                frames=int(inputs["frames"]),
                accent=accent if isinstance(accent, str) else "",
                video_path=item.video_path,
                in_s=float(inputs["in_s"]),
                out_s=float(inputs["out_s"]),
                speaker=str(inputs["speaker"]),
                role=str(inputs["role"]),
                venue=str(inputs["venue"]),
                recorded=str(inputs["recorded"]),
                channel=inputs.get("channel"),
                first_word=int(inputs["first_word"]),
                last_word=int(inputs["last_word"]),
                heard=[
                    (word.text, word.start, word.end)
                    for word in soundbite_clips.words_of(item.heard_words)
                ],
            )
        except (KeyError, TypeError, ValueError):
            raise RenderFailed("The sound bite clip does not say its cut and its size.") from None


async def _render_soundbite(
    job_id: int,
    plan: _BitePlan,
    storage: Storage,
    temp_paths: list[Path],
    started: float,
) -> None:
    """Makes the clip: the motion service draws the overlay (a transparent ProRes clip), then
    ffmpeg cuts the video window at the cut's start, frames the picture, lays the overlay over it
    and writes the file. The sound is the cut's own, unchanged."""
    if plan.frames < 2 or plan.out_s <= plan.in_s:
        raise RenderFailed("The sound bite clip has no length.")
    source = storage.get_path(plan.video_path)
    probe = await ffmpeg.probe_video(source)
    if probe is None or probe.width is None or probe.height is None:
        raise RenderFailed("The downloaded video could not be read.")
    if probe.audio is None:
        raise RenderFailed("The downloaded video has no sound, so it cannot be a sound bite.")
    framing = soundbite_render.framing_for((probe.width, probe.height), (plan.width, plan.height))

    name, detail = soundbite_render.lower_third_lines(
        {"speaker": plan.speaker, "role": plan.role, "venue": plan.venue, "recorded": plan.recorded}
    )
    credit = soundbite_render.credit_text(plan.channel)
    safe, caption = evidence_clip_layout.safe_and_caption(plan.width, plan.height)
    resolved = soundbite_render.overlay_resolved(
        width=plan.width,
        height=plan.height,
        fps=plan.fps,
        accent=plan.accent,
        fonts=graphics_lab.FONTS,
        safe=safe,
        caption=caption,
        name=name,
        detail=detail,
        credit=credit,
        last_word_start_s=soundbite_render.last_word_start(plan.heard, plan.last_word, plan.in_s),
    )
    warnings: list[dict[str, str]] = []
    if resolved["lower_third"] is None:
        warnings.append(
            {
                "code": "no_lower_third",
                "message": "The clip is too short for a lower third, so it has none.",
            }
        )
    overlay: Path | None = None
    versions: dict[str, Any] = {}
    render_s: float | None = None
    if resolved["lower_third"] is not None or resolved["credit"] is not None:
        async with SessionLocal() as session:
            base_url = await settings_service.get_str(session, settings_service.MOTION_URL_KEY)
        health = await motion_renderer.health(base_url)
        versions = {"remotion": health.get("remotion"), "chrome": health.get("chrome")}
        await phase_writer.note(job_id, phases.PREPARING_EVIDENCE)
        overlay = storage.new_temp_path("mov")
        temp_paths.append(overlay)
        body = graphics_render.render_body(
            OVERLAY_ENGINE,
            width=plan.width,
            height=plan.height,
            fps=plan.fps,
            frames=plan.frames,
            resolved=resolved,
            input=None,
            code=None,
            encoding=graphics_render.CALLOUT_ENCODING,
        )
        render_s = await motion_draw.draw_in_motion(job_id, base_url, body, overlay)
        drawn = await ffmpeg.probe_video(overlay)
        if drawn is None or drawn.frame_count is None:
            raise RenderFailed("The rendered overlay could not be read.")
        _, overlay_problems = graphics_render.check_probe(
            drawn,
            width=plan.width,
            height=plan.height,
            fps=plan.fps,
            frames=plan.frames,
            transparent=True,
        )
        if overlay_problems:
            raise RenderFailed(" ".join(overlay_problems))

    for_browser = plan.purpose == evidence_clips.PURPOSE_PREVIEW
    extension = "mp4" if for_browser else "mov"
    video = storage.new_temp_path(extension)
    temp_paths.append(video)
    graph = soundbite_render.compose_graph(
        framing,
        width=plan.width,
        height=plan.height,
        fps=plan.fps,
        frames=plan.frames,
        audio_s=plan.out_s - plan.in_s,
        channel_filters=render_commands.stereo_filters(probe.audio.channels),
        with_overlay=overlay is not None,
    )
    await phase_writer.note(job_id, phases.CHECKING_GRAPHIC)
    await run_ffmpeg(
        render_commands.soundbite_clip_args(
            source,
            overlay,
            video,
            start_s=plan.in_s,
            graph=graph,
            frames=plan.frames,
            fps=plan.fps,
            for_browser=for_browser,
        ),
        TRIM_TIMEOUT_S,
        "cutting the sound bite clip",
    )
    made = await ffmpeg.probe_video(video)
    if made is None or made.frame_count is None:
        raise RenderFailed("The sound bite clip could not be read after it was made.")
    checks, mismatches = graphics_render.check_probe(
        made, width=plan.width, height=plan.height, fps=plan.fps, frames=plan.frames
    )
    if made.audio is None:
        mismatches.append("The sound bite clip has no sound.")
    lufs = await ffmpeg.measure_loudness(
        video, pre_filters=render_commands.stereo_filters(made.audio.channels if made.audio else 2)
    )
    metrics: dict[str, Any] = {
        "engine": OVERLAY_ENGINE,
        "composition": OVERLAY_COMPOSITION,
        "framing": framing.kind,
        "source_px": [probe.width, probe.height],
        "lower_third": resolved["lower_third"] is not None,
        "credit": resolved["credit"] is not None,
        "speech_lufs": None if lufs is None else round(lufs, 1),
        "render_s": render_s,
        "job_s": round(time.monotonic() - started, 3),
        "size_bytes": video.stat().st_size,
        "frames": made.frame_count,
        "width": made.width,
        "height": made.height,
        "fps": made.fps,
        "codec": made.codec_name,
        "pix_fmt": made.pix_fmt,
        "checks": checks,
        "versions": versions,
    }
    if mismatches:
        raise VideoMismatch(" ".join(mismatches), metrics)
    await phase_writer.note(job_id, phases.SAVING_GRAPHIC)
    temp = await storage.describe_temp(video)
    stored = await storage.save(temp, plan.project_id, extension)
    await _save(
        job_id, plan.clip_id, stored.relative_path, temp.sha256, made.frame_count, metrics, warnings
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
