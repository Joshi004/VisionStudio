"""The `lab_music` job: one piece of audio from the Music lab, made by one of the GPU server's
music models (ACE-Step 1.5, YuE2, Stable Audio 3, Stable Audio Open or LTX text-to-audio).

For text-to-audio no file is uploaded, so `start` submits the request the service built and saves
the server's job id. An edit (repaint, cover, inpaint, transform) first uploads its source
recording with `POST /v1/uploads` and names it in the request (`source_audio_asset_id`); the upload
is done here, right before the submit, because the server deletes an upload that no job uses after
60 minutes, and a job that is submitted again after a pre-emption uploads again. Everything after
the submit is
`RemoteVideoHandler`'s: it polls once per tick, downloads the result, resubmits after a
pre-emption, handles an expired result, and purges and cancels on the server. Failure handling
follows ANALYSIS.md Section 5.8: a dropped connection never fails the job. (The shared phases
say "clip", although the file is audio.)

`_check_and_store` reads the downloaded file with ffprobe, stores it under `media/lab/` (FLAC, or
WAV for LTX), and writes the result on the `lab_music_run` row in one transaction with the
finished job. A lab job belongs to no project (`job.project_id` is NULL); the recordings of a
story's music themes (MUSIC-007) are the same job with the project set, and `_continue_music_theme`
checks them once stored.

The request is built and checked by `services/music_lab.py`, so a bad form starts nothing. This
module only submits what the job recorded, and refuses an endpoint that is not the one its model
(and operation) has (a job's input is data, not a place to pick any URL).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.core import outbound
from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Job, LabMusicRun
from app.db.session import SessionLocal
from app.jobs import dispatcher, phases, store
from app.jobs.gpu_job import GPU_URL_KEY, SERVER_RETRY_DELAY_S
from app.jobs.remote_video import RemoteVideoHandler
from app.providers import gpu_server, music_generator
from app.providers.gpu_server import GpuCallError
from app.services import ffmpeg, music_lab, music_models, music_themes
from app.services.music_models import EditOperation, MusicModel
from app.services.storage import StorageError, TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = music_lab.RUN_JOB


@dataclass(frozen=True)
class _Source:
    """The recording an edit starts from: a stored file under `media/` and how to send it."""

    path: str
    filename: str
    mime: str


@dataclass(frozen=True)
class _Plan:
    """What the job makes, read back from `job.input`."""

    run_id: int
    model: MusicModel
    endpoint: str
    request: dict[str, Any]
    extension: str
    # Set for an edit.
    operation: EditOperation | None
    source: _Source | None


def _plan(recorded: object) -> _Plan | None:
    """The plan stored on the job, or None when the input is not a music run's."""
    if not isinstance(recorded, dict):
        return None
    run_id, model = recorded.get("run_id"), recorded.get("model")
    request, endpoint = recorded.get("request"), recorded.get("endpoint")
    if isinstance(run_id, bool) or not isinstance(run_id, int):
        return None
    if not music_models.is_music_model(model) or not isinstance(request, dict):
        return None

    operation = recorded.get("operation")
    source: _Source | None = None
    if operation is None:
        expected = music_generator.ENDPOINTS[model]
    else:
        if not music_models.is_edit_operation(operation):
            return None
        expected_or_none = music_generator.EDIT_ENDPOINTS.get((operation, model))
        raw = recorded.get("source")
        if expected_or_none is None or not isinstance(raw, dict):
            return None
        path, filename, mime = raw.get("path"), raw.get("filename"), raw.get("mime")
        if not (isinstance(path, str) and isinstance(filename, str) and isinstance(mime, str)):
            return None
        expected = expected_or_none
        source = _Source(path=path, filename=filename, mime=mime)
    if endpoint != expected:
        return None
    return _Plan(
        run_id=run_id,
        model=model,
        endpoint=endpoint,
        request=request,
        extension=music_generator.EXTENSIONS[model],
        operation=operation,
        source=source,
    )


class GenerateLabMusicHandler(RemoteVideoHandler):
    job_type = JOB_TYPE

    # --- start: submit -----------------------------------------------------------------------

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

        retried_server_error = False
        retried_asset = False
        while True:
            try:
                if not await self._is_running(job_id):
                    return  # cancelled before it was submitted
                body = plan.request
                uploads: list[dict[str, Any]] = []
                if plan.source is not None:
                    await self._phase(job_id, phases.UPLOADING_MUSIC_SOURCE)
                    path = get_storage().get_path(plan.source.path)
                    remote_id = await gpu_server.upload_file(
                        base_url, path, plan.source.filename, plan.source.mime
                    )
                    uploads.append({"filename": plan.source.filename, "remote_asset_id": remote_id})
                    body = music_generator.with_source(body, remote_id)
                    if not await self._is_running(job_id):
                        return  # cancelled while uploading: nothing was submitted
                await self._phase(job_id, phases.SUBMITTING)
                answer = await gpu_server.submit(base_url, plan.endpoint, body)
                break
            except (StorageError, OSError):
                await self._fail(job_id, "The source recording's file could not be read.")
                return
            except GpuCallError as exc:
                # 502 at submit is retried once after a pause. A 400 for an unknown asset id
                # uploads the source again once. 429 and no answer put the job back in the
                # queue, and any other refusal fails it with the server's message.
                if exc.kind == "server_error" and not retried_server_error:
                    retried_server_error = True
                    await asyncio.sleep(SERVER_RETRY_DELAY_S)
                    continue
                unknown_asset = (
                    exc.status_code == 400 and "invalid asset reference" in exc.message.lower()
                )
                if exc.kind == "rejected" and unknown_asset and not retried_asset:
                    retried_asset = True  # the server lost the upload: send it again
                    continue
                await self._give_up_starting(job_id, exc)
                return

        submitted = {
            **(job.input if isinstance(job.input, dict) else {}),
            "server_url": docker_mapped(base_url),
            "submit_answer": answer.to_json(),
        }
        if plan.source is not None:
            # What was uploaded, and the request exactly as it was sent.
            submitted["uploads"] = uploads
            submitted["body"] = body
        async with SessionLocal() as session:
            saved = await store.mark_submitted(session, job_id, answer.job_id, submitted)
        if not saved:
            # Cancelled between the submit and here: the server job must be stopped too.
            await self._cancel_quietly(base_url, answer.job_id)

    # --- finish: store the audio on the run --------------------------------------------------

    async def _check_and_store(
        self, job: Job, base_url: str, result: outbound.DownloadResult, dest: Path
    ) -> None:
        plan = _plan(job.input)
        if plan is None:
            await self._fail_and_purge(job, base_url, "The request for this run is missing.")
            return

        probe = await ffmpeg.probe(dest)
        stream = probe.audio_streams[0] if probe is not None and probe.audio_streams else None
        duration = (probe.duration_s or stream.duration_s) if probe and stream else None
        if probe is None or stream is None or duration is None:
            await self._fail_and_purge(
                job, base_url, "The downloaded audio could not be read. Run it again."
            )
            return

        audio = {
            "codec": stream.codec_name,
            "sample_rate": stream.sample_rate,
            "channels": stream.channels,
            "duration_s": duration,
            "size_bytes": result.size_bytes,
        }
        remote = job.output.get("remote") if isinstance(job.output, dict) else None
        output: dict[str, Any] = {"run_id": plan.run_id, "audio": audio, "remote": remote}
        retries = job.output.get("download_retries") if isinstance(job.output, dict) else 0
        if isinstance(retries, int) and retries > 0:
            output["download_retries"] = retries

        temp = TempFile(path=dest, size_bytes=result.size_bytes, sha256=result.sha256)
        stored = await get_storage().save_lab(temp, plan.extension)

        # The file on the run and the finished job are saved together or not at all.
        async with SessionLocal() as session:
            run = await session.get(LabMusicRun, plan.run_id)
            if run is not None:
                run.path = stored.relative_path
                run.size_bytes = result.size_bytes
                run.sha256 = result.sha256
                run.duration_s = duration
                run.sample_rate = stream.sample_rate
                run.channels = stream.channels
            else:
                _logger.warning("job %d: audio stored but its run %s is gone", job.id, plan.run_id)
            if not await store.finish_job(session, job.id, output):
                await session.rollback()
                # Cancelled in the meantime. Stored files are never deleted.
                _logger.warning(
                    "job %d: audio stored but the job is no longer running: %s",
                    job.id,
                    stored.relative_path,
                )
                return
            await session.commit()

        _logger.info(
            "job %d: lab music stored: run=%s model=%s %.1f s %s Hz",
            job.id,
            plan.run_id,
            plan.model,
            duration,
            stream.sample_rate,
        )

        await self._continue_music_theme(job.id, plan.run_id)

        # Best effort: a failure here is recorded and never fails the audio.
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.merge_output(session, job.id, {"purge": purge})

    @staticmethod
    async def _continue_music_theme(job_id: int, run_id: int) -> None:
        """Checks the recording when it belongs to a music theme, and lets the first candidate
        that passes become the theme's canonical recording (MUSIC-007). Best effort: a failure
        never fails the audio (it is stored), and the owner can choose a candidate by hand.
        """
        try:
            if await music_themes.on_audio_stored(run_id):
                dispatcher.nudge()
        except Exception:
            _logger.exception("job %d: the music theme could not continue", job_id)
