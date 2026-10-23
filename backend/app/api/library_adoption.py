"""What the adoption endpoints of the characters and the environments share (PHASE-042).

The endpoints themselves live next to the others of their kind:

- `POST /api/lab/characters/{id}/adopt` and `POST /api/lab/environments/{id}/adopt` move the pins
  of the chosen projects to one version (`api/character_lab.py`, `api/environment_lab.py`);
- `PUT /api/projects/{id}/character-links/{discovery_id}/version` and the environment twin move
  one project's pin for one entry (`api/character_links.py`, `api/environment_links.py`).

The rules are in `services/library_adoption.py`.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services import library_adoption

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
MAX_PROJECTS: Final = 200

Version = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]
ProjectId = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]


class AdoptIn(BaseModel):
    """Move these projects' pins to this version of the library item."""

    model_config = ConfigDict(extra="forbid")

    version: Version
    project_ids: Annotated[list[ProjectId], Field(min_length=1, max_length=MAX_PROJECTS)]

    @field_validator("project_ids")
    @classmethod
    def _unique(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("Each project can be listed only once.")
        return value


class VersionIn(BaseModel):
    """The version one project's pin should move to."""

    model_config = ConfigDict(extra="forbid")

    version: Version


def refused(exc: library_adoption.AdoptionError) -> HTTPException:
    """An unlinked entry is a 404; every other refusal is a 422 with its readable message."""
    if isinstance(exc, library_adoption.LinkNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
