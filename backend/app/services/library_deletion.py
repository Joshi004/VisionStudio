"""Deleting a library character or environment (PHASE-055).

A library item is deleted for good: its row, everything that belongs to it (looks, versions,
takes, named looks, references, states, views, links and cast rows go with it through the
foreign keys' ON DELETE CASCADE) and the pictures, audio and clips only it used.

Projects that used the item are not changed, apart from one record each
(`project_missing_library_item`), written before the row goes. The record lets the project say
"this entry was deleted from the library" and ask the user to create it again or pick another,
instead of the pipeline quietly making a new one. Everything the project already made keeps its
files: the scenes, shots and takes only read as out of date, through the staleness rules
(`services/staleness.py`), because the entry is no longer linked.

Files: a picture (`lab_image`), a cut-out, a speech or a clip is deleted only when nothing else
still uses it. The check is deliberately cautious: anything that might still use a file keeps
it. The files are removed after the database commit, and a failure there is logged and never
raised, because the database is already consistent by then.

A library item is refused (`LibraryItemBusyError`) while work on it, or in a project that uses
it, is still running.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CharacterLook,
    CharacterLookCandidate,
    CharacterReference,
    CharacterTake,
    EnvironmentReference,
    EnvironmentReferenceCandidate,
    EnvironmentState,
    EnvironmentView,
    EnvironmentViewState,
    GenerationRequest,
    Job,
    LabImage,
    LabMusicRun,
    LabRun,
    LabVideoRun,
    LabVoiceRun,
    LibraryCharacter,
    LibraryCharacterVersion,
    LibraryEnvironment,
    LibraryEnvironmentVersion,
    Project,
    ProjectCastCharacter,
    ProjectCastEnvironment,
    ProjectCharacterLink,
    ProjectEnvironmentLink,
    ProjectMissingLibraryItem,
    ShotReferenceManifest,
    Voice,
)
from app.jobs import store
from app.services.storage import Storage, StorageError

_logger = logging.getLogger(__name__)

Kind = Literal["character", "environment"]
KINDS: Final[tuple[Kind, ...]] = ("character", "environment")


class LibraryDeletionError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


class LibraryItemNotFoundError(LibraryDeletionError):
    """There is no such library item."""


class LibraryItemBusyError(LibraryDeletionError):
    """Work on the item, or in a project that uses it, is still running."""


@dataclass(frozen=True)
class ProjectUse:
    """One project that uses the library item. `discovery_id` is the linked discovered entry,
    or None when the item is only in the project's cast.
    """

    project_id: int
    project_name: str
    discovery_id: str | None
    in_cast: bool


@dataclass(frozen=True)
class Preview:
    """What deleting a library item would affect, and why it cannot be done now, if so."""

    kind: Kind
    library_id: int
    name: str
    projects: list[ProjectUse]
    blocked_reason: str | None


@dataclass
class _Owned:
    """The runs, pictures and jobs that belong to the item, found before its row is deleted."""

    image_run_ids: set[int] = field(default_factory=set)
    # Result pictures the item points at directly (they may not come from a run it owns).
    image_ids: set[int] = field(default_factory=set)
    cutout_paths: set[str] = field(default_factory=set)
    voice_run_ids: set[int] = field(default_factory=set)
    video_run_ids: set[int] = field(default_factory=set)
    job_ids: set[int] = field(default_factory=set)


@dataclass
class _Found:
    """What the rows that stay still point at."""

    lab_images: set[int] = field(default_factory=set)
    voice_runs: set[int] = field(default_factory=set)
    cutouts: set[str] = field(default_factory=set)


def _check_kind(kind: str) -> Kind:
    if kind == "character":
        return "character"
    if kind == "environment":
        return "environment"
    raise LibraryDeletionError(f"Unknown kind '{kind}'.")


def _is_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _scan(value: Any, found: _Found) -> None:
    """Collects every picture id, voice-run id and cut-out path named anywhere in a JSON value.
    It reads more than it needs on purpose: a number that merely looks like a reference only
    makes a file stay.
    """
    if isinstance(value, dict):
        if _is_id(value.get("id")):
            if value.get("source") == "lab":
                found.lab_images.add(value["id"])
            elif value.get("source") == "voice_run":
                found.voice_runs.add(value["id"])
        for key, item in value.items():
            if isinstance(key, str):
                if key.endswith("image_id") and _is_id(item):
                    found.lab_images.add(item)
                elif key.endswith("image_ids") and isinstance(item, list):
                    found.lab_images.update(entry for entry in item if _is_id(entry))
                elif key == "cutout_path" and isinstance(item, str):
                    found.cutouts.add(item)
            _scan(item, found)
    elif isinstance(value, list):
        for item in value:
            _scan(item, found)


# --- Loading ---------------------------------------------------------------------------------


async def _load(
    session: AsyncSession, kind: Kind, library_id: int
) -> LibraryCharacter | LibraryEnvironment:
    item: LibraryCharacter | LibraryEnvironment | None
    if kind == "character":
        item = await session.get(LibraryCharacter, library_id)
    else:
        item = await session.get(LibraryEnvironment, library_id)
    if item is None:
        raise LibraryItemNotFoundError(f"There is no {kind} {library_id} in the library.")
    return item


async def _uses(session: AsyncSession, kind: Kind, library_id: int) -> list[ProjectUse]:
    """The projects that link the item or have it in their cast, oldest project first."""
    if kind == "character":
        link_rows = (
            await session.execute(
                select(
                    ProjectCharacterLink.project_id,
                    ProjectCharacterLink.discovery_id,
                    Project.name,
                )
                .join(Project, Project.id == ProjectCharacterLink.project_id)
                .where(ProjectCharacterLink.character_id == library_id)
            )
        ).all()
        cast_rows = (
            await session.execute(
                select(ProjectCastCharacter.project_id, Project.name)
                .join(Project, Project.id == ProjectCastCharacter.project_id)
                .where(ProjectCastCharacter.character_id == library_id)
            )
        ).all()
    else:
        link_rows = (
            await session.execute(
                select(
                    ProjectEnvironmentLink.project_id,
                    ProjectEnvironmentLink.discovery_id,
                    Project.name,
                )
                .join(Project, Project.id == ProjectEnvironmentLink.project_id)
                .where(ProjectEnvironmentLink.environment_id == library_id)
            )
        ).all()
        cast_rows = (
            await session.execute(
                select(ProjectCastEnvironment.project_id, Project.name)
                .join(Project, Project.id == ProjectCastEnvironment.project_id)
                .where(ProjectCastEnvironment.environment_id == library_id)
            )
        ).all()
    in_cast = {project_id for project_id, _name in cast_rows}
    uses: dict[int, ProjectUse] = {}
    for project_id, discovery_id, name in link_rows:
        uses[project_id] = ProjectUse(project_id, name, discovery_id, project_id in in_cast)
    for project_id, name in cast_rows:
        uses.setdefault(project_id, ProjectUse(project_id, name, None, True))
    return sorted(uses.values(), key=lambda use: use.project_id)


async def _ids(session: AsyncSession, column: Any, *conditions: Any) -> set[int]:
    """The non-NULL values of one integer column of the rows that match."""
    rows = await session.execute(select(column).where(*conditions))
    return {value for value in rows.scalars() if value is not None}


async def _owned_character(session: AsyncSession, character_id: int) -> _Owned:
    owned = _Owned()
    looks = (
        await session.execute(
            select(CharacterLook.id, CharacterLook.prompt_job_id).where(
                CharacterLook.character_id == character_id
            )
        )
    ).all()
    look_ids = {look_id for look_id, _job in looks}
    owned.job_ids |= {job_id for _id, job_id in looks if job_id is not None}
    if look_ids:
        owned.image_run_ids |= await _ids(
            session,
            CharacterLookCandidate.lab_run_id,
            CharacterLookCandidate.look_id.in_(look_ids),
        )
        owned.image_run_ids |= await _ids(
            session, CharacterReference.lab_run_id, CharacterReference.look_id.in_(look_ids)
        )
        owned.image_ids |= await _ids(
            session, CharacterReference.lab_image_id, CharacterReference.look_id.in_(look_ids)
        )
        paths = await session.execute(
            select(CharacterReference.cutout_path).where(
                CharacterReference.look_id.in_(look_ids),
                CharacterReference.cutout_path.is_not(None),
            )
        )
        owned.cutout_paths |= {path for path in paths.scalars() if path}
    take = CharacterTake.character_id == character_id
    owned.image_run_ids |= await _ids(session, CharacterTake.image_run_id, take)
    owned.image_run_ids |= await _ids(session, CharacterTake.last_frame_run_id, take)
    owned.voice_run_ids |= await _ids(session, CharacterTake.voice_run_id, take)
    owned.video_run_ids |= await _ids(session, CharacterTake.video_run_id, take)
    owned.job_ids |= await _ids(session, CharacterTake.prompt_job_id, take)
    return owned


async def _owned_environment(session: AsyncSession, environment_id: int) -> _Owned:
    owned = _Owned()
    references = (
        await session.execute(
            select(EnvironmentReference.id, EnvironmentReference.prompt_job_id).where(
                EnvironmentReference.environment_id == environment_id
            )
        )
    ).all()
    reference_ids = {reference_id for reference_id, _job in references}
    owned.job_ids |= {job_id for _id, job_id in references if job_id is not None}
    if reference_ids:
        owned.image_run_ids |= await _ids(
            session,
            EnvironmentReferenceCandidate.lab_run_id,
            EnvironmentReferenceCandidate.reference_id.in_(reference_ids),
        )
    owned.image_ids |= await _ids(
        session,
        LibraryEnvironmentVersion.reference_image_id,
        LibraryEnvironmentVersion.environment_id == environment_id,
    )
    state = EnvironmentState.environment_id == environment_id
    owned.image_run_ids |= await _ids(session, EnvironmentState.lab_run_id, state)
    owned.image_ids |= await _ids(session, EnvironmentState.reference_image_id, state)
    view = EnvironmentView.environment_id == environment_id
    owned.image_run_ids |= await _ids(session, EnvironmentView.lab_run_id, view)
    owned.image_ids |= await _ids(session, EnvironmentView.reference_image_id, view)
    owned.job_ids |= await _ids(session, EnvironmentView.prompt_job_id, view)
    view_ids = await _ids(session, EnvironmentView.id, view)
    if view_ids:
        view_state = EnvironmentViewState.view_id.in_(view_ids)
        owned.image_run_ids |= await _ids(session, EnvironmentViewState.lab_run_id, view_state)
        owned.image_ids |= await _ids(session, EnvironmentViewState.reference_image_id, view_state)
    return owned


# --- Checks ----------------------------------------------------------------------------------


async def _any_active(session: AsyncSession, job_ids: set[int]) -> bool:
    """Whether any of these jobs is queued or running."""
    active = await session.execute(
        select(Job.id).where(Job.id.in_(job_ids), Job.status.in_(store.ACTIVE_STATUSES)).limit(1)
    )
    return active.first() is not None


async def _busy_reason(
    session: AsyncSession, kind: Kind, library_id: int, owned: _Owned, uses: list[ProjectUse]
) -> str | None:
    """Why the item cannot be deleted now, or None.

    Only a job that is queued or running counts. A look's or a reference attempt's status is
    not enough: a look whose prompt job or angle pictures were cancelled, failed, or were
    interrupted by a restart keeps its `writing_prompt` or `making_angles` status, and a
    picture whose job failed or was cancelled keeps its `running` run.
    """
    job_ids = set(owned.job_ids)
    if owned.voice_run_ids:
        job_ids |= await _ids(session, LabVoiceRun.job_id, LabVoiceRun.id.in_(owned.voice_run_ids))
    if owned.video_run_ids:
        job_ids |= await _ids(session, LabVideoRun.job_id, LabVideoRun.id.in_(owned.video_run_ids))
    if job_ids and await _any_active(session, job_ids):
        return "Work on it is still running. Wait for it to finish, or cancel it, first."
    if owned.image_run_ids:
        picture_job_ids = await _ids(
            session,
            LabRun.job_id,
            LabRun.id.in_(owned.image_run_ids),
            LabRun.status == "running",
        )
        if picture_job_ids and await _any_active(session, picture_job_ids):
            return "A picture is being made right now. Wait for it to finish, then delete it."

    project_ids = {use.project_id for use in uses}
    if project_ids:
        names = {use.project_id: use.project_name for use in uses}
        active_project = await session.execute(
            select(Job.project_id)
            .where(Job.project_id.in_(project_ids), Job.status.in_(store.ACTIVE_STATUSES))
            .limit(1)
        )
        busy_project = active_project.scalars().first()
        if busy_project is not None:
            return (
                f"The project '{names[busy_project]}' uses it and has work running. "
                "Stop that work first."
            )
        if kind == "character":
            # A look of another character that waits for this one's picture (a younger self,
            # an older self) would never start.
            waiting = await session.execute(
                select(CharacterLook.project_id)
                .where(
                    CharacterLook.status == "waiting",
                    CharacterLook.project_id.in_(project_ids),
                    CharacterLook.character_id != library_id,
                )
                .limit(1)
            )
            waiting_project = waiting.scalars().first()
            if waiting_project is not None:
                return (
                    f"A character of the project '{names[waiting_project]}' is waiting for the "
                    "pictures of one of its characters. Let that finish first."
                )
    return None


async def _preview_of(
    session: AsyncSession, kind: Kind, library_id: int, ignore_project_id: int | None
) -> Preview:
    item = await _load(session, kind, library_id)
    uses = [
        use for use in await _uses(session, kind, library_id) if use.project_id != ignore_project_id
    ]
    if kind == "character":
        owned = await _owned_character(session, library_id)
    else:
        owned = await _owned_environment(session, library_id)
    reason = await _busy_reason(session, kind, library_id, owned, uses)
    return Preview(
        kind=kind,
        library_id=library_id,
        name=item.name,
        projects=uses,
        blocked_reason=reason,
    )


async def preview(
    session: AsyncSession, kind: str, library_id: int, *, ignore_project_id: int | None = None
) -> Preview:
    """What deleting the item would affect. Raises LibraryItemNotFoundError. A project that is
    being deleted too is passed as `ignore_project_id`: it is neither listed nor counted as
    busy.
    """
    return await _preview_of(session, _check_kind(kind), library_id, ignore_project_id)


async def ensure_deletable(
    session: AsyncSession, kind: str, library_id: int, *, ignore_project_id: int | None = None
) -> Preview:
    """Like `preview`, and raises LibraryItemBusyError when the item cannot be deleted now."""
    result = await _preview_of(session, _check_kind(kind), library_id, ignore_project_id)
    if result.blocked_reason is not None:
        raise LibraryItemBusyError(f"'{result.name}' cannot be deleted: {result.blocked_reason}")
    return result


# --- Deleting --------------------------------------------------------------------------------


async def _write_missing_records(
    session: AsyncSession, kind: Kind, library_id: int, name: str, uses: list[ProjectUse]
) -> None:
    for use in uses:
        # An older record of the same item (a library id can be reused) or of the same entry
        # would break a unique key.
        await session.execute(
            delete(ProjectMissingLibraryItem).where(
                ProjectMissingLibraryItem.project_id == use.project_id,
                ProjectMissingLibraryItem.kind == kind,
                ProjectMissingLibraryItem.library_id == library_id,
            )
        )
        if use.discovery_id is not None:
            await session.execute(
                delete(ProjectMissingLibraryItem).where(
                    ProjectMissingLibraryItem.project_id == use.project_id,
                    ProjectMissingLibraryItem.kind == kind,
                    ProjectMissingLibraryItem.discovery_id == use.discovery_id,
                )
            )
        session.add(
            ProjectMissingLibraryItem(
                project_id=use.project_id,
                kind=kind,
                library_id=library_id,
                discovery_id=use.discovery_id,
                name=name,
                in_cast=use.in_cast,
            )
        )
    await session.flush()


async def delete_item(session: AsyncSession, storage: Storage, kind: str, library_id: int) -> None:
    """Deletes the library item and the files only it used, and commits.

    Raises LibraryItemNotFoundError, or LibraryItemBusyError while work on it is running.
    """
    checked = _check_kind(kind)
    item = await _load(session, checked, library_id)
    uses = await _uses(session, checked, library_id)
    if checked == "character":
        owned = await _owned_character(session, library_id)
    else:
        owned = await _owned_environment(session, library_id)
    reason = await _busy_reason(session, checked, library_id, owned, uses)
    if reason is not None:
        raise LibraryItemBusyError(f"'{item.name}' cannot be deleted: {reason}")

    name = item.name
    await _write_missing_records(session, checked, library_id, name, uses)
    await session.delete(item)
    await session.commit()
    _logger.info("%s %d '%s' deleted; %d project(s) flagged", checked, library_id, name, len(uses))

    try:
        await _remove_owned_files(session, storage, owned)
    except Exception:
        # The database is already consistent: only some files stay behind.
        await session.rollback()
        _logger.exception("could not remove every file of %s %d", checked, library_id)


# --- Files -----------------------------------------------------------------------------------

# Where a picture is named inside another row's JSON.
_IMAGE_JSON_COLUMNS: Final[tuple[Any, ...]] = (
    LibraryCharacterVersion.look_references,
    LibraryCharacterVersion.named_looks,
    LibraryEnvironmentVersion.states,
    LibraryEnvironmentVersion.views,
    ShotReferenceManifest.content,
    GenerationRequest.content,
    CharacterTake.first_frame,
    CharacterTake.last_frame,
    CharacterTake.audio_input,
    EnvironmentState.inputs,
    EnvironmentView.inputs,
    EnvironmentViewState.inputs,
)

# Where a picture is named by a plain column.
_IMAGE_ID_COLUMNS: Final[tuple[Any, ...]] = (
    CharacterLook.reference_image_id,
    CharacterReference.lab_image_id,
    LibraryEnvironmentVersion.reference_image_id,
    EnvironmentState.reference_image_id,
    EnvironmentView.reference_image_id,
    EnvironmentViewState.reference_image_id,
)


async def _still_referenced(session: AsyncSession, owned: _Owned) -> _Found:
    """What the rows that stay still point at. Runs of the item itself do not count: they go
    with it.
    """
    found = _Found()
    for column in _IMAGE_JSON_COLUMNS:
        for value in (await session.execute(select(column))).scalars():
            _scan(value, found)
    for id_column in _IMAGE_ID_COLUMNS:
        rows = await session.execute(select(id_column).where(id_column.is_not(None)))
        found.lab_images.update(rows.scalars())

    other_runs = select(LabRun.reference_images).where(LabRun.id.not_in(owned.image_run_ids))
    for value in (await session.execute(other_runs)).scalars():
        _scan(value, found)
    other_videos = select(
        LabVideoRun.first_frame,
        LabVideoRun.last_frame,
        LabVideoRun.references,
        LabVideoRun.audio_input,
        LabVideoRun.audio_references,
    ).where(LabVideoRun.id.not_in(owned.video_run_ids))
    for row in (await session.execute(other_videos)).all():
        for value in row:
            _scan(value, found)
    return found


async def _path_in_use(session: AsyncSession, path: str) -> bool:
    """Whether any remaining row stores this file."""
    for column in (
        LabImage.path,
        Voice.path,
        LabVoiceRun.path,
        LabVideoRun.path,
        LabMusicRun.path,
        CharacterReference.cutout_path,
    ):
        found = await session.execute(select(exists().where(column == path)))
        if found.scalar():
            return True
    return False


async def _remove_owned_files(session: AsyncSession, storage: Storage, owned: _Owned) -> None:
    referenced = await _still_referenced(session, owned)
    paths: list[str] = []

    # Pictures: those of the item's runs and the ones it named, unless something else uses them.
    image_ids = set(owned.image_ids)
    if owned.image_run_ids:
        image_ids |= await _ids(session, LabImage.id, LabImage.run_id.in_(owned.image_run_ids))
    if image_ids:
        images = await session.execute(
            select(LabImage).where(LabImage.id.in_(image_ids), LabImage.origin == "result")
        )
        for image in images.scalars():
            if image.id not in referenced.lab_images:
                paths.append(image.path)
                await session.delete(image)
        await session.flush()
    # A run that kept a picture stays, as its history. One with none left goes.
    for run_id in owned.image_run_ids:
        kept = await session.execute(select(exists().where(LabImage.run_id == run_id)))
        if not kept.scalar():
            await session.execute(delete(LabRun).where(LabRun.id == run_id))

    paths.extend(owned.cutout_paths - referenced.cutouts)

    if owned.voice_run_ids:
        runs = await session.execute(
            select(LabVoiceRun).where(LabVoiceRun.id.in_(owned.voice_run_ids))
        )
        for run in runs.scalars():
            if run.id in referenced.voice_runs:
                continue
            saved = await session.execute(select(exists().where(Voice.lab_voice_run_id == run.id)))
            if saved.scalar():
                continue  # a saved voice shares this run's file
            if run.path:
                paths.append(run.path)
            await session.delete(run)
    if owned.video_run_ids:
        videos = await session.execute(
            select(LabVideoRun).where(LabVideoRun.id.in_(owned.video_run_ids))
        )
        for video in videos.scalars():
            if video.path:
                paths.append(video.path)
            await session.delete(video)
    await session.commit()

    for path in dict.fromkeys(paths):
        if await _path_in_use(session, path):
            continue
        try:
            await storage.delete_media(path)
        except (StorageError, OSError):
            _logger.warning("could not delete the file %s", path, exc_info=True)


async def remove_voice_runs(session: AsyncSession, storage: Storage, run_ids: set[int]) -> None:
    """Deletes speech samples of the Voice lab that were made for a project that is gone (a
    narrator or character voice sample), with their files. A sample that a saved voice shares
    stays. Commits. A failure is logged and never raised.
    """
    if not run_ids:
        return
    try:
        await _remove_owned_files(session, storage, _Owned(voice_run_ids=set(run_ids)))
    except Exception:
        await session.rollback()
        _logger.exception("could not remove the voice samples of a deleted project")
