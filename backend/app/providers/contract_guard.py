"""The GPU API contract guard (ANALYSIS.md Section 6.4 `ContractGuard` and 6.5).

Each configured source is a GET address whose JSON answer is recorded in
`api_snapshot`. You approve the recorded API once, and `check()` compares what
the server says now with the approved version. From Phase 5 on, the dispatcher
calls `check()` before it submits anything and submits only when `is_ok`
(both "changed" and "not approved" block). Phase 4 runs it from Test
connection and from `approve()`.

Rules that hold throughout:

- Snapshots are only ever inserted, never edited or deleted. The baseline of a
  source is its latest approved row, matched by source name and path.
- A pending row is never stored twice for the same version of a source.
- No database transaction is held across a network call: each function reads,
  commits to end the read, fetches, then makes one short write.
- One lock serialises `check()` and `approve()`. That is enough because the
  backend is one process (ANALYSIS.md Section 3.2).
- Logs name sources, statuses and short fingerprints, never document bodies.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, get_args

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbound
from app.core import settings as settings_service
from app.core.settings import ContractSource, EffectiveContractSources
from app.core.urls import docker_mapped, join_url
from app.db.models import ApiSnapshot
from app.db.types import utcnow
from app.services import api_contract
from app.services.api_contract import ContractDiff, TagGroup

CAPTURE_GAP_S = 3.0
FETCH_TIMEOUT_S = 10.0

SourceStatus = Literal["ok", "changed", "not_approved", "unreachable", "unreadable"]
CheckStatus = Literal["ok", "changed", "not_approved", "unreachable"]
ApproveOutcome = Literal[
    "approved", "unchanged", "unstable", "changed_again", "unreachable", "unreadable"
]

_logger = logging.getLogger(__name__)
_lock = asyncio.Lock()


# --- Results ---------------------------------------------------------------------


@dataclass(frozen=True)
class SourceCheck:
    """What one source looked like at the last check."""

    name: str
    called_url: str
    status: SourceStatus
    message: str | None
    approved_fingerprint: str | None
    current_fingerprint: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "called_url": self.called_url,
            "status": self.status,
            "message": self.message,
            "approved_fingerprint": self.approved_fingerprint,
            "current_fingerprint": self.current_fingerprint,
        }

    @classmethod
    def from_json(cls, data: object) -> SourceCheck | None:
        """Rebuilds a stored source result. Returns None when it is malformed."""
        if not isinstance(data, dict):
            return None
        try:
            item = cls(
                name=data["name"],
                called_url=data["called_url"],
                status=data["status"],
                message=data["message"],
                approved_fingerprint=data["approved_fingerprint"],
                current_fingerprint=data["current_fingerprint"],
            )
        except KeyError:
            return None

        texts_ok = isinstance(item.name, str) and isinstance(item.called_url, str)
        optional_ok = all(
            value is None or isinstance(value, str)
            for value in (item.message, item.approved_fingerprint, item.current_fingerprint)
        )
        status_ok = item.status in get_args(SourceStatus)
        return item if texts_ok and optional_ok and status_ok else None


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one `check()` over every configured source."""

    status: CheckStatus
    checked_at: datetime
    sources: tuple[SourceCheck, ...]

    @property
    def is_ok(self) -> bool:
        """True only when every source matches its approved version."""
        return self.status == "ok"

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checked_at": self.checked_at.isoformat(),
            "sources": [item.to_json() for item in self.sources],
        }

    @classmethod
    def from_json(cls, data: object) -> CheckResult | None:
        """Rebuilds a stored result. Returns None when the data is missing or malformed."""
        if not isinstance(data, dict):
            return None
        try:
            status = data["status"]
            checked_at = datetime.fromisoformat(data["checked_at"])
            raw_sources = data["sources"]
        except (KeyError, TypeError, ValueError):
            return None

        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=UTC)
        if status not in get_args(CheckStatus) or not isinstance(raw_sources, list):
            return None

        sources = [SourceCheck.from_json(raw) for raw in raw_sources]
        if any(item is None for item in sources):
            return None
        return cls(
            status=status,
            checked_at=checked_at,
            sources=tuple(item for item in sources if item is not None),
        )


@dataclass(frozen=True)
class SourceApproval:
    name: str
    called_url: str
    outcome: ApproveOutcome
    message: str | None
    fingerprint: str | None
    # Only for "unstable": what differed between the two fetches.
    diff: ContractDiff | None


@dataclass(frozen=True)
class ApproveResult:
    approved: bool
    sources: tuple[SourceApproval, ...]


@dataclass(frozen=True)
class ApprovedSummary:
    snapshot_id: int
    fingerprint: str
    server_content_hash: str | None
    api_version: str | None
    fetched_at: datetime
    approved_at: datetime | None
    # Only for an OpenAPI document.
    operation_count: int | None
    tags: tuple[TagGroup, ...]


@dataclass(frozen=True)
class PendingChange:
    snapshot_id: int
    fingerprint: str
    api_version: str | None
    fetched_at: datetime
    diff: ContractDiff


@dataclass(frozen=True)
class SourceOverview:
    source: ContractSource
    called_url: str
    approved: ApprovedSummary | None
    pending: PendingChange | None
    last_check: SourceCheck | None


@dataclass(frozen=True)
class ContractOverview:
    sources_setting: EffectiveContractSources
    last_check: CheckResult | None
    sources: tuple[SourceOverview, ...]


# --- Fetching --------------------------------------------------------------------


@dataclass(frozen=True)
class _Document:
    body: dict[str, Any]
    fingerprint: str
    server_content_hash: str | None
    api_version: str | None
    fetched_at: datetime


@dataclass(frozen=True)
class _Failure:
    kind: Literal["unreachable", "unreadable"]
    message: str


_Fetched = _Document | _Failure


async def _fetch(called_url: str) -> _Fetched:
    """Fetches one source. Never raises for a network problem.

    No answer at all (connection, timeout) and HTTP 5xx mean the server is
    "unreachable". Anything else that is not a JSON object, such as HTTP 4xx, a
    redirect, an answer that is too large or not JSON, means the documented
    address no longer answers as recorded: "unreadable".
    """
    fetched_at = utcnow()
    try:
        response = await outbound.request("GET", called_url, timeout_s=FETCH_TIMEOUT_S)
    except outbound.OutboundError as exc:
        kind = "unreachable" if exc.reason in ("connection", "timeout") else "unreadable"
        return _Failure(kind, str(exc))

    status = response.status_code
    if status >= 500:
        return _Failure("unreachable", f"The server answered HTTP {status}.")
    if status != 200:
        return _Failure("unreadable", f"The server answered HTTP {status} for this address.")

    try:
        body = response.json()
    except (ValueError, RecursionError):
        return _Failure("unreadable", "The answer is not valid JSON.")
    if not isinstance(body, dict):
        return _Failure("unreadable", "The answer is not a JSON object.")

    value, server_hash = api_contract.fingerprint(body)
    return _Document(
        body=body,
        fingerprint=value,
        server_content_hash=server_hash,
        api_version=api_contract.api_version(body),
        fetched_at=fetched_at,
    )


async def _fetch_all(targets: Sequence[_Target]) -> list[_Fetched]:
    return list(await asyncio.gather(*(_fetch(target.called_url) for target in targets)))


# --- Reading what is recorded ----------------------------------------------------


@dataclass(frozen=True)
class _Baseline:
    id: int
    fingerprint: str
    fetched_at: datetime


@dataclass(frozen=True)
class _Target:
    source: ContractSource
    called_url: str
    baseline: _Baseline | None


async def called_urls(session: AsyncSession) -> list[tuple[ContractSource, str]]:
    """Each source with the address it would be fetched from now, after Docker mapping."""
    effective = await settings_service.read_contract_sources(session)
    base_urls: dict[str, str] = {}
    pairs: list[tuple[ContractSource, str]] = []
    for source in effective.sources:
        if source.base not in base_urls:
            key = settings_service.BASE_SETTING[source.base]
            base_urls[source.base] = await settings_service.get_str(session, key)
        pairs.append((source, docker_mapped(join_url(base_urls[source.base], source.path))))
    return pairs


async def _latest_approved(session: AsyncSession, source: ContractSource) -> _Baseline | None:
    statement = (
        select(ApiSnapshot.id, ApiSnapshot.fingerprint, ApiSnapshot.fetched_at)
        .where(
            ApiSnapshot.source == source.name,
            ApiSnapshot.url == source.path,
            ApiSnapshot.state == "approved",
        )
        .order_by(ApiSnapshot.fetched_at.desc(), ApiSnapshot.id.desc())
        .limit(1)
    )
    row = (await session.execute(statement)).first()
    if row is None:
        return None
    return _Baseline(id=row.id, fingerprint=row.fingerprint, fetched_at=row.fetched_at)


async def _load_targets(session: AsyncSession) -> list[_Target]:
    targets: list[_Target] = []
    for source, called_url in await called_urls(session):
        baseline = await _latest_approved(session, source)
        targets.append(_Target(source=source, called_url=called_url, baseline=baseline))
    return targets


async def _pending_exists(session: AsyncSession, target: _Target, fingerprint: str) -> bool:
    """Is this version of the source already stored as pending, after the current baseline?"""
    statement = select(ApiSnapshot.id, ApiSnapshot.fetched_at).where(
        ApiSnapshot.source == target.source.name,
        ApiSnapshot.url == target.source.path,
        ApiSnapshot.state == "pending",
        ApiSnapshot.fingerprint == fingerprint,
    )
    rows = (await session.execute(statement)).all()
    baseline = target.baseline
    if baseline is None:
        return bool(rows)
    return any((row.fetched_at, row.id) > (baseline.fetched_at, baseline.id) for row in rows)


def _snapshot(
    source: ContractSource,
    document: _Document,
    *,
    state: Literal["approved", "pending"],
    approved_at: datetime | None,
) -> ApiSnapshot:
    return ApiSnapshot(
        source=source.name,
        url=source.path,
        fetched_at=document.fetched_at,
        fingerprint=document.fingerprint,
        server_content_hash=document.server_content_hash,
        api_version=document.api_version,
        body=document.body,
        state=state,
        approved_at=approved_at,
    )


def _short(fingerprint: str | None) -> str:
    return "-" if fingerprint is None else fingerprint[:19]


# --- check -----------------------------------------------------------------------


def _judge(target: _Target, fetched: _Fetched) -> SourceCheck:
    approved = target.baseline.fingerprint if target.baseline is not None else None
    name, called_url = target.source.name, target.called_url

    if isinstance(fetched, _Failure):
        return SourceCheck(name, called_url, fetched.kind, fetched.message, approved, None)
    if approved is None:
        return SourceCheck(
            name, called_url, "not_approved", "Not approved yet.", None, fetched.fingerprint
        )
    if fetched.fingerprint == approved:
        return SourceCheck(name, called_url, "ok", None, approved, fetched.fingerprint)
    return SourceCheck(
        name,
        called_url,
        "changed",
        "Differs from the approved version.",
        approved,
        fetched.fingerprint,
    )


def _overall(sources: Sequence[SourceCheck]) -> CheckStatus:
    """changed beats not approved, which beats unreachable.

    A source that cannot be read, but has an approved version, counts as changed:
    the documented address no longer answers as recorded.
    """
    for item in sources:
        has_baseline = item.approved_fingerprint is not None
        if item.status == "changed" or (item.status == "unreadable" and has_baseline):
            return "changed"
    if any(item.approved_fingerprint is None for item in sources):
        return "not_approved"
    if any(item.status == "unreachable" for item in sources):
        return "unreachable"
    return "ok"


async def check(session: AsyncSession) -> CheckResult:
    """Compares every source with its approved version and stores what it found.

    A changed source is stored as a pending snapshot, once per version. Nothing
    can be submitted unless the result `is_ok`.
    """
    async with _lock:
        targets = await _load_targets(session)
        await session.commit()  # end the read before any network call

        fetched = await _fetch_all(targets)
        checks = [_judge(target, item) for target, item in zip(targets, fetched, strict=True)]
        result = CheckResult(status=_overall(checks), checked_at=utcnow(), sources=tuple(checks))

        for target, item, source_check in zip(targets, fetched, checks, strict=True):
            if (
                source_check.status == "changed"
                and isinstance(item, _Document)
                and not await _pending_exists(session, target, item.fingerprint)
            ):
                session.add(_snapshot(target.source, item, state="pending", approved_at=None))
        await settings_service.write_internal(
            session, settings_service.GPU_CONTRACT_LAST_CHECK, result.to_json(), commit=False
        )
        await session.commit()

    _logger.info(
        "contract check: %s (%s)",
        result.status,
        ", ".join(f"{item.name}={item.status}" for item in result.sources),
    )
    return result


# --- approve ---------------------------------------------------------------------


def _judge_approval(
    target: _Target, first: _Fetched, second: _Fetched | None, expected: str | None
) -> SourceApproval:
    name, called_url = target.source.name, target.called_url

    def refused(
        outcome: ApproveOutcome, message: str, fingerprint: str | None = None
    ) -> SourceApproval:
        return SourceApproval(name, called_url, outcome, message, fingerprint, None)

    if isinstance(first, _Failure):
        return refused(first.kind, first.message)
    if second is None or isinstance(second, _Failure):
        kind = "unreachable" if second is None else second.kind
        message = "No answer on the second fetch." if second is None else second.message
        return refused(kind, message)

    if first.fingerprint != second.fingerprint:
        return SourceApproval(
            name,
            called_url,
            "unstable",
            "This source changes by itself: it answered differently a few seconds later, so it "
            "cannot be recorded as an API.",
            None,
            api_contract.diff_documents(first.body, second.body),
        )

    baseline = target.baseline
    if baseline is not None and baseline.fingerprint == first.fingerprint:
        return SourceApproval(
            name, called_url, "unchanged", "Already approved.", first.fingerprint, None
        )
    if expected is not None and expected != first.fingerprint:
        return refused(
            "changed_again",
            "The server now serves a different version than the one you reviewed. "
            "Run Test connection and review it again.",
            first.fingerprint,
        )
    return SourceApproval(name, called_url, "approved", None, first.fingerprint, None)


async def approve(session: AsyncSession, expected: Mapping[str, str]) -> ApproveResult:
    """Records the API as it is now, if every source answers the same twice.

    `expected` maps a source name to the fingerprint the user reviewed. A source
    that now serves something else is refused as "changed_again". All or nothing:
    approved snapshots are stored only when every source is approved or unchanged.
    """
    async with _lock:
        targets = await _load_targets(session)
        await session.commit()  # end the read before any network call

        first = await _fetch_all(targets)
        readable = [index for index, item in enumerate(first) if isinstance(item, _Document)]
        second: dict[int, _Fetched] = {}
        if readable:
            await asyncio.sleep(CAPTURE_GAP_S)
            again = await _fetch_all([targets[index] for index in readable])
            second = dict(zip(readable, again, strict=True))

        approvals = [
            _judge_approval(
                target, first[index], second.get(index), expected.get(target.source.name)
            )
            for index, target in enumerate(targets)
        ]
        everything_ok = all(item.outcome in ("approved", "unchanged") for item in approvals)

        now = utcnow()
        for target, item, approval in zip(targets, first, approvals, strict=True):
            if not isinstance(item, _Document):
                continue
            if approval.outcome == "changed_again":
                if not await _pending_exists(session, target, item.fingerprint):
                    session.add(_snapshot(target.source, item, state="pending", approved_at=None))
            elif approval.outcome == "approved" and everything_ok:
                session.add(_snapshot(target.source, item, state="approved", approved_at=now))

        if everything_ok:
            result = CheckResult(
                status="ok",
                checked_at=now,
                sources=tuple(
                    SourceCheck(
                        item.name, item.called_url, "ok", None, item.fingerprint, item.fingerprint
                    )
                    for item in approvals
                ),
            )
            await settings_service.write_internal(
                session, settings_service.GPU_CONTRACT_LAST_CHECK, result.to_json(), commit=False
            )
        await session.commit()

    _logger.info(
        "contract approve: %s (%s)",
        "approved" if everything_ok else "refused",
        ", ".join(f"{item.name}={item.outcome}:{_short(item.fingerprint)}" for item in approvals),
    )
    return ApproveResult(approved=everything_ok, sources=tuple(approvals))


# --- reading the stored state ----------------------------------------------------


async def last_check(session: AsyncSession) -> CheckResult | None:
    """The stored check result, or None if there is none that applies to the sources now.

    A result counts only while its sources and called addresses equal the ones
    that would be used now, so a check of an old address never stands in for the
    current one (the same rule as the connection test).
    """
    stored = CheckResult.from_json(
        await settings_service.read_internal(session, settings_service.GPU_CONTRACT_LAST_CHECK)
    )
    if stored is None:
        return None

    now = {(source.name, url) for source, url in await called_urls(session)}
    then = {(item.name, item.called_url) for item in stored.sources}
    return stored if now == then else None


async def missing_baselines(session: AsyncSession) -> list[str]:
    """Names of the sources that have no approved version yet."""
    missing: list[str] = []
    for source, _url in await called_urls(session):
        if await _latest_approved(session, source) is None:
            missing.append(source.name)
    return missing


async def _approved_row(session: AsyncSession, source: ContractSource) -> ApiSnapshot | None:
    statement = (
        select(ApiSnapshot)
        .where(
            ApiSnapshot.source == source.name,
            ApiSnapshot.url == source.path,
            ApiSnapshot.state == "approved",
        )
        .order_by(ApiSnapshot.fetched_at.desc(), ApiSnapshot.id.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


def _summarise(row: ApiSnapshot) -> ApprovedSummary:
    body = row.body if isinstance(row.body, dict) else {}
    is_spec = api_contract.is_openapi(body)
    return ApprovedSummary(
        snapshot_id=row.id,
        fingerprint=row.fingerprint,
        server_content_hash=row.server_content_hash,
        api_version=row.api_version,
        fetched_at=row.fetched_at,
        approved_at=row.approved_at,
        operation_count=api_contract.operation_count(body) if is_spec else None,
        tags=tuple(api_contract.operations_by_tag(body)) if is_spec else (),
    )


async def _pending_change(
    session: AsyncSession, source: ContractSource, fingerprint: str, approved_body: Any
) -> PendingChange | None:
    statement = (
        select(ApiSnapshot)
        .where(
            ApiSnapshot.source == source.name,
            ApiSnapshot.url == source.path,
            ApiSnapshot.state == "pending",
            ApiSnapshot.fingerprint == fingerprint,
        )
        .order_by(ApiSnapshot.id.desc())
        .limit(1)
    )
    row = (await session.execute(statement)).scalars().first()
    if row is None or not isinstance(row.body, dict) or not isinstance(approved_body, dict):
        return None
    return PendingChange(
        snapshot_id=row.id,
        fingerprint=row.fingerprint,
        api_version=row.api_version,
        fetched_at=row.fetched_at,
        diff=api_contract.diff_documents(approved_body, row.body),
    )


async def overview(session: AsyncSession) -> ContractOverview:
    """Everything the Settings page shows about the contract. Reads the database only."""
    effective = await settings_service.read_contract_sources(session)
    stored = await last_check(session)
    checks = {item.name: item for item in stored.sources} if stored is not None else {}

    sources: list[SourceOverview] = []
    for source, called_url in await called_urls(session):
        row = await _approved_row(session, source)
        source_check = checks.get(source.name)

        pending: PendingChange | None = None
        if (
            row is not None
            and source_check is not None
            and source_check.status == "changed"
            and source_check.current_fingerprint is not None
        ):
            pending = await _pending_change(
                session, source, source_check.current_fingerprint, row.body
            )
        sources.append(
            SourceOverview(
                source=source,
                called_url=called_url,
                approved=None if row is None else _summarise(row),
                pending=pending,
                last_check=source_check,
            )
        )
    return ContractOverview(sources_setting=effective, last_check=stored, sources=tuple(sources))
