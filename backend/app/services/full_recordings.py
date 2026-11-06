"""The state of a full recording of a recorded explainer, and how its jobs are queued (REC-004).

A person reads the whole script in one flow (`voice_recording` of scope `full`). Two jobs follow:

- `time_voice_recording` transcribes the whole file (in pieces when it is long) and matches the
  heard words to the whole script. The result is the recording's `voice_recording_timing` row.
- `split_voice_recording` cuts the file into one recorded take per scene. It is queued by the
  timing job, in the transaction that finishes it, when the match is good and no scene boundary
  is tight, and by `retry` when it failed.

`newest` works out where the newest full recording stands on every read. Nothing here is stored
except the jobs and the rows they make:

- `transcribing`: the timing job is queued or running.
- `transcription_failed`: it failed or was cancelled, or there is no job and no timing.
- `refused`: too few of the script's words were heard (R-5). Record it again.
- `tight`: at least one scene boundary has too little pause, or a word next to it was not heard
  (R-7). Deciding them is REC-005.
- `splitting`: every boundary is clean and the split job is queued or running.
- `split_failed`: every boundary is clean and the split has not run or failed.
- `split`: the scenes' takes were made from this recording.

This module does not import `speech_synthesis` (which imports it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, Project, SpeechUnitAudio, VoiceRecording, VoiceRecordingTiming
from app.jobs import store
from app.services import recording_boundaries
from app.services.recording_boundaries import Boundary, BoundaryError, SceneText
from app.services.word_timings import SOURCE_ESTIMATED

TIMING_JOB_TYPE: Final = "time_voice_recording"
SPLIT_JOB_TYPE: Final = "split_voice_recording"
# Two presses on one recording make one job.
DEDUPE_KEY: Final = "voice_recording_id"
SCOPE_FULL: Final = "full"

Stage = Literal[
    "transcribing",
    "transcription_failed",
    "refused",
    "tight",
    "splitting",
    "split_failed",
    "split",
]

TRANSCRIBING: Final = "The recording is being transcribed."
SPLITTING: Final = "The recording is being split into scenes."


class FullRecordingError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class FullRecordingStatus:
    """Where one full recording stands."""

    recording: VoiceRecording
    stage: Stage
    # The script the person was asked to read: each scene's take text at the time.
    scenes: list[SceneText]
    # Empty until the recording is timed from what Parakeet heard.
    boundaries: list[Boundary]
    match_percent: float | None
    threshold: int | None
    # Why the stage is `transcription_failed`, `split_failed` or (rarely) `refused`.
    error: str | None
    timing_job: Job | None
    split_job: Job | None

    @property
    def tight_count(self) -> int:
        return sum(1 for boundary in self.boundaries if boundary.tight)


# --- Messages ---------------------------------------------------------------------------------


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else f"{text}."


def stage_message(status: FullRecordingStatus) -> str:
    """One sentence about where the recording stands: what the speech step stops with and what
    the recording panel says.
    """
    stage = status.stage
    if stage == "transcribing":
        return TRANSCRIBING
    if stage == "splitting":
        return SPLITTING
    if stage == "tight":
        count = status.tight_count
        noun = "boundary" if count == 1 else "boundaries"
        return f"Decide the {count} tight scene {noun}."
    if stage == "refused":
        if status.error is not None:
            return f"The recording could not be used: {_sentence(status.error)}"
        return (
            f"The recording matched only {status.match_percent or 0}% of the script "
            f"({status.threshold or 0}% needed). Record it again."
        )
    if stage == "transcription_failed":
        return (
            f"The recording could not be transcribed: {_sentence(status.error or 'It failed.')} "
            "Try again in the recording panel."
        )
    if stage == "split_failed":
        return (
            f"The recording could not be split: {_sentence(status.error or 'It has not run.')} "
            "Try again in the recording panel."
        )
    return "The recording is split into scenes."


def tight_scene_ids(status: FullRecordingStatus) -> set[str]:
    """The scenes next to a tight boundary."""
    ids: set[str] = set()
    for boundary in status.boundaries:
        if boundary.tight:
            ids.update((boundary.after_scene_id, boundary.before_scene_id))
    return ids


# --- Pure ---------------------------------------------------------------------------------------


def scenes_of(recording: VoiceRecording) -> list[SceneText]:
    """The scenes a recording was made for, as `receive_full_recording` recorded them."""
    inputs = recording.inputs if isinstance(recording.inputs, dict) else {}
    found: list[SceneText] = []
    for item in inputs.get("scenes", []):
        if isinstance(item, dict) and isinstance(item.get("scene_id"), str):
            found.append(SceneText(scene_id=item["scene_id"], text=str(item.get("text", ""))))
    return found


def analyse(
    scenes: list[SceneText], timing: VoiceRecordingTiming, min_pause_ms: int
) -> list[Boundary]:
    """The scene boundaries of a recording timed from what Parakeet heard. Raises BoundaryError."""
    words: list[dict[str, Any]] = list(timing.words)
    spans = recording_boundaries.scene_spans(scenes, words)
    return recording_boundaries.boundaries(spans, words, min_pause_ms / 1000)


# --- Queueing -----------------------------------------------------------------------------------


async def queue_timing(
    session: AsyncSession, recording: VoiceRecording, *, commit: bool = True
) -> tuple[Job, bool]:
    """Queues the job that times a recording. Returns `(job, created)`: the job already doing it
    when it was not created. With `commit=False` the job is only flushed.
    """
    return await store.create_job(
        session,
        project_id=recording.project_id,
        type=TIMING_JOB_TYPE,
        provider="gpu",
        input={"requested": TIMING_JOB_TYPE, DEDUPE_KEY: recording.id},
        commit=commit,
        dedupe_key=DEDUPE_KEY,
    )


async def queue_split(
    session: AsyncSession, recording: VoiceRecording, *, commit: bool = True
) -> tuple[Job, bool]:
    """Queues the job that splits a recording into the scenes' takes (see `queue_timing`)."""
    return await store.create_job(
        session,
        project_id=recording.project_id,
        type=SPLIT_JOB_TYPE,
        provider="local",
        input={"requested": SPLIT_JOB_TYPE, DEDUPE_KEY: recording.id},
        commit=commit,
        dedupe_key=DEDUPE_KEY,
    )


# --- Reading ------------------------------------------------------------------------------------


def _job_error(job: Job) -> str:
    if job.error:
        return job.error
    return "It was cancelled." if job.status == "cancelled" else "It failed."


async def _newest_job(
    session: AsyncSession, project_id: int, job_type: str, recording_id: int
) -> Job | None:
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == job_type)
        .order_by(Job.id)
        .execution_options(populate_existing=True)
    )
    newest: Job | None = None
    for job in (await session.execute(statement)).scalars():  # the oldest first
        key = job.input.get(DEDUPE_KEY) if isinstance(job.input, dict) else None
        if key == recording_id:
            newest = job
    return newest


async def has_takes(session: AsyncSession, project_id: int, recording_id: int) -> bool:
    """Whether the scenes' takes were made from this recording."""
    statement = select(SpeechUnitAudio.inputs).where(
        SpeechUnitAudio.project_id == project_id,
        SpeechUnitAudio.mode == "recorded",
        SpeechUnitAudio.kind == "take",
        SpeechUnitAudio.path.is_not(None),
    )
    for inputs in (await session.execute(statement)).scalars():
        recorded = inputs.get("recording") if isinstance(inputs, dict) else None
        if isinstance(recorded, dict) and recorded.get("id") == recording_id:
            return True
    return False


async def timing_of(session: AsyncSession, recording_id: int) -> VoiceRecordingTiming | None:
    """The word timing of a recording, or None when it is not timed."""
    statement = (
        select(VoiceRecordingTiming)
        .where(VoiceRecordingTiming.voice_recording_id == recording_id)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def status_of(session: AsyncSession, recording: VoiceRecording) -> FullRecordingStatus:
    """Works out where one full recording stands."""
    project_id = recording.project_id
    scenes = scenes_of(recording)
    timing = await timing_of(session, recording.id)
    timing_job = await _newest_job(session, project_id, TIMING_JOB_TYPE, recording.id)
    split_job = await _newest_job(session, project_id, SPLIT_JOB_TYPE, recording.id)

    def made(stage: Stage, **values: Any) -> FullRecordingStatus:
        return FullRecordingStatus(
            recording=recording,
            stage=stage,
            scenes=scenes,
            boundaries=values.get("boundaries", []),
            match_percent=timing.match_percent if timing is not None else None,
            threshold=timing.threshold if timing is not None else None,
            error=values.get("error"),
            timing_job=timing_job,
            split_job=split_job,
        )

    if timing is None:
        if timing_job is not None and timing_job.status in store.ACTIVE_STATUSES:
            return made("transcribing")
        if timing_job is not None and timing_job.status != "succeeded":
            return made("transcription_failed", error=_job_error(timing_job))
        return made("transcription_failed", error="The recording was not transcribed.")
    if timing.source == SOURCE_ESTIMATED:
        return made("refused")

    min_pause_ms = await settings_service.get_int(
        session, settings_service.RECORDING_MIN_BOUNDARY_PAUSE_MS_KEY
    )
    try:
        found = analyse(scenes, timing, min_pause_ms)
    except BoundaryError as exc:
        return made("refused", error=str(exc))

    if await has_takes(session, project_id, recording.id):
        return made("split", boundaries=found)
    if any(boundary.tight for boundary in found):
        return made("tight", boundaries=found)
    if split_job is not None and split_job.status in store.ACTIVE_STATUSES:
        return made("splitting", boundaries=found)
    if split_job is not None and split_job.status != "succeeded":
        return made("split_failed", boundaries=found, error=_job_error(split_job))
    return made("split_failed", boundaries=found, error="The recording has not been split yet.")


async def newest(session: AsyncSession, project: Project) -> FullRecordingStatus | None:
    """Where the project's newest full recording stands, or None when it has none."""
    statement = (
        select(VoiceRecording)
        .where(VoiceRecording.project_id == project.id, VoiceRecording.scope == SCOPE_FULL)
        .order_by(VoiceRecording.version.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    recording = (await session.execute(statement)).scalars().first()
    if recording is None:
        return None
    return await status_of(session, recording)


async def retry(session: AsyncSession, project: Project, recording_id: int) -> Job:
    """Queues the job of the newest full recording that failed, or the split that has not run,
    and commits. Raises FullRecordingError.
    """
    current = await newest(session, project)
    if current is None or current.recording.id != recording_id:
        raise FullRecordingError("This is not the newest full recording.")
    if current.stage == "transcription_failed":
        job, _created = await queue_timing(session, current.recording)
        return job
    if current.stage == "split_failed":
        job, _created = await queue_split(session, current.recording)
        return job
    raise FullRecordingError("There is nothing to try again for this recording.")
