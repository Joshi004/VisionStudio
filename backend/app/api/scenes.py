"""Scene proposal (ANALYSIS.md Section 5.2).

`POST /api/projects/{id}/propose-scenes` creates the `plan_scenes` job and returns at once
with HTTP 202. It is a paid call (Section 6.2), so it only ever runs from this click, and
two gates ask first: the recording differs from the script, and scenes that already hold a
description, frames or a clip would be replaced. The dispatcher does the work.

`GET /api/projects/{id}/scenes` reads the database only: the scenes, the proposal they came
from, whether they are out of date, and the model the next proposal will call. It also
carries the script's words, which the page needs to edit the cuts.

`POST /api/projects/{id}/edit-cut` (Phase 7) adds, moves or removes one cut and answers with
the scenes as they are afterwards. It is not a job: it is a quick change to the database,
and it makes no call to the language model.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.api.projects import load_project
from app.core import settings as settings_service
from app.db.models import Asset, Job, Project, Scene
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.plan_scenes import LLM_MODEL_KEY, LLM_URL_KEY
from app.jobs.store import JobRow
from app.services import (
    cut_edits,
    frame_images,
    scene_cuts,
    scene_inputs,
    scene_planner,
    scene_prompt,
    transcript_matching,
)
from app.services import scenes as scenes_service
from app.services import transcripts as transcripts_service
from app.services.scene_inputs import MissingInput
from app.services.storage import media_url

_logger = logging.getLogger(__name__)

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No project has this id."}}
_NOT_READY = {
    422: {
        "model": ErrorResponse,
        "description": "There is no voiceover, script or current transcript yet, or the "
        "script is too long.",
    }
}
_NEEDS_CONFIRMATION = {
    409: {
        "model": ErrorResponse,
        "description": "The recording differs from the script, or scenes with inputs would "
        "be replaced, and the request did not confirm it.",
    }
}

CutSource = Literal["ai", "rule", "manual"]
StaleReasonOut = Literal["script_changed", "voiceover_changed"]


class ProposeScenesRequest(BaseModel):
    """What the user has confirmed. Every flag is off unless sent."""

    model_config = ConfigDict(extra="forbid")

    # Ask the model again even though the same request was answered before (paid).
    run_again: StrictBool = False
    # Go on although the recording differs from the script.
    accept_mismatch: StrictBool = False
    # Replace scenes that have a description, frames or a clip. Their files stay on disk.
    discard_scenes_with_inputs: StrictBool = False


# A word number: a whole number, zero or more. Not a float, a string or a boolean.
WordNumber = Annotated[int, Field(strict=True, ge=0)]


class CutEditRequest(BaseModel):
    """One edit of one cut. A cut is named by the number of the last word of the scene it
    ends, so "after word 12" is the gap between word 12 and word 13.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["add", "remove", "move"]
    # Add: the gap to cut at. Remove and move: the cut to remove or move.
    after_word: WordNumber
    # Move only: the gap to move the cut to.
    to_after_word: WordNumber | None = None
    # Clear the description, frames and clip of the scenes the edit changes, if they have any.
    # Their files stay on disk.
    discard_inputs: StrictBool = False


class FrameOut(BaseModel):
    """A scene's first or last frame: the original upload, and how it will be framed."""

    asset_id: int
    # The original's size as displayed (after the EXIF orientation).
    width: int | None
    height: int | None
    mime: str
    size_bytes: int
    created_at: datetime
    # The file exactly as uploaded.
    original_url: str
    # The frame as it will be sent: RGB, centre-cropped and resized to the project's current
    # generation size. The size is in the address, so a page that is out of date gets a 404
    # instead of a wrong framing.
    preview_url: str
    # About cropping or enlarging, for the project's current generation size.
    warnings: list[str]


class SceneOut(BaseModel):
    id: int
    index: int
    start_s: float
    end_s: float
    text: str
    cut_source: CutSource
    # Why this scene's cut needs a look, if it does.
    cut_note: str | None
    has_inputs: bool
    # The scene's first and last word (numbers in `ScenesOut.words`). None while the cuts
    # cannot be edited (see `edit_blocked_reason`).
    first_word: int | None
    last_word: int | None
    # The saved description (what the user typed).
    scene_description: str | None
    # What will be sent to the video model: the project's style prefix, the saved description
    # and the prompt suffix. None while there is no description.
    prompt: str | None
    first_frame: FrameOut | None
    last_frame: FrameOut | None
    # What is still needed (description, first_frame, last_frame). Ready when nothing is.
    missing: list[MissingInput]
    ready: bool


class SceneWordOut(BaseModel):
    """One word of the script, as the scenes were cut from it."""

    index: int
    word: str
    paragraph: int


class UsageOut(BaseModel):
    prompt_tokens: int | None
    completion_tokens: int | None
    # Hidden reasoning tokens. They are part of `completion_tokens` and billed as output.
    reasoning_tokens: int | None


class ChecksOut(BaseModel):
    entries: int
    exact: int
    moved: int
    flagged: int
    dropped: int


class SplitterOut(BaseModel):
    cuts_added: int
    cuts_removed: int


class ProposalOut(BaseModel):
    """The proposal the scenes came from (the newest `plan_scenes` job that succeeded)."""

    job_id: int
    finished_at: datetime | None
    # "rule": the model could not be used, and the rule-based splitter proposed the scenes.
    source: Literal["ai", "rule"]
    fallback_reason: str | None
    # Set when no call was made because the same request had been answered by this job.
    cache_hit_of_job_id: int | None
    model: str | None
    usage: UsageOut | None
    checks: ChecksOut | None
    splitter: SplitterOut | None


class LlmInfoOut(BaseModel):
    model: str
    # The address the app will really call, after Docker mapping.
    will_call: str | None


class ScenesOut(BaseModel):
    job: JobSummary | None
    proposal: ProposalOut | None
    scenes: list[SceneOut]
    stale_reasons: list[StaleReasonOut]
    llm: LlmInfoOut
    # The script's words, for editing the cuts. Empty when editing is not possible.
    words: list[SceneWordOut]
    # Why the cuts cannot be edited now (no scenes, a proposal running, out of date...).
    edit_blocked_reason: str | None
    # How many scenes have a description and both frames.
    ready_count: int


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _int_or_zero(value: object) -> int:
    return _int(value) or 0


def _proposal_out(job: Job) -> ProposalOut:
    output: Any = job.output if isinstance(job.output, dict) else {}
    recorded: Any = job.input if isinstance(job.input, dict) else {}

    request = recorded.get("request")
    model = request.get("model") if isinstance(request, dict) else None

    usage = output.get("usage")
    checks = output.get("checks")
    splitter = output.get("splitter")
    fallback = output.get("fallback_reason")
    return ProposalOut(
        job_id=job.id,
        finished_at=job.finished_at,
        source="rule" if output.get("source") == "rule" else "ai",
        fallback_reason=fallback if isinstance(fallback, str) else None,
        cache_hit_of_job_id=_int(output.get("cache_hit_of_job_id")),
        model=model if isinstance(model, str) else None,
        usage=(
            UsageOut(
                prompt_tokens=_int(usage.get("prompt_tokens")),
                completion_tokens=_int(usage.get("completion_tokens")),
                reasoning_tokens=_int(usage.get("reasoning_tokens")),
            )
            if isinstance(usage, dict)
            else None
        ),
        checks=(
            ChecksOut(
                entries=_int_or_zero(checks.get("entries")),
                exact=_int_or_zero(checks.get("exact")),
                moved=_int_or_zero(checks.get("moved")),
                flagged=_int_or_zero(checks.get("flagged")),
                dropped=_int_or_zero(checks.get("dropped")),
            )
            if isinstance(checks, dict)
            else None
        ),
        splitter=(
            SplitterOut(
                cuts_added=_int_or_zero(splitter.get("cuts_added")),
                cuts_removed=_int_or_zero(splitter.get("cuts_removed")),
            )
            if isinstance(splitter, dict)
            else None
        ),
    )


def _frame_out(project: Project, asset: Asset | None) -> FrameOut | None:
    if asset is None:
        return None
    warnings: list[str] = []
    if asset.width is not None and asset.height is not None:
        warnings = frame_images.frame_warnings(
            asset.width, asset.height, project.gen_width, project.gen_height
        )
    return FrameOut(
        asset_id=asset.id,
        width=asset.width,
        height=asset.height,
        mime=asset.mime,
        size_bytes=asset.size_bytes,
        created_at=asset.created_at,
        original_url=media_url(asset.path),
        preview_url=(
            f"/api/projects/{project.id}/frames/{asset.id}/preview"
            f"?width={project.gen_width}&height={project.gen_height}"
        ),
        warnings=warnings,
    )


def _scene_out(
    scene: Scene,
    project: Project,
    frames: dict[int, Asset],
    first_word: int | None,
    last_word: int | None,
) -> SceneOut:
    missing = scene_inputs.missing_inputs(scene)
    return SceneOut(
        id=scene.id,
        index=scene.index,
        start_s=scene.start_s,
        end_s=scene.end_s,
        text=scene.text,
        # The database CHECK constraint keeps this to the allowed values.
        cut_source=cast(CutSource, scene.cut_source),
        cut_note=scene.cut_note,
        has_inputs=scene_cuts.has_inputs(scene),
        first_word=first_word,
        last_word=last_word,
        scene_description=scene.scene_description,
        prompt=scene_prompt.assemble_prompt(
            project.style_prefix, scene.scene_description, project.prompt_suffix
        ),
        first_frame=_frame_out(project, frames.get(scene.first_frame_asset_id or 0)),
        last_frame=_frame_out(project, frames.get(scene.last_frame_asset_id or 0)),
        missing=missing,
        ready=not missing,
    )


async def _llm_info(session: AsyncSession) -> LlmInfoOut:
    url = await settings_service.read_setting(session, LLM_URL_KEY)
    model = await settings_service.get_str(session, LLM_MODEL_KEY)
    return LlmInfoOut(model=model, will_call=url.will_call)


@router.post(
    "/projects/{project_id}/propose-scenes",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_NOT_READY, **_NEEDS_CONFIRMATION},
)
async def propose_scenes(
    project_id: int,
    session: SessionDep,
    body: ProposeScenesRequest | None = None,
) -> JobDetail:
    """Starts proposing scenes (a paid call to the language model), or returns the proposal
    that is already active. The same request as an earlier one reuses its stored answer
    unless `run_again` is sent.
    """
    flags = body or ProposeScenesRequest()
    project = await load_project(session, project_id)

    if project.voiceover_asset_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload a voiceover first.")
    if project.script_text is None or not project.script_text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Paste the script first.")

    state = await transcripts_service.transcription_state(session, project)
    transcript = state.transcript
    if transcript is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Transcribe the voiceover first."
        )
    if state.stale_reasons:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The transcript is out of date. Transcribe again first.",
        )
    word_count = len(transcript.script_words) if isinstance(transcript.script_words, list) else 0
    if word_count > scene_planner.MAX_SCRIPT_WORDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"This script has {word_count:,} words; scene proposal handles up to "
            f"{scene_planner.MAX_SCRIPT_WORDS:,}.",
        )

    if state.warnings and not flags.accept_mismatch:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The recording differs from the script. "
            + " ".join(state.warnings)
            + " Confirm to propose scenes anyway.",
        )

    with_inputs = await scenes_service.scenes_with_inputs(session, project.id)
    if with_inputs and not flags.discard_scenes_with_inputs:
        noun = "scene has" if with_inputs == 1 else "scenes have"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{with_inputs} {noun} a description, frames or a clip. Proposing scenes replaces "
            "all the scenes and discards those inputs (their files stay on disk). "
            "Confirm to continue.",
        )

    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=scenes_service.PLAN_JOB,
        provider="llm",
        input={
            "transcript_id": transcript.id,
            "voiceover_asset_id": project.voiceover_asset_id,
            "script_sha256": transcript_matching.script_sha256(project.script_text),
            "run_again": flags.run_again,
            "accept_mismatch": flags.accept_mismatch,
            "discard_scenes_with_inputs": flags.discard_scenes_with_inputs,
        },
    )
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=None))


async def scenes_out(session: AsyncSession, project: Project) -> ScenesOut:
    """What the page shows about a project's scenes. Reads the database only.

    Every endpoint that changes a scene answers with this, so the page shows the change
    without another request.
    """
    state = await scenes_service.scenes_state(session, project)
    llm_info = await _llm_info(session)
    view = await scenes_service.cuts_view(session, project, state)
    frames = await scene_inputs.load_frames(session, state.scenes)

    job_out = None
    if state.job is not None:
        job_out = job_summary(JobRow(job=state.job, project_name=project.name, scene_index=None))

    words: list[SceneWordOut] = []
    blocked_reason: str | None = None
    # Each scene's first and last word, from the cuts: a scene starts after the cut before it.
    ranges: list[tuple[int | None, int | None]] = [(None, None)] * len(state.scenes)
    if isinstance(view, str):
        blocked_reason = view
    else:
        words = [
            SceneWordOut(index=word.index, word=word.text, paragraph=word.paragraph)
            for word in view.words
        ]
        previous_last = -1
        ranges = []
        for cut in view.cuts:
            ranges.append((previous_last + 1, cut.last_word))
            previous_last = cut.last_word

    scene_outs = [
        _scene_out(scene, project, frames, first_word, last_word)
        for scene, (first_word, last_word) in zip(state.scenes, ranges, strict=True)
    ]
    return ScenesOut(
        job=job_out,
        proposal=_proposal_out(state.proposal) if state.proposal is not None else None,
        scenes=scene_outs,
        stale_reasons=state.stale_reasons,
        llm=llm_info,
        words=words,
        edit_blocked_reason=blocked_reason,
        ready_count=sum(1 for scene in scene_outs if scene.ready),
    )


@router.get(
    "/projects/{project_id}/scenes",
    response_model=ScenesOut,
    responses=_NOT_FOUND,
)
async def get_scenes(project_id: int, session: SessionDep) -> ScenesOut:
    """The project's scenes and the proposal they came from. Reads the database only."""
    project = await load_project(session, project_id)
    return await scenes_out(session, project)


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _scene_numbers(scenes: list[Scene]) -> str:
    """Reads 'Scene 4' or 'Scenes 3 and 4', with the numbers shown to the user (from 1)."""
    numbers = [str(scene.index + 1) for scene in scenes]
    if len(numbers) == 1:
        return f"Scene {numbers[0]}"
    return f"Scenes {' and '.join(numbers)}"


@router.post(
    "/projects/{project_id}/edit-cut",
    response_model=ScenesOut,
    responses={
        **_NOT_FOUND,
        409: {
            "model": ErrorResponse,
            "description": "A scene the edit changes has a description, frames or a clip, "
            "and the request did not confirm clearing them.",
        },
        422: {
            "model": ErrorResponse,
            "description": "The cuts cannot be edited now (no scenes, a proposal running, "
            "out of date), or this edit is not possible.",
        },
    },
)
async def edit_cut(project_id: int, body: CutEditRequest, session: SessionDep) -> ScenesOut:
    """Adds, removes or moves one cut, and returns the scenes as they are afterwards.

    Only the scenes next to the cut are rebuilt. An added or moved cut is a manual cut,
    timed in the middle of the gap. When a scene the edit changes has a description, frames
    or a clip, nothing happens until the request sets `discard_inputs`: then those inputs
    are cleared (their files stay on disk).
    """
    if body.action == "move" and body.to_after_word is None:
        raise _unprocessable("Moving a cut needs to_after_word.")
    if body.action != "move" and body.to_after_word is not None:
        raise _unprocessable("Only a move takes to_after_word.")

    project = await load_project(session, project_id)
    # Take the write lock, then read: what is read below cannot change before the commit.
    await scenes_service.lock_scenes(session, project.id)
    await session.refresh(project)

    state = await scenes_service.scenes_state(session, project)
    view = await scenes_service.cuts_view(session, project, state)
    if isinstance(view, str):
        raise _unprocessable(view)

    try:
        if body.action == "add":
            edit = cut_edits.add_cut(view.words, view.cuts, body.after_word)
        elif body.action == "remove":
            edit = cut_edits.remove_cut(view.words, view.cuts, body.after_word)
        else:
            # to_after_word is set for a move: checked at the top.
            move_to = cast(int, body.to_after_word)
            edit = cut_edits.move_cut(view.words, view.cuts, body.after_word, move_to)
        specs = scene_cuts.build_scene_specs(view.words, edit.cuts, view.audio_end_s)
    except ValueError as exc:  # CutEditError is one
        raise _unprocessable(str(exc)) from None

    affected = state.scenes[edit.first : edit.first + edit.old_count]
    with_inputs = [scene for scene in affected if scene_cuts.has_inputs(scene)]
    if with_inputs and not body.discard_inputs:
        verb = "has" if len(with_inputs) == 1 else "have"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{_scene_numbers(with_inputs)} {verb} a description, frames or a clip. This edit "
            "clears them (their files stay on disk). Confirm to continue.",
        )

    await scenes_service.apply_cut_edit(
        session,
        state.scenes,
        edit,
        specs[edit.first : edit.first + edit.new_count],
        clear_inputs=bool(with_inputs),
    )
    await session.commit()
    _logger.info(
        "project %d: cut edit %s after word %d%s: scenes %d to %d rebuilt, inputs cleared: %s",
        project.id,
        body.action,
        body.after_word,
        f" to after word {body.to_after_word}" if body.to_after_word is not None else "",
        edit.first + 1,
        edit.first + edit.new_count,
        "yes" if with_inputs else "no",
    )
    return await scenes_out(session, project)
