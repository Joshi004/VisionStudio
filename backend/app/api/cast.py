"""The project's cast: its characters and places (project cast and character consistency).

`GET /api/projects/{id}/cast` reads the database only: the characters and the places, each with
its description, its reference prompt and picture, the newest job of each and what blocks the
next step.

`POST .../extract-cast` starts the `extract_cast` job: a language model reads the script and
lists the cast. It is a paid call, so it only runs from this click or from an automatic run, and
it replaces the whole cast, so it answers 409 until the request confirms that when there is a
cast already. `POST .../assign-cast` starts the `assign_cast` job (a paid call too), which
chooses the characters and the one place each scene shows.

A cast member is edited with `PATCH .../cast/{kind}/{id}` and gets its reference picture from
`POST .../cast/{kind}/{id}/write-reference-prompt` (a paid call that writes the prompt for the
image model) and `POST .../cast/{kind}/{id}/generate-reference` (the picture, made on the GPU
server; when the member has no prompt yet, the prompt is written first and the picture follows by
itself). `kind` is `character` or `location`. A scene's choice is overridden by hand with
`PATCH .../scenes/{id}/cast`, which answers with the scenes, like the other scene edits.

Every endpoint that starts a job returns at once with HTTP 202. The dispatcher does the work. The
rules are in `services/cast.py`.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal
from typing import cast as typing_cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.api.projects import load_project
from app.api.scenes import ScenesOut, scenes_out
from app.db.models import Asset, Job, Project, Scene
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.providers import image_generator
from app.services import cast as cast_service
from app.services import cast_extraction, scene_planner, transcript_matching
from app.services import scenes as scenes_service
from app.services.storage import media_url

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1

MemberId = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]
Kind = Literal["character", "location"]
MemberStatus = Literal["pending", "prompted", "ready", "failed"]
TextSource = Literal["manual", "ai"]

_NOT_FOUND = {
    404: {
        "model": ErrorResponse,
        "description": "No project, character, place or scene has this id.",
    }
}
_BLOCKED = {
    422: {
        "model": ErrorResponse,
        "description": "The step cannot start now: the script is empty or too long, other cast "
        "jobs are running, there are no scenes or no cast, or the member has nothing to work "
        "from.",
    }
}

_ALL_CAST_JOBS: Final = (
    cast_service.EXTRACT_JOB,
    cast_service.REFERENCE_PROMPT_JOB,
    cast_service.REFERENCE_IMAGE_JOB,
    cast_service.ASSIGN_JOB,
)


# --- What the page reads ---------------------------------------------------------------------


class CastMemberOut(BaseModel):
    kind: Kind
    id: int
    name: str
    # What the member looks like: the text the picture is made from, written by the AI and
    # edited by the user.
    appearance_description: str
    # Characters only: None for a place.
    personality_description: str | None
    voice_description: str | None
    # The prompt for the image model that makes the reference picture, and who wrote it.
    reference_prompt: str | None
    reference_prompt_source: TextSource | None
    status: MemberStatus
    # The reference picture (under `/media/`), or None while there is none. A character's has a
    # transparent backdrop when `reference_has_transparency`.
    reference_url: str | None
    reference_has_transparency: bool
    reference_width: int | None
    reference_height: int | None
    # The newest job that wrote the prompt, and the newest that made the picture, whatever
    # their status (a failed one says why).
    prompt_job: JobSummary | None
    image_job: JobSummary | None
    # Why the prompt, or the picture, cannot be made now, or None when it can.
    prompt_blocked_reason: str | None
    image_blocked_reason: str | None
    # How many scenes show this member.
    scene_count: int


class CastOut(BaseModel):
    characters: list[CastMemberOut]
    locations: list[CastMemberOut]
    # The newest `extract_cast` job, whatever its status.
    extract_job: JobSummary | None
    # Why the cast cannot be found now, or None when it can. The confirmation is not a reason:
    # the page asks first, and the endpoint answers 409.
    extract_blocked_reason: str | None
    # Finding the cast again replaces all of it (and the pictures made for it).
    extract_needs_confirmation: bool
    # The script is not the one the cast was found in.
    script_changed: bool
    # The newest `assign_cast` job, and why scenes cannot be assigned now, or None.
    assign_job: JobSummary | None
    assign_blocked_reason: str | None
    # How many scenes have a choice of character and place (nobody is a choice), of how many.
    scenes_assigned: int
    scene_count: int


class ExtractCastRequest(BaseModel):
    """What the user has confirmed. Every flag is off unless sent."""

    model_config = ConfigDict(extra="forbid")

    # Replace the cast that is there. Its pictures stay on disk, but belong to nobody.
    confirm_replace: StrictBool = False


class WriteReferencePromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Make the picture as soon as the prompt is written.
    generate_after: StrictBool = False


class CastMemberPatch(BaseModel):
    """What to change in a member. Only the fields that are sent change. A blank personality,
    voice or reference prompt clears it. A prompt written by hand is kept by every automatic run.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    appearance_description: str | None = None
    personality_description: str | None = None
    voice_description: str | None = None
    reference_prompt: str | None = None


class SceneCastRequest(BaseModel):
    """Both fields are always sent: an empty list means the scene shows no character, and null
    that it shows no place. The characters are listed in the order of their pictures.
    """

    model_config = ConfigDict(extra="forbid")

    character_ids: list[MemberId]
    location_id: MemberId | None


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _missing(message: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, message)


def _summary(project: Project, job: Job | None) -> JobSummary | None:
    if job is None:
        return None
    return job_summary(JobRow(job=job, project_name=project.name, scene_index=None))


def _extract_block(project: Project) -> str | None:
    script = project.script_text or ""
    if not script.strip():
        return "Paste the script first."
    words = len(script.split())
    if words > scene_planner.MAX_SCRIPT_WORDS:
        return (
            f"This script has {words:,} words; finding the cast handles up to "
            f"{scene_planner.MAX_SCRIPT_WORDS:,}."
        )
    return None


def _assign_block(state: scenes_service.ScenesState, cast: cast_service.Cast) -> str | None:
    if not state.scenes:
        return "There are no scenes yet. Propose scenes first."
    if state.job is not None and state.job.status in store.ACTIVE_STATUSES:
        return "A scene proposal is in progress. Wait for it to finish."
    if state.stale_reasons:
        return "The scenes are out of date. Propose scenes again first."
    if cast.is_empty:
        return "The project has no characters or places. Find the cast first."
    return None


async def _assets(session: AsyncSession, cast: cast_service.Cast) -> dict[int, Asset]:
    ids = {m.reference_asset_id for _kind, m in cast.members() if m.reference_asset_id is not None}
    if not ids:
        return {}
    statement = select(Asset).where(Asset.id.in_(ids)).execution_options(populate_existing=True)
    return {asset.id: asset for asset in (await session.execute(statement)).scalars()}


def _member_out(
    project: Project,
    kind: str,
    member: cast_service.Member,
    *,
    asset: Asset | None,
    prompt_job: Job | None,
    image_job: Job | None,
    scene_count: int,
) -> CastMemberOut:
    provenance = asset.provenance if asset is not None else None
    is_character = kind == cast_service.CHARACTER
    has_prompt = cast_service.has_prompt(member)
    prompt_source: TextSource | None = None
    if has_prompt:
        prompt_source = "ai" if member.reference_prompt_job_id is not None else "manual"
    return CastMemberOut(
        kind="character" if is_character else "location",
        id=member.id,
        name=member.name,
        appearance_description=member.appearance_description,
        personality_description=getattr(member, "personality_description", None),
        voice_description=getattr(member, "voice_description", None),
        reference_prompt=member.reference_prompt if has_prompt else None,
        reference_prompt_source=prompt_source,
        # The database CHECK constraint keeps this to the allowed values.
        status=typing_cast(MemberStatus, member.status),
        reference_url=media_url(asset.path) if asset is not None else None,
        reference_has_transparency=(
            isinstance(provenance, dict) and provenance.get("role") == "reference_cutout"
        ),
        reference_width=asset.width if asset is not None else None,
        reference_height=asset.height if asset is not None else None,
        prompt_job=_summary(project, prompt_job),
        image_job=_summary(project, image_job),
        prompt_blocked_reason=cast_service.prompt_block(member),
        image_blocked_reason=cast_service.image_block(member),
        scene_count=scene_count,
    )


async def cast_out(session: AsyncSession, project: Project) -> CastOut:
    """What the page shows about the project's cast. Reads the database only."""
    cast = await cast_service.load_cast(session, project.id)
    state = await scenes_service.scenes_state(session, project)
    assets = await _assets(session, cast)
    prompt_jobs = await cast_service.latest_member_jobs(
        session, project.id, cast_service.REFERENCE_PROMPT_JOB
    )
    image_jobs = await cast_service.latest_member_jobs(
        session, project.id, cast_service.REFERENCE_IMAGE_JOB
    )
    extract_job = await store.latest_job(session, project.id, cast_service.EXTRACT_JOB)
    assign_job = await store.latest_job(session, project.id, cast_service.ASSIGN_JOB)

    character_ids = await cast_service.load_character_ids(
        session, [scene.id for scene in state.scenes]
    )

    shown: dict[str, list[CastMemberOut]] = {cast_service.CHARACTER: [], cast_service.LOCATION: []}
    for kind, member in cast.members():
        key = cast_service.member_key(kind, member.id)
        if kind == cast_service.CHARACTER:
            count = sum(1 for scene in state.scenes if member.id in character_ids[scene.id])
        else:
            count = sum(1 for scene in state.scenes if scene.location_id == member.id)
        shown[kind].append(
            _member_out(
                project,
                kind,
                member,
                asset=assets.get(member.reference_asset_id or 0),
                prompt_job=prompt_jobs.get(key),
                image_job=image_jobs.get(key),
                scene_count=count,
            )
        )

    recorded = extract_job.input if extract_job is not None else None
    extracted_from = recorded.get("script_sha256") if isinstance(recorded, dict) else None
    script_changed = (
        not cast.is_empty
        and extract_job is not None
        and extract_job.status == "succeeded"
        and extracted_from != transcript_matching.script_sha256(project.script_text or "")
    )
    return CastOut(
        characters=shown[cast_service.CHARACTER],
        locations=shown[cast_service.LOCATION],
        extract_job=_summary(project, extract_job),
        extract_blocked_reason=_extract_block(project),
        extract_needs_confirmation=not cast.is_empty,
        script_changed=script_changed,
        assign_job=_summary(project, assign_job),
        assign_blocked_reason=_assign_block(state, cast),
        scenes_assigned=sum(1 for scene in state.scenes if scene.cast_assignment_source),
        scene_count=len(state.scenes),
    )


@router.get(
    "/projects/{project_id}/cast",
    response_model=CastOut,
    responses=_NOT_FOUND,
)
async def get_cast(project_id: int, session: SessionDep) -> CastOut:
    """The project's characters and places, and what can be done with them next."""
    project = await load_project(session, project_id)
    return await cast_out(session, project)


# --- Finding the cast and choosing who is in each scene ---------------------------------------


@router.post(
    "/projects/{project_id}/extract-cast",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **_NOT_FOUND,
        **_BLOCKED,
        409: {
            "model": ErrorResponse,
            "description": "The project has a cast already, and the request did not confirm "
            "replacing it.",
        },
    },
)
async def extract_cast(
    project_id: int,
    session: SessionDep,
    body: ExtractCastRequest | None = None,
) -> JobDetail:
    """Starts the job that finds the characters and the places in the script (a paid call to the
    language model), or returns the one already active. It replaces the whole cast when it
    finishes, so it needs `confirm_replace` when there is one.
    """
    flags = body or ExtractCastRequest()
    project = await load_project(session, project_id)
    # Taking the write lock first means what is read below cannot change before the job exists.
    await scenes_service.lock_scenes(session, project.id)

    active = await cast_service.active_jobs(session, project.id, [cast_service.EXTRACT_JOB])
    if active:
        await session.commit()
        return job_detail(JobRow(job=active[0], project_name=project.name, scene_index=None))
    block = _extract_block(project)
    if block is not None:
        raise _unprocessable(block)
    others = await cast_service.active_jobs(session, project.id, _ALL_CAST_JOBS)
    if others:
        raise _unprocessable(
            "Other cast jobs are waiting or running. Wait for them to finish, or cancel them, "
            "before finding the cast again."
        )
    cast = await cast_service.load_cast(session, project.id)
    if not cast.is_empty and not flags.confirm_replace:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The project has a cast already. Finding it again replaces every character and "
            "place, their reference pictures and the choice of who is in each scene. Confirm "
            "to continue.",
        )

    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=cast_service.EXTRACT_JOB,
        provider="llm",
        input={"requested": "extract_cast"},
    )
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=None))


@router.post(
    "/projects/{project_id}/assign-cast",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def assign_cast(project_id: int, session: SessionDep) -> JobDetail:
    """Starts the job that chooses, for every scene, the characters and the one place it shows
    (a paid call to the language model), or returns the one already active. A choice the user
    made by hand is kept.
    """
    project = await load_project(session, project_id)
    await scenes_service.lock_scenes(session, project.id)
    state = await scenes_service.scenes_state(session, project)
    cast = await cast_service.load_cast(session, project.id)
    active = await cast_service.active_jobs(session, project.id, [cast_service.ASSIGN_JOB])
    if active:
        await session.commit()
        return job_detail(JobRow(job=active[0], project_name=project.name, scene_index=None))
    block = _assign_block(state, cast)
    if block is not None:
        raise _unprocessable(block)

    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=cast_service.ASSIGN_JOB,
        provider="llm",
        input={"requested": "assign_cast"},
    )
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=None))


# --- One member --------------------------------------------------------------------------------


async def _load_member(
    session: AsyncSession, project: Project, kind: Kind, member_id: int
) -> cast_service.Member:
    member = (
        await cast_service.get_member(session, project.id, kind, member_id)
        if 1 <= member_id <= _MAX_ID
        else None
    )
    if member is None:
        what = "Character" if kind == cast_service.CHARACTER else "Place"
        raise _missing(f"{what} {member_id} does not exist in this project.")
    return member


@router.patch(
    "/projects/{project_id}/cast/{kind}/{member_id}",
    response_model=CastOut,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def edit_member(
    project_id: int, kind: Kind, member_id: int, body: CastMemberPatch, session: SessionDep
) -> CastOut:
    """Changes the text of one character or place. Answers with the whole cast."""
    project = await load_project(session, project_id)
    member = await _load_member(session, project, kind, member_id)
    sent = body.model_fields_set
    if not sent:
        raise _unprocessable("Send at least one field to change.")
    is_character = kind == cast_service.CHARACTER
    if not is_character and sent & {"personality_description", "voice_description"}:
        raise _unprocessable("A place has no personality or voice.")

    def one_line(value: str | None, limit: int, field: str) -> str | None:
        cleaned = " ".join((value or "").split())
        if len(cleaned) > limit:
            raise _unprocessable(f"The {field} must be at most {limit:,} characters.")
        return cleaned or None

    if "name" in sent:
        name = one_line(body.name, cast_extraction.NAME_MAX_CHARS, "name")
        if name is None:
            raise _unprocessable("The name cannot be blank.")
        cast = await cast_service.load_cast(session, project.id)
        pool = cast.characters if is_character else cast.locations
        if any(
            other.id != member.id and other.name.casefold() == name.casefold() for other in pool
        ):
            raise _unprocessable(f'There is another {kind} called "{name}".')
        member.name = name
    if "appearance_description" in sent:
        appearance = one_line(
            body.appearance_description, cast_extraction.TEXT_MAX_CHARS, "appearance"
        )
        if appearance is None:
            raise _unprocessable("The appearance cannot be blank.")
        member.appearance_description = appearance
    if is_character:
        if "personality_description" in sent:
            member.personality_description = one_line(
                body.personality_description, cast_extraction.NOTE_MAX_CHARS, "personality"
            )
        if "voice_description" in sent:
            member.voice_description = one_line(
                body.voice_description, cast_extraction.NOTE_MAX_CHARS, "voice"
            )
    if "reference_prompt" in sent:
        prompt = one_line(body.reference_prompt, image_generator.MAX_PROMPT_CHARS, "prompt")
        member.reference_prompt = prompt
        # No job wrote it now: it is the user's, and the automatic run keeps it.
        member.reference_prompt_job_id = None
        if member.reference_asset_id is None:
            member.status = "prompted" if prompt else "pending"
    await session.commit()
    return await cast_out(session, project)


@router.post(
    "/projects/{project_id}/cast/{kind}/{member_id}/write-reference-prompt",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def write_reference_prompt(
    project_id: int,
    kind: Kind,
    member_id: int,
    session: SessionDep,
    body: WriteReferencePromptRequest | None = None,
) -> JobDetail:
    """Starts the job that writes the prompt for the member's reference picture (a paid call to
    the language model), replacing the prompt it has, or returns the one already active.
    """
    flags = body or WriteReferencePromptRequest()
    project = await load_project(session, project_id)
    member = await _load_member(session, project, kind, member_id)
    block = cast_service.prompt_block(member)
    if block is not None:
        raise _unprocessable(block)
    return await _start(
        session,
        project,
        job_type=cast_service.REFERENCE_PROMPT_JOB,
        provider="llm",
        kind=kind,
        member_id=member.id,
        extra={"generate_after": flags.generate_after},
    )


@router.post(
    "/projects/{project_id}/cast/{kind}/{member_id}/generate-reference",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def generate_reference(
    project_id: int, kind: Kind, member_id: int, session: SessionDep
) -> JobDetail:
    """Starts the member's reference picture (an image made on the GPU server), or returns the
    job already active. A member with no prompt yet gets its prompt written first (a paid call
    to the language model), and the picture is made as soon as it is.
    """
    project = await load_project(session, project_id)
    member = await _load_member(session, project, kind, member_id)
    if not cast_service.has_prompt(member):
        block = cast_service.prompt_block(member)
        if block is not None:
            raise _unprocessable(block)
        return await _start(
            session,
            project,
            job_type=cast_service.REFERENCE_PROMPT_JOB,
            provider="llm",
            kind=kind,
            member_id=member.id,
            extra={"generate_after": True},
        )
    return await _start(
        session,
        project,
        job_type=cast_service.REFERENCE_IMAGE_JOB,
        provider="gpu",
        kind=kind,
        member_id=member.id,
        extra={},
    )


async def _start(
    session: AsyncSession,
    project: Project,
    *,
    job_type: str,
    provider: str,
    kind: str,
    member_id: int,
    extra: dict[str, bool],
) -> JobDetail:
    """Creates the member's job, unless one of this type is already active for that member."""
    named = {cast_service.KIND_KEY: kind, cast_service.ID_KEY: member_id}
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=job_type,
        provider=provider,
        input={"requested": "click", **named, **extra},
        same_input=named,
    )
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=None))


# --- A scene's choice, by hand -----------------------------------------------------------------


@router.patch(
    "/projects/{project_id}/scenes/{scene_id}/cast",
    response_model=ScenesOut,
    responses={**_NOT_FOUND, **_BLOCKED},
)
async def set_scene_cast(
    project_id: int, scene_id: int, body: SceneCastRequest, session: SessionDep
) -> ScenesOut:
    """Chooses the characters and the place one scene shows (an empty list or null for none).
    The choice is the user's: the AI never overwrites it. Answers with the scenes.
    """
    project = await load_project(session, project_id)
    if not 1 <= scene_id <= _MAX_ID:
        raise _missing(f"Scene {scene_id} does not exist in this project.")
    if len(set(body.character_ids)) != len(body.character_ids):
        raise _unprocessable("A character can be chosen only once for a scene.")
    if len(body.character_ids) > cast_service.MAX_SCENE_CHARACTERS:
        raise _unprocessable(
            f"A scene shows at most {cast_service.MAX_SCENE_CHARACTERS} characters: the image "
            "model takes a limited number of pictures."
        )
    await scenes_service.lock_scenes(session, project.id)
    scene = await session.get(Scene, scene_id, populate_existing=True)
    if scene is None or scene.project_id != project.id:
        await session.rollback()
        raise _missing(f"Scene {scene_id} does not exist in this project.")

    cast = await cast_service.load_cast(session, project.id)
    for character_id in body.character_ids:
        if cast.find(cast_service.CHARACTER, character_id) is None:
            await session.rollback()
            raise _unprocessable(f"Character {character_id} does not exist in this project.")
    if body.location_id is not None and cast.find(cast_service.LOCATION, body.location_id) is None:
        await session.rollback()
        raise _unprocessable(f"Place {body.location_id} does not exist in this project.")

    await cast_service.set_scene_characters(session, scene.id, body.character_ids)
    scene.location_id = body.location_id
    scene.cast_assignment_source = "manual"
    scene.cast_assignment_job_id = None
    await session.commit()
    return await scenes_out(session, project)
