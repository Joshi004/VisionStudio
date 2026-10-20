"""The Image lab: manual tests of two image models (Phase 13 and 22).

The lab is for trying a model by hand and comparing what comes back, so it is built to show the
model as it is: the request goes out as the form describes it, and the answer comes back as it
was, including an answer that ignored a setting or a call that was refused.

**Seedream (Bitdeer's image API).** A run is one synchronous call, not a `job`: the lab belongs
to no project, and `job` needs one. It is a paid call, so it only starts from a click
(`POST /api/lab/images/runs`), is never retried and never cached. At most 2 run at once.

`start_run` does the whole run in a task of its own, and the request only waits for it. If
the browser goes away while the call is in flight, the call still finishes and its images and
record are kept: a paid answer is never thrown away.

**Qwen-Image-2.1 (the GPU server).** A run takes minutes, so it is a `lab_image` job
(`job.project_id` is NULL) and a `lab_run` row that is `running` until the job ends
(`create_qwen_run`; `jobs/generate_lab_image.py` does the rest). The row's `status` is what the
job last said: a job that failed or was cancelled leaves the row `running`, so the page reads
the job as well (`api/image_lab.py`). Text to image only: the edit endpoint is not used.

The pure parts (`validate_form`, `build_generation_body`, `build_edit_fields`,
`validate_qwen_form`) hold no I/O. Everything that touches the database opens its own session,
because a Seedream task outlives the request.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import secrets
from collections.abc import AsyncIterable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

import anyio.to_thread
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Asset, Job, LabImage, LabRun
from app.db.session import SessionLocal
from app.jobs import store
from app.providers import contract_guard, image_api, image_generator
from app.services import api_contract, frame_images, image_models
from app.services.frame_images import FrameRejected
from app.services.storage import StorageError, TooLargeError, get_storage

_logger = logging.getLogger(__name__)

Mode = Literal["text_to_image", "image_to_image", "edit"]
RefSource = Literal["lab", "asset"]

# The address is the language model's one: the same Bitdeer key and host (Settings, "LLM URL").
BASE_URL_KEY: Final = "llm_base_url"

DEFAULT_MODEL: Final = "seedream-5.0-lite"
MAX_REFERENCES: Final = 14
MAX_PROMPT_CHARS: Final = 8000
MAX_EXTRA_CHARS: Final = 20_000
MAX_CONCURRENT_CALLS: Final = 2
# Bitdeer's price for one generated image (the figure on your screenshot of the model list).
PRICE_PER_IMAGE_USD: Final = 0.035

# What the "extra JSON" box may not change: the things the form itself is about.
_PROTECTED_EXTRA_KEYS: Final = frozenset({"model", "prompt", "image"})
_MODEL = re.compile(r"[A-Za-z0-9._/:-]{1,200}")
_SIZE = re.compile(r"[0-9]{1,5}x[0-9]{1,5}|[0-9](?:\.[0-9])?[Kk]")

_CALL_SLOTS = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
# A strong reference to each running task, so it is not collected while it works.
_TASKS: set[asyncio.Task[int]] = set()


class LabInputError(ValueError):
    """Something the form or a reference gets wrong. The message is meant for the user (422)."""


@dataclass(frozen=True)
class Ref:
    source: RefSource
    id: int


@dataclass(frozen=True)
class LabForm:
    mode: Mode
    model: str
    prompt: str
    size: str
    # True or False is sent as it is. None sends nothing, to see the API's own default.
    watermark: bool | None
    seed: int | None
    # With a number, `sequential_image_generation: "auto"` is sent with that maximum.
    sequential_max_images: int | None
    # How the `image` field goes out on /images/generations: a list, or a single string.
    image_field_as: Literal["list", "string"]
    # The name of the file field on /images/edits.
    edit_field_name: Literal["image", "image[]"]
    extra: dict[str, Any]
    references: list[Ref]


@dataclass(frozen=True)
class LoadedReference:
    ref: Ref
    jpeg: bytes


# --- The form: checks and request builders (pure) ------------------------------------------


def validate_form(form: LabForm) -> None:
    """Raises LabInputError for a form the call should not be made with."""
    if not form.prompt.strip():
        raise LabInputError("Write a prompt first.")
    if len(form.prompt) > MAX_PROMPT_CHARS:
        raise LabInputError(f"The prompt must be at most {MAX_PROMPT_CHARS:,} characters.")
    if not _MODEL.fullmatch(form.model):
        raise LabInputError("The model name may hold letters, numbers and . _ / : - only.")
    if not _SIZE.fullmatch(form.size):
        raise LabInputError('The size must look like "1632x2880" or "2K".')
    if form.seed is not None and not -1 <= form.seed <= 2_147_483_647:
        raise LabInputError("The seed must be from -1 to 2147483647.")
    if form.sequential_max_images is not None and not 1 <= form.sequential_max_images <= 15:
        raise LabInputError("An image set holds 1 to 15 images.")

    count = len(form.references)
    if form.mode == "text_to_image" and count:
        raise LabInputError(
            "Text to image takes no reference images. Remove them, or change the mode."
        )
    if form.mode != "text_to_image" and count == 0:
        raise LabInputError("Add at least one reference image for this mode.")
    if count > MAX_REFERENCES:
        raise LabInputError(f"At most {MAX_REFERENCES} reference images.")
    if form.mode == "image_to_image" and form.image_field_as == "string" and count != 1:
        raise LabInputError("Sending the image field as a string takes exactly one reference.")

    blocked = sorted(_PROTECTED_EXTRA_KEYS & form.extra.keys())
    if blocked:
        raise LabInputError(
            f"The extra JSON cannot hold {', '.join(blocked)}: the form sets those."
        )
    if len(json.dumps(form.extra)) > MAX_EXTRA_CHARS:
        raise LabInputError(f"The extra JSON must be at most {MAX_EXTRA_CHARS:,} characters.")


def data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def build_generation_body(form: LabForm, image_data_urls: Sequence[str]) -> dict[str, Any]:
    """The JSON body for `/images/generations`. `image_data_urls` is used in image to image
    mode only.
    """
    body: dict[str, Any] = {
        "model": form.model,
        "prompt": form.prompt,
        "size": form.size,
        "response_format": "b64_json",
    }
    if form.watermark is not None:
        body["watermark"] = form.watermark
    if form.seed is not None:
        body["seed"] = form.seed
    if form.sequential_max_images is not None:
        body["sequential_image_generation"] = "auto"
        body["sequential_image_generation_options"] = {"max_images": form.sequential_max_images}
    if form.mode == "image_to_image" and image_data_urls:
        as_string = form.image_field_as == "string" and len(image_data_urls) == 1
        body["image"] = image_data_urls[0] if as_string else list(image_data_urls)
    body.update(form.extra)
    return body


def build_edit_fields(form: LabForm) -> dict[str, str]:
    """The text fields of the form for `/images/edits`. Every value is a string, as a form
    sends it: a number or a flag is written out, and a list or an object is JSON.
    """
    fields: dict[str, str] = {
        "model": form.model,
        "prompt": form.prompt,
        "size": form.size,
        "response_format": "b64_json",
    }
    if form.watermark is not None:
        fields["watermark"] = "true" if form.watermark else "false"
    if form.seed is not None:
        fields["seed"] = str(form.seed)
    if form.sequential_max_images is not None:
        fields["sequential_image_generation"] = "auto"
        fields["sequential_image_generation_options"] = json.dumps(
            {"max_images": form.sequential_max_images}
        )
    for key, value in form.extra.items():
        fields[key] = value if isinstance(value, str) else json.dumps(value)
    return fields


def build_edit_files(
    form: LabForm, references: Sequence[LoadedReference]
) -> list[tuple[str, str, bytes, str]]:
    """The reference images as file parts, one per reference, all in the same field."""
    return [
        (form.edit_field_name, f"reference{number}.jpg", loaded.jpeg, "image/jpeg")
        for number, loaded in enumerate(references, start=1)
    ]


def estimate_cost(usage: dict[str, Any] | None) -> float | None:
    """The cost of a run from the usage block, or None when it does not say how many images."""
    count = usage.get("generated_images") if isinstance(usage, dict) else None
    if isinstance(count, bool) or not isinstance(count, int):
        return None
    return round(count * PRICE_PER_IMAGE_USD, 4)


# --- References ---------------------------------------------------------------------------


async def _reference_path(session: AsyncSession, number: int, ref: Ref) -> str:
    """The stored path of a reference, or LabInputError when there is no such image."""
    if ref.source == "lab":
        image = await session.get(LabImage, ref.id)
        if image is None:
            raise LabInputError(f"Reference {number}: there is no lab image {ref.id}.")
        return image.path
    asset = await session.get(Asset, ref.id)
    if asset is None or asset.kind != "frame":
        raise LabInputError(f"Reference {number}: there is no project frame {ref.id}.")
    return asset.path


async def load_references(references: Sequence[Ref]) -> list[LoadedReference]:
    """Reads each reference and makes it the JPEG that is sent. Raises LabInputError."""
    async with SessionLocal() as session:
        paths = [
            await _reference_path(session, number, ref)
            for number, ref in enumerate(references, start=1)
        ]
        await session.commit()  # end the read: no transaction stays open during the call

    storage = get_storage()
    loaded: list[LoadedReference] = []
    for number, (ref, relative_path) in enumerate(zip(references, paths, strict=True), start=1):
        try:
            jpeg = await frame_images.run_pillow(
                frame_images.render_reference_jpeg, storage.get_path(relative_path)
            )
        except (OSError, StorageError, Image.DecompressionBombError):
            raise LabInputError(
                f"Reference {number} could not be read. The file may be missing or damaged."
            ) from None
        loaded.append(LoadedReference(ref=ref, jpeg=jpeg))
    return loaded


# --- Running ------------------------------------------------------------------------------


async def start_run(form: LabForm) -> int:
    """Checks the form, makes the call and saves the run. Returns the run's id.

    The work runs in a task of its own that this function waits for. If the caller is
    cancelled (the browser closed the page), the task goes on to the end and saves the run.
    Raises LabInputError.
    """
    validate_form(form)
    task = asyncio.create_task(_execute(form))
    _TASKS.add(task)
    task.add_done_callback(_finished)
    return await asyncio.shield(task)


def _finished(task: asyncio.Task[int]) -> None:
    _TASKS.discard(task)
    if task.cancelled():
        _logger.warning("a lab run was cancelled before it finished")
    elif (exc := task.exception()) is not None and not isinstance(exc, LabInputError):
        _logger.error("a lab run failed", exc_info=exc)


async def _execute(form: LabForm) -> int:
    async with SessionLocal() as session:
        base_url = await settings_service.get_str(session, BASE_URL_KEY)
        await session.commit()
    references = await load_references(form.references)

    if form.mode == "edit":
        endpoint = image_api.EDITS_PATH
        fields = build_edit_fields(form)
        files = build_edit_files(form, references)
        request_record: dict[str, Any] = {
            "method": "POST",
            "path": endpoint,
            "form": fields,
            "files": [
                {"field": name, "filename": filename, "mime": mime, "bytes": len(content)}
                for name, filename, content, mime in files
            ],
        }
        request_bytes = sum(len(k) + len(v) for k, v in fields.items()) + sum(
            len(content) for _name, _filename, content, _mime in files
        )
        async with _CALL_SLOTS:
            result = await image_api.edit(base_url, fields, files)
    else:
        endpoint = image_api.GENERATIONS_PATH
        body = build_generation_body(form, [data_url(loaded.jpeg) for loaded in references])
        request_record = {"method": "POST", "path": endpoint, "body": image_api.sanitise(body)}
        request_bytes = len(json.dumps(body))
        async with _CALL_SLOTS:
            result = await image_api.generate(base_url, body)

    return await _save_run(form, endpoint, request_record, request_bytes, result)


@dataclass(frozen=True)
class _SavedImage:
    relative_path: str
    mime: str
    width: int
    height: int
    size_bytes: int
    sha256: str


def _write_new(path: Any, data: bytes) -> None:
    with path.open("xb") as file:
        file.write(data)


async def _store_result(data: bytes) -> _SavedImage:
    """Checks a returned image and moves it into `media/lab/`, exactly as it came. Raises
    FrameRejected.
    """
    storage = get_storage()
    path = storage.new_temp_path("img")
    await anyio.to_thread.run_sync(_write_new, path, data)
    try:
        temp = await storage.describe_temp(path)
        info = await frame_images.run_pillow(frame_images.inspect_image, temp.path)
        stored = await storage.save_lab(temp, info.ext)
    except BaseException:
        storage.discard(path)
        raise
    return _SavedImage(
        relative_path=stored.relative_path,
        mime=info.mime,
        width=info.width,
        height=info.height,
        size_bytes=temp.size_bytes,
        sha256=temp.sha256,
    )


async def _save_run(
    form: LabForm,
    endpoint: str,
    request_record: dict[str, Any],
    request_bytes: int,
    result: image_api.ImageCallResult,
) -> int:
    saved: list[_SavedImage] = []
    error = result.error
    for number, data in enumerate(result.images, start=1):
        try:
            saved.append(await _store_result(data))
        except FrameRejected as exc:
            note = f"Result image {number} could not be used: {exc.message}"
            error = f"{error} {note}" if error else note

    async with SessionLocal() as session:
        run = LabRun(
            mode=form.mode,
            endpoint=endpoint,
            model=form.model,
            prompt=form.prompt,
            params={
                "size": form.size,
                "watermark": form.watermark,
                "seed": form.seed,
                "sequential_max_images": form.sequential_max_images,
                "image_field_as": form.image_field_as,
                "edit_field_name": form.edit_field_name,
                "extra": form.extra,
            },
            reference_images=[{"source": ref.source, "id": ref.id} for ref in form.references],
            status="succeeded" if error is None and saved else "failed",
            http_status=result.http_status,
            error=error,
            seconds=round(result.seconds, 1),
            request_bytes=request_bytes,
            usage=result.usage,
            request=request_record,
            response=result.response,
        )
        try:
            session.add(run)
            await session.flush()
            for index, image in enumerate(saved):
                session.add(
                    LabImage(
                        origin="result",
                        run_id=run.id,
                        output_index=index,
                        path=image.relative_path,
                        mime=image.mime,
                        width=image.width,
                        height=image.height,
                        size_bytes=image.size_bytes,
                        sha256=image.sha256,
                    )
                )
            await session.commit()
        except BaseException:
            # Stored files are never deleted, so this leaves unreferenced files behind.
            _logger.warning(
                "lab images stored but not recorded: %s", [image.relative_path for image in saved]
            )
            raise
    _logger.info(
        "lab run %d: mode=%s model=%s %s http=%s images=%d %.1f s usage=%s",
        run.id,
        form.mode,
        form.model,
        run.status,
        result.http_status,
        len(saved),
        result.seconds,
        result.usage,
    )
    return run.id


# --- Qwen-Image-2.1 on the GPU server -----------------------------------------------------------

RUN_JOB: Final = "lab_image"
PARTITION_KEY: Final = "gpu_partition"


@dataclass(frozen=True)
class QwenLabForm:
    prompt: str
    mode: image_models.ImageMode
    aspect_ratio: str
    # Left out: a random seed.
    seed: int | None
    # The number of denoising steps. Left out: the server's own (40 in quality mode). Quality
    # mode only: fast mode always runs its own 8.
    steps: int | None


def validate_qwen_form(form: QwenLabForm) -> None:
    """Raises LabInputError for a form no Qwen run should be started with."""
    if not form.prompt.strip():
        raise LabInputError("Write a prompt first.")
    if len(form.prompt) > image_generator.MAX_PROMPT_CHARS:
        raise LabInputError(
            f"The prompt must be at most {image_generator.MAX_PROMPT_CHARS:,} characters."
        )
    if not image_models.is_image_mode(form.mode):
        raise LabInputError("Choose quality or fast.")
    if form.aspect_ratio not in image_models.ASPECT_RATIOS:
        raise LabInputError(f"Choose one of the shapes: {', '.join(image_models.ASPECT_RATIOS)}.")
    if form.seed is not None and not 0 <= form.seed < image_models.SEED_LIMIT:
        raise LabInputError(f"The seed must be from 0 to {image_models.SEED_LIMIT - 1}.")
    if form.steps is not None:
        if form.mode != "quality":
            raise LabInputError("The number of steps can only be set in quality mode.")
        if not image_generator.MIN_STEPS <= form.steps <= image_generator.MAX_STEPS:
            raise LabInputError(
                f"The number of steps must be from {image_generator.MIN_STEPS} to "
                f"{image_generator.MAX_STEPS}."
            )


async def create_qwen_run(
    session: AsyncSession, form: QwenLabForm, *, commit: bool = True
) -> tuple[LabRun, Job]:
    """Checks the form and starts one run on the GPU server. Commits, unless `commit` is False:
    the run and its job are then only flushed, so a caller (the Character lab, making several
    candidates at once) can link them and commit everything together. Raises LabInputError.

    The request is built and checked against the approved GPU API first (a request for an
    endpoint the API has not been approved with would only wait), so a bad form starts nothing.
    The run is a `lab_image` job of its own, never merged into an earlier one: each click is a
    GPU run, and trying a prompt again with another seed is what the lab is for.
    """
    validate_qwen_form(form)
    seed = form.seed if form.seed is not None else secrets.randbelow(image_models.SEED_LIMIT)
    partition = await settings_service.get_str(session, PARTITION_KEY)
    bodies = await contract_guard.latest_bodies(session)
    spec = next((body for body in bodies if api_contract.is_openapi(body)), None)
    prompt = form.prompt.strip()
    try:
        image_generator.check_endpoint(spec)
        request = image_generator.build_request(
            prompt=prompt,
            mode=form.mode,
            seed=seed,
            aspect_ratio=form.aspect_ratio,
            partition=partition,
            steps=form.steps,
        )
    except ValueError as exc:
        raise LabInputError(str(exc)) from exc

    width, height = image_models.ASPECT_SIZES[form.aspect_ratio]
    run = LabRun(
        mode="text_to_image",
        endpoint=image_generator.GENERATE_PATH,
        model=image_models.MODEL_ID,
        prompt=prompt,
        params={
            "engine": "qwen",
            "qwen_mode": form.mode,
            "aspect_ratio": form.aspect_ratio,
            "expected_size": {"width": width, "height": height},
            "seed": seed,
            "steps": form.steps,
        },
        reference_images=[],
        status="running",
        request={"method": "POST", "path": image_generator.GENERATE_PATH, "body": request},
    )
    session.add(run)
    await session.flush()
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=RUN_JOB,
        provider="gpu",
        input={
            "requested": "lab_image",
            "run_id": run.id,
            "image_model": image_models.MODEL_ID,
            "image_mode": form.mode,
            "aspect_ratio": form.aspect_ratio,
            "expected_size": {"width": width, "height": height},
            "endpoint": image_generator.GENERATE_PATH,
            "request": request,
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
        "lab image run started: run=%d job=%d mode=%s shape=%s",
        run.id,
        job.id,
        form.mode,
        form.aspect_ratio,
    )
    return run, job


@dataclass(frozen=True)
class QwenEditForm:
    """Qwen-Image-2.1's edit endpoint, from the Image lab or from the Character lab (a look's
    other angles, made by editing its chosen front-view picture).
    """

    prompt: str
    mode: image_models.ImageMode
    # None: the result follows the last reference's shape, instead of asking for one.
    aspect_ratio: str | None
    seed: int | None
    steps: int | None
    references: list[Ref]


def validate_qwen_edit_form(form: QwenEditForm) -> None:
    """Raises LabInputError for a form no Qwen edit run should be started with."""
    if not form.prompt.strip():
        raise LabInputError("Write a prompt first.")
    if len(form.prompt) > image_generator.MAX_PROMPT_CHARS:
        raise LabInputError(
            f"The prompt must be at most {image_generator.MAX_PROMPT_CHARS:,} characters."
        )
    if not image_models.is_image_mode(form.mode):
        raise LabInputError("Choose quality or fast.")
    if form.aspect_ratio is not None and form.aspect_ratio not in image_models.ASPECT_RATIOS:
        raise LabInputError(f"Choose one of the shapes: {', '.join(image_models.ASPECT_RATIOS)}.")
    if form.seed is not None and not 0 <= form.seed < image_models.SEED_LIMIT:
        raise LabInputError(f"The seed must be from 0 to {image_models.SEED_LIMIT - 1}.")
    if form.steps is not None:
        if form.mode != "quality":
            raise LabInputError("The number of steps can only be set in quality mode.")
        if not image_generator.MIN_STEPS <= form.steps <= image_generator.MAX_STEPS:
            raise LabInputError(
                f"The number of steps must be from {image_generator.MIN_STEPS} to "
                f"{image_generator.MAX_STEPS}."
            )
    if not 1 <= len(form.references) <= image_generator.MAX_REFERENCES:
        raise LabInputError(f"An edit needs 1 to {image_generator.MAX_REFERENCES} references.")


async def create_qwen_edit_run(
    session: AsyncSession, form: QwenEditForm, *, commit: bool = True
) -> tuple[LabRun, Job]:
    """Checks the form and starts one edit run on the GPU server. Commits, unless `commit` is
    False: the run and its job are then only flushed, so a caller (the Character lab, making
    several angles at once) can link them and commit everything together. Raises LabInputError.

    Like `create_qwen_run`, but on Qwen-Image-2.1's edit endpoint: the request names the
    references by the server's own asset ids, which only exist once `jobs/generate_lab_image.py`
    uploads them at submit time, so `create_qwen_edit_run` stores `{source, id}` for each
    reference and lets `GenerateLabImageHandler.start` resolve and upload them.
    """
    validate_qwen_edit_form(form)
    for number, ref in enumerate(form.references, start=1):
        await _reference_path(session, number, ref)  # only checks that it exists
    seed = form.seed if form.seed is not None else secrets.randbelow(image_models.SEED_LIMIT)
    partition = await settings_service.get_str(session, PARTITION_KEY)
    bodies = await contract_guard.latest_bodies(session)
    spec = next((body for body in bodies if api_contract.is_openapi(body)), None)
    prompt = form.prompt.strip()
    try:
        image_generator.check_edit_endpoint(spec)
        request = image_generator.build_edit_request(
            prompt=prompt,
            mode=form.mode,
            seed=seed,
            aspect_ratio=form.aspect_ratio,
            partition=partition,
            steps=form.steps,
        )
    except ValueError as exc:
        raise LabInputError(str(exc)) from exc

    expected = image_models.ASPECT_SIZES.get(form.aspect_ratio or "")
    expected_size = {"width": expected[0], "height": expected[1]} if expected else None
    reference_json = [{"source": ref.source, "id": ref.id} for ref in form.references]

    run = LabRun(
        mode="edit",
        endpoint=image_generator.EDIT_PATH,
        model=image_models.MODEL_ID,
        prompt=prompt,
        params={
            "engine": "qwen",
            "qwen_mode": form.mode,
            "aspect_ratio": form.aspect_ratio,
            "expected_size": expected_size,
            "seed": seed,
            "steps": form.steps,
        },
        reference_images=reference_json,
        status="running",
        request={"method": "POST", "path": image_generator.EDIT_PATH, "body": request},
    )
    session.add(run)
    await session.flush()
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=RUN_JOB,
        provider="gpu",
        input={
            "requested": "lab_image",
            "run_id": run.id,
            "image_model": image_models.MODEL_ID,
            "image_mode": form.mode,
            "aspect_ratio": form.aspect_ratio,
            "expected_size": expected_size,
            "endpoint": image_generator.EDIT_PATH,
            "request": request,
            "references": reference_json,
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
        "lab image edit run started: run=%d job=%d mode=%s refs=%d",
        run.id,
        job.id,
        form.mode,
        len(form.references),
    )
    return run, job


# --- Uploads --------------------------------------------------------------------------------


async def upload_image(chunks: AsyncIterable[bytes], content_length: int | None) -> LabImage:
    """Receives, checks and stores an image the user uploaded (the same rules as a frame).
    Raises FrameRejected.
    """
    too_large = f"The file is larger than {frame_images.FRAME_MAX_MB} MB."
    if content_length is not None and content_length > frame_images.FRAME_MAX_BYTES:
        raise FrameRejected(413, too_large)

    storage = get_storage()
    try:
        temp = await storage.receive(chunks, max_bytes=frame_images.FRAME_MAX_BYTES)
    except TooLargeError:
        raise FrameRejected(413, too_large) from None
    try:
        if temp.size_bytes == 0:
            raise FrameRejected(422, "The file is empty.")
        info = await frame_images.run_pillow(frame_images.inspect_image, temp.path)
        stored = await storage.save_lab(temp, info.ext)
    except BaseException:
        storage.discard(temp)
        raise

    async with SessionLocal() as session:
        image = LabImage(
            origin="upload",
            path=stored.relative_path,
            mime=info.mime,
            width=info.width,
            height=info.height,
            size_bytes=temp.size_bytes,
            sha256=temp.sha256,
        )
        try:
            session.add(image)
            await session.commit()
        except BaseException:
            _logger.warning("lab upload stored but not recorded: %s", stored.relative_path)
            raise
    _logger.info(
        "lab upload %d: %s %dx%d %d bytes",
        image.id,
        info.ext,
        info.width,
        info.height,
        temp.size_bytes,
    )
    return image


# --- Reads (the history, the library, the project frames) ----------------------------------


async def list_runs(session: AsyncSession, before_id: int | None, limit: int) -> list[LabRun]:
    """The newest runs first, `limit` of them, those with an id below `before_id` if given."""
    statement = select(LabRun).order_by(LabRun.id.desc()).limit(limit)
    if before_id is not None:
        statement = statement.where(LabRun.id < before_id)
    return list(
        (await session.execute(statement.execution_options(populate_existing=True))).scalars()
    )


async def get_run(session: AsyncSession, run_id: int) -> LabRun | None:
    return await session.get(LabRun, run_id)


async def jobs_for_runs(session: AsyncSession, runs: Sequence[LabRun]) -> dict[int, Job]:
    """The `lab_image` job of each run that has one, by run id (a Seedream run has none)."""
    job_ids = {run.job_id for run in runs if run.job_id is not None}
    if not job_ids:
        return {}
    found = await session.execute(
        select(Job).where(Job.id.in_(job_ids)).execution_options(populate_existing=True)
    )
    by_id = {job.id: job for job in found.scalars()}
    return {run.id: by_id[run.job_id] for run in runs if run.job_id in by_id}


async def images_by_run(session: AsyncSession, run_ids: Sequence[int]) -> dict[int, list[LabImage]]:
    """The result images of the runs, in the order they were returned."""
    if not run_ids:
        return {}
    statement = (
        select(LabImage)
        .where(LabImage.run_id.in_(run_ids))
        .order_by(LabImage.run_id, LabImage.output_index)
    )
    grouped: dict[int, list[LabImage]] = {}
    for image in (await session.execute(statement)).scalars():
        if image.run_id is not None:
            grouped.setdefault(image.run_id, []).append(image)
    return grouped


async def library(session: AsyncSession, limit: int = 60) -> list[LabImage]:
    """The newest lab images, uploads and results together."""
    statement = select(LabImage).order_by(LabImage.id.desc()).limit(limit)
    return list((await session.execute(statement)).scalars())


@dataclass(frozen=True)
class ReferenceDetail:
    path: str
    width: int | None
    height: int | None


async def reference_details(
    session: AsyncSession, runs: Sequence[LabRun]
) -> dict[tuple[str, int], ReferenceDetail]:
    """What the references of these runs look like now, keyed by (source, id). A reference
    that is gone is simply missing from the result.
    """
    wanted: dict[str, set[int]] = {"lab": set(), "asset": set()}
    for run in runs:
        for item in run.reference_images if isinstance(run.reference_images, list) else []:
            if isinstance(item, dict) and item.get("source") in wanted:
                if isinstance(item.get("id"), int):
                    wanted[item["source"]].add(item["id"])
    details: dict[tuple[str, int], ReferenceDetail] = {}
    if wanted["lab"]:
        found = await session.execute(select(LabImage).where(LabImage.id.in_(wanted["lab"])))
        for image in found.scalars():
            details[("lab", image.id)] = ReferenceDetail(image.path, image.width, image.height)
    if wanted["asset"]:
        found = await session.execute(select(Asset).where(Asset.id.in_(wanted["asset"])))
        for asset in found.scalars():
            details[("asset", asset.id)] = ReferenceDetail(asset.path, asset.width, asset.height)
    return details


async def project_frames(session: AsyncSession, project_id: int, limit: int = 200) -> list[Asset]:
    """A project's frame assets, newest first. No new frames are made (the narration pipeline
    that made them is retired), so these are the ones that are left.
    """
    statement = (
        select(Asset)
        .where(Asset.project_id == project_id, Asset.kind == "frame")
        .order_by(Asset.id.desc())
        .limit(limit)
    )
    return list((await session.execute(statement)).scalars())
