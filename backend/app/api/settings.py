"""`/api/settings`: the global settings (ANALYSIS.md Section 3.7).

Each answer carries the effective value and where it came from, so the page
can show "saved", "environment" or "built-in". Secrets are never returned,
only whether they are set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from app.api.errors import ErrorResponse
from app.core import settings as settings_service
from app.db.session import SessionDep
from app.jobs import dispatcher

router = APIRouter()

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "No setting has this key."},
    422: {"model": ErrorResponse, "description": "The value is not valid."},
}


class SettingChoiceItem(BaseModel):
    value: str
    label: str


class SettingItem(BaseModel):
    key: str
    group: str
    label: str
    help: str
    value_type: Literal["string", "integer"]
    value: str | int
    source: Literal["saved", "environment", "built_in"]
    default: str | int
    env_var: str | None
    allow_blank: bool
    min_value: int | None
    max_value: int | None
    # The allowed values of a setting that has a fixed set of them (shown as a choice list).
    choices: list[SettingChoiceItem] | None
    will_call: str | None
    note: str | None
    updated_at: datetime | None


class SecretStatus(BaseModel):
    name: str
    label: str
    is_set: bool


class SettingsResponse(BaseModel):
    settings: list[SettingItem]
    secrets: list[SecretStatus]


class SettingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Strict, so the string "4" is not quietly accepted as the number 4.
    value: StrictInt | StrictStr


def _to_item(effective: settings_service.EffectiveSetting) -> SettingItem:
    spec = effective.spec
    return SettingItem(
        key=spec.key,
        group=spec.group,
        label=spec.label,
        help=spec.help,
        value_type=spec.value_type,
        value=effective.value,
        source=effective.source,
        default=spec.default,
        env_var=spec.env_var,
        allow_blank=spec.allow_blank,
        min_value=spec.min_value,
        max_value=spec.max_value,
        choices=(
            [SettingChoiceItem(value=c.value, label=c.label) for c in spec.choices]
            if spec.choices is not None
            else None
        ),
        will_call=effective.will_call,
        note=effective.note,
        updated_at=effective.updated_at,
    )


@router.get("/settings", response_model=SettingsResponse)
async def list_settings(session: SessionDep) -> SettingsResponse:
    effective = await settings_service.read_all(session)
    return SettingsResponse(
        settings=[_to_item(item) for item in effective],
        secrets=[
            SecretStatus(
                name=secret.name,
                label=secret.label,
                is_set=settings_service.secret_is_set(secret.name),
            )
            for secret in settings_service.SECRETS
        ],
    )


@router.put("/settings/{key}", response_model=SettingItem, responses=_ERROR_RESPONSES)
async def save_setting(key: str, body: SettingUpdate, session: SessionDep) -> SettingItem:
    try:
        effective = await settings_service.save_setting(session, key, body.value)
    except settings_service.UnknownSettingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except settings_service.SettingValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    # A new URL or limit can let a waiting job proceed, so the dispatcher looks again now.
    dispatcher.nudge()
    return _to_item(effective)


@router.delete(
    "/settings/{key}", response_model=SettingItem, responses={404: _ERROR_RESPONSES[404]}
)
async def reset_setting(key: str, session: SessionDep) -> SettingItem:
    """Removes the saved value, so the environment or built-in value applies again."""
    try:
        effective = await settings_service.reset_setting(session, key)
    except settings_service.UnknownSettingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    dispatcher.nudge()
    return _to_item(effective)
