"""The global settings registry and the service that reads and saves them.

ANALYSIS.md Section 3.1 and 3.7: a value saved in the UI wins, then the
environment variable (a first-run default), then the built-in default. Values
are read at the moment they are used, so a change needs no restart. Later
phases read a setting with `get_str` or `get_int`.

`api_contract_sources` (DATABASE_STRUCTURE.md Section 6) is not here: Phase 4
adds it together with its own editor.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, NamedTuple

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import env_value
from app.core.urls import UrlError, docker_mapped, validate_base_url
from app.db.models import Setting
from app.db.types import utcnow

_logger = logging.getLogger(__name__)

SettingSource = Literal["saved", "environment", "built_in"]

# Rows in the `setting` table that the app writes for itself. They are not
# settings: the API never lists, saves or resets them. Add new ones here.
GPU_CONNECTION_LAST_TEST = "gpu_connection_last_test"
INTERNAL_KEYS = frozenset({GPU_CONNECTION_LAST_TEST})


class UnknownSettingError(LookupError):
    """The key is not a global setting."""


class SettingValueError(ValueError):
    """A value that fails validation. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class TextPattern:
    regex: str
    message: str


@dataclass(frozen=True)
class SettingSpec:
    """Everything the app knows about one global setting."""

    key: str
    group: str
    label: str
    help: str
    value_type: Literal["string", "integer"]
    default: str | int
    # Only string settings may have an environment variable (a first-run default).
    env_var: str | None = None
    is_url: bool = False
    allow_blank: bool = False
    min_value: int | None = None
    max_value: int | None = None
    pattern: TextPattern | None = None
    # When the value is blank, use this other setting's value instead.
    blank_falls_back_to: str | None = None

    def __post_init__(self) -> None:
        if self.env_var is not None and self.value_type != "string":
            raise ValueError(f"{self.key}: only string settings can have an environment variable")
        if self.value_type == "integer" and (self.min_value is None or self.max_value is None):
            raise ValueError(f"{self.key}: an integer setting needs a minimum and a maximum")


GROUP_GPU = "GPU server"
GROUP_LLM = "Language model"
GROUP_LIMITS = "Limits"

# The order here is the order on the Settings page. Defaults come from
# DATABASE_STRUCTURE.md Section 6 and ANALYSIS.md Section 3.1 and 3.7.
REGISTRY: tuple[SettingSpec, ...] = (
    SettingSpec(
        key="gpu_api_base_url",
        group=GROUP_GPU,
        label="GPU server URL",
        help=(
            "Address of your GPU server. Change it whenever the server's address changes. "
            "localhost and 127.0.0.1 are replaced by host.docker.internal when the app calls it."
        ),
        value_type="string",
        default="http://host.docker.internal:8012",
        env_var="GPU_API_BASE_URL",
        is_url=True,
    ),
    SettingSpec(
        key="transcription_url",
        group=GROUP_GPU,
        label="Transcription URL",
        help="Address of the transcription API. Leave blank to use the GPU server URL.",
        value_type="string",
        default="",
        is_url=True,
        allow_blank=True,
        blank_falls_back_to="gpu_api_base_url",
    ),
    SettingSpec(
        key="gpu_partition",
        group=GROUP_GPU,
        label="GPU partition",
        help=(
            "Cluster partition for new GPU jobs, for example main. Leave blank for the "
            "cluster's own default. The cluster ignores a name it does not know."
        ),
        value_type="string",
        default="",
        allow_blank=True,
        pattern=TextPattern(
            regex=r"[A-Za-z0-9._-]{1,64}",
            message="Use letters, numbers, dots, dashes and underscores only (up to 64).",
        ),
    ),
    SettingSpec(
        key="llm_base_url",
        group=GROUP_LLM,
        label="LLM URL",
        help=(
            "OpenAI-compatible address used to propose scene cuts. The Bitdeer key is sent "
            "only to api-inference.bitdeer.ai, never to another address."
        ),
        value_type="string",
        default="https://api-inference.bitdeer.ai/v1",
        env_var="BITDEEP_BASE_URL",
        is_url=True,
    ),
    SettingSpec(
        key="llm_model",
        group=GROUP_LLM,
        label="LLM model",
        help="Model name sent with every language model call.",
        value_type="string",
        default="zai-org/GLM-5.3-Flash",
        pattern=TextPattern(
            regex=r"[A-Za-z0-9._/:-]{1,200}",
            message="Use letters, numbers and these characters only: . _ / : - (up to 200).",
        ),
    ),
    SettingSpec(
        key="max_parallel_generations",
        group=GROUP_LIMITS,
        label="Maximum parallel clip generations",
        help=(
            "How many clips may generate on the GPU server at the same time. It applies the "
            "next time the app looks for work, and running jobs are not stopped."
        ),
        value_type="integer",
        default=4,
        min_value=1,
        max_value=16,
    ),
    SettingSpec(
        key="poll_interval_seconds",
        group=GROUP_LIMITS,
        label="Poll interval (seconds)",
        help=(
            "How often the backend checks running jobs. The GPU server recommends 10 to 15. "
            "It applies from the next check."
        ),
        value_type="integer",
        default=15,
        min_value=10,
        max_value=300,
    ),
    SettingSpec(
        key="max_parallel_ffmpeg",
        group=GROUP_LIMITS,
        label="Maximum parallel FFmpeg runs",
        help="How many FFmpeg renders may run at the same time. It applies to the next render.",
        value_type="integer",
        default=1,
        min_value=1,
        max_value=4,
    ),
)

_BY_KEY: dict[str, SettingSpec] = {spec.key: spec for spec in REGISTRY}


@dataclass(frozen=True)
class SecretSpec:
    """A secret read from the environment. The app only ever reports whether it is set."""

    name: str
    label: str


SECRETS: tuple[SecretSpec, ...] = (SecretSpec("BITDEEP_API_KEY", "Bitdeer API key"),)


def secret_is_set(name: str) -> bool:
    return env_value(name) is not None


@dataclass(frozen=True)
class EffectiveSetting:
    """A setting's value as it applies right now, and where that value came from."""

    spec: SettingSpec
    value: str | int
    source: SettingSource
    updated_at: datetime | None
    # Why a saved or environment value was skipped, if it was.
    note: str | None
    # For URL settings: the address the app will really call.
    will_call: str | None


def get_spec(key: str) -> SettingSpec:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise UnknownSettingError(f"Unknown setting: {key}") from None


def validate_value(spec: SettingSpec, raw: object) -> str | int:
    """Checks a value for a setting and returns it in the form that is stored."""
    if spec.value_type == "integer":
        return _validate_integer(spec, raw)
    return _validate_text(spec, raw)


def _validate_integer(spec: SettingSpec, raw: object) -> int:
    # bool is a subclass of int in Python, but `true` is not a number of jobs.
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise SettingValueError("Enter a whole number.")
    low, high = spec.min_value, spec.max_value
    if low is not None and high is not None and not low <= raw <= high:
        raise SettingValueError(f"Enter a number from {low} to {high}.")
    return raw


def _validate_text(spec: SettingSpec, raw: object) -> str:
    if not isinstance(raw, str):
        raise SettingValueError("Enter text.")
    value = raw.strip()

    if not value:
        if spec.allow_blank:
            return ""
        raise SettingValueError("Enter an address." if spec.is_url else "Enter a value.")

    if spec.is_url:
        try:
            return validate_base_url(value)
        except UrlError as exc:
            raise SettingValueError(str(exc)) from exc

    if spec.pattern is not None and not re.fullmatch(spec.pattern.regex, value):
        raise SettingValueError(spec.pattern.message)
    return value


class _Layer(NamedTuple):
    value: str | int
    source: SettingSource
    updated_at: datetime | None
    note: str | None


def _pick_layer(spec: SettingSpec, rows: dict[str, Setting]) -> _Layer:
    """Applies the precedence: saved, then environment, then built-in.

    A saved or environment value that fails validation is skipped, and the
    reason is returned as a note, so a bad value never breaks the app.
    """
    notes: list[str] = []

    row = rows.get(spec.key)
    if row is not None:
        try:
            return _Layer(validate_value(spec, row.value), "saved", row.updated_at, None)
        except SettingValueError as exc:
            notes.append(f"The saved value is not valid ({exc}) and is being ignored.")

    raw_env = env_value(spec.env_var) if spec.env_var else None
    if raw_env is not None:
        try:
            return _Layer(
                validate_value(spec, raw_env), "environment", None, " ".join(notes) or None
            )
        except SettingValueError as exc:
            notes.append(f"{spec.env_var} is not valid ({exc}) and is being ignored.")

    return _Layer(spec.default, "built_in", None, " ".join(notes) or None)


def _text_with_fallback(spec: SettingSpec, rows: dict[str, Setting]) -> str:
    """The effective text, using the fallback setting when this one is blank."""
    value = str(_pick_layer(spec, rows).value)
    if value == "" and spec.blank_falls_back_to is not None:
        return str(_pick_layer(_BY_KEY[spec.blank_falls_back_to], rows).value)
    return value


def _resolve(spec: SettingSpec, rows: dict[str, Setting]) -> EffectiveSetting:
    layer = _pick_layer(spec, rows)
    will_call: str | None = None
    if spec.is_url:
        base = _text_with_fallback(spec, rows)
        will_call = docker_mapped(base) if base else None
    return EffectiveSetting(
        spec=spec,
        value=layer.value,
        source=layer.source,
        updated_at=layer.updated_at,
        note=layer.note,
        will_call=will_call,
    )


def _keys_needed(spec: SettingSpec) -> list[str]:
    keys = [spec.key]
    if spec.blank_falls_back_to is not None:
        keys.append(spec.blank_falls_back_to)
    return keys


async def _load_rows(session: AsyncSession, keys: Iterable[str]) -> dict[str, Setting]:
    # populate_existing: never hand back a stale instance this session loaded earlier.
    statement = (
        select(Setting).where(Setting.key.in_(list(keys))).execution_options(populate_existing=True)
    )
    result = await session.execute(statement)
    return {row.key: row for row in result.scalars()}


async def read_setting(session: AsyncSession, key: str) -> EffectiveSetting:
    spec = get_spec(key)
    rows = await _load_rows(session, _keys_needed(spec))
    return _resolve(spec, rows)


async def read_all(session: AsyncSession) -> list[EffectiveSetting]:
    rows = await _load_rows(session, (spec.key for spec in REGISTRY))
    return [_resolve(spec, rows) for spec in REGISTRY]


async def get_str(session: AsyncSession, key: str) -> str:
    """The effective text of a string setting, read at the moment of use.

    For a setting that falls back (`transcription_url`), a blank value returns
    the other setting's value. The text is not Docker-mapped: `outbound.request`
    does that when it calls the address.
    """
    spec = get_spec(key)
    if spec.value_type != "string":
        raise TypeError(f"{key} is not a string setting")
    rows = await _load_rows(session, _keys_needed(spec))
    return _text_with_fallback(spec, rows)


async def get_int(session: AsyncSession, key: str) -> int:
    """The effective number of an integer setting, read at the moment of use."""
    spec = get_spec(key)
    if spec.value_type != "integer":
        raise TypeError(f"{key} is not an integer setting")
    rows = await _load_rows(session, [spec.key])
    value = _pick_layer(spec, rows).value
    assert isinstance(value, int)
    return value


async def _upsert(session: AsyncSession, key: str, value: Any) -> None:
    statement = insert(Setting).values(key=key, value=value, updated_at=utcnow())
    statement = statement.on_conflict_do_update(
        index_elements=[Setting.key],
        set_={"value": statement.excluded.value, "updated_at": statement.excluded.updated_at},
    )
    await session.execute(statement)


async def save_setting(session: AsyncSession, key: str, raw: object) -> EffectiveSetting:
    """Validates and saves a value, then returns the setting as it now applies."""
    spec = get_spec(key)
    value = validate_value(spec, raw)
    await _upsert(session, key, value)
    await session.commit()
    _logger.info("setting saved: %s", key)
    return await read_setting(session, key)


async def reset_setting(session: AsyncSession, key: str) -> EffectiveSetting:
    """Removes the saved value, so the environment or built-in value applies again."""
    get_spec(key)
    await session.execute(delete(Setting).where(Setting.key == key))
    await session.commit()
    _logger.info("setting reset: %s", key)
    return await read_setting(session, key)


def _check_internal(key: str) -> None:
    if key not in INTERNAL_KEYS:
        raise UnknownSettingError(f"Unknown internal key: {key}")


async def read_internal(session: AsyncSession, key: str) -> Any | None:
    """The stored JSON value of an internal row, or None when it was never written."""
    _check_internal(key)
    rows = await _load_rows(session, [key])
    row = rows.get(key)
    return None if row is None else row.value


async def write_internal(session: AsyncSession, key: str, value: Any) -> None:
    """Stores a JSON value in an internal row and commits."""
    _check_internal(key)
    await _upsert(session, key, value)
    await session.commit()
