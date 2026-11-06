"""Drawing a video in the motion service, shared by the render jobs that use it: the Graphics lab's
`render_lab_graphic` and the explainer's `render_shot_graphic` (EXG-005).

The two jobs send the same body (`graphics_render.render_body`), wait for the service in the same
way and download the file. A render the service says it could not draw, or does not finish in
time, raises `MotionRenderFailed`; a service that cannot be reached raises
`motion_renderer.MotionServiceError`, which is not the same thing: it says nothing about the
graphic.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Final

from app.jobs import phase_writer, phases
from app.jobs.render_story import RenderFailed
from app.providers import motion_renderer
from app.services import graphics_render

POLL_INTERVAL_S: Final = 1.0
# The phase is rewritten every this many percent, not on every poll.
PHASE_PERCENT_STEP: Final = 5


class MotionRenderFailed(RenderFailed):
    """The motion service answered `failed`, or did not finish within its time limit."""


async def draw_in_motion(
    job_id: int, base_url: str, body: dict[str, Any], dest: Path, *, note_phase: bool = True
) -> float | None:
    """Has the motion service draw the video and downloads it to `dest`. Returns the service's
    own render time in seconds. With `note_phase` False the job's phase is left alone (the story
    render draws many callouts at once and keeps its own phase, CMO-005).
    """
    if note_phase:
        await phase_writer.note(job_id, phases.SENDING_GRAPHIC)
    service_id = await motion_renderer.start_render(base_url, body)
    try:
        status = await wait_for_service(job_id, base_url, service_id, note_phase=note_phase)
        if note_phase:
            await phase_writer.note(job_id, phases.DOWNLOADING_GRAPHIC)
        await motion_renderer.download_render(base_url, service_id, dest)
    finally:
        await motion_renderer.delete_render(base_url, service_id)
    seconds = status.get("render_s")
    return float(seconds) if isinstance(seconds, int | float) else None


async def wait_for_service(
    job_id: int, base_url: str, service_id: str, *, note_phase: bool = True
) -> dict[str, Any]:
    """Polls the motion service until the render is done, writing its progress as the job's
    phase. Raises MotionRenderFailed when the service says it failed or does not finish in time.
    """
    limit_s = graphics_render.RENDER_TIME_LIMIT_S + graphics_render.BACKEND_EXTRA_WAIT_S
    deadline = time.monotonic() + limit_s
    shown = -PHASE_PERCENT_STEP
    while True:
        status = await motion_renderer.render_status(base_url, service_id)
        state = status.get("state")
        if state == "done":
            return status
        if state == "failed":
            reason = status.get("error")
            raise MotionRenderFailed(
                f"The motion service could not render the graphic: "
                f"{reason if isinstance(reason, str) and reason else 'no reason given'}"
            )
        if time.monotonic() > deadline:
            raise MotionRenderFailed(f"The motion service did not finish within {limit_s} s.")
        progress = status.get("progress")
        percent = int(float(progress) * 100) if isinstance(progress, int | float) else 0
        if note_phase and percent - shown >= PHASE_PERCENT_STEP:
            shown = percent
            await phase_writer.note(job_id, phases.rendering_graphic(percent))
        await asyncio.sleep(POLL_INTERVAL_S)
