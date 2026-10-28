"""Computes each stage's `state()` once per project during a read-only pass.

Every stage's `state()` is worked out on every read and calls the `state()` of the stages before
it, so one request used to compute the same stage hundreds of times. While the memo is on for a
session, `memoized_state` keeps the first answer for each (stage, project) and gives it back to
every later caller on the same session.

The memo is on only where the code reads and writes nothing:

- a GET request (`get_session` turns it on), and
- the evaluate pass of a pipeline run (`reading`).

Safety rules:

- The memo lives in `session.info`, so it is private to one request or one pass and is gone with
  the session.
- Any flush, commit or rollback replaces the memo with an empty one. A state is never kept past
  a write, even a write nobody expected in a read path.
- A result computed while a write happened is not kept.
- An exception is never kept.
- With the memo off, `memoized_state` calls the function as it was.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.models import Project

_logger = logging.getLogger(__name__)

_MEMO_KEY = "state_memo"
_STATS_KEY = "state_memo_stats"


def enable(session: AsyncSession) -> None:
    """Starts keeping `state()` answers on this session."""
    session.info[_MEMO_KEY] = {}
    session.info[_STATS_KEY] = {"computed": 0, "reused": 0}


def disable(session: AsyncSession) -> None:
    """Stops keeping `state()` answers and forgets them."""
    session.info.pop(_MEMO_KEY, None)
    stats = session.info.pop(_STATS_KEY, None)
    if stats is not None and stats["computed"]:
        _logger.debug("state memo: %d computed, %d reused", stats["computed"], stats["reused"])


@asynccontextmanager
async def reading(session: AsyncSession) -> AsyncIterator[None]:
    """The memo is on inside the block and always off after it."""
    enable(session)
    try:
        yield
    finally:
        disable(session)


def memoized_state[T](
    function: Callable[[AsyncSession, Any], Awaitable[T]],
) -> Callable[[AsyncSession, Any], Awaitable[T]]:
    """For a stage's `state(session, project)`. `project` is a `Project` or its id."""
    name = f"{function.__module__}.{function.__qualname__}"

    @wraps(function)
    async def wrapper(session: AsyncSession, project: Project | int) -> T:
        memo = session.info.get(_MEMO_KEY)
        if memo is None:
            return await function(session, project)
        key = (name, project if isinstance(project, int) else project.id)
        if key in memo:
            session.info[_STATS_KEY]["reused"] += 1
            return memo[key]
        result = await function(session, project)
        # A write during the computation replaced the memo: the result may be out of date.
        if session.info.get(_MEMO_KEY) is memo:
            memo[key] = result
            session.info[_STATS_KEY]["computed"] += 1
        return result

    return wrapper


def _forget(sync_session: Session, *_ignored: object) -> None:
    """After any write the answers kept so far may be out of date."""
    if _MEMO_KEY in sync_session.info:
        sync_session.info[_MEMO_KEY] = {}


event.listen(Session, "after_flush", _forget)
event.listen(Session, "after_commit", _forget)
event.listen(Session, "after_rollback", _forget)
