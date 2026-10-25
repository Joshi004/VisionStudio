"""`/api/projects/{project_id}/music-themes`: the recordings of a story's music themes (MUSIC-007).

- `GET ...` answers everything the story workspace shows for the stage in one call: each theme of
  the newest Music Bible with its fields, its candidate recordings, its emotional versions, the
  newest prompt job, and whether it is out of date. "Out of date" is worked out on every read.
- `POST .../run` starts whatever is missing or out of date for every theme (or, with
  `?theme_id=`, one theme): the prompt job, more candidates, or the versions. When it would
  replace a canonical recording the owner chose, the body must confirm it.
- `POST .../{theme_id}/choose` makes a candidate the theme's canonical recording; the versions are
  made again from it.
- `POST .../{theme_id}/versions/{emotion}/regenerate` makes one version again with a new seed.

A recording is a Music lab run (`lab_music_run`), so the rating, measurements and player of the
lab apply to it, and it has the lab's `LabMusicRunOut` shape. The rows and jobs are made by
`app/services/music_themes.py`. The answers never return ORM objects.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.music_bible import StandsFor
from app.api.music_lab import LabMusicRunOut, run_out
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import music_themes

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1
_MAX_TEXT = 200

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Music is off, there is no Music Bible, or the request cannot be done now.",
    }
}

ChosenBy = Literal["auto", "owner"]
Action = Literal["theme", "candidates", "versions"]


class ThemeCheckOut(BaseModel):
    """The technical check of a recording (`music_themes.check_recording`)."""

    passed: bool
    # What failed, in plain words. Empty when it passed.
    problems: list[str]
    duration_s: float | None
    leading_silence_s: float | None


class ThemeCandidateOut(BaseModel):
    id: int
    position: int
    seed: int
    chosen: bool
    # The recording (a lab run): its job, player URL, measurements endpoint and rating.
    run: LabMusicRunOut | None
    # None until the audio exists and has been checked.
    check: ThemeCheckOut | None


class ThemeVersionOut(BaseModel):
    id: int
    emotion: str
    method: Literal["text"]
    seed: int
    # Made from the candidate that is canonical now. False after another candidate was chosen:
    # it is shown until the new one replaces it.
    current: bool
    run: LabMusicRunOut | None
    check: ThemeCheckOut | None


class ThemeJobOut(BaseModel):
    """The newest `write_music_theme_prompt` job of the theme, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None
    # `theme` or `versions`.
    requested: str | None


class MusicThemeOut(BaseModel):
    """One theme of the newest Music Bible and where its recordings stand."""

    theme_id: str
    name: str
    main: bool
    stands_for: StandsFor
    signature_instrument: str
    emotions: list[str]
    # The newest recording of the theme (1, 2, ...), or None before the first.
    version: int | None
    # The ACE-Step fields sent for every candidate.
    fields: dict[str, object] | None
    chosen_candidate_id: int | None
    chosen_by: ChosenBy | None
    candidates: list[ThemeCandidateOut]
    versions: list[ThemeVersionOut]
    job: ThemeJobOut | None
    out_of_date: bool
    reasons: list[str]
    # True when recording the theme again would replace a canonical recording the owner chose.
    needs_confirmation: bool
    # The canonical recording is chosen and every emotion has a recording.
    done: bool
    # Something is being written or recorded now.
    active: bool
    # What a run would start next, or None when nothing is missing.
    action: Action | None
    # The emotions that still need a version.
    missing_emotions: list[str]


class MusicThemesState(BaseModel):
    bible_version: int | None
    themes: list[MusicThemeOut]
    music_enabled: bool
    # Why no theme can be recorded yet, or None.
    blocked_reason: str | None
    # The settings a run uses now.
    candidates_per_theme: int
    duration_s: int


class MusicThemesRun(BaseModel):
    # The jobs it queued. Empty when everything is done or already being made.
    job_ids: list[int]


class MusicThemesRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_owner: bool = False


class MusicThemeChooseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: int = Field(ge=1, le=_MAX_INT)


def _check_out(check: object) -> ThemeCheckOut | None:
    if not isinstance(check, dict) or not isinstance(check.get("passed"), bool):
        return None
    return ThemeCheckOut.model_validate(check)


def _theme_out(view: music_themes.ThemeView) -> MusicThemeOut:
    row = view.row
    chosen_id = row.chosen_candidate_id if row is not None else None
    job = view.job
    theme = view.theme
    return MusicThemeOut(
        theme_id=theme["id"],
        name=theme["name"],
        main=bool(theme.get("main")),
        stands_for=StandsFor.model_validate(theme["stands_for"]),
        signature_instrument=theme["signature_instrument"],
        emotions=list(theme.get("emotions") or []),
        version=row.version if row is not None else None,
        fields=dict(row.fields) if row is not None else None,
        chosen_candidate_id=chosen_id,
        # The database CHECK constraint keeps `chosen_by` to the two allowed values.
        chosen_by=cast(ChosenBy | None, row.chosen_by if row is not None else None),
        candidates=[
            ThemeCandidateOut(
                id=candidate.row.id,
                position=candidate.row.position,
                seed=candidate.row.seed,
                chosen=candidate.row.id == chosen_id,
                run=run_out(candidate.run) if candidate.run is not None else None,
                check=_check_out(candidate.row.check_result),
            )
            for candidate in view.candidates
        ],
        versions=[
            ThemeVersionOut(
                id=version.row.id,
                emotion=version.row.emotion,
                method="text",
                seed=version.row.seed,
                current=version.current,
                run=run_out(version.run) if version.run is not None else None,
                check=_check_out(version.row.check_result),
            )
            for version in view.versions
        ],
        job=(
            ThemeJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
                requested=job.input.get("requested") if isinstance(job.input, dict) else None,
            )
            if job is not None
            else None
        ),
        out_of_date=view.out_of_date,
        reasons=view.reasons,
        needs_confirmation=view.needs_confirmation,
        done=view.done,
        active=view.active,
        action=cast(Action | None, view.action),
        missing_emotions=view.to_write,
    )


async def _state(session: AsyncSession, project_id: int) -> MusicThemesState:
    project = await load_project(session, project_id)
    current = await music_themes.state(session, project)
    return MusicThemesState(
        bible_version=current.bible.version if current.bible is not None else None,
        themes=[_theme_out(view) for view in current.themes],
        music_enabled=current.music_enabled,
        blocked_reason=current.blocked_reason,
        candidates_per_theme=current.candidates_per_theme,
        duration_s=current.duration_s,
    )


def _refused(exc: music_themes.MusicThemeError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/music-themes",
    response_model=MusicThemesState,
    responses=_NOT_FOUND,
)
async def get_music_themes(project_id: int, session: SessionDep) -> MusicThemesState:
    return await _state(session, project_id)


@router.post(
    "/projects/{project_id}/music-themes/run",
    response_model=MusicThemesRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_music_themes(
    project_id: int,
    session: SessionDep,
    body: MusicThemesRunIn | None = None,
    theme_id: Annotated[str | None, Query(max_length=_MAX_TEXT)] = None,
) -> MusicThemesRun:
    """Starts what is missing or out of date: the model's prompt for a theme, more candidates when
    none could be chosen, or the versions of the emotions that have none. Paid GPU and model
    calls start only from here (or from a pipeline run), never by themselves.
    """
    project = await load_project(session, project_id)
    try:
        job_ids = await music_themes.start_run(
            session,
            project,
            theme_id=theme_id,
            confirm_replace_owner=body.confirm_replace_owner if body is not None else False,
        )
    except music_themes.MusicThemeError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return MusicThemesRun(job_ids=list(job_ids))


@router.post(
    "/projects/{project_id}/music-themes/{theme_id}/choose",
    response_model=MusicThemesRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def choose_music_theme_candidate(
    project_id: int,
    theme_id: Annotated[str, Path(max_length=_MAX_TEXT)],
    body: MusicThemeChooseIn,
    session: SessionDep,
) -> MusicThemesRun:
    """Makes the candidate the theme's canonical recording. The versions of its emotions are made
    again from it, so the ones made from the old choice read as out of date until they are.
    """
    project = await load_project(session, project_id)
    try:
        job_ids = await music_themes.choose(session, project, theme_id, body.candidate_id)
    except music_themes.MusicThemeError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return MusicThemesRun(job_ids=list(job_ids))


@router.post(
    "/projects/{project_id}/music-themes/{theme_id}/versions/{emotion}/regenerate",
    response_model=MusicThemesRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def regenerate_music_theme_version(
    project_id: int,
    theme_id: Annotated[str, Path(max_length=_MAX_TEXT)],
    emotion: Annotated[str, Path(max_length=_MAX_TEXT)],
    session: SessionDep,
) -> MusicThemesRun:
    """Makes one emotional version again: the same fields with a new seed. No model call."""
    project = await load_project(session, project_id)
    try:
        job_ids = await music_themes.regenerate_version(session, project, theme_id, emotion)
    except music_themes.MusicThemeError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return MusicThemesRun(job_ids=list(job_ids))
