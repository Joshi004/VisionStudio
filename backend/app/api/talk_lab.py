"""`/api/lab/talk`: the Talking character lab (Phase 24). A character picture speaks one line.

A *take* is made in up to three steps, each a job the other labs already run: the language model
writes the prompts, the Voice lab's speech model makes the speech (or an earlier speech is
reused), and the Video lab's lip-sync endpoint makes the clip.

`POST .../takes` checks the form and starts the take's first step, then returns at once with
HTTP 202. With `run: "all"` the take continues by itself, and the page follows it (each step
carries its job, the same one the Activity page shows). With `run: "voice"` or `run: "video"`
only that step starts, and `POST .../takes/{id}/continue` starts the next one.

`POST .../prompt-drafts` starts the paid job that writes the two prompts from a line of
dialogue, without making a take. It answers with that job; its `output` is what the page puts in
the form.

The picture is picked from what the Image lab holds (or a project's frame) or comes from a cast
character (`/api/lab/characters`), and is referred to by `{source, id}`; it is never copied.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.api.video_lab import (
    FirstFrameIn,
    FirstFrameOut,
    LabVideoRunOut,
    frame_out,
    frame_urls_for,
    runs_out,
)
from app.api.voice_lab import LabVoiceRunOut, run_out
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import talk_lab
from app.services.video_lab import FirstFrameRef

router = APIRouter()

# SQLite integers are 64-bit. Larger ids cannot exist, and must not reach the database.
_MAX_ID: Final = 2**63 - 1
Id = Annotated[int, Field(strict=True, ge=1, le=_MAX_ID)]
TakeId = Annotated[int, Path(ge=1, le=_MAX_ID)]

_INVALID = {422: {"model": ErrorResponse, "description": "The form breaks a rule."}}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No take has this id."}}

VoiceMode = Literal["design", "clone", "direction"]
Step = Literal["prompts", "voice", "video"]


class TalkTakeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # "all": the whole chain, continuing by itself. "voice" or "video": only that step.
    run: Literal["all", "voice", "video"]
    dialogue: StrictStr
    # The picture the character is made from. A cast character's picture is sent here too.
    image: FirstFrameIn
    character_id: Id | None = None
    # What you say about the character. Left out: the cast character's description, or the
    # prompt that made the picture.
    character_note: StrictStr | None = None
    delivery_note: StrictStr | None = None
    # A new speech: design (a described voice), clone (a saved voice) or direction (a saved
    # voice, steered). Left out when `reuse_voice_run_id` is sent.
    voice_mode: VoiceMode | None = None
    voice_id: Id | None = None
    # Reuse the speech of this finished Voice lab run instead of making a new one.
    reuse_voice_run_id: Id | None = None
    # Left out: written by the language model.
    voice_instruction: StrictStr | None = None
    video_prompt: StrictStr | None = None
    orientation: Literal["landscape", "portrait"]
    # Left out: a random seed.
    video_seed: StrictInt | None = None
    negative_prompt: StrictStr | None = None


class TalkPromptDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dialogue: StrictStr
    character_id: Id | None = None
    character_note: StrictStr | None = None
    # The picture, used to find the prompt that made it when nothing describes the character.
    image: FirstFrameIn | None = None
    delivery_note: StrictStr | None = None
    # design: write the voice and its delivery. direction: write only the delivery. clone, or
    # left out: no voice instruction.
    voice_mode: VoiceMode | None = None


class CharacterBrief(BaseModel):
    id: int
    name: str


class TalkTakeOut(BaseModel):
    id: int
    created_at: datetime
    dialogue: str
    character: CharacterBrief | None
    # The picture, for a thumbnail. Its `url` is None when the image is gone.
    image: FirstFrameOut | None
    character_note: str | None
    delivery_note: str | None
    # None when the take reuses a speech.
    voice_mode: VoiceMode | None
    voice_id: int | None
    voice_instruction: str | None
    video_prompt: str | None
    orientation: Literal["landscape", "portrait"]
    video_seed: int | None
    negative_prompt: str | None
    auto_continue: bool
    # Why the take could not start its next step by itself. None when there is nothing to say.
    last_error: str | None
    # Step 1, the language model. None when the prompts were written by hand.
    prompt_job: JobSummary | None
    # Step 2, the speech (made for this take, or reused from an earlier one).
    voice_run: LabVoiceRunOut | None
    # Step 3, the lip-synced clip.
    video_run: LabVideoRunOut | None
    # The step that is waiting or running now.
    running_step: Step | None
    # The step "continue" would start. None while a step runs, when the take is finished, or
    # when it has no speech it can use.
    next_step: Step | None


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


async def takes_out(session: AsyncSession, rows: list[talk_lab.TakeRow]) -> list[TalkTakeOut]:
    """The takes with their pictures, and each step's job and media."""
    urls = await frame_urls_for(session, (row.take.image for row in rows))
    videos = await runs_out(session, [row.video for row in rows if row.video is not None])
    video_by_id = {video.id: video for video in videos}

    out: list[TalkTakeOut] = []
    for row in rows:
        take = row.take
        state = row.state
        out.append(
            TalkTakeOut(
                id=take.id,
                created_at=take.created_at,
                dialogue=take.dialogue,
                character=(
                    CharacterBrief(id=row.character.id, name=row.character.name)
                    if row.character is not None
                    else None
                ),
                image=frame_out(take.image, urls),
                character_note=take.character_note,
                delivery_note=take.delivery_note,
                voice_mode=(
                    "clone"
                    if take.voice_mode == "clone"
                    else "direction"
                    if take.voice_mode == "direction"
                    else "design"
                    if take.voice_mode == "design"
                    else None
                ),
                voice_id=take.voice_id,
                voice_instruction=take.voice_instruction,
                video_prompt=take.video_prompt,
                orientation="portrait" if take.orientation == "portrait" else "landscape",
                video_seed=take.video_seed,
                negative_prompt=take.negative_prompt,
                auto_continue=take.auto_continue,
                last_error=take.last_error,
                prompt_job=(
                    job_summary(
                        JobRow(
                            job=row.prompt_job,
                            project_name=store.TALK_LAB_NAME,
                            scene_index=None,
                        )
                    )
                    if row.prompt_job is not None
                    else None
                ),
                voice_run=run_out(row.voice) if row.voice is not None else None,
                video_run=video_by_id.get(take.video_run_id) if take.video_run_id else None,
                running_step=state.active,
                # Nothing is offered while a step runs.
                next_step=talk_lab.next_step(take, state) if state.active is None else None,
            )
        )
    return out


@router.post(
    "/lab/talk/prompt-drafts",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_INVALID,
)
async def create_prompt_draft(body: TalkPromptDraftCreate, session: SessionDep) -> JobDetail:
    """Starts the job that writes the voice instruction and the video prompt from a line of
    dialogue (a paid call to the language model). Follow it with `GET /api/jobs/{id}`: when it
    has succeeded, `output.voice_instruction` and `output.video_prompt` are the texts and
    `output.warnings` is what to look at.
    """
    form = talk_lab.DraftForm(
        dialogue=body.dialogue,
        character_id=body.character_id,
        character_note=body.character_note,
        image=(
            FirstFrameRef(source=body.image.source, id=body.image.id)
            if body.image is not None
            else None
        ),
        delivery_note=body.delivery_note,
        voice_mode=body.voice_mode,
    )
    try:
        job = await talk_lab.create_prompt_draft(session, form)
    except talk_lab.TalkLabInputError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=store.TALK_LAB_NAME, scene_index=None))


@router.post(
    "/lab/talk/takes",
    response_model=TalkTakeOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_INVALID,
)
async def create_take(body: TalkTakeCreate, session: SessionDep) -> TalkTakeOut:
    """Saves a take and starts its first step. Each step is a paid call: the prompts a model
    call, the speech a GPU job of one to three minutes, the clip one of 5 to 10 minutes.
    """
    form = talk_lab.TalkForm(
        run=body.run,
        dialogue=body.dialogue,
        image=FirstFrameRef(source=body.image.source, id=body.image.id),
        character_id=body.character_id,
        character_note=body.character_note,
        delivery_note=body.delivery_note,
        voice_mode=body.voice_mode,
        voice_id=body.voice_id,
        reuse_voice_run_id=body.reuse_voice_run_id,
        voice_instruction=body.voice_instruction,
        video_prompt=body.video_prompt,
        orientation=body.orientation,
        video_seed=body.video_seed,
        negative_prompt=body.negative_prompt,
    )
    try:
        row = await talk_lab.create_take(session, form)
    except talk_lab.TalkLabInputError as exc:
        raise _unprocessable(str(exc)) from exc
    dispatcher.nudge()
    return (await takes_out(session, [row]))[0]


@router.get("/lab/talk/takes", response_model=list[TalkTakeOut])
async def list_takes(
    session: SessionDep,
    before_id: Annotated[int | None, Query(ge=1, le=_MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=talk_lab.LIST_LIMIT_MAX)] = 20,
) -> list[TalkTakeOut]:
    """The newest takes first. Pass the last id you have as `before_id` for the next page."""
    return await takes_out(session, await talk_lab.list_takes(session, before_id, limit))


@router.get("/lab/talk/takes/{take_id}", response_model=TalkTakeOut, responses=_NOT_FOUND)
async def get_take(take_id: TakeId, session: SessionDep) -> TalkTakeOut:
    row = await talk_lab.get_take(session, take_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Take {take_id} does not exist.")
    return (await takes_out(session, [row]))[0]


@router.post(
    "/lab/talk/takes/{take_id}/continue",
    response_model=TalkTakeOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def continue_take(take_id: TakeId, session: SessionDep) -> TalkTakeOut:
    """Starts the next step of a take (one step). Refused while a step is still running, and
    when the take is finished.
    """
    try:
        row = await talk_lab.continue_take(session, take_id)
    except talk_lab.TalkLabInputError as exc:
        raise _unprocessable(str(exc)) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Take {take_id} does not exist.")
    dispatcher.nudge()
    return (await takes_out(session, [row]))[0]
