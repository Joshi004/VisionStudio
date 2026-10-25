"""The `place_music` job: every selected music take gets its exact place on the finished video's
timeline (MUSIC-011, `Music_implementation_phases.md` Section 4.6 and 4.7).

`services/music_placement.start_run` creates the job. The job gathers what the placement is made
from (`music_placement.gather`, which measures the sounds it needs, cached by file hash), and
`services/music_placer.place` does the placing: pure code, the same every time. When code cannot
find a good point for an anchor, or the anchor matters a great deal, `place` returns questions,
each with the real moments it found. All of them go to the language model in **one** call
(`music_placement_writer`); the model only names one of the listed moments. Then `place` runs
again with the answers. A call that fails does not fail the job: those anchors are flagged for the
owner, and the placement is saved without the model's help.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold: at most 2 attempts (the second told what was wrong with the first
answer), a refusal never retried, every answer saved the moment it arrives, and a restart never
re-runs it (`never_rerun`). With nothing to ask, no call is made. The placement row is saved in
the same transaction that marks the job succeeded. Logs hold the job id and counts, never the
story or the answers.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import Project
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, music_placement, music_placement_writer, music_placer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = music_placement.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_TOO_LONG = "The model's answer was cut off because it reached the token limit."
_NO_PROJECT = "The project of this job no longer exists."


def _reader(questions: list[dict[str, Any]], warnings: list[str]) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, Any]:
        if result.finish_reason == "length":
            return _TOO_LONG, None
        try:
            answer = music_placement_writer.check_choice_answer(
                music_placement_writer.parse_answer(result.content), questions, warnings
            )
        except ValueError as exc:
            return str(exc), None
        return None, answer

    return read


class PlaceMusicHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running":
                await session.commit()
                return
            project_id = job.project_id
            job_input: dict[str, Any] = dict(job.input) if isinstance(job.input, dict) else {}
            await session.commit()
        if project_id is None:
            await self._fail(job_id, _NO_PROJECT)
            return

        await self._phase(job_id, phases.MEASURING_SOUNDS)
        async with SessionLocal() as session:
            project = await session.get(Project, project_id)
            if project is None:
                await self._fail(job_id, _NO_PROJECT)
                return
            try:
                gathered = await music_placement.gather(session, project)
            except music_placement.MusicPlacementError as exc:
                await self._fail(job_id, str(exc))
                return
            await session.commit()

        await self._phase(job_id, phases.PLACING_MUSIC)
        first = music_placer.place(gathered.data)
        final = first
        calls: dict[str, Any] = {}
        usage: dict[str, int] = {}
        reasons: dict[str, str] = {}
        failure: str | None = None
        if first.pending:
            answers, calls, usage, failure = await self._ask(job_id, job_input, first.pending)
            reasons = {key: value["reason"] for key, value in (answers or {}).items()}
            choices: dict[str, str | None] = {
                question["id"]: answers[question["id"]]["pick"] if answers is not None else None
                for question in first.pending
            }
            final = music_placer.place(gathered.data, choices)

        content = final.content
        content["facts"]["model_asked"] = len(first.pending)
        content["facts"]["model_failed"] = failure
        content["facts"]["unmeasured"] = gathered.unmeasured
        content["timeline"] = gathered.timeline
        for entry in content["choices"]:
            entry["reason"] = reasons.get(entry["id"], "")

        await self._phase(job_id, phases.SAVING_MUSIC_PLACEMENT)
        async with SessionLocal() as session:
            row = await music_placement.save_placement(
                session,
                project_id=project_id,
                plan_id=gathered.plan.id,
                job_id=job_id,
                inputs=gathered.inputs,
                content=content,
            )
            output = {
                "calls": calls,
                "usage": usage,
                "music_placement_id": row.id,
                "version": row.version,
                "placed": content["facts"]["placed"],
                "flags": len(content["flags"]),
                "model_asked": len(first.pending),
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the placement is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: music placed for project %d (version %d, %d placed, %d flagged, %d asked)",
            job_id,
            project_id,
            row.version,
            content["facts"]["placed"],
            len(content["flags"]),
            len(first.pending),
        )

    async def _ask(
        self, job_id: int, job_input: dict[str, Any], questions: list[dict[str, Any]]
    ) -> tuple[dict[str, dict[str, str]] | None, dict[str, Any], dict[str, int], str | None]:
        """The one call that answers every question: `(answers, calls, usage, failure)`.
        `answers` is None when the model gave no usable answer, with the reason in `failure`.
        """
        async with SessionLocal() as session:
            target = await llm_target.resolve(session, STORY_MODEL_KEY)
            await session.commit()
        await self._phase(job_id, phases.PREPARING_PROMPT)
        body = music_placement_writer.build_choice_request(questions, model=target.model)
        job_input.update(
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            calls_sent={
                "choice": {
                    "instructions_sha256": llm_call.instructions_sha256(body),
                    "request": body,
                }
            },
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        warnings: list[str] = []
        outcome = await llm_call.ask_model(
            job_id,
            target,
            body,
            _reader(questions, warnings),
            timeout_s=REQUEST_TIMEOUT_S,
            correct=True,
        )
        calls = {"choice": outcome.record()}
        if outcome.value is None:
            return None, calls, outcome.usage or {}, outcome.failure
        return outcome.value, calls, outcome.usage or {}, None

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
