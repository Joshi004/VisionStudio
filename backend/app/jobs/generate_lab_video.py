"""The `lab_video` job: one clip from the Video lab, on one model (Phase 19).

It is a remote job like `generate_clip`, and it is that handler with two differences, so it
extends it and keeps everything else (polling, pre-emption, the download retry, the cleanup on
the server, cancelling, the shared slots of `max_parallel_generations`):

- `start`: the request was built and checked when the run was created
  (`services/video_lab.create_runs`) and is stored in `job.input`, together with the endpoint,
  so nothing is worked out here. The first frame, if the run has one, is fitted to the run's
  size and uploaded. A run without one is text-to-video: the same endpoint, no `images`.
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
from app.services import ffmpeg, frame_images, video_lab
from app.services.storage import StorageError, TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = video_lab.RUN_JOB


@dataclass(frozen=True)
class _LabPlan:
    """What a start submits, read back from the job's input."""

    endpoint: str
    request: dict[str, Any]
    first_frame: video_lab.FirstFrameRef | None


def _plan(recorded: object) -> _LabPlan | None:
    """The plan stored on the job, or None when the input is not a run's."""
    if not isinstance(recorded, dict):
        return None
    endpoint = recorded.get("endpoint")
    request = recorded.get("request")
    if not isinstance(endpoint, str) or not isinstance(request, dict):
        return None
    frame = recorded.get("first_frame")
    first: video_lab.FirstFrameRef | None = None
    if isinstance(frame, dict):
        source, frame_id = frame.get("source"), frame.get("id")
        if source in ("lab", "asset") and isinstance(frame_id, int):
            first = video_lab.FirstFrameRef(source=source, id=frame_id)
        else:
            return None
    return _LabPlan(endpoint=endpoint, request=request, first_frame=first)


def _write_new_file(path: Path, data: bytes) -> None:
    # "xb": a temp file is always created, never opened over an existing one (storage.py).
    with open(path, "xb") as handle:
        handle.write(data)


class FrameUnavailable(Exception):
    """The first frame cannot be read. The message is meant to be shown to the user."""


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

    async def _first_frame_png(self, plan: _LabPlan) -> Path:
        """The first frame fitted to the run's size, as a lossless PNG in the temp folder.
        The caller removes it. Raises FrameUnavailable.
        """
        assert plan.first_frame is not None
        width, height = int(plan.request["width"]), int(plan.request["height"])
        async with SessionLocal() as session:
            try:
                relative = await video_lab.first_frame_path(session, plan.first_frame)
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
            raise FrameUnavailable("The first frame's file could not be found on disk.") from None
        except Exception as exc:  # Pillow raises many kinds of error for a damaged file.
            _logger.warning("lab first frame could not be fitted: %s", exc)
            raise FrameUnavailable(
                "The first frame could not be read to prepare it for the video model."
            ) from None
        temp = storage.new_temp_path("png")
        await anyio.to_thread.run_sync(_write_new_file, temp, png)
        return temp

    async def _upload_and_submit_run(self, job: Job, base_url: str, plan: _LabPlan) -> None:
        """Uploads the first frame (when there is one) and submits. The server's job id is
        saved the moment the submit answers, with nothing that can fail in between.

        The same answers as a scene's clip: 502 at submit is retried once after a pause, 429
        puts the job back in the queue, a 400 for an unknown asset id uploads the frame again
        once, and 422 or any other refusal fails the job with the server's message.
        """
        storage = get_storage()
        retried_server_error = False
        retried_asset = False
        while True:
            temp: Path | None = None
            try:
                uploads: list[dict[str, Any]] = []
                body = plan.request
                if plan.first_frame is not None:
                    await self._phase(job.id, phases.PREPARING_FRAMES)
                    temp = await self._first_frame_png(plan)
                    await self._phase(job.id, phases.UPLOADING_FRAMES)
                    filename = f"lab-frame-{plan.first_frame.source}-{plan.first_frame.id}.png"
                    remote_id = await video_generator.upload_frame(base_url, temp, filename)
                    uploads.append({"filename": filename, "remote_asset_id": remote_id})
                    body = video_generator.with_first_frame(plan.request, remote_id)
                if not await self._is_running(job.id):
                    return  # cancelled while uploading: nothing was submitted
                await self._phase(job.id, phases.SUBMITTING)
                provider_job_id = await video_generator.submit(base_url, plan.endpoint, body)
                break
            except FrameUnavailable as exc:
                await self._fail(job.id, str(exc))
                return
            except StorageError:
                await self._fail(job.id, "The first frame's file could not be found on disk.")
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
                if temp is not None:
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
