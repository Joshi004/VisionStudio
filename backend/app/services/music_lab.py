"""The Music lab: try the GPU server's music and sound models on one brief and compare them.

The lab belongs to no project. One click starts one or more runs (several models, and several
seeds of each), and a run is a `lab_music` job (`job.project_id` is NULL) that makes one piece of
audio, plus a `lab_music_run` row that holds what the page lists: the kind, the model, the brief,
the prompt fields that were sent, the seed and, once the job has finished, the stored file under
`media/lab/`. The runs of one click share a `group_key`, so the page shows them side by side. A
person listens and gives each run a verdict (good, usable or bad) and a note.

The fields of a run are what the model's request is made of (a caption and lyrics, a style, a
prompt: `music_models.FIELDS`). They come from the language model (`create_prompt_draft` starts
the paid job that writes them for one model) or are typed, and they are checked against the
limits of the server's schema before anything starts, so a bad form starts nothing.

Every run is a paid GPU job, so it starts only from a click and is never merged into an earlier
one: trying the same brief again with another seed is what the lab is for.

This module builds and checks the requests and reads the runs. It never calls the GPU server:
`jobs/generate_lab_music.py` does that.
"""

from __future__ import annotations

import logging
import math
import secrets
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, LabMusicRun
from app.jobs import store
from app.providers import contract_guard, music_generator
from app.services import api_contract, music_models
from app.services import music_prompt_writer as prompt_writer
from app.services.music_models import MusicKind, MusicModel

_logger = logging.getLogger(__name__)

RUN_JOB: Final = "lab_music"
PROMPT_JOB: Final = "write_lab_music_prompt"
PARTITION_KEY: Final = "gpu_partition"

# How many seeds of each model one click may start, and how many runs in all. Each is a paid GPU
# job of a few seconds to a few minutes (a model that is not loaded starts a worker first).
MAX_VARIANTS: Final = 4
MAX_RUNS_PER_CLICK: Final = 12
NOTE_MAX_CHARS: Final = 1000

VERDICTS: Final = ("good", "usable", "bad")

# The brief's text fields and how long each may be. They are what the prompt writer is told.
_BRIEF_TEXT_LIMITS: Final[dict[str, int]] = {
    "description": 2000,
    "era": 120,
    "mood_start": 200,
    "mood_middle": 200,
    "mood_end": 200,
    "dramatic_goal": 300,
    "place": 300,
    "sound_event": 300,
    "lyrics": 4000,
    "lyrics_theme": 500,
    "language": 40,
    "voice_note": 200,
}
_BRIEF_LIST_LIMITS: Final[dict[str, tuple[int, int]]] = {
    # name: (most items, most characters in an item), as the Story Bible has them.
    "genre": (4, 60),
    "tone": (5, 60),
}
# The fields that only mean something for a song.
_SONG_ONLY: Final = ("lyrics", "lyrics_theme", "language", "voice_note")
BRIEF_MAX_DURATION_S: Final = 600.0


class MusicLabInputError(ValueError):
    """Something the form gets wrong. The message is meant for the user (HTTP 422)."""


@dataclass(frozen=True)
class ModelFields:
    """The fields to send to one model, and the prompt job that wrote them (None when typed)."""

    model: MusicModel
    fields: dict[str, Any]
    prompt_job_id: int | None


@dataclass(frozen=True)
class MusicLabForm:
    kind: MusicKind
    brief: dict[str, Any]
    models: list[ModelFields]
    # How many seeds of each model to make, one after another from the first seed.
    variants: int
    # Left out: a random one.
    seed: int | None


@dataclass(frozen=True)
class RunRow:
    """A run with its job."""

    run: LabMusicRun
    job: Job | None


# --- The brief ----------------------------------------------------------------------------


def _clean_text(name: str, value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MusicLabInputError(f"The brief's {name.replace('_', ' ')} must be text.")
    text = value.strip()
    limit = _BRIEF_TEXT_LIMITS[name]
    if len(text) > limit:
        raise MusicLabInputError(
            f"The brief's {name.replace('_', ' ')} must be at most {limit:,} characters."
        )
    return text


def _clean_list(name: str, value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MusicLabInputError(f"The brief's {name} must be a list of words.")
    items = [" ".join(item.split()) for item in value if item.strip()]
    most, longest = _BRIEF_LIST_LIMITS[name]
    if len(items) > most:
        raise MusicLabInputError(f"The brief's {name} can have at most {most} items.")
    if any(len(item) > longest for item in items):
        raise MusicLabInputError(
            f"Each item of the brief's {name} must be at most {longest} characters."
        )
    return items


def clean_brief(kind: object, raw: object) -> dict[str, Any]:
    """The brief tidied and checked: text stripped, empty fields dropped, the song-only fields
    kept only for a song. Raises MusicLabInputError.
    """
    if not music_models.is_music_kind(kind):
        raise MusicLabInputError(
            "Choose what to make: a score, a song, a stem, a sound effect or an ambience."
        )
    source = raw if isinstance(raw, dict) else {}
    brief: dict[str, Any] = {"kind": kind}
    for name in _BRIEF_TEXT_LIMITS:
        if name in _SONG_ONLY and kind != "song":
            continue
        text = _clean_text(name, source.get(name))
        if text:
            brief[name] = text
    for name in _BRIEF_LIST_LIMITS:
        items = _clean_list(name, source.get(name))
        if items:
            brief[name] = items
    if "description" not in brief:
        raise MusicLabInputError("Describe what you need first.")

    duration = source.get("duration_s")
    if duration is not None:
        if (
            isinstance(duration, bool)
            or not isinstance(duration, int | float)
            or not math.isfinite(duration)
            or not 1 <= duration <= BRIEF_MAX_DURATION_S
        ):
            raise MusicLabInputError(
                f"The length must be from 1 to {BRIEF_MAX_DURATION_S:g} seconds."
            )
        brief["duration_s"] = float(duration)
    if source.get("under_narration") is True:
        brief["under_narration"] = True
    return brief


def models_for(kind: MusicKind) -> tuple[MusicModel, ...]:
    return music_models.KIND_MODELS[kind]


# --- Prompt drafts ------------------------------------------------------------------------


async def create_prompt_draft(
    session: AsyncSession, model: object, kind: object, raw_brief: object
) -> Job:
    """Starts the job that writes the fields of `model` from the brief. Commits.

    Raises MusicLabInputError. Each call is a paid try of its own, so none is merged into an
    earlier one.
    """
    brief = clean_brief(kind, raw_brief)
    if not music_models.is_music_model(model):
        raise MusicLabInputError("Choose a music model.")
    if model not in models_for(brief["kind"]):
        raise MusicLabInputError(
            f"{music_models.label(model)} does not make "
            f"{music_models.KIND_LABELS[brief['kind']].lower()}."
        )
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=PROMPT_JOB,
        provider="llm",
        input={
            "requested": "lab_music_prompt",
            "inputs": prompt_writer.prompt_inputs(model, brief),
        },
        dedupe=False,
    )
    return job


# --- Runs ---------------------------------------------------------------------------------


def validate_form(form: MusicLabForm) -> None:
    """Raises MusicLabInputError for a form no run should be started with. The brief and the
    fields are checked separately (`clean_brief`, `music_models.field_problems`).
    """
    if not form.models:
        raise MusicLabInputError("Choose at least one model.")
    seen: set[str] = set()
    for item in form.models:
        if item.model in seen:
            raise MusicLabInputError(f"{music_models.label(item.model)} is chosen twice.")
        seen.add(item.model)
        if item.model not in models_for(form.kind):
            raise MusicLabInputError(
                f"{music_models.label(item.model)} does not make "
                f"{music_models.KIND_LABELS[form.kind].lower()}."
            )
    if not 1 <= form.variants <= MAX_VARIANTS:
        raise MusicLabInputError(f"Make from 1 to {MAX_VARIANTS} versions of each model.")
    runs = len(form.models) * form.variants
    if runs > MAX_RUNS_PER_CLICK:
        raise MusicLabInputError(
            f"That would start {runs} runs. One click starts at most {MAX_RUNS_PER_CLICK}."
        )
    if form.seed is not None and not 0 <= form.seed <= music_models.SEED_MAX:
        raise MusicLabInputError(f"The seed must be from 0 to {music_models.SEED_MAX}.")


async def _check_prompt_job(session: AsyncSession, job_id: int | None) -> None:
    if job_id is None:
        return
    job = await session.get(Job, job_id)
    if job is None or job.type != PROMPT_JOB:
        raise MusicLabInputError(f"There is no prompt job {job_id}.")


async def create_runs(session: AsyncSession, form: MusicLabForm) -> list[RunRow]:
    """Checks the form and starts one run for every chosen model and seed. Commits. Raises
    MusicLabInputError.

    Everything is checked first (the brief, every model's fields, and that the newest recorded
    GPU API has each endpoint), so a bad form starts nothing. The runs share a `group_key`.
    Every model gets the same seeds, so the models can be compared on equal terms.
    """
    validate_form(form)
    brief = clean_brief(form.kind, form.brief)
    partition = await settings_service.get_str(session, PARTITION_KEY)
    bodies = await contract_guard.latest_bodies(session)
    spec = next((body for body in bodies if api_contract.is_openapi(body)), None)

    base_seed = form.seed if form.seed is not None else secrets.randbelow(music_models.SEED_MAX + 1)
    seeds = [(base_seed + offset) % (music_models.SEED_MAX + 1) for offset in range(form.variants)]

    planned: list[tuple[ModelFields, dict[str, Any], int, dict[str, Any]]] = []
    for item in form.models:
        fields = music_models.coerce_fields(item.model, item.fields)
        problems = music_models.field_problems(item.model, fields)
        if problems:
            raise MusicLabInputError(f"{music_models.label(item.model)}: {problems[0]}")
        try:
            music_generator.check_endpoint(spec, item.model)
        except ValueError as exc:
            raise MusicLabInputError(str(exc)) from exc
        await _check_prompt_job(session, item.prompt_job_id)
        for seed in seeds:
            body = music_generator.build_body(item.model, fields, seed=seed, partition=partition)
            planned.append((item, fields, seed, body))

    group_key = secrets.token_hex(8)
    rows: list[RunRow] = []
    for item, fields, seed, body in planned:
        endpoint = music_generator.ENDPOINTS[item.model]
        run = LabMusicRun(
            group_key=group_key,
            kind=form.kind,
            model=item.model,
            endpoint=endpoint,
            brief=brief,
            fields=fields,
            params={"seed": seed},
            prompt_job_id=item.prompt_job_id,
        )
        session.add(run)
        await session.flush()
        job, _created = await store.create_job(
            session,
            project_id=None,
            type=RUN_JOB,
            provider="gpu",
            input={
                "requested": "lab_music",
                "run_id": run.id,
                "model": item.model,
                "endpoint": endpoint,
                "request": body,
            },
            commit=False,
            dedupe=False,
        )
        run.job_id = job.id
        rows.append(RunRow(run=run, job=job))
    await session.commit()
    _logger.info(
        "lab music runs started: group=%s kind=%s runs=%d", group_key, form.kind, len(rows)
    )
    return rows


# --- Judging a run ------------------------------------------------------------------------


async def update_run(session: AsyncSession, run_id: int, changes: dict[str, Any]) -> RunRow | None:
    """Sets the verdict and/or the note of a run (only the keys in `changes`). None when the run
    does not exist. Commits. Raises MusicLabInputError.
    """
    run = await session.get(LabMusicRun, run_id)
    if run is None:
        return None
    if "verdict" in changes:
        verdict = changes["verdict"]
        if verdict is not None and verdict not in VERDICTS:
            raise MusicLabInputError("The verdict is good, usable or bad.")
        run.verdict = verdict
    if "note" in changes:
        note = changes["note"]
        if note is not None and not isinstance(note, str):
            raise MusicLabInputError("The note must be text.")
        text = (note or "").strip()
        if len(text) > NOTE_MAX_CHARS:
            raise MusicLabInputError(f"The note must be at most {NOTE_MAX_CHARS:,} characters.")
        run.note = text or None
    await session.commit()
    return await get_run(session, run_id)


# --- Reading runs -------------------------------------------------------------------------


def _rows(result: Any) -> list[RunRow]:
    return [RunRow(run=run, job=job) for run, job in result.all()]


def _select() -> Any:
    return select(LabMusicRun, Job).outerjoin(Job, Job.id == LabMusicRun.job_id)


async def list_runs(session: AsyncSession, before_id: int | None, limit: int) -> list[RunRow]:
    """The newest runs first, `limit` of them, those with an id below `before_id` if given."""
    statement = _select().order_by(LabMusicRun.id.desc()).limit(limit)
    if before_id is not None:
        statement = statement.where(LabMusicRun.id < before_id)
    return _rows(await session.execute(statement.execution_options(populate_existing=True)))


async def get_runs(session: AsyncSession, run_ids: Collection[int]) -> dict[int, RunRow]:
    """The runs with these ids, keyed by id. An id that is gone is simply missing."""
    if not run_ids:
        return {}
    statement = (
        _select().where(LabMusicRun.id.in_(run_ids)).execution_options(populate_existing=True)
    )
    return {row.run.id: row for row in _rows(await session.execute(statement))}


async def get_run(session: AsyncSession, run_id: int) -> RunRow | None:
    statement = _select().where(LabMusicRun.id == run_id).execution_options(populate_existing=True)
    rows = _rows(await session.execute(statement))
    return rows[0] if rows else None
