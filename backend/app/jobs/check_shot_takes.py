"""The `check_shot_takes` job: the technical check of the takes made before checks existed
(PHASE-029).

Every new take is checked when its clip is stored (`jobs/generate_shot.py`). A take stored
earlier has no check (`shot_take.validation` is NULL), so it is not selected and not rendered.
This local job reads each such take's stored clip with ffprobe, decodes it to the end, judges it
with the same rules (`services/shot_takes.judge_take`) and writes the result on the take.

It only writes `validation`. It never changes `selected_at` (a take that passes is the shot's
selected take again if it was the newest choice), and it never starts a GPU run: a clip that
fails here is shown as failed and the owner decides whether to generate the shot again.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, ShotTake
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.handlers import JobHandler
from app.services import shot_takes, take_validation
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = shot_takes.CHECK_JOB_TYPE

_UNREADABLE: Final = take_validation.Measured(
    frame_count=None, width=None, height=None, duration_s=None, has_audio=False, readable=False
)


class CheckShotTakesHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or job.project_id is None:
                await session.commit()
                return
            project_id = job.project_id
            statement = (
                select(ShotTake.id)
                .where(
                    ShotTake.project_id == project_id,
                    ShotTake.path.is_not(None),
                    ShotTake.validation.is_(None),
                )
                .order_by(ShotTake.id)
            )
            take_ids = list((await session.execute(statement)).scalars())

        passed = 0
        failed: list[int] = []
        for number, take_id in enumerate(take_ids, start=1):
            await self._phase(job_id, phases.checking_take(number, len(take_ids)))
            if await self._check_one(take_id):
                passed += 1
            else:
                failed.append(take_id)

        output: dict[str, Any] = {
            "checked": len(take_ids),
            "passed": passed,
            "failed_take_ids": failed,
        }
        async with SessionLocal() as session:
            await store.finish_job(session, job_id, output)
            await session.commit()
        _logger.info("job %d: %d clips checked, %d passed", job_id, len(take_ids), passed)

    @staticmethod
    async def _check_one(take_id: int) -> bool:
        """Checks and records one take. True when it passed."""
        async with SessionLocal() as session:
            take = await session.get(ShotTake, take_id)
            if take is None or take.path is None or take.validation is not None:
                return False
            measured = _UNREADABLE
            try:
                path = get_storage().get_path(take.path)
            except StorageError:
                path = None
            if path is not None and path.is_file():
                measured, _probe = await shot_takes.measure_clip(path)
            request_body = await _request_body_of(session, take)
            validation = await shot_takes.judge_take(session, take, measured, request_body)
            take.validation = validation
            await session.commit()
            return bool(validation["passed"])

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")


async def _request_body_of(session: AsyncSession, take: ShotTake) -> dict[str, Any] | None:
    """The body that was sent for the take, when its job still exists."""
    if take.job_id is None:
        return None
    job = await session.get(Job, take.job_id)
    recorded = job.input if job is not None and isinstance(job.input, dict) else {}
    body = recorded.get("request")
    return body if isinstance(body, dict) else None
