"""`/api/projects/{project_id}/story-renders`: the story's finished video (PHASE-028).

- `GET ...` answers everything the story workspace shows in one call: whether the story can be
  rendered now and why not, what the next render would warn about, the newest render job, and
  every finished render (newest first) with the video's address, what it measured, the takes it
  was made from, the loudness that was applied, and whether it is `current` or `out_of_date` (and
  why). Out of date is worked out on every read.
- `POST .../run` ("Render") starts the `render_story` job with the timeline as it is now. If a
  render is already waiting or running, that   job is returned and no second one is made.
- `GET .../{render_number}/captions.ytt` and `.../captions.srt` write a finished render's caption
  track as a YouTube caption file or a plain subtitle file (CAP-002, CAP-003). They are written
  when asked for and never stored.

A render is stored only when it succeeds (`services/story_renders.py`). The answers never return
ORM objects.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.discovery import DiscoveryJobOut
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import Job, Project, SceneRender, StoryRender
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import caption_plan, scene_renders, storage, story_renders
from app.services.caption_srt import srt_document
from app.services.caption_ytt import ytt_document
from app.services.story_renders import RenderEntry

router = APIRouter()

# A download's file name keeps only these; the project name is cut to this many characters.
_NOT_SAFE = re.compile(r"[^a-z0-9]+")
_SLUG_MAX = 60

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The story cannot be rendered now: a scene's shots are not ready, a shot "
        "has no clip, or a clip or a speech file is missing or too short.",
    }
}

Status = Literal["current", "out_of_date"]
WarningCode = Literal[
    "take_out_of_date",
    "take_without_sound",
    "caption_timing_estimated",
    "callout_at_unit_start",
    "callout_dropped",
    "shot_placeholder",
    "dialogue_not_heard",
    "scene_start_unknown",
]


class RenderWarningOut(BaseModel):
    code: WarningCode
    # The shot the warning is about. None for a warning about the whole render (the captions and
    # the callouts).
    scene_id: str | None = None
    shot_id: str | None = None
    message: str


class RenderGraphicOut(BaseModel):
    """The graphic a render used for a graphic shot (EXG-007): which attempt of which version."""

    id: int
    engine: Literal["generated_component", "remotion_blocks"]
    attempt: int


class RenderTakeOut(BaseModel):
    """The take a render used for one shot, or the graphic it used for a graphic shot (which has
    no take).
    """

    scene_id: str
    scene_index: int
    shot_id: str
    take_id: int | None
    take_number: int | None
    graphic: RenderGraphicOut | None
    # True when the render shows a placeholder for the shot (a scene render, SCN-003).
    placeholder: bool
    frames: int
    # The loudness measured over the part of the clip the shot uses, and the gain applied.
    sound: str | None
    loudness_lufs: float | None
    gain_db: float | None


class RenderNarrationOut(BaseModel):
    units: int
    loudness_lufs: float | None
    gain_db: float | None


class RenderMusicOut(BaseModel):
    """The music a render was made with (MUSIC-012). Only a render with music has it."""

    placement_version: int
    ambience: bool
    sounds: int
    # How many placed sounds were left out (the ambience switch, or a place outside the video).
    left_out: int
    # The layers that were made: `bed`, `score`, `sounds`.
    lanes: list[str]
    # The music was placed before every clip existed (a scene render, SCN-011), so
    # `placement_version` is 0.
    provisional: bool = False


class RenderMasterOut(BaseModel):
    """The finished loudness against its target (MUSIC-012). Only a render made with timeline
    version 2 has it.
    """

    target_lufs: float
    true_peak_db: float
    premaster_lufs: float | None
    premaster_true_peak_dbtp: float | None
    # False when the sound was too quiet or too short to measure, so it was left as it was.
    normalized: bool
    final_lufs: float | None
    final_true_peak_dbtp: float | None
    # One sentence for each miss of the target or the ceiling. Empty when both were met.
    notes: list[str]


class StoryRenderOut(BaseModel):
    id: int
    render_number: int
    status: Status
    # Why the render is out of date, one sentence each. Empty when it is current.
    reasons: list[str]
    url: str
    duration_s: float | None
    frame_count: int | None
    width: int | None
    height: int | None
    size_bytes: int
    has_audio: bool
    warnings: list[RenderWarningOut]
    takes: list[RenderTakeOut]
    narration: RenderNarrationOut | None
    music: RenderMusicOut | None
    master: RenderMasterOut | None
    # Whether the render has a caption track, so caption files can be downloaded (CAP-002).
    caption_file_available: bool
    # Whether the render draws its captions on the picture. False when it has no track.
    captions_burned: bool
    created_at: datetime
    job: DiscoveryJobOut | None


class SceneChangeOut(BaseModel):
    """A scene of the newest full render that differs from its newest scene render (SCN-013)."""

    scene_id: str
    scene_index: int
    title: str
    # False when the scene has no scene render at all (then `reasons` is empty).
    has_scene_render: bool
    # What differs, one sentence each. Music, captions, callouts and the mix are not compared.
    reasons: list[str]


class StoryRendersOut(BaseModel):
    can_render: bool
    # Why Render may not be pressed, or None.
    blocked_reason: str | None
    # What the next render would warn about. Empty when it cannot be made.
    warnings: list[RenderWarningOut]
    # How long the next render would be, or None when it cannot be made.
    planned_frames: int | None
    fps: int
    planned_seconds: float | None
    # The music placement version the next render would use, or None when it has no music.
    music_placement_version: int | None
    # Whether the next render leaves the beds and the point sounds out (the ambience switch).
    ambience_enabled: bool
    # The newest render job, whatever its status.
    job: DiscoveryJobOut | None
    renders: list[StoryRenderOut]
    # The scenes of the newest render that differ from their newest scene render, in story
    # order. Empty when there is no render yet.
    changed_scenes: list[SceneChangeOut]


class StoryRenderRunOut(BaseModel):
    job_id: int


def job_out(job: Job | None) -> DiscoveryJobOut | None:
    if job is None:
        return None
    return DiscoveryJobOut(
        id=job.id,
        status=cast(JobStatus, job.status),
        phase=job.phase,
        error=job.error,
    )


def warning_out(warning: dict[str, Any]) -> RenderWarningOut:
    return RenderWarningOut(
        code=warning["code"],
        scene_id=warning.get("scene_id"),
        shot_id=warning.get("shot_id"),
        message=warning["message"],
    )


def takes_out(row: StoryRender | SceneRender) -> list[RenderTakeOut]:
    """The take of each shot, from what the render recorded (never from the shots now)."""
    levels = {
        (item.get("scene_id"), item.get("shot_id")): item
        for item in (row.levels or {}).get("shots", [])
        if isinstance(item, dict)
    }
    takes: list[RenderTakeOut] = []
    for shot in row.inputs.get("shots", []):
        level = levels.get((shot["scene_id"], shot["shot_id"]), {})
        takes.append(
            RenderTakeOut(
                scene_id=shot["scene_id"],
                scene_index=shot["scene_index"],
                shot_id=shot["shot_id"],
                take_id=shot["take_id"],
                take_number=shot["take_number"],
                graphic=(
                    RenderGraphicOut.model_validate(shot["graphic"])
                    if isinstance(shot.get("graphic"), dict)
                    else None
                ),
                placeholder=isinstance(shot.get("placeholder"), dict),
                frames=shot["frames"],
                sound=level.get("sound"),
                loudness_lufs=level.get("loudness_lufs"),
                gain_db=level.get("gain_db"),
            )
        )
    return takes


def narration_out(row: StoryRender | SceneRender) -> RenderNarrationOut | None:
    narration = (row.levels or {}).get("narration")
    if not isinstance(narration, dict):
        return None
    return RenderNarrationOut(
        units=narration["units"],
        loudness_lufs=narration.get("loudness_lufs"),
        gain_db=narration.get("gain_db"),
    )


def _provisional_music(row: StoryRender | SceneRender) -> bool:
    """Whether the render's music was placed before every clip existed (SCN-011): the frozen
    timeline carries what it was placed from.
    """
    timeline = row.inputs if isinstance(row.inputs, dict) else {}
    music = timeline.get("music")
    return isinstance(music, dict) and isinstance(music.get("provisional"), dict)


def music_out(row: StoryRender | SceneRender) -> RenderMusicOut | None:
    music = (row.levels or {}).get("music")
    if not isinstance(music, dict):
        return None
    lanes = music.get("lanes")
    return RenderMusicOut(
        placement_version=music["placement_version"],
        ambience=music["ambience"],
        sounds=music["sounds"],
        left_out=music.get("left_out", 0),
        lanes=list(lanes) if isinstance(lanes, dict) else [],
        provisional=_provisional_music(row),
    )


def master_out(row: StoryRender | SceneRender) -> RenderMasterOut | None:
    master = (row.levels or {}).get("master")
    if not isinstance(master, dict):
        return None
    return RenderMasterOut(
        target_lufs=master["target_lufs"],
        true_peak_db=master["true_peak_db"],
        premaster_lufs=master.get("premaster_lufs"),
        premaster_true_peak_dbtp=master.get("premaster_true_peak_dbtp"),
        normalized=bool(master.get("normalized")),
        final_lufs=master.get("final_lufs"),
        final_true_peak_dbtp=master.get("final_true_peak_dbtp"),
        notes=[str(note) for note in master.get("notes") or []],
    )


def _recorded_captions(row: StoryRender) -> dict[str, Any] | None:
    """The caption track the render recorded, as stored (not read), or None."""
    timeline = row.inputs if isinstance(row.inputs, dict) else {}
    captions = timeline.get("captions")
    return captions if isinstance(captions, dict) else None


def _render_out(entry: RenderEntry) -> StoryRenderOut:
    row = entry.row
    captions = _recorded_captions(row)
    return StoryRenderOut(
        id=row.id,
        render_number=row.render_number,
        status=entry.status,
        reasons=entry.reasons,
        url=storage.media_url(row.path),
        duration_s=row.duration_s,
        frame_count=row.frame_count,
        width=row.width,
        height=row.height,
        size_bytes=row.size_bytes,
        has_audio=row.audio is not None,
        warnings=[warning_out(item) for item in row.inputs.get("warnings", [])],
        takes=takes_out(row),
        narration=narration_out(row),
        music=music_out(row),
        master=master_out(row),
        caption_file_available=captions is not None,
        # A track with no `burned` key is from before CAP-001 and was burned.
        captions_burned=captions is not None and captions.get("burned", True) is True,
        created_at=row.created_at,
        job=job_out(entry.job),
    )


@router.get(
    "/projects/{project_id}/story-renders",
    response_model=StoryRendersOut,
    responses=_NOT_FOUND,
)
async def get_story_renders(project_id: int, session: SessionDep) -> StoryRendersOut:
    project = await load_project(session, project_id)
    result = await story_renders.state(session, project)
    changes: list[scene_renders.SceneChange] = []
    if result.renders and isinstance(result.renders[0].row.inputs, dict):
        changes = await scene_renders.changed_scenes(
            session, project.id, result.renders[0].row.inputs
        )
    return StoryRendersOut(
        can_render=result.can_render,
        blocked_reason=result.blocked_reason,
        warnings=[warning_out(item) for item in result.warnings],
        planned_frames=result.planned_frames,
        fps=result.fps,
        planned_seconds=(
            round(result.planned_frames / result.fps, 3)
            if result.planned_frames is not None
            else None
        ),
        music_placement_version=result.music_placement_version,
        ambience_enabled=result.ambience_enabled,
        job=job_out(result.job),
        renders=[_render_out(entry) for entry in result.renders],
        changed_scenes=[
            SceneChangeOut(
                scene_id=change.scene_id,
                scene_index=change.index,
                title=change.title,
                has_scene_render=change.has_render,
                reasons=change.reasons,
            )
            for change in changes
        ],
    )


@router.post(
    "/projects/{project_id}/story-renders/run",
    response_model=StoryRenderRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_render(project_id: int, session: SessionDep) -> StoryRenderRunOut:
    """Starts the job that renders the story. If a render is already waiting or running, that
    job's id is returned and no second render is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await story_renders.start_render(session, project)
    except story_renders.StoryRendersError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dispatcher.nudge()
    return StoryRenderRunOut(job_id=job.id)


def _file_stem(project: Project, render_number: int) -> str:
    """A file name for a download, from the project's name and the render number. Only letters,
    digits and hyphens are kept, so it needs no escaping in a header.
    """
    ascii_name = unicodedata.normalize("NFKD", project.name).encode("ascii", "ignore").decode()
    slug = _NOT_SAFE.sub("-", ascii_name.lower()).strip("-")[:_SLUG_MAX].strip("-")
    return f"{slug or f'project-{project.id}'}-render-{render_number}"


async def _render_track(
    session: AsyncSession, project: Project, render_number: int
) -> caption_plan.CaptionTrack:
    """The caption track a finished render recorded. Raises 404 when the render does not exist
    or has no track, and 422 when the recorded track cannot be read.
    """
    row = await story_renders.find_render(session, project.id, render_number)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such render.")
    try:
        track = caption_plan.parse_track(_recorded_captions(row))
    except caption_plan.CaptionError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The caption track of this render cannot be read: {exc}.",
        ) from exc
    if track is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This render has no caption track. Render it again to get caption files.",
        )
    return track


@router.get(
    "/projects/{project_id}/story-renders/{render_number}/captions.ytt",
    response_class=Response,
    responses={
        200: {
            "content": {"application/xml": {"schema": {"type": "string"}}},
            "description": "The YouTube caption file (YTT) of the render.",
        },
        404: {
            "model": ErrorResponse,
            "description": "No such project or render, or the render has no caption track.",
        },
        422: {
            "model": ErrorResponse,
            "description": "The caption track recorded with the render cannot be read.",
        },
    },
)
async def get_captions_ytt(project_id: int, render_number: int, session: SessionDep) -> Response:
    """The render's caption track as a YouTube caption file, written now from the frozen track
    (nothing is stored). It has the words and timing of the burned-in captions.
    """
    project = await load_project(session, project_id)
    track = await _render_track(session, project, render_number)
    filename = f"{_file_stem(project, render_number)}.ytt"
    return Response(
        content=ytt_document(track).encode("utf-8"),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/projects/{project_id}/story-renders/{render_number}/captions.srt",
    response_class=Response,
    responses={
        200: {
            "content": {"application/x-subrip": {"schema": {"type": "string"}}},
            "description": "The subtitle file (SRT) of the render.",
        },
        404: {
            "model": ErrorResponse,
            "description": "No such project or render, or the render has no caption track.",
        },
        422: {
            "model": ErrorResponse,
            "description": "The caption track recorded with the render cannot be read.",
        },
    },
)
async def get_captions_srt(project_id: int, render_number: int, session: SessionDep) -> Response:
    """The render's caption track as a plain SRT file, written now from the frozen track (nothing
    is stored). Its lines are sentence-sized, in the script's own casing and punctuation.
    """
    project = await load_project(session, project_id)
    track = await _render_track(session, project, render_number)
    filename = f"{_file_stem(project, render_number)}.srt"
    return Response(
        content=srt_document(track).encode("utf-8"),
        media_type="application/x-subrip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
