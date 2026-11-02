"""`/api/lab/graphics`: the Graphics lab. One line of an explainer script, made into the same
graphic by four engines and compared (GFX-002).

`POST .../runs` makes a run from a line, an orientation and, optionally, a saved voice. No model
is called: the run has no brief yet, and its four engines say they are not built yet. With a
voice, the speech of the line starts at once and its words are timed when it is stored (GFX-004);
the brief cannot be written until that timing is stored. The engines are added by the later
phases of `Graphics_lab_implementation_phases.md`.

`GET .../runs` lists the runs, newest first. `GET .../runs/{id}` reads one with its brief job and,
for each engine, every render made for it (newest first).

`PATCH .../renders/{id}` records what a person decided after watching a render: a verdict and a
note.

The director call (GFX-003) is three clicks, each a paid call that starts only from the click:
`POST .../runs/{id}/brief` writes the brief of a run, `POST .../runs/{id}/make-all` writes it and
then starts every engine that is built, and `POST .../runs/{id}/ask-again` makes a new run with
the same line and writes its brief. A run's `brief` is what the director decided, and `resolved`
is what code worked out from it (§4.3 and §4.4 of `Graphics_lab_implementation_phases.md`).

The **test card** (GFX-005) proves the motion service and the render job: `POST .../test-cards`
renders a card of a chosen orientation and length, and `GET .../test-cards/newest` answers the
newest one and the video of the newest that succeeded. It belongs to no run and costs nothing;
only the newest video is kept.

A run is deleted through the shared lab-sample delete (`DELETE /api/lab/samples/graphic_run/{id}`,
`api/deletion.py`), which refuses while any of its jobs is still running and removes the videos.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

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
_CONFLICT = {409: {"model": ErrorResponse, "description": "The run's state does not allow it."}}

Orientation = Literal["landscape", "portrait"]
RunStateOut = Literal[
    "new", "making_voice", "voice_failed", "writing_brief", "brief_ready", "brief_failed"
]
VoiceStageOut = Literal["speaking", "timing", "ready", "failed"]
Verdict = Literal["good", "usable", "bad"]
BriefKind = Literal["kpi", "comparison", "trend", "process", "list", "statement", "concept"]
DerivedOp = Literal["pct_change", "difference", "ratio", "sum"]


class GraphicFactOut(BaseModel):
    """A number the line says."""

    id: str
    label: str
    # As the line says it: 12 for "12 billion dollars", with `scale` "billion".
    value: float
    unit: str
    scale: str
    said_as: str


class GraphicDerivedOut(BaseModel):
    """A value code works out from facts."""

    id: str
    label: str
    op: DerivedOp
    of: list[str]


class GraphicBeatOut(BaseModel):
    id: str
    phrase: str
    shows: str
    refs: list[str]


class GraphicBriefThemeOut(BaseModel):
    palette: str
    accent: str | None
    background: str
    motion: str
    mood: str


class GraphicBriefOut(BaseModel):
    """What the director decided (§4.3)."""

    kind: BriefKind
    intent: str
    visual_brief: str
    facts: list[GraphicFactOut]
    derived: list[GraphicDerivedOut]
    beats: list[GraphicBeatOut]
    theme: GraphicBriefThemeOut


class GraphicResolvedValueOut(BaseModel):
    label: str
    # The full value, with the scale applied.
    value: float
    unit: str
    # The text that appears on screen, written by code.
    display: str


class GraphicResolvedBeatOut(BaseModel):
    frame: int
    shows: str


class GraphicResolvedThemeOut(BaseModel):
    background: str
    surface: str
    text: str
    muted: str
    accent: str
    positive: str
    negative: str
    number: str
    background_style: str
    motion: str


class GraphicBoxOut(BaseModel):
    left: int
    top: int
    right: int
    bottom: int


class GraphicZoneOut(BaseModel):
    top: int
    bottom: int


class GraphicResolvedOut(BaseModel):
    """What code worked out from the brief, and what every engine is checked against (§4.4)."""

    width: int
    height: int
    fps: int
    frames: int
    # `estimated` or `parakeet`.
    timing_source: str
    facts: dict[str, GraphicResolvedValueOut]
    derived: dict[str, GraphicResolvedValueOut]
    beats: dict[str, GraphicResolvedBeatOut]
    theme: GraphicResolvedThemeOut
    fonts: dict[str, str]
    safe_area: GraphicBoxOut
    caption_zone: GraphicZoneOut
    # What code changed in the brief (for example a replaced accent colour).
    notes: list[str]


class GraphicRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 1 to 300 characters after trimming, and landscape or portrait. The service checks both and
    # answers with a message the page can show.
    line_text: StrictStr = Field(max_length=_REQUEST_LINE_MAX)
    orientation: StrictStr = Field(max_length=20)
    # A saved voice of the Voice lab that speaks the line. Left out: no voice, and the times of
    # the words are estimated.
    voice_id: StrictInt | None = Field(default=None, ge=1, le=_MAX_ID)


class GraphicTestCardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The service checks both and answers with a sentence the page can show.
    orientation: StrictStr = Field(max_length=20)
    frames: StrictInt = Field(ge=-_MAX_ID, le=_MAX_ID)


class GraphicTestCardResultOut(BaseModel):
    """A test card that was rendered and whose video is still stored."""

    job_id: int
    orientation: Orientation
    width: int
    height: int
    frames: int
    # The video, from /media.
    url: str
    size_bytes: int
    # What was measured (§4.7): the render time, the checks, the versions of Remotion and Chrome.
    metrics: Any
    # A sentence for each check that failed. Empty when every check passed.
    warnings: list[str]


class GraphicTestCardOut(BaseModel):
    # The newest test card job, whatever it is doing or how it ended. None before the first.
    job: JobSummary | None
    orientation: Orientation | None
    frames: int | None
    # The newest test card that succeeded and still has its video. None before the first.
    result: GraphicTestCardResultOut | None


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


class GraphicVoiceOut(BaseModel):
    """The voice of a run (GFX-004): the speech and where the timing of its words stands."""

    # The saved voice, by id and name (the name is None when the voice was deleted).
    voice_id: int | None
    voice_name: str | None
    speech_run_id: int
    # The speech alone, from /media. None until it is stored.
    speech_url: str | None
    speech_job: JobSummary | None
    timing_job: JobSummary | None
    state: VoiceStageOut
    # Why the voice failed. None otherwise.
    error: str | None
    # `parakeet`, or `estimated` when too few words matched. None until the timing is stored.
    timing_source: str | None
    match_percent: float | None
    threshold: int | None
    # A sentence about the timing, set when it was estimated.
    note: str | None


class GraphicRunOut(GraphicRunSummaryOut):
    # The size and frame rate of every video of the run.
    width: int
    height: int
    fps: int
    # The saved voice and the speech made with it (GFX-004). None for a run without a voice.
    voice_id: int | None
    speech_run_id: int | None
    voice: GraphicVoiceOut | None
    # The words of the line with their times (GFX-004).
    timing: Any | None
    # What the director decided (GFX-003), what code worked out from it, and the job that wrote it.
    brief: GraphicBriefOut | None
    resolved: GraphicResolvedOut | None
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


def voice_out(row: graphics_lab.RunRow) -> GraphicVoiceOut | None:
    """The run's voice, or None for a run without one."""
    status = row.voice_status
    run = row.run
    if status is None or run.speech_run_id is None:
        return None
    timing = run.timing if isinstance(run.timing, dict) else {}
    match_percent = timing.get("match_percent")
    threshold = timing.get("threshold")
    return GraphicVoiceOut(
        voice_id=run.voice_id,
        voice_name=row.voice.name if row.voice is not None else None,
        speech_run_id=run.speech_run_id,
        speech_url=media_url(row.speech.path) if row.speech and row.speech.path else None,
        speech_job=_job_out(row.speech_job),
        timing_job=_job_out(row.timing_job),
        state=status.stage,
        error=status.error,
        timing_source=timing.get("source"),
        match_percent=float(match_percent) if isinstance(match_percent, int | float) else None,
        threshold=int(threshold) if isinstance(threshold, int) else None,
        note=timing.get("note"),
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
        voice=voice_out(row),
        timing=run.timing,
        brief=run.brief,
        resolved=run.resolved,
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
    """Makes a run from a line (1 to 300 characters), an orientation and, optionally, a saved
    voice. No model is called. With a voice, its speech starts now (a GPU job).
    """
    try:
        row = await graphics_lab.create_run(
            session, body.line_text, body.orientation, body.voice_id
        )
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


async def _brief_click(session: SessionDep, run_id: int, action: Any) -> GraphicRunOut:
    """Runs one of the director clicks and answers the run: 404, 409 and 422 as the service says."""
    try:
        row = await action(session, run_id) if 1 <= run_id <= _MAX_ID else None
    except graphics_lab.GraphicsLabConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except graphics_lab.GraphicsLabInputError as exc:
        raise _unprocessable(str(exc)) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} does not exist.")
    return run_out(row)


@router.post(
    "/lab/graphics/runs/{run_id}/brief",
    response_model=GraphicRunOut,
    responses={**_NOT_FOUND, **_CONFLICT, **_INVALID},
)
async def write_brief(run_id: int, session: SessionDep) -> GraphicRunOut:
    """Starts the paid call that writes the run's brief. Refused (409) while it is being written
    or is written, and (422) for a line whose speech is longer than 15 s, before any call.
    """
    return await _brief_click(session, run_id, graphics_lab.start_brief)


@router.post(
    "/lab/graphics/runs/{run_id}/make-all",
    response_model=GraphicRunOut,
    responses={**_NOT_FOUND, **_CONFLICT, **_INVALID},
)
async def make_all(run_id: int, session: SessionDep) -> GraphicRunOut:
    """Writes the brief, then starts every engine that is built. With the brief already written,
    it only starts the built engines that have no render. An engine that is not built is skipped.
    """
    return await _brief_click(session, run_id, graphics_lab.make_all)


@router.post(
    "/lab/graphics/runs/{run_id}/ask-again",
    response_model=GraphicRunOut,
    status_code=status.HTTP_201_CREATED,
    responses={**_NOT_FOUND, **_CONFLICT, **_INVALID},
)
async def ask_again(run_id: int, session: SessionDep) -> GraphicRunOut:
    """Makes a new run with the same line and orientation, and starts its brief. The run this
    was asked on is not changed. The answer is the new run.
    """
    return await _brief_click(session, run_id, graphics_lab.ask_again)


def test_card_out(newest: Job | None, stored: Job | None) -> GraphicTestCardOut:
    """The newest test card job and the video of the newest one that succeeded."""
    recorded = newest.input if newest is not None and isinstance(newest.input, dict) else {}
    result: GraphicTestCardResultOut | None = None
    if stored is not None and isinstance(stored.output, dict):
        output = stored.output
        result = GraphicTestCardResultOut(
            job_id=stored.id,
            orientation=output["orientation"],
            width=output["width"],
            height=output["height"],
            frames=output["frames"],
            url=media_url(output["path"]),
            size_bytes=output["size_bytes"],
            metrics=output.get("metrics"),
            warnings=output.get("warnings") or [],
        )
    return GraphicTestCardOut(
        job=_job_out(newest),
        orientation=recorded.get("orientation"),
        frames=recorded.get("frames"),
        result=result,
    )


@router.post(
    "/lab/graphics/test-cards",
    response_model=GraphicTestCardOut,
    status_code=status.HTTP_201_CREATED,
    responses={**_CONFLICT, **_INVALID},
)
async def render_test_card(body: GraphicTestCardCreate, session: SessionDep) -> GraphicTestCardOut:
    """Renders the test card at an orientation and a length (72 to 360 frames) in the motion
    service. Refused (409) while another test card is being rendered. Nothing is paid for.
    """
    try:
        await graphics_lab.start_test_card(session, body.orientation, body.frames)
    except graphics_lab.GraphicsLabConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except graphics_lab.GraphicsLabInputError as exc:
        raise _unprocessable(str(exc)) from exc
    newest, stored = await graphics_lab.newest_test_card(session)
    return test_card_out(newest, stored)


@router.get("/lab/graphics/test-cards/newest", response_model=GraphicTestCardOut)
async def get_newest_test_card(session: SessionDep) -> GraphicTestCardOut:
    """The newest test card job and the video of the newest one that succeeded."""
    newest, stored = await graphics_lab.newest_test_card(session)
    return test_card_out(newest, stored)
