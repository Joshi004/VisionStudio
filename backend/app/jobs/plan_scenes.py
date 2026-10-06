"""The `plan_scenes` job: the language model names the cut words, and code checks them,
times them and enforces the scene length limits (ANALYSIS.md Section 5.2 and 6.4).

It is a paid job (Section 6.2), so these rules hold:

- It only starts from a click (`POST /api/projects/{id}/propose-scenes`).
- The same request is never paid for twice. The request body and its hash are saved on the
  job before the call, and an earlier job with the same hash that kept a usable answer is
  reused. "Run again" skips that lookup on purpose.
- Every answer is saved on the job (`record_output`) the moment it arrives, before anything
  is checked, so a crash after the paid call still leaves the answer behind.
- At most 2 attempts, the second only for a rate limit, a server error, no answer, or an
  answer that cannot be used. A refusal (HTTP 400, 401, 403, 404, 422) is never retried.
- After 2 failed attempts the rule-based splitter proposes the scenes alone, and the page
  says so. The job still succeeds.
- A restart never re-runs it (`never_rerun`): the dispatcher fails it with a message.

It is a local-style job: everything happens in `start`. There is no provider job id.
Logs hold the job id, what each attempt did and its token counts, never the prompt or the
model's answer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Asset, Project, Transcript
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.providers.llm import LlmCallError
from app.services import scene_cuts, scene_planner, scene_splitter
from app.services import scenes as scenes_service
from app.services import transcripts as transcripts_service
from app.services.scene_cuts import SceneSpec

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "plan_scenes"
# At most this many proposals run at once (a constant, not a setting).
CONCURRENCY_LIMIT: Final = 2
# One call, and one more if it fails in a way that can pass (ANALYSIS.md Section 5.8, 6.2).
MAX_ATTEMPTS: Final = 2
RETRY_DELAY_S: Final = 5.0
# The model reasons before it answers: "high" effort took 16 to 19 s in the spike.
REQUEST_TIMEOUT_S: Final = 180.0
RAW_CONTENT_MAX_CHARS: Final = 20_000

LLM_URL_KEY: Final = "llm_base_url"
LLM_MODEL_KEY: Final = "llm_model"

_ZERO_CHECKS: Final = {"entries": 0, "exact": 0, "moved": 0, "flagged": 0, "dropped": 0}


@dataclass
class _ModelOutcome:
    """What asking the model came to. `entries` is None when no usable answer was got."""

    entries: list[Any] | None
    # Set only when a call was paid for and its answer was usable.
    answer: dict[str, Any] | None
    cache_hit_of_job_id: int | None
    # Why the model could not be used, when `entries` is None.
    failure: str | None
    attempts: list[dict[str, Any]]
    # The raw text of the last answer that could not be used, for the job record.
    unusable_content: str | None
    # Tokens summed over the attempts that were answered. None when none was.
    usage: dict[str, int] | None


@dataclass(frozen=True)
class _Proposal:
    specs: list[SceneSpec]
    source: Literal["ai", "rule"]
    checks: dict[str, int]
    splitter: dict[str, int]


def _failure_text(exc: LlmCallError) -> str:
    """What to tell the user about a call that failed."""
    if exc.status_code is not None:
        return f"The language model answered HTTP {exc.status_code}: {exc.message}"
    return exc.message


def _read_answer(
    result: llm.ChatResult, words: list[scene_cuts.Word]
) -> tuple[str | None, list[Any]]:
    """Whether an answer can be used: `(None, entries)` if so, else `(why not, [])`."""
    if result.finish_reason == "length":
        return "The model's answer was cut off because it reached the token limit.", []
    try:
        entries = scene_planner.parse_answer(result.content)
    except ValueError as exc:
        return str(exc), []
    _cuts, stats = scene_planner.check_cuts(words, entries)
    if not stats.has_valid_entries:
        return "None of the cuts in the model's answer could be used.", []
    return None, entries


def _propose(
    words: list[scene_cuts.Word],
    entries: list[Any] | None,
    audio_end_s: float,
    min_s: float,
    max_s: float,
) -> _Proposal:
    """Checks the model's cuts and makes them fit the limits, or, with no usable answer,
    lets the splitter propose the cuts alone. Then builds the scenes. Pure CPU work.
    """
    if entries is None:
        cuts, split = scene_splitter.split_alone(words, audio_end_s, min_s, max_s)
        source: Literal["ai", "rule"] = "rule"
        checks = dict(_ZERO_CHECKS)
    else:
        cuts, stats = scene_planner.check_cuts(words, entries)
        cuts, split = scene_splitter.enforce_limits(words, cuts, audio_end_s, min_s, max_s)
        source = "ai"
        checks = {
            "entries": stats.entries,
            "exact": stats.exact,
            "moved": stats.moved,
            "flagged": stats.flagged,
            "dropped": stats.dropped,
        }
    specs = scene_cuts.build_scene_specs(words, cuts, audio_end_s)
    return _Proposal(
        specs=specs,
        source=source,
        checks=checks,
        splitter={"cuts_added": split.cuts_added, "cuts_removed": split.cuts_removed},
    )


class PlanScenesHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return CONCURRENCY_LIMIT

    async def start(self, job_id: int) -> None:
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            project = await session.get(Project, job.project_id)
            transcript_id = job_input.get("transcript_id")
            transcript = (
                await session.get(Transcript, transcript_id)
                if isinstance(transcript_id, int)
                else None
            )
            voiceover = (
                await session.get(Asset, project.voiceover_asset_id)
                if project is not None and project.voiceover_asset_id is not None
                else None
            )
            base_url = await settings_service.get_str(session, LLM_URL_KEY)
            model = await settings_service.get_str(session, LLM_MODEL_KEY)
            await session.commit()

        if project is None or transcript is None or voiceover is None:
            await self._fail(
                job_id, "The project, its transcript or its voiceover no longer exists."
            )
            return
        if project.script_text is None or not project.script_text.strip():
            await self._fail(job_id, "The script is empty. Paste the script and propose again.")
            return
        if transcripts_service.stale_reasons(transcript, project):
            await self._fail(
                job_id,
                "The script or the voiceover changed after you clicked Propose scenes, so the "
                "transcript no longer fits. Transcribe again, then propose again.",
            )
            return
        try:
            words = scene_cuts.words_from_script_words(transcript.script_words)
        except ValueError as exc:
            await self._fail(job_id, f"The transcript cannot be used: {exc} Transcribe again.")
            return
        if not words or len(words) > scene_planner.MAX_SCRIPT_WORDS:
            await self._fail(
                job_id,
                f"This script has {len(words):,} words; scene proposal handles 1 to "
                f"{scene_planner.MAX_SCRIPT_WORDS:,}.",
            )
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        audio_end_s = scene_cuts.end_of_audio(voiceover.duration_s, words)
        min_s, max_s = project.min_scene_seconds, project.max_scene_seconds
        body = scene_planner.build_request(
            words,
            model=model,
            min_s=min_s,
            max_s=max_s,
            audio_end_s=audio_end_s,
            instructions=project.cut_instructions,
        )
        input_hash = scene_planner.request_hash(llm.chat_url(base_url), body)
        job_input.update(
            server_url=docker_mapped(base_url),
            endpoint=llm.CHAT_PATH,
            request=body,
            input_hash=input_hash,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await self._get_cuts(
            job_id,
            project_id=project.id,
            words=words,
            base_url=base_url,
            body=body,
            input_hash=input_hash,
            run_again=job_input.get("run_again") is True,
        )

        phase = (
            phases.CHECKING_CUTS if outcome.entries is not None else phases.MODEL_FAILED_SPLITTER
        )
        await self._phase(job_id, phase)
        try:
            proposal = await asyncio.to_thread(
                _propose, words, outcome.entries, audio_end_s, min_s, max_s
            )
        except ValueError as exc:
            await self._fail(job_id, f"The scenes could not be built from the cuts: {exc}")
            return

        flagged = sum(1 for spec in proposal.specs if spec.cut_note)
        output: dict[str, Any] = {
            "source": proposal.source,
            "cache_hit_of_job_id": outcome.cache_hit_of_job_id,
            "fallback_reason": outcome.failure if proposal.source == "rule" else None,
            "answer": outcome.answer,
            "answer_usable": outcome.answer is not None,
            "content": outcome.unusable_content,
            "attempts": outcome.attempts,
            "usage": outcome.usage,
            "checks": proposal.checks,
            "splitter": proposal.splitter,
            "scene_count": len(proposal.specs),
            "flagged_scenes": flagged,
        }
        await self._save(
            job_id,
            project.id,
            proposal.specs,
            output,
            discard_with_inputs=job_input.get("discard_scenes_with_inputs") is True,
        )

    # --- Asking the model (or reusing an earlier answer) ----------------------------

    async def _get_cuts(
        self,
        job_id: int,
        *,
        project_id: int,
        words: list[scene_cuts.Word],
        base_url: str,
        body: dict[str, Any],
        input_hash: str,
        run_again: bool,
    ) -> _ModelOutcome:
        if not run_again:
            async with SessionLocal() as session:
                cached = await scenes_service.find_cached_answer(
                    session, project_id, input_hash, exclude_job_id=job_id
                )
                await session.commit()
            stored = cached.output["answer"].get("scenes") if cached is not None else None
            if cached is not None and isinstance(stored, list) and stored:
                await self._phase(job_id, phases.REUSING_ANSWER)
                _logger.info("job %d: reusing the answer stored on job %d", job_id, cached.id)
                return _ModelOutcome(
                    entries=stored,
                    answer=None,
                    cache_hit_of_job_id=cached.id,
                    failure=None,
                    attempts=[],
                    unusable_content=None,
                    usage=None,
                )
        return await self._ask_model(job_id, words, base_url, body)

    async def _ask_model(
        self, job_id: int, words: list[scene_cuts.Word], base_url: str, body: dict[str, Any]
    ) -> _ModelOutcome:
        outcome = _ModelOutcome(
            entries=None,
            answer=None,
            cache_hit_of_job_id=None,
            failure=None,
            attempts=[],
            unusable_content=None,
            usage=None,
        )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            await self._phase(job_id, phases.asking_model(attempt, MAX_ATTEMPTS))
            started = time.monotonic()
            try:
                result = await llm.complete(base_url, body, timeout_s=REQUEST_TIMEOUT_S)
            except LlmCallError as exc:
                outcome.failure = _failure_text(exc)
                outcome.attempts.append(
                    {
                        "outcome": exc.kind,
                        "http_status": exc.status_code,
                        "message": exc.message,
                        "finish_reason": None,
                        "response_id": None,
                        "elapsed_s": round(time.monotonic() - started, 1),
                        "usage": None,
                    }
                )
                _logger.info(
                    "job %d: language model attempt %d failed: %s (HTTP %s)",
                    job_id,
                    attempt,
                    exc.kind,
                    exc.status_code,
                )
                await self._save_progress(job_id, outcome)
                if exc.kind == "refused":
                    break  # asking again cannot help
            else:
                counts = llm.usage_counts(result.usage)
                self._add_usage(outcome, counts)
                problem, entries = _read_answer(result, words)
                outcome.attempts.append(
                    {
                        "outcome": "unusable" if problem else "answered",
                        "http_status": 200,
                        "message": problem,
                        "finish_reason": result.finish_reason,
                        "response_id": result.response_id,
                        "elapsed_s": round(time.monotonic() - started, 1),
                        "usage": counts,
                    }
                )
                _logger.info(
                    "job %d: language model attempt %d: %s, finish=%s, tokens prompt=%s "
                    "completion=%s reasoning=%s, %.1f s",
                    job_id,
                    attempt,
                    "unusable" if problem else "answered",
                    result.finish_reason,
                    counts["prompt_tokens"],
                    counts["completion_tokens"],
                    counts["reasoning_tokens"],
                    time.monotonic() - started,
                )
                if problem is None:
                    outcome.entries = entries
                    outcome.answer = {"scenes": entries}
                    outcome.failure = None
                    # The paid answer is saved before anything else happens to it.
                    await self._save_progress(job_id, outcome)
                    return outcome
                outcome.failure = problem
                outcome.unusable_content = result.content[:RAW_CONTENT_MAX_CHARS]
                await self._save_progress(job_id, outcome)

            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY_S)
        return outcome

    @staticmethod
    def _add_usage(outcome: _ModelOutcome, counts: dict[str, int | None]) -> None:
        total = outcome.usage or {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0}
        for key in total:
            total[key] += counts.get(key) or 0
        outcome.usage = total

    @staticmethod
    async def _save_progress(job_id: int, outcome: _ModelOutcome) -> None:
        """Writes what is known so far to `job.output`. The final output replaces it."""
        async with SessionLocal() as session:
            await store.record_output(
                session,
                job_id,
                {
                    "attempts": outcome.attempts,
                    "answer": outcome.answer,
                    "answer_usable": outcome.answer is not None,
                    "content": outcome.unusable_content,
                    "usage": outcome.usage,
                },
            )

    # --- Saving the scenes ------------------------------------------------------------

    async def _save(
        self,
        job_id: int,
        project_id: int,
        specs: list[SceneSpec],
        output: dict[str, Any],
        *,
        discard_with_inputs: bool,
    ) -> None:
        """Replaces the project's scenes and finishes the job in one transaction."""
        await self._phase(job_id, phases.SAVING_SCENES)
        with_inputs = 0
        async with SessionLocal() as session:
            # Finishing the job first takes the database's write lock, so the check below
            # and the replacement cannot be interleaved with another writer.
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            if not discard_with_inputs:
                with_inputs = await scenes_service.scenes_with_inputs(session, project_id)
            if with_inputs:
                await session.rollback()
            else:
                await scenes_service.replace_scenes(session, project_id, specs)
                await session.commit()

        if with_inputs:
            noun = "scene has" if with_inputs == 1 else "scenes have"
            await self._fail(
                job_id,
                f"{with_inputs} {noun} a description, frames or a clip that were added while "
                "this ran, so the scenes were not replaced. Propose scenes again and confirm "
                "to replace them.",
            )
            return
        _logger.info(
            "job %d: scenes proposed: source=%s scenes=%d flagged=%d reused_from=%s usage=%s",
            job_id,
            output["source"],
            output["scene_count"],
            output["flagged_scenes"],
            output["cache_hit_of_job_id"],
            output["usage"],
        )

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
