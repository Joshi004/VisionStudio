"""A library character's look: its white-backdrop reference pictures, five angles made from one
master (Phase 25).

**Making a look** (`start_look`):

1. A `write_character_look_prompt` job (`requested: "master"`) writes the master prompt from the
   character's card, with the same profile the project cast's own reference uses
   (`image_prompt_profiles.ACTIVE_CHARACTER_SHEET_PROFILE`).
2. When it finishes (`on_look_prompt_written`, called by the job), four `lab_image` runs with
   different random seeds make the candidates to choose a master from
   (`character_look_candidate` rows, read live from their `lab_run`).
3. `choose_master` cuts the backdrop from the chosen candidate (best effort, as the project
   cast does), stores it as the `front` reference, and starts four `lab_image` **edit** runs
   that turn the master into the other four angles, with a fixed prompt per angle: no language
   model is needed for this, because the turn each angle makes is always the same words.
4. Each angle's picture is cut out the same way once its job finishes
   (`on_angle_image_stored`, called by the job). Once every one of the five angles has a
   picture, the look is `ready`, and becomes the character's current look if it had none.

`redo_angle` starts one more edit run for a single angle (not `front`: that is the look's
master, fixed when it was chosen) and updates its row in place, so the character keeps its old
picture of that angle until the new one is ready.

This module creates rows and jobs, and does the (local, best-effort) backdrop removal. It never
calls the GPU server or the language model itself.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import (
    CharacterLook,
    CharacterLookCandidate,
    CharacterReference,
    Job,
    LabImage,
    LabRun,
    LibraryCharacter,
)
from app.db.session import SessionLocal
from app.jobs import store
from app.jobs.generate_frame import IMAGE_MODE_KEY
from app.services import background_removal, character_library, frame_images, image_lab
from app.services import image_models as image_models_service
from app.services.frame_images import FrameRejected
from app.services.image_lab import LabInputError, QwenEditForm, QwenLabForm, Ref
from app.services.storage import StorageError, StoredFile, get_storage

_logger = logging.getLogger(__name__)

# A standing figure is taller than wide, the same shape the project cast's own character
# reference uses.
MASTER_SHAPE: Final = "2:3"
CANDIDATE_COUNT: Final = 4


class CharacterLookError(ValueError):
    """Something the request gets wrong, or a step that cannot start now. The message is
    meant for the user (HTTP 422).
    """


# A fixed instruction per angle, applied by editing the master picture. Written to match the
# master's own wording (`QWEN_IMAGE_21_CHARACTER_SHEET`): the same character, outfit, pose
# conventions, backdrop and light, turned (or framed) a fixed way. No language model needed:
# the turn each angle makes is always the same words.
_ANGLE_PROMPTS: Final[dict[str, str]] = {
    "three_quarter": (
        "The exact same character as the reference picture: the same face, hair, build, "
        "skin, clothes, colours and plain white studio backdrop, lit the same even, soft way. "
        "Turn the character to a three-quarter angle, the body and the head turned about "
        "forty-five degrees to their own left, in the same relaxed standing pose with the "
        "arms slightly away from the body. The whole figure, head to feet, stays centred in "
        "the frame with a little space around it. Nothing else about the picture changes."
    ),
    "profile": (
        "The exact same character as the reference picture: the same face, hair, build, "
        "skin, clothes, colours and plain white studio backdrop, lit the same even, soft way. "
        "Turn the character to a full side profile, the body and the head turned ninety "
        "degrees to their own left so only the side of the face and the body is seen, in the "
        "same relaxed standing pose with the arms slightly away from the body. The whole "
        "figure, head to feet, stays centred in the frame with a little space around it. "
        "Nothing else about the picture changes."
    ),
    "back": (
        "The exact same character as the reference picture: the same hair, build, clothes, "
        "colours and plain white studio backdrop, lit the same even, soft way. Turn the "
        "character all the way around, so only the back of the head and the body is seen, "
        "facing away from the camera, in the same relaxed standing pose with the arms "
        "slightly away from the body. The whole figure, head to feet, stays centred in the "
        "frame with a little space around it. Nothing else about the picture changes."
    ),
    "face": (
        "The exact same character as the reference picture: the same face, hair, skin, "
        "colours and plain white studio backdrop, lit the same even, soft way. Move in to a "
        "close-up head-and-shoulders portrait, facing the camera directly, the face and the "
        "hair shown clearly from the top of the shoulders to the top of the head, centred in "
        "the frame with a little space around it. Nothing else about the picture changes."
    ),
}


async def _one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def _image_mode(session: AsyncSession) -> image_models_service.ImageMode:
    return image_models_service.resolve_mode(
        await settings_service.get_str(session, IMAGE_MODE_KEY)
    )


# --- Starting a look --------------------------------------------------------------------


async def _next_version(session: AsyncSession, character_id: int) -> int:
    statement = select(func.max(CharacterLook.version)).where(
        CharacterLook.character_id == character_id
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    return (highest or 0) + 1


async def start_look(session: AsyncSession, character_id: int) -> CharacterLook:
    """Starts a new, fresh version of a character's look: a job writes its master prompt
    first. Commits. Raises CharacterLookError.
    """
    character = await session.get(LibraryCharacter, character_id)
    if character is None:
        raise CharacterLookError(f"There is no character {character_id}.")
    version = await _next_version(session, character_id)
    look = CharacterLook(character_id=character_id, version=version, status="writing_prompt")
    session.add(look)
    await session.flush()
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=character_library.PROMPT_JOB,
        provider="llm",
        input={"requested": "master", "character_id": character_id, "look_id": look.id},
        commit=False,
        dedupe=False,
    )
    look.prompt_job_id = job.id
    await session.commit()
    _logger.info("look %d started: character=%d version=%d", look.id, character_id, version)
    return look


async def on_look_prompt_written(job_id: int) -> bool:
    """Called when a `write_character_look_prompt` job finishes. For a look's master prompt
    (`requested: "master"`), saves the prompt and starts the candidate pictures. Returns True
    when they started. Does nothing (returns False) for an audition line's job: it has no
    look to find.
    """
    async with SessionLocal() as session:
        statement = select(CharacterLook).where(CharacterLook.prompt_job_id == job_id)
        look = (await session.execute(statement)).scalars().first()
        if look is None or look.status != "writing_prompt":
            await session.commit()
            return False
        job = await session.get(Job, job_id)
        output = job.output if job is not None and isinstance(job.output, dict) else {}
        prompt = output.get("image_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            look.status = "failed"
            look.error = "The master prompt could not be written."
            await session.commit()
            return False
        look.prompt = prompt.strip()
        try:
            await _start_candidates(session, look)
        except CharacterLookError as exc:
            await session.rollback()
            look = await session.get(CharacterLook, look.id)
            if look is not None:
                look.status = "failed"
                look.error = str(exc)
                await session.commit()
            return False
        look.status = "choosing"
        await session.commit()
    _logger.info("look %d: master prompt saved, %d candidates started", look.id, CANDIDATE_COUNT)
    return True


async def on_look_prompt_failed(job_id: int, error: str) -> None:
    """Called when a `write_character_look_prompt` job for a look's master has failed. Marks
    the look `failed`, so the drawer can show why instead of waiting forever.
    """
    async with SessionLocal() as session:
        statement = select(CharacterLook).where(CharacterLook.prompt_job_id == job_id)
        look = (await session.execute(statement)).scalars().first()
        if look is not None and look.status == "writing_prompt":
            look.status = "failed"
            look.error = error
        await session.commit()


async def _start_candidates(session: AsyncSession, look: CharacterLook) -> None:
    mode = await _image_mode(session)
    prompt = look.prompt or ""
    for _ in range(CANDIDATE_COUNT):
        seed = secrets.randbelow(image_models_service.SEED_LIMIT)
        form = QwenLabForm(
            prompt=prompt, mode=mode, aspect_ratio=MASTER_SHAPE, seed=seed, steps=None
        )
        try:
            run, _job = await image_lab.create_qwen_run(session, form, commit=False)
        except LabInputError as exc:
            raise CharacterLookError(str(exc)) from exc
        session.add(CharacterLookCandidate(look_id=look.id, lab_run_id=run.id))


# --- Choosing the master, and the four angles made from it ------------------------------


async def choose_master(session: AsyncSession, look_id: int, candidate_id: int) -> CharacterLook:
    """Picks one candidate as the look's master picture, makes it the `front` reference, and
    starts the other four angles. Commits. Raises CharacterLookError.
    """
    look = await session.get(CharacterLook, look_id)
    if look is None:
        raise CharacterLookError(f"There is no look {look_id}.")
    if look.status != "choosing":
        raise CharacterLookError("This look is not ready to choose a master picture from yet.")
    candidate = await session.get(CharacterLookCandidate, candidate_id)
    if candidate is None or candidate.look_id != look_id:
        raise CharacterLookError(f"There is no candidate {candidate_id} on this look.")
    if candidate.lab_run_id is None:
        raise CharacterLookError("This candidate has no picture.")
    run = await session.get(LabRun, candidate.lab_run_id)
    if run is None or run.status != "succeeded":
        raise CharacterLookError("This candidate's picture is not ready yet.")
    image_statement = select(LabImage).where(LabImage.run_id == run.id)
    master_image = (await session.execute(image_statement)).scalars().first()
    if master_image is None:
        raise CharacterLookError("This candidate's picture is gone.")

    session.add(CharacterReference(look_id=look.id, angle="front", lab_run_id=run.id))
    try:
        await _start_angles(session, look, master_image.id)
    except CharacterLookError:
        await session.rollback()
        raise
    look.status = "making_angles"
    await session.commit()
    _logger.info(
        "look %d: master chosen: candidate=%d image=%d", look.id, candidate_id, master_image.id
    )
    # Best effort, after the choice is safely saved: the front picture already exists, so its
    # cut-out can be made without waiting for a job.
    await _sync_reference_from_run(run.id)
    return look


async def _start_angles(session: AsyncSession, look: CharacterLook, master_image_id: int) -> None:
    for angle, prompt in _ANGLE_PROMPTS.items():
        run_id = await _start_one_angle(session, prompt, master_image_id)
        session.add(CharacterReference(look_id=look.id, angle=angle, lab_run_id=run_id))


async def _start_one_angle(session: AsyncSession, prompt: str, master_image_id: int) -> int:
    mode = await _image_mode(session)
    form = QwenEditForm(
        prompt=prompt,
        mode=mode,
        # None: the angle follows the master's own shape, instead of asking for one.
        aspect_ratio=None,
        seed=None,
        steps=None,
        references=[Ref(source="lab", id=master_image_id)],
    )
    try:
        run, _job = await image_lab.create_qwen_edit_run(session, form, commit=False)
    except LabInputError as exc:
        raise CharacterLookError(str(exc)) from exc
    return run.id


async def redo_angle(session: AsyncSession, look_id: int, angle: str) -> CharacterReference:
    """Starts one fresh picture for a single angle of a look that has a master picture
    already (`making_angles` or `ready`). Updates the angle's row in place: the character
    keeps its old picture of that angle until the new one is ready. Commits. Raises
    CharacterLookError.
    """
    if angle == "front":
        raise CharacterLookError(
            "The front view is the look's master picture: start a new look to change it."
        )
    if angle not in _ANGLE_PROMPTS:
        raise CharacterLookError(f"{angle} is not a known angle.")
    look = await session.get(CharacterLook, look_id)
    if look is None:
        raise CharacterLookError(f"There is no look {look_id}.")
    if look.status not in ("making_angles", "ready"):
        raise CharacterLookError("This look has no master picture to make angles from yet.")

    front_statement = select(CharacterReference).where(
        CharacterReference.look_id == look_id, CharacterReference.angle == "front"
    )
    front = (await session.execute(front_statement)).scalars().first()
    if front is None or front.lab_image_id is None:
        raise CharacterLookError("This look has no master picture yet.")
    reference_statement = select(CharacterReference).where(
        CharacterReference.look_id == look_id, CharacterReference.angle == angle
    )
    reference = (await session.execute(reference_statement)).scalars().first()
    if reference is None:
        raise CharacterLookError(f"There is no {angle} reference on this look yet.")

    run_id = await _start_one_angle(session, _ANGLE_PROMPTS[angle], front.lab_image_id)
    reference.lab_run_id = run_id
    reference.lab_image_id = None
    reference.cutout_path = None
    reference.cutout_mime = None
    reference.cutout_width = None
    reference.cutout_height = None
    reference.cutout_size_bytes = None
    reference.cutout_sha256 = None
    if look.status == "ready":
        look.status = "making_angles"
    await session.commit()
    _logger.info("look %d: %s angle redone: run=%d", look.id, angle, run_id)
    return reference


# --- Filling in a reference once its picture is stored, and the backdrop cut-out --------


async def on_angle_image_stored(run_id: int) -> None:
    """Called (best effort) once a `lab_image` job has stored its picture. Fills in the
    `character_reference` row this run belongs to, if any; does nothing for a run that is not
    one of a look's angles (an Image lab run, or another character's candidate).
    """
    await _sync_reference_from_run(run_id)


async def _sync_reference_from_run(run_id: int) -> None:
    """Fills in a `character_reference` row once its picture exists: the picture itself
    always, its cut-out on a best-effort basis (the model that removes a backdrop is not
    always available, and the raw picture on its white backdrop is still a usable reference
    either way). Flips the look to `ready`, and sets the character's current look if it had
    none, once every one of its five angles has a picture. Never raises.
    """
    async with SessionLocal() as session:
        reference_statement = select(CharacterReference).where(
            CharacterReference.lab_run_id == run_id
        )
        reference = (await session.execute(reference_statement)).scalars().first()
        if reference is None:
            await session.commit()
            return
        image_statement = select(LabImage).where(LabImage.run_id == run_id)
        image = (await session.execute(image_statement)).scalars().first()
        if image is None:
            await session.commit()
            return
        reference_id, image_id, image_path = reference.id, image.id, image.path
        await session.commit()  # end the read before the (possibly slow) cut-out

    cutout = await _make_cutout(image_path)

    async with SessionLocal() as session:
        reference = await session.get(CharacterReference, reference_id)
        if reference is None:
            await session.commit()
            return
        reference.lab_image_id = image_id
        if cutout is not None:
            reference.cutout_path = cutout.relative_path
            reference.cutout_mime = cutout.mime
            reference.cutout_width = cutout.width
            reference.cutout_height = cutout.height
            reference.cutout_size_bytes = cutout.size_bytes
            reference.cutout_sha256 = cutout.sha256
        await _maybe_mark_ready(session, reference.look_id)
        await session.commit()
    _logger.info(
        "look reference %d filled: run=%d image=%d cutout=%s",
        reference_id,
        run_id,
        image_id,
        cutout is not None,
    )


async def _maybe_mark_ready(session: AsyncSession, look_id: int) -> None:
    look = await session.get(CharacterLook, look_id)
    if look is None or look.status != "making_angles":
        return
    filled_statement = select(CharacterReference.lab_image_id).where(
        CharacterReference.look_id == look_id
    )
    filled = (await session.execute(filled_statement)).scalars().all()
    if len(filled) != len(character_library.ANGLES) or any(value is None for value in filled):
        return
    look.status = "ready"
    # The most recently finished look becomes the one new takes are made from: starting a new
    # look is how an author asks for a different one to be current.
    character = await session.get(LibraryCharacter, look.character_id)
    if character is not None:
        character.current_look_id = look.id


class _Cutout:
    __slots__ = ("relative_path", "mime", "width", "height", "size_bytes", "sha256")

    def __init__(
        self,
        stored: StoredFile,
        mime: str,
        width: int,
        height: int,
        size_bytes: int,
        sha256: str,
    ) -> None:
        self.relative_path = stored.relative_path
        self.mime = mime
        self.width = width
        self.height = height
        self.size_bytes = size_bytes
        self.sha256 = sha256


async def _make_cutout(image_path: str) -> _Cutout | None:
    """The best-effort cut-out of a reference picture: None, with a warning logged, when the
    backdrop could not be removed or the result could not be stored.
    """
    storage = get_storage()
    try:
        png = await frame_images.run_pillow(
            background_removal.remove_background, storage.get_path(image_path)
        )
    except background_removal.BackgroundRemovalError as exc:
        _logger.warning("reference cut-out: backdrop not removed: %s", exc)
        return None
    try:
        temp = await storage.receive(_one_chunk(png), max_bytes=len(png))
        try:
            info = await frame_images.run_pillow(frame_images.inspect_image, temp.path)
            stored = await storage.save_lab(temp, info.ext)
        except BaseException:
            storage.discard(temp)
            raise
    except (StorageError, FrameRejected) as exc:
        _logger.warning("reference cut-out: not stored: %s", exc)
        return None
    return _Cutout(
        stored=stored,
        mime=info.mime,
        width=info.width,
        height=info.height,
        size_bytes=temp.size_bytes,
        sha256=temp.sha256,
    )


# --- Reading looks and references, for the API and for the Create panel ------------------


async def get_look(session: AsyncSession, look_id: int) -> CharacterLook | None:
    return await session.get(CharacterLook, look_id)


async def list_looks(session: AsyncSession, character_id: int) -> list[CharacterLook]:
    """Every look of a character, newest version first."""
    statement = (
        select(CharacterLook)
        .where(CharacterLook.character_id == character_id)
        .order_by(CharacterLook.version.desc())
    )
    return list((await session.execute(statement)).scalars().all())


async def candidates_for(session: AsyncSession, look_id: int) -> list[CharacterLookCandidate]:
    statement = select(CharacterLookCandidate).where(CharacterLookCandidate.look_id == look_id)
    return list((await session.execute(statement)).scalars().all())


async def references_for_look(session: AsyncSession, look_id: int) -> list[CharacterReference]:
    statement = select(CharacterReference).where(CharacterReference.look_id == look_id)
    return list((await session.execute(statement)).scalars().all())


async def references_for_take(
    session: AsyncSession, look_id: int, framing: character_library.Framing
) -> list[Ref]:
    """The look's ready references a take's picture is edited from, for this framing
    (`character_library.references_for`). Raises CharacterLookError when the look has none
    of an angle this framing needs yet.
    """
    wanted = character_library.references_for(framing)
    statement = select(CharacterReference).where(
        CharacterReference.look_id == look_id, CharacterReference.angle.in_(wanted)
    )
    found = {
        reference.angle: reference
        for reference in (await session.execute(statement)).scalars().all()
    }
    missing = [
        angle for angle in wanted if found.get(angle) is None or found[angle].lab_image_id is None
    ]
    if missing:
        raise CharacterLookError(
            f"This look has no picture yet for: {', '.join(missing)}. Wait for it to finish."
        )
    return [Ref(source="lab", id=found[angle].lab_image_id) for angle in wanted]
