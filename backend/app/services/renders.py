"""The final render in the database (ANALYSIS.md Section 5.5, 5.6 and 8; DATABASE_STRUCTURE.md
Section 4.2, 4.5 and 7).

A render is a `render_final` job, and its result is an `asset` (`kind='final'`). There is no
render table: every earlier render stays, as a succeeded job with its asset, the same way
a clip's takes do.

**The timeline.** The click that starts a render builds the *timeline description* of
Section 8 ("Render from a timeline description"): the ordered clips with their frame
counts and sound switches, the voiceover and the clip sound volume. It is stored on the job
(`job.input.timeline`), and the handler reads nothing else. A cut edit, another take or a new
volume after the click does not change that render, and a restart renders the same timeline
again. A future timeline editor would write this same description.

This module holds the pure rules (`render_block`, `selected_takes`, `build_timeline`) and
the read of the finished renders. It never runs FFmpeg: `app/jobs/render_final.py` does.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, Job, Project, Scene
from app.jobs import store
from app.services import clips, frame_counts

RENDER_JOB: Final = "render_final"
# The shape of `job.input.timeline`. The handler refuses a timeline it does not know.
TIMELINE_VERSION: Final = 1


@dataclass(frozen=True)
class Render:
    """One finished render: the job that made it and the final video it produced."""

    job: Job
    asset: Asset


def selected_takes(
    scenes: Sequence[Scene], takes: dict[int, list[clips.Take]]
) -> dict[int, clips.Take]:
    """The take each scene has selected, by scene id. A scene with no selected take, or
    whose selection is not one of its finished clips, is left out.
    """
    chosen: dict[int, clips.Take] = {}
    for scene in scenes:
        if scene.selected_clip_asset_id is None:
            continue
        for take in takes.get(scene.id, []):
            if take.asset.id == scene.selected_clip_asset_id:
                chosen[scene.id] = take
                break
    return chosen


def _numbers(scenes: Sequence[Scene]) -> str:
    """Scene numbers as the user sees them (from 1): "4", "3 and 4", "1, 6 and 7"."""
    numbers = [str(scene.index + 1) for scene in scenes]
    if len(numbers) == 1:
        return numbers[0]
    return f"{', '.join(numbers[:-1])} and {numbers[-1]}"


def _frame_count(take: clips.Take) -> int | None:
    count = take.provenance.get("frame_count")
    return count if isinstance(count, int) and not isinstance(count, bool) else None


def _is_silent_scene(scene: Scene, project: Project) -> bool:
    """A scene shorter than one frame on the fps grid takes no time in the video, so it
    needs no clip (and Generate refuses it anyway).
    """
    return clips.target_frames_for(scene, project) < 1


def render_block(
    project: Project,
    scenes: Sequence[Scene],
    selected: dict[int, clips.Take],
    *,
    plan_job: Job | None,
    stale_reasons: Sequence[str],
) -> str | None:
    """Why the project cannot be rendered now, or None when it can. Pure.

    The one rule behind the Render button and the endpoint. A selected take that is out of
    date but still long enough is not a reason: it covers the scene.
    """
    if project.voiceover_asset_id is None:
        return "Upload a voiceover first."
    if not scenes:
        return "There are no scenes yet. Propose scenes first."
    if plan_job is not None and plan_job.status in store.ACTIVE_STATUSES:
        return "A scene proposal is in progress. Wait for it to finish."
    if stale_reasons:
        return "The scenes are out of date. Propose scenes again before rendering."

    needed = [scene for scene in scenes if not _is_silent_scene(scene, project)]
    without_clip = [scene for scene in needed if scene.id not in selected]
    if without_clip:
        verb = "has" if len(without_clip) == 1 else "have"
        noun = "Scene" if len(without_clip) == 1 else "Scenes"
        return f"{noun} {_numbers(without_clip)} {verb} no clip yet."

    too_short: list[tuple[Scene, int, int]] = []
    for scene in needed:
        have = _frame_count(selected[scene.id])
        want = clips.target_frames_for(scene, project)
        if have is not None and have < want:
            too_short.append((scene, have, want))
    if len(too_short) == 1:
        scene, have, want = too_short[0]
        return (
            f"The clip of scene {scene.index + 1} has {have} frames; the scene now needs "
            f"{want}. Regenerate it, or use another take."
        )
    if too_short:
        details = ", ".join(
            f"scene {scene.index + 1}: {have} of {want} frames" for scene, have, want in too_short
        )
        return (
            f"The clips of scenes {_numbers([scene for scene, _h, _w in too_short])} are "
            f"shorter than their scenes now need ({details}). Regenerate them, or use other "
            "takes."
        )
    return None


def build_timeline(
    project: Project,
    scenes: Sequence[Scene],
    selected: dict[int, clips.Take],
    voiceover: Asset,
) -> dict[str, Any]:
    """The timeline description of a render (ANALYSIS.md Section 8). Pure.

    Each scene lasts `frame_counts.target_frames` frames, so the frames add up to the last
    boundary and the video is as long as the voiceover to within one frame (Section 5.5).
    The caller has checked `render_block`.
    """
    fps = project.fps
    entries: list[dict[str, Any]] = []
    total = 0
    for scene in scenes:
        frames = clips.target_frames_for(scene, project)
        if frames < 1:
            continue
        entries.append(
            {
                "scene_id": scene.id,
                "scene_index": scene.index,
                "start_s": scene.start_s,
                "end_s": scene.end_s,
                "start_frame": frame_counts.boundary_frame(scene.start_s, fps),
                "frames": frames,
                "asset_id": selected[scene.id].asset.id,
                "clip_sound": scene.use_clip_sound,
            }
        )
        total += frames
    return {
        "version": TIMELINE_VERSION,
        "fps": fps,
        "width": project.out_width,
        "height": project.out_height,
        "clip_sound_volume": project.clip_sound_volume,
        "voiceover": {"asset_id": voiceover.id, "duration_s": voiceover.duration_s},
        "total_frames": total,
        "clips": entries,
    }


async def active_render(session: AsyncSession, project_id: int) -> Job | None:
    """The project's render that is queued or running, if there is one."""
    statement = (
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.type == RENDER_JOB,
            Job.status.in_(store.ACTIVE_STATUSES),
        )
        .order_by(Job.id)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def list_renders(session: AsyncSession, project_id: int) -> list[Render]:
    """The finished renders of a project, newest first, in one query."""
    statement = (
        select(Job, Asset)
        .join(Asset, Asset.id == Job.result_asset_id)
        .where(
            Job.project_id == project_id,
            Job.type == RENDER_JOB,
            Job.status == "succeeded",
            Asset.kind == "final",
        )
        .order_by(Job.id.desc())
        .execution_options(populate_existing=True)
    )
    return [Render(job=job, asset=asset) for job, asset in (await session.execute(statement)).all()]
