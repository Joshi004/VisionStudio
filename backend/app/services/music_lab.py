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

An edit (MUSIC-004: repaint, cover, inpaint, transform) is a run too: it starts from a source
recording (an earlier run, an uploaded file or a join of two runs, `services/music_sources.py`),
has the fields of its operation (`music_models.EDIT_FIELDS`) and is made by the same job. Its
window or strength is part of the fields, so the card shows it with everything else that was sent.

This module builds and checks the requests and reads the runs. It never calls the GPU server:
`jobs/generate_lab_music.py` does that.
"""

from __future__ import annotations

import logging
import math
import secrets
from collections.abc import Collection
from dataclasses import dataclass, replace
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, LabMusicRun, LabMusicSource
from app.jobs import store
from app.providers import contract_guard, music_generator
from app.services import api_contract, music_models, music_sources
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
class SourceRef:
    """What an edit started from, for the run card."""

    type: Literal["run", "upload", "join"]
    label: str
    # The stored file, or None when it is gone from the database.
    path: str | None
    duration_s: float | None
    run_id: int | None
    source_id: int | None
    # The middle of a join, in seconds from the start of the joined file.
    seam_s: float | None
    recipe: dict[str, Any] | None


@dataclass(frozen=True)
class RunRow:
    """A run with its job, and for an edit what it started from."""

    run: LabMusicRun
    job: Job | None
    source: SourceRef | None = None


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
            music_generator.check_endpoint(spec, music_generator.ENDPOINTS[item.model])
        except ValueError as exc:
            raise MusicLabInputError(str(exc)) from exc
        await _check_prompt_job(session, item.prompt_job_id)
        for seed in seeds:
            body = music_generator.build_body(item.model, fields, seed=seed, partition=partition)
            planned.append((item, fields, seed, body))

    group_key = secrets.token_hex(8)
    rows: list[RunRow] = []
    for item, fields, seed, body in planned:
        rows.append(
            await add_run(
                session,
                model=item.model,
                kind=form.kind,
                brief=brief,
                fields=fields,
                seed=seed,
                body=body,
                group_key=group_key,
                prompt_job_id=item.prompt_job_id,
            )
        )
    await session.commit()
    _logger.info(
        "lab music runs started: group=%s kind=%s runs=%d", group_key, form.kind, len(rows)
    )
    return rows


async def add_run(
    session: AsyncSession,
    *,
    model: MusicModel,
    kind: MusicKind,
    brief: dict[str, Any],
    fields: dict[str, Any],
    seed: int,
    body: dict[str, Any],
    group_key: str,
    prompt_job_id: int | None = None,
    project_id: int | None = None,
) -> RunRow:
    """Adds one text-to-audio run and its `lab_music` job, and flushes. Does not commit, so a
    caller can start several runs, or save something else with them, in one transaction. `body`
    is the request the job submits (`music_generator.build_body`) and `fields` are what it was
    made from. `project_id` is None for a lab run; the story pipeline's runs (MUSIC-007) name
    their project, so the Activity page shows whose they are.
    """
    endpoint = music_generator.ENDPOINTS[model]
    run = LabMusicRun(
        group_key=group_key,
        kind=kind,
        model=model,
        endpoint=endpoint,
        brief=brief,
        fields=fields,
        params={"seed": seed},
        prompt_job_id=prompt_job_id,
    )
    session.add(run)
    await session.flush()
    job, _created = await store.create_job(
        session,
        project_id=project_id,
        type=RUN_JOB,
        provider="gpu",
        input={
            "requested": "lab_music",
            "run_id": run.id,
            "model": model,
            "endpoint": endpoint,
            "request": body,
        },
        commit=False,
        dedupe=False,
    )
    run.job_id = job.id
    return RunRow(run=run, job=job)


async def generation_partition(session: AsyncSession, model: MusicModel) -> str:
    """The GPU partition to send a story run to, after checking that the newest recorded GPU API
    has the model's text-to-audio endpoint (the check `create_runs` makes). Raises
    MusicLabInputError.
    """
    bodies = await contract_guard.latest_bodies(session)
    spec = next((body for body in bodies if api_contract.is_openapi(body)), None)
    try:
        music_generator.check_endpoint(spec, music_generator.ENDPOINTS[model])
    except ValueError as exc:
        raise MusicLabInputError(str(exc)) from exc
    return await settings_service.get_str(session, PARTITION_KEY)


# --- Edits --------------------------------------------------------------------------------


@dataclass(frozen=True)
class EditForm:
    """One edit: the operation, the model, the source (a run or a stored source), the fields of
    the operation, and how many seeds to make."""

    operation: str
    model: str
    kind: str
    # What the edit is for, in a sentence. It is the brief's description.
    description: str
    source_run_id: int | None
    source_id: int | None
    fields: dict[str, Any]
    variants: int
    seed: int | None


async def create_edits(session: AsyncSession, form: EditForm) -> list[RunRow]:
    """Checks the edit and starts one run for every seed. Commits. Raises MusicLabInputError.

    Everything is checked first (the operation and model, the source, the fields and the rules
    that need the source's length, and that the newest recorded GPU API has the endpoint and the
    upload endpoint), so a bad edit starts nothing. The runs share a `group_key`.
    """
    operation, model = form.operation, form.model
    if not music_models.is_edit_operation(operation):
        raise MusicLabInputError("Choose what to do: repaint, cover, inpaint or transform.")
    if not music_models.is_music_model(model) or not music_models.edit_supported(operation, model):
        raise MusicLabInputError(
            f"{music_models.label(model)} does not make "
            f"{music_models.EDIT_LABELS[operation].lower()}."
        )
    if not 1 <= form.variants <= MAX_VARIANTS:
        raise MusicLabInputError(f"Make from 1 to {MAX_VARIANTS} versions.")
    if form.seed is not None and not 0 <= form.seed <= music_models.SEED_MAX:
        raise MusicLabInputError(f"The seed must be from 0 to {music_models.SEED_MAX}.")
    brief = clean_brief(form.kind, {"description": form.description})

    try:
        source = await music_sources.resolve(
            session, run_id=form.source_run_id, source_id=form.source_id
        )
    except music_sources.MusicSourceError as exc:
        raise MusicLabInputError(exc.message) from exc

    fields = music_models.coerce_edit_fields(operation, model, form.fields)
    problems = music_models.edit_problems(operation, model, fields, source.duration_s)
    if problems:
        raise MusicLabInputError(f"{music_models.label(model)}: {problems[0]}")

    endpoint = music_generator.EDIT_ENDPOINTS[(operation, model)]
    bodies = await contract_guard.latest_bodies(session)
    spec = next((body for body in bodies if api_contract.is_openapi(body)), None)
    try:
        music_generator.check_edit_endpoints(spec, endpoint)
    except ValueError as exc:
        raise MusicLabInputError(str(exc)) from exc
    partition = await settings_service.get_str(session, PARTITION_KEY)

    base_seed = form.seed if form.seed is not None else secrets.randbelow(music_models.SEED_MAX + 1)
    seeds = [(base_seed + offset) % (music_models.SEED_MAX + 1) for offset in range(form.variants)]

    group_key = secrets.token_hex(8)
    rows: list[RunRow] = []
    for seed in seeds:
        body = music_generator.build_edit_body(
            operation, model, fields, seed=seed, partition=partition
        )
        run = LabMusicRun(
            group_key=group_key,
            kind=brief["kind"],
            model=model,
            endpoint=endpoint,
            brief=brief,
            fields=fields,
            params={"seed": seed},
            operation=operation,
            source_run_id=source.run_id,
            source_id=source.source_id,
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
                "model": model,
                "operation": operation,
                "endpoint": endpoint,
                "request": body,
                "source": {
                    "path": source.path,
                    "filename": source.filename,
                    "mime": source.mime,
                    "label": source.label,
                },
            },
            commit=False,
            dedupe=False,
        )
        run.job_id = job.id
        rows.append(RunRow(run=run, job=job))
    await session.commit()
    _logger.info(
        "lab music edits started: group=%s operation=%s model=%s source=%s runs=%d",
        group_key,
        operation,
        model,
        source.label,
        len(rows),
    )
    return await _attach_sources(session, rows)


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


async def _attach_sources(session: AsyncSession, rows: list[RunRow]) -> list[RunRow]:
    """The rows with what each edit started from. Text-to-audio rows are returned as they are."""
    run_ids = {row.run.source_run_id for row in rows if row.run.source_run_id is not None}
    source_ids = {row.run.source_id for row in rows if row.run.source_id is not None}
    if not run_ids and not source_ids:
        return rows
    runs: dict[int, LabMusicRun] = {}
    if run_ids:
        found = await session.execute(select(LabMusicRun).where(LabMusicRun.id.in_(run_ids)))
        runs = {run.id: run for run in found.scalars()}
    sources: dict[int, LabMusicSource] = {}
    if source_ids:
        found_sources = await session.execute(
            select(LabMusicSource).where(LabMusicSource.id.in_(source_ids))
        )
        sources = {source.id: source for source in found_sources.scalars()}

    attached: list[RunRow] = []
    for row in rows:
        ref: SourceRef | None = None
        if row.run.source_run_id is not None:
            source_run = runs.get(row.run.source_run_id)
            ref = SourceRef(
                type="run",
                label=f"Run {row.run.source_run_id}",
                path=source_run.path if source_run is not None else None,
                duration_s=source_run.duration_s if source_run is not None else None,
                run_id=row.run.source_run_id,
                source_id=None,
                seam_s=None,
                recipe=None,
            )
        elif row.run.source_id is not None:
            source = sources.get(row.run.source_id)
            if source is not None:
                ref = SourceRef(
                    type="join" if source.kind == "join" else "upload",
                    label=source.label,
                    path=source.path,
                    duration_s=source.duration_s,
                    run_id=None,
                    source_id=source.id,
                    seam_s=music_sources.seam_s(source),
                    recipe=source.recipe if isinstance(source.recipe, dict) else None,
                )
        attached.append(replace(row, source=ref))
    return attached


def _select() -> Any:
    return select(LabMusicRun, Job).outerjoin(Job, Job.id == LabMusicRun.job_id)


async def list_runs(session: AsyncSession, before_id: int | None, limit: int) -> list[RunRow]:
    """The newest runs first, `limit` of them, those with an id below `before_id` if given."""
    statement = _select().order_by(LabMusicRun.id.desc()).limit(limit)
    if before_id is not None:
        statement = statement.where(LabMusicRun.id < before_id)
    rows = _rows(await session.execute(statement.execution_options(populate_existing=True)))
    return await _attach_sources(session, rows)


async def get_runs(session: AsyncSession, run_ids: Collection[int]) -> dict[int, RunRow]:
    """The runs with these ids, keyed by id. An id that is gone is simply missing."""
    if not run_ids:
        return {}
    statement = (
        _select().where(LabMusicRun.id.in_(run_ids)).execution_options(populate_existing=True)
    )
    rows = await _attach_sources(session, _rows(await session.execute(statement)))
    return {row.run.id: row for row in rows}


async def get_run(session: AsyncSession, run_id: int) -> RunRow | None:
    statement = _select().where(LabMusicRun.id == run_id).execution_options(populate_existing=True)
    rows = await _attach_sources(session, _rows(await session.execute(statement)))
    return rows[0] if rows else None
