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
from dataclasses import dataclass, replace
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, ProjectMissingLibraryItem
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
    environment_views,
    explainer,
    generation_requests,
    look_state_images,
    look_state_resolution,
    music_bible,
    music_cue_writer,
    music_cues,
    music_placement,
    music_plan,
    music_takes,
    music_themes,
    review_points,
    scene_definitions,
    scene_events,
    scene_staging,
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
    word_timings,
)
from app.services.projects import SPEECH_NO_DIALOGUE, SPEECH_NO_NARRATION
from app.services.story_pipeline import (
    PROJECT_KEY,
    SCOPE_OUT_OF_DATE,
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

# What a run would replace that the user wrote (PHASE-037). Each is the `consent` of a target.
_MANUAL_STORY_BIBLE: Final = (
    "The newest Story Bible was written by you, and writing it again adds a version from the model."
)
_MANUAL_LIST: Final = (
    "The newest list was written by you, and finding it again adds a version from the model."
)
_MANUAL_DEFINITION: Final = (
    "The newest definition of this scene was written by you, and defining it again adds a "
    "version from the model."
)
_MANUAL_EVENTS: Final = (
    "The newest events of this scene were written by you, and extracting them again adds a "
    "version from the model."
)
_MANUAL_MUSIC_BIBLE: Final = (
    "The newest Music Bible was written or chosen by you, and writing it again adds a version "
    "from the model."
)
_MANUAL_MUSIC_PLAN: Final = (
    "The newest music plan was written by you, and planning the music again adds a version from "
    "the model."
)
_MANUAL_MUSIC_TAKE: Final = (
    "You chose the take of this cue, and making it again replaces your choice."
)
_MANUAL_MUSIC_THEME: Final = (
    "You chose the canonical recording of this theme, and recording it again replaces your choice."
)
_MANUAL_UNITS: Final = (
    "The newest speech units of this scene were written by you, and planning them again "
    "replaces your cuts."
)
_MANUAL_STAGING: Final = (
    "The newest staging of this scene was written by you, and staging it again adds a version "
    "from the model."
)
# PHASE-038: the directing stages.
_MANUAL_SHOT_PLAN: Final = (
    "The newest shot plan of this scene was written by you, and planning it again adds a "
    "version from the model."
)
_MANUAL_SHOT_DEFINITION: Final = (
    "The newest definition of this shot was written by you, and defining it again adds a "
    "version from the model."
)
_MANUAL_REFERENCES: Final = (
    "The newest references of this shot were chosen by you, and choosing them again replaces them."
)
_MANUAL_PROMPT: Final = (
    "The newest prompt of this shot was written by you, and compiling it again adds a version "
    "from the model."
)

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


def _options_for(options: RunOptions, target: Target) -> RunOptions:
    """The options a target is started with. A target the user rejected at a review point
    (PHASE-041) is replaced on purpose, so the stage is told it may replace what the user chose
    or wrote there, without the run's `confirm_overwrite` being given for everything else.
    """
    return replace(options, confirm_overwrite=True) if target.redo else options


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
            session,
            targets,
            deadline,
            lambda target: _ids_of(call(session, project, _options_for(options, target))),
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
                consent=(
                    _MANUAL_STORY_BIBLE
                    if bible is not None and bible.source == "manual" and not done
                    else None
                ),
                last_error=_failure(job),
                stale=bible is not None and not done,
            )
        ]
    )


async def _start_story_bible(session: AsyncSession, project: Project, options: RunOptions) -> Job:
    return await story_bible.start_run(
        session, project, confirm_replace_manual=options.confirm_overwrite
    )


def _discovery_adapter(kind: discovery.StageKind) -> Adapter:
    async def evaluate(session: AsyncSession, project: Project, options: RunOptions) -> StepView:
        story = project.script_text
        bible = await story_bible.latest(session, project.id)
        row = await discovery.latest(session, kind, project.id)
        job = await store.latest_job(session, project.id, discovery.SPECS[kind].job_type)
        bible_version = bible.version if bible is not None else None
        cast_sha256 = await discovery.current_cast_sha256(session, project.id, kind)
        done = row is not None and not discovery.is_out_of_date(
            story, row, bible_version, current_cast_sha256=cast_sha256
        )
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
                    consent=(
                        _MANUAL_LIST
                        if row is not None and row.source == "manual" and not done
                        else None
                    ),
                    last_error=_failure(job),
                    stale=row is not None and not done,
                )
            ]
        )

    async def call(session: AsyncSession, project: Project, options: RunOptions) -> Job:
        return await discovery.start_run(
            session, project, kind, confirm_replace_manual=options.confirm_overwrite
        )

    return Adapter(evaluate, _project_start(call))


# --- Linking (inline) -----------------------------------------------------------------------


def _deleted_block(missing: ProjectMissingLibraryItem | None, kind: str) -> str | None:
    """Why an entry cannot be linked by the run: its library item was deleted (PHASE-055), so
    the user has to create it again or pick another one first.
    """
    if missing is None:
        return None
    return (
        f"'{missing.name}' was deleted from the {kind} library. "
        f"Create the {kind} again or pick another one in the links step."
    )


async def _evaluate_links(session: AsyncSession, project: Project, options: RunOptions) -> StepView:
    characters = await character_links.state(session, project.id)
    environments = await environment_links.state(session, project.id)
    targets = [
        Target(
            f"character:{entry.item['id']}",
            str(entry.item.get("name", entry.item["id"])),
            entry.info is not None,
            ref=("character",),
            block=_deleted_block(entry.missing, "character"),
        )
        for entry in characters.entries
    ] + [
        Target(
            f"environment:{entry.item['id']}",
            str(entry.item.get("name", entry.item["id"])),
            entry.info is not None,
            ref=("environment",),
            block=_deleted_block(entry.missing, "environment"),
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
                stale=state.version is not None and not done,
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
                stale=entry.status == "out_of_date",
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
            # The definition is there: what is missing is the picture. A picture that is ready
            # is replaced (only when the user rejected it at a review point, PHASE-041).
            step = "replace" if picture.status == "ready" else "picture"
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
                stale=entry.status == "out_of_date",
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
                    session,
                    project,
                    discovery_id,
                    confirm_overwrite=_options_for(options, target).confirm_overwrite,
                )
            )
        if what == "replace":
            # Rejected at a review point: a new picture from the same definition (PHASE-039).
            await environment_definitions.replace_picture(session, project, discovery_id)
        else:
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
                stale=entry.status == "out_of_date",
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
                session,
                project,
                target.ref[0],
                confirm_overwrite=_options_for(options, target).confirm_overwrite,
            )
        ),
    )


# --- Voices and the narrator ----------------------------------------------------------------

_NARRATOR_KEY: Final = story_voices.NARRATOR_TARGET


async def _evaluate_voices(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    # A project with no dialogue needs no character voice, and one with no narration needs no
    # narrator voice (PHASE-049): those targets are left out, so nothing is paid for or awaited.
    needs_characters = project.speech_mode != SPEECH_NO_DIALOGUE
    needs_narrator = project.speech_mode != SPEECH_NO_NARRATION
    targets: list[Target] = []
    if not needs_characters:
        voice_entries: list[story_voices.EntryVoice] = []
    else:
        voice_entries = (await story_voices.state(session, project)).entries
    for entry in voice_entries:
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
                stale=entry.status == "out_of_date",
            )
        )
    if needs_narrator and explainer.is_explainer(project):
        # EXPLAINER-003: the narrator is the presenter. It is set from the presenter's voice in
        # the run itself (no job, nothing to wait for), and again when that voice changes.
        wanted = await explainer.presenter_voice_id(session, project.id)
        newest = (await story_voices.narrator_state(session, project)).version
        presenter_done = newest is not None and wanted is not None and newest.voice_id == wanted
        targets.append(
            Target(
                _NARRATOR_KEY,
                "Narrator (the presenter's voice)",
                presenter_done,
                block=None if wanted is not None else "The presenter has no saved voice.",
                ref=(_NARRATOR_KEY,),
                stale=newest is not None and not presenter_done,
            )
        )
    elif needs_narrator:
        narrator = await story_voices.narrator_state(session, project)
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
                stale=narrator.status == "out_of_date",
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
        if target.ref == (_NARRATOR_KEY,) and explainer.is_explainer(project):
            await story_voices.use_presenter_voice(session, project)
            return ()
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
                consent=_MANUAL_DEFINITION if entry.needs_confirmation and not done else None,
                last_error=_failure(entry.job),
                ref=(entry.item["id"],),
                stale=entry.status == "out_of_date",
                group=entry.item["id"],
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
        lambda target: _ids_of(
            scene_definitions.start_run(
                session,
                project,
                target.ref[0],
                confirm_replace_manual=_options_for(options, target).confirm_overwrite,
            )
        ),
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
                consent=_MANUAL_EVENTS if entry.needs_confirmation and not done else None,
                last_error=_failure(entry.job),
                ref=(entry.item["id"],),
                stale=entry.status == "out_of_date",
                group=entry.item["id"],
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
        lambda target: _ids_of(
            scene_events.start_run(
                session,
                project,
                target.ref[0],
                confirm_replace_manual=_options_for(options, target).confirm_overwrite,
            )
        ),
    )


# --- The Music Bible (MUSIC-006) ------------------------------------------------------------


async def _evaluate_music_bible(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    # With music switched off nothing is made (MD-21): the step has one target that is already
    # done, so a run reports it as skipped.
    if not project.music_enabled:
        return StepView([Target(PROJECT_KEY, "", True)])
    state = await music_bible.state(session, project)
    done = state.latest is not None and not state.out_of_date
    active = _active(state.job)
    return StepView(
        [
            Target(
                PROJECT_KEY,
                "",
                done,
                active=active,
                block=None if done or active else state.blocked_reason,
                consent=_MANUAL_MUSIC_BIBLE if state.needs_confirmation and not done else None,
                last_error=_failure(state.job),
                stale=state.latest is not None and not done,
            )
        ]
    )


async def _call_music_bible(session: AsyncSession, project: Project, options: RunOptions) -> Job:
    return await music_bible.start_run(
        session, project, confirm_replace_manual=options.confirm_overwrite
    )


# --- The music themes (MUSIC-007) -------------------------------------------------------------


def _theme_last_error(view: music_themes.ThemeView) -> str | None:
    """Why the work of a theme did not get anywhere: its prompt job failed, or no candidate could
    be chosen (each one failed its check or its job).
    """
    failure = _failure(view.job)
    if failure is not None:
        return failure
    if view.action == "candidates" and view.candidates:
        return "no recording of the theme passed its check"
    return None


async def _evaluate_music_themes(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    # With music switched off nothing is made (MD-21): one target that is already done.
    if not project.music_enabled:
        return StepView([Target(PROJECT_KEY, "", True)])
    state = await music_themes.state(session, project)
    if not state.themes:
        return _blocked_project(state.blocked_reason or "The Music Bible has no themes.")
    targets: list[Target] = []
    for view in state.themes:
        theme_id = view.theme["id"]
        targets.append(
            Target(
                f"theme:{theme_id}",
                str(view.theme.get("name", theme_id)),
                view.done,
                active=view.active,
                consent=_MANUAL_MUSIC_THEME if view.needs_confirmation and not view.done else None,
                last_error=_theme_last_error(view),
                ref=(theme_id,),
                stale=view.row is not None and view.out_of_date,
            )
        )
    return StepView(targets)


async def _start_music_themes(
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
        lambda target: music_themes.start_run(
            session,
            project,
            theme_id=target.ref[0],
            confirm_replace_owner=_options_for(options, target).confirm_overwrite,
        ),
    )


# --- The music plan (MUSIC-008) --------------------------------------------------------------


async def _evaluate_music_plan(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    # With music switched off nothing is made (MD-21): the step has one target that is already
    # done, so a run reports it as skipped.
    if not project.music_enabled:
        return StepView([Target(PROJECT_KEY, "", True)])
    state = await music_plan.state(session, project)
    done = state.latest is not None and not state.out_of_date
    active = _active(state.job)
    return StepView(
        [
            Target(
                PROJECT_KEY,
                "",
                done,
                active=active,
                block=None if done or active else state.blocked_reason,
                consent=_MANUAL_MUSIC_PLAN if state.needs_confirmation and not done else None,
                last_error=_failure(state.job),
                stale=state.latest is not None and not done,
            )
        ]
    )


async def _call_music_plan(session: AsyncSession, project: Project, options: RunOptions) -> Job:
    return await music_plan.start_run(
        session, project, confirm_replace_manual=options.confirm_overwrite
    )


# --- The music cues (MUSIC-009) -------------------------------------------------------------

# The targets of the step are named for the plan version they belong to, so that a revised plan
# starts its cues with fresh tries.
_CUE_PREFIX: Final = "cue"
_REVISE_PREFIX: Final = "revise"
_AUDIT_PREFIX: Final = "audit"


async def _evaluate_music_cues(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    # With music switched off nothing is made (MD-21): one target that is already done.
    if not project.music_enabled:
        return StepView([Target(PROJECT_KEY, "", True)])
    state = await music_cues.state(session, project)
    if state.plan is None or state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason or music_cues.NO_PLAN_MESSAGE)
    version = state.plan.version
    audio = [view for view in state.cues if view.makes_audio]
    if not audio:
        return StepView([Target(PROJECT_KEY, "", True)])  # silences and sounds H3 makes only

    cue_keys = tuple(f"{_CUE_PREFIX}:v{version}:{view.cue['id']}" for view in audio)
    targets: list[Target] = []
    for key, view in zip(cue_keys, audio, strict=True):
        targets.append(
            Target(
                key,
                str(view.cue["summary"]),
                view.done,
                active=view.active,
                block=None if view.done or view.active else view.blocked_reason,
                last_error=_failure(view.job),
                ref=(view.cue["id"],),
                stale=view.row is not None and not view.done,
            )
        )
    if state.revision_pending:
        # Cues that pushed back wait for one revision of the plan, then are detailed again.
        targets.append(
            Target(
                f"{_REVISE_PREFIX}:v{version}",
                "Revise the plan from the cues' objections",
                False,
                active=state.revision_active,
                last_error=_failure(state.plan_job),
                waits_for=cue_keys,
                stale=True,
            )
        )
    else:
        targets.append(
            Target(
                f"{_AUDIT_PREFIX}:v{version}",
                "Audit all prompts",
                state.audit_current,
                active=state.audit_active,
                last_error=_failure(state.audit_job),
                waits_for=cue_keys,
                stale=state.audit is not None and not state.audit_current,
            )
        )
    return StepView(targets)


async def _start_music_cues(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    loaded = await music_cues.load(session, project)

    async def make(target: Target) -> tuple[int, ...]:
        kind = target.key.split(":", 1)[0]
        if kind == _CUE_PREFIX:
            return await _ids_of(
                music_cues.start_cue(session, project, target.ref[0], loaded=loaded)
            )
        if kind == _REVISE_PREFIX:
            return await _ids_of(music_cues.start_revision(session, project))
        return await _ids_of(music_cues.start_audit(session, project))

    return await _start_each(session, targets, deadline, make)


# --- The music takes (MUSIC-010) ------------------------------------------------------------

# Named for the plan version, so that a new plan starts its takes with fresh tries.
_TAKE_PREFIX: Final = "take"


async def _evaluate_music_generation(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    # With music switched off nothing is made (MD-21): one target that is already done.
    if not project.music_enabled:
        return StepView([Target(PROJECT_KEY, "", True)])
    state = await music_takes.state(session, project)
    if state.plan is None or state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason or music_cues.NO_PLAN_MESSAGE)
    if not state.items:
        return StepView([Target(PROJECT_KEY, "", True)])  # no cue makes audio

    targets: list[Target] = []
    for view in state.items:
        label = str(view.cue_view.cue["summary"])
        if view.item["role"] == music_cue_writer.ROLE_HIT:
            label += " (hit)"
        targets.append(
            Target(
                f"{_TAKE_PREFIX}:v{state.plan.version}:{view.item_id}",
                label,
                view.done,
                active=view.active,
                block=None if view.done or view.active else view.blocked_reason or view.last_error,
                consent=_MANUAL_MUSIC_TAKE if view.needs_confirmation and not view.done else None,
                last_error=view.last_error,
                ref=(view.item_id,),
                stale=view.out_of_date,
            )
        )
    return StepView(targets)


async def _start_music_generation(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    async def make(target: Target) -> tuple[int, ...]:
        return await music_takes.start_run(
            session,
            project,
            item_id=target.ref[0],
            confirm_replace_owner=options.confirm_overwrite,
        )

    return await _start_each(session, targets, deadline, make)


# --- The music placement (MUSIC-011) --------------------------------------------------------


async def _evaluate_music_placement(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    # With music switched off nothing is made (MD-21): one target that is already done. So it is
    # when no cue makes audio: there is nothing to place.
    if not project.music_enabled:
        return StepView([Target(PROJECT_KEY, "", True)])
    state = await music_placement.state(session, project)
    if state.nothing_to_place:
        return StepView([Target(PROJECT_KEY, "", True)])
    done = state.latest is not None and not state.out_of_date and state.blocked_reason is None
    active = state.active
    return StepView(
        [
            Target(
                PROJECT_KEY,
                "",
                done,
                active=active,
                block=None if done or active else state.blocked_reason,
                last_error=_failure(state.job),
                stale=state.latest is not None and not done,
            )
        ]
    )


async def _call_music_placement(
    session: AsyncSession, project: Project, options: RunOptions
) -> Job:
    return await music_placement.start_run(session, project)


# --- Scene staging and environment views (PHASE-051, PHASE-052) ------------------------------


async def _evaluate_scene_staging(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await scene_staging.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    targets: list[Target] = []
    for entry in state.entries:
        done = entry.status == "staged"
        active = _active(entry.job)
        targets.append(
            Target(
                f"scene:{entry.item['id']}",
                _scene_label(entry.item),
                done,
                active=active,
                block=None if done or active else entry.blocked_reason,
                consent=_MANUAL_STAGING if entry.needs_confirmation and not done else None,
                last_error=_failure(entry.job),
                ref=(entry.item["id"],),
                stale=entry.status == "out_of_date",
                group=entry.item["id"],
            )
        )
    return StepView(targets)


async def _start_scene_staging(
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
            scene_staging.start_run(
                session,
                project,
                target.ref[0],
                confirm_replace_manual=_options_for(options, target).confirm_overwrite,
            )
        ),
    )


async def _evaluate_environment_views(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    state = await environment_views.state(session, project)
    if not state.entries and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    targets: list[Target] = []
    for entry in state.entries:
        planned = entry.status == "planned"
        pictures = entry.pictures_status
        done = planned and pictures == "ready"
        active = _active(entry.job) or (planned and pictures == "in_progress")
        block: str | None = None
        last_error = _failure(entry.job)
        if planned:
            # The plan is there: what is missing is the pictures of its views.
            step = "pictures"
            if not done and not active and not entry.can_make_pictures:
                block = entry.pictures_blocked_reason
            last_error = next((item.error for item in entry.views if item.error), last_error)
        else:
            step = "plan"
            if not active and not entry.can_plan:
                block = entry.plan_blocked_reason
        targets.append(
            Target(
                f"environment:{entry.discovery_id}",
                entry.name,
                done,
                active=active,
                block=None if done else block,
                last_error=last_error,
                ref=(entry.discovery_id, step),
                stale=entry.status == "out_of_date" or any(item.reasons for item in entry.views),
            )
        )
    return StepView(targets)


async def _start_environment_views(
    session: AsyncSession,
    project: Project,
    targets: list[Target],
    options: RunOptions,
    deadline: float,
) -> list[Started]:
    async def make(target: Target) -> tuple[int, ...]:
        discovery_id, what = target.ref
        if what == "plan":
            return await _ids_of(environment_views.start_plan(session, project, discovery_id))
        await environment_views.start_pictures(session, project, discovery_id)
        return ()

    return await _start_each(session, targets, deadline, make)


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
                stale=state.version is not None and not done,
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
        # A view in a state has no record until it is made: it is told apart by its two ids.
        record = (
            f"{item.view_id}/{item.state_id}"
            if item.kind == look_state_images.VIEW_STATE
            else str(item.record_id)
        )
        targets.append(
            Target(
                f"{item.kind}:{record}",
                f"{item.subject_name}: {item.name}",
                done,
                active=active,
                block=block,
                last_error=item.error,
                ref=(item.kind, record),
                stale=bool(item.reasons),
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
        elif kind == look_state_images.VIEW_STATE:
            view_id, state_id = record_id.split("/")
            await look_state_images.start_view_state_record(
                session, project, int(view_id), int(state_id)
            )
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
                consent=(
                    _MANUAL_UNITS
                    if entry.needs_confirmation and entry.status != "planned"
                    else None
                ),
                ref=(entry.item["id"],),
                stale=entry.status == "out_of_date",
                group=entry.item["id"],
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
    if options.scope == SCOPE_OUT_OF_DATE:
        # Only the scenes the run chose: "plan all" would also plan scenes it leaves alone.
        async def plan_scene(target: Target) -> tuple[int, ...]:
            await speech_units.plan_scene(
                session, project, target.ref[0], confirm_replace_manual=options.confirm_overwrite
            )
            return ()

        return await _start_each(session, targets, deadline, plan_scene)

    async def work() -> dict[str, str]:
        result = await speech_units.plan_all(
            session, project, confirm_replace_manual=options.confirm_overwrite
        )
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
                    stale=unit.status == "out_of_date",
                    group=scene_id,
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


# --- Word timings (EXPLAINER-007) -----------------------------------------------------------


async def _evaluate_word_timings(
    session: AsyncSession, project: Project, options: RunOptions
) -> StepView:
    # Only an explainer with captions or callouts on needs the time of each word. For any other
    # project the step has one target that is already done, so a run reports it as skipped.
    if not word_timings.wanted(project):
        return StepView([Target(PROJECT_KEY, "", True)])
    state = await speech_synthesis.state(session, project)
    timings = await word_timings.state(session, project)
    targets: list[Target] = []
    for scene in state.scenes:
        scene_id = scene.scene.item["id"]
        for unit in scene.units:
            unit_id = unit.unit["id"]
            key = f"unit:{scene_id}/{unit_id}"
            label = f"Scene {scene.scene.item.get('index')}, line {unit_id}"
            audio = unit.audio
            if audio is None:
                targets.append(
                    Target(key, label, False, block="Speak this line first.", group=scene_id)
                )
                continue
            entry = timings.get(audio.id)
            status = entry.status if entry is not None else "none"
            done = status in ("timed", "estimated")
            active = status == "in_progress"
            targets.append(
                Target(
                    key,
                    label,
                    done,
                    active=active,
                    last_error=entry.error if entry is not None else None,
                    ref=(scene_id, unit_id, str(audio.id)),
                    group=scene_id,
                )
            )
    if not targets and state.blocked_reason is not None:
        return _blocked_project(state.blocked_reason)
    return StepView(targets)


async def _start_word_timings(
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
        lambda target: _ids_of(word_timings.start(session, project, int(target.ref[2]))),
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
                consent=_MANUAL_SHOT_PLAN if entry.needs_confirmation and not done else None,
                last_error=_failure(entry.job),
                ref=(entry.item["id"],),
                stale=entry.status == "out_of_date",
                group=entry.item["id"],
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
        lambda target: _ids_of(
            shot_plans.start_run(
                session,
                project,
                target.ref[0],
                confirm_replace_manual=_options_for(options, target).confirm_overwrite,
            )
        ),
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
                    group=scene_id,
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
                    consent=(
                        _MANUAL_SHOT_DEFINITION if shot.needs_confirmation and not done else None
                    ),
                    last_error=_failure(shot.job),
                    ref=(scene_id, shot_id),
                    stale=shot.status == "out_of_date",
                    group=scene_id,
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
            shot_definitions.start_shot(
                session,
                project,
                target.ref[0],
                target.ref[1],
                confirm_replace_manual=options.confirm_overwrite,
            )
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
                # A check was made for shots that have changed since.
                stale=entry.status == "not_checked" and entry.row is not None,
                group=scene_id,
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


# --- Shot references (a job per shot with the language model, else inline) and generation
# requests (inline) ----------------------------------------------------------------------------


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
                active=_active(shot.job),
                block=None if shot.status == "selected" else shot.blocked_reason,
                consent=(
                    _MANUAL_REFERENCES
                    if shot.needs_confirmation and shot.status != "selected"
                    else None
                ),
                last_error=_failure(shot.job),
                ref=(scene.item["id"], shot.shot["id"]),
                stale=shot.status == "out_of_date",
                group=scene.item["id"],
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
    if options.scope == SCOPE_OUT_OF_DATE:
        # Only the shots the run chose: "select all" would also choose for shots it leaves alone.
        async def select(target: Target) -> tuple[int, ...]:
            result = await shot_references.select_shot(
                session,
                project,
                target.ref[0],
                target.ref[1],
                confirm_replace_manual=options.confirm_overwrite,
            )
            return tuple(item.job_id for item in result.queued)

        return await _start_each(session, targets, deadline, select)
    # One call for all the targets. With the fixed rule the manifests are made in it; with the
    # language model it queues a job for each shot, and the ids go onto the targets so that
    # cancelling the run cancels them.
    try:
        result = await shot_references.select_all(
            session, project, confirm_replace_manual=options.confirm_overwrite
        )
    except ValueError as exc:
        await session.rollback()
        return [Started(target, error=str(exc)) for target in targets]
    except Exception as exc:
        _logger.exception("pipeline: choosing the references failed unexpectedly")
        await session.rollback()
        return [Started(target, error=f"Unexpected error: {exc}") for target in targets]
    skipped = {
        _shot_key(item.scene_id, item.shot_id): item.reason
        for item in result.skipped
        if item.shot_id is not None
    }
    queued = {_shot_key(item.scene_id, item.shot_id): item.job_id for item in result.queued}
    return [
        Started(
            target,
            job_ids=(queued[target.key],) if target.key in queued else (),
            error=None if target.key in queued else skipped.get(target.key),
        )
        for target in targets
    ]


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
                stale=shot.status == "out_of_date",
                group=scene.item["id"],
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
    if options.scope == SCOPE_OUT_OF_DATE:
        # Only the shots the run chose: "plan all" would also plan shots it leaves alone.
        async def plan(target: Target) -> tuple[int, ...]:
            await generation_requests.plan_shot(session, project, target.ref[0], target.ref[1])
            return ()

        return await _start_each(session, targets, deadline, plan)

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
                    consent=_MANUAL_PROMPT if shot.needs_confirmation and not done else None,
                    last_error=_failure(shot.job),
                    ref=(scene.item["id"], shot.shot["id"]),
                    stale=shot.status == "out_of_date",
                    group=scene.item["id"],
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
            shot_prompts.start_shot(
                session,
                project,
                target.ref[0],
                target.ref[1],
                confirm_replace_manual=options.confirm_overwrite,
            )
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
        return (
            f"No take passed its check: {text} Generate the shot from its own button to retry, "
            "or select one of its takes to use it anyway."
        )
    dialogue = newest.dialogue_result
    if isinstance(dialogue, dict) and dialogue.get("passed") is False:
        messages = [
            str(problem["message"])
            for problem in dialogue.get("problems", [])
            if isinstance(problem, dict) and problem.get("message")
        ]
        text = " ".join(messages) or "The speech in the clip does not match the dialogue."
        return (
            f"No take passed its dialogue check: {text} "
            "Generate the shot from its own button to retry, or select one of its takes to use "
            "it anyway."
        )
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
        # The shot before the one being looked at, for a shot that continues it (PHASE-032).
        previous: Target | None = None
        for shot in scene.shots:
            shot_id = shot.shot["id"]
            # A clip being made, or a clip whose speech is being compared with its dialogue.
            generating = any(
                take.state in ("generating", "checking_dialogue") for take in shot.takes
            )
            unchecked = shot.status == "unchecked"
            done = shot.status == "generated" and not generating
            active = generating or (unchecked and checking)
            # A shot that continues the one before it starts from that shot's take, so it waits
            # until that shot is done. A run starts it with a single press, which does not chain.
            waits_for: tuple[str, ...] = ()
            if shot.continues_from is not None and previous is not None and not previous.done:
                waits_for = (previous.key,)
            block: str | None = None
            if not done and not active:
                if shot.status == "failed":
                    block = _failed_shot_reason(shot)
                elif not unchecked and not shot.can_run and not waits_for:
                    block = shot.blocked_reason
            target = Target(
                _shot_key(scene_id, shot_id),
                _shot_label(scene.item, shot.shot),
                done,
                active=active,
                block=block,
                last_error=_failure(shot.job),
                waits_for=waits_for,
                ref=(scene_id, shot_id, _CHECK if unchecked else _GENERATE),
                stale=shot.status == "out_of_date",
                group=scene_id,
                # A failed or unchecked shot has clips already: it is not a missing one.
                existing=bool(shot.takes),
            )
            targets.append(target)
            previous = target
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
                stale=bool(state.renders) and state.renders[0].status == "out_of_date",
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
    "music_bible": Adapter(_evaluate_music_bible, _project_start(_call_music_bible)),
    "music_themes": Adapter(_evaluate_music_themes, _start_music_themes),
    "music_plan": Adapter(_evaluate_music_plan, _project_start(_call_music_plan)),
    "music_cues": Adapter(_evaluate_music_cues, _start_music_cues),
    "music_generation": Adapter(_evaluate_music_generation, _start_music_generation),
    "resolution": Adapter(_evaluate_resolution, _project_start(_call_resolution)),
    "scene_staging": Adapter(_evaluate_scene_staging, _start_scene_staging),
    "environment_views": Adapter(_evaluate_environment_views, _start_environment_views),
    "look_state_images": Adapter(_evaluate_look_state_images, _start_look_state_images),
    "speech_units": Adapter(_evaluate_speech_units, _start_speech_units),
    "speech_synthesis": Adapter(_evaluate_speech_synthesis, _start_speech_synthesis),
    "word_timings": Adapter(_evaluate_word_timings, _start_word_timings),
    "shot_plans": Adapter(_evaluate_shot_plans, _start_shot_plans),
    "shot_definitions": Adapter(_evaluate_shot_definitions, _start_shot_definitions),
    "shot_continuity": Adapter(_evaluate_shot_continuity, _start_shot_continuity),
    "references": Adapter(_evaluate_references, _start_references),
    "generation_requests": Adapter(_evaluate_generation_requests, _start_generation_requests),
    "prompts": Adapter(_evaluate_prompts, _start_prompts),
    "shot_generation": Adapter(_evaluate_shot_generation, _start_shot_generation),
    "music_placement": Adapter(_evaluate_music_placement, _project_start(_call_music_placement)),
    "render": Adapter(_evaluate_render, _project_start(_call_render)),
}

if set(ADAPTERS) != set(STEP_KEYS):  # a step without an adapter would never run
    raise ValueError("story_pipeline_targets: the adapters and the steps do not match")


# --- What must be allowed before the run starts ---------------------------------------------

# The steps that can replace something the user chose or wrote.
_CONSENT_STEPS: Final[tuple[str, ...]] = (
    "story_bible",
    "character_discovery",
    "environment_discovery",
    "scene_discovery",
    "relations",
    "character_definitions",
    "environment_definitions",
    "character_images",
    "voices",
    "scene_definitions",
    "events",
    "music_bible",
    "music_themes",
    "music_plan",
    "music_generation",
    "scene_staging",
    "speech_units",
    "shot_plans",
    "shot_definitions",
    "references",
    "prompts",
)


@dataclass(frozen=True)
class Confirmation:
    """One target the run would replace, that the user must allow first."""

    step_key: str
    step_label: str
    # What is replaced ("Mira", "Narrator"); empty for the project.
    target: str
    reason: str
    # The target exists and is out of date: the `out_of_date` scope asks about these only.
    stale: bool = False


async def confirmations(session: AsyncSession, project: Project) -> list[Confirmation]:
    """The targets that a run started now would replace, and that need the user's consent: the
    ones that are not up to date and hold what the user chose or wrote. Read-only.
    """
    found: list[Confirmation] = []
    options = RunOptions()
    for key in _CONSENT_STEPS:
        view = await ADAPTERS[key].evaluate(session, project, options)
        found.extend(
            Confirmation(key, STEP_LABELS[key], target.label, target.consent, target.stale)
            for target in view.targets
            if not target.done and target.consent is not None
        )
    return found


# --- What there is to review at a review point (PHASE-041) ----------------------------------


@dataclass(frozen=True)
class ReviewStep:
    """The targets of one step of a review point that the user can approve or reject."""

    step_key: str
    step_label: str
    # Only targets that are done: a target that is not done has nothing to look at yet.
    targets: list[Target]


async def review_targets(
    session: AsyncSession, project: Project, point_key: str
) -> list[ReviewStep]:
    """The done targets of every step of a review point, read through the adapters. Read-only.
    An unknown point has none.
    """
    point = review_points.POINTS_BY_KEY.get(point_key)
    if point is None:
        return []
    options = RunOptions()
    steps: list[ReviewStep] = []
    for key in point.steps:
        view = await ADAPTERS[key].evaluate(session, project, options)
        steps.append(ReviewStep(key, STEP_LABELS[key], [t for t in view.targets if t.done]))
    return steps
