"""The `write_character_reference_prompt` job: a language model turns one cast member's
description (a character's or a place's) into the prompt for the image model that makes its
reference picture (ANALYSIS.md Section 6.2; project cast).

It is a cast job: one request, one member, one job. Its input names the member
(`cast_kind`, `cast_id`). It is a paid job, so the rules of `write_image_prompt` hold here too
(they are in `jobs/llm_call.py`): it only starts from a click or from an automatic run, every
answer is saved on the job the moment it arrives, at most 2 attempts, a refusal is never retried,
and a restart never re-runs it (`never_rerun`).

A click writes the prompt again even when the member has one (the endpoint says so). The save
sets the member's `reference_prompt` and, while it has no picture yet, its status `prompted`. It
does not make the picture: that is `generate_character_reference`, which the job starts itself
only when its input says `generate_after` (a click that asked for a picture of a member that had
no prompt).

The instructions, and everything that depends on the image model, are in
`services/cast_reference_prompt_writer.py` and `services/image_prompt_profiles.py`. It is a
local-style job: everything happens in `start`. Logs hold the job id, what each attempt did and
its token counts, never the prompt or the answer.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import Project
from app.db.session import SessionLocal
from app.jobs import dispatcher, llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import cast as cast_service
from app.services import cast_reference_prompt_writer as writer
from app.services import description_writer, llm_target, scene_planner
from app.services import image_prompt_writer as prompt_checks
from app.services.image_prompt_profiles import ImagePromptProfile
from app.services.image_prompt_writer import CheckedPrompt

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = cast_service.REFERENCE_PROMPT_JOB
MODEL_KEY: Final = "image_prompt_llm_model"
# One paragraph of about 200 words is a few hundred tokens (see `write_image_prompt`).
REQUEST_TIMEOUT_S: Final = 300.0

_MEMBER_GONE = "The character or the place no longer exists, so its prompt was not saved."


def _reader(profile: ImagePromptProfile) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, CheckedPrompt | None]:
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            answer = prompt_checks.parse_answer(result.content)
        except ValueError as exc:
            return str(exc), None
        checked = prompt_checks.check_prompt(answer, profile)
        if checked is None:
            return (
                "The model's image prompt was empty or longer than "
                f"{prompt_checks.FIELD_MAX_CHARS:,} characters.",
                None,
            )
        return None, checked

    return read


class WriteCharacterReferencePromptHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = MODEL_KEY

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            project = await session.get(Project, job.project_id)
            member_ref = cast_service.member_of_job(job)
            member = (
                await cast_service.get_member(session, project.id, *member_ref)
                if project is not None and member_ref is not None
                else None
            )
            target = await llm_target.resolve(session, MODEL_KEY)
            await session.commit()

        if project is None:
            await self._fail(job_id, "The project no longer exists.")
            return
        if member_ref is None or member is None:
            await self._fail(job_id, "The character or the place no longer exists.")
            return
        block = cast_service.prompt_block(member)
        if block is not None:
            await self._fail(job_id, block)
            return
        kind, member_id = member_ref

        await self._phase(job_id, phases.PREPARING_PROMPT)
        profile = writer.profile_for(kind)
        inputs = writer.prompt_inputs(kind, member, project)
        body = writer.build_request(inputs, model=target.model, profile=profile)
        job_input.update(
            profile={"id": profile.id, "version": profile.version},
            instructions_sha256=description_writer.instructions_sha256(body),
            inputs_sha256=prompt_checks.inputs_sha256(inputs),
            input_hash=scene_planner.request_hash(llm_target.call_url(target), body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=body,
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, _reader(profile), timeout_s=REQUEST_TIMEOUT_S
        )
        checked: CheckedPrompt | None = outcome.value
        if checked is None:
            await self._fail(
                job_id, f"The reference prompt could not be written: {outcome.failure}"
            )
            return

        await self._save(
            job_id,
            project.id,
            kind,
            member_id,
            checked,
            outcome,
            started,
            generate_after=job_input.get("generate_after") is True,
        )

    # --- Saving the prompt ----------------------------------------------------------

    async def _save(
        self,
        job_id: int,
        project_id: int,
        kind: str,
        member_id: int,
        checked: CheckedPrompt,
        outcome: llm_call.Outcome,
        started: float,
        *,
        generate_after: bool,
    ) -> None:
        """Writes the prompt into the member and finishes the job in one transaction. With
        `generate_after` (the click asked for a picture, and the member had no prompt) the job
        that makes the picture is created in the same transaction: the backend starts the next
        step by itself, so a prompt is never saved without the picture that was asked for.
        """
        await self._phase(job_id, phases.SAVING_REFERENCE_PROMPT)
        output = {
            **outcome.record(),
            "content": None,
            "image_prompt": checked.text,
            "word_count": checked.word_count,
            "warnings": list(checked.warnings),
            "seconds": round(time.monotonic() - started, 1),
        }
        gone = False
        started_picture = False
        async with SessionLocal() as session:
            # Finishing the job first takes the database's write lock, so the member cannot be
            # replaced between the check below and the write.
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            member = await cast_service.get_member(session, project_id, kind, member_id)
            if member is None:
                gone = True
                await session.rollback()
            else:
                cast_service.mark_prompted(member, checked.text, job_id)
                if generate_after:
                    named = {cast_service.KIND_KEY: kind, cast_service.ID_KEY: member_id}
                    _job, started_picture = await store.create_job(
                        session,
                        project_id=project_id,
                        type=cast_service.REFERENCE_IMAGE_JOB,
                        provider="gpu",
                        input={"requested": "after_prompt", **named},
                        commit=False,
                        same_input=named,
                    )
                await session.commit()
        if gone:
            await self._fail(job_id, _MEMBER_GONE)
            return
        if started_picture:
            dispatcher.nudge()
        _logger.info(
            "job %d: reference prompt written: %s=%d words=%d warnings=%d usage=%s",
            job_id,
            kind,
            member_id,
            checked.word_count,
            len(checked.warnings),
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
