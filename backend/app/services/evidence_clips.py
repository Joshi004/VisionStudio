"""The evidence clip: the video of one piece of evidence, zoomed to its quote (EVD-008,
`Evidence_layer_implementation_phases.md` §4.7).

EVD-008 made the **preview** (`evidence_clip.purpose = 'preview'`): from the review screen the
owner asks for a short video of an accepted piece, and watches how it will look. EVD-009 makes the
**shot clips** (`purpose = 'shot'`): one clip for each evidence shot of the cut plan, at the exact
length of the shot, with the same job and the same layout.

- `queue_preview` makes the `evidence_clip` row and the `render_evidence_clip` job for one accepted
  piece. A second press while one is waiting or running returns the same job.
- `shot_state` is where the clips of the evidence shots stand, scene by scene (EVD-009), and
  `queue_shot_clip` makes one. A clip is current when it shows the piece the shot names, has the
  shot's frame count and was made with the project's size and accent now: it does not depend on
  the plan's row, so a new plan that keeps a shot as it was keeps its clip.
- `previews_for` reads the newest preview of each piece, by `item_key`, so that a preview survives
  a re-import that did not change the piece.
- `accent_for` is the colour of the highlight: the graphics look's accent when the project has one,
  else the callout plan's accent (the colour of the captions' highlight), else the captions'
  highlight colour.
- `resolved_for` is the `resolved` of the motion service's request. The geometry is in
  `evidence_clip_layout.py`.

The agent's text (publisher, date) reaches the video only as text on a badge, cut short.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Literal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvidenceClip, EvidenceItem, Job, Project
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    callout_plan,
    caption_plan,
    evidence_claims,
    evidence_clip_layout,
    evidence_import,
    evidence_review,
    evidence_rounds,
    graphic_theme,
    graphics_lab,
    scene_timeline,
    shot_plans,
)

JOB_TYPE: Final = "render_evidence_clip"
# `job.input` is `{evidence_clip_id, preview_item_id}`. Two presses on one piece make one job.
CLIP_KEY: Final = "evidence_clip_id"
DEDUPE_KEY: Final = "preview_item_id"

PURPOSE_PREVIEW: Final = "preview"
# The clip of an evidence shot (EVD-009). Its job's input is `{evidence_clip_id, shot_clip_ref}`,
# and two presses on one shot make one job.
PURPOSE_SHOT: Final = "shot"
SHOT_DEDUPE_KEY: Final = "shot_clip_ref"
# Recorded on every clip. A change to the composition or the layout rules that changes how a clip
# looks raises it, so the previews made before read as out of date.
CLIP_VERSION: Final = 1
FPS: Final = graphics_lab.FPS
# What shows around the screenshot when the camera goes past its edge and the context.
BACKGROUND: Final = "#14181F"

SOURCE_THEME: Final = "graphic_theme"
SOURCE_CALLOUT_PLAN: Final = "callout_plan"
SOURCE_DEFAULT: Final = "default"

NOT_ACCEPTED_MESSAGE: Final = "Only an accepted piece of evidence can be previewed."
UNKNOWN_ITEM_MESSAGE: Final = "There is no such piece of evidence in the newest import."
NO_PICTURE_MESSAGE: Final = "This piece of evidence has no picture to draw."

_COLOUR: Final = re.compile(r"#[0-9A-Fa-f]{6}")
_MONTHS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_PUBLISHER_MAX_CHARS: Final = 60
_DATE_MAX_CHARS: Final = 20


# --- What a clip is made from (pure) -------------------------------------------------------


def _colour(value: object) -> str | None:
    return value.upper() if isinstance(value, str) and _COLOUR.fullmatch(value) else None


def _clean(value: object, limit: int) -> str | None:
    """One line of printable text, cut to `limit` characters, or None. The agent's text is never
    trusted further than this."""
    if not isinstance(value, str):
        return None
    text = " ".join("".join(char for char in value if char.isprintable() or char.isspace()).split())
    return text[:limit].rstrip() or None


def format_date(value: object) -> str | None:
    """A publication date as `3 Oct 2026` when it is an ISO date, else the text cut short."""
    text = _clean(value, _DATE_MAX_CHARS)
    if text is None:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return text
    return f"{parsed.day} {_MONTHS[parsed.month - 1]} {parsed.year}"


def badge_of(item: EvidenceItem) -> dict[str, Any]:
    """The source badge: `{publisher, date, page}`. The publisher falls back to the address's
    host, then to "Source". The page is for a PDF."""
    source = item.source if isinstance(item.source, dict) else {}
    publisher = _clean(source.get("publisher"), _PUBLISHER_MAX_CHARS)
    if publisher is None:
        for key in ("final_url", "url"):
            address = source.get(key)
            host = urlparse(address).hostname if isinstance(address, str) else None
            if host:
                publisher = _clean(host.removeprefix("www."), _PUBLISHER_MAX_CHARS)
                break
    capture = item.capture if isinstance(item.capture, dict) else {}
    page = capture.get("page")
    return {
        "publisher": publisher or "Source",
        "date": format_date(source.get("published")),
        "page": page if item.kind == "pdf" and isinstance(page, int) and page > 0 else None,
    }


def resolved_for(
    plan: evidence_clip_layout.ClipPlan,
    *,
    accent: str,
    badge: dict[str, Any],
    context_box: evidence_clip_layout.Box | None,
) -> dict[str, Any]:
    """The `resolved` of the motion service's request for an evidence clip. `context_box` is where
    the (cropped) context image sits in the world, or None when it is not sent. Pure."""
    geometry = plan.geometry
    safe, caption = evidence_clip_layout.safe_and_caption(plan.width, plan.height)
    line = plan.timeline
    return {
        "width": plan.width,
        "height": plan.height,
        "fps": plan.fps,
        "frames": plan.frames,
        "accent": accent,
        "background": BACKGROUND,
        "fonts": dict(graphics_lab.FONTS),
        "safe_area": safe,
        "caption_zone": caption,
        "image_box": [0, 0, geometry.image_w, geometry.image_h],
        "context_box": list(context_box) if context_box is not None else None,
        "start": list(plan.start),
        "end": list(plan.end),
        "rects": [list(rect) for rect in geometry.rects],
        "timeline": {
            "zoom_start": line.zoom_start,
            "zoom_end": line.zoom_end,
            "sweep_start": line.sweep_start,
            "sweep_end": line.sweep_end,
        },
        "badge_box": list(plan.badge),
        "badge": badge,
    }


def small_text_warning(plan: evidence_clip_layout.ClipPlan) -> dict[str, str] | None:
    """The `small_text` warning of a clip whose quote is too small to read, or None. Pure."""
    if plan.readable:
        return None
    return {
        "code": "small_text",
        "message": (
            f"The quote's text is {plan.text_height_px:.0f} px tall on the {plan.width} x "
            f"{plan.height} frame; at least {plan.min_text_height_px:.0f} px is needed to read it."
        ),
    }


# --- The accent ----------------------------------------------------------------------------


async def accent_for(session: AsyncSession, project: Project) -> tuple[str, str]:
    """The highlight's colour and where it came from: the graphics look's accent, else the callout
    plan's accent, else the captions' highlight colour."""
    if graphic_theme.wanted(project):
        theme = await graphic_theme.latest(session, project.id)
        content = theme.content if theme is not None else None
        inner = content.get("theme") if isinstance(content, dict) else None
        accent = _colour(inner.get("accent")) if isinstance(inner, dict) else None
        if accent is not None:
            return accent, SOURCE_THEME
    if project.callouts:
        plan = await callout_plan.latest(session, project.id)
        content = plan.content if plan is not None else None
        raw = content.get("accent") if isinstance(content, dict) else None
        accent = _colour(raw.get("colour") if isinstance(raw, dict) else raw)
        if accent is not None:
            return accent, SOURCE_CALLOUT_PLAN
    return caption_plan.HIGHLIGHT_COLOUR, SOURCE_DEFAULT


def preview_frames() -> int:
    return round(evidence_clip_layout.PREVIEW_S * FPS)


async def current_look(
    session: AsyncSession, project: Project, frames: int | None = None
) -> dict[str, Any]:
    """What a clip made now would be made with: a preview's length, or the `frames` of an evidence
    shot. A stored clip that differs is out of date.
    """
    accent, source = await accent_for(session, project)
    return {
        "width": project.out_width,
        "height": project.out_height,
        "fps": FPS,
        "frames": preview_frames() if frames is None else frames,
        "accent": accent,
        "accent_source": source,
        "clip_version": CLIP_VERSION,
    }


_LOOK_KEYS: Final = ("width", "height", "fps", "frames", "accent", "clip_version")


# --- Starting a preview --------------------------------------------------------------------


async def queue_preview(session: AsyncSession, project: Project, item_key: str) -> Job:
    """Queues the preview of one accepted piece of the newest import, and commits. If a preview of
    that piece is already waiting or running, its job is returned. Raises EvidenceReviewError
    (with the reason) when the piece cannot be previewed, and ImportRunningError while an import
    is going on.
    """
    view = await evidence_review.view(session, project)
    if view.import_id is None:
        raise evidence_review.EvidenceReviewError(
            view.blocked_reason or evidence_review.NO_IMPORT_MESSAGE
        )
    found: tuple[evidence_review.ReviewClaim, EvidenceItem] | None = None
    for claim in view.claims:
        for item in claim.items:
            if item.item_key == item_key:
                found = (claim, item)
    if found is None:
        raise evidence_review.EvidenceReviewError(UNKNOWN_ITEM_MESSAGE)
    claim, item = found
    if not item.usable or claim.decision.verdicts.get(item_key) != evidence_review.ACCEPTED:
        raise evidence_review.EvidenceReviewError(NOT_ACCEPTED_MESSAGE)
    if not item.image_path:
        raise evidence_review.EvidenceReviewError(NO_PICTURE_MESSAGE)
    import_job = await store.latest_job(session, project.id, evidence_import.JOB_TYPE)
    if import_job is not None and import_job.status in store.ACTIVE_STATUSES:
        raise evidence_review.ImportRunningError(evidence_review.IMPORT_RUNNING_MESSAGE)

    look = await current_look(session, project)
    # The job first: when one for this piece is already active it is the answer, and nothing else
    # is written. The clip's id is put in the job's input once the clip exists, in the same
    # transaction, so the dispatcher never sees a job without it.
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input={DEDUPE_KEY: item.id},
        commit=False,
        dedupe_key=DEDUPE_KEY,
    )
    if not created:
        return job
    clip = EvidenceClip(
        project_id=project.id,
        purpose=PURPOSE_PREVIEW,
        item_id=item.id,
        inputs={
            "items": [item_key],
            "item_ids": [item.id],
            "orientation": project.orientation,
            "length_s": evidence_clip_layout.PREVIEW_S,
            **look,
        },
    )
    session.add(clip)
    await session.flush()
    job.input = {CLIP_KEY: clip.id, DEDUPE_KEY: item.id}
    clip.render_job_id = job.id
    await session.commit()
    return job


# --- Reading previews ----------------------------------------------------------------------


@dataclass(frozen=True)
class Preview:
    """The newest preview of a piece, as the review screen shows it."""

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


def _is_out_of_date(clip: EvidenceClip, look: dict[str, Any]) -> bool:
    inputs = clip.inputs if isinstance(clip.inputs, dict) else {}
    return any(inputs.get(key) != look[key] for key in _LOOK_KEYS)


async def previews_for(
    session: AsyncSession, project: Project, item_keys: list[str]
) -> dict[str, Preview]:
    """The newest preview of each piece that has one, by `item_key`."""
    if not item_keys:
        return {}
    statement = (
        select(EvidenceClip, EvidenceItem.item_key, Job.status, Job.error)
        .join(EvidenceItem, EvidenceClip.item_id == EvidenceItem.id)
        .outerjoin(Job, EvidenceClip.render_job_id == Job.id)
        .where(
            EvidenceClip.project_id == project.id,
            EvidenceClip.purpose == PURPOSE_PREVIEW,
            EvidenceItem.item_key.in_(item_keys),
        )
        .order_by(EvidenceClip.id.desc())
    )
    rows = (await session.execute(statement)).all()
    if not rows:
        return {}
    look = await current_look(session, project)
    found: dict[str, Preview] = {}
    for clip, item_key, job_status, job_error in rows:
        if item_key in found:
            continue
        if job_status is None:
            job_status = "succeeded" if clip.media_path else "failed"
        found[item_key] = Preview(
            clip_id=clip.id,
            job_id=clip.render_job_id,
            status=job_status,
            error=clip.last_error or job_error,
            media_path=clip.media_path if job_status == "succeeded" else None,
            warnings=_warning_messages(clip.warnings),
            out_of_date=_is_out_of_date(clip, look),
            width=int(clip.inputs.get("width", look["width"])),
            height=int(clip.inputs.get("height", look["height"])),
        )
    return found


# --- The clips of the evidence shots (EVD-009) -----------------------------------------------

UNKNOWN_SHOT_MESSAGE: Final = "There is no such evidence shot in the newest shot plan."
SHOT_PLAN_OUT_OF_DATE_MESSAGE: Final = (
    "The shots of this scene are out of date. Plan them again first."
)
PIECE_GONE_MESSAGE: Final = (
    "This piece of evidence is not in the newest import any more. Plan the shots again."
)
NO_LENGTH_MESSAGE: Final = "The length of this shot is not known yet."
ALREADY_MADE_MESSAGE: Final = "The clip of this shot is already made."

ShotClipStatus = Literal["none", "working", "ready", "failed", "out_of_date"]


class EvidenceClipError(ValueError):
    """A shot clip that cannot be made. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class ShotClipEntry:
    """One evidence shot of a scene's newest plan and where its clip stands."""

    shot: dict[str, Any]
    plan_id: int
    claim_id: str
    piece: int
    item_key: str
    # The piece's row in the newest import, or None when it is not there (any more).
    item: EvidenceItem | None
    # The clip's length: the shot's frames on the timeline, or None when it has no timeline.
    frames: int | None
    status: ShotClipStatus
    # The newest clip of this shot, whatever its state, and its job.
    clip: EvidenceClip | None
    job: Job | None
    last_error: str | None
    # Why the clip cannot be made now, or None.
    blocked_reason: str | None

    @property
    def done(self) -> bool:
        return self.status == "ready"

    @property
    def ref(self) -> str:
        return shot_ref(self.shot["scene_id"], self.shot["id"])


@dataclass(frozen=True)
class SceneShotClips:
    """The evidence shots of one scene, in the plan's order. Only scenes that have some."""

    item: dict[str, Any]
    shots: list[ShotClipEntry]


@dataclass(frozen=True)
class ShotClipsState:
    """What the `evidence_clips` step reads. `wanted` is False for a project without evidence."""

    wanted: bool
    entries: list[SceneShotClips]


def shot_ref(scene_id: str, shot_id: str) -> str:
    return f"{scene_id}/{shot_id}"


def _is_current(clip: EvidenceClip, item_key: str, look: dict[str, Any]) -> bool:
    """The clip shows the piece the shot names and was made with the look and length of now."""
    inputs = clip.inputs if isinstance(clip.inputs, dict) else {}
    return inputs.get("item_key") == item_key and not _is_out_of_date(clip, look)


def _clip_status(
    clip: EvidenceClip | None, job: Job | None, item_key: str, look: dict[str, Any]
) -> tuple[ShotClipStatus, str | None]:
    """`(status, last error)` of the newest clip of a shot. Pure."""
    if clip is None:
        return "none", None
    if job is not None and job.status in store.ACTIVE_STATUSES:
        return "working", None
    if not _is_current(clip, item_key, look):
        return ("out_of_date" if clip.media_path else "none"), None
    succeeded = job is None or job.status == "succeeded"
    if clip.media_path and succeeded:
        return "ready", None
    error = clip.last_error or (job.error if job is not None else None)
    return "failed", error or "The clip could not be drawn."


async def _newest_shot_clips(
    session: AsyncSession, project: Project
) -> dict[tuple[str, str], tuple[EvidenceClip, Job | None]]:
    """The newest clip of each evidence shot of the project, by `(scene_id, shot_id)`."""
    statement = (
        select(EvidenceClip, Job)
        .outerjoin(Job, EvidenceClip.render_job_id == Job.id)
        .where(EvidenceClip.project_id == project.id, EvidenceClip.purpose == PURPOSE_SHOT)
        .order_by(EvidenceClip.id.desc())
        .execution_options(populate_existing=True)
    )
    found: dict[tuple[str, str], tuple[EvidenceClip, Job | None]] = {}
    for clip, job in (await session.execute(statement)).all():
        if clip.scene_id is None or clip.shot_id is None:
            continue
        found.setdefault((clip.scene_id, clip.shot_id), (clip, job))
    return found


async def _newest_pieces(session: AsyncSession, project: Project) -> dict[str, EvidenceItem]:
    """The usable pieces of the newest import of the newest round, by `item_key`."""
    current = await evidence_rounds.state(session, project)
    if current.round is None:
        return {}
    record = await evidence_import.latest_import(session, current.round.id)
    if record is None:
        return {}
    return {
        item.item_key: item
        for item in await evidence_import.items_of(session, record.id)
        if item.usable
    }


def _span_frames(entry: shot_plans.SceneEntry, shot_id: str) -> int | None:
    if entry.timeline is None:
        return None
    for span in entry.timeline.shots:
        if span.shot_id == shot_id:
            return span.clip_frames
    return None


def _blocked_reason(
    entry: shot_plans.SceneEntry, item: EvidenceItem | None, frames: int | None
) -> str | None:
    if entry.status != "planned":
        return SHOT_PLAN_OUT_OF_DATE_MESSAGE
    if item is None:
        return PIECE_GONE_MESSAGE
    if not item.image_path:
        return NO_PICTURE_MESSAGE
    if frames is None:
        return NO_LENGTH_MESSAGE
    return None


@memoized_state
async def shot_state(session: AsyncSession, project: Project) -> ShotClipsState:
    """The clips of the evidence shots of the newest plans, scene by scene. Worked out on every
    read; nothing here is stored but the clips.
    """
    if not evidence_claims.wanted(project):
        return ShotClipsState(wanted=False, entries=[])
    plans = await shot_plans.state(session, project)
    pieces = await _newest_pieces(session, project)
    newest = await _newest_shot_clips(session, project)
    looks: dict[int, dict[str, Any]] = {}

    scenes: list[SceneShotClips] = []
    for entry in plans.entries:
        if entry.row is None or not isinstance(entry.row.content, dict):
            continue
        shots: list[ShotClipEntry] = []
        for shot in entry.row.content.get("shots", []):
            if shot.get("type") != scene_timeline.EVIDENCE_SHOT_TYPE:
                continue
            about = shot.get("evidence")
            if not isinstance(about, dict) or not isinstance(about.get("item_key"), str):
                continue
            item_key = about["item_key"]
            item = pieces.get(item_key)
            frames = _span_frames(entry, shot["id"])
            clip, job = newest.get((entry.item["id"], shot["id"]), (None, None))
            look = {}
            if frames is not None:
                if frames not in looks:
                    looks[frames] = await current_look(session, project, frames)
                look = looks[frames]
            status, error = _clip_status(clip, job, item_key, look) if look else ("none", None)
            shots.append(
                ShotClipEntry(
                    shot={**shot, "scene_id": entry.item["id"]},
                    plan_id=entry.row.id,
                    claim_id=str(about.get("claim_id")),
                    piece=int(about.get("piece") or 1),
                    item_key=item_key,
                    item=item,
                    frames=frames,
                    status=status,
                    clip=clip,
                    job=job,
                    last_error=error,
                    blocked_reason=_blocked_reason(entry, item, frames),
                )
            )
        if shots:
            scenes.append(SceneShotClips(item=entry.item, shots=shots))
    return ShotClipsState(wanted=True, entries=scenes)


async def queue_shot_clip(
    session: AsyncSession, project: Project, scene_id: str, shot_id: str
) -> Job:
    """Queues the clip of one evidence shot, at the shot's exact length, and commits. A clip
    that is already waiting or running gives its job. Raises EvidenceClipError (with the reason)
    when the clip cannot be made now or is already made.
    """
    state = await shot_state(session, project)
    found = next(
        (
            shot
            for scene in state.entries
            for shot in scene.shots
            if shot.shot["scene_id"] == scene_id and shot.shot["id"] == shot_id
        ),
        None,
    )
    if found is None:
        raise EvidenceClipError(UNKNOWN_SHOT_MESSAGE)
    if found.status == "working" and found.job is not None:
        return found.job
    if found.status == "ready":
        raise EvidenceClipError(ALREADY_MADE_MESSAGE)
    if found.blocked_reason is not None:
        raise EvidenceClipError(found.blocked_reason)
    assert found.item is not None and found.frames is not None  # the refusal made sure

    look = await current_look(session, project, found.frames)
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input={SHOT_DEDUPE_KEY: found.ref},
        commit=False,
        dedupe_key=SHOT_DEDUPE_KEY,
    )
    if not created:
        return job
    clip = EvidenceClip(
        project_id=project.id,
        purpose=PURPOSE_SHOT,
        item_id=found.item.id,
        scene_id=scene_id,
        shot_id=shot_id,
        shot_plan_id=found.plan_id,
        attempt=(found.clip.attempt + 1) if found.clip is not None else 1,
        inputs={
            "items": [found.item_key],
            "item_ids": [found.item.id],
            "item_key": found.item_key,
            "claim_id": found.claim_id,
            "piece": found.piece,
            "orientation": project.orientation,
            "length_s": round(found.frames / FPS, 3),
            **look,
        },
    )
    session.add(clip)
    await session.flush()
    job.input = {CLIP_KEY: clip.id, SHOT_DEDUPE_KEY: found.ref}
    clip.render_job_id = job.id
    await session.commit()
    return job
