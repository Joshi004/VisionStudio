"""The Voices stage of a story project: a saved voice for each defined character and for the
narrator (PHASE-011, `Path_ahead.md` Sections 11 and 20).

A voice is made in three steps, none of which waits for a person (D-5):

1. A `design_voice` job (`jobs/design_voice.py`) asks the story model to write the description a
   voice is designed from. For a character the facts are its definition's `voice_identity`
   (`voice_design_writer.voice_facts`); for the narrator they are the StoryBible's narration
   style, tone and genre.
2. In the same transaction that finishes the job, `queue_sample` starts **one** design-mode
   Voice lab run that reads a fixed line (`voice_design_writer.CHARACTER_LINE`; the narrator
   reads the opening of the story).
3. When that speech is stored, `on_voice_finished` (called by `jobs/lab_voice.py`) saves it as a
   voice and attaches it, in one transaction. For a character it sets the library character's
   voice, writes the next version (`source = "ai"`) and moves the project's pin to it
   (`character_looks.pin_new_version`); for the narrator it adds the next `narrator_voice` row.

Re-choosing by hand is the Character Lab's own 3-sample audition: it writes a `manual` version
and never moves a pin. The narrator can be chosen by hand from the saved voices
(`choose_narrator`), which adds a `manual` version.

- A character reused from the project's cast (PHASE-048) that has no voice job in this project,
  and whose pinned version already holds a saved voice, is `ready` with that voice: nothing is
  designed for it and its voice is not replaced.
- `state` is what the story workspace shows for the characters, and `narrator_state` for the
  narrator. **All of it is worked out on every read** from the jobs, the runs and the saved
  voices and is never stored (D-3): a voice is `in_progress` while its description or its
  sample is being made, `failed` when one of them failed, `ready` when its voice is saved, and
  `out_of_date` when the facts it was designed from have changed since.
- `start_run` and `start_all` start characters; `start_narrator` starts the narrator.
  `start_all` also starts the narrator when it has no voice, failed, or has an `ai` voice that
  is out of date, and leaves a narrator chosen by hand alone.

Every job and run records its provenance: the run's `inputs` hold the project, the discovered
character, the library character, its pinned version and a hash of the facts the description was
written from (`voice_facts_sha256`); for the narrator, the StoryBible version and a hash of the
narration facts (`narration_sha256`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Job,
    LabVoiceRun,
    LibraryCharacter,
    NarratorVoice,
    Project,
    ProjectCharacterLink,
    StoryBible,
    Voice,
)
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.jobs import store
from app.services import (
    character_definitions,
    character_looks,
    character_versions,
    project_cast,
    story_bible,
    voice_design_writer,
    voice_lab,
    voices,
)
from app.services.character_definitions import EntryDefinition
from app.services.character_links import LinkInfo
from app.services.voice_lab import VoiceLabForm, VoiceLabInputError

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "design_voice"
# Two presses on one voice make one job; two voices run side by side.
DEDUPE_KEY: Final = "target"
NARRATOR_TARGET: Final = "narrator"

# How many of a project's newest voice jobs are read to find each voice's newest one.
_JOB_LOOKBACK: Final = 500

# The run's job finishes (the speech is stored) a moment before the voice is saved. A run that
# finished less than this long ago and has no voice yet is still being saved, not failed.
_SAVE_GRACE_S: Final = 30.0

# `unavailable`: no voice yet, and one cannot be made (see `blocked_reason`).
# `none`: no voice yet, and one can be made.
# `in_progress`: the description or the sample is being made. `failed`: one of them failed.
# `ready`: a voice is saved. `out_of_date`: saved, but designed from older facts.
Status = Literal["unavailable", "none", "in_progress", "failed", "ready", "out_of_date"]
# Where an `in_progress` voice is: the model is writing the description, or the sample is being
# made (and saved).
Stage = Literal["writing_description", "making_sample"]

_ALREADY_BEING_MADE: Final = "The voice is already being made."


class StoryVoiceError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class _Progress:
    """Where one `design_voice` job stands, from the job, its run and the saved voice."""

    stage: Stage | None
    # The job, the run or the saving failed.
    failed: bool
    error: str | None
    # The description the model wrote, once it has.
    instruction: str | None
    run: LabVoiceRun | None
    # The saved voice, once there is one.
    voice: Voice | None


@dataclass(frozen=True)
class EntryVoice:
    """One entry of the newest list of characters and where its voice stands."""

    definition: EntryDefinition
    status: Status
    stage: Stage | None
    # The description the voice was designed from, once the model wrote it.
    instruction: str | None
    # The saved voice, once there is one.
    voice: Voice | None
    # Why a `failed` voice failed.
    error: str | None
    # Why a `ready` voice is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    can_run: bool
    blocked_reason: str | None
    # True for a character chosen from the library: a voice changes its voice, so the user is
    # asked first.
    needs_confirmation: bool
    # The newest voice job of this character, whatever its status.
    job: Job | None


@dataclass(frozen=True)
class VoicesState:
    """What the story workspace shows. `discovery_version` is None when no list exists."""

    discovery_version: int | None
    entries: list[EntryVoice]


@dataclass(frozen=True)
class NarratorState:
    """The narrator voice and where it stands."""

    status: Status
    stage: Stage | None
    # The newest version, and its saved voice (None when the voice is gone or there is no
    # version).
    version: NarratorVoice | None
    voice: Voice | None
    instruction: str | None
    error: str | None
    reasons: list[str]
    # The newest StoryBible version, which an `ai` voice is derived from.
    story_bible_version: int | None
    can_run: bool
    blocked_reason: str | None
    # True when the newest version was chosen by hand: deriving a voice replaces that choice,
    # so the user is asked first.
    needs_confirmation: bool
    job: Job | None


@dataclass(frozen=True)
class Skipped:
    """A voice that "Make voices for all" did not start, and why."""

    discovery_id: str
    name: str
    reason: str


@dataclass(frozen=True)
class StartAllResult:
    job_ids: list[int]
    skipped: list[Skipped]


# --- Reading jobs, runs and voices --------------------------------------------------------


def _job_error(job: Job, what: str) -> str:
    if job.error:
        return job.error
    return f"The {what} was cancelled." if job.status == "cancelled" else f"The {what} failed."


async def _voice_for_run(session: AsyncSession, run_id: int) -> Voice | None:
    statement = (
        select(Voice)
        .where(Voice.lab_voice_run_id == run_id)
        .order_by(Voice.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def _progress(session: AsyncSession, job: Job) -> _Progress:
    """Where one `design_voice` job stands."""
    if job.status in store.ACTIVE_STATUSES:
        return _Progress("writing_description", False, None, None, None, None)
    if job.status != "succeeded":
        return _Progress(None, True, _job_error(job, "voice description"), None, None, None)

    output = job.output if isinstance(job.output, dict) else {}
    recorded = output.get("instruction")
    instruction = recorded if isinstance(recorded, str) else None
    statement = (
        select(LabVoiceRun)
        .where(LabVoiceRun.design_job_id == job.id)
        .order_by(LabVoiceRun.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    run = (await session.execute(statement)).scalars().first()
    if run is None:
        return _Progress(None, True, "The sample was not started.", instruction, None, None)
    run_job = (
        await session.get(Job, run.job_id, populate_existing=True)
        if run.job_id is not None
        else None
    )
    if run_job is None:
        return _Progress(None, True, "The sample's job is gone.", instruction, run, None)
    if run_job.status in store.ACTIVE_STATUSES:
        return _Progress("making_sample", False, None, instruction, run, None)
    if run_job.status != "succeeded":
        error = f"The sample could not be made: {_job_error(run_job, 'sample')}"
        return _Progress(None, True, error, instruction, run, None)

    voice = await _voice_for_run(session, run.id)
    if voice is not None:
        return _Progress(None, False, None, instruction, run, voice)
    finished = run_job.finished_at
    if finished is None or (utcnow() - finished).total_seconds() < _SAVE_GRACE_S:
        return _Progress("making_sample", False, None, instruction, run, None)
    error = "The sample was made but could not be saved as a voice. Make it again."
    return _Progress(None, True, error, instruction, run, None)


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest voice job of each target (`character:{discovery_id}` or `narrator`)."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == JOB_TYPE)
        .order_by(Job.id.desc())
        .limit(_JOB_LOOKBACK)
        .execution_options(populate_existing=True)
    )
    newest: dict[str, Job] = {}
    for job in (await session.execute(statement)).scalars():
        target = job.input.get(DEDUPE_KEY) if isinstance(job.input, dict) else None
        if isinstance(target, str) and target not in newest:
            newest[target] = job
    return newest


def _character_target(discovery_id: str) -> str:
    return f"character:{discovery_id}"


# --- Characters: reading the state --------------------------------------------------------


def _start_refusal(entry: EntryDefinition) -> str | None:
    """Why a voice cannot be made for this entry now, or None when it can."""
    info = entry.entry.info
    name = entry.item["name"]
    if info is None:
        return f"'{name}' is not linked to a Character Lab character yet. Link it first."
    if info.character.archived:
        return f"{info.character.name} is archived. Unarchive it in the Character Lab first."
    if entry.job is not None and entry.job.status in store.ACTIVE_STATUSES:
        return "A definition is being written. Wait for it to finish."
    if entry.status == "not_defined":
        return (
            f"{name} has no definition yet. Define the character first: its voice is made from it."
        )
    if entry.status == "out_of_date":
        return f"The definition of {name} is out of date. Define the character again first."
    return None


def _character_reasons(run: LabVoiceRun, entry: EntryDefinition) -> list[str]:
    """Why a ready voice no longer matches the definition the project pins, if it does not."""
    definition = entry.definition
    if definition is None:
        return []
    inputs = run.inputs if isinstance(run.inputs, dict) else {}
    facts = voice_design_writer.voice_facts(definition)
    if inputs.get("voice_facts_sha256") != voice_design_writer.facts_sha256(facts):
        return ["The character's voice definition has changed since this voice was made."]
    return []


async def _reused_voice(
    session: AsyncSession, info: LinkInfo, modes: dict[int, project_cast.Mode]
) -> Voice | None:
    """The saved voice of a reused character's pinned version, or None when the character is not
    reused or its pinned version has no voice.
    """
    if project_cast.reuse_mode(modes, info.character.id, info.link.how) is None:
        return None
    version = await character_versions.get_version(
        session, info.character.id, info.link.pinned_version
    )
    if version is None or version.voice_id is None:
        return None
    return await session.get(Voice, version.voice_id)


async def state(session: AsyncSession, project: Project) -> VoicesState:
    """The newest list of characters with where each one's voice stands. Worked out on every
    read; nothing here is stored.
    """
    definitions = await character_definitions.state(session, project)
    jobs = await _newest_jobs(session, project.id)
    modes = await project_cast.cast_modes(session, project.id, "characters")
    entries: list[EntryVoice] = []
    for entry in definitions.entries:
        info = entry.entry.info
        job = jobs.get(_character_target(entry.item["id"]))
        if job is not None and (
            info is None
            or not isinstance(job.input, dict)
            or job.input.get("character_id") != info.character.id
        ):
            # Made for another library character this entry used to be linked to.
            job = None
        progress = await _progress(session, job) if job is not None else None
        refusal = _start_refusal(entry)

        status: Status
        reasons: list[str] = []
        reused_voice = (
            await _reused_voice(session, info, modes) if progress is None and info else None
        )
        if reused_voice is not None:
            status = "ready"
        elif progress is None:
            status = "none" if refusal is None else "unavailable"
        elif progress.stage is not None:
            status = "in_progress"
        elif progress.failed or progress.run is None:
            status = "failed"
        else:
            reasons = _character_reasons(progress.run, entry)
            status = "out_of_date" if reasons else "ready"

        blocked = refusal
        if blocked is None and status == "in_progress":
            blocked = _ALREADY_BEING_MADE
        entries.append(
            EntryVoice(
                definition=entry,
                status=status,
                stage=progress.stage if progress is not None else None,
                instruction=progress.instruction if progress is not None else None,
                voice=progress.voice if progress is not None else reused_voice,
                error=progress.error if progress is not None and progress.failed else None,
                reasons=reasons,
                can_run=blocked is None,
                blocked_reason=blocked,
                needs_confirmation=entry.needs_confirmation,
                job=job,
            )
        )
    return VoicesState(discovery_version=definitions.discovery_version, entries=entries)


# --- Characters: starting runs ------------------------------------------------------------


async def _queue_character(
    session: AsyncSession, project: Project, item: EntryVoice
) -> tuple[Job, bool]:
    """Queues the job for one entry that `can_run`, and returns `(job, created)`. Commits."""
    entry = item.definition
    info = entry.entry.info
    definition = entry.definition
    assert info is not None and definition is not None  # `_start_refusal` made sure
    discovery_id = entry.item["id"]
    facts = voice_design_writer.voice_facts(definition)
    inputs = {
        "project_id": project.id,
        "discovery_id": discovery_id,
        "character_id": info.character.id,
        "character_version": info.link.pinned_version,
        "voice_facts_sha256": voice_design_writer.facts_sha256(facts),
    }
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "target": _character_target(discovery_id),
            "subject": "character",
            "project_id": project.id,
            "discovery_id": discovery_id,
            "character_id": info.character.id,
            "name": entry.item["name"],
            "facts": facts,
            "line": voice_design_writer.CHARACTER_LINE,
            # Written on the sample's run, and from there on the voice (D-3).
            "inputs": inputs,
        },
        dedupe_key=DEDUPE_KEY,
    )
    if created:
        _logger.info(
            "project %d: voice started for '%s': character=%d job=%d",
            project.id,
            discovery_id,
            info.character.id,
            job.id,
        )
    return job, created


async def start_run(
    session: AsyncSession,
    project: Project,
    discovery_id: str,
    *,
    confirm_overwrite: bool = False,
) -> tuple[Job, bool]:
    """Starts the voice of one character, and commits. Returns `(job, created)`: when the
    character's voice is already being made, that job is returned and `created` is False.

    A character the user chose from the library (`mapped`) is changed only when
    `confirm_overwrite` is true. Raises StoryVoiceError.
    """
    result = await state(session, project)
    item = next((e for e in result.entries if e.definition.item["id"] == discovery_id), None)
    if item is None:
        raise StoryVoiceError(
            f"There is no character '{discovery_id}' in the newest list of characters."
        )
    if item.status == "in_progress" and item.job is not None:
        return item.job, False
    if item.blocked_reason is not None:
        raise StoryVoiceError(item.blocked_reason)
    if item.needs_confirmation and not confirm_overwrite:
        name = item.definition.item["name"]
        raise StoryVoiceError(
            f"{name} was chosen from the Character Lab. Making a voice for it replaces its "
            "voice, so it has to be confirmed."
        )
    return await _queue_character(session, project, item)


def _skip_reason(item: EntryVoice) -> str | None:
    """Why "Make voices for all" leaves this character alone, or None when it starts it."""
    if item.status == "in_progress":
        return "Already being made."
    if item.blocked_reason is not None:
        return item.blocked_reason
    if item.needs_confirmation:
        return "Chosen from the Character Lab: make its voice on its own, which asks first."
    if item.status == "ready":
        return "Already has a voice. Use Make again to replace it."
    return None


async def start_all(session: AsyncSession, project: Project) -> StartAllResult:
    """Starts a voice for every defined character the pipeline made that has none yet, whose
    voice failed or whose voice is out of date, and for the narrator when it has none, failed
    or has an `ai` voice out of date. Everything else is skipped, with the reason. Commits each.
    Raises StoryVoiceError when there is no list of characters and the narrator cannot start
    either.
    """
    result = await state(session, project)
    narrator = await narrator_state(session, project)
    narrator_reason = _narrator_skip_reason(narrator)
    if result.discovery_version is None and narrator_reason is not None:
        raise StoryVoiceError("Find the characters first: there is nothing to give a voice yet.")

    job_ids: list[int] = []
    skipped: list[Skipped] = []
    for item in result.entries:
        entry_id = item.definition.item["id"]
        name = item.definition.item["name"]
        reason = _skip_reason(item)
        if reason is not None:
            skipped.append(Skipped(entry_id, name, reason))
            continue
        job, created = await _queue_character(session, project, item)
        if created:
            job_ids.append(job.id)
        else:
            skipped.append(Skipped(entry_id, name, "Already being made."))

    if narrator_reason is not None:
        skipped.append(Skipped(NARRATOR_TARGET, "Narrator", narrator_reason))
    else:
        job, created = await _queue_narrator(session, project)
        if created:
            job_ids.append(job.id)
        else:
            skipped.append(Skipped(NARRATOR_TARGET, "Narrator", "Already being made."))
    return StartAllResult(job_ids=job_ids, skipped=skipped)


# --- The narrator -------------------------------------------------------------------------


def _narrator_blocked(story: str | None, bible: StoryBible | None) -> str | None:
    """Why a narrator voice cannot be derived from this story and StoryBible, or None."""
    if story is None or not story.strip():
        return "Save the story first: the narrator reads its opening."
    if bible is None:
        return "Run the Story Bible first: the narrator's voice follows its storytelling style."
    if story_bible.is_out_of_date(story, bible):
        return (
            "The Story Bible is out of date, because the story has changed since it was "
            "written. Re-run the Story Bible first."
        )
    return None


async def _newest_narrator(session: AsyncSession, project_id: int) -> NarratorVoice | None:
    """The newest narrator voice version of the project, or None."""
    statement = (
        select(NarratorVoice)
        .where(NarratorVoice.project_id == project_id)
        .order_by(NarratorVoice.version.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def narrator_versions(session: AsyncSession, project_id: int) -> list[NarratorVoice]:
    """Every narrator voice version of the project, newest first."""
    statement = (
        select(NarratorVoice)
        .where(NarratorVoice.project_id == project_id)
        .order_by(NarratorVoice.version.desc())
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars())


async def narrator_state(session: AsyncSession, project: Project) -> NarratorState:
    """The narrator voice and where it stands. Worked out on every read; nothing is stored."""
    bible = await story_bible.latest(session, project.id)
    blocked = _narrator_blocked(project.script_text, bible)
    version = await _newest_narrator(session, project.id)
    voice = (
        await session.get(Voice, version.voice_id)
        if version is not None and version.voice_id is not None
        else None
    )
    job = (await _newest_jobs(session, project.id)).get(NARRATOR_TARGET)

    # A job counts only when it came after the newest version and did not make it: a job that
    # made the newest version is that version, and one a hand choice came after is forgotten.
    pending = (
        job
        if job is not None
        and (version is None or (version.job_id != job.id and job.created_at > version.created_at))
        else None
    )
    progress = await _progress(session, pending) if pending is not None else None

    status: Status
    stage: Stage | None = None
    error: str | None = None
    reasons: list[str] = []
    instruction: str | None = None
    if progress is not None and progress.stage is not None:
        status, stage, instruction = "in_progress", progress.stage, progress.instruction
    elif progress is not None and progress.failed:
        status, error, instruction = "failed", progress.error, progress.instruction
    elif version is None:
        status = "unavailable" if blocked is not None else "none"
    else:
        status = "ready"
        if version.source == "ai":
            made_by = await session.get(Job, version.job_id) if version.job_id is not None else None
            output = made_by.output if made_by is not None else None
            recorded = output.get("instruction") if isinstance(output, dict) else None
            instruction = recorded if isinstance(recorded, str) else None
            facts = voice_design_writer.narrator_facts(bible.content) if bible is not None else None
            inputs = version.inputs if isinstance(version.inputs, dict) else {}
            if facts is not None and inputs.get("narration_sha256") != (
                voice_design_writer.facts_sha256(facts)
            ):
                reasons = [
                    "The Story Bible's narration style has changed since this voice was made."
                ]
                status = "out_of_date"

    refusal = blocked
    if refusal is None and status == "in_progress":
        refusal = _ALREADY_BEING_MADE
    return NarratorState(
        status=status,
        stage=stage,
        version=version,
        voice=voice,
        instruction=instruction,
        error=error,
        reasons=reasons,
        story_bible_version=bible.version if bible is not None else None,
        can_run=refusal is None,
        blocked_reason=refusal,
        needs_confirmation=version is not None and version.source == "manual",
        job=job,
    )


def _narrator_skip_reason(narrator: NarratorState) -> str | None:
    """Why "Make voices for all" leaves the narrator alone, or None when it starts it."""
    if narrator.status == "in_progress":
        return "Already being made."
    if narrator.blocked_reason is not None:
        return narrator.blocked_reason
    if narrator.needs_confirmation:
        return "Chosen by hand: derive it on its own, which asks first."
    if narrator.status == "ready":
        return "Already has a voice. Use Make again to replace it."
    return None


async def _queue_narrator(session: AsyncSession, project: Project) -> tuple[Job, bool]:
    """Queues the job that derives the narrator's voice from the newest StoryBible, and
    commits. Returns `(job, created)`. The caller has checked `_narrator_blocked`.
    """
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    assert story is not None and bible is not None  # `_narrator_blocked` made sure
    facts = voice_design_writer.narrator_facts(bible.content)
    inputs = {
        "project_id": project.id,
        "story_bible_version": bible.version,
        "narration_sha256": voice_design_writer.facts_sha256(facts),
    }
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "target": NARRATOR_TARGET,
            "subject": "narrator",
            "project_id": project.id,
            "discovery_id": None,
            "character_id": None,
            "name": "Narrator",
            "facts": facts,
            "line": voice_design_writer.opening_line(story),
            "inputs": inputs,
        },
        dedupe_key=DEDUPE_KEY,
    )
    if created:
        _logger.info("project %d: narrator voice started: job=%d", project.id, job.id)
    return job, created


async def start_narrator(
    session: AsyncSession, project: Project, *, confirm_replace_manual: bool = False
) -> tuple[Job, bool]:
    """Starts deriving the narrator's voice from the StoryBible, and commits. Returns
    `(job, created)`: when one is already being made, that job is returned and `created` is
    False. A narrator chosen by hand is replaced only when `confirm_replace_manual` is true.
    Raises StoryVoiceError.
    """
    narrator = await narrator_state(session, project)
    if narrator.status == "in_progress" and narrator.job is not None:
        return narrator.job, False
    if narrator.blocked_reason is not None:
        raise StoryVoiceError(narrator.blocked_reason)
    if narrator.needs_confirmation and not confirm_replace_manual:
        raise StoryVoiceError(
            "The narrator's voice was chosen by hand. Deriving one from the Story Bible "
            "replaces that choice, so it has to be confirmed."
        )
    return await _queue_narrator(session, project)


async def choose_narrator(session: AsyncSession, project: Project, voice_id: int) -> NarratorVoice:
    """Makes a saved voice the narrator's, as a new `manual` version, and commits. Choosing the
    voice a hand choice already holds changes nothing. Raises StoryVoiceError.
    """
    if await session.get(Voice, voice_id) is None:
        raise StoryVoiceError(f"There is no saved voice {voice_id}.")
    newest = await _newest_narrator(session, project.id)
    if newest is not None and newest.source == "manual" and newest.voice_id == voice_id:
        return newest
    row = await _add_narrator_version(
        session, project.id, source="manual", voice_id=voice_id, job_id=None, inputs={}
    )
    await session.commit()
    _logger.info(
        "project %d: narrator voice chosen: voice=%d version=%d", project.id, voice_id, row.version
    )
    return row


async def _add_narrator_version(
    session: AsyncSession,
    project_id: int,
    *,
    source: str,
    voice_id: int,
    job_id: int | None,
    inputs: dict[str, Any],
) -> NarratorVoice:
    """Adds the next narrator version. Flushes, never commits."""
    statement = select(func.max(NarratorVoice.version)).where(
        NarratorVoice.project_id == project_id
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = NarratorVoice(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=source,
        voice_id=voice_id,
        job_id=job_id,
        inputs=inputs,
    )
    session.add(row)
    await session.flush()
    return row


# --- The two steps after the description --------------------------------------------------


async def queue_sample(
    session: AsyncSession, job_id: int, job_input: dict[str, Any], instruction: str
) -> int:
    """Queues the one design-mode Voice lab run that reads the job's line in a voice made from
    `instruction`, marks it as the story pipeline's (project, subject, character, job,
    provenance), and returns its id. Flushes but does not commit: the job commits it together
    with finishing itself, so a description is never "done" without its sample. Raises
    StoryVoiceError.
    """
    line = job_input.get("line")
    subject = job_input.get("subject")
    project_id = job_input.get("project_id")
    inputs = job_input.get("inputs")
    if (
        not isinstance(line, str)
        or subject not in ("character", "narrator")
        or not isinstance(project_id, int)
        or not isinstance(inputs, dict)
    ):
        raise StoryVoiceError("The job does not say what the sample should say.")
    discovery_id = job_input.get("discovery_id")
    form = VoiceLabForm(
        mode="design",
        text=line,
        instruction=instruction,
        voice_id=None,
        seed=None,
        cfg_scale=None,
    )
    try:
        row = await voice_lab.create_run(session, form, commit=False)
    except VoiceLabInputError as exc:
        raise StoryVoiceError(str(exc)) from exc
    run = row.run
    run.project_id = project_id
    run.subject = subject
    run.discovery_id = discovery_id if isinstance(discovery_id, str) else None
    run.design_job_id = job_id
    run.inputs = inputs
    await session.flush()
    return run.id


def _voice_name(label: str, project: Project) -> str:
    """The saved voice's name, cut to the length a voice name may have."""
    name = f"{label} ({project.name})"
    return name if len(name) <= voices.NAME_MAX_CHARS else name[: voices.NAME_MAX_CHARS - 1] + "…"


async def on_voice_finished(run_id: int) -> bool:
    """Called (best effort) once a Voice lab speech has been stored. When it is the sample the
    story pipeline made for a character or the narrator, saves it as a voice and attaches it in
    one transaction (see the module text). Returns True when a voice was saved. Does nothing
    (False) for any other run, for a speech already saved, and for a character whose link no
    longer points at the library character the sample was made for.
    """
    async with SessionLocal() as session:
        run = await session.get(LabVoiceRun, run_id)
        if (
            run is None
            or run.project_id is None
            or run.subject is None
            or run.path is None
            or await _voice_for_run(session, run.id) is not None
        ):
            await session.commit()
            return False
        project = await session.get(Project, run.project_id)
        if project is None:
            await session.commit()
            return False
        inputs = run.inputs if isinstance(run.inputs, dict) else {}

        if run.subject == "narrator":
            voice = await voices.create_from_run(
                session, run.id, _voice_name("Narrator", project), None, commit=False
            )
            await _add_narrator_version(
                session,
                project.id,
                source="ai",
                voice_id=voice.id,
                job_id=run.design_job_id,
                inputs=inputs,
            )
            await session.commit()
            _logger.info("project %d: narrator voice saved: voice=%d", project.id, voice.id)
            return True

        link_statement = select(ProjectCharacterLink).where(
            ProjectCharacterLink.project_id == project.id,
            ProjectCharacterLink.discovery_id == run.discovery_id,
        )
        link = (await session.execute(link_statement)).scalars().first()
        character = (
            await session.get(LibraryCharacter, link.character_id) if link is not None else None
        )
        if link is None or character is None or link.character_id != inputs.get("character_id"):
            # The link was removed or moved to another character while the sample was made.
            await session.commit()
            _logger.warning("run %d: its character is no longer linked; no voice saved", run.id)
            return False
        voice = await voices.create_from_run(
            session, run.id, _voice_name(character.name, project), None, commit=False
        )
        character.voice_id = voice.id
        character.updated_at = utcnow()
        pinned = await character_looks.pin_new_version(
            session,
            project_id=project.id,
            discovery_id=link.discovery_id,
            character=character,
            job_id=run.design_job_id,
        )
        await session.commit()
        _logger.info(
            "project %d: voice %d saved for character %d, pinned at version %s",
            project.id,
            voice.id,
            character.id,
            pinned,
        )
        return True
