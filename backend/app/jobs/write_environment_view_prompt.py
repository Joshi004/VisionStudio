"""The `write_environment_view_prompt` job (PHASE-052): a language model writes the edit prompt
of one view of an environment, on the view profile
(`image_prompt_profiles.ACTIVE_ENVIRONMENT_VIEW_PROFILE`), from what the view shows, what the
camera does relative to the master picture and the text of that side of the place.

`environment_views._queue_prompt` creates the job with the view's id, the master picture and,
for a `behind` view, the finished left and right pictures, and the text of the view's side and
zone. Once the prompt is saved, the edit run that makes the picture is started
(`environment_views.on_prompt_written`). If the model fails, the job fails and the view shows
why (its status is read from this job). Reuses `image_prompt_writer.py`'s reader and checks.

It is a paid call to the language model on the **image-prompt role**
(`llm_target.IMAGE_PROMPT_MODEL_KEY`), so the rules in `jobs/llm_call.py` hold: at most 2
attempts, a refusal never retried, every answer saved the moment it arrives, and a restart never
re-runs it (`never_rerun`). It is a local-style job: everything happens in `start`. Logs hold the
job id, what each attempt did and its token counts, never the prompt or the answer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import EnvironmentView
from app.db.session import SessionLocal
from app.jobs import dispatcher, llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import environment_view_prompt_writer as writer
from app.services import environment_views, llm_target
from app.services import image_prompt_writer as prompt_checks
from app.services.image_prompt_profiles import ACTIVE_ENVIRONMENT_VIEW_PROFILE
from app.services.image_prompt_writer import CheckedPrompt
from app.services.llm_target import IMAGE_PROMPT_MODEL_KEY

_logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S: Final = 300.0

_NO_VIEW = "The view no longer exists."


def _reader(result: llm.ChatResult) -> tuple[str | None, CheckedPrompt | None]:
    if result.finish_reason == "length":
        return "The model's answer was cut off because it reached the token limit.", None
    try:
        answer = prompt_checks.parse_answer(result.content)
    except ValueError as exc:
        return str(exc), None
    checked = prompt_checks.check_prompt(answer, ACTIVE_ENVIRONMENT_VIEW_PROFILE)
    if checked is None:
        return (
            "The model's image prompt was empty or longer than "
            f"{prompt_checks.FIELD_MAX_CHARS:,} characters.",
            None,
        )
    return None, checked


class WriteEnvironmentViewPromptHandler(JobHandler):
    job_type = environment_views.PROMPT_JOB
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = IMAGE_PROMPT_MODEL_KEY

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            view_id = job_input.get("view_id")
            view = await session.get(EnvironmentView, view_id) if isinstance(view_id, int) else None
            target = await llm_target.resolve(session, IMAGE_PROMPT_MODEL_KEY)
            fields = (
                {
                    "name": view.name,
                    "side": view.side,
                    "framing": view.framing,
                    "description": view.description,
                }
                if view is not None
                else None
            )
            await session.commit()

        if fields is None:
            await self._fail(job_id, _NO_VIEW)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        profile = ACTIVE_ENVIRONMENT_VIEW_PROFILE
        inputs = writer.prompt_inputs(
            **fields,
            side_text=job_input.get("side_text"),
            zone_text=job_input.get("zone_text"),
            pictures=writer.pictures_text(
                fields["side"],
                has_left=isinstance(job_input.get("left_image_id"), int),
                has_right=isinstance(job_input.get("right_image_id"), int),
            ),
        )
        body = writer.build_request(inputs, model=target.model, profile=profile)
        job_input.update(
            profile={"id": profile.id, "version": profile.version},
            instructions_sha256=llm_call.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, _reader, timeout_s=REQUEST_TIMEOUT_S
        )
        checked: CheckedPrompt | None = outcome.value
        if checked is None:
            await self._fail(job_id, f"The view prompt could not be written: {outcome.failure}")
            return

        await self._phase(job_id, phases.SAVING_VIEW_PROMPT)
        output = {
            **outcome.record(),
            "content": None,
            "image_prompt": checked.text,
            "word_count": checked.word_count,
            "warnings": list(checked.warnings),
            "seconds": round(time.monotonic() - started, 1),
        }
        async with SessionLocal() as session:
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            await session.commit()

        if await environment_views.on_prompt_written(job_id):
            dispatcher.nudge()
        _logger.info(
            "job %d: view prompt written: words=%d warnings=%d usage=%s",
            job_id,
            checked.word_count,
            len(checked.warnings),
            outcome.usage,
        )

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
