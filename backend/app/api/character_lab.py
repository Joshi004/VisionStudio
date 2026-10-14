"""`/api/lab/characters`: the Character lab (Phase 25).

A `library_character` is a reusable, project-independent character: a profile, a set of
white-backdrop reference pictures (a "look"), and an optional voice. It is unrelated to a
project's own cast (`/api/projects/{id}/cast`): the two are never linked.

- `POST /looks` starts a new look: a language model writes the master prompt, then four
  candidate pictures are made to choose from (`POST /looks/{id}/master`). `POST
  /looks/from-picture` does the same from the author's own uploaded picture, the candidates
  then being edits of it. Choosing one starts
  the other four angles by itself. `POST /looks/{id}/angles/{angle}` redoes a single angle.
- The voice is either an existing saved voice, one chosen from a 3-sample audition
  (`POST /{id}/voice/audition-line` writes a line to read, `POST /{id}/voice/auditions` makes
  the samples, `PUT /{id}/voice` chooses one, an existing voice, or mute), or none (a mute
  character).
- `POST /{id}/takes` is the Create panel: one click starts the whole chain (writing the
  prompts, then the picture, the speech and/or the video the output needs). `POST
  /takes/{id}/continue` starts a take's next step by hand; `POST /takes/{id}/rerun` edits a
  prompt and starts what that frees.

Every endpoint that starts a job or a GPU run answers at once with HTTP 202; the dispatcher
does the work and the page polls. The rules are in `services/character_library.py`,
`character_looks.py` and `character_takes.py`. A picture, a speech or a video made here is an
ordinary Image/Voice/Video lab run, so it also appears in those labs' own histories.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal
from typing import cast as typing_cast

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobSummary, job_summary
from app.api.video_lab import (
    AudioInputIn,
    AudioInputOut,
    FirstFrameIn,
    FirstFrameOut,
    audio_input_out,
    frame_out,
    frame_urls_for,
)
from app.db.models import (
    CharacterLook,
    Job,
    LabImage,
    LabRun,
    LabVoiceRun,
    LibraryCharacter,
    Voice,
)
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import character_library, character_looks, character_takes, image_lab
from app.services.character_looks import CharacterLookError
from app.services.character_takes import CharacterTakeError
from app.services.storage import media_url
from app.services.video_lab import AudioRef, FirstFrameRef
from app.services.video_models import LabVideoModel
from app.services.voices import VoiceInputError

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
Id = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]
CharacterId = Annotated[int, Path(ge=1, le=_MAX_ID)]
LookId = Annotated[int, Path(ge=1, le=_MAX_ID)]
TakeId = Annotated[int, Path(ge=1, le=_MAX_ID)]

_NOT_FOUND = {
    404: {"model": ErrorResponse, "description": "No character, look or take has this id."}
}
_INVALID = {422: {"model": ErrorResponse, "description": "The form breaks a rule."}}

EraKind = Literal["present", "past", "future"]
Framing = Literal["close_up", "medium", "wide"]
Orientation = Literal["portrait", "landscape"]
Angle = Literal["front", "three_quarter", "profile", "back", "face"]
LookStatus = Literal["writing_prompt", "choosing", "making_angles", "ready", "failed"]
Output = Literal["image", "audio", "video"]
RunStep = Literal["all", "image", "last_frame", "voice", "video"]
Step = Literal["prompts", "image", "last_frame", "voice", "video"]
# MiniMax's words for how a speech is used by an H3 clip.
AudioMarker = Literal["fully_copy", "partially_copy", "reference", "weak_reference"]
PromptKey = Literal["image_prompt", "last_frame_prompt", "video_prompt", "delivery_instruction"]


def _missing(message: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, message)


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _job_summary(job: Job | None) -> JobSummary | None:
    if job is None:
        return None
    return job_summary(JobRow(job=job, project_name=store.owner_name(job, None), scene_index=None))


# --- The character's profile and voice -----------------------------------------------------


class CharacterIn(BaseModel):
    """The profile step of the drawer. Every field is sent, even when it has not changed."""

    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    age: StrictInt | None = None
    gender: StrictStr = ""
    species: StrictStr
    era_kind: EraKind = "present"
    era_years: StrictInt | None = None
    era_setting: StrictStr | None = None
    appearance: StrictStr
    outfit: StrictStr | None = None
    personality: StrictStr | None = None
    notes: StrictStr | None = None
    has_visible_mouth: StrictBool = True


class CharacterPatch(BaseModel):
    """What to change in a character: any profile field, and/or `archived`. A profile field
    that is left out keeps its current value; the others still need the character's required
    fields to be given somewhere (now, or already saved).
    """

    model_config = ConfigDict(extra="forbid")

    name: StrictStr | None = None
    age: StrictInt | None = None
    gender: StrictStr | None = None
    species: StrictStr | None = None
    era_kind: EraKind | None = None
    era_years: StrictInt | None = None
    era_setting: StrictStr | None = None
    appearance: StrictStr | None = None
    outfit: StrictStr | None = None
    personality: StrictStr | None = None
    notes: StrictStr | None = None
    has_visible_mouth: StrictBool | None = None
    archived: StrictBool | None = None


class VoiceBriefOut(BaseModel):
    id: int
    name: str


class CharacterReferenceOut(BaseModel):
    angle: Angle
    # The picture as made, on its white backdrop. None until it is ready.
    url: str | None
    # The same picture with its backdrop removed, when that could be done. Prefer this for
    # display; `url` is always there once the angle is ready, even without a cutout.
    cutout_url: str | None
    ready: bool


class LookCandidateOut(BaseModel):
    id: int
    url: str | None
    job: JobSummary | None


class LookOut(BaseModel):
    id: int
    created_at: datetime
    version: int
    status: LookStatus
    prompt: str | None
    error: str | None
    prompt_job: JobSummary | None
    # The author's own picture this look was started from. None for a look made from the
    # profile alone.
    reference_url: str | None
    # Only while `status == "choosing"`.
    candidates: list[LookCandidateOut]
    # The angles made so far, in a fixed order. Empty before a master is chosen.
    references: list[CharacterReferenceOut]


class CharacterOut(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    name: str
    age: int | None
    gender: str
    species: str
    era_kind: EraKind
    era_years: int | None
    era_setting: str | None
    appearance: str
    outfit: str | None
    personality: str | None
    notes: str | None
    has_visible_mouth: bool
    voice: VoiceBriefOut | None
    voice_description: str | None
    current_look: LookOut | None
    archived: bool


class CharactersOut(BaseModel):
    characters: list[CharacterOut]
    next_before_id: int | None


class OptionsOut(BaseModel):
    genders: list[str]
    species: list[str]


_ANGLE_ORDER: Final[tuple[Angle, ...]] = character_library.ANGLES


async def _look_out(session: AsyncSession, look: CharacterLook) -> LookOut:
    prompt_job = await session.get(Job, look.prompt_job_id) if look.prompt_job_id else None
    candidates = await character_looks.candidates_for(session, look.id)
    references = await character_looks.references_for_look(session, look.id)

    candidate_run_ids = [c.lab_run_id for c in candidates if c.lab_run_id is not None]
    candidate_runs: dict[int, LabRun] = {}
    if candidate_run_ids:
        found = await session.execute(select(LabRun).where(LabRun.id.in_(candidate_run_ids)))
        candidate_runs = {run.id: run for run in found.scalars()}
    candidate_jobs = await image_lab.jobs_for_runs(session, list(candidate_runs.values()))
    candidate_images = await image_lab.images_by_run(session, candidate_run_ids)

    source_image = (
        await session.get(LabImage, look.reference_image_id) if look.reference_image_id else None
    )

    reference_image_ids = [r.lab_image_id for r in references if r.lab_image_id is not None]
    reference_images: dict[int, LabImage] = {}
    if reference_image_ids:
        found = await session.execute(select(LabImage).where(LabImage.id.in_(reference_image_ids)))
        reference_images = {image.id: image for image in found.scalars()}

    candidates_out = [
        LookCandidateOut(
            id=candidate.id,
            url=(
                media_url(candidate_images[candidate.lab_run_id][0].path)
                if candidate.lab_run_id in candidate_images
                else None
            ),
            job=_job_summary(candidate_jobs.get(candidate.lab_run_id or 0)),
        )
        for candidate in candidates
    ]
    by_angle = {reference.angle: reference for reference in references}
    references_out = []
    for angle in _ANGLE_ORDER:
        reference = by_angle.get(angle)
        if reference is None:
            references_out.append(
                CharacterReferenceOut(angle=angle, url=None, cutout_url=None, ready=False)
            )
            continue
        image = reference_images.get(reference.lab_image_id or 0)
        references_out.append(
            CharacterReferenceOut(
                angle=angle,
                url=media_url(image.path) if image is not None else None,
                cutout_url=media_url(reference.cutout_path) if reference.cutout_path else None,
                ready=reference.lab_image_id is not None,
            )
        )
    return LookOut(
        id=look.id,
        created_at=look.created_at,
        version=look.version,
        status=typing_cast(LookStatus, look.status),
        prompt=look.prompt,
        error=look.error,
        prompt_job=_job_summary(prompt_job),
        reference_url=media_url(source_image.path) if source_image is not None else None,
        candidates=candidates_out,
        references=references_out,
    )


async def _character_out(session: AsyncSession, character: LibraryCharacter) -> CharacterOut:
    voice = await session.get(Voice, character.voice_id) if character.voice_id else None
    current_look = (
        await character_looks.get_look(session, character.current_look_id)
        if character.current_look_id
        else None
    )
    return CharacterOut(
        id=character.id,
        created_at=character.created_at,
        updated_at=character.updated_at,
        name=character.name,
        age=character.age,
        gender=character.gender,
        species=character.species,
        era_kind=typing_cast(EraKind, character.era_kind),
        era_years=character.era_years,
        era_setting=character.era_setting,
        appearance=character.appearance,
        outfit=character.outfit,
        personality=character.personality,
        notes=character.notes,
        has_visible_mouth=character.has_visible_mouth,
        voice=VoiceBriefOut(id=voice.id, name=voice.name) if voice is not None else None,
        voice_description=character.voice_description,
        current_look=await _look_out(session, current_look) if current_look is not None else None,
        archived=character.archived,
    )


def _form(body: CharacterIn) -> character_library.CharacterForm:
    return character_library.CharacterForm(
        name=body.name,
        age=body.age,
        gender=body.gender,
        species=body.species,
        era_kind=body.era_kind,
        era_years=body.era_years,
        era_setting=body.era_setting,
        appearance=body.appearance,
        outfit=body.outfit,
        personality=body.personality,
        notes=body.notes,
        has_visible_mouth=body.has_visible_mouth,
    )


def _merged_form(
    character: LibraryCharacter, body: CharacterPatch
) -> character_library.CharacterForm:
    sent = body.model_fields_set

    def pick(field: str) -> Any:
        return getattr(body, field) if field in sent else getattr(character, field)

    return character_library.CharacterForm(
        name=pick("name"),
        age=pick("age"),
        gender=pick("gender"),
        species=pick("species"),
        era_kind=pick("era_kind"),
        era_years=pick("era_years"),
        era_setting=pick("era_setting"),
        appearance=pick("appearance"),
        outfit=pick("outfit"),
        personality=pick("personality"),
        notes=pick("notes"),
        has_visible_mouth=pick("has_visible_mouth"),
    )


@router.get("/lab/characters", response_model=CharactersOut)
async def list_characters(
    session: SessionDep,
    include_archived: bool = False,
    before_id: Annotated[int | None, Query(ge=1, le=_MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CharactersOut:
    """The newest characters first. Pass the last id you have as `before_id` for the next page."""
    characters = await character_library.list_characters(
        session, include_archived=include_archived, before_id=before_id, limit=limit
    )
    return CharactersOut(
        characters=[await _character_out(session, character) for character in characters],
        next_before_id=characters[-1].id if len(characters) == limit else None,
    )


@router.get("/lab/characters/options", response_model=OptionsOut)
async def get_options(session: SessionDep) -> OptionsOut:
    """The growable gender and species choices: a few suggestions, plus every value a
    character already has.
    """
    return OptionsOut(
        genders=await character_library.gender_options(session),
        species=await character_library.species_options(session),
    )


@router.post(
    "/lab/characters",
    response_model=CharacterOut,
    status_code=status.HTTP_201_CREATED,
    responses=_INVALID,
)
async def create_character(body: CharacterIn, session: SessionDep) -> CharacterOut:
    """Saves a new character's profile. Its look and voice are added afterwards."""
    try:
        character = await character_library.create_character(session, _form(body))
    except character_library.CharacterLibraryError as exc:
        raise _unprocessable(str(exc)) from exc
    return await _character_out(session, character)


@router.get("/lab/characters/{character_id}", response_model=CharacterOut, responses=_NOT_FOUND)
async def get_character(character_id: CharacterId, session: SessionDep) -> CharacterOut:
    character = await character_library.get_character(session, character_id)
    if character is None:
        raise _missing(f"There is no character {character_id}.")
    return await _character_out(session, character)


@router.patch(
    "/lab/characters/{character_id}",
    response_model=CharacterOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def edit_character(
    character_id: CharacterId, body: CharacterPatch, session: SessionDep
) -> CharacterOut:
    """Changes the profile, archives or unarchives a character, or both at once."""
    character = await character_library.get_character(session, character_id)
    if character is None:
        raise _missing(f"There is no character {character_id}.")
    sent = body.model_fields_set
    if not sent:
        raise _unprocessable("Send at least one field to change.")
    try:
        if sent - {"archived"}:
            character = await character_library.update_character(
                session, character_id, _merged_form(character, body)
            )
        if "archived" in sent and body.archived is not None:
            character = await character_library.set_archived(session, character_id, body.archived)
    except character_library.CharacterLibraryError as exc:
        raise _unprocessable(str(exc)) from exc
    return await _character_out(session, character)


# --- A character's look -------------------------------------------------------------------


@router.post(
    "/lab/characters/{character_id}/looks",
    response_model=LookOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def start_look(character_id: CharacterId, session: SessionDep) -> LookOut:
    """Starts a fresh look: a language model writes the master prompt, then four candidate
    pictures are made to choose from.
    """
    try:
        look = await character_looks.start_look(session, character_id)
    except CharacterLookError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return await _look_out(session, look)


class LookFromPictureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A lab image: upload the picture first (`POST /api/lab/images/uploads`).
    image_id: Id


@router.post(
    "/lab/characters/{character_id}/looks/from-picture",
    response_model=LookOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def start_look_from_picture(
    character_id: CharacterId, body: LookFromPictureIn, session: SessionDep
) -> LookOut:
    """Starts a fresh look from the author's own picture of the character: a language model
    writes the master prompt for it, then four candidates are made by editing that picture.
    The picture decides the face, hair, skin and build; the profile's outfit is applied on top.
    """
    try:
        look = await character_looks.start_look(session, character_id, body.image_id)
    except CharacterLookError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return await _look_out(session, look)


@router.get("/lab/characters/{character_id}/looks", response_model=list[LookOut])
async def list_looks(character_id: CharacterId, session: SessionDep) -> list[LookOut]:
    """Every look of this character, newest version first."""
    looks = await character_looks.list_looks(session, character_id)
    return [await _look_out(session, look) for look in looks]


@router.get("/lab/characters/looks/{look_id}", response_model=LookOut, responses=_NOT_FOUND)
async def get_look(look_id: LookId, session: SessionDep) -> LookOut:
    look = await character_looks.get_look(session, look_id)
    if look is None:
        raise _missing(f"There is no look {look_id}.")
    return await _look_out(session, look)


class ChooseMasterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: Id


@router.post(
    "/lab/characters/looks/{look_id}/master",
    response_model=LookOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def choose_master(look_id: LookId, body: ChooseMasterIn, session: SessionDep) -> LookOut:
    """Picks one candidate as the look's master picture and starts the other four angles."""
    try:
        look = await character_looks.choose_master(session, look_id, body.candidate_id)
    except CharacterLookError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return await _look_out(session, look)


@router.post(
    "/lab/characters/looks/{look_id}/angles/{angle}",
    response_model=LookOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def redo_angle(look_id: LookId, angle: Angle, session: SessionDep) -> LookOut:
    """Starts one more picture for a single angle. The character keeps its old one until the
    new one is ready.
    """
    try:
        await character_looks.redo_angle(session, look_id, angle)
    except CharacterLookError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    look = await character_looks.get_look(session, look_id)
    if look is None:
        raise _missing(f"There is no look {look_id}.")
    return await _look_out(session, look)


# --- A character's voice -------------------------------------------------------------------


class VoiceDescriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_description: StrictStr | None = None


@router.put(
    "/lab/characters/{character_id}/voice/description",
    response_model=CharacterOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def set_voice_description(
    character_id: CharacterId, body: VoiceDescriptionIn, session: SessionDep
) -> CharacterOut:
    """Sets what the audition's samples are made from."""
    try:
        character = await character_library.set_voice_description(
            session, character_id, body.voice_description
        )
    except character_library.CharacterLibraryError as exc:
        raise _unprocessable(str(exc)) from exc
    return await _character_out(session, character)


@router.post(
    "/lab/characters/{character_id}/voice/audition-line",
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def start_audition_line(character_id: CharacterId, session: SessionDep) -> JobSummary:
    """Starts the job that writes a short line to read aloud while auditioning a voice."""
    try:
        job = await character_library.start_audition_line(session, character_id)
    except character_library.CharacterLibraryError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    summary = _job_summary(job)
    assert summary is not None  # the job was just created
    return summary


class AuditionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line: StrictStr


class AuditionSampleOut(BaseModel):
    voice_run_id: int
    job: JobSummary | None
    url: str | None


@router.post(
    "/lab/characters/{character_id}/voice/auditions",
    response_model=list[AuditionSampleOut],
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def start_auditions(
    character_id: CharacterId, body: AuditionsIn, session: SessionDep
) -> list[AuditionSampleOut]:
    """Starts 3 design-mode samples of this line, read in the voice description, to choose a
    voice from.
    """
    try:
        rows = await character_library.start_auditions(session, character_id, body.line)
    except character_library.CharacterLibraryError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return [
        AuditionSampleOut(
            voice_run_id=row.run.id,
            job=_job_summary(row.job),
            url=media_url(row.run.path) if row.run.path is not None else None,
        )
        for row in rows
    ]


class VoiceChoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["existing", "audition", "none"]
    # source == "existing": the saved voice to use.
    voice_id: Id | None = None
    # source == "audition": the sample to save, and the name to save it under.
    voice_run_id: Id | None = None
    name: StrictStr | None = None


@router.put(
    "/lab/characters/{character_id}/voice",
    response_model=CharacterOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def set_voice(
    character_id: CharacterId, body: VoiceChoiceIn, session: SessionDep
) -> CharacterOut:
    """Sets the character's voice: an existing saved voice, an audition sample (saved as a
    named voice), or none (mute).
    """
    try:
        if body.source == "none":
            character = await character_library.set_voice(session, character_id, None)
        elif body.source == "existing":
            if body.voice_id is None:
                raise _unprocessable("Give the voice to use.")
            character = await character_library.set_voice(session, character_id, body.voice_id)
        else:
            if body.voice_run_id is None or not body.name or not body.name.strip():
                raise _unprocessable("Give the audition sample and a name for the voice.")
            character = await character_library.choose_audition(
                session, character_id, body.voice_run_id, body.name
            )
    except character_library.CharacterLibraryError as exc:
        raise _unprocessable(str(exc)) from exc
    except VoiceInputError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return await _character_out(session, character)


# --- Takes: the Create panel ----------------------------------------------------------------


class TakeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # "all": run the whole chain by itself. "image"/"last_frame"/"voice"/"video": start only that
    # one step.
    run: RunStep = "all"
    output: Output
    action: StrictStr | None = None
    dialogue: StrictStr | None = None
    framing: Framing = "medium"
    orientation: Orientation = "portrait"
    video_model: LabVideoModel | None = None
    lip_sync: StrictBool = False
    # Video with no dialogue only (MiniMax H3: also with dialogue when the clip does not match
    # the speech). Left out: 5 seconds.
    duration_s: Annotated[float, Field(allow_inf_nan=False, gt=0)] | None = None
    seed: StrictInt | None = None
    negative_prompt: StrictStr | None = None
    # --- MiniMax H3 only (the other models refuse these) ---
    # Pick the first frame instead of having one made.
    first_frame: FirstFrameIn | None = None
    # Make a last frame by editing the first frame. Not together with `last_frame`.
    make_last_frame: StrictBool = False
    # Pick the last frame instead.
    last_frame: FirstFrameIn | None = None
    # Pick the speech instead of having one made (a take with dialogue).
    audio: AudioInputIn | None = None
    # How the speech is used (a take with dialogue).
    audio_marker: AudioMarker = "reference"
    # True: the clip is as long as the speech, and `duration_s` is ignored.
    match_audio_duration: StrictBool = True
    # 4 to 100 denoising steps. Left out: the pipeline's own default.
    num_inference_steps: StrictInt | None = None
    # Also send the look's pictures as references after the frames (a take with dialogue).
    identity_refs: StrictBool = False


class RerunIn(BaseModel):
    """Edited prompt text(s). Only a text this take needs can be sent; sending one clears what
    was made from it, so the take's next step makes it again.
    """

    model_config = ConfigDict(extra="forbid")

    image_prompt: StrictStr | None = None
    last_frame_prompt: StrictStr | None = None
    video_prompt: StrictStr | None = None
    delivery_instruction: StrictStr | None = None


class TakeMediaOut(BaseModel):
    run_id: int
    url: str | None
    job: JobSummary | None


class TakeAudioOut(BaseModel):
    """The speech a take's clip hears: `{source, id}` as the Video lab names it, with its length
    (2 to 15 seconds is what MiniMax H3 takes).
    """

    audio: AudioInputOut
    duration_s: float | None


class TakeOut(BaseModel):
    id: int
    created_at: datetime
    character_id: int
    look_id: int | None
    output: Output
    action: str | None
    dialogue: str | None
    video_model: LabVideoModel | None
    lip_sync: bool
    framing: Framing
    orientation: Orientation
    seed: int | None
    duration_s: float | None
    negative_prompt: str | None
    # MiniMax H3 video takes only (else None, or off).
    audio_marker: AudioMarker | None
    match_audio_duration: bool
    num_inference_steps: int | None
    identity_refs: bool
    make_last_frame: bool
    prompts: dict[str, Any]
    # The texts this take uses, in the order the page shows them.
    prompt_keys: list[PromptKey]
    last_error: str | None
    # The steps this take has, in the order they run (a picture or a speech the author picked is
    # not a step). The step running now, if any, and the step that starts next (None once the
    # take is done).
    steps: list[Step]
    active_step: Step | None
    next_step: Step | None
    prompt_job: JobSummary | None
    image: TakeMediaOut | None
    # The last frame the take made (None when it picked one, or has none).
    last_frame: TakeMediaOut | None
    voice: TakeMediaOut | None
    video: TakeMediaOut | None
    # What a new take can start from, whether the take picked it or made it: the first frame,
    # the last frame (None when it has none) and the speech (None before it exists). They are
    # None until the picture or the speech is ready.
    first_frame_ref: FirstFrameOut | None
    last_frame_ref: FirstFrameOut | None
    audio_ref: TakeAudioOut | None


class TakesOut(BaseModel):
    takes: list[TakeOut]
    next_before_id: int | None


async def _audio_durations(
    session: AsyncSession, audio: list[AudioInputOut]
) -> dict[tuple[str, int], float | None]:
    """The length of each speech named, keyed by (source, id). A speech that is gone, or not
    made yet, has no length.
    """
    durations: dict[tuple[str, int], float | None] = {}
    run_ids = {ref.id for ref in audio if ref.source == "voice_run"}
    voice_ids = {ref.id for ref in audio if ref.source == "voice"}
    if run_ids:
        found_runs = await session.execute(select(LabVoiceRun).where(LabVoiceRun.id.in_(run_ids)))
        for run in found_runs.scalars():
            durations[("voice_run", run.id)] = run.duration_s
    if voice_ids:
        found_voices = await session.execute(select(Voice).where(Voice.id.in_(voice_ids)))
        for voice in found_voices.scalars():
            durations[("voice", voice.id)] = voice.duration_s
    return durations


def _row_audio(row: character_takes.TakeRow) -> AudioInputOut | None:
    """The speech the take's clip hears: the one the take picked, or the one it made (once it
    has a file).
    """
    picked = audio_input_out(row.take.audio_input)
    if picked is not None:
        return picked
    if row.voice is not None and row.voice.run.path is not None:
        return AudioInputOut(source="voice_run", id=row.voice.run.id)
    return None


async def _takes_out(session: AsyncSession, rows: list[character_takes.TakeRow]) -> list[TakeOut]:
    made_run_ids = [
        run_id
        for row in rows
        for run_id in (row.take.image_run_id, row.take.last_frame_run_id)
        if run_id is not None
    ]
    made_images = await image_lab.images_by_run(session, made_run_ids)

    def made_image(run_id: int | None) -> LabImage | None:
        found = made_images.get(run_id) if run_id is not None else None
        return found[0] if found else None

    def made_media(run_id: int | None, job: Job | None) -> TakeMediaOut | None:
        """A first frame or a last frame the take made, with its job."""
        if run_id is None:
            return None
        image = made_image(run_id)
        return TakeMediaOut(
            run_id=run_id,
            url=media_url(image.path) if image is not None else None,
            job=_job_summary(job),
        )

    # Thumbnails of the pictures a take picked (`{source, id}`) and of the ones it made.
    frame_urls = await frame_urls_for(
        session, [frame for row in rows for frame in (row.take.first_frame, row.take.last_frame)]
    )
    for found in made_images.values():
        if found:
            frame_urls[("lab", found[0].id)] = media_url(found[0].path)

    def frame_ref(picked: Any, run_id: int | None) -> FirstFrameOut | None:
        """The picture a new take could start from: the one the take picked, or the one it made
        (None while it is not made).
        """
        if picked is not None:
            return frame_out(picked, frame_urls)
        image = made_image(run_id)
        return None if image is None else frame_out({"source": "lab", "id": image.id}, frame_urls)

    row_audio = {row.take.id: _row_audio(row) for row in rows}
    durations = await _audio_durations(
        session, [audio for audio in row_audio.values() if audio is not None]
    )

    out = []
    for row in rows:
        take = row.take
        state = row.state
        audio = row_audio[take.id]
        voice = (
            TakeMediaOut(
                run_id=take.voice_run_id,
                url=media_url(row.voice.run.path) if row.voice and row.voice.run.path else None,
                job=_job_summary(row.voice.job) if row.voice else None,
            )
            if take.voice_run_id is not None
            else None
        )
        video = (
            TakeMediaOut(
                run_id=take.video_run_id,
                url=media_url(row.video.run.path) if row.video and row.video.run.path else None,
                job=_job_summary(row.video.job) if row.video else None,
            )
            if take.video_run_id is not None
            else None
        )
        out.append(
            TakeOut(
                id=take.id,
                created_at=take.created_at,
                character_id=take.character_id,
                look_id=take.look_id,
                output=typing_cast(Output, take.output),
                action=take.action,
                dialogue=take.dialogue,
                video_model=(
                    typing_cast(LabVideoModel, take.video_model) if take.video_model else None
                ),
                lip_sync=take.lip_sync,
                framing=typing_cast(Framing, take.framing),
                orientation=typing_cast(Orientation, take.orientation),
                seed=take.seed,
                duration_s=take.duration_s,
                negative_prompt=take.negative_prompt,
                audio_marker=(
                    typing_cast(AudioMarker, take.audio_marker) if take.audio_marker else None
                ),
                match_audio_duration=take.match_audio_duration,
                num_inference_steps=take.num_inference_steps,
                identity_refs=take.identity_refs,
                make_last_frame=take.make_last_frame,
                prompts=take.prompts if isinstance(take.prompts, dict) else {},
                prompt_keys=typing_cast(list[PromptKey], character_takes.prompt_keys(take)),
                last_error=take.last_error,
                steps=character_takes.step_order(take),
                active_step=state.active,
                next_step=character_takes.next_step(take, state),
                prompt_job=_job_summary(row.prompt_job),
                image=made_media(take.image_run_id, row.image_job),
                last_frame=made_media(take.last_frame_run_id, row.last_frame_job),
                voice=voice,
                video=video,
                first_frame_ref=frame_ref(take.first_frame, take.image_run_id),
                last_frame_ref=frame_ref(take.last_frame, take.last_frame_run_id),
                audio_ref=(
                    None
                    if audio is None
                    else TakeAudioOut(
                        audio=audio, duration_s=durations.get((audio.source, audio.id))
                    )
                ),
            )
        )
    return out


def _frame_ref(frame: FirstFrameIn | None) -> FirstFrameRef | None:
    return None if frame is None else FirstFrameRef(source=frame.source, id=frame.id)


@router.post(
    "/lab/characters/{character_id}/takes",
    response_model=TakeOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def create_take(character_id: CharacterId, body: TakeIn, session: SessionDep) -> TakeOut:
    """The Create panel: checks the form, saves a take and starts its first step (or, with
    `run` set to one step, only that step). A MiniMax H3 video take can also name a first
    frame, a last frame and a speech to use instead of having them made.
    """
    form = character_takes.TakeForm(
        character_id=character_id,
        run=body.run,
        output=body.output,
        action=body.action,
        dialogue=body.dialogue,
        framing=body.framing,
        orientation=body.orientation,
        video_model=body.video_model,
        lip_sync=body.lip_sync,
        duration_s=body.duration_s,
        seed=body.seed,
        negative_prompt=body.negative_prompt,
        first_frame=_frame_ref(body.first_frame),
        make_last_frame=body.make_last_frame,
        last_frame=_frame_ref(body.last_frame),
        audio=None if body.audio is None else AudioRef(source=body.audio.source, id=body.audio.id),
        audio_marker=body.audio_marker,
        match_audio_duration=body.match_audio_duration,
        num_inference_steps=body.num_inference_steps,
        identity_refs=body.identity_refs,
    )
    try:
        row = await character_takes.create_take(session, form)
    except CharacterTakeError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return (await _takes_out(session, [row]))[0]


@router.get("/lab/characters/{character_id}/takes", response_model=TakesOut)
async def list_takes(
    character_id: CharacterId,
    session: SessionDep,
    before_id: Annotated[int | None, Query(ge=1, le=_MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> TakesOut:
    """The character's gallery: the newest takes first. Pass the last id you have as
    `before_id` for the next page.
    """
    rows = await character_takes.list_takes(session, character_id, before_id, limit)
    return TakesOut(
        takes=await _takes_out(session, rows),
        next_before_id=rows[-1].take.id if len(rows) == limit else None,
    )


@router.get("/lab/characters/takes/{take_id}", response_model=TakeOut, responses=_NOT_FOUND)
async def get_take(take_id: TakeId, session: SessionDep) -> TakeOut:
    row = await character_takes.get_take(session, take_id)
    if row is None:
        raise _missing(f"There is no take {take_id}.")
    return (await _takes_out(session, [row]))[0]


@router.post(
    "/lab/characters/takes/{take_id}/continue",
    response_model=TakeOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def continue_take(take_id: TakeId, session: SessionDep) -> TakeOut:
    """Starts the take's next step by hand."""
    try:
        row = await character_takes.continue_take(session, take_id)
    except CharacterTakeError as exc:
        raise _unprocessable(str(exc)) from exc
    if row is None:
        raise _missing(f"There is no take {take_id}.")
    dispatcher.nudge()
    return (await _takes_out(session, [row]))[0]


@router.post(
    "/lab/characters/takes/{take_id}/rerun",
    response_model=TakeOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def rerun_take(take_id: TakeId, body: RerunIn, session: SessionDep) -> TakeOut:
    """Edits one or more of the take's prompts and starts what that frees."""
    try:
        row = await character_takes.rerun(
            session,
            take_id,
            image_prompt=body.image_prompt,
            last_frame_prompt=body.last_frame_prompt,
            video_prompt=body.video_prompt,
            delivery_instruction=body.delivery_instruction,
        )
    except CharacterTakeError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return (await _takes_out(session, [row]))[0]
