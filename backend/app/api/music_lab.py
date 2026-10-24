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

`POST .../edits` starts the same kind of run from a recording instead of text (MUSIC-004):
`repaint` or `cover` (ACE-Step), `inpaint` or `transform` (Stable Audio 3), `transform` (Stable
Audio Open). The recording is an earlier run, an uploaded file or a join of two runs. `POST
.../sources/upload` stores an uploaded recording (the raw file is the request body), `POST
.../sources/join` puts two finished runs end to end, with silence between and after them if asked,
and `GET .../sources` lists the stored ones.

`GET .../runs/{id}/measurements` says what is in a run's audio (silences, loudness, the loudest
moment, sudden sounds, quiet points, changes of character, how it ends). It is measured the first
time it is asked for and stored with the file's hash (MUSIC-003).

Several of the models are licensed with limits (YuE2 is non-commercial, Stable Audio needs a
licence above USD 1M revenue): `GET .../models` carries the warning for each, and the page shows it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.api.projects import content_length, require_octet_stream
from app.db.models import LabMusicSource
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.providers import music_generator
from app.services import audio_measurements, music_lab, music_models, music_sources
from app.services.music_models import MusicKind, MusicModel
from app.services.storage import StorageError, get_storage, media_url

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
Id = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]

_INVALID = {422: {"model": ErrorResponse, "description": "The form breaks a rule."}}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No run has this id."}}
_UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}

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


class MusicEditCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["repaint", "cover", "inpaint", "transform"]
    model: MusicModel
    kind: MusicKind
    # What the edit is for, in a sentence.
    description: StrictStr
    # Exactly one of the two: an earlier run, or an uploaded or joined recording.
    source_run_id: Id | None = None
    source_id: Id | None = None
    # The fields of the operation (`GET .../models` lists them). Checked field by field.
    fields: dict[str, Any] = Field(max_length=_MAX_KEYS)
    # How many seeds to make (1 to 4).
    variants: StrictInt = 1
    seed: StrictInt | None = None


class MusicSourceJoin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Two finished runs, in the order they are put together.
    run_ids: list[Id] = Field(min_length=2, max_length=2)
    # Silence between the two, and after them, in seconds.
    gap_s: Annotated[float, Field(allow_inf_nan=False)] = 0.0
    tail_s: Annotated[float, Field(allow_inf_nan=False)] = 0.0


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


class EditModelOut(BaseModel):
    model: MusicModel
    label: str
    endpoint: str
    # The longest source this model takes for the operation, in seconds.
    max_source_s: float
    fields: list[FieldSpecOut]


class EditOperationOut(BaseModel):
    id: Literal["repaint", "cover", "inpaint", "transform"]
    label: str
    help: str
    models: list[EditModelOut]


class MusicKindOut(BaseModel):
    id: MusicKind
    label: str
    # The models that make this kind, best first.
    models: list[MusicModel]


class MusicCatalogOut(BaseModel):
    kinds: list[MusicKindOut]
    models: list[MusicModelOut]
    # The editing operations, each with the models that make it and the fields it takes.
    operations: list[EditOperationOut]


class JoinPartOut(BaseModel):
    run_id: int
    # Where the part sits in the joined file, in seconds.
    start_s: float
    end_s: float


class MusicSourceOut(BaseModel):
    """A recording made for editing: an upload, or a join of two runs."""

    id: int
    created_at: datetime
    kind: Literal["upload", "join"]
    label: str
    url: str
    duration_s: float
    size_bytes: int
    sample_rate: int | None
    channels: int | None
    # A join only: the middle of the join, in seconds from the start, and how it was made.
    seam_s: float | None
    parts: list[JoinPartOut] | None
    gap_s: float | None
    tail_s: float | None


class RunSourceOut(BaseModel):
    """What an edit started from."""

    type: Literal["run", "upload", "join"]
    label: str
    # The recording, to play it. None when its file is gone.
    url: str | None
    duration_s: float | None
    run_id: int | None
    source_id: int | None
    seam_s: float | None


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
    # An edit: what it does and what it started from. None for text-to-audio.
    operation: Literal["repaint", "cover", "inpaint", "transform"] | None
    source: RunSourceOut | None


class LoudestMomentOut(BaseModel):
    # The middle of the loudest 100 ms, and its level in dB relative to full scale.
    time_s: float
    level_db: float


class SilenceOut(BaseModel):
    start_s: float
    end_s: float


class StrongPointOut(BaseModel):
    """A sudden sound or a change of character. `strength` is how many standard deviations the
    point stands above the file's typical value, so 3 is clear and 10 is unmistakable."""

    time_s: float
    strength: float


class QuietPointOut(BaseModel):
    time_s: float
    level_db: float


class EndingOut(BaseModel):
    # `decay`: the sound dies away (a real ending or a fade). `cut`: it stops while still loud.
    kind: Literal["decay", "cut"]
    end_level_db: float
    # How far the last half second is under the loud level of the piece.
    drop_db: float


class LoudnessOut(BaseModel):
    integrated_lufs: float | None
    loudness_range_lu: float | None
    true_peak_dbtp: float | None
    sample_peak_dbfs: float | None
    clipping: bool
    clipped_sample_count: int


class ShortTermLoudnessOut(BaseModel):
    # `lufs[i]` is the loudness of the 3 seconds that end at `i * step_s`. None where undefined
    # (the first 3 seconds, and silence).
    step_s: float
    lufs: list[float | None]


class AudioMeasurementOut(BaseModel):
    """What was measured in a run's audio (MUSIC-003). All times are seconds from the start."""

    analysis_version: int
    # The rules and thresholds the result was made with.
    parameters: dict[str, Any]
    sample_rate: int | None
    channels: int | None
    duration_s: float
    leading_silence_s: float
    trailing_silence_s: float
    # Silences inside the sound (the leading and trailing ones are the two fields above).
    silences: list[SilenceOut]
    loudness: LoudnessOut
    short_term_loudness: ShortTermLoudnessOut
    loudest_moment: LoudestMomentOut | None
    # Sudden sounds. Good to about 50 ms.
    onsets: list[StrongPointOut]
    quiet_points: list[QuietPointOut]
    # Where the sound changes character. None in the first and last 2 seconds.
    change_points: list[StrongPointOut]
    ending: EndingOut | None


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _field_spec_out(spec: music_models.FieldSpec) -> FieldSpecOut:
    return FieldSpecOut(
        name=spec.name,
        label=spec.label,
        type=spec.type,
        required=spec.required,
        max_chars=spec.max_chars,
        minimum=spec.minimum,
        maximum=spec.maximum,
        choices=list(spec.choices) if spec.choices else None,
    )


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
                fields=[_field_spec_out(spec) for spec in music_models.field_specs(model)],
            )
        )
    kinds = [
        MusicKindOut(id=kind, label=music_models.KIND_LABELS[kind], models=list(chosen))
        for kind, chosen in music_models.KIND_MODELS.items()
    ]
    operations = [
        EditOperationOut(
            id=operation,
            label=music_models.EDIT_LABELS[operation],
            help=music_models.EDIT_HELP[operation],
            models=[
                EditModelOut(
                    model=model,
                    label=music_models.LABELS[model],
                    endpoint=music_generator.EDIT_ENDPOINTS[(operation, model)],
                    max_source_s=music_models.MAX_SOURCE_S[(operation, model)],
                    fields=[
                        _field_spec_out(spec)
                        for spec in music_models.edit_field_specs(operation, model)
                    ],
                )
                for model in music_models.EDIT_MODELS[operation]
            ],
        )
        for operation in music_models.EDIT_OPERATION_IDS
    ]
    return MusicCatalogOut(kinds=kinds, models=models, operations=operations)


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
        operation=run.operation,  # type: ignore[arg-type]  # the database CHECK holds the four
        source=_run_source_out(row.source),
    )


def _run_source_out(ref: music_lab.SourceRef | None) -> RunSourceOut | None:
    if ref is None:
        return None
    return RunSourceOut(
        type=ref.type,
        label=ref.label,
        url=media_url(ref.path) if ref.path is not None else None,
        duration_s=ref.duration_s,
        run_id=ref.run_id,
        source_id=ref.source_id,
        seam_s=ref.seam_s,
    )


def source_out(source: LabMusicSource) -> MusicSourceOut:
    recipe = source.recipe if isinstance(source.recipe, dict) else None
    parts = recipe.get("parts") if recipe is not None else None
    return MusicSourceOut(
        id=source.id,
        created_at=source.created_at,
        kind=source.kind,  # type: ignore[arg-type]  # the database CHECK holds the two
        label=source.label,
        url=media_url(source.path),
        duration_s=source.duration_s,
        size_bytes=source.size_bytes,
        sample_rate=source.sample_rate,
        channels=source.channels,
        seam_s=music_sources.seam_s(source),
        parts=[JoinPartOut.model_validate(part) for part in parts]
        if isinstance(parts, list)
        else None,
        gap_s=recipe.get("gap_s") if recipe is not None else None,
        tail_s=recipe.get("tail_s") if recipe is not None else None,
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


@router.post(
    "/lab/music/edits",
    response_model=list[LabMusicRunOut],
    status_code=status.HTTP_202_ACCEPTED,
    responses=_INVALID,
)
async def create_edits(body: MusicEditCreate, session: SessionDep) -> list[LabMusicRunOut]:
    """Starts one edit run per seed, from an earlier run, an uploaded recording or a join of two
    runs. Each is a paid GPU job.
    """
    form = music_lab.EditForm(
        operation=body.operation,
        model=body.model,
        kind=body.kind,
        description=body.description,
        source_run_id=body.source_run_id,
        source_id=body.source_id,
        fields=body.fields,
        variants=body.variants,
        seed=body.seed,
    )
    try:
        rows = await music_lab.create_edits(session, form)
    except music_lab.MusicLabInputError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return [run_out(row) for row in rows]


@router.get("/lab/music/sources", response_model=list[MusicSourceOut])
async def list_sources(session: SessionDep) -> list[MusicSourceOut]:
    """The recordings made for editing (uploads and joins), newest first."""
    return [source_out(source) for source in await music_sources.list_sources(session)]


@router.post(
    "/lab/music/sources/upload",
    response_model=MusicSourceOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        413: {"model": ErrorResponse, "description": "The file is larger than the limit."},
        415: {
            "model": ErrorResponse,
            "description": "The body is not sent as application/octet-stream.",
        },
        422: {"model": ErrorResponse, "description": "The file or the name is not acceptable."},
    },
    openapi_extra=_UPLOAD_BODY,
)
async def upload_source(
    request: Request,
    session: SessionDep,
    name: Annotated[str, Query(max_length=400)],
) -> MusicSourceOut:
    """Stores a recording (WAV, MP3, M4A or FLAC, sent as the raw request body) to edit. The type
    is decided by what the file holds.
    """
    require_octet_stream(request)
    # No transaction of this request stays open while the file is received and probed.
    await session.commit()
    try:
        source = await music_sources.save_upload(
            session, name, request.stream(), content_length(request)
        )
    except music_sources.MusicSourceError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return source_out(source)


@router.post(
    "/lab/music/sources/join",
    response_model=MusicSourceOut,
    status_code=status.HTTP_201_CREATED,
    responses=_INVALID,
)
async def join_sources(body: MusicSourceJoin, session: SessionDep) -> MusicSourceOut:
    """Puts two finished runs end to end, with silence between them and after them if asked, and
    stores the result as a recording to edit. Free: nothing goes to the GPU server.
    """
    try:
        source = await music_sources.make_join(session, body.run_ids, body.gap_s, body.tail_s)
    except music_sources.MusicSourceError as exc:
        raise _unprocessable(exc.message) from exc
    return source_out(source)


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


@router.get(
    "/lab/music/runs/{run_id}/measurements",
    response_model=AudioMeasurementOut,
    responses={
        **_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "The run has no audio yet."},
        422: {"model": ErrorResponse, "description": "The audio could not be measured."},
    },
)
async def get_run_measurements(run_id: int, session: SessionDep) -> AudioMeasurementOut:
    """What is in the run's audio: silences, loudness, the loudest moment, sudden sounds, quiet
    points, places where the sound changes and how it ends. Measured the first time it is asked
    for and stored with the file's hash, so asking again reads the stored result.
    """
    row = await music_lab.get_run(session, run_id) if 1 <= run_id <= _MAX_ID else None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} does not exist.")
    run = row.run
    if run.path is None or run.sha256 is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Run {run_id} has no audio yet.")
    try:
        path = get_storage().get_path(run.path)
        content = await audio_measurements.measure(session, path, run.sha256)
    except (StorageError, audio_measurements.MeasurementError) as exc:
        raise _unprocessable(str(exc)) from exc
    return AudioMeasurementOut.model_validate(content)


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
