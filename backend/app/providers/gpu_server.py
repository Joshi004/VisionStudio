"""Talking to the GPU server: the health check (Phase 2).

The contract guard (Phase 4) is `contract_guard.py` next to this module, and
Phases 5 and 9 add the transcription and video adapters here too.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core import outbound
from app.core.urls import docker_mapped, join_url
from app.db.types import utcnow

HEALTH_PATH = "/v1/health"
HEALTH_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class HealthResult:
    """The outcome of one health check. Unreachable is a normal outcome, not an error."""

    reachable: bool
    called_url: str
    elapsed_ms: int
    http_status: int | None
    default_partition: str | None
    error: str | None
    checked_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "called_url": self.called_url,
            "elapsed_ms": self.elapsed_ms,
            "http_status": self.http_status,
            "default_partition": self.default_partition,
            "error": self.error,
            "checked_at": self.checked_at.isoformat(),
        }

    @classmethod
    def from_json(cls, data: object) -> HealthResult | None:
        """Rebuilds a stored result. Returns None when the data is missing or malformed."""
        if not isinstance(data, dict):
            return None
        try:
            checked_at = datetime.fromisoformat(data["checked_at"])
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=UTC)
            result = cls(
                reachable=data["reachable"],
                called_url=data["called_url"],
                elapsed_ms=data["elapsed_ms"],
                http_status=data["http_status"],
                default_partition=data["default_partition"],
                error=data["error"],
                checked_at=checked_at,
            )
        except (KeyError, TypeError, ValueError):
            return None

        types_ok = (
            isinstance(result.reachable, bool)
            and isinstance(result.called_url, str)
            and isinstance(result.elapsed_ms, int)
            and (result.http_status is None or isinstance(result.http_status, int))
            and (result.default_partition is None or isinstance(result.default_partition, str))
            and (result.error is None or isinstance(result.error, str))
        )
        return result if types_ok else None


def health_url(base_url: str) -> str:
    """The address a health check calls for this base URL, after Docker mapping."""
    return docker_mapped(join_url(base_url, HEALTH_PATH))


async def check_health(base_url: str) -> HealthResult:
    """Calls `GET /v1/health` on the GPU server. Never raises for a network problem.

    "Reachable" means HTTP 200 with a JSON object whose `status` is "ok".
    """
    called_url = health_url(base_url)
    checked_at = utcnow()
    started = time.monotonic()

    def result(
        *,
        reachable: bool,
        http_status: int | None = None,
        default_partition: str | None = None,
        error: str | None = None,
    ) -> HealthResult:
        return HealthResult(
            reachable=reachable,
            called_url=called_url,
            elapsed_ms=round((time.monotonic() - started) * 1000),
            http_status=http_status,
            default_partition=default_partition,
            error=error,
            checked_at=checked_at,
        )

    try:
        response = await outbound.request(
            "GET", join_url(base_url, HEALTH_PATH), timeout_s=HEALTH_TIMEOUT_S
        )
    except outbound.OutboundError as exc:
        return result(reachable=False, error=str(exc))

    status = response.status_code
    if status != 200:
        return result(
            reachable=False, http_status=status, error=f"The server answered HTTP {status}."
        )

    try:
        body = response.json()
    except ValueError:
        return result(reachable=False, http_status=status, error="The answer was not valid JSON.")

    if not isinstance(body, dict) or body.get("status") != "ok":
        return result(
            reachable=False,
            http_status=status,
            error="The answer is not the GPU API's health response.",
        )

    partition = body.get("default_partition")
    return result(
        reachable=True,
        http_status=status,
        default_partition=partition if isinstance(partition, str) else None,
    )
