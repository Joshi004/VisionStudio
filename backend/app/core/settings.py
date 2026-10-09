"""The global settings registry and the service that reads and saves them.

ANALYSIS.md Section 3.1 and 3.7: a value saved in the UI wins, then the
environment variable (a first-run default), then the built-in default. Values
are read at the moment they are used, so a change needs no restart. Later
phases read a setting with `get_str` or `get_int`.

`api_contract_sources` (DATABASE_STRUCTURE.md Section 6) is a list, not a text
or number setting, so it is not in `REGISTRY`: it has its own read, save and
reset functions at the end of this module, and its own endpoints (Phase 4).
The generic settings API keeps answering 404 for that key.
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
from app.services import video_models

_logger = logging.getLogger(__name__)

SettingSource = Literal["saved", "environment", "built_in"]

# Rows in the `setting` table that the app writes for itself. They are not
# settings: the API never lists, saves or resets them. Add new ones here.
GPU_CONNECTION_LAST_TEST = "gpu_connection_last_test"
GPU_CONTRACT_LAST_CHECK = "gpu_contract_last_check"
INTERNAL_KEYS = frozenset({GPU_CONNECTION_LAST_TEST, GPU_CONTRACT_LAST_CHECK})


class UnknownSettingError(LookupError):
    """The key is not a global setting."""


class SettingValueError(ValueError):
    """A value that fails validation. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class TextPattern:
    regex: str
    message: str


@dataclass(frozen=True)
class SettingChoice:
    """One allowed value of a setting that has a fixed set of them, and its name on the page."""

    value: str
    label: str


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
    # A string setting with a fixed set of allowed values: the page shows a choice list and
    # any other value is refused.
    choices: tuple[SettingChoice, ...] | None = None

    def __post_init__(self) -> None:
        if self.env_var is not None and self.value_type != "string":
            raise ValueError(f"{self.key}: only string settings can have an environment variable")
        if self.choices is not None:
            if self.value_type != "string":
                raise ValueError(f"{self.key}: only string settings can have choices")
            if self.default not in {choice.value for choice in self.choices}:
                raise ValueError(f"{self.key}: the default must be one of the choices")
        # An integer setting may leave min_value and max_value unset (both None) to take any
        # whole number with no range check. Setting only one of the two is still refused, since
        # a half-open range is almost certainly a mistake.
        if self.value_type == "integer" and (self.min_value is None) != (self.max_value is None):
            raise ValueError(f"{self.key}: set both min_value and max_value, or neither")


GROUP_GPU = "GPU server"
GROUP_LLM = "Language model"
GROUP_IMAGE = "Image model"
GROUP_VIDEO = "Video model"
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
        help="Model that proposes the scene cuts.",
        value_type="string",
        default="zai-org/GLM-5.3-Flash",
        pattern=TextPattern(
            regex=r"[A-Za-z0-9._/:-]{1,200}",
            message="Use letters, numbers and these characters only: . _ / : - (up to 200).",
        ),
    ),
    SettingSpec(
        key="description_llm_model",
        group=GROUP_LLM,
        label="Description model",
        help=(
            "Model that writes the scene descriptions and frame descriptions. It uses the "
            "LLM URL above. A larger model writes better, and costs more."
        ),
        value_type="string",
        default="zai-org/GLM-5.3",
        pattern=TextPattern(
            regex=r"[A-Za-z0-9._/:-]{1,200}",
            message="Use letters, numbers and these characters only: . _ / : - (up to 200).",
        ),
    ),
    SettingSpec(
        key="image_prompt_llm_model",
        group=GROUP_LLM,
        label="Image prompt model",
        help=(
            "Model that writes a detailed image prompt for each scene's first frame, one call "
            "per scene. It uses the LLM URL above."
        ),
        value_type="string",
        default="zai-org/GLM-5.3-Flash",
        pattern=TextPattern(
            regex=r"[A-Za-z0-9._/:-]{1,200}",
            message="Use letters, numbers and these characters only: . _ / : - (up to 200).",
        ),
    ),
    SettingSpec(
        key="image_model",
        group=GROUP_IMAGE,
        label="Image model",
        help=(
            "Model that makes each scene's first frame, one paid image per scene. It uses the "
            "LLM URL above (Bitdeer). The Image lab has its own model box."
        ),
        value_type="string",
        default="seedream-5.0-lite",
        pattern=TextPattern(
            regex=r"[A-Za-z0-9._/:-]{1,200}",
            message="Use letters, numbers and these characters only: . _ / : - (up to 200).",
        ),
    ),
    SettingSpec(
        key="default_video_model",
        group=GROUP_VIDEO,
        label="Default video model",
        help=(
            "The video model that makes clips when neither the scene nor its project chooses "
            "one (Project settings, and each scene's clip section). Regenerate can also pick "
            "a model for one take. LTX-2.5 cuts between several shots only when the prompt "
            "says so, and has no negative prompt. A scene that has a last frame is always made "
            "by LTX-2.3 for now: LTX-2.5 has no first-and-last-frame mode yet."
        ),
        value_type="string",
        default=video_models.DEFAULT_MODEL,
        choices=tuple(
            SettingChoice(model, video_models.LABELS[model]) for model in video_models.MODEL_IDS
        ),
    ),
    SettingSpec(
        key="default_negative_prompt",
        group=GROUP_VIDEO,
        label="Default negative prompt (LTX-2.3 only)",
        help=(
            "Sent to LTX-2.3 as its negative prompt whenever a project's own Negative "
            "prompt (Project settings, Guidelines) is blank. LTX-2.5 has no negative prompt "
            "and never gets it. New projects also start with this "
            "text in their own field. It keeps unwanted background music, speech, on-screen "
            "text and common video artifacts out of the clips. Blank it as well to let the "
            "GPU server's own default apply instead."
        ),
        value_type="string",
        default=(
            "background music, music, soundtrack, score, song, singing, lyrics, jingle, "
            "narration, voice-over, dialogue, speech, talking, on-screen text, captions, "
            "subtitles, titles, logo, watermark, blurry, low quality, distorted, warped, "
            "flickering, glitch, extra limbs, deformed hands, duplicated subject, jump cut, "
            "scene change"
        ),
        allow_blank=True,
    ),
    SettingSpec(
        key="max_parallel_generations",
        group=GROUP_LIMITS,
        label="Maximum parallel clip generations",
        help=(
            "How many clips may generate on the GPU server at the same time. It applies the "
            "next time the app looks for work, and running jobs are not stopped. No range is "
            "enforced: you are trusted to pick a number your GPU server can actually handle."
        ),
        value_type="integer",
        default=4,
    ),
    SettingSpec(
        key="max_parallel_image_generations",
        group=GROUP_LIMITS,
        label="Maximum parallel image generations",
        help=(
            "How many first frames may be made by the image model at the same time. Each image "
            "takes 20 to 50 seconds. It applies the next time the app looks for work, and "
            "running jobs are not stopped. No range is enforced: you are trusted to pick a "
            "number Bitdeer can actually handle."
        ),
        value_type="integer",
        default=2,
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
        help=(
            "How many FFmpeg renders may run at the same time. It applies to the next render. "
            "No range is enforced: you are trusted to pick a number this machine can handle."
        ),
        value_type="integer",
        default=1,
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

    if spec.choices is not None and value not in {choice.value for choice in spec.choices}:
        raise SettingValueError(
            "Choose one of: " + ", ".join(choice.label for choice in spec.choices) + "."
        )
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


async def write_internal(
    session: AsyncSession, key: str, value: Any, *, commit: bool = True
) -> None:
    """Stores a JSON value in an internal row, and commits unless the caller will."""
    _check_internal(key)
    await _upsert(session, key, value)
    if commit:
        await session.commit()


# --- API contract sources (Phase 4) -------------------------------------------------
#
# Each source is a GET address whose JSON answer is recorded and checked
# (ANALYSIS.md Section 6.5). It is a path on one of two servers: `base` says
# which. Paths are relative, so a new tunnel address never invalidates them.

CONTRACT_SOURCES_KEY = "api_contract_sources"
MAX_CONTRACT_SOURCES = 5
MAX_CONTRACT_PATH_CHARS = 500

ContractBase = Literal["gpu", "transcription"]

# The URL setting each base reads. A blank transcription URL falls back to the GPU server URL.
BASE_SETTING: dict[ContractBase, str] = {
    "gpu": "gpu_api_base_url",
    "transcription": "transcription_url",
}

_BASE_BY_TEXT: dict[str, ContractBase] = {"gpu": "gpu", "transcription": "transcription"}
_SOURCE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")


@dataclass(frozen=True)
class ContractSource:
    name: str
    base: ContractBase
    path: str


DEFAULT_CONTRACT_SOURCES: tuple[ContractSource, ...] = (
    ContractSource(name="guide", base="gpu", path="/v1/guide?format=json"),
    ContractSource(name="openapi", base="gpu", path="/openapi.json"),
)


@dataclass(frozen=True)
class EffectiveContractSources:
    sources: tuple[ContractSource, ...]
    source: Literal["saved", "built_in"]
    updated_at: datetime | None
    # Why a saved value was skipped, if it was.
    note: str | None


def contract_sources_to_json(sources: Iterable[ContractSource]) -> list[dict[str, str]]:
    return [{"name": item.name, "base": item.base, "path": item.path} for item in sources]


def validate_contract_sources(raw: object) -> tuple[ContractSource, ...]:
    """Checks a list of sources and returns it in the form that is stored.

    Raises `SettingValueError` with a message meant for the user.
    """
    limit_message = f"Add from 1 to {MAX_CONTRACT_SOURCES} sources."
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CONTRACT_SOURCES:
        raise SettingValueError(limit_message)

    sources: list[ContractSource] = []
    for number, item in enumerate(raw, start=1):
        sources.append(_validate_contract_source(number, item))

    names = [item.name for item in sources]
    for name in names:
        if names.count(name) > 1:
            raise SettingValueError(f'Two sources are called "{name}". Give each its own name.')

    targets = [(item.base, item.path) for item in sources]
    for target in targets:
        if targets.count(target) > 1:
            raise SettingValueError("Two sources point at the same address. Remove one of them.")
    return tuple(sources)


def _validate_contract_source(number: int, item: object) -> ContractSource:
    label = f"Source {number}"
    if (
        not isinstance(item, dict)
        or set(item) != {"name", "base", "path"}
        or not all(isinstance(value, str) for value in item.values())
    ):
        raise SettingValueError(f"{label} needs a name, a base and a path, all as text.")

    name = item["name"].strip()
    if not _SOURCE_NAME.fullmatch(name):
        raise SettingValueError(
            f"{label}: the name may use lower case letters, numbers, dashes and underscores, "
            "must start with a letter or number, and can be up to 40 characters."
        )

    base = _BASE_BY_TEXT.get(item["base"].strip())
    if base is None:
        raise SettingValueError(
            f'Source "{name}": choose the GPU server URL or the Transcription URL.'
        )

    path = item["path"].strip()
    problem = _contract_path_problem(path)
    if problem is not None:
        raise SettingValueError(f'Source "{name}": {problem}')
    return ContractSource(name=name, base=base, path=path)


def _contract_path_problem(path: str) -> str | None:
    if not path.startswith("/") or path.startswith("//"):
        return "the path must start with a single slash, for example /openapi.json."
    if len(path) > MAX_CONTRACT_PATH_CHARS:
        return f"the path is longer than {MAX_CONTRACT_PATH_CHARS} characters."
    if any(char.isspace() or not char.isprintable() for char in path):
        return "the path must not contain spaces or control characters."
    if "#" in path:
        return "the path must not contain #."
    return None


async def read_contract_sources(session: AsyncSession) -> EffectiveContractSources:
    """The sources that apply now. A saved list that fails validation is skipped, with a note."""
    rows = await _load_rows(session, [CONTRACT_SOURCES_KEY])
    row = rows.get(CONTRACT_SOURCES_KEY)
    note: str | None = None
    if row is not None:
        try:
            return EffectiveContractSources(
                sources=validate_contract_sources(row.value),
                source="saved",
                updated_at=row.updated_at,
                note=None,
            )
        except SettingValueError as exc:
            note = f"The saved list of sources is not valid ({exc}) and is being ignored."
    return EffectiveContractSources(
        sources=DEFAULT_CONTRACT_SOURCES, source="built_in", updated_at=None, note=note
    )


async def save_contract_sources(session: AsyncSession, raw: object) -> EffectiveContractSources:
    """Validates and saves the list of sources, then returns what now applies."""
    sources = validate_contract_sources(raw)
    await _upsert(session, CONTRACT_SOURCES_KEY, contract_sources_to_json(sources))
    await session.commit()
    _logger.info("setting saved: %s", CONTRACT_SOURCES_KEY)
    return await read_contract_sources(session)


async def reset_contract_sources(session: AsyncSession) -> EffectiveContractSources:
    """Removes the saved list, so the built-in sources apply again."""
    await session.execute(delete(Setting).where(Setting.key == CONTRACT_SOURCES_KEY))
    await session.commit()
    _logger.info("setting reset: %s", CONTRACT_SOURCES_KEY)
    return await read_contract_sources(session)
