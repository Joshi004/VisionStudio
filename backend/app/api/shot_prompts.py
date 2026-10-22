"""`/api/projects/{project_id}/shot-prompts`: the H3 Prompt Compilation stage (PHASE-026).

- `GET ...` answers everything the story workspace shows in one call: the newest list of scenes,
  and for each scene its shots (from the newest shot plan) with the status of each shot's prompt
  (`not_compiled`, `compiled`, `out_of_date`), why it is out of date, the newest prompt with its
  labels and provenance, the newest job, and whether Compile may be pressed. Out of date is
  worked out on every read.
- `POST .../run` ("Compile all") starts one job per shot, in every scene, whose generation
  request is planned and current and that has no current prompt and is not already being
  compiled.
- `POST .../{scene_id}/run` starts the jobs for the shots of one scene.
- `POST .../{scene_id}/{shot_id}/run` starts the job for one shot.

A job stores a new version of the shot's prompt (`services/shot_prompts.py`); nothing is written
to the Character Lab and nothing is sent to the video model. The answers never return ORM
objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.discovery import DiscoveryJobOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import shot_prompts
from app.services.shot_prompts import SceneEntry, ShotEntry

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The shot's generation request is not planned and current, the shot's "
        "specification cannot be read now, or the scene or shot is not in the newest list of "
        "scenes and shot plan.",
    }
}

Source = Literal["ai", "manual"]
Status = Literal["not_compiled", "compiled", "out_of_date"]
ShotType = Literal["establishing", "action", "reaction", "dialogue", "insert", "transition"]
RequestStatus = Literal["not_planned", "planned", "out_of_date"]
PromptFormat = Literal["reference", "generate"]
SubjectKind = Literal["character", "environment"]


class PromptSubjectOut(BaseModel):
    """One `<Subject k>` of the prompt: a character or the place, and the pictures showing it."""

    label: str
    subject_id: str
    subject_name: str
    kind: SubjectKind
    # The labels of the pictures that show it (`Picture 1`), and the view of each.
    pictures: list[str]
    views: list[str]


class PromptSpeakerOut(BaseModel):
    """One `<Audio n>` of the prompt: a line of dialogue and who says it."""

    # The id the prompt gives the voice (`S1`).
    speaker: str
    audio_label: str
    speaker_id: str
    unit_id: str
    # False when the speaker is not in the shot: the voice comes from an unseen speaker (Q-4).
    visible: bool
    # The subject that says it; None for an unseen speaker.
    subject_label: str | None
    # Where the line starts inside the shot, as the prompt writes it (`00:01.200`).
    cue: str
    text: str


class ShotPromptContentOut(BaseModel):
    format: PromptFormat
    endpoint: str
    # The finished prompt, as it is sent to the video model.
    prompt: str
    subjects: list[PromptSubjectOut]
    speakers: list[PromptSpeakerOut]
    # What is off in the prompt. None of it blocks.
    warnings: list[str]
    word_count: int
    char_count: int


class ShotPromptVersionOut(BaseModel):
    """The provenance of the newest prompt of a shot (D-3)."""

    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class PromptShotSkeletonOut(BaseModel):
    id: str
    type: ShotType
    description: str
    duration_seconds: float


class ShotPromptEntryOut(BaseModel):
    shot: PromptShotSkeletonOut
    status: Status
    # Why a compiled prompt is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # Where the shot's generation request stands: the prompt is compiled from it.
    request_status: RequestStatus
    prompt: ShotPromptContentOut | None
    version: ShotPromptVersionOut | None
    # The newest compile job of this shot, whatever its status.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None


class SceneShotPromptsOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    description: str
    shots: list[ShotPromptEntryOut]


class ShotPromptsOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    entries: list[SceneShotPromptsOut]
    # Why nothing can be compiled yet, or None.
    blocked_reason: str | None


class ShotPromptSkippedOut(BaseModel):
    scene_id: str
    # None when the whole scene was skipped.
    shot_id: str | None
    title: str
    reason: str


class ShotPromptsRunManyOut(BaseModel):
    job_ids: list[int]
    skipped: list[ShotPromptSkippedOut]


class ShotPromptsRunOneOut(BaseModel):
    job_id: int


def _shot_out(entry: ShotEntry) -> ShotPromptEntryOut:
    shot = entry.shot
    row = entry.row
    job = entry.job
    content = entry.content
    return ShotPromptEntryOut(
        shot=PromptShotSkeletonOut(
            id=shot["id"],
            type=shot["type"],
            description=shot["description"],
            duration_seconds=entry.duration_s,
        ),
        status=entry.status,
        reasons=entry.reasons,
        request_status=cast(RequestStatus, entry.request_status),
        prompt=ShotPromptContentOut.model_validate(content) if content is not None else None,
        version=(
            ShotPromptVersionOut(
                version=row.version,
                # The database CHECK constraint keeps `source` to the two allowed values.
                source=cast(Source, row.source),
                job_id=row.job_id,
                created_at=row.created_at,
            )
            if row is not None
            else None
        ),
        job=(
            DiscoveryJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        can_run=entry.can_run,
        blocked_reason=entry.blocked_reason,
    )


def _scene_out(entry: SceneEntry) -> SceneShotPromptsOut:
    return SceneShotPromptsOut(
        id=entry.item["id"],
        index=entry.item["index"],
        title=entry.item["title"],
        description=entry.item["description"],
        shots=[_shot_out(shot) for shot in entry.shots],
    )


def _run_many_out(started: shot_prompts.StartResult) -> ShotPromptsRunManyOut:
    return ShotPromptsRunManyOut(
        job_ids=started.job_ids,
        skipped=[
            ShotPromptSkippedOut(
                scene_id=item.scene_id,
                shot_id=item.shot_id,
                title=item.title,
                reason=item.reason,
            )
            for item in started.skipped
        ],
    )


def _refused(exc: shot_prompts.ShotPromptsError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/shot-prompts",
    response_model=ShotPromptsOut,
    responses=_NOT_FOUND,
)
async def get_shot_prompts(project_id: int, session: SessionDep) -> ShotPromptsOut:
    project = await load_project(session, project_id)
    result = await shot_prompts.state(session, project)
    return ShotPromptsOut(
        scenes_version=result.scenes_version,
        entries=[_scene_out(entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/shot-prompts/run",
    response_model=ShotPromptsRunManyOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> ShotPromptsRunManyOut:
    """Starts a job for every shot that has no current prompt and is not already being
    compiled. The shots that cannot be compiled are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await shot_prompts.start_all(session, project)
    except shot_prompts.ShotPromptsError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return _run_many_out(started)


@router.post(
    "/projects/{project_id}/shot-prompts/{scene_id}/run",
    response_model=ShotPromptsRunManyOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_scene(
    project_id: int, scene_id: DiscoveryId, session: SessionDep
) -> ShotPromptsRunManyOut:
    """Starts a job for every shot of one scene that has no current prompt and is not already
    being compiled.
    """
    project = await load_project(session, project_id)
    try:
        started = await shot_prompts.start_scene(session, project, scene_id)
    except shot_prompts.ShotPromptsError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return _run_many_out(started)


@router.post(
    "/projects/{project_id}/shot-prompts/{scene_id}/{shot_id}/run",
    response_model=ShotPromptsRunOneOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_shot(
    project_id: int, scene_id: DiscoveryId, shot_id: DiscoveryId, session: SessionDep
) -> ShotPromptsRunOneOut:
    """Starts the job that compiles one shot's prompt. If it already has a job waiting or
    running, that job's id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await shot_prompts.start_shot(session, project, scene_id, shot_id)
    except shot_prompts.ShotPromptsError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return ShotPromptsRunOneOut(job_id=job.id)
