"""`GET /api/health`: the database, FFmpeg and ffprobe, all read through the
app's own engine (ITERATION_1_PHASES.md Phase 1 [VERIFY]: `foreign_keys`
is a per-connection SQLite setting, so it must be checked this way, not
through a separate `sqlite3` session).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionDep

router = APIRouter()


class DatabaseStatus(BaseModel):
    ok: bool
    journal_mode: str | None = None
    foreign_keys: int | None = None
    revision: str | None = None


class ToolStatus(BaseModel):
    ok: bool
    version: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: DatabaseStatus
    ffmpeg: ToolStatus
    ffprobe: ToolStatus


async def _check_database(session: AsyncSession) -> DatabaseStatus:
    try:
        await session.execute(text("SELECT 1"))
        journal_mode = (await session.execute(text("PRAGMA journal_mode"))).scalar_one()
        foreign_keys = (await session.execute(text("PRAGMA foreign_keys"))).scalar_one()
        revision = (
            await session.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
    except SQLAlchemyError:
        return DatabaseStatus(ok=False)

    ok = journal_mode == "wal" and foreign_keys == 1 and revision is not None
    return DatabaseStatus(
        ok=ok, journal_mode=journal_mode, foreign_keys=foreign_keys, revision=revision
    )


def _tool_status(request: Request, tool: Literal["ffmpeg", "ffprobe"]) -> ToolStatus:
    # Set once at startup by the lifespan handler in app/main.py.
    version: str | None = getattr(request.app.state, f"{tool}_version", None)
    return ToolStatus(ok=version is not None, version=version)


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Something is not OK."}},
)
async def get_health(request: Request, response: Response, session: SessionDep) -> HealthResponse:
    database = await _check_database(session)
    ffmpeg = _tool_status(request, "ffmpeg")
    ffprobe = _tool_status(request, "ffprobe")

    healthy = database.ok and ffmpeg.ok and ffprobe.ok
    response.status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded",
        database=database,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
