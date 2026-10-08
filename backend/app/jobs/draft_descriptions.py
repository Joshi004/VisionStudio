"""The `draft_descriptions` job: a language model writes, for every scene of a project in one
request, the video prompt and the first frame description (ANALYSIS.md Section 4.2 and 6.2;
Phase 12, reworked for first-frame clips in Phase 15). It never writes a last frame
description.

It is a paid job (Section 6.2), so the rules of the scene proposal hold here too:

- It only starts from a click (`POST /api/projects/{id}/draft-descriptions`).
- The same request is never paid for twice. The request body and its hash are saved on the
  job before the call, and an earlier job with the same hash that kept a usable answer is
  reused. "Draft again" skips that lookup on purpose.
- Every answer is saved on the job (`record_output`) the moment it arrives, before anything
  is checked, so a crash after the paid call still leaves the answer behind.
- At most 2 attempts, the second only for a rate limit, a server error, no answer, or an
  answer that cannot be used. A refusal (HTTP 400, 401, 403, 404, 422) is never retried.
- A restart never re-runs it (`never_rerun`): the dispatcher fails it with a message.

What is different from the proposal: there is no rule-based fallback (nothing can write a
description without the model), so two failed attempts fail the job. And the save never
overwrites what the author wrote (`services/descriptions.plan_write`).

The instructions, and everything that depends on the video model, are in
`services/description_writer.py` and `services/description_profiles.py`. This job stores the
profile's id and version, a hash of the instructions, and the exact request, so a drafted
text can always be traced to the prompt that wrote it.

It is a local-style job: everything happens in `start`. There is no provider job id. Logs
hold the job id, what each attempt did and its token counts, never the prompt or the answer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.core.urls import docker_mapped
from app.db.models import Project, Scene
from app.db.session import SessionLocal
from app.jobs import phases, store
from app.jobs.handlers import JobHandler
from app.jobs.plan_scenes import LLM_URL_KEY
from app.providers import llm
from app.providers.llm import LlmCallError
from app.services import description_writer as writer
from app.services import descriptions as descriptions_service
from app.services import scene_planner
from app.services import scenes as scenes_service
from app.services.description_profiles import ACTIVE_PROFILE, PromptProfile
from app.services.description_writer import CheckedDrafts, SceneToDraft

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = descriptions_service.DRAFT_JOB
DESCRIPTION_MODEL_KEY: Final = "description_llm_model"

# At most this many drafts run at once (a constant, not a setting).
CONCURRENCY_LIMIT: Final = 2
# One call, and one more if it fails in a way that can pass (ANALYSIS.md Section 5.8, 6.2).
MAX_ATTEMPTS: Final = 2
RETRY_DELAY_S: Final = 5.0
# The model thinks before it writes, and how long it thinks varies: 15 scenes took 90 s once
# (6,570 reasoning tokens) and 263 s another time (9,708), at roughly 40 output tokens a
# second. A call that times out is paid for and lost, and its retry is paid again, so this
# is the time a full 32,000-token answer could need.
REQUEST_TIMEOUT_S: Final = 900.0
RAW_CONTENT_MAX_CHARS: Final = 20_000


@dataclass
class _Outcome:
    """What getting the model's drafts came to. `checked` is None when none could be used."""

    checked: CheckedDrafts | None = None
    # Set only when a call was paid for and its answer was usable.
    answer: dict[str, Any] | None = None
    cache_hit_of_job_id: int | None = None
    # Why the model could not be used, when `checked` is None.
    failure: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    # The raw text of the last answer that could not be used, for the job record.
    unusable_content: str | None = None
    # Tokens summed over the attempts that were answered. None when none was.
    usage: dict[str, int] | None = None


def _failure_text(exc: LlmCallError) -> str:
    """What to tell the user about a call that failed."""
    if exc.status_code is not None:
        return f"The language model answered HTTP {exc.status_code}: {exc.message}"
    return exc.message


def _read_answer(
    result: llm.ChatResult, sent: list[SceneToDraft], profile: PromptProfile
) -> tuple[str | None, dict[str, Any] | None, CheckedDrafts | None]:
    """Whether an answer can be used: `(None, answer, checked)` if so, else `(why not, None, None)`.

    The first value is the reason, which is shown to the user and kept on the job.
    """
    if result.finish_reason == "length":
        return "The model's answer was cut off because it reached the token limit.", None, None
    try:
        answer = writer.parse_answer(result.content)
    except ValueError as exc:
        return str(exc), None, None
    checked = writer.check_drafts(answer, sent, profile)
    if not checked.usable:
        return "None of the drafts in the model's answer could be used.", None, None
    return None, answer, checked


def _scene_record(scene: SceneToDraft) -> dict[str, Any]:
    return {
        "scene_id": scene.scene_id,
        "index": scene.index,
        "start_s": scene.start_s,
        "end_s": scene.end_s,
        "text": scene.text,
        "fixed": {
            writer.VIDEO_PROMPT: scene.fixed_video_prompt is not None,
            writer.FIRST_FRAME: scene.fixed_first_frame is not None,
            writer.LAST_FRAME: scene.fixed_last_frame is not None,
        },
    }


class DraftDescriptionsHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return CONCURRENCY_LIMIT

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            project = await session.get(Project, job.project_id)
            scenes: list[Scene] = []
            block: str | None = None
            sent: list[SceneToDraft] = []
            if project is not None:
                # The same refusals as the endpoint: the scenes may have changed while the
                # job waited for its turn.
                state = await scenes_service.scenes_state(session, project)
                scenes = state.scenes
                block = descriptions_service.draft_block(
                    scenes, plan_job=state.job, stale_reasons=state.stale_reasons
                )
                sent = [writer.to_draft(scene) for scene in scenes]
            base_url = await settings_service.get_str(session, LLM_URL_KEY)
            model = await settings_service.get_str(session, DESCRIPTION_MODEL_KEY)
            await session.commit()

        if project is None:
            await self._fail(job_id, "The project no longer exists.")
            return
        if block is not None:
            await self._fail(job_id, block)
            return
        if project.script_text is None or not project.script_text.strip():
            await self._fail(job_id, "The script is empty. Paste the script and draft again.")
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        profile = ACTIVE_PROFILE
        body = writer.build_request(
            project,
            sent,
            writer.script_paragraphs(project.script_text),
            model=model,
            profile=profile,
        )
        input_hash = scene_planner.request_hash(llm.chat_url(base_url), body)
        job_input.update(
            profile={"id": profile.id, "version": profile.version},
            instructions_sha256=writer.instructions_sha256(body),
            scenes_sent=[_scene_record(scene) for scene in sent],
            server_url=docker_mapped(base_url),
            endpoint=llm.CHAT_PATH,
            request=body,
            input_hash=input_hash,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await self._get_drafts(
            job_id,
            project_id=project.id,
            sent=sent,
            profile=profile,
            base_url=base_url,
            body=body,
            input_hash=input_hash,
            run_again=job_input.get("run_again") is True,
        )
        checked = outcome.checked
        if checked is None:
            await self._fail(
                job_id,
                f"The descriptions could not be drafted: {outcome.failure}",
            )
            return

        await self._save(job_id, project.id, sent, outcome, checked, started)

    # --- Asking the model (or reusing an earlier answer) ----------------------------

    async def _get_drafts(
        self,
        job_id: int,
        *,
        project_id: int,
        sent: list[SceneToDraft],
        profile: PromptProfile,
        base_url: str,
        body: dict[str, Any],
        input_hash: str,
        run_again: bool,
    ) -> _Outcome:
        if not run_again:
            async with SessionLocal() as session:
                cached = await descriptions_service.find_cached_answer(
                    session, project_id, input_hash, exclude_job_id=job_id
                )
                await session.commit()
            stored = cached.output.get("answer") if cached is not None else None
            if cached is not None and isinstance(stored, dict):
                checked = writer.check_drafts(stored, sent, profile)
                if checked.usable:
                    await self._phase(job_id, phases.REUSING_ANSWER)
                    _logger.info("job %d: reusing the answer stored on job %d", job_id, cached.id)
                    return _Outcome(checked=checked, cache_hit_of_job_id=cached.id)
        return await self._ask_model(job_id, sent, profile, base_url, body)

    async def _ask_model(
        self,
        job_id: int,
        sent: list[SceneToDraft],
        profile: PromptProfile,
        base_url: str,
        body: dict[str, Any],
    ) -> _Outcome:
        outcome = _Outcome()
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
                await self._phase(job_id, phases.CHECKING_DESCRIPTIONS)
                problem, answer, checked = _read_answer(result, sent, profile)
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
                    outcome.checked = checked
                    outcome.answer = answer
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
    def _add_usage(outcome: _Outcome, counts: dict[str, int | None]) -> None:
        total = outcome.usage or {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0}
        for key in total:
            total[key] += counts.get(key) or 0
        outcome.usage = total

    @staticmethod
    async def _save_progress(job_id: int, outcome: _Outcome) -> None:
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

    # --- Saving the drafts ----------------------------------------------------------

    async def _save(
        self,
        job_id: int,
        project_id: int,
        sent: list[SceneToDraft],
        outcome: _Outcome,
        checked: CheckedDrafts,
        started: float,
    ) -> None:
        """Writes the drafts into the scenes and finishes the job in one transaction."""
        await self._phase(job_id, phases.SAVING_DESCRIPTIONS)

        drafts = {draft.scene_id: draft for draft in checked.drafts}
        written_by_scene: dict[int, list[str]] = {}
        cleared_by_scene: dict[int, list[str]] = {}
        skipped = {"all_fixed": 0, "changed_while_drafting": 0, "missing_in_answer": 0}

        async with SessionLocal() as session:
            # Taking the database's write lock first means no cut edit can change a scene
            # between the check below and the write.
            await scenes_service.lock_scenes(session, project_id)
            current = {
                scene.id: scene for scene in await scenes_service.list_scenes(session, project_id)
            }
            for scene_sent in sent:
                scene = current.get(scene_sent.scene_id)
                if scene is None or not descriptions_service.unchanged(scene, scene_sent):
                    skipped["changed_while_drafting"] += 1
                elif scene_sent.all_fixed:
                    skipped["all_fixed"] += 1
                elif scene_sent.scene_id not in drafts:
                    skipped["missing_in_answer"] += 1
                else:
                    draft = drafts[scene_sent.scene_id]
                    plan = descriptions_service.plan_write(scene, draft, job_id)
                    for column, value in plan.values.items():
                        setattr(scene, column, value)
                    written_by_scene[scene.id] = plan.written
                    cleared_by_scene[scene.id] = plan.cleared

            output: dict[str, Any] = {
                "answer": outcome.answer,
                "answer_usable": outcome.answer is not None,
                "content": None,
                "attempts": outcome.attempts,
                "usage": outcome.usage,
                "cache_hit_of_job_id": outcome.cache_hit_of_job_id,
                "drafts": [
                    {
                        "scene_id": draft.scene_id,
                        "index": draft.index,
                        "continuity": draft.continuity,
                        writer.VIDEO_PROMPT: draft.video_prompt,
                        writer.FIRST_FRAME: draft.first_frame,
                        "warnings": list(draft.warnings),
                        "written": written_by_scene.get(draft.scene_id, []),
                        "cleared": cleared_by_scene.get(draft.scene_id, []),
                    }
                    for draft in checked.drafts
                ],
                "skipped": skipped,
                "dropped_entries": checked.dropped_entries,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: descriptions drafted: scenes=%d written=%d skipped=%s reused_from=%s usage=%s",
            job_id,
            len(sent),
            sum(1 for written in written_by_scene.values() if written),
            skipped,
            outcome.cache_hit_of_job_id,
            outcome.usage,
        )

    # --- Small helpers ----------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
