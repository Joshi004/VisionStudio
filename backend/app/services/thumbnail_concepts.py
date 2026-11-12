"""The thumbnail concepts of a project: who may appear, starting the job that writes the four
concepts, saving the owner's edits, and reading the versions back.

Every version is a new `thumbnail_concepts` row and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). `content` is `{concepts: [4 items]}`
(`services/thumbnail_concept_writer`). `inputs` records the Story Bible the version was written
from, and the newest render when its frames were sent to the model, so whether the version is
out of date is worked out when it is read and never stored.

Two ways make a version:

- `start_run` queues the `write_thumbnail_concepts` job: one call to the vision model writes the
  four concepts, and code checks them.
- `save_manual` stores the owner's edit of the newest version, checked by the same rules.

**Who may appear.** An explainer: its presenter. A story: every character linked to the project.
Each person is offered with the looks that have a picture (the character's usual look, and each
named look the pinned version froze); a character with no picture is left out, because the
picture step needs one to draw them.

**When concepts can be made.** The Story Bible must exist. A render is not needed: with one, the
model also sees frames of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CharacterNamedLook,
    Job,
    LibraryCharacter,
    LibraryCharacterVersion,
    Project,
    ProjectCharacterLink,
    StoryRender,
    ThumbnailConcepts,
)
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    character_links,
    character_versions,
    discovery,
    explainer,
    provenance,
    story_bible,
    user_feedback,
)
from app.services import thumbnail_concept_writer as writer

JOB_TYPE: Final = "write_thumbnail_concepts"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"

STORY_BIBLE_KIND: Final = "story_bible"
STORY_RENDER_KIND: Final = "story_render"

DEFAULT_LOOK: Final = "default"

NO_BIBLE_MESSAGE: Final = "Write the Story Bible first: the thumbnail follows its tone."
NO_CONCEPTS_MESSAGE: Final = "There are no thumbnail ideas yet, so there is nothing to change."
BEING_WRITTEN_MESSAGE: Final = "The thumbnail ideas are already being written."

_ABOUT_MAX_CHARS: Final = 300
_LOOK_TEXT_MAX_CHARS: Final = 150
# The angle to draw a person from, best first: the face must be clear.
_PICTURE_ORDER: Final = ("front", "three_quarter", "face", "profile", "back")


class ThumbnailConceptsError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- Who may appear --------------------------------------------------------------------------


@dataclass(frozen=True)
class Look:
    """One look a person can wear in a thumbnail, with the lab image the picture is drawn from."""

    slug: str
    description: str
    image_id: int


@dataclass(frozen=True)
class CastOption:
    """One person who may appear. `id` is what the concepts call them."""

    id: str
    name: str
    about: str
    looks: list[Look]

    def for_model(self) -> dict[str, Any]:
        """What the model is told. The lab image ids stay in the app."""
        return {
            "id": self.id,
            "name": self.name,
            "about": self.about,
            "looks": [{"slug": look.slug, "description": look.description} for look in self.looks],
        }

    def look(self, slug: str) -> Look | None:
        return next((look for look in self.looks if look.slug == slug), None)


def _cut(text: str | None, limit: int) -> str:
    one_line = " ".join((text or "").split())
    return one_line if len(one_line) <= limit else one_line[:limit].rstrip()


def _best_picture(references: Any) -> int | None:
    """The lab image id of the clearest angle of a frozen list of `{angle, lab_image_id, ...}`."""
    found: dict[str, int] = {}
    for entry in references if isinstance(references, list) else []:
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("angle"), str)
            and isinstance(entry.get("lab_image_id"), int)
        ):
            found[entry["angle"]] = entry["lab_image_id"]
    return next((found[angle] for angle in _PICTURE_ORDER if angle in found), None)


async def _looks_of(
    session: AsyncSession, character: LibraryCharacter, version: LibraryCharacterVersion
) -> list[Look]:
    """The looks of one pinned version that have a picture, the usual look first."""
    looks: list[Look] = []
    usual = _best_picture(version.look_references)
    if usual is not None:
        looks.append(
            Look(
                slug=DEFAULT_LOOK,
                description=_cut(
                    f"usual look: {character.outfit}" if character.outfit else "usual look",
                    _LOOK_TEXT_MAX_CHARS,
                ),
                image_id=usual,
            )
        )
    named = [item for item in version.named_looks or [] if isinstance(item, dict)]
    slugs = [str(item.get("slug")) for item in named if item.get("slug")]
    descriptions: dict[str, str] = {}
    if slugs:
        rows = await session.execute(
            select(CharacterNamedLook.slug, CharacterNamedLook.description).where(
                CharacterNamedLook.character_id == character.id,
                CharacterNamedLook.slug.in_(slugs),
            )
        )
        descriptions = {slug: description for slug, description in rows}
    for item in named:
        slug = item.get("slug")
        picture = _best_picture(item.get("references"))
        if isinstance(slug, str) and slug != DEFAULT_LOOK and picture is not None:
            looks.append(
                Look(
                    slug=slug,
                    description=_cut(descriptions.get(slug) or slug, _LOOK_TEXT_MAX_CHARS),
                    image_id=picture,
                )
            )
    return looks


async def _explainer_options(session: AsyncSession, project: Project) -> list[CastOption]:
    presenter = await explainer.presenter_of(session, project.id)
    if presenter is None:
        return []
    link = (
        (
            await session.execute(
                select(ProjectCharacterLink).where(
                    ProjectCharacterLink.project_id == project.id,
                    ProjectCharacterLink.character_id == presenter.id,
                )
            )
        )
        .scalars()
        .first()
    )
    version = (
        await character_versions.get_version(session, presenter.id, link.pinned_version)
        if link is not None
        else await character_versions.latest_version(session, presenter.id)
    )
    if version is None:
        return []
    looks = await _looks_of(session, presenter, version)
    # The outfit the owner chose for the presenter is listed first.
    if project.presenter_named_look_id is not None:
        chosen = await session.get(CharacterNamedLook, project.presenter_named_look_id)
        if chosen is not None:
            looks.sort(key=lambda look: look.slug != chosen.slug)
    if not looks:
        return []
    return [
        CastOption(
            id=explainer.slug_of(presenter.name, "presenter"),
            name=presenter.name,
            about=_cut(presenter.appearance, _ABOUT_MAX_CHARS),
            looks=looks,
        )
    ]


async def _story_options(session: AsyncSession, project: Project) -> list[CastOption]:
    links = await character_links.state(session, project.id)
    options: list[CastOption] = []
    for entry in links.entries:
        info = entry.info
        if info is None:
            continue
        version = await character_versions.get_version(
            session, info.character.id, info.link.pinned_version
        )
        if version is None:
            continue
        looks = await _looks_of(session, info.character, version)
        if not looks:
            continue
        description = entry.item.get("description")
        options.append(
            CastOption(
                id=str(entry.item["id"]),
                name=str(entry.item.get("name") or info.character.name),
                about=_cut(
                    description if isinstance(description, str) else info.character.appearance,
                    _ABOUT_MAX_CHARS,
                ),
                looks=looks,
            )
        )
    return options


async def cast_options(session: AsyncSession, project: Project) -> list[CastOption]:
    """The people who may appear in this project's thumbnails, each with the looks that have a
    picture. Worked out on every call.
    """
    if explainer.is_explainer(project):
        return await _explainer_options(session, project)
    return await _story_options(session, project)


def looks_of(options: list[CastOption]) -> dict[str, set[str]]:
    """The checker's view of `options`: each person's id with the look slugs they may wear."""
    return {option.id: {look.slug for look in option.looks} for option in options}


# --- Versions --------------------------------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> ThumbnailConcepts | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(ThumbnailConcepts)
        .where(ThumbnailConcepts.project_id == project_id)
        .order_by(ThumbnailConcepts.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def list_versions(session: AsyncSession, project_id: int) -> list[ThumbnailConcepts]:
    """Every version of the project, newest first."""
    statement = (
        select(ThumbnailConcepts)
        .where(ThumbnailConcepts.project_id == project_id)
        .order_by(ThumbnailConcepts.version.desc())
    )
    return list((await session.execute(statement)).scalars())


async def get_version(
    session: AsyncSession, project_id: int, version: int
) -> ThumbnailConcepts | None:
    """One version of the project, or None when there is no such version."""
    statement = select(ThumbnailConcepts).where(
        ThumbnailConcepts.project_id == project_id, ThumbnailConcepts.version == version
    )
    return (await session.execute(statement)).scalars().first()


async def _add_version(
    session: AsyncSession,
    *,
    project_id: int,
    source: str,
    job_id: int | None,
    inputs: dict[str, Any],
    content: dict[str, Any],
) -> ThumbnailConcepts:
    statement = select(func.max(ThumbnailConcepts.version)).where(
        ThumbnailConcepts.project_id == project_id
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = ThumbnailConcepts(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=source,
        job_id=job_id,
        inputs=inputs,
        content=content,
    )
    session.add(row)
    await session.flush()
    return row


async def save_version(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    inputs: dict[str, Any],
    content: dict[str, Any],
) -> ThumbnailConcepts:
    """Adds the next version, made by the model (`source` is `ai`). Flushes but does not
    commit: the job commits it together with finishing itself, so a job is never "succeeded"
    without its result.
    """
    return await _add_version(
        session,
        project_id=project_id,
        source=SOURCE_AI,
        job_id=job_id,
        inputs=inputs,
        content=content,
    )


async def newest_render(session: AsyncSession, project_id: int) -> StoryRender | None:
    """The project's newest finished render, or None when it has none."""
    statement = (
        select(StoryRender)
        .where(StoryRender.project_id == project_id)
        .order_by(StoryRender.render_number.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


# --- Starting a run --------------------------------------------------------------------------


def _saved_inputs(
    bible: Any, render: StoryRender | None, feedback: user_feedback.Feedback | None
) -> dict[str, Any]:
    """What a version is built from, in the artifact shape of D-3."""
    artifacts: list[dict[str, Any]] = [
        {"kind": STORY_BIBLE_KIND, "id": bible.id, "version": bible.version}
    ]
    if render is not None:
        artifacts.append({"kind": STORY_RENDER_KIND, "id": render.id})
    inputs: dict[str, Any] = {"artifacts": artifacts}
    if feedback is not None:
        inputs["feedback"] = feedback.for_version()
    return inputs


def _feedback_on(text: str, newest: ThumbnailConcepts | None) -> user_feedback.Feedback:
    """The user's note on the newest version, with its concepts as what it is about. Raises
    ThumbnailConceptsError when the note is not usable or there is nothing to talk about.
    """
    try:
        note = user_feedback.clean(text)
    except ValueError as exc:
        raise ThumbnailConceptsError(str(exc)) from exc
    if newest is None:
        raise ThumbnailConceptsError(NO_CONCEPTS_MESSAGE)
    return user_feedback.Feedback(
        text=note, previous=newest.content["concepts"], base_version=newest.version
    )


async def scene_titles(session: AsyncSession, project_id: int) -> list[str]:
    """The titles of the project's newest scene discovery, in order; empty when it has none."""
    row = await discovery.latest(session, "scenes", project_id)
    content = row.content if row is not None else None
    scenes = content.get("scenes") if isinstance(content, dict) else None
    titles: list[str] = []
    for scene in scenes if isinstance(scenes, list) else []:
        title = scene.get("title") if isinstance(scene, dict) else None
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())
    return titles


async def start_run(
    session: AsyncSession,
    project: Project,
    *,
    feedback: str | None = None,
    render: StoryRender | None = None,
    then_picture: dict[str, Any] | None = None,
) -> Job:
    """Queues the job that writes the concepts, from a copy of what it is made from, and
    commits. If a job is already waiting or running for the project, that job is returned and no
    new one is made; a note is never dropped silently, so a note is refused in that case.

    `feedback` is the owner's note on the newest version: the model writes the four concepts
    again with the note and that version in its request. `render` is the render whose frames
    are used (the newest when None). `then_picture` (`{"chosen_before": id or None}`) asks the
    job, once the concepts are stored, to make the pictures of all the concepts and choose the
    first one that is ready, unless the chosen thumbnail changed meanwhile (the YouTube draft,
    YT-003, YTF-003).
    Raises ThumbnailConceptsError.
    """
    bible = await story_bible.latest(session, project.id)
    if bible is None:
        raise ThumbnailConceptsError(NO_BIBLE_MESSAGE)
    note = _feedback_on(feedback, await latest(session, project.id)) if feedback else None
    options = await cast_options(session, project)
    if render is None:
        render = await newest_render(session, project.id)
    context = writer.context_for_model(
        bible.content,
        project.orientation,
        await scene_titles(session, project.id),
        [option.for_model() for option in options],
    )
    job_input: dict[str, Any] = {
        "context": context,
        "looks_of": {person: sorted(slugs) for person, slugs in looks_of(options).items()},
        "render_id": render.id if render is not None else None,
        "saved_inputs": _saved_inputs(bible, render, note),
    }
    if note is not None:
        job_input["feedback"] = note.for_job()
    if then_picture is not None:
        job_input["then_picture"] = then_picture
    job, created = await store.create_job(
        session, project_id=project.id, type=JOB_TYPE, provider="llm", input=job_input
    )
    if note is not None and not created:
        raise ThumbnailConceptsError(BEING_WRITTEN_MESSAGE)
    return job


# --- The owner's edit ------------------------------------------------------------------------


async def save_manual(
    session: AsyncSession, project: Project, concepts: list[dict[str, Any]]
) -> ThumbnailConcepts:
    """Stores the owner's edit of the concepts as the next version (`source` is `manual`), and
    commits. `concepts` is the complete list of four, in the shape of the stored content. The
    checks are the model's, except that a headline may be left empty. The inputs are those of
    the version that was edited, so an edit never makes old ideas look new. Refused while a job
    is writing the concepts. Raises ThumbnailConceptsError.
    """
    newest = await latest(session, project.id)
    if newest is None:
        raise ThumbnailConceptsError(NO_CONCEPTS_MESSAGE)
    active = await store.latest_job(session, project.id, JOB_TYPE)
    if active is not None and active.status in store.ACTIVE_STATUSES:
        raise ThumbnailConceptsError(BEING_WRITTEN_MESSAGE)
    options = await cast_options(session, project)
    try:
        content = writer.check_content(
            {"concepts": concepts}, looks_of(options), require_headline=False
        )
    except ValueError as exc:
        raise ThumbnailConceptsError(str(exc)) from exc
    inputs = {
        "artifacts": newest.inputs.get("artifacts", []) if isinstance(newest.inputs, dict) else [],
        "edited_from": {"id": newest.id, "version": newest.version},
    }
    row = await _add_version(
        session,
        project_id=project.id,
        source=SOURCE_MANUAL,
        job_id=None,
        inputs=inputs,
        content=content,
    )
    await session.commit()
    return row


# --- Reading the state -----------------------------------------------------------------------


def _recorded(inputs: Any, kind: str) -> dict[str, Any] | None:
    """The artifact record of this kind in `inputs`."""
    if not isinstance(inputs, dict):
        return None
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            return artifact
    return None


def out_of_date_reasons(
    row: ThumbnailConcepts, bible: Any, render: StoryRender | None
) -> list[str]:
    """Why a version is no longer current, one sentence each."""
    reasons: list[str] = []
    if not provenance.same_row(_recorded(row.inputs, STORY_BIBLE_KIND), bible):
        reasons.append("The Story Bible was written again since these ideas were made.")
    recorded_render = _recorded(row.inputs, STORY_RENDER_KIND)
    if render is not None:
        if recorded_render is None:
            reasons.append(
                "The video has been rendered since these ideas were made, "
                "so its frames can now be used."
            )
        elif recorded_render.get("id") != render.id:
            reasons.append("The video was rendered again since these ideas were made.")
    return reasons


@dataclass(frozen=True)
class ConceptsState:
    """What the board panel shows."""

    latest: ThumbnailConcepts | None
    versions: list[ThumbnailConcepts]
    # The newest job, whatever its status.
    job: Job | None
    out_of_date: bool
    reasons: list[str]
    # Why no concepts can be written yet, or None.
    blocked_reason: str | None
    # The people who may appear now, each with their looks.
    cast: list[CastOption]


@memoized_state
async def state(session: AsyncSession, project: Project) -> ConceptsState:
    """The project's thumbnail concepts with where they stand. Worked out on every read;
    nothing here is stored.
    """
    newest = await latest(session, project.id)
    bible = await story_bible.latest(session, project.id)
    render = await newest_render(session, project.id)
    reasons = out_of_date_reasons(newest, bible, render) if newest is not None else []
    return ConceptsState(
        latest=newest,
        versions=await list_versions(session, project.id),
        job=await store.latest_job(session, project.id, JOB_TYPE),
        out_of_date=bool(reasons),
        reasons=reasons,
        blocked_reason=None if bible is not None else NO_BIBLE_MESSAGE,
        cast=await cast_options(session, project),
    )
