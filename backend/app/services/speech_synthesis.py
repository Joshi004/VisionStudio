"""The Speech stage of a story project: every speech unit spoken in the right voice (PHASE-019,
`Path_ahead.md` Sections 20 and 21).

Each unit planned by PHASE-018 (`services/speech_units`) is spoken by one `synthesize_speech_unit`
job (`jobs/synthesize_speech_unit.py`, Breeze TTS on the GPU server). The job's WAV is stored and
its length **measured** with ffprobe, so timing comes from real audio and needs no transcription.

- **The voice.** Dialogue uses the saved voice of the speaker's library character at the version
  the project pins (PHASE-011). Narration uses the project's newest narrator voice. A unit whose
  voice does not exist cannot be made, and the reason says which voice to make first.
- **The mode** (a planning decision). A unit with a delivery emotion is **directed**: the saved
  voice reads the text, steered by a short instruction written here from the emotion. A unit with
  none is **cloned**: the saved voice reads the text as it is.
- **The key.** `audio_key` is a hash of the text, the voice, the mode and the instruction, never of
  the unit's id, which a new plan renumbers. A unit whose key already has audio is not made again,
  so a plan with one changed line makes only that line.
- `state` is what the story workspace shows. **Everything in it is worked out on every read** and
  never stored (D-3): a unit is `in_progress` while its newest job runs, `failed` when that job
  failed, `ready` when audio exists for its key, `out_of_date` when audio exists only for what the
  unit used to be (the reasons say what changed), and `none` when it has never been made.
- A scene's units can be made only while the scene's plan is current.

**A continuous explainer** (`project.voice_track`, FLOW-003) speaks each scene as one **take**
instead: the scene's unit texts joined with one space, so it reads exactly as the script, in the
presenter's voice (the narrator's, E-4), in `direction` mode with the project's presenter
delivery as the one instruction and guidance 4. A take is a `speech_unit_audio` row with kind
`take` and no unit; its key is a hash of the joined text, the voice and the instruction (never
equal to a unit's key), so an unchanged scene is not made again and one changed line makes only
its scene's take out of date. The units of such a project are not spoken one by one. A `lines`
project and a story never have a take and are unchanged.

`start_unit`, `start_take` and `start_all` queue the jobs and write one `speech_unit_audio` row
per job, in one transaction.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass, replace
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Job,
    LibraryCharacterVersion,
    Project,
    SpeechUnitAudio,
    Voice,
)
from app.db.state_memo import memoized_state
from app.jobs import store
from app.providers import speech_synthesizer
from app.services import (
    character_links,
    explainer,
    projects,
    speech_chunks,
    speech_units,
    story_voices,
)

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "synthesize_speech_unit"
# The `kind` of a scene's take (FLOW-003). A unit's is `narration` or `dialogue`.
KIND_TAKE: Final = "take"
TAKE_MODE: Final = "direction"
# Two presses on one line in one voice make one job.
DEDUPE_KEY: Final = "target"

# `unavailable`: cannot be made now (no voice, or no current plan). `none`: never made.
# `in_progress`: its job is queued or running. `failed`: its newest job failed. `ready`: audio
# exists for what the unit is now. `out_of_date`: audio exists only for what it used to be.
Status = Literal["unavailable", "none", "in_progress", "failed", "ready", "out_of_date"]

_ALREADY_BEING_MADE: Final = "The speech is already being made."
_SPOKEN_AS_TAKE: Final = "This explainer speaks each scene as one take. Make the scene's take."


class SpeechSynthesisError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class _VoiceChoice:
    """The voice a speaker has, or the reason it has none."""

    voice: Voice | None
    # What the audio's `inputs` record about where the voice came from.
    source: dict[str, Any]
    refusal: str | None


@dataclass(frozen=True)
class UnitEntry:
    """One speech unit and where its audio stands."""

    unit: dict[str, Any]
    status: Status
    # Why out-of-date audio no longer matches the unit, one sentence each.
    reasons: list[str]
    # The voice the unit is spoken in now, when it exists.
    voice: Voice | None
    mode: str | None
    instruction: str | None
    # The newest stored audio of the unit's key, when there is some (it plays even while a new
    # one is being made).
    audio: SpeechUnitAudio | None
    error: str | None
    can_run: bool
    blocked_reason: str | None
    job: Job | None


@dataclass(frozen=True)
class TakeEntry:
    """One scene's take of a continuous explainer and where its audio stands (FLOW-003)."""

    # The scene's unit texts joined: what the take says.
    text: str
    status: Status
    # Why out-of-date audio no longer matches the scene, one sentence each.
    reasons: list[str]
    voice: Voice | None
    # The delivery instruction every take of the project uses.
    instruction: str
    # The newest stored audio of the take's key, when there is some.
    audio: SpeechUnitAudio | None
    error: str | None
    can_run: bool
    blocked_reason: str | None
    job: Job | None


@dataclass(frozen=True)
class SceneAudio:
    """One scene of the newest list, with its plan and the audio of each of its units. A
    continuous explainer's scene also has its `take`; it is None for any other project and for a
    scene with no units.
    """

    scene: speech_units.SceneEntry
    units: list[UnitEntry]
    take: TakeEntry | None = None


@dataclass(frozen=True)
class AudioState:
    """What the story workspace shows. `scenes_version` is None when no list exists.
    `continuous` is true for a continuous explainer, whose scenes are spoken as takes.
    """

    scenes_version: int | None
    scenes: list[SceneAudio]
    # Why nothing can be made yet, or None.
    blocked_reason: str | None
    # The narrator's voice, and each discovered character's by its discovery id.
    narrator: _VoiceChoice
    characters: dict[str, _VoiceChoice]
    continuous: bool = False


@dataclass(frozen=True)
class Skipped:
    """A unit that "Make all" did not start, and why. `unit_id` is None for a scene's take."""

    scene_id: str
    unit_id: str | None
    reason: str


@dataclass(frozen=True)
class StartAllResult:
    job_ids: list[int]
    skipped: list[Skipped]


# --- Pure helpers -------------------------------------------------------------------------


def delivery_emotion(unit: dict[str, Any]) -> str | None:
    """The unit's delivery emotion, or None when it has none."""
    delivery = unit.get("delivery")
    if not isinstance(delivery, dict):
        return None
    emotion = delivery.get("emotion")
    if isinstance(emotion, str) and emotion.strip():
        return emotion.strip()
    return None


def choose_mode(unit: dict[str, Any]) -> Literal["clone", "direction"]:
    """Direction when the unit has a delivery emotion, otherwise clone."""
    return "direction" if delivery_emotion(unit) is not None else "clone"


def instruction_for(unit: dict[str, Any]) -> str | None:
    """The instruction that steers a directed unit, written from its emotion. None for a clone."""
    emotion = delivery_emotion(unit)
    if emotion is None:
        return None
    return f"Speak with this emotion: {emotion}."[: speech_synthesizer.INSTRUCTION_MAX_CHARS]


def audio_key(text: str, voice_id: int, mode: str, instruction: str | None) -> str:
    """The hash of what a unit's audio depends on."""
    recorded = json.dumps(
        {"text": text, "voice_id": voice_id, "mode": mode, "instruction": instruction},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(recorded.encode("utf-8")).hexdigest()


def is_continuous(project: Project) -> bool:
    """Whether the project speaks each scene as one take (FLOW-003)."""
    return project.voice_track == projects.VOICE_CONTINUOUS


def take_text(units: list[dict[str, Any]]) -> str:
    """What a scene's take says: its unit texts in order, joined with one space. Units are slices
    of the script, so nothing is added: a unit that ends at a comma stays a comma.
    """
    return " ".join(str(unit["text"]).strip() for unit in units)


def take_key(text: str, voice_id: int, instruction: str) -> str:
    """The hash of what a scene's take depends on. It records that it is a take, so it can never
    equal a unit's key even when a scene has one unit that says the same.
    """
    recorded = json.dumps(
        {
            "take": True,
            "text": text,
            "voice_id": voice_id,
            "mode": TAKE_MODE,
            "instruction": instruction,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(recorded.encode("utf-8")).hexdigest()


# --- Voices -------------------------------------------------------------------------------


async def _narrator_choice(session: AsyncSession, project: Project) -> _VoiceChoice:
    versions = await story_voices.narrator_versions(session, project.id)
    newest = versions[0] if versions else None
    voice = (
        await session.get(Voice, newest.voice_id)
        if newest is not None and newest.voice_id is not None
        else None
    )
    if newest is None or voice is None:
        return _VoiceChoice(
            None,
            {},
            "The narrator has no voice yet. Make it under Narrator voice first.",
        )
    return _VoiceChoice(voice, {"kind": "narrator", "narrator_voice_version": newest.version}, None)


async def _character_choices(
    session: AsyncSession, project: Project, names: dict[str, str]
) -> dict[str, _VoiceChoice]:
    """The voice of each discovered character, by its discovery id."""
    links = await character_links.state(session, project.id)
    choices: dict[str, _VoiceChoice] = {}
    for entry in links.entries:
        discovery_id = entry.item["id"]
        name = names.get(discovery_id, entry.item.get("name", discovery_id))
        info = entry.info
        if info is None:
            choices[discovery_id] = _VoiceChoice(
                None, {}, f"'{name}' is not linked to a Character Lab character yet. Link it first."
            )
            continue
        statement = select(LibraryCharacterVersion).where(
            LibraryCharacterVersion.character_id == info.character.id,
            LibraryCharacterVersion.version == info.link.pinned_version,
        )
        version = (await session.execute(statement)).scalars().first()
        voice = (
            await session.get(Voice, version.voice_id)
            if version is not None and version.voice_id is not None
            else None
        )
        if voice is None:
            choices[discovery_id] = _VoiceChoice(
                None,
                {},
                f"{name} has no saved voice. Make it under Character voices first.",
            )
            continue
        choices[discovery_id] = _VoiceChoice(
            voice,
            {
                "kind": "character",
                "discovery_id": discovery_id,
                "character_id": info.character.id,
                "pinned_version": info.link.pinned_version,
            },
            None,
        )
    return choices


def _choice_for(
    unit: dict[str, Any], narrator: _VoiceChoice, characters: dict[str, _VoiceChoice]
) -> _VoiceChoice:
    """The voice that speaks this unit."""
    if unit["kind"] == "narration":
        return narrator
    return characters.get(unit["speaker_id"]) or _VoiceChoice(
        None, {}, f"The speaker '{unit['speaker_id']}' is not in the story's cast."
    )


# --- Reading the state --------------------------------------------------------------------


async def _all_audio(session: AsyncSession, project_id: int) -> list[SpeechUnitAudio]:
    """Every audio row of the project, the newest first."""
    statement = (
        select(SpeechUnitAudio)
        .where(SpeechUnitAudio.project_id == project_id)
        .order_by(SpeechUnitAudio.id.desc())
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars())


async def _jobs_of(session: AsyncSession, rows: list[SpeechUnitAudio]) -> dict[int, Job]:
    """The jobs of the rows that are not stored yet, by id."""
    job_ids = {row.job_id for row in rows if row.path is None and row.job_id is not None}
    if not job_ids:
        return {}
    statement = select(Job).where(Job.id.in_(job_ids)).execution_options(populate_existing=True)
    return {job.id: job for job in (await session.execute(statement)).scalars()}


def _job_error(job: Job | None) -> str:
    if job is None:
        return "The speech's job is gone. Make it again."
    if job.status == "succeeded":
        return "The speech was made but not stored. Make it again."
    if job.error:
        return job.error
    return "The speech was cancelled." if job.status == "cancelled" else "The speech failed."


def _reasons(
    previous: SpeechUnitAudio,
    text: str,
    voice_id: int,
    mode: str,
    instruction: str | None,
    speaker: str,
) -> list[str]:
    """Why audio made for the unit earlier no longer matches it. `speaker` is who speaks it
    ("The narrator", or the character's name), so the reason says whose voice changed.
    """
    reasons: list[str] = []
    if previous.text != text:
        reasons.append("The text of this unit has changed since the speech was made.")
    if previous.voice_id != voice_id:
        reasons.append(f"{speaker}'s voice has changed since the speech was made.")
    if previous.mode != mode or previous.instruction != instruction:
        reasons.append("The delivery has changed since the speech was made.")
    return reasons or ["This unit has changed since the speech was made."]


def _unit_entry(
    unit: dict[str, Any],
    scene_id: str,
    scene_refusal: str | None,
    choice: _VoiceChoice,
    by_key: dict[str, list[SpeechUnitAudio]],
    by_unit: dict[tuple[str, str], list[SpeechUnitAudio]],
    jobs: dict[int, Job],
    speaker: str,
) -> UnitEntry:
    mode = choose_mode(unit)
    instruction = instruction_for(unit)
    voice = choice.voice
    if voice is None:
        return UnitEntry(
            unit=unit,
            status="unavailable",
            reasons=[],
            voice=None,
            mode=mode,
            instruction=instruction,
            audio=None,
            error=None,
            can_run=False,
            blocked_reason=choice.refusal,
            job=None,
        )

    text = unit["text"].strip()
    key = audio_key(text, voice.id, mode, instruction)
    rows = by_key.get(key, [])
    stored = next((row for row in rows if row.path is not None), None)
    newest = rows[0] if rows else None
    newest_job = jobs.get(newest.job_id) if newest is not None and newest.job_id else None

    status: Status
    reasons: list[str] = []
    error: str | None = None
    if (
        newest is not None
        and newest.path is None
        and (newest_job is not None and newest_job.status in store.ACTIVE_STATUSES)
    ):
        status = "in_progress"
    elif stored is not None:
        status = "ready"
    elif newest is not None:
        status, error = "failed", _job_error(newest_job)
    else:
        earlier = next(
            (row for row in by_unit.get((scene_id, unit["id"]), []) if row.path is not None), None
        )
        if earlier is None:
            status = "none"
        else:
            status = "out_of_date"
            reasons = _reasons(earlier, text, voice.id, mode, instruction, speaker)

    blocked = scene_refusal
    if blocked is None and status == "in_progress":
        blocked = _ALREADY_BEING_MADE
    return UnitEntry(
        unit=unit,
        status=status,
        reasons=reasons,
        voice=voice,
        mode=mode,
        instruction=instruction,
        audio=stored,
        error=error,
        can_run=blocked is None,
        blocked_reason=blocked,
        job=newest_job,
    )


def _take_reasons(
    previous: SpeechUnitAudio, text: str, voice_id: int, instruction: str
) -> list[str]:
    """Why a take made for the scene earlier no longer matches it."""
    reasons: list[str] = []
    if previous.text != text:
        reasons.append("The text of this scene has changed since the take was made.")
    if previous.voice_id != voice_id:
        reasons.append("The presenter's voice has changed since the take was made.")
    if previous.instruction != instruction:
        reasons.append("The delivery has changed since the take was made.")
    return reasons or ["This scene has changed since the take was made."]


def _take_entry(
    text: str,
    instruction: str,
    scene_refusal: str | None,
    choice: _VoiceChoice,
    by_key: dict[str, list[SpeechUnitAudio]],
    earlier_takes: list[SpeechUnitAudio],
    jobs: dict[int, Job],
) -> TakeEntry:
    """The take of one scene. It follows the rules of `_unit_entry`."""
    voice = choice.voice
    if voice is None:
        return TakeEntry(
            text=text,
            status="unavailable",
            reasons=[],
            voice=None,
            instruction=instruction,
            audio=None,
            error=None,
            can_run=False,
            blocked_reason=choice.refusal,
            job=None,
        )

    rows = by_key.get(take_key(text, voice.id, instruction), [])
    stored = next((row for row in rows if row.path is not None), None)
    newest = rows[0] if rows else None
    newest_job = jobs.get(newest.job_id) if newest is not None and newest.job_id else None

    status: Status
    reasons: list[str] = []
    error: str | None = None
    if (
        newest is not None
        and newest.path is None
        and (newest_job is not None and newest_job.status in store.ACTIVE_STATUSES)
    ):
        status = "in_progress"
    elif stored is not None:
        status = "ready"
    elif newest is not None:
        status, error = "failed", _job_error(newest_job)
    else:
        earlier = next((row for row in earlier_takes if row.path is not None), None)
        if earlier is None:
            status = "none"
        else:
            status = "out_of_date"
            reasons = _take_reasons(earlier, text, voice.id, instruction)

    blocked = scene_refusal
    if blocked is None and status == "in_progress":
        blocked = _ALREADY_BEING_MADE
    return TakeEntry(
        text=text,
        status=status,
        reasons=reasons,
        voice=voice,
        instruction=instruction,
        audio=stored,
        error=error,
        can_run=blocked is None,
        blocked_reason=blocked,
        job=newest_job,
    )


def _scene_refusal(entry: speech_units.SceneEntry) -> str | None:
    """Why this scene's units cannot be made now, from its plan, or None."""
    if entry.row is None:
        return "Plan this scene's speech units first."
    if entry.status == "out_of_date":
        return "The speech units of this scene are out of date. Plan them again first."
    return None


@memoized_state
async def state(session: AsyncSession, project: Project) -> AudioState:
    """The newest list of scenes with the audio of each unit. Worked out on every read; nothing
    here is stored.
    """
    planned = await speech_units.state(session, project)
    names = {character["id"]: character["name"] for character in planned.characters}
    rows = await _all_audio(session, project.id)
    jobs = await _jobs_of(session, rows)
    by_key: dict[str, list[SpeechUnitAudio]] = {}
    by_unit: dict[tuple[str, str], list[SpeechUnitAudio]] = {}
    takes_by_scene: dict[str, list[SpeechUnitAudio]] = {}
    for row in rows:  # newest first, so each list is too
        by_key.setdefault(row.audio_key, []).append(row)
        if row.kind == KIND_TAKE:
            takes_by_scene.setdefault(row.scene_id, []).append(row)
        elif row.unit_id is not None:
            by_unit.setdefault((row.scene_id, row.unit_id), []).append(row)

    narrator = await _narrator_choice(session, project)
    characters = await _character_choices(session, project, names)
    continuous = is_continuous(project)
    # One instruction for every take of the project (FLOW-003, F-3).
    delivery = await explainer.presenter_delivery(session, project) if continuous else ""

    scenes: list[SceneAudio] = []
    for entry in planned.entries:
        content = entry.content
        units: list[UnitEntry] = []
        scene_refusal = planned.blocked_reason or _scene_refusal(entry)
        for unit in content["units"] if content is not None else []:
            choice = _choice_for(unit, narrator, characters)
            speaker = (
                "The narrator"
                if unit["kind"] == "narration"
                else str(names.get(unit["speaker_id"], unit["speaker_id"]))
            )
            units.append(
                _unit_entry(
                    unit, entry.item["id"], scene_refusal, choice, by_key, by_unit, jobs, speaker
                )
            )
        take: TakeEntry | None = None
        if continuous:
            # The units are not spoken one by one: the scene is, as one take.
            units = [
                replace(unit, can_run=False, blocked_reason=unit.blocked_reason or _SPOKEN_AS_TAKE)
                for unit in units
            ]
            if units:
                take = _take_entry(
                    take_text([unit.unit for unit in units]),
                    delivery,
                    scene_refusal,
                    narrator,
                    by_key,
                    takes_by_scene.get(entry.item["id"], []),
                    jobs,
                )
        scenes.append(SceneAudio(scene=entry, units=units, take=take))
    return AudioState(
        scenes_version=planned.scenes_version,
        scenes=scenes,
        blocked_reason=planned.blocked_reason,
        narrator=narrator,
        characters=characters,
        continuous=continuous,
    )


# --- Starting -----------------------------------------------------------------------------


def _find(current: AudioState, scene_id: str, unit_id: str) -> tuple[SceneAudio, UnitEntry]:
    scene = next((item for item in current.scenes if item.scene.item["id"] == scene_id), None)
    if scene is None:
        raise SpeechSynthesisError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    unit = next((item for item in scene.units if item.unit["id"] == unit_id), None)
    if unit is None:
        raise SpeechSynthesisError(f"Scene '{scene_id}' has no speech unit '{unit_id}'.")
    return scene, unit


async def _queue(
    session: AsyncSession,
    project: Project,
    scene: SceneAudio,
    item: UnitEntry,
    choice: _VoiceChoice,
) -> tuple[Job, bool]:
    """Queues the job and adds the audio row of one unit that `can_run`. Flushes, does not
    commit. Returns `(job, created)`: the job already making this very speech when it was not.
    """
    voice, mode, instruction = item.voice, item.mode, item.instruction
    assert voice is not None and mode is not None  # `can_run` made sure
    unit = item.unit
    text = unit["text"].strip()
    key = audio_key(text, voice.id, mode, instruction)
    plan_row = scene.scene.row
    assert plan_row is not None  # the scene refusal made sure
    cfg_scale = speech_synthesizer.default_cfg_scale(instruction)

    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="gpu",
        input={
            "requested": JOB_TYPE,
            DEDUPE_KEY: key,
            "project_id": project.id,
            "scene_id": scene.scene.item["id"],
            "unit_id": unit["id"],
            "mode": mode,
            "chunks": speech_chunks.split_script(text),
            "instruction": instruction,
            "seed": secrets.randbelow(speech_synthesizer.SEED_MAX + 1),
            "cfg_scale": cfg_scale,
            # What the job needs of the voice, copied now: a later edit changes nothing for it.
            "reference": {
                "voice_id": voice.id,
                "path": voice.path,
                "mime": voice.mime,
                "text": voice.transcript,
            },
        },
        commit=False,
        dedupe_key=DEDUPE_KEY,
    )
    if not created:
        return job, False

    speaker = unit["speaker_id"]
    session.add(
        SpeechUnitAudio(
            project_id=project.id,
            scene_id=scene.scene.item["id"],
            unit_id=unit["id"],
            kind=unit["kind"],
            speaker_id=speaker,
            text=text,
            mode=mode,
            instruction=instruction,
            voice_id=voice.id,
            audio_key=key,
            job_id=job.id,
            inputs={
                "project_id": project.id,
                "artifacts": [
                    {"kind": "speech_units", "id": plan_row.id, "version": plan_row.version}
                ],
                "voice": choice.source,
            },
        )
    )
    await session.flush()
    _logger.info(
        "project %d: speech started for unit '%s' of scene '%s': voice=%d mode=%s job=%d",
        project.id,
        unit["id"],
        scene.scene.item["id"],
        voice.id,
        mode,
        job.id,
    )
    return job, True


async def start_unit(session: AsyncSession, project: Project, scene_id: str, unit_id: str) -> Job:
    """Makes the speech of one unit and commits. Raises SpeechSynthesisError."""
    current = await state(session, project)
    if current.blocked_reason is not None:
        raise SpeechSynthesisError(current.blocked_reason)
    scene, item = _find(current, scene_id, unit_id)
    if item.blocked_reason is not None:
        raise SpeechSynthesisError(item.blocked_reason)
    choice = _choice_for(item.unit, current.narrator, current.characters)
    job, _created = await _queue(session, project, scene, item, choice)
    await session.commit()
    return job


async def _queue_take(
    session: AsyncSession,
    project: Project,
    scene: SceneAudio,
    take: TakeEntry,
    choice: _VoiceChoice,
) -> tuple[Job, bool]:
    """Queues the job and adds the audio row of one scene's take that `can_run`. Flushes, does
    not commit. Returns `(job, created)`: the job already making this very take when it was not.
    The job is the one a unit's speech uses: the take is one long text, made in pieces of at most
    1000 characters with one voice, seed and guidance (`jobs/synthesize_speech`).
    """
    voice, instruction, text = take.voice, take.instruction, take.text
    assert voice is not None  # `can_run` made sure
    key = take_key(text, voice.id, instruction)
    plan_row = scene.scene.row
    assert plan_row is not None  # the scene refusal made sure
    scene_id = scene.scene.item["id"]

    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="gpu",
        input={
            "requested": JOB_TYPE,
            DEDUPE_KEY: key,
            "project_id": project.id,
            "scene_id": scene_id,
            "take": True,
            "mode": TAKE_MODE,
            "chunks": speech_chunks.split_script(text),
            "instruction": instruction,
            "seed": secrets.randbelow(speech_synthesizer.SEED_MAX + 1),
            "cfg_scale": speech_synthesizer.default_cfg_scale(instruction),
            # What the job needs of the voice, copied now: a later edit changes nothing for it.
            "reference": {
                "voice_id": voice.id,
                "path": voice.path,
                "mime": voice.mime,
                "text": voice.transcript,
            },
        },
        commit=False,
        dedupe_key=DEDUPE_KEY,
    )
    if not created:
        return job, False

    session.add(
        SpeechUnitAudio(
            project_id=project.id,
            scene_id=scene_id,
            unit_id=None,
            kind=KIND_TAKE,
            speaker_id=None,
            text=text,
            mode=TAKE_MODE,
            instruction=instruction,
            voice_id=voice.id,
            audio_key=key,
            job_id=job.id,
            inputs={
                "project_id": project.id,
                "artifacts": [
                    {"kind": "speech_units", "id": plan_row.id, "version": plan_row.version}
                ],
                "voice": choice.source,
                "delivery": instruction,
            },
        )
    )
    await session.flush()
    _logger.info(
        "project %d: take started for scene '%s': voice=%d job=%d",
        project.id,
        scene_id,
        voice.id,
        job.id,
    )
    return job, True


def _find_take(current: AudioState, scene_id: str) -> tuple[SceneAudio, TakeEntry]:
    scene = next((item for item in current.scenes if item.scene.item["id"] == scene_id), None)
    if scene is None:
        raise SpeechSynthesisError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    if scene.take is None:
        raise SpeechSynthesisError(
            f"Scene '{scene_id}' has no take: only a continuous explainer speaks its scenes as "
            "takes, and the scene needs speech units."
        )
    return scene, scene.take


async def start_take(session: AsyncSession, project: Project, scene_id: str) -> Job:
    """Makes the take of one scene (again if it is made) and commits. Raises
    SpeechSynthesisError.
    """
    current = await state(session, project)
    if current.blocked_reason is not None:
        raise SpeechSynthesisError(current.blocked_reason)
    scene, take = _find_take(current, scene_id)
    if take.blocked_reason is not None:
        raise SpeechSynthesisError(take.blocked_reason)
    job, _created = await _queue_take(session, project, scene, take, current.narrator)
    await session.commit()
    return job


def _skip_reason(item: UnitEntry) -> str | None:
    """Why "Make all" leaves this unit alone, or None when it starts it."""
    if item.blocked_reason is not None:
        return item.blocked_reason
    if item.status == "ready":
        return "Already made and up to date."
    return None


async def start_all(session: AsyncSession, project: Project) -> StartAllResult:
    """Makes every unit that has no current audio and commits once (every scene's take for a
    continuous explainer). The others are skipped, with the reason. Raises SpeechSynthesisError
    when nothing can be made yet.
    """
    current = await state(session, project)
    if current.blocked_reason is not None:
        raise SpeechSynthesisError(current.blocked_reason)
    job_ids: list[int] = []
    skipped: list[Skipped] = []
    for scene in current.scenes:
        scene_id = scene.scene.item["id"]
        if current.continuous:
            # One take per scene; the units are not spoken one by one.
            take = scene.take
            if take is None:
                continue
            reason = take.blocked_reason or (
                "Already made and up to date." if take.status == "ready" else None
            )
            if reason is not None:
                skipped.append(Skipped(scene_id, None, reason))
                continue
            job, created = await _queue_take(session, project, scene, take, current.narrator)
            if created:
                job_ids.append(job.id)
            else:
                skipped.append(Skipped(scene_id, None, "The same take is being made."))
            continue
        for item in scene.units:
            unit_id = item.unit["id"]
            reason = _skip_reason(item)
            if reason is not None:
                skipped.append(Skipped(scene_id, unit_id, reason))
                continue
            choice = _choice_for(item.unit, current.narrator, current.characters)
            job, created = await _queue(session, project, scene, item, choice)
            if created:
                job_ids.append(job.id)
            else:
                skipped.append(
                    Skipped(scene_id, unit_id, "The same line in the same voice is being made.")
                )
    await session.commit()
    return StartAllResult(job_ids=job_ids, skipped=skipped)
