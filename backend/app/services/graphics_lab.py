"""The Graphics lab: one line of an explainer script, made into the same graphic by four engines,
and the four videos compared (GFX-002).

The lab belongs to no project and changes none. A **run** (`lab_graphic_run`) is one line, one
orientation and, since GFX-004, an optional saved voice. Its brief and its timing belong to it, so
asking the director again makes a new run and a brief never changes under the renders made from
it. A **render** (`lab_graphic_render`) is one engine's attempt for a run: the input that engine
draws from, the jobs that wrote and rendered it, the video, the metrics and the owner's verdict.

What a run is doing is worked out on every read from its jobs and its stored fields
(`run_state`), as the Audio video lab does (`services/av_lab.py`). Only `last_error` is stored.

This module holds the form checks, the rows, the engine registry
(`services/graphics_engines.py`), the verdict, and (GFX-003) the clicks that start the paid
director call: **Write the brief** (`start_brief`), **Make all** (`make_all`) and **Ask again**
(`ask_again`). The brief itself is written by the job `write_lab_graphic_brief`.

**The voice (GFX-004).** A run made with a saved voice makes its speech at once, as a Voice lab
run in `direction` mode (`create_run`). When the speech is stored, `on_voice_finished` queues the
job `time_lab_graphic_words`, which times the words with Parakeet and stores the timing on the
run (`store_timing`). The brief waits for that timing (`start_brief` refuses until it is stored),
so the beat frames and the length of the graphic follow the real voice. A run's voice is never
changed: a different voice is a new run.

The engines (GFX-005 to GFX-010) fill in the rest, and read the names this module gives
(`voice_audio_of`, `size_of`, `FONTS`, the font constants).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Collection
from dataclasses import dataclass, replace
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, LabGraphicRender, LabGraphicRun, LabVoiceRun, Voice
from app.db.session import SessionLocal
from app.jobs import store
from app.services import (
    explainer,
    graphics_engines,
    graphics_render,
    graphics_resolve,
    library_deletion,
    projects,
    voice_lab,
)
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

BRIEF_JOB_TYPE: Final = "write_lab_graphic_brief"
RENDER_JOB_TYPE: Final = "render_lab_graphic"
TIMING_JOB_TYPE: Final = "time_lab_graphic_words"
# Two presses on one run make one timing job.
TIMING_DEDUPE_KEY: Final = "run_id"
# How the saved voice reads the line: the same delivery as the explainer pipeline.
SPEECH_DELIVERY: Final = explainer.DEFAULT_PRESENTER_DELIVERY

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

RunState = Literal[
    "new", "making_voice", "voice_failed", "writing_brief", "brief_ready", "brief_failed"
]
# `speaking`: the speech is being made. `timing`: Parakeet is timing its words. `ready`: the
# timing is stored. `failed`: a step of the voice ended without a result.
VoiceStage = Literal["speaking", "timing", "ready", "failed"]


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
class VoiceStatus:
    """Where the voice of a run stands, and why it failed when it did."""

    stage: VoiceStage
    error: str | None = None


@dataclass(frozen=True)
class RunRow:
    """A run with its brief job and its renders, newest first. `renders` is empty in a list.

    A run with a voice also has its speech, the saved voice and the jobs of the speech and of the
    timing (each None when it does not exist).
    """

    run: LabGraphicRun
    brief_job: Job | None
    renders: list[RenderRow]
    speech: LabVoiceRun | None = None
    voice: Voice | None = None
    speech_job: Job | None = None
    timing_job: Job | None = None

    @property
    def voice_status(self) -> VoiceStatus | None:
        """None for a run without a voice."""
        return voice_status(self.run, self.speech, self.speech_job, self.timing_job)

    @property
    def state(self) -> RunState:
        return run_state(self.run, self.brief_job, self.voice_status)


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


_ENDED_BADLY = ("failed", "cancelled")


def _job_error(job: Job | None, fallback: str) -> str:
    """Why a job ended without a result: its own message, or `fallback`."""
    if job is not None and job.status in _ENDED_BADLY and job.error:
        return job.error
    return fallback


def voice_status(
    run: LabGraphicRun,
    speech: LabVoiceRun | None,
    speech_job: Job | None,
    timing_job: Job | None,
) -> VoiceStatus | None:
    """Where the run's voice stands, or None when the run has none. The run's timing is the
    result: once it is stored the voice is `ready`, whatever happened to the jobs after that.
    """
    if run.speech_run_id is None:
        return None
    if run.timing is not None:
        return VoiceStatus("ready")
    if speech is None:
        return VoiceStatus("failed", "The speech of this run is gone.")
    if speech.path is None:
        if speech_job is not None and speech_job.status in store.ACTIVE_STATUSES:
            return VoiceStatus("speaking")
        return VoiceStatus("failed", _job_error(speech_job, "The speech was not made."))
    if timing_job is not None and timing_job.status in store.ACTIVE_STATUSES:
        return VoiceStatus("timing")
    return VoiceStatus("failed", _job_error(timing_job, "The words of the speech were not timed."))


def run_state(
    run: LabGraphicRun, brief_job: Job | None, voice: VoiceStatus | None = None
) -> RunState:
    """What the run is doing, worked out from its brief, the job that writes it and its voice.

    `new`: no brief was asked for. `making_voice`: the speech is being made or its words timed.
    `voice_failed`: that ended without a timing. `writing_brief`: the director job is waiting or
    running. `brief_ready`: the brief is stored. `brief_failed`: the job ended without one.
    """
    if run.brief is not None:
        return "brief_ready"
    if brief_job is not None:
        if brief_job.status in store.ACTIVE_STATUSES:
            return "writing_brief"
        return "brief_failed"
    if voice is not None and voice.stage != "ready":
        return "voice_failed" if voice.stage == "failed" else "making_voice"
    return "new"


async def voice_audio_of(session: AsyncSession, run: LabGraphicRun) -> str | None:
    """The stored path of the speech that goes into the run's videos, or None when the run has
    no voice (or its speech has no file). The render job (GFX-005) reads it to add the voice to
    every engine's video. The file can be longer than the graphic: the render cuts it to the
    graphic's length.
    """
    if run.speech_run_id is None:
        return None
    speech = await session.get(LabVoiceRun, run.speech_run_id)
    return speech.path if speech is not None else None


# --- Runs -----------------------------------------------------------------------------------


def check_voice_id(value: object) -> int | None:
    """The saved voice's id, or None for a run without a voice. Raises GraphicsLabInputError."""
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise GraphicsLabInputError("The voice must be a saved voice.")
    return value


async def create_run(
    session: AsyncSession,
    line_text: object,
    orientation: object,
    voice_id: object = None,
) -> RunRow:
    """Checks the form and adds one run. Commits. Raises GraphicsLabInputError. No model is
    called: the director call is its own click (GFX-003).

    With a saved voice the speech of the line is started now, as a Voice lab run in `direction`
    mode with the explainer's presenter delivery, and its words are timed when it is stored
    (`on_voice_finished`). A line whose estimated speech is longer than one graphic can be is
    refused before any speech is made.
    """
    text = clean_line(line_text)
    checked_orientation = check_orientation(orientation)
    saved_voice_id = check_voice_id(voice_id)
    speech_run_id: int | None = None
    if saved_voice_id is not None:
        await _estimated_timing(session, text)
        form = voice_lab.VoiceLabForm(
            mode="direction",
            text=text,
            instruction=SPEECH_DELIVERY,
            voice_id=saved_voice_id,
            seed=None,
            cfg_scale=None,
        )
        try:
            speech = await voice_lab.create_run(session, form, commit=False)
        except voice_lab.VoiceLabInputError as exc:
            await session.rollback()
            raise GraphicsLabInputError(str(exc)) from exc
        speech_run_id = speech.run.id
    run = LabGraphicRun(
        line_text=text,
        orientation=checked_orientation,
        voice_id=saved_voice_id,
        speech_run_id=speech_run_id,
    )
    session.add(run)
    await session.commit()
    _logger.info(
        "lab graphic run %d created: %s, voice=%s", run.id, run.orientation, saved_voice_id
    )
    created = await get_run(session, run.id)
    assert created is not None
    return created


def _select() -> Any:
    return select(LabGraphicRun, Job).outerjoin(Job, Job.id == LabGraphicRun.brief_job_id)


async def _with_voices(session: AsyncSession, rows: list[RunRow]) -> list[RunRow]:
    """The rows with the speech, saved voice and jobs of each run that has a voice, loaded
    together.
    """
    speech_ids = {row.run.speech_run_id for row in rows if row.run.speech_run_id is not None}
    if not speech_ids:
        return rows
    voice_ids = {row.run.voice_id for row in rows if row.run.voice_id is not None}
    speeches = {
        speech.id: speech
        for speech in (
            await session.execute(
                select(LabVoiceRun)
                .where(LabVoiceRun.id.in_(speech_ids))
                .execution_options(populate_existing=True)
            )
        ).scalars()
    }
    voices: dict[int, Voice] = {}
    if voice_ids:
        found = await session.execute(
            select(Voice).where(Voice.id.in_(voice_ids)).execution_options(populate_existing=True)
        )
        voices = {voice.id: voice for voice in found.scalars()}
    job_ids = {row.run.timing_job_id for row in rows if row.run.timing_job_id is not None}
    job_ids |= {speech.job_id for speech in speeches.values() if speech.job_id is not None}
    jobs = await _jobs(session, job_ids)
    attached: list[RunRow] = []
    for row in rows:
        speech = speeches.get(row.run.speech_run_id) if row.run.speech_run_id is not None else None
        attached.append(
            replace(
                row,
                speech=speech,
                voice=voices.get(row.run.voice_id) if row.run.voice_id is not None else None,
                speech_job=jobs.get(speech.job_id)
                if speech is not None and speech.job_id is not None
                else None,
                timing_job=jobs.get(row.run.timing_job_id)
                if row.run.timing_job_id is not None
                else None,
            )
        )
    return attached


async def list_runs(session: AsyncSession, before_id: int | None, limit: int) -> list[RunRow]:
    """The newest runs first, `limit` of them, those with an id below `before_id` if given."""
    statement = _select().order_by(LabGraphicRun.id.desc()).limit(limit)
    if before_id is not None:
        statement = statement.where(LabGraphicRun.id < before_id)
    result = await session.execute(statement.execution_options(populate_existing=True))
    rows = [RunRow(run=run, brief_job=job, renders=[]) for run, job in result.all()]
    return await _with_voices(session, rows)


async def get_run(session: AsyncSession, run_id: int) -> RunRow | None:
    """The run with its brief job, its voice and its renders, newest first. None when it does
    not exist.
    """
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
    row = RunRow(
        run=run, brief_job=brief_job, renders=await _render_rows(session, renders.scalars())
    )
    return (await _with_voices(session, [row]))[0]


# --- The voice (GFX-004) ----------------------------------------------------------------------


async def on_voice_finished(speech_run_id: int) -> bool:
    """Called (best effort) once a Voice lab speech has been stored. Queues the timing of the
    words of every run made with this speech that has no timing and no timing job yet. Returns
    True when a job was queued.
    """
    # A session of its own: this is called from the speech job, after it was saved.
    async with SessionLocal() as session:
        statement = select(LabGraphicRun).where(
            LabGraphicRun.speech_run_id == speech_run_id,
            LabGraphicRun.timing.is_(None),
            LabGraphicRun.timing_job_id.is_(None),
        )
        runs = list((await session.execute(statement)).scalars())
        queued = False
        for run in runs:
            job, created = await store.create_job(
                session,
                project_id=None,
                type=TIMING_JOB_TYPE,
                provider="gpu",
                input={"requested": TIMING_JOB_TYPE, TIMING_DEDUPE_KEY: run.id},
                commit=False,
                dedupe_key=TIMING_DEDUPE_KEY,
            )
            run.timing_job_id = job.id
            queued = queued or created
        await session.commit()
    return queued


async def speech_for_timing(
    session: AsyncSession, run_id: int
) -> tuple[str, str, float | None] | None:
    """What the timing job needs: the stored path of the run's speech, the run's line and the
    speech's measured length. None when the run or its speech (or its file) is gone.
    """
    statement = select(LabGraphicRun).where(LabGraphicRun.id == run_id)
    run = (await session.execute(statement.execution_options(populate_existing=True))).scalar()
    if run is None or run.speech_run_id is None:
        return None
    speech = await session.get(LabVoiceRun, run.speech_run_id)
    if speech is None or speech.path is None:
        return None
    return speech.path, run.line_text, speech.duration_s


def voice_timing(alignment: Any, threshold: int, duration_s: float) -> dict[str, Any]:
    """The timing of a run with a voice, from `word_timings.Alignment`. It has the shape the
    brief and `graphics_resolve.resolve` read: one entry for each word of the line, and
    `duration_s` the length of the speech. Below the threshold the times are estimated over the
    real speech, and `note` says so.
    """
    timing: dict[str, Any] = {
        "source": alignment.source,
        "duration_s": round(duration_s, 3),
        "match_percent": alignment.match_percent,
        "threshold": threshold,
        "heard_text": alignment.heard_text,
        "words": alignment.words,
    }
    if alignment.source == graphics_resolve.SOURCE_ESTIMATED:
        timing["note"] = (
            f"Parakeet's words matched {alignment.match_percent:g}% of the line, and "
            f"{threshold}% is needed, so the word times are estimated over the speech."
        )
    return timing


async def store_timing(session: AsyncSession, run_id: int, timing: dict[str, Any]) -> bool:
    """Saves the timing on the run. No commit. False when the run is gone or already has a
    timing (a brief may have been written from it, so it stands).
    """
    statement = select(LabGraphicRun).where(LabGraphicRun.id == run_id)
    run = (await session.execute(statement.execution_options(populate_existing=True))).scalar()
    if run is None or run.timing is not None:
        return False
    run.timing = timing
    run.last_error = None
    return True


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


def _require_voice_timed(row: RunRow) -> None:
    """Raises GraphicsLabConflictError unless the run has no voice or its voice is timed: the
    brief is resolved from the real times, so it waits for them.
    """
    status = row.voice_status
    if status is None or status.stage == "ready":
        return
    if status.stage == "failed":
        reason = (status.error or "").rstrip(". ")
        raise GraphicsLabConflictError(f"The voice failed: {reason}. Make a new run to try again.")
    raise GraphicsLabConflictError(
        "The voice is still being made and timed. Write the brief when it is ready."
    )


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
    _require_voice_timed(row)
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
    GraphicsLabInputError when the line is too long, and GraphicsLabConflictError when the run's
    voice is not timed.

    A run with a voice keeps it: the new run shares the same speech and copies its timing, so
    nothing is spoken or timed again and the brief can start at once.
    """
    row = await get_run(session, run_id)
    if row is None:
        return None
    source = row.run
    # Checked before the new run is made, so a refused click leaves nothing behind.
    if source.speech_run_id is None:
        await _estimated_timing(session, source.line_text)
        created = await create_run(session, source.line_text, source.orientation)
        return await start_brief(session, created.run.id)
    _require_voice_timed(row)
    assert source.timing is not None
    _ensure_fits(source.timing)
    copy = LabGraphicRun(
        line_text=source.line_text,
        orientation=source.orientation,
        voice_id=source.voice_id,
        speech_run_id=source.speech_run_id,
        timing=source.timing,
    )
    session.add(copy)
    await session.commit()
    _logger.info("lab graphic run %d created as a copy of run %d, with its voice", copy.id, run_id)
    return await start_brief(session, copy.id)


# --- Rendering (GFX-005) ----------------------------------------------------------------------


async def queue_render(session: AsyncSession, render: LabGraphicRender) -> Job:
    """Queues the job that makes the render's video from the input the render holds, and links it
    as the render's `render_job_id`. No commit: the caller commits it together with the render
    row, as an engine's `start` does. Two presses on one render make one job (the existing job is
    returned).
    """
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=RENDER_JOB_TYPE,
        provider="local",
        input={
            "requested": graphics_render.REQUESTED_RENDER,
            graphics_render.RENDER_DEDUPE_KEY: render.id,
        },
        commit=False,
        dedupe_key=graphics_render.RENDER_DEDUPE_KEY,
    )
    render.render_job_id = job.id
    render.last_error = None
    return job


async def start_test_card(session: AsyncSession, orientation: object, frames: object) -> Job:
    """Starts the job that renders the test card of the Graphics tab at a size and a length.
    Commits. It belongs to no run and is no paid call: it only needs the motion service.

    Raises GraphicsLabInputError for an unknown orientation or a length outside what a graphic
    can be, and GraphicsLabConflictError while another test card is being made.
    """
    checked_orientation = check_orientation(orientation)
    low, high = graphics_render.TEST_CARD_MIN_FRAMES, graphics_render.TEST_CARD_MAX_FRAMES
    if not isinstance(frames, int) or isinstance(frames, bool) or not low <= frames <= high:
        raise GraphicsLabInputError(
            f"The test card must be from {low} to {high} frames "
            f"({low / FPS:g} to {high / FPS:g} seconds)."
        )
    job, created = await store.create_job(
        session,
        project_id=None,
        type=RENDER_JOB_TYPE,
        provider="local",
        input={
            "requested": graphics_render.REQUESTED_TEST_CARD,
            "orientation": checked_orientation,
            "frames": frames,
        },
        dedupe_key=graphics_render.TEST_CARD_DEDUPE_KEY,
    )
    if not created:
        raise GraphicsLabConflictError("A test card is already being rendered.")
    _logger.info("test card job %d started: %s, %d frames", job.id, checked_orientation, frames)
    return job


async def _test_card_jobs(session: AsyncSession) -> list[Job]:
    """The jobs that render a test card, newest first."""
    statement = (
        select(Job)
        .where(
            Job.type == RENDER_JOB_TYPE,
            Job.input["requested"].as_string() == graphics_render.REQUESTED_TEST_CARD,
        )
        .order_by(Job.id.desc())
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars())


async def newest_test_card(session: AsyncSession) -> tuple[Job | None, Job | None]:
    """The newest test card job (whatever it is doing, or how it ended), and the newest one that
    succeeded and still has its video. Either may be None.
    """
    jobs = await _test_card_jobs(session)
    newest = jobs[0] if jobs else None
    stored = next(
        (
            job
            for job in jobs
            if job.status == "succeeded"
            and isinstance(job.output, dict)
            and isinstance(job.output.get("path"), str)
        ),
        None,
    )
    return newest, stored


# A test card's file is only ever a `lab/<32 hex>.mp4`; any other path in a job's output is left
# alone.
_TEST_CARD_PATH = re.compile(r"lab/[0-9a-f]{32}\.mp4")


async def prune_test_cards(session: AsyncSession, *, keep_job_id: int) -> int:
    """Removes the video files of the test cards older than job `keep_job_id`, so only the newest
    stays (the owner's decision in GFX-005). A file that another row still uses is kept. Commits.
    Returns how many files were removed.
    """
    removed = 0
    storage = get_storage()
    for job in await _test_card_jobs(session):
        if job.id >= keep_job_id or job.status != "succeeded":
            continue
        output = job.output if isinstance(job.output, dict) else {}
        path = output.get("path")
        if not isinstance(path, str):
            continue
        if _TEST_CARD_PATH.fullmatch(path) and not await library_deletion.path_in_use(
            session, path
        ):
            try:
                removed += int(await storage.delete_media(path))
            except StorageError:
                _logger.warning("test card file %s could not be removed", path)
                continue
        # The file is gone (or was never ours to remove): the job no longer points at it.
        job.output = {key: value for key, value in output.items() if key != "path"}
    await session.commit()
    return removed
