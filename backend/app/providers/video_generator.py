"""The video adapter: LTX-2.3 on the GPU server (ANALYSIS.md Section 5.3, 5.4 and 6.4).

`VideoGenerator` is split into steps, because the dispatcher saves the server's job id
right after submitting and resumes after a restart. Upload, status, download, cancel and
purge are the calls every backend shares (`gpu_server.py`). What is specific to LTX lives
here. A clip is made by one of two endpoints, chosen once per job from the scene's frames
(`scene_inputs.clip_mode`):

- keyframe interpolation, `POST /v1/ltx/videos/keyframe-interpolation`
  (`KeyframeInterpolationRequest`), when the scene has a last frame. `with_keyframes` puts
  the first keyframe at `frame_idx` 0 and the last at `num_frames - 1`, both with strength
  1.0. The endpoint has no `enhance_prompt` field, so the prompt is never rewritten.
- image-to-video, `POST /v1/ltx/videos/generate` (`TextToVideoRequest`), when it has only a
  first frame. `with_first_frame` attaches the frame at `frame_idx` 0 with strength 1.0.
  `build_request` always sends `mode: "quality"` (the default, `fast`, silently ignores the
  negative prompt) and `enhance_prompt: false` (a rewrite would be invisible).

Neither body sends `orientation`, `duration_seconds` (the frame count is computed here) or
`crf` (the pipeline's own default applies).

- `frame_limits`: the limits the approved OpenAPI document declares for `num_frames` on the
  endpoint in use.
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
from app.services.scene_inputs import ClipMode

KEYFRAME_PATH: Final = "/v1/ltx/videos/keyframe-interpolation"
GENERATE_PATH: Final = "/v1/ltx/videos/generate"
ENDPOINTS: Final[dict[ClipMode, str]] = {
    "first_frame": GENERATE_PATH,
    "first_and_last": KEYFRAME_PATH,
}
_REQUEST_SCHEMAS: Final[dict[str, str]] = {
    KEYFRAME_PATH: "KeyframeInterpolationRequest",
    GENERATE_PATH: "TextToVideoRequest",
}
_SIZE_MULTIPLE: Final = 64


def clip_mode_for(endpoint: object) -> ClipMode | None:
    """The mode a recorded endpoint stands for, or None for an endpoint this phase does not
    know (a job or a clip from before it never has one).
    """
    for mode, path in ENDPOINTS.items():
        if endpoint == path:
            return mode
    return None


def no_endpoint_message(endpoint: str) -> str:
    return f"The approved GPU API has no {endpoint} endpoint."


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


def frame_limits(spec: dict[str, Any], endpoint: str) -> FrameLimits:
    """Reads the limits for `num_frames` on `endpoint` from the approved OpenAPI document.

    Raises ValueError, with a message for the user that names the endpoint, when the
    document has no such endpoint or request schema.
    """
    paths = spec.get("paths")
    operation = paths.get(endpoint, {}).get("post") if isinstance(paths, dict) else None
    schema_name = _REQUEST_SCHEMAS.get(endpoint)
    if not isinstance(operation, dict) or schema_name is None:
        raise ValueError(no_endpoint_message(endpoint))

    schemas = spec.get("components", {}).get("schemas", {})
    schema = schemas.get(schema_name) if isinstance(schemas, dict) else None
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or "num_frames" not in properties:
        raise ValueError(f"The approved GPU API has no num_frames field on the {endpoint} request.")

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
    endpoint: str,
    prompt: str,
    negative_prompt: str | None,
    width: int,
    height: int,
    num_frames: int,
    fps: int,
    seed: int,
    partition: str,
) -> dict[str, Any]:
    """The body for `endpoint` without its frames (those need the server's asset ids).

    `negative_prompt` is sent only when the project has one: it replaces the pipeline's
    own default, so leaving it out keeps that default. `partition` is sent only when the
    setting is not blank. For `/v1/ltx/videos/generate` the body also says `mode: "quality"`
    and `enhance_prompt: false` explicitly, so neither relies on a server default. A request
    holds only what the user chose and the numbers worked out from it, so it can be stored
    and sent again unchanged.
    """
    body: dict[str, Any] = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "frame_rate": float(fps),
        "seed": seed,
    }
    if endpoint == GENERATE_PATH:
        body["mode"] = "quality"
        body["enhance_prompt"] = False
    if negative_prompt is not None and negative_prompt.strip():
        body["negative_prompt"] = negative_prompt
    if partition:
        body["partition"] = partition
    return body


def with_keyframes(
    request: dict[str, Any], first_remote_id: str, last_remote_id: str
) -> dict[str, Any]:
    """The keyframe body: the first frame is the video's first frame, the last frame its last."""
    return {
        **request,
        "keyframes": [
            {"asset_id": first_remote_id, "frame_idx": 0, "strength": 1.0},
            {"asset_id": last_remote_id, "frame_idx": request["num_frames"] - 1, "strength": 1.0},
        ],
    }


def with_first_frame(request: dict[str, Any], first_remote_id: str) -> dict[str, Any]:
    """The image-to-video body: the frame is the video's literal first frame (`frame_idx` 0)."""
    return {
        **request,
        "images": [{"asset_id": first_remote_id, "frame_idx": 0, "strength": 1.0}],
    }


# --- The steps of a clip job (every call raises `gpu_server.GpuCallError`) ----------


async def upload_frame(base_url: str, path: Path, filename: str) -> str:
    """Uploads one normalised frame (a PNG) and returns the server's asset id."""
    return await gpu_server.upload_file(base_url, path, filename, "image/png")


async def submit(base_url: str, endpoint: str, body: dict[str, Any]) -> str:
    """Submits the clip to `endpoint` and returns the server's job id."""
    return await gpu_server.submit_job(base_url, endpoint, body)


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
