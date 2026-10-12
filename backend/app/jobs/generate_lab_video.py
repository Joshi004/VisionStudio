"""The `lab_video` job: one clip from the Video lab, on one model (Phase 19).

It is a remote job like `generate_clip`, and it is that handler with two differences, so it
extends it and keeps everything else (polling, pre-emption, the download retry, the cleanup on
the server, cancelling, the shared slots of `max_parallel_generations`):

- `start`: the request was built and checked when the run was created
  (`services/video_lab.create_runs`) and is stored in `job.input`, together with the endpoint,
  so nothing is worked out here. The first frame and the last frame, if the run has them, are
  fitted to the run's size and uploaded. A run without a first frame is text-to-video: the
  same endpoint, no `images`. A lip-synced clip (the Talking character lab) also has `audio`,
  the speech it matches: it is uploaded after the frame and named in the body (`with_audio`).
  Every attempt (after pre-emption, an expired result) sends the same stored request, with the
  same seed, because "the correct response to a pre-emption failure is to resubmit the exact
  same request unchanged" (the server's guide).
- `_check_and_store`: the clip is stored under `media/lab/` and written on the `lab_video_run`
  row, in one transaction with the finished job. There is no scene to point at a take.

The job belongs to no project (`job.project_id` is NULL).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import anyio.to_thread

from app.core import outbound
from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Job, LabVideoRun
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.generate_clip import GPU_URL_KEY, SERVER_RETRY_DELAY_S, GenerateClipHandler
from app.providers import video_generator
from app.providers.gpu_server import GpuCallError
from app.services import ffmpeg, frame_images, speech_audio, video_lab
from app.services.storage import StorageError, TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = video_lab.RUN_JOB
# Silence added past the clip's end, so the speech covers the model's last audio latent frame
# (about 25 a second) whatever way it rounds. The server reads only the clip's length of it.
AUDIO_PAD_MARGIN_S: Final = 0.2


@dataclass(frozen=True)
class _LabPlan:
    """What a start submits, read back from the job's input."""

    endpoint: str
    request: dict[str, Any]
    first_frame: video_lab.FirstFrameRef | None
    last_frame: video_lab.FirstFrameRef | None
    # Only a lip-synced clip (audio-to-video) has one.
    audio: _AudioInput | None = None


@dataclass(frozen=True)
class _AudioInput:
    """The speech a lip-synced clip matches, as the run stored it on the job."""

    source: str
    id: int
    path: str
    mime: str


def _audio_input(value: object) -> _AudioInput | None:
    """The speech stored on the job's input, or None when there is none or it is malformed."""
    if not isinstance(value, dict):
        return None
    source, audio_id = value.get("source"), value.get("id")
    path, mime = value.get("path"), value.get("mime")
    if (
        source in ("voice_run", "voice")
        and isinstance(audio_id, int)
        and not isinstance(audio_id, bool)
        and isinstance(path, str)
        and isinstance(mime, str)
    ):
        return _AudioInput(source=str(source), id=audio_id, path=path, mime=mime)
    return None


def _frame_ref(frame: object) -> video_lab.FirstFrameRef | None:
    """A frame stored on the job's input, or None when there is none or it is malformed."""
    if not isinstance(frame, dict):
        return None
    source, frame_id = frame.get("source"), frame.get("id")
    if source in ("lab", "asset") and isinstance(frame_id, int):
        return video_lab.FirstFrameRef(source=source, id=frame_id)
    return None


def _plan(recorded: object) -> _LabPlan | None:
    """The plan stored on the job, or None when the input is not a run's."""
    if not isinstance(recorded, dict):
        return None
    endpoint = recorded.get("endpoint")
    request = recorded.get("request")
    if not isinstance(endpoint, str) or not isinstance(request, dict):
        return None
    first = _frame_ref(recorded.get("first_frame"))
    if recorded.get("first_frame") is not None and first is None:
        return None
    last = _frame_ref(recorded.get("last_frame"))
    if recorded.get("last_frame") is not None and last is None:
        return None
    if last is not None and first is None:
        return None
    audio = _audio_input(recorded.get("audio"))
    if recorded.get("audio") is not None and audio is None:
        return None
    return _LabPlan(
        endpoint=endpoint, request=request, first_frame=first, last_frame=last, audio=audio
    )


def _write_new_file(path: Path, data: bytes) -> None:
    # "xb": a temp file is always created, never opened over an existing one (storage.py).
    with open(path, "xb") as handle:
        handle.write(data)


class FrameUnavailable(Exception):
    """The first frame cannot be read. The message is meant to be shown to the user."""


class AudioUnavailable(Exception):
    """The speech of a lip-synced clip cannot be found. The message is for the user."""


class GenerateLabVideoHandler(GenerateClipHandler):
    job_type = JOB_TYPE

    # --- start: upload the first frame (if any) and submit --------------------------------

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            await session.commit()

        plan = _plan(job.input)
        if plan is None:
            await self._fail(job_id, "The request for this run is missing.")
            return
        await self._upload_and_submit_run(job, base_url, plan)

    async def _frame_png(self, plan: _LabPlan, ref: video_lab.FirstFrameRef, name: str) -> Path:
        """A frame fitted to the run's size, as a lossless PNG in the temp folder. `name` is
        "first" or "last", for the messages. The caller removes it. Raises FrameUnavailable.
        """
        width, height = int(plan.request["width"]), int(plan.request["height"])
        async with SessionLocal() as session:
            try:
                relative = await video_lab.first_frame_path(session, ref)
            except video_lab.LabVideoInputError as exc:
                raise FrameUnavailable(str(exc)) from exc
            await session.commit()

        storage = get_storage()
        try:
            source = storage.get_path(relative)
            png = await frame_images.run_pillow(
                frame_images.render_frame_png, source, width, height
            )
        except StorageError:
            raise FrameUnavailable(f"The {name} frame's file could not be found on disk.") from None
        except Exception as exc:  # Pillow raises many kinds of error for a damaged file.
            _logger.warning("lab %s frame could not be fitted: %s", name, exc)
            raise FrameUnavailable(
                f"The {name} frame could not be read to prepare it for the video model."
            ) from None
        temp = storage.new_temp_path("png")
        await anyio.to_thread.run_sync(_write_new_file, temp, png)
        return temp

    @staticmethod
    async def _upload_audio(
        base_url: str, audio: _AudioInput, request: dict[str, Any], temps: list[Path]
    ) -> tuple[str, str]:
        """Uploads the speech of a lip-synced clip, padded with silence to the clip's length.
        Returns the file name sent and the server's asset id. The padded WAV is added to `temps`
        for the caller to remove. Raises AudioUnavailable and GpuCallError.

        The model needs audio for the whole clip: a speech shorter than the clip fails on the
        GPU with "Latent shape ... does not match target shape". The clip is rounded up to the
        next `8k + 1` frames, so it is up to about 0.3 s longer than the speech.
        """
        storage = get_storage()
        try:
            source = storage.get_path(audio.path)
        except StorageError:
            raise AudioUnavailable("The speech's file could not be found on disk.") from None
        clip_s = float(request["num_frames"]) / float(request["frame_rate"])
        padded = storage.new_temp_path("wav")
        temps.append(padded)
        try:
            await speech_audio.pad_to(source, padded, clip_s + AUDIO_PAD_MARGIN_S)
        except speech_audio.PadError as exc:
            raise AudioUnavailable(str(exc)) from exc
        filename = f"lab-speech-{audio.source}-{audio.id}.wav"
        remote_id = await video_generator.upload_audio(base_url, padded, filename, "audio/wav")
        return filename, remote_id

    async def _upload_and_submit_run(self, job: Job, base_url: str, plan: _LabPlan) -> None:
        """Uploads the first frame (when there is one) and submits. The server's job id is
        saved the moment the submit answers, with nothing that can fail in between.

        The same answers as a scene's clip: 502 at submit is retried once after a pause, 429
        puts the job back in the queue, a 400 for an unknown asset id uploads the frames again
        once, and 422 or any other refusal fails the job with the server's message.
        """
        storage = get_storage()
        retried_server_error = False
        retried_asset = False
        while True:
            temps: list[Path] = []
            try:
                uploads: list[dict[str, Any]] = []
                body = plan.request
                if plan.first_frame is not None:
                    await self._phase(job.id, phases.PREPARING_FRAMES)
                    named = [("first", plan.first_frame)]
                    if plan.last_frame is not None:
                        named.append(("last", plan.last_frame))
                    for name, ref in named:
                        temps.append(await self._frame_png(plan, ref, name))
                    await self._phase(job.id, phases.UPLOADING_FRAMES)
                    for (_name, ref), temp in zip(named, temps, strict=True):
                        filename = f"lab-frame-{ref.source}-{ref.id}.png"
                        remote_id = await video_generator.upload_frame(base_url, temp, filename)
                        uploads.append({"filename": filename, "remote_asset_id": remote_id})
                    body = video_generator.with_frames(
                        plan.endpoint,
                        plan.request,
                        uploads[0]["remote_asset_id"],
                        uploads[1]["remote_asset_id"] if len(uploads) > 1 else None,
                    )
                if plan.audio is not None:
                    await self._phase(job.id, phases.UPLOADING_AUDIO)
                    filename, audio_remote_id = await self._upload_audio(
                        base_url, plan.audio, plan.request, temps
                    )
                    uploads.append({"filename": filename, "remote_asset_id": audio_remote_id})
                    body = video_generator.with_audio(body, audio_remote_id)
                if not await self._is_running(job.id):
                    return  # cancelled while uploading: nothing was submitted
                await self._phase(job.id, phases.SUBMITTING)
                provider_job_id = await video_generator.submit(base_url, plan.endpoint, body)
                break
            except (FrameUnavailable, AudioUnavailable) as exc:
                await self._fail(job.id, str(exc))
                return
            except StorageError:
                await self._fail(job.id, "A frame's file could not be found on disk.")
                return
            except GpuCallError as exc:
                if exc.kind == "server_error" and not retried_server_error:
                    retried_server_error = True
                    await asyncio.sleep(SERVER_RETRY_DELAY_S)
                    continue
                unknown_asset = (
                    exc.status_code == 400 and "invalid asset reference" in exc.message.lower()
                )
                if exc.kind == "rejected" and unknown_asset and not retried_asset:
                    retried_asset = True  # the server lost an upload: send it again
                    continue
                await self._give_up_starting(job.id, exc)
                return
            finally:
                for temp in temps:
                    storage.discard(temp)

        submitted = {
            **(job.input if isinstance(job.input, dict) else {}),
            "server_url": docker_mapped(base_url),
            "uploads": uploads,
            "body": body,
        }
        async with SessionLocal() as session:
            saved = await store.mark_submitted(session, job.id, provider_job_id, submitted)
        if not saved:
            # Cancelled between the submit and here: the server job must be stopped too.
            await self._cancel_quietly(base_url, provider_job_id)

    # --- finish: store the clip on the run ---------------------------------------------------

    async def _check_and_store(
        self, job: Job, base_url: str, result: outbound.DownloadResult, dest: Path
    ) -> None:
        recorded = job.input if isinstance(job.input, dict) else {}
        run_id = recorded.get("run_id")

        probe = await ffmpeg.probe_video(dest)
        if probe is None or probe.frame_count is None:
            await self._fail_and_purge(
                job, base_url, "The downloaded clip could not be read. Run it again."
            )
            return

        audio = (
            {
                "codec": probe.audio.codec_name,
                "sample_rate": probe.audio.sample_rate,
                "channels": probe.audio.channels,
            }
            if probe.audio is not None
            else None
        )
        remote = job.output.get("remote") if isinstance(job.output, dict) else None
        output: dict[str, Any] = {
            "run_id": run_id,
            "clip": {
                "frame_count": probe.frame_count,
                "num_frames": (recorded.get("request") or {}).get("num_frames"),
                "width": probe.width,
                "height": probe.height,
                "fps": probe.fps,
                "duration_s": probe.duration_s,
                "size_bytes": result.size_bytes,
                "audio": audio,
            },
            "remote": remote,
        }
        retries = job.output.get("download_retries") if isinstance(job.output, dict) else 0
        if isinstance(retries, int) and retries > 0:
            output["download_retries"] = retries

        storage = get_storage()
        temp = TempFile(path=dest, size_bytes=result.size_bytes, sha256=result.sha256)
        stored = await storage.save_lab(temp, "mp4")

        # The file on the run and the finished job are saved together or not at all.
        async with SessionLocal() as session:
            run = await session.get(LabVideoRun, run_id) if isinstance(run_id, int) else None
            if run is not None:
                run.path = stored.relative_path
                run.size_bytes = result.size_bytes
                run.sha256 = result.sha256
                run.width = probe.width
                run.height = probe.height
                run.frame_count = probe.frame_count
                run.duration_s = probe.duration_s
                run.audio = audio
            else:
                _logger.warning("job %d: clip stored but its run %s is gone", job.id, run_id)
            if not await store.finish_job(session, job.id, output):
                await session.rollback()
                # Cancelled in the meantime. Stored files are never deleted.
                _logger.warning(
                    "job %d: clip stored but the job is no longer running: %s",
                    job.id,
                    stored.relative_path,
                )
                return
            await session.commit()

        _logger.info(
            "job %d: lab clip stored: run=%s frames=%d %sx%s %.2f fps audio=%s",
            job.id,
            run_id,
            probe.frame_count,
            probe.width,
            probe.height,
            probe.fps or 0.0,
            audio["codec"] if audio else "none",
        )

        # Best effort: a failure here is recorded and never fails the clip.
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.merge_output(session, job.id, {"purge": purge})
