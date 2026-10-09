"""`/api/lab/videos`: the Video lab (Phase 19). Try a prompt on LTX-2.3 and LTX-2.5.

`POST .../runs` checks the form and starts one run per chosen model, then returns at once with
HTTP 202: a run is a GPU job of 5 to 10 minutes, so the page follows it by itself (each run
carries its job, the same one the Activity page shows). Two models make two runs with the same
prompt, first frame, size, length, recipe and seed, so the clips differ only by the model.

`POST .../prompt-drafts` starts the paid job that writes a multi-shot prompt from an idea. It
answers with that job; its `output.prompt` is what the page puts in the form.

The first frame is picked from what the Image lab holds (`/api/lab/images/library`,
`/api/lab/images/uploads`, `/api/lab/images/project-frames`): a run refers to it by
`{source, id}` and never copies it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.db.models import Asset, LabImage
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import video_lab
from app.services.storage import media_url
from app.services.video_models import VideoModel

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1

_INVALID = {422: {"model": ErrorResponse, "description": "The form breaks a rule."}}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No run has this id."}}

Id = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]


class FirstFrameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # "lab": an image the Image lab holds (an upload or a result). "asset": a project's frame.
    source: Literal["lab", "asset"]
    id: Id


class LabVideoRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: StrictStr
    # One model, or both: two runs that differ only by the model.
    models: list[VideoModel] = Field(min_length=1, max_length=video_lab.MAX_MODELS)
    mode: Literal["quality", "fast"]
    orientation: Literal["landscape", "portrait"]
    duration_s: Annotated[float, Field(allow_inf_nan=False)]
    # Left out: a random seed, shared by the runs of one click.
    seed: StrictInt | None = None
    # LTX-2.3 only. Left out or blank: the pipeline's own default applies.
    negative_prompt: StrictStr | None = None
    first_frame: FirstFrameIn | None = None


class PromptDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea: StrictStr
    shots: StrictInt
    duration_s: Annotated[float, Field(allow_inf_nan=False)]
    # What the first frame shows, when the clip will start from one.
    first_frame_note: StrictStr | None = None


class FirstFrameOut(BaseModel):
    source: Literal["lab", "asset"]
    id: int
    # The image, for a thumbnail. None when it is gone.
    url: str | None


class LabVideoRunOut(BaseModel):
    id: int
    created_at: datetime
    # The runs that one click started share it. The page shows them side by side.
    group_key: str | None
    video_model: VideoModel
    endpoint: str
    prompt: str
    # What the form held and what was sent: mode, orientation, size, fps, duration, frame count,
    # seed and, for LTX-2.3, the negative prompt.
    params: dict[str, Any]
    first_frame: FirstFrameOut | None
    # The run's job: its status, phase and error, with cancel and resubmit.
    job: JobSummary | None
    # The finished clip, from /media (with Range requests, so it seeks). None until then.
    url: str | None
    size_bytes: int | None
    width: int | None
    height: int | None
    frame_count: int | None
    duration_s: float | None
    audio_codec: str | None


class LabVideoRunsOut(BaseModel):
    runs: list[LabVideoRunOut]


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


async def _frame_urls(
    session: AsyncSession, rows: list[video_lab.RunRow]
) -> dict[tuple[str, int], str]:
    """The stored path of each first frame the runs use, keyed by (source, id). A frame that is
    gone is simply missing.
    """
    wanted: dict[str, set[int]] = {"lab": set(), "asset": set()}
    for row in rows:
        frame = row.run.first_frame
        if isinstance(frame, dict) and frame.get("source") in wanted:
            frame_id = frame.get("id")
            if isinstance(frame_id, int):
                wanted[str(frame["source"])].add(frame_id)

    urls: dict[tuple[str, int], str] = {}
    if wanted["lab"]:
        images = await session.execute(select(LabImage).where(LabImage.id.in_(wanted["lab"])))
        for image in images.scalars():
            urls[("lab", image.id)] = media_url(image.path)
    if wanted["asset"]:
        assets = await session.execute(
            select(Asset).where(Asset.id.in_(wanted["asset"]), Asset.kind == "frame")
        )
        for asset in assets.scalars():
            urls[("asset", asset.id)] = media_url(asset.path)
    return urls


def _run_out(row: video_lab.RunRow, frame_urls: dict[tuple[str, int], str]) -> LabVideoRunOut:
    run = row.run
    frame = run.first_frame
    first_frame: FirstFrameOut | None = None
    if isinstance(frame, dict) and frame.get("source") in ("lab", "asset"):
        frame_id = frame.get("id")
        if isinstance(frame_id, int):
            source: Literal["lab", "asset"] = "lab" if frame["source"] == "lab" else "asset"
            first_frame = FirstFrameOut(
                source=source, id=frame_id, url=frame_urls.get((source, frame_id))
            )
    audio = run.audio
    codec = audio.get("codec") if isinstance(audio, dict) else None
    return LabVideoRunOut(
        id=run.id,
        created_at=run.created_at,
        group_key=run.group_key,
        # The database CHECK constraint keeps this to the known models.
        video_model="ltx-2.5" if run.video_model == "ltx-2.5" else "ltx-2.3",
        endpoint=run.endpoint,
        prompt=run.prompt,
        params=run.params if isinstance(run.params, dict) else {},
        first_frame=first_frame,
        job=(
            job_summary(JobRow(job=row.job, project_name=store.NO_PROJECT_NAME, scene_index=None))
            if row.job is not None
            else None
        ),
        url=media_url(run.path) if run.path is not None else None,
        size_bytes=run.size_bytes,
        width=run.width,
        height=run.height,
        frame_count=run.frame_count,
        duration_s=run.duration_s,
        audio_codec=codec if isinstance(codec, str) else None,
    )


async def _runs_out(session: AsyncSession, rows: list[video_lab.RunRow]) -> list[LabVideoRunOut]:
    urls = await _frame_urls(session, rows)
    return [_run_out(row, urls) for row in rows]


@router.post(
    "/lab/videos/runs",
    response_model=LabVideoRunsOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_INVALID,
)
async def create_runs(body: LabVideoRunCreate, session: SessionDep) -> LabVideoRunsOut:
    """Starts one run per chosen model. Each is a paid GPU job of 5 to 10 minutes."""
    form = video_lab.LabVideoForm(
        prompt=body.prompt,
        models=body.models,
        mode=body.mode,
        orientation=body.orientation,
        duration_s=body.duration_s,
        seed=body.seed,
        negative_prompt=body.negative_prompt,
        first_frame=(
            video_lab.FirstFrameRef(source=body.first_frame.source, id=body.first_frame.id)
            if body.first_frame is not None
            else None
        ),
    )
    try:
        rows = await video_lab.create_runs(session, form)
    except video_lab.LabVideoInputError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return LabVideoRunsOut(runs=await _runs_out(session, rows))


@router.get("/lab/videos/runs", response_model=list[LabVideoRunOut])
async def list_runs(
    session: SessionDep,
    before_id: Annotated[int | None, Query(ge=1, le=_MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[LabVideoRunOut]:
    """The newest runs first. Pass the last id you have as `before_id` for the next page."""
    return await _runs_out(session, await video_lab.list_runs(session, before_id, limit))


@router.get("/lab/videos/runs/{run_id}", response_model=LabVideoRunOut, responses=_NOT_FOUND)
async def get_run(run_id: int, session: SessionDep) -> LabVideoRunOut:
    row = await video_lab.get_run(session, run_id) if 1 <= run_id <= _MAX_ID else None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} does not exist.")
    return (await _runs_out(session, [row]))[0]


@router.post(
    "/lab/videos/prompt-drafts",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_INVALID,
)
async def create_prompt_draft(body: PromptDraftCreate, session: SessionDep) -> JobDetail:
    """Starts the job that writes a multi-shot prompt from an idea (a paid call to the language
    model). Follow it with `GET /api/jobs/{id}`: when it has succeeded, `output.prompt` is the
    prompt and `output.warnings` is what to look at.
    """
    try:
        job = await video_lab.create_prompt_draft(
            session, body.idea, body.shots, body.duration_s, body.first_frame_note
        )
    except video_lab.LabVideoInputError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=store.NO_PROJECT_NAME, scene_index=None))
