"""Making a project's voiceover from its script (Phase 21).

`POST /api/projects/{id}/voiceover/generate` creates the `generate_voiceover` job and returns at
once with HTTP 202. The dispatcher does the work: Breeze TTS speaks the script in the project's
saved voice (`PATCH /api/projects/{id}` with `voice_id`), and the WAV becomes the project's
voiceover. `GET .../voiceover/generation` reads the database only: the newest such job, and
whether the voiceover is one the app made from the script as it is now.

Breeze TTS 2's weights and outputs are licensed for research and non-commercial use only.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import projects as projects_service
from app.services import voiceover_generation as generation
from app.services import voices

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No project has this id."}}
_NOT_READY = {
    409: {"model": ErrorResponse, "description": "Another job of the project is in the way."},
    422: {"model": ErrorResponse, "description": "The project has no script or no voice yet."},
}


class VoiceoverGenerationOut(BaseModel):
    # The newest voiceover job of the project, whatever its status.
    job: JobSummary | None
    # Why a voiceover cannot be made from the script and the chosen voice now, or null.
    blocked: str | None
    # The project's voiceover was made by the app (not uploaded).
    voiceover_is_ai: bool
    # ... and the script has not changed since. False for an uploaded voiceover.
    voiceover_current: bool


@router.post(
    "/projects/{project_id}/voiceover/generate",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_NOT_READY},
)
async def generate_voiceover(project_id: int, session: SessionDep) -> JobDetail:
    """Starts making the voiceover from the script, or returns the job that is already active.
    The new voiceover replaces the project's current one (the old file is kept).
    """
    project = await load_project(session, project_id)
    voice = await voices.get_voice(session, project.voice_id) if project.voice_id else None
    reason = generation.block_reason(project, voice)
    if reason is not None or voice is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, reason)
    busy = await generation.busy_reason(session, project.id)
    if busy is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, busy)

    job, _created = await generation.create_job(session, project, voice)
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=None))


@router.get(
    "/projects/{project_id}/voiceover/generation",
    response_model=VoiceoverGenerationOut,
    responses=_NOT_FOUND,
)
async def get_voiceover_generation(project_id: int, session: SessionDep) -> VoiceoverGenerationOut:
    """The newest voiceover job and whether the voiceover is up to date. Reads the database
    only.
    """
    project = await load_project(session, project_id)
    job = await store.latest_job(session, project.id, generation.JOB_TYPE)
    voice = await voices.get_voice(session, project.voice_id) if project.voice_id else None
    asset = await projects_service.get_voiceover(session, project)
    return VoiceoverGenerationOut(
        job=(
            job_summary(JobRow(job=job, project_name=project.name, scene_index=None))
            if job is not None
            else None
        ),
        blocked=generation.block_reason(project, voice),
        voiceover_is_ai=asset is not None and asset.source == "ai",
        voiceover_current=generation.is_current(project, asset),
    )
