"""The Environment Definition stage of a story project (PHASE-013, `Path_ahead.md` Section 13).

Each discovered environment that is linked to a library environment
(`services/environment_links.py`) gets one `define_environment` job. The job asks the model for
the structured definition and `save_definition` stores it **on the library environment**: the
profile fields it fills are overwritten from it
(`services/environment_definition_writer.to_profile`), the environment's `definition` holds the
structured form, a new `library_environment_version` is written (`source` is `ai`, with the job
and the inputs it was built from, D-3), and the project's pin moves to that version. That last
step is this stage's own change to the pin; a lab edit never moves it. The same transaction
then starts the version's canonical picture (`services/environment_references`, a pipeline
attempt: one candidate, taken as the picture by itself), so the picture is attached to the
version the project pins.

- `start_run` queues the job for one entry. It refuses, readably, when the story, the
  StoryBible, the scenes or the link is missing, and when the environment was chosen from the
  library (`how = "mapped"`) and the user has not confirmed the overwrite.
- `start_all` queues a job for every linked entry that the pipeline made (`how = "created"`),
  that is not archived, not already defined and current, and not already being defined. A
  mapped environment is never touched by it, except one from the project's cast (see below)
  that still needs a definition. The jobs run side by side when the pool allows
  (`store.create_job` with `dedupe_key`).
- `start_picture` starts the picture again for an entry that is defined but has no picture
  (it failed, or was never started).
- `state` is what the story workspace shows: for each entry its link, its status, why it is out
  of date, the definition the pinned version holds, the newest job and how the picture is
  doing. **Out of date is worked out on every read** and never stored: a version is judged only
  when it was written for this project and this entry, and then the story text, the
  StoryBible, the entry's name and description and the story's scenes are compared with what
  its `inputs` recorded.
- `save_definition` is called by the job and flushes without committing; the job commits it
  together with finishing itself.

A mapped environment that is in the project's cast (`services/project_cast.py`, PHASE-048) is a
**reused** environment, and the user already chose to use it, so nothing asks before it is
defined. Its mode decides the rest: with `as_is` a pinned version that holds a definition counts
as `defined` whatever project it was written for, and is never judged out of date; with
`rewrite_text` the normal rules apply, so a definition is written for this story. Either way a
definition that is written treats the environment's current profile as fixed and keeps the
canonical picture it already has (`keep_picture`).

The scenes are an input because Section 13 gives the model "the scenes using the environment".
Scene discovery records no environment ids (D-15), so the model is given the whole list of
scenes and the story, and works out where the environment appears itself. A definition is
therefore out of date when the scenes are found again, and nothing can be defined until the
scenes exist and are up to date.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    EnvironmentReference,
    Job,
    LabImage,
    LabRun,
    LibraryEnvironment,
    LibraryEnvironmentVersion,
    Project,
    ProjectEnvironmentLink,
    SceneDiscovery,
    StoryBible,
)
from app.db.state_memo import memoized_state
from app.db.types import utcnow
from app.jobs import store
from app.services import (
    discovery,
    environment_definition_writer,
    environment_library,
    environment_links,
    environment_references,
    environment_versions,
    image_lab,
    library_adoption,
    project_cast,
    story_bible,
)
from app.services.environment_links import EntryState

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "define_environment"
# Two presses on one environment make one job; two environments run side by side.
DEDUPE_KEY: Final = "discovery_id"

# How many of a project's newest definition jobs are read to find each entry's newest one.
_JOB_LOOKBACK: Final = 500

STORY_BIBLE_KIND: Final = "story_bible"
ENVIRONMENT_DISCOVERY_KIND: Final = "environment_discovery"
SCENE_DISCOVERY_KIND: Final = "scene_discovery"

_DEAD_JOB_STATUSES: Final = ("failed", "cancelled")

# `unlinked`: no library environment yet. `not_defined`: linked, but no definition was written
# for this entry in this project. `defined`: written, and nothing it was built from has
# changed. `out_of_date`: written, and something it was built from has changed (the reasons).
Status = Literal["unlinked", "not_defined", "defined", "out_of_date"]

# `unavailable`: no picture can be made yet (not linked, or not defined). `none`: defined, and
# no picture was started or one was never attached. `in_progress`: being made (`stage` says
# which step). `failed`: the attempt failed (`error` says why). `ready`: the pinned version has
# its canonical picture.
PictureStatus = Literal["unavailable", "none", "in_progress", "failed", "ready"]
PictureStage = Literal["writing_prompt", "drawing"]


class EnvironmentDefinitionError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class PictureState:
    """How the canonical picture of the version a project pins is doing."""

    status: PictureStatus
    stage: PictureStage | None
    error: str | None
    # The pinned version's canonical picture, when it has one.
    image: LabImage | None
    # Whether Retry picture may be pressed, and the reason when it may not.
    can_run: bool
    blocked_reason: str | None


@dataclass(frozen=True)
class EntryDefinition:
    """One entry of the newest list of environments and where its definition stands."""

    item: dict[str, Any]
    entry: EntryState
    status: Status
    # Why a defined entry is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The pinned version, when it holds a definition written for this entry (else None).
    version: LibraryEnvironmentVersion | None
    # The newest definition job of this entry, whatever its status.
    job: Job | None
    # Whether the Define button may be pressed, and the reason when it may not.
    can_run: bool
    blocked_reason: str | None
    # True when pressing Define overwrites an environment the user chose from the library, so
    # the user is asked first.
    needs_confirmation: bool
    picture: PictureState

    @property
    def definition(self) -> dict[str, Any] | None:
        return self.version.definition if self.version is not None else None


@dataclass(frozen=True)
class DefinitionsState:
    """What the story workspace shows. `discovery_version` is None when no list exists."""

    discovery_version: int | None
    entries: list[EntryDefinition]
    # Why nothing can be defined yet (no story, StoryBible or scenes, or one out of date), or
    # None.
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    """An entry that "Define all" did not start, and why."""

    discovery_id: str
    name: str
    reason: str


@dataclass(frozen=True)
class StartAllResult:
    job_ids: list[int]
    skipped: list[Skipped]


@dataclass(frozen=True)
class _Inputs:
    """What every job of a run reads: the saved story and the artifacts it is built from."""

    story: str
    bible: StoryBible
    scenes: SceneDiscovery


# --- Inputs -------------------------------------------------------------------------------


def entry_sha256(item: dict[str, Any]) -> str:
    """A name for the entry as the model saw it: its name and its one-line description."""
    text = json.dumps(
        {"name": item["name"], "description": item["description"]},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _latest_scenes(session: AsyncSession, project_id: int) -> SceneDiscovery | None:
    return cast(SceneDiscovery | None, await discovery.latest(session, "scenes", project_id))


def _blocked_reason(
    story: str | None, bible: StoryBible | None, scenes: SceneDiscovery | None
) -> str | None:
    """Why nothing can be defined from this story, StoryBible and scenes, or None when it can."""
    if story is None or not story.strip():
        return "Save the story first: an environment is defined from the story."
    if bible is None:
        return "Run the Story Bible first: an environment is defined with its help."
    if story_bible.is_out_of_date(story, bible):
        return (
            "The Story Bible is out of date, because the story has changed since it was "
            "written. Re-run the Story Bible first, then define the environments."
        )
    if scenes is None:
        return "Find the scenes first: an environment is defined with their help."
    if discovery.is_out_of_date(story, scenes, bible.version):
        return (
            "The scenes are out of date, because the story or the Story Bible has changed "
            "since they were found. Find the scenes again first, then define the environments."
        )
    return None


async def _require_inputs(session: AsyncSession, project: Project) -> _Inputs:
    """The saved story, its up-to-date StoryBible and its up-to-date scenes. Raises
    EnvironmentDefinitionError.
    """
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    scenes = await _latest_scenes(session, project.id)
    reason = _blocked_reason(story, bible, scenes)
    if reason is not None or story is None or bible is None or scenes is None:
        raise EnvironmentDefinitionError(reason or "There is no story to define from.")
    return _Inputs(story=story, bible=bible, scenes=scenes)


def _entry_refusal(entry: EntryState) -> str | None:
    """Why this entry cannot be defined on its own (no link, or an archived environment)."""
    if entry.info is None:
        return (
            f"'{entry.item['name']}' is not linked to a Character Lab environment yet. "
            "Link it first."
        )
    if entry.info.environment.archived:
        return (
            f"{entry.info.environment.name} is archived. Unarchive it in the Character Lab to "
            "define it."
        )
    return None


def _reuse(entry: EntryState, modes: dict[int, project_cast.Mode]) -> project_cast.Mode | None:
    """The cast mode of the entry when it is a reused environment, else None."""
    if entry.info is None:
        return None
    return project_cast.reuse_mode(modes, entry.info.link.environment_id, entry.info.link.how)


def _needs_confirmation(entry: EntryState, modes: dict[int, project_cast.Mode]) -> bool:
    """Whether defining the entry overwrites an environment the user chose by hand. One from
    the project's cast does not: choosing it for the cast was the confirmation.
    """
    return (
        entry.info is not None and entry.info.link.how == "mapped" and _reuse(entry, modes) is None
    )


def _other(other: dict[str, Any]) -> dict[str, str]:
    """One of the other environments as the model sees it."""
    return {"id": other["id"], "name": other["name"], "description": other["description"]}


async def _queue(
    session: AsyncSession,
    project: Project,
    run: _Inputs,
    newest: discovery.Discovery,
    entry: EntryState,
    items: list[dict[str, Any]],
    *,
    keep_picture: bool,
) -> tuple[Job, bool]:
    """Queues the job for one linked entry, and returns `(job, created)`. `created` is False
    when the entry already has a job waiting or running, which is returned instead.
    """
    assert entry.info is not None  # the callers refuse an unlinked entry first
    item = entry.item
    story_hash = story_bible.story_sha256(run.story)
    artifacts = [
        {"kind": STORY_BIBLE_KIND, "id": run.bible.id, "version": run.bible.version},
        {"kind": ENVIRONMENT_DISCOVERY_KIND, "id": newest.id, "version": newest.version},
        {"kind": SCENE_DISCOVERY_KIND, "id": run.scenes.id, "version": run.scenes.version},
    ]
    inputs = {
        "project_id": project.id,
        "discovery_id": item["id"],
        "story_sha256": story_hash,
        "entry_sha256": entry_sha256(item),
        "artifacts": artifacts,
    }
    return await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "story_text": run.story,
            "story_sha256": story_hash,
            "story_bible_id": run.bible.id,
            "story_bible_version": run.bible.version,
            "discovery_version": newest.version,
            "discovery_id": item["id"],
            "entry": {
                "id": item["id"],
                "name": item["name"],
                "description": item["description"],
            },
            "others": [_other(other) for other in items if other["id"] != item["id"]],
            "scenes": environment_definition_writer.scenes_for_prompt(run.scenes.content["scenes"]),
            "environment_id": entry.info.link.environment_id,
            # A reused environment: its profile is fixed and its picture is kept (PHASE-048).
            "keep_picture": keep_picture,
            # Written onto the version the job makes (D-3).
            "inputs": inputs,
        },
        dedupe_key=DEDUPE_KEY,
    )


async def _entries(
    session: AsyncSession, project: Project
) -> tuple[discovery.Discovery, list[dict[str, Any]], list[EntryState]]:
    """The newest list of environments (its row, its items) and each item's link. Raises
    EnvironmentDefinitionError when there is no list.
    """
    newest = await discovery.latest(session, "environments", project.id)
    if newest is None:
        raise EnvironmentDefinitionError(
            "Find the environments first: there is nothing to define yet."
        )
    links = await environment_links.state(session, project.id)
    return newest, newest.content["environments"], links.entries


# --- Starting runs ------------------------------------------------------------------------


async def start_run(
    session: AsyncSession,
    project: Project,
    discovery_id: str,
    *,
    confirm_overwrite: bool = False,
) -> Job:
    """Queues the job that defines one environment, and commits. If that environment already
    has a job waiting or running, that job is returned and no new one is made.

    An environment the user chose from the library (`mapped`) is overwritten only when
    `confirm_overwrite` is true. Raises EnvironmentDefinitionError.
    """
    run = await _require_inputs(session, project)
    newest, items, entries = await _entries(session, project)
    entry = next((entry for entry in entries if entry.item["id"] == discovery_id), None)
    if entry is None:
        raise EnvironmentDefinitionError(
            f"There is no environment '{discovery_id}' in the newest list of environments."
        )
    refusal = _entry_refusal(entry)
    if refusal is not None:
        raise EnvironmentDefinitionError(refusal)
    modes = await project_cast.cast_modes(session, project.id, "environments")
    if _needs_confirmation(entry, modes) and not confirm_overwrite:
        raise EnvironmentDefinitionError(
            f"{entry.item['name']} was chosen from the Character Lab. Defining it overwrites "
            "its description, atmosphere and era, so it has to be confirmed."
        )
    job, _created = await _queue(
        session, project, run, newest, entry, items, keep_picture=_reuse(entry, modes) is not None
    )
    return job


async def start_all(session: AsyncSession, project: Project) -> StartAllResult:
    """Queues a job for every linked environment that the pipeline made, that is not archived,
    not defined and current already, and not being defined, and commits each. An environment
    chosen from the library is skipped (define it on its own, which asks first). Raises
    EnvironmentDefinitionError when there is no story, StoryBible, scenes or list of
    environments.
    """
    run = await _require_inputs(session, project)
    newest, items, entries = await _entries(session, project)
    current = {item.item["id"]: item for item in (await state(session, project)).entries}
    modes = await project_cast.cast_modes(session, project.id, "environments")
    job_ids: list[int] = []
    skipped: list[Skipped] = []
    for entry in entries:
        name = entry.item["name"]
        refusal = _entry_refusal(entry)
        if refusal is not None:
            skipped.append(Skipped(entry.item["id"], name, refusal))
            continue
        if _needs_confirmation(entry, modes):
            skipped.append(
                Skipped(
                    entry.item["id"],
                    name,
                    "Chosen from the Character Lab: define it on its own, which asks first.",
                )
            )
            continue
        if current[entry.item["id"]].status == "defined":
            skipped.append(Skipped(entry.item["id"], name, "Already defined and up to date."))
            continue
        keep_picture = _reuse(entry, modes) is not None
        job, created = await _queue(
            session, project, run, newest, entry, items, keep_picture=keep_picture
        )
        if created:
            job_ids.append(job.id)
        else:
            skipped.append(Skipped(entry.item["id"], name, "Already being defined."))
    return StartAllResult(job_ids=job_ids, skipped=skipped)


async def start_picture(
    session: AsyncSession, project: Project, discovery_id: str
) -> EnvironmentReference:
    """Starts the canonical picture of the version the project pins again, for an environment
    that is defined but has no picture (it failed, or was never started). Commits. Raises
    EnvironmentDefinitionError.
    """
    current = await state(session, project)
    entry = next((entry for entry in current.entries if entry.item["id"] == discovery_id), None)
    if entry is None:
        raise EnvironmentDefinitionError(
            f"There is no environment '{discovery_id}' in the newest list of environments."
        )
    if not entry.picture.can_run:
        raise EnvironmentDefinitionError(
            entry.picture.blocked_reason or "The picture cannot be made now."
        )
    info = entry.entry.info
    assert info is not None  # `can_run` is only true for a linked entry
    pinned = await environment_versions.get_version(
        session, info.link.environment_id, info.link.pinned_version
    )
    assert pinned is not None  # `can_run` is only true when the pinned version exists
    try:
        return await environment_references.start_reference(
            session,
            info.link.environment_id,
            pipeline=environment_references.PipelineAttempt(
                project_id=project.id, discovery_id=discovery_id, version_id=pinned.id
            ),
        )
    except environment_references.EnvironmentReferenceError as exc:
        raise EnvironmentDefinitionError(str(exc)) from exc


async def replace_picture(
    session: AsyncSession, project: Project, discovery_id: str
) -> EnvironmentReference:
    """Makes a new canonical picture for an environment that already has one (PHASE-039), and
    commits. The picture of a pinned version is frozen, so the old one is kept with its
    version: a new version is written with the same definition and inputs and no picture, the
    project's pin moves to it, and the picture is started for it like the pipeline starts one.
    Everything that used the old picture then reads out of date, and nothing is made again by
    itself. Raises EnvironmentDefinitionError.

    It needs the environment linked, defined and current, with a picture, whose pinned version
    is the environment's newest (a newer one made in the lab would otherwise be left behind),
    and no picture being made.
    """
    current = await state(session, project)
    entry = next((entry for entry in current.entries if entry.item["id"] == discovery_id), None)
    if entry is None:
        raise EnvironmentDefinitionError(
            f"There is no environment '{discovery_id}' in the newest list of environments."
        )
    info = entry.entry.info
    if info is None:
        raise EnvironmentDefinitionError("Link the environment first.")
    if entry.status != "defined" or entry.version is None:
        raise EnvironmentDefinitionError(
            "Define the environment first, and bring its definition up to date: the new "
            "picture is made from the definition."
        )
    if info.environment.archived:
        raise EnvironmentDefinitionError(
            f"{info.environment.name} is archived. Unarchive it in the Character Lab."
        )
    if entry.picture.status == "in_progress":
        raise EnvironmentDefinitionError("The picture is being made.")
    pinned = entry.version
    if pinned.reference_image_id is None:
        raise EnvironmentDefinitionError("There is no picture to replace. Use Retry picture.")
    newest = await environment_versions.latest_version(session, info.link.environment_id)
    if newest is None or newest.version != pinned.version:
        raise EnvironmentDefinitionError(
            "A newer version of this environment exists in the Character Lab than the one the "
            "project uses. Move the project to it first."
        )

    # A version adopted from the lab has no `inputs` of its own: the new version carries the
    # ones that stand for the project's definition (PHASE-042), so it needs no provenance link.
    inputs = await library_adoption.effective_inputs(session, "environment", info.link, pinned)
    version = await environment_versions.record_version_if_changed(
        session, info.environment, source="ai", inputs=inputs, new_picture=True
    )
    assert version is not None  # `new_picture` always adds a version
    info.link.pinned_version = version.version
    if inputs is not None:
        info.link.provenance_version = None
    info.link.updated_at = utcnow()
    try:
        attempt = await environment_references.start_reference(
            session,
            info.link.environment_id,
            pipeline=environment_references.PipelineAttempt(
                project_id=project.id, discovery_id=discovery_id, version_id=version.id
            ),
            commit=False,
        )
    except environment_references.EnvironmentReferenceError as exc:
        await session.rollback()
        raise EnvironmentDefinitionError(str(exc)) from exc
    await session.commit()
    return attempt


# --- Reading the state --------------------------------------------------------------------


def _recorded_version(inputs: dict[str, Any], kind: str) -> int | None:
    """The version of the artifact of this kind that `inputs` says the definition read."""
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            version = artifact.get("version")
            return version if isinstance(version, int) else None
    return None


def _out_of_date_reasons(
    inputs: dict[str, Any],
    story: str | None,
    newest_bible_version: int | None,
    newest_scenes_version: int | None,
    item: dict[str, Any],
) -> list[str]:
    """Why a definition written for this entry is no longer current, one sentence each."""
    reasons: list[str] = []
    if story is None or not story.strip():
        reasons.append("The story is now empty.")
    elif inputs.get("story_sha256") != story_bible.story_sha256(story):
        reasons.append("The story has changed since this definition was written.")
    recorded_bible = _recorded_version(inputs, STORY_BIBLE_KIND)
    if recorded_bible is None or (
        newest_bible_version is not None and newest_bible_version > recorded_bible
    ):
        reasons.append("The Story Bible has been written again since this definition was made.")
    if inputs.get("entry_sha256") != entry_sha256(item):
        reasons.append("The environment's name or description has changed in the list.")
    recorded_scenes = _recorded_version(inputs, SCENE_DISCOVERY_KIND)
    if recorded_scenes is None or (
        newest_scenes_version is not None and newest_scenes_version > recorded_scenes
    ):
        reasons.append("The scenes have been found again since this definition was made.")
    return reasons


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest definition job of each discovered environment of the project, by its id."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == JOB_TYPE)
        .order_by(Job.id.desc())
        .limit(_JOB_LOOKBACK)
        .execution_options(populate_existing=True)
    )
    newest: dict[str, Job] = {}
    for job in (await session.execute(statement)).scalars():
        key = job.input.get(DEDUPE_KEY) if isinstance(job.input, dict) else None
        if isinstance(key, str) and key not in newest:
            newest[key] = job
    return newest


async def _newest_attempts(
    session: AsyncSession, project_id: int
) -> dict[tuple[str, int], EnvironmentReference]:
    """The newest picture attempt the pipeline made for each `(discovered environment, version)`
    of the project.
    """
    statement = (
        select(EnvironmentReference)
        .where(EnvironmentReference.project_id == project_id)
        .order_by(EnvironmentReference.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[tuple[str, int], EnvironmentReference] = {}
    for attempt in (await session.execute(statement)).scalars():
        if attempt.discovery_id is None:
            continue
        key = (attempt.discovery_id, attempt.version_id)
        if key not in newest:
            newest[key] = attempt
    return newest


def _job_error(job: Job, what: str) -> str:
    if job.error:
        return job.error
    return f"The {what} was cancelled." if job.status == "cancelled" else f"The {what} failed."


async def _attempt_progress(
    session: AsyncSession, attempt: EnvironmentReference
) -> tuple[PictureStatus, PictureStage | None, str | None]:
    """How a picture attempt that has not attached its picture is doing: still going
    (`in_progress`, and the stage), or `failed` with the reason. The picture of a finished
    attempt is on the version, so a finished attempt that got here lost it.
    """
    if attempt.status == "failed":
        return "failed", None, attempt.error or "The picture failed."
    if attempt.status == "writing_prompt":
        prompt_job = (
            await session.get(Job, attempt.prompt_job_id)
            if attempt.prompt_job_id is not None
            else None
        )
        if prompt_job is not None and prompt_job.status in _DEAD_JOB_STATUSES:
            error = _job_error(prompt_job, "picture prompt")
            return "failed", None, f"The picture's prompt could not be written: {error}"
        return "in_progress", "writing_prompt", None

    candidates = await environment_references.candidates_for(session, attempt.id)
    run_ids = [c.lab_run_id for c in candidates if c.lab_run_id is not None]
    runs = (
        list((await session.execute(select(LabRun).where(LabRun.id.in_(run_ids)))).scalars())
        if run_ids
        else []
    )
    images = await image_lab.images_by_run(session, run_ids)
    if any(images.get(run_id) for run_id in run_ids):
        return (
            "failed",
            None,
            "The picture was made but could not be attached to the environment. Press Retry "
            "picture.",
        )
    jobs = await image_lab.jobs_for_runs(session, runs)
    if jobs and all(job.status in _DEAD_JOB_STATUSES for job in jobs.values()):
        error = _job_error(next(iter(jobs.values())), "picture")
        return "failed", None, f"The picture could not be drawn: {error}"
    return "in_progress", "drawing", None


async def _picture_state(
    session: AsyncSession,
    *,
    entry: EntryState,
    pinned: LibraryEnvironmentVersion | None,
    defined: bool,
    active_definition: bool,
    attempts: dict[tuple[str, int], EnvironmentReference],
) -> PictureState:
    """How the canonical picture of the version the entry pins is doing."""
    if entry.info is None or pinned is None:
        return PictureState("unavailable", None, None, None, False, "Link the environment first.")
    if pinned.reference_image_id is not None:
        image = await session.get(LabImage, pinned.reference_image_id)
        return PictureState("ready", None, None, image, False, None)
    if not defined:
        return PictureState(
            "unavailable",
            None,
            None,
            None,
            False,
            f"{entry.info.environment.name} has no definition yet. Define it first: its "
            "picture is made from the definition.",
        )

    attempt = attempts.get((entry.item["id"], pinned.id))
    status: PictureStatus = "none"
    stage: PictureStage | None = None
    error: str | None = None
    if attempt is not None:
        status, stage, error = await _attempt_progress(session, attempt)
    blocked: str | None = None
    if entry.info.environment.archived:
        blocked = f"{entry.info.environment.name} is archived. Unarchive it in the Character Lab."
    elif active_definition:
        blocked = "A definition is being written. Wait for it to finish."
    elif status == "in_progress":
        blocked = "The picture is being made."
    return PictureState(status, stage, error, None, blocked is None, blocked)


@memoized_state
async def state(session: AsyncSession, project: Project) -> DefinitionsState:
    """The newest list of environments with where each definition and picture stands. Worked
    out on every read; nothing here is stored.
    """
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    scenes = await _latest_scenes(session, project.id)
    blocked = _blocked_reason(story, bible, scenes)
    newest_bible_version = bible.version if bible is not None else None
    newest_scenes_version = scenes.version if scenes is not None else None
    links = await environment_links.state(session, project.id)
    jobs = await _newest_jobs(session, project.id)
    attempts = await _newest_attempts(session, project.id)
    modes = await project_cast.cast_modes(session, project.id, "environments")

    entries: list[EntryDefinition] = []
    for entry in links.entries:
        item = entry.item
        job = jobs.get(item["id"])
        active = job is not None and job.status in store.ACTIVE_STATUSES
        status: Status = "unlinked"
        reasons: list[str] = []
        version: LibraryEnvironmentVersion | None = None
        pinned: LibraryEnvironmentVersion | None = None
        if entry.info is not None:
            status = "not_defined"
            pinned = await environment_versions.get_version(
                session, entry.info.link.environment_id, entry.info.link.pinned_version
            )
            # The pinned version's own `inputs`, or, for a version the project adopted from the
            # lab (PHASE-042), those of the version that stands for the project's definition.
            inputs = await library_adoption.effective_inputs(
                session, "environment", entry.info.link, pinned
            )
            if (
                _reuse(entry, modes) == "as_is"
                and pinned is not None
                and pinned.definition is not None
            ):
                # An environment reused as it is: its own definition counts, whatever project
                # wrote it, and it is never out of date (the story did not make it).
                version = pinned
                status = "defined"
            # Otherwise only a definition written for this entry in this project counts: a
            # pinned version defined for another project, or made by hand in the lab and not
            # adopted over this project's own definition, does not.
            elif (
                pinned is not None
                and pinned.definition is not None
                and inputs is not None
                and library_adoption.names_project(inputs, project.id, item["id"])
            ):
                version = pinned
                reasons = _out_of_date_reasons(
                    inputs, story, newest_bible_version, newest_scenes_version, item
                )
                status = "out_of_date" if reasons else "defined"

        refusal = _entry_refusal(entry)
        blocked_reason = blocked or refusal
        if blocked_reason is None and active:
            blocked_reason = "A definition is already being written."
        picture = await _picture_state(
            session,
            entry=entry,
            pinned=pinned,
            defined=version is not None,
            active_definition=active,
            attempts=attempts,
        )
        entries.append(
            EntryDefinition(
                item=item,
                entry=entry,
                status=status,
                reasons=reasons,
                version=version,
                job=job,
                can_run=blocked_reason is None,
                blocked_reason=blocked_reason,
                needs_confirmation=_needs_confirmation(entry, modes),
                picture=picture,
            )
        )
    return DefinitionsState(
        discovery_version=links.discovery_version, entries=entries, blocked_reason=blocked
    )


async def current_profile_card(
    session: AsyncSession, environment: LibraryEnvironment
) -> str | None:
    """The environment's profile as text for the model to keep to, or None when it has nothing
    a person wrote to keep to.

    An environment the pipeline made from a discovered environment and nobody has touched
    holds only the discovery's name and line, and a default era of the present: telling that to
    the model would push every story into the present day. So the profile is given when the
    environment already has a definition (the pipeline's own text, kept stable when it is
    defined again) or when its newest version was made by hand in the lab.
    """
    if environment.definition is None:
        newest = await environment_versions.latest_version(session, environment.id)
        if newest is None or newest.source != "manual":
            return None
    return environment_library.environment_card(environment)


async def current_picture_prompt(
    session: AsyncSession, environment: LibraryEnvironment
) -> str | None:
    """The prompt the environment's newest version's canonical picture was made from, or None
    when it has no picture or the picture was uploaded (PHASE-050). A reused place that keeps
    its picture shows this to the definition, so its spatial plan agrees with the picture.
    """
    newest = await environment_versions.latest_version(session, environment.id)
    if newest is None or newest.reference_image_id is None:
        return None
    image = await session.get(LabImage, newest.reference_image_id)
    if image is None or image.run_id is None:
        return None
    run = await session.get(LabRun, image.run_id)
    if run is None or not run.prompt:
        return None
    return run.prompt


# --- Saving a definition ------------------------------------------------------------------


async def save_definition(
    session: AsyncSession,
    *,
    project_id: int,
    discovery_id: str,
    environment_id: int,
    definition: dict[str, Any],
    job_id: int,
    inputs: dict[str, Any],
    keep_picture: bool = False,
) -> LibraryEnvironmentVersion:
    """Writes the definition onto the library environment, adds its next version, moves the
    project's pin to it and starts the version's canonical picture. Flushes but does not
    commit: the job commits it together with finishing itself, so a job is never "succeeded"
    without its result.

    With `keep_picture` (a reused environment) the new version keeps the canonical picture the
    environment already has, so no new picture is started for it.

    The profile fields the definition fills are overwritten (the name and the notes are not).
    If the environment already holds exactly this definition, built from the same inputs, no
    version is added and the pin moves to the newest one. The picture is started unless that
    version already has one; a picture that cannot be started is not an error here (the
    definition is the stage's result, and the workspace offers Retry picture). Raises
    EnvironmentDefinitionError when the link was removed, or moved to another environment,
    while the model was answering.
    """
    statement = select(ProjectEnvironmentLink).where(
        ProjectEnvironmentLink.project_id == project_id,
        ProjectEnvironmentLink.discovery_id == discovery_id,
    )
    link = (await session.execute(statement)).scalars().first()
    if link is None or link.environment_id != environment_id:
        raise EnvironmentDefinitionError(
            f"The link of '{discovery_id}' to the Character Lab changed while the definition "
            "was being written, so it was not saved."
        )
    environment = await session.get(LibraryEnvironment, environment_id)
    if environment is None:
        raise EnvironmentDefinitionError("The environment is no longer in the Character Lab.")

    profile = environment_definition_writer.to_profile(definition)
    for field in environment_definition_writer.PROFILE_FIELDS_WRITTEN:
        setattr(environment, field, profile[field])
    environment.definition = definition
    environment.updated_at = utcnow()

    version = await environment_versions.record_version_if_changed(
        session, environment, source="ai", job_id=job_id, inputs=inputs, keep_picture=keep_picture
    )
    if version is None:
        version = await environment_versions.latest_version(session, environment_id)
    assert version is not None  # an environment with a definition always has a version

    link.pinned_version = version.version
    # The new version carries this project's own `inputs`, so an adopted version's provenance
    # (PHASE-042) is no longer needed.
    link.provenance_version = None
    link.updated_at = utcnow()
    await session.flush()
    _logger.info(
        "job %d: environment %d defined as '%s' for project %d, pinned at version %d",
        job_id,
        environment_id,
        discovery_id,
        project_id,
        version.version,
    )

    if version.reference_image_id is None:
        try:
            await environment_references.start_reference(
                session,
                environment_id,
                pipeline=environment_references.PipelineAttempt(
                    project_id=project_id, discovery_id=discovery_id, version_id=version.id
                ),
                commit=False,
            )
        except environment_references.EnvironmentReferenceError as exc:
            _logger.warning(
                "job %d: the picture of environment %d version %d was not started: %s",
                job_id,
                environment_id,
                version.version,
                exc,
            )
    return version
