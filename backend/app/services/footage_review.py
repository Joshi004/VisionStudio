"""The owner's review of the footage the research found (FTG-012,
`Footage_broll_implementation_phases.md` FT-11).

The owner decides, for every mark of the newest round:

- an `accepted` or `rejected` verdict for each **usable** piece of the newest import;
- which pieces are **shown** on video and in what order (the owner's own files are in the same
  list, accepted when they were added);
- where a video piece starts and ends (`use`), and the portrait crop of the mark;
- or "no footage here" for the whole mark.

Everything is stored as new versions of `footage_decision` (`services/footage_decisions.py`);
nothing here has a table of its own and no stored row is changed. A decision names a piece by its
`item_key`, so a new import that did not change a piece keeps the decision for it.

**The review covers the newest round and its newest import.** A mark is *live* when it still
counts and the round holds it unchanged (`footage_rounds.keys_by_id`). A mark that is not live is
shown but cannot be decided on: its words or note changed since the round.

**A mark is decided** when every usable piece of the newest import on it has a verdict, or the
owner chose "no footage here". A mark with no usable piece is decided already: finding nothing is
a fine answer. "Review done" is refused until every live mark is decided. It adds the round's id
(`r2`) to `reviewed_rounds`, which is what `footage_rounds.state` reads as `reviewed`, so the
`footage` step needs nothing else. A later change (a verdict, an order, a start and end) goes
straight to the video and leaves the round reviewed. Only a new import of the round takes it off
again (`footage_import.make_import`).

Everything the agent wrote (the summary, the notes on a piece, the source) is data: it is read
from the stored rows and returned as text. Nothing here follows an address.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FootageImport, FootageItem, Project
from app.jobs import store
from app.services import (
    footage_clips,
    footage_decisions,
    footage_import,
    footage_marks,
    footage_rounds,
)
from app.services.storage import media_url

VIDEO_KIND: Final = "video"
OWNER_KEY_PREFIX: Final = "owner-"
FRAMINGS: Final = ("left", "centre", "right")

# The part of an agent's video that plays lasts this long (the brief's `clip_seconds`).
USE_MIN_S: Final = float(footage_rounds.CLIP_MIN_S)
USE_MAX_S: Final = float(footage_rounds.CLIP_MAX_S)
_EPSILON: Final = 0.0015

NO_IMPORT_MESSAGE: Final = "Import the research results first, then review them here."
IMPORT_RUNNING_MESSAGE: Final = "The results are being imported. Review them when that is done."
NOT_IN_IMPORT_MESSAGE: Final = "That piece is not in the newest import of the research."
UNUSABLE_MESSAGE: Final = "That piece did not pass the checks, so it cannot be used."
MARK_CHANGED_MESSAGE: Final = (
    "The words or the note of this mark changed since the round was written, so its pieces "
    "cannot be decided on."
)
OWN_FILE_MESSAGE: Final = "That is one of your own files. Change it on the mark."
NOT_VIDEO_MESSAGE: Final = "Only a video has a start and an end."
UNKNOWN_MARK_MESSAGE: Final = "There is no such footage mark."
UNKNOWN_ITEM_MESSAGE: Final = "There is no such piece of footage."
FRAMING_MESSAGE: Final = "The crop is only for a portrait video."
FRAMING_VALUE_MESSAGE: Final = "The crop must be left, centre or right."
ALREADY_REVIEWED_MESSAGE: Final = "This round is already reviewed."
NO_ROUND_LIVE_MESSAGE: Final = "The marks changed since the round was written. Write a new round."


class FootageReviewError(ValueError):
    """A change that cannot be made. The message is meant to be shown to the user."""


class UnknownItemError(FootageReviewError):
    """The piece does not exist."""


class UnknownMarkError(FootageReviewError):
    """The mark does not exist."""


# --- What the review shows -----------------------------------------------------------------


@dataclass(frozen=True)
class ReviewPiece:
    """One piece of footage on a mark, the agent's or the owner's."""

    item_key: str
    piece_id: str
    origin: str
    kind: str | None
    usable: bool
    # Why it did not pass the checks, one sentence each. Empty for a usable piece.
    reasons: list[str]
    tier: str | None
    # `url`, `final_url`, `publisher`, `title`, `published` and `licence`; None for an owner's file.
    source: dict[str, str | None] | None
    what_it_shows: str | None
    same_event: str | None
    event_date: str | None
    on_screen_text: str | None
    credit: str | None
    warnings: list[dict[str, str]]
    # `accepted` or `rejected`, or None when the owner has not decided.
    verdict: str | None
    # Where it is in the list shown on the mark (from 0), or None when it is not shown.
    shown_at: int | None
    # The picture of an image, a page or a PDF page, and the prepared video with its strip.
    image_url: str | None = None
    video_url: str | None = None
    strip_url: str | None = None
    strip: dict[str, Any] | None = None
    width: int | None = None
    height: int | None = None
    # A video: how long the stored video is, the part that plays, and the instant the agent chose,
    # all in seconds of the stored video. The cuts are in the same seconds.
    window_s: float | None = None
    use: dict[str, float] | None = None
    moment_s: float | None = None
    cuts: list[float] = field(default_factory=list)
    # A page or a PDF: the focus boxes as fractions of the image, and the PDF page.
    focus_rects: list[list[float]] = field(default_factory=list)
    focus_text: str | None = None
    page: int | None = None
    preview: footage_clips.Preview | None = None


@dataclass(frozen=True)
class ReviewMark:
    id: str
    text: str
    note: str
    kind_hint: str
    # The mark still counts and the round holds it unchanged: its pieces can be decided on.
    live: bool
    no_footage: bool
    framing: str | None
    # The agent's own report on the mark; None when it wrote none.
    status: str | None
    summary: str
    attempts: list[dict[str, str]]
    # The pieces of the newest import, usable or not.
    pieces: list[ReviewPiece]
    # What is shown on the mark now, in order: the owner's files and the accepted pieces.
    shown: list[ReviewPiece]
    undecided: int


@dataclass(frozen=True)
class ReviewView:
    wanted: bool
    round_id: str | None
    import_version: int | None
    # `none`, `brief_written`, `imported` or `reviewed`.
    status: str
    importing: bool
    orientation: str
    undecided: int
    can_finish: bool
    finish_blocked_reason: str | None
    marks: list[ReviewMark]


# --- Reading -------------------------------------------------------------------------------


@dataclass
class _Context:
    rounds: footage_rounds.FootageRoundsState
    record: FootageImport | None
    # The usable and unusable pieces of the newest import.
    items: list[FootageItem]
    content: Any
    importing: bool
    # The ids of the marks that count and that the newest round holds unchanged.
    live: set[str]
    # The ids of the marks in the newest round's brief.
    in_brief: set[str]


async def _load(session: AsyncSession, project: Project) -> _Context:
    rounds = await footage_rounds.state(session, project)
    record: FootageImport | None = None
    items: list[FootageItem] = []
    live: set[str] = set()
    in_brief: set[str] = set()
    row = rounds.round
    if rounds.wanted and row is not None:
        record = await footage_import.latest_import(session, row.id)
        if record is not None:
            items = await footage_import.items_of(session, record.id)
        held = footage_rounds.keys_by_id(
            row.brief.get("marks") if isinstance(row.brief, dict) else None
        )
        in_brief = set(held)
        if project.script_text is not None:
            now = footage_rounds.keys_by_id(
                footage_rounds.brief_marks(project.script_text, rounds.marks, {})
            )
            live = {mark_id for mark_id, key in now.items() if held.get(mark_id) == key}
    decision = await footage_decisions.latest(session, project.id) if rounds.wanted else None
    job = (
        await store.latest_job(session, project.id, footage_import.JOB_TYPE)
        if rounds.wanted
        else None
    )
    return _Context(
        rounds=rounds,
        record=record,
        items=items,
        content=decision.content if decision is not None else None,
        importing=job is not None and job.status in store.ACTIVE_STATUSES,
        live=live,
        in_brief=in_brief,
    )


def _text_list(value: Any) -> list[str]:
    return [text for text in value if isinstance(text, str)] if isinstance(value, list) else []


def _reasons(checks: Any) -> list[str]:
    if not isinstance(checks, dict):
        return []
    return [
        entry["reason"]
        for entry in checks.values()
        if isinstance(entry, dict) and isinstance(entry.get("reason"), str)
    ]


def _warnings(warnings: Any) -> list[dict[str, str]]:
    return [
        {"code": entry["code"], "message": entry["message"]}
        for entry in (warnings if isinstance(warnings, list) else [])
        if isinstance(entry, dict)
        and isinstance(entry.get("code"), str)
        and isinstance(entry.get("message"), str)
    ]


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _pixels(value: Any) -> tuple[int | None, int | None]:
    if isinstance(value, list) and len(value) == 2 and all(isinstance(v, int) for v in value):
        return value[0], value[1]
    return None, None


def _source(item: FootageItem) -> dict[str, str | None] | None:
    source = item.source if isinstance(item.source, dict) else None
    if source is None:
        return None
    return {
        key: source[key] if isinstance(source.get(key), str) else None
        for key in ("url", "final_url", "publisher", "title", "published", "licence")
    }


def _window_s(item: FootageItem) -> float | None:
    capture = item.capture if isinstance(item.capture, dict) else {}
    window = capture.get("window")
    if isinstance(window, dict):
        start, end = _number(window.get("start_s")), _number(window.get("end_s"))
        if start is not None and end is not None and end > start:
            return round(end - start, 3)
    return _number(capture.get("duration_s"))


def _strip(item: FootageItem) -> dict[str, Any] | None:
    capture = item.capture if isinstance(item.capture, dict) else {}
    keys = ("strip_every_s", "strip_columns", "strip_rows", "strip_tile_px", "strip_frames")
    if any(capture.get(key) is None for key in keys):
        return None
    tile = capture["strip_tile_px"]
    if not (isinstance(tile, list) and len(tile) == 2):
        return None
    # The keys of `capture`, as `footage_files.FileView.strip` has them.
    return {key: capture[key] for key in keys}


def _rects(value: Any) -> list[list[float]]:
    found: list[list[float]] = []
    for rect in value if isinstance(value, list) else []:
        if isinstance(rect, list) and len(rect) == 4 and all(_number(v) is not None for v in rect):
            found.append([float(v) for v in rect])
    return found


def _piece(item: FootageItem, entry: dict[str, Any] | None) -> ReviewPiece:
    """One item as the review shows it. `entry` is the owner's decisions on its mark."""
    capture = item.capture if isinstance(item.capture, dict) else {}
    verdicts = {v["item_key"]: v.get("verdict") for v in entry["items"]} if entry else {}
    shown = entry["shown"] if entry else []
    shown_at = shown.index(item.item_key) if item.item_key in shown else None
    width, height = _pixels(capture.get("video_px" if item.kind == VIDEO_KIND else "image_px"))
    piece = ReviewPiece(
        item_key=item.item_key,
        piece_id=item.piece_id,
        origin=item.origin,
        kind=item.kind,
        usable=item.usable,
        reasons=[] if item.usable else _reasons(item.checks),
        tier=item.tier,
        source=_source(item),
        what_it_shows=item.what_it_shows,
        same_event=item.same_event,
        event_date=item.event_date,
        on_screen_text=item.on_screen_text,
        credit=item.credit,
        warnings=_warnings(item.warnings),
        verdict=verdicts.get(item.item_key),
        shown_at=shown_at,
        width=width,
        height=height,
    )
    if not item.usable:
        return piece
    if item.kind == VIDEO_KIND:
        decided = entry["use"].get(item.item_key) if entry else None
        times = footage_clips.video_times(item, decided)
        return replace(
            piece,
            video_url=media_url(item.video_path) if item.video_path else None,
            strip_url=media_url(item.strip_path) if item.strip_path else None,
            strip=_strip(item),
            window_s=_window_s(item),
            use=(
                {"start_s": times.use_start_s, "end_s": times.use_end_s}
                if times is not None
                else None
            ),
            moment_s=times.moment_s if times is not None else None,
            cuts=[float(c) for c in item.cuts if _number(c) is not None]
            if isinstance(item.cuts, list)
            else [],
        )
    return replace(
        piece,
        image_url=media_url(item.image_path) if item.image_path else None,
        focus_rects=_rects(capture.get("focus_rects")),
        focus_text=capture.get("focus_text")
        if isinstance(capture.get("focus_text"), str)
        else None,
        page=capture.get("page") if isinstance(capture.get("page"), int) else None,
    )


async def _items_by_key(
    session: AsyncSession, project_id: int, keys: set[str]
) -> dict[str, FootageItem]:
    """The newest row of each item key (a re-import may hold the same key again)."""
    if not keys:
        return {}
    statement = (
        select(FootageItem)
        .where(FootageItem.project_id == project_id, FootageItem.item_key.in_(keys))
        .order_by(FootageItem.id.desc())
        .execution_options(populate_existing=True)
    )
    found: dict[str, FootageItem] = {}
    for item in (await session.execute(statement)).scalars():
        found.setdefault(item.item_key, item)
    return found


def _undecided_in(ctx: _Context, mark_id: str, entry: dict[str, Any] | None) -> int:
    """How many usable pieces of the newest import on a live mark have no verdict."""
    if mark_id not in ctx.live or (entry is not None and entry["no_footage"]):
        return 0
    decided = {v["item_key"] for v in entry["items"] if v.get("verdict")} if entry else set()
    return sum(
        1
        for item in ctx.items
        if item.mark_id == mark_id and item.usable and item.item_key not in decided
    )


def _finish_refusal(ctx: _Context, undecided: int) -> str | None:
    if not ctx.rounds.wanted:
        return footage_marks.OFF_MESSAGE
    if ctx.importing:
        return IMPORT_RUNNING_MESSAGE
    if ctx.record is None:
        return NO_IMPORT_MESSAGE
    if ctx.rounds.status == footage_rounds.STATUS_REVIEWED:
        return ALREADY_REVIEWED_MESSAGE
    if not ctx.rounds.live or not ctx.live:
        return NO_ROUND_LIVE_MESSAGE
    if undecided:
        many = "pieces" if undecided != 1 else "piece"
        return f"Accept or reject the {undecided} {many} still undecided."
    return None


def _results(ctx: _Context) -> dict[str, Any]:
    results = ctx.record.results if ctx.record is not None else None
    return results if isinstance(results, dict) else {}


async def view(session: AsyncSession, project: Project) -> ReviewView:
    """The review of the newest import. A project without footage, or with nothing imported yet,
    has no marks."""
    ctx = await _load(session, project)
    row = ctx.rounds.round
    empty = ReviewView(
        wanted=ctx.rounds.wanted,
        round_id=f"r{row.round_no}" if row is not None else None,
        import_version=ctx.record.version if ctx.record is not None else None,
        status=ctx.rounds.status,
        importing=ctx.importing,
        orientation=project.orientation,
        undecided=0,
        can_finish=False,
        finish_blocked_reason=_finish_refusal(ctx, 0),
        marks=[],
    )
    if not ctx.rounds.wanted or ctx.record is None:
        return empty

    entries = {e["mark_id"]: e for e in footage_decisions.marks_of(ctx.content)}
    shown_keys = {key for e in entries.values() for key in e["shown"]}
    shown_items = await _items_by_key(session, project.id, shown_keys)
    # The newest import's row of a piece wins over an older row of the same key.
    for item in ctx.items:
        if item.item_key in shown_items:
            shown_items[item.item_key] = item

    marks: list[ReviewMark] = []
    total = 0
    for mark in ctx.rounds.marks:
        mark_id = mark["id"]
        if mark_id not in ctx.in_brief:
            continue
        entry = entries.get(mark_id)
        result = _results(ctx).get(mark_id)
        result = result if isinstance(result, dict) else {}
        pieces = [_piece(item, entry) for item in ctx.items if item.mark_id == mark_id]
        shown = [
            _piece(shown_items[key], entry)
            for key in (entry["shown"] if entry else [])
            if key in shown_items
        ]
        undecided = _undecided_in(ctx, mark_id, entry)
        total += undecided
        attempts = [
            {"what": a.get("what", ""), "outcome": a.get("outcome", "")}
            for a in result.get("attempts", [])
            if isinstance(a, dict)
        ]
        marks.append(
            ReviewMark(
                id=mark_id,
                text=mark["text"],
                note=mark["note"],
                kind_hint=mark["kind_hint"],
                live=mark_id in ctx.live,
                no_footage=bool(entry and entry["no_footage"]),
                framing=footage_clips.framing_of(entry["framing"]) if entry else None,
                status=result.get("status") if isinstance(result.get("status"), str) else None,
                summary=result.get("summary") if isinstance(result.get("summary"), str) else "",
                attempts=attempts,
                pieces=pieces,
                shown=shown,
                undecided=undecided,
            )
        )

    # The previews of every piece that can be drawn, whether shown or not yet.
    wanted_keys = {
        piece.item_key for mark in marks for piece in (*mark.pieces, *mark.shown) if piece.usable
    }
    by_key = {item.item_key: item for item in ctx.items}
    by_key.update({key: item for key, item in shown_items.items() if key not in by_key})
    previews = await footage_clips.previews_for(
        session, project, [by_key[key] for key in sorted(wanted_keys) if key in by_key]
    )
    marks = [
        replace(
            mark,
            pieces=[replace(p, preview=previews.get(p.item_key)) for p in mark.pieces],
            shown=[replace(p, preview=previews.get(p.item_key)) for p in mark.shown],
        )
        for mark in marks
    ]
    reason = _finish_refusal(ctx, total)
    return replace(
        empty, undecided=total, can_finish=reason is None, finish_blocked_reason=reason, marks=marks
    )


# --- The owner's actions -------------------------------------------------------------------


def _guard(ctx: _Context) -> None:
    """Nothing can be changed for a project without footage or while an import runs."""
    if not ctx.rounds.wanted:
        raise FootageReviewError(footage_marks.OFF_MESSAGE)
    if ctx.importing:
        raise FootageReviewError(IMPORT_RUNNING_MESSAGE)


def _guard_import(ctx: _Context) -> None:
    _guard(ctx)
    if ctx.record is None:
        raise FootageReviewError(NO_IMPORT_MESSAGE)


async def _agent_piece(
    session: AsyncSession, project: Project, ctx: _Context, item_key: str, *, accepting: bool
) -> FootageItem:
    """The piece of the agent a change is about. A piece of the newest import must be usable (and,
    to accept it, on a live mark). A piece shown from an earlier import can only be rejected or
    have its start and end moved (`accepting` False)."""
    newest = next((item for item in ctx.items if item.item_key == item_key), None)
    if newest is not None:
        if not newest.usable:
            raise FootageReviewError(UNUSABLE_MESSAGE)
        if accepting and newest.mark_id not in ctx.live:
            raise FootageReviewError(MARK_CHANGED_MESSAGE)
        return newest
    if item_key.startswith(OWNER_KEY_PREFIX):
        raise FootageReviewError(OWN_FILE_MESSAGE)
    older = (await _items_by_key(session, project.id, {item_key})).get(item_key)
    if older is None:
        raise UnknownItemError(UNKNOWN_ITEM_MESSAGE)
    entry = footage_decisions.mark_entry(ctx.content, older.mark_id)
    if accepting or entry is None or item_key not in entry["shown"] or older.origin != "agent":
        raise FootageReviewError(NOT_IN_IMPORT_MESSAGE)
    return older


async def decide_piece(
    session: AsyncSession, project: Project, item_key: str, verdict: str
) -> None:
    """Accepts or rejects a piece of the agent. An accepted piece is shown after the mark's other
    agent pieces and before the owner's own files; a rejected one is taken off. Commits. Raises
    FootageReviewError, UnknownItemError."""
    ctx = await _load(session, project)
    _guard_import(ctx)
    if verdict not in (footage_decisions.ACCEPTED, footage_decisions.REJECTED):
        raise FootageReviewError("The verdict must be accepted or rejected.")
    item = await _agent_piece(
        session, project, ctx, item_key, accepting=verdict == footage_decisions.ACCEPTED
    )
    entry = footage_decisions.mark_entry(ctx.content, item.mark_id)
    owner_keys = frozenset(
        key for key in (entry["shown"] if entry else []) if key.startswith(OWNER_KEY_PREFIX)
    )
    await footage_decisions.set_verdict(
        session, project, item.mark_id, item_key, verdict, before=owner_keys
    )


def check_use(start_s: float, end_s: float, window_s: float) -> tuple[float, float]:
    """The start and end the owner chose for an agent's video of `window_s` seconds, rounded to a
    thousandth. They lie inside the video and the part lasts 2 to 15 seconds. Raises
    FootageReviewError."""
    if not (math.isfinite(start_s) and math.isfinite(end_s)):
        raise FootageReviewError("The start and the end must be numbers.")
    start, end = round(start_s, 3), round(end_s, 3)
    if start < 0 or end > window_s + _EPSILON:
        raise FootageReviewError("The part shown must lie inside the video.")
    end = min(end, round(window_s, 3))
    length = end - start
    if length < USE_MIN_S - _EPSILON or length > USE_MAX_S + _EPSILON:
        raise FootageReviewError(
            f"The part shown must last {USE_MIN_S:g} to {USE_MAX_S:g} seconds."
        )
    return start, end


async def set_piece_use(
    session: AsyncSession, project: Project, item_key: str, start_s: float, end_s: float
) -> None:
    """Moves where an agent's video starts and ends, in seconds of the stored video. Commits.
    Raises FootageReviewError, UnknownItemError."""
    ctx = await _load(session, project)
    _guard_import(ctx)
    item = await _agent_piece(session, project, ctx, item_key, accepting=False)
    if item.kind != VIDEO_KIND:
        raise FootageReviewError(NOT_VIDEO_MESSAGE)
    window_s = _window_s(item)
    if window_s is None:
        raise FootageReviewError("The length of the video is not known.")
    start, end = check_use(start_s, end_s, window_s)
    try:
        await footage_decisions.set_use(
            session, project, item.mark_id, item_key, start, end, require_shown=False
        )
    except footage_decisions.FootageDecisionError as exc:
        raise FootageReviewError(str(exc)) from exc


def _require_mark(ctx: _Context, mark_id: str) -> None:
    if not any(mark["id"] == mark_id for mark in ctx.rounds.marks):
        raise UnknownMarkError(UNKNOWN_MARK_MESSAGE)


async def set_mark_framing(
    session: AsyncSession, project: Project, mark_id: str, framing: str | None
) -> None:
    """Sets the portrait crop of a mark (`left`, `centre`, `right` or None). Commits. Raises
    FootageReviewError, UnknownMarkError."""
    ctx = await _load(session, project)
    _guard(ctx)
    _require_mark(ctx, mark_id)
    if project.orientation != "portrait":
        raise FootageReviewError(FRAMING_MESSAGE)
    if framing is not None and framing not in FRAMINGS:
        raise FootageReviewError(FRAMING_VALUE_MESSAGE)
    await footage_decisions.set_framing(session, project, mark_id, framing)


async def set_mark_no_footage(
    session: AsyncSession, project: Project, mark_id: str, value: bool
) -> None:
    """Sets or clears the owner's "no footage here" on a mark. Commits. Raises
    FootageReviewError, UnknownMarkError."""
    ctx = await _load(session, project)
    _guard(ctx)
    _require_mark(ctx, mark_id)
    await footage_decisions.set_no_footage(session, project, [mark_id], value)


async def finish_review(session: AsyncSession, project: Project) -> None:
    """Marks the newest round reviewed. Refused until every live mark is decided. Commits. Raises
    FootageReviewError."""
    ctx = await _load(session, project)
    undecided = sum(
        _undecided_in(ctx, mark["id"], footage_decisions.mark_entry(ctx.content, mark["id"]))
        for mark in ctx.rounds.marks
        if mark["id"] in ctx.in_brief
    )
    reason = _finish_refusal(ctx, undecided)
    if reason is not None:
        raise FootageReviewError(reason)
    row = ctx.rounds.round
    assert row is not None
    await footage_decisions.set_round_reviewed(session, project, f"r{row.round_no}", True)
