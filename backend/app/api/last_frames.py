"""Last frames (Phase 23; ANALYSIS.md Section 4.2 and 6.2).

`POST .../generate-last-frames` creates one `generate_last_frame` job for every scene that has a
current last frame prompt and a first frame, and no last frame or an AI last frame that is out of
date, and `POST .../scenes/{id}/generate-last-frame` creates one for a single scene. Each job is
one image made by Qwen-Image-2.1's edit endpoint on the GPU server (it edits the scene's first
frame), so it only ever runs from one of these clicks (or the automatic run), and the page shows
the number of images first. Both return at once with HTTP 202. The dispatcher does the work, at
most "maximum parallel image generations" at a time.

A last frame the author uploaded is never replaced by "all". The one-scene endpoint replaces it
only when the request says `replace_upload` (it answers 409 until then), and the upload stays
among the scene's earlier last frames. `POST .../scenes/{id}/select-last-frame` goes back to one of
those earlier frames and answers with the scenes, like `select-first-frame`. The rules are in
`services/last_frames.py`.

Both start endpoints take the database's write lock before they read the scenes
(`scenes_service.lock_scenes`), like a cut edit does, so a cut edit that is running cannot
change a scene between the check and the jobs.
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
from app.services import first_frames as first_frames_service
from app.services import image_prompts as image_prompts_service
from app.services import last_frame_prompts as last_prompts_service
from app.services import last_frames as last_frames_service
from app.services import scene_inputs
from app.services import scenes as scenes_service
from app.services.descriptions import DRAFT_JOB

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1

AssetId = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No project or scene has this id."}}
_BLOCKED = {
    422: {
        "model": ErrorResponse,
        "description": "A last frame cannot be made now: there are no scenes, a proposal or a "
        "draft is running, the scenes are out of date, or the scene has no current last frame "
        "prompt (none, out of date, or being written) or no first frame (none, or being made).",
    }
}


class GenerateLastFrameRequest(BaseModel):
    """What the user has confirmed. Every flag is off unless sent."""

    model_config = ConfigDict(extra="forbid")

    # Replace a last frame the user uploaded. It stays among the scene's earlier last frames.
    replace_upload: StrictBool = False


class SelectLastFrameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The `asset_id` of one of the scene's earlier last frames.
    asset_id: AssetId


class GenerateLastFramesOut(BaseModel):
    # The jobs that were created, in scene order. Empty when no scene needed one.
    jobs: list[JobSummary]
    created: int


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _scene_missing(scene_id: int) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND, f"Scene {scene_id} does not exist in this project."
    )


async def _locked_state(
    session: AsyncSession, project: Project
) -> tuple[scenes_service.ScenesState, str | None]:
    """Takes the write lock, then reads the scenes and the reason the whole project is
    blocked, if there is one: what is read cannot change before the commit that follows.
    """
    await scenes_service.lock_scenes(session, project.id)
    await session.refresh(project)
    state = await scenes_service.scenes_state(session, project)
    draft_job = await store.latest_job(session, project.id, DRAFT_JOB)
    block = image_prompts_service.project_block(
        state.scenes,
        plan_job=state.job,
        stale_reasons=state.stale_reasons,
        draft_job=draft_job,
    )
    return state, block


@router.post(
    "/projects/{project_id}/generate-last-frames",
    response_model=GenerateLastFramesOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def generate_last_frames(project_id: int, session: SessionDep) -> GenerateLastFramesOut:
    """Starts one last frame job (an image made on the GPU server) for every scene that has a
    current last frame prompt and a first frame, nothing running, and no last frame or an AI
    last frame that is out of date. Frames the user uploaded are skipped. All the jobs are
    created in one transaction. The page asks before calling this, and it shows how many it
    will start (`ScenesOut.last_frame_candidate_count`).
    """
    project = await load_project(session, project_id)
    state, block = await _locked_state(session, project)
    if block is not None:
        raise _unprocessable(block)

    frames = await scene_inputs.load_frames(session, state.scenes)
    active_lasts = await last_frames_service.active_last_frame_jobs(session, project.id)
    active_firsts = await first_frames_service.active_frame_jobs(session, project.id)
    active_prompts = await last_prompts_service.active_prompt_jobs(session, project.id)
    prompt_states = await last_prompts_service.prompt_states(session, project, state.scenes)
    candidates: list[Scene] = [
        scene
        for scene in state.scenes
        if last_frames_service.is_candidate(
            scene,
            frames.get(scene.first_frame_asset_id or 0),
            frames.get(scene.last_frame_asset_id or 0),
            prompt_out_of_date=scene.id in prompt_states and prompt_states[scene.id].out_of_date,
            prompt_job_active=scene.id in active_prompts,
            first_frame_job_active=scene.id in active_firsts,
            last_frame_job_active=scene.id in active_lasts,
        )
    ]
    nothing = last_frames_service.all_block(len(candidates), len(active_lasts))
    if nothing is not None:
        raise _unprocessable(nothing)

    created: list[JobSummary] = []
    for scene in candidates:
        job, was_created = await store.create_job(
            session,
            project_id=project.id,
            type=last_frames_service.LAST_FRAME_JOB,
            provider="gpu",
            scene_id=scene.id,
            input={
                "requested": "generate_all",
                "replace_upload": False,
                "last_frame_at_click": scene.last_frame_asset_id,
            },
            commit=False,
        )
        if was_created:
            created.append(
                job_summary(JobRow(job=job, project_name=project.name, scene_index=scene.index))
            )
    await session.commit()
    if created:
        dispatcher.nudge()
    return GenerateLastFramesOut(jobs=created, created=len(created))


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/generate-last-frame",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **_NOT_FOUND,
        **_BLOCKED,
        409: {
            "model": ErrorResponse,
            "description": "The scene's last frame is one the user uploaded, and the request "
            "did not confirm replacing it.",
        },
    },
)
async def generate_last_frame(
    project_id: int,
    scene_id: int,
    session: SessionDep,
    body: GenerateLastFrameRequest | None = None,
) -> JobDetail:
    """Starts the last frame of one scene (an image made on the GPU server by editing its first
    frame), or returns the job already active for it. A frame the user uploaded is replaced only
    when the request sets `replace_upload`: it stays among the scene's earlier last frames.
    """
    flags = body or GenerateLastFrameRequest()
    project = await load_project(session, project_id)
    state, block = await _locked_state(session, project)
    scene = (
        next((item for item in state.scenes if item.id == scene_id), None)
        if 1 <= scene_id <= _MAX_ID
        else None
    )
    if scene is None:
        raise _scene_missing(scene_id)
    if block is not None:
        raise _unprocessable(block)

    active = (await last_frames_service.active_last_frame_jobs(session, project.id)).get(scene.id)
    if active is None:
        active_firsts = await first_frames_service.active_frame_jobs(session, project.id)
        active_prompts = await last_prompts_service.active_prompt_jobs(session, project.id)
        prompt_states = await last_prompts_service.prompt_states(session, project, [scene])
        frames = await scene_inputs.load_frames(session, [scene])
        scene_block = last_frames_service.scene_block(
            scene,
            frames.get(scene.first_frame_asset_id or 0),
            prompt_out_of_date=scene.id in prompt_states and prompt_states[scene.id].out_of_date,
            prompt_job_active=scene.id in active_prompts,
            first_frame_job_active=scene.id in active_firsts,
        )
        if scene_block is not None:
            raise _unprocessable(scene_block)
        if (
            last_frames_service.needs_upload_confirmation(
                scene, frames.get(scene.last_frame_asset_id or 0)
            )
            and not flags.replace_upload
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"The last frame of scene {scene.index + 1} is one you uploaded. Confirm to "
                "make an AI frame instead: your upload stays in the list of earlier frames.",
            )

    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=last_frames_service.LAST_FRAME_JOB,
        provider="gpu",
        scene_id=scene.id,
        input={
            "requested": "generate",
            "replace_upload": flags.replace_upload,
            "last_frame_at_click": scene.last_frame_asset_id,
        },
    )
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=scene.index))


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/select-last-frame",
    response_model=ScenesOut,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No project or scene has this id, or the asset is not one of the "
            "scene's earlier last frames.",
        }
    },
)
async def select_last_frame(
    project_id: int, scene_id: int, body: SelectLastFrameRequest, session: SessionDep
) -> ScenesOut:
    """Makes one of the scene's earlier last frames its last frame again. A scene that continues
    this scene's action then starts on it.
    """
    project = await load_project(session, project_id)
    if not 1 <= scene_id <= _MAX_ID:
        raise _scene_missing(scene_id)
    try:
        await last_frames_service.select_last_frame(session, project.id, scene_id, body.asset_id)
    except first_frames_service.SceneGone:
        raise _scene_missing(scene_id) from None
    except first_frames_service.FrameNotChoosable:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Asset {body.asset_id} is not one of this scene's earlier last frames.",
        ) from None
    return await scenes_out(session, project)
