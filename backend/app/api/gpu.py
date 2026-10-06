"""`/api/gpu`: what the app knows about the GPU server and its API.

The connection test (Phase 2) and the contract guard (Phase 4). Everything
here except the two POST actions and the sources editor reads the database
only: page loads never call the GPU server.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.api.errors import ErrorResponse
from app.core import settings as settings_service
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.providers import contract_guard
from app.services import gpu_status

router = APIRouter()

_VALIDATION_ERROR: dict[int | str, dict[str, object]] = {
    422: {"model": ErrorResponse, "description": "The value is not valid."},
}


class _FromObject(BaseModel):
    """Output models are filled from the service's dataclasses."""

    model_config = ConfigDict(from_attributes=True)


# --- Connection test -------------------------------------------------------------


class ConnectionTest(_FromObject):
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


class SourceCheckOut(_FromObject):
    name: str
    called_url: str
    status: Literal["ok", "changed", "not_approved", "unreachable", "unreadable"]
    message: str | None
    approved_fingerprint: str | None
    current_fingerprint: str | None


class ContractCheckOut(_FromObject):
    status: Literal["ok", "changed", "not_approved", "unreachable"]
    checked_at: datetime
    sources: list[SourceCheckOut]


class ConnectionTestResult(BaseModel):
    health: ConnectionTest
    # None when the server did not answer, so its API was not checked.
    contract: ContractCheckOut | None


@router.get("/gpu/connection", response_model=ConnectionState)
async def get_connection(session: SessionDep) -> ConnectionState:
    """The last stored test result. Reads the database only, never calls the server."""
    result = await gpu_status.last_connection_test(session)
    return ConnectionState(
        last_test=None if result is None else ConnectionTest.model_validate(result)
    )


@router.post("/gpu/connection/test", response_model=ConnectionTestResult)
async def test_connection(session: SessionDep) -> ConnectionTestResult:
    """Tests the saved GPU server URL now, then checks its API if it answered.

    An unreachable server is a normal 200 answer.
    """
    outcome = await gpu_status.run_connection_test(session)
    # A server that answers again can let waiting jobs proceed.
    dispatcher.nudge()
    return ConnectionTestResult(
        health=ConnectionTest.model_validate(outcome.health),
        contract=None
        if outcome.contract is None
        else ContractCheckOut.model_validate(outcome.contract),
    )


# --- Status for the banner -------------------------------------------------------


class ServerStatusOut(_FromObject):
    state: Literal["reachable", "unreachable", "unknown"]
    checked_at: datetime | None
    called_url: str | None
    error: str | None


class ContractStatusOut(_FromObject):
    state: Literal["ok", "changed", "not_approved", "unreachable", "unknown"]
    checked_at: datetime | None
    sources: list[SourceCheckOut]
    message: str | None


class GpuStatus(_FromObject):
    server: ServerStatusOut
    contract: ContractStatusOut
    waiting_jobs: int


@router.get("/gpu/status", response_model=GpuStatus)
async def get_status(session: SessionDep) -> GpuStatus:
    """The stored state the banner reads. Reads the database only, never calls the server."""
    return GpuStatus.model_validate(await gpu_status.system_status(session))


# --- Contract: sources -----------------------------------------------------------


class ContractSourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    base: StrictStr
    path: StrictStr


class ContractSourcesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[ContractSourceIn]


class ContractSourceOut(BaseModel):
    name: str
    base: Literal["gpu", "transcription"]
    path: str
    called_url: str


class ContractSourcesOut(BaseModel):
    sources: list[ContractSourceOut]
    source: Literal["saved", "built_in"]
    updated_at: datetime | None
    note: str | None


def _sources_out(
    effective: settings_service.EffectiveContractSources, urls: dict[str, str]
) -> ContractSourcesOut:
    return ContractSourcesOut(
        sources=[
            ContractSourceOut(
                name=item.name, base=item.base, path=item.path, called_url=urls[item.name]
            )
            for item in effective.sources
        ],
        source=effective.source,
        updated_at=effective.updated_at,
        note=effective.note,
    )


async def _current_urls(session: SessionDep) -> dict[str, str]:
    return {source.name: url for source, url in await contract_guard.called_urls(session)}


@router.put("/gpu/contract/sources", response_model=ContractSourcesOut, responses=_VALIDATION_ERROR)
async def save_contract_sources(
    body: ContractSourcesUpdate, session: SessionDep
) -> ContractSourcesOut:
    """Saves the list of sources whose answers are recorded and checked."""
    try:
        effective = await settings_service.save_contract_sources(
            session, [item.model_dump() for item in body.sources]
        )
    except settings_service.SettingValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _sources_out(effective, await _current_urls(session))


@router.delete("/gpu/contract/sources", response_model=ContractSourcesOut)
async def reset_contract_sources(session: SessionDep) -> ContractSourcesOut:
    """Removes the saved list, so the built-in sources apply again."""
    effective = await settings_service.reset_contract_sources(session)
    return _sources_out(effective, await _current_urls(session))


# --- Contract: the recorded API ----------------------------------------------------


class OperationOut(_FromObject):
    method: str
    path: str
    summary: str | None


class TagGroupOut(_FromObject):
    tag: str
    operations: list[OperationOut]


class DiffEntryOut(_FromObject):
    path: str
    kind: Literal["added", "removed", "changed"]
    before: str | None
    after: str | None
    text_diff: list[str] | None


class OpenApiChangesOut(_FromObject):
    operations_added: list[str]
    operations_removed: list[str]
    operations_changed: list[str]
    schemas_added: list[str]
    schemas_removed: list[str]
    schemas_changed: list[str]


class ContractDiffOut(_FromObject):
    entries: list[DiffEntryOut]
    truncated: bool
    openapi: OpenApiChangesOut | None


class ApprovedSummaryOut(_FromObject):
    snapshot_id: int
    fingerprint: str
    server_content_hash: str | None
    api_version: str | None
    fetched_at: datetime
    approved_at: datetime | None
    operation_count: int | None
    tags: list[TagGroupOut]


class PendingChangeOut(_FromObject):
    snapshot_id: int
    fingerprint: str
    api_version: str | None
    fetched_at: datetime
    diff: ContractDiffOut


class SourceOverviewOut(BaseModel):
    name: str
    base: Literal["gpu", "transcription"]
    path: str
    called_url: str
    approved: ApprovedSummaryOut | None
    pending: PendingChangeOut | None
    last_check: SourceCheckOut | None


class ContractOverviewOut(BaseModel):
    sources_setting: ContractSourcesOut
    last_check: ContractCheckOut | None
    sources: list[SourceOverviewOut]


@router.get("/gpu/contract", response_model=ContractOverviewOut)
async def get_contract(session: SessionDep) -> ContractOverviewOut:
    """The approved API, any change waiting for approval, and the last check.

    Reads the database only, never calls the server, and never returns whole documents.
    """
    overview = await contract_guard.overview(session)
    urls = {item.source.name: item.called_url for item in overview.sources}
    return ContractOverviewOut(
        sources_setting=_sources_out(overview.sources_setting, urls),
        last_check=None
        if overview.last_check is None
        else ContractCheckOut.model_validate(overview.last_check),
        sources=[
            SourceOverviewOut(
                name=item.source.name,
                base=item.source.base,
                path=item.source.path,
                called_url=item.called_url,
                approved=None
                if item.approved is None
                else ApprovedSummaryOut.model_validate(item.approved),
                pending=None
                if item.pending is None
                else PendingChangeOut.model_validate(item.pending),
                last_check=None
                if item.last_check is None
                else SourceCheckOut.model_validate(item.last_check),
            )
            for item in overview.sources
        ],
    )


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Source name -> the fingerprint the user reviewed. Empty for a first approval.
    expected: dict[str, StrictStr] = Field(default_factory=dict)


class SourceApprovalOut(_FromObject):
    name: str
    called_url: str
    outcome: Literal[
        "approved", "unchanged", "unstable", "changed_again", "unreachable", "unreadable"
    ]
    message: str | None
    fingerprint: str | None
    diff: ContractDiffOut | None


class ApproveResponse(BaseModel):
    approved: bool
    sources: list[SourceApprovalOut]


@router.post("/gpu/contract/approve", response_model=ApproveResponse)
async def approve_contract(body: ApproveRequest, session: SessionDep) -> ApproveResponse:
    """Records the API as it is now, if every source answers the same twice.

    Takes a few seconds: each source is fetched twice, a few seconds apart. A refused
    approval is a normal 200 answer with `approved: false` and a reason per source.
    """
    result = await contract_guard.approve(session, body.expected)
    # An approved API releases the jobs that were paused because it had changed.
    dispatcher.nudge()
    return ApproveResponse(
        approved=result.approved,
        sources=[SourceApprovalOut.model_validate(item) for item in result.sources],
    )
