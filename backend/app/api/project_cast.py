"""`/api/projects/{project_id}/cast`: the library characters and environments the user wants to
reuse in a story project (PHASE-048).

- `GET ...` answers the whole cast: the characters and the environments, each with its mode and
  whether the library item is archived.
- `PUT .../{kind}/{library_id}` puts a library item in the cast, or changes the mode of one that
  is in it already. `kind` is `characters` or `environments`.
- `DELETE .../{kind}/{library_id}` takes an item out of the cast. The library item stays.

Every action is a database write that is done before the answer; none is a job. The two that
change the cast answer with the new cast. The rules are in `app/services/project_cast.py`.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from fastapi import APIRouter, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.projects import load_project
from app.db.session import SessionDep
from app.services import project_cast
from app.services.project_cast import CastMember, Kind, Mode

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1

LibraryId = Annotated[int, Path(ge=1, le=_MAX_ID)]

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project or cast member."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no such library item, it is archived, or the cast is full.",
    }
}


class CastMemberOut(BaseModel):
    library_id: int
    name: str
    mode: Literal["as_is", "rewrite_text"]
    archived: bool


class CastOut(BaseModel):
    characters: list[CastMemberOut]
    environments: list[CastMemberOut]


class CastMemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["as_is", "rewrite_text"] = "as_is"


def _member_out(member: CastMember) -> CastMemberOut:
    return CastMemberOut(
        library_id=member.library_id,
        name=member.name,
        mode=member.mode,
        archived=member.archived,
    )


async def _cast_out(session: AsyncSession, project_id: int) -> CastOut:
    return CastOut(
        characters=[
            _member_out(member)
            for member in await project_cast.list_cast(session, project_id, "characters")
        ],
        environments=[
            _member_out(member)
            for member in await project_cast.list_cast(session, project_id, "environments")
        ],
    )


def _refused(exc: project_cast.CastError) -> HTTPException:
    if isinstance(exc, project_cast.CastMemberNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get("/projects/{project_id}/cast", response_model=CastOut, responses=_NOT_FOUND)
async def get_cast(project_id: int, session: SessionDep) -> CastOut:
    project = await load_project(session, project_id)
    return await _cast_out(session, project.id)


@router.put(
    "/projects/{project_id}/cast/{kind}/{library_id}",
    response_model=CastOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def put_cast_member(
    project_id: int,
    kind: Kind,
    library_id: LibraryId,
    body: CastMemberIn,
    session: SessionDep,
) -> CastOut:
    """Puts a library item in the cast with this mode, or changes the mode of one already in it."""
    project = await load_project(session, project_id)
    mode: Mode = body.mode
    try:
        await project_cast.add_member(session, project.id, kind, library_id, mode)
    except project_cast.CastError as exc:
        raise _refused(exc) from exc
    return await _cast_out(session, project.id)


@router.delete(
    "/projects/{project_id}/cast/{kind}/{library_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_NOT_FOUND,
)
async def delete_cast_member(
    project_id: int, kind: Kind, library_id: LibraryId, session: SessionDep
) -> Response:
    """Takes the library item out of the cast. The item itself stays in its lab."""
    project = await load_project(session, project_id)
    try:
        await project_cast.remove_member(session, project.id, kind, library_id)
    except project_cast.CastError as exc:
        raise _refused(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
