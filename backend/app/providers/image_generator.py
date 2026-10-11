"""The image adapter: Qwen-Image-2.1 on the GPU server (text to image only).

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

The edit endpoint (`/v1/qwen-image21/images/edit`) is not used yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from app.core import outbound
from app.providers import gpu_server
from app.services.image_models import ASPECT_RATIOS, ImageMode

GENERATE_PATH: Final = "/v1/qwen-image21/images/generate"
REQUEST_SCHEMA: Final = "QwenImageGenerateRequest"

MAX_PROMPT_CHARS: Final = 8000
MIN_STEPS: Final = 1
MAX_STEPS: Final = 100


def no_endpoint_message() -> str:
    return (
        f"The approved GPU API has no {GENERATE_PATH} endpoint. Open Settings, check the GPU "
        "API and approve it."
    )


def check_endpoint(spec: dict[str, Any] | None) -> None:
    """Raises ValueError, with a message for the user, when the approved OpenAPI document has
    no image generation endpoint (or no document was recorded at all).
    """
    paths = spec.get("paths") if isinstance(spec, dict) else None
    item = paths.get(GENERATE_PATH) if isinstance(paths, dict) else None
    if not isinstance(item, dict) or not isinstance(item.get("post"), dict):
        raise ValueError(no_endpoint_message())


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
    if not prompt.strip():
        raise ValueError("The image prompt is empty.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"The image prompt must be at most {MAX_PROMPT_CHARS:,} characters.")
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(f"The shape {aspect_ratio} is not one the image model makes.")
    if steps is not None:
        if mode != "quality":
            raise ValueError("The number of steps can only be set in quality mode.")
        if not MIN_STEPS <= steps <= MAX_STEPS:
            raise ValueError(f"The number of steps must be from {MIN_STEPS} to {MAX_STEPS}.")

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


# --- The steps of an image job (every call raises `gpu_server.GpuCallError`) ----------


async def submit(base_url: str, body: dict[str, Any]) -> str:
    """Submits the request and returns the server's job id."""
    return await gpu_server.submit_job(base_url, GENERATE_PATH, body)


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
