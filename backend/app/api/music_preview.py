"""`/api/projects/{project_id}/music-preview`: hear the music in context (MUSIC-012).

- `POST ...` starts the `preview_music_mix` job: a short sound-only file of the story's own mix
  for one scene, or for one cue with two seconds around it. With `take_id`, the cue is heard with
  that take instead of the selected one (nothing is saved, no model is asked). If a preview of the
  same thing is already waiting or running, its job is returned.
- `GET ...` answers the project's newest preview job, whatever it is of, with the file's address
  once it has succeeded.

The job and its file are made by `services/music_preview.py` and `jobs/preview_music_mix.py`. The
answers never return ORM objects.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, StrictInt, StrictStr, model_validator

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Job
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import music_preview, storage

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1
_MAX_ID_CHARS = 100

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The music cannot be previewed now: music is off, something it needs is "
        "not ready, or the scene, cue or take does not exist.",
    }
}


class MusicPreviewRequest(BaseModel):
    """What to hear: exactly one of `scene_id` and `cue_id`, and optionally a take to hear in
    place of the selected one.
    """

    scene_id: StrictStr | None = Field(default=None, min_length=1, max_length=_MAX_ID_CHARS)
    cue_id: StrictStr | None = Field(default=None, min_length=1, max_length=_MAX_ID_CHARS)
    take_id: StrictInt | None = Field(default=None, ge=1, le=_MAX_INT)

    @model_validator(mode="after")
    def _one_target(self) -> MusicPreviewRequest:
        if (self.scene_id is None) == (self.cue_id is None):
            raise ValueError("Ask for a scene or a cue, not both and not neither.")
        return self


class MusicPreviewRun(BaseModel):
    job_id: int


class MusicPreviewOut(BaseModel):
    """The newest preview job."""

    job_id: int
    status: JobStatus
    phase: str | None
    error: str | None
    # What it is of.
    scene_id: str | None
    cue_id: str | None
    take_id: int | None
    # The file, once the job has succeeded.
    url: str | None
    duration_s: float | None
    # The part of the story it covers, in seconds.
    window_start_s: float | None
    window_end_s: float | None


class MusicPreviewState(BaseModel):
    preview: MusicPreviewOut | None


def _preview_out(job: Job) -> MusicPreviewOut:
    request = job.input if isinstance(job.input, dict) else {}
    output: dict[str, Any] = job.output if isinstance(job.output, dict) else {}
    file = output.get("file") if isinstance(output.get("file"), dict) else {}
    window = output.get("window") if isinstance(output.get("window"), dict) else {}
    path = file.get("path")
    return MusicPreviewOut(
        job_id=job.id,
        status=cast(JobStatus, job.status),
        phase=job.phase,
        error=job.error,
        scene_id=request.get("scene_id"),
        cue_id=request.get("cue_id"),
        take_id=request.get("take_id"),
        url=storage.media_url(path)
        if job.status == "succeeded" and isinstance(path, str)
        else None,
        duration_s=file.get("duration_s"),
        window_start_s=window.get("start_s"),
        window_end_s=window.get("end_s"),
    )


@router.post(
    "/projects/{project_id}/music-preview",
    response_model=MusicPreviewRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_music_preview(
    project_id: int, body: MusicPreviewRequest, session: SessionDep
) -> MusicPreviewRun:
    """Starts the job that makes a preview. The same preview, if already waiting or running, is
    returned instead of a second job.
    """
    project = await load_project(session, project_id)
    target = music_preview.Target(body.scene_id, body.cue_id, body.take_id)
    try:
        job = await music_preview.start(session, project, target)
    except music_preview.MusicPreviewError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return MusicPreviewRun(job_id=job.id)


@router.get(
    "/projects/{project_id}/music-preview",
    response_model=MusicPreviewState,
    responses=_NOT_FOUND,
)
async def get_music_preview(project_id: int, session: SessionDep) -> MusicPreviewState:
    project = await load_project(session, project_id)
    job = await music_preview.latest_job(session, project.id)
    return MusicPreviewState(preview=_preview_out(job) if job is not None else None)
