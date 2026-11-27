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
- `framing` and `no_footage`, `reviewed_rounds`: written by the review (FTG-012), kept as they are.

A decision names a piece by its `item_key`, so a new import keeps the decisions for pieces that
did not change. This module only stores what it is given: the rules about files and times are
checked by `services/footage_files.py`.
"""

from __future__ import annotations

import copy
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FootageDecision, Project

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
) -> None:
    """Moves where a video file starts and ends, in seconds of its stored video. Commits. The
    times are checked by the caller. Raises FootageDecisionError when the file is not shown.
    """
    current = await latest(session, project.id)
    if item_key not in shown_keys(current.content if current is not None else None, mark_id):
        raise FootageDecisionError(NOT_SHOWN_MESSAGE)

    def change(entry: dict[str, Any]) -> None:
        entry["use"][item_key] = {"start_s": start_s, "end_s": end_s}

    await _edit(session, project, mark_id, change, commit=True)
