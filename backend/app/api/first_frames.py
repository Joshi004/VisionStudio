"""First frames (Phase 17; ANALYSIS.md Section 4.2 and 6.2).

`POST .../generate-first-frames` creates one `generate_frame` job for every scene that has a
current image prompt and no first frame, or an AI first frame that is out of date, and
`POST .../scenes/{id}/generate-first-frame` creates one for a single scene. Each job is one
paid image from the image model, so it only ever runs from one of these clicks, and the page
shows the number of images and the estimated cost first. Both return at once with HTTP 202.
The dispatcher does the work, at most "maximum parallel image generations" at a time.

A frame the author uploaded is never replaced by "all". The one-scene endpoint replaces it only
when the request says `replace_upload` (it answers 409 until then), and the upload stays
among the scene's earlier frames. `POST .../scenes/{id}/select-first-frame` goes back to one
of those earlier frames and answers with the scenes, like `select-take`. The rules are in
`services/first_frames.py`.

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
from app.services import first_frames as frames_service
from app.services import image_prompts as prompts_service
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
        "description": "A first frame cannot be made now: there are no scenes, a proposal or a "
        "draft is running, the scenes are out of date, or the scene has no current image "
        "prompt (none, out of date, or being written).",
    }
}


class GenerateFirstFrameRequest(BaseModel):
    """What the user has confirmed. Every flag is off unless sent."""

    model_config = ConfigDict(extra="forbid")

    # Replace a first frame the user uploaded. It stays among the scene's earlier frames.
    replace_upload: StrictBool = False


class SelectFirstFrameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The `asset_id` of one of the scene's earlier frames.
    asset_id: AssetId


class GenerateFirstFramesOut(BaseModel):
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
    block = prompts_service.project_block(
        state.scenes,
        plan_job=state.job,
        stale_reasons=state.stale_reasons,
        draft_job=draft_job,
    )
    return state, block


@router.post(
    "/projects/{project_id}/generate-first-frames",
    response_model=GenerateFirstFramesOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def generate_first_frames(project_id: int, session: SessionDep) -> GenerateFirstFramesOut:
    """Starts one first frame job (a paid image from the image model) for every scene that has
    a current image prompt, nothing running, and no first frame or an AI first frame that is
    out of date. Frames the user uploaded are skipped. All the jobs are created in one
    transaction. The page asks before calling this, and it shows how many it will start
    (`ScenesOut.frame_candidate_count`) and the estimated cost.
    """
    project = await load_project(session, project_id)
    state, block = await _locked_state(session, project)
    if block is not None:
        raise _unprocessable(block)

    frames = await scene_inputs.load_frames(session, state.scenes)
    active_frames = await frames_service.active_frame_jobs(session, project.id)
    active_prompts = await prompts_service.active_prompt_jobs(session, project.id)
    prompt_states = await prompts_service.prompt_states(session, project, state.scenes)
    candidates: list[Scene] = [
        scene
        for scene in state.scenes
        if frames_service.is_candidate(
            scene,
            frames.get(scene.first_frame_asset_id or 0),
            prompt_out_of_date=scene.id in prompt_states and prompt_states[scene.id].out_of_date,
            prompt_job_active=scene.id in active_prompts,
            frame_job_active=scene.id in active_frames,
        )
    ]
    nothing = frames_service.all_block(len(candidates), len(active_frames))
    if nothing is not None:
        raise _unprocessable(nothing)

    created: list[JobSummary] = []
    for scene in candidates:
        job, was_created = await store.create_job(
            session,
            project_id=project.id,
            type=frames_service.FRAME_JOB,
            provider="image",
            scene_id=scene.id,
            input={
                "requested": "generate_all",
                "replace_upload": False,
                "first_frame_at_click": scene.first_frame_asset_id,
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
    return GenerateFirstFramesOut(jobs=created, created=len(created))


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/generate-first-frame",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **_NOT_FOUND,
        **_BLOCKED,
        409: {
            "model": ErrorResponse,
            "description": "The scene's first frame is one the user uploaded, and the request "
            "did not confirm replacing it.",
        },
    },
)
async def generate_first_frame(
    project_id: int,
    scene_id: int,
    session: SessionDep,
    body: GenerateFirstFrameRequest | None = None,
) -> JobDetail:
    """Starts the first frame of one scene (a paid image from the image model), or returns the
    job already active for it. A frame the user uploaded is replaced only when the request
    sets `replace_upload`: it stays among the scene's earlier frames.
    """
    flags = body or GenerateFirstFrameRequest()
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

    active = (await frames_service.active_frame_jobs(session, project.id)).get(scene.id)
    if active is None:
        active_prompts = await prompts_service.active_prompt_jobs(session, project.id)
        prompt_states = await prompts_service.prompt_states(session, project, [scene])
        scene_block = frames_service.scene_block(
            scene,
            prompt_out_of_date=scene.id in prompt_states and prompt_states[scene.id].out_of_date,
            prompt_job_active=scene.id in active_prompts,
        )
        if scene_block is not None:
            raise _unprocessable(scene_block)
        first_frame = (await scene_inputs.load_frames(session, [scene])).get(
            scene.first_frame_asset_id or 0
        )
        if (
            frames_service.needs_upload_confirmation(scene, first_frame)
            and not flags.replace_upload
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"The first frame of scene {scene.index + 1} is one you uploaded. Confirm to "
                "make an AI frame instead: your upload stays in the list of earlier frames.",
            )

    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=frames_service.FRAME_JOB,
        provider="image",
        scene_id=scene.id,
        input={
            "requested": "generate",
            "replace_upload": flags.replace_upload,
            "first_frame_at_click": scene.first_frame_asset_id,
        },
    )
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=scene.index))


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/select-first-frame",
    response_model=ScenesOut,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No project or scene has this id, or the asset is not one of the "
            "scene's earlier frames.",
        }
    },
)
async def select_first_frame(
    project_id: int, scene_id: int, body: SelectFirstFrameRequest, session: SessionDep
) -> ScenesOut:
    """Makes one of the scene's earlier frames its first frame again."""
    project = await load_project(session, project_id)
    if not 1 <= scene_id <= _MAX_ID:
        raise _scene_missing(scene_id)
    try:
        await frames_service.select_first_frame(session, project.id, scene_id, body.asset_id)
    except frames_service.SceneGone:
        raise _scene_missing(scene_id) from None
    except frames_service.FrameNotChoosable:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Asset {body.asset_id} is not one of this scene's earlier frames.",
        ) from None
    return await scenes_out(session, project)
