"""The `write_image_prompt` job: a language model turns one scene's first frame description,
video prompt, narration and the draft's `world` into a detailed prompt for the image model
(ANALYSIS.md Section 4.2 and 6.2; Phase 16).

It is a scene job: one request, one scene, one job (`job.scene_id`). It is a paid job
(Section 6.2), so the rules of the scene proposal and of drafting hold here too:

- It only starts from a click (`POST .../write-image-prompts` or `.../write-image-prompt`).
- The same request is never paid for twice. The request body and its hash are saved on the
  job before the call, and an earlier job for this scene with the same hash that kept a usable
  answer is reused. "Write again" skips that lookup on purpose.
- Every answer is saved on the job (`record_output`) the moment it arrives, before anything
  is checked, so a crash after the paid call still leaves the answer behind.
- At most 2 attempts, the second only for a rate limit, a server error, no answer, or an
  answer that cannot be used. A refusal (HTTP 400, 401, 403, 404, 422) is never retried.
- A restart never re-runs it (`never_rerun`): the dispatcher fails it with a message.

There is no rule-based fallback (nothing can write a prompt without the model), so two failed
attempts fail the job. The save never overwrites a prompt the author wrote
(`services/image_prompts.write_values`), and it writes nothing when the scene's cut changed
while the model was working.

The instructions, and everything that depends on the image model, are in
`services/image_prompt_writer.py` and `services/image_prompt_profiles.py`. This job stores the
profile's id and version, a hash of the instructions, a hash of the scene's inputs and the exact
request, so a prompt can always be traced to what it was written from, and the page can tell
when the scene has changed since.

It is a local-style job: everything happens in `start`. There is no provider job id. Logs hold
the job id, what each attempt did and its token counts, never the prompt or the answer.
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
from app.services import description_writer, scene_planner
from app.services import image_prompt_writer as writer
from app.services import image_prompts as prompts_service
from app.services import scenes as scenes_service
from app.services.descriptions import DRAFT_JOB
from app.services.image_prompt_profiles import ACTIVE_IMAGE_PROFILE, ImagePromptProfile
from app.services.image_prompt_writer import CheckedPrompt

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = prompts_service.IMAGE_PROMPT_JOB
IMAGE_PROMPT_MODEL_KEY: Final = "image_prompt_llm_model"

# At most this many prompts are written at once (a constant, not a setting). One scene's
# request is small and quick, so a project's prompts are done in about a minute.
CONCURRENCY_LIMIT: Final = 4
# One call, and one more if it fails in a way that can pass (ANALYSIS.md Section 5.8, 6.2).
MAX_ATTEMPTS: Final = 2
RETRY_DELAY_S: Final = 5.0
# The Flash model reasons before it answers: "high" effort took 16 to 19 s for the scene
# proposal (Phase 6). A call that times out is paid for and lost, so this is generous.
REQUEST_TIMEOUT_S: Final = 180.0
RAW_CONTENT_MAX_CHARS: Final = 20_000

_CUT_CHANGED = (
    "The scene's cut changed while the image prompt was being written, so it was not saved. "
    "Write it again."
)
_AUTHOR_WROTE = "You wrote this image prompt while the AI was writing one, so yours was kept."


@dataclass
class _Outcome:
    """What getting the prompt came to. `checked` is None when none could be used."""

    checked: CheckedPrompt | None = None
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
    result: llm.ChatResult, profile: ImagePromptProfile
) -> tuple[str | None, dict[str, Any] | None, CheckedPrompt | None]:
    """Whether an answer can be used: `(None, answer, checked)` if so, else `(why not, None,
    None)`. The first value is the reason, which is shown to the user and kept on the job.
    """
    if result.finish_reason == "length":
        return "The model's answer was cut off because it reached the token limit.", None, None
    try:
        answer = writer.parse_answer(result.content)
    except ValueError as exc:
        return str(exc), None, None
    checked = writer.check_prompt(answer, profile)
    if checked is None:
        return (
            "The model's image prompt was empty or longer than "
            f"{writer.FIELD_MAX_CHARS:,} characters.",
            None,
            None,
        )
    return None, answer, checked


def _scene_record(scene: Scene) -> dict[str, Any]:
    return {
        "scene_id": scene.id,
        "index": scene.index,
        "start_s": scene.start_s,
        "end_s": scene.end_s,
        "text": scene.text,
    }


class WriteImagePromptHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"

    async def concurrency_limit(self, session: AsyncSession) -> int:
        return CONCURRENCY_LIMIT

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if (
                job is None
                or job.status != "running"
                or job.scene_id is None
                or not isinstance(job.input, dict)
            ):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            project = await session.get(Project, job.project_id)
            scene = await session.get(Scene, job.scene_id, populate_existing=True)
            block: str | None = None
            source = writer.NO_SOURCE
            if project is not None and scene is not None:
                # The same refusals as the endpoints: the project may have changed while the
                # job waited for its turn.
                state = await scenes_service.scenes_state(session, project)
                draft_job = await store.latest_job(session, project.id, DRAFT_JOB)
                block = prompts_service.project_block(
                    state.scenes,
                    plan_job=state.job,
                    stale_reasons=state.stale_reasons,
                    draft_job=draft_job,
                ) or prompts_service.scene_block(scene)
                source = (await prompts_service.load_sources(session, project.id, [scene]))[
                    scene.id
                ]
            base_url = await settings_service.get_str(session, LLM_URL_KEY)
            model = await settings_service.get_str(session, IMAGE_PROMPT_MODEL_KEY)
            await session.commit()

        if project is None or scene is None:
            await self._fail(job_id, "The project or the scene no longer exists.")
            return
        if block is not None:
            await self._fail(job_id, block)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        profile = ACTIVE_IMAGE_PROFILE
        inputs = writer.prompt_inputs(scene, project, source)
        body = writer.build_request(inputs, model=model, profile=profile)
        input_hash = scene_planner.request_hash(llm.chat_url(base_url), body)
        scene_sent = _scene_record(scene)
        job_input.update(
            profile={"id": profile.id, "version": profile.version},
            instructions_sha256=description_writer.instructions_sha256(body),
            scene_sent=scene_sent,
            source_draft_job_id=source.job_id,
            world_from_job_id=source.world_job_id,
            inputs_sha256=writer.inputs_sha256(inputs),
            server_url=docker_mapped(base_url),
            endpoint=llm.CHAT_PATH,
            request=body,
            input_hash=input_hash,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await self._get_prompt(
            job_id,
            project_id=project.id,
            scene_id=scene.id,
            profile=profile,
            base_url=base_url,
            body=body,
            input_hash=input_hash,
            run_again=job_input.get("run_again") is True,
        )
        checked = outcome.checked
        if checked is None:
            await self._fail(job_id, f"The image prompt could not be written: {outcome.failure}")
            return

        await self._save(job_id, project.id, scene_sent, outcome, checked, started)

    # --- Asking the model (or reusing an earlier answer) ----------------------------

    async def _get_prompt(
        self,
        job_id: int,
        *,
        project_id: int,
        scene_id: int,
        profile: ImagePromptProfile,
        base_url: str,
        body: dict[str, Any],
        input_hash: str,
        run_again: bool,
    ) -> _Outcome:
        if not run_again:
            async with SessionLocal() as session:
                cached = await prompts_service.find_cached_answer(
                    session, project_id, scene_id, input_hash, exclude_job_id=job_id
                )
                await session.commit()
            stored = cached.output.get("answer") if cached is not None else None
            if cached is not None and isinstance(stored, dict):
                checked = writer.check_prompt(stored, profile)
                if checked is not None:
                    await self._phase(job_id, phases.REUSING_ANSWER)
                    _logger.info("job %d: reusing the answer stored on job %d", job_id, cached.id)
                    return _Outcome(checked=checked, cache_hit_of_job_id=cached.id)
        return await self._ask_model(job_id, profile, base_url, body)

    async def _ask_model(
        self, job_id: int, profile: ImagePromptProfile, base_url: str, body: dict[str, Any]
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
                await self._phase(job_id, phases.CHECKING_IMAGE_PROMPT)
                problem, answer, checked = _read_answer(result, profile)
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

    # --- Saving the prompt ----------------------------------------------------------

    async def _save(
        self,
        job_id: int,
        project_id: int,
        scene_sent: dict[str, Any],
        outcome: _Outcome,
        checked: CheckedPrompt,
        started: float,
    ) -> None:
        """Writes the prompt into the scene and finishes the job in one transaction."""
        await self._phase(job_id, phases.SAVING_IMAGE_PROMPT)

        output: dict[str, Any] = {
            "answer": outcome.answer,
            "answer_usable": outcome.answer is not None,
            "content": None,
            "attempts": outcome.attempts,
            "usage": outcome.usage,
            "cache_hit_of_job_id": outcome.cache_hit_of_job_id,
            "image_prompt": checked.text,
            "word_count": checked.word_count,
            "warnings": list(checked.warnings),
            "seconds": round(time.monotonic() - started, 1),
        }
        problem: str | None = None
        async with SessionLocal() as session:
            # Taking the database's write lock first means no cut edit can change the scene
            # between the check below and the write.
            await scenes_service.lock_scenes(session, project_id)
            scene = await session.get(Scene, scene_sent["scene_id"], populate_existing=True)
            if scene is None:
                # The scene was merged away, and its jobs with it.
                await session.rollback()
                return
            if not prompts_service.unchanged(scene, scene_sent):
                problem = _CUT_CHANGED
            else:
                values = prompts_service.write_values(scene, checked.text, job_id)
                if values is None:
                    problem = _AUTHOR_WROTE
                else:
                    for column, value in values.items():
                        setattr(scene, column, value)
                    if not await store.finish_job(session, job_id, output):
                        await session.rollback()
                        return
                    await session.commit()
            if problem is not None:
                await session.rollback()
        if problem is not None:
            await self._fail(job_id, problem)
            return

        _logger.info(
            "job %d: image prompt written: scene=%d words=%d warnings=%d reused_from=%s usage=%s",
            job_id,
            scene_sent["scene_id"],
            checked.word_count,
            len(checked.warnings),
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
