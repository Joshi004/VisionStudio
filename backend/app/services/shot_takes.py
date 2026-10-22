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
- **The selected take of a shot is its ready take with the newest `selected_at`.** A take gets
  `selected_at` when its job finishes and when the user selects it, so whichever happened last
  decides.
- `state` is what the story workspace shows. **Out of date is worked out on every read** and never
  stored: the shot's prompt was compiled again since the take was made, or is itself out of date
  (which already covers the request, the references and the definition).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
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
from app.services import api_contract, shot_prompts, video_lab, video_models
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "generate_shot"
# Two presses on one shot make one job; two shots run side by side. The key is `scene/shot`.
DEDUPE_KEY: Final = "shot_key"

# The MIME type of the stored dialogue audio (`jobs/synthesize_speech_unit.py` stores a WAV).
AUDIO_MIME: Final = "audio/wav"

PROMPT_KIND: Final = "shot_prompt"
REQUEST_KIND: Final = shot_prompts.REQUEST_KIND

# `not_generated`: no take of this shot is ready. `generated`: its selected take was made from
# the shot's current prompt. `out_of_date`: the selected take was made from something that has
# changed (see the reasons).
Status = Literal["not_generated", "generated", "out_of_date"]
# `generating`: the take's job is waiting or running. `ready`: the clip is stored. `failed`: the
# job ended without a clip (failed or cancelled).
TakeState = Literal["generating", "ready", "failed"]


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


def _take_state(row: ShotTake, job: Job | None) -> TakeState:
    if _is_ready(row):
        return "ready"
    if job is not None and job.status in store.ACTIVE_STATUSES:
        return "generating"
    return "failed"


def _selected_id(rows: list[ShotTake]) -> int | None:
    """The id of the shot's selected take: its ready take with the newest `selected_at`."""
    newest: ShotTake | None = None
    for row in rows:
        if not _is_ready(row) or row.selected_at is None:
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
    return None


async def state(session: AsyncSession, project: Project) -> ShotTakesState:
    """The newest list of scenes with where each shot's generation stands. Worked out on every
    read; nothing here is stored.
    """
    prompts = await shot_prompts.state(session, project)
    grouped = await _takes_by_shot(session, project.id)
    jobs = await _jobs_of(session, [row for rows in grouped.values() for row in rows])
    entries: list[SceneEntry] = []
    for scene in prompts.entries:
        scene_id = scene.item["id"]
        shots: list[ShotEntry] = []
        for prompt in scene.shots:
            rows = grouped.get(_shot_key(scene_id, prompt.shot["id"]), [])
            selected_id = _selected_id(rows)
            takes = [
                TakeEntry(
                    row=row,
                    job=jobs.get(row.job_id) if row.job_id is not None else None,
                    state=_take_state(row, jobs.get(row.job_id) if row.job_id else None),
                    selected=row.id == selected_id,
                    reasons=_take_reasons(row, prompt) if _is_ready(row) else [],
                )
                for row in rows
            ]
            status: Status = "not_generated"
            reasons: list[str] = []
            selected = next((take for take in takes if take.selected), None)
            if selected is not None:
                reasons = selected.reasons
                status = "out_of_date" if reasons else "generated"
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
    )


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
    session: AsyncSession, project: Project, scene_id: str, shot: ShotEntry, prompt: ShotPrompt
) -> tuple[Job, bool]:
    """Adds the take and queues the job of one shot that `can_run`. Flushes, does not commit.
    Returns `(job, created)`: the job already generating the shot when it was not created (no
    take is added then). Raises ShotTakesError.
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
    take.selected_at = await selection_time(session, project.id, scene_id, shot_id)
    await session.commit()
    return take


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
