"""The `import_evidence` job: imports the newest research round's results (EVD-006,
`Evidence_layer_implementation_phases.md` §4.6).

`services/evidence_import.start_import` queues the job (`input` is `{round_no, round_id}`, the
round that was newest then). When it runs, `evidence_import.make_import` reads the round's
`results/` folder, checks every piece of evidence, copies the files of the usable pieces into
storage, and adds the `evidence_import` row and its `evidence_item` rows, which are saved in the
same transaction that marks the job succeeded. No model is called, and nothing is paid. The round
folder is only read.

`job.output`: `{import_id, version, round_id, report}` (`report` as stored on the import). If the
round is no longer the newest, or no longer has the claims that count, nothing is saved and the
job fails with the reason. If saving fails, the files this job copied are removed again; a file
an earlier import stored is never removed.

The transcription of each clip of a sound bite claim is queued with the rows
(`transcribe_evidence_clip`, SB-006); this job only makes them.

A local job with `start_again`: after a restart it runs from the start. Files copied by a run
that was cut off by a restart stay in the media folder unused.
"""

from __future__ import annotations

import logging
from typing import Final

from app.db.models import Project
from app.db.session import SessionLocal
from app.jobs import dispatcher, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.services import evidence_import
from app.services.storage import StorageError

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = evidence_import.JOB_TYPE


class ImportEvidenceHandler(JobHandler):
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
            round_no = job.input.get("round_no") if isinstance(job.input, dict) else None
            await session.commit()
        if project_id is None or not isinstance(round_no, int):
            await self._fail(job_id, "This job has no project or round.")
            return

        await phase_writer.note(job_id, phases.IMPORTING_EVIDENCE)
        new_paths: list[str] = []
        async with SessionLocal() as session:
            project = await session.get(Project, project_id)
            if project is None:
                await store.fail_job(session, job_id, "The project no longer exists.")
                return
            try:
                record = await evidence_import.make_import(
                    session, project, job_id, round_no, new_paths
                )
                output = {
                    "import_id": record.id,
                    "version": record.version,
                    "round_id": f"r{round_no}",
                    "report": record.report,
                }
                if not await store.finish_job(session, job_id, output):
                    # The job was cancelled meanwhile: the rows are not kept, and neither are
                    # the files.
                    await session.rollback()
                    await evidence_import.discard_files(new_paths)
                    return
                await session.commit()
                # Clips of sound bite claims were queued for transcription with the rows.
                dispatcher.nudge()
            except evidence_import.EvidenceImportError as exc:
                await session.rollback()
                await evidence_import.discard_files(new_paths)
                await store.fail_job(session, job_id, str(exc))
                return
            except (StorageError, OSError) as exc:
                _logger.warning("job %d: the evidence files could not be stored: %s", job_id, exc)
                await session.rollback()
                await evidence_import.discard_files(new_paths)
                await store.fail_job(
                    session, job_id, f"The evidence files could not be stored: {exc}"
                )
                return
            except BaseException:
                await session.rollback()
                await evidence_import.discard_files(new_paths)
                raise
        _logger.info(
            "job %d: round r%d imported for project %d as import %d (%s)",
            job_id,
            round_no,
            project_id,
            output["version"],
            output["report"],
        )

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
