"""`/api/projects/{project_id}/graphic-briefs`: the briefs of the graphic shots of a continuous
explainer (EXG-004).

- `GET ...` answers everything the board panel shows for the stage in one call: each scene's
  graphic shots with their words, the sentences around them, where the newest brief stands (and
  why it is out of date), the newest job and the brief itself. "Out of date" is worked out on
  every read.
- `POST .../{scene_id}/{shot_id}/run` starts the `write_shot_graphic_brief` job of one shot: one
  model call writes the brief. The body may hold `feedback`, the owner's note on the newest brief.

The rows and the job are made by `app/services/shot_graphic_briefs.py`. The answers never return
ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import shot_graphic_briefs, user_feedback

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Not a continuous explainer with graphics on, the Story Bible is missing, "
        "the scene's shots are not planned and current, the shot is not a graphic shot, or the "
        "note cannot be used.",
    }
}

Status = Literal["none", "writing", "ready", "failed", "out_of_date"]
Kind = Literal["kpi", "comparison", "trend", "process", "list", "statement", "concept"]
Unit = Literal["usd", "percent", "points", "multiple", "count", "none"]
Scale = Literal["none", "thousand", "million", "billion", "trillion"]
Op = Literal["pct_change", "difference", "ratio", "sum"]


# --- What the brief holds --------------------------------------------------------------------


class BriefFactOut(BaseModel):
    id: str
    label: str
    value: float
    unit: Unit
    scale: Scale
    said_as: str


class BriefDerivedOut(BaseModel):
    id: str
    label: str
    op: Op
    of: list[str]


class BriefBeatOut(BaseModel):
    id: str
    phrase: str
    shows: str
    refs: list[str]
    # The second the beat starts, counted from the start of the shot. None when it cannot be
    # worked out.
    at_s: float | None


class BriefContent(BaseModel):
    kind: Kind
    intent: str
    visual_brief: str
    facts: list[BriefFactOut]
    derived: list[BriefDerivedOut]
    beats: list[BriefBeatOut]


class BriefOut(BaseModel):
    id: int
    version: int
    source: Literal["ai", "manual"]
    job_id: int | None
    created_at: datetime
    # The owner's note this version was made with, or None.
    feedback: str | None
    content: BriefContent


class BriefJobOut(BaseModel):
    """The newest `write_shot_graphic_brief` job of the shot, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class GraphicShotOut(BaseModel):
    id: str
    description: str
    # The shot's words and where it sits in the scene's take, in seconds.
    spoken_text: str
    start_s: float
    end_s: float
    # The sentences around the shot that a number may be said in, as the take reads now. Empty
    # when the take is not ready.
    words_before: str
    words_after: str
    status: Status
    # One sentence for each thing the newest brief was built from that has changed.
    reasons: list[str]
    # Why the newest job made no brief newer than the newest one, or None.
    last_error: str | None
    can_run: bool
    blocked_reason: str | None
    job: BriefJobOut | None
    brief: BriefOut | None


class GraphicBriefSceneOut(BaseModel):
    id: str
    index: int | None
    title: str
    blocked_reason: str | None
    shots: list[GraphicShotOut]


class GraphicBriefsState(BaseModel):
    scenes: list[GraphicBriefSceneOut]
    # Why no brief can be written yet (or at all for this project), or None.
    blocked_reason: str | None
    # False for a story and for an explainer with graphics off.
    wanted: bool


class GraphicBriefRun(BaseModel):
    job_id: int


class GraphicBriefRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The owner's note on the newest brief. `user_feedback.clean` checks it again.
    feedback: str | None = Field(default=None, max_length=user_feedback.MAX_CHARS)


# --- Mapping ---------------------------------------------------------------------------------


def _brief_out(entry: shot_graphic_briefs.ShotEntry) -> BriefOut | None:
    row = entry.row
    if row is None:
        return None
    content: dict[str, Any] = dict(row.content)
    beats = [
        {**beat, "at_s": entry.beat_times.get(beat["id"])} for beat in content.get("beats", [])
    ]
    return BriefOut(
        id=row.id,
        version=row.version,
        source=cast(Literal["ai", "manual"], row.source),
        job_id=row.job_id,
        created_at=row.created_at,
        feedback=user_feedback.text_of(row.inputs),
        content=BriefContent.model_validate({**content, "beats": beats}),
    )


def _shot_out(entry: shot_graphic_briefs.ShotEntry) -> GraphicShotOut:
    shot = entry.shot
    job = entry.job
    context = entry.context
    return GraphicShotOut(
        id=shot["id"],
        description=shot["description"],
        spoken_text=shot["spoken_text"],
        start_s=shot["start_s"],
        end_s=shot["end_s"],
        words_before=context.before if context is not None else "",
        words_after=context.after if context is not None else "",
        status=cast(Status, entry.status),
        reasons=entry.reasons,
        last_error=entry.last_error,
        can_run=entry.can_run,
        blocked_reason=entry.blocked_reason,
        job=(
            BriefJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        brief=_brief_out(entry),
    )


async def _state(session: AsyncSession, project: Project) -> GraphicBriefsState:
    state = await shot_graphic_briefs.state(session, project)
    return GraphicBriefsState(
        scenes=[
            GraphicBriefSceneOut(
                id=scene.item["id"],
                index=scene.item.get("index"),
                title=str(scene.item.get("title", scene.item["id"])),
                blocked_reason=scene.blocked_reason,
                shots=[_shot_out(entry) for entry in scene.shots],
            )
            for scene in state.entries
            # A scene with no graphic shot has nothing to show.
            if scene.shots
        ],
        blocked_reason=state.blocked_reason,
        wanted=state.wanted,
    )


# --- Endpoints -------------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/graphic-briefs",
    response_model=GraphicBriefsState,
    responses=_NOT_FOUND,
)
async def get_graphic_briefs(project_id: int, session: SessionDep) -> GraphicBriefsState:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/graphic-briefs/{scene_id}/{shot_id}/run",
    response_model=GraphicBriefRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_graphic_brief(
    project_id: int,
    scene_id: DiscoveryId,
    shot_id: DiscoveryId,
    session: SessionDep,
    body: GraphicBriefRunIn | None = None,
) -> GraphicBriefRun:
    """Starts the job that writes the brief of one graphic shot. If the shot already has a job
    waiting or running, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await shot_graphic_briefs.start_shot(
            session,
            project,
            scene_id,
            shot_id,
            feedback=body.feedback if body is not None else None,
        )
    except shot_graphic_briefs.ShotGraphicBriefError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return GraphicBriefRun(job_id=job.id)
