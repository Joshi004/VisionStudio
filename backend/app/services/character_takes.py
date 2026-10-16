"""A take: one thing made from a library character — a picture, a piece of speech, or a clip,
with or without dialogue (Phase 25).

A take is made in up to five steps, each a job or run the other labs already know how to run,
exactly as a take of the old Talking character lab was:

1. **prompts**: a `write_character_take_prompt` job (a paid call to the language model) writes
   exactly the texts the take's remaining steps need (`character_take_prompt_writer.needed_keys`):
   an image prompt, a last-frame prompt, a video prompt, a delivery instruction, or several of
   these together. The author may edit any of them before the next step runs.
2. **image**: for an "image" take, or a "video" take's first frame, a `lab_image` **edit** run
   makes the picture from the character's current look's reference pictures
   (`character_looks.references_for_take`, chosen by the take's framing).
3. **last_frame** (MiniMax H3 video takes that ask for it): a second `lab_image` edit run makes
   the clip's last frame by editing the first frame.
4. **voice**: for an "audio" take, or a "video" take with dialogue, a Voice lab run reads the
   dialogue in the character's saved voice, steered by the delivery instruction (`direction`
   mode: never a fresh "design" voice, so the character sounds the same in every take).
5. **video**: for a "video" take, a Video lab run makes the clip from the picture. With LTX and
   dialogue, it is LTX's audio-to-video endpoint, lip-synced when asked for; without dialogue,
   the model's plain image-to-video. With MiniMax H3 and dialogue, it is H3's reference
   endpoint: the first frame is `<Picture 1>`, the last frame (if any) `<Picture 2>`, the speech
   `<Audio 1>`, and the author's audio marker says how the speech is used. Without dialogue, it
   is H3's plain endpoint with the first frame and the last frame (if any).

A MiniMax H3 take can use a first frame, a last frame and a speech the author picked instead of
having them made (`first_frame`, `last_frame`, `audio_input`): the step that would make them is
skipped, and so is the text only that step needs. That is how one request is tried again with
another marker or seed without paying for the pictures or the speech twice.

A take made with `run="all"` continues by itself: when a step's job or run finishes
(`on_prompts_written`, `on_image_stored`, `on_voice_finished`, called by the jobs that drive
those steps), the next step is started. Every step is a paid GPU or model call, so a step
starts only from a click: either the one that made the take, or "continue"
(`continue_take`), which starts one step. If a step cannot be started after the step before it
paid off, the reason is kept on the take (`last_error`) and the chain stops.

This module creates rows and jobs. It never calls the GPU server or the language model.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import (
    CharacterTake,
    Job,
    LabImage,
    LabRun,
    LabVoiceRun,
    LibraryCharacter,
    Voice,
)
from app.db.session import SessionLocal
from app.jobs import store
from app.jobs.generate_frame import IMAGE_MODE_KEY
from app.services import (
    character_library,
    character_looks,
    image_lab,
    video_lab,
    video_models,
    voice_lab,
)
from app.services import character_take_prompt_writer as writer
from app.services import image_models as image_models_service
from app.services.character_looks import CharacterLookError
from app.services.image_lab import LabInputError, QwenEditForm, Ref
from app.services.video_lab import (
    AudioRef,
    FirstFrameRef,
    H3ReferenceForm,
    LabVideoForm,
    LabVideoInputError,
    LipSyncForm,
)
from app.services.video_models import DEFAULT_MODEL, LabVideoModel, VideoModel, is_video_model
from app.services.voice_lab import VoiceLabForm, VoiceLabInputError

_logger = logging.getLogger(__name__)

TAKE_PROMPT_JOB: Final = "write_character_take_prompt"

Output = writer.Output
AudioMarker = writer.AudioMarker
AUDIO_MARKERS = writer.AUDIO_MARKERS
Orientation = Literal["portrait", "landscape"]
ORIENTATIONS: Final[tuple[Orientation, ...]] = ("portrait", "landscape")
Step = Literal["prompts", "image", "last_frame", "voice", "video"]
RunStep = Literal["all", "image", "last_frame", "voice", "video"]
RUN_STEPS: Final[tuple[RunStep, ...]] = ("all", "image", "last_frame", "voice", "video")

STEP_LABELS: Final[dict[str, str]] = {
    "prompts": "prompt writing",
    "image": "picture",
    "last_frame": "last frame",
    "voice": "speech",
    "video": "video",
}
_ACTIVE: Final = ("queued", "running")
LIST_LIMIT_MAX: Final = 50
DEFAULT_SILENT_DURATION_S: Final = 5.0

# Which generated shape a take's picture is made at, from its framing and orientation.
_ASPECT_RATIO: Final[dict[tuple[str, str], str]] = {
    ("close_up", "portrait"): "3:4",
    ("close_up", "landscape"): "4:3",
    ("medium", "portrait"): "2:3",
    ("medium", "landscape"): "3:2",
    ("wide", "portrait"): "9:16",
    ("wide", "landscape"): "16:9",
}
# A MiniMax H3 clip is 768 x 1344 or 1344 x 768 whatever the framing is (the framing only
# chooses which of the character's pictures the picture is edited from), so its first frame is
# made at the nearest shape the image model offers: 9:16 or 16:9.
_H3_ASPECT_RATIO: Final[dict[str, str]] = {"portrait": "9:16", "landscape": "16:9"}
# How much of a reused speech's words an error message quotes.
_QUOTE_CHARS: Final = 200


class CharacterTakeError(ValueError):
    """Something the form gets wrong, or a step that cannot start now. The message is meant
    for the user (HTTP 422).
    """


@dataclass(frozen=True)
class TakeForm:
    """What a click on "Create" (the Create panel) sends."""

    character_id: int
    run: RunStep
    output: Output
    # Ignored for "audio".
    action: str | None
    # None: no dialogue. Required for "audio". Optional for "video" (a silent clip without it).
    dialogue: str | None
    # Image and video only.
    framing: character_library.Framing
    orientation: Orientation
    # Video only.
    video_model: LabVideoModel | None
    lip_sync: bool
    # Video, with no dialogue only (with MiniMax H3 also with dialogue when the clip does not
    # match the speech): the clip's length. With LTX and dialogue it follows the speech.
    duration_s: float | None
    seed: int | None
    negative_prompt: str | None
    # MiniMax H3 video takes only. The frames and the speech can be picked instead of made.
    first_frame: FirstFrameRef | None = None
    # Make the last frame by editing the first frame. Not together with `last_frame`.
    make_last_frame: bool = False
    last_frame: FirstFrameRef | None = None
    audio: AudioRef | None = None
    # How the speech is used. Only a take with dialogue.
    audio_marker: AudioMarker = writer.DEFAULT_MARKER
    # True: the clip is as long as the speech. Only a take with dialogue.
    match_audio_duration: bool = True
    num_inference_steps: int | None = None
    # Also send the look's pictures as references after the frames. Only a take with dialogue.
    identity_refs: bool = False


@dataclass(frozen=True)
class TakeState:
    """Where a take is: the rows and jobs of its steps (None where a step has not run)."""

    prompt_job: Job | None
    image_run: LabRun | None
    image_job: Job | None
    voice_run: voice_lab.RunRow | None
    video_run: video_lab.RunRow | None
    last_frame_run: LabRun | None = None
    last_frame_job: Job | None = None

    @property
    def active(self) -> Step | None:
        """The step that is waiting or running now, if any."""
        if _is_active(self.prompt_job):
            return "prompts"
        if _is_active(self.image_job):
            return "image"
        if _is_active(self.last_frame_job):
            return "last_frame"
        if self.voice_run is not None and _is_active(self.voice_run.job):
            return "voice"
        if self.video_run is not None and _is_active(self.video_run.job):
            return "video"
        return None

    @property
    def image_done(self) -> bool:
        return self.image_run is not None and self.image_run.status == "succeeded"

    @property
    def last_frame_done(self) -> bool:
        return self.last_frame_run is not None and self.last_frame_run.status == "succeeded"

    @property
    def voice_done(self) -> bool:
        return self.voice_run is not None and self.voice_run.run.path is not None

    @property
    def video_done(self) -> bool:
        return self.video_run is not None and self.video_run.run.path is not None


@dataclass(frozen=True)
class TakeRow:
    """A take with the rows and jobs of its steps."""

    take: CharacterTake
    character: LibraryCharacter | None
    prompt_job: Job | None
    image_run: LabRun | None
    image_job: Job | None
    voice: voice_lab.RunRow | None
    video: video_lab.RunRow | None
    last_frame_run: LabRun | None = None
    last_frame_job: Job | None = None

    @property
    def state(self) -> TakeState:
        return TakeState(
            prompt_job=self.prompt_job,
            image_run=self.image_run,
            image_job=self.image_job,
            voice_run=self.voice,
            video_run=self.video,
            last_frame_run=self.last_frame_run,
            last_frame_job=self.last_frame_job,
        )


# --- Small helpers -----------------------------------------------------------------------


def _is_active(job: Job | None) -> bool:
    return job is not None and job.status in _ACTIVE


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _clean(value: str | None) -> str | None:
    return None if _blank(value) else value.strip()


def _too_long(value: str | None, limit: int, what: str) -> None:
    if value is not None and len(value) > limit:
        raise CharacterTakeError(f"The {what} must be at most {limit:,} characters.")


async def _fresh(session: AsyncSession, model: Any, object_id: int | None) -> Any:
    """The row of `model` with this id as the database has it now, or None."""
    if object_id is None:
        return None
    statement = select(model).where(model.id == object_id).execution_options(populate_existing=True)
    return (await session.execute(statement)).scalars().first()


async def _state(session: AsyncSession, take: CharacterTake) -> TakeState:
    image_run = await _fresh(session, LabRun, take.image_run_id)
    image_job = await _fresh(session, Job, image_run.job_id if image_run else None)
    last_frame_run = await _fresh(session, LabRun, take.last_frame_run_id)
    last_frame_job = await _fresh(session, Job, last_frame_run.job_id if last_frame_run else None)
    voice_run = await voice_lab.get_run(session, take.voice_run_id) if take.voice_run_id else None
    video_run = await video_lab.get_run(session, take.video_run_id) if take.video_run_id else None
    return TakeState(
        prompt_job=await _fresh(session, Job, take.prompt_job_id),
        image_run=image_run,
        image_job=image_job,
        voice_run=voice_run,
        video_run=video_run,
        last_frame_run=last_frame_run,
        last_frame_job=last_frame_job,
    )


async def _image_mode(session: AsyncSession) -> image_models_service.ImageMode:
    return image_models_service.resolve_mode(
        await settings_service.get_str(session, IMAGE_MODE_KEY)
    )


# --- Which step is next ------------------------------------------------------------------


def is_h3(take: CharacterTake) -> bool:
    """Does this take make its clip with MiniMax H3?"""
    return take.output == "video" and take.video_model == video_models.H3_MODEL


def _target(take: CharacterTake) -> writer.Target:
    """What the take's video prompt is written for: LTX, MiniMax H3's reference endpoint (it
    has dialogue, so there is a speech to hear) or H3's plain endpoint (it has none).
    """
    if not is_h3(take):
        return "ltx"
    return "h3_reference" if not _blank(take.dialogue) else "h3_generate"


def _makes_last_frame(take: CharacterTake) -> bool:
    """Does the take make its own last frame (by editing its first frame)? A last frame the
    author picked is not made.
    """
    return is_h3(take) and take.make_last_frame and take.last_frame is None


def _has_last_frame(take: CharacterTake) -> bool:
    """Does the clip have a last frame at all, made or picked?"""
    return is_h3(take) and (take.make_last_frame or take.last_frame is not None)


def _first_frame_ready(take: CharacterTake, state: TakeState) -> bool:
    """Is the first frame there: picked by the author, or made and finished?"""
    return take.first_frame is not None or state.image_done


def _needed(take: CharacterTake) -> frozenset[str]:
    """The texts the take's steps need (`writer.needed_keys`), given what the author picked."""
    return writer.needed_keys(
        take.output,
        take.dialogue,
        first_frame_given=take.first_frame is not None,
        audio_given=take.audio_input is not None,
        last_frame=_makes_last_frame(take),
    )


def step_order(take: CharacterTake) -> list[Step]:
    """The steps a take has, in the order they run: a picture, a last frame or a speech the
    author picked is not a step. (The page shows exactly these.)
    """
    if take.output == "image":
        return ["prompts", "image"]
    if take.output == "audio":
        return ["prompts", "voice"]
    steps: list[Step] = ["prompts"]
    if take.first_frame is None:
        steps.append("image")
    if _makes_last_frame(take):
        steps.append("last_frame")
    if not _blank(take.dialogue) and take.audio_input is None:
        steps.append("voice")
    steps.append("video")
    return steps


def prompt_keys(take: CharacterTake) -> list[str]:
    """The texts a take uses, in the order the page shows them."""
    needed = _needed(take)
    return [
        key
        for key in (
            writer.IMAGE_PROMPT,
            writer.LAST_FRAME_PROMPT,
            writer.VIDEO_PROMPT,
            writer.DELIVERY_INSTRUCTION,
        )
        if key in needed
    ]


def _needs_prompts(take: CharacterTake, state: TakeState) -> bool:
    """Is a text missing that a step still to run needs? Once a step has run, its text is no
    longer needed, even if it happened to come out blank.
    """
    needed = _needed(take)
    stored = take.prompts if isinstance(take.prompts, dict) else {}
    pending: set[str] = set()
    if not state.image_done and writer.IMAGE_PROMPT in needed:
        pending.add(writer.IMAGE_PROMPT)
    if not state.last_frame_done and writer.LAST_FRAME_PROMPT in needed:
        pending.add(writer.LAST_FRAME_PROMPT)
    if not state.video_done and writer.VIDEO_PROMPT in needed:
        pending.add(writer.VIDEO_PROMPT)
    if not state.voice_done and writer.DELIVERY_INSTRUCTION in needed:
        pending.add(writer.DELIVERY_INSTRUCTION)
    return any(_blank(stored.get(key)) for key in pending)


def next_step(take: CharacterTake, state: TakeState) -> Step | None:
    """The step to start next, or None when the take is finished. A first frame, a last frame
    or a speech the author picked counts as done: nothing is made for it.
    """
    if take.output == "image":
        if state.image_done:
            return None
    elif take.output == "audio":
        if state.voice_done:
            return None
    elif state.video_done:
        return None

    if _needs_prompts(take, state):
        return "prompts"
    if take.output in ("image", "video") and not _first_frame_ready(take, state):
        return "image"
    if _makes_last_frame(take) and not state.last_frame_done:
        return "last_frame"
    needs_voice = take.output == "audio" or (
        take.output == "video" and not _blank(take.dialogue) and take.audio_input is None
    )
    if needs_voice and not state.voice_done:
        return "voice"
    return "video" if take.output == "video" else None


# --- Starting a step ---------------------------------------------------------------------


def _ref_json(ref: FirstFrameRef | AudioRef | None) -> dict[str, Any] | None:
    """A picture or a speech as the take stores it: `{source, id}`."""
    return None if ref is None else {"source": ref.source, "id": ref.id}


def _frame_ref(value: Any) -> FirstFrameRef | None:
    """A stored `{source, id}` picture, or None when `value` is not one (or is None)."""
    if (
        isinstance(value, dict)
        and value.get("source") in ("lab", "asset")
        and isinstance(value.get("id"), int)
    ):
        source: video_lab.FrameSource = "lab" if value["source"] == "lab" else "asset"
        return FirstFrameRef(source=source, id=value["id"])
    return None


def _audio_ref(value: Any) -> AudioRef | None:
    """A stored `{source, id}` speech, or None when `value` is not one (or is None)."""
    if (
        isinstance(value, dict)
        and value.get("source") in ("voice_run", "voice")
        and isinstance(value.get("id"), int)
    ):
        source: video_lab.AudioSource = "voice_run" if value["source"] == "voice_run" else "voice"
        return AudioRef(source=source, id=value["id"])
    return None


async def _picture_note(session: AsyncSession, value: Any) -> str | None:
    """What the language model can be told about a picture the author picked: the prompt it was
    made from, when it is a result of the lab. The model cannot see pictures, so for an upload or
    a project frame there is nothing to tell.
    """
    ref = _frame_ref(value)
    if ref is None or ref.source != "lab":
        return None
    image = await session.get(LabImage, ref.id)
    if image is None or image.run_id is None:
        return None
    run = await session.get(LabRun, image.run_id)
    return run.prompt if run is not None else None


async def _start_prompts(session: AsyncSession, take: CharacterTake) -> None:
    character = await session.get(LibraryCharacter, take.character_id)
    card = character_library.character_card(character) if character is not None else ""
    target = _target(take)
    identity_pictures = (
        len(character_library.references_for(take.framing))
        if target == "h3_reference" and take.identity_refs
        else 0
    )
    inputs = writer.prompt_inputs(
        card=card,
        action=take.action,
        dialogue=take.dialogue,
        needed=_needed(take),
        target=target,
        marker=take.audio_marker,
        has_last_frame=_has_last_frame(take),
        identity_pictures=identity_pictures,
        first_frame_note=await _picture_note(session, take.first_frame),
        last_frame_note=await _picture_note(session, take.last_frame),
    )
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=TAKE_PROMPT_JOB,
        provider="llm",
        input={"take_id": take.id, "inputs": inputs},
        commit=False,
        dedupe=False,
    )
    take.prompt_job_id = job.id


async def _stored_image(session: AsyncSession, run_id: int) -> LabImage | None:
    """The picture an image run stored, or None while it has none."""
    statement = select(LabImage).where(LabImage.run_id == run_id)
    return (await session.execute(statement)).scalars().first()


async def _first_frame_ref(session: AsyncSession, take: CharacterTake) -> FirstFrameRef:
    """The picture the clip starts from: the one the author picked, or the one the take made.
    Raises CharacterTakeError while there is none.
    """
    if take.first_frame is not None:
        picked = _frame_ref(take.first_frame)
        if picked is None:
            raise CharacterTakeError("The first frame this take names is not a picture.")
        return picked
    if take.image_run_id is None:
        raise CharacterTakeError("Make the picture first: the video starts from it.")
    image = await _stored_image(session, take.image_run_id)
    if image is None:
        raise CharacterTakeError("The picture is not ready yet.")
    return FirstFrameRef(source="lab", id=image.id)


async def _last_frame_ref(session: AsyncSession, take: CharacterTake) -> FirstFrameRef | None:
    """The picture the clip ends on (picked or made), or None when it has no last frame. Raises
    CharacterTakeError when the take makes one and it is not ready.
    """
    if take.last_frame is not None:
        picked = _frame_ref(take.last_frame)
        if picked is None:
            raise CharacterTakeError("The last frame this take names is not a picture.")
        return picked
    if not take.make_last_frame:
        return None
    if take.last_frame_run_id is None:
        raise CharacterTakeError("Make the last frame first: the video ends on it.")
    image = await _stored_image(session, take.last_frame_run_id)
    if image is None:
        raise CharacterTakeError("The last frame is not ready yet.")
    return FirstFrameRef(source="lab", id=image.id)


async def _start_image(session: AsyncSession, take: CharacterTake) -> None:
    if take.first_frame is not None:
        raise CharacterTakeError("This take uses a first frame you picked: no picture is made.")
    prompts = take.prompts if isinstance(take.prompts, dict) else {}
    prompt = prompts.get(writer.IMAGE_PROMPT)
    if not isinstance(prompt, str) or _blank(prompt):
        raise CharacterTakeError("Write the image prompt first.")
    if take.look_id is None:
        raise CharacterTakeError("This character has no look to make a picture from yet.")
    try:
        references = await character_looks.references_for_take(session, take.look_id, take.framing)
    except CharacterLookError as exc:
        raise CharacterTakeError(str(exc)) from exc

    mode = await _image_mode(session)
    aspect_ratio = (
        _H3_ASPECT_RATIO[take.orientation]
        if is_h3(take)
        else _ASPECT_RATIO[(take.framing, take.orientation)]
    )
    form = QwenEditForm(
        prompt=prompt.strip(),
        mode=mode,
        aspect_ratio=aspect_ratio,
        seed=take.seed,
        steps=None,
        references=references,
    )
    try:
        run, _job = await image_lab.create_qwen_edit_run(session, form, commit=False)
    except LabInputError as exc:
        raise CharacterTakeError(str(exc)) from exc
    take.image_run_id = run.id


async def _start_last_frame(session: AsyncSession, take: CharacterTake) -> None:
    """Makes the clip's last frame by editing its first frame, with the edit instruction the
    language model wrote. The edit follows the first frame's own shape, so a picked first frame
    of any size gives a last frame of the same size.
    """
    if not _makes_last_frame(take):
        raise CharacterTakeError("This take does not make a last frame.")
    prompts = take.prompts if isinstance(take.prompts, dict) else {}
    prompt = prompts.get(writer.LAST_FRAME_PROMPT)
    if not isinstance(prompt, str) or _blank(prompt):
        raise CharacterTakeError("Write the last frame prompt first.")
    first_frame = await _first_frame_ref(session, take)
    form = QwenEditForm(
        prompt=prompt.strip(),
        mode=await _image_mode(session),
        aspect_ratio=None,
        seed=take.seed,
        steps=None,
        references=[Ref(source=first_frame.source, id=first_frame.id)],
    )
    try:
        run, _job = await image_lab.create_qwen_edit_run(session, form, commit=False)
    except LabInputError as exc:
        raise CharacterTakeError(str(exc)) from exc
    take.last_frame_run_id = run.id


async def _start_voice(session: AsyncSession, take: CharacterTake) -> None:
    if take.audio_input is not None:
        raise CharacterTakeError("This take uses a speech you picked: no speech is made.")
    character = await session.get(LibraryCharacter, take.character_id)
    if character is None or not character_library.has_voice(character):
        raise CharacterTakeError("This character has no voice: choose or audition one first.")
    text = take.dialogue
    if _blank(text):
        raise CharacterTakeError("Write the dialogue first.")
    prompts = take.prompts if isinstance(take.prompts, dict) else {}
    instruction = prompts.get(writer.DELIVERY_INSTRUCTION)
    if not isinstance(instruction, str) or _blank(instruction):
        raise CharacterTakeError("Write the delivery instruction first.")
    form = VoiceLabForm(
        mode="direction",
        text=(text or "").strip(),
        instruction=instruction.strip(),
        voice_id=character.voice_id,
        seed=None,
        cfg_scale=None,
    )
    try:
        row = await voice_lab.create_run(session, form, commit=False)
    except VoiceLabInputError as exc:
        raise CharacterTakeError(str(exc)) from exc
    take.voice_run_id = row.run.id


async def _start_h3_video(
    session: AsyncSession, take: CharacterTake, prompt: str, first_frame: FirstFrameRef
) -> video_lab.RunRow:
    """The clip of a MiniMax H3 take.

    Without dialogue: H3's plain endpoint, which takes the first frame and the last frame (if
    any) itself and makes its own sound. With dialogue: H3's reference endpoint, which has no
    first-frame field, so the first frame is `<Picture 1>`, the last frame (if any) `<Picture 2>`,
    the character's own pictures (when asked for) the pictures after them, and the speech is
    `<Audio 1>`. This order is what the prompt was written for (`character_take_prompt_writer`).
    """
    orientation: video_lab.Orientation = take.orientation
    last_frame = await _last_frame_ref(session, take)

    if _blank(take.dialogue):
        silent_form = LabVideoForm(
            prompt=prompt,
            models=[video_models.H3_MODEL],
            mode="quality",
            orientation=orientation,
            duration_s=take.duration_s or DEFAULT_SILENT_DURATION_S,
            seed=take.seed,
            negative_prompt=None,
            first_frame=first_frame,
            last_frame=last_frame,
            num_inference_steps=take.num_inference_steps,
        )
        try:
            rows = await video_lab.create_runs(session, silent_form, commit=False)
        except LabVideoInputError as exc:
            raise CharacterTakeError(str(exc)) from exc
        return rows[0]

    audio = _audio_ref(take.audio_input)
    if audio is None:
        if take.voice_run_id is None:
            raise CharacterTakeError("Make the speech first: the video follows it.")
        audio = AudioRef(source="voice_run", id=take.voice_run_id)

    pictures = [first_frame] if last_frame is None else [first_frame, last_frame]
    if take.identity_refs:
        if take.look_id is None:
            raise CharacterTakeError("This character has no look to take pictures from yet.")
        try:
            looks = await character_looks.references_for_take(session, take.look_id, take.framing)
        except CharacterLookError as exc:
            raise CharacterTakeError(str(exc)) from exc
        pictures += [FirstFrameRef(source=look.source, id=look.id) for look in looks]
    reference_form = H3ReferenceForm(
        prompt=prompt,
        orientation=orientation,
        seed=take.seed,
        references=pictures,
        audio=audio,
        match_audio_duration=take.match_audio_duration,
        duration_s=None
        if take.match_audio_duration
        else take.duration_s or DEFAULT_SILENT_DURATION_S,
        num_inference_steps=take.num_inference_steps,
    )
    try:
        return await video_lab.create_h3_reference_run(session, reference_form, commit=False)
    except LabVideoInputError as exc:
        raise CharacterTakeError(str(exc)) from exc


async def _start_video(session: AsyncSession, take: CharacterTake) -> None:
    prompts = take.prompts if isinstance(take.prompts, dict) else {}
    video_prompt = prompts.get(writer.VIDEO_PROMPT)
    if not isinstance(video_prompt, str) or _blank(video_prompt):
        raise CharacterTakeError("Write the video prompt first.")
    first_frame = await _first_frame_ref(session, take)
    if is_h3(take):
        h3_row = await _start_h3_video(session, take, video_prompt.strip(), first_frame)
        take.video_run_id = h3_row.run.id
        return

    orientation: video_lab.Orientation = take.orientation
    video_model: VideoModel = (
        take.video_model if is_video_model(take.video_model) else DEFAULT_MODEL
    )

    if not _blank(take.dialogue):
        if take.voice_run_id is None:
            raise CharacterTakeError("Make the speech first: the video follows it.")
        audio_form = LipSyncForm(
            prompt=video_prompt.strip(),
            orientation=orientation,
            seed=take.seed,
            negative_prompt=take.negative_prompt,
            first_frame=first_frame,
            audio=AudioRef(source="voice_run", id=take.voice_run_id),
            video_model=video_model,
            lip_sync=take.lip_sync,
        )
        try:
            row = await video_lab.create_audio_run(session, audio_form, commit=False)
        except LabVideoInputError as exc:
            raise CharacterTakeError(str(exc)) from exc
    else:
        silent_form = LabVideoForm(
            prompt=video_prompt.strip(),
            models=[video_model],
            mode="quality",
            orientation=orientation,
            duration_s=take.duration_s or DEFAULT_SILENT_DURATION_S,
            seed=take.seed,
            negative_prompt=take.negative_prompt,
            first_frame=first_frame,
            last_frame=None,
        )
        try:
            rows = await video_lab.create_runs(session, silent_form, commit=False)
        except LabVideoInputError as exc:
            raise CharacterTakeError(str(exc)) from exc
        row = rows[0]
    take.video_run_id = row.run.id


async def _start_step(session: AsyncSession, take: CharacterTake, step: Step) -> None:
    """Creates the rows and the job of `step` (flushed, not committed) and links them to the
    take. Raises CharacterTakeError. The caller commits, or rolls back.
    """
    if step == "prompts":
        await _start_prompts(session, take)
    elif step == "image":
        await _start_image(session, take)
    elif step == "last_frame":
        await _start_last_frame(session, take)
    elif step == "voice":
        await _start_voice(session, take)
    else:
        await _start_video(session, take)
    take.last_error = None
    _logger.info("take %d: %s step started", take.id, step)


# --- Making a take -----------------------------------------------------------------------


def _h3_settings_given(form: TakeForm) -> bool:
    """Does the form set something only a MiniMax H3 take has?"""
    return (
        form.first_frame is not None
        or form.make_last_frame
        or form.last_frame is not None
        or form.audio is not None
        or form.identity_refs
        or form.num_inference_steps is not None
    )


def _same_words(first: str, second: str) -> bool:
    return " ".join(first.split()) == " ".join(second.split())


async def _audio_words(session: AsyncSession, ref: AudioRef) -> str | None:
    """What a speech the author picked says: the text a Voice lab speech was read from, or a
    saved voice's transcript. None when the speech is not found.
    """
    if ref.source == "voice_run":
        run = await session.get(LabVoiceRun, ref.id)
        return run.text if run is not None else None
    voice = await session.get(Voice, ref.id)
    return voice.transcript if voice is not None else None


async def _check_picture(session: AsyncSession, ref: FirstFrameRef) -> None:
    try:
        await video_lab.first_frame_path(session, ref)
    except LabVideoInputError as exc:
        raise CharacterTakeError(str(exc)) from exc


async def _validate_h3(session: AsyncSession, form: TakeForm, has_dialogue: bool) -> None:
    """The checks of a MiniMax H3 video take, on top of the ones every take gets. Like the rest of
    `_validate` it refuses what a later step would refuse, so no paid step is wasted: the
    pictures and the speech picked must exist, and a picked speech must last what H3's
    reference endpoint takes. (A speech the take makes is checked when the clip starts: how long
    it lasts is not known before.)
    """
    if form.lip_sync:
        raise CharacterTakeError("Lip sync is for LTX: MiniMax H3 makes the talking itself.")
    if not _blank(form.negative_prompt):
        raise CharacterTakeError("MiniMax H3 has no negative prompt.")
    steps = form.num_inference_steps
    if steps is not None and not video_lab.H3_STEPS_MIN <= steps <= video_lab.H3_STEPS_MAX:
        raise CharacterTakeError(
            f"The steps must be from {video_lab.H3_STEPS_MIN} to {video_lab.H3_STEPS_MAX}."
        )
    if form.audio_marker not in AUDIO_MARKERS:
        raise CharacterTakeError("Choose how the speech is used.")
    if form.make_last_frame and form.last_frame is not None:
        raise CharacterTakeError("Make the last frame or pick one, not both.")
    if form.identity_refs and not has_dialogue:
        raise CharacterTakeError(
            "The character's own pictures are sent as references with dialogue only."
        )
    if form.audio is not None and not has_dialogue:
        raise CharacterTakeError("A speech to use needs dialogue: write what the character says.")
    for picture in (form.first_frame, form.last_frame):
        if picture is not None:
            await _check_picture(session, picture)

    if has_dialogue:
        if form.audio_marker == "fully_copy" and not form.match_audio_duration:
            raise CharacterTakeError(
                "With fully_copy the speech is the whole soundtrack, so the clip must be as "
                "long as the speech."
            )
        if form.audio is not None:
            try:
                audio = await video_lab.audio_file(session, form.audio)
            except LabVideoInputError as exc:
                raise CharacterTakeError(str(exc)) from exc
            if not audio.duration_s > 0:  # written so that NaN is rejected too
                raise CharacterTakeError("The speech has no length.")
            words = await _audio_words(session, form.audio)
            if (
                form.audio_marker in writer.COPY_MARKERS
                and words is not None
                and not _same_words(words, form.dialogue or "")
            ):
                quoted = words if len(words) <= _QUOTE_CHARS else f"{words[:_QUOTE_CHARS]}…"
                raise CharacterTakeError(
                    f"With {form.audio_marker} the speech is copied, so the dialogue must be "
                    f"exactly what the speech says: “{quoted}”"
                )
    if not has_dialogue or not form.match_audio_duration:
        duration = form.duration_s if form.duration_s is not None else DEFAULT_SILENT_DURATION_S
        if not video_lab.DURATION_MIN_S <= duration <= video_lab.DURATION_MAX_S:
            raise CharacterTakeError(
                f"The length must be from {video_lab.DURATION_MIN_S:g} to "
                f"{video_lab.DURATION_MAX_S:g} seconds."
            )


async def _validate(session: AsyncSession, form: TakeForm) -> LibraryCharacter:
    """Raises CharacterTakeError for a form no take should be started with. Everything a
    later step would refuse is refused here, so a paid step is never wasted on a form that
    cannot finish.
    """
    character = await session.get(LibraryCharacter, form.character_id)
    if character is None:
        raise CharacterTakeError(f"There is no character {form.character_id}.")
    if form.run not in RUN_STEPS:
        raise CharacterTakeError("Choose what to run.")
    _too_long(form.action, writer.ACTION_MAX_CHARS, "action")
    _too_long(form.dialogue, writer.DIALOGUE_MAX_CHARS, "dialogue")
    has_dialogue = not _blank(form.dialogue)
    if has_dialogue and not character_library.has_voice(character):
        raise CharacterTakeError(
            "This character is mute (it has no saved voice): leave the dialogue out, or "
            "choose a different character."
        )

    if form.output == "audio":
        if not has_dialogue:
            raise CharacterTakeError("Write what the character says first.")
        return character

    if form.framing not in character_library.FRAMINGS:
        raise CharacterTakeError("Choose close-up, medium or wide.")
    if form.orientation not in ORIENTATIONS:
        raise CharacterTakeError("Choose portrait or landscape.")
    if form.seed is not None and not 0 <= form.seed < image_models_service.SEED_LIMIT:
        raise CharacterTakeError(
            f"The seed must be from 0 to {image_models_service.SEED_LIMIT - 1}."
        )

    if form.output == "image":
        return character

    # video
    if form.video_model is not None and not video_models.is_lab_video_model(form.video_model):
        raise CharacterTakeError("Choose LTX-2.3, LTX-2.5 or MiniMax H3.")
    if form.video_model == video_models.H3_MODEL:
        await _validate_h3(session, form, has_dialogue)
        return character
    if _h3_settings_given(form):
        raise CharacterTakeError(
            "Picking a first frame, a last frame or a speech, and the steps, are for "
            "MiniMax H3 only."
        )
    if form.lip_sync:
        if not has_dialogue:
            raise CharacterTakeError("Lip sync needs dialogue: write what the character says.")
        if not character.has_visible_mouth:
            raise CharacterTakeError(
                "This character has no visible mouth, so lip sync is not offered for it."
            )
    _too_long(form.negative_prompt, video_lab.NEGATIVE_PROMPT_MAX_CHARS, "negative prompt")
    if not has_dialogue:
        duration = form.duration_s if form.duration_s is not None else DEFAULT_SILENT_DURATION_S
        if not video_lab.DURATION_MIN_S <= duration <= video_lab.DURATION_MAX_S:
            raise CharacterTakeError(
                f"The length must be from {video_lab.DURATION_MIN_S:g} to "
                f"{video_lab.DURATION_MAX_S:g} seconds."
            )
    return character


async def create_take(session: AsyncSession, form: TakeForm) -> TakeRow:
    """Checks the form, saves a take and starts its first step. Commits. Raises
    CharacterTakeError, and then nothing is saved.

    `run="all"` starts the first step the take needs and the take then continues by itself.
    `run="image"`, `run="last_frame"`, `run="voice"` and `run="video"` start only that step (a
    rerun of one step with an edited prompt).
    """
    character = await _validate(session, form)
    h3 = form.output == "video" and form.video_model == video_models.H3_MODEL
    # What the clip has: a speech to hear (H3's reference endpoint) or none (H3's plain one).
    h3_speaks = h3 and not _blank(form.dialogue)
    take = CharacterTake(
        character_id=form.character_id,
        look_id=character.current_look_id,
        output=form.output,
        action=_clean(form.action),
        dialogue=_clean(form.dialogue),
        video_model=form.video_model if form.output == "video" else None,
        lip_sync=form.lip_sync if form.output == "video" else False,
        framing=form.framing if form.output != "audio" else "medium",
        orientation=form.orientation if form.output != "audio" else "portrait",
        seed=form.seed,
        # A clip that does not follow its speech has a length of its own.
        duration_s=(
            form.duration_s or DEFAULT_SILENT_DURATION_S
            if form.output == "video"
            and (_blank(form.dialogue) or (h3_speaks and not form.match_audio_duration))
            else None
        ),
        negative_prompt=_clean(form.negative_prompt) if form.output == "video" else None,
        audio_marker=form.audio_marker if h3_speaks else None,
        match_audio_duration=form.match_audio_duration if h3_speaks else False,
        num_inference_steps=form.num_inference_steps if h3 else None,
        identity_refs=form.identity_refs if h3_speaks else False,
        first_frame=_ref_json(form.first_frame) if h3 else None,
        make_last_frame=form.make_last_frame if h3 else False,
        last_frame=_ref_json(form.last_frame) if h3 else None,
        audio_input=_ref_json(form.audio) if h3_speaks else None,
        auto_continue=form.run == "all",
    )
    session.add(take)
    await session.flush()

    step: Step | None
    if form.run == "all":
        step = next_step(take, await _state(session, take))
    else:
        step = form.run
    try:
        if step is None:
            raise CharacterTakeError("There is nothing left to run for this take.")
        await _start_step(session, take, step)
    except CharacterTakeError:
        await session.rollback()
        raise
    await session.commit()
    _logger.info(
        "take %d created: character=%d output=%s run=%s",
        take.id,
        form.character_id,
        form.output,
        form.run,
    )
    return (await _rows(session, [take]))[0]


async def continue_take(session: AsyncSession, take_id: int) -> TakeRow | None:
    """Starts the take's next step. Commits. Returns None when there is no such take. Raises
    CharacterTakeError when a step is still running, when the take is finished, or when the
    next step cannot start, and then nothing changes.
    """
    take = await _fresh(session, CharacterTake, take_id)
    if take is None:
        return None
    state = await _state(session, take)
    if state.active is not None:
        raise CharacterTakeError(f"The {STEP_LABELS[state.active]} step is still running.")
    step = next_step(take, state)
    if step is None:
        raise CharacterTakeError("This take is finished. Start a new take to try again.")
    try:
        await _start_step(session, take, step)
    except CharacterTakeError:
        await session.rollback()
        raise
    await session.commit()
    return (await _rows(session, [take]))[0]


# A human edit is held to the same limit the model's own answer is checked against
# (`character_take_prompt_writer.check_prompts`): the delivery instruction follows Breeze
# TTS's own limit, the others the general field limit. A MiniMax H3 video prompt is several
# sections long, so it has a limit of its own (`_field_limit`).
_FIELD_LIMIT: Final[dict[str, int]] = {
    writer.IMAGE_PROMPT: writer.FIELD_MAX_CHARS,
    writer.LAST_FRAME_PROMPT: writer.FIELD_MAX_CHARS,
    writer.VIDEO_PROMPT: writer.FIELD_MAX_CHARS,
    writer.DELIVERY_INSTRUCTION: writer.DELIVERY_MAX_CHARS,
}
_FIELD_LABEL: Final[dict[str, str]] = {
    writer.IMAGE_PROMPT: "image prompt",
    writer.LAST_FRAME_PROMPT: "last frame prompt",
    writer.VIDEO_PROMPT: "video prompt",
    writer.DELIVERY_INSTRUCTION: "delivery instruction",
}


def _field_limit(take: CharacterTake, key: str) -> int:
    if key == writer.VIDEO_PROMPT and is_h3(take):
        return writer.H3_PROMPT_MAX_CHARS
    return _FIELD_LIMIT[key]


async def rerun(
    session: AsyncSession,
    take_id: int,
    *,
    image_prompt: str | None = None,
    last_frame_prompt: str | None = None,
    video_prompt: str | None = None,
    delivery_instruction: str | None = None,
) -> TakeRow:
    """Edits one or more of an existing take's texts and starts whatever that frees to run
    again: changing the image prompt clears its picture (and, for a video, the video that
    followed it, and a last frame made from that picture); changing the last frame prompt clears
    the last frame and the video; changing the video prompt clears the video; changing the
    delivery instruction clears the speech (and, for a video, the video that followed it).
    Commits. Raises CharacterTakeError, and then nothing changes.
    """
    take = await _fresh(session, CharacterTake, take_id)
    if take is None:
        raise CharacterTakeError(f"There is no take {take_id}.")
    state = await _state(session, take)
    if state.active is not None:
        raise CharacterTakeError(f"The {STEP_LABELS[state.active]} step is still running.")

    needed = _needed(take)
    given = {
        writer.IMAGE_PROMPT: image_prompt,
        writer.LAST_FRAME_PROMPT: last_frame_prompt,
        writer.VIDEO_PROMPT: video_prompt,
        writer.DELIVERY_INSTRUCTION: delivery_instruction,
    }
    changed = {key: value for key, value in given.items() if value is not None}
    if not changed:
        raise CharacterTakeError("Give at least one changed text.")
    for key, value in changed.items():
        if key not in needed:
            raise CharacterTakeError(f"This take does not use the {_FIELD_LABEL[key]}.")
        if _blank(value):
            raise CharacterTakeError(f"The {_FIELD_LABEL[key]} cannot be blank.")
        _too_long(value, _field_limit(take, key), _FIELD_LABEL[key])

    stored = dict(take.prompts) if isinstance(take.prompts, dict) else {}
    for key, value in changed.items():
        stored[key] = (value or "").strip()
    take.prompts = stored

    if writer.IMAGE_PROMPT in changed:
        take.image_run_id = None
        if take.output == "video":
            take.video_run_id = None
            # A last frame made from the old picture no longer belongs to the new one.
            if _makes_last_frame(take):
                take.last_frame_run_id = None
    if writer.LAST_FRAME_PROMPT in changed:
        take.last_frame_run_id = None
        take.video_run_id = None
    if writer.VIDEO_PROMPT in changed:
        take.video_run_id = None
    if writer.DELIVERY_INSTRUCTION in changed:
        take.voice_run_id = None
        if take.output == "video":
            take.video_run_id = None
    take.last_error = None

    step = next_step(take, await _state(session, take))
    if step is None or step == "prompts":
        raise CharacterTakeError("There is nothing to run again from this change.")
    try:
        await _start_step(session, take, step)
    except CharacterTakeError:
        await session.rollback()
        raise
    await session.commit()
    _logger.info("take %d: rerun, %s step started", take.id, step)
    return (await _rows(session, [take]))[0]


# --- Continuing by itself -----------------------------------------------------------------


async def _advance(take_id: int) -> bool:
    """Starts the next step of a take that is set to continue by itself, in a transaction of
    its own. Never starts the prompts step (that would loop forever on its own answer).
    Returns True when a step started. When it cannot, the reason is kept on the take.
    """
    async with SessionLocal() as session:
        take = await _fresh(session, CharacterTake, take_id)
        if take is None or not take.auto_continue:
            await session.commit()
            return False
        state = await _state(session, take)
        step = None if state.active is not None else next_step(take, state)
        if step not in ("image", "last_frame", "voice", "video"):
            await session.commit()
            return False
        try:
            await _start_step(session, take, step)
        except CharacterTakeError as exc:
            await session.rollback()
            _logger.warning("take %d: the %s step could not start: %s", take_id, step, exc)
            take = await _fresh(session, CharacterTake, take_id)
            if take is not None:
                take.last_error = f"The {STEP_LABELS[step]} step could not start: {exc}"
            await session.commit()
            return False
        await session.commit()
        return True


async def on_prompts_written(job_id: int) -> bool:
    """Called when a `write_character_take_prompt` job has finished. If a take was started
    with this job, copies the texts onto it (only where the take has none: what the author
    wrote stays), then starts its next step if it is set to continue by itself. Returns True
    when a step started.
    """
    async with SessionLocal() as session:
        statement = select(CharacterTake).where(CharacterTake.prompt_job_id == job_id)
        take = (await session.execute(statement)).scalars().first()
        if take is None:
            await session.commit()
            return False
        job = await _fresh(session, Job, job_id)
        output = job.output if job is not None and isinstance(job.output, dict) else {}
        stored = dict(take.prompts) if isinstance(take.prompts, dict) else {}
        changed = False
        for key in (
            writer.IMAGE_PROMPT,
            writer.LAST_FRAME_PROMPT,
            writer.VIDEO_PROMPT,
            writer.DELIVERY_INSTRUCTION,
        ):
            value = output.get(key)
            if _blank(stored.get(key)) and isinstance(value, str) and not _blank(value):
                stored[key] = value.strip()
                changed = True
        if changed:
            take.prompts = stored
        take_id = take.id
        await session.commit()
    return await _advance(take_id)


async def on_image_stored(run_id: int) -> bool:
    """Called (best effort) once a `lab_image` job has stored its picture. Starts the next step
    of every take whose first frame or last frame this is and that is set to continue by
    itself. Returns True when a step started.
    """
    async with SessionLocal() as session:
        statement = select(CharacterTake.id).where(
            or_(CharacterTake.image_run_id == run_id, CharacterTake.last_frame_run_id == run_id),
            CharacterTake.auto_continue.is_(True),
            CharacterTake.video_run_id.is_(None),
        )
        take_ids = list((await session.execute(statement)).scalars().all())
        await session.commit()
    started = False
    for take_id in take_ids:
        started = await _advance(take_id) or started
    return started


async def on_voice_finished(run_id: int) -> bool:
    """Called when a Voice lab speech has been stored. Starts the video of every take that
    made this speech and is set to continue by itself. Returns True when a step started.
    """
    async with SessionLocal() as session:
        statement = select(CharacterTake.id).where(
            CharacterTake.voice_run_id == run_id,
            CharacterTake.auto_continue.is_(True),
            CharacterTake.video_run_id.is_(None),
        )
        take_ids = list((await session.execute(statement)).scalars().all())
        await session.commit()
    started = False
    for take_id in take_ids:
        started = await _advance(take_id) or started
    return started


# --- Reading takes -----------------------------------------------------------------------


async def _rows(session: AsyncSession, takes: Collection[CharacterTake]) -> list[TakeRow]:
    """The takes with their characters, jobs and runs, loaded together."""
    ordered = list(takes)
    character_ids = {t.character_id for t in ordered}
    prompt_job_ids = {t.prompt_job_id for t in ordered if t.prompt_job_id is not None}
    image_run_ids = {
        run_id
        for t in ordered
        for run_id in (t.image_run_id, t.last_frame_run_id)
        if run_id is not None
    }
    voice_ids = {t.voice_run_id for t in ordered if t.voice_run_id is not None}
    video_ids = {t.video_run_id for t in ordered if t.video_run_id is not None}

    characters: dict[int, LibraryCharacter] = {}
    if character_ids:
        found = await session.execute(
            select(LibraryCharacter)
            .where(LibraryCharacter.id.in_(character_ids))
            .execution_options(populate_existing=True)
        )
        characters = {c.id: c for c in found.scalars()}

    # The first frames' and the last frames' runs are the same kind of run.
    image_runs: dict[int, LabRun] = {}
    if image_run_ids:
        found = await session.execute(
            select(LabRun)
            .where(LabRun.id.in_(image_run_ids))
            .execution_options(populate_existing=True)
        )
        image_runs = {run.id: run for run in found.scalars()}
    image_job_ids = {run.job_id for run in image_runs.values() if run.job_id is not None}

    jobs: dict[int, Job] = {}
    wanted_job_ids = prompt_job_ids | image_job_ids
    if wanted_job_ids:
        found = await session.execute(
            select(Job).where(Job.id.in_(wanted_job_ids)).execution_options(populate_existing=True)
        )
        jobs = {job.id: job for job in found.scalars()}

    def run_job(run_id: int | None) -> Job | None:
        """The job of an image run (a first frame's or a last frame's), if it has one."""
        run = image_runs.get(run_id) if run_id is not None else None
        return jobs.get(run.job_id) if run is not None and run.job_id is not None else None

    voices = await voice_lab.get_runs(session, voice_ids)
    videos = await video_lab.get_runs(session, video_ids)

    return [
        TakeRow(
            take=take,
            character=characters.get(take.character_id),
            prompt_job=jobs.get(take.prompt_job_id) if take.prompt_job_id else None,
            image_run=image_runs.get(take.image_run_id) if take.image_run_id else None,
            image_job=run_job(take.image_run_id),
            voice=voices.get(take.voice_run_id) if take.voice_run_id else None,
            video=videos.get(take.video_run_id) if take.video_run_id else None,
            last_frame_run=(
                image_runs.get(take.last_frame_run_id) if take.last_frame_run_id else None
            ),
            last_frame_job=run_job(take.last_frame_run_id),
        )
        for take in ordered
    ]


async def list_takes(
    session: AsyncSession, character_id: int | None, before_id: int | None, limit: int
) -> list[TakeRow]:
    """The newest takes first, `limit` of them, those with an id below `before_id` if given,
    those of one character if given.
    """
    statement = (
        select(CharacterTake)
        .order_by(CharacterTake.id.desc())
        .limit(min(limit, LIST_LIMIT_MAX))
        .execution_options(populate_existing=True)
    )
    if character_id is not None:
        statement = statement.where(CharacterTake.character_id == character_id)
    if before_id is not None:
        statement = statement.where(CharacterTake.id < before_id)
    takes = (await session.execute(statement)).scalars().all()
    return await _rows(session, takes)


async def get_take(session: AsyncSession, take_id: int) -> TakeRow | None:
    take = await _fresh(session, CharacterTake, take_id)
    if take is None:
        return None
    return (await _rows(session, [take]))[0]
