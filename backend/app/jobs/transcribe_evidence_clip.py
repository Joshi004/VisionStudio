"""The `transcribe_evidence_clip` job: what is said in a sound bite clip, and how well does it match
the quote? (SB-006, `Sound_bite_implementation_phases.md` §4.6)

It is `time_speech_words` for the audio of an imported `video` piece: the clip's sound goes to
Parakeet on the GPU server, and the heard words are compared with the claim's words
(`services/soundbite_analysis.py`). The upload, the polling and the download are the parent's;
what is sent and where the result goes differ:

- `start`: if another item of the project holds the same clip file and has heard words, they are
  used and nothing is sent. Otherwise the sound is taken out of the stored clip as a mono 16 kHz
  WAV, uploaded, and its transcription submitted.
- `finish` (the parent's): download the transcript, then `_match_and_store` here.

**Input:** `{requested, evidence_item_id}` (after the submit also what the parent adds: the
server's URL, the upload and the request body). **Output:** `{evidence_item_id, processing_time,
reused, fidelity, words, flags}`.

The result is the item's `heard_words`, `fidelity`, `proposed_trim` and `flags`, written in the
same transaction that finishes the job. An empty transcript is a valid answer (fidelity
`mismatch`, flag `no_speech`), not a failed job. A job that fails leaves the clip usable with no
heard words; the review offers "Transcribe again".

A remote job with `resume`: after a restart a submitted job keeps being polled, an unsubmitted
one is queued again. Not in `store.REMOTE_CANCEL_TYPES`, like `time_speech_words`: it runs for
seconds. Logs hold ids, never the words.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Job
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.time_speech_words import (
    PARTITION_KEY,
    TRANSCRIPTION_URL_KEY,
    TimeSpeechWordsHandler,
    processing_time,
)
from app.providers import transcriber
from app.services import gpu_priority, soundbite_clips
from app.services.soundbite_analysis import HeardWord
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = soundbite_clips.JOB_TYPE


class TranscribeEvidenceClipHandler(TimeSpeechWordsHandler):
    job_type = JOB_TYPE
    target_key = soundbite_clips.DEDUPE_KEY

    # --- start: reuse, or take out the sound, upload and submit ------------------------------

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            recorded = dict(job.input) if isinstance(job.input, dict) else {}
            item_id = recorded.get(self.target_key)
            inputs = (
                await soundbite_clips.load_inputs(session, item_id)
                if isinstance(item_id, int)
                else None
            )
            reused = (
                await soundbite_clips.reusable_words(session, item_id)
                if inputs is not None and isinstance(item_id, int)
                else None
            )
            base_url = await settings_service.get_str(session, TRANSCRIPTION_URL_KEY)
            partition = await settings_service.get_str(session, PARTITION_KEY)
            priority = await gpu_priority.level_for(session, job)  # SCN-002
            await session.commit()

        if inputs is None or not isinstance(item_id, int):
            await self._fail(job_id, "The clip this transcription was queued for is gone.")
            return
        if reused is not None:
            await self._analyse_and_finish(job_id, inputs, reused, None, reused=True)
            return

        storage = get_storage()
        try:
            clip = storage.get_path(inputs.video_path)
        except StorageError:
            await self._fail(job_id, "The clip file could not be found on disk.")
            return
        if not clip.is_file():
            await self._fail(job_id, "The clip file could not be found on disk.")
            return

        await self._phase(job_id, phases.UPLOADING_CLIP_FOR_TRANSCRIPT)
        wav = storage.new_temp_path("wav")
        filename = f"clip-{item_id}.wav"
        try:
            try:
                await soundbite_clips.extract_wav(clip, wav)
            except soundbite_clips.SoundbiteClipError as exc:
                await self._fail(job_id, str(exc))
                return
            sent = await self._upload_and_submit(
                job_id,
                wav,
                filename,
                base_url,
                partition,
                priority,
                upload_phase=phases.UPLOADING_CLIP_FOR_TRANSCRIPT,
            )
        finally:
            wav.unlink(missing_ok=True)
        if sent is None:
            return
        remote_asset_id, provider_job_id = sent

        submitted = {
            **recorded,
            "server_url": docker_mapped(base_url),
            "upload": {"filename": filename, "remote_asset_id": remote_asset_id},
            "endpoint": transcriber.TRANSCRIBE_PATH,
            "body": transcriber.build_body(remote_asset_id, partition, priority),
        }
        async with SessionLocal() as session:
            await store.mark_submitted(session, job_id, provider_job_id, submitted)

    # --- finish: compare, trim, flag, store --------------------------------------------------

    async def _match_and_store(
        self, job: Job, body: dict[str, Any], spoken: list[transcriber.SpokenWord]
    ) -> bool:
        recorded = job.input if isinstance(job.input, dict) else {}
        item_id = recorded.get(self.target_key)
        async with SessionLocal() as session:
            inputs = (
                await soundbite_clips.load_inputs(session, item_id)
                if isinstance(item_id, int)
                else None
            )
            await session.commit()
        if inputs is None:
            await self._fail(job.id, "The clip this transcription was made for is gone.")
            return False
        await self._phase(job.id, phases.MATCHING_WORDS)
        words = [HeardWord(word.word, word.start, word.end) for word in spoken]
        return await self._analyse_and_finish(
            job.id, inputs, words, processing_time(body), reused=False
        )

    async def _analyse_and_finish(
        self,
        job_id: int,
        inputs: soundbite_clips.ClipInputs,
        words: list[HeardWord],
        seconds: float | None,
        *,
        reused: bool,
    ) -> bool:
        """Analyses the heard words and saves the result with the finished job. True when the job
        finished."""
        try:
            analysis = await soundbite_clips.compute(inputs, words)
        except soundbite_clips.SoundbiteClipError as exc:
            await self._fail(job_id, str(exc))
            return False

        async with SessionLocal() as session:
            if not await soundbite_clips.store_result(session, inputs.item_id, analysis):
                await store.fail_job(
                    session, job_id, "The clip this transcription was made for is gone."
                )
                return False
            output = {
                "evidence_item_id": inputs.item_id,
                "processing_time": seconds,
                "reused": reused,
                "fidelity": analysis.fidelity,
                "words": len(words),
                "flags": [flag["code"] for flag in analysis.flags],
            }
            # The result and the finished job are saved together or not at all.
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                _logger.warning("job %d: clip analysed but the job is not running", job_id)
                return False
            await session.commit()
        _logger.info(
            "job %d: clip of item %d transcribed: fidelity=%s words=%d reused=%s",
            job_id,
            inputs.item_id,
            analysis.fidelity,
            len(words),
            reused,
        )
        return True
