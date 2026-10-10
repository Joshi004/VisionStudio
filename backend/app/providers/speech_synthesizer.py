"""The speech adapter: Breeze TTS 2 on the GPU server (Phase 21).

Uploading a reference recording, polling the job and downloading its result are the calls every
backend shares (`gpu_server.py`). What is specific to Breeze TTS lives here:

- `build_body`: `POST /v1/breeze-tts/synthesize` takes `text` and, depending on which of the
  other fields are sent, makes one of three kinds of speech:
  - **design**: `text` (and an `instruction`, a description of the voice). No recording.
  - **clone**: `text`, `reference_audio_asset_id` and `reference_text` (the exact words of the
    recording). The reference voice speaks `text`.
  - **direction**: clone plus an `instruction` that steers tone, emotion and pace.
- The answer is a mono 24 kHz WAV, downloaded with `gpu_server.download_result`.

The limits below are the ones the server's OpenAPI document declares for `SynthesizeRequest`.
The server cuts a request that would make more than about two minutes of speech, so the text of
a long script is split into several requests (`services/speech_chunks.py`).

Breeze TTS 2's weights and its outputs are licensed for research and non-commercial use only.
"""

from __future__ import annotations

from typing import Any, Final

from app.providers import gpu_server

SYNTHESIZE_PATH: Final = "/v1/breeze-tts/synthesize"

TEXT_MAX_CHARS: Final = 1000
INSTRUCTION_MAX_CHARS: Final = 500
REFERENCE_TEXT_MAX_CHARS: Final = 1000
SEED_MAX: Final = 2147483647
DEFAULT_SEED: Final = 42
CFG_SCALE_MAX: Final = 10.0
# The server recommends 4 whenever an instruction is sent, and 1 otherwise.
CFG_SCALE_PLAIN: Final = 1.0
CFG_SCALE_WITH_INSTRUCTION: Final = 4.0


def default_cfg_scale(instruction: str | None) -> float:
    """The guidance the server recommends: 4 with an instruction, else 1."""
    return CFG_SCALE_WITH_INSTRUCTION if instruction and instruction.strip() else CFG_SCALE_PLAIN


def build_body(
    *,
    text: str,
    instruction: str | None,
    reference_remote_id: str | None,
    reference_text: str | None,
    seed: int,
    cfg_scale: float,
    partition: str,
) -> dict[str, Any]:
    """The request body. A blank `instruction` and a blank `partition` are not sent.

    The reference recording and its transcript go together: sending only one is a ValueError
    here, because the server answers 422 for it.
    """
    if (reference_remote_id is None) != (reference_text is None):
        raise ValueError("The reference recording and its transcript are sent together.")
    body: dict[str, Any] = {"text": text, "seed": seed, "cfg_scale": cfg_scale}
    if instruction is not None and instruction.strip():
        body["instruction"] = instruction.strip()
    if reference_remote_id is not None and reference_text is not None:
        body["reference_audio_asset_id"] = reference_remote_id
        body["reference_text"] = reference_text
    if partition:
        body["partition"] = partition
    return body


async def submit(base_url: str, body: dict[str, Any]) -> str:
    """Submits the speech and returns the server's job id.

    Raises `gpu_server.GpuCallError`.
    """
    return await gpu_server.submit_job(base_url, SYNTHESIZE_PATH, body)
