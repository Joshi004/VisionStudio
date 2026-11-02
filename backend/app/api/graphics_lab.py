"""`/api/lab/graphics`: the Graphics lab. One line of an explainer script, made into the same
graphic by four engines and compared (GFX-002).

`POST .../runs` makes a run from a line and an orientation. Nothing is started: the run has no
brief yet, and its four engines say they are not built yet. The brief, the voice and the engines
are added by the later phases of `Graphics_lab_implementation_phases.md`.

`GET .../runs` lists the runs, newest first. `GET .../runs/{id}` reads one with its brief job and,
for each engine, every render made for it (newest first).

`PATCH .../renders/{id}` records what a person decided after watching a render: a verdict and a
note.

A run is deleted through the shared lab-sample delete (`DELETE /api/lab/samples/graphic_run/{id}`,
`api/deletion.py`), which refuses while any of its jobs is still running and removes the videos.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.api.errors import ErrorResponse
from app.api.jobs import JobSummary, job_summary
from app.db.models import Job
from app.db.session import SessionDep
from app.jobs import store
from app.jobs.store import JobRow
from app.services import graphics_engines, graphics_lab
from app.services.graphics_engines import EngineKey
from app.services.storage import media_url

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1

# The widest line the request may carry. The form's own limit (`graphics_lab.LINE_MAX_CHARS`) is
# checked by the service, so the user gets its message; this only stops a huge body.
_REQUEST_LINE_MAX: Final = 2000

_INVALID = {422: {"model": ErrorResponse, "description": "The form breaks a rule."}}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No run or render has this id."}}

Orientation = Literal["landscape", "portrait"]
RunStateOut = Literal["new", "writing_brief", "brief_ready", "brief_failed"]
Verdict = Literal["good", "usable", "bad"]


class GraphicRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 1 to 300 characters after trimming, and landscape or portrait. The service checks both and
    # answers with a message the page can show.
    line_text: StrictStr = Field(max_length=_REQUEST_LINE_MAX)
    orientation: StrictStr = Field(max_length=20)


class GraphicRenderUpdate(BaseModel):
    """Only the fields that are sent are changed; `null` clears one."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict | None = None
    note: StrictStr | None = None


class GraphicRenderOut(BaseModel):
    id: int
    created_at: datetime
    run_id: int
    engine: EngineKey
    # The renders of one engine of a run are numbered from 1.
    attempt: int
    # What the engine draws from (the template spec, the block scene or the component code), and
    # the model call that wrote it. None until then.
    input: Any | None
    input_job: JobSummary | None
    # The render this one repeats with the same input and no model call, if it does.
    repeat_of: int | None
    render_job: JobSummary | None
    # The finished video, from /media. None until the render job has stored it.
    url: str | None
    metrics: Any | None
    warnings: Any | None
    verdict: Verdict | None
    note: str | None
    last_error: str | None


class GraphicEngineOut(BaseModel):
    key: EngineKey
    label: str
    # False until the engine's own phase has built it: its card then says "not built yet".
    built: bool
    # Every render made for this engine, newest first.
    renders: list[GraphicRenderOut]


class GraphicRunSummaryOut(BaseModel):
    id: int
    created_at: datetime
    line_text: str
    orientation: Orientation
    # Worked out on every read from the brief and the job that writes it.
    state: RunStateOut


class GraphicRunOut(GraphicRunSummaryOut):
    # The size and frame rate of every video of the run.
    width: int
    height: int
    fps: int
    # The saved voice and the speech made with it (GFX-004). None for a run without a voice.
    voice_id: int | None
    speech_run_id: int | None
    # The words of the line with their times (GFX-004).
    timing: Any | None
    # What the director decided (GFX-003), and the job that wrote it.
    brief: Any | None
    brief_job: JobSummary | None
    last_error: str | None
    # The four engines in the order of the design, each with its renders.
    engines: list[GraphicEngineOut]


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _job_out(job: Job | None) -> JobSummary | None:
    if job is None:
        return None
    return job_summary(JobRow(job=job, project_name=store.owner_name(job, None)))


def render_out(row: graphics_lab.RenderRow) -> GraphicRenderOut:
    render = row.render
    return GraphicRenderOut(
        id=render.id,
        created_at=render.created_at,
        run_id=render.run_id,
        engine=render.engine,  # type: ignore[arg-type]  # the database CHECK holds the four keys
        attempt=render.attempt,
        input=render.input,
        input_job=_job_out(row.input_job),
        repeat_of=render.repeat_of,
        render_job=_job_out(row.render_job),
        url=media_url(render.media_path) if render.media_path is not None else None,
        metrics=render.metrics,
        warnings=render.warnings,
        verdict=render.verdict,  # type: ignore[arg-type]  # the database CHECK holds the three
        note=render.note,
        last_error=render.last_error,
    )


def run_summary_out(row: graphics_lab.RunRow) -> GraphicRunSummaryOut:
    run = row.run
    return GraphicRunSummaryOut(
        id=run.id,
        created_at=run.created_at,
        line_text=run.line_text,
        orientation=run.orientation,  # type: ignore[arg-type]  # the database CHECK holds two
        state=row.state,
    )


def run_out(row: graphics_lab.RunRow) -> GraphicRunOut:
    run = row.run
    width, height = graphics_lab.size_of(run)
    by_engine: dict[str, list[GraphicRenderOut]] = {key: [] for key in graphics_engines.ENGINES}
    for render_row in row.renders:
        by_engine[render_row.render.engine].append(render_out(render_row))
    return GraphicRunOut(
        **run_summary_out(row).model_dump(),
        width=width,
        height=height,
        fps=graphics_lab.FPS,
        voice_id=run.voice_id,
        speech_run_id=run.speech_run_id,
        timing=run.timing,
        brief=run.brief,
        brief_job=_job_out(row.brief_job),
        last_error=run.last_error,
        engines=[
            GraphicEngineOut(
                key=engine.key,
                label=engine.label,
                built=engine.built,
                renders=by_engine[engine.key],
            )
            for engine in graphics_engines.ENGINES.values()
        ],
    )


@router.post(
    "/lab/graphics/runs",
    response_model=GraphicRunOut,
    status_code=status.HTTP_201_CREATED,
    responses=_INVALID,
)
async def create_run(body: GraphicRunCreate, session: SessionDep) -> GraphicRunOut:
    """Makes a run from a line (1 to 300 characters) and an orientation. Nothing is started."""
    try:
        row = await graphics_lab.create_run(session, body.line_text, body.orientation)
    except graphics_lab.GraphicsLabInputError as exc:
        raise _unprocessable(str(exc)) from exc
    return run_out(row)


@router.get("/lab/graphics/runs", response_model=list[GraphicRunSummaryOut])
async def list_runs(
    session: SessionDep,
    before_id: Annotated[int | None, Query(ge=1, le=_MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[GraphicRunSummaryOut]:
    """The newest runs first. Pass the last id you have as `before_id` for the next page."""
    rows = await graphics_lab.list_runs(session, before_id, limit)
    return [run_summary_out(row) for row in rows]


@router.get(
    "/lab/graphics/runs/{run_id}",
    response_model=GraphicRunOut,
    responses=_NOT_FOUND,
)
async def get_run(run_id: int, session: SessionDep) -> GraphicRunOut:
    """One run with its brief and, for each of the four engines, its renders."""
    row = await graphics_lab.get_run(session, run_id) if 1 <= run_id <= _MAX_ID else None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} does not exist.")
    return run_out(row)


@router.patch(
    "/lab/graphics/renders/{render_id}",
    response_model=GraphicRenderOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def update_render(
    render_id: int, body: GraphicRenderUpdate, session: SessionDep
) -> GraphicRenderOut:
    """Records the verdict and/or the note of a render. Only the fields in the body are changed."""
    changes = {key: getattr(body, key) for key in body.model_fields_set}
    try:
        row = (
            await graphics_lab.update_render(session, render_id, changes)
            if 1 <= render_id <= _MAX_ID
            else None
        )
    except graphics_lab.GraphicsLabInputError as exc:
        raise _unprocessable(str(exc)) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Render {render_id} does not exist.")
    return render_out(row)
