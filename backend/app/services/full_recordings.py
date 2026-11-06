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
- `tight`: at least one tight scene boundary (too little pause, or a word next to it was not
  heard, R-7) has no decision of the owner yet (REC-005: `decide`, `keep_all`).
- `splitting`: every tight boundary is decided and the split job is queued or running.
- `split_failed`: every tight boundary is decided and the scenes have no takes at the cuts now
  wanted, and the split has not run or failed.
- `split`: every scene has a take made from this recording at the cuts now wanted. A scene's take
  matches when it was cut at the samples the current cuts give it, so a changed decision makes
  new takes only for the scenes either side of the cut that moved.

This module does not import `speech_synthesis` (which imports it).
"""

from __future__ import annotations

import asyncio
import io
import math
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import (
    Job,
    Project,
    RecordingBoundaryDecision,
    SpeechUnitAudio,
    VoiceRecording,
    VoiceRecordingTiming,
)
from app.db.types import utcnow
from app.jobs import store
from app.services import recording_boundaries
from app.services.recording_boundaries import (
    Boundary,
    BoundaryDecision,
    BoundaryError,
    BoundaryKey,
    SceneText,
)
from app.services.speech_audio import SAMPLE_RATE
from app.services.storage import StorageError, get_storage
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


class RecordingNotFound(FullRecordingError):
    """The full recording asked for does not exist in the project."""


# The longest piece of a recording `excerpt` gives, in seconds.
MAX_EXCERPT_S: Final = 10.0
# The stages in which the owner may decide a boundary: not while the recording is not timed or
# is being split (a running split must not see decisions change under it).
DECIDABLE_STAGES: Final = ("tight", "split_failed", "split")


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
    # The owner's decisions (REC-005), by the ids of the two scenes of a boundary.
    decisions: dict[BoundaryKey, BoundaryDecision] = field(default_factory=dict)
    # Where each boundary is cut now, in the order of `boundaries`.
    cuts: list[float] = field(default_factory=list)
    # Of each scene, the id of its take (a `speech_unit_audio` row) cut from this recording at
    # the cuts now wanted. A scene with none has to be split again.
    scene_takes: dict[str, int] = field(default_factory=dict)

    @property
    def tight_count(self) -> int:
        return sum(1 for boundary in self.boundaries if boundary.tight)

    @property
    def open_count(self) -> int:
        """The tight boundaries nobody has decided."""
        return sum(
            1
            for boundary in self.boundaries
            if boundary.tight and recording_boundaries.key_of(boundary) not in self.decisions
        )


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
        count = status.open_count
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


async def takes_of(
    session: AsyncSession, project_id: int, recording_id: int
) -> list[SpeechUnitAudio]:
    """The stored takes cut from this recording, the newest first."""
    statement = (
        select(SpeechUnitAudio)
        .where(
            SpeechUnitAudio.project_id == project_id,
            SpeechUnitAudio.mode == "recorded",
            SpeechUnitAudio.kind == "take",
            SpeechUnitAudio.path.is_not(None),
        )
        .order_by(SpeechUnitAudio.id.desc())
        .execution_options(populate_existing=True)
    )
    found: list[SpeechUnitAudio] = []
    for take in (await session.execute(statement)).scalars():
        recorded = take.inputs.get("recording") if isinstance(take.inputs, dict) else None
        if isinstance(recorded, dict) and recorded.get("id") == recording_id:
            found.append(take)
    return found


async def decisions_of(
    session: AsyncSession, recording_id: int
) -> dict[BoundaryKey, BoundaryDecision]:
    """The owner's decisions on the boundaries of one recording."""
    statement = (
        select(RecordingBoundaryDecision)
        .where(RecordingBoundaryDecision.recording_id == recording_id)
        .execution_options(populate_existing=True)
    )
    return {
        (row.after_scene_id, row.before_scene_id): BoundaryDecision(row.decision, row.cut_s)
        for row in (await session.execute(statement)).scalars()
    }


def total_samples_of(recording: VoiceRecording) -> int:
    """The length of a recording in samples, from its stored length."""
    return round(recording.duration_s * SAMPLE_RATE)


def matching_takes(
    scenes: list[SceneText], cuts: list[float], total_samples: int, takes: list[SpeechUnitAudio]
) -> dict[str, int]:
    """Of each scene, the newest take among `takes` (newest first) that was cut at the samples
    the current `cuts` give the scene: the scene's id in the result, the take's id as the value.
    The end of the last scene is the end of the recording and is not compared. Raises
    BoundaryError when the recording is too short for its scenes.
    """
    if not scenes:
        return {}
    windows = recording_boundaries.split_windows(total_samples, cuts, SAMPLE_RATE)
    found: dict[str, int] = {}
    for position, (scene, (first, last)) in enumerate(zip(scenes, windows, strict=True)):
        end = None if position == len(scenes) - 1 else last
        for take in takes:
            window = take.inputs.get("window") if isinstance(take.inputs, dict) else None
            if (
                take.scene_id == scene.scene_id
                and take.text == scene.text
                and recording_boundaries.window_matches(window, first, end)
            ):
                found[scene.scene_id] = take.id
                break
    return found


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
            decisions=values.get("decisions", {}),
            cuts=values.get("cuts", []),
            scene_takes=values.get("scene_takes", {}),
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

    decisions = await decisions_of(session, recording.id)
    try:
        cuts = recording_boundaries.final_cuts(found, decisions)
        scene_takes = matching_takes(
            scenes,
            cuts,
            total_samples_of(recording),
            await takes_of(session, project_id, recording.id),
        )
    except BoundaryError as exc:
        return made("refused", error=str(exc))
    details: dict[str, Any] = {
        "boundaries": found,
        "decisions": decisions,
        "cuts": cuts,
        "scene_takes": scene_takes,
    }

    if scenes and len(scene_takes) == len(scenes):
        return made("split", **details)
    undecided = any(
        boundary.tight and recording_boundaries.key_of(boundary) not in decisions
        for boundary in found
    )
    if undecided:
        return made("tight", **details)
    if split_job is not None and split_job.status in store.ACTIVE_STATUSES:
        return made("splitting", **details)
    if split_job is not None and split_job.status != "succeeded":
        return made("split_failed", error=_job_error(split_job), **details)
    return made("split_failed", error="The recording has not been split yet.", **details)


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


# --- Decisions (REC-005) ------------------------------------------------------------------------


async def _decidable(
    session: AsyncSession, project: Project, recording_id: int
) -> FullRecordingStatus:
    """The newest full recording, when its boundaries can be decided. Raises FullRecordingError."""
    current = await newest(session, project)
    if current is None or current.recording.id != recording_id:
        raise FullRecordingError("This is not the newest full recording.")
    if current.stage == "splitting":
        raise FullRecordingError("The recording is being split. Decide again when it is done.")
    if current.stage not in DECIDABLE_STAGES:
        raise FullRecordingError(
            "The scene boundaries can be decided once the recording has been transcribed "
            "and accepted."
        )
    return current


async def _write_decisions(
    session: AsyncSession,
    recording: VoiceRecording,
    changes: dict[BoundaryKey, BoundaryDecision],
) -> None:
    """Saves decisions: a new row for a boundary without one, else the row is changed."""
    statement = (
        select(RecordingBoundaryDecision)
        .where(RecordingBoundaryDecision.recording_id == recording.id)
        .execution_options(populate_existing=True)
    )
    existing = {
        (row.after_scene_id, row.before_scene_id): row
        for row in (await session.execute(statement)).scalars()
    }
    now = utcnow()
    for (after_scene_id, before_scene_id), decision in changes.items():
        row = existing.get((after_scene_id, before_scene_id))
        if row is None:
            session.add(
                RecordingBoundaryDecision(
                    project_id=recording.project_id,
                    recording_id=recording.id,
                    after_scene_id=after_scene_id,
                    before_scene_id=before_scene_id,
                    decision=decision.decision,
                    cut_s=decision.cut_s,
                )
            )
        else:
            row.decision = decision.decision
            row.cut_s = decision.cut_s
            row.updated_at = now
    await session.flush()


async def _queue_split_if_needed(session: AsyncSession, recording: VoiceRecording) -> Job | None:
    """After a decision: queues the split (not committed) when nothing is left to decide and
    some scene has no take at its current cuts. Returns the job, or None when none was needed.
    """
    refreshed = await status_of(session, recording)
    if refreshed.stage != "split_failed":
        return None
    job, _created = await queue_split(session, recording, commit=False)
    return job


async def decide(
    session: AsyncSession,
    project: Project,
    recording_id: int,
    after_scene_id: str,
    before_scene_id: str,
    decision: str,
    cut_s: float | None,
) -> Job | None:
    """Decides one tight boundary of the newest full recording: `keep` (cut in the middle of the
    pause) or `cut_at` (cut at `cut_s`, which must be inside the boundary's window and between
    the cuts either side). Commits. Returns the split job it queued, or None. Raises
    FullRecordingError.
    """
    if decision not in (recording_boundaries.DECISION_KEEP, recording_boundaries.DECISION_CUT_AT):
        raise FullRecordingError("The decision must be 'keep' or 'cut_at'.")
    cutting = decision == recording_boundaries.DECISION_CUT_AT
    if cutting != (cut_s is not None):
        raise FullRecordingError("A cut point is needed when, and only when, cutting at it.")
    current = await _decidable(session, project, recording_id)
    key = (after_scene_id, before_scene_id)
    index = next(
        (
            i
            for i, item in enumerate(current.boundaries)
            if recording_boundaries.key_of(item) == key
        ),
        None,
    )
    if index is None:
        raise FullRecordingError("There is no such scene boundary in this recording.")
    boundary = current.boundaries[index]
    if not boundary.tight:
        raise FullRecordingError(
            "Only a tight boundary can be decided. This one is cut in the middle of its pause."
        )
    chosen: float | None = None
    if cut_s is not None:
        if not math.isfinite(cut_s):
            raise FullRecordingError("The cut point is not a number.")
        chosen = round(cut_s, 3)
    try:
        recording_boundaries.check_cut(
            current.boundaries,
            index,
            chosen if chosen is not None else boundary.cut_s,
            current.decisions,
            check_window=cutting,
        )
    except BoundaryError as exc:
        raise FullRecordingError(str(exc)) from exc
    await _write_decisions(session, current.recording, {key: BoundaryDecision(decision, chosen)})
    job = await _queue_split_if_needed(session, current.recording)
    await session.commit()
    return job


async def keep_all(session: AsyncSession, project: Project, recording_id: int) -> Job | None:
    """Keeps as is every tight boundary of the newest full recording that has no decision.
    Commits. Returns the split job it queued, or None. Raises FullRecordingError.
    """
    current = await _decidable(session, project, recording_id)
    decisions = dict(current.decisions)
    changes: dict[BoundaryKey, BoundaryDecision] = {}
    for index, boundary in enumerate(current.boundaries):
        key = recording_boundaries.key_of(boundary)
        if not boundary.tight or key in decisions:
            continue
        try:
            recording_boundaries.check_cut(
                current.boundaries, index, boundary.cut_s, decisions, check_window=False
            )
        except BoundaryError as exc:
            raise FullRecordingError(str(exc)) from exc
        keep = BoundaryDecision(recording_boundaries.DECISION_KEEP, None)
        decisions[key] = keep
        changes[key] = keep
    if not changes:
        raise FullRecordingError("No tight boundary is waiting for a decision.")
    await _write_decisions(session, current.recording, changes)
    job = await _queue_split_if_needed(session, current.recording)
    await session.commit()
    return job


# --- A piece of a recording (REC-005) -----------------------------------------------------------


def _read_excerpt(path: Path, start_s: float, end_s: float) -> bytes:
    """The WAV of a part of a recording in the takes' format. Blocking: call it from a thread."""
    try:
        with wave.open(str(path), "rb") as source:
            if (
                source.getnchannels() != 1
                or source.getframerate() != SAMPLE_RATE
                or source.getsampwidth() != 2
            ):
                raise FullRecordingError("The recording is not in the voice format.")
            total = source.getnframes()
            first = math.floor(start_s * SAMPLE_RATE)
            last = min(math.ceil(end_s * SAMPLE_RATE), total)
            if first >= total:
                raise FullRecordingError("The part asked for is outside the recording.")
            source.setpos(first)
            frames = source.readframes(last - first)
    except (wave.Error, EOFError, OSError) as exc:
        raise FullRecordingError("The recording could not be read as a WAV file.") from exc
    out = io.BytesIO()
    with wave.open(out, "wb") as piece:
        piece.setnchannels(1)
        piece.setsampwidth(2)
        piece.setframerate(SAMPLE_RATE)
        piece.writeframes(frames)
    return out.getvalue()


async def excerpt(
    session: AsyncSession, project: Project, recording_id: int, start_s: float, end_s: float
) -> bytes:
    """A part of a full recording as a WAV, for the boundary player and the cut point editor. At
    most `MAX_EXCERPT_S` seconds; an end past the end of the recording is cut short. Raises
    RecordingNotFound, or FullRecordingError for a part that is empty, too long or outside.
    """
    recording = await session.get(VoiceRecording, recording_id)
    if recording is None or recording.project_id != project.id or recording.scope != SCOPE_FULL:
        raise RecordingNotFound("There is no such full recording.")
    if not (math.isfinite(start_s) and math.isfinite(end_s)) or start_s < 0 or end_s <= start_s:
        raise FullRecordingError("The part asked for is empty.")
    if end_s - start_s > MAX_EXCERPT_S:
        raise FullRecordingError(f"At most {MAX_EXCERPT_S:g} seconds can be taken at a time.")
    try:
        path = get_storage().get_path(recording.path)
    except StorageError as exc:
        raise FullRecordingError("The recording file could not be found.") from exc
    return await asyncio.to_thread(_read_excerpt, path, start_s, end_s)
