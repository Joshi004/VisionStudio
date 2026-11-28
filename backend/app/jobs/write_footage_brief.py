"""The `write_footage_brief` job: writes a footage research round's brief into the files folder
(FTG-007, `Footage_broll_implementation_phases.md` §4.3, §4.5).

`services/footage_rounds.start_brief` queues the job (`input.mark_list_version` is only a note of
the version that was newest then). When it runs it reads the marks and the story as they are at
that moment (`footage_rounds.make_round`), makes `footage/<project_id>/r<n>/` with
`brief/footage.json`, `brief/README.md` and an empty `results/`, and saves the `footage_round` row
in the same transaction that marks the job succeeded. No model is called, and nothing is paid. If
the marks cannot be sent to research any more (they changed while the job waited), nothing is
written and the job fails with the reason.

`job.output`: `{round_id, round_no, folder, marks, brief_sha256}`. `marks` is how many marks the
brief carries. Logs hold the job id, the round and the count, never the marks.

A local job with `start_again`: after a restart it runs from the start. A folder written for a row
that was never saved is left unused, and the next round takes the next number.
"""

from __future__ import annotations

import logging
from typing import Final

from app.db.models import Project
from app.db.session import SessionLocal
from app.jobs import phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.services import footage_rounds

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = footage_rounds.JOB_TYPE


class WriteFootageBriefHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "local"
    restart_rule = "start_again"

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            project_id = job.project_id
            await session.commit()
        if project_id is None:
            await self._fail(job_id, "This job has no project.")
            return

        await phase_writer.note(job_id, phases.WRITING_FOOTAGE_BRIEF)
        async with SessionLocal() as session:
            project = await session.get(Project, project_id)
            if project is None:
                await store.fail_job(session, job_id, "The project no longer exists.")
                return
            try:
                row = await footage_rounds.make_round(session, project, job_id)
            except footage_rounds.FootageRoundsError as exc:
                await session.rollback()
                await store.fail_job(session, job_id, str(exc))
                return
            round_no = row.round_no
            output = {
                "round_id": f"r{round_no}",
                "round_no": round_no,
                "folder": row.folder,
                "marks": len(row.brief["marks"]),
                "brief_sha256": row.brief_sha256,
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the row is not kept, and neither is the folder.
                await session.rollback()
                await footage_rounds.discard_round(project_id, round_no)
                return
            await session.commit()
        _logger.info(
            "job %d: footage brief r%d written for project %d (%d marks)",
            job_id,
            round_no,
            project_id,
            output["marks"],
        )

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
