"""The `prepare_footage_file` job: makes an owner's video ready to be shown as footage (FTG-003,
`Footage_broll_implementation_phases.md` FT-7 and §4.7).

`services/footage_files.receive_file` stores the video as it came (`footage_item.upload_*`) and
queues this job with `input` `{item_id}`. The job:

1. reads the stored original (the item's `upload_path`) and its frame rate;
2. makes the copy that is shown (`services/footage_frames.prepare`): H.264, `yuv420p`, **no
   sound**, the shorter side at most 1080 pixels, a constant frame rate;
3. checks the copy with ffprobe: H.264, `yuv420p`, no audio stream, not above the size limit, and
   a length within half a second of the original's;
4. writes the strip (a frame every 0.5 s) and finds the cut times of the copy;
5. stores the copy and the strip, and in one transaction fills the item (`video_*`, `strip_*`,
   `cuts`, `capture`, `prepare_job_id`) and makes it usable, together with finishing the job.

The original stays stored and unchanged. A failure writes the reason to `item.checks.prepare`
(the card shows it) and fails the job. A local job: nothing is paid for and no model is asked.
After a restart it runs again from the start. Logs hold ids and sizes, never file names.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from app.db.models import FootageItem
from app.db.session import SessionLocal
from app.jobs import phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.services import ffmpeg, footage_files, footage_frames
from app.services.storage import Storage, StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = footage_files.JOB_TYPE
# How far the copy's length may differ from the original's, in seconds.
DURATION_TOLERANCE_S: Final = 0.5


class PrepareFailed(Exception):
    """The video cannot be made ready. The message is meant to be shown to the user."""


class PrepareFootageFileHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def start(self, job_id: int) -> None:
        storage = get_storage()
        temp_paths: list[Path] = []
        item_id: int | None = None
        try:
            async with SessionLocal() as session:
                job = await store.get_job(session, job_id)
                await session.commit()
            if job is None or job.status != "running":
                return
            recorded = job.input if isinstance(job.input, dict) else {}
            value = recorded.get(footage_files.ITEM_KEY)
            item_id = value if isinstance(value, int) and not isinstance(value, bool) else None
            if item_id is None:
                raise PrepareFailed("The job names no video.")
            await self._prepare(job_id, item_id, storage, temp_paths)
        except (PrepareFailed, footage_frames.FramesError) as exc:
            await self._fail(job_id, item_id, str(exc))
        except (StorageError, OSError) as exc:
            _logger.warning("job %d: the footage video could not be stored: %s", job_id, exc)
            await self._fail(job_id, item_id, "The video could not be stored.")
        finally:
            for path in temp_paths:
                storage.discard(path)

    async def _prepare(
        self, job_id: int, item_id: int, storage: Storage, temp_paths: list[Path]
    ) -> None:
        async with SessionLocal() as session:
            item = await session.get(FootageItem, item_id)
            await session.commit()
        if item is None or item.origin != "owner" or item.kind != "video" or not item.upload_path:
            raise PrepareFailed("The video this job was queued for is gone.")
        if item.usable:
            # Made ready by an earlier run that was cut off before the job was marked finished.
            async with SessionLocal() as session:
                await store.finish_job(session, job_id, {"item_id": item_id, "already": True})
                await session.commit()
            return
        source = storage.get_path(item.upload_path)
        if not source.is_file():
            raise PrepareFailed("The video file could not be found on disk.")

        original = await ffmpeg.probe_video(source)
        if original is None or original.duration_s is None:
            raise PrepareFailed("The video could not be read.")

        await phase_writer.note(job_id, phases.PREPARING_FOOTAGE_VIDEO)
        video_temp = storage.new_temp_path("mp4")
        temp_paths.append(video_temp)
        await footage_frames.prepare(source, video_temp, original.fps or footage_frames.DEFAULT_FPS)
        made = await ffmpeg.probe_video(video_temp)
        duration_s = _check_copy(made, original.duration_s)
        assert made is not None and made.width is not None and made.height is not None

        await phase_writer.note(job_id, phases.FINDING_FOOTAGE_CUTS)
        layout = footage_frames.strip_layout(duration_s)
        strip_temp = storage.new_temp_path("jpg")
        temp_paths.append(strip_temp)
        await footage_frames.write_strip(video_temp, strip_temp, layout)
        cuts = await footage_frames.find_cuts(video_temp, duration_s)

        await phase_writer.note(job_id, phases.SAVING_FOOTAGE_VIDEO)
        video_file = await storage.describe_temp(video_temp)
        strip_file = await storage.describe_temp(strip_temp)
        video_stored = await storage.save(video_file, item.project_id, "mp4")
        strip_stored = await storage.save(strip_file, item.project_id, "jpg")
        new_paths = [video_stored.relative_path, strip_stored.relative_path]

        async with SessionLocal() as session:
            row = await session.get(FootageItem, item_id)
            if row is None:
                await self._remove(storage, new_paths)
                raise PrepareFailed("The video this job was queued for is gone.")
            row.video_path = video_stored.relative_path
            row.video_sha256 = video_file.sha256
            row.strip_path = strip_stored.relative_path
            row.strip_sha256 = strip_file.sha256
            row.cuts = cuts
            row.capture = _capture(row.capture, made, duration_s, layout)
            row.prepare_job_id = job_id
            row.checks = None
            row.usable = True
            output = {
                "item_id": item_id,
                "duration_s": duration_s,
                "video_px": [made.width, made.height],
                "fps": made.fps,
                "cuts": len(cuts),
                "video_bytes": video_file.size_bytes,
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the item stays as it was.
                await session.rollback()
                await self._remove(storage, new_paths)
                return
            await session.commit()
        _logger.info(
            "job %d: footage video of item %d ready (%.1f s, %d cuts)",
            job_id,
            item_id,
            duration_s,
            len(cuts),
        )

    @staticmethod
    async def _remove(storage: Storage, paths: list[str]) -> None:
        """Takes away files this run stored and nothing refers to."""
        for path in paths:
            try:
                await storage.delete_media(path)
            except (StorageError, OSError):
                _logger.warning("a footage file of a cancelled job was left: %s", path)

    @staticmethod
    async def _fail(job_id: int, item_id: int | None, message: str) -> None:
        async with SessionLocal() as session:
            if item_id is not None:
                item = await session.get(FootageItem, item_id)
                if item is not None and not item.usable:
                    item.checks = {"prepare": message}
                    await session.commit()
            await store.fail_job(session, job_id, message)


def _check_copy(made: ffmpeg.VideoProbe | None, original_s: float) -> float:
    """Checks the copy against what was asked for. Returns its length in seconds. Raises
    PrepareFailed."""
    if made is None or made.width is None or made.height is None or made.duration_s is None:
        raise PrepareFailed("The prepared video could not be read.")
    if made.codec_name != "h264" or made.pix_fmt != "yuv420p":
        raise PrepareFailed("The prepared video is not H.264 in the expected format.")
    if made.audio is not None:
        raise PrepareFailed("The prepared video still has sound.")
    if min(made.width, made.height) > footage_frames.MAX_SHORT_SIDE:
        raise PrepareFailed("The prepared video is larger than the limit.")
    if abs(made.duration_s - original_s) > DURATION_TOLERANCE_S:
        raise PrepareFailed("The prepared video is not as long as the original.")
    return round(made.duration_s, 3)


def _capture(
    earlier: Any,
    made: ffmpeg.VideoProbe,
    duration_s: float,
    layout: footage_frames.StripLayout,
) -> dict[str, Any]:
    """The item's `capture` once the copy exists: what it had, with the copy's length (the part
    shown by default cannot go past it) and the facts the card and the render need."""
    capture: dict[str, Any] = dict(earlier) if isinstance(earlier, dict) else {}
    use = capture.get("use")
    if isinstance(use, dict) and isinstance(use.get("end_s"), int | float):
        capture["use"] = {**use, "end_s": round(min(float(use["end_s"]), duration_s), 3)}
    capture.update(
        {
            "duration_s": duration_s,
            "video_px": [made.width, made.height],
            "fps": made.fps,
            "strip_every_s": layout.every_s,
            "strip_columns": layout.columns,
            "strip_rows": layout.rows,
            "strip_tile_px": [layout.tile_w, layout.tile_h],
            "strip_frames": layout.frames,
        }
    )
    return capture
