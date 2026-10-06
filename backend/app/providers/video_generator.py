"""The video adapter: LTX-2.3 keyframe interpolation on the GPU server (ANALYSIS.md Section
5.3, 5.4 and 6.4).

`VideoGenerator` is split into steps, because the dispatcher saves the server's job id
right after submitting and resumes after a restart. Upload, status, download, cancel and
purge are the calls every backend shares (`gpu_server.py`). What is specific to LTX lives
here:

- `build_request` and `with_keyframes`: the body of
  `POST /v1/ltx/videos/keyframe-interpolation`, following the recorded API
  (`KeyframeInterpolationRequest`). The first keyframe is at `frame_idx` 0 and the last at
  `num_frames - 1`, both with strength 1.0. There is no `enhance_prompt` field on this
  endpoint, so the prompt is never rewritten. `crf` is not sent, so the pipeline's own
  default applies.
- `frame_limits`: the limits the approved OpenAPI document declares for `num_frames`.
- `check_size`: width and height must be multiples of 64 (the server does not check this
  at submission, so a wrong size wastes a GPU run).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.core import outbound
from app.providers import gpu_server
from app.services.frame_counts import MIN_NUM_FRAMES

KEYFRAME_PATH: Final = "/v1/ltx/videos/keyframe-interpolation"
REQUEST_SCHEMA: Final = "KeyframeInterpolationRequest"
_SIZE_MULTIPLE: Final = 64

NO_ENDPOINT: Final = "The approved GPU API has no keyframe-interpolation endpoint."


@dataclass(frozen=True)
class FrameLimits:
    """What the recorded API says about `num_frames`. `max_frames` is None when the API
    declares no maximum (as in the API recorded on 2026-10-06).
    """

    min_frames: int
    max_frames: int | None


def _number_schema(prop: Any) -> dict[str, Any]:
    """The integer or number branch of a property that may also allow null."""
    if not isinstance(prop, dict):
        return {}
    branches = prop.get("anyOf")
    for branch in branches if isinstance(branches, list) else [prop]:
        if isinstance(branch, dict) and branch.get("type") in ("integer", "number"):
            return branch
    return {}


def _whole(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def frame_limits(spec: dict[str, Any]) -> FrameLimits:
    """Reads the limits for `num_frames` from the approved OpenAPI document.

    Raises ValueError, with a message for the user, when the document has no
    keyframe-interpolation endpoint or request schema.
    """
    paths = spec.get("paths")
    operation = paths.get(KEYFRAME_PATH, {}).get("post") if isinstance(paths, dict) else None
    if not isinstance(operation, dict):
        raise ValueError(NO_ENDPOINT)

    schemas = spec.get("components", {}).get("schemas", {})
    schema = schemas.get(REQUEST_SCHEMA) if isinstance(schemas, dict) else None
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or "num_frames" not in properties:
        raise ValueError(
            "The approved GPU API has no num_frames field on the keyframe-interpolation request."
        )

    declared = _number_schema(properties["num_frames"])
    minimum = _whole(declared.get("minimum"))
    maximum = _whole(declared.get("maximum"))
    return FrameLimits(
        min_frames=max(minimum if minimum is not None else MIN_NUM_FRAMES, MIN_NUM_FRAMES),
        max_frames=maximum,
    )


def check_size(width: int, height: int) -> None:
    """Raises ValueError when a side is not a positive multiple of 64."""
    for name, value in (("width", width), ("height", height)):
        if value <= 0 or value % _SIZE_MULTIPLE != 0:
            raise ValueError(
                f"The generation {name} is {value}, which is not a multiple of {_SIZE_MULTIPLE}. "
                "Change it in Project settings."
            )


def check_frames(num_frames: int, limits: FrameLimits) -> None:
    """Raises ValueError when the frame count is outside what the recorded API allows."""
    if num_frames < limits.min_frames:
        raise ValueError(
            f"The clip needs {num_frames} frames, below the API's minimum of {limits.min_frames}."
        )
    if limits.max_frames is not None and num_frames > limits.max_frames:
        raise ValueError(
            f"The clip needs {num_frames} frames, above the API's maximum of {limits.max_frames}. "
            "Change the scene's cuts, or lower the project's frame rate."
        )


def build_request(
    *,
    prompt: str,
    negative_prompt: str | None,
    width: int,
    height: int,
    num_frames: int,
    fps: int,
    seed: int,
    partition: str,
) -> dict[str, Any]:
    """The request body without its keyframes (those need the server's asset ids).

    `negative_prompt` is sent only when the project has one: it replaces the pipeline's
    own default, so leaving it out keeps that default. `partition` is sent only when the
    setting is not blank. A request holds only what the user chose and the numbers worked
    out from it, so it can be stored and sent again unchanged.
    """
    body: dict[str, Any] = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "frame_rate": float(fps),
        "seed": seed,
    }
    if negative_prompt is not None and negative_prompt.strip():
        body["negative_prompt"] = negative_prompt
    if partition:
        body["partition"] = partition
    return body


def with_keyframes(
    request: dict[str, Any], first_remote_id: str, last_remote_id: str
) -> dict[str, Any]:
    """The full body: the first frame is the video's first frame, the last frame its last."""
    return {
        **request,
        "keyframes": [
            {"asset_id": first_remote_id, "frame_idx": 0, "strength": 1.0},
            {"asset_id": last_remote_id, "frame_idx": request["num_frames"] - 1, "strength": 1.0},
        ],
    }


# --- The steps of a clip job (every call raises `gpu_server.GpuCallError`) ----------


async def upload_frame(base_url: str, path: Path, filename: str) -> str:
    """Uploads one normalised frame (a PNG) and returns the server's asset id."""
    return await gpu_server.upload_file(base_url, path, filename, "image/png")


async def submit(base_url: str, body: dict[str, Any]) -> str:
    """Submits the clip and returns the server's job id."""
    return await gpu_server.submit_job(base_url, KEYFRAME_PATH, body)


async def status(base_url: str, provider_job_id: str) -> gpu_server.RemoteStatus:
    return await gpu_server.job_status(base_url, provider_job_id)


async def download(base_url: str, provider_job_id: str, dest: Path) -> outbound.DownloadResult:
    """Downloads the finished clip into the new file `dest`."""
    return await gpu_server.download_result(base_url, provider_job_id, dest)


async def cancel(base_url: str, provider_job_id: str) -> gpu_server.CancelAnswer:
    return await gpu_server.cancel_job(base_url, provider_job_id)


async def cleanup(base_url: str, provider_job_id: str) -> gpu_server.PurgeAnswer:
    """Purges the finished job on the server, with the frames that were uploaded for it."""
    return await gpu_server.purge_job(base_url, provider_job_id)
