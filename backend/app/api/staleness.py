"""`/api/projects/{project_id}/staleness`: what is out of date in the project (PHASE-039).

- `GET ...` lists every out-of-date artifact, grouped by step of the story pipeline, with the
  reasons and whether it can be accepted as it is. Worked out on every read from what each stage
  recorded (D-3); nothing is stored for it.
- `POST .../accept` keeps one out-of-date artifact as it is: it adds a version with the same
  content whose provenance says it was made from what is current now. It makes no job and calls
  no model, and nothing made from the artifact is touched. It answers the new list, or 422 with
  the stage's own reason.

The answers never return ORM objects.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.projects import load_project
from app.db.models import Project
from app.db.session import SessionDep
from app.services import staleness

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The artifact is not out of date, cannot be accepted as it is, or its "
        "stage refused (for example because the stage before it is not ready).",
    }
}

_Id = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=48)]


class StalenessItemOut(BaseModel):
    """One out-of-date artifact. The key fields say which one: the stage uses `scene_id`,
    `shot_id`, `discovery_id` or `unit_id`, and leaves the others out.
    """

    stage: str
    title: str
    reasons: list[str]
    # True when "Accept as is" is offered for it.
    acceptable: bool
    scene_id: str | None = None
    shot_id: str | None = None
    discovery_id: str | None = None
    unit_id: str | None = None


class StalenessGroupOut(BaseModel):
    step: str
    label: str
    items: list[StalenessItemOut]


class StalenessOut(BaseModel):
    count: int
    groups: list[StalenessGroupOut]


class AcceptIn(BaseModel):
    """Which artifact to accept as it is. `scene_id` and `shot_id` are given for the stages
    that work per scene or per shot.
    """

    model_config = ConfigDict(extra="forbid")

    stage: staleness.AcceptStage
    scene_id: _Id | None = None
    shot_id: _Id | None = None


def _out(overview: staleness.Overview) -> StalenessOut:
    return StalenessOut(
        count=overview.count,
        groups=[
            StalenessGroupOut(
                step=group.step,
                label=group.label,
                items=[
                    StalenessItemOut(
                        stage=item.stage,
                        title=item.title,
                        reasons=item.reasons,
                        acceptable=item.acceptable,
                        scene_id=item.scene_id,
                        shot_id=item.shot_id,
                        discovery_id=item.discovery_id,
                        unit_id=item.unit_id,
                    )
                    for item in group.items
                ],
            )
            for group in overview.groups
        ],
    )


async def _read(session: AsyncSession, project: Project) -> StalenessOut:
    return _out(await staleness.overview(session, project))


@router.get(
    "/projects/{project_id}/staleness",
    response_model=StalenessOut,
    responses=_NOT_FOUND,
)
async def get_staleness(project_id: int, session: SessionDep) -> StalenessOut:
    """Everything out of date in the project, by step, with the reasons."""
    project = await load_project(session, project_id)
    return await _read(session, project)


@router.post(
    "/projects/{project_id}/staleness/accept",
    response_model=StalenessOut,
    status_code=status.HTTP_200_OK,
    responses={**_NOT_FOUND, **_INVALID},
)
async def accept_as_is(project_id: int, body: AcceptIn, session: SessionDep) -> StalenessOut:
    """Keeps one out-of-date artifact as it is, then answers what is still out of date."""
    project = await load_project(session, project_id)
    try:
        overview = await staleness.accept_as_is(
            session, project, body.stage, scene_id=body.scene_id, shot_id=body.shot_id
        )
    except staleness.StalenessError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _out(overview)
