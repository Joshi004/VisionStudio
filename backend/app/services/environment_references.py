"""A library environment's canonical reference picture (PHASE-012): one empty, wide
establishing view of the place at 16:9.

**Making one** (`start_reference`):

1. A `write_environment_prompt` job writes the prompt from the card of the version the picture
   is for, on the environment sheet profile
   (`image_prompt_profiles.ACTIVE_ENVIRONMENT_SHEET_PROFILE`).
2. When it finishes (`on_prompt_written`, called by the job), `lab_image` text-to-image runs
   with different random seeds make the candidates (`environment_reference_candidate` rows,
   read live from their `lab_run`). Nothing else is started: a place has no angles and its
   picture is not cut out, because the place is the background.
3. The candidate becomes the canonical picture of the version the attempt was made for
   (`library_environment_version.reference_image_id`).

There are two kinds of attempt:

- **A lab attempt** is for the environment's newest version. It makes four candidates and
  waits: `choose` makes the one the author picks the canonical picture.
- **A pipeline attempt** (PHASE-013, `PipelineAttempt`) is for the version a story project
  pins, started by the Environment Definition stage. It makes one candidate and takes it as the
  canonical picture by itself (`on_candidate_image_stored`, D-5), the way a pipeline look
  takes its one candidate as the master (PHASE-010).

**Versions and pictures.** A picture is made for one version's text, so an edit never carries it
forward: the new version starts with none and the older one keeps its own. In the lab, `choose`
and a new lab attempt work on the environment's **newest** version only, and not on a version
that a project pins and that already has its picture (**frozen**): such a picture is what the
project's later stages read, so it is never replaced. To get another picture, edit the
environment (a new version) and make one for that. The pipeline only ever puts a picture on a
version that has none.

This module creates rows and jobs. It never calls the GPU server or the language model itself.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
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
    ProjectEnvironmentLink,
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
# How many candidates a lab attempt makes for the author to choose from.
CANDIDATE_COUNT: Final = 4
# How many candidates a pipeline attempt makes: the one is taken as the picture by itself.
AUTOMATIC_CANDIDATE_COUNT: Final = 1


class EnvironmentReferenceError(ValueError):
    """Something the request gets wrong, or a step that cannot start now. The message is meant
    for the user (HTTP 422).
    """


@dataclass(frozen=True)
class PipelineAttempt:
    """What marks an attempt as made by the story pipeline: the project and the discovered
    environment it is for, and the version (`library_environment_version.id`) the project pins,
    which is the version the picture is made for.
    """

    project_id: int
    discovery_id: str
    version_id: int


# --- Pins and the frozen rule -------------------------------------------------------------


async def pinning_links(
    session: AsyncSession, environment_id: int, version: int
) -> list[ProjectEnvironmentLink]:
    """The links of the projects that pin this version of the environment."""
    statement = (
        select(ProjectEnvironmentLink)
        .where(
            ProjectEnvironmentLink.environment_id == environment_id,
            ProjectEnvironmentLink.pinned_version == version,
        )
        .order_by(ProjectEnvironmentLink.id)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars())


async def is_frozen(session: AsyncSession, version: LibraryEnvironmentVersion) -> bool:
    """Whether the version's picture can no longer be changed in the lab because a project pins
    the version and the version already has its picture.
    """
    if version.reference_image_id is None:
        return False
    return bool(await pinning_links(session, version.environment_id, version.version))


# --- Starting an attempt ------------------------------------------------------------------


async def start_reference(
    session: AsyncSession,
    environment_id: int,
    *,
    pipeline: PipelineAttempt | None = None,
    commit: bool = True,
) -> EnvironmentReference:
    """Starts an attempt to make a canonical picture: a job writes the prompt first. Raises
    EnvironmentReferenceError.

    Without `pipeline` this is a lab attempt for the environment's newest version, which must
    not be frozen. With it, this is the story pipeline's attempt for the version the project
    pins, which must not have a picture yet (an archived environment is allowed: the
    definition that asked for the picture was already saved). Commits, unless `commit` is
    False: the attempt and its job are then only flushed, so the Environment Definition stage
    can save the definition and start the picture in one transaction.
    """
    environment = await session.get(LibraryEnvironment, environment_id)
    if environment is None:
        raise EnvironmentReferenceError(f"There is no environment {environment_id}.")
    if pipeline is None:
        if environment.archived:
            raise EnvironmentReferenceError("This environment is archived: unarchive it first.")
        version = await environment_versions.latest_version(session, environment_id)
        if version is None:
            raise EnvironmentReferenceError("This environment has no version yet: save it first.")
        if await is_frozen(session, version):
            raise EnvironmentReferenceError(
                f"Version {version.version} is pinned by a project and already has its picture, "
                "so it cannot be replaced. Edit the environment to make a new version, then "
                "make a picture for that one."
            )
    else:
        found = await session.get(LibraryEnvironmentVersion, pipeline.version_id)
        if found is None or found.environment_id != environment_id:
            raise EnvironmentReferenceError("The version this picture is for does not exist.")
        version = found
        if version.reference_image_id is not None:
            raise EnvironmentReferenceError(f"Version {version.version} already has its picture.")
    busy = await session.execute(
        select(EnvironmentReference.id).where(
            EnvironmentReference.version_id == version.id,
            EnvironmentReference.status == "writing_prompt",
        )
    )
    if busy.first() is not None:
        raise EnvironmentReferenceError("A prompt is already being written for this version.")

    attempt = EnvironmentReference(
        environment_id=environment_id,
        version_id=version.id,
        project_id=pipeline.project_id if pipeline is not None else None,
        discovery_id=pipeline.discovery_id if pipeline is not None else None,
    )
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
    if commit:
        await session.commit()
    else:
        await session.flush()
    _logger.info(
        "environment %d: reference %d started for version %d (%s)",
        environment_id,
        attempt.id,
        version.version,
        "pipeline" if pipeline is not None else "lab",
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
        count = _candidate_count(attempt)
        try:
            await _start_candidates(session, attempt, count)
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
        count,
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


def _candidate_count(attempt: EnvironmentReference) -> int:
    """One candidate for an attempt the story pipeline made, four for one made in the lab."""
    return AUTOMATIC_CANDIDATE_COUNT if attempt.project_id is not None else CANDIDATE_COUNT


async def _start_candidates(
    session: AsyncSession, attempt: EnvironmentReference, count: int
) -> None:
    """`count` text-to-image runs from the prompt, each with its own random seed. No commit."""
    mode = image_models_service.resolve_mode(
        await settings_service.get_str(session, IMAGE_MODE_KEY)
    )
    for _ in range(count):
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
    version can be changed, and not one that a project pins and that already has its picture
    (`is_frozen`). Commits. Raises EnvironmentReferenceError.
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
    if await is_frozen(session, version):
        raise EnvironmentReferenceError(
            f"Version {version.version} is pinned by a project and already has its picture, so "
            "it cannot be replaced. Edit the environment to make a new version, then make a "
            "picture for that one."
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


async def on_candidate_image_stored(run_id: int) -> bool:
    """Called (best effort) once a `lab_image` job has stored its picture. When the picture is
    the candidate of an attempt the story pipeline made (`project_id` set), takes it as the
    canonical picture of the version the attempt was made for (D-5), unless that version has a
    picture already (a lab attempt chose one first). Returns True when the picture was set.
    Does nothing (False) for a lab attempt, whose picture the author chooses, and for a run
    that is no candidate.
    """
    async with SessionLocal() as session:
        statement = select(EnvironmentReferenceCandidate).where(
            EnvironmentReferenceCandidate.lab_run_id == run_id
        )
        candidate = (await session.execute(statement)).scalars().first()
        attempt = (
            await session.get(EnvironmentReference, candidate.reference_id)
            if candidate is not None
            else None
        )
        if attempt is None or attempt.project_id is None:
            await session.commit()
            return False
        version = await session.get(LibraryEnvironmentVersion, attempt.version_id)
        if version is None or version.reference_image_id is not None:
            await session.commit()
            return False
        image_statement = select(LabImage).where(LabImage.run_id == run_id)
        image = (await session.execute(image_statement)).scalars().first()
        if image is None:
            await session.commit()
            return False
        image_id = image.id
        version.reference_image_id = image_id
        environment_id, version_number = attempt.environment_id, version.version
        await session.commit()
    _logger.info(
        "environment %d: version %d picture taken automatically: image=%d",
        environment_id,
        version_number,
        image_id,
    )
    return True


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
