"""`/api/projects/{project_id}/music-placement`: the music placement stage (MUSIC-011).

- `POST .../run` starts the `place_music` job: every selected music take gets its exact place on
  the finished video's timeline, with its fades and joins. The job asks the language model at
  most once, to choose among real moments when code cannot.
- `GET ...` answers everything the story workspace shows for the stage in one call: the newest
  version, the list of versions, the newest job and why the newest version is out of date.
  "Out of date" is worked out on every read.
- `GET .../versions/{version}` answers one older (or the newest) version.

The rows and the job are made by `app/services/music_placement.py`. The answers never return ORM
objects. Positions are samples at `sample_rate` (48 kHz); the seconds beside them are for
reading. The placement is not edited in this phase.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import MusicPlacement, Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import music_placement as music_placement_service

router = APIRouter()

# SQLite integers are 64-bit. Larger numbers cannot exist, and must not reach the database.
_MAX_INT = 2**63 - 1

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or version."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "Music is off, or something the placement needs is not ready.",
    }
}


# --- What a placement holds ----------------------------------------------------------------


class PlacementFadeOut(BaseModel):
    samples: int
    shape: str


class PlacementEdgeOut(BaseModel):
    """Where a score or ambience cue starts or stops being heard, and how it was found."""

    nominal_s: float
    chosen_s: float
    chosen_sample: int
    # What the point is: a cut, a pause, a hit, a quiet fade, a swell of a bed, the planned second.
    kind: str
    description: str
    # 0 found in the window, 1 widened, 2 gentler technique, 3 covered, 4 the model chose,
    # 5 flagged.
    ladder_step: int
    flagged: bool
    covered: bool
    technique: str
    chosen_by: str
    notes: list[str]
    inside_speech: bool


class PlacementMomentOut(BaseModel):
    """Where a hit or a point sound lands."""

    nominal_s: float
    chosen_s: float
    kind: str
    description: str
    ladder_step: int
    chosen_by: str
    notes: list[str]
    moment_sample: int
    source_peak_sample: int


class PlacementJoinPartnerOut(BaseModel):
    cue_id: str
    type: str


class PlacedSoundOut(BaseModel):
    item_id: str
    cue_id: str
    role: str
    kind: str
    summary: str
    take_id: int
    lab_run_id: int | None
    sha256: str
    duration_s: float
    # `score`, `bed` or `sounds`.
    lane: str
    story_start_sample: int
    source_in_sample: int
    source_out_sample: int
    length_samples: int
    fade_in: PlacementFadeOut
    fade_out: PlacementFadeOut
    match_gain_db: float
    start: PlacementEdgeOut | None
    end: PlacementEdgeOut | None
    moment: PlacementMomentOut | None
    join_in: PlacementJoinPartnerOut | None
    join_out: PlacementJoinPartnerOut | None
    slide_s: float
    slide_reason: str | None
    back_timed: bool
    fallbacks: list[str]
    notes: list[str]


class PlacementJoinOut(BaseModel):
    from_cue: str
    to_cue: str
    type: str
    made_as: str
    point_s: float
    length_s: float
    ladder_step: int
    notes: list[str]


class PlacementH3SoundOut(BaseModel):
    cue_id: str
    summary: str
    shot: str
    event: str
    nominal_s: float
    chosen_s: float
    kind: str
    ladder_step: int
    description: str


class PlacementMixRequestOut(BaseModel):
    kind: str
    cue_id: str
    second: float
    length_s: float
    reason: str


class PlacementChoiceOut(BaseModel):
    id: str
    cue_id: str
    edge: str
    picked: str
    important: bool
    reason: str


class PlacementFlagOut(BaseModel):
    cue_id: str
    item_id: str | None
    edge: str
    second: float
    message: str


class PlacementInsideSpeechOut(BaseModel):
    cue_id: str
    edge: str
    second: float
    flagged: bool


class PlacementFactsOut(BaseModel):
    placed: int
    # Starts and stops inside a spoken word (expected empty, or flagged).
    inside_speech: list[PlacementInsideSpeechOut]
    model_asked: int
    model_failed: str | None
    unmeasured: list[str]


class PlacementSceneSpanOut(BaseModel):
    ref: str
    title: str
    start_s: float
    end_s: float


class PlacementSpeechSpanOut(BaseModel):
    ref: str
    kind: str
    start_s: float
    end_s: float


class PlacementTimelineOut(BaseModel):
    """The scenes, speech and shot cuts the placement was made on, in seconds."""

    total_s: float
    scenes: list[PlacementSceneSpanOut]
    speech: list[PlacementSpeechSpanOut]
    cuts_s: list[float]


class MusicPlacementContent(BaseModel):
    sample_rate: int
    total_samples: int
    # The settings and fixed values the placement used.
    constants: dict[str, float]
    placements: list[PlacedSoundOut]
    joins: list[PlacementJoinOut]
    h3_sounds: list[PlacementH3SoundOut]
    mix_requests: list[PlacementMixRequestOut]
    choices: list[PlacementChoiceOut]
    flags: list[PlacementFlagOut]
    facts: PlacementFactsOut
    timeline: PlacementTimelineOut


class MusicPlacementVersionOut(BaseModel):
    version: int
    plan_id: int
    job_id: int | None
    created_at: datetime


class MusicPlacementOut(MusicPlacementVersionOut):
    id: int
    content: MusicPlacementContent


class MusicPlacementJobOut(BaseModel):
    """The newest `place_music` job of the project, whatever its status."""

    id: int
    status: JobStatus
    phase: str | None
    error: str | None


class MusicPlacementState(BaseModel):
    latest: MusicPlacementOut | None
    versions: list[MusicPlacementVersionOut]
    job: MusicPlacementJobOut | None
    # Only the newest version is judged. False when there is no version.
    out_of_date: bool
    # One sentence for each thing the newest version was built from that has changed.
    reasons: list[str]
    # Why the music cannot be placed now, or None.
    blocked_reason: str | None
    music_enabled: bool
    # The plan has no cue that needs a recording: there is nothing to place.
    nothing_to_place: bool


class MusicPlacementRun(BaseModel):
    job_id: int


# --- Mapping rows to answers ---------------------------------------------------------------


def _partner(value: dict[str, Any] | None) -> PlacementJoinPartnerOut | None:
    if value is None:
        return None
    return PlacementJoinPartnerOut(cue_id=value["with"], type=value["type"])


def _placement_out(item: dict[str, Any]) -> PlacedSoundOut:
    fields = {key: value for key, value in item.items() if key not in ("join_in", "join_out")}
    return PlacedSoundOut.model_validate(
        {
            **fields,
            "slide_reason": item.get("slide_reason"),
            "moment": item.get("moment"),
            "join_in": _partner(item.get("join_in")),
            "join_out": _partner(item.get("join_out")),
        }
    )


def _join_out(item: dict[str, Any]) -> PlacementJoinOut:
    return PlacementJoinOut.model_validate(
        {"made_as": item["type"], **item, "from_cue": item["from"], "to_cue": item["to"]}
    )


def _content_out(content: dict[str, Any]) -> MusicPlacementContent:
    return MusicPlacementContent(
        sample_rate=content["sample_rate"],
        total_samples=content["total_samples"],
        constants={key: float(value) for key, value in content["constants"].items()},
        placements=[_placement_out(item) for item in content["placements"]],
        joins=[_join_out(item) for item in content["joins"]],
        h3_sounds=[PlacementH3SoundOut.model_validate(item) for item in content["h3_sounds"]],
        mix_requests=[
            PlacementMixRequestOut.model_validate(item) for item in content["mix_requests"]
        ],
        choices=[PlacementChoiceOut.model_validate(item) for item in content["choices"]],
        flags=[
            PlacementFlagOut.model_validate({"item_id": None, **item}) for item in content["flags"]
        ],
        facts=PlacementFactsOut.model_validate(content["facts"]),
        timeline=PlacementTimelineOut.model_validate(content["timeline"]),
    )


def _version_out(row: MusicPlacement) -> MusicPlacementVersionOut:
    return MusicPlacementVersionOut(
        version=row.version, plan_id=row.plan_id, job_id=row.job_id, created_at=row.created_at
    )


def _placement_row_out(row: MusicPlacement) -> MusicPlacementOut:
    return MusicPlacementOut(
        **_version_out(row).model_dump(), id=row.id, content=_content_out(row.content)
    )


async def _state(session: AsyncSession, project: Project) -> MusicPlacementState:
    state = await music_placement_service.state(session, project)
    job = state.job
    return MusicPlacementState(
        latest=_placement_row_out(state.latest) if state.latest is not None else None,
        versions=[_version_out(row) for row in state.versions],
        job=(
            MusicPlacementJobOut(
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
        blocked_reason=state.blocked_reason,
        music_enabled=state.music_enabled,
        nothing_to_place=state.nothing_to_place,
    )


# --- Endpoints -----------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/music-placement/run",
    response_model=MusicPlacementRun,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_music_placement(project_id: int, session: SessionDep) -> MusicPlacementRun:
    """Starts the job that places the music. If one is already waiting or running for the
    project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await music_placement_service.start_run(session, project)
    except music_placement_service.MusicPlacementError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return MusicPlacementRun(job_id=job.id)


@router.get(
    "/projects/{project_id}/music-placement",
    response_model=MusicPlacementState,
    responses=_NOT_FOUND,
)
async def get_music_placement(project_id: int, session: SessionDep) -> MusicPlacementState:
    return await _state(session, await load_project(session, project_id))


@router.get(
    "/projects/{project_id}/music-placement/versions/{version}",
    response_model=MusicPlacementOut,
    responses=_NOT_FOUND,
)
async def get_music_placement_version(
    project_id: int,
    version: Annotated[int, Path(ge=1, le=_MAX_INT)],
    session: SessionDep,
) -> MusicPlacementOut:
    project = await load_project(session, project_id)
    row = await music_placement_service.get_version(session, project.id, version)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"The project has no music placement version {version}."
        )
    return _placement_row_out(row)
