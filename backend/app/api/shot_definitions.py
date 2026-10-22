"""`/api/projects/{project_id}/shot-definitions`: the Shot Definition stage (PHASE-022).

- `GET ...` answers everything the story workspace shows in one call: the newest list of scenes,
  and for each scene its shots (from the newest shot plan) with the status of each shot's
  definition (`not_defined`, `defined`, `out_of_date`), why it is out of date, its newest
  specification with its provenance, the newest job, and whether Define may be pressed. Out of
  date is worked out on every read.
- `POST .../run` ("Define all") starts one job per shot, in every scene that can be defined,
  that is not defined and up to date already and is not already being defined.
- `POST .../{scene_id}/run` starts the jobs for the shots of one scene.
- `POST .../{scene_id}/{shot_id}/run` starts the job for one shot. When the newest definition
  was written by the user, the body must say `confirm_replace_manual`. The body may also hold
  `feedback`, the user's note on the newest definition: the shot is defined again with the
  note (PHASE-038).
- `PUT .../{scene_id}/{shot_id}` saves the user's edit of a shot's specification as its next
  version (`source` is `manual`), checked like the model's answer. What follows a saved
  definition (references, request, prompt, continuity) is started as after a job
  (`services/shot_chain.py`).

A job stores a new version of the shot's definition (`services/shot_definitions.py`); nothing is
written to the Character Lab. The answers never return ORM objects.
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
from app.services import shot_chain, shot_definitions, user_feedback
from app.services.shot_definitions import SceneEntry, ShotEntry

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The scene's shots are not planned, current and ready for generation, "
        "the looks and states are not resolved and current, the scene is not in the newest "
        "list of scenes, or the shot is not in its shot plan.",
    }
}

Source = Literal["ai", "manual"]
Status = Literal["not_defined", "defined", "out_of_date"]
ShotType = Literal["establishing", "action", "reaction", "dialogue", "insert", "transition"]
PlanStatus = Literal["not_planned", "planned", "out_of_date"]
SpeechKind = Literal["narration", "dialogue"]


# --- The specification, as `Path_ahead.md` Section 26 gives it -------------------------------


class ShotCharacterOut(BaseModel):
    id: str
    expression: str
    pose: str
    gaze: str


class ShotCompositionOut(BaseModel):
    shot_size: str
    angle: str
    focus: str


class ShotCameraOut(BaseModel):
    movement: str
    intensity: str


class ShotActionOut(BaseModel):
    start_state: str
    primary_action: str
    end_state: str


class ShotDialogueLineOut(BaseModel):
    """A line of dialogue heard in the shot. Written by code from the shot's speech units."""

    unit_id: str
    speaker_id: str
    text: str


class ShotAudioIntentOut(BaseModel):
    # None when the shot carries no dialogue. There is no music field (Section 26).
    dialogue: list[ShotDialogueLineOut] | None
    ambient: str
    sound_events: list[str]


class ShotDefinitionContentOut(BaseModel):
    shot_id: str
    scene_id: str
    # Seconds, from the scene's timeline.
    duration: float
    visual_story: str
    characters: list[ShotCharacterOut]
    environment_state: dict[str, str | bool]
    composition: ShotCompositionOut
    camera: ShotCameraOut
    action: ShotActionOut
    continuity_start: dict[str, str]
    continuity_end: dict[str, str]
    audio_intent: ShotAudioIntentOut


# --- The stage's state ----------------------------------------------------------------------


class ShotDefinitionVersionOut(BaseModel):
    """The provenance of the newest definition of a shot (D-3)."""

    version: int
    source: Source
    job_id: int | None
    created_at: datetime
    # The user's note this version was made from, or None (PHASE-038).
    feedback: str | None = None


class ShotSkeletonOut(BaseModel):
    """The shot as the plan gives it (PHASE-020), with its length from the timeline."""

    id: str
    type: ShotType
    description: str
    source_event_ids: list[str]
    speech_unit_ids: list[str]
    duration_seconds: float
    # Seconds from the start of the scene; None when the timeline cannot be worked out.
    start_seconds: float | None


class ShotDefinitionEntryOut(BaseModel):
    shot: ShotSkeletonOut
    status: Status
    # Why a defined shot is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    definition: ShotDefinitionContentOut | None
    version: ShotDefinitionVersionOut | None
    # The newest definition job of this shot, whatever its status.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None
    # True when the newest definition was written by the user: defining it again by model has
    # to be confirmed (PHASE-038).
    needs_confirmation: bool


class SceneShotDefinitionsOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    description: str
    # Where the scene's shot plan stands, and which version its shots were read from.
    plan_status: PlanStatus
    plan_version: int | None
    shots: list[ShotDefinitionEntryOut]
    # Why this scene's shots cannot be defined, or None.
    blocked_reason: str | None
    can_run: bool


class ShotDefinitionsOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    entries: list[SceneShotDefinitionsOut]
    # Why nothing can be defined yet, or None.
    blocked_reason: str | None


class ShotDefinitionSkippedOut(BaseModel):
    scene_id: str
    # None when the whole scene was skipped.
    shot_id: str | None
    title: str
    reason: str


class ShotDefinitionsRunManyOut(BaseModel):
    job_ids: list[int]
    skipped: list[ShotDefinitionSkippedOut]


class ShotDefinitionsRunOneOut(BaseModel):
    job_id: int


class ShotDefinitionRunIn(BaseModel):
    """The optional body of the run of one shot."""

    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False
    # The user's note on the newest definition. `user_feedback.clean` checks it again.
    feedback: str | None = Field(default=None, max_length=user_feedback.MAX_CHARS)


# --- An edited specification ------------------------------------------------------------------
# The id, the scene, the duration and the dialogue are set by code. The rules (the sizes, the
# known character ids) are checked by `shot_definition_writer.check_answer`; these limits only
# keep a request from being huge.

_Text = Field(max_length=2000)


class ShotCharacterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=200)
    expression: str = _Text
    pose: str = _Text
    gaze: str = _Text


class ShotCompositionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_size: str = Field(max_length=100)
    angle: str = _Text
    focus: str = _Text


class ShotCameraIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    movement: str = _Text
    intensity: str = _Text


class ShotActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_state: str = _Text
    primary_action: str = _Text
    end_state: str = _Text


class ShotAudioIntentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ambient: str = _Text
    sound_events: list[str] = Field(max_length=50)


class ShotDefinitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual_story: str = _Text
    characters: list[ShotCharacterIn] = Field(max_length=200)
    environment_state: dict[str, str | bool] = Field(max_length=200)
    composition: ShotCompositionIn
    camera: ShotCameraIn
    action: ShotActionIn
    continuity_start: dict[str, str] = Field(max_length=200)
    continuity_end: dict[str, str] = Field(max_length=200)
    audio_intent: ShotAudioIntentIn


def _shot_out(entry: ShotEntry) -> ShotDefinitionEntryOut:
    shot = entry.shot
    row = entry.row
    job = entry.job
    content = entry.content
    return ShotDefinitionEntryOut(
        shot=ShotSkeletonOut(
            id=shot["id"],
            type=shot["type"],
            description=shot["description"],
            source_event_ids=shot["source_event_ids"],
            speech_unit_ids=shot["speech_unit_ids"],
            duration_seconds=entry.duration_s,
            start_seconds=entry.start_s,
        ),
        status=entry.status,
        reasons=entry.reasons,
        definition=ShotDefinitionContentOut.model_validate(content)
        if content is not None
        else None,
        version=(
            ShotDefinitionVersionOut(
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


def _scene_out(entry: SceneEntry) -> SceneShotDefinitionsOut:
    return SceneShotDefinitionsOut(
        id=entry.item["id"],
        index=entry.item["index"],
        title=entry.item["title"],
        description=entry.item["description"],
        plan_status=entry.plan_status,
        plan_version=entry.plan.version if entry.plan is not None else None,
        shots=[_shot_out(shot) for shot in entry.shots],
        blocked_reason=entry.blocked_reason,
        can_run=entry.can_run,
    )


def _run_many_out(started: shot_definitions.StartResult) -> ShotDefinitionsRunManyOut:
    return ShotDefinitionsRunManyOut(
        job_ids=started.job_ids,
        skipped=[
            ShotDefinitionSkippedOut(
                scene_id=item.scene_id,
                shot_id=item.shot_id,
                title=item.title,
                reason=item.reason,
            )
            for item in started.skipped
        ],
    )


def _refused(exc: shot_definitions.ShotDefinitionsError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/shot-definitions",
    response_model=ShotDefinitionsOut,
    responses=_NOT_FOUND,
)
async def get_shot_definitions(project_id: int, session: SessionDep) -> ShotDefinitionsOut:
    project = await load_project(session, project_id)
    return await _state_out(session, project)


async def _state_out(session: AsyncSession, project: Project) -> ShotDefinitionsOut:
    result = await shot_definitions.state(session, project)
    return ShotDefinitionsOut(
        scenes_version=result.scenes_version,
        entries=[_scene_out(entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/shot-definitions/run",
    response_model=ShotDefinitionsRunManyOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> ShotDefinitionsRunManyOut:
    """Starts a job for every shot, in every scene that can be defined, that is not defined and
    up to date already and is not already being defined. The others are skipped, with the
    reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await shot_definitions.start_all(session, project)
    except shot_definitions.ShotDefinitionsError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return _run_many_out(started)


@router.post(
    "/projects/{project_id}/shot-definitions/{scene_id}/run",
    response_model=ShotDefinitionsRunManyOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_scene(
    project_id: int, scene_id: DiscoveryId, session: SessionDep
) -> ShotDefinitionsRunManyOut:
    """Starts a job for every shot of one scene that is not defined and up to date already and
    is not already being defined.
    """
    project = await load_project(session, project_id)
    try:
        started = await shot_definitions.start_scene(session, project, scene_id)
    except shot_definitions.ShotDefinitionsError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return _run_many_out(started)


@router.post(
    "/projects/{project_id}/shot-definitions/{scene_id}/{shot_id}/run",
    response_model=ShotDefinitionsRunOneOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_shot(
    project_id: int,
    scene_id: DiscoveryId,
    shot_id: DiscoveryId,
    session: SessionDep,
    body: ShotDefinitionRunIn | None = None,
) -> ShotDefinitionsRunOneOut:
    """Starts the job that defines one shot. If it already has a job waiting or running, that
    job's id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await shot_definitions.start_shot(
            session,
            project,
            scene_id,
            shot_id,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
            feedback=body.feedback if body is not None else None,
        )
    except shot_definitions.ShotDefinitionsError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return ShotDefinitionsRunOneOut(job_id=job.id)


@router.put(
    "/projects/{project_id}/shot-definitions/{scene_id}/{shot_id}",
    response_model=ShotDefinitionsOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_shot_definition(
    project_id: int,
    scene_id: DiscoveryId,
    shot_id: DiscoveryId,
    body: ShotDefinitionIn,
    session: SessionDep,
) -> ShotDefinitionsOut:
    """Saves the edited specification of one shot as its next version, written by the user, and
    then runs the steps that follow a definition (references, request, prompt, continuity).
    """
    project = await load_project(session, project_id)
    try:
        await shot_definitions.save_manual(session, project, scene_id, shot_id, body.model_dump())
    except shot_definitions.ShotDefinitionsError as exc:
        raise _refused(exc) from exc
    await shot_chain.after_definition_saved(project_id, scene_id, shot_id)
    return await _state_out(session, project)
