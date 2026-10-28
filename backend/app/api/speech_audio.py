"""`/api/projects/{project_id}/speech-audio`: the Speech stage of a story project (PHASE-019).

- `GET ...` answers where the audio of every speech unit stands, scene by scene: its status
  (`unavailable`, `none`, `in_progress`, `failed`, `ready`, `out_of_date`), the voice and Breeze
  mode it is spoken with, the stored audio and its **measured** length, why out-of-date audio
  no longer matches, and whether Make may be pressed. The units themselves (text, estimate) come
  from `GET .../speech-units`; this answer is keyed by their ids. All of it is worked out on
  every read.
- `POST .../run` ("Make all") starts the speech of every unit that has no current audio. The
  others are skipped, with the reason.
- `POST .../{scene_id}/{unit_id}/run` starts the speech of one unit, again if it is made.

A speech is made by the `synthesize_speech_unit` job (`services/speech_synthesis.py`). For an
explainer with captions or callouts on, each unit also says where the timing of its words stands
(`word_timing`, `services/word_timings.py`). The answers never return ORM objects.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel

from app.api.discovery import DiscoveryJobOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Job
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import speech_synthesis, word_timings
from app.services.speech_synthesis import UnitEntry
from app.services.storage import media_url

router = APIRouter()

UnitId = Annotated[str, Path(pattern=r"^su_[0-9]+$", max_length=24)]

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The scene or unit is not in the newest plan, the plan is out of date, "
        "or the unit has no voice to speak with yet.",
    }
}

Status = Literal["unavailable", "none", "in_progress", "failed", "ready", "out_of_date"]
Mode = Literal["clone", "direction"]
WordTimingStatus = Literal["none", "in_progress", "failed", "timed", "estimated"]


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


class SpeechAudioOut(BaseModel):
    """The stored speech of a unit and its measured length."""

    url: str
    measured_seconds: float
    sample_rate: int | None


class WordTimingOut(BaseModel):
    """Where the word timing of a unit's stored speech stands (EXPLAINER-007). `estimated`
    means too few words matched what Parakeet heard, so each word got its share of the speech's
    length instead.
    """

    status: WordTimingStatus
    # Of a timed or estimated speech: the share of script words that matched, the share that was
    # needed, and what Parakeet heard.
    match_percent: float | None
    threshold: int | None
    heard_text: str | None
    # Why a `failed` timing failed.
    error: str | None


class SpeechUnitAudioOut(BaseModel):
    """Where the audio of one speech unit stands."""

    unit_id: str
    status: Status
    # Why out-of-date audio no longer matches the unit, one sentence each.
    reasons: list[str]
    # The voice the unit is spoken in now, and how.
    voice_id: int | None
    voice_name: str | None
    mode: Mode | None
    instruction: str | None
    # The newest stored audio of what the unit is now. Plays while a new one is being made.
    audio: SpeechAudioOut | None
    # Why a `failed` speech failed.
    error: str | None
    can_run: bool
    blocked_reason: str | None
    # The newest job of this unit's current speech, whatever its status.
    job: DiscoveryJobOut | None
    # The time of each word of the stored speech. None unless the project is an explainer with
    # captions or callouts on, and the unit has stored audio.
    word_timing: WordTimingOut | None


class SpeechSceneAudioOut(BaseModel):
    scene_id: str
    units: list[SpeechUnitAudioOut]


class SpeechAudioStateOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    scenes: list[SpeechSceneAudioOut]
    # Why nothing can be made yet, or None.
    blocked_reason: str | None


class SpeechAudioSkippedOut(BaseModel):
    scene_id: str
    unit_id: str
    reason: str


class SpeechAudioRunAllOut(BaseModel):
    job_ids: list[int]
    skipped: list[SpeechAudioSkippedOut]


class SpeechAudioRunOut(BaseModel):
    job_id: int


def _word_timing_out(entry: word_timings.TimingEntry | None) -> WordTimingOut | None:
    if entry is None:
        return None
    timing = entry.timing
    return WordTimingOut(
        status=entry.status,
        match_percent=timing.match_percent if timing is not None else None,
        threshold=timing.threshold if timing is not None else None,
        heard_text=timing.heard_text if timing is not None else None,
        error=entry.error,
    )


def _unit_out(
    item: UnitEntry, timings: dict[int, word_timings.TimingEntry] | None
) -> SpeechUnitAudioOut:
    audio = item.audio
    return SpeechUnitAudioOut(
        unit_id=item.unit["id"],
        status=item.status,
        reasons=item.reasons,
        voice_id=item.voice.id if item.voice is not None else None,
        voice_name=item.voice.name if item.voice is not None else None,
        # The database CHECK constraint keeps the mode to the two allowed values.
        mode=cast(Mode | None, item.mode),
        instruction=item.instruction,
        audio=(
            SpeechAudioOut(
                url=media_url(audio.path),
                measured_seconds=audio.duration_s,
                sample_rate=audio.sample_rate,
            )
            if audio is not None and audio.path is not None and audio.duration_s is not None
            else None
        ),
        error=item.error,
        can_run=item.can_run,
        blocked_reason=item.blocked_reason,
        job=_job_out(item.job),
        word_timing=(
            _word_timing_out(timings.get(audio.id))
            if timings is not None and audio is not None
            else None
        ),
    )


def _refused(exc: speech_synthesis.SpeechSynthesisError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/speech-audio",
    response_model=SpeechAudioStateOut,
    responses=_NOT_FOUND,
)
async def get_speech_audio(project_id: int, session: SessionDep) -> SpeechAudioStateOut:
    project = await load_project(session, project_id)
    current = await speech_synthesis.state(session, project)
    timings = await word_timings.state(session, project) if word_timings.wanted(project) else None
    return SpeechAudioStateOut(
        scenes_version=current.scenes_version,
        scenes=[
            SpeechSceneAudioOut(
                scene_id=scene.scene.item["id"],
                units=[_unit_out(item, timings) for item in scene.units],
            )
            for scene in current.scenes
        ],
        blocked_reason=current.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/speech-audio/run",
    response_model=SpeechAudioRunAllOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> SpeechAudioRunAllOut:
    """Starts the speech of every unit that has no current audio. Every other unit is skipped,
    with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await speech_synthesis.start_all(session, project)
    except speech_synthesis.SpeechSynthesisError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return SpeechAudioRunAllOut(
        job_ids=started.job_ids,
        skipped=[
            SpeechAudioSkippedOut(scene_id=item.scene_id, unit_id=item.unit_id, reason=item.reason)
            for item in started.skipped
        ],
    )


@router.post(
    "/projects/{project_id}/speech-audio/{scene_id}/{unit_id}/run",
    response_model=SpeechAudioRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_one(
    project_id: int, scene_id: DiscoveryId, unit_id: UnitId, session: SessionDep
) -> SpeechAudioRunOut:
    """Starts the speech of one unit, again if it is made. Refused while that very speech is
    already being made.
    """
    project = await load_project(session, project_id)
    try:
        job = await speech_synthesis.start_unit(session, project, scene_id, unit_id)
    except speech_synthesis.SpeechSynthesisError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return SpeechAudioRunOut(job_id=job.id)
