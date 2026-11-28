"""The owner's footage decisions for the whole project (FTG-003,
`Footage_broll_implementation_phases.md` §4.12).

Every change is a new `footage_decision` row with the next `version`, and a stored row is never
changed (the artifact provenance convention, DATABASE_STRUCTURE.md Section 2.1). One list covers
the project, because an owner's own file has no round. `content` is:

    {
      "marks": [
        {
          "mark_id": "f3",
          "items": [{"item_key": "owner-ab12...", "verdict": "accepted"}],
          "shown": ["owner-ab12..."],
          "use": {"owner-ab12...": {"start_s": 0.0, "end_s": 12.5}},
          "framing": null,
          "no_footage": false
        }
      ],
      "reviewed_rounds": []
    }

- `items`: the owner's verdict on each piece of the mark, by `item_key`: `accepted` or `rejected`.
- `shown`: the item keys to show, in order. An accepted piece the owner removed is not in it.
- `use`: a video piece's start and end in seconds of its stored video, moved by the owner.
- `no_footage`: the owner's "no footage here" (FTG-007: Continue without footage and its undo).
- `framing`: the portrait crop of the mark (`left`, `centre`, `right` or null), set by the review
  (FTG-012).
- `reviewed_rounds`: round ids like `r2`, added by Review done and taken off again by a new import
  of the round (FTG-012).

A decision names a piece by its `item_key`, so a new import keeps the decisions for pieces that
did not change. This module only stores what it is given: the rules about files and times are
checked by `services/footage_files.py`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FootageDecision, FootageItem, Project
from app.services import footage_marks

ACCEPTED: Final = "accepted"
REJECTED: Final = "rejected"

NOT_SHOWN_MESSAGE: Final = "That file is not shown on this mark."
ORDER_MESSAGE: Final = "The order must list every file shown on this mark, once each."


class FootageDecisionError(ValueError):
    """A change that cannot be made. The message is meant to be shown to the user."""


# --- Reading (pure) ------------------------------------------------------------------------


def _normalised(content: Any) -> dict[str, Any]:
    """A copy of a stored `content` with every key present, so edits never meet a missing one."""
    source = content if isinstance(content, dict) else {}
    marks: list[dict[str, Any]] = []
    for stored in source.get("marks", []) if isinstance(source.get("marks"), list) else []:
        if not isinstance(stored, dict) or not isinstance(stored.get("mark_id"), str):
            continue
        marks.append(
            {
                "mark_id": stored["mark_id"],
                "items": [dict(item) for item in stored.get("items") or []],
                "shown": list(stored.get("shown") or []),
                "use": copy.deepcopy(stored.get("use") or {}),
                "framing": stored.get("framing"),
                "no_footage": bool(stored.get("no_footage", False)),
            }
        )
    reviewed = source.get("reviewed_rounds")
    return {"marks": marks, "reviewed_rounds": list(reviewed) if isinstance(reviewed, list) else []}


def marks_of(content: Any) -> list[dict[str, Any]]:
    """The decisions on every mark, each with every key present (a copy)."""
    return _normalised(content)["marks"]


def mark_entry(content: Any, mark_id: str) -> dict[str, Any] | None:
    """The decisions on one mark, or None when the owner has decided nothing on it."""
    for entry in marks_of(content):
        if entry["mark_id"] == mark_id:
            return entry
    return None


def shown_keys(content: Any, mark_id: str) -> list[str]:
    """The item keys shown on a mark, in order."""
    entry = mark_entry(content, mark_id)
    return list(entry["shown"]) if entry is not None else []


def _entry_for_edit(content: dict[str, Any], mark_id: str) -> dict[str, Any]:
    """The mark's entry in a normalised `content`, added with nothing decided when it has none."""
    for entry in content["marks"]:
        if entry["mark_id"] == mark_id:
            return entry
    entry = {
        "mark_id": mark_id,
        "items": [],
        "shown": [],
        "use": {},
        "framing": None,
        "no_footage": False,
    }
    content["marks"].append(entry)
    return entry


# --- Versions ------------------------------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> FootageDecision | None:
    """The project's newest version, or None when the owner has decided nothing."""
    statement = (
        select(FootageDecision)
        .where(FootageDecision.project_id == project_id)
        .order_by(FootageDecision.version.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def _add_version(
    session: AsyncSession, project: Project, based_on: FootageDecision | None, content: Any
) -> FootageDecision:
    row = FootageDecision(
        project_id=project.id,
        version=(based_on.version if based_on is not None else 0) + 1,
        inputs={"decision_version": based_on.version if based_on is not None else None},
        content=content,
    )
    session.add(row)
    await session.flush()
    return row


async def _edit(
    session: AsyncSession, project: Project, mark_id: str, change: Any, *, commit: bool
) -> None:
    """Stores a new version made by `change(entry)` on a copy of the newest one's entry for
    `mark_id`. Nothing is stored when `change` leaves the content as it was.
    """
    based_on = await latest(session, project.id)
    before = _normalised(based_on.content if based_on is not None else None)
    after = copy.deepcopy(before)
    change(_entry_for_edit(after, mark_id))
    if after == before and based_on is not None:
        return
    await _add_version(session, project, based_on, after)
    if commit:
        await session.commit()


def _set_verdict(entry: dict[str, Any], item_key: str, verdict: str) -> None:
    for item in entry["items"]:
        if item["item_key"] == item_key:
            item["verdict"] = verdict
            return
    entry["items"].append({"item_key": item_key, "verdict": verdict})


# --- The owner's actions -------------------------------------------------------------------


async def add_accepted(
    session: AsyncSession, project: Project, mark_id: str, item_key: str
) -> None:
    """An owner's own file counts as accepted when it is added (FT-11): it is shown after the
    mark's other pieces. Flushes but does not commit: the upload commits it with the item.
    """

    def change(entry: dict[str, Any]) -> None:
        _set_verdict(entry, item_key, ACCEPTED)
        if item_key not in entry["shown"]:
            entry["shown"].append(item_key)

    await _edit(session, project, mark_id, change, commit=False)


async def remove_item(session: AsyncSession, project: Project, mark_id: str, item_key: str) -> None:
    """The owner takes a file off the mark: it is rejected and no longer shown. The stored item
    and its files stay. Commits. Raises FootageDecisionError when the file is not shown.
    """
    current = await latest(session, project.id)
    if item_key not in shown_keys(current.content if current is not None else None, mark_id):
        raise FootageDecisionError(NOT_SHOWN_MESSAGE)

    def change(entry: dict[str, Any]) -> None:
        _set_verdict(entry, item_key, REJECTED)
        entry["shown"] = [key for key in entry["shown"] if key != item_key]

    await _edit(session, project, mark_id, change, commit=True)


async def reorder(session: AsyncSession, project: Project, mark_id: str, shown: list[str]) -> None:
    """Puts the files shown on a mark in a new order. `shown` must hold exactly the keys shown
    now, once each. Commits. Raises FootageDecisionError.
    """
    current = await latest(session, project.id)
    keys = shown_keys(current.content if current is not None else None, mark_id)
    if len(shown) != len(set(shown)) or sorted(shown) != sorted(keys):
        raise FootageDecisionError(ORDER_MESSAGE)

    def change(entry: dict[str, Any]) -> None:
        entry["shown"] = list(shown)

    await _edit(session, project, mark_id, change, commit=True)


async def set_use(
    session: AsyncSession,
    project: Project,
    mark_id: str,
    item_key: str,
    start_s: float,
    end_s: float,
    *,
    require_shown: bool = True,
) -> None:
    """Moves where a video file starts and ends, in seconds of its stored video. Commits. The
    times are checked by the caller. Raises FootageDecisionError when the file is not shown,
    unless `require_shown` is False (the review lets the owner move a piece before accepting it).
    """
    current = await latest(session, project.id)
    if require_shown and item_key not in shown_keys(
        current.content if current is not None else None, mark_id
    ):
        raise FootageDecisionError(NOT_SHOWN_MESSAGE)

    def change(entry: dict[str, Any]) -> None:
        entry["use"][item_key] = {"start_s": start_s, "end_s": end_s}

    await _edit(session, project, mark_id, change, commit=True)


async def set_no_footage(
    session: AsyncSession, project: Project, mark_ids: list[str], value: bool
) -> None:
    """Sets or clears the owner's "no footage here" on each of `mark_ids`, as one new version
    (FTG-007). Nothing is stored when nothing changes. Commits. A mark with no entry yet gets one
    with nothing else decided; clearing a flag on a mark with no entry stores nothing.
    """
    based_on = await latest(session, project.id)
    before = _normalised(based_on.content if based_on is not None else None)
    after = copy.deepcopy(before)
    for mark_id in mark_ids:
        if value:
            _entry_for_edit(after, mark_id)["no_footage"] = True
        else:
            for entry in after["marks"]:
                if entry["mark_id"] == mark_id:
                    entry["no_footage"] = False
    if after == before:
        return
    await _add_version(session, project, based_on, after)
    await session.commit()


async def set_verdict(
    session: AsyncSession,
    project: Project,
    mark_id: str,
    item_key: str,
    verdict: str,
    *,
    before: frozenset[str] = frozenset(),
) -> None:
    """The owner's verdict on a piece of the agent (FTG-012). `accepted` also shows it, ahead of
    the first piece in `before` that is shown (the owner's own files), or last when none is;
    a piece already shown keeps its place. `rejected` takes it off the mark. Commits. Nothing is
    stored when nothing changes. The caller checks that the piece may be decided on.
    """
    if verdict not in (ACCEPTED, REJECTED):
        raise FootageDecisionError("The verdict must be accepted or rejected.")

    def change(entry: dict[str, Any]) -> None:
        _set_verdict(entry, item_key, verdict)
        if verdict == ACCEPTED:
            if item_key not in entry["shown"]:
                position = next(
                    (index for index, key in enumerate(entry["shown"]) if key in before),
                    len(entry["shown"]),
                )
                entry["shown"].insert(position, item_key)
        else:
            entry["shown"] = [key for key in entry["shown"] if key != item_key]

    await _edit(session, project, mark_id, change, commit=True)


async def set_framing(
    session: AsyncSession, project: Project, mark_id: str, framing: str | None
) -> None:
    """The portrait crop of a mark: `left`, `centre`, `right` or None. Commits. The caller checks
    the value. Nothing is stored when nothing changes."""

    def change(entry: dict[str, Any]) -> None:
        entry["framing"] = framing

    await _edit(session, project, mark_id, change, commit=True)


async def set_round_reviewed(
    session: AsyncSession, project: Project, round_id: str, value: bool, *, commit: bool = True
) -> None:
    """Adds `round_id` (like `r2`) to the rounds the owner reviewed, or takes it off. Nothing is
    stored when it is already so. With `commit` False the version is flushed, not committed (a
    new import takes its round off in the transaction that stores the import).
    """
    based_on = await latest(session, project.id)
    before = _normalised(based_on.content if based_on is not None else None)
    after = copy.deepcopy(before)
    listed = [value for value in after["reviewed_rounds"] if value != round_id]
    after["reviewed_rounds"] = [*listed, round_id] if value else listed
    if after == before:
        return
    await _add_version(session, project, based_on, after)
    if commit:
        await session.commit()


# --- What is shown now (FTG-004) -----------------------------------------------------------

VIDEO_KIND: Final = "video"


@dataclass(frozen=True)
class ShownFootagePiece:
    """One piece the owner chose to show on a mark. `length_s` is how long a video piece can play
    (its `use`), and None for a still piece (image, page or PDF)."""

    item_key: str
    kind: str
    length_s: float | None


@dataclass(frozen=True)
class ShownFootageMark:
    """A footage mark that has pieces to show. `start` and `end` are code-point positions in
    `script_text` (end not included), as for claims; `pieces` are in the owner's order and are
    never empty."""

    id: str
    start: int
    end: int
    text: str
    pieces: tuple[ShownFootagePiece, ...]


def use_range(decided: Any, capture: Any) -> tuple[float, float] | None:
    """The part of a video that plays, `(start_s, end_s)` as the owner's moved `use` when there is
    one, otherwise as the capture recorded it. None when neither gives a positive length. (The
    owner's `use` is in seconds of the stored video; see `footage_clips` for a capture's.)"""
    for use in (decided, capture.get("use") if isinstance(capture, dict) else None):
        if not isinstance(use, dict):
            continue
        start, end = use.get("start_s"), use.get("end_s")
        if (
            isinstance(start, int | float)
            and isinstance(end, int | float)
            and not isinstance(start, bool)
            and not isinstance(end, bool)
            and end > start
        ):
            return float(start), float(end)
    return None


def _use_length(decided: Any, capture: Any) -> float | None:
    """The length of the part of a video that plays (see `use_range`), or None."""
    found = use_range(decided, capture)
    return None if found is None else round(found[1] - found[0], 3)


async def shown_marks(session: AsyncSession, project: Project) -> list[ShownFootageMark]:
    """The footage marks that have pieces to show, in story order (FTG-004).

    A mark counts when it is not dropped and its words are in the story. A piece is shown when the
    owner's newest decision lists it, its item is usable and its kind is known. A mark the owner
    decided "no footage here" for shows nothing. A project without footage reads no tables.
    """
    if not footage_marks.wanted(project):
        return []
    marks = footage_marks.counting((await footage_marks.state(session, project)).marks)
    if not marks:
        return []
    row = await latest(session, project.id)
    entries = {entry["mark_id"]: entry for entry in marks_of(row.content if row else None)}
    wanted = {
        mark["id"]: list(entries[mark["id"]]["shown"])
        for mark in marks
        if mark["id"] in entries and not entries[mark["id"]]["no_footage"]
    }
    keys = {key for shown in wanted.values() for key in shown}
    if not keys:
        return []
    statement = select(FootageItem).where(
        FootageItem.project_id == project.id, FootageItem.item_key.in_(keys)
    )
    items = {
        item.item_key: item
        for item in (
            await session.execute(statement.execution_options(populate_existing=True))
        ).scalars()
    }
    found: list[ShownFootageMark] = []
    for mark in marks:
        pieces: list[ShownFootagePiece] = []
        for key in wanted.get(mark["id"], []):
            item = items.get(key)
            if item is None or not item.usable or item.kind is None:
                continue
            length_s: float | None = None
            if item.kind == VIDEO_KIND:
                decided = entries[mark["id"]]["use"].get(key)
                length_s = _use_length(decided, item.capture)
                if length_s is None:
                    continue
            pieces.append(ShownFootagePiece(item_key=key, kind=item.kind, length_s=length_s))
        if pieces:
            found.append(
                ShownFootageMark(
                    id=mark["id"],
                    start=mark["start"],
                    end=mark["end"],
                    text=mark["text"],
                    pieces=tuple(pieces),
                )
            )
    return found
