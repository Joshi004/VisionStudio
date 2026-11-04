"""`/api/projects/{project_id}/shot-takes`: the generation of each shot's clip (PHASE-027).

- `GET ...` answers everything the story workspace shows in one call: the newest list of scenes,
  and for each scene its shots (from the newest shot plan) with the status of each shot's
  generation (`not_generated`, `generated`, `out_of_date`, `failed`, `unchecked`), why it is out
  of date, every take of the shot (newest first, with the clip's address, its measured length,
  its state: `generating`, `ready` or `failed`, and its technical check), which take is
  selected (only a take that passed its check can be), the newest job, and whether Generate may
  be pressed. Out of date is worked out on every read.
- `POST .../check` ("Check takes") starts the local job that checks the clips made before the
  checks existed. It starts no generation.
- `POST .../rescore-dialogue` ("Score dialogue again", SCN-001) judges every failed dialogue check
  again from its stored transcript, with no GPU work and no new job, and answers what changed.
- `POST .../run` ("Generate all") starts one job for every shot, in every scene, whose prompt is
  compiled and current and that has no current take and is not already being generated.
- `POST .../{scene_id}/run` starts the jobs for the shots of one scene, and pushes the scene to the
  front of the GPU server's queue.
- `POST .../{scene_id}/push` and `DELETE .../push` (SCN-002) push one scene to the front of the
  server's queue, and end the push. Neither starts a generation.
- `POST .../{scene_id}/{shot_id}/run` starts one more take of one shot (Generate or Regenerate).
- `PUT .../{scene_id}/{shot_id}/voice-source` (FLOW-008) sets which voice a presenter shot of a
  continuous explainer is heard with in the render: `take` (the default) or `clip`. It only makes
  the render out of date.
- `POST .../{scene_id}/{shot_id}/takes/{take_id}/select` makes a ready take the shot's selected
  one, also a take that failed a check (the user accepts it), and stops the shot's automatic
  retries.

A shot that continues the one before it (PHASE-032) names it in `continues_from`, waits (its
`blocked_reason` says so) until that shot has a take that passed its checks, and carries on each
take the `anchor` it was cut from. **Generate all** and **Generate scene** chain such shots.

A job makes a new take (`services/shot_takes.py`); nothing is written to the Character Lab and no
other shot changes. The answers never return ORM objects.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import jobs as jobs_api
from app.api.discovery import DiscoveryJobOut
from app.api.environment_links import DiscoveryId
from app.api.errors import ErrorResponse
from app.api.jobs import JobStatus
from app.api.projects import load_project
from app.api.scene_filter import (
    SceneIdQuery,
    SceneShotsSummaryOut,
    ShotsQuery,
    includes_shots,
    is_active,
    summarize,
)
from app.db.models import Asset, Job
from app.db.session import SessionDep
from app.jobs import dispatcher
from app.services import gpu_priority, shot_takes, shot_voice_sources, storage
from app.services.shot_takes import SceneEntry, ShotEntry, TakeEntry

_logger = logging.getLogger(__name__)

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such project."}}
_INVALID = {
    422: {
        "model": ErrorResponse,
        "description": "The shot's prompt is not compiled and current, a picture or an audio "
        "file is missing, the remote server API has no such endpoint, the take has no clip or "
        "its checks are not done, or the scene, shot or take is not in the newest list of "
        "scenes and shot plan.",
    }
}

Status = Literal["not_generated", "generated", "out_of_date", "failed", "unchecked"]
TakeState = Literal["generating", "checking_dialogue", "ready", "failed"]
PromptStatus = Literal["not_compiled", "compiled", "out_of_date"]
# `presenter` is the type of a shot of a continuous explainer that shows the presenter (FLOW-005).
ShotType = Literal[
    "establishing",
    "action",
    "reaction",
    "dialogue",
    "insert",
    "transition",
    "presenter",
    "graphic",
]
ProblemKind = Literal["clip", "plan"]
DialogueOutcome = Literal["matched", "close_match", "not_verifiable", "mismatch", "no_speech"]
VoiceSource = Literal["take", "clip"]


class TakeProblemOut(BaseModel):
    code: str
    message: str


class TakeValidationOut(BaseModel):
    """The technical check of a take's clip (PHASE-029). `kind` is `clip` when another seed may
    fix it (retried automatically) and `plan` when the shot's scene has to be planned again.
    """

    passed: bool
    kind: ProblemKind | None
    problems: list[TakeProblemOut]
    checked_at: datetime | None
    # True when the check failed and the user selected the take anyway.
    accepted: bool


class DialogueLineOut(BaseModel):
    """One dialogue line the clip must contain."""

    unit_id: str
    label: str
    text: str
    starts_in_shot_seconds: float


class TakeDialogueOut(BaseModel):
    """The speech-recognition check of a take with dialogue (PHASE-031): what Parakeet heard in
    the clip next to the shot's lines. `similarity` and `threshold` are percents.
    """

    passed: bool
    similarity: float
    threshold: int
    problems: list[TakeProblemOut]
    # The intended words and the heard words after normalizing (lower case, no punctuation).
    expected_text: str
    heard_text: str
    checked_at: datetime | None
    # True when the check failed and the user selected the take anyway.
    accepted: bool
    # SCN-001: what kind of answer the check gave, and the matching step at which it passed
    # (`exact`, `numbers`, `spelling`, `homophones`, `short_line`, `not_verifiable`; None when it
    # failed). `close_match` is a pass under the short-line rule, and `not_verifiable` a pass
    # because nothing was heard on a line too slight to check.
    outcome: DialogueOutcome = "matched"
    rule: str | None = None


AnchorUse = Literal["first_frame", "reference"]


class TakeAnchorOut(BaseModel):
    """PHASE-032: what a take of a continuity shot was cut from. Its first frame (or one more
    reference picture) is frame `frame_index` of take `take_number` of the shot `from_shot_id`,
    the frame that take shows last at its shot's target duration.
    """

    from_shot_id: str
    take_id: int
    take_number: int
    frame_index: int | None
    use: AnchorUse
    # The frame's own address, so it can be looked at. None when the file is gone.
    url: str | None


class ShotTakeOut(BaseModel):
    id: int
    take_number: int
    state: TakeState
    # True for the one take of the shot that is selected.
    selected: bool
    seed: int
    # The clip's address; None until the take is ready.
    url: str | None
    # What the clip measured at ffprobe, None until the take is ready.
    duration_s: float | None
    frame_count: int | None
    width: int | None
    height: int | None
    has_audio: bool | None
    size_bytes: int | None
    # Why this take is out of date, one sentence each. Empty when it is current.
    reasons: list[str]
    created_at: datetime
    selected_at: datetime | None
    job: DiscoveryJobOut | None
    # The technical check, or None when the clip has not been checked.
    validation: TakeValidationOut | None
    # 0 for a take somebody asked for; n for the nth automatic retry of a failed clip.
    retry_attempt: int
    # The lines of dialogue the clip must contain. Empty for a shot with no dialogue, whose take
    # is never transcribed.
    dialogue: list[DialogueLineOut]
    # The speech-recognition check, or None when it was not made (yet).
    dialogue_check: TakeDialogueOut | None
    # The newest job of the take's dialogue check, whatever its status.
    dialogue_job: DiscoveryJobOut | None
    # The take of the shot before it that this take continues (PHASE-032), or None.
    anchor: TakeAnchorOut | None = None
    # The version of the shot prompt this take was made from, or None (PHASE-038).
    prompt_version: int | None = None


class TakeShotSkeletonOut(BaseModel):
    id: str
    type: ShotType
    description: str
    # The shot's length on the timeline: the clip is at least this long.
    duration_seconds: float


class ShotTakesEntryOut(BaseModel):
    shot: TakeShotSkeletonOut
    status: Status
    # Why the selected take is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # Where the shot's compiled prompt stands: the clip is generated from it.
    prompt_status: PromptStatus
    takes: list[ShotTakeOut]
    selected_take_id: int | None
    # The newest take's job, whatever its status.
    job: DiscoveryJobOut | None
    can_run: bool
    blocked_reason: str | None
    # PHASE-032: the id of the shot before it when this shot continues it with no cut, else
    # None. While that shot has no current, passing take, `blocked_reason` says this shot waits.
    continues_from: str | None = None
    # FLOW-008: the voice a presenter shot of a continuous explainer is heard with in the render,
    # the scene's voice take or its clip's own sound. None for every other shot.
    voice_source: VoiceSource | None = None
    # SCN-001: the shot failed and its two newest takes heard the same words, so no more takes
    # are made by themselves. The owner listens and uses a take anyway, or changes the prompt.
    needs_review: bool = False


class SceneShotTakesOut(BaseModel):
    """One scene of the newest list of scenes."""

    id: str
    index: int
    title: str
    description: str
    # Empty when the list was asked for without this scene's shots; `summary` still counts them.
    shots: list[ShotTakesEntryOut]
    summary: SceneShotsSummaryOut


class ShotTakesOut(BaseModel):
    # None when the project has no discovered scenes yet.
    scenes_version: int | None
    entries: list[SceneShotTakesOut]
    # Why nothing can be generated yet, or None.
    blocked_reason: str | None
    # How many ready takes have no check yet, and the newest job that checks them.
    unchecked_count: int
    check_job: DiscoveryJobOut | None
    # The most automatic retries a failed clip gets (0 means none).
    max_retries: int
    # SCN-001: how many takes have a failed dialogue check that "Score dialogue again" can judge.
    rescorable_count: int = 0
    # SCN-002: the scene pushed to the front of the GPU server's queue, or None.
    pushed_scene_id: str | None = None


class PushSceneOut(BaseModel):
    """What a push (or "Stop pushing") did to the clips of the scene that already wait on the
    GPU server. Clips not yet sent take the new level when they are sent.
    """

    # The scene pushed (or, after a stop, the scene that was pushed). None when none was.
    scene_id: str | None
    # Clips whose priority on the server was changed.
    changed: int
    # Clips that had already started (or were gone): nothing to change.
    already_running: int
    # Clips whose change the server did not answer. They keep their old level.
    not_reached: int


class ShotTakesSkippedOut(BaseModel):
    scene_id: str
    # None when the whole scene was skipped.
    shot_id: str | None
    title: str
    reason: str


class ShotTakesRunManyOut(BaseModel):
    job_ids: list[int]
    skipped: list[ShotTakesSkippedOut]


class ShotTakesRunOneOut(BaseModel):
    job_id: int


class SelectedTakeOut(BaseModel):
    take_id: int
    selected_at: datetime


class ShotTakesCheckOut(BaseModel):
    job_id: int


class RescoredTakeOut(BaseModel):
    scene_id: str
    shot_id: str
    take_number: int


class RescoreDialogueOut(BaseModel):
    """What "Score dialogue again" did (SCN-001): no clip was made and no job was queued."""

    # How many failed dialogue checks were judged again.
    rescored: int
    # How many of them pass now, by the matching step at which they passed.
    now_passing_by_rule: dict[str, int]
    still_failing: int
    # The takes that became their shot's selected take.
    selected: list[RescoredTakeOut]


class VoiceSourceIn(BaseModel):
    source: VoiceSource


class VoiceSourceOut(BaseModel):
    source: VoiceSource


def _job_out(job: Job | None) -> DiscoveryJobOut | None:
    if job is None:
        return None
    return DiscoveryJobOut(
        id=job.id,
        status=cast(JobStatus, job.status),
        phase=job.phase,
        error=job.error,
    )


def _validation_out(validation: dict[str, Any] | None) -> TakeValidationOut | None:
    if validation is None:
        return None
    checked_at = validation.get("checked_at")
    return TakeValidationOut(
        passed=validation.get("passed") is True,
        kind=cast(ProblemKind | None, validation.get("kind")),
        problems=[
            TakeProblemOut(code=problem["code"], message=problem["message"])
            for problem in validation.get("problems", [])
        ],
        checked_at=datetime.fromisoformat(checked_at) if isinstance(checked_at, str) else None,
        accepted=validation.get("accepted_at") is not None,
    )


def _dialogue_outcome(result: dict[str, Any], problems: list[Any]) -> DialogueOutcome:
    """The outcome a check recorded. A check made before SCN-001 recorded none: a pass is
    `matched`, and a failure is told by its problem code.
    """
    stored = result.get("outcome")
    if stored in ("matched", "close_match", "not_verifiable", "mismatch", "no_speech"):
        return cast(DialogueOutcome, stored)
    if result.get("passed") is True:
        return "matched"
    codes = [problem.get("code") for problem in problems if isinstance(problem, dict)]
    return "no_speech" if "no_speech" in codes else "mismatch"


def _dialogue_check_out(result: dict[str, Any] | None) -> TakeDialogueOut | None:
    if result is None:
        return None
    checked_at = result.get("checked_at")
    similarity = result.get("similarity")
    threshold = result.get("threshold")
    problems = result.get("problems", [])
    return TakeDialogueOut(
        outcome=_dialogue_outcome(result, problems),
        rule=result.get("rule") if isinstance(result.get("rule"), str) else None,
        passed=result.get("passed") is True,
        similarity=float(similarity) if isinstance(similarity, int | float) else 0.0,
        threshold=threshold if isinstance(threshold, int) else 0,
        problems=[
            TakeProblemOut(code=problem["code"], message=problem["message"])
            for problem in result.get("problems", [])
        ],
        expected_text=str(result.get("expected_text", "")),
        heard_text=str(result.get("heard_text", "")),
        checked_at=datetime.fromisoformat(checked_at) if isinstance(checked_at, str) else None,
        accepted=result.get("accepted_at") is not None,
    )


def _anchor_out(entry: TakeEntry, frame_urls: dict[int, str]) -> TakeAnchorOut | None:
    anchor = entry.anchor
    if anchor is None:
        return None
    frame_index = anchor.get("frame_index")
    asset_id = anchor.get("asset_id")
    return TakeAnchorOut(
        from_shot_id=str(anchor.get("from_shot_id")),
        take_id=int(anchor["take_id"]),
        take_number=int(anchor["take_number"]),
        frame_index=frame_index if isinstance(frame_index, int) else None,
        use=cast(AnchorUse, anchor.get("use")),
        url=frame_urls.get(asset_id) if isinstance(asset_id, int) else None,
    )


def _take_out(entry: TakeEntry, frame_urls: dict[int, str]) -> ShotTakeOut:
    row = entry.row
    audio = row.audio
    return ShotTakeOut(
        id=row.id,
        take_number=row.take_number,
        state=entry.state,
        selected=entry.selected,
        seed=row.seed,
        url=storage.media_url(row.path) if row.path is not None else None,
        duration_s=row.duration_s,
        frame_count=row.frame_count,
        width=row.width,
        height=row.height,
        has_audio=(audio is not None) if row.path is not None else None,
        size_bytes=row.size_bytes,
        reasons=entry.reasons,
        created_at=row.created_at,
        selected_at=row.selected_at,
        job=_job_out(entry.job),
        validation=_validation_out(entry.validation),
        retry_attempt=entry.retry_attempt,
        dialogue=[
            DialogueLineOut(
                unit_id=line.unit_id,
                label=line.label,
                text=line.text,
                starts_in_shot_seconds=line.starts_in_shot_seconds,
            )
            for line in entry.dialogue
        ],
        dialogue_check=_dialogue_check_out(entry.dialogue_result),
        dialogue_job=_job_out(entry.dialogue_job),
        anchor=_anchor_out(entry, frame_urls),
        prompt_version=shot_takes.prompt_version_of(row),
    )


def _shot_out(entry: ShotEntry, frame_urls: dict[int, str]) -> ShotTakesEntryOut:
    shot = entry.shot
    selected = entry.selected
    return ShotTakesEntryOut(
        shot=TakeShotSkeletonOut(
            id=shot["id"],
            type=shot["type"],
            description=shot["description"],
            duration_seconds=entry.duration_s,
        ),
        status=entry.status,
        reasons=entry.reasons,
        prompt_status=cast(PromptStatus, entry.prompt_status),
        takes=[_take_out(take, frame_urls) for take in entry.takes],
        selected_take_id=selected.row.id if selected is not None else None,
        job=_job_out(entry.job),
        can_run=entry.can_run,
        blocked_reason=entry.blocked_reason,
        continues_from=entry.continues_from,
        voice_source=cast(VoiceSource | None, entry.voice_source),
        needs_review=entry.needs_review,
    )


def _is_working(shot: ShotEntry) -> bool:
    """True when the shot's newest take is being made, or a take's speech is being checked."""
    return is_active(shot.job) or any(is_active(take.dialogue_job) for take in shot.takes)


def _scene_out(
    entry: SceneEntry, frame_urls: dict[int, str], with_shots: bool
) -> SceneShotTakesOut:
    return SceneShotTakesOut(
        id=entry.item["id"],
        index=entry.item["index"],
        title=entry.item["title"],
        description=entry.item["description"],
        shots=[_shot_out(shot, frame_urls) for shot in entry.shots] if with_shots else [],
        summary=summarize(
            entry.shots,
            status=lambda shot: shot.status,
            active=_is_working,
            # What "Generate scene" starts: no good clip, and not waiting for a check.
            todo=lambda shot: shot.can_run and shot.status not in ("generated", "unchecked"),
        ),
    )


async def _frame_urls(scenes: Sequence[SceneEntry], session: AsyncSession) -> dict[int, str]:
    """The address of every anchor frame the takes of these scenes name, by asset id (PHASE-032)."""
    ids: set[int] = set()
    for scene in scenes:
        for shot in scene.shots:
            for take in shot.takes:
                asset_id = take.anchor.get("asset_id") if take.anchor is not None else None
                if isinstance(asset_id, int):
                    ids.add(asset_id)
    if not ids:
        return {}
    rows = (await session.execute(select(Asset.id, Asset.path).where(Asset.id.in_(ids)))).all()
    return {asset_id: storage.media_url(path) for asset_id, path in rows}


def _run_many_out(started: shot_takes.StartResult) -> ShotTakesRunManyOut:
    return ShotTakesRunManyOut(
        job_ids=started.job_ids,
        skipped=[
            ShotTakesSkippedOut(
                scene_id=item.scene_id,
                shot_id=item.shot_id,
                title=item.title,
                reason=item.reason,
            )
            for item in started.skipped
        ],
    )


def _refused(exc: shot_takes.ShotTakesError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get(
    "/projects/{project_id}/shot-takes",
    response_model=ShotTakesOut,
    responses=_NOT_FOUND,
)
async def get_shot_takes(
    project_id: int,
    session: SessionDep,
    scene_id: SceneIdQuery = None,
    shots: ShotsQuery = True,
) -> ShotTakesOut:
    project = await load_project(session, project_id)
    result = await shot_takes.state(session, project)
    sent = {
        entry.item["id"]: includes_shots(entry.item["id"], scene_id, shots)
        for entry in result.entries
    }
    frame_urls = await _frame_urls(
        [entry for entry in result.entries if sent[entry.item["id"]]], session
    )
    return ShotTakesOut(
        scenes_version=result.scenes_version,
        entries=[_scene_out(entry, frame_urls, sent[entry.item["id"]]) for entry in result.entries],
        blocked_reason=result.blocked_reason,
        unchecked_count=result.unchecked_count,
        check_job=_job_out(result.check_job),
        max_retries=result.max_retries,
        rescorable_count=result.rescorable_count,
        pushed_scene_id=project.pushed_scene_id,
    )


@router.post(
    "/projects/{project_id}/shot-takes/check",
    response_model=ShotTakesCheckOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def check_takes(project_id: int, session: SessionDep) -> ShotTakesCheckOut:
    """Starts the job that checks the clips made before the checks existed. It starts no
    generation. If it is already waiting or running, that job's id is returned.
    """
    project = await load_project(session, project_id)
    try:
        job = await shot_takes.start_check(session, project)
    except shot_takes.ShotTakesError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return ShotTakesCheckOut(job_id=job.id)


@router.post(
    "/projects/{project_id}/shot-takes/rescore-dialogue",
    response_model=RescoreDialogueOut,
    responses=_NOT_FOUND,
)
async def rescore_dialogue(project_id: int, session: SessionDep) -> RescoreDialogueOut:
    """Judges every failed dialogue check of the project again from the words it recorded as
    heard, with the current matching rules (SCN-001). Nothing is transcribed, no clip is made and
    no job is queued. A shot with no selected take gets its newest take that passes now.
    """
    project = await load_project(session, project_id)
    report = await shot_takes.rescore_dialogue(session, project)
    return RescoreDialogueOut(
        rescored=report.rescored,
        now_passing_by_rule=report.now_passing_by_rule,
        still_failing=report.still_failing,
        selected=[
            RescoredTakeOut(scene_id=scene_id, shot_id=shot_id, take_number=number)
            for scene_id, shot_id, number in report.selected
        ],
    )


@router.post(
    "/projects/{project_id}/shot-takes/run",
    response_model=ShotTakesRunManyOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_all(project_id: int, session: SessionDep) -> ShotTakesRunManyOut:
    """Starts a job for every shot that has no current take and is not already being
    generated. The shots that cannot be generated are skipped, with the reason.
    """
    project = await load_project(session, project_id)
    try:
        started = await shot_takes.start_all(session, project)
    except shot_takes.ShotTakesError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        dispatcher.nudge()
    return _run_many_out(started)


@router.post(
    "/projects/{project_id}/shot-takes/{scene_id}/run",
    response_model=ShotTakesRunManyOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_scene(
    project_id: int, scene_id: DiscoveryId, session: SessionDep
) -> ShotTakesRunManyOut:
    """Starts a job for every shot of one scene that has no current take and is not already
    being generated.
    """
    project = await load_project(session, project_id)
    try:
        started = await shot_takes.start_scene(session, project, scene_id)
    except shot_takes.ShotTakesError as exc:
        raise _refused(exc) from exc
    if started.job_ids:
        # The owner asked for this scene now (SCN-002): its clips go to the front of the
        # server's queue. Done before the nudge, so the new jobs are sent at level 1.
        try:
            await gpu_priority.push_scene(session, project, scene_id)
        except gpu_priority.PushError:
            _logger.warning("scene '%s' of project %d could not be pushed", scene_id, project.id)
        dispatcher.nudge()
    return _run_many_out(started)


def _push_out(report: gpu_priority.PushReport) -> PushSceneOut:
    return PushSceneOut(
        scene_id=report.scene_id,
        changed=report.changed,
        already_running=report.already_running,
        not_reached=report.not_reached,
    )


@router.post(
    "/projects/{project_id}/shot-takes/{scene_id}/push",
    response_model=PushSceneOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def push_scene(project_id: int, scene_id: DiscoveryId, session: SessionDep) -> PushSceneOut:
    """Pushes one scene to the front of the GPU server's queue (SCN-002): its clips are sent
    with the most urgent priority, and the ones already waiting on the server are changed. A
    scene pushed before goes back to its place in story order. Starts no generation.
    """
    project = await load_project(session, project_id)
    try:
        report = await gpu_priority.push_scene(session, project, scene_id)
    except gpu_priority.PushError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _push_out(report)


@router.delete(
    "/projects/{project_id}/shot-takes/push",
    response_model=PushSceneOut,
    responses=_NOT_FOUND,
)
async def stop_push(project_id: int, session: SessionDep) -> PushSceneOut:
    """Ends the push: the scene's clips go back to their place in story order. Does nothing
    when no scene is pushed.
    """
    project = await load_project(session, project_id)
    return _push_out(await gpu_priority.stop_push(session, project))


@router.post(
    "/projects/{project_id}/shot-takes/{scene_id}/{shot_id}/run",
    response_model=ShotTakesRunOneOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_INVALID},
)
async def run_shot(
    project_id: int, scene_id: DiscoveryId, shot_id: DiscoveryId, session: SessionDep
) -> ShotTakesRunOneOut:
    """Starts the job that makes one more take of a shot. If it already has a job waiting or
    running, that job's id is returned and no second take is made.
    """
    project = await load_project(session, project_id)
    try:
        job = await shot_takes.start_shot(session, project, scene_id, shot_id)
    except shot_takes.ShotTakesError as exc:
        raise _refused(exc) from exc
    dispatcher.nudge()
    return ShotTakesRunOneOut(job_id=job.id)


@router.post(
    "/projects/{project_id}/shot-takes/{scene_id}/{shot_id}/takes/{take_id}/select",
    response_model=SelectedTakeOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def select_take(
    project_id: int,
    scene_id: DiscoveryId,
    shot_id: DiscoveryId,
    take_id: int,
    session: SessionDep,
) -> SelectedTakeOut:
    """Makes a ready take the selected one of its shot. A take that failed a check is accepted
    as it is. The shot's automatic retries that are waiting or running are cancelled, since the
    user is satisfied. When the take was accepted although it failed and was made by **Generate
    all** or **Generate scene**, the shot that continues it is queued, as it would have been had
    the take passed. The other shots do not change.
    """
    project = await load_project(session, project_id)
    try:
        take = await shot_takes.select_take(session, project, scene_id, shot_id, take_id)
    except shot_takes.ShotTakesError as exc:
        raise _refused(exc) from exc
    assert take.selected_at is not None  # `select_take` just set it
    selected = SelectedTakeOut(take_id=take.id, selected_at=take.selected_at)
    accepted_failed_take = shot_takes.overridden(take)

    # A retry that cannot be cancelled now (it is downloading its clip, or the GPU server does
    # not answer) finishes, but neither replaces this choice nor is retried (`chosen_since`).
    for job in await shot_takes.active_retry_jobs(session, project.id, scene_id, shot_id):
        try:
            await jobs_api.cancel_job(job.id, session)
        except HTTPException as exc:
            _logger.info("take %d selected: retry job %d not cancelled: %s", take_id, job.id, exc)

    if accepted_failed_take:
        try:
            dependent = await shot_takes.start_dependents(session, take_id)
        except Exception:
            _logger.exception("take %d: the shot that continues it could not be queued", take_id)
        else:
            if dependent is not None:
                dispatcher.nudge()
    return selected


@router.put(
    "/projects/{project_id}/shot-takes/{scene_id}/{shot_id}/voice-source",
    response_model=VoiceSourceOut,
    responses={**_NOT_FOUND, **_INVALID},
)
async def set_voice_source(
    project_id: int,
    scene_id: DiscoveryId,
    shot_id: DiscoveryId,
    body: VoiceSourceIn,
    session: SessionDep,
) -> VoiceSourceOut:
    """Sets the voice a presenter shot of a continuous explainer is heard with in the render:
    the scene's voice take (`take`, the default) or its clip's own sound (`clip`). No clip is
    made again; only the render becomes out of date. Any other shot is refused.
    """
    project = await load_project(session, project_id)
    try:
        source = await shot_voice_sources.set_source(
            session, project, scene_id, shot_id, body.source
        )
    except shot_voice_sources.ShotVoiceSourceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return VoiceSourceOut(source=source)
