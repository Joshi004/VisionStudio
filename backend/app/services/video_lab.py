"""The Video lab: try a prompt on LTX-2.3 and LTX-2.5, side by side (Phase 19).

The lab belongs to no project. A run is a `lab_video` job (`job.project_id` is NULL) that makes
one clip on one model, and a `lab_video_run` row that holds what the page lists and compares:
the model, the prompt, the form's parameters and, once the job has finished, the stored file
under `media/lab/`. The job holds the status, the phase, the exact request and the server's
answers, so a run can be resumed after a restart or a pre-emption like a scene's clip.

"Run on both models" makes two runs from one click. They share a `group_key`, the same prompt,
the same first frame, the same size and length, the same recipe and the same seed, so the two
clips differ only by the model. Each run is a paid GPU job of 5 to 10 minutes, so a run starts
only from a click, is never retried by itself beyond what a scene's clip is, and is never
merged into an earlier one (`dedupe=False`).

This module builds and checks the requests and reads the runs. It never calls the GPU server:
`jobs/generate_lab_video.py` does that.
"""

from __future__ import annotations

import logging
import math
import secrets
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Asset, Job, LabImage, LabVideoRun, LabVoiceRun, Voice
from app.jobs import store
from app.providers import contract_guard, video_generator
from app.services import api_contract, frame_counts, projects, video_models
from app.services import lab_prompt_writer as prompt_writer
from app.services.scene_inputs import ClipMode
from app.services.video_models import VideoModel

_logger = logging.getLogger(__name__)

RUN_JOB: Final = "lab_video"
PROMPT_JOB: Final = "write_lab_video_prompt"
PARTITION_KEY: Final = "gpu_partition"

Mode = Literal["quality", "fast"]
Orientation = Literal["landscape", "portrait"]
FrameSource = Literal["lab", "asset"]
# The speech a lip-synced clip matches: a Voice lab run, or a saved voice's recording.
AudioSource = Literal["voice_run", "voice"]

MAX_PROMPT_CHARS: Final = 8000
NEGATIVE_PROMPT_MAX_CHARS: Final = 2000
# What the server's guide says the model handles (an automatic length is clamped to 1 to 20 s).
DURATION_MIN_S: Final = 1.0
DURATION_MAX_S: Final = 20.0
# What `lip_sync: true` forces the server's own frame rate to (ANALYSIS.md / the server's
# 0.12.0 guide); `create_audio_run` computes the frame count at this rate itself.
LIP_SYNC_FPS: Final = 25
# Seeds are drawn below this, so they fit every signed 32-bit integer field.
SEED_LIMIT: Final = 2**31
MAX_MODELS: Final = 2


class LabVideoInputError(ValueError):
    """Something the form gets wrong. The message is meant for the user (HTTP 422)."""


@dataclass(frozen=True)
class FirstFrameRef:
    """The image a run starts or ends on: an upload or a result in the lab, or a project's frame."""

    source: FrameSource
    id: int


@dataclass(frozen=True)
class LabVideoForm:
    prompt: str
    models: Sequence[VideoModel]
    mode: Mode
    orientation: Orientation
    duration_s: float
    seed: int | None
    # LTX-2.3 only. Blank or None sends none, so the pipeline's own default applies.
    negative_prompt: str | None
    first_frame: FirstFrameRef | None
    # Needs a first frame. A run with both frames moves from the first to the last.
    last_frame: FirstFrameRef | None = None


@dataclass(frozen=True)
class AudioRef:
    """The speech a lip-synced clip is made to match."""

    source: AudioSource
    id: int


@dataclass(frozen=True)
class LipSyncForm:
    """A clip of a character speaking a recorded speech (audio-to-video on LTX-2.3 or LTX-2.5).

    The length is not asked for: it follows the speech. The first frame is needed, because it
    is what pins how the speaker looks. `lip_sync` additionally redraws the speaker's mouth to
    match the audio exactly (TBDub, in the same job); when it is on, the clip is made at 25 fps
    regardless of the project's own frame rate, because the server would force that anyway.
    """

    prompt: str
    orientation: Orientation
    seed: int | None
    negative_prompt: str | None
    first_frame: FirstFrameRef
    audio: AudioRef
    video_model: VideoModel = "ltx-2.3"
    lip_sync: bool = False


@dataclass(frozen=True)
class ResolvedAudio:
    """A speech's stored file, as the run needs it."""

    path: str
    mime: str
    duration_s: float


@dataclass(frozen=True)
class RunRow:
    """A run with its job (None only if the job row was deleted)."""

    run: LabVideoRun
    job: Job | None


# --- The form (pure checks) ---------------------------------------------------------------


def validate_form(form: LabVideoForm) -> None:
    """Raises LabVideoInputError for a form no run should be started with."""
    if not form.prompt.strip():
        raise LabVideoInputError("Write a prompt first.")
    if len(form.prompt) > MAX_PROMPT_CHARS:
        raise LabVideoInputError(f"The prompt must be at most {MAX_PROMPT_CHARS:,} characters.")
    if not 1 <= len(form.models) <= MAX_MODELS or len(set(form.models)) != len(form.models):
        raise LabVideoInputError("Choose LTX-2.3, LTX-2.5, or both.")
    for model in form.models:
        if not video_models.is_video_model(model):
            raise LabVideoInputError(f"{model} is not a known video model.")
    # Written so that NaN, which compares false to everything, is rejected too.
    if not DURATION_MIN_S <= form.duration_s <= DURATION_MAX_S:
        raise LabVideoInputError(
            f"The length must be from {DURATION_MIN_S:g} to {DURATION_MAX_S:g} seconds."
        )
    if form.seed is not None and not 0 <= form.seed < SEED_LIMIT:
        raise LabVideoInputError(f"The seed must be from 0 to {SEED_LIMIT - 1}.")
    if form.negative_prompt is not None and len(form.negative_prompt) > NEGATIVE_PROMPT_MAX_CHARS:
        raise LabVideoInputError(
            f"The negative prompt must be at most {NEGATIVE_PROMPT_MAX_CHARS:,} characters."
        )
    if form.last_frame is not None and form.first_frame is None:
        raise LabVideoInputError("A last frame needs a first frame too.")


def validate_lip_sync_form(form: LipSyncForm) -> None:
    """Raises LabVideoInputError for a lip-sync form no run should be started with."""
    if not form.prompt.strip():
        raise LabVideoInputError("Write the video prompt first.")
    if len(form.prompt) > MAX_PROMPT_CHARS:
        raise LabVideoInputError(f"The prompt must be at most {MAX_PROMPT_CHARS:,} characters.")
    if form.video_model not in video_generator.AUDIO_ENDPOINTS:
        raise LabVideoInputError(f"{form.video_model} is not a known video model.")
    if form.seed is not None and not 0 <= form.seed < SEED_LIMIT:
        raise LabVideoInputError(f"The seed must be from 0 to {SEED_LIMIT - 1}.")
    if form.negative_prompt is not None and len(form.negative_prompt) > NEGATIVE_PROMPT_MAX_CHARS:
        raise LabVideoInputError(
            f"The negative prompt must be at most {NEGATIVE_PROMPT_MAX_CHARS:,} characters."
        )


def validate_prompt_draft(idea: str, shots: int, duration_s: float, note: str | None) -> None:
    """Raises LabVideoInputError for a request for a multi-shot prompt that should not be made."""
    if not idea.strip():
        raise LabVideoInputError("Write the idea first.")
    if len(idea) > prompt_writer.IDEA_MAX_CHARS:
        raise LabVideoInputError(
            f"The idea must be at most {prompt_writer.IDEA_MAX_CHARS:,} characters."
        )
    if not prompt_writer.MIN_SHOTS <= shots <= prompt_writer.MAX_SHOTS:
        raise LabVideoInputError(
            f"Ask for {prompt_writer.MIN_SHOTS} to {prompt_writer.MAX_SHOTS} shots."
        )
    if not DURATION_MIN_S <= duration_s <= DURATION_MAX_S:
        raise LabVideoInputError(
            f"The length must be from {DURATION_MIN_S:g} to {DURATION_MAX_S:g} seconds."
        )
    if note is not None and len(note) > prompt_writer.FIRST_FRAME_NOTE_MAX_CHARS:
        raise LabVideoInputError(
            f"The first frame note must be at most "
            f"{prompt_writer.FIRST_FRAME_NOTE_MAX_CHARS:,} characters."
        )


# --- The first and last frame ----------------------------------------------------------------


async def first_frame_path(session: AsyncSession, ref: FirstFrameRef) -> str:
    """The stored path of the first frame, or LabVideoInputError when there is no such image."""
    if ref.source == "lab":
        image = await session.get(LabImage, ref.id)
        if image is None:
            raise LabVideoInputError(f"There is no lab image {ref.id}.")
        return image.path
    asset = await session.get(Asset, ref.id)
    if asset is None or asset.kind != "frame":
        raise LabVideoInputError(f"There is no project frame {ref.id}.")
    return asset.path


# --- The speech of a lip-synced clip -----------------------------------------------------------


async def audio_file(session: AsyncSession, ref: AudioRef) -> ResolvedAudio:
    """The stored file of the speech, or LabVideoInputError when there is none to use.

    A Voice lab run only has a file once its job has finished. A Voice lab speech is a WAV; a
    saved voice keeps the type it was uploaded with.
    """
    if ref.source == "voice_run":
        run = await session.get(LabVoiceRun, ref.id)
        if run is None:
            raise LabVideoInputError(f"There is no Voice lab speech {ref.id}.")
        if run.path is None or run.duration_s is None:
            raise LabVideoInputError(
                f"Voice lab speech {ref.id} is not made yet. Wait for it to finish."
            )
        return ResolvedAudio(path=run.path, mime="audio/wav", duration_s=run.duration_s)
    voice = await session.get(Voice, ref.id)
    if voice is None:
        raise LabVideoInputError(f"There is no saved voice {ref.id}.")
    return ResolvedAudio(path=voice.path, mime=voice.mime, duration_s=voice.duration_s)


# --- Starting runs ---------------------------------------------------------------------------


def _frame_json(ref: FirstFrameRef | None) -> dict[str, Any] | None:
    return None if ref is None else {"source": ref.source, "id": ref.id}


async def create_runs(
    session: AsyncSession, form: LabVideoForm, *, commit: bool = True
) -> list[RunRow]:
    """Checks the form and starts one run per model. Commits, unless `commit` is False: the
    runs and their jobs are then only flushed, so a caller (a take of the Character lab,
    making a silent clip) can link one and commit everything together.

    A run with a last frame is made by the model's first-and-last-frame endpoint, one without
    by its image-to-video (or text-to-video) endpoint.

    Raises LabVideoInputError. Every request is checked against the limits of the approved GPU
    API first (ANALYSIS.md Section 5.3 and 5.8: a wrong request wastes a GPU run), so a model
    the approved API does not have an endpoint for refuses the whole click, and no run starts.
    """
    validate_form(form)
    if form.first_frame is not None:
        await first_frame_path(session, form.first_frame)  # only checks that it exists
    if form.last_frame is not None:
        await first_frame_path(session, form.last_frame)

    sizes = projects.ORIENTATION_DEFAULTS[form.orientation]
    fps = projects.DEFAULT_FPS
    target = round(form.duration_s * fps)
    num_frames = frame_counts.request_num_frames(target)
    seed = form.seed if form.seed is not None else secrets.randbelow(SEED_LIMIT)
    partition = await settings_service.get_str(session, PARTITION_KEY)
    bodies = await contract_guard.latest_bodies(session)
    spec = next((body for body in bodies if api_contract.is_openapi(body)), None)

    negative_prompt = (form.negative_prompt or "").strip() or None
    group_key = secrets.token_hex(8)
    frame_json = _frame_json(form.first_frame)
    last_frame_json = _frame_json(form.last_frame)
    clip_mode: ClipMode = "first_and_last" if form.last_frame is not None else "first_frame"

    # Every request is built and checked before any row is written.
    planned: list[tuple[VideoModel, str, dict[str, Any], dict[str, Any]]] = []
    for model in form.models:
        endpoint = video_generator.endpoint_for(model, clip_mode).endpoint
        try:
            if spec is None:
                raise ValueError(video_generator.no_endpoint_message(endpoint))
            video_generator.check_frames(num_frames, video_generator.frame_limits(spec, endpoint))
            video_generator.check_size(sizes.gen_width, sizes.gen_height)
        except ValueError as exc:
            raise LabVideoInputError(f"{video_models.label(model)}: {exc}") from exc
        request = video_generator.build_request(
            endpoint=endpoint,
            prompt=form.prompt.strip(),
            negative_prompt=negative_prompt,
            width=sizes.gen_width,
            height=sizes.gen_height,
            num_frames=num_frames,
            fps=fps,
            seed=seed,
            partition=partition,
            mode=form.mode,
        )
        params: dict[str, Any] = {
            "mode": form.mode,
            "orientation": form.orientation,
            "width": sizes.gen_width,
            "height": sizes.gen_height,
            "fps": fps,
            "duration_s": form.duration_s,
            "num_frames": num_frames,
            "seed": seed,
            # Only a model that has the field gets it, so the page can show what was sent.
            "negative_prompt": request.get("negative_prompt"),
        }
        planned.append((model, endpoint, request, params))

    rows: list[RunRow] = []
    for model, endpoint, request, params in planned:
        run = LabVideoRun(
            group_key=group_key,
            video_model=model,
            endpoint=endpoint,
            prompt=form.prompt.strip(),
            params=params,
            first_frame=frame_json,
            last_frame=last_frame_json,
        )
        session.add(run)
        await session.flush()
        job, _created = await store.create_job(
            session,
            project_id=None,
            type=RUN_JOB,
            provider="gpu",
            input={
                "requested": "lab_video",
                "run_id": run.id,
                "video_model": model,
                "endpoint": endpoint,
                "request": request,
                "first_frame": frame_json,
                "last_frame": last_frame_json,
            },
            commit=False,
            dedupe=False,
        )
        run.job_id = job.id
        rows.append(RunRow(run=run, job=job))
    if commit:
        await session.commit()
    else:
        await session.flush()
    _logger.info(
        "lab video runs started: group=%s models=%s frames=%d",
        group_key,
        ",".join(form.models),
        num_frames,
    )
    return rows


async def create_audio_run(
    session: AsyncSession, form: LipSyncForm, *, commit: bool = True
) -> RunRow:
    """Checks the form and starts one lip-synced clip. Commits, unless `commit` is False: the
    run and its job are then only flushed, so a caller (a take of the Character lab) can link
    them and commit everything together.

    The clip is made by the chosen model's audio-to-video endpoint, in the quality recipe only,
    from the first frame (how the speaker looks) and the speech. Its length follows the speech:
    the frame count is the smallest `8k + 1` that is at least as long, so the speech is never
    cut. When `form.lip_sync` is on, the clip is made at 25 fps instead of the project's own
    frame rate, because the server would force that anyway once lip sync runs; computing it here
    keeps the stored request the one that actually ran. The request is checked against the
    newest recorded GPU API like every other run, so a server that does not have the endpoint
    refuses the run.

    Raises LabVideoInputError.
    """
    validate_lip_sync_form(form)
    await first_frame_path(session, form.first_frame)  # only checks that it exists
    audio = await audio_file(session, form.audio)
    if not audio.duration_s > 0:  # written so that NaN is rejected too
        raise LabVideoInputError("The speech has no length, so no clip can be made to match it.")
    if audio.duration_s > DURATION_MAX_S:
        raise LabVideoInputError(
            f"The speech lasts {audio.duration_s:.1f} seconds and a clip can be at most "
            f"{DURATION_MAX_S:g} seconds. Shorten the dialogue."
        )

    sizes = projects.ORIENTATION_DEFAULTS[form.orientation]
    fps = LIP_SYNC_FPS if form.lip_sync else projects.DEFAULT_FPS
    num_frames = frame_counts.request_num_frames(math.ceil(audio.duration_s * fps))
    seed = form.seed if form.seed is not None else secrets.randbelow(SEED_LIMIT)
    partition = await settings_service.get_str(session, PARTITION_KEY)
    bodies = await contract_guard.latest_bodies(session)
    spec = next((body for body in bodies if api_contract.is_openapi(body)), None)

    model: VideoModel = form.video_model
    endpoint = video_generator.audio_endpoint_for(model)
    try:
        if spec is None:
            raise ValueError(video_generator.no_endpoint_message(endpoint))
        video_generator.check_frames(num_frames, video_generator.frame_limits(spec, endpoint))
        video_generator.check_size(sizes.gen_width, sizes.gen_height)
    except ValueError as exc:
        raise LabVideoInputError(
            f"Lip-sync: {exc} If the GPU server has this endpoint, test the connection in "
            "Settings, so the app reads its current API."
        ) from exc
    request = video_generator.build_request(
        endpoint=endpoint,
        prompt=form.prompt.strip(),
        negative_prompt=(form.negative_prompt or "").strip() or None,
        width=sizes.gen_width,
        height=sizes.gen_height,
        num_frames=num_frames,
        fps=fps,
        seed=seed,
        partition=partition,
    )
    if form.lip_sync:
        # The server would force this anyway; sending it ourselves keeps the stored request
        # the one that actually ran, and lets `jobs/generate_lab_video.py` tell this run apart
        # from a plain audio-to-video one when it reads `remote.lip_sync` back.
        request["lip_sync"] = True
    params: dict[str, Any] = {
        "mode": "quality",
        "orientation": form.orientation,
        "width": sizes.gen_width,
        "height": sizes.gen_height,
        "fps": fps,
        # The clip is as long as the speech, rounded up to the frames the model makes.
        "duration_s": round(num_frames / fps, 3),
        "audio_duration_s": audio.duration_s,
        "num_frames": num_frames,
        "seed": seed,
        "negative_prompt": request.get("negative_prompt"),
        "lip_sync": form.lip_sync,
    }
    frame_json = _frame_json(form.first_frame)
    audio_json = {"source": form.audio.source, "id": form.audio.id}

    run = LabVideoRun(
        group_key=secrets.token_hex(8),
        video_model=model,
        endpoint=endpoint,
        prompt=form.prompt.strip(),
        params=params,
        first_frame=frame_json,
        last_frame=None,
        audio_input=audio_json,
    )
    session.add(run)
    await session.flush()
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=RUN_JOB,
        provider="gpu",
        input={
            "requested": "lab_video",
            "run_id": run.id,
            "video_model": model,
            "endpoint": endpoint,
            "request": request,
            "first_frame": frame_json,
            "last_frame": None,
            # What the job needs of the speech, copied now like a voice's recording is for a
            # speech: a later change to the run changes nothing for this clip.
            "audio": {**audio_json, "path": audio.path, "mime": audio.mime},
        },
        commit=False,
        dedupe=False,
    )
    run.job_id = job.id
    if commit:
        await session.commit()
    else:
        await session.flush()
    _logger.info(
        "lab lip-sync run started: run=%d audio=%s:%d frames=%d",
        run.id,
        form.audio.source,
        form.audio.id,
        num_frames,
    )
    return RunRow(run=run, job=job)


async def create_prompt_draft(
    session: AsyncSession, idea: str, shots: int, duration_s: float, first_frame_note: str | None
) -> Job:
    """Starts the job that writes a multi-shot prompt from an idea. Commits.

    Raises LabVideoInputError. Each call is a paid try of its own, so none is merged into an
    earlier one.
    """
    validate_prompt_draft(idea, shots, duration_s, first_frame_note)
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=PROMPT_JOB,
        provider="llm",
        input={
            "requested": "lab_video_prompt",
            "inputs": prompt_writer.prompt_inputs(idea, shots, duration_s, first_frame_note),
        },
        dedupe=False,
    )
    return job


# --- Reading runs -----------------------------------------------------------------------------


def _rows(result: Any) -> list[RunRow]:
    return [RunRow(run=run, job=job) for run, job in result.all()]


async def list_runs(session: AsyncSession, before_id: int | None, limit: int) -> list[RunRow]:
    """The newest runs first, `limit` of them, those with an id below `before_id` if given."""
    statement = (
        select(LabVideoRun, Job)
        .outerjoin(Job, Job.id == LabVideoRun.job_id)
        .order_by(LabVideoRun.id.desc())
        .limit(limit)
    )
    if before_id is not None:
        statement = statement.where(LabVideoRun.id < before_id)
    return _rows(await session.execute(statement.execution_options(populate_existing=True)))


async def get_runs(session: AsyncSession, run_ids: Collection[int]) -> dict[int, RunRow]:
    """The runs with these ids, keyed by id. An id that is gone is simply missing."""
    if not run_ids:
        return {}
    statement = (
        select(LabVideoRun, Job)
        .outerjoin(Job, Job.id == LabVideoRun.job_id)
        .where(LabVideoRun.id.in_(run_ids))
        .execution_options(populate_existing=True)
    )
    return {row.run.id: row for row in _rows(await session.execute(statement))}


async def get_run(session: AsyncSession, run_id: int) -> RunRow | None:
    statement = (
        select(LabVideoRun, Job)
        .outerjoin(Job, Job.id == LabVideoRun.job_id)
        .where(LabVideoRun.id == run_id)
        .execution_options(populate_existing=True)
    )
    rows = _rows(await session.execute(statement))
    return rows[0] if rows else None
