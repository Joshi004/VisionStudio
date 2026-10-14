"""The image adapter: Qwen-Image-2.1 on the GPU server (text to image, and edit).

It is made of steps, like `video_generator.py`, because the dispatcher saves the server's job id
right after submitting and resumes after a restart. Upload, status, download, cancel and purge
are the calls every backend shares (`gpu_server.py`); what is specific to this model lives here:

- `POST /v1/qwen-image21/images/generate` (`QwenImageGenerateRequest`). The body is
  `prompt`, `mode` (`quality` or `fast`), `seed`, `aspect_ratio` and, when the setting is not
  blank, `partition`. `num_inference_steps` is sent only when the caller asks for it, and
  only with `quality` (the server refuses it with `fast`: 422). There is no negative prompt
  and no size field: the shape is one of the seven in `services/image_models.ASPECT_SIZES`.
- The answer is one PNG, `GET /v1/jobs/{job_id}/result`. A job takes minutes (the server loads
  about 31 GB of weights first) and reports no progress.

- `POST /v1/qwen-image21/images/edit` (`QwenImageEditRequest`), which makes a scene's last
  frame by editing its first frame (Phase 23). The body is the same, plus
  `reference_image_asset_ids` (1 to 10 images uploaded with `POST /v1/uploads`, so the body needs
  the server's asset ids, like a clip's). `aspect_ratio` is optional there: left out, the result
  follows the last reference image's shape, at about 4 megapixels. `build_edit_request` builds
  the body without the ids and `with_references` adds them, so the stored request can be sent
  again after the references are uploaded again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from app.core import outbound
from app.providers import gpu_server
from app.services.image_models import ASPECT_RATIOS, ImageMode

GENERATE_PATH: Final = "/v1/qwen-image21/images/generate"
REQUEST_SCHEMA: Final = "QwenImageGenerateRequest"
EDIT_PATH: Final = "/v1/qwen-image21/images/edit"
EDIT_REQUEST_SCHEMA: Final = "QwenImageEditRequest"
MAX_REFERENCES: Final = 10

MAX_PROMPT_CHARS: Final = 8000
MIN_STEPS: Final = 1
MAX_STEPS: Final = 100


def no_endpoint_message(path: str = GENERATE_PATH) -> str:
    return (
        f"The GPU API has no {path} endpoint. Open Settings and test the GPU connection, "
        "so the app reads the server's current API."
    )


def _check_path(spec: dict[str, Any] | None, path: str) -> None:
    paths = spec.get("paths") if isinstance(spec, dict) else None
    item = paths.get(path) if isinstance(paths, dict) else None
    if not isinstance(item, dict) or not isinstance(item.get("post"), dict):
        raise ValueError(no_endpoint_message(path))


def check_endpoint(spec: dict[str, Any] | None) -> None:
    """Raises ValueError, with a message for the user, when the approved OpenAPI document has
    no image generation endpoint (or no document was recorded at all).
    """
    _check_path(spec, GENERATE_PATH)


def check_edit_endpoint(spec: dict[str, Any] | None) -> None:
    """Raises ValueError, with a message for the user, when the approved OpenAPI document has
    no image edit endpoint (or no document was recorded at all).
    """
    _check_path(spec, EDIT_PATH)


def _check_prompt(prompt: str) -> None:
    if not prompt.strip():
        raise ValueError("The image prompt is empty.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"The image prompt must be at most {MAX_PROMPT_CHARS:,} characters.")


def _check_steps(steps: int | None, mode: ImageMode) -> None:
    if steps is None:
        return
    if mode != "quality":
        raise ValueError("The number of steps can only be set in quality mode.")
    if not MIN_STEPS <= steps <= MAX_STEPS:
        raise ValueError(f"The number of steps must be from {MIN_STEPS} to {MAX_STEPS}.")


def build_request(
    *,
    prompt: str,
    mode: ImageMode,
    seed: int,
    aspect_ratio: str,
    partition: str,
    steps: int | None = None,
) -> dict[str, Any]:
    """The body for `GENERATE_PATH`. It holds only what the user chose and what was worked out
    from it, so it can be stored and sent again unchanged.

    `partition` is sent only when it is not blank. `steps` (`num_inference_steps`) is for
    `quality` only. Raises ValueError for a request the server would refuse.
    """
    _check_prompt(prompt)
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(f"The shape {aspect_ratio} is not one the image model makes.")
    _check_steps(steps, mode)

    body: dict[str, Any] = {
        "prompt": prompt,
        "mode": mode,
        "seed": seed,
        "aspect_ratio": aspect_ratio,
    }
    if steps is not None:
        body["num_inference_steps"] = steps
    if partition:
        body["partition"] = partition
    return body


def build_edit_request(
    *,
    prompt: str,
    mode: ImageMode,
    seed: int,
    aspect_ratio: str | None,
    partition: str,
    steps: int | None = None,
) -> dict[str, Any]:
    """The body for `EDIT_PATH` without its references (those need the server's asset ids, see
    `with_references`). Like `build_request`, it holds only what the user chose and what was
    worked out from it, so it can be stored and sent again unchanged.

    `aspect_ratio` is left out of the body when it is None: the result then follows the last
    reference image's shape. `partition` is sent only when it is not blank. Raises ValueError
    for a request the server would refuse.
    """
    _check_prompt(prompt)
    if aspect_ratio is not None and aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(f"The shape {aspect_ratio} is not one the image model makes.")
    _check_steps(steps, mode)

    body: dict[str, Any] = {"prompt": prompt, "mode": mode, "seed": seed}
    if aspect_ratio is not None:
        body["aspect_ratio"] = aspect_ratio
    if steps is not None:
        body["num_inference_steps"] = steps
    if partition:
        body["partition"] = partition
    return body


def with_references(request: dict[str, Any], remote_ids: list[str]) -> dict[str, Any]:
    """The full body of an edit: `request` plus the references, in the order the prompt names
    them. Raises ValueError for no reference, or for more than the server takes.
    """
    if not 1 <= len(remote_ids) <= MAX_REFERENCES:
        raise ValueError(f"An edit needs 1 to {MAX_REFERENCES} reference images.")
    return {**request, "reference_image_asset_ids": list(remote_ids)}


# --- The steps of an image job (every call raises `gpu_server.GpuCallError`) ----------


async def upload_reference(base_url: str, path: Path, filename: str) -> str:
    """Uploads one reference image (a PNG) and returns the server's asset id."""
    return await gpu_server.upload_file(base_url, path, filename, "image/png")


async def submit(base_url: str, body: dict[str, Any], endpoint: str = GENERATE_PATH) -> str:
    """Submits the request to `endpoint` and returns the server's job id."""
    return await gpu_server.submit_job(base_url, endpoint, body)


async def status(base_url: str, provider_job_id: str) -> gpu_server.RemoteStatus:
    return await gpu_server.job_status(base_url, provider_job_id)


async def download(base_url: str, provider_job_id: str, dest: Path) -> outbound.DownloadResult:
    """Downloads the finished image (a PNG) into the new file `dest`."""
    return await gpu_server.download_result(base_url, provider_job_id, dest)


async def cancel(base_url: str, provider_job_id: str) -> gpu_server.CancelAnswer:
    return await gpu_server.cancel_job(base_url, provider_job_id)


async def cleanup(base_url: str, provider_job_id: str) -> gpu_server.PurgeAnswer:
    """Purges the finished job on the server."""
    return await gpu_server.purge_job(base_url, provider_job_id)
