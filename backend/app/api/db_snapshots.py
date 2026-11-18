"""`/api/db-snapshots`: the database snapshots in the files folder (STOR-004)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.api.errors import ErrorResponse
from app.services import db_snapshots as service

router = APIRouter()


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    made_at: datetime
    size_bytes: int


class SnapshotsStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # False when snapshots cannot be made now; `problem` says why.
    enabled: bool
    problem: str | None
    running: bool
    last: SnapshotOut | None
    last_error: str | None
    stale: bool


@router.get("/db-snapshots", response_model=SnapshotsStatusOut)
async def get_db_snapshots() -> SnapshotsStatusOut:
    return SnapshotsStatusOut.model_validate(await service.status())


@router.post(
    "/db-snapshots",
    response_model=SnapshotsStatusOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: {"model": ErrorResponse, "description": "Off, or one is already running."}},
)
async def make_db_snapshot() -> SnapshotsStatusOut:
    """Starts a snapshot in the background. Poll `GET` to see when it is done."""
    try:
        await service.request_snapshot()
    except (service.SnapshotsOff, service.SnapshotRunning) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return SnapshotsStatusOut.model_validate(await service.status())
