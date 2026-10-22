"""The H3 Prompt Compilation stage of a story project (PHASE-026, `Path_ahead.md` Section 30).

Each shot whose generation request is planned (PHASE-025) gets one `compile_shot_prompt` job. The
job asks the model for the creative pieces of the final H3 prompt, code writes the fixed parts
around them (`services/shot_prompt_writer`), and `save_shot_prompt` stores the checked prompt as a
new `shot_prompt` row: one immutable row per run, numbered per shot, with the provenance of the
artifact convention (D-3). Like a shot definition, a prompt belongs to the project alone: nothing
is written to the Character Lab and no pin moves.

The model reads the StoryBible, the scene, the shot's specification, the characters it shows or
hears and the environment (all as the shot was defined from them), and the labels of the shot's
generation request: which `<Picture n>` shows which subject and which `<Audio n>` is whose line.

- A shot can be compiled only when its newest generation request exists and is current. The
  reason says what is missing.
- `start_shot` queues the job for one shot (compiling again is allowed), `start_scene` one for
  every shot of a scene that has no current prompt and is not being compiled, and `start_all` the
  same for every scene. The jobs run side by side when the pool allows (`store.create_job` with
  `dedupe_key`).
- `queue_if_ready` is called after a shot's request is planned (the `define_shot` job, the
  repair of a cut and the buttons that plan), so a shot gets its prompt by itself.
- `state` is what the story workspace shows. **Out of date is worked out on every read** and
  never stored: the shot's request was planned again, or is itself out of date (which already
  covers the shot's references, its definition, the shot plan and the looks and states).
- `save_shot_prompt` is called by the job and flushes without committing; the job commits it
  together with finishing itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GenerationRequest, Job, Project, ShotDefinition, ShotPrompt
from app.jobs import store
from app.services import (
    generation_requests,
    scene_definitions,
    shot_definitions,
    shot_prompt_writer,
)

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "compile_shot_prompt"
# Two presses on one shot make one job; two shots run side by side. The key is `scene/shot`.
DEDUPE_KEY: Final = "shot_key"

# How many of a project's newest compile jobs are read to find each shot's newest one.
_JOB_LOOKBACK: Final = 2000

REQUEST_KIND: Final = "generation_request"
MANIFEST_KIND: Final = generation_requests.MANIFEST_KIND
DEFINITION_KIND: Final = generation_requests.DEFINITION_KIND
STORY_BIBLE_KIND: Final = shot_definitions.STORY_BIBLE_KIND
CHARACTER_DEFINITION_KIND: Final = scene_definitions.CHARACTER_DEFINITION_KIND
ENVIRONMENT_DEFINITION_KIND: Final = scene_definitions.ENVIRONMENT_DEFINITION_KIND
# What a prompt records of what its request and its context were built from.
_FROM_REQUEST: Final = (MANIFEST_KIND, DEFINITION_KIND)
_FROM_CONTEXT: Final = (STORY_BIBLE_KIND, CHARACTER_DEFINITION_KIND, ENVIRONMENT_DEFINITION_KIND)

# `not_compiled`: no prompt was made for this shot. `compiled`: made, and nothing it was built
# from has changed. `out_of_date`: made, and something it was built from has changed (see the
# reasons).
Status = Literal["not_compiled", "compiled", "out_of_date"]


class ShotPromptsError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class ShotEntry:
    """One shot of the newest shot plan and where its prompt stands."""

    shot: dict[str, Any]
    duration_s: float
    # Where the shot's generation request stands: `not_planned`, `planned` or `out_of_date`.
    request_status: str
    # The newest generation request of the shot, when it has one.
    request: GenerationRequest | None
    status: Status
    # Why a compiled prompt is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The newest prompt of this shot, when it has one.
    row: ShotPrompt | None
    # The newest compile job of this shot, whatever its status.
    job: Job | None
    can_run: bool
    blocked_reason: str | None

    @property
    def content(self) -> dict[str, Any] | None:
        return self.row.content if self.row is not None else None


@dataclass(frozen=True)
class SceneEntry:
    """One scene of the newest list of scenes and where its shots' prompts stand."""

    item: dict[str, Any]
    shots: list[ShotEntry]


@dataclass(frozen=True)
class ShotPromptsState:
    """What the story workspace shows. `scenes_version` is None when no list exists."""

    scenes_version: int | None
    entries: list[SceneEntry]
    # Why nothing can be compiled yet, or None.
    blocked_reason: str | None


@dataclass(frozen=True)
class Skipped:
    """A shot (or, with no `shot_id`, a whole scene) that a "Compile" press did not start."""

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


def _recorded(inputs: Any, kind: str) -> dict[str, Any] | None:
    """The first artifact of this kind that `inputs` says the prompt was built from."""
    artifacts = inputs.get("artifacts") if isinstance(inputs, dict) else None
    for artifact in artifacts if isinstance(artifacts, list) else []:
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            return artifact
    return None


def _out_of_date_reasons(row: ShotPrompt, entry: generation_requests.ShotEntry) -> list[str]:
    """Why a prompt compiled for this shot is no longer current, one sentence each."""
    request = entry.row
    if request is None:
        return ["The shot has no generation request now."]
    recorded = _recorded(row.inputs, REQUEST_KIND)
    if recorded is None or recorded.get("id") != request.id:
        return ["The generation request of the shot was planned again since the prompt was made."]
    if entry.status == "out_of_date":
        return ["The generation request of the shot is out of date."]
    return []


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest compile job of each shot of the project, by its `scene/shot` key."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == JOB_TYPE)
        .order_by(Job.id.desc())
        .limit(_JOB_LOOKBACK)
        .execution_options(populate_existing=True)
    )
    newest: dict[str, Job] = {}
    for job in (await session.execute(statement)).scalars():
        key = job.input.get(DEDUPE_KEY) if isinstance(job.input, dict) else None
        if isinstance(key, str) and key not in newest:
            newest[key] = job
    return newest


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, ShotPrompt]:
    """The newest prompt of each shot of the project, by its `scene/shot` key."""
    statement = (
        select(ShotPrompt)
        .where(ShotPrompt.project_id == project_id)
        .order_by(ShotPrompt.version.desc(), ShotPrompt.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, ShotPrompt] = {}
    for row in (await session.execute(statement)).scalars():
        key = _shot_key(row.scene_id, row.shot_id)
        if key not in newest:
            newest[key] = row
    return newest


def _refusal(request: GenerationRequest | None, request_status: str) -> str | None:
    """Why this shot's prompt cannot be compiled now, from its request, or None."""
    if request is None:
        return "Plan this shot's generation request first: its prompt is compiled from it."
    if request_status == "out_of_date":
        return "The generation request of this shot is out of date. Plan it again first."
    return None


async def state(session: AsyncSession, project: Project) -> ShotPromptsState:
    """The newest list of scenes with where each shot's prompt stands. Worked out on every
    read; nothing here is stored.
    """
    requests = await generation_requests.state(session, project)
    rows = await _newest_rows(session, project.id)
    jobs = await _newest_jobs(session, project.id)
    entries: list[SceneEntry] = []
    for scene in requests.entries:
        scene_id = scene.item["id"]
        shots: list[ShotEntry] = []
        for entry in scene.shots:
            key = _shot_key(scene_id, entry.shot["id"])
            row = rows.get(key)
            job = jobs.get(key)
            status: Status = "not_compiled"
            reasons: list[str] = []
            if row is not None:
                reasons = _out_of_date_reasons(row, entry)
                status = "out_of_date" if reasons else "compiled"
            blocked = _refusal(entry.row, entry.status)
            if blocked is None and job is not None and job.status in store.ACTIVE_STATUSES:
                blocked = "This shot's prompt is already being compiled."
            shots.append(
                ShotEntry(
                    shot=entry.shot,
                    duration_s=entry.duration_s,
                    request_status=entry.status,
                    request=entry.row,
                    status=status,
                    reasons=reasons,
                    row=row,
                    job=job,
                    can_run=blocked is None,
                    blocked_reason=blocked,
                )
            )
        entries.append(SceneEntry(item=scene.item, shots=shots))
    return ShotPromptsState(
        scenes_version=requests.scenes_version,
        entries=entries,
        blocked_reason=requests.blocked_reason,
    )


# --- Starting runs ------------------------------------------------------------------------


def _find_shot(
    current: ShotPromptsState, scene_id: str, shot_id: str
) -> tuple[SceneEntry, ShotEntry]:
    scene = next((entry for entry in current.entries if entry.item["id"] == scene_id), None)
    if scene is None:
        raise ShotPromptsError(f"There is no scene '{scene_id}' in the newest scene list.")
    shot = next((entry for entry in scene.shots if entry.shot["id"] == shot_id), None)
    if shot is None:
        raise ShotPromptsError(
            f"There is no shot '{shot_id}' in the newest shot plan of the scene '{scene_id}'."
        )
    return scene, shot


def _inputs(
    project_id: int,
    scene_id: str,
    shot_id: str,
    request: GenerationRequest,
    context: dict[str, Any],
) -> dict[str, Any]:
    """The `inputs` written onto the prompt (D-3): the request it is compiled for, what that
    request was planned from, and what the model is shown about the story and its subjects.
    """
    artifacts: list[dict[str, Any]] = [
        {"kind": REQUEST_KIND, "id": request.id, "version": request.version}
    ]
    for kind in _FROM_REQUEST:
        recorded = _recorded(request.inputs, kind)
        if recorded is not None:
            artifacts.append(recorded)
    shown = context["inputs"]
    for artifact in shown["artifacts"]:
        if isinstance(artifact, dict) and artifact.get("kind") in _FROM_CONTEXT:
            artifacts.append(artifact)
    return {
        "project_id": project_id,
        "scene_id": scene_id,
        "shot_id": shot_id,
        "story_sha256": shown["story_sha256"],
        "artifacts": artifacts,
    }


async def _queue(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    shot: ShotEntry,
    context: dict[str, Any] | str,
) -> tuple[Job, bool]:
    """Queues the job for this shot and returns `(job, created)`. `created` is False when the
    shot already has a job waiting or running, which is returned instead. `context` is what
    `shot_definitions.shot_contexts` gave for the shot. Raises ShotPromptsError when this shot
    cannot be compiled.
    """
    request = shot.request
    refusal = _refusal(request, shot.request_status)
    if refusal is not None:
        raise ShotPromptsError(refusal)
    assert request is not None
    if isinstance(context, str):
        raise ShotPromptsError(context)
    recorded = _recorded(request.inputs, DEFINITION_KIND)
    definition = (
        await session.get(ShotDefinition, recorded["id"])
        if recorded is not None and isinstance(recorded.get("id"), int)
        else None
    )
    if definition is None:
        raise ShotPromptsError("The shot definition this shot's request was planned from is gone.")
    try:
        shot_prompt_writer.layout(request.content)
    except shot_prompt_writer.ShotPromptError as exc:
        raise ShotPromptsError(str(exc)) from exc
    shot_id = shot.shot["id"]
    return await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            DEDUPE_KEY: _shot_key(scene_id, shot_id),
            "scene_id": scene_id,
            "shot_id": shot_id,
            "story_bible_id": context["story_bible_id"],
            "story_bible_version": context["story_bible_version"],
            "generation_request_id": request.id,
            "generation_request": request.content,
            "scene": context["scene"],
            "shot_definition": definition.content,
            "characters": context["characters"],
            "environment": context["environment"],
            "inputs": _inputs(project.id, scene_id, shot_id, request, context),
        },
        dedupe_key=DEDUPE_KEY,
    )


async def start_shot(session: AsyncSession, project: Project, scene_id: str, shot_id: str) -> Job:
    """Queues the job that compiles one shot's prompt, and commits. If that shot already has a
    job waiting or running, that job is returned and no new one is made. Raises
    ShotPromptsError.
    """
    current = await state(session, project)
    _scene, shot = _find_shot(current, scene_id, shot_id)
    contexts = await shot_definitions.shot_contexts(session, project, [(scene_id, shot_id)])
    job, _created = await _queue(session, project, scene_id, shot, contexts[(scene_id, shot_id)])
    return job


async def _start_shots(
    session: AsyncSession,
    project: Project,
    scene: SceneEntry,
    contexts: dict[tuple[str, str], dict[str, Any] | str],
    result: StartResult,
) -> None:
    """Queues a job for every shot of the scene that has no current prompt and is not being
    compiled, adding to `result`.
    """
    scene_id = scene.item["id"]
    title = scene.item["title"]
    for shot in scene.shots:
        shot_id = shot.shot["id"]
        if shot.status == "compiled":
            result.skipped.append(
                Skipped(scene_id, shot_id, title, "Already compiled and up to date.")
            )
            continue
        if shot.blocked_reason is not None:
            result.skipped.append(Skipped(scene_id, shot_id, title, shot.blocked_reason))
            continue
        try:
            job, created = await _queue(
                session, project, scene_id, shot, contexts[(scene_id, shot_id)]
            )
        except ShotPromptsError as exc:
            result.skipped.append(Skipped(scene_id, shot_id, title, str(exc)))
            continue
        if created:
            result.job_ids.append(job.id)
        else:
            result.skipped.append(Skipped(scene_id, shot_id, title, "Already being compiled."))


def _wanted_keys(scene: SceneEntry) -> list[tuple[str, str]]:
    """The shots of a scene that a press would try to compile."""
    return [
        (scene.item["id"], shot.shot["id"])
        for shot in scene.shots
        if shot.status != "compiled" and shot.blocked_reason is None
    ]


async def start_scene(session: AsyncSession, project: Project, scene_id: str) -> StartResult:
    """Queues a job for every shot of one scene that has no current prompt and is not being
    compiled. Raises ShotPromptsError for an unknown scene.
    """
    current = await state(session, project)
    scene = next((entry for entry in current.entries if entry.item["id"] == scene_id), None)
    if scene is None:
        raise ShotPromptsError(f"There is no scene '{scene_id}' in the newest scene list.")
    contexts = await shot_definitions.shot_contexts(session, project, _wanted_keys(scene))
    result = StartResult(job_ids=[], skipped=[])
    await _start_shots(session, project, scene, contexts, result)
    return result


async def start_all(session: AsyncSession, project: Project) -> StartResult:
    """Queues a job for every shot, in every scene, that has no current prompt and is not being
    compiled. A shot that cannot be compiled is skipped with the reason. Raises ShotPromptsError
    when nothing can be compiled yet.
    """
    current = await state(session, project)
    if current.blocked_reason is not None:
        raise ShotPromptsError(current.blocked_reason)
    keys = [key for scene in current.entries for key in _wanted_keys(scene)]
    contexts = await shot_definitions.shot_contexts(session, project, keys)
    result = StartResult(job_ids=[], skipped=[])
    for scene in current.entries:
        await _start_shots(session, project, scene, contexts, result)
    return result


async def queue_if_ready(
    session: AsyncSession, project_id: int, scene_id: str, shot_id: str
) -> Job | None:
    """Queues the compile job of this shot when its request is planned and current and it has no
    current prompt; commits. Returns the job when one was made. Called after a shot's request is
    planned; a shot that cannot be done is logged and left for the user's **Compile**.
    """
    project = await session.get(Project, project_id)
    if project is None:
        return None
    try:
        current = await state(session, project)
        _scene, shot = _find_shot(current, scene_id, shot_id)
        if shot.status == "compiled" or shot.blocked_reason is not None:
            return None
        contexts = await shot_definitions.shot_contexts(session, project, [(scene_id, shot_id)])
        job, created = await _queue(session, project, scene_id, shot, contexts[(scene_id, shot_id)])
    except ShotPromptsError as exc:
        _logger.info(
            "shot '%s' of scene '%s' of project %d: prompt not queued by itself: %s",
            shot_id,
            scene_id,
            project_id,
            exc,
        )
        return None
    return job if created else None


async def queue_after_planning(project_id: int, scene_id: str, shot_id: str) -> None:
    """The step that follows a shot's request being planned: queues the shot's compile job when
    it is ready and wakes the dispatcher. It opens its own session, so it can be called after
    the caller's commit, and it never raises: a failure here must not fail a job that has
    succeeded, or an answer that has been sent.
    """
    # Imported here: the dispatcher imports the handlers, which import this module.
    from app.db.session import SessionLocal
    from app.jobs import dispatcher

    try:
        async with SessionLocal() as session:
            job = await queue_if_ready(session, project_id, scene_id, shot_id)
    except Exception:
        _logger.exception(
            "the prompt of shot '%s' of scene '%s' could not be queued", shot_id, scene_id
        )
        return
    if job is not None:
        dispatcher.nudge()


# --- Saving the prompt --------------------------------------------------------------------


async def save_shot_prompt(
    session: AsyncSession,
    *,
    project_id: int,
    scene_id: str,
    shot_id: str,
    generation_request_id: int,
    content: dict[str, Any],
    job_id: int,
    inputs: dict[str, Any],
) -> ShotPrompt:
    """Adds the shot's next version. Flushes but does not commit: the job commits it together
    with finishing itself, so a job is never "succeeded" without its result.

    `inputs` is what the job was started with and is stored as it is.
    """
    statement = select(func.max(ShotPrompt.version)).where(
        ShotPrompt.project_id == project_id,
        ShotPrompt.scene_id == scene_id,
        ShotPrompt.shot_id == shot_id,
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = ShotPrompt(
        project_id=project_id,
        scene_id=scene_id,
        shot_id=shot_id,
        generation_request_id=generation_request_id,
        version=(highest or 0) + 1,
        source="ai",
        job_id=job_id,
        inputs=inputs,
        content=content,
    )
    session.add(row)
    await session.flush()
    _logger.info(
        "job %d: prompt of shot '%s' of scene '%s' of project %d saved, version %d",
        job_id,
        shot_id,
        scene_id,
        project_id,
        row.version,
    )
    return row
