"""`/api/gpu`: what the app knows about the GPU server.

Phase 2 has the connection test only. The contract guard (Phase 4) adds to
this area.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.db.session import SessionDep
from app.services import gpu_status

router = APIRouter()


class ConnectionTest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reachable: bool
    called_url: str
    elapsed_ms: int
    http_status: int | None
    default_partition: str | None
    error: str | None
    checked_at: datetime


class ConnectionState(BaseModel):
    # None when nothing was tested yet, or only a different address was.
    last_test: ConnectionTest | None


@router.get("/gpu/connection", response_model=ConnectionState)
async def get_connection(session: SessionDep) -> ConnectionState:
    """The last stored test result. Reads the database only, never calls the server."""
    result = await gpu_status.last_connection_test(session)
    return ConnectionState(
        last_test=None if result is None else ConnectionTest.model_validate(result)
    )


@router.post("/gpu/connection/test", response_model=ConnectionTest)
async def test_connection(session: SessionDep) -> ConnectionTest:
    """Tests the saved GPU server URL now. An unreachable server is a normal 200 answer."""
    result = await gpu_status.run_connection_test(session)
    return ConnectionTest.model_validate(result)
