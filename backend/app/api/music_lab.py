"""`/api/lab/music`: the Music lab. Try the GPU server's music and sound models on one brief.

`GET .../models` says what the lab can make: the kinds of sound, the models that make each, the
fields each model takes (with their limits) and each model's licence warning.

`POST .../prompt-drafts` starts the paid job that writes the fields of one model from a brief. It
answers with that job; its `output.fields` and `output.warnings` are what the page puts in the
form.

`POST .../runs` checks the form and starts one run per chosen model and seed, then returns at
once with HTTP 202: a run is a GPU job of seconds to minutes (a model that is not loaded starts a
worker first), so the page follows it by itself (each run carries its job, the same one the
Activity page shows). The runs of one click share a `group_key`.

`PATCH .../runs/{id}` records what a person decided after listening: a verdict and a note.

Several of the models are licensed with limits (YuE2 is non-commercial, Stable Audio needs a
licence above USD 1M revenue): `GET .../models` carries the warning for each, and the page shows it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.providers import music_generator
from app.services import music_lab, music_models
from app.services.music_models import MusicKind, MusicModel
from app.services.storage import media_url

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
Id = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]

_INVALID = {422: {"model": ErrorResponse, "description": "The form breaks a rule."}}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No run has this id."}}

# The widest a free-form object of the request may be. The values are checked field by field.
_MAX_KEYS: Final = 40


class MusicBrief(BaseModel):
    """What the author wants. Every part but `description` is optional: the ones with a story
    stage named are what that stage will fill in when the story pipeline makes the music.
    """

    model_config = ConfigDict(extra="forbid")

    description: StrictStr
    # From the Story Bible.
    genre: list[StrictStr] | None = Field(default=None, max_length=20)
    tone: list[StrictStr] | None = Field(default=None, max_length=20)
    era: StrictStr | None = None
    # From the scene definition.
    mood_start: StrictStr | None = None
    mood_middle: StrictStr | None = None
    mood_end: StrictStr | None = None
    dramatic_goal: StrictStr | None = None
    # From the environment.
    place: StrictStr | None = None
    # From the timeline.
    duration_s: Annotated[float, Field(allow_inf_nan=False)] | None = None
    under_narration: StrictBool | None = None
    # From the scene's events.
    sound_event: StrictStr | None = None
    # A song only: the lyrics to sing, or a theme to write them from.
    lyrics: StrictStr | None = None
    lyrics_theme: StrictStr | None = None
    language: StrictStr | None = None
    voice_note: StrictStr | None = None


class MusicPromptDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: MusicModel
    kind: MusicKind
    brief: MusicBrief


class ModelFieldsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: MusicModel
    # The model's fields (`GET .../models` lists them). Checked field by field.
    fields: dict[str, Any] = Field(max_length=_MAX_KEYS)
    # The prompt job that wrote the fields, when the language model did.
    prompt_job_id: Id | None = None


class LabMusicRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MusicKind
    brief: MusicBrief
    models: list[ModelFieldsIn] = Field(max_length=len(music_models.MODEL_IDS))
    # How many seeds of each model to make (1 to 4).
    variants: StrictInt = 1
    # Left out: a random seed. The versions use this seed and the next ones.
    seed: StrictInt | None = None


class LabMusicRunUpdate(BaseModel):
    """Only the fields that are sent are changed; `null` clears one."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["good", "usable", "bad"] | None = None
    note: StrictStr | None = None


class FieldSpecOut(BaseModel):
    name: str
    label: str
    type: Literal["text", "int", "number", "flag"]
    required: bool
    max_chars: int | None
    minimum: float | None
    maximum: float | None
    choices: list[str] | None


class MusicModelOut(BaseModel):
    id: MusicModel
    label: str
    endpoint: str
    # "open", "community", "non_commercial" or "unknown", and the warning to show for it.
    license_level: Literal["open", "community", "non_commercial", "unknown"]
    license_note: str
    # What the model's duration can be, in seconds. None: the length follows the lyrics.
    min_duration_s: float | None
    max_duration_s: float | None
    # The audio the model makes, as stored.
    extension: str
    fields: list[FieldSpecOut]


class MusicKindOut(BaseModel):
    id: MusicKind
    label: str
    # The models that make this kind, best first.
    models: list[MusicModel]


class MusicCatalogOut(BaseModel):
    kinds: list[MusicKindOut]
    models: list[MusicModelOut]


class LabMusicRunOut(BaseModel):
    id: int
    created_at: datetime
    # The runs of one click share it.
    group_key: str
    kind: MusicKind
    model: MusicModel
    model_label: str
    brief: dict[str, Any]
    # The fields as they were sent to the model, and what else was sent: `{seed}`.
    fields: dict[str, Any]
    params: dict[str, Any]
    # The prompt job that wrote the fields, when the language model did.
    prompt_job_id: int | None
    # The run's job: its status, phase and error.
    job: JobSummary | None
    # The finished audio, from /media. None until then.
    url: str | None
    size_bytes: int | None
    duration_s: float | None
    sample_rate: int | None
    channels: int | None
    verdict: Literal["good", "usable", "bad"] | None
    note: str | None


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _catalog() -> MusicCatalogOut:
    models = []
    for model in music_models.MODEL_IDS:
        licence = music_models.LICENSES[model]
        models.append(
            MusicModelOut(
                id=model,
                label=music_models.LABELS[model],
                endpoint=music_generator.ENDPOINTS[model],
                license_level=licence.level,
                license_note=licence.text,
                min_duration_s=music_models.MIN_DURATION_S[model],
                max_duration_s=music_models.MAX_DURATION_S[model],
                extension=music_generator.EXTENSIONS[model],
                fields=[
                    FieldSpecOut(
                        name=spec.name,
                        label=spec.label,
                        type=spec.type,
                        required=spec.required,
                        max_chars=spec.max_chars,
                        minimum=spec.minimum,
                        maximum=spec.maximum,
                        choices=list(spec.choices) if spec.choices else None,
                    )
                    for spec in music_models.field_specs(model)
                ],
            )
        )
    kinds = [
        MusicKindOut(id=kind, label=music_models.KIND_LABELS[kind], models=list(chosen))
        for kind, chosen in music_models.KIND_MODELS.items()
    ]
    return MusicCatalogOut(kinds=kinds, models=models)


def run_out(row: music_lab.RunRow) -> LabMusicRunOut:
    run = row.run
    return LabMusicRunOut(
        id=run.id,
        created_at=run.created_at,
        group_key=run.group_key,
        kind=run.kind,  # type: ignore[arg-type]  # the database CHECK holds the five kinds
        model=run.model,  # type: ignore[arg-type]  # the database CHECK holds the five models
        model_label=music_models.label(run.model),
        brief=run.brief if isinstance(run.brief, dict) else {},
        fields=run.fields if isinstance(run.fields, dict) else {},
        params=run.params if isinstance(run.params, dict) else {},
        prompt_job_id=run.prompt_job_id,
        job=(
            job_summary(JobRow(job=row.job, project_name=store.owner_name(row.job, None)))
            if row.job is not None
            else None
        ),
        url=media_url(run.path) if run.path is not None else None,
        size_bytes=run.size_bytes,
        duration_s=run.duration_s,
        sample_rate=run.sample_rate,
        channels=run.channels,
        verdict=run.verdict,  # type: ignore[arg-type]  # the database CHECK holds the three
        note=run.note,
    )


@router.get("/lab/music/models", response_model=MusicCatalogOut)
async def get_models() -> MusicCatalogOut:
    """The kinds of sound the lab makes, the models that make each, the fields each model takes
    and its licence warning.
    """
    return _catalog()


@router.post(
    "/lab/music/prompt-drafts",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_INVALID,
)
async def create_prompt_draft(body: MusicPromptDraftCreate, session: SessionDep) -> JobDetail:
    """Starts the job that writes the fields of one model from a brief (a paid call to the
    language model). Follow it with `GET /api/jobs/{id}`: when it has succeeded, `output.fields`
    are the fields and `output.warnings` is what to look at.
    """
    try:
        job = await music_lab.create_prompt_draft(
            session, body.model, body.kind, body.brief.model_dump(exclude_none=True)
        )
    except music_lab.MusicLabInputError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=store.NO_PROJECT_NAME))


@router.post(
    "/lab/music/runs",
    response_model=list[LabMusicRunOut],
    status_code=status.HTTP_202_ACCEPTED,
    responses=_INVALID,
)
async def create_runs(body: LabMusicRunCreate, session: SessionDep) -> list[LabMusicRunOut]:
    """Starts one run per chosen model and seed. Each is a paid GPU job."""
    form = music_lab.MusicLabForm(
        kind=body.kind,
        brief=body.brief.model_dump(exclude_none=True),
        models=[
            music_lab.ModelFields(
                model=item.model, fields=item.fields, prompt_job_id=item.prompt_job_id
            )
            for item in body.models
        ],
        variants=body.variants,
        seed=body.seed,
    )
    try:
        rows = await music_lab.create_runs(session, form)
    except music_lab.MusicLabInputError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return [run_out(row) for row in rows]


@router.get("/lab/music/runs", response_model=list[LabMusicRunOut])
async def list_runs(
    session: SessionDep,
    before_id: Annotated[int | None, Query(ge=1, le=_MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[LabMusicRunOut]:
    """The newest runs first. Pass the last id you have as `before_id` for the next page."""
    rows = await music_lab.list_runs(session, before_id, limit)
    return [run_out(row) for row in rows]


@router.get("/lab/music/runs/{run_id}", response_model=LabMusicRunOut, responses=_NOT_FOUND)
async def get_run(run_id: int, session: SessionDep) -> LabMusicRunOut:
    row = await music_lab.get_run(session, run_id) if 1 <= run_id <= _MAX_ID else None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} does not exist.")
    return run_out(row)


@router.patch(
    "/lab/music/runs/{run_id}",
    response_model=LabMusicRunOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def update_run(run_id: int, body: LabMusicRunUpdate, session: SessionDep) -> LabMusicRunOut:
    """Records the verdict and/or the note of a run. Only the fields in the body are changed."""
    changes = {key: getattr(body, key) for key in body.model_fields_set}
    try:
        row = (
            await music_lab.update_run(session, run_id, changes) if 1 <= run_id <= _MAX_ID else None
        )
    except music_lab.MusicLabInputError as exc:
        raise _unprocessable(str(exc)) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} does not exist.")
    return run_out(row)
