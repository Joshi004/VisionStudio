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
from app.jobs.draft_descriptions import DESCRIPTION_MODEL_KEY
from app.jobs.generate_clip import MAX_PARALLEL_KEY
from app.jobs.generate_frame import IMAGE_MODEL_KEY
from app.jobs.generate_frame import MAX_PARALLEL_KEY as MAX_PARALLEL_IMAGES_KEY
from app.jobs.plan_scenes import LLM_MODEL_KEY, LLM_URL_KEY
from app.jobs.store import JobRow
from app.jobs.write_image_prompt import IMAGE_PROMPT_MODEL_KEY
from app.providers import video_generator
from app.services import clips as clips_service
from app.services import (
    cut_edits,
    description_writer,
    frame_images,
    image_lab,
    scene_cuts,
    scene_inputs,
    scene_planner,
    scene_prompt,
    transcript_matching,
)
from app.services import descriptions as descriptions_service
from app.services import first_frames as first_frames_service
from app.services import image_prompts as image_prompts_service
from app.services import renders as renders_service
from app.services import scenes as scenes_service
from app.services import transcripts as transcripts_service
from app.services.scene_inputs import ClipMode, MissingInput
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
# Who wrote a text of a scene: the author (typed or edited), or the AI that drafts them.
TextSource = Literal["manual", "ai"]
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
    # Who made the file: the user (an upload), or the image model (`ai`). `derived` frames are
    # the copies sent to the video model and are never a scene's frame.
    source: Literal["upload", "ai", "derived"]
    # The `generate_frame` job that made an AI frame. None for an upload.
    job_id: int | None
    # An AI frame made from an image prompt that differs from the scene's now (computed, never
    # stored). False for an upload.
    out_of_date: bool


class TakeOut(BaseModel):
    """One finished clip of a scene (a succeeded `generate_clip` job and its asset)."""

    asset_id: int
    job_id: int
    # The clip's file, served from /media (with Range requests, so it seeks).
    url: str
    created_at: datetime
    seed: int | None
    # The frames in the file (counted by ffprobe) and the frames the scene needed.
    frame_count: int | None
    target_frames: int | None
    duration_s: float | None
    # The codec of the clip's own sound, None when it has none.
    audio_codec: str | None
    # How the clip was made: from the first frame alone, or from both frames. None for a clip
    # that did not record its endpoint.
    clip_mode: ClipMode | None
    # This is the take the final video uses.
    selected: bool
    # The scene's cuts have changed since this take was made.
    out_of_date: bool
    # The take has fewer frames than the scene needs now.
    too_short: bool


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
    # The saved description: the motion prompt, typed by the user or drafted by the AI.
    scene_description: str | None
    # Who wrote it. None while there is no description.
    scene_description_source: TextSource | None
    # What the first and last frame should show: a guide for making the frames, typed or
    # drafted. Each has its own source. The AI writes only the first one: the last-frame
    # description is for a last frame the user adds by hand.
    first_frame_description: str | None
    last_frame_description: str | None
    first_frame_description_source: TextSource | None
    last_frame_description_source: TextSource | None
    # The job that last wrote AI text into this scene. Kept after the user edits the text.
    description_job_id: int | None
    # The detailed prompt for the image model that makes the first frame (Phase 16), who wrote
    # it, and the `write_image_prompt` job that last wrote AI text into it.
    image_prompt: str | None
    image_prompt_source: TextSource | None
    image_prompt_job_id: int | None
    # The AI prompt was written from inputs that differ from the scene's now (computed from
    # the hash its job kept, never stored). False for a prompt the user wrote.
    image_prompt_out_of_date: bool
    # The newest job that writes this scene's image prompt, whatever its status.
    image_prompt_job: JobSummary | None
    # Why an image prompt cannot be written for this scene now, or None when it can.
    image_prompt_blocked_reason: str | None
    # What will be sent to the video model: the project's style prefix, the saved description
    # and the prompt suffix. None while there is no description.
    prompt: str | None
    first_frame: FrameOut | None
    last_frame: FrameOut | None
    # The first frame is an AI frame made from an image prompt that differs from the scene's now.
    first_frame_out_of_date: bool
    # The newest job that makes this scene's first frame, whatever its status (Phase 17).
    frame_job: JobSummary | None
    # Why that job's frame was not attached to the scene (it was kept among the earlier frames),
    # or None.
    frame_job_note: str | None
    # Why a first frame cannot be made for this scene now, or None when it can. Replacing an
    # upload is not a reason: the page asks first.
    frame_blocked_reason: str | None
    # The frames the scene can go back to, newest first: the frames its jobs made, and what
    # they replaced. The frame in use now is among them when an AI job made it.
    first_frame_choices: list[FrameOut]
    # What is still needed (description, first_frame). Ready when nothing is: the last frame
    # is optional.
    missing: list[MissingInput]
    ready: bool
    # How the clip will be made: from the first frame alone, or, when a last frame is
    # attached, from both frames (the clip is made to end on it).
    clip_mode: ClipMode
    # Whether the final video uses this scene's own clip sound.
    use_clip_sound: bool
    # The take the final video uses, if any.
    selected_clip_asset_id: int | None
    # How many frames the scene lasts at the project's frame rate (Phase 10 uses it too).
    target_frames: int
    # The newest clip job of this scene, whatever its status.
    clip_job: JobSummary | None
    # The server's usual time for such a job, as of its last check.
    clip_typical_run_seconds: float | None
    # Why a clip cannot be generated for this scene now, or None when it can.
    generate_blocked_reason: str | None
    # The finished clips, newest first.
    takes: list[TakeOut]


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
    # How many scenes have a description and a first frame.
    ready_count: int
    # How many scenes "Generate all ready scenes" would start: ready, no clip yet, nothing
    # running, and not blocked.
    generate_ready_count: int
    # The setting, so the page can say how many run at once.
    max_parallel_generations: int
    # Why the final video cannot be rendered now (a scene has no clip, a clip is too short,
    # the scenes are out of date...), or None when it can. Changes with every take or cut edit,
    # which answer with this object, so the Render button follows without another request.
    render_blocked_reason: str | None
    # The newest job that drafts the descriptions with AI, whatever its status (Phase 12).
    description_job: JobSummary | None
    # The model the next draft will call, and the address after Docker mapping.
    description_llm: LlmInfoOut
    # Why the descriptions cannot be drafted now, or None when they can.
    draft_blocked_reason: str | None
    # How many scenes have at least one text the AI may write (not the author's own).
    draftable_count: int
    # The model the next image prompt will be written by, and the address after Docker mapping.
    image_prompt_llm: LlmInfoOut
    # Why "Write image prompts" cannot start any job now, or None when it can.
    image_prompts_blocked_reason: str | None
    # How many jobs "Write image prompts" would start: scenes with text to work from and no
    # prompt or an out-of-date AI prompt, and nothing running.
    image_prompt_candidate_count: int
    # The model the next first frame will be made by (the Bitdeer image model), and the address
    # after Docker mapping.
    image_llm: LlmInfoOut
    # Why "Generate first frames" cannot start any job now, or None when it can.
    frames_blocked_reason: str | None
    # How many jobs "Generate first frames" would start: scenes with a current image prompt and
    # no first frame or an out-of-date AI one, and nothing running. Uploads are skipped.
    frame_candidate_count: int
    # The setting, so the page can say how many images are made at once.
    max_parallel_image_generations: int
    # Bitdeer's price for one image, in US dollars. An estimate: the page marks it so.
    price_per_image_usd: float


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


def _frame_out(
    project: Project, asset: Asset | None, *, out_of_date: bool = False
) -> FrameOut | None:
    if asset is None:
        return None
    provenance: Any = asset.provenance
    recorded_job = provenance.get("job_id") if isinstance(provenance, dict) else None
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
        # The database CHECK constraint keeps this to the allowed values.
        source=cast(Literal["upload", "ai", "derived"], asset.source),
        job_id=_int(recorded_job) if asset.source == "ai" else None,
        out_of_date=out_of_date,
    )


def _clip_typical_seconds(job: Job | None) -> float | None:
    """The server's usual run time, from the last status check stored on the job."""
    output = job.output if job is not None else None
    remote = output.get("remote") if isinstance(output, dict) else None
    value = remote.get("typical_run_seconds") if isinstance(remote, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _take_out(take: clips_service.Take, scene: Scene, project: Project) -> TakeOut:
    recorded = take.provenance
    audio = recorded.get("audio")
    codec = audio.get("codec") if isinstance(audio, dict) else None
    seed = recorded.get("seed")
    target = recorded.get("target_frames")
    return TakeOut(
        asset_id=take.asset.id,
        job_id=take.job.id,
        url=media_url(take.asset.path),
        created_at=take.asset.created_at,
        seed=_int(seed),
        frame_count=_int(recorded.get("frame_count")),
        target_frames=_int(target),
        duration_s=take.asset.duration_s,
        audio_codec=codec if isinstance(codec, str) else None,
        clip_mode=video_generator.clip_mode_for(recorded.get("endpoint")),
        selected=scene.selected_clip_asset_id == take.asset.id,
        out_of_date=clips_service.take_is_out_of_date(recorded, scene),
        too_short=clips_service.take_is_too_short(recorded, scene, project),
    )


def _scene_out(
    scene: Scene,
    project: Project,
    frames: dict[int, Asset],
    first_word: int | None,
    last_word: int | None,
    *,
    scenes_blocked: str | None,
    active_clip: Job | None,
    clip_job: Job | None,
    takes: list[clips_service.Take],
    prompt_out_of_date: bool,
    prompt_job: Job | None,
    prompt_blocked: str | None,
    frame_job: Job | None,
    frame_blocked: str | None,
    frame_choices: list[Asset],
) -> SceneOut:
    missing = scene_inputs.missing_inputs(scene)
    first_asset = frames.get(scene.first_frame_asset_id or 0)
    first_out_of_date = first_frames_service.frame_out_of_date(scene, first_asset)
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
        # The database CHECK constraints keep these to the allowed values.
        scene_description_source=cast(TextSource | None, scene.scene_description_source),
        first_frame_description=scene.first_frame_description,
        last_frame_description=scene.last_frame_description,
        first_frame_description_source=cast(
            TextSource | None, scene.first_frame_description_source
        ),
        last_frame_description_source=cast(TextSource | None, scene.last_frame_description_source),
        description_job_id=scene.description_job_id,
        image_prompt=scene.image_prompt,
        image_prompt_source=cast(TextSource | None, scene.image_prompt_source),
        image_prompt_job_id=scene.image_prompt_job_id,
        image_prompt_out_of_date=prompt_out_of_date,
        image_prompt_job=(
            job_summary(JobRow(job=prompt_job, project_name=project.name, scene_index=scene.index))
            if prompt_job is not None
            else None
        ),
        image_prompt_blocked_reason=prompt_blocked,
        prompt=scene_prompt.assemble_prompt(
            project.style_prefix, scene.scene_description, project.prompt_suffix
        ),
        first_frame=_frame_out(project, first_asset, out_of_date=first_out_of_date),
        last_frame=_frame_out(project, frames.get(scene.last_frame_asset_id or 0)),
        first_frame_out_of_date=first_out_of_date,
        frame_job=(
            job_summary(JobRow(job=frame_job, project_name=project.name, scene_index=scene.index))
            if frame_job is not None
            else None
        ),
        frame_job_note=first_frames_service.not_attached_note(frame_job),
        frame_blocked_reason=frame_blocked,
        first_frame_choices=[
            out
            for asset in frame_choices
            if (
                out := _frame_out(
                    project,
                    asset,
                    out_of_date=first_frames_service.frame_out_of_date(scene, asset),
                )
            )
            is not None
        ],
        missing=missing,
        ready=not missing,
        clip_mode=scene_inputs.clip_mode(scene),
        use_clip_sound=scene.use_clip_sound,
        selected_clip_asset_id=scene.selected_clip_asset_id,
        target_frames=clips_service.target_frames_for(scene, project),
        clip_job=(
            job_summary(JobRow(job=clip_job, project_name=project.name, scene_index=scene.index))
            if clip_job is not None
            else None
        ),
        clip_typical_run_seconds=_clip_typical_seconds(clip_job),
        generate_blocked_reason=clips_service.generation_block(
            scene, project, scenes_blocked=scenes_blocked, active=active_clip
        ),
        takes=[_take_out(take, scene, project) for take in takes],
    )


async def _llm_info(session: AsyncSession, model_key: str = LLM_MODEL_KEY) -> LlmInfoOut:
    url = await settings_service.read_setting(session, LLM_URL_KEY)
    model = await settings_service.get_str(session, model_key)
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

    # A proposal replaces every scene, and deleting a scene deletes its clip jobs.
    generating = len(await clips_service.active_clip_jobs(session, project.id))
    if generating:
        noun = "scene" if generating == 1 else "scenes"
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Clips are being generated for {generating} {noun}. Wait for them, or cancel "
            "them, before proposing scenes.",
        )
    # The same for image prompts (Phase 16): deleting a scene deletes the job that is writing
    # its prompt, and the paid answer with it.
    writing = len(await image_prompts_service.active_prompt_jobs(session, project.id))
    if writing:
        noun = "scene" if writing == 1 else "scenes"
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Image prompts are being written for {writing} {noun}. Wait for them to finish "
            "before proposing scenes.",
        )
    # And for first frames (Phase 17): the paid image would be lost with its scene's job.
    making = len(await first_frames_service.active_frame_jobs(session, project.id))
    if making:
        noun = "scene" if making == 1 else "scenes"
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"First frames are being made for {making} {noun}. Wait for them to finish "
            "before proposing scenes.",
        )

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


class DraftDescriptionsRequest(BaseModel):
    """What the user has confirmed. Every flag is off unless sent."""

    model_config = ConfigDict(extra="forbid")

    # Ask the model again even though the same request was answered before (paid).
    run_again: StrictBool = False


@router.post(
    "/projects/{project_id}/draft-descriptions",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **_NOT_FOUND,
        422: {
            "model": ErrorResponse,
            "description": "There are no scenes yet, a proposal is running, the scenes are out "
            "of date, there are too many, or every text was written by the user.",
        },
    },
)
async def draft_descriptions(
    project_id: int,
    session: SessionDep,
    body: DraftDescriptionsRequest | None = None,
) -> JobDetail:
    """Starts drafting the scene descriptions (a paid call to the language model), or returns
    the draft that is already active. The same request as an earlier one reuses its stored
    answer unless `run_again` is sent. Text the user wrote is never overwritten.
    """
    flags = body or DraftDescriptionsRequest()
    project = await load_project(session, project_id)

    state = await scenes_service.scenes_state(session, project)
    block = descriptions_service.draft_block(
        state.scenes, plan_job=state.job, stale_reasons=state.stale_reasons
    )
    if block is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, block)

    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=descriptions_service.DRAFT_JOB,
        provider="llm",
        input={"requested": "draft", "run_again": flags.run_again},
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
    description_llm = await _llm_info(session, DESCRIPTION_MODEL_KEY)
    description_job = await store.latest_job(session, project.id, descriptions_service.DRAFT_JOB)
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

    # Clips (Phase 9): the newest job and the finished takes of each scene, and whether the
    # scenes as a whole can be generated at all.
    scenes_blocked = clips_service.scenes_block_reason(state.job, state.stale_reasons)
    active_clips = await clips_service.active_clip_jobs(session, project.id)
    clip_jobs = await store.latest_jobs_by_scene(session, project.id, clips_service.GENERATE_JOB)
    takes = await clips_service.takes_by_scene(session, project.id)
    max_parallel = await settings_service.get_int(session, MAX_PARALLEL_KEY)

    # Image prompts (Phase 16): the newest job of each scene, which prompts are out of date
    # (computed from the hash their job kept), and why a prompt cannot be written.
    image_prompt_llm = await _llm_info(session, IMAGE_PROMPT_MODEL_KEY)
    prompt_jobs = await store.latest_jobs_by_scene(
        session, project.id, image_prompts_service.IMAGE_PROMPT_JOB
    )
    active_prompts = await image_prompts_service.active_prompt_jobs(session, project.id)
    prompt_states = await image_prompts_service.prompt_states(session, project, state.scenes)
    prompts_project_block = image_prompts_service.project_block(
        state.scenes,
        plan_job=state.job,
        stale_reasons=state.stale_reasons,
        draft_job=description_job,
    )

    def prompt_out_of_date(scene: Scene) -> bool:
        return scene.id in prompt_states and prompt_states[scene.id].out_of_date

    # First frames (Phase 17): the newest job of each scene, the frames each scene can go back
    # to, and why a frame cannot be made.
    image_llm = await _llm_info(session, IMAGE_MODEL_KEY)
    max_parallel_images = await settings_service.get_int(session, MAX_PARALLEL_IMAGES_KEY)
    frame_jobs = await store.latest_jobs_by_scene(
        session, project.id, first_frames_service.FRAME_JOB
    )
    active_frames = await first_frames_service.active_frame_jobs(session, project.id)
    choices = await first_frames_service.frame_choices(session, project.id)

    def frame_blocked(scene: Scene) -> str | None:
        return prompts_project_block or first_frames_service.scene_block(
            scene,
            prompt_out_of_date=prompt_out_of_date(scene),
            prompt_job_active=scene.id in active_prompts,
        )

    scene_outs = [
        _scene_out(
            scene,
            project,
            frames,
            first_word,
            last_word,
            scenes_blocked=scenes_blocked,
            active_clip=active_clips.get(scene.id),
            clip_job=clip_jobs.get(scene.id),
            takes=takes.get(scene.id, []),
            prompt_out_of_date=prompt_out_of_date(scene),
            prompt_job=prompt_jobs.get(scene.id),
            prompt_blocked=prompts_project_block or image_prompts_service.scene_block(scene),
            frame_job=frame_jobs.get(scene.id),
            frame_blocked=frame_blocked(scene),
            frame_choices=choices.get(scene.id, []),
        )
        for scene, (first_word, last_word) in zip(state.scenes, ranges, strict=True)
    ]
    frame_candidates = sum(
        1
        for scene in state.scenes
        if first_frames_service.is_candidate(
            scene,
            frames.get(scene.first_frame_asset_id or 0),
            prompt_out_of_date=prompt_out_of_date(scene),
            prompt_job_active=scene.id in active_prompts,
            frame_job_active=scene.id in active_frames,
        )
    )
    prompt_candidates = sum(
        1
        for scene in state.scenes
        if image_prompts_service.is_candidate(
            scene,
            out_of_date=prompt_out_of_date(scene),
            active=active_prompts.get(scene.id),
        )
    )
    generate_ready_count = sum(
        1
        for scene in state.scenes
        if clips_service.is_generate_all_candidate(
            scene,
            project,
            scenes_blocked=scenes_blocked,
            active=active_clips.get(scene.id),
        )
    )
    return ScenesOut(
        job=job_out,
        proposal=_proposal_out(state.proposal) if state.proposal is not None else None,
        scenes=scene_outs,
        stale_reasons=state.stale_reasons,
        llm=llm_info,
        words=words,
        edit_blocked_reason=blocked_reason,
        ready_count=sum(1 for scene in scene_outs if scene.ready),
        generate_ready_count=generate_ready_count,
        max_parallel_generations=max_parallel,
        render_blocked_reason=renders_service.render_block(
            project,
            state.scenes,
            renders_service.selected_takes(state.scenes, takes),
            plan_job=state.job,
            stale_reasons=state.stale_reasons,
        ),
        description_job=(
            job_summary(JobRow(job=description_job, project_name=project.name, scene_index=None))
            if description_job is not None
            else None
        ),
        description_llm=description_llm,
        draft_blocked_reason=descriptions_service.draft_block(
            state.scenes, plan_job=state.job, stale_reasons=state.stale_reasons
        ),
        draftable_count=description_writer.draftable_count(state.scenes),
        image_prompt_llm=image_prompt_llm,
        image_prompts_blocked_reason=prompts_project_block
        or image_prompts_service.all_block(prompt_candidates, len(active_prompts)),
        image_prompt_candidate_count=prompt_candidates,
        image_llm=image_llm,
        frames_blocked_reason=prompts_project_block
        or first_frames_service.all_block(frame_candidates, len(active_frames)),
        frame_candidate_count=frame_candidates,
        max_parallel_image_generations=max_parallel_images,
        price_per_image_usd=image_lab.PRICE_PER_IMAGE_USD,
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
    # A clip being generated belongs to the scene as it is. Only the scenes this edit changes
    # are protected, so the rest of the cuts stay editable during a long batch.
    active_clips = await clips_service.active_clip_jobs(session, project.id)
    generating = [scene for scene in affected if scene.id in active_clips]
    if generating:
        verb = "has" if len(generating) == 1 else "have"
        pronoun = "it" if len(generating) == 1 else "them"
        raise _unprocessable(
            f"{_scene_numbers(generating)} {verb} a clip being generated. Wait for {pronoun} "
            "to finish, or cancel the job, before changing this cut."
        )
    # An image prompt being written is lost with its scene's jobs, paid answer included.
    active_prompts = await image_prompts_service.active_prompt_jobs(session, project.id)
    writing = [scene for scene in affected if scene.id in active_prompts]
    if writing:
        verb = "has" if len(writing) == 1 else "have"
        pronoun = "it" if len(writing) == 1 else "them"
        raise _unprocessable(
            f"{_scene_numbers(writing)} {verb} an image prompt being written. Wait for "
            f"{pronoun} to finish before changing this cut."
        )
    # A first frame being made is lost the same way (Phase 17).
    active_frames = await first_frames_service.active_frame_jobs(session, project.id)
    making = [scene for scene in affected if scene.id in active_frames]
    if making:
        verb = "has" if len(making) == 1 else "have"
        pronoun = "it" if len(making) == 1 else "them"
        raise _unprocessable(
            f"{_scene_numbers(making)} {verb} a first frame being made. Wait for {pronoun} "
            "to finish before changing this cut."
        )
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
