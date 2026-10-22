"""The `generate_shot` job: one take of one shot's clip, made by MiniMax H3 (PHASE-027).

It is the Video lab's clip job (`GenerateLabVideoHandler`) with another place to put the result.
`start` is inherited as it is: `services/shot_takes._queue` stores the exact request on the job
(`endpoint`, `request`, the ordered `references` and the ordered `audios`, the same shape the lab
writes), so the pictures and the dialogue audio are uploaded in order, the request is submitted,
and a pre-emption sends the same request again. Polling, the download, the clean-up on the server,
cancelling and the GPU slots (an H3 clip holds 4 or 8 GPUs, `pools.slot_cost`) are the shared ones
of `RemoteVideoHandler`.

Only `_check_and_store` differs. The clip is checked with ffprobe, stored under the **project's**
media folder (not `media/lab/`), and written on the `shot_take` row the job was queued with
(found by `shot_take.job_id`): the file, its checksum, its size and frame count and its audio
track, and `selected_at`, so the take that has just finished is the shot's selected take. The row
and the finished job are saved in one transaction. The clip is not trimmed here: the render does
that, to the shot's exact length (D-9). It is not judged either: validation and retry are
PHASE-029.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select

from app.core import outbound
from app.db.models import Job, ShotTake
from app.db.session import SessionLocal
from app.jobs import store
from app.jobs.generate_lab_video import GenerateLabVideoHandler
from app.services import ffmpeg, shot_takes
from app.services.storage import TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = shot_takes.JOB_TYPE


class GenerateShotHandler(GenerateLabVideoHandler):
    job_type = JOB_TYPE

    async def _check_and_store(
        self, job: Job, base_url: str, result: outbound.DownloadResult, dest: Path
    ) -> None:
        if job.project_id is None:
            # A shot's job is always made with its project; this only guards a damaged row.
            await self._fail_and_purge(job, base_url, "The clip belongs to no project.")
            return
        recorded = job.input if isinstance(job.input, dict) else {}

        probe = await ffmpeg.probe_video(dest)
        if probe is None or probe.frame_count is None:
            await self._fail_and_purge(
                job, base_url, "The downloaded clip could not be read. Generate it again."
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
        stored = await storage.save(temp, job.project_id, "mp4")

        # The take and the finished job are saved together or not at all.
        async with SessionLocal() as session:
            statement = select(ShotTake).where(ShotTake.job_id == job.id)
            take = (await session.execute(statement)).scalars().first()
            if take is not None:
                take.path = stored.relative_path
                take.size_bytes = result.size_bytes
                take.sha256 = result.sha256
                take.width = probe.width
                take.height = probe.height
                take.frame_count = probe.frame_count
                take.duration_s = probe.duration_s
                take.audio = audio
                take.selected_at = await shot_takes.selection_time(
                    session, take.project_id, take.scene_id, take.shot_id
                )
                output["take_id"] = take.id
                output["take_number"] = take.take_number
            else:
                _logger.warning("job %d: clip stored but its take is gone", job.id)
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
            "job %d: shot clip stored: take=%s frames=%d %sx%s %.2f fps audio=%s",
            job.id,
            output.get("take_id"),
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
