"""The Talking character lab: a character picture speaks one line of dialogue (Phase 24).

A *take* (`lab_talk_run`) is made in up to three steps, each a job of its own that the other
labs already know how to run:

1. **prompts**: a `write_talk_prompts` job (a paid call to the language model) writes the
   instruction for the speech model and the prompt for the video model. The author may write
   either by hand instead.
2. **voice**: a Voice lab run (`lab_voice`, Breeze TTS 2) makes the speech from the dialogue:
   from a description of a voice (`design`), a saved voice (`clone`), or a saved voice steered
   by the instruction (`direction`). A take may instead reuse the speech of an earlier Voice
   lab run, which skips this step.
3. **video**: a Video lab run on LTX-2.3's audio-to-video endpoint makes the character speak
   that speech, lip-synced (`video_lab.create_audio_run`).

A take made with `run="all"` continues by itself (`auto_continue`): when the prompts job
finishes (`on_prompts_written`, called by the job) and when the speech is stored
(`on_voice_finished`, called by the Voice lab job), the next step is started. Every step is a
paid GPU or model call, so a step starts only from a click: either the one that made the take,
or "continue" (`continue_take`), which starts one step. If a step cannot be started after the
step before it paid off, the reason is kept on the take (`last_error`) and the chain stops.

This module creates rows and jobs. It never calls the GPU server or the language model.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Job,
    LabCharacter,
    LabImage,
    LabRun,
    LabTalkRun,
    LabVideoRun,
    LabVoiceRun,
    Voice,
)
from app.db.session import SessionLocal
from app.jobs import store
from app.providers import speech_synthesizer
from app.services import talk_prompt_writer as writer
from app.services import video_lab, voice_lab
from app.services.talk_prompt_writer import VoiceKind
from app.services.video_lab import AudioRef, FirstFrameRef, LipSyncForm, Orientation
from app.services.voice_lab import VoiceLabForm, VoiceLabInputError

_logger = logging.getLogger(__name__)

PROMPT_JOB: Final = "write_talk_prompts"

Step = Literal["prompts", "voice", "video"]
# What a click starts: the whole chain, only the speech, or only the clip.
RunStep = Literal["all", "voice", "video"]
RUN_STEPS: Final[tuple[RunStep, ...]] = ("all", "voice", "video")
VoiceMode = voice_lab.Mode

STEP_LABELS: Final[dict[str, str]] = {
    "prompts": "prompt writing",
    "voice": "speech",
    "video": "video",
}
_ACTIVE: Final = ("queued", "running")
LIST_LIMIT_MAX: Final = 50


class TalkLabInputError(ValueError):
    """Something the form gets wrong, or a step that cannot start now. The message is meant for
    the user (HTTP 422).
    """


@dataclass(frozen=True)
class TalkForm:
    """What a click on "run" sends."""

    run: RunStep
    dialogue: str
    image: FirstFrameRef
    character_id: int | None
    # What the author says about the character. Wins over the cast character's description.
    character_note: str | None
    delivery_note: str | None
    # A new speech: design | clone | direction. None when `reuse_voice_run_id` is set.
    voice_mode: VoiceMode | None
    # clone and direction: the saved voice. design: none.
    voice_id: int | None
    # Reuse the speech of this finished Voice lab run instead of making a new one.
    reuse_voice_run_id: int | None
    # Left blank, they are written by the language model (or, for the video prompt, needed).
    voice_instruction: str | None
    video_prompt: str | None
    orientation: Orientation
    video_seed: int | None
    negative_prompt: str | None


@dataclass(frozen=True)
class DraftForm:
    """What a click on "write with GLM" sends. No take is made."""

    dialogue: str
    character_id: int | None
    character_note: str | None
    # The picture, used to find the prompt that made it when nothing describes the character.
    image: FirstFrameRef | None
    delivery_note: str | None
    # None: no voice instruction is wanted (a saved voice cloned as it is, or a speech reused).
    voice_mode: VoiceMode | None


@dataclass(frozen=True)
class TakeState:
    """Where a take is: the rows and jobs of its three steps (None where a step has not run)."""

    prompt_job: Job | None
    voice_run: LabVoiceRun | None
    voice_job: Job | None
    video_run: LabVideoRun | None
    video_job: Job | None

    @property
    def active(self) -> Step | None:
        """The step that is waiting or running now, if any."""
        if _is_active(self.prompt_job):
            return "prompts"
        if _is_active(self.voice_job):
            return "voice"
        if _is_active(self.video_job):
            return "video"
        return None

    @property
    def voice_done(self) -> bool:
        return self.voice_run is not None and self.voice_run.path is not None

    @property
    def video_done(self) -> bool:
        return self.video_run is not None and self.video_run.path is not None


@dataclass(frozen=True)
class TakeRow:
    """A take with the three steps it is made of."""

    take: LabTalkRun
    character: LabCharacter | None
    prompt_job: Job | None
    voice: voice_lab.RunRow | None
    video: video_lab.RunRow | None

    @property
    def state(self) -> TakeState:
        return TakeState(
            prompt_job=self.prompt_job,
            voice_run=self.voice.run if self.voice is not None else None,
            voice_job=self.voice.job if self.voice is not None else None,
            video_run=self.video.run if self.video is not None else None,
            video_job=self.video.job if self.video is not None else None,
        )


# --- Small helpers -----------------------------------------------------------------------------


def _is_active(job: Job | None) -> bool:
    return job is not None and job.status in _ACTIVE


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _clean(value: str | None) -> str | None:
    """The text without surrounding space, or None when it is blank."""
    return None if value is None or not value.strip() else value.strip()


def _too_long(value: str | None, limit: int, what: str) -> None:
    if value is not None and len(value.strip()) > limit:
        raise TalkLabInputError(f"The {what} must be at most {limit:,} characters.")


def voice_kind(mode: str | None) -> VoiceKind:
    """What the language model should write for the voice: design and direction have an
    instruction; a clone without one, and a speech that is reused, have none.
    """
    if mode == "design":
        return "design"
    if mode == "direction":
        return "direction"
    return "none"


def _image_ref(value: Any) -> FirstFrameRef:
    """The picture stored on a take, as a reference. The take's own check keeps it well formed."""
    return FirstFrameRef(source=value["source"], id=value["id"])


async def _fresh(session: AsyncSession, model: Any, object_id: int | None) -> Any:
    """The row of `model` with this id as the database has it now, or None."""
    if object_id is None:
        return None
    statement = select(model).where(model.id == object_id).execution_options(populate_existing=True)
    return (await session.execute(statement)).scalars().first()


async def _state(session: AsyncSession, take: LabTalkRun) -> TakeState:
    voice_run = await _fresh(session, LabVoiceRun, take.voice_run_id)
    video_run = await _fresh(session, LabVideoRun, take.video_run_id)
    return TakeState(
        prompt_job=await _fresh(session, Job, take.prompt_job_id),
        voice_run=voice_run,
        voice_job=await _fresh(session, Job, voice_run.job_id if voice_run else None),
        video_run=video_run,
        video_job=await _fresh(session, Job, video_run.job_id if video_run else None),
    )


# --- Which step is next ------------------------------------------------------------------------


def _needs_prompts(take: LabTalkRun, state: TakeState) -> bool:
    """Is a prompt missing that the steps still to run need? The video prompt always is. The
    voice instruction is when a speech is still to be made from a description or directed.
    """
    if _blank(take.video_prompt):
        return True
    return (
        not state.voice_done
        and take.voice_mode in ("design", "direction")
        and _blank(take.voice_instruction)
    )


def next_step(take: LabTalkRun, state: TakeState) -> Step | None:
    """The step to start next, or None when the take is finished, when a take that reuses a
    speech has none it can use, or when the speech is still waiting (see `TakeState.active`).
    """
    if state.video_done:
        return None
    if _needs_prompts(take, state):
        return "prompts"
    if not state.voice_done:
        return "voice" if take.voice_mode is not None else None
    return "video"


# --- Starting a step ---------------------------------------------------------------------------


async def _image_prompt(session: AsyncSession, lab_image_id: int) -> str | None:
    """The prompt of the Image lab run that made this image, if it was made by one."""
    statement = (
        select(LabRun.prompt)
        .join(LabImage, LabImage.run_id == LabRun.id)
        .where(LabImage.id == lab_image_id)
    )
    prompt = (await session.execute(statement)).scalars().first()
    return _clean(prompt)


async def _description(
    session: AsyncSession,
    *,
    note: str | None,
    character_id: int | None,
    image: FirstFrameRef | None,
) -> str | None:
    """What the language model is told about the character: what the author wrote, else the
    cast character's description, else the prompt that made the picture. None when there is
    nothing, and the model then describes a plain, neutral speaker.
    """
    if not _blank(note):
        return _clean(note)
    if character_id is not None:
        character = await session.get(LabCharacter, character_id)
        if character is not None and not _blank(character.description):
            return character.description.strip()
    if image is not None and image.source == "lab":
        prompt = await _image_prompt(session, image.id)
        if prompt is not None:
            return prompt[: writer.CHARACTER_MAX_CHARS]
    return None


async def _start_prompts(session: AsyncSession, take: LabTalkRun) -> None:
    description = await _description(
        session,
        note=take.character_note,
        character_id=take.character_id,
        image=_image_ref(take.image),
    )
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=PROMPT_JOB,
        provider="llm",
        input={
            "requested": "talk_prompts",
            "take_id": take.id,
            "inputs": writer.prompt_inputs(
                take.dialogue, description, take.delivery_note, voice_kind(take.voice_mode)
            ),
        },
        commit=False,
        dedupe=False,
    )
    take.prompt_job_id = job.id


async def _start_voice(session: AsyncSession, take: LabTalkRun) -> None:
    if take.voice_mode is None:
        raise TalkLabInputError("This take reuses an earlier speech, so it makes no new one.")
    form = VoiceLabForm(
        mode=take.voice_mode,
        text=take.dialogue,
        # Clone has no instruction: the voice is reproduced as it is.
        instruction=None if take.voice_mode == "clone" else take.voice_instruction,
        voice_id=take.voice_id,
        seed=None,
        cfg_scale=None,
    )
    row = await voice_lab.create_run(session, form, commit=False)
    take.voice_run_id = row.run.id


async def _start_video(session: AsyncSession, take: LabTalkRun) -> None:
    if take.voice_run_id is None:
        raise TalkLabInputError("Make or choose the speech first: the video follows it.")
    if take.video_prompt is None or _blank(take.video_prompt):
        raise TalkLabInputError("Write the video prompt first.")
    form = LipSyncForm(
        prompt=take.video_prompt,
        orientation="portrait" if take.orientation == "portrait" else "landscape",
        seed=take.video_seed,
        negative_prompt=take.negative_prompt,
        first_frame=_image_ref(take.image),
        audio=AudioRef(source="voice_run", id=take.voice_run_id),
    )
    row = await video_lab.create_audio_run(session, form, commit=False)
    take.video_run_id = row.run.id


async def _start_step(session: AsyncSession, take: LabTalkRun, step: Step) -> None:
    """Creates the rows and the job of `step` (flushed, not committed) and links them to the
    take. Raises TalkLabInputError. The caller commits, or rolls back.
    """
    try:
        if step == "prompts":
            await _start_prompts(session, take)
        elif step == "voice":
            await _start_voice(session, take)
        else:
            await _start_video(session, take)
    except (video_lab.LabVideoInputError, VoiceLabInputError) as exc:
        raise TalkLabInputError(str(exc)) from exc
    take.last_error = None
    _logger.info("talk take %d: %s step started", take.id, step)


# --- Making a take -----------------------------------------------------------------------------


async def _validate(session: AsyncSession, form: TalkForm) -> None:
    """Raises TalkLabInputError for a form no take should be started with. Everything a later
    step would refuse is refused here, so a paid step is never wasted on a form that cannot
    finish.
    """
    if not form.dialogue.strip():
        raise TalkLabInputError("Write the line the character says first.")
    _too_long(form.dialogue, writer.DIALOGUE_MAX_CHARS, "dialogue")
    _too_long(form.character_note, writer.CHARACTER_MAX_CHARS, "character description")
    _too_long(form.delivery_note, writer.DELIVERY_MAX_CHARS, "delivery note")
    _too_long(form.voice_instruction, speech_synthesizer.INSTRUCTION_MAX_CHARS, "voice instruction")
    _too_long(form.video_prompt, video_lab.MAX_PROMPT_CHARS, "video prompt")
    _too_long(form.negative_prompt, video_lab.NEGATIVE_PROMPT_MAX_CHARS, "negative prompt")
    if form.video_seed is not None and not 0 <= form.video_seed < video_lab.SEED_LIMIT:
        raise TalkLabInputError(f"The seed must be from 0 to {video_lab.SEED_LIMIT - 1}.")

    if form.reuse_voice_run_id is not None:
        if form.run == "voice":
            raise TalkLabInputError("The speech step makes a new speech: do not reuse one.")
        if form.voice_mode is not None or form.voice_id is not None:
            raise TalkLabInputError(
                "A reused speech needs no voice settings: leave the voice mode and voice out."
            )
        # A speech that is not finished, or is gone, cannot be reused.
        await video_lab.audio_file(session, AudioRef("voice_run", form.reuse_voice_run_id))
    else:
        if form.run == "video":
            raise TalkLabInputError("The video step needs a speech: choose one to reuse.")
        if form.voice_mode is None:
            raise TalkLabInputError(
                "Choose how the speech is made (a described voice, a saved voice, or a saved "
                "voice with direction), or reuse an earlier speech."
            )
        if form.voice_mode == "design" and form.voice_id is not None:
            raise TalkLabInputError("A described voice is made new: do not choose a saved one.")
        if form.voice_mode != "design" and form.voice_id is None:
            raise TalkLabInputError("Choose the saved voice that reads the line.")
        if form.voice_id is not None and await session.get(Voice, form.voice_id) is None:
            raise TalkLabInputError(f"There is no saved voice {form.voice_id}.")

    if form.run == "video" and _blank(form.video_prompt):
        raise TalkLabInputError("Write the video prompt first.")
    await video_lab.first_frame_path(session, form.image)  # only checks that it exists
    if form.character_id is not None and await session.get(LabCharacter, form.character_id) is None:
        raise TalkLabInputError(f"There is no character {form.character_id}.")


async def create_take(session: AsyncSession, form: TalkForm) -> TakeRow:
    """Checks the form, saves a take and starts its first step. Commits. Raises
    TalkLabInputError, and then nothing is saved.

    `run="all"` starts the first step the take needs (the prompts if one is missing, else the
    speech, else the video) and the take then continues by itself. `run="voice"` and
    `run="video"` start only that step.
    """
    try:
        await _validate(session, form)
    except video_lab.LabVideoInputError as exc:
        raise TalkLabInputError(str(exc)) from exc

    reuse = form.reuse_voice_run_id is not None
    take = LabTalkRun(
        dialogue=form.dialogue.strip(),
        character_id=form.character_id,
        image={"source": form.image.source, "id": form.image.id},
        character_note=_clean(form.character_note),
        delivery_note=_clean(form.delivery_note),
        voice_mode=None if reuse else form.voice_mode,
        voice_id=None if reuse else form.voice_id,
        voice_instruction=_clean(form.voice_instruction),
        video_prompt=_clean(form.video_prompt),
        orientation=form.orientation,
        video_seed=form.video_seed,
        negative_prompt=_clean(form.negative_prompt),
        auto_continue=form.run == "all",
        voice_run_id=form.reuse_voice_run_id,
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
            raise TalkLabInputError("There is nothing left to run for this take.")
        await _start_step(session, take, step)
    except TalkLabInputError:
        await session.rollback()
        raise
    await session.commit()
    _logger.info("talk take %d created: run=%s", take.id, form.run)
    return (await _rows(session, [take]))[0]


async def continue_take(session: AsyncSession, take_id: int) -> TakeRow | None:
    """Starts the take's next step. Commits. Returns None when there is no such take. Raises
    TalkLabInputError when a step is still running, when the take is finished, or when the next
    step cannot start, and then nothing changes.

    It starts one step. Whether the take then goes on by itself is what it was made with.
    """
    take = await _fresh(session, LabTalkRun, take_id)
    if take is None:
        return None
    state = await _state(session, take)
    if state.active is not None:
        raise TalkLabInputError(f"The {STEP_LABELS[state.active]} step is still running.")
    step = next_step(take, state)
    if step is None:
        if state.video_done:
            raise TalkLabInputError("This take is finished. Start a new take to try again.")
        raise TalkLabInputError(
            "This take has no speech it can use. Start a new take with a new or another speech."
        )
    try:
        await _start_step(session, take, step)
    except TalkLabInputError:
        await session.rollback()
        raise
    await session.commit()
    return (await _rows(session, [take]))[0]


# --- The prompts of a take without a take (the "write with GLM" button) ---------------------


async def create_prompt_draft(session: AsyncSession, form: DraftForm) -> Job:
    """Starts the job that writes the two prompts from a line of dialogue. Commits. Raises
    TalkLabInputError. Each call is a paid try of its own, so none is merged into an earlier
    one. The page puts the answer (`job.output`) into the form.
    """
    if not form.dialogue.strip():
        raise TalkLabInputError("Write the line the character says first.")
    _too_long(form.dialogue, writer.DIALOGUE_MAX_CHARS, "dialogue")
    _too_long(form.character_note, writer.CHARACTER_MAX_CHARS, "character description")
    _too_long(form.delivery_note, writer.DELIVERY_MAX_CHARS, "delivery note")
    if form.character_id is not None and await session.get(LabCharacter, form.character_id) is None:
        raise TalkLabInputError(f"There is no character {form.character_id}.")

    description = await _description(
        session, note=form.character_note, character_id=form.character_id, image=form.image
    )
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=PROMPT_JOB,
        provider="llm",
        input={
            "requested": "talk_prompts",
            "inputs": writer.prompt_inputs(
                form.dialogue, description, form.delivery_note, voice_kind(form.voice_mode)
            ),
        },
        dedupe=False,
    )
    return job


# --- Continuing by itself ----------------------------------------------------------------------


async def _advance(take_id: int) -> bool:
    """Starts the next step of a take that is set to continue by itself, in a transaction of its
    own. Never starts the prompts step (that would loop). Returns True when a step started.
    When it cannot start, the reason is kept on the take.
    """
    async with SessionLocal() as session:
        take = await _fresh(session, LabTalkRun, take_id)
        if take is None or not take.auto_continue:
            await session.commit()
            return False
        state = await _state(session, take)
        step = None if state.active is not None else next_step(take, state)
        if step not in ("voice", "video"):
            await session.commit()
            return False
        try:
            await _start_step(session, take, step)
        except TalkLabInputError as exc:
            await session.rollback()
            _logger.warning("talk take %d: the %s step could not start: %s", take_id, step, exc)
            take = await _fresh(session, LabTalkRun, take_id)
            if take is not None:
                take.last_error = f"The {STEP_LABELS[step]} step could not start: {exc}"
            await session.commit()
            return False
        await session.commit()
        return True


async def on_prompts_written(job_id: int) -> bool:
    """Called when a `write_talk_prompts` job has finished. If a take was started with this job,
    copies the prompts onto it (only where the take has none: what the author wrote stays), then
    starts its next step if it is set to continue by itself. Returns True when a step started.
    """
    async with SessionLocal() as session:
        statement = select(LabTalkRun).where(LabTalkRun.prompt_job_id == job_id)
        take = (await session.execute(statement)).scalars().first()
        if take is None:
            await session.commit()
            return False
        job = await _fresh(session, Job, job_id)
        output = job.output if job is not None and isinstance(job.output, dict) else {}
        video, voice = output.get("video_prompt"), output.get("voice_instruction")
        if _blank(take.video_prompt) and isinstance(video, str) and not _blank(video):
            take.video_prompt = video.strip()
        if (
            take.voice_mode in ("design", "direction")
            and _blank(take.voice_instruction)
            and isinstance(voice, str)
            and not _blank(voice)
        ):
            take.voice_instruction = voice.strip()
        take_id = take.id
        await session.commit()
    return await _advance(take_id)


async def on_voice_finished(run_id: int) -> bool:
    """Called when a Voice lab speech has been stored. Starts the video of every take that made
    this speech and is set to continue by itself. Returns True when a step started.
    """
    async with SessionLocal() as session:
        statement = select(LabTalkRun.id).where(
            LabTalkRun.voice_run_id == run_id,
            LabTalkRun.auto_continue.is_(True),
            LabTalkRun.video_run_id.is_(None),
        )
        take_ids = list((await session.execute(statement)).scalars().all())
        await session.commit()
    started = False
    for take_id in take_ids:
        started = await _advance(take_id) or started
    return started


# --- Reading takes -----------------------------------------------------------------------------


async def _rows(session: AsyncSession, takes: Collection[LabTalkRun]) -> list[TakeRow]:
    """The takes with their characters, jobs and runs, loaded together."""
    ordered = list(takes)
    character_ids = {t.character_id for t in ordered if t.character_id is not None}
    job_ids = {t.prompt_job_id for t in ordered if t.prompt_job_id is not None}
    voice_ids = {t.voice_run_id for t in ordered if t.voice_run_id is not None}
    video_ids = {t.video_run_id for t in ordered if t.video_run_id is not None}

    characters: dict[int, LabCharacter] = {}
    if character_ids:
        found = await session.execute(
            select(LabCharacter)
            .where(LabCharacter.id.in_(character_ids))
            .execution_options(populate_existing=True)
        )
        characters = {c.id: c for c in found.scalars()}
    jobs: dict[int, Job] = {}
    if job_ids:
        found = await session.execute(
            select(Job).where(Job.id.in_(job_ids)).execution_options(populate_existing=True)
        )
        jobs = {job.id: job for job in found.scalars()}
    voices = await voice_lab.get_runs(session, voice_ids)
    videos = await video_lab.get_runs(session, video_ids)

    return [
        TakeRow(
            take=take,
            character=characters.get(take.character_id) if take.character_id else None,
            prompt_job=jobs.get(take.prompt_job_id) if take.prompt_job_id else None,
            voice=voices.get(take.voice_run_id) if take.voice_run_id else None,
            video=videos.get(take.video_run_id) if take.video_run_id else None,
        )
        for take in ordered
    ]


async def list_takes(session: AsyncSession, before_id: int | None, limit: int) -> list[TakeRow]:
    """The newest takes first, `limit` of them, those with an id below `before_id` if given."""
    statement = (
        select(LabTalkRun)
        .order_by(LabTalkRun.id.desc())
        .limit(min(limit, LIST_LIMIT_MAX))
        .execution_options(populate_existing=True)
    )
    if before_id is not None:
        statement = statement.where(LabTalkRun.id < before_id)
    takes = (await session.execute(statement)).scalars().all()
    return await _rows(session, takes)


async def get_take(session: AsyncSession, take_id: int) -> TakeRow | None:
    take = await _fresh(session, LabTalkRun, take_id)
    if take is None:
        return None
    return (await _rows(session, [take]))[0]
