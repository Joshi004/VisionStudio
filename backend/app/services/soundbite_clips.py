"""A sound bite clip after import: its words, its analysis and its cut (SB-006).

`services/evidence_import.py` calls `analyse_now` for every usable `video` piece of a sound bite
claim, with the rows it makes. The clip's words are the words of the source's captions that the
capture tool kept (`soundbite_analysis.words_from_captions`); nothing is sent to a server. The
words are compared with the claim (`services/soundbite_analysis.py`) and the result is written on
the `evidence_item` row: `heard_words`, `fidelity`, `proposed_trim` and `flags`.

**What the words are for.** They find the quote in the clip and give the cut and the clip's
captions their places. They are not proved by the app: the owner listens to the clip and decides
whether the words are said properly when accepting it (SB-007).

**A clip whose words cannot be made** (no captions file, or the sound cannot be read) stays usable
with no words. The review will not accept a clip that has no words, so the owner rejects it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvidenceImport, EvidenceItem, EvidenceRound
from app.services import ffmpeg, soundbite_analysis
from app.services.soundbite_analysis import Analysis, HeardWord
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

# The audio measured for the trim: mono, 16 kHz.
AUDIO_RATE: Final = 16000
# The most audio read for the trim. The window is at most 90 s (checked on import).
MAX_AUDIO_S: Final = 100.0
MAX_CAPTIONS_BYTES: Final = 5 * 1024 * 1024


class SoundbiteClipError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- What the analysis works from --------------------------------------------------------------


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


def _read_json(path: Path) -> Any:
    with path.open("rb") as handle:
        data = handle.read(MAX_CAPTIONS_BYTES + 1)
    if len(data) > MAX_CAPTIONS_BYTES:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


async def compute(inputs: ClipInputs) -> Analysis:
    """Decodes the clip's audio, takes the clip's words from the source's captions and analyses
    them. Raises SoundbiteClipError when the files cannot be read."""
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
    if captions_file is None or not captions_file.is_file():
        raise SoundbiteClipError("The clip has no captions file, so it has no words.")
    captions = await asyncio.to_thread(_read_json, captions_file)
    if captions is None:
        raise SoundbiteClipError("The clip's captions could not be read.")
    window = inputs.capture.get("window")
    window_start = window.get("start_s") if isinstance(window, dict) else None
    if isinstance(window_start, bool) or not isinstance(window_start, int | float):
        raise SoundbiteClipError("The clip does not say where it starts in the video.")
    raw = await ffmpeg.decode_mono_float(video, AUDIO_RATE, max_seconds=MAX_AUDIO_S)
    if raw is None:
        raise SoundbiteClipError("The clip's sound could not be read.")
    samples = np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<f4").astype(np.float32)
    duration_s = len(samples) / AUDIO_RATE
    words = soundbite_analysis.words_from_captions(captions, float(window_start), duration_s)
    return await asyncio.to_thread(
        soundbite_analysis.analyse,
        quote=inputs.quote,
        words=words,
        samples=samples,
        rate=AUDIO_RATE,
        duration_s=duration_s,
        near_s=inputs.near_s,
        brief_entry=inputs.brief_entry,
        source=inputs.source,
        capture=inputs.capture,
        captions=captions,
    )


async def analyse_now(session: AsyncSession, item: EvidenceItem) -> None:
    """Works out the words, the match, the cut and the flags of one stored clip (the item must
    have its id) and writes them on the item. Flushed, not committed: the import saves them with
    its rows. A clip that cannot be analysed keeps no words; the reason is logged (ids only,
    never the words)."""
    inputs = await load_inputs(session, item.id)
    if inputs is None:
        _logger.warning("clip of item %d has no brief entry or no video file", item.id)
        return
    try:
        analysis = await compute(inputs)
    except SoundbiteClipError as exc:
        _logger.warning("clip of item %d has no words: %s", item.id, exc)
        return
    await store_result(session, item.id, analysis)
    _logger.info(
        "clip of item %d analysed: fidelity=%s words=%d",
        item.id,
        analysis.fidelity,
        len(analysis.heard_words.get("words", [])),
    )


async def trim_for(item: EvidenceItem, first: int, last: int) -> dict[str, Any]:
    """The cut for a clip whose quote runs from word `first` to word `last` (the owner's choice
    in the review): `{in_s, out_s, in_clean, out_clean}`, found in the clip's own audio exactly
    as the proposed cut is. Raises SoundbiteClipError when the clip has no words, a position is
    not a word, or the files cannot be read.
    """
    words = words_of(item.heard_words)
    if not words:
        raise SoundbiteClipError("This clip has no words yet, so it cannot be trimmed.")
    if not 0 <= first <= last < len(words):
        raise SoundbiteClipError("The start and end words are not words of this clip.")
    if item.video_path is None:
        raise SoundbiteClipError("The clip file could not be found on disk.")
    try:
        video = get_storage().get_path(item.video_path)
    except StorageError as exc:
        raise SoundbiteClipError("The clip file could not be found on disk.") from exc
    if not video.is_file():
        raise SoundbiteClipError("The clip file could not be found on disk.")
    raw = await ffmpeg.decode_mono_float(video, AUDIO_RATE, max_seconds=MAX_AUDIO_S)
    if raw is None:
        raise SoundbiteClipError("The clip's sound could not be read.")
    samples = np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<f4").astype(np.float32)
    trim = await asyncio.to_thread(
        soundbite_analysis.propose_trim,
        samples,
        AUDIO_RATE,
        words,
        first,
        last,
        len(samples) / AUDIO_RATE,
    )
    if trim is None:
        raise SoundbiteClipError("The clip's sound is too short to find a cut in.")
    return trim


async def store_result(session: AsyncSession, item_id: int, analysis: Analysis) -> bool:
    """Writes an analysis on its item (flushed, not committed). False when the item is gone."""
    item = await session.get(EvidenceItem, item_id)
    if item is None:
        return False
    item.heard_words = analysis.heard_words
    item.fidelity = analysis.fidelity
    item.proposed_trim = analysis.proposed_trim
    item.flags = analysis.flags
    await session.flush()
    return True
