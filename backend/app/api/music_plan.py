"""`/api/projects/{project_id}/music-plan`: the music plan stage (MUSIC-008).

- `POST .../run` starts the `write_music_plan` job: the plan, then rounds of critics and a
  reviser. When the newest version was written by the owner, the body must confirm the
  replacement.
- `PUT ...` saves the owner's edited plan as the next version (`source` is `manual`). The plan
  is checked against the timeline as it is now.
- `GET ...` answers everything the story workspace shows for the stage in one call: the newest
  version, the list of versions, the newest job, why the newest version is out of date, and what
  the editor needs (the timeline as it is now, and the Bible's themes). "Out of date" is worked
  out on every read.
- `GET .../versions/{version}` answers one older (or the newest) version.

The rows and the job are made by `app/services/music_plan.py`. The answers never return ORM
objects. Boundaries are sent as `from_cue` and `to_cue` (the stored keys are `from` and `to`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import MusicPlan, Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import music_plan as music_plan_service

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or version."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Music is off, the shots are not ready, or the plan breaks a rule.",
    }
}

Source = Literal["ai", "manual"]
CueKind = Literal["score", "bed", "point", "hit", "silence"]
Maker = Literal["ace_step", "stable_audio_3", "h3"]
Join = Literal["crossfade", "under_cover", "through_silence", "hard_cut"]
Lane = Literal["score", "bed"]


# --- The timeline --------------------------------------------------------------------------


class MoodOut(BaseModel):
    start: str
    middle: str
    end: str


class SceneSpanOut(BaseModel):
    ref: str
    id: str
    title: str
    start_s: float
    end_s: float
    mood: MoodOut


class ShotSpanOut(BaseModel):
    ref: str
    scene_id: str
    type: str | None
    description: str
    start_s: float
    end_s: float
    event_ids: list[str]


class UnitSpanOut(BaseModel):
    ref: str
    scene_id: str
    kind: Literal["narration", "dialogue"]
    speaker: str | None
    off_screen: bool
    text: str
    start_s: float
    end_s: float


class EventSpanOut(BaseModel):
    ref: str
    scene_id: str
    type: str
    start_s: float
    end_s: float
    time_from: Literal["unit", "shot"]
    # The references of the shots that show it.
    shots: list[str]
    description: str | None = None
    units: list[str] | None = None


class GapOut(BaseModel):
    after: str
    before: str
    start_s: float
    end_s: float


class TimelineOut(BaseModel):
    """The condensed story timeline, in seconds from the start of the story."""

    total_s: float
    scenes: list[SceneSpanOut]
    shots: list[ShotSpanOut]
    units: list[UnitSpanOut]
    events: list[EventSpanOut]
    gaps: list[GapOut]


# --- The plan ------------------------------------------------------------------------------


class AnchorOut(BaseModel):
    ref: str
    edge: Literal["start", "end"]
    relation: Literal["before", "just_before", "on", "after", "under"]
    strict: Literal["tight", "loose"]
    # The nominal story second it resolves to.
    seconds: float


class SoundRequestOut(BaseModel):
    shot: str
    event: str


class ReroutedOut(BaseModel):
    reason: str


class CueOut(BaseModel):
    id: str
    kind: CueKind
    maker: Maker | None
    summary: str
    purpose: str
    theme_id: str | None
    emotion: str | None
    intensity: int
    # A score, bed or silence has `start` and `end`; a point or hit has `at`.
    start: AnchorOut | None
    end: AnchorOut | None
    at: AnchorOut | None
    # Null at an edge where a boundary decides how the cue meets its neighbour.
    start_style: str | None
    end_style: str | None
    sound_request: SoundRequestOut | None
    # Set when a point sound given to H3 was made by Stable Audio 3 instead.
    rerouted: ReroutedOut | None
    reason: str


class BoundaryOut(BaseModel):
    from_cue: str
    to_cue: str
    lane: Lane
    join: Join
    reason: str


class SoundRequestListOut(BaseModel):
    cue_id: str
    shot: str
    event: str


class PlanContent(BaseModel):
    cues: list[CueOut]
    boundaries: list[BoundaryOut]
    # The sounds H3 is asked for, one per shot (derived from the cues).
    sound_requests: list[SoundRequestListOut]


class PlanSilenceOut(BaseModel):
    cue_id: str
    start_s: float
    end_s: float


class StretchOut(BaseModel):
    start_s: float
    end_s: float
    length_s: float


class FactsOut(BaseModel):
    total_s: float
    score_coverage_pct: float
    bed_coverage_pct: float
    counts: dict[str, int]
    silences: list[PlanSilenceOut]
    longest_without_score: StretchOut | None
    rerouted: list[str]


class NoteOut(BaseModel):
    target: str
    problem: str
    suggestion: str


class CritiqueOut(BaseModel):
    lens: str
    # `ok`, `change`, or `failed` when the critic's answer could not be used.
    verdict: Literal["ok", "change", "failed"]
    notes: list[NoteOut]
    failure: str | None


class RoundOut(BaseModel):
    round: int
    critiques: list[CritiqueOut]
    revised: bool
    failure: str | None


class MusicPlanVersionOut(BaseModel):
    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class MusicPlanOut(MusicPlanVersionOut):
    id: int
    content: PlanContent
    facts: FactsOut
    rounds: list[RoundOut]
    # The timeline the plan was written against.
    timeline: TimelineOut


class MusicPlanJobOut(BaseModel):
    """The newest `write_music_plan` job of the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class ThemeRef(BaseModel):
    id: str
    name: str


class MusicPlanState(BaseModel):
    latest: MusicPlanOut | None
    versions: list[MusicPlanVersionOut]
    job: MusicPlanJobOut | None
    # Only the newest version is judged. False when there is no version.
    out_of_date: bool
    # One sentence for each thing the newest version was built from that has changed.
    reasons: list[str]
    # True when running the model again would add a version after one the owner wrote.
    needs_confirmation: bool
    # Why no music plan can be written yet, or None.
    blocked_reason: str | None
    music_enabled: bool
    # The review rounds a run makes at most (a setting).
    critic_rounds: int
    # The timeline as it is now, which an edit is checked against. None while blocked.
    timeline: TimelineOut | None
    # The themes of the newest Music Bible.
    themes: list[ThemeRef]


class MusicPlanRun(BaseModel):
    job_id: int


class MusicPlanRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False


# --- What an edit sends --------------------------------------------------------------------


class AnchorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(max_length=500)
    edge: str = Field(max_length=50)
    relation: str = Field(max_length=50)
    strict: str = Field(max_length=50)


class SoundRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot: str = Field(max_length=500)
    event: str = Field(max_length=500)


class CueIn(BaseModel):
    """A cue as edited. Its `id` is a label that boundaries use; code sets `cue_1`, `cue_2`, ...
    in time order. `maker` only matters for a point sound.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=200)
    kind: str = Field(max_length=50)
    summary: str = Field(max_length=5000)
    purpose: str = Field(max_length=5000)
    reason: str = Field(max_length=5000)
    intensity: int = Field(ge=-1000, le=1000)
    theme_id: str | None = Field(default=None, max_length=500)
    emotion: str | None = Field(default=None, max_length=5000)
    maker: str | None = Field(default=None, max_length=50)
    start: AnchorIn | None = None
    end: AnchorIn | None = None
    at: AnchorIn | None = None
    start_style: str | None = Field(default=None, max_length=50)
    end_style: str | None = Field(default=None, max_length=50)
    sound_request: SoundRequestIn | None = None


class BoundaryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_cue: str = Field(max_length=200)
    to_cue: str = Field(max_length=200)
    join: str = Field(max_length=50)
    reason: str = Field(max_length=5000)


class MusicPlanSaveIn(BaseModel):
    """The plan as the owner edited it. What is allowed is checked by
    `music_plan_writer.check_plan`; these limits only keep a request from being huge.
    """

    model_config = ConfigDict(extra="forbid")

    cues: list[CueIn] = Field(max_length=500)
    boundaries: list[BoundaryIn] = Field(max_length=1000)


def _answer_of(body: MusicPlanSaveIn) -> dict[str, Any]:
    """The edit in the shape of the model's answer."""
    boundaries = [
        {"from": item.from_cue, "to": item.to_cue, "join": item.join, "reason": item.reason}
        for item in body.boundaries
    ]
    return {"cues": [cue.model_dump() for cue in body.cues], "boundaries": boundaries}


# --- Mapping rows to answers ---------------------------------------------------------------


def _version_out(row: MusicPlan) -> MusicPlanVersionOut:
    return MusicPlanVersionOut(
        # The database CHECK constraint keeps `source` to the two allowed values.
        version=row.version,
        source=cast(Source, row.source),
        job_id=row.job_id,
        created_at=row.created_at,
    )


def _content_out(content: dict[str, Any]) -> PlanContent:
    boundaries = [
        BoundaryOut(
            from_cue=item["from"],
            to_cue=item["to"],
            lane=item["lane"],
            join=item["join"],
            reason=item["reason"],
        )
        for item in content["boundaries"]
    ]
    return PlanContent(
        cues=[CueOut.model_validate(cue) for cue in content["cues"]],
        boundaries=boundaries,
        sound_requests=[
            SoundRequestListOut.model_validate(item) for item in content["sound_requests"]
        ],
    )


def _plan_out(row: MusicPlan) -> MusicPlanOut:
    return MusicPlanOut(
        **_version_out(row).model_dump(),
        id=row.id,
        content=_content_out(row.content),
        facts=FactsOut.model_validate(row.facts),
        rounds=[RoundOut.model_validate(item) for item in row.rounds],
        timeline=TimelineOut.model_validate(row.timeline),
    )


async def _state(session: AsyncSession, project: Project) -> MusicPlanState:
    state = await music_plan_service.state(session, project)
    job = state.job
    return MusicPlanState(
        latest=_plan_out(state.latest) if state.latest is not None else None,
        versions=[_version_out(row) for row in state.versions],
        job=(
            MusicPlanJobOut(
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
        critic_rounds=state.critic_rounds,
        timeline=(
            TimelineOut.model_validate(state.timeline) if state.timeline is not None else None
        ),
        themes=[ThemeRef(**item) for item in state.themes],
    )


# --- Endpoints -----------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/music-plan/run",
    response_model=MusicPlanRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_music_plan(
    project_id: int, session: SessionDep, body: MusicPlanRunIn | None = None
) -> MusicPlanRun:
    """Starts the job that writes the music plan and reviews it. If one is already waiting or
    running for the project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await music_plan_service.start_run(
            session,
            project,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except music_plan_service.MusicPlanError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return MusicPlanRun(job_id=job.id)


@router.get(
    "/projects/{project_id}/music-plan",
    response_model=MusicPlanState,
    responses=_NOT_FOUND,
)
async def get_music_plan(project_id: int, session: SessionDep) -> MusicPlanState:
    return await _state(session, await load_project(session, project_id))


@router.put(
    "/projects/{project_id}/music-plan",
    response_model=MusicPlanState,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_music_plan(
    project_id: int, body: MusicPlanSaveIn, session: SessionDep
) -> MusicPlanState:
    """Saves the whole edited plan as the next version, written by the owner."""
    project = await load_project(session, project_id)
    try:
        await music_plan_service.save_manual(session, project, _answer_of(body))
    except music_plan_service.MusicPlanError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return await _state(session, project)


@router.get(
    "/projects/{project_id}/music-plan/versions/{version}",
    response_model=MusicPlanOut,
    responses=_NOT_FOUND,
)
async def get_music_plan_version(
    project_id: int,
    version: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> MusicPlanOut:
    project = await load_project(session, project_id)
    row = await music_plan_service.get_version(session, project.id, version)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"The project has no music plan version {version}."
        )
    return _plan_out(row)
