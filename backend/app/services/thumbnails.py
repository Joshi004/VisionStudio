"""The thumbnails of a project: making one picture from each concept the owner approves, drawing
the headline on it, and choosing one.

The concepts are `services/thumbnail_concepts.py`. This module takes one concept of one version
and:

1. builds the picture's prompt in code from the concept's fields (`image_prompt`), so what the
   model decided (who appears, where the headline goes) is what the picture is asked for;
2. starts one Image lab run per concept: text to image when nobody appears, Qwen-Image-2.1's
   edit endpoint when people do, with each person's look picture as a reference ("image 1" in
   the prompt is the first person);
3. when the picture is stored (`on_thumbnail_image_stored`, called by `jobs/generate_lab_image`),
   draws the headline on it (`services/thumbnail_compose.py`) and stores the finished PNG under
   the project's media folder.

Changing the headline later draws the same picture again with no GPU work. At most one thumbnail
of a project is chosen. Whether a thumbnail is out of date is worked out on read from its
concept version; nothing is stored and nothing is deleted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, LabImage, LabRun, Project, Thumbnail
from app.db.session import SessionLocal
from app.db.state_memo import memoized_state
from app.services import (
    graphic_theme,
    image_lab,
    image_models,
    story_bible,
    thumbnail_compose,
    thumbnail_concepts,
)
from app.services import thumbnail_concept_writer as writer
from app.services.image_lab import LabInputError, QwenEditForm, QwenLabForm, Ref
from app.services.image_models import IMAGE_MODE_KEY
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

# How a text area is said to the image model.
_AREA_WORDS: Final[dict[str, str]] = {
    "left": "left half",
    "right": "right half",
    "top": "top third",
    "bottom": "bottom third",
    "top_left": "top left corner area",
    "top_right": "top right corner area",
    "bottom_left": "bottom left corner area",
    "bottom_right": "bottom right corner area",
}

NO_VERSION_MESSAGE: Final = "There is no such version of the thumbnail ideas."
NO_CONCEPT_MESSAGE: Final = "Choose at least one idea to make a picture of."
NO_THUMBNAIL_MESSAGE: Final = "There is no such thumbnail."
NOT_READY_MESSAGE: Final = "This thumbnail has no picture yet."

# The key on a picture's `lab_image` job input that asks for the picture to be chosen once it is
# ready (the YouTube draft, YT-003): `{"chosen_before": id or None}`, the thumbnail that was the
# chosen one when the draft was asked for. It is chosen only if that is still the chosen one.
CHOOSE_WHEN_READY_KEY: Final = "choose_when_ready"


class ThumbnailError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- The picture's prompt ------------------------------------------------------------------


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def image_prompt(
    concept: dict[str, Any], people: list[tuple[str, dict[str, str]]], shape: str
) -> str:
    """The prompt of one concept's picture. `people` is each person who appears, as
    `(name, {expression, pose, ...})`, in the order of the references (the first person is
    image 1). With no people the prompt is for text to image. `shape` is the picture's shape,
    for example `16:9`.
    """
    area = _AREA_WORDS.get(str(concept["text_area"]), "one side")
    parts = [f"A bold, eye-catching video thumbnail picture, {shape} shape."]
    for number, (name, look) in enumerate(people, start=1):
        expression = _sentence(f"{name} has this expression: {look['expression']}")
        pose = _sentence(f"{name} is posed like this: {look['pose']}")
        parts.append(
            f"Image {number} shows {name}. Draw {name} in the new picture with exactly the face, "
            f"hair, skin and clothes of image {number}, and do not copy the plain backdrop of "
            f"image {number}. {expression} {pose}"
        )
    parts.append(_sentence(f"The idea: {concept['idea']}"))
    parts.append(_sentence(f"Composition: {concept['composition']}"))
    parts.append(_sentence(f"Background: {concept['background']}"))
    parts.append(_sentence(f"Mood and colours: {concept['mood']}"))
    parts.append(
        f"Keep the {area} of the picture empty, plain and calm, with nothing important in it, "
        "because a headline is added there later. Sharp focus, strong contrast, clear and easy "
        "to read when small. There is no text, letter, word, number, logo, caption or watermark "
        "anywhere in the picture."
    )
    return " ".join(parts)


# --- Making the pictures -------------------------------------------------------------------


def _concept_at(concepts_row: Any, index: int) -> dict[str, Any]:
    concepts = concepts_row.content["concepts"]
    return dict(concepts[index])


async def _start_one(
    session: AsyncSession,
    project: Project,
    version: int,
    index: int,
    concept: dict[str, Any],
    options: dict[str, thumbnail_concepts.CastOption],
    mode: image_models.ImageMode,
    choose_when_ready: dict[str, Any] | None = None,
) -> Thumbnail:
    """Starts the Image lab run of one concept and adds its `thumbnails` row. Flushes only.
    `choose_when_ready` is written on the picture's job (see `on_thumbnail_image_stored`).
    """
    shape = image_models.pick_aspect_ratio(*thumbnail_compose.size_for(project.orientation))
    people: list[tuple[str, dict[str, str]]] = []
    references: list[Ref] = []
    for person in concept["people"]:
        option = options.get(person["id"])
        look = option.look(person["look"]) if option is not None else None
        if option is None or look is None:
            raise ThumbnailError(
                f"Idea {index + 1}: {person['id']} with the look '{person['look']}' has no "
                "picture any more. Change the idea first."
            )
        people.append((option.name, person))
        references.append(Ref(source="lab", id=look.image_id))
    prompt = image_prompt(concept, people, shape)
    try:
        if references:
            run, job = await image_lab.create_qwen_edit_run(
                session,
                QwenEditForm(
                    prompt=prompt,
                    mode=mode,
                    aspect_ratio=shape,
                    seed=None,
                    steps=None,
                    references=references,
                ),
                commit=False,
            )
        else:
            run, job = await image_lab.create_qwen_run(
                session,
                QwenLabForm(prompt=prompt, mode=mode, aspect_ratio=shape, seed=None, steps=None),
                commit=False,
            )
    except LabInputError as exc:
        raise ThumbnailError(f"Idea {index + 1}: {exc}") from exc
    if choose_when_ready is not None:
        # The job has not run yet, and nothing rewrites its input afterwards.
        job.input = {
            **(job.input if isinstance(job.input, dict) else {}),
            CHOOSE_WHEN_READY_KEY: choose_when_ready,
        }
    row = Thumbnail(
        project_id=project.id,
        concept_version=version,
        concept_index=index,
        lab_run_id=run.id,
        headline=str(concept["headline"]),
        text_area=str(concept["text_area"]),
    )
    session.add(row)
    await session.flush()
    return row


async def start_images(
    session: AsyncSession,
    project: Project,
    concept_version: int,
    indexes: list[int],
    *,
    choose_when_ready: dict[str, Any] | None = None,
) -> list[Thumbnail]:
    """Starts one picture for each chosen concept of a version, and commits. Everything is
    checked before any run is made, and a failure undoes all of them. The caller nudges the
    dispatcher. `choose_when_ready` is written on each picture's job. Raises ThumbnailError.
    """
    chosen = sorted(set(indexes))
    if not chosen:
        raise ThumbnailError(NO_CONCEPT_MESSAGE)
    row = await thumbnail_concepts.get_version(session, project.id, concept_version)
    if row is None:
        raise ThumbnailError(NO_VERSION_MESSAGE)
    count = len(row.content["concepts"])
    if chosen[0] < 0 or chosen[-1] >= count:
        raise ThumbnailError(f"The ideas are numbered from 1 to {count}.")
    options = {
        option.id: option for option in await thumbnail_concepts.cast_options(session, project)
    }
    mode = image_models.resolve_mode(await settings_service.get_str(session, IMAGE_MODE_KEY))
    started: list[Thumbnail] = []
    try:
        for index in chosen:
            started.append(
                await _start_one(
                    session,
                    project,
                    concept_version,
                    index,
                    _concept_at(row, index),
                    options,
                    mode,
                    choose_when_ready,
                )
            )
    except ThumbnailError:
        await session.rollback()
        raise
    await session.commit()
    _logger.info(
        "project %d: %d thumbnail pictures started from ideas version %d",
        project.id,
        len(started),
        concept_version,
    )
    return started


async def chosen_id(session: AsyncSession, project_id: int) -> int | None:
    """The id of the project's chosen thumbnail, or None when none is chosen."""
    statement = (
        select(Thumbnail.id)
        .where(Thumbnail.project_id == project_id, Thumbnail.chosen.is_(True))
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def start_follow_up_picture(
    project_id: int, concept_version: int, then_picture: dict[str, Any]
) -> bool:
    """Called (best effort) by the job that wrote thumbnail concepts for a YouTube draft, once
    the concepts are stored: starts the picture of the first concept, to be chosen when it is
    ready. Does nothing (False) when the chosen thumbnail is no longer the one that was chosen
    when the draft was asked for, because the owner has chosen one since. The caller nudges the
    dispatcher when this returns True.
    """
    before = then_picture.get("chosen_before")
    async with SessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None or await chosen_id(session, project_id) != before:
            await session.commit()
            return False
        try:
            await start_images(
                session,
                project,
                concept_version,
                [0],
                choose_when_ready={"chosen_before": before},
            )
        except ThumbnailError as exc:
            _logger.warning(
                "project %d: the thumbnail picture was not started: %s", project_id, exc
            )
            return False
    return True


# --- Drawing the headline ------------------------------------------------------------------


async def _accent(session: AsyncSession, project_id: int) -> str | None:
    """The accent colour of the project's graphics look, or None when it has none."""
    theme = await graphic_theme.latest(session, project_id)
    content = theme.content if theme is not None else None
    inner = content.get("theme") if isinstance(content, dict) else None
    accent = inner.get("accent") if isinstance(inner, dict) else None
    return thumbnail_compose.valid_accent(accent)


async def _draw(session: AsyncSession, row: Thumbnail, project: Project) -> str | None:
    """Draws the headline on the row's picture and stores the result as the row's finished
    PNG. Returns the path of the PNG it replaced (to delete after the commit), or None. Does
    not commit. Raises ThumbnailError.
    """
    image = (
        await session.get(LabImage, row.background_image_id)
        if row.background_image_id is not None
        else None
    )
    if image is None:
        raise ThumbnailError(NOT_READY_MESSAGE)
    storage = get_storage()
    width, height = thumbnail_compose.size_for(project.orientation)
    temp = storage.new_temp_path("png")
    try:
        await thumbnail_compose.compose(
            storage.get_path(image.path),
            temp,
            width=width,
            height=height,
            headline=row.headline,
            text_area=row.text_area,
            accent=await _accent(session, project.id),
        )
        stored = await storage.save(await storage.describe_temp(temp), project.id, "png")
    except (thumbnail_compose.ThumbnailPictureError, StorageError) as exc:
        storage.discard(temp)
        raise ThumbnailError(f"The thumbnail could not be drawn: {exc}") from exc
    replaced = row.path
    row.path = stored.relative_path
    row.width = width
    row.height = height
    return replaced


async def _delete_file(relative_path: str | None) -> None:
    """Removes a replaced PNG of ours. Best effort: a file that is left behind does no harm."""
    if relative_path is None:
        return
    try:
        await get_storage().delete_media(relative_path)
    except StorageError:
        _logger.warning("a replaced thumbnail file could not be removed: %s", relative_path)


async def on_thumbnail_image_stored(run_id: int) -> bool:
    """Called (best effort) once a `lab_image` job has stored its picture. When the picture is
    the one a thumbnail was waiting for, it becomes the thumbnail's picture and the headline is
    drawn on it. Returns True when the thumbnail was finished. Does nothing (False) for any
    other picture. A headline that cannot be drawn leaves the picture attached, and drawing
    again (changing the headline) can be tried by hand.
    """
    async with SessionLocal() as session:
        row = (
            (await session.execute(select(Thumbnail).where(Thumbnail.lab_run_id == run_id)))
            .scalars()
            .first()
        )
        if row is None or row.background_image_id is not None:
            await session.commit()
            return False
        image = (
            (await session.execute(select(LabImage).where(LabImage.run_id == run_id)))
            .scalars()
            .first()
        )
        project = await session.get(Project, row.project_id)
        if image is None or project is None:
            await session.commit()
            return False
        row.background_image_id = image.id
        await session.flush()
        try:
            await _draw(session, row, project)
        except ThumbnailError as exc:
            _logger.warning("thumbnail %d: %s", row.id, exc)
            await session.commit()
            return False
        await _choose_if_asked(session, row, run_id)
        await session.commit()
    _logger.info("thumbnail %d: finished from run %d", row.id, run_id)
    return True


async def _choose_if_asked(session: AsyncSession, row: Thumbnail, run_id: int) -> None:
    """Makes the finished thumbnail the chosen one when its picture's job asks for it
    (`choose_when_ready`) and the chosen thumbnail is still the one that was chosen when it was
    asked for. A choice the owner made meanwhile is never replaced. Does not commit.
    """
    run = await session.get(LabRun, run_id)
    job = await session.get(Job, run.job_id) if run is not None and run.job_id is not None else None
    marker = (
        job.input.get(CHOOSE_WHEN_READY_KEY)
        if job is not None and isinstance(job.input, dict)
        else None
    )
    if not isinstance(marker, dict) or row.path is None:
        return
    if await chosen_id(session, row.project_id) != marker.get("chosen_before"):
        return
    await session.execute(
        update(Thumbnail).where(Thumbnail.project_id == row.project_id).values(chosen=False)
    )
    row.chosen = True


# --- Editing and choosing ------------------------------------------------------------------


async def _get(session: AsyncSession, project: Project, thumbnail_id: int) -> Thumbnail:
    row = await session.get(Thumbnail, thumbnail_id)
    if row is None or row.project_id != project.id:
        raise ThumbnailError(NO_THUMBNAIL_MESSAGE)
    return row


async def set_headline(
    session: AsyncSession, project: Project, thumbnail_id: int, headline: str
) -> Thumbnail:
    """Changes a thumbnail's headline and draws the picture again (no GPU work), and commits.
    An empty headline draws no text. Raises ThumbnailError.
    """
    row = await _get(session, project, thumbnail_id)
    try:
        text = writer.check_headline(headline)
    except ValueError as exc:
        raise ThumbnailError(str(exc)) from exc
    row.headline = text
    replaced = await _draw(session, row, project)
    await session.commit()
    await _delete_file(replaced)
    return row


async def set_chosen(
    session: AsyncSession, project: Project, thumbnail_id: int, chosen: bool
) -> Thumbnail:
    """Makes a thumbnail the project's chosen one (clearing the earlier choice), or clears the
    choice, and commits. Only a finished thumbnail can be chosen. Raises ThumbnailError.
    """
    row = await _get(session, project, thumbnail_id)
    if chosen and row.path is None:
        raise ThumbnailError(NOT_READY_MESSAGE)
    await session.execute(
        update(Thumbnail).where(Thumbnail.project_id == project.id).values(chosen=False)
    )
    row.chosen = chosen
    await session.commit()
    return row


# --- Reading the state ---------------------------------------------------------------------


@dataclass(frozen=True)
class ThumbnailEntry:
    """One thumbnail and where it stands."""

    row: Thumbnail
    # The `lab_image` job that makes the picture; None when its run or job is gone.
    job: Job | None
    # The run's error when the picture failed.
    error: str | None
    # Why the ideas this thumbnail was made from are out of date. Empty when they are current.
    reasons: list[str]


@dataclass(frozen=True)
class ThumbnailsState:
    """What the board panel shows."""

    concepts: thumbnail_concepts.ConceptsState
    thumbnails: list[ThumbnailEntry]
    # The size of a finished thumbnail of this project.
    width: int
    height: int


@memoized_state
async def state(session: AsyncSession, project: Project) -> ThumbnailsState:
    """The concepts and every thumbnail with where it stands, newest first. Worked out on every
    read; nothing here is stored.
    """
    concepts = await thumbnail_concepts.state(session, project)
    rows = list(
        (
            await session.execute(
                select(Thumbnail)
                .where(Thumbnail.project_id == project.id)
                .order_by(Thumbnail.id.desc())
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    run_ids = [row.lab_run_id for row in rows if row.lab_run_id is not None]
    runs: list[LabRun] = []
    if run_ids:
        runs = list((await session.execute(select(LabRun).where(LabRun.id.in_(run_ids)))).scalars())
    jobs = await image_lab.jobs_for_runs(session, runs)
    run_by_id = {run.id: run for run in runs}

    bible = await story_bible.latest(session, project.id)
    render = await thumbnail_concepts.newest_render(session, project.id)
    reasons_of: dict[int, list[str]] = {}
    for version in concepts.versions:
        reasons_of[version.version] = thumbnail_concepts.out_of_date_reasons(version, bible, render)

    entries: list[ThumbnailEntry] = []
    for row in rows:
        run = run_by_id.get(row.lab_run_id) if row.lab_run_id is not None else None
        entries.append(
            ThumbnailEntry(
                row=row,
                job=jobs.get(run.id) if run is not None else None,
                error=run.error if run is not None else None,
                reasons=reasons_of.get(row.concept_version, []),
            )
        )
    width, height = thumbnail_compose.size_for(project.orientation)
    return ThumbnailsState(concepts=concepts, thumbnails=entries, width=width, height=height)
