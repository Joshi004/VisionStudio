"""A DateTime type that stores naive UTC and returns timezone-aware UTC.

SQLite stores no time zone (DATABASE_STRUCTURE.md Section 1). Without this,
elapsed times computed in the browser would be off by the server's own
offset (ITERATION_1_PHASES.md Phase 1 pitfalls, 5.5 hours for this project).
Always construct new timestamps with `utcnow()`, never `datetime.now()` or
`datetime.utcnow()` (the latter returns a naive value and is deprecated).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    """The current time, timezone-aware, in UTC."""
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Stores naive UTC in SQLite; always returns timezone-aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime passed to UTCDateTime; use utcnow()")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)
