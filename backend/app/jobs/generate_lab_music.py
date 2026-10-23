"""The `lab_music` job: one piece of audio from the Music lab, made by one of the GPU server's
music models (ACE-Step 1.5, YuE2, Stable Audio 3, Stable Audio Open or LTX text-to-audio).

It is the simplest remote job there is: no file is uploaded (text-to-audio only), so `start`
submits the request the service built and saves the server's job id. Everything after that is
`RemoteVideoHandler`'s: it polls once per tick, downloads the result, resubmits after a
pre-emption, handles an expired result, and purges and cancels on the server. Failure handling
follows ANALYSIS.md Section 5.8: a dropped connection never fails the job. (The shared phases
say "clip", although the file is audio.)

`_check_and_store` reads the downloaded file with ffprobe, stores it under `media/lab/` (FLAC, or
WAV for LTX), and writes the result on the `lab_music_run` row in one transaction with the
finished job. The job belongs to no project (`job.project_id` is NULL).

The request is built and checked by `services/music_lab.py`, so a bad form starts nothing. This
module only submits what the job recorded, and refuses an endpoint that is not the one its model
has (a job's input is data, not a place to pick any URL).
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
from app.jobs import phases, store
from app.jobs.gpu_job import GPU_URL_KEY, SERVER_RETRY_DELAY_S
from app.jobs.remote_video import RemoteVideoHandler
from app.providers import gpu_server, music_generator
from app.providers.gpu_server import GpuCallError
from app.services import ffmpeg, music_lab, music_models
from app.services.music_models import MusicModel
from app.services.storage import TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = music_lab.RUN_JOB


@dataclass(frozen=True)
class _Plan:
    """What the job makes, read back from `job.input`."""

    run_id: int
    model: MusicModel
    endpoint: str
    request: dict[str, Any]
    extension: str


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
    if endpoint != music_generator.ENDPOINTS[model]:
        return None
    return _Plan(
        run_id=run_id,
        model=model,
        endpoint=endpoint,
        request=request,
        extension=music_generator.EXTENSIONS[model],
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
        while True:
            try:
                if not await self._is_running(job_id):
                    return  # cancelled before it was submitted
                await self._phase(job_id, phases.SUBMITTING)
                answer = await gpu_server.submit(base_url, plan.endpoint, plan.request)
                break
            except GpuCallError as exc:
                # 502 at submit is retried once after a pause. 429 and no answer put the job
                # back in the queue, and any other refusal fails it with the server's message.
                if exc.kind == "server_error" and not retried_server_error:
                    retried_server_error = True
                    await asyncio.sleep(SERVER_RETRY_DELAY_S)
                    continue
                await self._give_up_starting(job_id, exc)
                return

        submitted = {
            **(job.input if isinstance(job.input, dict) else {}),
            "server_url": docker_mapped(base_url),
            "submit_answer": answer.to_json(),
        }
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

        # Best effort: a failure here is recorded and never fails the audio.
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.merge_output(session, job.id, {"purge": purge})
