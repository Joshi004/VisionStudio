"""The final render (Phase 10; ANALYSIS.md Section 3.3, 3.4 and 5.6).

`POST /api/projects/{id}/render` creates a `render_final` job and returns at once with HTTP
202. The job's input is the *timeline* built from the scenes as they are at this moment
(which clip, how many frames, which clip sound), so nothing that changes afterwards affects
that render. The dispatcher does the work, limited by "maximum parallel FFmpeg runs".

`GET /api/projects/{id}/renders` reads the database only: the newest render job (whatever its
status) and every finished render, newest first. A finished render stays when the next one
is made.

Only a queued render can be cancelled (`POST /api/jobs/{id}/cancel`): a running one is a few
FFmpeg runs on this machine, and ends by itself.

Like Generate, the start takes the database's write lock before it reads the scenes
(`scenes_service.lock_scenes`), so a cut edit that is running cannot change a scene between
the check and the job.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.api.projects import load_project
from app.db.models import Asset
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import clips as clips_service
from app.services import renders as renders_service
from app.services import scenes as scenes_service
from app.services.storage import media_url

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No project has this id."}}
_BLOCKED = {
    422: {
        "model": ErrorResponse,
        "description": "The project cannot be rendered now: there is no voiceover or no scene, "
        "a scene has no clip or its clip is too short, or the scenes are out of date or "
        "being replaced.",
    }
}


class RenderOut(BaseModel):
    """One finished render (a succeeded `render_final` job and its `final` asset)."""

    asset_id: int
    job_id: int
    # The video's file, served from /media (with Range requests, so it seeks).
    url: str
    created_at: datetime
    duration_s: float | None
    width: int | None
    height: int | None
    size_bytes: int
    # What this render was made with (from the timeline stored on the job).
    clip_sound_volume: float | None
    scene_count: int
    # Scenes whose own clip sound was switched off for this render.
    muted_scene_count: int


class RendersOut(BaseModel):
    # The newest render job, whatever its status. None if there never was one.
    job: JobSummary | None
    renders: list[RenderOut]


def _render_out(render: renders_service.Render) -> RenderOut:
    recorded: Any = render.asset.provenance if isinstance(render.asset.provenance, dict) else {}
    volume = recorded.get("clip_sound_volume")
    has_volume = isinstance(volume, int | float) and not isinstance(volume, bool)
    clip_ids = recorded.get("clip_asset_ids")
    muted = recorded.get("muted_scene_indexes")
    return RenderOut(
        asset_id=render.asset.id,
        job_id=render.job.id,
        url=media_url(render.asset.path),
        created_at=render.asset.created_at,
        duration_s=render.asset.duration_s,
        width=render.asset.width,
        height=render.asset.height,
        size_bytes=render.asset.size_bytes,
        clip_sound_volume=float(volume) if has_volume else None,
        scene_count=len(clip_ids) if isinstance(clip_ids, list) else 0,
        muted_scene_count=len(muted) if isinstance(muted, list) else 0,
    )


@router.post(
    "/projects/{project_id}/render",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def start_render(project_id: int, session: SessionDep) -> JobDetail:
    """Starts rendering the final video from the selected take of every scene, or returns
    the render that is already queued or running (two quick clicks make one job).
    """
    project = await load_project(session, project_id)
    await scenes_service.lock_scenes(session, project.id)
    await session.refresh(project)

    active = await renders_service.active_render(session, project.id)
    if active is not None:
        await session.commit()
        return job_detail(JobRow(job=active, project_name=project.name, scene_index=None))

    state = await scenes_service.scenes_state(session, project)
    takes = await clips_service.takes_by_scene(session, project.id)
    selected = renders_service.selected_takes(state.scenes, takes)
    block = renders_service.render_block(
        project,
        state.scenes,
        selected,
        plan_job=state.job,
        stale_reasons=state.stale_reasons,
    )
    voiceover = (
        await session.get(Asset, project.voiceover_asset_id)
        if project.voiceover_asset_id is not None
        else None
    )
    if block is not None or voiceover is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, block or "Upload a voiceover first."
        )

    timeline = renders_service.build_timeline(project, state.scenes, selected, voiceover)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=renders_service.RENDER_JOB,
        provider="local",
        input={"requested": "render", "timeline": timeline},
    )
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=None))


@router.get(
    "/projects/{project_id}/renders",
    response_model=RendersOut,
    responses=_NOT_FOUND,
)
async def get_renders(project_id: int, session: SessionDep) -> RendersOut:
    """The project's newest render job and its finished renders. Reads the database only."""
    project = await load_project(session, project_id)
    job = await store.latest_job(session, project.id, renders_service.RENDER_JOB)
    finished = await renders_service.list_renders(session, project.id)
    return RendersOut(
        job=(
            job_summary(JobRow(job=job, project_name=project.name, scene_index=None))
            if job is not None
            else None
        ),
        renders=[_render_out(render) for render in finished],
    )
