"""What the app last learned about the GPU server.

Page loads never call the GPU server (ITERATION_1_PHASES.md Section 4.2). They
read the result stored here, which is written by the Test connection button in
Phase 2, and later also by the contract guard (Phase 4) and the dispatcher
(Phase 5). Callers read and write it only through this module.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.providers.gpu_server import HealthResult, check_health, health_url

GPU_URL_KEY = "gpu_api_base_url"


async def run_connection_test(session: AsyncSession) -> HealthResult:
    """Tests the saved GPU server URL now, stores the result and returns it."""
    base_url = await settings_service.get_str(session, GPU_URL_KEY)
    # End the read transaction before the network call: never hold one across it.
    await session.commit()

    result = await check_health(base_url)
    await settings_service.write_internal(
        session, settings_service.GPU_CONNECTION_LAST_TEST, result.to_json()
    )
    return result


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
