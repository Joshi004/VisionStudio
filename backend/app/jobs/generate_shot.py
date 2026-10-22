"""The `generate_shot` job: one take of one shot's clip, made by MiniMax H3 (PHASE-027).

It is the Video lab's clip job (`GenerateLabVideoHandler`) with another place to put the result.
`start` is inherited as it is: `services/shot_takes._queue` stores the exact request on the job
(`endpoint`, `request`, the ordered `references` and the ordered `audios`, the same shape the lab
writes), so the pictures and the dialogue audio are uploaded in order, the request is submitted,
and a pre-emption sends the same request again. Polling, the download, the clean-up on the server,
cancelling and the GPU slots (an H3 clip holds 4 or 8 GPUs, `pools.slot_cost`) are the shared ones
of `RemoteVideoHandler`.

Only `_check_and_store` differs. The clip is read with ffprobe and decoded to the end, stored
under the **project's** media folder (not `media/lab/`), and written on the `shot_take` row the
job was queued with (found by `shot_take.job_id`): the file, its checksum, its size and frame
count and its audio track, and its technical check (`validation`, PHASE-029). `selected_at` is
set only when the clip **passed**, so the take that has just finished is the shot's selected take
only if it is good. The row and the finished job are saved in one transaction.

A take whose shot carries dialogue is **not selected here** (PHASE-031): when its clip passed, the
`check_take_dialogue` job is queued in the same transaction, and that job selects the take if the
speech in the clip matches the dialogue.

The clip is not trimmed here: the render does that, to the shot's exact length (D-9).

A clip that fails for a reason a new seed can fix (it cannot be read or decoded, it has no sound,
its size or number of frames is wrong) starts another take by itself after the row is saved
(`shot_takes.queue_retry`, up to the `shot_take_max_retries` setting). A shot whose own length is
out of the H3 bounds is not retried: its scene has to be planned again.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select

from app.core import outbound
from app.db.models import Job, ShotTake
from app.db.session import SessionLocal
from app.jobs import dispatcher, store
from app.jobs.generate_lab_video import GenerateLabVideoHandler
from app.services import shot_takes, take_validation
from app.services.storage import TempFile, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = shot_takes.JOB_TYPE


async def start_dependents(take_id: int | None) -> None:
    """Queues the shot that continues the shot of a take that has just become selected, when the
    take was made as part of **Generate all** or **Generate scene** (PHASE-032). Best effort and
    never raises: the take is already saved. Also called by the dialogue check job.
    """
    if take_id is None:
        return
    try:
        async with SessionLocal() as session:
            job = await shot_takes.start_dependents(session, take_id)
    except Exception:
        _logger.exception("take %d: the shot that continues it could not be queued", take_id)
        return
    if job is not None:
        dispatcher.nudge()
        _logger.info(
            "take %d selected: the shot that continues it queued as job %d", take_id, job.id
        )


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
        request_body = recorded.get("request")
        request_body = request_body if isinstance(request_body, dict) else None

        measured, probe = await shot_takes.measure_clip(dest)
        if probe is None or not measured.readable:
            take_id = await self._record_unreadable(job, measured, request_body)
            await self._fail_and_purge(
                job, base_url, "The downloaded clip could not be read. Generate it again."
            )
            await self._retry(take_id)
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
        retry_take_id: int | None = None
        selected_take_id: int | None = None
        queued_dialogue_check = False
        async with SessionLocal() as session:
            statement = select(ShotTake).where(ShotTake.job_id == job.id)
            take = (await session.execute(statement)).scalars().first()
            if take is not None:
                validation = await shot_takes.judge_take(session, take, measured, request_body)
                take.path = stored.relative_path
                take.size_bytes = result.size_bytes
                take.sha256 = result.sha256
                take.width = probe.width
                take.height = probe.height
                take.frame_count = probe.frame_count
                take.duration_s = probe.duration_s
                take.audio = audio
                take.validation = validation
                if validation["passed"]:
                    if await shot_takes.dialogue_lines(session, take):
                        # A take with dialogue is selected only after its speech has been
                        # checked (PHASE-031). The check is queued in this transaction, so the
                        # take is never seen as "not checked" without a job making it.
                        await shot_takes.queue_dialogue_check(session, take, commit=False)
                        queued_dialogue_check = True
                    else:
                        take.selected_at = await shot_takes.selection_time(
                            session, take.project_id, take.scene_id, take.shot_id
                        )
                        selected_take_id = take.id
                elif validation["kind"] == "clip":
                    retry_take_id = take.id
                output["take_id"] = take.id
                output["take_number"] = take.take_number
                output["check"] = {
                    "passed": validation["passed"],
                    "problems": [problem["code"] for problem in validation["problems"]],
                    "dialogue_check_queued": queued_dialogue_check,
                }
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
            "job %d: shot clip stored: take=%s frames=%d %sx%s %.2f fps audio=%s check=%s",
            job.id,
            output.get("take_id"),
            probe.frame_count,
            probe.width,
            probe.height,
            probe.fps or 0.0,
            audio["codec"] if audio else "none",
            output.get("check"),
        )
        if queued_dialogue_check:
            dispatcher.nudge()

        # Best effort: a failure here is recorded and never fails the clip.
        purge = await self._purge(base_url, job.provider_job_id)
        async with SessionLocal() as session:
            await store.merge_output(session, job.id, {"purge": purge})

        await self._retry(retry_take_id)
        await start_dependents(selected_take_id)

    @staticmethod
    async def _record_unreadable(
        job: Job, measured: take_validation.Measured, request_body: dict[str, Any] | None
    ) -> int | None:
        """Writes the failed check on the take of a clip that could not be read, and returns the
        take's id. The take has no file: it reads as failed, and the job fails after this.
        """
        async with SessionLocal() as session:
            statement = select(ShotTake).where(ShotTake.job_id == job.id)
            take = (await session.execute(statement)).scalars().first()
            if take is None:
                return None
            take.validation = await shot_takes.judge_take(session, take, measured, request_body)
            await session.commit()
            return take.id

    @staticmethod
    async def _retry(take_id: int | None) -> None:
        """Queues the automatic retry of a take that failed its check, when the rules allow it.
        Never raises: the clip's own outcome is already saved.
        """
        if take_id is None:
            return
        try:
            async with SessionLocal() as session:
                retry_job = await shot_takes.queue_retry(session, take_id)
        except Exception:
            _logger.exception("take %d: the automatic retry could not be queued", take_id)
            return
        if retry_job is not None:
            dispatcher.nudge()
            _logger.info("take %d failed its check: retry queued as job %d", take_id, retry_job.id)
