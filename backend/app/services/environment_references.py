"""A library environment's canonical reference picture (PHASE-012): one empty, wide
establishing view of the place at 16:9, chosen by the author from four candidates.

**Making one** (`start_reference`), for the environment's newest version:

1. A `write_environment_prompt` job writes the prompt from the environment's card, on the
   environment sheet profile (`image_prompt_profiles.ACTIVE_ENVIRONMENT_SHEET_PROFILE`).
2. When it finishes (`on_prompt_written`, called by the job), four `lab_image` text-to-image
   runs with different random seeds make the candidates (`environment_reference_candidate`
   rows, read live from their `lab_run`). Nothing else is started: a place has no angles and
   its picture is not cut out, because the place is the background.
3. `choose` makes one candidate the canonical picture of the version the attempt was made for
   (`library_environment_version.reference_image_id`).

**Versions and pictures.** A picture is made for one version's text. `choose` only works on the
environment's **newest** version, and may replace the picture already chosen for it. Once an
edit adds a newer version, the older one is frozen and keeps its own picture; the new version
starts with none. (PHASE-013 will tighten this to "frozen once a project pins it".)

This module creates rows and jobs. It never calls the GPU server or the language model itself.
"""

from __future__ import annotations

import logging
import secrets
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import (
    EnvironmentReference,
    EnvironmentReferenceCandidate,
    Job,
    LabImage,
    LabRun,
    LibraryEnvironment,
    LibraryEnvironmentVersion,
)
from app.db.session import SessionLocal
from app.jobs import store
from app.services import environment_library, environment_versions, image_lab
from app.services import image_models as image_models_service
from app.services.image_lab import LabInputError, QwenLabForm
from app.services.image_models import IMAGE_MODE_KEY

_logger = logging.getLogger(__name__)

# A place is shown wide, whatever the orientation of the project that later uses it.
REFERENCE_SHAPE: Final = "16:9"
# How many candidates one attempt makes to choose from.
CANDIDATE_COUNT: Final = 4


class EnvironmentReferenceError(ValueError):
    """Something the request gets wrong, or a step that cannot start now. The message is meant
    for the user (HTTP 422).
    """


# --- Starting an attempt ------------------------------------------------------------------


async def start_reference(session: AsyncSession, environment_id: int) -> EnvironmentReference:
    """Starts an attempt to make a canonical picture for the environment's newest version: a
    job writes the prompt first. Commits. Raises EnvironmentReferenceError.
    """
    environment = await session.get(LibraryEnvironment, environment_id)
    if environment is None:
        raise EnvironmentReferenceError(f"There is no environment {environment_id}.")
    if environment.archived:
        raise EnvironmentReferenceError("This environment is archived: unarchive it first.")
    version = await environment_versions.latest_version(session, environment_id)
    if version is None:
        raise EnvironmentReferenceError("This environment has no version yet: save it first.")
    busy = await session.execute(
        select(EnvironmentReference.id).where(
            EnvironmentReference.version_id == version.id,
            EnvironmentReference.status == "writing_prompt",
        )
    )
    if busy.first() is not None:
        raise EnvironmentReferenceError("A prompt is already being written for this version.")

    attempt = EnvironmentReference(environment_id=environment_id, version_id=version.id)
    session.add(attempt)
    await session.flush()
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=environment_library.PROMPT_JOB,
        provider="llm",
        input={
            "environment_id": environment_id,
            "reference_id": attempt.id,
            "version": version.version,
        },
        commit=False,
        dedupe=False,
    )
    attempt.prompt_job_id = job.id
    await session.commit()
    _logger.info(
        "environment %d: reference %d started for version %d",
        environment_id,
        attempt.id,
        version.version,
    )
    return attempt


async def on_prompt_written(job_id: int) -> bool:
    """Called when a `write_environment_prompt` job finishes. Saves the prompt and starts the
    candidate pictures. Returns True when they started. If they cannot be started the attempt
    is marked `failed`, so the page shows why instead of waiting forever.
    """
    async with SessionLocal() as session:
        statement = select(EnvironmentReference).where(EnvironmentReference.prompt_job_id == job_id)
        attempt = (await session.execute(statement)).scalars().first()
        if attempt is None or attempt.status != "writing_prompt":
            await session.commit()
            return False
        job = await session.get(Job, job_id)
        output = job.output if job is not None and isinstance(job.output, dict) else {}
        prompt = output.get("image_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            attempt.status = "failed"
            attempt.error = "The reference prompt could not be written."
            await session.commit()
            return False
        attempt.prompt = prompt.strip()
        attempt_id = attempt.id
        try:
            await _start_candidates(session, attempt)
        except EnvironmentReferenceError as exc:
            await session.rollback()
            failed = await session.get(EnvironmentReference, attempt_id)
            if failed is not None:
                failed.status = "failed"
                failed.error = str(exc)
                await session.commit()
            return False
        attempt.status = "ready"
        await session.commit()
    _logger.info(
        "environment reference %d: prompt saved, %d candidates started",
        attempt_id,
        CANDIDATE_COUNT,
    )
    return True


async def on_prompt_failed(job_id: int, error: str) -> None:
    """Called when a `write_environment_prompt` job has failed. Marks the attempt `failed`."""
    async with SessionLocal() as session:
        statement = select(EnvironmentReference).where(EnvironmentReference.prompt_job_id == job_id)
        attempt = (await session.execute(statement)).scalars().first()
        if attempt is not None and attempt.status == "writing_prompt":
            attempt.status = "failed"
            attempt.error = error
        await session.commit()


async def _start_candidates(session: AsyncSession, attempt: EnvironmentReference) -> None:
    """Four text-to-image runs from the prompt, each with its own random seed. No commit."""
    mode = image_models_service.resolve_mode(
        await settings_service.get_str(session, IMAGE_MODE_KEY)
    )
    for _ in range(CANDIDATE_COUNT):
        seed = secrets.randbelow(image_models_service.SEED_LIMIT)
        form = QwenLabForm(
            prompt=attempt.prompt or "",
            mode=mode,
            aspect_ratio=REFERENCE_SHAPE,
            seed=seed,
            steps=None,
        )
        try:
            run, _job = await image_lab.create_qwen_run(session, form, commit=False)
        except LabInputError as exc:
            raise EnvironmentReferenceError(str(exc)) from exc
        session.add(EnvironmentReferenceCandidate(reference_id=attempt.id, lab_run_id=run.id))


# --- Choosing the canonical picture --------------------------------------------------------


async def choose(
    session: AsyncSession, reference_id: int, candidate_id: int
) -> LibraryEnvironmentVersion:
    """Makes one candidate the canonical picture of the version its attempt was made for, and
    returns that version. It replaces a picture chosen earlier. Only the environment's newest
    version can be changed. Commits. Raises EnvironmentReferenceError.
    """
    attempt = await session.get(EnvironmentReference, reference_id)
    if attempt is None:
        raise EnvironmentReferenceError(f"There is no reference {reference_id}.")
    version = await session.get(LibraryEnvironmentVersion, attempt.version_id)
    if version is None:
        raise EnvironmentReferenceError("The version this picture was made for is gone.")
    newest = await environment_versions.latest_version(session, attempt.environment_id)
    if newest is None or newest.id != version.id:
        raise EnvironmentReferenceError(
            f"Version {version.version} is frozen: only the newest version's picture can be "
            "changed. Make a new picture for the newest version."
        )
    candidate = await session.get(EnvironmentReferenceCandidate, candidate_id)
    if candidate is None or candidate.reference_id != reference_id:
        raise EnvironmentReferenceError(f"There is no candidate {candidate_id} on this attempt.")
    if candidate.lab_run_id is None:
        raise EnvironmentReferenceError("This candidate has no picture.")
    run = await session.get(LabRun, candidate.lab_run_id)
    if run is None or run.status != "succeeded":
        raise EnvironmentReferenceError("This candidate's picture is not ready yet.")
    image_statement = select(LabImage).where(LabImage.run_id == run.id)
    image = (await session.execute(image_statement)).scalars().first()
    if image is None:
        raise EnvironmentReferenceError("This candidate's picture is gone.")

    version.reference_image_id = image.id
    await session.commit()
    _logger.info(
        "environment %d: version %d picture chosen: image=%d",
        attempt.environment_id,
        version.version,
        image.id,
    )
    return version


# --- Reading ------------------------------------------------------------------------------


async def list_references(session: AsyncSession, environment_id: int) -> list[EnvironmentReference]:
    """Every attempt for the environment, newest first."""
    statement = (
        select(EnvironmentReference)
        .where(EnvironmentReference.environment_id == environment_id)
        .order_by(EnvironmentReference.id.desc())
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars().all())


async def candidates_for(
    session: AsyncSession, reference_id: int
) -> list[EnvironmentReferenceCandidate]:
    """The attempt's candidates, in the order they were made."""
    statement = (
        select(EnvironmentReferenceCandidate)
        .where(EnvironmentReferenceCandidate.reference_id == reference_id)
        .order_by(EnvironmentReferenceCandidate.id)
    )
    return list((await session.execute(statement)).scalars().all())
