"""Transcription of a project's voiceover (ANALYSIS.md Section 5.1).

`POST /api/projects/{id}/transcribe` creates the job and returns at once with HTTP 202.
The dispatcher does the work. `GET /api/projects/{id}/transcription` reads the database
only: the newest transcribe job and the newest transcript, with the counts, the mismatch
warning and whether the transcript is out of date.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.api.projects import load_project
from app.db.models import Transcript
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import transcripts as transcripts_service
from app.services.transcript_matching import MatchCounts

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No project has this id."}}
_NOT_READY = {
    422: {"model": ErrorResponse, "description": "The project has no voiceover or no script yet."}
}


class ScriptWordOut(BaseModel):
    index: int
    word: str
    start: float
    end: float
    # False: the recogniser did not hear this word, and its times are interpolated.
    matched: bool
    paragraph: int


class TranscriptCountsOut(BaseModel):
    script_words: int
    matched: int
    interpolated: int
    spoken_words: int
    extra_spoken: int


class TranscriptOut(BaseModel):
    id: int
    created_at: datetime
    provider: str
    voiceover_asset_id: int | None
    script_words: list[ScriptWordOut]
    counts: TranscriptCountsOut
    warnings: list[str]
    stale_reasons: list[Literal["script_changed", "voiceover_changed"]]
    processing_time: float | None


class TranscriptionOut(BaseModel):
    job: JobSummary | None
    transcript: TranscriptOut | None


def _transcript_out(
    transcript: Transcript,
    counts: MatchCounts,
    warnings: list[str],
    stale: list[transcripts_service.StaleReason],
    processing_time: float | None,
) -> TranscriptOut:
    return TranscriptOut(
        id=transcript.id,
        created_at=transcript.created_at,
        provider=transcript.provider,
        voiceover_asset_id=transcript.voiceover_asset_id,
        script_words=[ScriptWordOut(**entry) for entry in transcript.script_words],
        counts=TranscriptCountsOut(
            script_words=counts.script_words,
            matched=counts.matched,
            interpolated=counts.interpolated,
            spoken_words=counts.spoken_words,
            extra_spoken=counts.extra_spoken,
        ),
        warnings=warnings,
        stale_reasons=stale,
        processing_time=processing_time,
    )


@router.post(
    "/projects/{project_id}/transcribe",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_NOT_READY},
)
async def start_transcription(project_id: int, session: SessionDep) -> JobDetail:
    """Starts transcribing the voiceover, or returns the job that is already active."""
    project = await load_project(session, project_id)
    if project.voiceover_asset_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload a voiceover first.")
    if project.script_text is None or not project.script_text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Paste the script first.")

    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=transcripts_service.TRANSCRIBE_JOB,
        provider="gpu",
        input={"voiceover_asset_id": project.voiceover_asset_id},
    )
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=None))


@router.get(
    "/projects/{project_id}/transcription",
    response_model=TranscriptionOut,
    responses=_NOT_FOUND,
)
async def get_transcription(project_id: int, session: SessionDep) -> TranscriptionOut:
    """The newest transcribe job and transcript of the project. Reads the database only."""
    project = await load_project(session, project_id)
    state = await transcripts_service.transcription_state(session, project)

    transcript_out = None
    if state.transcript is not None and state.counts is not None:
        transcript_out = _transcript_out(
            state.transcript,
            state.counts,
            state.warnings,
            state.stale_reasons,
            state.processing_time,
        )
    job_out = None
    if state.job is not None:
        job_out = job_summary(JobRow(job=state.job, project_name=project.name, scene_index=None))
    return TranscriptionOut(job=job_out, transcript=transcript_out)
