"""The evidence clip: the video of one piece of evidence, zoomed to its quote (EVD-008,
`Evidence_layer_implementation_phases.md` §4.7).

This phase makes the **preview** (`evidence_clip.purpose = 'preview'`): from the review screen the
owner asks for a short video of an accepted piece, and watches how it will look. EVD-009 makes the
exact-length clips of evidence shots with the same job and the same layout.

- `queue_preview` makes the `evidence_clip` row and the `render_evidence_clip` job for one accepted
  piece. A second press while one is waiting or running returns the same job.
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
from typing import Any, Final
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvidenceClip, EvidenceItem, Job, Project
from app.jobs import store
from app.services import (
    callout_plan,
    caption_plan,
    evidence_clip_layout,
    evidence_import,
    evidence_review,
    graphic_theme,
    graphics_lab,
)

JOB_TYPE: Final = "render_evidence_clip"
# `job.input` is `{evidence_clip_id, preview_item_id}`. Two presses on one piece make one job.
CLIP_KEY: Final = "evidence_clip_id"
DEDUPE_KEY: Final = "preview_item_id"

PURPOSE_PREVIEW: Final = "preview"
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


async def current_look(session: AsyncSession, project: Project) -> dict[str, Any]:
    """What a preview made now would be made with. A stored preview that differs is out of date."""
    accent, source = await accent_for(session, project)
    return {
        "width": project.out_width,
        "height": project.out_height,
        "fps": FPS,
        "frames": preview_frames(),
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
