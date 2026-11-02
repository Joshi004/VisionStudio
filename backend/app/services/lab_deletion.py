"""Deleting one sample of a lab: an image run, a video run, a speech, a piece of music, an
Audio video test or a Graphics run.

A sample is deleted for good, with its file, but only when nothing else uses it. Anything that
does (a character's look, a saved voice, a take, a project's music, another run that was started
from it) refuses the delete, and `preview` lists those places so the user can see why. A sample
whose job is still queued or running is refused too. Nothing else is changed: a sample is never
deleted "anyway" and left dangling in the places that used it.

Order, as in `services/library_deletion.py`: everything that could refuse is checked first, the
rows are deleted and committed, then the files that no remaining row stores are removed. A failure
while removing a file is logged and never raised, because the database is already consistent.

The jobs behind a sample stay in the Activity list. Their ids are read first when the user asks
for the GPU server to be cleaned too (`services/server_cleanup.py`).

A character take that made the sample (its picture, its last frame, its speech or its clip) is
not a place that uses it: the take goes with it, and `preview` says so. Except a take that is a
clip of an Audio video test (the test needs it), or a take whose clip would stay behind without it
(the clip is deleted first, which deletes the take). The other runs of a deleted take stay in
their labs.

An Audio video test is the exception to "nothing uses it": it owns its clips (the takes of its
parts and their video runs), its two rendered videos, its speech and the slices of it. These go
with it, except for a speech or a slice that a copy of the test still uses.

A Graphics run is the other exception (GFX-002). Its renders belong to it (they go with it, and
so does each render's video), and nothing else uses it. The speech and the saved voice it may name
belong to the Voice lab and stay.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AvLabSegment,
    AvLabTest,
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
    LabGraphicRender,
    LabGraphicRun,
    LabImage,
    LabMusicRun,
    LabMusicTrialCase,
    LabRun,
    LabVideoRun,
    LabVoiceRun,
    LibraryCharacter,
    LibraryCharacterVersion,
    LibraryEnvironment,
    LibraryEnvironmentVersion,
    MusicTake,
    MusicTheme,
    MusicThemeCandidate,
    MusicThemeVersion,
    Project,
    ShotReferenceManifest,
    Voice,
)
from app.jobs import store
from app.services import library_deletion, server_cleanup
from app.services.server_cleanup import PurgePlan
from app.services.storage import Storage, StorageError

_logger = logging.getLogger(__name__)

Kind = Literal["image_run", "video_run", "voice_run", "music_run", "av_test", "graphic_run"]
KINDS: Final[tuple[Kind, ...]] = (
    "image_run",
    "video_run",
    "voice_run",
    "music_run",
    "av_test",
    "graphic_run",
)

# An owner of a row that uses a sample: what it is (`character`, `environment`, `project`,
# `take`, `av_test` or `voice`) and its id.
Owner = tuple[str, int]

_SNIPPET_CHARS: Final = 60
_RUNNING_REASON: Final = "It is still being made. Wait for it to finish, or cancel it, first."
_IN_USE_REASON: Final = (
    "It is still used elsewhere. Remove it from the places listed, or delete them, first. The "
    "pictures of a character or an environment go when it is deleted."
)


class LabDeletionError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


class SampleNotFoundError(LabDeletionError):
    """There is no such sample."""


class SampleBlockedError(LabDeletionError):
    """The sample is still being made, or something still uses it."""


@dataclass(frozen=True)
class Preview:
    """What deleting a sample would do, and why it cannot be done now, if so."""

    kind: Kind
    sample_id: int
    label: str
    used_by: list[str]
    # What goes with it, by name: the character takes that made it.
    also_deletes: list[str]
    blocked_reason: str | None


@dataclass
class _Inspection:
    label: str
    used_by: list[str] = field(default_factory=list)
    # The jobs behind the sample: they must not be running, and they are what a server cleanup
    # purges.
    job_ids: set[int] = field(default_factory=set)
    running: bool = False
    # The character takes that made the sample, deleted with it, and their names.
    takes: list[CharacterTake] = field(default_factory=list)
    also_deletes: list[str] = field(default_factory=list)

    @property
    def blocked_reason(self) -> str | None:
        if self.running:
            return _RUNNING_REASON
        if self.used_by:
            return _IN_USE_REASON
        return None


def _check_kind(kind: str) -> Kind:
    for known in KINDS:
        if kind == known:
            return known
    raise LabDeletionError(f"Unknown kind '{kind}'.")


def _snippet(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= _SNIPPET_CHARS:
        return one_line
    return one_line[: _SNIPPET_CHARS - 3] + "..."


# --- Who owns a row that uses a sample -------------------------------------------------------


def _through(owner_column: Any, parent_key: Any, child_key: Any) -> Any:
    """The owner of a row that only reaches it through its parent row."""
    return select(owner_column).where(parent_key == child_key).scalar_subquery()


# For every table that can name a lab sample (the lists in `library_deletion` and the columns
# below): what kind of owner a row has, and the SQL that gives the owner's id.
_OWNERS: Final[dict[Any, tuple[str, Any]]] = {
    LibraryCharacterVersion: ("character", LibraryCharacterVersion.character_id),
    CharacterLook: ("character", CharacterLook.character_id),
    CharacterLookCandidate: (
        "character",
        _through(CharacterLook.character_id, CharacterLook.id, CharacterLookCandidate.look_id),
    ),
    CharacterReference: (
        "character",
        _through(CharacterLook.character_id, CharacterLook.id, CharacterReference.look_id),
    ),
    CharacterTake: ("take", CharacterTake.id),
    AvLabTest: ("av_test", AvLabTest.id),
    AvLabSegment: ("av_test", AvLabSegment.test_id),
    LibraryEnvironmentVersion: ("environment", LibraryEnvironmentVersion.environment_id),
    EnvironmentReferenceCandidate: (
        "environment",
        _through(
            EnvironmentReference.environment_id,
            EnvironmentReference.id,
            EnvironmentReferenceCandidate.reference_id,
        ),
    ),
    EnvironmentState: ("environment", EnvironmentState.environment_id),
    EnvironmentView: ("environment", EnvironmentView.environment_id),
    EnvironmentViewState: (
        "environment",
        _through(EnvironmentView.environment_id, EnvironmentView.id, EnvironmentViewState.view_id),
    ),
    ShotReferenceManifest: ("project", ShotReferenceManifest.project_id),
    GenerationRequest: ("project", GenerationRequest.project_id),
    MusicTake: ("project", MusicTake.project_id),
    MusicThemeCandidate: (
        "project",
        _through(MusicTheme.project_id, MusicTheme.id, MusicThemeCandidate.theme_row_id),
    ),
    MusicThemeVersion: (
        "project",
        _through(MusicTheme.project_id, MusicTheme.id, MusicThemeVersion.theme_row_id),
    ),
    Voice: ("voice", Voice.id),
    LabVoiceRun: ("project", LabVoiceRun.project_id),
}


async def _owners_of(session: AsyncSession, column: Any, condition: Any) -> set[Owner]:
    """The owners of the rows of `column`'s table that match `condition`."""
    model = column.class_
    kind, owner_id = _OWNERS[model]
    rows = await session.execute(select(owner_id).select_from(model).where(condition))
    return {(kind, owner) for owner in rows.scalars() if owner is not None}


async def _owners_of_json(
    session: AsyncSession, column: Any, attribute: str, wanted: set[int]
) -> set[Owner]:
    """The owners of the rows whose JSON `column` names one of `wanted`. `attribute` is what
    to read from the scan: `lab_images` or `voice_runs`.
    """
    model = column.class_
    kind, owner_id = _OWNERS[model]
    rows = await session.execute(select(column, owner_id).select_from(model))
    owners: set[Owner] = set()
    for value, owner in rows.all():
        if owner is None:
            continue
        found = library_deletion.References()
        library_deletion.scan_references(value, found)
        if getattr(found, attribute) & wanted:
            owners.add((kind, owner))
    return owners


async def _runs_using(
    session: AsyncSession,
    id_column: Any,
    json_columns: Iterable[Any],
    attribute: str,
    wanted: set[int],
    *,
    skip_id: int | None = None,
) -> list[int]:
    """The ids of the lab runs whose JSON columns name one of `wanted`."""
    rows = await session.execute(select(id_column, *json_columns).order_by(id_column))
    ids: list[int] = []
    for row_id, *values in rows.all():
        if row_id == skip_id:
            continue
        found = library_deletion.References()
        for value in values:
            library_deletion.scan_references(value, found)
        if getattr(found, attribute) & wanted:
            ids.append(row_id)
    return ids


async def _name(session: AsyncSession, kind: str, owner_id: int) -> str:
    if kind == "character":
        character = await session.get(LibraryCharacter, owner_id)
        return f"Character '{character.name}'" if character else f"Character {owner_id}"
    if kind == "environment":
        environment = await session.get(LibraryEnvironment, owner_id)
        return f"Environment '{environment.name}'" if environment else f"Environment {owner_id}"
    if kind == "project":
        project = await session.get(Project, owner_id)
        return f"Project '{project.name}'" if project else f"Project {owner_id}"
    if kind == "voice":
        voice = await session.get(Voice, owner_id)
        return f"Saved voice '{voice.name}'" if voice else f"Saved voice {owner_id}"
    if kind == "take":
        # The clips of an Audio video test are takes the Character lab does not list.
        found = await session.execute(
            select(AvLabSegment.test_id).where(AvLabSegment.take_id == owner_id)
        )
        test_id = found.scalars().first()
        if test_id is not None:
            return f"Audio-video test {test_id}"
        take = await session.get(CharacterTake, owner_id)
        owner = await session.get(LibraryCharacter, take.character_id) if take else None
        return f"A take of character '{owner.name}'" if owner else f"Character take {owner_id}"
    return f"Audio-video test {owner_id}"


async def _names(session: AsyncSession, owners: set[Owner]) -> list[str]:
    names = {await _name(session, kind, owner_id) for kind, owner_id in owners}
    return sorted(names)


async def _ids(session: AsyncSession, column: Any, *conditions: Any) -> set[int]:
    """The non-NULL values of one integer column of the rows that match."""
    rows = await session.execute(select(column).where(*conditions))
    return {value for value in rows.scalars() if value is not None}


async def _any_active(session: AsyncSession, job_ids: set[int]) -> bool:
    """Whether any of these jobs is queued or running."""
    if not job_ids:
        return False
    active = await session.execute(
        select(Job.id).where(Job.id.in_(job_ids), Job.status.in_(store.ACTIVE_STATUSES)).limit(1)
    )
    return active.first() is not None


# --- The character takes that made a sample --------------------------------------------------


@dataclass
class _MakerTakes:
    """The character takes that made a sample, sorted into those that go with it and those that
    keep it from being deleted.
    """

    takes: list[CharacterTake] = field(default_factory=list)
    also_deletes: list[str] = field(default_factory=list)
    used_by: list[str] = field(default_factory=list)
    # The jobs of every step of these takes: while one is running, nothing is deleted.
    job_ids: set[int] = field(default_factory=set)


async def _take_job_ids(session: AsyncSession, take: CharacterTake) -> set[int]:
    job_ids = {take.prompt_job_id} if take.prompt_job_id is not None else set()
    steps: tuple[tuple[Any, int | None], ...] = (
        (LabRun, take.image_run_id),
        (LabRun, take.last_frame_run_id),
        (LabVoiceRun, take.voice_run_id),
        (LabVideoRun, take.video_run_id),
    )
    for model, run_id in steps:
        if run_id is not None:
            job_ids |= await _ids(session, model.job_id, model.id == run_id)
    return job_ids


async def _maker_takes(session: AsyncSession, condition: Any, *, is_clip: bool) -> _MakerTakes:
    """The takes that match `condition` (the takes that made the sample). `is_clip`: the sample
    is the take's clip, so no clip of the take is left behind when the take goes.
    """
    rows = await session.execute(select(CharacterTake).where(condition).order_by(CharacterTake.id))
    found = _MakerTakes()
    for take in rows.scalars():
        found.job_ids |= await _take_job_ids(session, take)
        test_ids = await _ids(session, AvLabSegment.test_id, AvLabSegment.take_id == take.id)
        if test_ids:
            found.used_by += [f"Audio-video test {test_id}" for test_id in sorted(test_ids)]
        elif not is_clip and take.video_run_id is not None:
            found.used_by.append(f"Video lab run {take.video_run_id}")
        else:
            character = await session.get(LibraryCharacter, take.character_id)
            owner = f"'{character.name}'" if character else str(take.character_id)
            words = take.dialogue or take.action or take.output
            found.takes.append(take)
            found.also_deletes.append(f"The take of character {owner}: {_snippet(words)}")
    return found


def _unique(names: list[str]) -> list[str]:
    return list(dict.fromkeys(names))


# --- Looking at a sample ---------------------------------------------------------------------

# The columns that name an image run itself (the columns that name its pictures are
# `library_deletion.IMAGE_ID_COLUMNS` and `IMAGE_JSON_COLUMNS`). A take that made the run is not
# here: it goes with the run (`_maker_takes`).
_IMAGE_RUN_COLUMNS: Final[tuple[Any, ...]] = (
    CharacterLookCandidate.lab_run_id,
    CharacterReference.lab_run_id,
    EnvironmentReferenceCandidate.lab_run_id,
    EnvironmentState.lab_run_id,
    EnvironmentView.lab_run_id,
    EnvironmentViewState.lab_run_id,
)


async def _inspect_image_run(session: AsyncSession, run_id: int) -> _Inspection:
    run = await session.get(LabRun, run_id)
    if run is None:
        raise SampleNotFoundError(f"There is no image run {run_id}.")
    image_ids = await _ids(session, LabImage.id, LabImage.run_id == run_id)

    owners: set[Owner] = set()
    for column in _IMAGE_RUN_COLUMNS:
        owners |= await _owners_of(session, column, column == run_id)
    if image_ids:
        for column in library_deletion.IMAGE_ID_COLUMNS:
            owners |= await _owners_of(session, column, column.in_(image_ids))
        for column in library_deletion.IMAGE_JSON_COLUMNS:
            owners |= await _owners_of_json(session, column, "lab_images", image_ids)
    used_by = await _names(session, owners)

    if image_ids:
        image_runs = await _runs_using(
            session, LabRun.id, (LabRun.reference_images,), "lab_images", image_ids, skip_id=run_id
        )
        used_by += [f"Image lab run {other}" for other in image_runs]
        video_runs = await _runs_using(
            session,
            LabVideoRun.id,
            (LabVideoRun.first_frame, LabVideoRun.last_frame, LabVideoRun.references),
            "lab_images",
            image_ids,
        )
        used_by += [f"Video lab run {other}" for other in video_runs]

    makers = await _maker_takes(
        session,
        or_(CharacterTake.image_run_id == run_id, CharacterTake.last_frame_run_id == run_id),
        is_clip=False,
    )
    job_ids = {run.job_id} if run.job_id is not None else set()
    return _Inspection(
        label=f"Image run {run.id}: {_snippet(run.prompt)}",
        used_by=_unique(used_by + makers.used_by),
        job_ids=job_ids,
        running=await _any_active(session, job_ids | makers.job_ids),
        takes=makers.takes,
        also_deletes=makers.also_deletes,
    )


async def _inspect_video_run(session: AsyncSession, run_id: int) -> _Inspection:
    run = await session.get(LabVideoRun, run_id)
    if run is None:
        raise SampleNotFoundError(f"There is no video run {run_id}.")
    makers = await _maker_takes(session, CharacterTake.video_run_id == run_id, is_clip=True)
    job_ids = {run.job_id} if run.job_id is not None else set()
    return _Inspection(
        label=f"Video run {run.id}: {_snippet(run.prompt)}",
        used_by=makers.used_by,
        job_ids=job_ids,
        running=await _any_active(session, job_ids | makers.job_ids),
        takes=makers.takes,
        also_deletes=makers.also_deletes,
    )


async def _voice_run_uses(session: AsyncSession, run_id: int) -> list[str]:
    """Where a speech is used. A saved voice shares the speech's file, so it counts. A take
    that made the speech is not counted here (`_maker_takes`).
    """
    owners: set[Owner] = set()
    owners |= await _owners_of(session, Voice.lab_voice_run_id, Voice.lab_voice_run_id == run_id)
    owners |= await _owners_of(session, AvLabTest.voice_run_id, AvLabTest.voice_run_id == run_id)
    owners |= await _owners_of(
        session, AvLabSegment.slice_run_id, AvLabSegment.slice_run_id == run_id
    )
    owners |= await _owners_of_json(session, CharacterTake.audio_input, "voice_runs", {run_id})
    owners |= await _owners_of(session, LabVoiceRun.project_id, LabVoiceRun.id == run_id)
    used_by = await _names(session, owners)

    video_runs = await _runs_using(
        session,
        LabVideoRun.id,
        (LabVideoRun.audio_input, LabVideoRun.audio_references),
        "voice_runs",
        {run_id},
    )
    return used_by + [f"Video lab run {other}" for other in video_runs]


async def _inspect_voice_run(session: AsyncSession, run_id: int) -> _Inspection:
    run = await session.get(LabVoiceRun, run_id)
    if run is None:
        raise SampleNotFoundError(f"There is no speech {run_id}.")
    used_by = await _voice_run_uses(session, run_id)
    makers = await _maker_takes(session, CharacterTake.voice_run_id == run_id, is_clip=False)
    job_ids = {run.job_id} if run.job_id is not None else set()
    return _Inspection(
        label=f"Speech {run.id}: {_snippet(run.text)}",
        used_by=_unique(used_by + makers.used_by),
        job_ids=job_ids,
        running=await _any_active(session, job_ids | makers.job_ids),
        takes=makers.takes,
        also_deletes=makers.also_deletes,
    )


async def _inspect_music_run(session: AsyncSession, run_id: int) -> _Inspection:
    run = await session.get(LabMusicRun, run_id)
    if run is None:
        raise SampleNotFoundError(f"There is no music run {run_id}.")

    owners: set[Owner] = set()
    for column in (
        MusicTake.lab_run_id,
        MusicThemeCandidate.lab_run_id,
        MusicThemeVersion.lab_run_id,
    ):
        owners |= await _owners_of(session, column, column == run_id)
    used_by = await _names(session, owners)

    cases = await session.execute(select(LabMusicTrialCase.title, LabMusicTrialCase.run_ids))
    for title, case_run_ids in cases.all():
        if isinstance(case_run_ids, list) and run_id in case_run_ids:
            used_by.append(f"Music trial case '{title}'")
    # A run made by editing this one points at it, and its row cannot lose that pointer.
    edits = await _ids(session, LabMusicRun.id, LabMusicRun.source_run_id == run_id)
    used_by += [f"Music lab run {other} (an edit of it)" for other in sorted(edits)]

    job_ids = {job for job in (run.job_id, run.prompt_job_id) if job is not None}
    return _Inspection(
        label=f"Music run {run.id}: {run.kind}, {run.model}",
        used_by=used_by,
        job_ids=job_ids,
        running=await _any_active(session, job_ids),
    )


@dataclass
class _AvParts:
    """What an Audio video test owns."""

    segments: list[AvLabSegment]
    takes: list[CharacterTake]
    video_run_ids: set[int]
    slice_run_ids: set[int]


async def _av_parts(session: AsyncSession, test: AvLabTest) -> _AvParts:
    segment_rows = await session.execute(
        select(AvLabSegment).where(AvLabSegment.test_id == test.id)
    )
    segments = list(segment_rows.scalars())
    take_ids = {segment.take_id for segment in segments if segment.take_id is not None}
    takes: list[CharacterTake] = []
    if take_ids:
        take_rows = await session.execute(
            select(CharacterTake).where(CharacterTake.id.in_(take_ids))
        )
        takes = list(take_rows.scalars())
    return _AvParts(
        segments=segments,
        takes=takes,
        video_run_ids={take.video_run_id for take in takes if take.video_run_id is not None},
        slice_run_ids={
            segment.slice_run_id for segment in segments if segment.slice_run_id is not None
        },
    )


async def _inspect_av_test(session: AsyncSession, test_id: int) -> _Inspection:
    test = await session.get(AvLabTest, test_id)
    if test is None:
        raise SampleNotFoundError(f"There is no audio-video test {test_id}.")
    parts = await _av_parts(session, test)
    job_ids = {job for job in (test.timing_job_id, test.render_job_id) if job is not None}
    if test.voice_run_id is not None:
        job_ids |= await _ids(session, LabVoiceRun.job_id, LabVoiceRun.id == test.voice_run_id)
    if parts.video_run_ids:
        job_ids |= await _ids(session, LabVideoRun.job_id, LabVideoRun.id.in_(parts.video_run_ids))
    job_ids |= {take.prompt_job_id for take in parts.takes if take.prompt_job_id is not None}
    return _Inspection(
        label=f"Audio-video test {test.id}: {_snippet(test.text)}",
        job_ids=job_ids,
        running=await _any_active(session, job_ids),
    )


async def _inspect_graphic_run(session: AsyncSession, run_id: int) -> _Inspection:
    run = await session.get(LabGraphicRun, run_id)
    if run is None:
        raise SampleNotFoundError(f"There is no Graphics run {run_id}.")
    renders = await session.execute(
        select(LabGraphicRender).where(LabGraphicRender.run_id == run_id)
    )
    job_ids = {run.brief_job_id, run.timing_job_id}
    for render in renders.scalars():
        job_ids |= {render.input_job_id, render.render_job_id}
    job_ids.discard(None)
    return _Inspection(
        label=f"Graphics run {run.id}: {_snippet(run.line_text)}",
        job_ids=job_ids,
        running=await _any_active(session, job_ids),
    )


async def _inspect(session: AsyncSession, kind: Kind, sample_id: int) -> _Inspection:
    if kind == "image_run":
        return await _inspect_image_run(session, sample_id)
    if kind == "video_run":
        return await _inspect_video_run(session, sample_id)
    if kind == "voice_run":
        return await _inspect_voice_run(session, sample_id)
    if kind == "music_run":
        return await _inspect_music_run(session, sample_id)
    if kind == "graphic_run":
        return await _inspect_graphic_run(session, sample_id)
    return await _inspect_av_test(session, sample_id)


async def preview(session: AsyncSession, kind: str, sample_id: int) -> Preview:
    """What deleting the sample would do. Raises SampleNotFoundError."""
    checked = _check_kind(kind)
    found = await _inspect(session, checked, sample_id)
    return Preview(
        kind=checked,
        sample_id=sample_id,
        label=found.label,
        used_by=found.used_by,
        also_deletes=found.also_deletes,
        blocked_reason=found.blocked_reason,
    )


# --- Deleting --------------------------------------------------------------------------------
# Each function deletes the rows (the caller commits) and returns the files they stored.


async def _remove_image_run(session: AsyncSession, run_id: int) -> list[str]:
    paths: list[str] = []
    images = await session.execute(select(LabImage).where(LabImage.run_id == run_id))
    for image in images.scalars():
        paths.append(image.path)
        await session.delete(image)
    await session.flush()
    run = await session.get(LabRun, run_id)
    if run is not None:
        await session.delete(run)
    return paths


async def _remove_video_run(session: AsyncSession, run_id: int) -> list[str]:
    run = await session.get(LabVideoRun, run_id)
    if run is None:
        return []
    await session.delete(run)
    return [run.path] if run.path else []


async def _remove_voice_run(session: AsyncSession, run_id: int) -> list[str]:
    run = await session.get(LabVoiceRun, run_id)
    if run is None:
        return []
    await session.delete(run)
    return [run.path] if run.path else []


async def _remove_music_run(session: AsyncSession, run_id: int) -> list[str]:
    run = await session.get(LabMusicRun, run_id)
    if run is None:
        return []
    await session.delete(run)
    return [run.path] if run.path else []


async def _remove_graphic_run(session: AsyncSession, run_id: int) -> list[str]:
    """Deletes the run and its renders, and returns the videos they stored."""
    run = await session.get(LabGraphicRun, run_id)
    if run is None:
        return []
    renders = await session.execute(
        select(LabGraphicRender).where(LabGraphicRender.run_id == run_id)
    )
    paths: list[str] = []
    for render in renders.scalars():
        if render.media_path:
            paths.append(render.media_path)
        await session.delete(render)
    await session.flush()
    await session.delete(run)
    return paths


async def _remove_av_test(session: AsyncSession, test_id: int) -> list[str]:
    test = await session.get(AvLabTest, test_id)
    if test is None:
        return []
    parts = await _av_parts(session, test)
    paths = [path for path in (test.mixed_path, test.tts_path) if path]
    speech_id = test.voice_run_id

    for segment in parts.segments:
        await session.delete(segment)
    for take in parts.takes:
        await session.delete(take)
    await session.delete(test)
    for video_id in parts.video_run_ids:
        paths += await _remove_video_run(session, video_id)
    await session.flush()

    # A copy of the test shares the speech and the slices, so one that is still used stays.
    speech_ids = set(parts.slice_run_ids)
    if speech_id is not None:
        speech_ids.add(speech_id)
    for run_id in sorted(speech_ids):
        used = await _voice_run_uses(session, run_id)
        made_by_takes = await _ids(session, CharacterTake.id, CharacterTake.voice_run_id == run_id)
        if not used and not made_by_takes:
            paths += await _remove_voice_run(session, run_id)
    return paths


async def _remove_rows(session: AsyncSession, kind: Kind, sample_id: int) -> list[str]:
    if kind == "image_run":
        return await _remove_image_run(session, sample_id)
    if kind == "video_run":
        return await _remove_video_run(session, sample_id)
    if kind == "voice_run":
        return await _remove_voice_run(session, sample_id)
    if kind == "music_run":
        return await _remove_music_run(session, sample_id)
    if kind == "graphic_run":
        return await _remove_graphic_run(session, sample_id)
    return await _remove_av_test(session, sample_id)


async def _remove_files(session: AsyncSession, storage: Storage, paths: list[str]) -> None:
    for path in dict.fromkeys(paths):
        if await library_deletion.path_in_use(session, path):
            continue
        try:
            await storage.delete_media(path)
        except (StorageError, OSError):
            _logger.warning("could not delete the file %s", path, exc_info=True)


async def delete(
    session: AsyncSession,
    storage: Storage,
    kind: str,
    sample_id: int,
    *,
    purge_server: bool = False,
) -> PurgePlan | None:
    """Deletes the sample and the files only it used, and commits.

    Raises SampleNotFoundError, or SampleBlockedError while it is being made or used. With
    `purge_server` it returns what to purge on the GPU server afterwards
    (`server_cleanup.purge`), read before the rows are gone; otherwise None.
    """
    checked = _check_kind(kind)
    found = await _inspect(session, checked, sample_id)
    if found.blocked_reason is not None:
        places = f" Used by: {'; '.join(found.used_by)}." if found.used_by else ""
        raise SampleBlockedError(f"{found.label} cannot be deleted: {found.blocked_reason}{places}")

    plan = await server_cleanup.make_plan(session, found.job_ids) if purge_server else None
    for take in found.takes:
        await session.delete(take)
    await session.flush()
    paths = await _remove_rows(session, checked, sample_id)
    await session.commit()
    _logger.info("%s %d deleted, with %d take(s)", checked, sample_id, len(found.takes))

    try:
        await _remove_files(session, storage, paths)
    except Exception:
        # The database is already consistent: only some files stay behind.
        await session.rollback()
        _logger.exception("could not remove every file of %s %d", checked, sample_id)
    return plan
