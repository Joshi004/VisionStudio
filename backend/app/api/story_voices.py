"""`/api/projects/{project_id}/character-voices` and `.../narrator-voice`: the Voices stage of a
story project (PHASE-011).

- `GET .../character-voices` answers everything the story workspace shows for the characters in
  one call: the newest list of characters, and for each entry its library character and pinned
  version, the status of its voice (`unavailable`, `none`, `in_progress`, `failed`, `ready`,
  `out_of_date`), where an unfinished voice is, the description it was designed from, the saved
  voice and whether Make voice may be pressed. All of it is worked out on every read.
- `POST .../character-voices/run` ("Make voices for all") starts a voice for every defined
  character the pipeline made that has none yet, whose voice failed or is out of date, and for
  the narrator when it has none or an out-of-date derived one. Every other voice is skipped,
  with the reason (the narrator is listed as `narrator`).
- `POST .../character-voices/{discovery_id}/run` starts the voice of one character. A character
  chosen from the library gets one only when the body says `confirm_overwrite: true`.
- `GET .../narrator-voice` answers the narrator's newest voice and its status.
- `POST .../narrator-voice/run` derives the narrator's voice from the StoryBible. It replaces a
  voice chosen by hand only when the body says `confirm_replace_manual: true`.
- `PUT .../narrator-voice` makes a saved voice the narrator's.

A voice is made by the `design_voice` job and one Voice lab run (`services/story_voices.py`).
The answers never return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.character_links import DiscoveryId
from app.api.discovery import DiscoveryJobOut
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.api.voice_lab import VoiceOut, voice_out
from app.db.models import Job
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import story_voices
from app.services.story_voices import EntryVoice, NarratorState

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is nothing to make a voice for yet, or the voice breaks a rule: "
        "not linked, not defined, out of date, archived, or needs confirming.",
    }
}

Status = Literal["unavailable", "none", "in_progress", "failed", "ready", "out_of_date"]
Stage = Literal["writing_description", "making_sample"]
DefinitionStatus = Literal["unlinked", "not_defined", "defined", "out_of_date"]


def _job_out(job: Job | None) -> DiscoveryJobOut | None:
    if job is None:
        return None
    return DiscoveryJobOut(
        id=job.id,
        # The database CHECK constraint keeps this to the allowed values.
        status=cast(JobStatus, job.status),
        phase=job.phase,
        error=job.error,
    )


class StoryVoiceEntryOut(BaseModel):
    """One entry of the newest list of characters."""

    id: str
    name: str
    description: str
    # The library character the entry is linked to, and the version the project pins. None
    # while the entry is unlinked.
    character_id: int | None
    character_name: str | None
    pinned_version: int | None
    # Where the definition stands (`Status` of the Character Definition stage).
    definition_status: DefinitionStatus
    status: Status
    # Only while `status` is `in_progress`.
    stage: Stage | None
    # What the voice was designed from, once the model has written it.
    instruction: str | None
    # The saved voice, once there is one.
    voice: VoiceOut | None
    # Why a `failed` voice failed.
    error: str | None
    # Why a `ready` voice is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    can_run: bool
    blocked_reason: str | None
    # True for a character chosen from the library: a voice replaces its voice, so the user is
    # asked first.
    needs_confirmation: bool
    # The newest voice job of this character, whatever its status.
    job: DiscoveryJobOut | None


class StoryVoicesOut(BaseModel):
    # None when the project has no discovered characters yet.
    discovery_version: int | None
    entries: list[StoryVoiceEntryOut]


class StoryVoiceRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required for a character chosen from the library.
    confirm_overwrite: bool = False


class StoryVoiceSkippedOut(BaseModel):
    # The discovered character's id, or `narrator`.
    discovery_id: str
    name: str
    reason: str


class StoryVoiceRunAllOut(BaseModel):
    job_ids: list[int]
    skipped: list[StoryVoiceSkippedOut]


class StoryVoiceRunOut(BaseModel):
    job_id: int


class NarratorVersionOut(BaseModel):
    version: int
    # `ai`: derived from the StoryBible. `manual`: a saved voice chosen by hand.
    source: Literal["ai", "manual"]
    created_at: datetime
    job_id: int | None
    # The StoryBible version an `ai` voice was derived from.
    story_bible_version: int | None


class NarratorVoiceOut(BaseModel):
    status: Status
    stage: Stage | None
    # The narrator's newest voice version and its saved voice. None until there is one.
    version: NarratorVersionOut | None
    voice: VoiceOut | None
    # What an `ai` voice was designed from.
    instruction: str | None
    error: str | None
    reasons: list[str]
    # The newest StoryBible version, which a voice is derived from. None when there is none.
    story_bible_version: int | None
    can_run: bool
    blocked_reason: str | None
    # True when the voice was chosen by hand: deriving one replaces it, so the user is asked.
    needs_confirmation: bool
    job: DiscoveryJobOut | None


class NarratorRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required when the narrator's voice was chosen by hand.
    confirm_replace_manual: bool = False


class NarratorRunOut(BaseModel):
    job_id: int


class NarratorChooseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_id: Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]


def _entry_out(item: EntryVoice) -> StoryVoiceEntryOut:
    definition = item.definition
    info = definition.entry.info
    return StoryVoiceEntryOut(
        id=definition.item["id"],
        name=definition.item["name"],
        description=definition.item["description"],
        character_id=info.character.id if info is not None else None,
        character_name=info.character.name if info is not None else None,
        pinned_version=info.link.pinned_version if info is not None else None,
        definition_status=definition.status,
        status=item.status,
        stage=item.stage,
        instruction=item.instruction,
        voice=voice_out(item.voice) if item.voice is not None else None,
        error=item.error,
        reasons=item.reasons,
        can_run=item.can_run,
        blocked_reason=item.blocked_reason,
        needs_confirmation=item.needs_confirmation,
        job=_job_out(item.job),
    )


def _narrator_out(narrator: NarratorState) -> NarratorVoiceOut:
    version = narrator.version
    inputs = version.inputs if version is not None and isinstance(version.inputs, dict) else {}
    bible_version = inputs.get("story_bible_version")
    return NarratorVoiceOut(
        status=narrator.status,
        stage=narrator.stage,
        version=(
            NarratorVersionOut(
                version=version.version,
                source="ai" if version.source == "ai" else "manual",
                created_at=version.created_at,
                job_id=version.job_id,
                story_bible_version=bible_version if isinstance(bible_version, int) else None,
            )
            if version is not None
            else None
        ),
        voice=voice_out(narrator.voice) if narrator.voice is not None else None,
        instruction=narrator.instruction,
        error=narrator.error,
        reasons=narrator.reasons,
        story_bible_version=narrator.story_bible_version,
        can_run=narrator.can_run,
        blocked_reason=narrator.blocked_reason,
        needs_confirmation=narrator.needs_confirmation,
        job=_job_out(narrator.job),
    )


def _refused(exc: story_voices.StoryVoiceError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


# --- Characters ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/character-voices",
    response_model=StoryVoicesOut,
    responses=_NOT_FOUND,
)
async def get_character_voices(project_id: int, session: SessionDep) -> StoryVoicesOut:
    project = await load_project(session, project_id)
    result = await story_voices.state(session, project)
    return StoryVoicesOut(
        discovery_version=result.discovery_version,
        entries=[_entry_out(item) for item in result.entries],
    )


@router.post(
    "/projects/{project_id}/character-voices/run",
    response_model=StoryVoiceRunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> StoryVoiceRunAllOut:
    """Starts a voice for every defined character the pipeline made that has none yet, whose
    voice failed or is out of date, and for the narrator when it has none or an out-of-date
    derived one. Every other voice is skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await story_voices.start_all(session, project)
    except story_voices.StoryVoiceError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return StoryVoiceRunAllOut(
        job_ids=started.job_ids,
        skipped=[
            StoryVoiceSkippedOut(discovery_id=item.discovery_id, name=item.name, reason=item.reason)
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/character-voices/{discovery_id}/run",
    response_model=StoryVoiceRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_one(
    project_id: int,
    discovery_id: DiscoveryId,
    session: SessionDep,
    body: StoryVoiceRunIn | None = None,
) -> StoryVoiceRunOut:
    """Starts the voice of one character. If it is already being made, that job's id is
    returned and no second voice is made.
    """
    project = await load_project(session, project_id)
    try:
        job, created = await story_voices.start_run(
            session,
            project,
            discovery_id,
            confirm_overwrite=body.confirm_overwrite if body is not None else False,
        )
    except story_voices.StoryVoiceError as exc:
        raise _refused(exc) from exc
    if created:
        dispatcher.nudge()
    return StoryVoiceRunOut(job_id=job.id)


# --- The narrator -------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/narrator-voice",
    response_model=NarratorVoiceOut,
    responses=_NOT_FOUND,
)
async def get_narrator_voice(project_id: int, session: SessionDep) -> NarratorVoiceOut:
    project = await load_project(session, project_id)
    return _narrator_out(await story_voices.narrator_state(session, project))


@router.post(
    "/projects/{project_id}/narrator-voice/run",
    response_model=NarratorRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_narrator(
    project_id: int, session: SessionDep, body: NarratorRunIn | None = None
) -> NarratorRunOut:
    """Derives the narrator's voice from the StoryBible. If one is already being made, that
    job's id is returned and no second voice is made.
    """
    project = await load_project(session, project_id)
    try:
        job, created = await story_voices.start_narrator(
            session,
            project,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except story_voices.StoryVoiceError as exc:
        raise _refused(exc) from exc
    if created:
        dispatcher.nudge()
    return NarratorRunOut(job_id=job.id)


@router.put(
    "/projects/{project_id}/narrator-voice",
    response_model=NarratorVoiceOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def choose_narrator_voice(
    project_id: int, body: NarratorChooseIn, session: SessionDep
) -> NarratorVoiceOut:
    """Makes a saved voice the narrator's, as a new version chosen by hand."""
    project = await load_project(session, project_id)
    try:
        await story_voices.choose_narrator(session, project, body.voice_id)
    except story_voices.StoryVoiceError as exc:
        raise _refused(exc) from exc
    return _narrator_out(await story_voices.narrator_state(session, project))
