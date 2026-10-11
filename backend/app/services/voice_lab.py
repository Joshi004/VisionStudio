"""The Voice lab: try Breeze TTS on a text (Phase 21).

The lab belongs to no project. A run is a `lab_voice` job (`job.project_id` is NULL) that makes
one speech, and a `lab_voice_run` row that holds what the page lists: the mode, the text, the
settings and, once the job has finished, the stored WAV under `media/lab/`. The job holds the
status, the phase and the exact request, so a run can be resumed after a restart or a
pre-emption.

Three modes, as the server has them:

- `design`: the voice is made from a description (`instruction`). No saved voice.
- `clone`: a saved voice reads the text.
- `direction`: a saved voice reads the text, steered by the instruction (tone, emotion, pace).

A run is one request, so its text is at most 1000 characters. Each run is a paid GPU job of
one to three minutes, so it starts only from a click and is never merged into an earlier one.

Breeze TTS 2's weights and outputs are licensed for research and non-commercial use only.

This module builds and checks the requests and reads the runs. It never calls the GPU server:
`jobs/lab_voice.py` does that.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, LabVoiceRun, Voice
from app.jobs import store
from app.providers import speech_synthesizer

_logger = logging.getLogger(__name__)

RUN_JOB: Final = "lab_voice"

Mode = Literal["design", "clone", "direction"]
MODES: Final[tuple[Mode, ...]] = ("design", "clone", "direction")


class VoiceLabInputError(ValueError):
    """Something the form gets wrong. The message is meant for the user (HTTP 422)."""


@dataclass(frozen=True)
class VoiceLabForm:
    mode: Mode
    text: str
    # design: describes the voice (optional). direction: how to say it (needed). clone: none.
    instruction: str | None
    # clone and direction: the saved voice. design: none.
    voice_id: int | None
    # Left out: a random seed.
    seed: int | None
    # Left out: 4 with an instruction, 1 without (what the server recommends).
    cfg_scale: float | None


@dataclass(frozen=True)
class RunRow:
    """A run with its job and the voice it used (None for design, or a voice that is gone)."""

    run: LabVoiceRun
    job: Job | None
    voice: Voice | None


def _instruction(form: VoiceLabForm) -> str | None:
    return (form.instruction or "").strip() or None


def validate_form(form: VoiceLabForm) -> None:
    """Raises VoiceLabInputError for a form no run should be started with."""
    if form.mode not in MODES:
        raise VoiceLabInputError("Choose design, clone or direction.")
    text = form.text.strip()
    if not text:
        raise VoiceLabInputError("Write the text to speak first.")
    if len(text) > speech_synthesizer.TEXT_MAX_CHARS:
        raise VoiceLabInputError(
            f"The text must be at most {speech_synthesizer.TEXT_MAX_CHARS:,} characters."
        )
    instruction = _instruction(form)
    if instruction is not None and len(instruction) > speech_synthesizer.INSTRUCTION_MAX_CHARS:
        raise VoiceLabInputError(
            f"The instruction must be at most {speech_synthesizer.INSTRUCTION_MAX_CHARS} "
            "characters."
        )
    if form.mode == "design" and form.voice_id is not None:
        raise VoiceLabInputError("Design makes a new voice: do not choose a saved one.")
    if form.mode != "design" and form.voice_id is None:
        raise VoiceLabInputError("Choose the saved voice that reads the text.")
    if form.mode == "clone" and instruction is not None:
        raise VoiceLabInputError("Clone has no instruction. Use direction to steer the delivery.")
    if form.mode == "direction" and instruction is None:
        raise VoiceLabInputError("Direction needs an instruction: tone, emotion or pace.")
    if form.seed is not None and not 0 <= form.seed <= speech_synthesizer.SEED_MAX:
        raise VoiceLabInputError(f"The seed must be from 0 to {speech_synthesizer.SEED_MAX}.")
    # Written so that NaN, which compares false to everything, is rejected too.
    if form.cfg_scale is not None and not 0 < form.cfg_scale <= speech_synthesizer.CFG_SCALE_MAX:
        raise VoiceLabInputError(
            f"The guidance must be above 0 and at most {speech_synthesizer.CFG_SCALE_MAX:g}."
        )


async def create_run(session: AsyncSession, form: VoiceLabForm, *, commit: bool = True) -> RunRow:
    """Checks the form and starts one run. Commits, unless `commit` is False: the run and its
    job are then only flushed, so a caller (a take of the Talking character lab) can link them
    and commit everything together. Raises VoiceLabInputError.
    """
    validate_form(form)
    voice: Voice | None = None
    if form.voice_id is not None:
        voice = await session.get(Voice, form.voice_id)
        if voice is None:
            raise VoiceLabInputError(f"There is no saved voice {form.voice_id}.")

    text = form.text.strip()
    instruction = _instruction(form)
    seed = (
        form.seed if form.seed is not None else secrets.randbelow(speech_synthesizer.SEED_MAX + 1)
    )
    cfg_scale = (
        form.cfg_scale
        if form.cfg_scale is not None
        else speech_synthesizer.default_cfg_scale(instruction)
    )
    run = LabVoiceRun(
        mode=form.mode,
        text=text,
        instruction=instruction,
        voice_id=voice.id if voice is not None else None,
        params={"seed": seed, "cfg_scale": cfg_scale},
    )
    session.add(run)
    await session.flush()
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=RUN_JOB,
        provider="gpu",
        input={
            "requested": "lab_voice",
            "run_id": run.id,
            "mode": form.mode,
            "chunks": [text],
            "instruction": instruction,
            "seed": seed,
            "cfg_scale": cfg_scale,
            # What the job needs of the voice, copied now: a later edit of the voice changes
            # nothing for this run.
            "reference": (
                {
                    "voice_id": voice.id,
                    "path": voice.path,
                    "mime": voice.mime,
                    "text": voice.transcript,
                }
                if voice is not None
                else None
            ),
        },
        commit=False,
        dedupe=False,
    )
    run.job_id = job.id
    if commit:
        await session.commit()
    else:
        await session.flush()
    _logger.info("lab voice run started: run=%d mode=%s chars=%d", run.id, form.mode, len(text))
    return RunRow(run=run, job=job, voice=voice)


def _rows(result: Any) -> list[RunRow]:
    return [RunRow(run=run, job=job, voice=voice) for run, job, voice in result.all()]


def _select() -> Any:
    return (
        select(LabVoiceRun, Job, Voice)
        .outerjoin(Job, Job.id == LabVoiceRun.job_id)
        .outerjoin(Voice, Voice.id == LabVoiceRun.voice_id)
    )


async def list_runs(session: AsyncSession, before_id: int | None, limit: int) -> list[RunRow]:
    """The newest runs first, `limit` of them, those with an id below `before_id` if given."""
    statement = _select().order_by(LabVoiceRun.id.desc()).limit(limit)
    if before_id is not None:
        statement = statement.where(LabVoiceRun.id < before_id)
    return _rows(await session.execute(statement.execution_options(populate_existing=True)))


async def get_runs(session: AsyncSession, run_ids: Collection[int]) -> dict[int, RunRow]:
    """The runs with these ids, keyed by id. An id that is gone is simply missing."""
    if not run_ids:
        return {}
    statement = (
        _select().where(LabVoiceRun.id.in_(run_ids)).execution_options(populate_existing=True)
    )
    return {row.run.id: row for row in _rows(await session.execute(statement))}


async def get_run(session: AsyncSession, run_id: int) -> RunRow | None:
    statement = _select().where(LabVoiceRun.id == run_id).execution_options(populate_existing=True)
    rows = _rows(await session.execute(statement))
    return rows[0] if rows else None
