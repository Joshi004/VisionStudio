"""The `describe_photo` job: a vision model reads a photo from the Image lab and writes the text
of a new character (appearance, outfit, personality) or of a new outfit (description, name,
note), so the owner does not have to type them (`services/photo_describer.py`).

`job.input` holds `lab_image_id` and `mode` (`character` or `outfit`) only. The answer is on
`job.output.fields`, and nothing is saved anywhere else: the page puts the text in its boxes,
where the owner reads and changes it before saving.

It is a paid call to the Bitdeer vision model (`vision_llm_model`), so the rules of
`jobs/llm_call.py` hold: at most 2 attempts, a refusal is never retried, the answer is saved the
moment it arrives, and a restart does not run it again (`never_rerun`). The job counts in the
same paid pool as the other language-model jobs. The photo is not copied onto the job, and logs
hold the job id and token counts, never the photo or the answer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.models import LabImage
from app.db.session import SessionLocal
from app.jobs import llm_call, phase_writer, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target
from app.services import photo_describer as describer
from app.services.llm_target import VISION_MODEL_KEY
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "describe_photo"
# A vision model takes longer than a text one, and the photo is a large upload.
REQUEST_TIMEOUT_S: Final = 180.0

_BAD_INPUT = "This job does not say which photo to read, or how."
_NO_PHOTO = "The photo is no longer in the Image lab."


def _read(mode: str) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, str] | None]:
        if result.finish_reason == "length":
            return "The model's answer was cut off because it reached the token limit.", None
        try:
            return None, describer.check_answer(result.content, mode)
        except describer.PhotoError as exc:
            return str(exc), None

    return read


class DescribePhotoHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = VISION_MODEL_KEY

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            image_id = job_input.get("lab_image_id")
            mode = job_input.get("mode")
            image = await session.get(LabImage, image_id) if isinstance(image_id, int) else None
            relative_path = image.path if image is not None else None
            target = await llm_target.resolve(session, VISION_MODEL_KEY)
            await session.commit()

        if not isinstance(image_id, int) or mode not in describer.MODES:
            await self._fail(job_id, _BAD_INPUT)
            return
        if relative_path is None:
            await self._fail(job_id, _NO_PHOTO)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        try:
            path = get_storage().get_path(relative_path)
            jpeg = await asyncio.to_thread(describer.prepare_photo, path)
        except (describer.PhotoError, StorageError) as exc:
            await self._fail(job_id, str(exc))
            return
        body = describer.build_request(jpeg, mode, model=target.model)
        job_input.update(
            instructions_sha256=llm_call.instructions_sha256(body),
            server_url=docker_mapped(target.base_url),
            endpoint=llm_target.endpoint(target),
            request=describer.without_photo(body),
        )
        async with SessionLocal() as session:
            await store.update_input(session, job_id, job_input)

        outcome = await llm_call.ask_model(
            job_id, target, body, _read(mode), timeout_s=REQUEST_TIMEOUT_S
        )
        fields: dict[str, str] | None = outcome.value
        if fields is None:
            await self._fail(job_id, f"The photo could not be described: {outcome.failure}")
            return

        output = {
            **outcome.record(),
            "content": None,
            "fields": fields,
            "mode": mode,
            "seconds": round(time.monotonic() - started, 1),
        }
        async with SessionLocal() as session:
            if not await store.finish_job(session, job_id, output):
                await session.rollback()
                return
            await session.commit()
        _logger.info("job %d: photo described (%s), usage=%s", job_id, mode, outcome.usage)

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        await phase_writer.note(job_id, phase)

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
