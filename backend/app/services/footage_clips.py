"""The footage clip: the video of one piece of footage at its exact length (FTG-005,
`Footage_broll_implementation_phases.md` §4.10).

Two kinds of clip, both rows of `footage_clip` drawn by the job `render_footage_clip`:

- **The clip of a placed piece** (`purpose = 'piece'`, `placed_key` `{run}:{item_key}`): one for
  each piece `shot_plans` places over the shots of a scene (FTG-004), at the exact frames of its
  place on the scene's timeline, plus one spare frame as for every drawn clip. `piece_state` is
  where they stand, and `queue_piece_clip` makes one.
- **The preview** (`purpose = 'preview'`): a fixed `PREVIEW_S` seconds of one piece the owner chose
  to show, asked for from the mark card. A video preview is as long as the part of the video that
  plays when that is shorter. `queue_preview` makes one and `previews_for` reads the newest.

A clip is **current** when every entry of its look is what a clip made now would have: the file
(its SHA-256), the part of the video used and the moment chosen in it, the frames, the size, the
frame rate, the portrait crop, the clip version and, for a page or a PDF, the highlight's colour.
So a clip is drawn again only when its look changes, never because another mark did. Nothing here
is stored but the clips; every status is worked out on read.

Times: the owner's moved `use` is in seconds of the stored video. A capture's `use` and `moment_s`
are seconds of the *source* video, and the stored file starts at the capture's `window.start_s`,
so those two are moved back by it. `footage_item.cuts` is already in seconds of the stored video.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FootageClip, FootageItem, Job, Project
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    evidence_clips,
    footage_decisions,
    footage_marks,
    footage_placement,
    footage_video,
    frame_counts,
    shot_plans,
)

JOB_TYPE: Final = "render_footage_clip"
# `job.input` is `{footage_clip_id, preview_item_id}` for a preview and `{footage_clip_id,
# piece_ref}` for a piece. Two presses on one target make one job.
CLIP_KEY: Final = "footage_clip_id"
PREVIEW_DEDUPE_KEY: Final = "preview_item_id"
PIECE_DEDUPE_KEY: Final = "piece_ref"

PURPOSE_PREVIEW: Final = "preview"
PURPOSE_PIECE: Final = "piece"

# Recorded on every clip. A change to a composition or to the layout rules that changes how a clip
# looks raises it, so the clips made before read as out of date.
CLIP_VERSION: Final = 1
FPS: Final = evidence_clips.FPS
# The length of a preview (a video's is shorter when the part that plays is).
PREVIEW_S: Final = 6.0

KIND_VIDEO: Final = "video"
KIND_IMAGE: Final = "image"
KIND_PAGE: Final = "page"
KIND_PDF: Final = "pdf"
# A page and a PDF are drawn with the highlight, so their clips depend on its colour.
_CROPPED_KINDS: Final = (KIND_VIDEO, KIND_IMAGE)
_ACCENT_KINDS: Final = (KIND_PAGE, KIND_PDF)

NOT_SHOWN_MESSAGE: Final = "That file is not shown on its mark."
NOT_READY_MESSAGE: Final = "The file of this piece is not ready."
NO_MEDIA_MESSAGE: Final = "This piece has no picture or video to draw."
NO_USE_MESSAGE: Final = "The part of this video to show is not known."
UNKNOWN_PIECE_MESSAGE: Final = "There is no such footage piece in the newest shot plans."
PIECE_ALREADY_MADE_MESSAGE: Final = "The clip of this piece is already made."
SHOT_PLAN_OUT_OF_DATE_MESSAGE: Final = (
    "The shots of this scene are out of date. Plan them again first."
)

ClipStatus = Literal["none", "working", "ready", "failed", "out_of_date"]


class FootageClipError(ValueError):
    """A clip that cannot be made. The message is meant to be shown to the user."""


# --- What a clip is made from (pure) -----------------------------------------------------------


def piece_frames(start_s: float, end_s: float) -> int:
    """The frames of a placed piece's clip: its own length on the frame grid, and one spare frame
    as for any drawn clip."""
    return frame_counts.target_frames(start_s, end_s, FPS) + 1


def preview_frames(video_length_s: float | None) -> int:
    """The frames of a preview: `PREVIEW_S`, or the length of the video part that plays when it is
    shorter (`video_length_s`)."""
    seconds = PREVIEW_S if video_length_s is None else min(PREVIEW_S, video_length_s)
    return max(1, round(seconds * FPS))


def _number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _window_offset(capture: Any) -> float:
    """Where the stored video starts in the source video, 0 when the capture has no window (an
    owner's own video)."""
    window = capture.get("window") if isinstance(capture, dict) else None
    start = _number(window.get("start_s")) if isinstance(window, dict) else None
    return start if start is not None else 0.0


@dataclass(frozen=True)
class VideoTimes:
    """The part of the stored video that plays, `use_start_s` to `use_end_s`, and the instant the
    agent chose in it (None for an owner's video), all in seconds of the stored video."""

    use_start_s: float
    use_end_s: float
    moment_s: float | None

    @property
    def length_s(self) -> float:
        return round(self.use_end_s - self.use_start_s, 3)


def video_times(item: FootageItem, decided: Any) -> VideoTimes | None:
    """The times of a video piece, or None when it has no usable part to play. `decided` is the
    owner's moved `use` (seconds of the stored video), if any."""
    capture = item.capture if isinstance(item.capture, dict) else {}
    offset = _window_offset(capture)
    found = footage_decisions.use_range(decided, None)
    # The owner's moved `use` is already in seconds of the stored video; a capture's is not.
    use_offset = 0.0
    if found is None:
        found = footage_decisions.use_range(None, capture)
        use_offset = offset
    if found is None:
        return None
    moment = _number(capture.get("moment_s"))
    return VideoTimes(
        use_start_s=round(max(0.0, found[0] - use_offset), 3),
        use_end_s=round(max(0.0, found[1] - use_offset), 3),
        moment_s=None if moment is None else round(moment - offset, 3),
    )


def media_of(item: FootageItem) -> tuple[str, str] | None:
    """`(path, sha256)` of the file a clip is drawn from, or None when the piece has none."""
    if item.kind == KIND_VIDEO:
        path, sha = item.video_path, item.video_sha256
    elif item.kind in (KIND_IMAGE, KIND_PAGE, KIND_PDF):
        path, sha = item.image_path, item.image_sha256
    else:
        return None
    return (path, sha or "") if path else None


def look_for(
    item: FootageItem,
    *,
    frames: int,
    width: int,
    height: int,
    framing: str | None,
    accent: str,
    times: VideoTimes | None,
) -> dict[str, Any] | None:
    """What a clip of `frames` frames made now would be made with, or None when the piece has no
    file (or, for a video, no part to play). `accent` goes in only for a page or a PDF."""
    media = media_of(item)
    if media is None or item.kind is None:
        return None
    if item.kind == KIND_VIDEO and times is None:
        return None
    look: dict[str, Any] = {
        "kind": item.kind,
        "item_key": item.item_key,
        "media_sha256": media[1],
        "frames": frames,
        "width": width,
        "height": height,
        "fps": FPS,
        # The portrait crop only changes a video or a photo; a page or a PDF is never cropped.
        "framing": framing_of(framing) if item.kind in _CROPPED_KINDS else None,
        "clip_version": CLIP_VERSION,
    }
    if times is not None:
        look["use"] = [times.use_start_s, times.use_end_s]
        look["moment_s"] = times.moment_s
    if item.kind in _ACCENT_KINDS:
        look["accent"] = accent
    return look


def framing_of(value: object) -> str | None:
    """The owner's portrait crop of a mark when it is `left`, `centre` or `right`, else None."""
    return footage_video.crop_of(value)


def is_out_of_date(clip: FootageClip, look: dict[str, Any]) -> bool:
    """The clip was made with something other than `look`."""
    inputs = clip.inputs if isinstance(clip.inputs, dict) else {}
    return any(inputs.get(key) != value for key, value in look.items())


def _status(
    clip: FootageClip | None, job: Job | None, look: dict[str, Any] | None
) -> tuple[ClipStatus, str | None]:
    """`(status, last error)` of the newest clip of a target. Pure."""
    if clip is None:
        return "none", None
    if job is not None and job.status in store.ACTIVE_STATUSES:
        return "working", None
    if look is not None and is_out_of_date(clip, look):
        return ("out_of_date" if clip.media_path else "none"), None
    if clip.media_path and (job is None or job.status == "succeeded"):
        return "ready", None
    error = clip.last_error or (job.error if job is not None else None)
    return "failed", error or "The clip could not be drawn."


# --- Reading from the database -----------------------------------------------------------------


async def _items(session: AsyncSession, project: Project, keys: set[str]) -> dict[str, FootageItem]:
    """The newest row of each item key (a re-import may hold the same key again)."""
    if not keys:
        return {}
    statement = (
        select(FootageItem)
        .where(FootageItem.project_id == project.id, FootageItem.item_key.in_(keys))
        .order_by(FootageItem.id.desc())
        .execution_options(populate_existing=True)
    )
    found: dict[str, FootageItem] = {}
    for item in (await session.execute(statement)).scalars():
        found.setdefault(item.item_key, item)
    return found


async def _newest_clips(
    session: AsyncSession, project: Project, purpose: str
) -> dict[str, tuple[FootageClip, Job | None]]:
    """The newest clip of each target of this purpose: by `placed_key` for a piece, by the item's
    `item_key` for a preview."""
    statement = (
        select(FootageClip, Job, FootageItem.item_key)
        .join(FootageItem, FootageClip.item_id == FootageItem.id)
        .outerjoin(Job, FootageClip.render_job_id == Job.id)
        .where(FootageClip.project_id == project.id, FootageClip.purpose == purpose)
        .order_by(FootageClip.id.desc())
        .execution_options(populate_existing=True)
    )
    found: dict[str, tuple[FootageClip, Job | None]] = {}
    for clip, job, item_key in (await session.execute(statement)).all():
        key = clip.placed_key if purpose == PURPOSE_PIECE else item_key
        if key is not None:
            found.setdefault(key, (clip, job))
    return found


async def _decided(session: AsyncSession, project: Project) -> Any:
    row = await footage_decisions.latest(session, project.id)
    return row.content if row is not None else None


def _mark_decisions(content: Any, mark_id: str) -> tuple[str | None, dict[str, Any]]:
    """The owner's portrait crop of a mark and the `use` he moved, by item key."""
    entry = footage_decisions.mark_entry(content, mark_id)
    if entry is None:
        return None, {}
    return framing_of(entry["framing"]), entry["use"]


# --- The clips of the placed pieces ------------------------------------------------------------


@dataclass(frozen=True)
class PieceClipEntry:
    """One piece placed over a scene's shots, and where its clip stands."""

    scene_id: str
    # The scene's item, for its label on the board.
    scene_item: dict[str, Any]
    plan_id: int
    piece: footage_placement.PlacedPiece
    item: FootageItem | None
    frames: int
    # What a clip made now would be made with, or None when the piece cannot be drawn.
    look: dict[str, Any] | None
    status: ClipStatus
    clip: FootageClip | None
    job: Job | None
    last_error: str | None
    # Why the clip cannot be made now, or None.
    blocked_reason: str | None

    @property
    def done(self) -> bool:
        return self.status == "ready"

    @property
    def placed_key(self) -> str:
        return self.piece.key

    @property
    def ref(self) -> str:
        # A placed key already starts with its scene, so it names the piece on its own.
        return self.piece.key


@dataclass(frozen=True)
class PieceClipsState:
    """What the `footage_clips` step reads. `wanted` is False for a project without footage."""

    wanted: bool
    entries: list[PieceClipEntry]


def _blocked(
    entry: shot_plans.SceneEntry, item: FootageItem | None, look: dict[str, Any] | None
) -> str | None:
    if entry.status != "planned":
        return SHOT_PLAN_OUT_OF_DATE_MESSAGE
    if item is None or not item.usable:
        return NOT_READY_MESSAGE
    if media_of(item) is None:
        return NO_MEDIA_MESSAGE
    if look is None:
        return NO_USE_MESSAGE
    return None


@memoized_state
async def piece_state(session: AsyncSession, project: Project) -> PieceClipsState:
    """The clips of the footage placed over the shots of the newest plans, scene by scene. Worked
    out on every read; nothing here is stored but the clips. A project without footage reads no
    table."""
    if not footage_marks.wanted(project):
        return PieceClipsState(wanted=False, entries=[])
    plans = await shot_plans.state(session, project)
    placed = [(entry, piece) for entry in plans.entries for piece in entry.footage]
    if not placed:
        return PieceClipsState(wanted=True, entries=[])
    items = await _items(session, project, {piece.item_key for _, piece in placed})
    newest = await _newest_clips(session, project, PURPOSE_PIECE)
    content = await _decided(session, project)
    accent, _ = await evidence_clips.accent_for(session, project)

    entries: list[PieceClipEntry] = []
    for scene, piece in placed:
        item = items.get(piece.item_key)
        framing, moved = _mark_decisions(content, piece.mark_id)
        frames = piece_frames(piece.start_s, piece.end_s)
        look: dict[str, Any] | None = None
        if item is not None and item.usable:
            times = (
                video_times(item, moved.get(piece.item_key)) if item.kind == KIND_VIDEO else None
            )
            look = look_for(
                item,
                frames=frames,
                width=project.out_width,
                height=project.out_height,
                framing=framing,
                accent=accent,
                times=times,
            )
        clip, job = newest.get(piece.key, (None, None))
        status, error = _status(clip, job, look)
        entries.append(
            PieceClipEntry(
                scene_id=scene.item["id"],
                scene_item=scene.item,
                plan_id=scene.row.id if scene.row is not None else 0,
                piece=piece,
                item=item,
                frames=frames,
                look=look,
                status=status,
                clip=clip,
                job=job,
                last_error=error,
                blocked_reason=_blocked(scene, item, look),
            )
        )
    return PieceClipsState(wanted=True, entries=entries)


async def queue_piece_clip(session: AsyncSession, project: Project, placed_key: str) -> Job:
    """Queues the clip of one placed piece, at its exact length, and commits. A clip that is
    already waiting or running gives its job. Raises FootageClipError (with the reason) when the
    clip cannot be made now or is already made."""
    state = await piece_state(session, project)
    found = next((entry for entry in state.entries if entry.placed_key == placed_key), None)
    if found is None:
        raise FootageClipError(UNKNOWN_PIECE_MESSAGE)
    if found.status == "working" and found.job is not None:
        return found.job
    if found.status == "ready":
        raise FootageClipError(PIECE_ALREADY_MADE_MESSAGE)
    if found.blocked_reason is not None:
        raise FootageClipError(found.blocked_reason)
    assert found.item is not None and found.look is not None  # the refusal made sure

    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input={PIECE_DEDUPE_KEY: found.ref},
        commit=False,
        dedupe_key=PIECE_DEDUPE_KEY,
    )
    if not created:
        return job
    clip = FootageClip(
        project_id=project.id,
        purpose=PURPOSE_PIECE,
        item_id=found.item.id,
        scene_id=found.scene_id,
        placed_key=placed_key,
        shot_plan_id=found.plan_id or None,
        attempt=(found.clip.attempt + 1) if found.clip is not None else 1,
        inputs={
            "mark_id": found.piece.mark_id,
            "orientation": project.orientation,
            "length_s": round(found.frames / FPS, 3),
            **found.look,
        },
    )
    session.add(clip)
    await session.flush()
    job.input = {CLIP_KEY: clip.id, PIECE_DEDUPE_KEY: found.ref}
    clip.render_job_id = job.id
    await session.commit()
    return job


# --- Previews ----------------------------------------------------------------------------------


def _preview_look(
    project: Project, item: FootageItem, content: Any, accent: str
) -> dict[str, Any] | None:
    framing, moved = _mark_decisions(content, item.mark_id)
    times = video_times(item, moved.get(item.item_key)) if item.kind == KIND_VIDEO else None
    return look_for(
        item,
        frames=preview_frames(times.length_s if times is not None else None),
        width=project.out_width,
        height=project.out_height,
        framing=framing,
        accent=accent,
        times=times,
    )


async def queue_preview(session: AsyncSession, project: Project, item_key: str) -> Job:
    """Queues the preview of one piece shown on a mark, and commits. If a preview of that piece is
    already waiting or running, its job is returned. Raises FootageClipError (with the reason)
    when the piece cannot be previewed."""
    if not footage_marks.wanted(project):
        raise FootageClipError("Footage is not on for this project.")
    item = (await _items(session, project, {item_key})).get(item_key)
    content = await _decided(session, project)
    if item is None or item_key not in footage_decisions.shown_keys(content, item.mark_id):
        raise FootageClipError(NOT_SHOWN_MESSAGE)
    if not item.usable:
        raise FootageClipError(NOT_READY_MESSAGE)
    if media_of(item) is None:
        raise FootageClipError(NO_MEDIA_MESSAGE)
    accent, _ = await evidence_clips.accent_for(session, project)
    look = _preview_look(project, item, content, accent)
    if look is None:
        raise FootageClipError(NO_USE_MESSAGE)

    # The job first: when one for this piece is already active it is the answer, and nothing else
    # is written. The clip's id is put in the job's input once the clip exists, in the same
    # transaction, so the dispatcher never sees a job without it.
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input={PREVIEW_DEDUPE_KEY: item.id},
        commit=False,
        dedupe_key=PREVIEW_DEDUPE_KEY,
    )
    if not created:
        return job
    clip = FootageClip(
        project_id=project.id,
        purpose=PURPOSE_PREVIEW,
        item_id=item.id,
        inputs={
            "mark_id": item.mark_id,
            "orientation": project.orientation,
            "length_s": round(look["frames"] / FPS, 3),
            **look,
        },
    )
    session.add(clip)
    await session.flush()
    job.input = {CLIP_KEY: clip.id, PREVIEW_DEDUPE_KEY: item.id}
    clip.render_job_id = job.id
    await session.commit()
    return job


@dataclass(frozen=True)
class Preview:
    """The newest preview of a piece, as the mark card shows it."""

    clip_id: int
    job_id: int | None
    # `queued`, `running`, `succeeded`, `failed` or `cancelled`.
    status: str
    error: str | None
    media_path: str | None
    warnings: list[str]
    out_of_date: bool
    # The size the video was made at, which can differ from the project's size now.
    width: int
    height: int


def _warning_messages(warnings: Any) -> list[str]:
    return [
        entry["message"]
        for entry in (warnings if isinstance(warnings, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("message"), str)
    ]


async def previews_for(
    session: AsyncSession, project: Project, items: list[FootageItem]
) -> dict[str, Preview]:
    """The newest preview of each of `items` that has one, by `item_key`. A preview is out of
    date when its look is not the one a preview made now would have."""
    if not items or not footage_marks.wanted(project):
        return {}
    newest = await _newest_clips(session, project, PURPOSE_PREVIEW)
    wanted = [item for item in items if item.item_key in newest]
    if not wanted:
        return {}
    content = await _decided(session, project)
    accent, _ = await evidence_clips.accent_for(session, project)
    found: dict[str, Preview] = {}
    for item in wanted:
        clip, job = newest[item.item_key]
        job_status = (
            job.status if job is not None else ("succeeded" if clip.media_path else "failed")
        )
        look = _preview_look(project, item, content, accent)
        inputs = clip.inputs if isinstance(clip.inputs, dict) else {}
        found[item.item_key] = Preview(
            clip_id=clip.id,
            job_id=clip.render_job_id,
            status=job_status,
            error=clip.last_error or (job.error if job is not None else None),
            media_path=clip.media_path if job_status == "succeeded" else None,
            warnings=_warning_messages(clip.warnings),
            out_of_date=look is None or is_out_of_date(clip, look),
            width=int(inputs.get("width", project.out_width)),
            height=int(inputs.get("height", project.out_height)),
        )
    return found
