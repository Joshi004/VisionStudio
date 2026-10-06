"""The async database engine and session factory.

Async SQLAlchemy with aiosqlite (Phase 1 decision, approved): the Phase 5
dispatcher loop lives in the event loop, so the app never blocks it on a
database call. Alembic, which runs synchronously, uses the plain
`sqlite://` driver instead (see `app/db/migrations/env.py`).

This module is deliberately not imported by `app/db/models.py`, so running
Alembic (which only needs the ORM metadata) never creates this async engine.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_config

engine = create_async_engine(get_config().async_database_url)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
    """Runs on every new connection the pool opens (Phase 1 decision, approved).

    `foreign_keys` is a per-connection SQLite setting, not a database-wide
    one, so it must be set here rather than once at startup
    (ITERATION_1_PHASES.md Phase 1 [VERIFY]: check it through the app's
    engine, not a separate `sqlite3` session).
    """
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


# `expire_on_commit=False`: with async SQLAlchemy, lazy loading (which a post-commit
# expire would trigger on next attribute access) fails outside an active session
# (ITERATION_1_PHASES.md Phase 1 pitfalls). Model instances keep their values after commit.
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    async with SessionLocal() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
