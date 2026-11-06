"""The `split_voice_recording` job: cut a full recording into one take per scene. (REC-004)

A local job, like `render_av_test` (FFmpeg only; nothing is paid for and no model is asked; a
restart makes the split again from the start):

1. the recording's timing gives each scene's words, and `full_recordings.analyse` the scene
   boundaries. The job refuses to run while any tight boundary has no decision of the owner;
2. each cut is the middle of the pause (R-7), or the cut point the owner decided (REC-005). The
   cuts are rounded to a sample and the scenes are `split_windows`, so together they are exactly
   the recording;
3. a scene that already has a take cut from this recording at exactly those samples is left
   alone (so a changed decision makes new takes only for the scenes either side of the cut that
   moved). Every other scene is cut out with a 15 ms fade at every cut inside the recording (the
   start of the first scene and the end of the last are not faded), and its length is checked
   to the sample;
4. in one transaction every scene cut gets a recorded `speech_unit_audio` take (`inputs` names the
   recording, the window it was cut from and the decisions on its two boundaries), the job that
   times the words of each take is queued (as for any take), and the job is finished.

Every temporary file is removed afterwards. Logs hold ids, never the text.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Any, Final

from app.core import settings as settings_service
from app.db.models import SpeechUnitAudio, VoiceRecording
from app.db.session import SessionLocal
from app.jobs import dispatcher, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.services import (
    full_recordings,
    recording_boundaries,
    speech_audio,
    speech_synthesis,
    word_timings,
)
from app.services.recording_boundaries import BoundaryError
from app.services.speech_audio import SAMPLE_RATE
from app.services.storage import Storage, StorageError, TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = full_recordings.SPLIT_JOB_TYPE
_FADE_SAMPLES: Final = round(speech_audio.SCENE_FADE_S * SAMPLE_RATE)


class SplitFailed(Exception):
    """The recording cannot be split. The message is meant to be shown to the user."""


def frame_count(path: Path) -> int:
    """The number of samples of a WAV in the takes' format (mono, 24 kHz, 16-bit). Raises
    SplitFailed when it is not that format.
    """
    try:
        with wave.open(str(path), "rb") as file:
            if (
                file.getnchannels() != 1
                or file.getframerate() != SAMPLE_RATE
                or file.getsampwidth() != 2
            ):
                raise SplitFailed("The recording is not in the voice format.")
            return file.getnframes()
    except (wave.Error, EOFError, OSError) as exc:
        raise SplitFailed("The recording could not be read as a WAV file.") from exc


class SplitVoiceRecordingHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def start(self, job_id: int) -> None:
        storage = get_storage()
        temp_paths: list[Path] = []
        try:
            await self._split(job_id, storage, temp_paths)
        except (SplitFailed, BoundaryError, speech_audio.CutError) as exc:
            async with SessionLocal() as session:
                await store.fail_job(session, job_id, str(exc))
        except StorageError as exc:
            async with SessionLocal() as session:
                await store.fail_job(session, job_id, f"A file could not be stored: {exc}")
        finally:
            for path in temp_paths:
                storage.discard(path)

    async def _split(self, job_id: int, storage: Storage, temp_paths: list[Path]) -> None:
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
            timing = (
                await full_recordings.timing_of(session, recording.id)
                if recording is not None
                else None
            )
            min_pause_ms = await settings_service.get_int(
                session, settings_service.RECORDING_MIN_BOUNDARY_PAUSE_MS_KEY
            )
            decisions = (
                await full_recordings.decisions_of(session, recording.id)
                if recording is not None
                else {}
            )
            earlier_takes = (
                await full_recordings.takes_of(session, recording.project_id, recording.id)
                if recording is not None
                else []
            )
            await session.commit()
        if recording is None:
            raise SplitFailed("The recording this split was queued for is gone.")
        if timing is None or timing.source != word_timings.SOURCE_PARAKEET:
            raise SplitFailed("The recording has no usable word timing.")

        scenes = full_recordings.scenes_of(recording)
        found = full_recordings.analyse(scenes, timing, min_pause_ms)
        if any(
            boundary.tight and recording_boundaries.key_of(boundary) not in decisions
            for boundary in found
        ):
            raise SplitFailed("Some scene boundaries are tight. Decide them first.")
        cuts = recording_boundaries.final_cuts(found, decisions)

        source = storage.get_path(recording.path)
        if not source.is_file():
            raise SplitFailed("The recording file could not be found on disk.")
        total_samples = frame_count(source)
        windows = recording_boundaries.split_windows(total_samples, cuts, SAMPLE_RATE)
        # A scene with a take at these very samples keeps it.
        have = full_recordings.matching_takes(scenes, cuts, total_samples, earlier_takes)
        positions = [
            position for position, scene in enumerate(scenes) if scene.scene_id not in have
        ]

        await self._phase(job_id, phases.SPLITTING_RECORDING)
        temps: list[TempFile] = []
        for position in positions:
            first, last = windows[position]
            fade = min(_FADE_SAMPLES, (last - first) // 2)
            dest = storage.new_temp_path("wav")
            temp_paths.append(dest)
            await speech_audio.cut_scene(
                source,
                dest,
                first,
                last,
                fade if position > 0 else 0,
                fade if position < len(windows) - 1 else 0,
            )
            if frame_count(dest) != last - first:
                raise SplitFailed("A scene was not cut to the length it should have.")
            temps.append(await storage.describe_temp(dest))

        await self._phase(job_id, phases.SAVING_SCENE_TAKES)
        stored = [await storage.save(temp, recording.project_id, "wav") for temp in temps]
        await self._save(
            job_id,
            recording,
            scenes,
            windows,
            cuts,
            found,
            decisions,
            positions,
            temps,
            [item.relative_path for item in stored],
        )

    @staticmethod
    def _decisions_of_scene(
        position: int,
        scenes: list[recording_boundaries.SceneText],
        found: list[recording_boundaries.Boundary],
        decisions: dict[recording_boundaries.BoundaryKey, recording_boundaries.BoundaryDecision],
    ) -> list[dict[str, Any]]:
        """The decisions on the two boundaries of a scene (the one before it and the one after
        it), for the take's `inputs`. A boundary nobody decided is not listed.
        """
        listed: list[dict[str, Any]] = []
        for index in (position - 1, position):
            if not 0 <= index < len(found):
                continue
            decided = decisions.get(recording_boundaries.key_of(found[index]))
            if decided is not None:
                listed.append(
                    {
                        "after_scene_id": found[index].after_scene_id,
                        "before_scene_id": found[index].before_scene_id,
                        "decision": decided.decision,
                        "cut_s": decided.cut_s,
                    }
                )
        return listed

    @staticmethod
    async def _save(
        job_id: int,
        recording: VoiceRecording,
        scenes: list[recording_boundaries.SceneText],
        windows: list[tuple[int, int]],
        cuts: list[float],
        found: list[recording_boundaries.Boundary],
        decisions: dict[recording_boundaries.BoundaryKey, recording_boundaries.BoundaryDecision],
        positions: list[int],
        temps: list[TempFile],
        paths: list[str],
    ) -> None:
        plans = {
            item["scene_id"]: item
            for item in recording.inputs.get("scenes", [])
            if isinstance(item, dict) and "scene_id" in item
        }
        output: dict[str, Any] = {
            "voice_recording_id": recording.id,
            "scenes": len(scenes),
            "samples": windows[-1][1],
        }
        async with SessionLocal() as session:
            # A run in the meantime may have made a scene's take at these very cuts: it stands.
            already = full_recordings.matching_takes(
                scenes,
                cuts,
                windows[-1][1],
                await full_recordings.takes_of(session, recording.project_id, recording.id),
            )
            new_takes: list[SpeechUnitAudio] = []
            for position, temp, path in zip(positions, temps, paths, strict=True):
                scene = scenes[position]
                if scene.scene_id in already:
                    continue
                first, last = windows[position]
                start_s, end_s = round(first / SAMPLE_RATE, 6), round(last / SAMPLE_RATE, 6)
                plan = plans.get(scene.scene_id, {})
                take = SpeechUnitAudio(
                    project_id=recording.project_id,
                    scene_id=scene.scene_id,
                    unit_id=None,
                    kind=speech_synthesis.KIND_TAKE,
                    speaker_id=None,
                    text=scene.text,
                    mode=speech_synthesis.MODE_RECORDED,
                    instruction=None,
                    voice_id=None,
                    audio_key=speech_synthesis.recorded_take_key(
                        scene.text, recording.sha256, start_s, end_s
                    ),
                    job_id=None,
                    path=path,
                    size_bytes=temp.size_bytes,
                    sha256=temp.sha256,
                    duration_s=(last - first) / SAMPLE_RATE,
                    sample_rate=SAMPLE_RATE,
                    inputs={
                        "project_id": recording.project_id,
                        "artifacts": [
                            {
                                "kind": "speech_units",
                                "id": plan.get("plan_id"),
                                "version": plan.get("plan_version"),
                            }
                        ],
                        "recording": {"id": recording.id, "sha256": recording.sha256},
                        "window": {
                            "start_s": start_s,
                            "end_s": end_s,
                            "start_sample": first,
                            "end_sample": last,
                        },
                        "decisions": SplitVoiceRecordingHandler._decisions_of_scene(
                            position, scenes, found, decisions
                        ),
                    },
                )
                session.add(take)
                new_takes.append(take)
            await session.flush()
            # The word timing of a take is always made, and is saved with the take.
            for take in new_takes:
                await word_timings.queue(session, take, commit=False)
            output["take_audio_ids"] = [take.id for take in new_takes]
            output["kept_take_ids"] = sorted(already.values())
            # The takes and the finished job are saved together or not at all.
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                # Stored files are never deleted.
                _logger.warning(
                    "job %d: scenes stored but the job is not running: %d files", job_id, len(paths)
                )
                return
            await session.commit()
        _logger.info(
            "job %d: recording %d split into %d takes", job_id, recording.id, len(new_takes)
        )
        dispatcher.nudge()

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        await phase_writer.note(job_id, phase)
