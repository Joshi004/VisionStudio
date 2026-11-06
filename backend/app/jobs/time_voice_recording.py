"""The `time_voice_recording` job: when is each script word of a full recording spoken? (REC-004)

It is `time_speech_words` for the recording of the whole script of a recorded explainer: the
recording goes to Parakeet and the heard words are matched to the whole script
(`word_timings.align`). Two things differ from the parent, which does the polling and the
download:

- **A recording of any length (R-6).** The recording is cut at silences into pieces of at most
  `recording_transcription_piece_s` seconds (a short one is a single piece, sent whole). The
  pieces are sent one after the other: when a piece is transcribed, its words are added to
  `job.input.heard` with the piece's start added to every time, and the job is put back in the
  queue to send the next one. `job.input.pieces` holds the plan and `job.input.done` the
  server's job ids of the pieces that are transcribed, so a restart goes on with the first piece
  that is not.
- **Where the result goes.** After the last piece, the words are matched to the whole script and
  stored as the recording's `voice_recording_timing` row, with a per-word `heard` flag. In the
  same transaction that finishes the job, the split job is queued when the match is good and no
  scene boundary is tight (`services/full_recordings.py`).

A recording whose heard words match the script too little gets estimated timing, which means the
recording is refused (R-5): the panel says so and the owner records it again. The job itself
finishes. Logs hold ids, never the text.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Job, VoiceRecording, VoiceRecordingTiming
from app.db.session import SessionLocal
from app.jobs import dispatcher, phases, store
from app.jobs.time_speech_words import (
    PARTITION_KEY,
    TRANSCRIPTION_URL_KEY,
    TimeSpeechWordsHandler,
    processing_time,
)
from app.providers import transcriber
from app.services import (
    ffmpeg,
    full_recordings,
    gpu_priority,
    recording_boundaries,
    speech_audio,
    word_timings,
)
from app.services.recording_boundaries import BoundaryError
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

_ROUND_DIGITS: Final = 3


def read_pieces(value: object) -> list[tuple[float, float]] | None:
    """The plan on the job's input, or None when there is none yet or it cannot be used."""
    if not isinstance(value, list) or not value:
        return None
    pieces: list[tuple[float, float]] = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or any(
                isinstance(number, bool) or not isinstance(number, int | float) for number in item
            )
        ):
            return None
        pieces.append((float(item[0]), float(item[1])))
    return pieces


def _strings(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _heard_words(value: object) -> list[list[Any]]:
    """The words of the pieces that are transcribed: `[word, start, end]`."""
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, list) and len(item) == 3 and isinstance(item[0], str)
    ]


class TimeVoiceRecordingHandler(TimeSpeechWordsHandler):
    job_type = full_recordings.TIMING_JOB_TYPE
    target_key = full_recordings.DEDUPE_KEY

    async def _speech_path(self, session: AsyncSession, target_id: object) -> str | None:
        recording = (
            await session.get(VoiceRecording, target_id) if isinstance(target_id, int) else None
        )
        return recording.path if recording is not None else None

    # --- start: plan the pieces, send the next one ---------------------------------------------

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            recorded = dict(job.input) if isinstance(job.input, dict) else {}
            recording_id = recorded.get(self.target_key)
            recording = (
                await session.get(VoiceRecording, recording_id)
                if isinstance(recording_id, int)
                else None
            )
            base_url = await settings_service.get_str(session, TRANSCRIPTION_URL_KEY)
            partition = await settings_service.get_str(session, PARTITION_KEY)
            piece_s = await settings_service.get_int(
                session, settings_service.RECORDING_TRANSCRIPTION_PIECE_S_KEY
            )
            priority = await gpu_priority.level_for(session, job)  # SCN-002
            await session.commit()

        if recording is None:
            await self._fail(job_id, "The recording this timing was queued for is gone.")
            return
        storage = get_storage()
        try:
            path = storage.get_path(recording.path)
        except StorageError:
            await self._fail(job_id, "The recording file could not be found on disk.")
            return
        if not path.is_file():
            await self._fail(job_id, "The recording file could not be found on disk.")
            return

        pieces = read_pieces(recorded.get("pieces"))
        if pieces is None:
            pieces = await self._plan_pieces(job_id, path, recording.duration_s, piece_s)
            if pieces is None:
                return
            recorded["pieces"] = [[start, end] for start, end in pieces]
            recorded["done"] = []
            recorded["heard"] = []
            async with SessionLocal() as session:
                if not await store.update_input(session, job_id, recorded):
                    return

        done = _strings(recorded.get("done"))
        index = len(done)
        if index >= len(pieces):
            await self._fail(job_id, "Every piece of the recording is transcribed already.")
            return
        part, parts = index + 1, len(pieces)
        start_s, end_s = pieces[index]

        filename = f"recording-{recording.id}-part-{part}.wav"
        temp = None
        try:
            if parts == 1:
                upload_path = path  # a short recording is sent whole, as it is stored
            else:
                await self._phase(
                    job_id, phases.speech_part(phases.CUTTING_RECORDING_PIECE, part, parts)
                )
                temp = storage.new_temp_path("wav")
                try:
                    await speech_audio.cut_window(path, temp, start_s, end_s, end_s - start_s)
                except speech_audio.PadError as exc:
                    await self._fail(job_id, str(exc))
                    return
                upload_path = temp
            sent = await self._upload_and_submit(
                job_id,
                upload_path,
                filename,
                base_url,
                partition,
                priority,
                upload_phase=phases.speech_part(
                    phases.UPLOADING_SPEECH_FOR_TRANSCRIPT, part, parts
                ),
                submit_phase=phases.speech_part(phases.SUBMITTING, part, parts),
            )
        finally:
            if temp is not None:
                storage.discard(temp)
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

    async def _plan_pieces(
        self, job_id: int, path: Any, duration_s: float, piece_s: int
    ) -> list[tuple[float, float]] | None:
        """Cuts the recording into pieces at its silences. A recording that fits one piece needs
        no search. None when the search failed: the job is then failed.
        """
        if duration_s <= piece_s:
            return recording_boundaries.transcription_pieces(duration_s, [], piece_s)
        await self._phase(job_id, phases.FINDING_RECORDING_PAUSES)
        silences = await ffmpeg.find_silences(path, duration_s)
        if silences is None:
            await self._fail(job_id, "The recording could not be searched for pauses.")
            return None
        return recording_boundaries.transcription_pieces(duration_s, silences, piece_s)

    # --- finish: add the piece, send the next or store -----------------------------------------

    async def _match_and_store(
        self, job: Job, body: dict[str, Any], spoken: list[transcriber.SpokenWord]
    ) -> bool:
        recorded = dict(job.input) if isinstance(job.input, dict) else {}
        pieces = read_pieces(recorded.get("pieces"))
        provider_job_id = job.provider_job_id
        if pieces is None or provider_job_id is None:
            await self._fail(job.id, "The plan of this recording's pieces is missing.")
            return False
        done = _strings(recorded.get("done"))

        # A repeat of this call (the job was cut short after the piece was added) finds the
        # piece already in the list.
        if provider_job_id not in done:
            if len(done) >= len(pieces):
                await self._fail(job.id, "The server answered for a piece that is not in the plan.")
                return False
            offset = pieces[len(done)][0]
            recorded["heard"] = [
                *_heard_words(recorded.get("heard")),
                *(
                    [
                        word.word,
                        round(word.start + offset, _ROUND_DIGITS),
                        round(word.end + offset, _ROUND_DIGITS),
                    ]
                    for word in spoken
                ),
            ]
            recorded["done"] = [*done, provider_job_id]
            async with SessionLocal() as session:
                if not await store.update_input(session, job.id, recorded):
                    return False
            done = recorded["done"]

        if len(done) < len(pieces):
            async with SessionLocal() as session:
                await store.requeue(session, job.id, phases.NEXT_RECORDING_PIECE)
            dispatcher.nudge()
            return True
        return await self._store_timing(job, body, recorded, len(pieces))

    async def _store_timing(
        self, job: Job, body: dict[str, Any], recorded: dict[str, Any], piece_count: int
    ) -> bool:
        """Matches all the heard words to the script and saves the result with the finished job.
        True when the job finished.
        """
        recording_id = recorded.get(self.target_key)
        async with SessionLocal() as session:
            recording = (
                await session.get(VoiceRecording, recording_id)
                if isinstance(recording_id, int)
                else None
            )
            if recording is None:
                await store.fail_job(
                    session, job.id, "The recording this timing was made for is gone."
                )
                return False
            existing = (
                (
                    await session.execute(
                        select(VoiceRecordingTiming).where(
                            VoiceRecordingTiming.voice_recording_id == recording.id
                        )
                    )
                )
                .scalars()
                .first()
            )
            output: dict[str, Any] = {
                "voice_recording_id": recording.id,
                "processing_time": processing_time(body),
                "pieces": piece_count,
            }
            if existing is not None:
                # Timed by an earlier job in the meantime: its result stands.
                output["timing"] = {"kept": existing.id}
            else:
                await self._add_timing(session, job, recording, recorded, output)
            # The result and the finished job are saved together or not at all.
            if not await store.finish_job(session, job.id, output):
                await session.rollback()
                _logger.warning("job %d: words matched but the job is not running", job.id)
                return False
            await session.commit()
        if "split_job_id" in output:
            dispatcher.nudge()
        return True

    @staticmethod
    async def _add_timing(
        session: AsyncSession,
        job: Job,
        recording: VoiceRecording,
        recorded: dict[str, Any],
        output: dict[str, Any],
    ) -> None:
        """Adds the recording's timing row and, when every boundary is clean, queues the split.
        Fills `output`.
        """
        threshold = await settings_service.get_int(
            session, settings_service.WORD_TIMING_MATCH_THRESHOLD_KEY
        )
        spoken = [
            transcriber.SpokenWord(word=item[0], start=float(item[1]), end=float(item[2]))
            for item in _heard_words(recorded.get("heard"))
        ]
        alignment = word_timings.align(recording.text, spoken, recording.duration_s, threshold)
        timing = VoiceRecordingTiming(
            project_id=recording.project_id,
            voice_recording_id=recording.id,
            source=alignment.source,
            match_percent=alignment.match_percent,
            threshold=threshold,
            words=[
                {**word, "heard": heard}
                for word, heard in zip(alignment.words, alignment.heard, strict=True)
            ],
            heard_text=alignment.heard_text,
            job_id=job.id,
        )
        session.add(timing)
        await session.flush()
        output["timing"] = {
            "source": alignment.source,
            "match_percent": alignment.match_percent,
            "threshold": threshold,
            "words": len(alignment.words),
        }
        _logger.info(
            "job %d: recording %d timed: source=%s match=%s%% (needed %s%%)",
            job.id,
            recording.id,
            alignment.source,
            alignment.match_percent,
            threshold,
        )
        if alignment.source != word_timings.SOURCE_PARAKEET:
            return  # refused: the owner records it again
        min_pause_ms = await settings_service.get_int(
            session, settings_service.RECORDING_MIN_BOUNDARY_PAUSE_MS_KEY
        )
        try:
            found = full_recordings.analyse(
                full_recordings.scenes_of(recording), timing, min_pause_ms
            )
        except BoundaryError as exc:
            output["boundaries_error"] = str(exc)
            return
        tight = sum(1 for boundary in found if boundary.tight)
        output["tight_boundaries"] = tight
        if tight == 0:
            split, _created = await full_recordings.queue_split(session, recording, commit=False)
            output["split_job_id"] = split.id
