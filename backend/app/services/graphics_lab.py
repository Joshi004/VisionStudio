"""The Graphics lab: one line of an explainer script, made into the same graphic by four engines,
and the four videos compared (GFX-002).

The lab belongs to no project and changes none. A **run** (`lab_graphic_run`) is one line, one
orientation and, from GFX-004, an optional saved voice. Its brief and its timing belong to it, so
asking the director again makes a new run and a brief never changes under the renders made from
it. A **render** (`lab_graphic_render`) is one engine's attempt for a run: the input that engine
draws from, the jobs that wrote and rendered it, the video, the metrics and the owner's verdict.

What a run is doing is worked out on every read from its jobs and its stored fields
(`run_state`), as the Audio video lab does (`services/av_lab.py`). Only `last_error` is stored.

This module holds the form checks, the rows, the engine registry
(`services/graphics_engines.py`), the verdict, and (GFX-003) the clicks that start the paid
director call: **Write the brief** (`start_brief`), **Make all** (`make_all`) and **Ask again**
(`ask_again`). The brief itself is written by the job `write_lab_graphic_brief`. The voice
(GFX-004) and the engines (GFX-005 to GFX-010) fill in the rest, and read the names this module
gives (`voice_audio_of`, `size_of`, `FONTS`, the font constants).
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, LabGraphicRender, LabGraphicRun
from app.jobs import store
from app.services import graphics_engines, graphics_resolve, projects

_logger = logging.getLogger(__name__)

BRIEF_JOB_TYPE: Final = "write_lab_graphic_brief"

LINE_MAX_CHARS: Final = 300
NOTE_MAX_CHARS: Final = 1000
VERDICTS: Final = ("good", "usable", "bad")
ORIENTATIONS: Final = (projects.LANDSCAPE, projects.PORTRAIT)

# Every video of the lab is 24 frames a second (G-4, G-10), as H3 and the render are.
FPS: Final = 24

# The two fonts of every engine (G-11), loaded from the files in `assets/fonts/` and never from
# the internet. The titles and the numbers use the display font, all other text the text font.
DISPLAY_FONT_NAME: Final = "Montserrat ExtraBold"
DISPLAY_FONT_FILE: Final = "Montserrat-ExtraBold.ttf"
TEXT_FONT_NAME: Final = "Inter Medium"
TEXT_FONT_FILE: Final = "Inter-Medium.ttf"
# The fonts as the resolved brief names them (§4.4).
FONTS: Final = {"display": DISPLAY_FONT_NAME, "text": TEXT_FONT_NAME}

RunState = Literal["new", "writing_brief", "brief_ready", "brief_failed"]


class GraphicsLabInputError(ValueError):
    """Something the form gets wrong. The message is meant for the user (HTTP 422)."""


class GraphicsLabConflictError(Exception):
    """A click that the run's state does not allow. The message is meant for the user (HTTP 409)."""


@dataclass(frozen=True)
class RenderRow:
    """A render with the jobs behind it (either may be None)."""

    render: LabGraphicRender
    input_job: Job | None
    render_job: Job | None


@dataclass(frozen=True)
class RunRow:
    """A run with its brief job and its renders, newest first. `renders` is empty in a list."""

    run: LabGraphicRun
    brief_job: Job | None
    renders: list[RenderRow]

    @property
    def state(self) -> RunState:
        return run_state(self.run, self.brief_job)


# --- The form -------------------------------------------------------------------------------


def clean_line(value: object) -> str:
    """The line trimmed and checked. Raises GraphicsLabInputError."""
    if not isinstance(value, str):
        raise GraphicsLabInputError("The line must be text.")
    text = value.strip()
    if not text:
        raise GraphicsLabInputError("Type the line to make a graphic for.")
    if len(text) > LINE_MAX_CHARS:
        raise GraphicsLabInputError(f"The line must be at most {LINE_MAX_CHARS} characters.")
    return text


def check_orientation(value: object) -> str:
    """The orientation, when it is one the lab makes. Raises GraphicsLabInputError."""
    if not isinstance(value, str) or value not in ORIENTATIONS:
        raise GraphicsLabInputError("Choose landscape or portrait.")
    return value


def size_of(run: LabGraphicRun) -> tuple[int, int]:
    """The width and height of every video of the run, in pixels."""
    sizes = projects.ORIENTATION_DEFAULTS[run.orientation]
    return sizes.out_width, sizes.out_height


# --- State ----------------------------------------------------------------------------------


def run_state(run: LabGraphicRun, brief_job: Job | None) -> RunState:
    """What the run is doing, worked out from its brief and the job that writes it.

    `new`: no brief was asked for. `writing_brief`: the director job is waiting or running.
    `brief_ready`: the brief is stored. `brief_failed`: the job ended without one.
    """
    if run.brief is not None:
        return "brief_ready"
    if brief_job is None:
        return "new"
    if brief_job.status in store.ACTIVE_STATUSES:
        return "writing_brief"
    return "brief_failed"


async def voice_audio_of(session: AsyncSession, run: LabGraphicRun) -> str | None:
    """The stored path of the speech that goes into the run's videos, or None when the run has
    no voice. GFX-004 fills this in: until then no run has a voice, so it is always None. The
    render job (GFX-005) reads it to add the voice to every engine's video.
    """
    return None


# --- Runs -----------------------------------------------------------------------------------


async def create_run(session: AsyncSession, line_text: object, orientation: object) -> RunRow:
    """Checks the form and adds one run. Commits. Raises GraphicsLabInputError. Nothing is
    started: the director call is its own click (GFX-003).
    """
    run = LabGraphicRun(line_text=clean_line(line_text), orientation=check_orientation(orientation))
    session.add(run)
    await session.commit()
    _logger.info("lab graphic run %d created: %s", run.id, run.orientation)
    return RunRow(run=run, brief_job=None, renders=[])


def _select() -> Any:
    return select(LabGraphicRun, Job).outerjoin(Job, Job.id == LabGraphicRun.brief_job_id)


async def list_runs(session: AsyncSession, before_id: int | None, limit: int) -> list[RunRow]:
    """The newest runs first, `limit` of them, those with an id below `before_id` if given."""
    statement = _select().order_by(LabGraphicRun.id.desc()).limit(limit)
    if before_id is not None:
        statement = statement.where(LabGraphicRun.id < before_id)
    result = await session.execute(statement.execution_options(populate_existing=True))
    return [RunRow(run=run, brief_job=job, renders=[]) for run, job in result.all()]


async def get_run(session: AsyncSession, run_id: int) -> RunRow | None:
    """The run with its brief job and its renders, newest first. None when it does not exist."""
    statement = (
        _select().where(LabGraphicRun.id == run_id).execution_options(populate_existing=True)
    )
    found = (await session.execute(statement)).first()
    if found is None:
        return None
    run, brief_job = found
    renders = await session.execute(
        select(LabGraphicRender)
        .where(LabGraphicRender.run_id == run_id)
        .order_by(LabGraphicRender.id.desc())
        .execution_options(populate_existing=True)
    )
    return RunRow(
        run=run, brief_job=brief_job, renders=await _render_rows(session, renders.scalars())
    )


async def _render_rows(session: AsyncSession, renders: Any) -> list[RenderRow]:
    """The renders with their input job and render job, loaded together."""
    rows = list(renders)
    job_ids = {
        job_id
        for render in rows
        for job_id in (render.input_job_id, render.render_job_id)
        if job_id is not None
    }
    jobs = await _jobs(session, job_ids)
    return [
        RenderRow(
            render=render,
            input_job=jobs.get(render.input_job_id) if render.input_job_id is not None else None,
            render_job=jobs.get(render.render_job_id) if render.render_job_id is not None else None,
        )
        for render in rows
    ]


async def _jobs(session: AsyncSession, job_ids: Collection[int]) -> dict[int, Job]:
    if not job_ids:
        return {}
    statement = select(Job).where(Job.id.in_(job_ids)).execution_options(populate_existing=True)
    return {job.id: job for job in (await session.execute(statement)).scalars()}


# --- Judging a render -----------------------------------------------------------------------


async def update_render(
    session: AsyncSession, render_id: int, changes: dict[str, Any]
) -> RenderRow | None:
    """Sets the verdict and/or the note of a render (only the keys in `changes`). None when the
    render does not exist. Commits. Raises GraphicsLabInputError.
    """
    render = await session.get(LabGraphicRender, render_id)
    if render is None:
        return None
    if "verdict" in changes:
        verdict = changes["verdict"]
        if verdict is not None and verdict not in VERDICTS:
            raise GraphicsLabInputError("The verdict is good, usable or bad.")
        render.verdict = verdict
    if "note" in changes:
        note = changes["note"]
        if note is not None and not isinstance(note, str):
            raise GraphicsLabInputError("The note must be text.")
        text = (note or "").strip()
        if len(text) > NOTE_MAX_CHARS:
            raise GraphicsLabInputError(f"The note must be at most {NOTE_MAX_CHARS:,} characters.")
        render.note = text or None
    await session.commit()
    return (await _render_rows(session, [render]))[0]


# --- The director call (GFX-003) --------------------------------------------------------------


async def _estimated_timing(session: AsyncSession, line_text: str) -> dict[str, Any]:
    """The estimated timing of a line at the pace in Settings. Raises GraphicsLabInputError when
    the line's speech is longer than one graphic can be, before any paid call.
    """
    pace = await settings_service.get_int(session, settings_service.GRAPHICS_WPM_KEY)
    timing = graphics_resolve.estimated_timing(line_text, pace)
    _ensure_fits(timing)
    return timing


def _ensure_fits(timing: dict[str, Any]) -> None:
    try:
        graphics_resolve.ensure_fits(timing)
    except ValueError as exc:
        raise GraphicsLabInputError(str(exc)) from exc


async def start_brief(
    session: AsyncSession, run_id: int, *, then_start_engines: bool = False
) -> RunRow | None:
    """Starts the paid job that writes the run's brief. None when the run does not exist. Commits.

    Raises GraphicsLabConflictError when the brief is being written or is written already (**Ask
    again** makes a new run), and GraphicsLabInputError when the line is too long: nothing is
    paid for then. A run keeps the timing it was first given; a run without one gets the
    estimated timing now. Two clicks make one job.
    """
    row = await get_run(session, run_id)
    if row is None:
        return None
    run = row.run
    if row.state == "brief_ready":
        raise GraphicsLabConflictError(
            "The brief is already written. Use Ask again to make a new run with the same line."
        )
    if row.state == "writing_brief":
        raise GraphicsLabConflictError("The brief is already being written.")
    if run.timing is None:
        run.timing = await _estimated_timing(session, run.line_text)
    else:
        _ensure_fits(run.timing)
    job, created = await store.create_job(
        session,
        project_id=None,
        type=BRIEF_JOB_TYPE,
        provider="llm",
        input={
            "requested": "lab_graphic_brief",
            "run_id": run.id,
            "line_text": run.line_text,
            "orientation": run.orientation,
            "timing": run.timing,
            "then_start_engines": then_start_engines,
        },
        commit=False,
        dedupe_key="run_id",
    )
    if not created:
        await session.rollback()
        raise GraphicsLabConflictError("The brief is already being written.")
    run.brief_job_id = job.id
    run.last_error = None
    await session.commit()
    _logger.info("lab graphic run %d: brief job %d started", run.id, job.id)
    return await get_run(session, run.id)


async def start_engines(session: AsyncSession, run_id: int) -> RunRow | None:
    """Starts every engine that is built and has no render yet, for a run whose brief is ready.
    Engines that are not built are skipped. None when the run does not exist. Commits.

    Best effort: each engine is started and committed on its own, so one that fails never undoes
    another. A failure is kept as a render of that engine with its message in `last_error`, which
    the engine's card shows. Raises GraphicsLabConflictError when the brief is not ready.
    """
    row = await get_run(session, run_id)
    if row is None:
        return None
    if row.run.brief is None:
        raise GraphicsLabConflictError("The brief is not written yet.")
    started = {render_row.render.engine for render_row in row.renders}
    for engine in graphics_engines.ENGINES.values():
        if engine.start is None or engine.key in started:
            continue
        try:
            # Read again: a failed start rolls back, which expires the objects of the session.
            run = await session.get(LabGraphicRun, run_id)
            if run is None:
                return None
            await engine.start(session, run)
            await session.commit()
        except Exception as exc:
            _logger.exception("lab graphic run %d: %s could not be started", run_id, engine.key)
            await session.rollback()
            await _record_start_failure(session, run_id, engine.key, str(exc))
    return await get_run(session, run_id)


async def _record_start_failure(
    session: AsyncSession, run_id: int, engine_key: str, message: str
) -> None:
    newest = await session.scalar(
        select(func.max(LabGraphicRender.attempt)).where(
            LabGraphicRender.run_id == run_id, LabGraphicRender.engine == engine_key
        )
    )
    session.add(
        LabGraphicRender(
            run_id=run_id,
            engine=engine_key,
            attempt=(newest or 0) + 1,
            last_error=f"The engine could not be started: {message}"[: store.ERROR_MAX_CHARS],
        )
    )
    await session.commit()


async def make_all(session: AsyncSession, run_id: int) -> RunRow | None:
    """**Make all**: writes the brief and then starts every built engine. When the brief is
    already written, only the built engines that have no render are started. None when the run
    does not exist. Raises GraphicsLabConflictError and GraphicsLabInputError as `start_brief`.
    """
    row = await get_run(session, run_id)
    if row is None:
        return None
    if row.state == "brief_ready":
        return await start_engines(session, run_id)
    return await start_brief(session, run_id, then_start_engines=True)


async def ask_again(session: AsyncSession, run_id: int) -> RunRow | None:
    """**Ask again**: a new run with the same line and orientation, and its brief started. The
    old run is not changed. None when the run does not exist. Commits. Raises
    GraphicsLabInputError when the line is too long.
    """
    source = await session.get(LabGraphicRun, run_id)
    if source is None:
        return None
    # Checked before the new run is made, so a refused click leaves nothing behind.
    await _estimated_timing(session, source.line_text)
    created = await create_run(session, source.line_text, source.orientation)
    return await start_brief(session, created.run.id)
