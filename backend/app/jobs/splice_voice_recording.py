"""The `splice_voice_recording` job: put the accepted patches into a full recording. (REC-006)

A local job, like `split_voice_recording` (FFmpeg only; nothing is paid for and no model is asked;
a restart makes the splice again from the start). It makes a **new version** of the full
recording; the version it was made from, and every patch, stay as they are.

1. the newest full recording, its regions and the state of the patch recorded for each
   (`full_recordings.status_of`) are read again. The job refuses to run when the recording is no
   longer the newest, or is being split, and when no patch is accepted;
2. for each accepted patch the stretch of the recording it replaces runs from the middle of the
   pause before the region to the middle of the pause after it. The patch is trimmed to its words
   plus as much silence on each side as the recording had there (`patch_window_s`);
3. the loudness of the recording around each region (10 s each side) and of the trimmed patch is
   measured, and the patch gets the difference as gain, within 12 dB;
4. FFmpeg joins the stretches with a 15 ms crossfade at every join, inside the silence. The length
   of the result is checked against the plan to the sample;
5. in one transaction the file is stored, a `voice_recording` row (`scope = 'full'`, the next
   `version`, `origin = 'splice'`, `base_recording_id` = the version it was made from, `patch_id`
   = the first patch) is added, the job that transcribes it is queued, and this job is finished.
   The new version is analysed like any recording, and takes over the owner's decisions on the
   boundaries the patches did not touch (`time_voice_recording`).

Every temporary file is removed afterwards. Logs hold ids, never the text.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Project, VoiceRecording
from app.db.session import SessionLocal
from app.jobs import dispatcher, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.jobs.split_voice_recording import SplitFailed, frame_count
from app.services import ffmpeg, full_recordings, recording_patches, speech_audio
from app.services.recording_boundaries import BoundaryError
from app.services.speech_audio import SAMPLE_RATE, SCENE_FADE_S
from app.services.storage import Storage, StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = full_recordings.SPLICE_JOB_TYPE
_FADE_SAMPLES: Final = round(SCENE_FADE_S * SAMPLE_RATE)


class SpliceFailed(Exception):
    """The patches cannot be spliced. The message is meant to be shown to the user."""


class _Accepted:
    """One accepted patch, read for the splice."""

    def __init__(self, status: full_recordings.RegionStatus) -> None:
        assert status.patch is not None and status.words is not None
        self.region = status.region
        self.patch = status.patch
        self.words = status.words


class SpliceVoiceRecordingHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def start(self, job_id: int) -> None:
        storage = get_storage()
        temp_paths: list[Path] = []
        try:
            await self._splice(job_id, storage, temp_paths)
        except (SpliceFailed, SplitFailed, BoundaryError, speech_audio.SpliceError) as exc:
            async with SessionLocal() as session:
                await store.fail_job(session, job_id, str(exc))
        except StorageError as exc:
            async with SessionLocal() as session:
                await store.fail_job(session, job_id, f"A file could not be stored: {exc}")
        finally:
            for path in temp_paths:
                storage.discard(path)

    async def _splice(self, job_id: int, storage: Storage, temp_paths: list[Path]) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            recorded = job.input if isinstance(job.input, dict) else {}
            recording_id = recorded.get(full_recordings.DEDUPE_KEY)
            recording = (
                await session.get(VoiceRecording, recording_id)
                if isinstance(recording_id, int)
                else None
            )
            project = (
                await session.get(Project, recording.project_id) if recording is not None else None
            )
            current = (
                await full_recordings.newest(session, project) if project is not None else None
            )
            await session.commit()
        if recording is None or current is None:
            raise SpliceFailed("The recording this splice was queued for is gone.")
        if current.recording.id != recording.id:
            raise SpliceFailed("A newer recording was made in the meantime. Nothing was spliced.")
        if current.stage not in full_recordings.DECIDABLE_STAGES:
            raise SpliceFailed("The recording is being split. Splice when that is done.")
        accepted = sorted(
            (_Accepted(item) for item in current.regions if item.stage == "accepted"),
            key=lambda item: item.region.first_word,
        )
        if not accepted:
            raise SpliceFailed("No recorded part is accepted.")

        base_path = storage.get_path(recording.path)
        if not base_path.is_file():
            raise SpliceFailed("The recording file could not be found on disk.")
        total_samples = frame_count(base_path)
        total_s = total_samples / SAMPLE_RATE
        patch_paths: list[Path] = []
        for item in accepted:
            patch_path = storage.get_path(item.patch.path)
            if not patch_path.is_file():
                raise SpliceFailed("A patch file could not be found on disk.")
            patch_paths.append(patch_path)

        await self._phase(job_id, phases.MEASURING_PATCH_LOUDNESS)
        items: list[recording_patches.SpliceItem] = []
        for item, patch_path in zip(accepted, patch_paths, strict=True):
            region = item.region
            patch_total = frame_count(patch_path)
            window_start, window_end = recording_patches.patch_window_s(
                region, item.words, patch_total / SAMPLE_RATE
            )
            patch_start = recording_patches.to_sample(window_start, SAMPLE_RATE, patch_total)
            patch_end = recording_patches.to_sample(window_end, SAMPLE_RATE, patch_total)
            around_start = max(0.0, region.join_start_s - recording_patches.LOUDNESS_SPAN_S)
            around_end = min(total_s, region.join_end_s + recording_patches.LOUDNESS_SPAN_S)
            base_lufs = await ffmpeg.measure_loudness(
                base_path, start_s=around_start, duration_s=around_end - around_start
            )
            patch_lufs = await ffmpeg.measure_loudness(
                patch_path,
                start_s=patch_start / SAMPLE_RATE,
                duration_s=(patch_end - patch_start) / SAMPLE_RATE,
            )
            items.append(
                recording_patches.SpliceItem(
                    patch_id=item.patch.id,
                    base_start=recording_patches.to_sample(
                        region.join_start_s, SAMPLE_RATE, total_samples
                    ),
                    base_end=recording_patches.to_sample(
                        region.join_end_s, SAMPLE_RATE, total_samples
                    ),
                    patch_start=patch_start,
                    patch_end=patch_end,
                    gain_db=recording_patches.gain_db(base_lufs, patch_lufs),
                )
            )

        pieces = recording_patches.splice_pieces(total_samples, items, _FADE_SAMPLES)
        deltas = [
            recording_patches.delta_samples(
                item,
                _FADE_SAMPLES,
                (1 if item.base_start > 0 else 0) + (1 if item.base_end < total_samples else 0),
            )
            for item in items
        ]
        expected = recording_patches.spliced_length(pieces, _FADE_SAMPLES)
        if expected != total_samples + sum(deltas):
            raise SpliceFailed("The length of the new recording could not be worked out.")

        await self._phase(job_id, phases.SPLICING_PATCHES)
        dest = storage.new_temp_path("wav")
        temp_paths.append(dest)
        await speech_audio.splice(base_path, patch_paths, dest, pieces, _FADE_SAMPLES)
        if frame_count(dest) != expected:
            raise SpliceFailed("The new recording was not made to the length it should have.")
        temp = await storage.describe_temp(dest)

        await self._phase(job_id, phases.SAVING_SPLICED_RECORDING)
        stored = await storage.save(temp, recording.project_id, "wav")
        details: list[dict[str, Any]] = [
            {
                "patch_id": item.patch.id,
                "patch_sha256": item.patch.sha256,
                "first_word": item.region.first_word,
                "last_word": item.region.last_word,
                "join_start_s": item.region.join_start_s,
                "join_end_s": item.region.join_end_s,
                "base_start_sample": splice.base_start,
                "base_end_sample": splice.base_end,
                "patch_start_sample": splice.patch_start,
                "patch_end_sample": splice.patch_end,
                "gain_db": splice.gain_db,
                "delta_samples": delta,
                "boundaries": [
                    {"after_scene_id": after, "before_scene_id": before}
                    for after, before in item.region.tight_keys()
                ],
            }
            for item, splice, delta in zip(accepted, items, deltas, strict=True)
        ]
        await self._save(
            job_id, recording, stored.relative_path, temp, expected, details, _FADE_SAMPLES
        )

    @staticmethod
    async def _save(
        job_id: int,
        recording: VoiceRecording,
        path: str,
        temp: Any,
        total_samples: int,
        details: list[dict[str, Any]],
        fade_samples: int,
    ) -> None:
        inputs = recording.inputs if isinstance(recording.inputs, dict) else {}
        async with SessionLocal() as session:
            newest_version = (
                await session.execute(
                    select(func.max(VoiceRecording.version)).where(
                        VoiceRecording.project_id == recording.project_id,
                        VoiceRecording.scope == full_recordings.SCOPE_FULL,
                    )
                )
            ).scalar_one_or_none()
            if newest_version != recording.version:
                # Stored files are never deleted.
                _logger.warning("job %d: spliced file stored but not used: %s", job_id, path)
                raise SpliceFailed(
                    "A newer recording was made in the meantime. Nothing was spliced."
                )
            version = (newest_version or 0) + 1
            spliced = VoiceRecording(
                project_id=recording.project_id,
                scope=full_recordings.SCOPE_FULL,
                version=version,
                base_recording_id=recording.id,
                patch_id=min(item["patch_id"] for item in details),
                text=recording.text,
                origin="splice",
                path=path,
                size_bytes=temp.size_bytes,
                sha256=temp.sha256,
                duration_s=total_samples / SAMPLE_RATE,
                inputs={
                    "project_id": recording.project_id,
                    "artifacts": inputs.get("artifacts", []),
                    "scenes": inputs.get("scenes", []),
                    "base": {
                        "id": recording.id,
                        "version": recording.version,
                        "sha256": recording.sha256,
                    },
                    "fade_samples": fade_samples,
                    "patches": details,
                },
            )
            session.add(spliced)
            try:
                await session.flush()
                timing, _created = await full_recordings.queue_timing(
                    session, spliced, commit=False
                )
                output: dict[str, Any] = {
                    "voice_recording_id": recording.id,
                    "new_recording_id": spliced.id,
                    "version": version,
                    "patches": [item["patch_id"] for item in details],
                    "samples": total_samples,
                    "timing_job_id": timing.id,
                }
                # The new version and the finished job are saved together or not at all.
                if not await store.finish_job(session, job_id, output):
                    await session.rollback()
                    _logger.warning(
                        "job %d: spliced file stored but the job is not running: %s", job_id, path
                    )
                    return
                await session.commit()
            except IntegrityError:
                await session.rollback()
                raise SpliceFailed(
                    "Another recording was received at the same time. Try again."
                ) from None
        _logger.info(
            "job %d: recording %d spliced into version %d with %d patches",
            job_id,
            recording.id,
            version,
            len(details),
        )
        dispatcher.nudge()

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        await phase_writer.note(job_id, phase)
