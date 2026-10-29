"""The Audio video lab, inside a library character (AVLAB).

A test is made from a text, a delivery instruction and the parts of the text the author marked
for video:

1. **speech**: the whole text is spoken as one Voice lab speech in the character's saved voice
   (`direction` mode, so the instruction steers the delivery). A long text is made as pieces in
   the same voice and joined, as every speech job does (`voice_lab.create_run(long_text=True)`).
2. **timing**: Parakeet times every word (`jobs/time_lab_speech_words.py`, `word_timings.align`).
3. **parts**: each marked part is cut out of the speech at the middle of the silence before its
   first word and after its last word, padded with silence to the next H3 length (`17n + 5`
   frames), and stored as a speech of its own. A Character lab take then makes the clip from it
   with MiniMax H3 (the shared first frame, the slice as `<Audio 1>`, the test's `audio_marker`).
4. **render**: two videos are made by FFmpeg (`jobs/render_av_test.py`,
   `services/av_lab_render.py`), one with the speech in the gaps and the clip's own sound inside
   the parts, one with the speech only and the clips muted.

A test belongs to no project. Its `state` is worked out on every read from the speech, the jobs
and the takes; the only thing stored about progress is `last_error` (a failure no job holds).

This module creates rows and jobs. It never calls the GPU server.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AvLabSegment, AvLabTest, Job, LabVoiceRun, LibraryCharacter
from app.db.session import SessionLocal
from app.jobs import store
from app.services import (
    character_library,
    character_takes,
    frame_counts,
    speech_audio,
    video_lab,
    video_models,
    voice_lab,
)
from app.services.storage import StorageError, get_storage
from app.services.video_lab import AudioRef, FirstFrameRef, LabVideoInputError
from app.services.voice_lab import VoiceLabForm, VoiceLabInputError

_logger = logging.getLogger(__name__)

TIMING_JOB: Final = "time_lab_speech_words"
RENDER_JOB: Final = "render_av_test"
# Two presses on one test make one job.
DEDUPE_KEY: Final = "test_id"

AudioMarker = Literal["fully_copy", "partially_copy"]
AUDIO_MARKERS: Final[tuple[AudioMarker, ...]] = ("fully_copy", "partially_copy")
Orientation = Literal["portrait", "landscape"]
ORIENTATIONS: Final[tuple[Orientation, ...]] = ("portrait", "landscape")

TEXT_MAX_CHARS: Final = voice_lab.LONG_TEXT_MAX_CHARS
# Each part is a paid H3 clip, so a test has few.
MAX_PARTS: Final = 8
FPS: Final = frame_counts.H3_FPS
# What the language model that writes a clip's prompt is told happens in it.
CLIP_ACTION: Final = "The character speaks directly to the camera."
# The size of an H3 clip, for a clip whose file was stored with no size: `video_lab.H3_SIZES`.

# `speaking`: the speech is being made. `timing`: Parakeet is timing its words. `clips`: the clips
# of the parts are being made. `ready`: every clip exists, nothing is rendered yet. `rendering`:
# the two videos are being made. `done`: both videos exist. `failed`: a step failed (`error`).
Status = Literal["speaking", "timing", "clips", "ready", "rendering", "done", "failed"]
# `waiting`: nothing of the clip has started. `working`: a step of its take runs. `ready`: the
# clip exists. `failed`: its take failed.
SegmentStatus = Literal["waiting", "working", "ready", "failed"]


class AvLabError(ValueError):
    """Something the form gets wrong, or a step that cannot start now. The message is meant for
    the user (HTTP 422).
    """


@dataclass(frozen=True)
class PartRange:
    """A part the author marked: the words from `start_word` to `end_word` (included), counted
    from 0 in `text.split()`.
    """

    start_word: int
    end_word: int


@dataclass(frozen=True)
class TestForm:
    """What a click on "Make the test" sends."""

    character_id: int
    text: str
    instruction: str
    audio_marker: str
    orientation: str
    first_frame: FirstFrameRef
    parts: Sequence[PartRange]


@dataclass(frozen=True)
class SegmentPlan:
    """A part laid on the speech: its words, its place in seconds and the length of its clip."""

    start_word: int
    end_word: int
    text: str
    start_s: float
    end_s: float
    clip_frames: int


@dataclass(frozen=True)
class SegmentEntry:
    """One part of a test and where its clip stands."""

    segment: AvLabSegment
    slice_run: LabVoiceRun | None
    take: character_takes.TakeRow | None
    status: SegmentStatus
    # The step of the take that runs now, as the page names it.
    step: str | None
    error: str | None
    # The clip, once it exists.
    clip: video_lab.RunRow | None


@dataclass(frozen=True)
class TestState:
    test: AvLabTest
    status: Status
    error: str | None
    voice: voice_lab.RunRow | None
    timing_job: Job | None
    render_job: Job | None
    segments: list[SegmentEntry]
    # A warning about the word times (they were estimated), or None.
    timing_warning: str | None
    # Whether Render can be pressed now.
    can_render: bool


@dataclass(frozen=True)
class RenderPart:
    """What the render needs of one part: its place in the speech and its clip."""

    start_s: float
    end_s: float
    clip: Path
    has_audio: bool


@dataclass(frozen=True)
class RenderSources:
    still: Path
    speech: Path
    speech_duration_s: float
    width: int
    height: int
    parts: list[RenderPart]


# --- Pure rules ---------------------------------------------------------------------------


def words_of(text: str) -> list[str]:
    """The words of a text, as the word timing counts them."""
    return text.split()


def check_parts(parts: Sequence[PartRange], word_count: int) -> None:
    """Raises AvLabError unless the parts are 1 to `MAX_PARTS` word ranges inside the text, in
    order, with no word in two of them.
    """
    if not parts:
        raise AvLabError("Mark at least one part of the text for video.")
    if len(parts) > MAX_PARTS:
        raise AvLabError(f"Mark at most {MAX_PARTS} parts: each one is a paid video clip.")
    previous_end = -1
    for number, part in enumerate(parts, start=1):
        if not 0 <= part.start_word <= part.end_word < word_count:
            raise AvLabError(f"Part {number} is not inside the text.")
        if part.start_word <= previous_end:
            raise AvLabError(f"Part {number} overlaps the part before it, or is out of order.")
        previous_end = part.end_word


def part_bounds(
    words: Sequence[dict[str, Any]], part: PartRange, duration_s: float
) -> tuple[float, float]:
    """Where a part starts and ends in the speech: the middle of the silence before its first
    word (0 for the first word of the text) and the middle of the silence after its last word (the
    end of the speech for the last word). Two parts side by side meet at one point.
    """
    first = words[part.start_word]
    if part.start_word == 0:
        start = 0.0
    else:
        start = (float(words[part.start_word - 1]["end"]) + float(first["start"])) / 2
        start = min(start, float(first["start"]))
    last = words[part.end_word]
    if part.end_word == len(words) - 1:
        end = duration_s
    else:
        end = (float(last["end"]) + float(words[part.end_word + 1]["start"])) / 2
        end = max(end, float(last["end"]))
    return start, min(end, duration_s)


def clip_frames_for(length_s: float, number: int) -> int:
    """The H3 frame count (`17n + 5`) of a clip that holds `length_s` seconds. Raises AvLabError
    for a part longer than the longest clip H3 makes.
    """
    wanted = math.ceil(length_s * FPS - 1e-6)
    frames = frame_counts.h3_num_frames(wanted)
    if frames > frame_counts.H3_MAX_FRAMES:
        longest = frame_counts.H3_MAX_FRAMES / FPS
        raise AvLabError(
            f"Part {number} lasts {length_s:.1f} s, and a clip lasts at most {longest:.1f} s. "
            "Split it into two parts."
        )
    return frames


def plan_segments(
    timing: dict[str, Any], duration_s: float, parts: Sequence[PartRange]
) -> list[SegmentPlan]:
    """Lays the parts on the timed speech. Raises AvLabError."""
    words = timing.get("words")
    if not isinstance(words, list) or not words:
        raise AvLabError("The speech has no timed words.")
    check_parts(parts, len(words))
    plans: list[SegmentPlan] = []
    for number, part in enumerate(parts, start=1):
        start_s, end_s = part_bounds(words, part, duration_s)
        if end_s <= start_s:
            raise AvLabError(f"Part {number} has no length in the speech.")
        plans.append(
            SegmentPlan(
                start_word=part.start_word,
                end_word=part.end_word,
                text=" ".join(
                    str(word["text"]) for word in words[part.start_word : part.end_word + 1]
                ),
                start_s=round(start_s, 3),
                end_s=round(end_s, 3),
                clip_frames=clip_frames_for(end_s - start_s, number),
            )
        )
    return plans


def parts_of(value: Any) -> list[PartRange]:
    """The parts as a test stores them (`[{start_word, end_word}]`)."""
    return [
        PartRange(int(item["start_word"]), int(item["end_word"]))
        for item in (value if isinstance(value, list) else [])
    ]


# --- Rows ---------------------------------------------------------------------------------


async def _fresh(session: AsyncSession, test_id: int | None) -> AvLabTest | None:
    if test_id is None:
        return None
    statement = (
        select(AvLabTest).where(AvLabTest.id == test_id).execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def get_test(session: AsyncSession, test_id: int) -> AvLabTest | None:
    return await _fresh(session, test_id)


async def list_tests(
    session: AsyncSession, character_id: int, before_id: int | None, limit: int
) -> list[AvLabTest]:
    """The character's tests, the newest first, `limit` of them, those with an id below
    `before_id` if given.
    """
    statement = (
        select(AvLabTest)
        .where(AvLabTest.character_id == character_id)
        .order_by(AvLabTest.id.desc())
        .limit(limit)
        .execution_options(populate_existing=True)
    )
    if before_id is not None:
        statement = statement.where(AvLabTest.id < before_id)
    return list((await session.execute(statement)).scalars())


async def _segments_of(session: AsyncSession, test_id: int) -> list[AvLabSegment]:
    statement = (
        select(AvLabSegment)
        .where(AvLabSegment.test_id == test_id)
        .order_by(AvLabSegment.position)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars())


# --- Creating a test ----------------------------------------------------------------------


async def create_test(session: AsyncSession, form: TestForm) -> AvLabTest:
    """Checks the form, makes the speech's run and saves the test. Commits. Raises AvLabError,
    and then nothing is saved. The rest follows by itself: the speech's job times its words when
    it is stored (`on_voice_finished`), and the timing job makes the parts (`on_timing_finished`).
    """
    character = await session.get(LibraryCharacter, form.character_id)
    if character is None:
        raise AvLabError(f"There is no character {form.character_id}.")
    if not character_library.has_voice(character):
        raise AvLabError("This character has no saved voice: choose or audition one first.")
    if form.audio_marker not in AUDIO_MARKERS:
        raise AvLabError("Choose fully_copy or partially_copy.")
    if form.orientation not in ORIENTATIONS:
        raise AvLabError("Choose portrait or landscape.")
    text = form.text.strip()
    instruction = form.instruction.strip()
    if not instruction:
        raise AvLabError("Write how the text is spoken: tone, emotion or pace.")
    check_parts(form.parts, len(words_of(text)))
    try:
        await video_lab.first_frame_path(session, form.first_frame)
    except LabVideoInputError as exc:
        raise AvLabError(str(exc)) from exc

    speech = VoiceLabForm(
        mode="direction",
        text=text,
        instruction=instruction,
        voice_id=character.voice_id,
        seed=None,
        cfg_scale=None,
    )
    try:
        run = await voice_lab.create_run(session, speech, commit=False, long_text=True)
    except VoiceLabInputError as exc:
        await session.rollback()
        raise AvLabError(str(exc)) from exc
    test = AvLabTest(
        character_id=character.id,
        text=text,
        instruction=instruction,
        audio_marker=form.audio_marker,
        orientation=form.orientation,
        first_frame={"source": form.first_frame.source, "id": form.first_frame.id},
        parts=[{"start_word": p.start_word, "end_word": p.end_word} for p in form.parts],
        voice_run_id=run.run.id,
    )
    session.add(test)
    await session.commit()
    _logger.info(
        "audio video test %d created: character=%d parts=%d", test.id, character.id, len(form.parts)
    )
    return test


# --- The steps that follow the speech ----------------------------------------------------


async def on_voice_finished(run_id: int) -> bool:
    """Called (best effort) once a Voice lab speech has been stored. Queues the timing of the
    words of every test that was made from this speech and has none yet. Returns True when a job
    was queued.
    """
    async with SessionLocal() as session:
        statement = select(AvLabTest).where(
            AvLabTest.voice_run_id == run_id,
            AvLabTest.word_timing.is_(None),
            AvLabTest.timing_job_id.is_(None),
        )
        tests = list((await session.execute(statement)).scalars())
        queued = False
        for test in tests:
            job, created = await store.create_job(
                session,
                project_id=None,
                type=TIMING_JOB,
                provider="gpu",
                input={"requested": TIMING_JOB, DEDUPE_KEY: test.id},
                commit=False,
                dedupe_key=DEDUPE_KEY,
            )
            test.timing_job_id = job.id
            queued = queued or created
        await session.commit()
    return queued


def timing_dict(alignment: Any, threshold: int) -> dict[str, Any]:
    """A word timing as a test stores it, from `word_timings.Alignment`."""
    return {
        "source": alignment.source,
        "match_percent": alignment.match_percent,
        "threshold": threshold,
        "heard_text": alignment.heard_text,
        "words": alignment.words,
    }


async def speech_for_timing(
    session: AsyncSession, test_id: int
) -> tuple[str, str, float | None] | None:
    """What the timing job needs: the stored path of the test's speech, the test's text and the
    speech's measured length. None when the test or its speech is gone.
    """
    test = await _fresh(session, test_id)
    run = await session.get(LabVoiceRun, test.voice_run_id) if test and test.voice_run_id else None
    if test is None or run is None or run.path is None:
        return None
    return run.path, test.text, run.duration_s


async def store_timing(session: AsyncSession, test_id: int, timing: dict[str, Any]) -> bool:
    """Saves the word timing on the test. No commit. False when the test is gone or already has a
    timing (its parts were made from that one, so it stands).
    """
    test = await _fresh(session, test_id)
    if test is None or test.word_timing is not None:
        return False
    test.word_timing = timing
    test.last_error = None
    return True


async def on_timing_finished(test_id: int) -> bool:
    """Called (best effort) once the timing job has saved the words' times: cuts each part out of
    the speech, saves the segments and starts the clip of each. Returns True when a take started.
    A failure that no job holds is kept on the test (`last_error`).
    """
    async with SessionLocal() as session:
        test = await _fresh(session, test_id)
        if test is None or test.word_timing is None or await _segments_of(session, test_id):
            return False
        run = await session.get(LabVoiceRun, test.voice_run_id) if test.voice_run_id else None
        if run is None or run.path is None or run.duration_s is None:
            test.last_error = "The speech of this test is gone."
            await session.commit()
            return False
        try:
            plans = plan_segments(test.word_timing, run.duration_s, parts_of(test.parts))
            slices = [await _store_slice(session, test, run, plan) for plan in plans]
        except (AvLabError, StorageError, speech_audio.PadError) as exc:
            await session.rollback()
            failed = await _fresh(session, test_id)
            if failed is not None:
                failed.last_error = str(exc)
            await session.commit()
            _logger.warning("audio video test %d: the parts could not be made: %s", test_id, exc)
            return False
        for position, (plan, slice_run) in enumerate(zip(plans, slices, strict=True), start=1):
            session.add(
                AvLabSegment(
                    test_id=test.id,
                    position=position,
                    start_word=plan.start_word,
                    end_word=plan.end_word,
                    text=plan.text,
                    start_s=plan.start_s,
                    end_s=plan.end_s,
                    clip_frames=plan.clip_frames,
                    slice_run_id=slice_run.id,
                )
            )
        await session.commit()
    return await _start_takes(test_id)


async def _store_slice(
    session: AsyncSession, test: AvLabTest, run: LabVoiceRun, plan: SegmentPlan
) -> LabVoiceRun:
    """Cuts one part out of the speech, stores it and adds the Voice lab run that holds it (a
    run with a file and no job, so the Character lab can use it as a speech). Flushes.
    """
    storage = get_storage()
    total_s = plan.clip_frames / FPS
    dest = storage.new_temp_path("wav")
    try:
        await speech_audio.cut_window(
            storage.get_path(run.path or ""), dest, plan.start_s, plan.end_s, total_s
        )
        temp = await storage.describe_temp(dest)
        stored = await storage.save_lab(temp, "wav")
    except Exception:
        storage.discard(dest)
        raise
    params = dict(run.params) if isinstance(run.params, dict) else {}
    params.update({"av_lab_test_id": test.id, "start_s": plan.start_s, "end_s": plan.end_s})
    piece = LabVoiceRun(
        mode="direction",
        text=plan.text,
        instruction=test.instruction,
        voice_id=run.voice_id,
        params=params,
        path=stored.relative_path,
        size_bytes=temp.size_bytes,
        sha256=temp.sha256,
        duration_s=total_s,
    )
    session.add(piece)
    await session.flush()
    return piece


async def _start_takes(test_id: int) -> bool:
    """Starts the take that makes the clip of every part that has none. Each take runs by itself
    from there (its prompt, then its video). Returns True when one started.
    """
    started = False
    async with SessionLocal() as session:
        test = await _fresh(session, test_id)
        if test is None:
            await session.commit()
            return False
        marker = test.audio_marker
        orientation = test.orientation
        character_id = test.character_id
        first_frame = _frame_ref(test.first_frame)
        pending = [
            segment for segment in await _segments_of(session, test_id) if segment.take_id is None
        ]
        for segment in pending:
            form = character_takes.TakeForm(
                character_id=character_id,
                run="all",
                output="video",
                action=CLIP_ACTION,
                dialogue=segment.text,
                framing="medium",
                orientation=orientation,  # type: ignore[arg-type]
                video_model=video_models.H3_MODEL,
                lip_sync=False,
                duration_s=None,
                seed=None,
                negative_prompt=None,
                first_frame=first_frame,
                audio=AudioRef(source="voice_run", id=segment.slice_run_id or 0),
                audio_marker=marker,  # type: ignore[arg-type]
                match_audio_duration=True,
            )
            try:
                row = await character_takes.create_take(session, form)
            except character_takes.CharacterTakeError as exc:
                await session.rollback()
                failed = await _fresh(session, test_id)
                if failed is not None:
                    failed.last_error = (
                        f"The clip of part {segment.position} could not start: {exc}"
                    )
                await session.commit()
                _logger.warning("audio video test %d: part %d: %s", test_id, segment.position, exc)
                return started
            fresh = await session.get(AvLabSegment, segment.id)
            if fresh is not None:
                fresh.take_id = row.take.id
            await session.commit()
            started = True
    return started


def _frame_ref(value: Any) -> FirstFrameRef:
    source: video_lab.FrameSource = "lab" if value.get("source") == "lab" else "asset"
    return FirstFrameRef(source=source, id=int(value["id"]))


async def copy_test(session: AsyncSession, test_id: int, audio_marker: str) -> AvLabTest:
    """Makes a new test from an earlier one with another way of using the speech: the same text,
    speech, word times, parts, slices and first frame, so the two tests are heard on identical
    audio. Only the clips are made again. Commits. Raises AvLabError.
    """
    if audio_marker not in AUDIO_MARKERS:
        raise AvLabError("Choose fully_copy or partially_copy.")
    source = await _fresh(session, test_id)
    if source is None:
        raise AvLabError(f"There is no test {test_id}.")
    segments = await _segments_of(session, test_id)
    if source.word_timing is None or not segments:
        raise AvLabError("Wait until the speech is made and its parts are cut, then copy it.")
    copy = AvLabTest(
        character_id=source.character_id,
        text=source.text,
        instruction=source.instruction,
        audio_marker=audio_marker,
        orientation=source.orientation,
        first_frame=source.first_frame,
        parts=source.parts,
        voice_run_id=source.voice_run_id,
        timing_job_id=source.timing_job_id,
        word_timing=source.word_timing,
        copied_from_id=source.id,
    )
    session.add(copy)
    await session.flush()
    for segment in segments:
        session.add(
            AvLabSegment(
                test_id=copy.id,
                position=segment.position,
                start_word=segment.start_word,
                end_word=segment.end_word,
                text=segment.text,
                start_s=segment.start_s,
                end_s=segment.end_s,
                clip_frames=segment.clip_frames,
                slice_run_id=segment.slice_run_id,
            )
        )
    await session.commit()
    _logger.info("audio video test %d copied from %d as %s", copy.id, source.id, audio_marker)
    await _start_takes(copy.id)
    return copy


# --- Reading a test -----------------------------------------------------------------------


_FAILED: Final = ("failed", "cancelled")


def _job_failed(job: Job | None) -> bool:
    return job is not None and job.status in _FAILED


def _job_error(job: Job | None, fallback: str) -> str:
    if job is not None and job.error:
        return job.error
    return fallback


async def _segment_entry(session: AsyncSession, segment: AvLabSegment) -> SegmentEntry:
    slice_run = (
        await session.get(LabVoiceRun, segment.slice_run_id) if segment.slice_run_id else None
    )
    row = await character_takes.get_take(session, segment.take_id) if segment.take_id else None
    if row is None:
        return SegmentEntry(segment, slice_run, None, "waiting", None, None, None)
    clip = row.video if row.video is not None and row.video.run.path is not None else None
    if clip is not None:
        return SegmentEntry(segment, slice_run, row, "ready", None, None, clip)
    active = row.state.active
    if active is not None:
        return SegmentEntry(
            segment, slice_run, row, "working", character_takes.STEP_LABELS[active], None, None
        )
    error = row.take.last_error
    if error is None and _job_failed(row.prompt_job):
        error = _job_error(row.prompt_job, "The prompt could not be written.")
    if error is None and row.video is not None and _job_failed(row.video.job):
        error = _job_error(row.video.job, "The clip could not be made.")
    if error is not None:
        return SegmentEntry(segment, slice_run, row, "failed", None, error, None)
    return SegmentEntry(segment, slice_run, row, "working", None, None, None)


def _timing_warning(timing: Any) -> str | None:
    if not isinstance(timing, dict) or timing.get("source") != "estimated":
        return None
    return (
        f"Parakeet matched only {timing.get('match_percent', 0):g}% of the words, so the times "
        "are estimated and a cut may fall a little off its word."
    )


async def read(session: AsyncSession, test: AvLabTest) -> TestState:
    """Where a test stands. Worked out on every read; nothing here is stored."""
    voice = await voice_lab.get_run(session, test.voice_run_id) if test.voice_run_id else None
    timing_job = await _job(session, test.timing_job_id)
    render_job = await _job(session, test.render_job_id)
    segments = [
        await _segment_entry(session, segment) for segment in await _segments_of(session, test.id)
    ]
    wanted = len(parts_of(test.parts))
    all_ready = len(segments) == wanted and all(entry.status == "ready" for entry in segments)

    status: Status
    error: str | None = None
    if voice is None:
        status, error = "failed", "The speech of this test is gone."
    elif voice.run.path is None:
        if voice.job is not None and voice.job.status in store.ACTIVE_STATUSES:
            status = "speaking"
        else:
            status, error = "failed", _job_error(voice.job, "The speech could not be made.")
    elif test.word_timing is None:
        if _job_failed(timing_job):
            status, error = "failed", _job_error(timing_job, "The words could not be timed.")
        else:
            status = "timing"
    elif not segments:
        status = "failed" if test.last_error else "clips"
        error = test.last_error
    elif any(entry.status == "failed" for entry in segments):
        status = "failed"
        error = next(entry.error for entry in segments if entry.status == "failed")
    elif not all_ready:
        status = "failed" if test.last_error else "clips"
        error = test.last_error
    elif render_job is not None and render_job.status in store.ACTIVE_STATUSES:
        status = "rendering"
    elif _job_failed(render_job) and not (test.mixed_path and test.tts_path):
        status, error = "failed", _job_error(render_job, "The videos could not be rendered.")
    elif test.mixed_path and test.tts_path:
        status = "done"
    else:
        status = "ready"
    rendering = render_job is not None and render_job.status in store.ACTIVE_STATUSES
    return TestState(
        test=test,
        status=status,
        error=error,
        voice=voice,
        timing_job=timing_job,
        render_job=render_job,
        segments=segments,
        timing_warning=_timing_warning(test.word_timing),
        can_render=all_ready and not rendering and test.word_timing is not None,
    )


async def _job(session: AsyncSession, job_id: int | None) -> Job | None:
    if job_id is None:
        return None
    statement = select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
    return (await session.execute(statement)).scalars().first()


# --- Rendering ----------------------------------------------------------------------------


async def start_render(session: AsyncSession, test_id: int) -> AvLabTest:
    """Queues the render of the two videos. Commits. Raises AvLabError."""
    test = await _fresh(session, test_id)
    if test is None:
        raise AvLabError(f"There is no test {test_id}.")
    state = await read(session, test)
    if state.status == "rendering":
        raise AvLabError("The videos are already being made.")
    if not state.can_render:
        raise AvLabError("Every part needs its clip before the videos can be made.")
    job, _created = await store.create_job(
        session,
        project_id=None,
        type=RENDER_JOB,
        provider="local",
        input={"requested": RENDER_JOB, DEDUPE_KEY: test.id},
        commit=False,
        dedupe_key=DEDUPE_KEY,
    )
    test.render_job_id = job.id
    test.last_error = None
    await session.commit()
    return test


async def render_sources(session: AsyncSession, test_id: int) -> RenderSources:
    """What the render job reads: the files and the places of the parts. Raises AvLabError."""
    storage = get_storage()
    test = await _fresh(session, test_id)
    if test is None:
        raise AvLabError("The test is gone.")
    state = await read(session, test)
    if not state.can_render and not (state.render_job and state.render_job.status == "running"):
        raise AvLabError("Every part needs its clip before the videos can be made.")
    if state.voice is None or state.voice.run.path is None or state.voice.run.duration_s is None:
        raise AvLabError("The speech of this test is gone.")
    try:
        still = storage.get_path(
            await video_lab.first_frame_path(session, _frame_ref(test.first_frame))
        )
        speech = storage.get_path(state.voice.run.path)
        parts: list[RenderPart] = []
        for entry in state.segments:
            if entry.clip is None or entry.clip.run.path is None:
                raise AvLabError(f"Part {entry.segment.position} has no clip.")
            parts.append(
                RenderPart(
                    start_s=entry.segment.start_s,
                    end_s=entry.segment.end_s,
                    clip=storage.get_path(entry.clip.run.path),
                    has_audio=entry.clip.run.audio is not None,
                )
            )
    except (StorageError, LabVideoInputError) as exc:
        raise AvLabError(str(exc)) from exc
    first = state.segments[0].clip
    default_width, default_height = video_lab.H3_SIZES[test.orientation]
    width = first.run.width if first is not None and first.run.width else default_width
    height = first.run.height if first is not None and first.run.height else default_height
    return RenderSources(
        still=still,
        speech=speech,
        speech_duration_s=state.voice.run.duration_s,
        width=width - width % 2,
        height=height - height % 2,
        parts=parts,
    )


async def store_render(
    session: AsyncSession, test_id: int, mixed_path: str, tts_path: str, info: dict[str, Any]
) -> bool:
    """Saves the two rendered videos on the test. No commit. False when the test is gone."""
    test = await _fresh(session, test_id)
    if test is None:
        return False
    test.mixed_path = mixed_path
    test.tts_path = tts_path
    test.render_info = info
    test.last_error = None
    return True
