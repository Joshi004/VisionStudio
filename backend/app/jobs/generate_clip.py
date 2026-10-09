"""The `generate_clip` job: one LTX clip (LTX-2.3 or LTX-2.5) for one scene (ANALYSIS.md
Section 3.3, 5.3, 5.8 and 6.4).

It is a remote job, so the three steps follow `JobHandler`:

- `start`: build the request once (the first time only), upload the frame or frames, submit,
  and save the server's job id at once.
- `poll`: ask the server about the job once per tick.
- `finish`: download the clip, check it with ffprobe, store it as a take and make it the
  scene's selected take, then purge the job on the server.

**The request is built once.** The first `start` works out the video model (the Regenerate
choice in `job.input`, else the scene's, the project's or the app's default:
`video_models.resolve`), the clip mode (a scene with a last frame is made by keyframe
interpolation, one without by image-to-video from its first frame:
`scene_inputs.clip_mode`), the endpoint (`video_generator.endpoint_for`: LTX-2.5 has no
keyframe endpoint yet, so such a scene falls back to LTX-2.3 and the job says so), the
prompt, the size, the frame count, the seed and the normalised frame or frames from the scene
and the project as they are then, and stores that in `job.input`. Every later attempt (after
pre-emption, an expired result or a Resubmit) sends the same stored request to the same
stored endpoint with the same seed and re-uploads the same files, because "the correct
response to a pre-emption failure is to resubmit the exact same request unchanged" (the
server's guide). A frame added or removed after the click changes nothing for a job already
prepared. A new seed comes only with a new job.

Failure handling follows ANALYSIS.md Section 5.8, row by row (see the notes in each
method). A dropped connection never fails the job.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbound
from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Asset, Job, Project, Scene
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.handlers import JobHandler
from app.jobs.transcribe import is_preemption, phase_for_poll_error
from app.providers import contract_guard, video_generator
from app.providers.gpu_server import GpuCallError
from app.services import (
    api_contract,
    clips,
    derived_frames,
    ffmpeg,
    frame_counts,
    scene_inputs,
    scene_prompt,
    video_models,
)
from app.services.assets import add_asset
from app.services.storage import StorageError, TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = clips.GENERATE_JOB
GPU_URL_KEY: Final = "gpu_api_base_url"
PARTITION_KEY: Final = "gpu_partition"
DEFAULT_NEGATIVE_PROMPT_KEY: Final = "default_negative_prompt"
DEFAULT_VIDEO_MODEL_KEY: Final = "default_video_model"
MAX_PARALLEL_KEY: Final = "max_parallel_generations"

SERVER_RETRY_DELAY_S: Final = 5.0
# How many ticks the download is tried again while the server answers 410 but still says the
# result is ready (about two minutes at the default poll interval).
MAX_RESULT_RETRIES: Final = 8
# Seeds are drawn below this, so they fit every signed 32-bit integer field.
_SEED_LIMIT: Final = 2**31


@dataclass(frozen=True)
class _Plan:
    """What a start submits: the endpoint, the request without its frames, and the file or
    two files to upload (`last` is None for a clip made from the first frame alone).
    """

    endpoint: str
    request: dict[str, Any]
    first: Asset
    last: Asset | None
    # The job's input as stored, which a submission extends.
    recorded: dict[str, Any]


class GenerateClipHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "gpu"
    restart_rule = "resume"
    # The Video lab's clips use the same GPUs, so they share these slots.
    concurrency_group = "video_generation"

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return await settings_service.get_int(session, MAX_PARALLEL_KEY)

    # --- start: prepare (once), upload, submit ----------------------------------

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            partition = await settings_service.get_str(session, PARTITION_KEY)
            default_negative_prompt = await settings_service.get_str(
                session, DEFAULT_NEGATIVE_PROMPT_KEY
            )
            default_video_model = await settings_service.get_str(session, DEFAULT_VIDEO_MODEL_KEY)
            await session.commit()

        plan = await self._stored_plan(job)
        if plan is None:
            plan = await self._prepare(job, partition, default_negative_prompt, default_video_model)
            if plan is None:
                return  # the job was failed, or cancelled, in there
        await self._upload_and_submit(job, base_url, plan)

    @staticmethod
    async def _stored_plan(job: Job) -> _Plan | None:
        """The plan of an earlier attempt, read back from the job's input. None the first time."""
        recorded = job.input if isinstance(job.input, dict) else {}
        request = recorded.get("request")
        endpoint = recorded.get("endpoint")
        first_id = _sent_asset_id(recorded.get("first_frame"))
        if (
            not isinstance(request, dict)
            or not isinstance(endpoint, str)
            or video_generator.clip_mode_for(endpoint) is None
            or first_id is None
        ):
            return None
        # Only a keyframe clip has a last frame. A first-frame job stores none.
        last_id: int | None = None
        if video_generator.clip_mode_for(endpoint) == "first_and_last":
            last_id = _sent_asset_id(recorded.get("last_frame"))
            if last_id is None:
                return None
        async with SessionLocal() as session:
            first = await session.get(Asset, first_id)
            last = await session.get(Asset, last_id) if last_id is not None else None
            await session.commit()
        if first is None or (last_id is not None and last is None):
            return None
        return _Plan(endpoint=endpoint, request=request, first=first, last=last, recorded=recorded)

    async def _prepare(
        self,
        job: Job,
        partition: str,
        default_negative_prompt: str,
        default_video_model: str,
    ) -> _Plan | None:
        """Works out the video model, the clip mode, the request and the frames to send. Runs
        on the first attempt only.

        The model is the Regenerate choice stored in `job.input["video_model"]`, else the
        scene's, the project's or the app's default (`video_models.resolve`). The endpoint
        follows from the model and the clip mode (`video_generator.endpoint_for`). The model
        asked for, the model that made the clip, where the choice came from and the note when
        they differ (LTX-2.5 has no keyframe interpolation yet) are all stored in `job.input`.

        The negative prompt is the project's own when it has one, otherwise the app's default
        negative prompt (a global setting). It is stored in the request like everything else,
        so a later attempt sends the same one. LTX-2.5 has no such field, so its request has
        none (`video_generator.build_request`).

        The mode comes from the scene's frames as they are now (a last frame attached means
        keyframe interpolation, none means image-to-video from the first frame), and is
        stored with the endpoint, so a frame added or removed later changes nothing.

        Fails the job (returns None) when the scene is no longer ready, or the request would
        break a limit of the approved API (ANALYSIS.md Section 5.3 and 5.8: a wrong request
        wastes a GPU run, so it is refused here).
        """
        await self._phase(job.id, phases.PREPARING_FRAMES)
        async with SessionLocal() as session:
            scene = await session.get(Scene, job.scene_id) if job.scene_id is not None else None
            project = (
                await session.get(Project, job.project_id) if job.project_id is not None else None
            )
            first = await _frame(session, scene.first_frame_asset_id) if scene else None
            last = await _frame(session, scene.last_frame_asset_id) if scene else None
            mode = scene_inputs.clip_mode(scene) if scene else None
            bodies = await contract_guard.approved_bodies(session)
            await session.commit()

        if scene is None or project is None or mode is None:
            await self._fail(job.id, "The scene for this clip no longer exists.")
            return None
        # The inputs may have changed since the click (the description, a frame, the cuts).
        block = clips.generation_block(scene, project, scenes_blocked=None, active=None)
        prompt = scene_prompt.assemble_prompt(
            project.style_prefix, scene.scene_description, project.prompt_suffix
        )
        needs_last = mode == "first_and_last"
        if block is not None or prompt is None or first is None or (needs_last and last is None):
            await self._fail(job.id, block or "The scene is not ready any more.")
            return None
        asked = job.input.get("video_model") if isinstance(job.input, dict) else None
        requested_model, model_source = video_models.resolve(
            asked, scene.video_model, project.video_model, default_video_model
        )
        choice = video_generator.endpoint_for(requested_model, mode)
        endpoint = choice.endpoint

        fps = project.fps
        target = frame_counts.target_frames(scene.start_s, scene.end_s, fps)
        num_frames = frame_counts.request_num_frames(target)
        spec = next((body for body in bodies if api_contract.is_openapi(body)), None)
        try:
            if spec is None:
                raise ValueError(video_generator.no_endpoint_message(endpoint))
            video_generator.check_frames(num_frames, video_generator.frame_limits(spec, endpoint))
            video_generator.check_size(project.gen_width, project.gen_height)
        except ValueError as exc:
            await self._fail(job.id, str(exc))
            return None

        first_sent: Asset
        last_sent: Asset | None = None
        async with SessionLocal() as session:
            try:
                first_sent = await derived_frames.frame_to_send(
                    session, first, project.gen_width, project.gen_height
                )
                if needs_last and last is not None:
                    last_sent = await derived_frames.frame_to_send(
                        session, last, project.gen_width, project.gen_height
                    )
            except derived_frames.FrameNotUsable as exc:
                await self._fail(job.id, str(exc))
                return None

        project_negative_prompt = (project.negative_prompt or "").strip()
        negative_prompt = project_negative_prompt or default_negative_prompt.strip() or None

        request = video_generator.build_request(
            endpoint=endpoint,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=project.gen_width,
            height=project.gen_height,
            num_frames=num_frames,
            fps=fps,
            seed=secrets.randbelow(_SEED_LIMIT),
            partition=partition,
        )
        recorded: dict[str, Any] = {
            **(job.input if isinstance(job.input, dict) else {}),
            "scene": {"index": scene.index, "start_s": scene.start_s, "end_s": scene.end_s},
            "fps": fps,
            "target_frames": target,
            "clip_mode": mode,
            "first_frame": {"original_asset_id": first.id, "sent_asset_id": first_sent.id},
            "last_frame": (
                {"original_asset_id": last.id, "sent_asset_id": last_sent.id}
                if last is not None and last_sent is not None
                else None
            ),
            "video_model": choice.model,
            "video_model_requested": requested_model,
            "video_model_source": model_source,
            "model_note": choice.note,
            "endpoint": endpoint,
            "request": request,
        }
        # Saved before anything is uploaded: the exact request, so a restart or a resubmission
        # sends the same one.
        async with SessionLocal() as session:
            if not await store.update_input(session, job.id, recorded):
                return None  # cancelled while preparing
        return _Plan(
            endpoint=endpoint, request=request, first=first_sent, last=last_sent, recorded=recorded
        )

    async def _upload_and_submit(self, job: Job, base_url: str, plan: _Plan) -> None:
        """Uploads the frame or frames and submits. The server's job id is saved the moment
        the submit answers, with nothing that can fail in between (ANALYSIS.md Section 3.3).

        - 502 at submit: retried once after a pause.
        - 429: the job goes back to the queue and waits.
        - 400 for an unknown asset id: the frame or frames are uploaded again, once.
        - 422 and any other refusal: the job fails with the server's message and is not
          retried, because the request we built is what is wrong.
        """
        storage = get_storage()
        retried_server_error = False
        retried_asset = False
        while True:
            try:
                await self._phase(job.id, phases.UPLOADING_FRAMES)
                uploads: list[dict[str, Any]] = []
                frames = [plan.first] if plan.last is None else [plan.first, plan.last]
                for asset in frames:
                    filename = f"frame-{asset.id}.png"
                    remote_id = await video_generator.upload_frame(
                        base_url, storage.get_path(asset.path), filename
                    )
                    uploads.append(
                        {
                            "asset_id": asset.id,
                            "filename": filename,
                            "size_bytes": asset.size_bytes,
                            "remote_asset_id": remote_id,
                        }
                    )
                if not await self._is_running(job.id):
                    return  # cancelled while uploading: nothing was submitted
                await self._phase(job.id, phases.SUBMITTING)
                # A keyframe plan always has two frames and a first-frame plan one (`_prepare`
                # and `_stored_plan` both guarantee it).
                if video_generator.clip_mode_for(plan.endpoint) == "first_and_last":
                    body = video_generator.with_keyframes(
                        plan.request, uploads[0]["remote_asset_id"], uploads[1]["remote_asset_id"]
                    )
                else:
                    body = video_generator.with_first_frame(
                        plan.request, uploads[0]["remote_asset_id"]
                    )
                provider_job_id = await video_generator.submit(base_url, plan.endpoint, body)
                break
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
                    retried_asset = True  # the server lost an upload: send them again
                    continue
                await self._give_up_starting(job.id, exc)
                return

        submitted = {
            **plan.recorded,
            "server_url": docker_mapped(base_url),
            "uploads": uploads,
            "body": body,
        }
        async with SessionLocal() as session:
            saved = await store.mark_submitted(session, job.id, provider_job_id, submitted)
        if not saved:
            # Cancelled between the submit and here: the server job must be stopped too.
            await self._cancel_quietly(base_url, provider_job_id)

    async def _give_up_starting(self, job_id: int, exc: GpuCallError) -> None:
        async with SessionLocal() as session:
            if exc.kind == "unreachable":
                await store.requeue(session, job_id, phases.WAITING_SERVER_UNREACHABLE)
            elif exc.kind == "busy":
                await store.requeue(session, job_id, phases.WAITING_SERVER_BUSY)
            else:
                await store.fail_job(
                    session,
                    job_id,
                    f"Could not start the clip: {exc} It was not retried automatically.",
                )

    # --- poll ---------------------------------------------------------------------

    async def poll(self, job_id: int) -> bool:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            await session.commit()
        if job is None or job.status != "running" or not job.provider_job_id:
            return False

        try:
            remote = await video_generator.status(base_url, job.provider_job_id)
        except GpuCallError as exc:
            # Never fails the job: no answer means check again. A 404 shows "not found on
            # this server" (and offers Resubmit), it does not fail.
            await self._record_poll(job_id, phase_for_poll_error(exc))
            return False

        # Keep what else the output holds (the count of download retries).
        previous = job.output if isinstance(job.output, dict) else {}
        output = {**previous, "remote": remote.to_json()}
        if remote.status == "queued":
            await self._record_poll(job_id, phases.QUEUED_ON_CLUSTER, output)
        elif remote.status == "running":
            await self._record_poll(job_id, phases.RUNNING_ON_CLUSTER, output)
        elif remote.status == "succeeded":
            # From here the clip is being fetched: it can no longer be cancelled.
            await self._record_poll(job_id, phases.DOWNLOADING_CLIP, output)
            return True
        else:
            await self._server_reported_failure(job, base_url, remote.error)
        return False

    async def _server_reported_failure(self, job: Job, base_url: str, error: str | None) -> None:
        """The server says the job failed.

        A pre-emption (or SIGTERM, exit 137 or 143) is resubmitted unchanged, up to 3 attempts
        in all. Any other failure stops here, with the server's text shown: the guide says not
        to retry blindly in a loop. Either way the failed job is purged on the server first.
        """
        message = error or "The server reported the job as failed."
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            if is_preemption(message) and job.attempt < phases.MAX_ATTEMPTS:
                await store.requeue(
                    session, job.id, phases.preempted(job.attempt + 1), next_attempt=True
                )
                return
            await store.fail_job(session, job.id, f"The GPU server reported an error: {message}")
            await store.merge_output(session, job.id, {"purge": purge})

    # --- finish: download, check, store ---------------------------------------------

    async def finish(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            base_url = await settings_service.get_str(session, GPU_URL_KEY)
            await session.commit()
        if job is None or job.status != "running" or not job.provider_job_id:
            return

        await self._phase(job_id, phases.DOWNLOADING_CLIP)
        storage = get_storage()
        # Downloaded to a temporary file, and moved into place only after ffprobe passes.
        dest = storage.new_temp_path("mp4")
        try:
            try:
                result = await video_generator.download(base_url, job.provider_job_id, dest)
            except GpuCallError as exc:
                await self._result_not_downloaded(job, base_url, exc)
                return
            await self._phase(job_id, phases.CHECKING_CLIP)
            await self._check_and_store(job, base_url, result, dest)
        finally:
            storage.discard(dest)

    async def _result_not_downloaded(self, job: Job, base_url: str, exc: GpuCallError) -> None:
        """The download did not give a clip.

        - 409: the job is not finished after all. The next tick asks again.
        - 410: expired, or not released yet (see `_result_gone`).
        - 404 and no answer: shown as such, never a failure.
        - Anything unusable fails the job.
        """
        if exc.kind == "rejected" and exc.status_code == 409:
            return
        if exc.kind == "rejected" and exc.status_code == 410:
            await self._result_gone(job, base_url)
            return
        async with SessionLocal() as session:
            if exc.kind in ("bad_answer", "rejected"):
                await store.fail_job(session, job.id, f"The clip could not be downloaded: {exc}")
            else:
                await store.record_poll(session, job.id, phase_for_poll_error(exc))

    async def _result_gone(self, job: Job, base_url: str) -> None:
        """HTTP 410 on the result: the clip expired, or the server has not released it yet.

        ANALYSIS.md Section 5.8 says to check the status again. The server can answer 410
        for a while after a job finished (seen on 2026-10-06: the status already said
        `succeeded` with `result_ready`, and the file downloaded fine a minute later). So
        while the status still says the result is ready, the download is tried again at the
        next tick, up to `MAX_RESULT_RETRIES` times. Only a result that is no longer ready
        (it expired), or one that stays 410, is submitted again unchanged.
        """
        recorded = job.output if isinstance(job.output, dict) else {}
        retries = _count(recorded.get("download_retries"))
        try:
            remote = await video_generator.status(base_url, job.provider_job_id or "")
        except GpuCallError as exc:
            async with SessionLocal() as session:
                await store.record_poll(session, job.id, phase_for_poll_error(exc))
            return

        action = after_gone_result(
            remote.status, remote.result_ready, retries=retries, attempt=job.attempt
        )
        async with SessionLocal() as session:
            if action == "try_again":
                output = {**recorded, "remote": remote.to_json(), "download_retries": retries + 1}
                await store.record_poll(session, job.id, phases.RESULT_NOT_READY, output)
            elif action == "resubmit":
                await store.requeue(session, job.id, phases.EXPIRED, next_attempt=True)
            else:
                await store.fail_job(
                    session,
                    job.id,
                    "The clip expired on the server before it could be downloaded, "
                    f"after {phases.MAX_ATTEMPTS} attempts. Regenerate to try again.",
                )

    async def _check_and_store(
        self, job: Job, base_url: str, result: outbound.DownloadResult, dest: Path
    ) -> None:
        recorded = job.input if isinstance(job.input, dict) else {}
        request = recorded.get("request") if isinstance(recorded.get("request"), dict) else {}
        target = recorded.get("target_frames")
        target = target if isinstance(target, int) else 0

        probe = await ffmpeg.probe_video(dest)
        if probe is None or probe.frame_count is None:
            await self._fail_and_purge(
                job, base_url, "The downloaded clip could not be read. Regenerate to try again."
            )
            return
        if probe.frame_count < target:
            await self._fail_and_purge(
                job,
                base_url,
                f"The clip has {probe.frame_count} frames; the scene needs {target}. "
                "Regenerate to try again.",
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
        scene_range = recorded.get("scene") if isinstance(recorded.get("scene"), dict) else {}
        remote = job.output.get("remote") if isinstance(job.output, dict) else None
        provenance: dict[str, Any] = {
            "provider": "gpu",
            "pipeline": remote.get("pipeline") if isinstance(remote, dict) else None,
            "endpoint": recorded.get("endpoint"),
            # Which video model made the clip (an older job names none, but its endpoint
            # does), what was asked for, which level chose it, and why they differ, if they do.
            "video_model": recorded.get("video_model")
            or video_generator.model_for(recorded.get("endpoint")),
            "video_model_requested": recorded.get("video_model_requested"),
            "video_model_source": recorded.get("video_model_source"),
            "model_note": recorded.get("model_note"),
            # How the clip was made: the LTX mode the request named (None for keyframe
            # interpolation, which has no such field) and from which frames.
            "mode": request.get("mode"),
            "clip_mode": video_generator.clip_mode_for(recorded.get("endpoint")),
            "server_url": recorded.get("server_url"),
            "provider_job_id": job.provider_job_id,
            "job_id": job.id,
            "scene_id": job.scene_id,
            "scene_start_s": scene_range.get("start_s"),
            "scene_end_s": scene_range.get("end_s"),
            "prompt": request.get("prompt"),
            "negative_prompt": request.get("negative_prompt"),
            "seed": request.get("seed"),
            "fps": request.get("frame_rate"),
            "num_frames": request.get("num_frames"),
            "target_frames": target,
            "frame_count": probe.frame_count,
            "first_frame_asset_id": _sent_asset_id(recorded.get("first_frame")),
            "last_frame_asset_id": _sent_asset_id(recorded.get("last_frame")),
            "audio": audio,
        }
        output: dict[str, Any] = {
            "clip": {
                "frame_count": probe.frame_count,
                "target_frames": target,
                "num_frames": request.get("num_frames"),
                "width": probe.width,
                "height": probe.height,
                "fps": probe.fps,
                "duration_s": probe.duration_s,
                "size_bytes": result.size_bytes,
                "audio": audio,
            },
            "remote": remote,
        }
        retries = _count(job.output.get("download_retries") if isinstance(job.output, dict) else 0)
        if retries:
            output["download_retries"] = retries

        storage = get_storage()
        temp = TempFile(path=dest, size_bytes=result.size_bytes, sha256=result.sha256)
        stored = await storage.save(temp, job.project_id, "mp4")

        # The clip, the finished job and the scene's selected take are saved together or not
        # at all (DATABASE_STRUCTURE.md Section 7).
        async with SessionLocal() as session:
            asset = await add_asset(
                session,
                project_id=job.project_id,
                kind="clip",
                stored=stored,
                mime="video/mp4",
                size_bytes=result.size_bytes,
                sha256=result.sha256,
                source="ai",
                duration_s=probe.duration_s,
                width=probe.width,
                height=probe.height,
                provenance=provenance,
            )
            if not await store.finish_job(session, job.id, output, result_asset_id=asset.id):
                await session.rollback()
                # Cancelled in the meantime. Stored files are never deleted.
                _logger.warning(
                    "job %d: clip stored but the job is no longer running: %s",
                    job.id,
                    stored.relative_path,
                )
                return
            await session.execute(
                update(Scene)
                .where(Scene.id == job.scene_id, Scene.project_id == job.project_id)
                .values(selected_clip_asset_id=asset.id)
                .execution_options(synchronize_session=False)
            )
            await session.commit()

        _logger.info(
            "job %d: clip stored: scene=%s asset=%d frames=%d/%d %sx%s %.2f fps audio=%s",
            job.id,
            job.scene_id,
            asset.id,
            probe.frame_count,
            target,
            probe.width,
            probe.height,
            probe.fps or 0.0,
            audio["codec"] if audio else "none",
        )

        # Best effort: a failure here is recorded and never fails the clip.
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.merge_output(session, job.id, {"purge": purge})

    async def _fail_and_purge(self, job: Job, base_url: str, message: str) -> None:
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.fail_job(session, job.id, message)
            await store.merge_output(session, job.id, {"purge": purge})

    # --- the server's cleanup and cancel (best effort) -----------------------------------

    @staticmethod
    async def _purge(base_url: str, provider_job_id: str | None) -> dict[str, Any]:
        """Deletes the finished job and its uploads on the server. A failure is recorded
        and ignored (ANALYSIS.md Section 5.3).
        """
        if not provider_job_id:
            return {"skipped": "no server job"}
        try:
            return (await video_generator.cleanup(base_url, provider_job_id)).to_json()
        except GpuCallError as exc:
            _logger.warning("could not purge server job %s: %s", provider_job_id, exc)
            return {"error": str(exc)}

    @staticmethod
    async def _cancel_quietly(base_url: str, provider_job_id: str) -> None:
        try:
            await video_generator.cancel(base_url, provider_job_id)
        except GpuCallError as exc:
            _logger.warning("could not cancel server job %s: %s", provider_job_id, exc)

    # --- small helpers ---------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _record_poll(job_id: int, phase: str, output: dict[str, Any] | None = None) -> None:
        async with SessionLocal() as session:
            await store.record_poll(session, job_id, phase, output)

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)

    @staticmethod
    async def _is_running(job_id: int) -> bool:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            await session.commit()
        return job is not None and job.status == "running"


async def _frame(session: AsyncSession, asset_id: int | None) -> Asset | None:
    if asset_id is None:
        return None
    asset = await session.get(Asset, asset_id)
    return asset if asset is not None and asset.kind == "frame" else None


def after_gone_result(
    remote_status: str, result_ready: bool, *, retries: int, attempt: int
) -> Literal["try_again", "resubmit", "fail"]:
    """What to do when the result download answered 410 and the status was asked again.

    The server still calls the job finished with its result ready: it has not released the
    file yet, so try the download again at the next tick (a limited number of times).
    Otherwise the result is gone: submit the same request again, up to `MAX_ATTEMPTS`.
    """
    if remote_status == "succeeded" and result_ready and retries < MAX_RESULT_RETRIES:
        return "try_again"
    return "resubmit" if attempt < phases.MAX_ATTEMPTS else "fail"


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _sent_asset_id(frame: object) -> int | None:
    """The id of the file that was sent, from `input.first_frame` or `input.last_frame`."""
    if not isinstance(frame, dict):
        return None
    value = frame.get("sent_asset_id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None
