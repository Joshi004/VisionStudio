"""The `extract_cast` job: a language model reads the whole script and lists the characters and
the places of its story, each with a description (ANALYSIS.md Section 6.2; project cast).

It is a paid job, so the rules of the scene proposal hold here too:

- It only starts from a click (`POST /api/projects/{id}/extract-cast`) or from an automatic run.
- Every answer is saved on the job the moment it arrives, before anything is checked
  (`jobs/llm_call.py`), so a crash after the paid call still leaves the answer behind.
- At most 2 attempts, the second only for a rate limit, a server error, no answer, or an
  answer that cannot be used. A refusal (HTTP 400, 401, 403, 404, 422) is never retried.
- A restart never re-runs it (`never_rerun`): the dispatcher fails it with a message.

There is no rule-based fallback (nothing but the model can tell who is in a story), so two failed
attempts fail the job. A successful answer replaces the project's whole cast
(`cast.replace_cast`), so the endpoint asks for confirmation when there is a cast already.

It is a local-style job: everything happens in `start`. There is no provider job id. Logs hold
the job id, what each attempt did and its token counts, never the prompt or the answer.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import Project
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import cast as cast_service
from app.services import cast_extraction, llm_target, scene_planner, transcript_matching
from app.services.cast_extraction import CastList

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = cast_service.EXTRACT_JOB
MODEL_KEY: Final = "description_llm_model"
# The model reasons before it answers (see `plan_scenes`). The answer is streamed, so this limits
# only the whole call.
REQUEST_TIMEOUT_S: Final = 600.0

# The jobs that read or write the cast: a cast replaced under them would leave them with nothing.
_BLOCKING_JOBS: Final = (
    cast_service.REFERENCE_PROMPT_JOB,
    cast_service.REFERENCE_IMAGE_JOB,
    cast_service.ASSIGN_JOB,
)


def _read_answer(result: llm.ChatResult) -> tuple[str | None, CastList | None]:
    """Whether an answer can be used: `(None, cast)` if so, else `(why not, None)`."""
    if result.finish_reason == "length":
        return "The model's answer was cut off because it reached the token limit.", None
    try:
        return None, cast_extraction.parse_answer(result.content)
    except ValueError as exc:
        return str(exc), None


class ExtractCastHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            project = await session.get(Project, job.project_id)
            target = await llm_target.resolve(session, MODEL_KEY)
            await session.commit()

        if project is None:
            await self._fail(job_id, "The project no longer exists.")
            return
        script = project.script_text or ""
        if not script.strip():
            await self._fail(job_id, "The script is empty. Paste the script and try again.")
            return
        words = len(script.split())
        if words > scene_planner.MAX_SCRIPT_WORDS:
            await self._fail(
                job_id,
                f"This script has {words:,} words; finding the cast handles 1 to "
                f"{scene_planner.MAX_SCRIPT_WORDS:,}.",
            )
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = cast_extraction.build_request(
            script,
            model=target.model,
            style=project.style_prefix,
            instructions=project.description_instructions,
        )
        job_input.update(
            # The script the cast was found in, so the page can tell when it has changed since.
            script_sha256=transcript_matching.script_sha256(script),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, _read_answer, timeout_s=REQUEST_TIMEOUT_S
        )
        found = outcome.value
        if found is None:
            await self._fail(job_id, f"The cast could not be found: {outcome.failure}")
            return

        await self._save(job_id, project.id, found, outcome)

    # --- Saving the cast ------------------------------------------------------------

    async def _save(
        self, job_id: int, project_id: int, found: CastList, outcome: llm_call.Outcome
    ) -> None:
        """Replaces the project's cast and finishes the job in one transaction."""
        await self._phase(job_id, phases.SAVING_CAST)
        output = {
            **outcome.record(),
            "content": None,
            "characters": len(found.characters),
            "locations": len(found.locations),
        }
        blocked = 0
        async with SessionLocal() as session:
            # Finishing the job first takes the database's write lock, so the check below and
            # the replacement cannot be interleaved with another writer.
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            blocked = len(await cast_service.active_jobs(session, project_id, _BLOCKING_JOBS))
            if blocked:
                await session.rollback()
            else:
                await cast_service.replace_cast(session, project_id, found)
                await session.commit()

        if blocked:
            noun = "job is" if blocked == 1 else "jobs are"
            await self._fail(
                job_id,
                f"{blocked} cast {noun} running that started while this ran, so the cast was "
                "not replaced. Wait for them, then find the cast again.",
            )
            return
        _logger.info(
            "job %d: cast found: characters=%d locations=%d usage=%s",
            job_id,
            len(found.characters),
            len(found.locations),
            outcome.usage,
        )

    # --- Small helpers --------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
