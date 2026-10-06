"""What the app last learned about the GPU server and its API.

Page loads never call the GPU server (ITERATION_1_PHASES.md Section 4.2). They
read the stored results kept here: the last connection test (written by the
Test connection button and, from Phase 5, by the dispatcher) and the last
contract check (written by `contract_guard`). Callers read and write them only
through this module and `contract_guard`.

`system_status` is what the banner on every page reads. Phase 5 fills in
`waiting_jobs`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.providers import contract_guard
from app.providers.contract_guard import CheckResult, SourceCheck
from app.providers.gpu_server import HealthResult, check_health, health_url

GPU_URL_KEY = "gpu_api_base_url"


@dataclass(frozen=True)
class ConnectionTestOutcome:
    health: HealthResult
    # None when the health check failed: the API is not checked on a server that does not answer.
    contract: CheckResult | None


async def run_connection_test(session: AsyncSession) -> ConnectionTestOutcome:
    """Tests the saved GPU server URL now, then checks its API, and stores both results."""
    base_url = await settings_service.get_str(session, GPU_URL_KEY)
    # End the read transaction before the network call: never hold one across it.
    await session.commit()

    health = await check_health(base_url)
    await settings_service.write_internal(
        session, settings_service.GPU_CONNECTION_LAST_TEST, health.to_json()
    )
    contract = await contract_guard.check(session) if health.reachable else None
    return ConnectionTestOutcome(health=health, contract=contract)


async def last_connection_test(session: AsyncSession) -> HealthResult | None:
    """The stored result, or None if there is none for the address that would be called now.

    A test of an old address must never pass for the current one.
    """
    stored = HealthResult.from_json(
        await settings_service.read_internal(session, settings_service.GPU_CONNECTION_LAST_TEST)
    )
    if stored is None:
        return None

    base_url = await settings_service.get_str(session, GPU_URL_KEY)
    return stored if stored.called_url == health_url(base_url) else None


@dataclass(frozen=True)
class ServerStatus:
    state: Literal["reachable", "unreachable", "unknown"]
    checked_at: datetime | None
    called_url: str | None
    error: str | None


@dataclass(frozen=True)
class ContractStatus:
    state: Literal["ok", "changed", "not_approved", "unreachable", "unknown"]
    # When the result was recorded. None for "not_approved" and "unknown".
    checked_at: datetime | None
    sources: tuple[SourceCheck, ...]
    message: str | None


@dataclass(frozen=True)
class SystemStatus:
    server: ServerStatus
    contract: ContractStatus
    waiting_jobs: int


def _server_status(health: HealthResult | None) -> ServerStatus:
    if health is None:
        return ServerStatus(state="unknown", checked_at=None, called_url=None, error=None)
    return ServerStatus(
        state="reachable" if health.reachable else "unreachable",
        checked_at=health.checked_at,
        called_url=health.called_url,
        error=health.error,
    )


def _contract_status(stored: CheckResult | None, missing: list[str]) -> ContractStatus:
    # Computed from the approved snapshots on every read, so it is never stale.
    if missing:
        return ContractStatus(
            state="not_approved",
            checked_at=None,
            sources=stored.sources if stored is not None else (),
            message=f"Not approved yet: {', '.join(missing)}.",
        )
    # Every source has an approved version now, so a stored "not_approved" is out of date.
    if stored is None or stored.status == "not_approved":
        return ContractStatus(state="unknown", checked_at=None, sources=(), message=None)

    message: str | None = None
    if stored.status == "changed":
        names = [
            item.name
            for item in stored.sources
            if item.status in ("changed", "unreadable") and item.approved_fingerprint is not None
        ]
        message = f"Differs from the approved version: {', '.join(names)}."
    elif stored.status == "unreachable":
        problems = [item.message for item in stored.sources if item.status == "unreachable"]
        message = next((text for text in problems if text), "The API could not be fetched.")
    return ContractStatus(
        state=stored.status, checked_at=stored.checked_at, sources=stored.sources, message=message
    )


async def system_status(session: AsyncSession) -> SystemStatus:
    """The stored state the banner on every page reads. Never calls the GPU server."""
    server = _server_status(await last_connection_test(session))
    contract = _contract_status(
        await contract_guard.last_check(session), await contract_guard.missing_baselines(session)
    )
    # Phase 5 counts the jobs paused by a changed API here.
    return SystemStatus(server=server, contract=contract, waiting_jobs=0)
