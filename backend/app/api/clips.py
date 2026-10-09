"""Clip generation (Phase 9; ANALYSIS.md Section 3.3, 3.4 and 5.3).

`POST .../scenes/{id}/generate` creates a `generate_clip` job and returns at once with HTTP
202. `POST .../generate-ready-scenes` does the same for every scene that is ready and has no
clip yet. The dispatcher does the work: it starts the jobs while fewer than the "maximum
parallel clip generations" setting are running.

`POST .../scenes/{id}/select-take` makes one of a scene's finished clips the one the final
video uses, `PUT .../scenes/{id}/clip-sound` switches the scene's own clip sound on or off and
`PUT .../scenes/{id}/video-model` sets (or clears) the scene's own video model. All three
answer with the scenes as they are afterwards (`ScenesOut`), so the page shows the change
without another request.

`generate` may carry a `video_model`: the model for that one take (the Regenerate picker). It
is kept in `job.input`, and the job works out the rest (`jobs/generate_clip.py`).

Cancelling a clip job is `POST /api/jobs/{id}/cancel` (`api/jobs.py`), which also cancels it on
the GPU server.

Every endpoint that reads the scenes and then creates a job takes the database's write lock
first (`scenes_service.lock_scenes`), like a cut edit does, so a cut edit that is running
cannot change a scene between the check and the job.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.api.projects import load_project
from app.api.scenes import ScenesOut, scenes_out
from app.db.models import Project, Scene
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import clips as clips_service
from app.services import scenes as scenes_service
from app.services.video_models import VideoModel

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No project or scene has this id."}}
_BLOCKED = {
    422: {
        "model": ErrorResponse,
        "description": "A clip cannot be generated now: the scene is not ready, is longer than "
        "the project's maximum, or the scenes are out of date or being replaced.",
    }
}

AssetId = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]


class SelectTakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The `asset_id` of one of the scene's finished clips (a take).
    asset_id: AssetId


class ClipSoundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_clip_sound: StrictBool


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The video model for this one take. Left out, the scene's own choice, the project's or the
    # app's default is used. Nothing is saved: the scene keeps its own choice.
    video_model: VideoModel | None = None


class VideoModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The scene's own video model, or `null` to use the project's (and then the app's).
    video_model: VideoModel | None


class GenerateReadyOut(BaseModel):
    # The jobs that were created, in scene order. Empty when no scene needed one.
    jobs: list[JobSummary]
    created: int


def _scene_missing(scene_id: int) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND, f"Scene {scene_id} does not exist in this project."
    )


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


async def _locked_state(session: AsyncSession, project: Project) -> scenes_service.ScenesState:
    """Takes the write lock, then reads the scenes: what is read cannot change before the
    commit that follows.
    """
    await scenes_service.lock_scenes(session, project.id)
    await session.refresh(project)
    return await scenes_service.scenes_state(session, project)


def _find_scene(state: scenes_service.ScenesState, scene_id: int) -> Scene | None:
    return next((scene for scene in state.scenes if scene.id == scene_id), None)


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/generate",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def generate_clip(
    project_id: int,
    scene_id: int,
    session: SessionDep,
    body: GenerateRequest | None = None,
) -> JobDetail:
    """Starts generating a clip for the scene (Generate, and Regenerate when it has one).

    A scene that already has a clip being generated returns that job: two quick clicks make
    one job. Each new job gets its own random seed, so it makes a new take. The optional
    `video_model` makes this one take with that model.
    """
    project = await load_project(session, project_id)
    state = await _locked_state(session, project)
    scene = _find_scene(state, scene_id) if 1 <= scene_id <= _MAX_ID else None
    if scene is None:
        raise _scene_missing(scene_id)

    active = (await clips_service.active_clip_jobs(session, project.id)).get(scene.id)
    if active is None:
        scenes_blocked = clips_service.scenes_block_reason(state.job, state.stale_reasons)
        block = clips_service.generation_block(
            scene, project, scenes_blocked=scenes_blocked, active=None
        )
        if block is not None:
            raise _unprocessable(block)

    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=clips_service.GENERATE_JOB,
        provider="gpu",
        scene_id=scene.id,
        input=(
            {"requested": "generate", "video_model": body.video_model}
            if body is not None and body.video_model is not None
            else {"requested": "generate"}
        ),
    )
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=scene.index))


@router.post(
    "/projects/{project_id}/generate-ready-scenes",
    response_model=GenerateReadyOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def generate_ready_scenes(project_id: int, session: SessionDep) -> GenerateReadyOut:
    """Starts a clip for every scene that is ready, has no clip yet and has no job running.

    All the jobs are created in one transaction. The page asks before calling this, and it
    shows how many it will start (`ScenesOut.generate_ready_count`).
    """
    project = await load_project(session, project_id)
    state = await _locked_state(session, project)
    scenes_blocked = clips_service.scenes_block_reason(state.job, state.stale_reasons)
    if scenes_blocked is not None:
        raise _unprocessable(scenes_blocked)

    active = await clips_service.active_clip_jobs(session, project.id)
    created: list[JobSummary] = []
    for scene in state.scenes:
        if not clips_service.is_generate_all_candidate(
            scene, project, scenes_blocked=None, active=active.get(scene.id)
        ):
            continue
        job, was_created = await store.create_job(
            session,
            project_id=project.id,
            type=clips_service.GENERATE_JOB,
            provider="gpu",
            scene_id=scene.id,
            input={"requested": "generate_all"},
            commit=False,
        )
        if was_created:
            created.append(
                job_summary(JobRow(job=job, project_name=project.name, scene_index=scene.index))
            )
    await session.commit()
    if created:
        dispatcher.nudge()
    return GenerateReadyOut(jobs=created, created=len(created))


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/select-take",
    response_model=ScenesOut,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No project or scene has this id, or the asset is not a finished "
            "clip of this scene.",
        }
    },
)
async def select_take(
    project_id: int, scene_id: int, body: SelectTakeRequest, session: SessionDep
) -> ScenesOut:
    """Makes one of the scene's finished clips the one the final video uses."""
    project = await load_project(session, project_id)
    if not 1 <= scene_id <= _MAX_ID:
        raise _scene_missing(scene_id)
    try:
        await clips_service.select_take(session, project.id, scene_id, body.asset_id)
    except clips_service.SceneGone:
        raise _scene_missing(scene_id) from None
    except clips_service.TakeNotFound:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Asset {body.asset_id} is not a finished clip of this scene.",
        ) from None
    return await scenes_out(session, project)


@router.put(
    "/projects/{project_id}/scenes/{scene_id}/clip-sound",
    response_model=ScenesOut,
    responses=_NOT_FOUND,
)
async def set_clip_sound(
    project_id: int, scene_id: int, body: ClipSoundRequest, session: SessionDep
) -> ScenesOut:
    """Switches the scene's own clip sound on or off for the final video (Phase 10 reads it)."""
    project = await load_project(session, project_id)
    if not 1 <= scene_id <= _MAX_ID:
        raise _scene_missing(scene_id)
    try:
        await clips_service.set_clip_sound(session, project.id, scene_id, body.use_clip_sound)
    except clips_service.SceneGone:
        raise _scene_missing(scene_id) from None
    return await scenes_out(session, project)


@router.put(
    "/projects/{project_id}/scenes/{scene_id}/video-model",
    response_model=ScenesOut,
    responses=_NOT_FOUND,
)
async def set_video_model(
    project_id: int, scene_id: int, body: VideoModelRequest, session: SessionDep
) -> ScenesOut:
    """Sets the scene's own video model, or clears it (`null`) to use the project's. It
    changes the clips generated from now on, not the ones already made.
    """
    project = await load_project(session, project_id)
    if not 1 <= scene_id <= _MAX_ID:
        raise _scene_missing(scene_id)
    try:
        await clips_service.set_video_model(session, project.id, scene_id, body.video_model)
    except clips_service.SceneGone:
        raise _scene_missing(scene_id) from None
    return await scenes_out(session, project)
