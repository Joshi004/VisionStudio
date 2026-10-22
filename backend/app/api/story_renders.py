"""`/api/projects/{project_id}/story-renders`: the story's finished video (PHASE-028).

- `GET ...` answers everything the story workspace shows in one call: whether the story can be
  rendered now and why not, what the next render would warn about, the newest render job, and
  every finished render (newest first) with the video's address, what it measured, the takes it
  was made from, the loudness that was applied, and whether it is `current` or `out_of_date` (and
  why). Out of date is worked out on every read.
- `POST .../run` ("Render") starts the `render_story` job with the timeline as it is now. If a
  render is already waiting or running, that job is returned and no second one is made.

A render is stored only when it succeeds (`services/story_renders.py`). The answers never return
ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.discovery import DiscoveryJobOut
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Job
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import storage, story_renders
from app.services.story_renders import RenderEntry

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The story cannot be rendered now: a scene's shots are not ready, a shot "
        "has no clip, or a clip or a speech file is missing or too short.",
    }
}

Status = Literal["current", "out_of_date"]
WarningCode = Literal["take_out_of_date", "take_without_sound"]


class RenderWarningOut(BaseModel):
    code: WarningCode
    scene_id: str
    shot_id: str
    message: str


class RenderTakeOut(BaseModel):
    """The take a render used for one shot."""

    scene_id: str
    scene_index: int
    shot_id: str
    take_id: int
    take_number: int
    frames: int
    # The loudness measured over the part of the clip the shot uses, and the gain applied.
    sound: str | None
    loudness_lufs: float | None
    gain_db: float | None


class RenderNarrationOut(BaseModel):
    units: int
    loudness_lufs: float | None
    gain_db: float | None


class StoryRenderOut(BaseModel):
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
    narration: RenderNarrationOut | None
    created_at: datetime
    job: DiscoveryJobOut | None


class StoryRendersOut(BaseModel):
    can_render: bool
    # Why Render may not be pressed, or None.
    blocked_reason: str | None
    # What the next render would warn about. Empty when it cannot be made.
    warnings: list[RenderWarningOut]
    # How long the next render would be, or None when it cannot be made.
    planned_frames: int | None
    fps: int
    planned_seconds: float | None
    # The newest render job, whatever its status.
    job: DiscoveryJobOut | None
    renders: list[StoryRenderOut]


class StoryRenderRunOut(BaseModel):
    job_id: int


def _job_out(job: Job | None) -> DiscoveryJobOut | None:
    if job is None:
        return None
    return DiscoveryJobOut(
        id=job.id,
        status=cast(JobStatus, job.status),
        phase=job.phase,
        error=job.error,
    )


def _warning_out(warning: dict[str, Any]) -> RenderWarningOut:
    return RenderWarningOut(
        code=warning["code"],
        scene_id=warning["scene_id"],
        shot_id=warning["shot_id"],
        message=warning["message"],
    )


def _takes_out(entry: RenderEntry) -> list[RenderTakeOut]:
    """The take of each shot, from what the render recorded (never from the shots now)."""
    row = entry.row
    levels = {
        (item.get("scene_id"), item.get("shot_id")): item
        for item in (row.levels or {}).get("shots", [])
        if isinstance(item, dict)
    }
    takes: list[RenderTakeOut] = []
    for shot in row.inputs.get("shots", []):
        level = levels.get((shot["scene_id"], shot["shot_id"]), {})
        takes.append(
            RenderTakeOut(
                scene_id=shot["scene_id"],
                scene_index=shot["scene_index"],
                shot_id=shot["shot_id"],
                take_id=shot["take_id"],
                take_number=shot["take_number"],
                frames=shot["frames"],
                sound=level.get("sound"),
                loudness_lufs=level.get("loudness_lufs"),
                gain_db=level.get("gain_db"),
            )
        )
    return takes


def _narration_out(entry: RenderEntry) -> RenderNarrationOut | None:
    narration = (entry.row.levels or {}).get("narration")
    if not isinstance(narration, dict):
        return None
    return RenderNarrationOut(
        units=narration["units"],
        loudness_lufs=narration.get("loudness_lufs"),
        gain_db=narration.get("gain_db"),
    )


def _render_out(entry: RenderEntry) -> StoryRenderOut:
    row = entry.row
    return StoryRenderOut(
        id=row.id,
        render_number=row.render_number,
        status=entry.status,
        reasons=entry.reasons,
        url=storage.media_url(row.path),
        duration_s=row.duration_s,
        frame_count=row.frame_count,
        width=row.width,
        height=row.height,
        size_bytes=row.size_bytes,
        has_audio=row.audio is not None,
        warnings=[_warning_out(item) for item in row.inputs.get("warnings", [])],
        takes=_takes_out(entry),
        narration=_narration_out(entry),
        created_at=row.created_at,
        job=_job_out(entry.job),
    )


@router.get(
    "/projects/{project_id}/story-renders",
    response_model=StoryRendersOut,
    responses=_NOT_FOUND,
)
async def get_story_renders(project_id: int, session: SessionDep) -> StoryRendersOut:
    project = await load_project(session, project_id)
    result = await story_renders.state(session, project)
    return StoryRendersOut(
        can_render=result.can_render,
        blocked_reason=result.blocked_reason,
        warnings=[_warning_out(item) for item in result.warnings],
        planned_frames=result.planned_frames,
        fps=result.fps,
        planned_seconds=(
            round(result.planned_frames / result.fps, 3)
            if result.planned_frames is not None
            else None
        ),
        job=_job_out(result.job),
        renders=[_render_out(entry) for entry in result.renders],
    )


@router.post(
    "/projects/{project_id}/story-renders/run",
    response_model=StoryRenderRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_render(project_id: int, session: SessionDep) -> StoryRenderRunOut:
    """Starts the job that renders the story. If a render is already waiting or running, that
    job's id is returned and no second render is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await story_renders.start_render(session, project)
    except story_renders.StoryRendersError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return StoryRenderRunOut(job_id=job.id)
