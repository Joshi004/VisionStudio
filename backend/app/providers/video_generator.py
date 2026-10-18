"""The video adapter: LTX-2.3, LTX-2.5 and MiniMax H3 on the GPU server (ANALYSIS.md Section
5.3, 5.4 and 6.4).

`VideoGenerator` is split into steps, because the dispatcher saves the server's job id
right after submitting and resumes after a restart. Upload, status, download, cancel and
purge are the calls every backend shares (`gpu_server.py`). What is specific to LTX lives
here. A clip is made by one endpoint, chosen once per job from the video model and the
scene's frames (`scene_inputs.clip_mode`), by `endpoint_for`:

- LTX-2.3 keyframe interpolation, `POST /v1/ltx/videos/keyframe-interpolation`
  (`KeyframeInterpolationRequest`), when the scene has a last frame. `with_frames` puts
  the first keyframe at `frame_idx` 0 and the last at `num_frames - 1`, both with strength
  1.0. The endpoint has no `enhance_prompt` field, so the prompt is never rewritten.
- LTX-2.3 image-to-video, `POST /v1/ltx/videos/generate` (`TextToVideoRequest`), when the
  scene has only a first frame. `with_frames` attaches the frame at `frame_idx` 0 with
  strength 1.0. `build_request` always sends `mode: "quality"` (the default, `fast`,
  silently ignores the negative prompt) and `enhance_prompt: false` (a rewrite would be
  invisible).
- LTX-2.5 image-to-video, `POST /v1/ltx25/videos/generate` (`Ltx25TextToVideoRequest`),
  with the same first-frame body. `mode: "quality"` there is the DFR recipe (sharper detail,
  more GPU memory). The endpoint has no `negative_prompt` field (neither recipe uses
  guidance), so `build_request` never sends one to it.

- LTX-2.5 first and last frame, `POST /v1/ltx25/videos/interpolate`
  (`Ltx25InterpolateRequest`), when the scene has a last frame. The body names the two
  frames as `first_frame_asset_id` and `last_frame_asset_id`. The endpoint has `mode` and
  `enhance_prompt` like the generate endpoints, and no `negative_prompt`. Two frames of
  different places make the model cross-dissolve instead of moving the camera, so a scene's
  two frames should show the same place, subject and light.

- LTX-2.3 audio-to-video, `POST /v1/ltx/videos/audio-to-video` (`AudioToVideoRequest`), and
  LTX-2.5 audio-to-video, `POST /v1/ltx25/videos/audio-to-video` (`Ltx25AudioToVideoRequest`):
  the video is made to match a recorded speech, which is muxed into the MP4 unchanged. The frame
  at `frame_idx` 0 pins how the speaker looks (`with_frames`, the first-frame body) and
  `with_audio` names the speech. Both are quality recipe only, so the body has no `mode` and no
  `enhance_prompt`, and both accept a negative prompt (version 0.12.0 of the server's guide).

- `lip_sync: bool` on either audio-to-video endpoint (also 0.12.0): after the video is made,
  TBDub redraws the speaker's mouth to match the audio exactly, in the same job. The server
  forces `frame_rate` to 25 when it is on, so the caller must compute the frame count at 25 fps
  itself and send that `frame_rate`, so the stored request matches what runs. Failure is silent
  on the server (the job still succeeds, without lip sync): `gpu_server.RemoteStatus.lip_sync`
  carries whether it was applied.

- MiniMax H3 (a scene's clip, the Video lab and the Character lab's takes),
  `POST /v1/h3/videos/generate`
  (`H3GenerateRequest`): text-to-video, first frame, or first and last frame, all by one
  endpoint. The body has no `frame_rate` (a fixed 24 fps), `mode`, `enhance_prompt` or
  `negative_prompt`; it has an optional `num_inference_steps`. The frames are named as
  `first_frame_asset_id` and `last_frame_asset_id`. The prompt is used exactly as sent and
  was trained in a structured format, with a first line that places the frames
  (`h3_prompt_prefix`). `ENDPOINTS` lists it for both clip modes. Because one endpoint serves both
  modes, the mode of a recorded H3 clip cannot be read back from its endpoint: it is stored next
  to it (`clip_mode_for`). A scene that has a last frame but is shorter than the shortest H3 clip
  (`frame_counts.H3_MIN_FRAMES`, 5.17 s) is made by LTX-2.5 instead, with a note, because H3 lands
  on the last frame at the very end of a clip that the render would cut before it.
- MiniMax H3 reference mode, `POST /v1/h3/videos/audio-to-video` (`H3AudioToVideoRequest`):
  up to 9 reference pictures (`image_asset_ids`) and, optionally, audio references
  (`audio_asset_ids`, a list of up to 3, each documented as 2 to 15 s) that the model reads and
  then makes its own soundtrack from, unlike the LTX audio-to-video endpoints, which mux the
  speech in unchanged. Since version 0.14.0 of the server's guide the field is the list
  `audio_asset_ids`: the old single `audio_asset_id` is refused with a 422.
  `with_h3_references` adds them. `match_audio_duration` needs at least one audio.

`with_frames` builds the part of the body that names the frames, in the shape the chosen
endpoint wants. Every pair of (model, clip mode) has an endpoint. `endpoint_for` still falls
back to LTX-2.3 for a pair that has none, and says so in a note.

No body sends `orientation`, `duration_seconds` (the frame count is computed here), `crf`
(the pipeline's own default applies) or `auto_duration` (the voiceover sets the length).

- `frame_limits`: the limits the approved OpenAPI document declares for `num_frames` on the
  endpoint in use.
- `check_size`: width and height must be multiples of 64 (the server does not check this
  at submission, so a wrong size wastes a GPU run).
"""

from __future__ import annotations

import mimetypes
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.core import outbound
from app.providers import gpu_server
from app.services import video_models
from app.services.frame_counts import H3_FPS, H3_MIN_FRAMES, MIN_NUM_FRAMES
from app.services.scene_inputs import ClipMode
from app.services.video_models import H3_MODEL, LabVideoModel, LtxModel, VideoModel

KEYFRAME_PATH: Final = "/v1/ltx/videos/keyframe-interpolation"
GENERATE_PATH: Final = "/v1/ltx/videos/generate"
LTX25_GENERATE_PATH: Final = "/v1/ltx25/videos/generate"
LTX25_INTERPOLATE_PATH: Final = "/v1/ltx25/videos/interpolate"
# Lip-sync: makes the video to match a recorded speech and muxes that speech in unchanged
# (`AudioToVideoRequest` / `Ltx25AudioToVideoRequest`). Neither has `mode` (quality recipe only)
# or `enhance_prompt`. Used by the Character lab (and, for LTX-2.3, by scenes later), so they
# are not in `ENDPOINTS` (which is keyed by `ClipMode`, not by "has audio").
AUDIO_TO_VIDEO_PATH: Final = "/v1/ltx/videos/audio-to-video"
LTX25_AUDIO_TO_VIDEO_PATH: Final = "/v1/ltx25/videos/audio-to-video"
# MiniMax H3, used by scenes, the Video lab and the Character lab's takes: text, first-frame and
# first-and-last-frame video by one endpoint, and reference mode (pictures and an audio
# reference) by the other.
H3_GENERATE_PATH: Final = "/v1/h3/videos/generate"
H3_AUDIO_TO_VIDEO_PATH: Final = "/v1/h3/videos/audio-to-video"
# The audio-to-video endpoint for each LTX model (MiniMax H3's reference mode is a different
# kind of clip, started by `create_h3_reference_run`).
AUDIO_ENDPOINTS: Final[dict[LtxModel, str]] = {
    "ltx-2.3": AUDIO_TO_VIDEO_PATH,
    "ltx-2.5": LTX25_AUDIO_TO_VIDEO_PATH,
}
# Which endpoint makes a clip, by video model and by how the clip is made. A pair that is
# missing falls back to LTX-2.3 in `endpoint_for`. MiniMax H3 has one endpoint for both modes
# (and for a text-only clip, which only the Video lab makes).
ENDPOINTS: Final[dict[tuple[VideoModel, ClipMode], str]] = {
    ("ltx-2.3", "first_frame"): GENERATE_PATH,
    ("ltx-2.3", "first_and_last"): KEYFRAME_PATH,
    ("ltx-2.5", "first_frame"): LTX25_GENERATE_PATH,
    ("ltx-2.5", "first_and_last"): LTX25_INTERPOLATE_PATH,
    ("minimax-h3", "first_frame"): H3_GENERATE_PATH,
    ("minimax-h3", "first_and_last"): H3_GENERATE_PATH,
}
_REQUEST_SCHEMAS: Final[dict[str, str]] = {
    KEYFRAME_PATH: "KeyframeInterpolationRequest",
    GENERATE_PATH: "TextToVideoRequest",
    LTX25_GENERATE_PATH: "Ltx25TextToVideoRequest",
    LTX25_INTERPOLATE_PATH: "Ltx25InterpolateRequest",
    AUDIO_TO_VIDEO_PATH: "AudioToVideoRequest",
    LTX25_AUDIO_TO_VIDEO_PATH: "Ltx25AudioToVideoRequest",
    H3_GENERATE_PATH: "H3GenerateRequest",
    H3_AUDIO_TO_VIDEO_PATH: "H3AudioToVideoRequest",
}
# The endpoints that take `mode` and `enhance_prompt` (the keyframe and audio-to-video endpoints
# have neither, and neither do the MiniMax H3 ones).
_MODE_ENDPOINTS: Final = frozenset({GENERATE_PATH, LTX25_GENERATE_PATH, LTX25_INTERPOLATE_PATH})
# The endpoints that have a `negative_prompt` field. The two plain LTX-2.5 endpoints have none
# (they run without guidance), but LTX-2.5 audio-to-video does (its own default includes "bad
# lip sync", which a value sent here replaces).
_NEGATIVE_PROMPT_ENDPOINTS: Final = frozenset(
    {GENERATE_PATH, KEYFRAME_PATH, AUDIO_TO_VIDEO_PATH, LTX25_AUDIO_TO_VIDEO_PATH}
)
_LTX23_PREFIX: Final = "/v1/ltx/"
_LTX25_PREFIX: Final = "/v1/ltx25/"
_H3_PREFIX: Final = "/v1/h3/"
# What `/v1/h3/videos/audio-to-video` takes: up to 9 reference pictures (`image_asset_ids`) and
# up to 3 audios (`audio_asset_ids`). The Video lab uses at most two audios (one per character).
H3_MAX_REFERENCE_IMAGES: Final = 9
H3_MAX_REFERENCE_AUDIOS: Final = 3
_SIZE_MULTIPLE: Final = 64
# MiniMax H3, from the GPU server's guide (version 0.13.0). It is trained at 1344 x 768 and
# 768 x 1344 whatever the project's own size is, so a clip is asked for at these sizes by the
# project's orientation (both are multiples of 64, so the frame fitting and `check_size` keep
# working). The render scales the clip to the output size afterwards.
H3_SIZES: Final[dict[str, tuple[int, int]]] = {
    "landscape": (1344, 768),
    "portrait": (768, 1344),
}
# What the server's guide says the first line of an H3 prompt must be when frames are given.
_H3_FIRST_FRAME_LINE: Final = (
    "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) "
    "is fully referenced."
)
_H3_FIRST_AND_LAST_LINE: Final = (
    "How the reference pictures align with the target video -- Picture 1 (from Shot 1) aligns "
    "with the 0.00-second mark of the target video; Picture 2 (from Shot {shots}) aligns with "
    "the {seconds}-second mark of the target video."
)
_H3_SHOT_MARKER = re.compile(r"\[Shot\s+(\d+)\]", re.IGNORECASE)


@dataclass(frozen=True)
class EndpointChoice:
    """The endpoint a clip is made by, and the model that endpoint belongs to.

    `model` differs from the model asked for when there was no endpoint for it (then `note`
    says why, in words meant for the user).
    """

    endpoint: str
    model: VideoModel
    note: str | None


def endpoint_for(
    model: VideoModel, mode: ClipMode, duration_s: float | None = None
) -> EndpointChoice:
    """The endpoint that makes a clip of this `mode` with `model`.

    `duration_s` is the scene's length. It only matters for MiniMax H3 with a last frame: H3
    reaches the last frame at the very end of a clip that is at least `H3_MIN_FRAMES` long, so
    a shorter scene would be cut before the last frame is shown. That clip is made by LTX-2.5
    instead and the note says so. Left out, the length is not checked.

    Every other pair of model and mode has an endpoint today. For a pair that has none, the
    clip is made by LTX-2.3 and the note says so.
    """
    if (
        model == H3_MODEL
        and mode == "first_and_last"
        and duration_s is not None
        and round(duration_s * H3_FPS) < H3_MIN_FRAMES
    ):
        h3_fallback: VideoModel = "ltx-2.5"
        h3_note = (
            f"{video_models.label(model)} makes a clip of at least {H3_MIN_FRAMES / H3_FPS:.2f} s "
            "and reaches the last frame at the very end of it, so this scene "
            f"({duration_s:.2f} s) would be cut before the last frame is shown. "
            f"{video_models.label(h3_fallback)} is used for this clip."
        )
        return EndpointChoice(
            endpoint=ENDPOINTS[(h3_fallback, mode)], model=h3_fallback, note=h3_note
        )
    endpoint = ENDPOINTS.get((model, mode))
    if endpoint is not None:
        return EndpointChoice(endpoint=endpoint, model=model, note=None)
    fallback: VideoModel = "ltx-2.3"
    note = (
        f"{video_models.label(model)} cannot make a clip from a first and a last frame yet, "
        f"so {video_models.label(fallback)} is used for this clip."
    )
    return EndpointChoice(endpoint=ENDPOINTS[(fallback, mode)], model=fallback, note=note)


def lab_endpoint_for(model: LabVideoModel, mode: ClipMode) -> str:
    """The endpoint the Video lab makes a clip of this `mode` with. Unlike `endpoint_for` there
    is no fallback to another model: the lab runs exactly the models it was asked for.

    Raises ValueError, with a message for the user, for a pair that has no endpoint.
    """
    endpoint = ENDPOINTS.get((model, mode))
    if endpoint is None:
        raise ValueError(f"{video_models.label(model)} has no endpoint for this kind of clip.")
    return endpoint


def is_h3_endpoint(endpoint: object) -> bool:
    """True for the two MiniMax H3 endpoints (whose jobs hold 4 or 8 GPUs, as the server sizes
    them).
    """
    return isinstance(endpoint, str) and endpoint.startswith(_H3_PREFIX)


def audio_endpoint_for(model: LtxModel) -> str:
    """The audio-to-video endpoint of this LTX model."""
    return AUDIO_ENDPOINTS[model]


def model_for(endpoint: object) -> VideoModel | None:
    """The video model a recorded endpoint belongs to, or None for an endpoint that belongs
    to none (every older clip names an `/v1/ltx/` path, so it counts as LTX-2.3).
    """
    if not isinstance(endpoint, str):
        return None
    if endpoint.startswith(_LTX25_PREFIX):
        return "ltx-2.5"
    if endpoint.startswith(_LTX23_PREFIX):
        return "ltx-2.3"
    if endpoint.startswith(_H3_PREFIX):
        return H3_MODEL
    return None


def clip_mode_for(endpoint: object, recorded_mode: object = None) -> ClipMode | None:
    """The mode a recorded endpoint stands for, or None for an endpoint this phase does not
    know (a job or a clip from before it never has one).

    A MiniMax H3 endpoint serves both modes, so for it the mode stored next to the endpoint
    (`recorded_mode`, from the job's input or the clip's provenance) decides, and None is
    returned when there is none. Every other endpoint stands for exactly one mode.
    """
    if is_h3_endpoint(endpoint):
        if recorded_mode == "first_frame" or recorded_mode == "first_and_last":
            return recorded_mode
        return None
    for (_model, mode), path in ENDPOINTS.items():
        if endpoint == path:
            return mode
    return None


def no_endpoint_message(endpoint: str) -> str:
    return f"The GPU API has no {endpoint} endpoint."


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
        raise ValueError(f"The GPU API has no num_frames field on the {endpoint} request.")

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
    num_inference_steps: int | None = None,
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

    A MiniMax H3 body (`/v1/h3/`) has no `frame_rate` (the model runs at a fixed 24 fps, so
    `fps` is not sent), `mode`, `enhance_prompt` or `negative_prompt`: `mode` and
    `negative_prompt` are ignored for it. `num_inference_steps` is sent only to H3 and only when
    it is given; left out, the pipeline's own default (50 steps) applies.
    """
    body: dict[str, Any] = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "frame_rate": float(fps),
        "seed": seed,
    }
    if is_h3_endpoint(endpoint):
        del body["frame_rate"]
        if num_inference_steps is not None:
            body["num_inference_steps"] = num_inference_steps
        if partition:
            body["partition"] = partition
        return body
    if endpoint in _MODE_ENDPOINTS:
        body["mode"] = mode
        body["enhance_prompt"] = False
    if endpoint in _NEGATIVE_PROMPT_ENDPOINTS and negative_prompt and negative_prompt.strip():
        body["negative_prompt"] = negative_prompt
    if partition:
        body["partition"] = partition
    return body


def with_frames(
    endpoint: str,
    request: dict[str, Any],
    first_remote_id: str,
    last_remote_id: str | None,
) -> dict[str, Any]:
    """The full body: `request` plus the frames, in the shape `endpoint` wants.

    The first frame is always the video's literal first frame. A last frame is needed by the
    two first-and-last endpoints and ignored by the first-frame ones. MiniMax H3 has one
    endpoint for both: it gets the last frame when there is one.
    """
    if endpoint == H3_GENERATE_PATH:
        body = {**request, "first_frame_asset_id": first_remote_id}
        if last_remote_id is not None:
            body["last_frame_asset_id"] = last_remote_id
        return body
    if endpoint in (KEYFRAME_PATH, LTX25_INTERPOLATE_PATH):
        if last_remote_id is None:
            raise ValueError(f"{endpoint} needs a last frame.")
        if endpoint == LTX25_INTERPOLATE_PATH:
            return {
                **request,
                "first_frame_asset_id": first_remote_id,
                "last_frame_asset_id": last_remote_id,
            }
        return {
            **request,
            "keyframes": [
                {"asset_id": first_remote_id, "frame_idx": 0, "strength": 1.0},
                {
                    "asset_id": last_remote_id,
                    "frame_idx": request["num_frames"] - 1,
                    "strength": 1.0,
                },
            ],
        }
    return {
        **request,
        "images": [{"asset_id": first_remote_id, "frame_idx": 0, "strength": 1.0}],
    }


def with_audio(request: dict[str, Any], audio_remote_id: str) -> dict[str, Any]:
    """`request` plus the speech the video is made to match, for `AUDIO_TO_VIDEO_PATH`.

    The speech is read from its start. `audio_max_duration` is left out, so the server reads as
    much as the video lasts (`num_frames / frame_rate`), and the caller has already made the
    video at least as long as the speech.
    """
    return {**request, "audio_asset_id": audio_remote_id, "audio_start_time": 0.0}


def with_h3_references(
    request: dict[str, Any],
    image_remote_ids: Sequence[str],
    audio_remote_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """`request` plus the references of a MiniMax H3 reference clip, for `H3_AUDIO_TO_VIDEO_PATH`.

    The pictures are named in the order given, and that order is what the prompt's
    `<Picture 1>`, `<Picture 2>`, ... mean. The audios are `<Audio 1>`, `<Audio 2>`, ... in the
    order given: references the model reads, not a soundtrack that is muxed in. There can be none
    (the audio is optional), and then no `audio_asset_ids` is sent. The older single
    `audio_asset_id` is never sent: the server refuses it.
    """
    if not 1 <= len(image_remote_ids) <= H3_MAX_REFERENCE_IMAGES:
        raise ValueError(
            f"A MiniMax H3 reference clip needs 1 to {H3_MAX_REFERENCE_IMAGES} pictures."
        )
    if len(audio_remote_ids) > H3_MAX_REFERENCE_AUDIOS:
        raise ValueError(
            f"A MiniMax H3 reference clip takes at most {H3_MAX_REFERENCE_AUDIOS} audios."
        )
    body = {**request, "image_asset_ids": list(image_remote_ids)}
    if audio_remote_ids:
        body["audio_asset_ids"] = list(audio_remote_ids)
    return body


def h3_prompt_prefix(num_frames: int, has_first: bool, has_last: bool, prompt: str) -> str:
    """The first line a MiniMax H3 prompt needs when frames are given, or "" when it needs none.

    H3 was trained on a prompt whose first line places the frames on the clip's timeline, so the
    code writes it (it depends on the frame count, which the language model cannot know) and the
    author or the language model writes the rest:

    - a first frame only: the first picture is fully referenced at 0.00 seconds;
    - a first and a last frame: picture 1 sits at 0.00 seconds and picture 2 at the clip's
      length in seconds, with two decimals (124 frames at 24 fps is 5.17). The last picture
      belongs to the last `[Shot N]` the prompt names, or to shot 1 when it names none;
    - no frame (text-to-video), or a last frame alone (the lab never makes one): no line.

    A prompt that already opens with that line is left alone (an earlier run was edited and
    sent again), so the line is never doubled.
    """
    if not has_first:
        return ""
    stripped = prompt.lstrip()
    if stripped.startswith(("For the target video,", "How the reference pictures align")):
        return ""
    if not has_last:
        return _H3_FIRST_FRAME_LINE
    shots = max((int(number) for number in _H3_SHOT_MARKER.findall(prompt)), default=1)
    return _H3_FIRST_AND_LAST_LINE.format(shots=shots, seconds=f"{num_frames / H3_FPS:.2f}")


# --- The steps of a clip job (every call raises `gpu_server.GpuCallError`) ----------


async def upload_frame(base_url: str, path: Path, filename: str) -> str:
    """Uploads one normalised frame (a PNG) and returns the server's asset id."""
    return await gpu_server.upload_file(base_url, path, filename, "image/png")


async def upload_reference_picture(base_url: str, path: Path, filename: str) -> str:
    """Uploads one reference picture of a MiniMax H3 reference clip, as it is stored (it is not
    cropped to the clip: the pictures do not set its shape), and returns the server's asset id.
    The server reads the file's type from the extension of `filename`, so the stored file's own
    extension must be kept there.
    """
    mime = mimetypes.guess_type(filename)[0] or "image/png"
    return await gpu_server.upload_file(base_url, path, filename, mime)


async def upload_audio(base_url: str, path: Path, filename: str, mime: str) -> str:
    """Uploads the speech a lip-sync clip is made to match and returns the server's asset id."""
    return await gpu_server.upload_file(base_url, path, filename, mime)


async def submit(base_url: str, endpoint: str, body: dict[str, Any]) -> gpu_server.SubmitAnswer:
    """Submits the clip to `endpoint` and returns the server's answer: its job id and, for a
    MiniMax H3 clip, the GPUs it was given and its estimated run time.
    """
    return await gpu_server.submit(base_url, endpoint, body)


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
