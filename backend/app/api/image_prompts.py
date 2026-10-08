"""Image prompts (Phase 16; ANALYSIS.md Section 4.2 and 6.2).

`POST .../write-image-prompts` creates one `write_image_prompt` job for every scene that needs
one (no prompt yet, or an AI prompt that is out of date), and `POST .../scenes/{id}/write-image-
prompt` creates one for a single scene. Each job is a paid call to the language model, so it
only ever runs from one of these clicks. The page shows the number of calls first. Both return
at once with HTTP 202. The dispatcher does the work.

A prompt the author wrote is never overwritten: "all" skips it, and the one-scene endpoint
refuses it (clear it first). The rules are in `services/image_prompts.py`.

Both endpoints take the database's write lock before they read the scenes
(`scenes_service.lock_scenes`), like a cut edit does, so a cut edit that is running cannot
change a scene between the check and the jobs.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.api.projects import load_project
from app.db.models import Project, Scene
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import image_prompts as prompts_service
from app.services import scenes as scenes_service
from app.services.descriptions import DRAFT_JOB

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No project or scene has this id."}}
_BLOCKED = {
    422: {
        "model": ErrorResponse,
        "description": "Image prompts cannot be written now: there are no scenes, a proposal "
        "or a draft is running, the scenes are out of date, the scene has no text to work "
        "from, or the prompt was written by the user.",
    }
}


class WriteImagePromptRequest(BaseModel):
    """What the user has confirmed. Every flag is off unless sent."""

    model_config = ConfigDict(extra="forbid")

    # Ask the model again even though the same request was answered before (paid).
    run_again: StrictBool = False


class WriteImagePromptsOut(BaseModel):
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
    "/projects/{project_id}/write-image-prompts",
    response_model=WriteImagePromptsOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def write_image_prompts(project_id: int, session: SessionDep) -> WriteImagePromptsOut:
    """Starts one image prompt job (a paid call to the language model) for every scene that
    has text to work from and no prompt, or an AI prompt that is out of date, and no job
    running. Prompts the user wrote are skipped. All the jobs are created in one transaction.
    The page asks before calling this, and it shows how many it will start
    (`ScenesOut.image_prompt_candidate_count`).
    """
    project = await load_project(session, project_id)
    state, block = await _locked_state(session, project)
    if block is not None:
        raise _unprocessable(block)

    active = await prompts_service.active_prompt_jobs(session, project.id)
    states = await prompts_service.prompt_states(session, project, state.scenes)
    candidates: list[Scene] = [
        scene
        for scene in state.scenes
        if prompts_service.is_candidate(
            scene,
            out_of_date=scene.id in states and states[scene.id].out_of_date,
            active=active.get(scene.id),
        )
    ]
    nothing = prompts_service.all_block(len(candidates), len(active))
    if nothing is not None:
        raise _unprocessable(nothing)

    created: list[JobSummary] = []
    for scene in candidates:
        job, was_created = await store.create_job(
            session,
            project_id=project.id,
            type=prompts_service.IMAGE_PROMPT_JOB,
            provider="llm",
            scene_id=scene.id,
            input={"requested": "write_all", "run_again": False},
            commit=False,
        )
        if was_created:
            created.append(
                job_summary(JobRow(job=job, project_name=project.name, scene_index=scene.index))
            )
    await session.commit()
    if created:
        dispatcher.nudge()
    return WriteImagePromptsOut(jobs=created, created=len(created))


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/write-image-prompt",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def write_image_prompt(
    project_id: int,
    scene_id: int,
    session: SessionDep,
    body: WriteImagePromptRequest | None = None,
) -> JobDetail:
    """Starts writing the image prompt of one scene (a paid call to the language model), or
    returns the job already active for it. The same request as an earlier one reuses its stored
    answer unless `run_again` is sent. A prompt the user wrote is refused: clear it first.
    """
    flags = body or WriteImagePromptRequest()
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

    active = (await prompts_service.active_prompt_jobs(session, project.id)).get(scene.id)
    if active is None:
        scene_block = prompts_service.scene_block(scene)
        if scene_block is not None:
            raise _unprocessable(scene_block)

    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=prompts_service.IMAGE_PROMPT_JOB,
        provider="llm",
        scene_id=scene.id,
        input={"requested": "write", "run_again": flags.run_again},
    )
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=scene.index))
