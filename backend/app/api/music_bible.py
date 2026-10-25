"""`/api/projects/{project_id}/music-bible`: the Music Bible stage (MUSIC-006).

- `POST .../run` starts the `write_music_bible` job in `full` mode: four directions, a choice
  and the Bible. When the newest version was written or chosen by the owner, the body must
  confirm the replacement.
- `POST .../choose` starts the job in `expand` mode: the owner picked another of the four
  directions of an earlier version, so only the Bible is written again.
- `PUT ...` saves the owner's edited Bible as the next version (`source` is `manual`).
- `GET ...` answers everything the story workspace shows for the stage in one call: the newest
  version, the list of versions, the newest job, why the newest version is out of date, and what
  the editor needs. "Out of date" is worked out on every read.
- `GET .../versions/{version}` answers one older (or the newest) version.

The rows and the job are made by `app/services/music_bible.py`. The answers never return ORM
objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import MusicBible, Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import music_bible as music_bible_service

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or version."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Music is off, or the story is not ready for a Music Bible.",
    }
}

Source = Literal["ai", "manual"]
ChoiceBy = Literal["ai", "owner"]


class DirectionOut(BaseModel):
    id: str
    name: str
    summary: str
    instruments: list[str]
    feel: str
    differs_by: str


class ChoiceOut(BaseModel):
    direction_id: str
    # `ai` when the model chose, `owner` when the owner chose another direction.
    by: ChoiceBy
    reasons: str


class SoundWorld(BaseModel):
    instruments: list[str]
    avoid: list[str]


class MusicalFeel(BaseModel):
    tempo: str
    mode_leaning: str
    density: str


class StandsFor(BaseModel):
    kind: Literal["character", "place", "idea"]
    # The id of the character or place, or None for an idea.
    ref: str | None
    description: str


class ThemeOut(BaseModel):
    id: str
    name: str
    main: bool
    stands_for: StandsFor
    signature_instrument: str
    emotions: list[str]


class ArcEntry(BaseModel):
    scene_id: str
    music: str


class Restraint(BaseModel):
    amount: str
    silence_rules: list[str]


class MusicBibleContent(BaseModel):
    """The Bible itself (`Music_implementation_phases.md` Section 4.2)."""

    concept: str
    sound_world: SoundWorld
    musical_feel: MusicalFeel
    themes: list[ThemeOut]
    arc: list[ArcEntry]
    restraint: Restraint
    ambience_signature: str


class MusicBibleVersionOut(BaseModel):
    version: int
    source: Source
    job_id: int | None
    created_at: datetime
    chosen_by: ChoiceBy


class MusicBibleOut(MusicBibleVersionOut):
    id: int
    directions: list[DirectionOut]
    choice: ChoiceOut
    content: MusicBibleContent


class MusicBibleJobOut(BaseModel):
    """The newest `write_music_bible` job of the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class SceneRef(BaseModel):
    id: str
    title: str


class NameRef(BaseModel):
    id: str
    name: str


class MusicBibleState(BaseModel):
    latest: MusicBibleOut | None
    versions: list[MusicBibleVersionOut]
    job: MusicBibleJobOut | None
    # Only the newest version is judged. False when there is no version.
    out_of_date: bool
    # One sentence for each thing the newest version was built from that has changed.
    reasons: list[str]
    # True when running the model again would add a version after one the owner wrote or chose.
    needs_confirmation: bool
    # Why no Music Bible can be written yet, or None.
    blocked_reason: str | None
    music_enabled: bool
    # The most themes a Bible may have (the main theme included).
    max_themes: int
    # What the editor offers: the scenes in story order, and what a theme may stand for.
    scenes: list[SceneRef]
    characters: list[NameRef]
    places: list[NameRef]


class MusicBibleRun(BaseModel):
    job_id: int


class MusicBibleRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False


class MusicBibleChooseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The version whose four directions the choice is made from.
    version: int = Field(ge=1, le=_MAX_INT)
    direction_id: str = Field(max_length=50)


class StandsForIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(max_length=50)
    ref: str | None = Field(default=None, max_length=500)
    description: str = Field(max_length=5000)


class ThemeIn(BaseModel):
    """A theme as edited. Its `id` is not sent: code sets `theme_1`, `theme_2`, ... with the
    main theme first.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=5000)
    main: StrictBool
    stands_for: StandsForIn
    signature_instrument: str = Field(max_length=5000)
    emotions: list[str] = Field(max_length=100)


class ArcEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str = Field(max_length=500)
    music: str = Field(max_length=5000)


class SoundWorldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruments: list[str] = Field(max_length=100)
    avoid: list[str] = Field(max_length=100)


class MusicalFeelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tempo: str = Field(max_length=5000)
    mode_leaning: str = Field(max_length=5000)
    density: str = Field(max_length=5000)


class RestraintIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str = Field(max_length=5000)
    silence_rules: list[str] = Field(max_length=100)


class MusicBibleSaveIn(BaseModel):
    """The Bible as the owner edited it. The size limits that matter are checked by
    `music_bible_writer.check_bible`; these only keep a request from being huge.
    """

    model_config = ConfigDict(extra="forbid")

    concept: str = Field(max_length=5000)
    sound_world: SoundWorldIn
    musical_feel: MusicalFeelIn
    themes: list[ThemeIn] = Field(max_length=100)
    arc: list[ArcEntryIn] = Field(max_length=1000)
    restraint: RestraintIn
    ambience_signature: str = Field(max_length=5000)


def _version_out(row: MusicBible) -> MusicBibleVersionOut:
    return MusicBibleVersionOut(
        # The database CHECK constraint keeps `source` to the two allowed values.
        version=row.version,
        source=cast(Source, row.source),
        job_id=row.job_id,
        created_at=row.created_at,
        chosen_by=cast(ChoiceBy, row.choice["by"]),
    )


def _bible_out(row: MusicBible) -> MusicBibleOut:
    return MusicBibleOut(
        **_version_out(row).model_dump(),
        id=row.id,
        directions=[DirectionOut.model_validate(direction) for direction in row.directions],
        choice=ChoiceOut.model_validate(row.choice),
        content=MusicBibleContent.model_validate(row.content),
    )


@router.post(
    "/projects/{project_id}/music-bible/run",
    response_model=MusicBibleRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_music_bible(
    project_id: int, session: SessionDep, body: MusicBibleRunIn | None = None
) -> MusicBibleRun:
    """Starts the job that writes the four directions, the choice and the Bible. If one is
    already waiting or running for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await music_bible_service.start_run(
            session,
            project,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except music_bible_service.MusicBibleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return MusicBibleRun(job_id=job.id)


@router.post(
    "/projects/{project_id}/music-bible/choose",
    response_model=MusicBibleRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def choose_music_direction(
    project_id: int, body: MusicBibleChooseIn, session: SessionDep
) -> MusicBibleRun:
    """Starts the job that writes the Bible again from the direction the owner chose. The four
    directions are not written again.
    """
    project = await load_project(session, project_id)
    try:
        job = await music_bible_service.start_choose(
            session, project, body.version, body.direction_id
        )
    except music_bible_service.MusicBibleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return MusicBibleRun(job_id=job.id)


async def _state(session: AsyncSession, project: Project) -> MusicBibleState:
    state = await music_bible_service.state(session, project)
    job = state.job
    return MusicBibleState(
        latest=_bible_out(state.latest) if state.latest is not None else None,
        versions=[_version_out(row) for row in state.versions],
        job=(
            MusicBibleJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        out_of_date=state.out_of_date,
        reasons=state.reasons,
        needs_confirmation=state.needs_confirmation,
        blocked_reason=state.blocked_reason,
        music_enabled=state.music_enabled,
        max_themes=state.max_themes,
        scenes=[SceneRef(**scene) for scene in state.scenes],
        characters=[NameRef(**item) for item in state.characters],
        places=[NameRef(**item) for item in state.places],
    )


@router.get(
    "/projects/{project_id}/music-bible",
    response_model=MusicBibleState,
    responses=_NOT_FOUND,
)
async def get_music_bible(project_id: int, session: SessionDep) -> MusicBibleState:
    return await _state(session, await load_project(session, project_id))


@router.put(
    "/projects/{project_id}/music-bible",
    response_model=MusicBibleState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_music_bible(
    project_id: int, body: MusicBibleSaveIn, session: SessionDep
) -> MusicBibleState:
    """Saves the whole edited Bible as the next version, written by the owner."""
    project = await load_project(session, project_id)
    try:
        await music_bible_service.save_manual(session, project, body.model_dump())
    except music_bible_service.MusicBibleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _state(session, project)


@router.get(
    "/projects/{project_id}/music-bible/versions/{version}",
    response_model=MusicBibleOut,
    responses=_NOT_FOUND,
)
async def get_music_bible_version(
    project_id: int,
    version: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> MusicBibleOut:
    project = await load_project(session, project_id)
    row = await music_bible_service.get_version(session, project.id, version)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"The project has no Music Bible version {version}."
        )
    return _bible_out(row)
