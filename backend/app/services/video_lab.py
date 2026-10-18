"""The Video lab: try a prompt on LTX-2.3, LTX-2.5 and MiniMax H3, side by side (Phase 19).

MiniMax H3 differs from LTX in its sizes (1344 x 768), its fixed 24 fps, its `17n + 5` frame
grid, its prompt format and the 4 or 8 GPUs the server gives it, so `create_runs` works all of
that out per model. Its reference mode (pictures and optional audio
references, no first frame) is its own form, `H3ReferenceForm`, started by
`create_h3_reference_run`.

The lab belongs to no project. A run is a `lab_video` job (`job.project_id` is NULL) that makes
one clip on one model, and a `lab_video_run` row that holds what the page lists and compares:
the model, the prompt, the form's parameters and, once the job has finished, the stored file
under `media/lab/`. The job holds the status, the phase, the exact request and the server's
answers, so a run can be resumed after a restart or a pre-emption like a scene's clip.

"Run on several models" makes one run per model from one click. They share a `group_key`, the
same prompt, the same first frame, the same length, the same recipe and the same seed, so the
clips differ only by the model (and by what the model forces: H3's size and frame grid). Each
run is a paid GPU job of 5 to 10 minutes or more, so a run starts
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
from app.services.lab_prompt_profiles import profile_for
from app.services.scene_inputs import ClipMode
from app.services.video_models import DEFAULT_MODEL, LabVideoModel, LtxModel

_logger = logging.getLogger(__name__)

RUN_JOB: Final = "lab_video"
PROMPT_JOB: Final = "write_lab_video_prompt"
PARTITION_KEY: Final = "gpu_partition"

Mode = Literal["quality", "fast"]
Orientation = Literal["landscape", "portrait"]
FrameSource = Literal["lab", "asset"]
# The speech a lip-synced clip matches: a Voice lab run, or a saved voice's recording.
AudioSource = Literal["voice_run", "voice"]
# What a picture of a MiniMax H3 reference clip is: one of up to two characters, the scene they
# are in, or anything else (a prop, a style). It only decides how the page writes the prompt's
# skeleton and loads a run back into the form: the server sees pictures, not roles.
ReferenceRole = Literal["character_1", "character_2", "scene", "other"]
# The character a reference clip's audio is the voice of.
VoiceOwner = Literal["character_1", "character_2"]

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
MAX_MODELS: Final = len(video_models.LAB_MODEL_IDS)

# MiniMax H3 is trained at 1344 x 768 and 768 x 1344 whatever the project's own size is; the lab
# sends these sizes explicitly (`video_generator.H3_SIZES`, the same ones a scene's clip uses).
H3_SIZES: Final = video_generator.H3_SIZES
# H3 has no length limit of its own here: the app sends what was asked (within the general
# `DURATION_MIN_S` to `DURATION_MAX_S`) and shows the GPU server's answer, which documents 124 to
# 345 frames (5.17 to 14.4 s) and a 2 to 15 s audio reference. This is for trying out what the
# server really does with a shorter or longer clip or audio.
# Denoising steps: 4 to 100, and the pipeline's own default (50) when none is sent.
H3_STEPS_MIN: Final = 4
H3_STEPS_MAX: Final = 100
# The Video lab's reference form has room for two characters, each with an optional voice, so a
# run has at most two audios (the server takes three).
H3_MAX_AUDIOS: Final = 2
# The ambience text goes into the prompt's `overall_soundscape`, which is a few sentences.
AMBIENCE_MAX_CHARS: Final = 1000


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
    models: Sequence[LabVideoModel]
    # LTX only: MiniMax H3 has one recipe and ignores it.
    mode: Mode
    orientation: Orientation
    duration_s: float
    seed: int | None
    # LTX-2.3 only. Blank or None sends none, so the pipeline's own default applies.
    negative_prompt: str | None
    first_frame: FirstFrameRef | None
    # Needs a first frame. A run with both frames moves from the first to the last.
    last_frame: FirstFrameRef | None = None
    # MiniMax H3 only: 4 to 100 denoising steps. None sends none (the pipeline's own 50).
    num_inference_steps: int | None = None


@dataclass(frozen=True)
class AudioRef:
    """The speech a lip-synced clip is made to match."""

    source: AudioSource
    id: int


@dataclass(frozen=True)
class H3ReferenceForm:
    """A MiniMax H3 reference clip: 1 to 9 pictures and, optionally, up to two audio references,
    no first frame.

    The pictures are `<Picture 1>`, `<Picture 2>`, ... in the prompt, in this order, and the
    audios are `<Audio 1>`, `<Audio 2>`, in this order. An audio is a reference the model reads
    (its voice, its delivery) and then makes its own soundtrack from. It is not muxed in, unlike
    a lip-synced LTX clip. There may be none: the clip then has the model's own sound. The
    pictures do not set the clip's shape, so `orientation` does.

    `reference_roles` (one for each picture), `audio_owners` (one for each audio) and `ambience`
    are what the Video lab's form knew when it wrote the prompt. They change nothing that is
    sent: they are kept on the run so it loads back into the form. Empty (a Character lab take)
    means "not given": every picture is `other`, and the audios have no owner.
    """

    prompt: str
    orientation: Orientation
    seed: int | None
    references: Sequence[FirstFrameRef]
    audios: Sequence[AudioRef]
    # True: the clip is as long as the first audio (so it needs one). False: it lasts `duration_s`.
    match_audio_duration: bool
    duration_s: float | None = None
    num_inference_steps: int | None = None
    reference_roles: Sequence[ReferenceRole] = ()
    audio_owners: Sequence[VoiceOwner] = ()
    ambience: str | None = None


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
    video_model: LtxModel = "ltx-2.3"
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


def _check_duration(duration_s: float) -> None:
    """Raises LabVideoInputError for a clip length outside the general range."""
    # Written so that NaN, which compares false to everything, is rejected too.
    if not DURATION_MIN_S <= duration_s <= DURATION_MAX_S:
        raise LabVideoInputError(
            f"The length must be from {DURATION_MIN_S:g} to {DURATION_MAX_S:g} seconds."
        )


def _check_h3_steps(steps: int | None) -> None:
    """Raises LabVideoInputError for a number of denoising steps H3 does not take."""
    if steps is not None and not H3_STEPS_MIN <= steps <= H3_STEPS_MAX:
        raise LabVideoInputError(
            f"MiniMax H3: the steps must be from {H3_STEPS_MIN} to {H3_STEPS_MAX}."
        )


def validate_form(form: LabVideoForm) -> None:
    """Raises LabVideoInputError for a form no run should be started with."""
    if not form.prompt.strip():
        raise LabVideoInputError("Write a prompt first.")
    if len(form.prompt) > MAX_PROMPT_CHARS:
        raise LabVideoInputError(f"The prompt must be at most {MAX_PROMPT_CHARS:,} characters.")
    if not 1 <= len(form.models) <= MAX_MODELS or len(set(form.models)) != len(form.models):
        raise LabVideoInputError("Choose one or more models, each at most once.")
    for model in form.models:
        if not video_models.is_lab_video_model(model):
            raise LabVideoInputError(f"{model} is not a known video model.")
    _check_duration(form.duration_s)
    _check_h3_steps(form.num_inference_steps)
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
        raise LabVideoInputError(
            f"{video_models.label(form.video_model)} cannot make a clip from a recorded speech."
        )
    if form.seed is not None and not 0 <= form.seed < SEED_LIMIT:
        raise LabVideoInputError(f"The seed must be from 0 to {SEED_LIMIT - 1}.")
    if form.negative_prompt is not None and len(form.negative_prompt) > NEGATIVE_PROMPT_MAX_CHARS:
        raise LabVideoInputError(
            f"The negative prompt must be at most {NEGATIVE_PROMPT_MAX_CHARS:,} characters."
        )


def validate_h3_reference_form(form: H3ReferenceForm) -> None:
    """Raises LabVideoInputError for a reference form no run should be started with."""
    if not form.prompt.strip():
        raise LabVideoInputError("Write the video prompt first.")
    if len(form.prompt) > MAX_PROMPT_CHARS:
        raise LabVideoInputError(f"The prompt must be at most {MAX_PROMPT_CHARS:,} characters.")
    if not 1 <= len(form.references) <= video_generator.H3_MAX_REFERENCE_IMAGES:
        raise LabVideoInputError(
            f"Choose 1 to {video_generator.H3_MAX_REFERENCE_IMAGES} reference pictures."
        )
    _check_h3_cast(form)
    if form.match_audio_duration:
        if not form.audios:
            raise LabVideoInputError(
                "Add a voice for the clip to match, or choose a length instead."
            )
    else:
        if form.duration_s is None:
            raise LabVideoInputError("Choose a length, or let the clip match the audio.")
        _check_duration(form.duration_s)
    _check_h3_steps(form.num_inference_steps)
    if form.seed is not None and not 0 <= form.seed < SEED_LIMIT:
        raise LabVideoInputError(f"The seed must be from 0 to {SEED_LIMIT - 1}.")


def _check_h3_cast(form: H3ReferenceForm) -> None:
    """Raises LabVideoInputError for audios, picture roles or an ambience a reference clip
    cannot have.
    """
    if len(form.audios) > H3_MAX_AUDIOS:
        raise LabVideoInputError(f"Add at most {H3_MAX_AUDIOS} voices.")
    if form.ambience is not None and len(form.ambience) > AMBIENCE_MAX_CHARS:
        raise LabVideoInputError(f"The ambience must be at most {AMBIENCE_MAX_CHARS:,} characters.")

    roles = form.reference_roles
    if roles and len(roles) != len(form.references):
        raise LabVideoInputError("Each reference picture needs a role.")
    names = {"character_1": "Character 1", "character_2": "Character 2", "scene": "the scene"}
    for role, name in names.items():
        if list(roles).count(role) > 1:
            raise LabVideoInputError(f"Only one picture can be {name}.")

    owners = form.audio_owners
    if owners and len(owners) != len(form.audios):
        raise LabVideoInputError("Each voice must say which character it belongs to.")
    if len(set(owners)) != len(owners):
        raise LabVideoInputError("Each character can have only one voice.")
    if roles:
        for owner in owners:
            if owner not in roles:
                name = "Character 1" if owner == "character_1" else "Character 2"
                raise LabVideoInputError(f"{name} has a voice but no picture. Add its picture.")


def validate_prompt_draft(
    idea: str,
    shots: int,
    duration_s: float,
    note: str | None,
    target_model: LabVideoModel = DEFAULT_MODEL,
) -> None:
    """Raises LabVideoInputError for a request for a multi-shot prompt that should not be made.
    The number of shots and the length depend on the model the prompt is for: MiniMax H3 takes 1
    to 4 shots, LTX 2 to 4 shots; both take 1 to 20 seconds.
    """
    profile = profile_for(target_model)
    if not idea.strip():
        raise LabVideoInputError("Write the idea first.")
    if len(idea) > prompt_writer.IDEA_MAX_CHARS:
        raise LabVideoInputError(
            f"The idea must be at most {prompt_writer.IDEA_MAX_CHARS:,} characters."
        )
    if not profile.min_shots <= shots <= profile.max_shots:
        raise LabVideoInputError(f"Ask for {profile.min_shots} to {profile.max_shots} shots.")
    _check_duration(duration_s)
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
    by its image-to-video (or text-to-video) endpoint. Size, frame rate and frame count are
    worked out per model: an LTX run uses the orientation's size, 24 fps and the next `8k + 1`
    frames; a MiniMax H3 run uses 1344 x 768 (or 768 x 1344), a fixed 24 fps and the next
    `17n + 5` frames, and its prompt gets the first line that places the frames
    (`video_generator.h3_prompt_prefix`). The run keeps the prompt as typed; the request holds
    the prompt that is sent.

    Raises LabVideoInputError. Every request is checked against the limits of the newest
    recorded GPU API first (a wrong request wastes a GPU run), so a model the API does not have
    an endpoint for refuses the whole click, and no run starts.
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
    planned: list[tuple[LabVideoModel, str, dict[str, Any], dict[str, Any]]] = []
    prompt = form.prompt.strip()
    for model in form.models:
        is_h3 = model == video_models.H3_MODEL
        try:
            endpoint = video_generator.lab_endpoint_for(model, clip_mode)
            if is_h3:
                width, height = H3_SIZES[form.orientation]
                run_fps = frame_counts.H3_FPS
                run_frames = frame_counts.h3_num_frames(round(form.duration_s * run_fps))
            else:
                width, height = sizes.gen_width, sizes.gen_height
                run_fps, run_frames = fps, num_frames
            if spec is None:
                raise ValueError(video_generator.no_endpoint_message(endpoint))
            limits = video_generator.frame_limits(spec, endpoint)  # also checks the endpoint exists
            if not is_h3:
                # H3's frame range is left to the GPU server, so its real answer shows.
                video_generator.check_frames(run_frames, limits)
            video_generator.check_size(width, height)
        except ValueError as exc:
            raise LabVideoInputError(f"{video_models.label(model)}: {exc}") from exc

        sent_prompt = prompt
        if is_h3:
            prefix = video_generator.h3_prompt_prefix(
                run_frames, form.first_frame is not None, form.last_frame is not None, prompt
            )
            if prefix:
                sent_prompt = f"{prefix}\n\n{prompt}"
        request = video_generator.build_request(
            endpoint=endpoint,
            prompt=sent_prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            num_frames=run_frames,
            fps=run_fps,
            seed=seed,
            partition=partition,
            mode=form.mode,
            num_inference_steps=form.num_inference_steps if is_h3 else None,
        )
        params: dict[str, Any] = {
            # MiniMax H3 has one recipe, so the form's recipe is not recorded for it.
            "mode": None if is_h3 else form.mode,
            "orientation": form.orientation,
            "width": width,
            "height": height,
            "fps": run_fps,
            "duration_s": form.duration_s,
            "num_frames": run_frames,
            "seed": seed,
            # Only a model that has the field gets it, so the page can show what was sent.
            "negative_prompt": request.get("negative_prompt"),
        }
        if is_h3:
            params["num_inference_steps"] = form.num_inference_steps
        planned.append((model, endpoint, request, params))

    rows: list[RunRow] = []
    for model, endpoint, request, params in planned:
        run = LabVideoRun(
            group_key=group_key,
            video_model=model,
            endpoint=endpoint,
            prompt=prompt,
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
        "lab video runs started: group=%s models=%s frames=%s",
        group_key,
        ",".join(form.models),
        ",".join(str(params["num_frames"]) for _model, _endpoint, _request, params in planned),
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

    model: LtxModel = form.video_model
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


async def create_h3_reference_run(
    session: AsyncSession, form: H3ReferenceForm, *, commit: bool = True
) -> RunRow:
    """Checks the form and starts one MiniMax H3 reference clip. Commits, unless `commit` is
    False: the run and its job are then only flushed, so a caller can link them and commit
    everything together.

    The clip is made by `/v1/h3/videos/audio-to-video` from the pictures (`<Picture n>`, in the
    order given) and the audio references, if any (`<Audio n>`, in the order given). An audio can
    be any length above 0: the GPU server documents 2 to 15 s, and what it does with another
    length is shown on the run. The pictures do not set the clip's shape, so the size is the
    orientation's (1344 x 768 or 768 x 1344). The prompt is sent exactly as written: the
    six-part reference format has no first line for the code to add.

    With `match_audio_duration` the request says so and sends no `num_frames` (the two exclude
    each other on the server), so the server decides the clip's length from the first audio (it
    documents 124 to 345 frames). Otherwise the frame count is the smallest `17n + 5` at least
    as long as `duration_s`, and the server's frame range is not checked here.

    Raises LabVideoInputError.
    """
    validate_h3_reference_form(form)
    for reference in form.references:
        await first_frame_path(session, reference)  # only checks that it exists
    audios = [await audio_file(session, ref) for ref in form.audios]
    for number, audio in enumerate(audios, start=1):
        if not audio.duration_s > 0:  # written so that NaN is rejected too
            raise LabVideoInputError(f"Voice {number} has no length.")

    width, height = H3_SIZES[form.orientation]
    fps = frame_counts.H3_FPS
    if form.duration_s is not None and not form.match_audio_duration:
        seconds = form.duration_s
        target = round(seconds * fps)
    else:
        # `validate_h3_reference_form` guarantees a first audio when the clip matches the audio.
        seconds = audios[0].duration_s
        target = math.ceil(seconds * fps)  # rounded up, so the audio is never cut
    num_frames = frame_counts.h3_num_frames(target)
    seed = form.seed if form.seed is not None else secrets.randbelow(SEED_LIMIT)
    partition = await settings_service.get_str(session, PARTITION_KEY)
    bodies = await contract_guard.latest_bodies(session)
    spec = next((body for body in bodies if api_contract.is_openapi(body)), None)

    endpoint = video_generator.H3_AUDIO_TO_VIDEO_PATH
    try:
        if spec is None:
            raise ValueError(video_generator.no_endpoint_message(endpoint))
        video_generator.frame_limits(spec, endpoint)  # only checks the endpoint exists
        video_generator.check_size(width, height)
    except ValueError as exc:
        raise LabVideoInputError(
            f"{video_models.label(video_models.H3_MODEL)}: {exc} If the GPU server has this "
            "endpoint, test the connection in Settings, so the app reads its current API."
        ) from exc
    request = video_generator.build_request(
        endpoint=endpoint,
        prompt=form.prompt.strip(),
        negative_prompt=None,
        width=width,
        height=height,
        num_frames=num_frames,
        fps=fps,
        seed=seed,
        partition=partition,
        num_inference_steps=form.num_inference_steps,
    )
    if form.match_audio_duration:
        # The server refuses both: the clip's length is the audio's.
        del request["num_frames"]
        request["match_audio_duration"] = True

    params: dict[str, Any] = {
        "mode": None,
        "orientation": form.orientation,
        "width": width,
        "height": height,
        "fps": fps,
        # What the clip should last. With `match_audio_duration` the server rounds it onto its
        # frame grid, so the real length is on the finished run.
        "duration_s": round(seconds, 3),
        "num_frames": None if form.match_audio_duration else num_frames,
        "seed": seed,
        "negative_prompt": None,
        "num_inference_steps": form.num_inference_steps,
        "match_audio_duration": form.match_audio_duration,
        # The first audio's length (the older runs' only one), and the length of each audio.
        "audio_duration_s": audios[0].duration_s if audios else None,
        "audio_durations_s": [audio.duration_s for audio in audios],
        # What the form knew when it wrote the prompt, so the run loads back into it. Written in
        # full: a form that gave no roles has every picture as `other`.
        "reference_roles": list(form.reference_roles) or ["other"] * len(form.references),
        "audio_owners": list(form.audio_owners),
        "ambience": (form.ambience or "").strip() or None,
    }
    reference_json = [{"source": ref.source, "id": ref.id} for ref in form.references]
    audio_jsons = [{"source": ref.source, "id": ref.id} for ref in form.audios]

    run = LabVideoRun(
        group_key=secrets.token_hex(8),
        video_model=video_models.H3_MODEL,
        endpoint=endpoint,
        prompt=form.prompt.strip(),
        params=params,
        first_frame=None,
        last_frame=None,
        # The first audio, or NULL: what the page reads for a lip-synced clip's one speech.
        audio_input=audio_jsons[0] if audio_jsons else None,
        references=reference_json,
        audio_references=audio_jsons or None,
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
            "video_model": video_models.H3_MODEL,
            "endpoint": endpoint,
            "request": request,
            "first_frame": None,
            "last_frame": None,
            # Uploaded in this order: the order is what `<Picture n>` means in the prompt.
            "references": reference_json,
            # What the job needs of each audio (none is allowed), in the order of `<Audio n>`,
            # copied now like a voice's recording is for a speech: a later change to the run
            # changes nothing for this clip.
            "audios": [
                {**audio_json, "path": audio.path, "mime": audio.mime}
                for audio_json, audio in zip(audio_jsons, audios, strict=True)
            ],
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
        "lab H3 reference run started: run=%d audios=%d pictures=%d match_audio=%s",
        run.id,
        len(audios),
        len(form.references),
        form.match_audio_duration,
    )
    return RunRow(run=run, job=job)


async def create_prompt_draft(
    session: AsyncSession,
    idea: str,
    shots: int,
    duration_s: float,
    first_frame_note: str | None,
    target_model: LabVideoModel = DEFAULT_MODEL,
) -> Job:
    """Starts the job that writes a multi-shot prompt from an idea, in the format of
    `target_model` (MiniMax H3's structured prompt, or LTX-2.5's one paragraph). Commits.

    Raises LabVideoInputError. Each call is a paid try of its own, so none is merged into an
    earlier one.
    """
    validate_prompt_draft(idea, shots, duration_s, first_frame_note, target_model)
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=PROMPT_JOB,
        provider="llm",
        input={
            "requested": "lab_video_prompt",
            "inputs": prompt_writer.prompt_inputs(
                idea, shots, duration_s, first_frame_note, target_model
            ),
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
