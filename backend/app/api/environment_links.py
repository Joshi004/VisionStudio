"""`/api/projects/{project_id}/environment-links`: a story project's discovered environments,
linked to Character Lab library environments and pinned to a version of each (PHASE-013).

- `GET ...` answers everything the story workspace shows in one call: the newest discovered
  list with each entry's link (or none), and the links whose discovered environment is no
  longer in the newest list. "A newer version is available" is worked out on every read from
  the pin and the library environment's newest version; it is information only.
- `POST .../link-all` makes a library environment for every unlinked entry.
- `POST .../{discovery_id}/create` makes one library environment from one entry and pins it.
- `PUT .../{discovery_id}` links the entry to an existing library environment and pins its
  newest version.
- `DELETE .../{discovery_id}` removes a link. The library environment stays in the lab.

Every action is a database write that is done before the answer, so none of them is a job. The
three that change links answer with the new state. The rules are in
`app/services/environment_links.py`. The answers never return ORM objects.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, cast

from fastapi import APIRouter, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.projects import load_project
from app.db.session import SessionDep
from app.services import environment_links
from app.services.environment_links import LinkInfo

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1

# The slug rule of discovered ids (`services/discovery_writer.clean_slug`): checked here so a
# stray value is refused before it reaches the database.
DiscoveryId = Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]*$", max_length=48)]

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or link."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no such discovered environment or library environment, or the "
        "link breaks a rule.",
    }
}

How = Literal["created", "mapped"]


class LinkedEnvironmentOut(BaseModel):
    """The library environment an entry is linked to, and the version the project pins."""

    environment_id: int
    name: str
    archived: bool
    how: How
    pinned_version: int
    # The library environment's newest version (None only for one with no version).
    newest_version: int | None
    # True when the lab has made a version after the pinned one. Information only: the pin
    # does not move.
    newer_version_available: bool
    # The version of the discovered list the link was made from.
    discovery_version: int


class OrphanedEnvironmentLinkOut(LinkedEnvironmentOut):
    """A link whose discovered environment is not in the newest list."""

    discovery_id: str


class EnvironmentLinkEntryOut(BaseModel):
    """One entry of the newest discovered list. `link` is None while it is unlinked."""

    id: str
    name: str
    description: str
    link: LinkedEnvironmentOut | None


class EnvironmentLinksOut(BaseModel):
    # None when the project has no discovered environments yet.
    discovery_version: int | None
    entries: list[EnvironmentLinkEntryOut]
    orphaned: list[OrphanedEnvironmentLinkOut]


class EnvironmentMapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]


def _linked_out(info: LinkInfo) -> LinkedEnvironmentOut:
    return LinkedEnvironmentOut(
        environment_id=info.link.environment_id,
        name=info.environment.name,
        archived=info.environment.archived,
        # The database CHECK constraint keeps `how` to the two allowed values.
        how=cast(How, info.link.how),
        pinned_version=info.link.pinned_version,
        newest_version=info.newest_version,
        newer_version_available=info.newer_version_available,
        discovery_version=info.link.discovery_version,
    )


async def _state_out(session: AsyncSession, project_id: int) -> EnvironmentLinksOut:
    links = await environment_links.state(session, project_id)
    return EnvironmentLinksOut(
        discovery_version=links.discovery_version,
        entries=[
            EnvironmentLinkEntryOut(
                id=entry.item["id"],
                name=entry.item["name"],
                description=entry.item["description"],
                link=_linked_out(entry.info) if entry.info is not None else None,
            )
            for entry in links.entries
        ],
        orphaned=[
            OrphanedEnvironmentLinkOut(
                **_linked_out(info).model_dump(), discovery_id=info.link.discovery_id
            )
            for info in links.orphaned
        ],
    )


def _refused(exc: environment_links.EnvironmentLinkError) -> HTTPException:
    if isinstance(exc, environment_links.LinkNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/environment-links",
    response_model=EnvironmentLinksOut,
    responses=_NOT_FOUND,
)
async def get_environment_links(project_id: int, session: SessionDep) -> EnvironmentLinksOut:
    project = await load_project(session, project_id)
    return await _state_out(session, project.id)


@router.post(
    "/projects/{project_id}/environment-links/link-all",
    response_model=EnvironmentLinksOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def link_all(project_id: int, session: SessionDep) -> EnvironmentLinksOut:
    """Makes a library environment for every unlinked entry of the newest list. When everything
    is linked already, nothing is made.
    """
    project = await load_project(session, project_id)
    try:
        await environment_links.link_all(session, project)
    except environment_links.EnvironmentLinkError as exc:
        raise _refused(exc) from exc
    return await _state_out(session, project.id)


@router.post(
    "/projects/{project_id}/environment-links/{discovery_id}/create",
    response_model=EnvironmentLinksOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def create_link(
    project_id: int, discovery_id: DiscoveryId, session: SessionDep
) -> EnvironmentLinksOut:
    """Makes a new library environment from one entry of the newest list and pins its version
    1.
    """
    project = await load_project(session, project_id)
    try:
        await environment_links.create(session, project, discovery_id)
    except environment_links.EnvironmentLinkError as exc:
        raise _refused(exc) from exc
    return await _state_out(session, project.id)


@router.put(
    "/projects/{project_id}/environment-links/{discovery_id}",
    response_model=EnvironmentLinksOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def map_link(
    project_id: int, discovery_id: DiscoveryId, body: EnvironmentMapIn, session: SessionDep
) -> EnvironmentLinksOut:
    """Links one entry of the newest list to an existing library environment and pins that
    environment's newest version.
    """
    project = await load_project(session, project_id)
    try:
        await environment_links.map_to_existing(session, project, discovery_id, body.environment_id)
    except environment_links.EnvironmentLinkError as exc:
        raise _refused(exc) from exc
    return await _state_out(session, project.id)


@router.delete(
    "/projects/{project_id}/environment-links/{discovery_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_NOT_FOUND,
)
async def delete_link(project_id: int, discovery_id: DiscoveryId, session: SessionDep) -> Response:
    """Removes the link. The library environment stays in the Character Lab."""
    project = await load_project(session, project_id)
    try:
        await environment_links.unlink(session, project, discovery_id)
    except environment_links.EnvironmentLinkError as exc:
        raise _refused(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
