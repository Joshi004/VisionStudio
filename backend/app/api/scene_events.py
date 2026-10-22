"""`/api/projects/{project_id}/scene-events`: the Event Extraction stage (PHASE-015).

- `GET ...` answers everything the story workspace shows in one call: the newest list of
  scenes, and for each scene its status (`not_extracted`, `extracted`, `out_of_date`), why it is
  out of date, its newest events with their provenance, the newest job, and whether Extract may
  be pressed. Out of date is worked out on every read.
- `POST .../run` ("Extract all") starts one job per scene that is not extracted and up to date
  already, is defined and is not already being extracted.
- `POST .../{scene_id}/run` starts the job for one scene. When the scene's newest events were
  written by the user, the body must confirm the replacement (PHASE-037).
- `PUT .../{scene_id}` saves the user's edited events of one scene as its next version (`source`
  is `manual`). They are checked like the model's answer, including that every speech event is
  found in the scene's text in order.

A job stores a new version of the scene's events (`services/scene_events.py`); nothing is
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
from app.services import scene_events
from app.services.scene_events import SceneEntry

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no saved story, up-to-date Story Bible or lists, or the scene "
        "is not defined yet, or the scene is not in the newest list.",
    }
}

Source = Literal["ai", "manual"]
Status = Literal["not_extracted", "extracted", "out_of_date"]
EventType = Literal["narration", "dialogue", "action", "sound_event", "pause"]


# --- The events, as `Path_ahead.md` Section 17 gives them -----------------------------------


class SceneEventDeliveryOut(BaseModel):
    emotion: str


class SceneEventOut(BaseModel):
    """One event. Which fields are set depends on `type`: `narration` has `text`; `dialogue`
    has `speaker_id`, `text` and maybe `delivery`; `action` and `sound_event` have
    `description`; `pause` has none of them.
    """

    id: str
    type: EventType
    text: str | None = None
    speaker_id: str | None = None
    delivery: SceneEventDeliveryOut | None = None
    description: str | None = None


class SceneUncoveredOut(BaseModel):
    """A piece of the scene's text that no narration or dialogue event covers."""

    text: str
    # The speech event the text follows, or None for text before the first one.
    after_event_id: str | None


class SceneEventsContentOut(BaseModel):
    scene_id: str
    events: list[SceneEventOut]
    uncovered: list[SceneUncoveredOut]


# --- The stage's state ----------------------------------------------------------------------


class SceneEventsVersionOut(BaseModel):
    """The provenance of the newest events of a scene (D-3)."""

    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class SceneEventsCharacterOut(BaseModel):
    id: str
    name: str


class SceneEventsEntryOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    description: str
    status: Status
    # Why an extracted scene is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    events: SceneEventsContentOut | None
    version: SceneEventsVersionOut | None
    # The newest extraction job of this scene, whatever its status.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None
    # True when extracting this scene again would add a version after one the user wrote.
    needs_confirmation: bool


class SceneEventsOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    # The discovered characters, so that a speaker can be shown by name.
    characters: list[SceneEventsCharacterOut]
    entries: list[SceneEventsEntryOut]
    # Why nothing can be extracted yet, or None.
    blocked_reason: str | None


class SceneEventsSkippedOut(BaseModel):
    scene_id: str
    title: str
    reason: str


class SceneEventsRunAllOut(BaseModel):
    job_ids: list[int]
    skipped: list[SceneEventsSkippedOut]


class SceneEventsRunOut(BaseModel):
    job_id: int


class SceneEventsRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False


class SceneEventDeliveryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emotion: str | None = Field(default=None, max_length=1000)


class SceneEventIn(BaseModel):
    """One event of an edited list. Which fields count depends on `type` (see `SceneEventOut`);
    the rules are checked by `event_extraction_writer.check_answer`, and the id is set by code.
    These limits only keep a request from being huge.
    """

    model_config = ConfigDict(extra="forbid")

    type: EventType
    text: str | None = Field(default=None, max_length=20000)
    speaker_id: str | None = Field(default=None, max_length=200)
    delivery: SceneEventDeliveryIn | None = None
    description: str | None = Field(default=None, max_length=5000)


class SceneEventsSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[SceneEventIn] = Field(max_length=500)


def _entry_out(entry: SceneEntry) -> SceneEventsEntryOut:
    row = entry.row
    job = entry.job
    content = entry.content
    return SceneEventsEntryOut(
        id=entry.item["id"],
        index=entry.item["index"],
        title=entry.item["title"],
        description=entry.item["description"],
        status=entry.status,
        reasons=entry.reasons,
        events=SceneEventsContentOut.model_validate(content) if content is not None else None,
        version=(
            SceneEventsVersionOut(
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
        needs_confirmation=entry.needs_confirmation,
    )


def _refused(exc: scene_events.SceneEventsError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/scene-events",
    response_model=SceneEventsOut,
    responses=_NOT_FOUND,
)
async def get_scene_events(project_id: int, session: SessionDep) -> SceneEventsOut:
    project = await load_project(session, project_id)
    return await _state_out(session, project)


async def _state_out(session: AsyncSession, project: Project) -> SceneEventsOut:
    result = await scene_events.state(session, project)
    return SceneEventsOut(
        scenes_version=result.scenes_version,
        characters=[SceneEventsCharacterOut(**character) for character in result.characters],
        entries=[_entry_out(entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/scene-events/run",
    response_model=SceneEventsRunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> SceneEventsRunAllOut:
    """Starts a job for every scene that is not extracted and up to date already, is defined
    and is not already being extracted. The others are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await scene_events.start_all(session, project)
    except scene_events.SceneEventsError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return SceneEventsRunAllOut(
        job_ids=started.job_ids,
        skipped=[
            SceneEventsSkippedOut(scene_id=item.scene_id, title=item.title, reason=item.reason)
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/scene-events/{scene_id}/run",
    response_model=SceneEventsRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_one(
    project_id: int,
    scene_id: DiscoveryId,
    session: SessionDep,
    body: SceneEventsRunIn | None = None,
) -> SceneEventsRunOut:
    """Starts the job that extracts one scene's events. If it already has a job waiting or
    running, that job's id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await scene_events.start_run(
            session,
            project,
            scene_id,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except scene_events.SceneEventsError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return SceneEventsRunOut(job_id=job.id)


@router.put(
    "/projects/{project_id}/scene-events/{scene_id}",
    response_model=SceneEventsOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_events(
    project_id: int, scene_id: DiscoveryId, body: SceneEventsSaveIn, session: SessionDep
) -> SceneEventsOut:
    """Saves the whole edited list of events of one scene as its next version, written by the
    user. Events are numbered again in the order given.
    """
    project = await load_project(session, project_id)
    try:
        await scene_events.save_manual(
            session,
            project,
            scene_id,
            [event.model_dump(exclude_none=True) for event in body.events],
        )
    except scene_events.SceneEventsError as exc:
        raise _refused(exc) from exc
    return await _state_out(session, project)
