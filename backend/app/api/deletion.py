"""Deleting projects, library characters and library environments (PHASE-055).

- `GET /projects/{id}/deletion-preview` lists the characters and environments the project used,
  and the other projects that use them too, so the user can choose what goes with the project.
- `POST /projects/{id}/delete` deletes the project and the chosen characters and environments.
  It is a POST because it carries the choice in its body.
- `GET /lab/characters/{id}/deletion-preview` and `DELETE /lab/characters/{id}`, and the same two
  for `/lab/environments/{id}`: the projects that use the item are listed first, and are flagged
  (not changed) when it is deleted.

A refusal because work is still running is a 409; a missing item is a 404. The rules are in
`services/project_deletion.py` and `services/library_deletion.py`. The answers never return ORM
objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import ErrorResponse
from app.api.projects import load_project
from app.db.session import SessionDep
from app.services import library_deletion, project_deletion
from app.services.storage import Storage, get_storage

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
LibraryId = Annotated[int, Path(ge=1, le=_MAX_ID)]
ItemId = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or library item."}}
_BUSY = {
    409: {"model": ErrorResponse, "description": "Work on it is still running."},
}

StorageDep = Annotated[Storage, Depends(get_storage)]


class ProjectUseOut(BaseModel):
    """A project that uses a library item."""

    project_id: int
    project_name: str
    # The discovered entry that is linked to the item, or None when it is only in the cast.
    discovery_id: str | None
    in_cast: bool


class MissingItemOut(BaseModel):
    """What a project's link panel shows for an entry whose library item was deleted."""

    name: str
    deleted_at: datetime


class LibraryDeletionPreviewOut(BaseModel):
    library_id: int
    name: str
    projects: list[ProjectUseOut]
    blocked_reason: str | None


class DeletionItemOut(BaseModel):
    """One library item a project used, as the delete dialog lists it."""

    library_id: int
    name: str
    how: Literal["created", "mapped", "cast", "made_for_project"]
    archived: bool
    in_cast: bool
    other_projects: list[str]
    blocked_reason: str | None


class ProjectDeletionPreviewOut(BaseModel):
    project_id: int
    name: str
    blocked_reason: str | None
    take_count: int
    render_count: int
    characters: list[DeletionItemOut]
    environments: list[DeletionItemOut]


class ProjectDeleteIn(BaseModel):
    """The library items to delete with the project. Anything left out stays in the library."""

    model_config = ConfigDict(extra="forbid")

    character_ids: list[ItemId] = Field(default_factory=list, max_length=500)
    environment_ids: list[ItemId] = Field(default_factory=list, max_length=500)


def _item_out(item: project_deletion.ItemPreview) -> DeletionItemOut:
    return DeletionItemOut(
        library_id=item.library_id,
        name=item.name,
        how=item.how,
        archived=item.archived,
        in_cast=item.in_cast,
        other_projects=item.other_projects,
        blocked_reason=item.blocked_reason,
    )


def _library_out(result: library_deletion.Preview) -> LibraryDeletionPreviewOut:
    return LibraryDeletionPreviewOut(
        library_id=result.library_id,
        name=result.name,
        projects=[
            ProjectUseOut(
                project_id=use.project_id,
                project_name=use.project_name,
                discovery_id=use.discovery_id,
                in_cast=use.in_cast,
            )
            for use in result.projects
        ],
        blocked_reason=result.blocked_reason,
    )


def _refused(exc: library_deletion.LibraryDeletionError) -> HTTPException:
    if isinstance(exc, library_deletion.LibraryItemNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, library_deletion.LibraryItemBusyError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


# --- Projects --------------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/deletion-preview",
    response_model=ProjectDeletionPreviewOut,
    responses=_NOT_FOUND,
)
async def get_project_deletion_preview(
    project_id: int, session: SessionDep
) -> ProjectDeletionPreviewOut:
    project = await load_project(session, project_id)
    result = await project_deletion.preview(session, project)
    return ProjectDeletionPreviewOut(
        project_id=result.project_id,
        name=result.name,
        blocked_reason=result.blocked_reason,
        take_count=result.take_count,
        render_count=result.render_count,
        characters=[_item_out(item) for item in result.characters],
        environments=[_item_out(item) for item in result.environments],
    )


@router.post(
    "/projects/{project_id}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **_NOT_FOUND,
        **_BUSY,
        422: {"model": ErrorResponse, "description": "A chosen item is not the project's."},
    },
)
async def delete_project(
    project_id: int, body: ProjectDeleteIn, session: SessionDep, storage: StorageDep
) -> Response:
    """Deletes the project, its files, and the chosen characters and environments."""
    project = await load_project(session, project_id)
    try:
        await project_deletion.delete_project(
            session, storage, project, body.character_ids, body.environment_ids
        )
    except project_deletion.ProjectBusyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except project_deletion.ProjectDeletionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except library_deletion.LibraryDeletionError as exc:
        raise _refused(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Library characters and environments -----------------------------------------------------


async def _preview(session: SessionDep, kind: str, library_id: int) -> LibraryDeletionPreviewOut:
    try:
        return _library_out(await library_deletion.preview(session, kind, library_id))
    except library_deletion.LibraryDeletionError as exc:
        raise _refused(exc) from exc


async def _delete(session: SessionDep, storage: Storage, kind: str, library_id: int) -> Response:
    try:
        await library_deletion.delete_item(session, storage, kind, library_id)
    except library_deletion.LibraryDeletionError as exc:
        raise _refused(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/lab/characters/{character_id}/deletion-preview",
    response_model=LibraryDeletionPreviewOut,
    responses=_NOT_FOUND,
)
async def get_character_deletion_preview(
    character_id: LibraryId, session: SessionDep
) -> LibraryDeletionPreviewOut:
    return await _preview(session, "character", character_id)


@router.delete(
    "/lab/characters/{character_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND, **_BUSY},
)
async def delete_character(
    character_id: LibraryId, session: SessionDep, storage: StorageDep
) -> Response:
    """Deletes the character for good. Projects that used it are flagged, not changed."""
    return await _delete(session, storage, "character", character_id)


@router.get(
    "/lab/environments/{environment_id}/deletion-preview",
    response_model=LibraryDeletionPreviewOut,
    responses=_NOT_FOUND,
)
async def get_environment_deletion_preview(
    environment_id: LibraryId, session: SessionDep
) -> LibraryDeletionPreviewOut:
    return await _preview(session, "environment", environment_id)


@router.delete(
    "/lab/environments/{environment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND, **_BUSY},
)
async def delete_environment(
    environment_id: LibraryId, session: SessionDep, storage: StorageDep
) -> Response:
    """Deletes the environment for good. Projects that used it are flagged, not changed."""
    return await _delete(session, storage, "environment", environment_id)
