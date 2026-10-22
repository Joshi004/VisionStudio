"""`/api/projects/{project_id}/speech-units`: the Speech Planning stage (PHASE-018).

- `GET ...` answers everything the story workspace shows in one call: the newest list of scenes,
  and for each scene its status (`not_planned`, `planned`, `out_of_date`), why it is out of
  date, its newest speech units with their provenance, and whether Plan may be pressed. Out of
  date is worked out on every read.
- `POST .../run` ("Plan all") plans every scene that has current events and no current plan.
- `POST .../{scene_id}/run` plans one scene and answers with that scene's entry. When the
  scene's newest units were written by the user, the body must confirm the replacement
  (PHASE-037).
- `PUT .../{scene_id}` saves the user's own cuts of the scene's speech events as its next version
  (`source` is `manual`). Only the cuts may move: the words stay as the events have them.

Planning is plain code, so it is done inside the request and nothing waits in a job. A plan is a
new version of the scene's speech units (`services/speech_units.py`). The answers never return ORM
objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.projects import load_project
from app.db.session import SessionDep
from app.services import speech_units
from app.services.speech_units import SceneEntry

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The scene has no current events, the speech rules cannot be used, or "
        "the scene is not in the newest list.",
    }
}

Source = Literal["ai", "manual"]
Status = Literal["not_planned", "planned", "out_of_date"]
UnitKind = Literal["narration", "dialogue"]


class SpeechUnitDeliveryOut(BaseModel):
    emotion: str


class SpeechUnitOut(BaseModel):
    """One speech unit. `speaker_id` is None for narration. `part` of `parts` says which piece of
    its event this is.
    """

    id: str
    event_id: str
    kind: UnitKind
    speaker_id: str | None
    text: str
    delivery: SpeechUnitDeliveryOut | None
    order: int
    part: int
    parts: int
    estimated_seconds: float


class SpeechUnitWarningOut(BaseModel):
    event_id: str
    message: str


class SpeechUnitsContentOut(BaseModel):
    scene_id: str
    units: list[SpeechUnitOut]
    warnings: list[SpeechUnitWarningOut]


class SpeechUnitsVersionOut(BaseModel):
    """The provenance of the newest plan of a scene (D-3)."""

    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class SpeechUnitsCharacterOut(BaseModel):
    id: str
    name: str


class SpeechUnitsEntryOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    description: str
    status: Status
    # Why a planned scene is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    units: SpeechUnitsContentOut | None
    version: SpeechUnitsVersionOut | None
    can_run: bool
    blocked_reason: str | None
    # True when planning this scene again would add a version after one the user wrote.
    needs_confirmation: bool


class SpeechUnitsOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    # The discovered characters, so that a speaker can be shown by name.
    characters: list[SpeechUnitsCharacterOut]
    entries: list[SpeechUnitsEntryOut]
    # Why nothing can be planned yet, or None.
    blocked_reason: str | None


class SpeechUnitsSkippedOut(BaseModel):
    scene_id: str
    title: str
    reason: str


class SpeechUnitsRunAllOut(BaseModel):
    planned: list[str]
    skipped: list[SpeechUnitsSkippedOut]


class SpeechUnitsRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False


class SpeechUnitIn(BaseModel):
    """One piece of an event's text, as the user cut it. The words are checked against the event
    by `speech_unit_planner.plan_units`; the limit only keeps a request from being huge.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(max_length=200)
    text: str = Field(max_length=20000)


class SpeechUnitsSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units: list[SpeechUnitIn] = Field(max_length=1000)


def _entry_out(entry: SceneEntry) -> SpeechUnitsEntryOut:
    row = entry.row
    content = entry.content
    return SpeechUnitsEntryOut(
        id=entry.item["id"],
        index=entry.item["index"],
        title=entry.item["title"],
        description=entry.item["description"],
        status=entry.status,
        reasons=entry.reasons,
        units=SpeechUnitsContentOut.model_validate(content) if content is not None else None,
        version=(
            SpeechUnitsVersionOut(
                version=row.version,
                # The database CHECK constraint keeps `source` to the two allowed values.
                source=cast(Source, row.source),
                job_id=row.job_id,
                created_at=row.created_at,
            )
            if row is not None
            else None
        ),
        can_run=entry.can_run,
        blocked_reason=entry.blocked_reason,
        needs_confirmation=entry.needs_confirmation,
    )


def _out(result: speech_units.SpeechState) -> SpeechUnitsOut:
    return SpeechUnitsOut(
        scenes_version=result.scenes_version,
        characters=[SpeechUnitsCharacterOut(**character) for character in result.characters],
        entries=[_entry_out(entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


def _refused(exc: speech_units.SpeechUnitsError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/speech-units",
    response_model=SpeechUnitsOut,
    responses=_NOT_FOUND,
)
async def get_speech_units(project_id: int, session: SessionDep) -> SpeechUnitsOut:
    project = await load_project(session, project_id)
    return _out(await speech_units.state(session, project))


@router.post(
    "/projects/{project_id}/speech-units/run",
    response_model=SpeechUnitsRunAllOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> SpeechUnitsRunAllOut:
    """Plans every scene that has current events and no current plan. The others are skipped,
    with the reason.
    """
    project = await load_project(session, project_id)
    try:
        result = await speech_units.plan_all(session, project)
    except speech_units.SpeechUnitsError as exc:
        raise _refused(exc) from exc
    return SpeechUnitsRunAllOut(
        planned=result.planned,
        skipped=[
            SpeechUnitsSkippedOut(scene_id=item.scene_id, title=item.title, reason=item.reason)
            for item in result.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/speech-units/{scene_id}/run",
    response_model=SpeechUnitsEntryOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_one(
    project_id: int,
    scene_id: DiscoveryId,
    session: SessionDep,
    body: SpeechUnitsRunIn | None = None,
) -> SpeechUnitsEntryOut:
    """Plans one scene's speech units, as a new version, and answers with the scene's entry."""
    project = await load_project(session, project_id)
    try:
        await speech_units.plan_scene(
            session,
            project,
            scene_id,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except speech_units.SpeechUnitsError as exc:
        raise _refused(exc) from exc
    current = await speech_units.state(session, project)
    entry = next(item for item in current.entries if item.item["id"] == scene_id)
    return _entry_out(entry)


@router.put(
    "/projects/{project_id}/speech-units/{scene_id}",
    response_model=SpeechUnitsEntryOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_units(
    project_id: int, scene_id: DiscoveryId, body: SpeechUnitsSaveIn, session: SessionDep
) -> SpeechUnitsEntryOut:
    """Saves the user's own cuts of one scene's speech events as its next version."""
    project = await load_project(session, project_id)
    try:
        await speech_units.save_manual(
            session, project, scene_id, [unit.model_dump() for unit in body.units]
        )
    except speech_units.SpeechUnitsError as exc:
        raise _refused(exc) from exc
    current = await speech_units.state(session, project)
    entry = next(item for item in current.entries if item.item["id"] == scene_id)
    return _entry_out(entry)
