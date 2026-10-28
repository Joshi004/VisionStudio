"""Counts the committed writes of each project, so a client can tell cheaply that "something
changed" (`GET /api/projects/{id}/activity`).

Two counters are kept in memory, in the one backend process:

- one per project, bumped when a commit wrote a row that belongs to the project (a row with a
  `project_id`, or the project itself);
- one for everything else (library items, settings, labs, and any statement that names no
  project), bumped for every project's revision, because a project may read any of it.

Rules:

- Writes are noted while the session works and only counted at `after_commit`, so a client
  that sees a new revision always finds the data committed. A rollback forgets them. A
  savepoint that is rolled back keeps them: a bump too many is harmless, one too few is not.
- Jobs are not counted here. A job changes all the time, and the job rows are read directly
  (`services/activity.py`).
- The counters are lost with the process. `BOOT_ID` is part of every revision, so a restart
  always changes it.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session

from app.db.models import Project

BOOT_ID: Final = uuid4().hex[:8]

# Tables whose writes say nothing about a project's data: the job rows are read directly, the
# other two are written by the provider guard and by measuring audio.
_IGNORED_TABLES: Final = frozenset({"job", "api_snapshot", "audio_measurement"})

_PENDING_KEY = "activity_pending"
# The key of what a session wrote that belongs to no project.
_GLOBAL: Final = "global"

_global_count = 0
_project_counts: dict[int, int] = {}


def counters(project_id: int) -> tuple[str, int, int]:
    """The boot id, the count of writes that belong to no project, and the project's own."""
    return BOOT_ID, _global_count, _project_counts.get(project_id, 0)


def _note(session: Session, scope: int | str) -> None:
    """Remembers that this session wrote something of `scope` (a project id, or `_GLOBAL`)."""
    pending: set[int | str] = session.info.setdefault(_PENDING_KEY, set())
    pending.add(scope)


def _scope_of(obj: object) -> int | str | None:
    """Whose data a changed row is: a project id, `_GLOBAL`, or None when it does not count."""
    table = getattr(obj, "__tablename__", None)
    if table in _IGNORED_TABLES:
        return None
    if isinstance(obj, Project):
        return obj.id
    project_id = getattr(obj, "project_id", None)
    return project_id if isinstance(project_id, int) else _GLOBAL


def _on_after_flush(session: Session, _context: object) -> None:
    changed: list[Any] = [*session.new, *session.deleted]
    changed.extend(obj for obj in session.dirty if session.is_modified(obj))
    for obj in changed:
        scope = _scope_of(obj)
        if scope is not None:
            _note(session, scope)


def _on_orm_execute(state: ORMExecuteState) -> None:
    """A statement that writes without going through the unit of work (`update(Model)`,
    `delete(Model)`, `insert(Model)`). It names a table, not a project, so it counts for all.
    """
    if not (state.is_insert or state.is_update or state.is_delete):
        return
    table = getattr(state.statement, "table", None)
    if getattr(table, "name", None) in _IGNORED_TABLES:
        return
    _note(state.session, _GLOBAL)


def _on_after_commit(session: Session) -> None:
    global _global_count
    pending: set[int | str] = session.info.pop(_PENDING_KEY, set())
    for scope in pending:
        if scope == _GLOBAL:
            _global_count += 1
        elif isinstance(scope, int):
            _project_counts[scope] = _project_counts.get(scope, 0) + 1


def _on_after_rollback(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)


event.listen(Session, "after_flush", _on_after_flush)
event.listen(Session, "do_orm_execute", _on_orm_execute)
event.listen(Session, "after_commit", _on_after_commit)
event.listen(Session, "after_rollback", _on_after_rollback)
