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
- `POST .../{scene_id}/{shot_id}/run` starts the job for one shot. When the newest prompt was
  written by the user, the body must say `confirm_replace_manual`. The body may also hold
  `feedback`, the user's note on the newest prompt: the prompt is written again with the note
  (PHASE-038). Nothing is sent to the video model by it.
- `PUT .../{scene_id}/{shot_id}` saves the user's edit of the pieces of a shot's prompt as its
  next version (`source` is `manual`). Code builds the prompt from the pieces with the same
  checks as for the model's answer.

A job stores a new version of the shot's prompt (`services/shot_prompts.py`); nothing is written
to the Character Lab and nothing is sent to the video model. The answers never return ORM
objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.discovery import DiscoveryJobOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import shot_prompts, user_feedback
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
    # The creative pieces the model wrote (or the user edited), by name. The prompt is built from
    # them and the parts that code writes.
    pieces: dict[str, str] = {}
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
    # The user's note this version was made from, or None (PHASE-038).
    feedback: str | None = None


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
    # True when the newest prompt was written by the user: compiling it again by model has to be
    # confirmed (PHASE-038).
    needs_confirmation: bool


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


class ShotPromptRunIn(BaseModel):
    """The optional body of the run of one shot."""

    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False
    # The user's note on the newest prompt. `user_feedback.clean` checks it again.
    feedback: str | None = Field(default=None, max_length=user_feedback.MAX_CHARS)


class ShotPromptEditIn(BaseModel):
    """The edited pieces, by name (`shot_prompt_writer` says which names a shot has). The rules
    are checked by `shot_prompt_writer.check_answer`; the limits here only keep a request from
    being huge.
    """

    model_config = ConfigDict(extra="forbid")

    pieces: dict[str, str] = Field(max_length=50)


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
                feedback=user_feedback.text_of(row.inputs),
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
        needs_confirmation=entry.needs_confirmation,
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
    return await _state_out(session, project)


async def _state_out(session: AsyncSession, project: Project) -> ShotPromptsOut:
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
    project_id: int,
    scene_id: DiscoveryId,
    shot_id: DiscoveryId,
    session: SessionDep,
    body: ShotPromptRunIn | None = None,
) -> ShotPromptsRunOneOut:
    """Starts the job that compiles one shot's prompt. If it already has a job waiting or
    running, that job's id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await shot_prompts.start_shot(
            session,
            project,
            scene_id,
            shot_id,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
            feedback=body.feedback if body is not None else None,
        )
    except shot_prompts.ShotPromptsError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return ShotPromptsRunOneOut(job_id=job.id)


@router.put(
    "/projects/{project_id}/shot-prompts/{scene_id}/{shot_id}",
    response_model=ShotPromptsOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_shot_prompt(
    project_id: int,
    scene_id: DiscoveryId,
    shot_id: DiscoveryId,
    body: ShotPromptEditIn,
    session: SessionDep,
) -> ShotPromptsOut:
    """Saves the edited pieces of one shot's prompt as its next version, written by the user.
    Nothing is sent to the video model.
    """
    project = await load_project(session, project_id)
    try:
        await shot_prompts.save_manual(session, project, scene_id, shot_id, body.pieces)
    except shot_prompts.ShotPromptsError as exc:
        raise _refused(exc) from exc
    return await _state_out(session, project)
