"""`/api/projects/{project_id}/shot-references`: the reference manifest of each shot (PHASE-024).

- `GET ...` answers everything the story workspace shows in one call: the newest list of scenes,
  and for each scene its shots (from the newest shot plan) with the status of each shot's
  manifest (`not_selected`, `selected`, `out_of_date`), why it is out of date, the newest
  manifest (the ordered pictures with their addresses, and the catalog they were chosen from)
  with its provenance, and whether Select may be pressed. Out of date is worked out on every
  read.
- `POST .../run` ("Select all") chooses the references of every shot, in every scene, that has
  none or an out of date manifest.
- `POST .../{scene_id}/run` does the same for one scene.
- `POST .../{scene_id}/{shot_id}/run` does it for one shot. When the newest manifest was chosen
  by the user, the body must say `confirm_replace_manual` (PHASE-038).
- `PUT .../{scene_id}/{shot_id}` saves the user's own choice of pictures (from the catalog the
  shot may use, in the order given) as the shot's next manifest (`source` and `method` are
  `manual`). The generation request and the prompt follow, as after any manifest.

The setting `reference_selection_method` says who chooses (PHASE-033). The fixed rule chooses
in the request, with no model and no job. With the language model, a job is queued for each shot
(`select_shot_references`) and its manifest appears when it is done. Either way the answer is 200
and says which shots were chosen now (`selected`), which were queued (`queued`) and which were
skipped and why. A manifest is a new version of the shot's manifest
(`services/shot_references.py`); nothing is written to the Character Lab. The answers never
return ORM objects.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.discovery import DiscoveryJobOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.db.models import LabImage, Project
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import generation_requests, shot_chain, shot_prompts, shot_references, storage
from app.services.shot_references import SceneEntry, ShotEntry

_logger = logging.getLogger(__name__)

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The shot is not defined and current, a picture it needs is missing, or "
        "the scene or shot is not in the newest list of scenes and shot plan.",
    }
}

Source = Literal["ai", "manual"]
Method = Literal["deterministic", "llm", "manual"]
Status = Literal["not_selected", "selected", "out_of_date"]
# `presenter` is the type of a shot of a continuous explainer that shows the presenter (FLOW-005).
ShotType = Literal[
    "establishing", "action", "reaction", "dialogue", "insert", "transition", "presenter"
]
PictureKind = Literal["character", "environment"]
DefinitionStatus = Literal["not_defined", "defined", "out_of_date"]


class ReferencePictureOut(BaseModel):
    """One picture of the manifest, in the order it is sent."""

    order: int
    lab_image_id: int
    # None when the picture no longer exists.
    url: str | None
    kind: PictureKind
    subject_id: str
    subject_name: str
    # A character's angle (`front`, `three_quarter`, `face`, ...) or `environment`.
    view: str
    # `default`, or the slug of the named look or state the picture belongs to.
    variant: str
    # True when the look the scene resolved to had no picture of this angle and the default
    # look's was used instead.
    fallback: bool
    description: str
    # Why the language model chose this picture. None when the fixed rule chose, and for a
    # manifest made before PHASE-033.
    reason: str | None = None


class CatalogPictureOut(BaseModel):
    """One picture that could have been chosen."""

    lab_image_id: int
    url: str | None
    kind: PictureKind
    subject_id: str
    subject_name: str
    view: str
    variant: str
    is_resolved: bool
    description: str


class ShotReferenceManifestOut(BaseModel):
    # How it was chosen: by the language model, by the fixed rule, or by the user.
    method: Method
    # Why the fixed rule chose when the language model was meant to (its answer could not be
    # used, or the call failed). None otherwise.
    fallback_reason: str | None = None
    shot_size: str
    framing: str
    focus_character_id: str | None
    references: list[ReferencePictureOut]
    catalog: list[CatalogPictureOut]
    notes: list[str]


class ShotReferenceVersionOut(BaseModel):
    """The provenance of the newest manifest of a shot (D-3)."""

    version: int
    source: Source
    # The job that chose it with the language model. None when the fixed rule chose (no model
    # was asked) and for a manifest the user chose.
    job_id: int | None
    created_at: datetime


class ShotReferenceSkeletonOut(BaseModel):
    id: str
    type: ShotType
    description: str
    duration_seconds: float


class ShotReferenceEntryOut(BaseModel):
    shot: ShotReferenceSkeletonOut
    # Where the shot's definition stands: the manifest is chosen from it.
    definition_status: DefinitionStatus
    status: Status
    # Why a selected manifest is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    manifest: ShotReferenceManifestOut | None
    version: ShotReferenceVersionOut | None
    # The newest job that chose this shot's references with the language model, whatever its
    # status. None when the fixed rule has always chosen.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None
    # True when the newest manifest was chosen by the user: choosing again by the fixed rule or
    # the model has to be confirmed (PHASE-038).
    needs_confirmation: bool


class SceneShotReferencesOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    description: str
    shots: list[ShotReferenceEntryOut]


class ShotReferencesOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    entries: list[SceneShotReferencesOut]
    # Why nothing can be chosen yet, or None.
    blocked_reason: str | None


class ShotReferenceSelectedOut(BaseModel):
    scene_id: str
    shot_id: str
    version: int


class ShotReferenceSkippedOut(BaseModel):
    scene_id: str
    shot_id: str | None
    title: str
    reason: str


class ShotReferenceQueuedOut(BaseModel):
    scene_id: str
    shot_id: str
    job_id: int


class ShotReferenceRunIn(BaseModel):
    """The optional body of the run of one shot."""

    model_config = ConfigDict(extra="forbid")

    confirm_replace_manual: bool = False


class ShotReferencesEditIn(BaseModel):
    """The user's own choice: the ids of the pictures (`lab_image_id` of the catalog), in the
    order they are sent. The rules (in the catalog, no repeat, from 1 to 9) are checked by
    `reference_selection.manual`; the limit here only keeps a request from being huge.
    """

    model_config = ConfigDict(extra="forbid")

    lab_image_ids: list[int] = Field(max_length=100)


class ShotReferencesRunOut(BaseModel):
    # Chosen by the fixed rule, inside the request.
    selected: list[ShotReferenceSelectedOut]
    # Handed to the language model: a job for each, whose result appears when it is done.
    queued: list[ShotReferenceQueuedOut]
    skipped: list[ShotReferenceSkippedOut]


async def _urls(state: shot_references.ShotReferencesState, session: SessionDep) -> dict[int, str]:
    """The address of every picture the newest manifests name, by lab image id."""
    ids: set[int] = set()
    for scene in state.entries:
        for shot in scene.shots:
            if shot.row is not None:
                for picture in (*shot.row.content["references"], *shot.row.content["catalog"]):
                    ids.add(picture["lab_image_id"])
    if not ids:
        return {}
    rows = (
        await session.execute(select(LabImage.id, LabImage.path).where(LabImage.id.in_(ids)))
    ).all()
    return {image_id: storage.media_url(path) for image_id, path in rows}


def _manifest_out(content: dict[str, Any], urls: dict[int, str]) -> ShotReferenceManifestOut:
    return ShotReferenceManifestOut(
        method=content["method"],
        # A manifest made before PHASE-033 has no `fallback_reason`.
        fallback_reason=content.get("fallback_reason"),
        shot_size=content["shot_size"],
        framing=content["framing"],
        focus_character_id=content["focus_character_id"],
        references=[
            ReferencePictureOut(**picture, url=urls.get(picture["lab_image_id"]))
            for picture in content["references"]
        ],
        catalog=[
            CatalogPictureOut(**picture, url=urls.get(picture["lab_image_id"]))
            for picture in content["catalog"]
        ],
        notes=content["notes"],
    )


def _shot_out(entry: ShotEntry, urls: dict[int, str]) -> ShotReferenceEntryOut:
    shot = entry.shot
    row = entry.row
    return ShotReferenceEntryOut(
        shot=ShotReferenceSkeletonOut(
            id=shot["id"],
            type=shot["type"],
            description=shot["description"],
            duration_seconds=entry.duration_s,
        ),
        definition_status=cast(DefinitionStatus, entry.definition_status),
        status=entry.status,
        reasons=entry.reasons,
        manifest=_manifest_out(row.content, urls) if row is not None else None,
        version=(
            ShotReferenceVersionOut(
                version=row.version,
                # The database CHECK constraint keeps `source` to the two allowed values.
                source=cast(Source, row.source),
                job_id=row.job_id,
                created_at=row.created_at,
            )
            if row is not None
            else None
        ),
        job=(
            DiscoveryJobOut(
                id=entry.job.id,
                status=cast(JobStatus, entry.job.status),
                phase=entry.job.phase,
                error=entry.job.error,
            )
            if entry.job is not None
            else None
        ),
        can_run=entry.can_run,
        blocked_reason=entry.blocked_reason,
        needs_confirmation=entry.needs_confirmation,
    )


def _scene_out(entry: SceneEntry, urls: dict[int, str]) -> SceneShotReferencesOut:
    return SceneShotReferencesOut(
        id=entry.item["id"],
        index=entry.item["index"],
        title=entry.item["title"],
        description=entry.item["description"],
        shots=[_shot_out(shot, urls) for shot in entry.shots],
    )


def _run_out(result: shot_references.SelectResult) -> ShotReferencesRunOut:
    return ShotReferencesRunOut(
        selected=[
            ShotReferenceSelectedOut(
                scene_id=item.scene_id, shot_id=item.shot_id, version=item.version
            )
            for item in result.selected
        ],
        queued=[
            ShotReferenceQueuedOut(scene_id=item.scene_id, shot_id=item.shot_id, job_id=item.job_id)
            for item in result.queued
        ],
        skipped=[
            ShotReferenceSkippedOut(
                scene_id=item.scene_id, shot_id=item.shot_id, title=item.title, reason=item.reason
            )
            for item in result.skipped
        ],
    )


def _refused(exc: shot_references.ShotReferencesError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


async def _plan_requests(
    session: SessionDep, project_id: int, result: shot_references.SelectResult
) -> None:
    """Plans the generation request of each shot whose references were just chosen (PHASE-025).
    A shot that cannot be planned yet is left for the user's **Plan** and never fails the press.
    A shot that was planned has its prompt compiled next (PHASE-026). The shots handed to the
    language model (`result.queued`) are planned by their own job when it is done; here the
    dispatcher is only woken for them.
    """
    if result.queued:
        dispatcher.nudge()
    for item in result.selected:
        try:
            planned = await generation_requests.plan_if_ready(
                session, project_id, item.scene_id, item.shot_id
            )
        except Exception:
            _logger.exception(
                "the generation request of shot '%s' of scene '%s' could not be planned",
                item.shot_id,
                item.scene_id,
            )
            continue
        if planned:
            await shot_prompts.queue_after_planning(project_id, item.scene_id, item.shot_id)


@router.get(
    "/projects/{project_id}/shot-references",
    response_model=ShotReferencesOut,
    responses=_NOT_FOUND,
)
async def get_shot_references(project_id: int, session: SessionDep) -> ShotReferencesOut:
    project = await load_project(session, project_id)
    return await _state_out(session, project)


async def _state_out(session: AsyncSession, project: Project) -> ShotReferencesOut:
    result = await shot_references.state(session, project)
    urls = await _urls(result, session)
    return ShotReferencesOut(
        scenes_version=result.scenes_version,
        entries=[_scene_out(entry, urls) for entry in result.entries],
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/projects/{project_id}/shot-references/run",
    response_model=ShotReferencesRunOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> ShotReferencesRunOut:
    """Chooses the references of every shot that has none or an out of date manifest. The shots
    that cannot be done are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        result = await shot_references.select_all(session, project)
    except shot_references.ShotReferencesError as exc:
        raise _refused(exc) from exc
    await _plan_requests(session, project_id, result)
    return _run_out(result)


@router.post(
    "/projects/{project_id}/shot-references/{scene_id}/run",
    response_model=ShotReferencesRunOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_scene(
    project_id: int, scene_id: DiscoveryId, session: SessionDep
) -> ShotReferencesRunOut:
    """Chooses the references of every shot of one scene that has none or an out of date
    manifest.
    """
    project = await load_project(session, project_id)
    try:
        result = await shot_references.select_scene(session, project, scene_id)
    except shot_references.ShotReferencesError as exc:
        raise _refused(exc) from exc
    await _plan_requests(session, project_id, result)
    return _run_out(result)


@router.post(
    "/projects/{project_id}/shot-references/{scene_id}/{shot_id}/run",
    response_model=ShotReferencesRunOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_shot(
    project_id: int,
    scene_id: DiscoveryId,
    shot_id: DiscoveryId,
    session: SessionDep,
    body: ShotReferenceRunIn | None = None,
) -> ShotReferencesRunOut:
    """Chooses the references of one shot. Refused with the reason when it cannot be done."""
    project = await load_project(session, project_id)
    try:
        result = await shot_references.select_shot(
            session,
            project,
            scene_id,
            shot_id,
            confirm_replace_manual=body.confirm_replace_manual if body is not None else False,
        )
    except shot_references.ShotReferencesError as exc:
        raise _refused(exc) from exc
    await _plan_requests(session, project_id, result)
    return _run_out(result)


@router.put(
    "/projects/{project_id}/shot-references/{scene_id}/{shot_id}",
    response_model=ShotReferencesOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def save_shot_references(
    project_id: int,
    scene_id: DiscoveryId,
    shot_id: DiscoveryId,
    body: ShotReferencesEditIn,
    session: SessionDep,
) -> ShotReferencesOut:
    """Saves the user's own choice of pictures for one shot as its next manifest, and then plans
    the generation request and queues the prompt, as after any manifest.
    """
    project = await load_project(session, project_id)
    try:
        await shot_references.save_manual(session, project, scene_id, shot_id, body.lab_image_ids)
    except shot_references.ShotReferencesError as exc:
        raise _refused(exc) from exc
    await shot_chain.after_references_saved(project_id, scene_id, shot_id)
    return await _state_out(session, project)
