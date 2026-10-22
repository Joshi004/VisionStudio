"""The Character lab's library of environments (PHASE-012): global, project-independent places
an author builds once and a story project can link to and pin a version of
(`services/environment_links.py`, PHASE-013).

An environment is never deleted, only archived, like characters and voices. Its profile is
versioned (`services/environment_versions.py`): creating one writes version 1, and an edit that
changes the profile adds the next version. Making its canonical reference picture is in
`services/environment_references.py`.

`environment_card` renders everything the prompt writer needs as one block of plain English,
so there is exactly one place that turns the row's columns into words.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LibraryEnvironment
from app.db.types import utcnow
from app.services import environment_versions

_logger = logging.getLogger(__name__)

# The job that writes an environment's reference picture prompt.
PROMPT_JOB: Final = "write_environment_prompt"

NAME_MAX_CHARS: Final = 80
DESCRIPTION_MAX_CHARS: Final = 2500
ATMOSPHERE_MAX_CHARS: Final = 500
NOTES_MAX_CHARS: Final = 1000
ERA_SETTING_MAX_CHARS: Final = 200
MIN_ERA_YEARS: Final = 1
MAX_ERA_YEARS: Final = 10_000
LIST_LIMIT: Final = 200

EraKind = Literal["present", "past", "future"]
ERA_KINDS: Final[tuple[EraKind, ...]] = ("present", "past", "future")


class EnvironmentLibraryError(ValueError):
    """Something the form gets wrong. The message is meant for the user (HTTP 422)."""


@dataclass(frozen=True)
class EnvironmentForm:
    """What the create form, or an edit, sends."""

    name: str
    description: str
    era_kind: EraKind
    era_years: int | None
    era_setting: str | None
    atmosphere: str | None
    notes: str | None


def _clean(value: str | None) -> str | None:
    return None if value is None or not value.strip() else " ".join(value.split())


def _too_long(value: str | None, limit: int, what: str) -> None:
    if value is not None and len(value) > limit:
        raise EnvironmentLibraryError(f"The {what} must be at most {limit:,} characters.")


def validate_form(form: EnvironmentForm) -> None:
    """Raises EnvironmentLibraryError for a form no environment should be saved with."""
    if not form.name.strip():
        raise EnvironmentLibraryError("Give the environment a name.")
    _too_long(form.name, NAME_MAX_CHARS, "name")
    if not form.description.strip():
        raise EnvironmentLibraryError("Describe what the environment looks like.")
    _too_long(form.description, DESCRIPTION_MAX_CHARS, "description")
    _too_long(form.atmosphere, ATMOSPHERE_MAX_CHARS, "atmosphere")
    _too_long(form.notes, NOTES_MAX_CHARS, "notes")
    _too_long(form.era_setting, ERA_SETTING_MAX_CHARS, "era setting")
    if form.era_kind not in ERA_KINDS:
        raise EnvironmentLibraryError("Choose present, past or future.")
    if form.era_kind == "present":
        if form.era_years is not None:
            raise EnvironmentLibraryError("The present has no number of years: leave it out.")
    elif form.era_years is None or not MIN_ERA_YEARS <= form.era_years <= MAX_ERA_YEARS:
        raise EnvironmentLibraryError(
            f"Give the number of years, from {MIN_ERA_YEARS} to {MAX_ERA_YEARS:,}."
        )


def _apply(environment: LibraryEnvironment, form: EnvironmentForm) -> None:
    environment.name = " ".join(form.name.split())
    environment.description = form.description.strip()
    environment.era_kind = form.era_kind
    environment.era_years = form.era_years
    environment.era_setting = _clean(form.era_setting)
    environment.atmosphere = _clean(form.atmosphere)
    environment.notes = _clean(form.notes)


async def create_environment(session: AsyncSession, form: EnvironmentForm) -> LibraryEnvironment:
    """Checks the form and saves a new environment, as its version 1. Commits. Raises
    EnvironmentLibraryError.
    """
    validate_form(form)
    environment = LibraryEnvironment(name="")
    _apply(environment, form)
    session.add(environment)
    await session.flush()  # the environment's id, for its first version
    await environment_versions.record_version_if_changed(session, environment)
    await session.commit()
    _logger.info("environment %d created: %s", environment.id, environment.name)
    return environment


async def update_environment(
    session: AsyncSession, environment_id: int, form: EnvironmentForm
) -> LibraryEnvironment:
    """Checks the form and saves it onto an existing environment, and adds a new version when
    the profile changed. Commits. Raises EnvironmentLibraryError.
    """
    validate_form(form)
    environment = await session.get(LibraryEnvironment, environment_id)
    if environment is None:
        raise EnvironmentLibraryError(f"There is no environment {environment_id}.")
    _apply(environment, form)
    environment.updated_at = utcnow()
    await environment_versions.record_version_if_changed(session, environment)
    await session.commit()
    _logger.info("environment %d updated", environment.id)
    return environment


async def set_archived(
    session: AsyncSession, environment_id: int, archived: bool
) -> LibraryEnvironment:
    """Archives or unarchives an environment. Never deletes one, and adds no version. Commits."""
    environment = await session.get(LibraryEnvironment, environment_id)
    if environment is None:
        raise EnvironmentLibraryError(f"There is no environment {environment_id}.")
    environment.archived = archived
    environment.updated_at = utcnow()
    await session.commit()
    return environment


async def get_environment(session: AsyncSession, environment_id: int) -> LibraryEnvironment | None:
    return await session.get(LibraryEnvironment, environment_id)


async def list_environments(
    session: AsyncSession, *, include_archived: bool, before_id: int | None, limit: int
) -> list[LibraryEnvironment]:
    """The newest environments first, `limit` of them (at most LIST_LIMIT), those with an id
    below `before_id` if given. Archived environments are left out unless asked for.
    """
    statement = (
        select(LibraryEnvironment)
        .order_by(LibraryEnvironment.id.desc())
        .limit(min(limit, LIST_LIMIT))
        .execution_options(populate_existing=True)
    )
    if not include_archived:
        statement = statement.where(LibraryEnvironment.archived.is_(False))
    if before_id is not None:
        statement = statement.where(LibraryEnvironment.id < before_id)
    return list((await session.execute(statement)).scalars().all())


# --- The environment card: everything the prompt writer is told about the place -----------


def _era_text(kind: str, years: int | None, setting: str | None) -> str:
    """The environment's time, in words. The year is worked out from today's date, so a card
    written today and one written next year say the same thing about the same place.
    """
    if kind == "present":
        return "set in the present day"
    count = years or 0
    today = date.today()
    if kind == "past":
        text = f"set about {count:,} years in the past, around {today.year - count}"
    else:
        text = f"set about {count:,} years in the future, around {today.year + count}"
    if setting:
        text += f" ({setting})"
    return text


def card_from_profile(profile: Mapping[str, Any]) -> str:
    """Everything the prompt writer is told about an environment, as one block of plain
    English, from a profile (the seven fields of `environment_versions.PROFILE_FIELDS`, as a
    version freezes them). Pure. Used for a version's picture, so the prompt describes the
    version the picture is made for and never a later edit of the head.
    """
    lines = [
        f"Name: {profile['name']}.",
        f"Time: {_era_text(profile['era_kind'], profile['era_years'], profile['era_setting'])}.",
    ]
    if profile["description"]:
        lines.append(f"Description: {profile['description']}")
    if profile["atmosphere"]:
        lines.append(f"Atmosphere: {profile['atmosphere']}")
    if profile["notes"]:
        lines.append(f"Other notes: {profile['notes']}")
    return "\n".join(lines)


def environment_card(environment: LibraryEnvironment) -> str:
    """Everything the prompt writer is told about the environment as it is now. Pure: it reads
    columns only.
    """
    return card_from_profile(environment_versions.profile_of(environment))


# --- Making an environment from a story project's discovered environment (PHASE-013) -------


async def create_from_discovery(
    session: AsyncSession,
    *,
    name: str,
    description: str,
    project_id: int,
    discovery_id: str,
) -> LibraryEnvironment:
    """Makes a library environment from a story project's discovered environment, as its
    version 1 (`source` is `ai`, because the text came from the model). Flushes but does not
    commit: the caller commits it together with the link, so an environment is never made
    without its link. Raises EnvironmentLibraryError.

    The discovery gives a name and one line: they become the name and the description. The era
    is the present, and the atmosphere and the notes stay empty until the Environment
    Definition stage (or the author) fills them. The environment is marked with the project and
    the discovered environment it came from.
    """
    clean_name = _clean(name)
    if clean_name is None:
        raise EnvironmentLibraryError("Give the environment a name.")
    _too_long(clean_name, NAME_MAX_CHARS, "name")
    clean_description = _clean(description)
    if clean_description is None:
        raise EnvironmentLibraryError("Describe what the environment looks like.")
    _too_long(clean_description, DESCRIPTION_MAX_CHARS, "description")
    environment = LibraryEnvironment(
        name=clean_name,
        description=clean_description,
        origin_project_id=project_id,
        origin_discovery_id=discovery_id,
    )
    session.add(environment)
    await session.flush()  # the environment's id, for its first version
    await environment_versions.record_version_if_changed(session, environment, source="ai")
    _logger.info(
        "environment %d created from project %d's discovered environment %s",
        environment.id,
        project_id,
        discovery_id,
    )
    return environment
