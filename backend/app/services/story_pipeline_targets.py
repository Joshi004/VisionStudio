"""What each step of the story pipeline looks at and starts (PHASE-030).

Every step has an adapter with two functions:

- `evaluate(session, project, options)` reads the stage's own `state()` and says which targets
  (a character, a scene, a shot, or the project) are done, which have work in progress, and why
  any other one cannot be started. It writes nothing.
- `start(session, project, targets, options, deadline)` starts the targets the run chose, with
  the stage's own per-target start function (`start_run`, `start_shot`, `start_unit`, ...), the
  one the stage's button calls. Four steps do their work inline instead of making a job:
  linking, speech planning, reference selection and generation requests.

A stage's `*Error` (all are `ValueError`) never escapes `start`: it becomes the `error` of that
target's `Started`, and the run counts it as a try (`services/story_pipeline.py`).

The rules of what "up to date" means for each step are in PHASE-030 of `Implementation_phases.md`.
The stage services are the only source of truth: nothing here is stored.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project
from app.db.types import utcnow
from app.jobs import store
from app.services import (
    character_definitions,
    character_images,
    character_links,
    character_relations,
    discovery,
    environment_definitions,
    environment_links,
    generation_requests,
    look_state_images,
    look_state_resolution,
    scene_definitions,
    scene_events,
    shot_continuity,
    shot_definitions,
    shot_plans,
    shot_prompts,
    shot_references,
    shot_takes,
    speech_synthesis,
    speech_units,
    story_bible,
    story_renders,
    story_voices,
)
from app.services.story_pipeline import (
    PROJECT_KEY,
    STEP_KEYS,
    STEP_LABELS,
    RunOptions,
    Started,
    StepView,
    Target,
)

_logger = logging.getLogger(__name__)

# A stage queues its follow-on work (a re-plan, the repairs of a check) a moment after the job
# that caused it ends. A scene that looks stuck for less than this long is waited for.
SETTLE_SECONDS: Final = 60.0

_STORY_FIRST: Final = "Save the story first: the pipeline starts from it."

Evaluate = Callable[[AsyncSession, Project, RunOptions], Awaitable[StepView]]
# `deadline` is a `time.monotonic()` value: a start function that makes one job per target stops
# after it (but always starts at least one), so a poll never holds the dispatcher for long.
StartTargets = Callable[
    [AsyncSession, Project, list[Target], RunOptions, float], Awaitable[list[Started]]
]


@dataclass(frozen=True)
class Adapter:
    evaluate: Evaluate
    start: StartTargets


# --- Small helpers --------------------------------------------------------------------------


def _blank(text: str | None) -> bool:
    return text is None or not text.strip()


def _active(job: Job | None) -> bool:
    return job is not None and job.status in store.ACTIVE_STATUSES


def _failure(job: Job | None) -> str | None:
    """Why a job did not make its result, or None when it did not fail."""
    if job is None:
        return None
    if job.status == "failed":
        return job.error or "the job failed"
    if job.status == "cancelled":
        return "the job was cancelled"
    return None


def _scene_label(item: dict[str, Any]) -> str:
    index = item.get("index")
    title = item.get("title") or item.get("id") or ""
    return f"Scene {index}: {title}" if index is not None else f"Scene {title}"


def _shot_label(scene: dict[str, Any], shot: dict[str, Any]) -> str:
    index = scene.get("index")
    prefix = f"Scene {index}" if index is not None else f"Scene {scene.get('id')}"
    return f"{prefix}, shot {shot.get('id')}"


def _shot_key(scene_id: str, shot_id: str) -> str:
    return f"shot:{scene_id}/{shot_id}"


def _blocked_project(reason: str) -> StepView:
    """A step whose stage cannot even list its targets yet: one target that is not done."""
    return StepView([Target(PROJECT_KEY, "", False, block=reason)])


async def _ids_of(call: Awaitable[Any]) -> tuple[int, ...]:
    """The id of the job a start function returned (it returns the job, or `(job, created)`).
    A start function that makes no job (a look, a picture) gives none.
    """
    result = await call
    job = result[0] if isinstance(result, tuple) else result
    return (job.id,) if isinstance(job, Job) else ()


async def _start_each(
    session: AsyncSession,
    targets: list[Target],
    deadline: float,
    make: Callable[[Target], Awaitable[tuple[int, ...]]],
) -> list[Started]:
    """Starts the targets one by one. A start that raises is reported on its target and the
    others go on. Stops after `deadline`, but always starts the first.
    """
    results: list[Started] = []
    for target in targets:
        if results and time.monotonic() > deadline:
            break
        try:
            results.append(Started(target, job_ids=await make(target)))
        except ValueError as exc:
            await session.rollback()
            results.append(Started(target, error=str(exc)))
        except Exception as exc:
            _logger.exception("pipeline: starting '%s' failed unexpectedly", target.key)
            await session.rollback()
            results.append(Started(target, error=f"Unexpected error: {exc}"))
    return results


def _project_start(
    call: Callable[[AsyncSession, Project, RunOptions], Awaitable[Any]],
) -> StartTargets:
    """The start function of a step with one target: it calls `call` for it."""

    async def start(
        session: AsyncSession,
        project: Project,
        targets: list[Target],
        options: RunOptions,
        deadline: float,
    ) -> list[Started]:
        return await _start_each(
            session, targets, deadline, lambda _t: _ids_of(call(session, project, options))
        )

    return start


async def _start_inline(
    session: AsyncSession,
    targets: list[Target],
    work: Callable[[], Awaitable[dict[str, str]]],
) -> list[Started]:
    """Runs the work of an inline step once for all its targets. `work` returns the reason a
    target was left out, by target key. An error it raises is the reason for every target.
    """
    try:
        skipped = await work()
    except ValueError as exc:
        await session.rollback()
        return [Started(target, error=str(exc)) for target in targets]
    except Exception as exc:
        _logger.exception("pipeline: inline step failed unexpectedly")
        await session.rollback()
        return [Started(target, error=f"Unexpected error: {exc}") for target in targets]
    return [Started(target, error=skipped.get(target.key)) for target in targets]


# --- Story Bible and the discoveries --------------------------------------------------------


async def _evaluate_story_bible(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    story = project.script_text
    bible = await story_bible.latest(session, project.id)
    job = await store.latest_job(session, project.id, story_bible.JOB_TYPE)
    done = bible is not None and not story_bible.is_out_of_date(story, bible)
    return StepView(
        [
            Target(
                PROJECT_KEY,
                "",
                done,
                active=_active(job),
                block=_STORY_FIRST if _blank(story) else None,
                last_error=_failure(job),
            )
        ]
    )


async def _start_story_bible(session: AsyncSession, project: Project, options: RunOptions) -> Job:
    return await story_bible.start_run(session, project)


def _discovery_adapter(kind: discovery.StageKind) -> Adapter:
    async def evaluate(session: AsyncSession, project: Project, options: RunOptions) -> StepView:
        story = project.script_text
        bible = await story_bible.latest(session, project.id)
        row = await discovery.latest(session, kind, project.id)
        job = await store.latest_job(session, project.id, discovery.SPECS[kind].job_type)
        bible_version = bible.version if bible is not None else None
        done = row is not None and not discovery.is_out_of_date(story, row, bible_version)
        block: str | None = None
        if _blank(story):
            block = _STORY_FIRST
        elif bible is None or story_bible.is_out_of_date(story, bible):
            block = f"The Story Bible is not up to date, so the {kind} cannot be found yet."
        return StepView(
            [
                Target(
                    PROJECT_KEY,
                    "",
                    done,
                    active=_active(job),
                    block=block,
                    last_error=_failure(job),
                )
            ]
        )

    async def call(session: AsyncSession, project: Project, options: RunOptions) -> Job:
        return await discovery.start_run(session, project, kind)

    return Adapter(evaluate, _project_start(call))


# --- Linking (inline) -----------------------------------------------------------------------


async def _evaluate_links(session: AsyncSession, project: Project, options: RunOptions) -> StepView:
    characters = await character_links.state(session, project.id)
    environments = await environment_links.state(session, project.id)
    targets = [
        Target(
            f"character:{entry.item['id']}",
            str(entry.item.get("name", entry.item["id"])),
            entry.info is not None,
            ref=("character",),
        )
        for entry in characters.entries
    ] + [
        Target(
            f"environment:{entry.item['id']}",
            str(entry.item.get("name", entry.item["id"])),
            entry.info is not None,
            ref=("environment",),
        )
        for entry in environments.entries
    ]
    return StepView(targets)


async def _start_links(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    async def link_characters() -> dict[str, str]:
        await character_links.link_all(session, project)
        return {}

    async def link_environments() -> dict[str, str]:
        await environment_links.link_all(session, project)
        return {}

    results: list[Started] = []
    characters = [target for target in targets if target.ref == ("character",)]
    if characters:
        results.extend(await _start_inline(session, characters, link_characters))
    environments = [target for target in targets if target.ref == ("environment",)]
    if environments:
        results.extend(await _start_inline(session, environments, link_environments))
    return results


# --- Character relations --------------------------------------------------------------------


async def _evaluate_relations(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await character_relations.state(session, project)
    if state.discovery_version is None:
        return _blocked_project(state.blocked_reason or "Find the characters first.")
    if len(state.characters) < character_relations.MIN_CHARACTERS:
        return StepView([Target(PROJECT_KEY, "", True)])  # relations are between two or more
    done = state.version is not None and not state.reasons
    active = _active(state.job)
    return StepView(
        [
            Target(
                PROJECT_KEY,
                "",
                done,
                active=active,
                block=None if done or active else state.blocked_reason,
                consent=(
                    "The newest relations were written by you, and finding them again adds a "
                    "version from the model."
                    if state.needs_confirmation and not done
                    else None
                ),
                last_error=_failure(state.job),
            )
        ]
    )


async def _call_relations(session: AsyncSession, project: Project, options: RunOptions) -> Job:
    return await character_relations.start_run(
        session, project, confirm_replace_manual=options.confirm_overwrite
    )


# --- Character definitions ------------------------------------------------------------------


async def _evaluate_character_definitions(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await character_definitions.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    targets: list[Target] = []
    for entry in state.entries:
        done = entry.status == "defined"
        active = _active(entry.job)
        targets.append(
            Target(
                f"character:{entry.item['id']}",
                str(entry.item.get("name", entry.item["id"])),
                done,
                active=active,
                block=None if done or active else entry.blocked_reason,
                consent=(
                    "Chosen from the Character Lab: defining it overwrites its profile."
                    if entry.needs_confirmation and not done
                    else None
                ),
                last_error=_failure(entry.job),
                ref=(entry.item["id"],),
            )
        )
    return StepView(targets)


async def _start_character_definitions(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    return await _start_each(
        session,
        targets,
        deadline,
        lambda target: _ids_of(
            character_definitions.start_run(
                session, project, target.ref[0], confirm_overwrite=options.confirm_overwrite
            )
        ),
    )


# --- Environment definitions (with the picture) ---------------------------------------------


async def _evaluate_environment_definitions(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await environment_definitions.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    targets: list[Target] = []
    for entry in state.entries:
        discovery_id = entry.item["id"]
        label = str(entry.item.get("name", discovery_id))
        picture = entry.picture
        defined = entry.status == "defined"
        done = defined and picture.status == "ready"
        active = _active(entry.job) or (defined and picture.status == "in_progress")
        block: str | None = None
        last_error: str | None = _failure(entry.job)
        if defined:
            # The definition is there: what is missing is the picture.
            step = "picture"
            if not done and not active and not picture.can_run:
                block = picture.blocked_reason
            last_error = picture.error or last_error
        else:
            step = "define"
            if not active and not entry.can_run:
                block = entry.blocked_reason
        targets.append(
            Target(
                f"environment:{discovery_id}",
                label,
                done,
                active=active,
                block=None if done else block,
                consent=(
                    "Chosen from the Character Lab: defining it overwrites its description, "
                    "atmosphere and era."
                    if entry.needs_confirmation and not defined
                    else None
                ),
                last_error=last_error,
                ref=(discovery_id, step),
            )
        )
    return StepView(targets)


async def _start_environment_definitions(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    async def make(target: Target) -> tuple[int, ...]:
        discovery_id, what = target.ref
        if what == "define":
            return await _ids_of(
                environment_definitions.start_run(
                    session, project, discovery_id, confirm_overwrite=options.confirm_overwrite
                )
            )
        await environment_definitions.start_picture(session, project, discovery_id)
        return ()

    return await _start_each(session, targets, deadline, make)


# --- Character images -----------------------------------------------------------------------


async def _evaluate_character_images(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await character_images.state(session, project)
    targets: list[Target] = []
    for entry in state.entries:
        discovery_id = entry.definition.item["id"]
        done = entry.status == "ready"
        active = entry.status == "in_progress"
        waits_for: tuple[str, ...] = ()
        block: str | None = None
        if not done and not active and not entry.can_run:
            block = entry.blocked_reason
            if entry.base_refusal is not None and entry.made_from is not None:
                # Drawn from another character: it goes on once that one has images.
                waits_for = (f"character:{entry.made_from.discovery_id}",)
        targets.append(
            Target(
                f"character:{discovery_id}",
                str(entry.definition.item.get("name", discovery_id)),
                done,
                active=active,
                block=block,
                consent=(
                    "Chosen from the Character Lab: new images make a new look its current look."
                    if entry.needs_confirmation and not done
                    else None
                ),
                last_error=entry.error,
                waits_for=waits_for,
                ref=(discovery_id,),
            )
        )
    return StepView(targets)


async def _start_character_images(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    return await _start_each(
        session,
        targets,
        deadline,
        lambda target: _ids_of(
            character_images.start_run(
                session, project, target.ref[0], confirm_overwrite=options.confirm_overwrite
            )
        ),
    )


# --- Voices and the narrator ----------------------------------------------------------------

_NARRATOR_KEY: Final = story_voices.NARRATOR_TARGET


async def _evaluate_voices(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    voices = await story_voices.state(session, project)
    narrator = await story_voices.narrator_state(session, project)
    targets: list[Target] = []
    for entry in voices.entries:
        discovery_id = entry.definition.item["id"]
        done = entry.status == "ready"
        active = entry.status == "in_progress"
        targets.append(
            Target(
                f"character:{discovery_id}",
                str(entry.definition.item.get("name", discovery_id)),
                done,
                active=active,
                block=None if done or active else entry.blocked_reason,
                consent=(
                    "Chosen from the Character Lab: a new voice replaces its voice."
                    if entry.needs_confirmation and not done
                    else None
                ),
                last_error=entry.error or _failure(entry.job),
                ref=(discovery_id,),
            )
        )
    narrator_done = narrator.status == "ready"
    narrator_active = narrator.status == "in_progress"
    targets.append(
        Target(
            _NARRATOR_KEY,
            "Narrator",
            narrator_done,
            active=narrator_active,
            block=None if narrator_done or narrator_active else narrator.blocked_reason,
            consent=(
                "The narrator's voice was chosen by hand, and a new one replaces it."
                if narrator.needs_confirmation and not narrator_done
                else None
            ),
            last_error=narrator.error or _failure(narrator.job),
            ref=(_NARRATOR_KEY,),
        )
    )
    return StepView(targets)


async def _start_voices(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    async def make(target: Target) -> tuple[int, ...]:
        if target.ref == (_NARRATOR_KEY,):
            return await _ids_of(
                story_voices.start_narrator(
                    session, project, confirm_replace_manual=options.confirm_overwrite
                )
            )
        return await _ids_of(
            story_voices.start_run(
                session, project, target.ref[0], confirm_overwrite=options.confirm_overwrite
            )
        )

    return await _start_each(session, targets, deadline, make)


# --- Scene definitions and events -----------------------------------------------------------


async def _evaluate_scene_definitions(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await scene_definitions.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    targets: list[Target] = []
    for entry in state.entries:
        done = entry.status == "defined"
        active = _active(entry.job)
        targets.append(
            Target(
                f"scene:{entry.item['id']}",
                _scene_label(entry.item),
                done,
                active=active,
                block=None if done or active else entry.blocked_reason,
                last_error=_failure(entry.job),
                ref=(entry.item["id"],),
            )
        )
    return StepView(targets)


async def _start_scene_definitions(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    return await _start_each(
        session,
        targets,
        deadline,
        lambda target: _ids_of(scene_definitions.start_run(session, project, target.ref[0])),
    )


async def _evaluate_events(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await scene_events.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    targets: list[Target] = []
    for entry in state.entries:
        done = entry.status == "extracted"
        active = _active(entry.job)
        targets.append(
            Target(
                f"scene:{entry.item['id']}",
                _scene_label(entry.item),
                done,
                active=active,
                block=None if done or active else entry.blocked_reason,
                last_error=_failure(entry.job),
                ref=(entry.item["id"],),
            )
        )
    return StepView(targets)


async def _start_events(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    return await _start_each(
        session,
        targets,
        deadline,
        lambda target: _ids_of(scene_events.start_run(session, project, target.ref[0])),
    )


# --- Looks and states -----------------------------------------------------------------------


async def _evaluate_resolution(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await look_state_resolution.state(session, project)
    done = state.version is not None and not state.reasons
    active = _active(state.job)
    return StepView(
        [
            Target(
                PROJECT_KEY,
                "",
                done,
                active=active,
                block=None if done or active else state.blocked_reason,
                last_error=_failure(state.job),
            )
        ]
    )


async def _call_resolution(session: AsyncSession, project: Project, options: RunOptions) -> Job:
    return await look_state_resolution.start_run(session, project)


async def _evaluate_look_state_images(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await look_state_images.state(session, project)
    if not state.items and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    targets: list[Target] = []
    for item in state.items:
        done = item.status == "ready"
        active = item.status == "in_progress"
        block: str | None = None
        if not done and not active:
            block = state.blocked_reason or (None if item.can_run else item.blocked_reason)
        targets.append(
            Target(
                f"{item.kind}:{item.record_id}",
                f"{item.subject_name}: {item.name}",
                done,
                active=active,
                block=block,
                last_error=item.error,
                ref=(item.kind, str(item.record_id)),
            )
        )
    return StepView(targets)


async def _start_look_state_images(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    async def make(target: Target) -> tuple[int, ...]:
        kind, record_id = target.ref
        if kind == "look":
            await look_state_images.start_look_record(session, project, int(record_id))
        else:
            await look_state_images.start_state_record(session, project, int(record_id))
        return ()

    return await _start_each(session, targets, deadline, make)


# --- Speech ---------------------------------------------------------------------------------


async def _evaluate_speech_units(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await speech_units.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    return StepView(
        [
            Target(
                f"scene:{entry.item['id']}",
                _scene_label(entry.item),
                entry.status == "planned",
                block=None if entry.status == "planned" else entry.blocked_reason,
                ref=(entry.item["id"],),
            )
            for entry in state.entries
        ]
    )


async def _start_speech_units(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    async def work() -> dict[str, str]:
        result = await speech_units.plan_all(session, project)
        return {f"scene:{skipped.scene_id}": skipped.reason for skipped in result.skipped}

    return await _start_inline(session, targets, work)


async def _evaluate_speech_synthesis(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await speech_synthesis.state(session, project)
    targets: list[Target] = []
    for scene in state.scenes:
        scene_id = scene.scene.item["id"]
        for unit in scene.units:
            unit_id = unit.unit["id"]
            done = unit.status == "ready"
            active = unit.status == "in_progress"
            targets.append(
                Target(
                    f"unit:{scene_id}/{unit_id}",
                    f"Scene {scene.scene.item.get('index')}, line {unit_id}",
                    done,
                    active=active,
                    block=None if done or active else unit.blocked_reason,
                    last_error=unit.error or _failure(unit.job),
                    ref=(scene_id, unit_id),
                )
            )
    if not targets and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    return StepView(targets)


async def _start_speech_synthesis(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    return await _start_each(
        session,
        targets,
        deadline,
        lambda target: _ids_of(
            speech_synthesis.start_unit(session, project, target.ref[0], target.ref[1])
        ),
    )


# --- Shot plans -----------------------------------------------------------------------------


async def _evaluate_shot_plans(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await shot_plans.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    now = utcnow()
    targets: list[Target] = []
    for entry in state.entries:
        active = _active(entry.job)
        ready = entry.status == "planned" and entry.generation_ready
        done = ready and not active
        block: str | None = None
        settling = False
        if not done and not active:
            if entry.status == "planned":
                # Planned, but the plan cannot be used for generation. A re-plan is queued by
                # the job that saved it, a moment later: wait for it, then report.
                recent = (
                    entry.row is not None
                    and (now - entry.row.created_at).total_seconds() < SETTLE_SECONDS
                )
                settling = recent and entry.replan_attempt < state.replan_max_tries
                if not settling:
                    block = entry.generation_blocked_reason or (
                        "The plan of this scene cannot be used to make clips."
                    )
            elif not entry.can_run:
                block = entry.blocked_reason
        targets.append(
            Target(
                f"scene:{entry.item['id']}",
                _scene_label(entry.item),
                done,
                active=active,
                block=block,
                settling=settling,
                last_error=_failure(entry.job),
                ref=(entry.item["id"],),
            )
        )
    return StepView(targets)


async def _start_shot_plans(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    return await _start_each(
        session,
        targets,
        deadline,
        lambda target: _ids_of(shot_plans.start_run(session, project, target.ref[0])),
    )


# --- Shot definitions -----------------------------------------------------------------------


async def _evaluate_shot_definitions(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await shot_definitions.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    targets: list[Target] = []
    for scene in state.entries:
        scene_id = scene.item["id"]
        if not scene.shots:
            targets.append(
                Target(
                    f"scene:{scene_id}",
                    _scene_label(scene.item),
                    False,
                    block=scene.blocked_reason or "This scene has no planned shots.",
                )
            )
        for shot in scene.shots:
            shot_id = shot.shot["id"]
            repairing = shot.blocked_reason == shot_definitions.REPAIRING_REASON
            active = _active(shot.job) or repairing
            done = shot.status == "defined" and not active
            targets.append(
                Target(
                    _shot_key(scene_id, shot_id),
                    _shot_label(scene.item, shot.shot),
                    done,
                    active=active,
                    block=None if done or active else (shot.blocked_reason or scene.blocked_reason),
                    last_error=_failure(shot.job),
                    ref=(scene_id, shot_id),
                )
            )
    return StepView(targets)


async def _start_shot_definitions(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    return await _start_each(
        session,
        targets,
        deadline,
        lambda target: _ids_of(
            shot_definitions.start_shot(session, project, target.ref[0], target.ref[1])
        ),
    )


# --- Shot continuity ------------------------------------------------------------------------


async def _evaluate_shot_continuity(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await shot_continuity.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    now = utcnow()
    targets: list[Target] = []
    warnings: list[str] = []
    for entry in state.entries:
        label = _scene_label(entry.item)
        scene_id = entry.item["id"]
        active = entry.status in ("checking", "reconciling")
        settling = False
        block: str | None = None
        done = entry.status == "consistent"
        if entry.status == "mismatches":
            # The cuts that do not line up are repaired by the job that found them, a moment
            # after it ends, until the round limit. Whatever remains is a warning: the run
            # never starts the paid repair rounds again.
            recent = (
                entry.row is not None
                and (now - entry.row.created_at).total_seconds() < SETTLE_SECONDS
            )
            if recent and not entry.round_limit_reached:
                settling = True
            else:
                done = True
                warnings.append(
                    f"{label}: {len(entry.mismatches)} cut(s) still do not line up"
                    + (
                        f" after {entry.round} round(s) of repairs."
                        if entry.round_limit_reached
                        else "."
                    )
                    + " Fix them from the scene, or render as it is."
                )
        elif entry.status == "not_checked" and not entry.can_run:
            block = entry.blocked_reason
        targets.append(
            Target(
                f"scene:{scene_id}",
                label,
                done,
                active=active,
                block=block,
                settling=settling,
                last_error=_failure(entry.job),
                ref=(scene_id,),
            )
        )
    return StepView(targets, warnings=warnings)


async def _start_shot_continuity(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    async def make(target: Target) -> tuple[int, ...]:
        # Queues the check only when the scene's shots are all defined and no check covers
        # them: the same call the shot jobs make when they end. It never restarts the rounds.
        job = await shot_continuity.queue_check_if_ready(session, project.id, target.ref[0])
        if job is None:
            raise shot_continuity.ShotContinuityError(
                "The continuity check was not queued: the scene's shots are not all defined, "
                "or a check covers them already."
            )
        return (job.id,)

    return await _start_each(session, targets, deadline, make)


# --- Shot references and generation requests (inline) ---------------------------------------


async def _evaluate_references(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await shot_references.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    return StepView(
        [
            Target(
                _shot_key(scene.item["id"], shot.shot["id"]),
                _shot_label(scene.item, shot.shot),
                shot.status == "selected",
                block=None if shot.status == "selected" else shot.blocked_reason,
                ref=(scene.item["id"], shot.shot["id"]),
            )
            for scene in state.entries
            for shot in scene.shots
        ]
    )


async def _start_references(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    async def work() -> dict[str, str]:
        result = await shot_references.select_all(session, project)
        return {
            _shot_key(skipped.scene_id, skipped.shot_id): skipped.reason
            for skipped in result.skipped
            if skipped.shot_id is not None
        }

    return await _start_inline(session, targets, work)


async def _evaluate_generation_requests(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await generation_requests.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    return StepView(
        [
            Target(
                _shot_key(scene.item["id"], shot.shot["id"]),
                _shot_label(scene.item, shot.shot),
                shot.status == "planned",
                block=None if shot.status == "planned" else shot.blocked_reason,
                ref=(scene.item["id"], shot.shot["id"]),
            )
            for scene in state.entries
            for shot in scene.shots
        ]
    )


async def _start_generation_requests(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    async def work() -> dict[str, str]:
        result = await generation_requests.plan_all(session, project)
        return {
            _shot_key(skipped.scene_id, skipped.shot_id): skipped.reason
            for skipped in result.skipped
            if skipped.shot_id is not None
        }

    return await _start_inline(session, targets, work)


# --- Shot prompts ---------------------------------------------------------------------------


async def _evaluate_prompts(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await shot_prompts.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    targets: list[Target] = []
    for scene in state.entries:
        for shot in scene.shots:
            done = shot.status == "compiled"
            active = _active(shot.job)
            targets.append(
                Target(
                    _shot_key(scene.item["id"], shot.shot["id"]),
                    _shot_label(scene.item, shot.shot),
                    done,
                    active=active,
                    block=None if done or active else shot.blocked_reason,
                    last_error=_failure(shot.job),
                    ref=(scene.item["id"], shot.shot["id"]),
                )
            )
    return StepView(targets)


async def _start_prompts(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    return await _start_each(
        session,
        targets,
        deadline,
        lambda target: _ids_of(
            shot_prompts.start_shot(session, project, target.ref[0], target.ref[1])
        ),
    )


# --- Shot clips -----------------------------------------------------------------------------

_CHECK: Final = "check"
_GENERATE: Final = "generate"


def _failed_shot_reason(shot: shot_takes.ShotEntry) -> str:
    """Why a `failed` shot became a problem. The run adds no GPU retries of its own."""
    newest = shot.takes[0] if shot.takes else None
    if newest is None:
        return "No clip could be made. Generate the shot from its own button to try again."
    validation = newest.validation
    if isinstance(validation, dict) and validation.get("passed") is False:
        messages = [
            str(problem["message"])
            for problem in validation.get("problems", [])
            if isinstance(problem, dict) and problem.get("message")
        ]
        text = " ".join(messages) or "The clip did not pass its check."
        if validation.get("kind") == "plan":
            return (
                f"The planned length of the shot is not possible for the clip model: {text} "
                "Plan the scene's shots again."
            )
        return f"No take passed its check: {text} Generate the shot from its own button to retry."
    error = _failure(newest.job)
    if error is not None:
        return f"The clip could not be made: {error}. Generate the shot again from its own button."
    return "No clip could be made. Generate the shot from its own button to try again."


async def _evaluate_shot_generation(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await shot_takes.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    checking = _active(state.check_job)
    targets: list[Target] = []
    for scene in state.entries:
        scene_id = scene.item["id"]
        for shot in scene.shots:
            shot_id = shot.shot["id"]
            generating = any(take.state == "generating" for take in shot.takes)
            unchecked = shot.status == "unchecked"
            done = shot.status == "generated" and not generating
            active = generating or (unchecked and checking)
            block: str | None = None
            if not done and not active:
                if shot.status == "failed":
                    block = _failed_shot_reason(shot)
                elif not unchecked and not shot.can_run:
                    block = shot.blocked_reason
            targets.append(
                Target(
                    _shot_key(scene_id, shot_id),
                    _shot_label(scene.item, shot.shot),
                    done,
                    active=active,
                    block=block,
                    last_error=_failure(shot.job),
                    ref=(scene_id, shot_id, _CHECK if unchecked else _GENERATE),
                )
            )
    return StepView(targets)


async def _start_shot_generation(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    results: list[Started] = []
    to_check = [target for target in targets if target.ref[-1] == _CHECK]
    if to_check:
        # Clips made before the checks existed are checked once, for the whole project. The
        # check is free; a new clip is a GPU run.
        check_ids: tuple[int, ...] = ()
        check_error: str | None = None
        try:
            check_job = await shot_takes.start_check(session, project)
            check_ids = (check_job.id,)
        except ValueError as exc:
            await session.rollback()
            check_error = str(exc)
        # One job serves every shot; it is recorded once.
        results.extend(
            Started(target, job_ids=check_ids if position == 0 else (), error=check_error)
            for position, target in enumerate(to_check)
        )
    to_generate = [target for target in targets if target.ref[-1] == _GENERATE]
    results.extend(
        await _start_each(
            session,
            to_generate,
            deadline,
            lambda target: _ids_of(
                shot_takes.start_shot(session, project, target.ref[0], target.ref[1])
            ),
        )
    )
    return results


# --- The render -----------------------------------------------------------------------------


async def _evaluate_render(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await story_renders.state(session, project)
    active = _active(state.job)
    done = bool(state.renders) and state.renders[0].status == "current" and not active
    return StepView(
        [
            Target(
                PROJECT_KEY,
                "",
                done,
                active=active,
                block=None if done or active or state.can_render else state.blocked_reason,
                last_error=_failure(state.job),
            )
        ]
    )


async def _call_render(session: AsyncSession, project: Project, options: RunOptions) -> Job:
    return await story_renders.start_render(session, project)


# --- The adapters ---------------------------------------------------------------------------

ADAPTERS: Final[dict[str, Adapter]] = {
    "story_bible": Adapter(_evaluate_story_bible, _project_start(_start_story_bible)),
    "character_discovery": _discovery_adapter("characters"),
    "environment_discovery": _discovery_adapter("environments"),
    "scene_discovery": _discovery_adapter("scenes"),
    "links": Adapter(_evaluate_links, _start_links),
    "relations": Adapter(_evaluate_relations, _project_start(_call_relations)),
    "character_definitions": Adapter(_evaluate_character_definitions, _start_character_definitions),
    "environment_definitions": Adapter(
        _evaluate_environment_definitions, _start_environment_definitions
    ),
    "character_images": Adapter(_evaluate_character_images, _start_character_images),
    "voices": Adapter(_evaluate_voices, _start_voices),
    "scene_definitions": Adapter(_evaluate_scene_definitions, _start_scene_definitions),
    "events": Adapter(_evaluate_events, _start_events),
    "resolution": Adapter(_evaluate_resolution, _project_start(_call_resolution)),
    "look_state_images": Adapter(_evaluate_look_state_images, _start_look_state_images),
    "speech_units": Adapter(_evaluate_speech_units, _start_speech_units),
    "speech_synthesis": Adapter(_evaluate_speech_synthesis, _start_speech_synthesis),
    "shot_plans": Adapter(_evaluate_shot_plans, _start_shot_plans),
    "shot_definitions": Adapter(_evaluate_shot_definitions, _start_shot_definitions),
    "shot_continuity": Adapter(_evaluate_shot_continuity, _start_shot_continuity),
    "references": Adapter(_evaluate_references, _start_references),
    "generation_requests": Adapter(_evaluate_generation_requests, _start_generation_requests),
    "prompts": Adapter(_evaluate_prompts, _start_prompts),
    "shot_generation": Adapter(_evaluate_shot_generation, _start_shot_generation),
    "render": Adapter(_evaluate_render, _project_start(_call_render)),
}

if set(ADAPTERS) != set(STEP_KEYS):  # a step without an adapter would never run
    raise ValueError("story_pipeline_targets: the adapters and the steps do not match")


# --- What must be allowed before the run starts ---------------------------------------------

# The steps that can replace something the user chose or wrote.
_CONSENT_STEPS: Final[tuple[str, ...]] = (
    "relations",
    "character_definitions",
    "environment_definitions",
    "character_images",
    "voices",
)


@dataclass(frozen=True)
class Confirmation:
    """One target the run would replace, that the user must allow first."""

    step_key: str
    step_label: str
    # What is replaced ("Mira", "Narrator"); empty for the project.
    target: str
    reason: str


async def confirmations(session: AsyncSession, project: Project) -> list[Confirmation]:
    """The targets that a run started now would replace, and that need the user's consent: the
    ones that are not up to date and hold what the user chose or wrote. Read-only.
    """
    found: list[Confirmation] = []
    options = RunOptions()
    for key in _CONSENT_STEPS:
        view = await ADAPTERS[key].evaluate(session, project, options)
        found.extend(
            Confirmation(key, STEP_LABELS[key], target.label, target.consent)
            for target in view.targets
            if not target.done and target.consent is not None
        )
    return found
