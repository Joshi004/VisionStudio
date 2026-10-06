"""The transcription adapter: Parakeet on the GPU server (ANALYSIS.md Section 5.1 and 6.4).

`Transcriber` is split into steps, because the dispatcher saves the server's job id and
resumes after a restart. Uploading the voiceover, polling the job and downloading its
result are the calls every backend shares (`gpu_server.py`). What is specific to
transcription lives here:

- `submit`: `POST /v1/parakeet/transcribe` with `{"audio_asset_id": ...}`. There is no
  language field (Parakeet detects it) and no seed (the same input gives the same output).
- `parse_result`: checks that the downloaded transcript has the documented shape.

The transcription URL setting decides which server these calls go to. A blank value means
the GPU server URL.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

from app.providers import gpu_server

TRANSCRIBE_PATH: Final = "/v1/parakeet/transcribe"

# The file types the server accepts (ANALYSIS.md Section 5.1). It judges by the extension of
# the uploaded file name and answers 400 for anything else.
PARAKEET_EXTENSIONS: Final = frozenset(
    {
        "3gp",
        "aac",
        "aif",
        "aiff",
        "amr",
        "avi",
        "caf",
        "flac",
        "m4a",
        "mkv",
        "mov",
        "mp3",
        "mp4",
        "ogg",
        "opus",
        "wav",
        "webm",
        "wma",
    }
)


@dataclass(frozen=True)
class SpokenWord:
    """One word the recogniser heard, with its time in seconds."""

    word: str
    start: float
    end: float


def build_body(remote_asset_id: str, partition: str) -> dict[str, Any]:
    """The request body. `partition` is sent only when the setting is not blank."""
    body: dict[str, Any] = {"audio_asset_id": remote_asset_id}
    if partition:
        body["partition"] = partition
    return body


async def submit(base_url: str, remote_asset_id: str, partition: str) -> str:
    """Submits the transcription and returns the server's job id.

    Raises `gpu_server.GpuCallError`.
    """
    return await gpu_server.submit_job(
        base_url, TRANSCRIBE_PATH, build_body(remote_asset_id, partition)
    )


def _seconds(value: object) -> float | None:
    # bool is a subclass of int in Python, but `true` is not a time.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def parse_result(body: object) -> list[SpokenWord]:
    """The spoken words of a downloaded transcript, in the order they were heard.

    Checks the documented shape (ANALYSIS.md Section 5.1): `word_timestamps` is a list of
    `{word, start, end}` with times in seconds. Raises `ValueError` with a message meant
    for the user when it is not. An empty list is a valid answer: a recording with no
    detected speech. Times are not required to increase strictly, because the recogniser
    sometimes returns a zero-length word or a word that starts before the previous one
    ended; an `end` before its own `start` is lifted to the `start`.
    """
    if not isinstance(body, dict):
        raise ValueError("The transcript is not a JSON object.")
    raw_words = body.get("word_timestamps")
    if not isinstance(raw_words, list):
        raise ValueError("The transcript has no word_timestamps list.")

    words: list[SpokenWord] = []
    for position, item in enumerate(raw_words, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("word"), str):
            raise ValueError(f"Word {position} of the transcript has no text.")
        start = _seconds(item.get("start"))
        end = _seconds(item.get("end"))
        if start is None or end is None:
            raise ValueError(f"Word {position} of the transcript has no valid start and end time.")
        words.append(SpokenWord(word=item["word"], start=start, end=max(start, end)))
    return words
