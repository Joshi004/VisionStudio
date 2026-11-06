"""Drawing the motion callouts of a story or scene render (CMO-005,
`Callouts_motion_implementation_phases.md` §4.7).

It is the step *drawing the callouts* of `jobs/render_story.py`, which `jobs/render_scene.py`
shares. For each entry of the frozen timeline that has `motion`, it asks the motion service to
draw the callout's version at the entry's real zone and length, as a ProRes 4444 clip with an
alpha channel (`graphics_render.CALLOUT_ENCODING`), downloads it to the render's temp folder and
checks it with ffprobe. At most `graphics_max_parallel_renders` clips are drawn at once.

**Fallbacks (CM-10).** A callout whose drawing fails (the service says it could not draw it, the
file is not what was asked for, or the attempt is gone) is drawn with its other version when the
timeline recorded one, and, when that fails too, as a box (the render's ASS file draws it, as it
does for a project of boxes). Each fallback is a `callout_fallback` warning on the render. A
motion service that cannot be reached at all fails the render with a message: no callout is
quietly turned into a box because a service is down.

The frozen timeline is never changed: what was drawn is recorded on the render's `levels`.
Nothing is cached (CM-11): every render draws every motion callout again. Logs hold the job id and
counts, never the words.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from app.core import settings as settings_service
from app.db.models import CalloutGraphic
from app.db.session import SessionLocal
from app.jobs import callout_graphic_common, motion_draw
from app.jobs.render_story import RenderFailed
from app.providers import motion_renderer
from app.services import (
    callout_graphics,
    callout_render,
    ffmpeg,
    graphics_render,
    render_commands,
)
from app.services.storage import Storage

_logger = logging.getLogger(__name__)

SERVICE_DOWN_MESSAGE: Final = (
    "The motion service is not running, and this project's callouts are drawn by it. "
    "Start it, or switch callouts to simple boxes."
)
# ffprobe reads every packet of a clip; a long callout is a large file.
PROBE_TIMEOUT_S: Final = 300.0
# What a callout that is drawn as a box is called in the render's record.
BOX: Final = "box"


class DrawFailed(Exception):
    """One version of one callout could not be drawn. The message says why, in one sentence."""


@dataclass(frozen=True)
class Clip:
    """A drawn callout: its entry, the file, the story frame its first frame shows at, and how
    many frames it has.
    """

    entry: callout_render.CalloutEntry
    path: Path
    start_frame: int
    frames: int
    ref: callout_render.MotionRef


@dataclass
class DrawnCallouts:
    """What the step made."""

    clips: list[Clip] = field(default_factory=list)
    # The motion entries that are boxes after all (neither version could be drawn).
    boxed: set[str] = field(default_factory=set)
    # One record per motion entry, in the timeline's order.
    records: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    draw_s: float = 0.0

    def overlays_by_shot(self, shot_frames: Sequence[int]) -> list[list[render_commands.Overlay]]:
        """The overlays of each shot, from the frames of every shot in order. A callout that
        runs across a cut is split over the shots it crosses, each part starting at the clip's
        frame that falls on the shot's first frame it shows in (ProRes frames are all key frames,
        so starting in the middle of a clip is exact).
        """
        shots: list[list[render_commands.Overlay]] = []
        first = 0
        for frames in shot_frames:
            end = first + frames
            overlays: list[render_commands.Overlay] = []
            for clip in self.clips:
                low = max(first, clip.start_frame)
                high = min(end, clip.start_frame + clip.frames)
                if high <= low:
                    continue
                assert clip.entry.motion is not None  # a clip is only made for a motion entry
                overlays.append(
                    render_commands.Overlay(
                        path=clip.path,
                        x=clip.entry.motion.x,
                        y=clip.entry.motion.y,
                        at_frame=low - first,
                        from_frame=low - clip.start_frame,
                        to_frame=high - clip.start_frame,
                    )
                )
            shots.append(overlays)
            first = end
        return shots

    def levels(self) -> dict[str, Any]:
        """The render's record of what was drawn, for `levels["callouts"]`."""
        return {"drawn": self.records, "warnings": self.warnings}

    def summary(self, total: int) -> dict[str, Any]:
        """The counts for `output.callouts`. `total` is the number of callouts of the render:
        those with no clip are boxes.
        """
        by_version: dict[str, int] = {engine: 0 for engine in callout_render.MOTION_ENGINES}
        for clip in self.clips:
            by_version[clip.ref.engine] += 1
        by_version[BOX] = total - len(self.clips)
        return {
            "by_version": by_version,
            "fallbacks": sum(1 for record in self.records if record["fallback"]),
            "draw_s": round(self.draw_s, 1),
            "largest_bytes": max((record["size_bytes"] or 0 for record in self.records), default=0),
        }


@dataclass
class _Result:
    clip: Clip | None
    record: dict[str, Any]
    warning: dict[str, Any] | None


def _label(entry: callout_render.CalloutEntry) -> str:
    return f'"{entry.parts[0].text}"'


def _version(engine: str) -> str:
    return callout_graphics.ENGINE_LABELS.get(engine, engine).lower()


def has_motion(track: callout_render.CalloutTrack | None) -> bool:
    return track is not None and any(entry.motion is not None for entry in track.entries)


async def _require_service(base_url: str) -> None:
    """Fails the render, with a message, when the motion service cannot be reached."""
    try:
        await motion_renderer.health(base_url)
    except motion_renderer.MotionServiceError as exc:
        _logger.warning("motion service not reachable for the callouts: %s", exc)
        raise RenderFailed(SERVICE_DOWN_MESSAGE) from exc


def _probe_problem(
    probe: ffmpeg.VideoProbe | None, motion: callout_render.MotionDraw, frames: int, fps: int
) -> str | None:
    """What is wrong with a drawn clip, or None: ProRes with an alpha channel, the asked size,
    frame count and frame rate. (ffprobe reads the 10-bit pixel format back as `yuva444p12le`,
    so only the alpha is checked.)
    """
    if probe is None or probe.frame_count is None:
        return "The drawn callout could not be read."
    if probe.codec_name != "prores" or not (probe.pix_fmt or "").startswith("yuva"):
        return "The drawn callout is not a ProRes video with an alpha channel."
    if (probe.width, probe.height) != (motion.width, motion.height):
        return f"The drawn callout is {probe.width} x {probe.height}; it should be " + (
            f"{motion.width} x {motion.height}."
        )
    if probe.frame_count != frames:
        return f"The drawn callout has {probe.frame_count} frames; it should have {frames}."
    if probe.fps is None or abs(probe.fps - fps) > 0.001:
        return f"The drawn callout runs at {probe.fps} frames per second; it should be {fps}."
    return None


async def _attempt(
    ref: callout_render.MotionRef, project_id: int
) -> tuple[dict[str, Any], Any, str | None]:
    """The resolved callout and what is drawn (a block scene or the code) of an attempt. Raises
    DrawFailed.
    """
    async with SessionLocal() as session:
        row = await session.get(CalloutGraphic, ref.graphic_id)
        await session.commit()
    if row is None or row.project_id != project_id or row.engine != ref.engine:
        raise DrawFailed("Its graphic is gone.")
    inputs = row.inputs if isinstance(row.inputs, dict) else {}
    resolved = inputs.get("resolved")
    if not isinstance(resolved, dict) or row.input is None:
        raise DrawFailed("Its graphic has nothing to draw.")
    if ref.engine == callout_graphics.BLOCKS:
        try:
            return resolved, callout_graphic_common.scene_of(row.input), None
        except RenderFailed as exc:
            raise DrawFailed(str(exc)) from exc
    code = graphics_render.code_of(row.input)
    if code is None:
        raise DrawFailed("Its component has no code to draw.")
    return resolved, None, code


async def _draw_version(
    job_id: int,
    base_url: str,
    storage: Storage,
    temp_paths: list[Path],
    project_id: int,
    fps: int,
    entry: callout_render.CalloutEntry,
    ref: callout_render.MotionRef,
) -> tuple[Clip, dict[str, Any]]:
    """Draws one version of a callout. Raises DrawFailed for what is wrong with this callout, and
    RenderFailed for a motion service that cannot be reached.
    """
    motion = entry.motion
    assert motion is not None
    resolved, scene, code = await _attempt(ref, project_id)
    try:
        request = callout_graphics.render_request(
            resolved, motion, entry.start_ms, entry.end_ms, fps
        )
    except callout_graphics.CalloutGraphicsError as exc:
        raise DrawFailed(str(exc)) from exc
    body = graphics_render.render_body(
        callout_graphic_common.MOTION_ENGINES[ref.engine],
        width=motion.width,
        height=motion.height,
        fps=fps,
        frames=request.frames,
        resolved=request.resolved,
        input=scene,
        code=code,
        encoding=graphics_render.CALLOUT_ENCODING,
    )
    dest = storage.new_temp_path("mov")
    temp_paths.append(dest)
    try:
        render_s = await motion_draw.draw_in_motion(job_id, base_url, body, dest, note_phase=False)
    except motion_draw.MotionRenderFailed as exc:
        raise DrawFailed(str(exc)) from exc
    except motion_renderer.MotionServiceError as exc:
        # A refusal of this request is this callout's; a service that is gone is the render's.
        await _require_service(base_url)
        raise DrawFailed(str(exc)) from exc
    probe = await ffmpeg.probe_video(dest, timeout_s=PROBE_TIMEOUT_S)
    problem = _probe_problem(probe, motion, request.frames, fps)
    if problem is not None:
        raise DrawFailed(problem)
    clip = Clip(entry, dest, request.start_frame, request.frames, ref)
    return clip, {"render_s": render_s, "size_bytes": dest.stat().st_size, "frames": request.frames}


async def _draw_entry(
    gate: asyncio.Semaphore,
    job_id: int,
    base_url: str,
    storage: Storage,
    temp_paths: list[Path],
    project_id: int,
    fps: int,
    entry: callout_render.CalloutEntry,
) -> _Result:
    """Draws a callout with its version, else with the other one, else it stays a box."""
    motion = entry.motion
    assert motion is not None
    tries = [motion.use] + ([motion.other] if motion.other is not None else [])
    failures: list[str] = []
    async with gate:
        for index, ref in enumerate(tries):
            try:
                clip, measured = await _draw_version(
                    job_id, base_url, storage, temp_paths, project_id, fps, entry, ref
                )
            except DrawFailed as exc:
                failures.append(f"{callout_graphics.ENGINE_LABELS[ref.engine]}: {exc}")
                continue
            warning = None
            if index > 0:
                warning = {
                    "code": callout_render.CODE_FALLBACK,
                    "message": f"The callout {_label(entry)} is drawn with its "
                    f"{_version(ref.engine)} version, because its "
                    f"{_version(motion.use.engine)} version could not be drawn: {failures[0]}",
                }
            record = {
                "id": entry.id,
                "engine": ref.engine,
                "graphic_id": ref.graphic_id,
                "fallback": index > 0,
                "because": failures[0] if index > 0 else None,
                **measured,
            }
            return _Result(clip, record, warning)
    record = {
        "id": entry.id,
        "engine": BOX,
        "graphic_id": None,
        "fallback": True,
        "because": "; ".join(failures),
        "render_s": None,
        "size_bytes": None,
        "frames": None,
    }
    warning = {
        "code": callout_render.CODE_FALLBACK,
        "message": f"The callout {_label(entry)} is drawn as a simple box, because neither "
        f"version of its graphic could be drawn: {'; '.join(failures)}",
    }
    return _Result(None, record, warning)


async def draw_callouts(
    job_id: int,
    project_id: int,
    track: callout_render.CalloutTrack,
    fps: int,
    storage: Storage,
    temp_paths: list[Path],
) -> DrawnCallouts:
    """Draws every motion callout of the timeline's track (see the module note). Every clip is a
    temp file of the render, removed with the others. Raises RenderFailed when the motion service
    cannot be reached.
    """
    entries = [entry for entry in track.entries if entry.motion is not None]
    async with SessionLocal() as session:
        base_url = await settings_service.get_str(session, settings_service.MOTION_URL_KEY)
        limit = await settings_service.get_int(session, settings_service.GRAPHICS_MAX_RENDERS_KEY)
    await _require_service(base_url)

    started = time.monotonic()
    gate = asyncio.Semaphore(max(1, limit))
    results = await asyncio.gather(
        *(
            _draw_entry(gate, job_id, base_url, storage, temp_paths, project_id, fps, entry)
            for entry in entries
        ),
        return_exceptions=True,
    )
    drawn = DrawnCallouts(draw_s=time.monotonic() - started)
    for entry, result in zip(entries, results, strict=True):
        if isinstance(result, BaseException):
            # Every other callout has finished by now; the render fails with this one's reason.
            raise result
        drawn.records.append(result.record)
        if result.warning is not None:
            drawn.warnings.append(result.warning)
        if result.clip is None:
            drawn.boxed.add(entry.id)
        else:
            drawn.clips.append(result.clip)
    _logger.info(
        "job %d: callouts drawn: %d clips, %d boxes, %.1f s",
        job_id,
        len(drawn.clips),
        len(drawn.boxed),
        drawn.draw_s,
    )
    return drawn
