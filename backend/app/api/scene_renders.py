"""`/api/projects/{project_id}/scene-renders`: one scene's video (SCN-003).

- `GET ...` answers, for every scene of the story in story order, everything the story workspace
  shows in one call: whether the scene can be rendered now and why not, how many shots would show
  a placeholder, what the next render would warn about, whether it would have music (and why not),
  the newest scene render job, and every finished render of the scene (newest first) with the
  video's address, the takes it was made from, and whether it is `current` or `out_of_date` (and
  why). Out of date is worked out on every read.
- `POST .../{scene_id}/run` ("Render scene") starts the `render_scene` job with the scene's
  timeline as it is now. If a render of that scene is already waiting or running, that job is
  returned and no second one is made.

A scene render is stored only when it succeeds (`services/scene_renders.py`) and is a different
thing from the story's full render. The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.discovery import DiscoveryJobOut
from app.api.errors import ErrorResponse
from app.api.projects import load_project
from app.api.story_renders import (
    RenderMasterOut,
    RenderMusicOut,
    RenderNarrationOut,
    RenderTakeOut,
    RenderWarningOut,
    job_out,
    master_out,
    music_out,
    narration_out,
    takes_out,
    warning_out,
)
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import scene_renders, storage
from app.services.scene_renders import SceneRenderEntry, SceneRenderState

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The scene cannot be rendered now: it has no such scene, its shots are "
        "not ready, a clip is too short, or a speech file is missing.",
    }
}

Status = Literal["current", "out_of_date"]


class SceneRenderOut(BaseModel):
    id: int
    render_number: int
    status: Status
    # Why the render is out of date, one sentence each. Empty when it is current.
    reasons: list[str]
    url: str
    duration_s: float | None
    frame_count: int | None
    width: int | None
    height: int | None
    size_bytes: int
    has_audio: bool
    warnings: list[RenderWarningOut]
    takes: list[RenderTakeOut]
    # How many shots of the render are placeholders.
    placeholders: int
    narration: RenderNarrationOut | None
    music: RenderMusicOut | None
    master: RenderMasterOut | None
    created_at: datetime
    job: DiscoveryJobOut | None


class SceneRenderStateOut(BaseModel):
    scene_id: str
    index: int
    title: str
    can_render: bool
    # Why Render scene may not be pressed, or None.
    blocked_reason: str | None
    # What the next render of the scene would warn about. Empty when it cannot be made.
    warnings: list[RenderWarningOut]
    # How long the next render would be, or None when it cannot be made.
    planned_frames: int | None
    planned_seconds: float | None
    # How many shots the next render would show as a placeholder.
    placeholders: int
    # The music placement version the next render would use, or None when it has no music.
    music_placement_version: int | None
    # Why the next render has no music although the project wants it, or None.
    no_music_reason: str | None
    # The newest render job of this scene, whatever its status.
    job: DiscoveryJobOut | None
    renders: list[SceneRenderOut]


class SceneRendersOut(BaseModel):
    fps: int
    scenes: list[SceneRenderStateOut]


class SceneRenderRunOut(BaseModel):
    job_id: int


def _render_out(entry: SceneRenderEntry) -> SceneRenderOut:
    row = entry.row
    takes = takes_out(row)
    return SceneRenderOut(
        id=row.id,
        render_number=row.render_number,
        status=cast(Status, entry.status),
        reasons=entry.reasons,
        url=storage.media_url(row.path),
        duration_s=row.duration_s,
        frame_count=row.frame_count,
        width=row.width,
        height=row.height,
        size_bytes=row.size_bytes,
        has_audio=row.audio is not None,
        warnings=[warning_out(item) for item in row.inputs.get("warnings", [])],
        takes=takes,
        placeholders=sum(1 for take in takes if take.placeholder),
        narration=narration_out(row),
        music=music_out(row),
        master=master_out(row),
        created_at=row.created_at,
        job=job_out(entry.job),
    )


def _scene_out(scene: SceneRenderState, fps: int) -> SceneRenderStateOut:
    return SceneRenderStateOut(
        scene_id=scene.scene_id,
        index=scene.index,
        title=scene.title,
        can_render=scene.can_render,
        blocked_reason=scene.blocked_reason,
        warnings=[warning_out(item) for item in scene.warnings],
        planned_frames=scene.planned_frames,
        planned_seconds=(
            round(scene.planned_frames / fps, 3) if scene.planned_frames is not None else None
        ),
        placeholders=scene.placeholders,
        music_placement_version=scene.music_placement_version,
        no_music_reason=scene.no_music_reason,
        job=job_out(scene.job),
        renders=[_render_out(entry) for entry in scene.renders],
    )


@router.get(
    "/projects/{project_id}/scene-renders",
    response_model=SceneRendersOut,
    responses=_NOT_FOUND,
)
async def get_scene_renders(project_id: int, session: SessionDep) -> SceneRendersOut:
    project = await load_project(session, project_id)
    result = await scene_renders.state(session, project)
    return SceneRendersOut(
        fps=result.fps,
        scenes=[_scene_out(scene, result.fps) for scene in result.scenes],
    )


@router.post(
    "/projects/{project_id}/scene-renders/{scene_id}/run",
    response_model=SceneRenderRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_scene_render(
    project_id: int, scene_id: str, session: SessionDep
) -> SceneRenderRunOut:
    """Starts the job that renders one scene. If a render of that scene is already waiting or
    running, that job's id is returned and no second render is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await scene_renders.start_render(session, project, scene_id)
    except scene_renders.SceneRendersError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return SceneRenderRunOut(job_id=job.id)
