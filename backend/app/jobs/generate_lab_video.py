"""The `lab_video` job: one clip from the Video lab, on one model (Phase 19).

It is a remote job like `generate_clip`, and it is that handler with two differences, so it
extends it and keeps everything else (polling, pre-emption, the download retry, the cleanup on
the server, cancelling, the shared slots of the GPU pool, `max_parallel_gpu_jobs`):

- `start`: the request was built and checked when the run was created
  (`services/video_lab.create_runs`) and is stored in `job.input`, together with the endpoint,
  so nothing is worked out here. The first frame and the last frame, if the run has them, are
  fitted to the run's size and uploaded. A run without a first frame is text-to-video: the
  same endpoint, no `images`. A lip-synced clip (the Character lab) also has `audio`, the
  speech it matches: it is uploaded after the frame and named in the body (`with_audio`).
  A MiniMax H3 reference clip has `references` (1 to 9 pictures, uploaded as they are stored and
  in order, because the order is what `<Picture n>` means in the prompt) and, optionally,
  `audios` (up to two audio references, uploaded as they are stored too, never padded, in the
  order of `<Audio n>`): H3 reads them as references and makes its own soundtrack
  (`with_h3_references`). A job made before GPU API 0.14.0 holds one `audio`, read as a list of
  one.
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
    # A lip-synced clip (audio-to-video) has the one speech it matches. A MiniMax H3 reference
    # clip has none, one or two audio references, in the order the prompt names them
    # (`<Audio 1>`, ...). Every other clip has none.
    audios: tuple[_AudioInput, ...] = ()
    # Only a MiniMax H3 reference clip has any: its pictures, in the order the prompt names them.
    references: tuple[video_lab.FirstFrameRef, ...] = ()


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


def _audio_inputs(recorded: dict[str, Any]) -> tuple[_AudioInput, ...] | None:
    """The audios stored on the job's input, in order: an empty tuple when there are none, or
    None when they are malformed. A job made before GPU API 0.14.0 holds its one speech as
    `audio` instead of the list `audios`, and is read as a list of one.
    """
    value = recorded.get("audios")
    if value is None and recorded.get("audio") is not None:
        value = [recorded["audio"]]
    if value is None:
        return ()
    if not isinstance(value, list):
        return None
    audios: list[_AudioInput] = []
    for item in value:
        audio = _audio_input(item)
        if audio is None:
            return None
        audios.append(audio)
    return tuple(audios)


def _frame_ref(frame: object) -> video_lab.FirstFrameRef | None:
    """A frame stored on the job's input, or None when there is none or it is malformed."""
    if not isinstance(frame, dict):
        return None
    source, frame_id = frame.get("source"), frame.get("id")
    if source in ("lab", "asset") and isinstance(frame_id, int):
        return video_lab.FirstFrameRef(source=source, id=frame_id)
    return None


def _reference_refs(value: object) -> tuple[video_lab.FirstFrameRef, ...] | None:
    """The reference pictures stored on the job's input: an empty tuple when there are none, or
    None when the list is malformed.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        return None
    refs: list[video_lab.FirstFrameRef] = []
    for item in value:
        ref = _frame_ref(item)
        if ref is None:
            return None
        refs.append(ref)
    return tuple(refs)


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
    audios = _audio_inputs(recorded)
    if audios is None:
        return None
    references = _reference_refs(recorded.get("references"))
    if references is None:
        return None
    return _LabPlan(
        endpoint=endpoint,
        request=request,
        first_frame=first,
        last_frame=last,
        audios=audios,
        references=references,
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
        # The audio of a MiniMax H3 reference clip is optional: only its pictures are needed.
        if plan.endpoint == video_generator.H3_AUDIO_TO_VIDEO_PATH and not plan.references:
            await self._fail(job_id, "The reference pictures of this run are missing.")
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

    @staticmethod
    async def _upload_references(
        base_url: str, plan: _LabPlan, uploads: list[dict[str, Any]]
    ) -> list[str]:
        """Uploads the reference pictures of a MiniMax H3 reference clip, one after the other and
        in order, as they are stored (no crop: they do not set the clip's shape). Returns the
        server's asset ids in that order and appends what was uploaded to `uploads`. Raises
        FrameUnavailable and GpuCallError.
        """
        storage = get_storage()
        remote_ids: list[str] = []
        for number, ref in enumerate(plan.references, start=1):
            async with SessionLocal() as session:
                try:
                    relative = await video_lab.first_frame_path(session, ref)
                except video_lab.LabVideoInputError as exc:
                    raise FrameUnavailable(f"Reference picture {number}: {exc}") from exc
                await session.commit()
            try:
                path = storage.get_path(relative)
            except StorageError:
                raise FrameUnavailable(
                    f"Reference picture {number}'s file could not be found on disk."
                ) from None
            # The server reads the file's type from the extension, so the stored one is kept.
            filename = f"lab-reference-{ref.source}-{ref.id}{Path(relative).suffix or '.png'}"
            remote_id = await video_generator.upload_reference_picture(base_url, path, filename)
            remote_ids.append(remote_id)
            uploads.append({"filename": filename, "remote_asset_id": remote_id})
        return remote_ids

    @staticmethod
    async def _upload_audio_reference(base_url: str, audio: _AudioInput) -> tuple[str, str]:
        """Uploads the audio reference of a MiniMax H3 reference clip exactly as it is stored.
        Unlike the speech of an LTX lip-sync clip it is not padded: H3 reads 2 to 15 seconds of
        it as a reference and makes its own soundtrack. Returns the file name sent and the
        server's asset id. Raises AudioUnavailable and GpuCallError.
        """
        try:
            path = get_storage().get_path(audio.path)
        except StorageError:
            raise AudioUnavailable(
                "The audio reference's file could not be found on disk."
            ) from None
        filename = (
            f"lab-reference-audio-{audio.source}-{audio.id}{Path(audio.path).suffix or '.wav'}"
        )
        remote_id = await video_generator.upload_audio(base_url, path, filename, audio.mime)
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
                image_remote_ids: list[str] = []
                if plan.references:
                    await self._phase(job.id, phases.UPLOADING_REFERENCE)
                    image_remote_ids = await self._upload_references(base_url, plan, uploads)
                if plan.endpoint == video_generator.H3_AUDIO_TO_VIDEO_PATH:
                    # The audios are references the model reads, not a soundtrack: each is sent
                    # as it is stored, in order (`<Audio 1>` first). There may be none.
                    audio_remote_ids: list[str] = []
                    if plan.audios:
                        await self._phase(job.id, phases.UPLOADING_VOICE)
                    for audio in plan.audios:
                        filename, audio_remote_id = await self._upload_audio_reference(
                            base_url, audio
                        )
                        audio_remote_ids.append(audio_remote_id)
                        uploads.append({"filename": filename, "remote_asset_id": audio_remote_id})
                    body = video_generator.with_h3_references(
                        body, image_remote_ids, audio_remote_ids
                    )
                elif plan.audios:
                    # A lip-synced clip: its one speech, padded to the clip's length.
                    await self._phase(job.id, phases.UPLOADING_AUDIO)
                    filename, audio_remote_id = await self._upload_audio(
                        base_url, plan.audios[0], plan.request, temps
                    )
                    body = video_generator.with_audio(body, audio_remote_id)
                    uploads.append({"filename": filename, "remote_asset_id": audio_remote_id})
                if not await self._is_running(job.id):
                    return  # cancelled while uploading: nothing was submitted
                await self._phase(job.id, phases.SUBMITTING)
                answer = await video_generator.submit(base_url, plan.endpoint, body)
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
            # What the server said at the submit (a MiniMax H3 job: its GPUs and estimate). The
            # polls refresh the same two numbers in `output.remote`.
            "submit_answer": answer.to_json(),
        }
        async with SessionLocal() as session:
            saved = await store.mark_submitted(session, job.id, answer.job_id, submitted)
        if not saved:
            # Cancelled between the submit and here: the server job must be stopped too.
            await self._cancel_quietly(base_url, answer.job_id)

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
        lip_sync_requested = bool((recorded.get("request") or {}).get("lip_sync"))
        lip_sync_result = remote.get("lip_sync") if isinstance(remote, dict) else None
        lip_sync_applied = (
            lip_sync_result.get("applied") is True
            if lip_sync_requested and isinstance(lip_sync_result, dict)
            else None
        )
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
                if lip_sync_requested:
                    lip_sync_error = (
                        lip_sync_result.get("error") if isinstance(lip_sync_result, dict) else None
                    )
                    run.params = {
                        **(run.params or {}),
                        "lip_sync_applied": lip_sync_applied,
                        "lip_sync_error": lip_sync_error,
                    }
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

        if lip_sync_requested and lip_sync_applied is False:
            # The clip is kept (the user paid for it), but the server job that made it is kept
            # too, unpurged, so a later re-sync can still name it as `source_job_id`.
            purge: dict[str, Any] = {"skipped": "lip sync was not applied; kept for a re-sync"}
        else:
            # Best effort: a failure here is recorded and never fails the clip.
            purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.merge_output(session, job.id, {"purge": purge})
