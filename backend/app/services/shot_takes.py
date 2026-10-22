"""The generation of a shot's clip (PHASE-027, `Path_ahead.md` Section 31).

Each shot whose H3 prompt is compiled (PHASE-026) and current can be sent to the video model. One
press makes one **take** of the shot: a `shot_take` row and one `generate_shot` job (a GPU job,
`jobs/generate_shot.py`) that uploads the shot's pictures and dialogue audio, submits the request
and stores the clip on the take. Several takes of one shot never replace each other, and shots
run side by side when the GPU pool allows (`store.create_job` with `dedupe_key`).

- **Nothing is queued by itself.** The buttons are **Generate all**, **Generate scene** and
  **Generate** (or **Regenerate**) of one shot. A clip holds 4 to 8 GPUs, so a person starts it.
- **The request is built here, when the job is queued** (as `video_lab.create_h3_reference_run`
  does for the lab): the body is made from the shot's generation request (the endpoint, the size
  and the frame count, PHASE-025) and its compiled prompt (PHASE-026), with a **new random seed
  for every take** and the `gpu_partition` setting. The endpoint is checked against the newest
  recorded GPU API. The body is stored on the job and sent again unchanged after a pre-emption.
- **The selected take of a shot is its ready take that passed its technical check, with the
  newest `selected_at`.** A take gets `selected_at` when its job finishes (only if it passed) and
  when the user selects it (only a passing take), so whichever happened last decides.
- **Every clip is checked in code (PHASE-029, `take_validation.py`)** when it is stored. A clip
  that fails for a reason a new seed can fix is generated again by itself, up to the
  `shot_take_max_retries` setting (`queue_retry`). The takes made before the checks existed are
  checked by the `check_shot_takes` job (`start_check`).
- **A take whose shot carries dialogue is checked a second time (PHASE-031).** After its clip
  passes the technical check, the `check_take_dialogue` job transcribes it with Parakeet and
  compares the heard words with the shot's dialogue lines (`dialogue_check.py`); the result is on
  `shot_take.dialogue_check`. Such a take is selected, by the job or by the user, only when both
  checks passed, and a take whose speech does not match is generated again by `queue_retry`, with
  the same limit as any failed clip. A shot with no dialogue is never transcribed.
- `state` is what the story workspace shows. **Out of date is worked out on every read** and never
  stored: the shot's prompt was compiled again since the take was made, or is itself out of date
  (which already covers the request, the references and the definition).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import (
    GenerationRequest,
    Job,
    LabImage,
    Project,
    ShotPrompt,
    ShotTake,
    SpeechUnitAudio,
)
from app.db.types import utcnow
from app.jobs import store
from app.providers import contract_guard, video_generator
from app.services import (
    api_contract,
    dialogue_check,
    ffmpeg,
    shot_prompts,
    take_validation,
    video_lab,
    video_models,
)
from app.services.duration_policy import DurationPolicy, DurationPolicyError, read_duration_policy
from app.services.frame_counts import H3_FPS, H3_MAX_FRAMES
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "generate_shot"
# The local job that checks the takes that have no stored check (PHASE-029).
CHECK_JOB_TYPE: Final = "check_shot_takes"
# The GPU job that transcribes one take's clip with Parakeet and compares it with the shot's
# dialogue lines (PHASE-031). One per take: its input holds `take_id`, which is also its dedupe key.
DIALOGUE_JOB_TYPE: Final = "check_take_dialogue"
DIALOGUE_DEDUPE_KEY: Final = "take_id"
# Two presses on one shot make one job; two shots run side by side. The key is `scene/shot`.
DEDUPE_KEY: Final = "shot_key"

# The MIME type of the stored dialogue audio (`jobs/synthesize_speech_unit.py` stores a WAV).
AUDIO_MIME: Final = "audio/wav"

PROMPT_KIND: Final = "shot_prompt"
REQUEST_KIND: Final = shot_prompts.REQUEST_KIND

# `not_generated`: the shot has no take yet, or its first take is being made. `generated`: its
# selected take was made from the shot's current prompt. `out_of_date`: the selected take was
# made from something that has changed (see the reasons). `failed`: no take passed its technical
# check (PHASE-029) or its job ended without a clip, and nothing is being generated. `unchecked`:
# no take passed, and a clip that was made before the checks existed has not been checked yet.
Status = Literal["not_generated", "generated", "out_of_date", "failed", "unchecked"]
# `generating`: the take's job is waiting or running. `checking_dialogue`: the clip is stored and
# passed its technical check, and the job that compares its speech with the shot's dialogue is
# waiting or running (PHASE-031). `ready`: the clip is stored. `failed`: the job ended without a
# clip (failed or cancelled).
TakeState = Literal["generating", "checking_dialogue", "ready", "failed"]


class ShotTakesError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class TakeEntry:
    """One take of a shot and where it stands."""

    row: ShotTake
    job: Job | None
    state: TakeState
    # True for the one take of the shot that is selected.
    selected: bool
    # Why this take is out of date, one sentence each. Empty when it is current.
    reasons: list[str]
    # The technical check as stored (`take_validation`), or None when the clip is not checked.
    validation: dict[str, Any] | None
    # 0 for a take somebody asked for; n for the nth automatic retry of a failed clip.
    retry_attempt: int
    # The dialogue lines the shot carried when the take was made. Empty: nothing to verify.
    dialogue: list[dialogue_check.DialogueLine]
    # The speech-recognition check as stored (`dialogue_check`), or None when it was not made.
    dialogue_result: dict[str, Any] | None
    # The newest job of the take's dialogue check, whatever its status.
    dialogue_job: Job | None
    # True when the clip passed its technical check but still needs a check that has not been
    # made (its technical check for a clip older than PHASE-029, its dialogue check for a take
    # with dialogue) and no job is making it now.
    unchecked: bool


@dataclass(frozen=True)
class ShotEntry:
    """One shot of the newest shot plan and where its generation stands."""

    shot: dict[str, Any]
    duration_s: float
    # Where the shot's compiled prompt stands: `not_compiled`, `compiled` or `out_of_date`.
    prompt_status: str
    status: Status
    # Why the selected take is out of date. Empty unless `out_of_date`.
    reasons: list[str]
    # Every take of the shot, the newest first.
    takes: list[TakeEntry]
    # The newest take's job, whatever its status.
    job: Job | None
    can_run: bool
    blocked_reason: str | None

    @property
    def selected(self) -> TakeEntry | None:
        return next((take for take in self.takes if take.selected), None)


@dataclass(frozen=True)
class SceneEntry:
    """One scene of the newest list of scenes and where its shots' generation stands."""

    item: dict[str, Any]
    shots: list[ShotEntry]


@dataclass(frozen=True)
class ShotTakesState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    entries: list[SceneEntry]
    # Why nothing can be generated yet, or None.
    blocked_reason: str | None
    # How many ready takes have no stored check (made before PHASE-029), and the newest job of
    # the action that checks them.
    unchecked_count: int
    check_job: Job | None
    # The `shot_take_max_retries` setting, for showing "retry n of m".
    max_retries: int


@dataclass(frozen=True)
class Skipped:
    """A shot (or, with no `shot_id`, a whole scene) that a "Generate" press did not start."""

    scene_id: str
    shot_id: str | None
    title: str
    reason: str


@dataclass(frozen=True)
class StartResult:
    job_ids: list[int]
    skipped: list[Skipped]


def _shot_key(scene_id: str, shot_id: str) -> str:
    return f"{scene_id}/{shot_id}"


# --- Reading the state --------------------------------------------------------------------


def _is_ready(row: ShotTake) -> bool:
    return row.path is not None


def _take_state(row: ShotTake, job: Job | None, *, checking_dialogue: bool) -> TakeState:
    if _is_ready(row):
        return "checking_dialogue" if checking_dialogue else "ready"
    if job is not None and job.status in store.ACTIVE_STATUSES:
        return "generating"
    return "failed"


def _dialogue_of(
    row: ShotTake, request_content: dict[str, Any] | None
) -> list[dialogue_check.DialogueLine]:
    """The dialogue lines a take was meant to carry: the ones recorded on it when it was made,
    else (a take made before PHASE-031) those of the generation request it was made from.
    """
    recorded = row.inputs.get("dialogue") if isinstance(row.inputs, dict) else None
    if isinstance(recorded, list):
        return dialogue_check.lines_of(recorded)
    if isinstance(request_content, dict):
        return dialogue_check.lines_of(request_content.get("audios"))
    return []


def _needs_dialogue_check(row: ShotTake, lines: list[dialogue_check.DialogueLine]) -> bool:
    """A take with dialogue whose clip passed its technical check and whose speech has not been
    compared with the lines yet.
    """
    return bool(lines) and take_validation.passed(row.validation) and row.dialogue_check is None


def _usable(row: ShotTake, lines: list[dialogue_check.DialogueLine]) -> bool:
    """A take that may be a shot's selected take: its clip is stored and passed its technical
    check, and, when the shot carries dialogue, its speech passed the dialogue check.
    """
    return (
        _is_ready(row)
        and take_validation.passed(row.validation)
        and (not lines or dialogue_check.passed(row.dialogue_check))
    )


def _retry_attempt(row: ShotTake) -> int:
    retry = row.inputs.get("retry") if isinstance(row.inputs, dict) else None
    attempt = retry.get("attempt") if isinstance(retry, dict) else None
    return attempt if isinstance(attempt, int) and not isinstance(attempt, bool) else 0


def _selected_id(
    rows: list[ShotTake], lines_by_take: dict[int, list[dialogue_check.DialogueLine]]
) -> int | None:
    """The id of the shot's selected take: its ready take that passed its technical check (and,
    with dialogue, its dialogue check), with the newest `selected_at`. A take that failed or was
    never checked is never selected.
    """
    newest: ShotTake | None = None
    for row in rows:
        if row.selected_at is None or not _usable(row, lines_by_take.get(row.id, [])):
            continue
        if (
            newest is None
            or newest.selected_at is None
            or (row.selected_at, row.id) > (newest.selected_at, newest.id)
        ):
            newest = row
    return newest.id if newest is not None else None


def _take_reasons(row: ShotTake, prompt: shot_prompts.ShotEntry) -> list[str]:
    """Why a take made for this shot is no longer current, one sentence each."""
    current = prompt.row
    if current is None:
        return ["The shot has no compiled prompt now."]
    if row.shot_prompt_id != current.id:
        return ["The prompt of the shot was compiled again since this take was made."]
    if prompt.status == "out_of_date":
        return ["The prompt of the shot is out of date."]
    return []


async def _takes_by_shot(session: AsyncSession, project_id: int) -> dict[str, list[ShotTake]]:
    """Every take of the project, by its `scene/shot` key, the newest take first."""
    statement = (
        select(ShotTake)
        .where(ShotTake.project_id == project_id)
        .order_by(ShotTake.take_number.desc(), ShotTake.id.desc())
        .execution_options(populate_existing=True)
    )
    grouped: dict[str, list[ShotTake]] = {}
    for row in (await session.execute(statement)).scalars():
        grouped.setdefault(_shot_key(row.scene_id, row.shot_id), []).append(row)
    return grouped


async def _jobs_of(session: AsyncSession, rows: list[ShotTake]) -> dict[int, Job]:
    ids = {row.job_id for row in rows if row.job_id is not None}
    if not ids:
        return {}
    statement = select(Job).where(Job.id.in_(ids)).execution_options(populate_existing=True)
    return {job.id: job for job in (await session.execute(statement)).scalars()}


def _refusal(prompt: shot_prompts.ShotEntry, takes: list[TakeEntry]) -> str | None:
    """Why this shot cannot be generated now, or None."""
    if prompt.row is None:
        return "Compile this shot's prompt first: the clip is generated from it."
    if prompt.status == "out_of_date":
        return "The prompt of this shot is out of date. Compile it again first."
    request = prompt.request
    if request is None or prompt.row.generation_request_id != request.id:
        return "The prompt of this shot was not compiled for its current request. Compile it again."
    if prompt.request_status != "planned":
        return "The generation request of this shot is not current. Plan it again first."
    if any(take.state == "generating" for take in takes):
        return "This shot is already being generated."
    if any(take.state == "checking_dialogue" for take in takes):
        return "The speech in this shot's newest clip is being checked against its dialogue."
    return None


async def _requests_of(session: AsyncSession, rows: list[ShotTake]) -> dict[int, dict[str, Any]]:
    """The content of the generation request each take was made from, by request id."""
    ids = {row.generation_request_id for row in rows if row.generation_request_id is not None}
    if not ids:
        return {}
    statement = select(GenerationRequest.id, GenerationRequest.content).where(
        GenerationRequest.id.in_(ids)
    )
    return {
        request_id: content
        for request_id, content in (await session.execute(statement)).all()
        if isinstance(content, dict)
    }


async def _dialogue_jobs(session: AsyncSession, project_id: int) -> dict[int, Job]:
    """The newest dialogue-check job of each take of the project, by take id."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == DIALOGUE_JOB_TYPE)
        .order_by(Job.id)
        .execution_options(populate_existing=True)
    )
    newest: dict[int, Job] = {}
    for job in (await session.execute(statement)).scalars():
        take_id = job.input.get(DIALOGUE_DEDUPE_KEY) if isinstance(job.input, dict) else None
        if isinstance(take_id, int) and not isinstance(take_id, bool):
            newest[take_id] = job  # ascending ids, so the last one is the newest
    return newest


async def dialogue_lines(session: AsyncSession, row: ShotTake) -> list[dialogue_check.DialogueLine]:
    """The dialogue lines a take was meant to carry (see `_dialogue_of`)."""
    request_row = (
        await session.get(GenerationRequest, row.generation_request_id)
        if row.generation_request_id is not None
        else None
    )
    return _dialogue_of(row, request_row.content if request_row is not None else None)


async def state(session: AsyncSession, project: Project) -> ShotTakesState:
    """The newest list of scenes with where each shot's generation stands. Worked out on every
    read; nothing here is stored.
    """
    prompts = await shot_prompts.state(session, project)
    grouped = await _takes_by_shot(session, project.id)
    all_rows = [row for rows in grouped.values() for row in rows]
    jobs = await _jobs_of(session, all_rows)
    requests = await _requests_of(session, all_rows)
    dialogue_jobs = await _dialogue_jobs(session, project.id)
    lines_by_take = {
        row.id: _dialogue_of(
            row, requests.get(row.generation_request_id) if row.generation_request_id else None
        )
        for row in all_rows
    }

    def checking(row: ShotTake) -> bool:
        """A take with dialogue that is waiting for its dialogue check to finish."""
        job = dialogue_jobs.get(row.id)
        return (
            job is not None
            and job.status in store.ACTIVE_STATUSES
            and _needs_dialogue_check(row, lines_by_take[row.id])
        )

    def _needs_a_check(row: ShotTake) -> bool:
        return (
            _is_ready(row)
            and not checking(row)
            and (row.validation is None or _needs_dialogue_check(row, lines_by_take[row.id]))
        )

    entries: list[SceneEntry] = []
    for scene in prompts.entries:
        scene_id = scene.item["id"]
        shots: list[ShotEntry] = []
        for prompt in scene.shots:
            rows = grouped.get(_shot_key(scene_id, prompt.shot["id"]), [])
            selected_id = _selected_id(rows, lines_by_take)
            takes = []
            for row in rows:
                lines = lines_by_take[row.id]
                takes.append(
                    TakeEntry(
                        row=row,
                        job=jobs.get(row.job_id) if row.job_id is not None else None,
                        state=_take_state(
                            row,
                            jobs.get(row.job_id) if row.job_id else None,
                            checking_dialogue=checking(row),
                        ),
                        selected=row.id == selected_id,
                        reasons=_take_reasons(row, prompt) if _is_ready(row) else [],
                        validation=row.validation if isinstance(row.validation, dict) else None,
                        retry_attempt=_retry_attempt(row),
                        dialogue=lines,
                        dialogue_result=(
                            row.dialogue_check if isinstance(row.dialogue_check, dict) else None
                        ),
                        dialogue_job=dialogue_jobs.get(row.id),
                        unchecked=_needs_a_check(row),
                    )
                )
            status: Status = "not_generated"
            reasons: list[str] = []
            selected = next((take for take in takes if take.selected), None)
            if selected is not None:
                reasons = selected.reasons
                status = "out_of_date" if reasons else "generated"
            elif takes and not _already_generating_takes(takes):
                status = "unchecked" if any(take.unchecked for take in takes) else "failed"
            blocked = _refusal(prompt, takes)
            shots.append(
                ShotEntry(
                    shot=prompt.shot,
                    duration_s=prompt.duration_s,
                    prompt_status=prompt.status,
                    status=status,
                    reasons=reasons,
                    takes=takes,
                    job=takes[0].job if takes else None,
                    can_run=blocked is None,
                    blocked_reason=blocked,
                )
            )
        entries.append(SceneEntry(item=scene.item, shots=shots))
    return ShotTakesState(
        scenes_version=prompts.scenes_version,
        entries=entries,
        blocked_reason=prompts.blocked_reason,
        # Every take of the project, also one of a shot that is not in the newest plan.
        unchecked_count=sum(1 for row in all_rows if _needs_a_check(row)),
        check_job=await store.latest_job(session, project.id, CHECK_JOB_TYPE),
        max_retries=await settings_service.get_int(
            session, settings_service.SHOT_TAKE_MAX_RETRIES_KEY
        ),
    )


def _already_generating_takes(takes: list[TakeEntry]) -> bool:
    """A take's clip is being made, or its dialogue is being checked."""
    return any(take.state in ("generating", "checking_dialogue") for take in takes)


# --- Starting runs ------------------------------------------------------------------------


def _find_shot(
    current: ShotTakesState, scene_id: str, shot_id: str
) -> tuple[SceneEntry, ShotEntry]:
    scene = next((entry for entry in current.entries if entry.item["id"] == scene_id), None)
    if scene is None:
        raise ShotTakesError(f"There is no scene '{scene_id}' in the newest scene list.")
    shot = next((entry for entry in scene.shots if entry.shot["id"] == shot_id), None)
    if shot is None:
        raise ShotTakesError(
            f"There is no shot '{shot_id}' in the newest shot plan of the scene '{scene_id}'."
        )
    return scene, shot


def _stored_file_exists(relative_path: str | None) -> bool:
    if not relative_path:
        return False
    try:
        return get_storage().get_path(relative_path).is_file()
    except StorageError:
        return False


async def _inputs_of_request(
    session: AsyncSession, content: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The pictures and the audios of a generation request as the job reads them, in the order
    the prompt names them, after checking that every file is still there. Raises ShotTakesError.
    """
    references: list[dict[str, Any]] = []
    for picture in content["pictures"]:
        image = await session.get(LabImage, picture["lab_image_id"])
        if image is None or not _stored_file_exists(image.path):
            raise ShotTakesError(
                f"The picture '{picture['label']}' ({picture['subject_name']}, "
                f"{picture['view']}) is missing. Choose the shot's references again."
            )
        references.append({"source": "lab", "id": image.id})

    audios: list[dict[str, Any]] = []
    for audio in content["audios"]:
        speech = await session.get(SpeechUnitAudio, audio["speech_unit_audio_id"])
        if speech is None or not _stored_file_exists(speech.path):
            raise ShotTakesError(
                f"The speech of the line '{audio['unit_id']}' ({audio['label']}) is missing. "
                "Make it again."
            )
        # What the job needs of the audio, copied now: a later change moves nothing for it.
        audios.append(
            {
                "source": "speech_unit",
                "id": speech.id,
                "path": speech.path,
                "mime": AUDIO_MIME,
            }
        )
    return references, audios


async def _build_body(
    session: AsyncSession, content: dict[str, Any], prompt_text: str, seed: int
) -> dict[str, Any]:
    """The body sent to the video model (without the uploaded files), checked against the
    newest recorded GPU API. Raises ShotTakesError.
    """
    endpoint = content["endpoint"]
    partition = await settings_service.get_str(session, video_lab.PARTITION_KEY)
    bodies = await contract_guard.latest_bodies(session)
    spec = next((body for body in bodies if api_contract.is_openapi(body)), None)
    try:
        if spec is None:
            raise ValueError(video_generator.no_endpoint_message(endpoint))
        video_generator.frame_limits(spec, endpoint)  # only checks the endpoint exists
        video_generator.check_size(content["width"], content["height"])
    except ValueError as exc:
        raise ShotTakesError(
            f"{video_models.label(video_models.H3_MODEL)}: {exc} If the GPU server has this "
            "endpoint, test the connection in Settings, so the app reads its current API."
        ) from exc
    return video_generator.build_request(
        endpoint=endpoint,
        prompt=prompt_text,
        negative_prompt=None,
        width=content["width"],
        height=content["height"],
        num_frames=content["num_frames"],
        fps=content["fps"],
        seed=seed,
        partition=partition,
    )


async def _next_take_number(
    session: AsyncSession, project_id: int, scene_id: str, shot_id: str
) -> int:
    statement = select(func.max(ShotTake.take_number)).where(
        ShotTake.project_id == project_id,
        ShotTake.scene_id == scene_id,
        ShotTake.shot_id == shot_id,
    )
    return ((await session.execute(statement)).scalar_one_or_none() or 0) + 1


async def _queue(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    shot: ShotEntry,
    prompt: ShotPrompt,
    retry: dict[str, Any] | None = None,
) -> tuple[Job, bool]:
    """Adds the take and queues the job of one shot that `can_run`. Flushes, does not commit.
    Returns `(job, created)`: the job already generating the shot when it was not created (no
    take is added then). `retry` is `{attempt, of_take_id, problems}` for the automatic retry of
    a failed clip, and is recorded on the take. Raises ShotTakesError.
    """
    request_row = (
        await session.get(GenerationRequest, prompt.generation_request_id)
        if prompt.generation_request_id is not None
        else None
    )
    if request_row is None:
        raise ShotTakesError("The generation request this shot's prompt was compiled for is gone.")
    content = request_row.content
    prompt_content = prompt.content
    if prompt_content.get("endpoint") != content.get("endpoint"):
        raise ShotTakesError(
            "The prompt of this shot was written for another endpoint than its request. "
            "Compile it again."
        )

    references, audios = await _inputs_of_request(session, content)
    seed = secrets.randbelow(video_lab.SEED_LIMIT)
    body = await _build_body(session, content, prompt_content["prompt"], seed)

    shot_id = shot.shot["id"]
    key = _shot_key(scene_id, shot_id)
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="gpu",
        input={
            "requested": JOB_TYPE,
            DEDUPE_KEY: key,
            "scene_id": scene_id,
            "shot_id": shot_id,
            "video_model": video_models.H3_MODEL,
            "endpoint": content["endpoint"],
            "request": body,
            "first_frame": None,
            "last_frame": None,
            "references": references,
            "audios": audios,
        },
        commit=False,
        dedupe_key=DEDUPE_KEY,
    )
    if not created:
        return job, False

    take = ShotTake(
        project_id=project.id,
        scene_id=scene_id,
        shot_id=shot_id,
        take_number=await _next_take_number(session, project.id, scene_id, shot_id),
        shot_prompt_id=prompt.id,
        generation_request_id=request_row.id,
        job_id=job.id,
        seed=seed,
        inputs={
            "project_id": project.id,
            "scene_id": scene_id,
            "shot_id": shot_id,
            "artifacts": [
                {"kind": PROMPT_KIND, "id": prompt.id, "version": prompt.version},
                {"kind": REQUEST_KIND, "id": request_row.id, "version": request_row.version},
            ],
            "endpoint": content["endpoint"],
            "num_frames": content["num_frames"],
            "target_seconds": content["target_seconds"],
            # The lines the clip must contain (PHASE-031); empty for a shot with no dialogue.
            "dialogue": dialogue_check.lines_as_json(dialogue_check.lines_of(content["audios"])),
            # Only a take made by the automatic retry of a failed clip has this (PHASE-029).
            **({"retry": retry} if retry is not None else {}),
        },
    )
    session.add(take)
    await session.flush()
    _logger.info(
        "shot '%s' of scene '%s' of project %d: take %d queued as job %d",
        shot_id,
        scene_id,
        project.id,
        take.take_number,
        job.id,
    )
    return job, True


async def start_shot(session: AsyncSession, project: Project, scene_id: str, shot_id: str) -> Job:
    """Queues the job that generates one more take of a shot, and commits. If the shot already
    has a job waiting or running, that job is returned and no take is added. Raises
    ShotTakesError.
    """
    current = await state(session, project)
    _scene, shot = _find_shot(current, scene_id, shot_id)
    if shot.blocked_reason is not None and not _already_generating(shot):
        raise ShotTakesError(shot.blocked_reason)
    prompt = await _newest_prompt(session, project.id, scene_id, shot_id)
    if prompt is None:
        raise ShotTakesError("Compile this shot's prompt first: the clip is generated from it.")
    job, _created = await _queue(session, project, scene_id, shot, prompt)
    await session.commit()
    return job


def _already_generating(shot: ShotEntry) -> bool:
    return any(take.state == "generating" for take in shot.takes)


async def _newest_prompt(
    session: AsyncSession, project_id: int, scene_id: str, shot_id: str
) -> ShotPrompt | None:
    statement = (
        select(ShotPrompt)
        .where(
            ShotPrompt.project_id == project_id,
            ShotPrompt.scene_id == scene_id,
            ShotPrompt.shot_id == shot_id,
        )
        .order_by(ShotPrompt.version.desc(), ShotPrompt.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def _start_shots(
    session: AsyncSession, project: Project, scene: SceneEntry, result: StartResult
) -> None:
    """Queues a job for every shot of the scene that has no current take and is not being
    generated, adding to `result`.
    """
    scene_id = scene.item["id"]
    title = scene.item["title"]
    for shot in scene.shots:
        shot_id = shot.shot["id"]
        if shot.status == "generated":
            result.skipped.append(
                Skipped(scene_id, shot_id, title, "Already generated and up to date.")
            )
            continue
        if shot.status == "unchecked":
            # A clip made before the checks existed may be fine: checking it costs seconds, a
            # new take costs a GPU run. Regenerate on the shot itself if a new take is wanted.
            result.skipped.append(
                Skipped(
                    scene_id,
                    shot_id,
                    title,
                    "Its clips have not been checked yet. Press Check takes first.",
                )
            )
            continue
        if shot.blocked_reason is not None:
            result.skipped.append(Skipped(scene_id, shot_id, title, shot.blocked_reason))
            continue
        prompt = await _newest_prompt(session, project.id, scene_id, shot_id)
        if prompt is None:
            result.skipped.append(
                Skipped(scene_id, shot_id, title, "Compile this shot's prompt first.")
            )
            continue
        try:
            job, created = await _queue(session, project, scene_id, shot, prompt)
        except ShotTakesError as exc:
            result.skipped.append(Skipped(scene_id, shot_id, title, str(exc)))
            continue
        if created:
            result.job_ids.append(job.id)
        else:
            result.skipped.append(Skipped(scene_id, shot_id, title, "Already being generated."))


async def start_scene(session: AsyncSession, project: Project, scene_id: str) -> StartResult:
    """Queues a job for every shot of one scene that has no current take and is not being
    generated, and commits. Raises ShotTakesError for an unknown scene.
    """
    current = await state(session, project)
    scene = next((entry for entry in current.entries if entry.item["id"] == scene_id), None)
    if scene is None:
        raise ShotTakesError(f"There is no scene '{scene_id}' in the newest scene list.")
    result = StartResult(job_ids=[], skipped=[])
    await _start_shots(session, project, scene, result)
    await session.commit()
    return result


async def start_all(session: AsyncSession, project: Project) -> StartResult:
    """Queues a job for every shot, in every scene, that has no current take and is not being
    generated, and commits. A shot that cannot be generated is skipped with the reason. Raises
    ShotTakesError when nothing can be generated yet.
    """
    current = await state(session, project)
    if current.blocked_reason is not None:
        raise ShotTakesError(current.blocked_reason)
    result = StartResult(job_ids=[], skipped=[])
    for scene in current.entries:
        await _start_shots(session, project, scene, result)
    await session.commit()
    return result


# --- Selecting a take ---------------------------------------------------------------------


async def select_take(
    session: AsyncSession, project: Project, scene_id: str, shot_id: str, take_id: int
) -> ShotTake:
    """Makes one ready take the shot's selected take, and commits. The take that was selected
    last is the selected one, so this stamps `selected_at` with a time after every other take's.
    Raises ShotTakesError.
    """
    take = await session.get(ShotTake, take_id)
    if (
        take is None
        or take.project_id != project.id
        or take.scene_id != scene_id
        or take.shot_id != shot_id
    ):
        raise ShotTakesError(
            f"The shot '{shot_id}' of the scene '{scene_id}' has no take {take_id}."
        )
    if not _is_ready(take):
        raise ShotTakesError("This take has no clip yet, so it cannot be selected.")
    if take.validation is None:
        raise ShotTakesError("This take has not been checked yet. Press Check takes first.")
    if not take_validation.passed(take.validation):
        raise ShotTakesError(
            "This take failed its technical check, so it cannot be selected: "
            + _problem_text(take.validation)
        )
    lines = await dialogue_lines(session, take)
    if lines and take.dialogue_check is None:
        raise ShotTakesError(
            "The speech in this take has not been checked against the dialogue yet. "
            "Wait for the check, or press Check takes."
        )
    if lines and not dialogue_check.passed(take.dialogue_check):
        raise ShotTakesError(
            "This take failed its dialogue check, so it cannot be selected: "
            + _problem_text(take.dialogue_check)
        )
    take.selected_at = await selection_time(session, project.id, scene_id, shot_id)
    await session.commit()
    return take


def _problem_text(validation: dict[str, Any]) -> str:
    problems = validation.get("problems")
    if not isinstance(problems, list):
        return "no reason was recorded."
    messages = [
        problem["message"]
        for problem in problems
        if isinstance(problem, dict) and isinstance(problem.get("message"), str)
    ]
    return " ".join(messages) or "no reason was recorded."


# --- Checking a clip ----------------------------------------------------------------------


async def measure_clip(
    path: Path,
) -> tuple[take_validation.Measured, ffmpeg.VideoProbe | None]:
    """Reads a clip with ffprobe and decodes it to the end. The probe is None, and the
    measurement says `readable=False`, when ffprobe cannot read the file. Never raises.
    """
    probe = await ffmpeg.probe_video(path)
    if probe is None or probe.frame_count is None:
        unreadable = take_validation.Measured(
            frame_count=None,
            width=None,
            height=None,
            duration_s=None,
            has_audio=False,
            readable=False,
        )
        return unreadable, probe
    measured = take_validation.Measured(
        frame_count=probe.frame_count,
        width=probe.width,
        height=probe.height,
        duration_s=probe.duration_s,
        has_audio=probe.audio is not None,
        decode_problem=await ffmpeg.decode_problem(path),
    )
    return measured, probe


async def _policy_now(session: AsyncSession) -> DurationPolicy:
    """The duration policy that applies now. When the saved settings are out of order, only the
    server's own limit is enforced, so a clip is not failed because of a settings mistake.
    """
    try:
        return await read_duration_policy(session)
    except DurationPolicyError:
        return DurationPolicy(
            hard_min_s=0, hard_max_s=H3_MAX_FRAMES // H3_FPS, target_min_s=0, target_max_s=0
        )


async def judge_take(
    session: AsyncSession,
    take: ShotTake,
    measured: take_validation.Measured,
    request_body: dict[str, Any] | None,
) -> dict[str, Any]:
    """The value for `shot_take.validation` of a take whose clip was measured. `request_body` is
    the body that was sent to the server when it is still known (the job's input), else None and
    the take's generation request says what was asked.
    """
    request_row = (
        await session.get(GenerationRequest, take.generation_request_id)
        if take.generation_request_id is not None
        else None
    )
    expected = take_validation.expected_of(
        take_inputs=take.inputs if isinstance(take.inputs, dict) else {},
        request_body=request_body,
        request_content=request_row.content if request_row is not None else None,
    )
    checked_at = utcnow()
    if expected is None:
        return {
            "version": take_validation.VERSION,
            "passed": False,
            "kind": "plan",
            "checked_at": checked_at.isoformat(),
            "problems": [
                {
                    "code": "request_missing",
                    "message": (
                        "What this take was asked for is no longer known, so it cannot be "
                        "checked. Generate the shot again."
                    ),
                }
            ],
            "measured": None,
            "expected": None,
        }
    verdict = take_validation.validate(measured, expected, await _policy_now(session))
    return verdict.to_json(measured, expected, checked_at=checked_at)


# --- Retrying a failed clip ---------------------------------------------------------------


def _retryable_failure(take: ShotTake) -> dict[str, Any] | None:
    """The stored check that failed the take for a reason another seed can fix: its technical
    check (`kind` is `clip`), or, when that passed, its dialogue check (PHASE-031). None when the
    take did not fail, was not checked, or failed because of the plan.
    """
    validation = take.validation
    if not isinstance(validation, dict):
        return None
    if validation.get("passed") is False:
        return validation if validation.get("kind") == "clip" else None
    check = take.dialogue_check
    if (
        validation.get("passed") is True
        and isinstance(check, dict)
        and check.get("passed") is False
        and check.get("kind") == "clip"
    ):
        return check
    return None


async def queue_retry(session: AsyncSession, take_id: int) -> Job | None:
    """Queues another take of a shot whose take `take_id` failed its technical check or its
    dialogue check, with a new seed, and commits. Returns the job, or None when no retry is made:
    the take did not fail for a reason another seed can fix (`kind` is not `clip`), the tries are
    used up (`shot_take_max_retries`), the take is not the shot's newest take any more, or the shot
    cannot be generated now (its prompt or request changed meanwhile; the user presses Generate).
    """
    take = await session.get(ShotTake, take_id)
    if take is None:
        return None
    validation = _retryable_failure(take)
    if validation is None:
        return None
    attempt = _retry_attempt(take)
    max_tries = await settings_service.get_int(session, settings_service.SHOT_TAKE_MAX_RETRIES_KEY)
    if attempt >= max_tries:
        _logger.info(
            "shot '%s' of scene '%s' of project %d: take %d failed its check; the %d retries "
            "are used",
            take.shot_id,
            take.scene_id,
            take.project_id,
            take.take_number,
            max_tries,
        )
        return None
    newest = (await _next_take_number(session, take.project_id, take.scene_id, take.shot_id)) - 1
    project = await session.get(Project, take.project_id)
    if project is None or take.take_number != newest:
        return None

    try:
        current = await state(session, project)
        _scene, shot = _find_shot(current, take.scene_id, take.shot_id)
        prompt = await _newest_prompt(session, project.id, take.scene_id, take.shot_id)
        if shot.blocked_reason is not None or prompt is None or prompt.id != take.shot_prompt_id:
            _logger.info(
                "shot '%s' of scene '%s' of project %d: not generated again by itself: %s",
                take.shot_id,
                take.scene_id,
                take.project_id,
                shot.blocked_reason or "its prompt was compiled again",
            )
            return None
        retry = {
            "attempt": attempt + 1,
            "of_take_id": take.id,
            "problems": [
                p["code"]
                for p in validation.get("problems", [])
                if isinstance(p, dict) and isinstance(p.get("code"), str)
            ],
        }
        job, created = await _queue(session, project, take.scene_id, shot, prompt, retry)
    except ShotTakesError as exc:
        await session.rollback()
        _logger.info(
            "shot '%s' of scene '%s' of project %d: not generated again by itself: %s",
            take.shot_id,
            take.scene_id,
            take.project_id,
            exc,
        )
        return None
    await session.commit()
    return job if created else None


# --- Checking takes made before the checks existed -----------------------------------------


async def takes_needing_a_check(session: AsyncSession, project_id: int) -> list[ShotTake]:
    """The ready takes of a project that still need a check and have no job making it: a clip
    with no technical check (made before PHASE-029), or a take with dialogue that passed its
    technical check and whose speech was never compared with the lines (PHASE-031).
    """
    statement = (
        select(ShotTake)
        .where(ShotTake.project_id == project_id, ShotTake.path.is_not(None))
        .order_by(ShotTake.id)
        .execution_options(populate_existing=True)
    )
    rows = list((await session.execute(statement)).scalars())
    requests = await _requests_of(session, rows)
    dialogue_jobs = await _dialogue_jobs(session, project_id)
    needing: list[ShotTake] = []
    for row in rows:
        if row.validation is None:
            needing.append(row)
            continue
        request_id = row.generation_request_id
        lines = _dialogue_of(row, requests.get(request_id) if request_id is not None else None)
        job = dialogue_jobs.get(row.id)
        working = job is not None and job.status in store.ACTIVE_STATUSES
        if _needs_dialogue_check(row, lines) and not working:
            needing.append(row)
    return needing


async def queue_dialogue_check(
    session: AsyncSession, take: ShotTake, *, commit: bool = True
) -> tuple[Job, bool]:
    """Queues the job that compares the speech in a take's clip with the shot's dialogue lines.
    Returns `(job, created)`: the job already checking the take when it was not created. With
    `commit=False` the job is only flushed, so the caller saves it with the take.
    """
    job, created = await store.create_job(
        session,
        project_id=take.project_id,
        type=DIALOGUE_JOB_TYPE,
        provider="gpu",
        input={"requested": DIALOGUE_JOB_TYPE, DIALOGUE_DEDUPE_KEY: take.id},
        commit=commit,
        dedupe_key=DIALOGUE_DEDUPE_KEY,
    )
    if created:
        _logger.info(
            "take %d of project %d: dialogue check queued as job %d",
            take.id,
            take.project_id,
            job.id,
        )
    return job, created


async def start_check(session: AsyncSession, project: Project) -> Job:
    """Queues the job that checks every ready take of the project that still needs a check (no
    technical check, or, with dialogue, no dialogue check), and commits. If that job is already
    waiting or running, it is returned. Raises ShotTakesError when no take needs a check.
    """
    if not await takes_needing_a_check(session, project.id):
        raise ShotTakesError("Every clip of this project has been checked already.")
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=CHECK_JOB_TYPE,
        provider="local",
        input={"requested": CHECK_JOB_TYPE},
    )
    if created:
        _logger.info("takes of project %d: check queued as job %d", project.id, job.id)
    return job


async def selection_time(
    session: AsyncSession, project_id: int, scene_id: str, shot_id: str
) -> datetime:
    """The `selected_at` for a take that is being selected now: the current time, or one
    microsecond after the newest selection of the shot if that is later, so the take selected
    last always has the newest time.
    """
    statement = select(func.max(ShotTake.selected_at)).where(
        ShotTake.project_id == project_id,
        ShotTake.scene_id == scene_id,
        ShotTake.shot_id == shot_id,
    )
    newest = (await session.execute(statement)).scalar_one_or_none()
    now = utcnow()
    return max(now, newest + timedelta(microseconds=1)) if newest is not None else now
