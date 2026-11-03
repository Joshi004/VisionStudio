"""`/api/projects/{project_id}/graphics`: the graphics of the graphic shots of a continuous
explainer, both versions of each shot (EXG-005).

- `GET ...` answers everything the board panel shows for the stage in one call: each scene's
  graphic shots with where the graphics stand, the resolved brief they are drawn from (for the
  safe-area and caption-area overlays), the voice take with the time it has at the clip's first
  frame, and for each of the two versions every attempt with its video, jobs and checks. "Out of
  date" is worked out on every read.
- `POST .../{scene_id}/{shot_id}/run` makes what is missing for one shot (the pipeline's own start
  function): a new model call for a version that has nothing, the render again for an input with
  no video, and a new render of the input it already has for a video that is out of date (a new
  theme), which asks no model.
- `POST .../{scene_id}/{shot_id}/{engine}/ask-again` makes a new attempt of one version, with the
  same brief and a new model call.

The rows and the jobs are made by `app/services/shot_graphics.py`. The answers never return ORM
objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.graphics_lab import GraphicCallOut, GraphicResolvedOut
from app.api.jobs import JobSummary, job_summary
from app.api.projects import load_project
from app.db.models import Job, Project
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import graphics_lab, shot_graphics
from app.services.storage import media_url

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Not a continuous explainer with graphics on, the shot is not a graphic "
        "shot, the theme or the brief is missing or out of date, or a version is already being "
        "made.",
    }
}

EngineKey = Literal["generated_component", "remotion_blocks"]
Status = Literal["none", "writing", "rendering", "ready", "out_of_date", "failed"]
ShotStatus = Literal["none", "working", "ready", "out_of_date", "failed"]
BriefStatus = Literal["none", "writing", "ready", "failed", "out_of_date"]


class ShotGraphicAttemptOut(BaseModel):
    """One attempt of one version: what it draws from, the jobs, the video and the checks."""

    id: int
    created_at: datetime
    # The attempts of one version of a shot are numbered from 1.
    attempt: int
    # The video is drawn from what is current now (the theme, the timing and the size).
    current: bool
    # `writing` or `rendering` while a job of the attempt is waiting or running.
    stage: Literal["writing", "rendering"] | None
    # The component code or the block scene, and the model call that wrote it. None until then.
    input: Any | None
    input_job: JobSummary | None
    # The time, attempts and tokens of that call. None while it has none, and for an attempt made
    # by a new theme, which asks no model.
    input_call: GraphicCallOut | None
    render_job: JobSummary | None
    # The finished video, from /media. None until the render job has stored it.
    url: str | None
    metrics: Any | None
    warnings: Any | None
    # Why it has no video, or None.
    last_error: str | None
    # A component that has no video and that nothing more will be tried for.
    failed_outright: bool
    # The attempt whose input this one draws again for a new theme, or None.
    rerender_of: int | None
    # The attempt of a component whose render failed, which this one repairs, or None.
    repair_of: int | None


class ShotGraphicEngineOut(BaseModel):
    key: EngineKey
    label: str
    status: Status
    # A component that failed outright (no current video, nothing more will be tried).
    failed_outright: bool
    # Why the newest attempt has no video, or None.
    last_error: str | None
    # Newest first.
    attempts: list[ShotGraphicAttemptOut]


class ShotVoiceOut(BaseModel):
    """The scene's voice take, which the panel plays with the videos. The clips have no sound."""

    # From /media.
    url: str
    # The take's time at the first frame of the clip, in seconds. Negative for the first shot of
    # a scene, which starts inside the lead-in.
    offset_s: float


class ShotGraphicShotOut(BaseModel):
    id: str
    description: str
    # The shot's words and where it sits in the scene's take, in seconds.
    spoken_text: str
    start_s: float
    end_s: float
    status: ShotStatus
    # One sentence for each thing the videos were drawn for that has changed.
    reasons: list[str]
    # What went wrong for each version that has nothing usable, or None.
    last_error: str | None
    can_run: bool
    blocked_reason: str | None
    brief_id: int | None
    brief_version: int | None
    brief_status: BriefStatus
    # What code worked out from the brief, the theme, the take and the timeline. None when it
    # cannot be worked out now.
    resolved: GraphicResolvedOut | None
    voice: ShotVoiceOut | None
    # The generated component first, then the building blocks.
    engines: list[ShotGraphicEngineOut]


class ShotGraphicSceneOut(BaseModel):
    id: str
    index: int | None
    title: str
    blocked_reason: str | None
    shots: list[ShotGraphicShotOut]


class ShotGraphicsStateOut(BaseModel):
    scenes: list[ShotGraphicSceneOut]
    # Why nothing can be made for the project at all, or None.
    blocked_reason: str | None
    # False for a story and for an explainer with graphics off.
    wanted: bool
    # The version of the project's newest graphics look, and whether it is current.
    theme_version: int | None
    theme_current: bool


class ShotGraphicsRun(BaseModel):
    # The jobs started. Empty when the shot already has everything.
    job_ids: list[int]


class ShotGraphicAskRun(BaseModel):
    job_id: int


# --- Mapping ---------------------------------------------------------------------------------


def _job_out(job: Job | None, project: Project) -> JobSummary | None:
    if job is None:
        return None
    return job_summary(JobRow(job=job, project_name=store.owner_name(job, project.name)))


def _attempt_out(entry: shot_graphics.AttemptEntry, project: Project) -> ShotGraphicAttemptOut:
    row = entry.row
    call = graphics_lab.input_call_of(entry.input_job)
    rerender = row.inputs.get("rerender_of") if isinstance(row.inputs, dict) else None
    return ShotGraphicAttemptOut(
        id=row.id,
        created_at=row.created_at,
        attempt=row.attempt,
        current=entry.current,
        stage=cast(Literal["writing", "rendering"] | None, entry.stage),
        input=row.input,
        input_job=_job_out(entry.input_job, project),
        input_call=(
            GraphicCallOut(
                seconds=call.seconds,
                attempts=call.attempts,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                reasoning_tokens=call.reasoning_tokens,
            )
            if call is not None
            else None
        ),
        render_job=_job_out(entry.render_job, project),
        url=media_url(row.media_path) if row.media_path is not None else None,
        metrics=row.metrics,
        warnings=row.warnings,
        last_error=entry.error,
        failed_outright=row.failed_outright,
        rerender_of=rerender if isinstance(rerender, int) else None,
        repair_of=row.repair_of,
    )


def _engine_out(entry: shot_graphics.EngineEntry, project: Project) -> ShotGraphicEngineOut:
    return ShotGraphicEngineOut(
        key=cast(EngineKey, entry.key),
        label=entry.label,
        status=cast(Status, entry.status),
        failed_outright=entry.failed_outright,
        last_error=entry.last_error,
        attempts=[_attempt_out(attempt, project) for attempt in entry.attempts],
    )


def _shot_out(entry: shot_graphics.ShotEntry, project: Project) -> ShotGraphicShotOut:
    shot = entry.shot
    voice_url = shot_graphics.voice_url(entry)
    return ShotGraphicShotOut(
        id=shot["id"],
        description=shot["description"],
        spoken_text=shot["spoken_text"],
        start_s=shot["start_s"],
        end_s=shot["end_s"],
        status=cast(ShotStatus, entry.status),
        reasons=entry.reasons,
        last_error=entry.last_error,
        can_run=entry.can_run,
        blocked_reason=entry.blocked_reason,
        brief_id=entry.brief.id if entry.brief is not None else None,
        brief_version=entry.brief.version if entry.brief is not None else None,
        brief_status=cast(BriefStatus, entry.brief_status),
        resolved=(
            GraphicResolvedOut.model_validate(entry.resolved)
            if entry.resolved is not None
            else None
        ),
        voice=(
            ShotVoiceOut(url=voice_url, offset_s=entry.voice_offset_s)
            if voice_url is not None
            else None
        ),
        engines=[_engine_out(engine, project) for engine in entry.engines],
    )


async def _state(session: AsyncSession, project: Project) -> ShotGraphicsStateOut:
    state = await shot_graphics.state(session, project)
    return ShotGraphicsStateOut(
        scenes=[
            ShotGraphicSceneOut(
                id=scene.item["id"],
                index=scene.item.get("index"),
                title=str(scene.item.get("title", scene.item["id"])),
                blocked_reason=scene.blocked_reason,
                shots=[_shot_out(entry, project) for entry in scene.shots],
            )
            for scene in state.entries
            # A scene with no graphic shot has nothing to show.
            if scene.shots
        ],
        blocked_reason=state.blocked_reason,
        wanted=state.wanted,
        theme_version=state.theme_version,
        theme_current=state.theme_current,
    )


# --- Endpoints -------------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/graphics",
    response_model=ShotGraphicsStateOut,
    responses=_NOT_FOUND,
)
async def get_shot_graphics(project_id: int, session: SessionDep) -> ShotGraphicsStateOut:
    return await _state(session, await load_project(session, project_id))


@router.post(
    "/projects/{project_id}/graphics/{scene_id}/{shot_id}/run",
    response_model=ShotGraphicsRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_shot_graphics(
    project_id: int, scene_id: DiscoveryId, shot_id: DiscoveryId, session: SessionDep
) -> ShotGraphicsRun:
    """Makes what is missing for one graphic shot. A version that has a current video, or that
    failed outright, is left alone (a shot that has everything starts no job). A shot whose
    graphics are being made is refused with 422.
    """
    project = await load_project(session, project_id)
    try:
        jobs = await shot_graphics.start_shot(session, project, scene_id, shot_id)
    except shot_graphics.ShotGraphicsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return ShotGraphicsRun(job_ids=[job.id for job in jobs])


@router.post(
    "/projects/{project_id}/graphics/{scene_id}/{shot_id}/{engine}/ask-again",
    response_model=ShotGraphicAskRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def ask_shot_graphic_again(
    project_id: int,
    scene_id: DiscoveryId,
    shot_id: DiscoveryId,
    engine: EngineKey,
    session: SessionDep,
) -> ShotGraphicAskRun:
    """A paid model call: makes one version again as a new attempt, from the same brief."""
    project = await load_project(session, project_id)
    try:
        job = await shot_graphics.ask_again(session, project, scene_id, shot_id, engine)
    except shot_graphics.ShotGraphicsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return ShotGraphicAskRun(job_id=job.id)
