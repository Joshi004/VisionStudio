"""A story project's music plan: starting the job that writes it, saving its versions, and
reading them back (MUSIC-008, `Music_implementation_phases.md` Section 4.2 and 4.3, levels 1
and 1b).

Every version is a new `music_plan` row and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). A version holds the condensed
timeline the plan was written against, the plan as first written (`draft`), the rounds of
critics and revisions, the final plan (`content`) and measured facts about it. `inputs` records
the exact upstream rows it was built from and the hash of the timeline, so whether it is out of
date is worked out when it is read and never stored.

Two ways make a version:

- `start_run` queues a job: the model writes the plan (level 1), and up to
  `music_plan_critic_rounds` rounds of four critics and a reviser refine it (level 1b).
- `save_manual` stores the owner's edit, checked the way the model's answer is.

**When a plan can be made (MD-3).** Every scene needs a shot plan that is current and whose
timeline has no blocking problem, so that every start and end is exact. The Music Bible must
exist. A plan is out of date when the Music Bible, a scene's shot plan, speech units, events or
definition were made again, the scenes changed, or the timing of the story is not what the plan
was written against.

**Sounds H3 makes (QM-16, option b).** The plan comes after the shot plans and beside the shot
definitions, so it cannot add a sound to a shot's prompt. A point sound given to H3 must name a
`sound_event` its shot already shows (`services/music_plan_writer`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, MusicBible, MusicPlan, Project
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    music_bible,
    music_plan_writer,
    music_timeline,
    provenance,
    scene_definitions,
    scene_events,
    shot_plans,
    speech_units,
)

JOB_TYPE: Final = "write_music_plan"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"

MUSIC_BIBLE_KIND: Final = "music_bible"
SHOT_PLAN_KIND: Final = "shot_plan"
SPEECH_UNITS_KIND: Final = "speech_units"
SCENE_EVENTS_KIND: Final = "scene_events"
SCENE_DEFINITION_KIND: Final = "scene_definition"
# What is recorded per scene, with the words used when it changes.
_SCENE_KINDS: Final = (
    (SHOT_PLAN_KIND, "shots"),
    (SPEECH_UNITS_KIND, "speech"),
    (SCENE_EVENTS_KIND, "events"),
    (SCENE_DEFINITION_KIND, "definition"),
)

MUSIC_OFF_MESSAGE: Final = "Music is switched off for this project. Switch it on in the settings."
REPLACE_MESSAGE: Final = (
    "The newest music plan was written by you. Running the model adds a new version from the "
    "model, so it has to be confirmed."
)
BUSY_MESSAGE: Final = "The music plan is being written. Wait for it to finish first."
# The "lens" under which the cues' objections are shown to the reviser and kept in `rounds`
# (MUSIC-009). `inputs.pushback` of a version made from them records the round.
PUSHBACK_LENS: Final = "cue_detail"
NO_BIBLE_MESSAGE: Final = "Write the Music Bible first: the plan follows it."


class MusicPlanError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- Loading what the plan is made from ----------------------------------------------------


@dataclass(frozen=True)
class _Scene:
    """One scene's upstream rows, in story order."""

    item: dict[str, Any]
    shot_plan: shot_plans.SceneEntry
    speech: speech_units.SceneEntry | None
    events: scene_events.SceneEntry | None
    definition: scene_definitions.SceneEntry | None


@dataclass(frozen=True)
class _Loaded:
    bible: MusicBible | None
    scenes: list[_Scene]
    names: dict[str, str]
    blocked_reason: str | None
    # The condensed timeline, when every scene is ready (`blocked_reason` is then None).
    timeline: dict[str, Any] | None

    @property
    def scene_ids(self) -> list[str]:
        return [scene.item["id"] for scene in self.scenes]

    @property
    def theme_ids(self) -> set[str]:
        if self.bible is None:
            return set()
        return {theme["id"] for theme in self.bible.content["themes"]}


def _scene_blocked_reason(scene: _Scene) -> str | None:
    title = scene.item["title"]
    if not scene.shot_plan.generation_ready:
        why = scene.shot_plan.generation_blocked_reason or "its shot plan cannot be used"
        return f"Plan the shots of the scene '{title}' first: {why}"
    if scene.speech is None or scene.speech.row is None:
        return f"The speech of the scene '{title}' is not planned."
    if scene.events is None or scene.events.row is None:
        return f"The events of the scene '{title}' are missing."
    if scene.definition is None or scene.definition.row is None:
        return f"The scene '{title}' has no definition."
    return None


def _scene_input(scene: _Scene, names: dict[str, str]) -> music_timeline.SceneInput:
    plan = scene.shot_plan
    assert plan.timeline is not None and plan.story_start_s is not None and plan.content
    assert scene.speech is not None and scene.speech.content is not None
    assert scene.events is not None and scene.events.content is not None
    assert scene.definition is not None and scene.definition.definition is not None
    definition = scene.definition.definition
    return music_timeline.SceneInput(
        scene_id=scene.item["id"],
        title=scene.item["title"],
        story_start_s=plan.story_start_s,
        timeline=plan.timeline,
        shots=plan.content["shots"],
        units=scene.speech.content["units"],
        events=scene.events.content["events"],
        mood=definition["mood"],
        characters=list(definition["characters"]),
        names=names,
    )


async def _load(session: AsyncSession, project: Project) -> _Loaded:
    bible = await music_bible.latest(session, project.id)
    plans = await shot_plans.state(session, project)
    speech = await speech_units.state(session, project)
    events = await scene_events.state(session, project)
    definitions = await scene_definitions.state(session, project)
    speech_by = {entry.item["id"]: entry for entry in speech.entries}
    events_by = {entry.item["id"]: entry for entry in events.entries}
    definitions_by = {entry.item["id"]: entry for entry in definitions.entries}
    scenes = [
        _Scene(
            item=entry.item,
            shot_plan=entry,
            speech=speech_by.get(entry.item["id"]),
            events=events_by.get(entry.item["id"]),
            definition=definitions_by.get(entry.item["id"]),
        )
        for entry in plans.entries
    ]
    names = {item["id"]: item["name"] for item in speech.characters}

    blocked: str | None = None
    if bible is None:
        blocked = NO_BIBLE_MESSAGE
    elif not scenes:
        blocked = plans.blocked_reason or "Find the scenes first: the plan covers every scene."
    else:
        for scene in scenes:
            blocked = _scene_blocked_reason(scene)
            if blocked is not None:
                break

    timeline = None
    if blocked is None:
        timeline = music_timeline.build([_scene_input(scene, names) for scene in scenes])
    return _Loaded(
        bible=bible, scenes=scenes, names=names, blocked_reason=blocked, timeline=timeline
    )


def _inputs(loaded: _Loaded) -> dict[str, Any]:
    """What a version is built from, in the artifact shape of D-3. A manual save records
    exactly what a job would. The caller has checked that nothing is blocked.
    """
    assert loaded.bible is not None and loaded.timeline is not None
    artifacts: list[dict[str, Any]] = [
        {"kind": MUSIC_BIBLE_KIND, "id": loaded.bible.id, "version": loaded.bible.version}
    ]
    for scene in loaded.scenes:
        rows = (
            (SHOT_PLAN_KIND, scene.shot_plan.row),
            (SPEECH_UNITS_KIND, scene.speech.row if scene.speech else None),
            (SCENE_EVENTS_KIND, scene.events.row if scene.events else None),
            (SCENE_DEFINITION_KIND, scene.definition.row if scene.definition else None),
        )
        for kind, row in rows:
            assert row is not None
            artifacts.append(
                {"kind": kind, "id": row.id, "version": row.version, "scene_id": scene.item["id"]}
            )
    return {"artifacts": artifacts, "timeline_sha256": music_timeline.sha256(loaded.timeline)}


async def critic_rounds(session: AsyncSession) -> int:
    """The number of review rounds that applies now, read at the moment of use."""
    return await settings_service.get_int(session, settings_service.MUSIC_PLAN_CRITIC_ROUNDS_KEY)


async def _job_input(session: AsyncSession, loaded: _Loaded) -> dict[str, Any]:
    """What a job is sent: a copy of everything it needs, taken when the button was pressed."""
    assert loaded.bible is not None and loaded.timeline is not None
    return {
        "bible": loaded.bible.content,
        "timeline": loaded.timeline,
        "theme_ids": sorted(loaded.theme_ids),
        "critic_rounds": await critic_rounds(session),
        "saved_inputs": _inputs(loaded),
    }


# --- Starting runs -------------------------------------------------------------------------


def needs_confirmation(row: MusicPlan | None) -> bool:
    """Whether running the model again would replace what the owner wrote."""
    return row is not None and row.source == SOURCE_MANUAL


async def _refuse_when_unable(session: AsyncSession, project: Project) -> _Loaded:
    if not project.music_enabled:
        raise MusicPlanError(MUSIC_OFF_MESSAGE)
    loaded = await _load(session, project)
    if loaded.blocked_reason is not None:
        raise MusicPlanError(loaded.blocked_reason)
    return loaded


async def start_run(
    session: AsyncSession, project: Project, *, confirm_replace_manual: bool = False
) -> Job:
    """Queues the job that writes the music plan from the story as it stands now, and commits.
    If a job of this kind is already waiting or running for the project, that job is returned
    and no new one is made (two quick clicks make one paid run).

    When the newest version was written by the owner, the run replaces it only when
    `confirm_replace_manual` is true. Raises MusicPlanError.
    """
    loaded = await _refuse_when_unable(session, project)
    if needs_confirmation(await latest(session, project.id)) and not confirm_replace_manual:
        raise MusicPlanError(REPLACE_MESSAGE)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input=await _job_input(session, loaded),
    )
    return job


async def start_pushback_revision(
    session: AsyncSession,
    project: Project,
    *,
    plan_id: int,
    notes: list[dict[str, Any]],
    pushback_round: int,
) -> Job:
    """Queues the job that revises the newest plan from the objections of its cues, and commits
    (MUSIC-009). `plan_id` must be the newest version, which must be the model's own and not out
    of date. The new version records the round in `inputs.pushback`. Raises MusicPlanError.
    """
    loaded = await _refuse_when_unable(session, project)
    newest = await latest(session, project.id)
    if newest is None or newest.id != plan_id:
        raise MusicPlanError("The music plan has changed. Detail the cues again first.")
    if newest.source != SOURCE_AI:
        raise MusicPlanError("The newest music plan was written by you, so it is not revised.")
    if not notes:
        raise MusicPlanError("There is nothing to revise the plan from.")
    job_input = await _job_input(session, loaded)
    job_input["saved_inputs"] = {
        **job_input["saved_inputs"],
        "pushback": {
            "round": pushback_round,
            "from": {"id": newest.id, "version": newest.version},
            "notes": notes,
        },
    }
    job_input.update(mode="pushback", previous_plan=newest.content, notes=notes)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input=job_input,
    )
    return job


# --- Versions ------------------------------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> MusicPlan | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(MusicPlan)
        .where(MusicPlan.project_id == project_id)
        .order_by(MusicPlan.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def list_versions(session: AsyncSession, project_id: int) -> list[MusicPlan]:
    """Every version of the project, newest first."""
    statement = (
        select(MusicPlan)
        .where(MusicPlan.project_id == project_id)
        .order_by(MusicPlan.version.desc())
    )
    return list((await session.execute(statement)).scalars())


async def get_version(session: AsyncSession, project_id: int, version: int) -> MusicPlan | None:
    """One version of the project, or None when there is no such version."""
    statement = select(MusicPlan).where(
        MusicPlan.project_id == project_id, MusicPlan.version == version
    )
    return (await session.execute(statement)).scalars().first()


async def _add_version(
    session: AsyncSession,
    project_id: int,
    *,
    source: str,
    job_id: int | None,
    inputs: dict[str, Any],
    timeline: dict[str, Any],
    draft: dict[str, Any],
    rounds: list[dict[str, Any]],
    content: dict[str, Any],
) -> MusicPlan:
    statement = select(func.max(MusicPlan.version)).where(MusicPlan.project_id == project_id)
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = MusicPlan(
        project_id=project_id,
        version=(highest or 0) + 1,
        source=source,
        job_id=job_id,
        inputs=inputs,
        timeline=timeline,
        draft=draft,
        rounds=rounds,
        content=content,
        facts=music_plan_writer.facts(content, float(timeline["total_s"])),
    )
    session.add(row)
    await session.flush()
    return row


async def save_version(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    inputs: dict[str, Any],
    timeline: dict[str, Any],
    draft: dict[str, Any],
    rounds: list[dict[str, Any]],
    content: dict[str, Any],
) -> MusicPlan:
    """Adds the next version, made by the model (`source` is `ai`). Flushes but does not
    commit: the job commits it together with finishing itself, so a job is never "succeeded"
    without its result.
    """
    return await _add_version(
        session,
        project_id,
        source=SOURCE_AI,
        job_id=job_id,
        inputs=inputs,
        timeline=timeline,
        draft=draft,
        rounds=rounds,
        content=content,
    )


async def save_manual(
    session: AsyncSession, project: Project, content: dict[str, Any]
) -> MusicPlan:
    """Stores the owner's edited plan as the next version (`source` is `manual`), and commits.

    The plan is checked against the timeline as it is now, the way the model's answer is
    (`music_plan_writer.check_plan`): every anchor must exist, cues are in order, overlaps are
    only at crossfades, every neighbouring pair has one boundary and so on. So the new version
    is current. It needs what a run needs, and is refused while a job is writing the plan.
    Raises MusicPlanError.
    """
    newest = await latest(session, project.id)
    if newest is None:
        raise MusicPlanError("There is no music plan to edit yet.")
    active = await store.latest_job(session, project.id, JOB_TYPE)
    if active is not None and active.status in store.ACTIVE_STATUSES:
        raise MusicPlanError(BUSY_MESSAGE)
    loaded = await _refuse_when_unable(session, project)
    assert loaded.timeline is not None
    try:
        checked = music_plan_writer.check_plan(
            content,
            index=music_timeline.index_of(loaded.timeline),
            theme_ids=loaded.theme_ids,
        )
    except ValueError as exc:
        raise MusicPlanError(str(exc)) from exc
    row = await _add_version(
        session,
        project.id,
        source=SOURCE_MANUAL,
        job_id=None,
        inputs={**_inputs(loaded), "edited_from": {"id": newest.id, "version": newest.version}},
        timeline=loaded.timeline,
        draft=newest.draft,
        rounds=newest.rounds,
        content=checked,
    )
    await session.commit()
    return row


# --- Reading the state ---------------------------------------------------------------------


def _recorded(
    inputs: dict[str, Any], kind: str, scene_id: str | None = None
) -> dict[str, Any] | None:
    """The artifact of this kind (and scene) that `inputs` says the version was built from."""
    for artifact in inputs.get("artifacts") or []:
        if (
            isinstance(artifact, dict)
            and artifact.get("kind") == kind
            and artifact.get("scene_id") == scene_id
        ):
            return artifact
    return None


def _out_of_date_reasons(row: MusicPlan, loaded: _Loaded) -> list[str]:
    """Why this version is no longer current, one sentence each. Worked out on every read."""
    inputs = row.inputs if isinstance(row.inputs, dict) else {}
    reasons: list[str] = []

    if not provenance.same_row(_recorded(inputs, MUSIC_BIBLE_KIND), loaded.bible):
        reasons.append("The Music Bible has been written again since this plan was made.")

    recorded_scenes = {
        artifact["scene_id"]
        for artifact in inputs.get("artifacts") or []
        if isinstance(artifact, dict) and artifact.get("kind") == SHOT_PLAN_KIND
    }
    titles = {scene.item["id"]: scene.item["title"] for scene in loaded.scenes}
    if recorded_scenes != set(titles):
        reasons.append("The list of scenes has changed since this plan was made.")

    for scene in loaded.scenes:
        scene_id = scene.item["id"]
        if scene_id not in recorded_scenes:
            continue  # a new scene: the list of scenes has already been reported
        current = {
            SHOT_PLAN_KIND: scene.shot_plan.row,
            SPEECH_UNITS_KIND: scene.speech.row if scene.speech else None,
            SCENE_EVENTS_KIND: scene.events.row if scene.events else None,
            SCENE_DEFINITION_KIND: scene.definition.row if scene.definition else None,
        }
        for kind, what in _SCENE_KINDS:
            if not provenance.same_row(_recorded(inputs, kind, scene_id), current[kind]):
                reasons.append(
                    f"The {what} of the scene '{titles[scene_id]}' changed since this plan was "
                    "made."
                )

    if not reasons and loaded.timeline is not None:
        if inputs.get("timeline_sha256") != music_timeline.sha256(loaded.timeline):
            reasons.append("The timing of the story has changed since this plan was made.")
    return reasons


@dataclass(frozen=True)
class MusicPlanState:
    """What the story workspace shows."""

    latest: MusicPlan | None
    versions: list[MusicPlan]
    # The newest job, whatever its status.
    job: Job | None
    out_of_date: bool
    reasons: list[str]
    needs_confirmation: bool
    # Why no music plan can be written yet, or None.
    blocked_reason: str | None
    music_enabled: bool
    critic_rounds: int
    # The timeline as it is now (what an edit is checked against), or None when blocked.
    timeline: dict[str, Any] | None
    # The themes of the newest Music Bible, to offer in the editor.
    themes: list[dict[str, str]]


@memoized_state
async def state(session: AsyncSession, project: Project) -> MusicPlanState:
    """The project's music plan with where it stands. Worked out on every read; nothing here
    is stored.
    """
    loaded = await _load(session, project)
    newest = await latest(session, project.id)
    reasons = _out_of_date_reasons(newest, loaded) if newest is not None else []
    themes = (
        [{"id": theme["id"], "name": theme["name"]} for theme in loaded.bible.content["themes"]]
        if loaded.bible is not None
        else []
    )
    return MusicPlanState(
        latest=newest,
        versions=await list_versions(session, project.id),
        job=await store.latest_job(session, project.id, JOB_TYPE),
        out_of_date=bool(reasons),
        reasons=reasons,
        needs_confirmation=needs_confirmation(newest),
        blocked_reason=loaded.blocked_reason,
        music_enabled=project.music_enabled,
        critic_rounds=await critic_rounds(session),
        timeline=loaded.timeline,
        themes=themes,
    )
