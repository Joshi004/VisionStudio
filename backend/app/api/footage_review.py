"""`/api/projects/{project_id}/footage/review`: the owner's review of the footage the research
found (FTG-012).

- `GET ...` answers the newest import's pieces for each mark, the owner's verdicts, what is shown
  on each mark in order, and whether Review done can be pressed.
- `PUT .../items/{item_key}` accepts or rejects a piece of the agent.
- `PUT .../items/{item_key}/use` moves where an agent's video starts and ends.
- `PUT .../marks/{mark_id}/framing` sets the portrait crop of a mark.
- `PUT .../marks/{mark_id}/no-footage` sets or clears "no footage here" on a mark.
- `POST .../done` marks the newest round reviewed.

The order of what a mark shows, taking off one of the owner's files and the preview of a file are
the routes of `api/footage_files.py` (`PUT /footage-marks/{mark_id}/order`, `DELETE
/footage-files/{item_key}`, `POST /footage-files/{item_key}/preview`).

Every change is a new version of the owner's footage decisions and answers the review as it is
then. Everything the agent wrote is returned as plain text; the app follows no address. The
answers never return ORM objects.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.footage_files import (
    FootageFileStripOut,
    FootageFileUseOut,
    FootagePreviewOut,
    preview_out,
    strip_out,
)
from app.api.projects import load_project
from app.db.models import Project
from app.db.session import SessionDep
from app.services import footage_review as review_service

router = APIRouter()

MarkId = Annotated[str, Path(max_length=50)]
ItemKey = Annotated[str, Path(max_length=100)]

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project, mark or piece."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The project has no footage, nothing is imported, or the change breaks "
        "a rule.",
    }
}

PieceKind = Literal["video", "image", "page", "pdf"]
Verdict = Literal["accepted", "rejected"]
Framing = Literal["left", "centre", "right"]
RoundStatus = Literal["none", "brief_written", "imported", "reviewed"]


class FootageReviewSourceOut(BaseModel):
    """Where a piece came from, as the agent wrote it. Plain text."""

    url: str | None
    final_url: str | None
    publisher: str | None
    title: str | None
    published: str | None
    licence: str | None


class FootageReviewWarningOut(BaseModel):
    code: str
    message: str


class FootageReviewPieceOut(BaseModel):
    item_key: str
    piece_id: str
    origin: Literal["agent", "owner"]
    kind: PieceKind | None
    usable: bool
    # Why it did not pass the checks. Empty for a usable piece.
    reasons: list[str]
    tier: str | None
    source: FootageReviewSourceOut | None
    what_it_shows: str | None
    same_event: Literal["yes", "no", "unknown"] | None
    event_date: str | None
    on_screen_text: Literal["none", "small", "large"] | None
    credit: str | None
    warnings: list[FootageReviewWarningOut]
    verdict: Verdict | None
    # Where it is in the list shown on its mark (from 0), or null when it is not shown.
    shown_at: int | None
    # Under /media. The picture of an image, a page or a PDF page.
    image_url: str | None
    video_url: str | None
    strip_url: str | None
    strip: FootageFileStripOut | None
    width: int | None
    height: int | None
    # A video, in seconds of the stored video: its length, the part that plays, the instant the
    # agent chose and the cut times.
    window_s: float | None
    use: FootageFileUseOut | None
    moment_s: float | None
    cuts: list[float]
    # A page or a PDF: the focus boxes as fractions of the image.
    focus_rects: list[list[float]]
    focus_text: str | None
    page: int | None
    preview: FootagePreviewOut | None


class FootageReviewAttemptOut(BaseModel):
    what: str
    outcome: str


class FootageReviewMarkOut(BaseModel):
    id: str
    text: str
    note: str
    kind_hint: str
    # Its pieces can be decided on (the words and note are as in the round).
    live: bool
    no_footage: bool
    framing: Framing | None
    # The agent's own report: `found`, `not_found` or `blocked`; null when it wrote none.
    status: Literal["found", "not_found", "blocked"] | None
    summary: str
    attempts: list[FootageReviewAttemptOut]
    # The pieces of the newest import, usable or not.
    pieces: list[FootageReviewPieceOut]
    # What is shown on the mark now, in order.
    shown: list[FootageReviewPieceOut]
    undecided: int


class FootageReviewOut(BaseModel):
    wanted: bool
    round_id: str | None
    import_version: int | None
    status: RoundStatus
    importing: bool
    orientation: Literal["landscape", "portrait"]
    undecided: int
    can_finish: bool
    finish_blocked_reason: str | None
    marks: list[FootageReviewMarkOut]


class FootageReviewVerdictIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict


class FootageReviewUseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_s: StrictFloat | StrictInt = Field(ge=0, le=100000)
    end_s: StrictFloat | StrictInt = Field(ge=0, le=100000)


class FootageReviewFramingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framing: Framing | None


class FootageReviewNoFootageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    no_footage: StrictBool


# --- Mapping ---------------------------------------------------------------------------------


def _piece_out(piece: review_service.ReviewPiece) -> FootageReviewPieceOut:
    return FootageReviewPieceOut(
        item_key=piece.item_key,
        piece_id=piece.piece_id,
        origin=cast(Any, piece.origin),
        kind=cast(Any, piece.kind),
        usable=piece.usable,
        reasons=piece.reasons,
        tier=piece.tier,
        source=(FootageReviewSourceOut(**piece.source) if piece.source is not None else None),
        what_it_shows=piece.what_it_shows,
        same_event=cast(Any, piece.same_event),
        event_date=piece.event_date,
        on_screen_text=cast(Any, piece.on_screen_text),
        credit=piece.credit,
        warnings=[FootageReviewWarningOut(**warning) for warning in piece.warnings],
        verdict=cast(Any, piece.verdict),
        shown_at=piece.shown_at,
        image_url=piece.image_url,
        video_url=piece.video_url,
        strip_url=piece.strip_url,
        strip=strip_out(piece.strip),
        width=piece.width,
        height=piece.height,
        window_s=piece.window_s,
        use=(FootageFileUseOut(**piece.use) if piece.use is not None else None),
        moment_s=piece.moment_s,
        cuts=piece.cuts,
        focus_rects=piece.focus_rects,
        focus_text=piece.focus_text,
        page=piece.page,
        preview=preview_out(piece.preview),
    )


async def _review(session: AsyncSession, project: Project) -> FootageReviewOut:
    found = await review_service.view(session, project)
    return FootageReviewOut(
        wanted=found.wanted,
        round_id=found.round_id,
        import_version=found.import_version,
        status=cast(RoundStatus, found.status),
        importing=found.importing,
        orientation=cast(Any, found.orientation),
        undecided=found.undecided,
        can_finish=found.can_finish,
        finish_blocked_reason=found.finish_blocked_reason,
        marks=[
            FootageReviewMarkOut(
                id=mark.id,
                text=mark.text,
                note=mark.note,
                kind_hint=mark.kind_hint,
                live=mark.live,
                no_footage=mark.no_footage,
                framing=cast(Any, mark.framing),
                status=cast(Any, mark.status),
                summary=mark.summary,
                attempts=[FootageReviewAttemptOut(**attempt) for attempt in mark.attempts],
                pieces=[_piece_out(piece) for piece in mark.pieces],
                shown=[_piece_out(piece) for piece in mark.shown],
                undecided=mark.undecided,
            )
            for mark in found.marks
        ],
    )


def _refusal(exc: review_service.FootageReviewError) -> HTTPException:
    if isinstance(exc, review_service.UnknownItemError | review_service.UnknownMarkError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


# --- Endpoints -------------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/footage/review",
    response_model=FootageReviewOut,
    responses=_NOT_FOUND,
)
async def get_footage_review(project_id: int, session: SessionDep) -> FootageReviewOut:
    return await _review(session, await load_project(session, project_id))


@router.put(
    "/projects/{project_id}/footage/review/items/{item_key}",
    response_model=FootageReviewOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def decide_footage_piece(
    project_id: int, item_key: ItemKey, body: FootageReviewVerdictIn, session: SessionDep
) -> FootageReviewOut:
    """Accepts or rejects a piece of the agent. An accepted piece is shown on its mark."""
    project = await load_project(session, project_id)
    try:
        await review_service.decide_piece(session, project, item_key, body.verdict)
    except review_service.FootageReviewError as exc:
        raise _refusal(exc) from exc
    return await _review(session, project)


@router.put(
    "/projects/{project_id}/footage/review/items/{item_key}/use",
    response_model=FootageReviewOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def set_footage_piece_use(
    project_id: int, item_key: ItemKey, body: FootageReviewUseIn, session: SessionDep
) -> FootageReviewOut:
    """Moves where a video starts and ends, in seconds of the stored video: inside the video,
    2 to 15 seconds."""
    project = await load_project(session, project_id)
    try:
        await review_service.set_piece_use(
            session, project, item_key, float(body.start_s), float(body.end_s)
        )
    except review_service.FootageReviewError as exc:
        raise _refusal(exc) from exc
    return await _review(session, project)


@router.put(
    "/projects/{project_id}/footage/review/marks/{mark_id}/framing",
    response_model=FootageReviewOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def set_footage_framing(
    project_id: int, mark_id: MarkId, body: FootageReviewFramingIn, session: SessionDep
) -> FootageReviewOut:
    """Sets the portrait crop of a mark; null fits the picture over a blurred copy."""
    project = await load_project(session, project_id)
    try:
        await review_service.set_mark_framing(session, project, mark_id, body.framing)
    except review_service.FootageReviewError as exc:
        raise _refusal(exc) from exc
    return await _review(session, project)


@router.put(
    "/projects/{project_id}/footage/review/marks/{mark_id}/no-footage",
    response_model=FootageReviewOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def set_footage_review_no_footage(
    project_id: int, mark_id: MarkId, body: FootageReviewNoFootageIn, session: SessionDep
) -> FootageReviewOut:
    """Sets or clears "no footage here" on a mark."""
    project = await load_project(session, project_id)
    try:
        await review_service.set_mark_no_footage(session, project, mark_id, body.no_footage)
    except review_service.FootageReviewError as exc:
        raise _refusal(exc) from exc
    return await _review(session, project)


@router.post(
    "/projects/{project_id}/footage/review/done",
    response_model=FootageReviewOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def finish_footage_review(project_id: int, session: SessionDep) -> FootageReviewOut:
    """Marks the newest round reviewed. Refused while a piece is undecided."""
    project = await load_project(session, project_id)
    try:
        await review_service.finish_review(session, project)
    except review_service.FootageReviewError as exc:
        raise _refusal(exc) from exc
    return await _review(session, project)
