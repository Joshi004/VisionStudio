"""`/api/lab/characters/{id}/av-tests`: the Audio video lab, inside a character (AVLAB).

A test is one text spoken whole in the character's voice, with some parts of it marked for video.
`POST` makes the test and returns at once (HTTP 202): the dispatcher makes the speech, times its
words, cuts the parts and makes a clip for each, and the page polls `GET` until `status` is
`ready`. `POST /av-tests/{id}/render` then makes the two videos (the mixed one and the one with
the speech only), and `POST /av-tests/{id}/copy` makes the same test again with the other way of
using the speech, on the very same speech, word times, parts and first frame.

The rules are in `services/av_lab.py`. Nothing here is stored: every field is worked out on
every read.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal
from typing import cast as typing_cast

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobSummary, job_summary
from app.api.video_lab import FirstFrameIn, FirstFrameOut, frame_out, frame_urls_for
from app.db.models import AvLabTest, Job, LibraryCharacter
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import av_lab
from app.services.storage import media_url
from app.services.video_lab import FirstFrameRef

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
CharacterId = Annotated[int, Path(ge=1, le=_MAX_ID)]
TestId = Annotated[int, Path(ge=1, le=_MAX_ID)]

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No character or test has this id."}}
_INVALID = {422: {"model": ErrorResponse, "description": "The form breaks a rule."}}

AudioMarker = Literal["fully_copy", "partially_copy"]
Orientation = Literal["portrait", "landscape"]
Status = Literal["speaking", "timing", "clips", "ready", "rendering", "done", "failed"]
SegmentStatus = Literal["waiting", "working", "ready", "failed"]


def _missing(message: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, message)


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _job_summary(job: Job | None) -> JobSummary | None:
    if job is None:
        return None
    return job_summary(JobRow(job=job, project_name=store.owner_name(job, None)))


# --- The form ------------------------------------------------------------------------------


class PartIn(BaseModel):
    """A part marked for video: the words from `start_word` to `end_word` (included), counted
    from 0 in the text split at spaces and line breaks.
    """

    model_config = ConfigDict(extra="forbid")

    start_word: Annotated[StrictInt, Field(ge=0)]
    end_word: Annotated[StrictInt, Field(ge=0)]


class TestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: StrictStr
    # How the whole text is spoken: tone, emotion, pace.
    instruction: StrictStr
    # How each clip uses its part of the speech.
    audio_marker: AudioMarker = "fully_copy"
    orientation: Orientation = "portrait"
    first_frame: FirstFrameIn
    parts: list[PartIn] = Field(min_length=1, max_length=av_lab.MAX_PARTS)


class CopyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_marker: AudioMarker


# --- The answer ----------------------------------------------------------------------------


class PartOut(BaseModel):
    start_word: int
    end_word: int


class SegmentOut(BaseModel):
    position: int
    start_word: int
    end_word: int
    text: str
    # Where the part lies in the speech, and the length H3 is asked for.
    start_s: float
    end_s: float
    clip_frames: int
    status: SegmentStatus
    # The step of the clip's take that runs now, as a label ("prompt writing", "video").
    step: str | None
    error: str | None
    take_id: int | None
    # The part of the speech the clip hears (padded with silence to the clip's length).
    audio_url: str | None
    clip_url: str | None
    clip_duration_s: float | None
    # Whether the clip has a sound track of its own (what the mixed video plays inside the part).
    clip_has_sound: bool | None


class TimingOut(BaseModel):
    # "parakeet": the times were heard. "estimated": too few words matched, so they are spread.
    source: str
    match_percent: float
    threshold: int


class RenderInfoOut(BaseModel):
    fps: int
    frames: int
    duration_s: float
    width: int
    height: int
    # The numbers (from 1) of the parts whose clip has no sound track.
    clips_without_sound: list[int]


class TestOut(BaseModel):
    id: int
    created_at: datetime
    character_id: int
    text: str
    instruction: str
    audio_marker: AudioMarker
    orientation: Orientation
    first_frame: FirstFrameOut | None
    parts: list[PartOut]
    status: Status
    error: str | None
    # A warning that does not stop the test (the word times are estimated), or None.
    timing_warning: str | None
    timing: TimingOut | None
    speech_run_id: int | None
    speech_url: str | None
    speech_duration_s: float | None
    speech_job: JobSummary | None
    timing_job: JobSummary | None
    render_job: JobSummary | None
    segments: list[SegmentOut]
    # The two videos, once rendered.
    mixed_url: str | None
    tts_only_url: str | None
    render: RenderInfoOut | None
    can_render: bool
    # The test this one was copied from, if any.
    copied_from_id: int | None


class TestsOut(BaseModel):
    tests: list[TestOut]
    next_before_id: int | None


def _timing_out(timing: Any) -> TimingOut | None:
    if not isinstance(timing, dict):
        return None
    return TimingOut(
        source=str(timing.get("source", "")),
        match_percent=float(timing.get("match_percent", 0)),
        threshold=int(timing.get("threshold", 0)),
    )


def _render_out(info: Any) -> RenderInfoOut | None:
    if not isinstance(info, dict):
        return None
    try:
        return RenderInfoOut(
            fps=int(info["fps"]),
            frames=int(info["frames"]),
            duration_s=float(info["duration_s"]),
            width=int(info["width"]),
            height=int(info["height"]),
            clips_without_sound=[int(number) for number in info.get("clips_without_sound", [])],
        )
    except (KeyError, TypeError, ValueError):
        return None


def _segment_out(entry: av_lab.SegmentEntry) -> SegmentOut:
    segment = entry.segment
    slice_path = entry.slice_run.path if entry.slice_run is not None else None
    clip = entry.clip.run if entry.clip is not None else None
    return SegmentOut(
        position=segment.position,
        start_word=segment.start_word,
        end_word=segment.end_word,
        text=segment.text,
        start_s=segment.start_s,
        end_s=segment.end_s,
        clip_frames=segment.clip_frames,
        status=entry.status,
        step=entry.step,
        error=entry.error,
        take_id=segment.take_id,
        audio_url=media_url(slice_path) if slice_path else None,
        clip_url=media_url(clip.path) if clip is not None and clip.path else None,
        clip_duration_s=clip.duration_s if clip is not None else None,
        clip_has_sound=(clip.audio is not None) if clip is not None and clip.path else None,
    )


async def _tests_out(session: AsyncSession, tests: list[AvLabTest]) -> list[TestOut]:
    frame_urls = await frame_urls_for(session, [test.first_frame for test in tests])
    out: list[TestOut] = []
    for test in tests:
        state = await av_lab.read(session, test)
        voice = state.voice.run if state.voice is not None else None
        out.append(
            TestOut(
                id=test.id,
                created_at=test.created_at,
                character_id=test.character_id,
                text=test.text,
                instruction=test.instruction,
                audio_marker=typing_cast(AudioMarker, test.audio_marker),
                orientation=typing_cast(Orientation, test.orientation),
                first_frame=frame_out(test.first_frame, frame_urls),
                parts=[
                    PartOut(start_word=part.start_word, end_word=part.end_word)
                    for part in av_lab.parts_of(test.parts)
                ],
                status=state.status,
                error=state.error,
                timing_warning=state.timing_warning,
                timing=_timing_out(test.word_timing),
                speech_run_id=test.voice_run_id,
                speech_url=media_url(voice.path) if voice is not None and voice.path else None,
                speech_duration_s=voice.duration_s if voice is not None else None,
                speech_job=_job_summary(state.voice.job if state.voice is not None else None),
                timing_job=_job_summary(state.timing_job),
                render_job=_job_summary(state.render_job),
                segments=[_segment_out(entry) for entry in state.segments],
                mixed_url=media_url(test.mixed_path) if test.mixed_path else None,
                tts_only_url=media_url(test.tts_path) if test.tts_path else None,
                render=_render_out(test.render_info),
                can_render=state.can_render,
                copied_from_id=test.copied_from_id,
            )
        )
    return out


# --- Routes --------------------------------------------------------------------------------


@router.post(
    "/lab/characters/{character_id}/av-tests",
    response_model=TestOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def create_test(character_id: CharacterId, body: TestIn, session: SessionDep) -> TestOut:
    """Checks the form, saves the test and starts the speech of the whole text. The rest follows
    by itself: the words are timed, the parts are cut and their clips are made.
    """
    if await session.get(LibraryCharacter, character_id) is None:
        raise _missing(f"There is no character {character_id}.")
    form = av_lab.TestForm(
        character_id=character_id,
        text=body.text,
        instruction=body.instruction,
        audio_marker=body.audio_marker,
        orientation=body.orientation,
        first_frame=FirstFrameRef(source=body.first_frame.source, id=body.first_frame.id),
        parts=[av_lab.PartRange(part.start_word, part.end_word) for part in body.parts],
    )
    try:
        test = await av_lab.create_test(session, form)
    except av_lab.AvLabError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return (await _tests_out(session, [test]))[0]


@router.get("/lab/characters/{character_id}/av-tests", response_model=TestsOut)
async def list_tests(
    character_id: CharacterId,
    session: SessionDep,
    before_id: Annotated[int | None, Query(ge=1, le=_MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> TestsOut:
    """The character's tests, the newest first. Pass the last id you have as `before_id` for the
    next page.
    """
    tests = await av_lab.list_tests(session, character_id, before_id, limit)
    return TestsOut(
        tests=await _tests_out(session, tests),
        next_before_id=tests[-1].id if len(tests) == limit else None,
    )


@router.get("/lab/characters/av-tests/{test_id}", response_model=TestOut, responses=_NOT_FOUND)
async def get_test(test_id: TestId, session: SessionDep) -> TestOut:
    test = await av_lab.get_test(session, test_id)
    if test is None:
        raise _missing(f"There is no test {test_id}.")
    return (await _tests_out(session, [test]))[0]


@router.post(
    "/lab/characters/av-tests/{test_id}/render",
    response_model=TestOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def render_test(test_id: TestId, session: SessionDep) -> TestOut:
    """Makes the two videos, once every part has its clip. Nothing is paid for: it is FFmpeg."""
    try:
        test = await av_lab.start_render(session, test_id)
    except av_lab.AvLabError as exc:
        if await av_lab.get_test(session, test_id) is None:
            raise _missing(str(exc)) from exc
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return (await _tests_out(session, [test]))[0]


@router.post(
    "/lab/characters/av-tests/{test_id}/copy",
    response_model=TestOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def copy_test(test_id: TestId, body: CopyIn, session: SessionDep) -> TestOut:
    """Makes a new test from this one with another way of using the speech. It keeps the speech,
    the word times, the parts and the first frame, and makes the clips again (each one is a paid
    video run).
    """
    try:
        test = await av_lab.copy_test(session, test_id, body.audio_marker)
    except av_lab.AvLabError as exc:
        if await av_lab.get_test(session, test_id) is None:
            raise _missing(str(exc)) from exc
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return (await _tests_out(session, [test]))[0]
