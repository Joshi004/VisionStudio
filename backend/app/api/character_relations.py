"""`/api/projects/{project_id}/character-relations`: the relations between a story's characters
(PHASE-047).

- `GET ...` answers everything the story workspace shows in one call: the newest list of
  characters, the newest version of the relations (only the ones between characters that are
  still in the list, and the ones that are not), why the version is out of date, the newest job
  and whether Find relations may be pressed. Out of date is worked out on every read.
- `POST .../run` starts the `discover_relations` job. When the newest version was written by the
  user, the body must say `confirm_replace_manual: true`.
- `PUT ...` saves the user's whole edited list as the next version (`source` is `manual`). The
  list is checked the same way the model's answer is.

The rows and the job are made by `app/services/character_relations.py`. The answers never
return ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.discovery import DiscoveryJobOut
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import CharacterRelations
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import character_relation_writer as writer
from app.services import character_relations

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "There is no saved story, up-to-date Story Bible or list of characters, "
        "or the relations are not valid, or the newest ones need confirming.",
    }
}

Source = Literal["ai", "manual"]
# What is stored. `child` and `grandchild` are only accepted on input.
Kind = Literal["younger_self", "older_self", "twin", "parent", "sibling", "grandparent"]
InputKind = Literal[
    "younger_self", "older_self", "twin", "parent", "sibling", "grandparent", "child", "grandchild"
]
CharacterId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=48)]


class RelationCharacterOut(BaseModel):
    id: str
    name: str
    description: str


class RelationOut(BaseModel):
    """`character` is the `kind` of `of`: "young_arjun" is the "younger_self" of "arjun"."""

    character: str
    kind: Kind
    of: str


class RelationsVersionOut(BaseModel):
    version: int
    source: Source
    job_id: int | None
    created_at: datetime


class CharacterRelationsOut(BaseModel):
    # None when the project has no discovered characters yet.
    discovery_version: int | None
    characters: list[RelationCharacterOut]
    # None when there is no version yet.
    latest: RelationsVersionOut | None
    # The newest version's relations between characters that are in the newest list.
    relations: list[RelationOut]
    # Its relations that name a character that is no longer in the list.
    dropped: list[RelationOut]
    # Why the newest version is out of date, one sentence each.
    reasons: list[str]
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None
    # True when finding the relations again replaces a list the user wrote.
    needs_confirmation: bool


class RelationRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False


class RelationRunOut(BaseModel):
    job_id: int


class RelationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character: CharacterId
    kind: InputKind
    of: CharacterId


class RelationsSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relations: list[RelationIn] = Field(max_length=writer.MAX_RELATIONS)


def _version_out(row: CharacterRelations) -> RelationsVersionOut:
    return RelationsVersionOut(
        version=row.version,
        # The database CHECK constraint keeps `source` to the two allowed values.
        source=cast(Source, row.source),
        job_id=row.job_id,
        created_at=row.created_at,
    )


def _relations_out(relations: list[dict[str, str]]) -> list[RelationOut]:
    return [
        RelationOut(
            character=relation["character"],
            kind=cast(Kind, relation["kind"]),
            of=relation["of"],
        )
        for relation in relations
    ]


def _state_out(result: character_relations.RelationsState) -> CharacterRelationsOut:
    job = result.job
    return CharacterRelationsOut(
        discovery_version=result.discovery_version,
        characters=[
            RelationCharacterOut(id=item["id"], name=item["name"], description=item["description"])
            for item in result.characters
        ],
        latest=_version_out(result.version) if result.version is not None else None,
        relations=_relations_out(result.relations),
        dropped=_relations_out(result.dropped),
        reasons=result.reasons,
        job=(
            DiscoveryJobOut(
                id=job.id,
                status=cast(JobStatus, job.status),
                phase=job.phase,
                error=job.error,
            )
            if job is not None
            else None
        ),
        can_run=result.can_run,
        blocked_reason=result.blocked_reason,
        needs_confirmation=result.needs_confirmation,
    )


def _refused(exc: character_relations.CharacterRelationError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/character-relations",
    response_model=CharacterRelationsOut,
    responses=_NOT_FOUND,
)
async def get_character_relations(project_id: int, session: SessionDep) -> CharacterRelationsOut:
    project = await load_project(session, project_id)
    return _state_out(await character_relations.state(session, project))


@router.post(
    "/projects/{project_id}/character-relations/run",
    response_model=RelationRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_character_relations(
    project_id: int, session: SessionDep, body: RelationRunIn | None = None
) -> RelationRunOut:
    """Starts the job that finds the relations. If one is already waiting or running for the
    project, its id is returned and no second job is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await character_relations.start_run(
            session,
            project,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except character_relations.CharacterRelationError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return RelationRunOut(job_id=job.id)


@router.put(
    "/projects/{project_id}/character-relations",
    response_model=CharacterRelationsOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_character_relations(
    project_id: int, body: RelationsSaveIn, session: SessionDep
) -> CharacterRelationsOut:
    """Saves the whole edited list as the next version, written by the user."""
    project = await load_project(session, project_id)
    try:
        await character_relations.save_manual(
            session,
            project,
            [relation.model_dump() for relation in body.relations],
        )
    except character_relations.CharacterRelationError as exc:
        raise _refused(exc) from exc
    return _state_out(await character_relations.state(session, project))
