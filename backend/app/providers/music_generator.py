"""The music adapter: the audio models of the GPU server's "Music generation" and "Audio
generation" groups (API 0.18.0), for the Music lab.

Like `video_generator.py`, the steps after the submit are the calls every backend shares
(`gpu_server.py`: upload, status, download, cancel, purge). What is specific to the music models
is here: which endpoint makes the audio and what its request body is.

Text-to-audio first (the editing endpoints are described after this list):

- ACE-Step 1.5, `POST /v1/ace-step15/music/generate` (`AceStepGenerateRequest`). A song with
  vocals or an instrumental from a `caption` and `lyrics`. Tempo, key and length are fields of
  their own, and are left out of the body when empty so that the model's planner chooses them
  (`thinking`). Result: a 48 kHz FLAC.
- YuE2, `POST /v1/yue2/songs/generate` (`Yue2GenerateRequest`). A sung song from a `style` line
  (language first, tempo inside it) and `lyrics`. The length follows the lyrics. `cot` stays at
  the server's default (`full`, melody and chords). Result: a 48 kHz FLAC.
- Stable Audio 3, `POST /v1/stable-audio3/audio/generate` (`StableAudio3GenerateRequest`).
  Instrumental music, stems, instruments and sound effects from a `prompt`, up to 285 s. The
  post-trained checkpoint has no `cfg_scale` and no `negative_prompt`, so none is ever sent.
  Result: a 44.1 kHz FLAC.
- Stable Audio Open, `POST /v1/stable-audio-open/audio/generate`
  (`StableAudioOpenGenerateRequest`). Sound effects, loops and ambience up to 47 s, with a
  `negative_prompt`. Result: a 44.1 kHz FLAC.
- LTX text-to-audio, `POST /v1/ltx/audio/generate` (`TextToAudioRequest`). Sound effects or
  ambience, with a `negative_prompt` and `duration_seconds`. Result: a WAV.

Editing (MUSIC-004) starts from a recording that was uploaded with `POST /v1/uploads`; the body
names it as `source_audio_asset_id`. `build_edit_body` makes the body without that id (the job
adds it after the upload, `with_source`):

- ACE-Step `repaint` (`/v1/ace-step15/music/repaint`): `repaint_start` and optional `repaint_end`.
- ACE-Step `cover` (`/v1/ace-step15/music/cover`): `cover_strength`.
- Stable Audio 3 `inpaint` (`/v1/stable-audio3/audio/inpaint`): `mask_start`, `mask_end` and an
  optional `duration`. A window past the end of the source extends it.
- Stable Audio 3 `transform` (`/v1/stable-audio3/audio/transform`): `init_noise_level` (0 to 1).
- Stable Audio Open `transform` (`/v1/stable-audio-open/audio/transform`): `init_noise_level`
  (0.05 to 20) and a `negative_prompt`.

The result of every editing endpoint is a FLAC. Every body also names the `partition` (when the
Settings name one).
"""

from __future__ import annotations

from typing import Any, Final

from app.providers.gpu_server import UPLOAD_PATH
from app.services import music_models
from app.services.music_models import EditOperation, MusicModel

ACE_STEP_GENERATE_PATH: Final = "/v1/ace-step15/music/generate"
YUE2_GENERATE_PATH: Final = "/v1/yue2/songs/generate"
STABLE_AUDIO_3_GENERATE_PATH: Final = "/v1/stable-audio3/audio/generate"
STABLE_AUDIO_OPEN_GENERATE_PATH: Final = "/v1/stable-audio-open/audio/generate"
LTX_AUDIO_PATH: Final = "/v1/ltx/audio/generate"

ENDPOINTS: Final[dict[MusicModel, str]] = {
    "ace-step-1.5": ACE_STEP_GENERATE_PATH,
    "yue2": YUE2_GENERATE_PATH,
    "stable-audio-3": STABLE_AUDIO_3_GENERATE_PATH,
    "stable-audio-open": STABLE_AUDIO_OPEN_GENERATE_PATH,
    "ltx-audio": LTX_AUDIO_PATH,
}

ACE_STEP_REPAINT_PATH: Final = "/v1/ace-step15/music/repaint"
ACE_STEP_COVER_PATH: Final = "/v1/ace-step15/music/cover"
STABLE_AUDIO_3_INPAINT_PATH: Final = "/v1/stable-audio3/audio/inpaint"
STABLE_AUDIO_3_TRANSFORM_PATH: Final = "/v1/stable-audio3/audio/transform"
STABLE_AUDIO_OPEN_TRANSFORM_PATH: Final = "/v1/stable-audio-open/audio/transform"

EDIT_ENDPOINTS: Final[dict[tuple[EditOperation, MusicModel], str]] = {
    ("repaint", "ace-step-1.5"): ACE_STEP_REPAINT_PATH,
    ("cover", "ace-step-1.5"): ACE_STEP_COVER_PATH,
    ("inpaint", "stable-audio-3"): STABLE_AUDIO_3_INPAINT_PATH,
    ("transform", "stable-audio-3"): STABLE_AUDIO_3_TRANSFORM_PATH,
    ("transform", "stable-audio-open"): STABLE_AUDIO_OPEN_TRANSFORM_PATH,
}

# The extension the audio is stored with. The servers answer FLAC, except LTX, which answers WAV.
EXTENSIONS: Final[dict[MusicModel, str]] = {
    "ace-step-1.5": "flac",
    "yue2": "flac",
    "stable-audio-3": "flac",
    "stable-audio-open": "flac",
    "ltx-audio": "wav",
}


def no_endpoint_message(endpoint: str) -> str:
    return (
        f"The GPU API has no {endpoint} endpoint. Open Settings and test the GPU connection, "
        "so the app reads the server's current API."
    )


def check_endpoint(spec: dict[str, Any] | None, endpoint: str) -> None:
    """Raises ValueError, with a message for the user, when the newest recorded OpenAPI document
    has no POST endpoint at `endpoint` (or no document was recorded at all).
    """
    paths = spec.get("paths") if isinstance(spec, dict) else None
    item = paths.get(endpoint) if isinstance(paths, dict) else None
    if not isinstance(item, dict) or not isinstance(item.get("post"), dict):
        raise ValueError(no_endpoint_message(endpoint))


def check_edit_endpoints(spec: dict[str, Any] | None, endpoint: str) -> None:
    """Like `check_endpoint`, for an edit: the source is uploaded first, so the upload endpoint
    must exist as well."""
    check_endpoint(spec, endpoint)
    check_endpoint(spec, UPLOAD_PATH)


def _optional(body: dict[str, Any], name: str, value: object) -> None:
    """Adds a field only when it has a value, so the server's own default stands otherwise."""
    if value is None or value == "":
        return
    body[name] = value


def build_body(
    model: MusicModel, fields: dict[str, Any], *, seed: int, partition: str
) -> dict[str, Any]:
    """The request body for `model`. `fields` are checked (`music_models.field_problems`).

    Nothing here is hidden from the job record: the job stores this body as it is sent.
    """
    body: dict[str, Any] = {"seed": seed}
    _optional(body, "partition", partition)

    if model == "ace-step-1.5":
        body["caption"] = fields["caption"]
        body["lyrics"] = fields.get("lyrics") or ""
        body["instrumental"] = bool(fields.get("instrumental"))
        _optional(body, "vocal_language", fields.get("vocal_language"))
        _optional(body, "bpm", fields.get("bpm"))
        _optional(body, "keyscale", fields.get("keyscale"))
        _optional(body, "time_signature", fields.get("time_signature"))
        _optional(body, "duration", fields.get("duration"))
        # With the tempo, key and length given, the planning step has nothing left to fill in;
        # turning it off keeps the song exactly as specified.
        given = all(fields.get(name) for name in ("bpm", "keyscale", "duration"))
        body["thinking"] = not given
    elif model == "yue2":
        body["style"] = fields["style"]
        body["lyrics"] = fields["lyrics"]
    else:
        duration = fields.get("duration") or music_models.DEFAULT_DURATION_S[model]
        body["prompt"] = fields["prompt"]
        if model == "ltx-audio":
            body["duration_seconds"] = duration
            _optional(body, "negative_prompt", fields.get("negative_prompt"))
        else:
            body["duration"] = duration
            if model == "stable-audio-open":
                _optional(body, "negative_prompt", fields.get("negative_prompt"))
    return body


def build_edit_body(
    operation: EditOperation,
    model: MusicModel,
    fields: dict[str, Any],
    *,
    seed: int,
    partition: str,
) -> dict[str, Any]:
    """The request body of an edit, without `source_audio_asset_id` (the job adds it once the
    source is uploaded: `with_source`). `fields` are checked (`music_models.edit_problems`).

    Nothing is hidden from the job record: the job stores the finished body as it is sent.
    """
    body: dict[str, Any] = {"seed": seed}
    _optional(body, "partition", partition)

    if model == "ace-step-1.5":
        body["caption"] = fields["caption"]
        body["lyrics"] = fields.get("lyrics") or ""
        body["instrumental"] = bool(fields.get("instrumental"))
        _optional(body, "vocal_language", fields.get("vocal_language"))
        if operation == "repaint":
            body["repaint_start"] = fields["repaint_start"]
            _optional(body, "repaint_end", fields.get("repaint_end"))
        else:
            body["cover_strength"] = fields["cover_strength"]
    else:
        body["prompt"] = fields["prompt"]
        if operation == "inpaint":
            body["mask_start"] = fields["mask_start"]
            body["mask_end"] = fields["mask_end"]
        else:
            body["init_noise_level"] = fields["init_noise_level"]
        _optional(body, "duration", fields.get("duration"))
        if model == "stable-audio-open":
            _optional(body, "negative_prompt", fields.get("negative_prompt"))
    return body


def with_source(body: dict[str, Any], source_asset_id: str) -> dict[str, Any]:
    """`body` with the uploaded source named."""
    return {**body, "source_audio_asset_id": source_asset_id}
