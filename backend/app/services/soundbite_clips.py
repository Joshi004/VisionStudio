"""A sound bite clip after import: its transcription job, its analysis and its status (SB-006).

`services/evidence_import.py` queues one `transcribe_evidence_clip` job for every usable `video`
piece of a sound bite claim (`queue`). The job (`jobs/transcribe_evidence_clip.py`) sends the
clip's audio to Parakeet and then calls `compute` and `store_result` here: the heard words are
compared with the claim (`services/soundbite_analysis.py`) and the result is written on the
`evidence_item` row: `heard_words`, `fidelity`, `proposed_trim` and `flags`.

**What the transcription of a clip is for.** The agent's quote and YouTube's captions only found
the moment. The words are proved by what the app itself heard (SB-6).

**Reuse.** The audio of a clip with the same `video_sha256` is transcribed once per project: a
later import of the same clip takes the heard words of the earlier item and sends nothing to the
server. The comparison with the claim and the trim are worked out again each time.

**A failed transcription** leaves the piece usable, with no heard words. It is shown as failed
with the reason, and `retry` queues a new job. The review (SB-007) will not accept a clip that has
no heard words.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvidenceImport, EvidenceItem, EvidenceRound, Job
from app.jobs import store
from app.services import ffmpeg, soundbite_analysis
from app.services.soundbite_analysis import Analysis, HeardWord
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "transcribe_evidence_clip"
# The key of the job's input that names the clip. Two presses on one clip make one job.
DEDUPE_KEY: Final = "evidence_item_id"

# The audio sent to Parakeet and measured for the trim: mono, 16 kHz.
AUDIO_RATE: Final = 16000
EXTRACT_TIMEOUT_S: Final = 120.0
# The most audio read for the trim. The window is at most 90 s (checked on import).
MAX_AUDIO_S: Final = 100.0
MAX_CAPTIONS_BYTES: Final = 5 * 1024 * 1024

# `none`: no transcription asked for (a video that is only context). `in_progress`: its job is
# queued or running. `failed`: its newest job failed or was cancelled. `done`: heard words stored.
Status = Literal["none", "in_progress", "failed", "done"]


class SoundbiteClipError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- Queueing and status -----------------------------------------------------------------------


async def queue(session: AsyncSession, item: EvidenceItem, *, commit: bool = False) -> Job:
    """Queues the transcription of one stored clip (the item must have its id) and notes the job
    on the item. Two calls make one job while it is active. With `commit=False` the job and the
    item's change are only flushed, so the import saves them with its rows.
    """
    job, _created = await store.create_job(
        session,
        project_id=item.project_id,
        type=JOB_TYPE,
        provider="gpu",
        input={"requested": JOB_TYPE, DEDUPE_KEY: item.id},
        commit=False,
        dedupe_key=DEDUPE_KEY,
    )
    item.transcribe_job_id = job.id
    if commit:
        await session.commit()
    else:
        await session.flush()
    return job


def transcription_status(item: EvidenceItem, job: Job | None) -> tuple[Status, str | None]:
    """Where the transcription of a clip stands, and why it failed. Worked out on every read."""
    if item.heard_words is not None:
        return "done", None
    if job is None:
        return "none", None
    if job.status in store.ACTIVE_STATUSES:
        return "in_progress", None
    if job.status == "succeeded":
        return "failed", "The transcription finished without a result."
    if job.error:
        return "failed", job.error
    return "failed", "The transcription was cancelled." if job.status == "cancelled" else (
        "The transcription failed."
    )


async def jobs_of(session: AsyncSession, items: list[EvidenceItem]) -> dict[int, Job]:
    """The transcription job of each item that has one, by the item's id."""
    ids = {item.transcribe_job_id for item in items if item.transcribe_job_id is not None}
    if not ids:
        return {}
    rows = await session.execute(
        select(Job).where(Job.id.in_(ids)).execution_options(populate_existing=True)
    )
    by_id = {job.id: job for job in rows.scalars()}
    return {
        item.id: by_id[item.transcribe_job_id] for item in items if item.transcribe_job_id in by_id
    }


# --- What the job works from -------------------------------------------------------------------


@dataclass(frozen=True)
class ClipInputs:
    """What the analysis of one clip needs, read once so no session is held while it runs."""

    item_id: int
    video_path: str
    captions_path: str | None
    quote: str
    near_s: float | None
    brief_entry: dict[str, Any]
    source: dict[str, Any]
    capture: dict[str, Any]


async def load_inputs(session: AsyncSession, item_id: int) -> ClipInputs | None:
    """The inputs of a clip's analysis, or None when the item or its brief entry is gone."""
    item = await session.get(EvidenceItem, item_id)
    if item is None or item.video_path is None:
        return None
    round_brief = (
        await session.execute(
            select(EvidenceRound.brief)
            .join(EvidenceImport, EvidenceImport.round_id == EvidenceRound.id)
            .where(EvidenceImport.id == item.import_id)
        )
    ).scalar_one_or_none()
    claims = round_brief.get("claims") if isinstance(round_brief, dict) else None
    entry = next(
        (
            claim
            for claim in (claims if isinstance(claims, list) else [])
            if isinstance(claim, dict) and claim.get("id") == item.claim_id
        ),
        None,
    )
    if entry is None or not isinstance(entry.get("text"), str):
        return None
    capture = dict(item.capture) if isinstance(item.capture, dict) else {}
    window = capture.get("window") if isinstance(capture.get("window"), dict) else {}
    at = capture.get("quote_at_s") if isinstance(capture.get("quote_at_s"), dict) else {}
    start, window_start = at.get("start"), window.get("start_s")
    near_s = (
        float(start) - float(window_start)
        if isinstance(start, int | float) and isinstance(window_start, int | float)
        else None
    )
    return ClipInputs(
        item_id=item.id,
        video_path=item.video_path,
        captions_path=item.captions_path,
        quote=entry["text"],
        near_s=near_s,
        brief_entry=dict(entry),
        source=dict(item.source) if isinstance(item.source, dict) else {},
        capture=capture,
    )


async def reusable_words(session: AsyncSession, item_id: int) -> list[HeardWord] | None:
    """The heard words of another item of the project with the same clip file, or None. Nothing
    is sent to the server for a clip that was transcribed before."""
    item = await session.get(EvidenceItem, item_id)
    if item is None or item.video_sha256 is None:
        return None
    donor = (
        (
            await session.execute(
                select(EvidenceItem)
                .where(
                    EvidenceItem.project_id == item.project_id,
                    EvidenceItem.video_sha256 == item.video_sha256,
                    EvidenceItem.id != item.id,
                    EvidenceItem.heard_words.is_not(None),
                )
                .order_by(EvidenceItem.id.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return words_of(donor.heard_words) if donor is not None else None


def words_of(heard_words: Any) -> list[HeardWord]:
    """The words of a stored `heard_words` value."""
    raw = heard_words.get("words") if isinstance(heard_words, dict) else None
    words: list[HeardWord] = []
    for entry in raw if isinstance(raw, list) else []:
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("text"), str)
            and isinstance(entry.get("start"), int | float)
            and isinstance(entry.get("end"), int | float)
        ):
            words.append(HeardWord(entry["text"], float(entry["start"]), float(entry["end"])))
    return words


# --- Audio and analysis ------------------------------------------------------------------------


def _extract_args(source: Path, dest: Path) -> list[str]:
    return [
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-n",
        "-i",
        ffmpeg.file_input(source),
        "-vn",
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(AUDIO_RATE),
        "-c:a",
        "pcm_s16le",
        ffmpeg.file_input(dest),
    ]


async def extract_wav(source: Path, dest: Path) -> None:
    """Writes the clip's sound as a mono 16 kHz WAV into the new file `dest`. Raises
    SoundbiteClipError."""
    try:
        result = await ffmpeg.run_tool(
            "ffmpeg", _extract_args(source, dest), timeout_s=EXTRACT_TIMEOUT_S
        )
    except ffmpeg.ToolError as exc:
        raise SoundbiteClipError(f"The clip's sound could not be taken out: {exc}") from exc
    if result.returncode != 0 or not dest.is_file():
        raise SoundbiteClipError("The clip's sound could not be taken out.")


def _read_json(path: Path) -> Any:
    with path.open("rb") as handle:
        data = handle.read(MAX_CAPTIONS_BYTES + 1)
    if len(data) > MAX_CAPTIONS_BYTES:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


async def compute(inputs: ClipInputs, words: list[HeardWord]) -> Analysis:
    """Decodes the clip's audio and analyses it with the heard words. Raises SoundbiteClipError
    when the files cannot be read."""
    storage = get_storage()
    try:
        video = storage.get_path(inputs.video_path)
        captions_file = (
            storage.get_path(inputs.captions_path) if inputs.captions_path is not None else None
        )
    except StorageError as exc:
        raise SoundbiteClipError("The clip file could not be found on disk.") from exc
    if not video.is_file():
        raise SoundbiteClipError("The clip file could not be found on disk.")
    raw = await ffmpeg.decode_mono_float(video, AUDIO_RATE, max_seconds=MAX_AUDIO_S)
    if raw is None:
        raise SoundbiteClipError("The clip's sound could not be read.")
    samples = np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<f4").astype(np.float32)
    captions = None
    if captions_file is not None and captions_file.is_file():
        captions = await asyncio.to_thread(_read_json, captions_file)
    return await asyncio.to_thread(
        soundbite_analysis.analyse,
        quote=inputs.quote,
        words=words,
        samples=samples,
        rate=AUDIO_RATE,
        duration_s=len(samples) / AUDIO_RATE,
        near_s=inputs.near_s,
        brief_entry=inputs.brief_entry,
        source=inputs.source,
        capture=inputs.capture,
        captions=captions,
    )


async def store_result(session: AsyncSession, item_id: int, analysis: Analysis) -> bool:
    """Writes an analysis on its item (flushed, not committed: the job commits it with finishing
    itself). False when the item is gone."""
    item = await session.get(EvidenceItem, item_id)
    if item is None:
        return False
    item.heard_words = analysis.heard_words
    item.fidelity = analysis.fidelity
    item.proposed_trim = analysis.proposed_trim
    item.flags = analysis.flags
    await session.flush()
    return True
