"""`/api/projects/{project_id}/character-definitions`: the Character Definition stage (PHASE-009).

- `GET ...` answers everything the story workspace shows in one call: the newest list of
  characters, and for each entry its library character, its status (`unlinked`, `not_defined`,
  `defined`, `out_of_date`), why it is out of date, the definition the pinned version holds,
  the newest job, and whether Define may be pressed. Out of date is worked out on every read.
- `POST .../run` ("Define all") starts one job per linked character that the pipeline made,
  skipping (with the reason) a character chosen from the library, an archived one and one that
  is already being defined.
- `POST .../{discovery_id}/run` starts the job for one character. A character chosen from the
  library is overwritten only when the body says `confirm_overwrite: true`.

A job writes the definition onto the library character, as a new version the project pins
(`services/character_definitions.py`). The answers never return ORM objects. The definition
models here are also used by the Character Lab endpoints, which show it read-only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.api.character_links import DiscoveryId
from app.api.discovery import DiscoveryJobOut
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import character_definitions
from app.services.character_definitions import EntryDefinition

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no saved story, up-to-date Story Bible or list of characters, "
        "or the character is not linked, is archived, or needs confirming.",
    }
}

Source = Literal["ai", "manual"]
Status = Literal["unlinked", "not_defined", "defined", "out_of_date"]
EraKind = Literal["present", "past", "future"]


# --- The definition, as `Path_ahead.md` Section 11 gives it (plus species, mouth and era) ----


class VisualIdentityOut(BaseModel):
    apparent_age: int | None
    sex: str
    species: str
    has_visible_mouth: bool
    build: str
    height_character: str
    skin_tone: str
    face_shape: str
    hair: str
    eyes: str
    distinctive_features: str


class DefaultWardrobeOut(BaseModel):
    upper: str
    lower: str
    footwear: str


class VoiceIdentityOut(BaseModel):
    age_character: str
    pitch: str
    texture: str
    accent: str
    default_energy: str


class BehaviorOut(BaseModel):
    baseline: str
    gesture_style: str


class EraOut(BaseModel):
    kind: EraKind
    years: int | None
    setting: str | None


class CharacterDefinitionOut(BaseModel):
    id: str
    visual_identity: VisualIdentityOut
    default_wardrobe: DefaultWardrobeOut
    voice_identity: VoiceIdentityOut
    behavior: BehaviorOut
    era: EraOut


# --- The stage's state ----------------------------------------------------------------------


class DefinitionVersionOut(BaseModel):
    """The version of the library character that holds the definition (the one the project
    pins): the provenance of the definition (D-3).
    """

    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class DefinitionEntryOut(BaseModel):
    """One entry of the newest list of characters."""

    id: str
    name: str
    description: str
    # The library character the entry is linked to, and the version the project pins. None
    # while the entry is unlinked.
    character_id: int | None
    character_name: str | None
    pinned_version: int | None
    status: Status
    # Why a defined entry is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The definition the pinned version holds, when it was written for this entry in this
    # project. None otherwise.
    definition: CharacterDefinitionOut | None
    version: DefinitionVersionOut | None
    # The newest definition job of this entry, whatever its status.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None
    # True for a character chosen from the library: defining it overwrites its profile, so
    # the user is asked first.
    needs_confirmation: bool


class CharacterDefinitionsOut(BaseModel):
    # None when the project has no discovered characters yet.
    discovery_version: int | None
    entries: list[DefinitionEntryOut]
    # Why nothing can be defined yet (no saved story, or no up-to-date Story Bible), or None.
    blocked_reason: str | None


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required for a character chosen from the library (it is overwritten).
    confirm_overwrite: bool = False


class SkippedOut(BaseModel):
    discovery_id: str
    name: str
    reason: str


class RunAllOut(BaseModel):
    job_ids: list[int]
    skipped: list[SkippedOut]


class RunOut(BaseModel):
    job_id: int


def _entry_out(entry: EntryDefinition) -> DefinitionEntryOut:
    info = entry.entry.info
    version = entry.version
    job = entry.job
    definition = entry.definition
    return DefinitionEntryOut(
        id=entry.item["id"],
        name=entry.item["name"],
        description=entry.item["description"],
        character_id=info.character.id if info is not None else None,
        character_name=info.character.name if info is not None else None,
        pinned_version=info.link.pinned_version if info is not None else None,
        status=entry.status,
        reasons=entry.reasons,
        definition=(
            CharacterDefinitionOut.model_validate(definition) if definition is not None else None
        ),
        version=(
            DefinitionVersionOut(
                version=version.version,
                # The database CHECK constraint keeps `source` to the two allowed values.
                source=cast(Source, version.source),
                job_id=version.job_id,
                created_at=version.created_at,
            )
            if version is not None
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


def _refused(exc: character_definitions.CharacterDefinitionError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/character-definitions",
    response_model=CharacterDefinitionsOut,
    responses=_NOT_FOUND,
)
async def get_character_definitions(
    project_id: int, session: SessionDep
) -> CharacterDefinitionsOut:
    project = await load_project(session, project_id)
    result = await character_definitions.state(session, project)
    return CharacterDefinitionsOut(
        discovery_version=result.discovery_version,
        entries=[_entry_out(entry) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/character-definitions/run",
    response_model=RunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> RunAllOut:
    """Starts a job for every linked character the pipeline made. A character chosen from the
    library, an archived one and one already being defined are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await character_definitions.start_all(session, project)
    except character_definitions.CharacterDefinitionError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return RunAllOut(
        job_ids=started.job_ids,
        skipped=[
            SkippedOut(discovery_id=item.discovery_id, name=item.name, reason=item.reason)
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/character-definitions/{discovery_id}/run",
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_one(
    project_id: int,
    discovery_id: DiscoveryId,
    session: SessionDep,
    body: RunIn | None = None,
) -> RunOut:
    """Starts the job that defines one character. If it already has a job waiting or running,
    that job's id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await character_definitions.start_run(
            session,
            project,
            discovery_id,
            confirm_overwrite=body.confirm_overwrite if body is not None else False,
        )
    except character_definitions.CharacterDefinitionError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return RunOut(job_id=job.id)
