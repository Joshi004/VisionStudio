"""`/api/lab/voices` and `/api/voices`: the Voice lab and the saved voices (Phase 21).

`POST /api/lab/voices/runs` checks the form and starts one run with HTTP 202: a run is a GPU job
of one to three minutes, so the page follows it by itself (each run carries its job, the same
one the Activity page shows).

A saved voice is a clean recording and its exact transcript. It comes from an upload
(`POST /api/voices`, the recording as the raw request body, with the name and the transcript in
the query) or from a run (`POST /api/lab/voices/runs/{id}/save-voice`). The lab's clone and
direction modes use it.

Breeze TTS 2's weights and outputs are licensed for research and non-commercial use only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from app.api.errors import ErrorResponse
from app.api.jobs import JobSummary, job_summary
from app.api.projects import content_length, require_octet_stream
from app.db.models import Voice
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import voice_lab, voices
from app.services.storage import media_url

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
Id = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]
RunId = Annotated[int, Path(ge=1, le=_MAX_ID)]
VoiceId = Annotated[int, Path(ge=1, le=_MAX_ID)]

_INVALID = {422: {"model": ErrorResponse, "description": "The form breaks a rule."}}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "There is no such run or voice."}}
_UPLOAD_BODY: Final[dict[str, Any]] = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


class VoiceOut(BaseModel):
    id: int
    created_at: datetime
    name: str
    # "upload": a recording that was uploaded. "lab_run": a speech the Voice lab made.
    origin: Literal["upload", "lab_run"]
    url: str
    mime: str
    duration_s: float
    size_bytes: int
    # What the recording says, word for word.
    transcript: str
    lab_voice_run_id: int | None


class VoiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr | None = None
    transcript: StrictStr | None = None


class VoiceFromRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    # Left out: the text of the run.
    transcript: StrictStr | None = None


class LabVoiceRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["design", "clone", "direction"]
    text: StrictStr
    # design: describes the voice (optional). direction: how to say it (needed). clone: none.
    instruction: StrictStr | None = None
    # clone and direction: the saved voice. design: none.
    voice_id: Id | None = None
    # Left out: a random seed.
    seed: StrictInt | None = None
    # Left out: 4 with an instruction, 1 without.
    cfg_scale: Annotated[float, Field(allow_inf_nan=False)] | None = None


class VoiceBrief(BaseModel):
    id: int
    name: str


class LabVoiceRunOut(BaseModel):
    id: int
    created_at: datetime
    mode: Literal["design", "clone", "direction"]
    text: str
    instruction: str | None
    # The saved voice that read the text. None for design, or when the voice is gone.
    voice: VoiceBrief | None
    # What was sent: seed and cfg_scale.
    params: dict[str, Any]
    # The run's job: its status, phase and error.
    job: JobSummary | None
    # The finished WAV, from /media. None until then.
    url: str | None
    size_bytes: int | None
    duration_s: float | None


def _voice_out(voice: Voice) -> VoiceOut:
    return VoiceOut(
        id=voice.id,
        created_at=voice.created_at,
        name=voice.name,
        origin="lab_run" if voice.origin == "lab_run" else "upload",
        url=media_url(voice.path),
        mime=voice.mime,
        duration_s=voice.duration_s,
        size_bytes=voice.size_bytes,
        transcript=voice.transcript,
        lab_voice_run_id=voice.lab_voice_run_id,
    )


def run_out(row: voice_lab.RunRow) -> LabVoiceRunOut:
    run = row.run
    mode: Literal["design", "clone", "direction"] = (
        "clone" if run.mode == "clone" else "direction" if run.mode == "direction" else "design"
    )
    return LabVoiceRunOut(
        id=run.id,
        created_at=run.created_at,
        mode=mode,
        text=run.text,
        instruction=run.instruction,
        voice=VoiceBrief(id=row.voice.id, name=row.voice.name) if row.voice is not None else None,
        params=run.params if isinstance(run.params, dict) else {},
        job=(
            job_summary(JobRow(job=row.job, project_name=store.owner_name(row.job, None)))
            if row.job is not None
            else None
        ),
        url=media_url(run.path) if run.path is not None else None,
        size_bytes=run.size_bytes,
        duration_s=run.duration_s,
    )


def _voice_error(exc: voices.VoiceInputError) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


# --- The Voice lab -------------------------------------------------------------------------


@router.post(
    "/lab/voices/runs",
    response_model=LabVoiceRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_INVALID,
)
async def create_run(body: LabVoiceRunCreate, session: SessionDep) -> LabVoiceRunOut:
    """Starts one run. It is a paid GPU job of one to three minutes."""
    form = voice_lab.VoiceLabForm(
        mode=body.mode,
        text=body.text,
        instruction=body.instruction,
        voice_id=body.voice_id,
        seed=body.seed,
        cfg_scale=body.cfg_scale,
    )
    try:
        row = await voice_lab.create_run(session, form)
    except voice_lab.VoiceLabInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return run_out(row)


@router.get("/lab/voices/runs", response_model=list[LabVoiceRunOut])
async def list_runs(
    session: SessionDep,
    before_id: Annotated[int | None, Query(ge=1, le=_MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[LabVoiceRunOut]:
    """The newest runs first. Pass the last id you have as `before_id` for the next page."""
    rows = await voice_lab.list_runs(session, before_id, limit)
    return [run_out(row) for row in rows]


@router.get("/lab/voices/runs/{run_id}", response_model=LabVoiceRunOut, responses=_NOT_FOUND)
async def get_run(run_id: RunId, session: SessionDep) -> LabVoiceRunOut:
    row = await voice_lab.get_run(session, run_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} does not exist.")
    return run_out(row)


@router.post(
    "/lab/voices/runs/{run_id}/save-voice",
    response_model=VoiceOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        **_NOT_FOUND,
        **_INVALID,
        409: {"model": ErrorResponse, "description": "The run has no speech yet."},
    },
)
async def save_run_as_voice(run_id: RunId, body: VoiceFromRun, session: SessionDep) -> VoiceOut:
    """Saves the speech of a finished run as a voice that can be cloned. The transcript is what
    the speech says: left out, it is the run's text.
    """
    try:
        voice = await voices.create_from_run(session, run_id, body.name, body.transcript)
    except voices.VoiceInputError as exc:
        raise _voice_error(exc) from exc
    return _voice_out(voice)


# --- Saved voices --------------------------------------------------------------------------


@router.get("/voices", response_model=list[VoiceOut])
async def list_voices(session: SessionDep) -> list[VoiceOut]:
    """The saved voices, newest first."""
    return [_voice_out(voice) for voice in await voices.list_voices(session)]


@router.post(
    "/voices",
    response_model=VoiceOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        413: {"model": ErrorResponse, "description": "The file is larger than the limit."},
        415: {
            "model": ErrorResponse,
            "description": "The body is not sent as application/octet-stream.",
        },
        422: {"model": ErrorResponse, "description": "The file or a text is not acceptable."},
    },
    openapi_extra=_UPLOAD_BODY,
)
async def upload_voice(
    request: Request,
    session: SessionDep,
    name: Annotated[str, Query(max_length=400)],
    transcript: Annotated[str, Query(max_length=4000)],
) -> VoiceOut:
    """Saves a recording (WAV, MP3, M4A or FLAC, sent as the raw request body) as a voice.
    `transcript` is what it says, word for word.
    """
    require_octet_stream(request)
    # No transaction of this request stays open while the file is received and probed.
    await session.commit()
    try:
        voice = await voices.create_from_upload(
            session, name, transcript, request.stream(), content_length(request)
        )
    except voices.VoiceInputError as exc:
        raise _voice_error(exc) from exc
    return _voice_out(voice)


@router.patch("/voices/{voice_id}", response_model=VoiceOut, responses={**_NOT_FOUND, **_INVALID})
async def update_voice(voice_id: VoiceId, body: VoiceUpdate, session: SessionDep) -> VoiceOut:
    """Changes a voice's name and/or transcript. The recording stays."""
    try:
        voice = await voices.update_voice(session, voice_id, body.name, body.transcript)
    except voices.VoiceInputError as exc:
        raise _voice_error(exc) from exc
    return _voice_out(voice)
