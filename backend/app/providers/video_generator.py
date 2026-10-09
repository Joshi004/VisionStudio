"""The video adapter: LTX-2.3 and LTX-2.5 on the GPU server (ANALYSIS.md Section 5.3, 5.4
and 6.4).

`VideoGenerator` is split into steps, because the dispatcher saves the server's job id
right after submitting and resumes after a restart. Upload, status, download, cancel and
purge are the calls every backend shares (`gpu_server.py`). What is specific to LTX lives
here. A clip is made by one endpoint, chosen once per job from the video model and the
scene's frames (`scene_inputs.clip_mode`), by `endpoint_for`:

- LTX-2.3 keyframe interpolation, `POST /v1/ltx/videos/keyframe-interpolation`
  (`KeyframeInterpolationRequest`), when the scene has a last frame. `with_keyframes` puts
  the first keyframe at `frame_idx` 0 and the last at `num_frames - 1`, both with strength
  1.0. The endpoint has no `enhance_prompt` field, so the prompt is never rewritten.
- LTX-2.3 image-to-video, `POST /v1/ltx/videos/generate` (`TextToVideoRequest`), when the
  scene has only a first frame. `with_first_frame` attaches the frame at `frame_idx` 0 with
  strength 1.0. `build_request` always sends `mode: "quality"` (the default, `fast`,
  silently ignores the negative prompt) and `enhance_prompt: false` (a rewrite would be
  invisible).
- LTX-2.5 image-to-video, `POST /v1/ltx25/videos/generate` (`Ltx25TextToVideoRequest`),
  with the same first-frame body. `mode: "quality"` there is the DFR recipe (sharper detail,
  more GPU memory). The endpoint has no `negative_prompt` field (neither recipe uses
  guidance), so `build_request` never sends one to it.

LTX-2.5 has no keyframe interpolation endpoint yet. A scene that has a last frame therefore
falls back to LTX-2.3, and `endpoint_for` says so in a note. When the server adds the
endpoint, it is one more entry in `ENDPOINTS` (and one in `_REQUEST_SCHEMAS`).

No body sends `orientation`, `duration_seconds` (the frame count is computed here), `crf`
(the pipeline's own default applies) or `auto_duration` (the voiceover sets the length).

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
from app.services import video_models
from app.services.frame_counts import MIN_NUM_FRAMES
from app.services.scene_inputs import ClipMode
from app.services.video_models import VideoModel

KEYFRAME_PATH: Final = "/v1/ltx/videos/keyframe-interpolation"
GENERATE_PATH: Final = "/v1/ltx/videos/generate"
LTX25_GENERATE_PATH: Final = "/v1/ltx25/videos/generate"
# Which endpoint makes a clip, by video model and by how the clip is made. A pair that is
# missing (LTX-2.5 with a last frame) falls back to LTX-2.3 in `endpoint_for`.
ENDPOINTS: Final[dict[tuple[VideoModel, ClipMode], str]] = {
    ("ltx-2.3", "first_frame"): GENERATE_PATH,
    ("ltx-2.3", "first_and_last"): KEYFRAME_PATH,
    ("ltx-2.5", "first_frame"): LTX25_GENERATE_PATH,
}
_REQUEST_SCHEMAS: Final[dict[str, str]] = {
    KEYFRAME_PATH: "KeyframeInterpolationRequest",
    GENERATE_PATH: "TextToVideoRequest",
    LTX25_GENERATE_PATH: "Ltx25TextToVideoRequest",
}
# The endpoints that take `mode` and `enhance_prompt` (the keyframe endpoint has neither).
_MODE_ENDPOINTS: Final = frozenset({GENERATE_PATH, LTX25_GENERATE_PATH})
# The endpoints that have a `negative_prompt` field. LTX-2.5 has none: it runs without
# guidance, so there would be nothing for one to act on.
_NEGATIVE_PROMPT_ENDPOINTS: Final = frozenset({GENERATE_PATH, KEYFRAME_PATH})
_LTX23_PREFIX: Final = "/v1/ltx/"
_LTX25_PREFIX: Final = "/v1/ltx25/"
_SIZE_MULTIPLE: Final = 64


@dataclass(frozen=True)
class EndpointChoice:
    """The endpoint a clip is made by, and the model that endpoint belongs to.

    `model` differs from the model asked for when there was no endpoint for it (then `note`
    says why, in words meant for the user).
    """

    endpoint: str
    model: VideoModel
    note: str | None


def endpoint_for(model: VideoModel, mode: ClipMode) -> EndpointChoice:
    """The endpoint that makes a clip of this `mode` with `model`.

    LTX-2.5 has no keyframe interpolation yet, so a clip with a last frame is made by
    LTX-2.3 and the note says so.
    """
    endpoint = ENDPOINTS.get((model, mode))
    if endpoint is not None:
        return EndpointChoice(endpoint=endpoint, model=model, note=None)
    fallback: VideoModel = "ltx-2.3"
    note = (
        f"{video_models.label(model)} cannot make a clip from a first and a last frame yet, "
        f"so {video_models.label(fallback)} is used for this clip."
    )
    return EndpointChoice(endpoint=ENDPOINTS[(fallback, mode)], model=fallback, note=note)


def model_for(endpoint: object) -> VideoModel | None:
    """The video model a recorded endpoint belongs to, or None for an endpoint that belongs
    to neither (every older clip names an `/v1/ltx/` path, so it counts as LTX-2.3).
    """
    if not isinstance(endpoint, str):
        return None
    if endpoint.startswith(_LTX25_PREFIX):
        return "ltx-2.5"
    if endpoint.startswith(_LTX23_PREFIX):
        return "ltx-2.3"
    return None


def clip_mode_for(endpoint: object) -> ClipMode | None:
    """The mode a recorded endpoint stands for, or None for an endpoint this phase does not
    know (a job or a clip from before it never has one).
    """
    for (_model, mode), path in ENDPOINTS.items():
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
    mode: str = "quality",
) -> dict[str, Any]:
    """The body for `endpoint` without its frames (those need the server's asset ids).

    `negative_prompt` is sent only to an endpoint that has the field (the two LTX-2.3
    endpoints; LTX-2.5 has none) and only when it is not blank: it replaces the pipeline's
    own default, so leaving it out keeps that default. The caller passes the project's own
    negative prompt, or the app's default negative prompt (a global setting) when the
    project has none, so it is blank only when both are. `partition` is sent only when the
    setting is not blank. For the two generate endpoints (LTX-2.3 and LTX-2.5) the body also
    says `mode` and `enhance_prompt: false` explicitly, so neither relies on a server default.
    `mode` is `quality` unless the caller says otherwise (a scene's clip is always quality;
    the Video lab can also ask for `fast`). A request holds only what the user chose and the
    numbers worked out from it, so it can be stored and sent again unchanged.
    """
    body: dict[str, Any] = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "frame_rate": float(fps),
        "seed": seed,
    }
    if endpoint in _MODE_ENDPOINTS:
        body["mode"] = mode
        body["enhance_prompt"] = False
    if endpoint in _NEGATIVE_PROMPT_ENDPOINTS and negative_prompt and negative_prompt.strip():
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
