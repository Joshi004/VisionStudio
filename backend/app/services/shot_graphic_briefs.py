"""The briefs of the graphic shots of a continuous explainer: starting the job that writes one,
saving its versions, and reading where each stands (EXG-004,
`Explainer_graphics_implementation_phases.md` §3.2 and §3.4).

Every version is a new `shot_graphic_brief` row for one shot and a stored row is never changed
(the artifact provenance convention, DATABASE_STRUCTURE.md Section 2.1). `content` is the brief
(`services/shot_graphic_brief_writer`, with no theme). `inputs` records what it was built from, so
whether it is out of date is worked out when it is read and never stored:

- `artifacts`: the shot plan, the Story Bible and the voice take (with the timing of its words);
- `skeleton_sha256`: a hash of the shot's own fields in the plan;
- `shot` and `words`: the shot's first and last word, its times, and its words timed from the
  shot's start (the beats' times are worked out from them);
- `context`: the first and last word of the context, its text and its hash;
- `feedback`, when the owner wrote a note.

**When a brief can be written.** The project is a continuous explainer with graphics on, its Story
Bible exists, the scene's newest shot plan is current and usable, the scene's take is ready and
timed from what was heard, and the shot is a `graphic` shot of that plan.

**Out of date.** A brief is out of date when its shot changed in the plan (the hash), when the
sentences around it changed (the context hash), or when the take was made or timed again. Planning
a scene again therefore makes out of date only the brief of a graphic shot that really changed.
Nothing here is stored but the versions; there is no manual edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project, ShotGraphicBrief
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    cut_planning_writer,
    graphic_theme,
    shot_graphic_brief_writer,
    shot_plans,
    story_bible,
    take_timings,
    user_feedback,
)

JOB_TYPE: Final = "write_shot_graphic_brief"
DEDUPE_KEY: Final = "shot_key"
SOURCE_AI: Final = "ai"

STORY_BIBLE_KIND: Final = "story_bible"
SHOT_PLAN_KIND: Final = "shot_plan"
SPEECH_TAKE_KIND: Final = "speech_take"

_JOB_LOOKBACK: Final = 2000

# `none`: no brief was made for this shot. `writing`: a job is waiting or running. `ready`: made,
# and nothing it was built from has changed. `failed`: no brief, and the newest job did not make
# one. `out_of_date`: made, and something it was built from has changed (see the reasons).
Status = str

NO_BIBLE_MESSAGE: Final = (
    "Write the Story Bible first: the graphic briefs follow its title and tone."
)
NO_PLAN_MESSAGE: Final = "Plan this scene's shots first: the graphic briefs are written from them."
NOT_GRAPHIC_MESSAGE: Final = "This shot is not a graphic shot."
NO_BRIEF_MESSAGE: Final = "This shot has no brief yet, so there is nothing to comment on."
BEING_WRITTEN_MESSAGE: Final = "The brief of this shot is already being written."


class ShotGraphicBriefError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


def is_graphic_shot(shot: dict[str, Any]) -> bool:
    """Whether a shot of a plan is a graphic shot (EXG-003)."""
    return shot.get("type") == cut_planning_writer.GRAPHIC


def shot_key(scene_id: str, shot_id: str) -> str:
    return f"{scene_id}/{shot_id}"


# --- What a brief is written from ------------------------------------------------------------


@dataclass(frozen=True)
class _Loaded:
    """Everything a run or a read of the state needs, loaded once."""

    project: Project
    bible: Any
    plans: shot_plans.ShotPlansState
    clocks: dict[str, take_timings.TakeClock]
    plan_by_scene: dict[str, shot_plans.SceneEntry]


async def _load(session: AsyncSession, project: Project) -> _Loaded:
    plans = await shot_plans.state(session, project)
    return _Loaded(
        project=project,
        bible=await story_bible.latest(session, project.id),
        plans=plans,
        clocks=await take_timings.scene_clocks(session, project),
        plan_by_scene={entry.item["id"]: entry for entry in plans.entries},
    )


@dataclass(frozen=True)
class _Material:
    """What the brief of one shot is written from, worked out from the plan and the take."""

    shot: dict[str, Any]
    words: list[dict[str, Any]]
    context: shot_graphic_brief_writer.Context
    skeleton_sha256: str
    context_sha256: str
    take_id: int
    timing_id: int


def _material(shot: dict[str, Any], clock: take_timings.TakeClock) -> _Material | None:
    """The words, the context and the hashes of one graphic shot of a plan, or None when the
    shot's words are not in the take (the plan was made on another take). `clock` must be ready
    (no `blocked_reason`).
    """
    assert clock.audio is not None and clock.timing is not None
    if not 1 <= int(shot["start_word"]) <= int(shot["last_word"]) <= len(clock.words):
        return None
    spans = [
        {"unit_id": span.unit_id, "first_word": span.first_word, "last_word": span.last_word}
        for span in clock.spans
    ]
    context = shot_graphic_brief_writer.context_of(
        clock.words, spans, int(shot["start_word"]), int(shot["last_word"])
    )
    return _Material(
        shot=shot,
        words=shot_graphic_brief_writer.timed_words(
            clock.words, int(shot["start_word"]), int(shot["last_word"]), float(shot["start_s"])
        ),
        context=context,
        skeleton_sha256=shot_graphic_brief_writer.skeleton_sha256(shot),
        context_sha256=shot_graphic_brief_writer.context_sha256(context.text),
        take_id=clock.audio.id,
        timing_id=clock.timing.id,
    )


def _refusal(loaded: _Loaded, scene_id: str) -> str | None:
    """Why the briefs of this scene's graphic shots cannot be written now, or None."""
    if not graphic_theme.wanted(loaded.project):
        return graphic_theme.OFF_MESSAGE
    if loaded.bible is None:
        return NO_BIBLE_MESSAGE
    plan = loaded.plan_by_scene.get(scene_id)
    if plan is None:
        return f"There is no scene '{scene_id}' in the newest list of scenes."
    if plan.row is None or not cut_planning_writer.is_cut_plan(plan.row.content):
        return NO_PLAN_MESSAGE
    if not plan.generation_ready:
        return (
            plan.generation_blocked_reason or "The shots of this scene are not ready."
        ) + " Plan the shots again first."
    clock = loaded.clocks.get(scene_id)
    if clock is None:
        return take_timings.NOT_MADE_REASON
    if clock.blocked_reason is not None:
        return clock.blocked_reason
    return None


def _find_shot(loaded: _Loaded, scene_id: str, shot_id: str) -> dict[str, Any]:
    plan = loaded.plan_by_scene.get(scene_id)
    if plan is None:
        raise ShotGraphicBriefError(f"There is no scene '{scene_id}' in the newest list of scenes.")
    shots = plan.content["shots"] if plan.content is not None else []
    for shot in shots:
        if shot["id"] == shot_id:
            if not is_graphic_shot(shot):
                raise ShotGraphicBriefError(NOT_GRAPHIC_MESSAGE)
            return shot
    raise ShotGraphicBriefError(f"There is no shot '{shot_id}' in the scene '{scene_id}'.")


# --- Versions --------------------------------------------------------------------------------


async def newest_row(
    session: AsyncSession, project_id: int, scene_id: str, shot_id: str
) -> ShotGraphicBrief | None:
    """The newest brief of one shot, or None when it has none."""
    statement = (
        select(ShotGraphicBrief)
        .where(
            ShotGraphicBrief.project_id == project_id,
            ShotGraphicBrief.scene_id == scene_id,
            ShotGraphicBrief.shot_id == shot_id,
        )
        .order_by(ShotGraphicBrief.version.desc(), ShotGraphicBrief.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def save_version(
    session: AsyncSession,
    *,
    project_id: int,
    scene_id: str,
    shot_id: str,
    shot_plan_id: int,
    job_id: int,
    inputs: dict[str, Any],
    content: dict[str, Any],
) -> ShotGraphicBrief:
    """Adds the next version of the shot's brief, made by the model (`source` is `ai`). Flushes
    but does not commit: the job commits it together with finishing itself, so a job is never
    "succeeded" without its result.
    """
    statement = select(func.max(ShotGraphicBrief.version)).where(
        ShotGraphicBrief.project_id == project_id,
        ShotGraphicBrief.scene_id == scene_id,
        ShotGraphicBrief.shot_id == shot_id,
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = ShotGraphicBrief(
        project_id=project_id,
        scene_id=scene_id,
        shot_id=shot_id,
        shot_plan_id=shot_plan_id,
        version=(highest or 0) + 1,
        source=SOURCE_AI,
        job_id=job_id,
        inputs=inputs,
        content=content,
    )
    session.add(row)
    await session.flush()
    return row


# --- Starting a run --------------------------------------------------------------------------


def _feedback_on(text: str, newest: ShotGraphicBrief | None) -> user_feedback.Feedback:
    """The user's note on the newest brief of a shot, with that brief as what it is about. Raises
    ShotGraphicBriefError when the note is not usable or there is no brief to talk about.
    """
    try:
        note = user_feedback.clean(text)
    except ValueError as exc:
        raise ShotGraphicBriefError(str(exc)) from exc
    if newest is None:
        raise ShotGraphicBriefError(NO_BRIEF_MESSAGE)
    return user_feedback.Feedback(
        text=note,
        previous=shot_graphic_brief_writer.previous_brief(newest.content),
        base_version=newest.version,
    )


def _saved_inputs(
    loaded: _Loaded,
    scene_id: str,
    plan: shot_plans.SceneEntry,
    material: _Material,
    feedback: user_feedback.Feedback | None,
) -> dict[str, Any]:
    """What a version is built from, in the artifact shape of D-3."""
    assert plan.row is not None and loaded.bible is not None
    shot = material.shot
    inputs: dict[str, Any] = {
        "artifacts": [
            {"kind": SHOT_PLAN_KIND, "id": plan.row.id, "version": plan.row.version},
            {"kind": STORY_BIBLE_KIND, "id": loaded.bible.id, "version": loaded.bible.version},
            {
                "kind": SPEECH_TAKE_KIND,
                "id": material.take_id,
                "timing_id": material.timing_id,
            },
        ],
        "skeleton_sha256": material.skeleton_sha256,
        "shot": {
            "start_word": shot["start_word"],
            "last_word": shot["last_word"],
            "start_s": shot["start_s"],
            "end_s": shot["end_s"],
        },
        "words": material.words,
        "context": {
            "first_word": material.context.first_word,
            "last_word": material.context.last_word,
            "text": material.context.text,
            "sha256": material.context_sha256,
        },
    }
    if feedback is not None:
        inputs["feedback"] = feedback.for_version()
    return inputs


async def _queue(
    session: AsyncSession,
    loaded: _Loaded,
    scene_id: str,
    shot_id: str,
    feedback: user_feedback.Feedback | None = None,
) -> tuple[Job, bool]:
    """Queues the job for this shot and returns `(job, created)`; the job already waiting or
    running is returned, with `created` False. Raises ShotGraphicBriefError.
    """
    refusal = _refusal(loaded, scene_id)
    if refusal is not None:
        raise ShotGraphicBriefError(refusal)
    shot = _find_shot(loaded, scene_id, shot_id)
    plan = loaded.plan_by_scene[scene_id]
    material = _material(shot, loaded.clocks[scene_id])
    if material is None:
        raise ShotGraphicBriefError(
            "The words of this shot are not in the scene's take. Plan the shots again first."
        )
    assert plan.row is not None
    job_input: dict[str, Any] = {
        DEDUPE_KEY: shot_key(scene_id, shot_id),
        "scene_id": scene_id,
        "shot_id": shot_id,
        "shot_plan_id": plan.row.id,
        "shot_words": material.context.shot,
        "before": material.context.before,
        "after": material.context.after,
        "description": shot["description"],
        "shot_seconds": round(float(shot["end_s"]) - float(shot["start_s"]), 3),
        "orientation": loaded.project.orientation,
        "bible": shot_graphic_brief_writer.bible_for_model(loaded.bible.content),
        "saved_inputs": _saved_inputs(loaded, scene_id, plan, material, feedback),
    }
    if feedback is not None:
        job_input["feedback"] = feedback.for_job()
    return await store.create_job(
        session,
        project_id=loaded.project.id,
        type=JOB_TYPE,
        provider="llm",
        input=job_input,
        dedupe_key=DEDUPE_KEY,
    )


async def start_shot(
    session: AsyncSession,
    project: Project,
    scene_id: str,
    shot_id: str,
    *,
    feedback: str | None = None,
) -> Job:
    """Queues the job that writes the brief of one graphic shot, from a copy of what it is made
    from, and commits. If that shot already has a job waiting or running, that job is returned and
    no new one is made; a note is never dropped silently, so it is refused in that case.

    `feedback` is the owner's note on the newest brief: the model writes the brief again with the
    note and that brief in its request. Raises ShotGraphicBriefError when it cannot be written.
    """
    loaded = await _load(session, project)
    note = None
    if feedback is not None:
        note = _feedback_on(feedback, await newest_row(session, project.id, scene_id, shot_id))
    job, created = await _queue(session, loaded, scene_id, shot_id, note)
    if note is not None and not created:
        raise ShotGraphicBriefError(BEING_WRITTEN_MESSAGE)
    return job


# --- Reading the state -----------------------------------------------------------------------


@dataclass(frozen=True)
class ShotEntry:
    """One graphic shot of a scene's newest plan and where its brief stands."""

    # The shot as the plan stores it.
    shot: dict[str, Any]
    status: Status
    # Why a written brief is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The context of the shot as the take reads now, or None when the take is not ready.
    context: shot_graphic_brief_writer.Context | None
    # The newest brief of the shot, when it has one.
    row: ShotGraphicBrief | None
    # The second each beat of the newest brief starts, from the start of the shot, by beat id.
    beat_times: dict[str, float]
    # The newest job of this shot, whatever its status.
    job: Job | None
    # Why the newest job did not make a brief newer than the newest one, or None.
    last_error: str | None
    # Whether the Write button may be pressed, and the reason when it may not.
    can_run: bool
    blocked_reason: str | None


@dataclass(frozen=True)
class SceneEntry:
    """One scene of the newest list of scenes and its graphic shots."""

    item: dict[str, Any]
    shots: list[ShotEntry]
    # Why this scene's briefs cannot be written, or None.
    blocked_reason: str | None


@dataclass(frozen=True)
class ShotGraphicBriefsState:
    """What the board panel shows."""

    entries: list[SceneEntry]
    # Why no brief can be written yet (or at all for this project), or None.
    blocked_reason: str | None
    # Whether the project has graphic briefs at all (a continuous explainer with graphics on).
    wanted: bool


def _recorded(inputs: Any, kind: str) -> dict[str, Any] | None:
    if not isinstance(inputs, dict):
        return None
    for artifact in inputs.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            return artifact
    return None


def _out_of_date_reasons(row: ShotGraphicBrief, material: _Material | None) -> list[str]:
    """Why a brief is no longer current, one sentence each. `material` is what the shot is made
    of now, or None when the take cannot be read now (its own stage says so).
    """
    if material is None or not isinstance(row.inputs, dict):
        return []
    inputs = row.inputs
    reasons: list[str] = []
    if inputs.get("skeleton_sha256") != material.skeleton_sha256:
        reasons.append("The shot was planned again, and its words, times or description changed.")
    context = inputs.get("context")
    recorded_context = context.get("sha256") if isinstance(context, dict) else None
    if recorded_context != material.context_sha256:
        reasons.append("The sentences around the shot changed.")
    take = _recorded(inputs, SPEECH_TAKE_KIND)
    if take is None:
        reasons.append("This brief did not record the voice take it was written on.")
    elif take.get("id") != material.take_id:
        reasons.append("The voice take of the scene was made again since this brief was written.")
    elif take.get("timing_id") != material.timing_id:
        reasons.append("The words of the voice take were timed again since this brief was written.")
    return reasons


def _beat_times(row: ShotGraphicBrief | None) -> dict[str, float]:
    """The second each beat of a brief starts, from the start of its shot, from the words it was
    written on. Empty when there is no brief or its words cannot be read.
    """
    if row is None or not isinstance(row.inputs, dict):
        return {}
    words = row.inputs.get("words")
    if not isinstance(words, list) or not words:
        return {}
    try:
        return shot_graphic_brief_writer.beat_times(row.content, words)
    except (ValueError, KeyError, TypeError):
        return {}


async def _newest_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest brief job of each shot of the project, by its `scene/shot` key."""
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


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, ShotGraphicBrief]:
    """The newest brief of each shot of the project, by its `scene/shot` key."""
    statement = (
        select(ShotGraphicBrief)
        .where(ShotGraphicBrief.project_id == project_id)
        .order_by(ShotGraphicBrief.version.desc(), ShotGraphicBrief.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, ShotGraphicBrief] = {}
    for row in (await session.execute(statement)).scalars():
        key = shot_key(row.scene_id, row.shot_id)
        if key not in newest:
            newest[key] = row
    return newest


def _failure(job: Job | None, row: ShotGraphicBrief | None) -> str | None:
    """Why the newest job made no brief, when it is newer than the newest brief."""
    if job is None or job.status not in ("failed", "cancelled"):
        return None
    if row is not None and row.job_id is not None and row.job_id > job.id:
        return None
    return job.error or ("the job was cancelled" if job.status == "cancelled" else "the job failed")


async def _build(
    session: AsyncSession, project: Project, loaded: _Loaded
) -> ShotGraphicBriefsState:
    wanted = graphic_theme.wanted(project)
    if not wanted:
        return ShotGraphicBriefsState(
            entries=[], blocked_reason=graphic_theme.OFF_MESSAGE, wanted=False
        )
    jobs = await _newest_jobs(session, project.id)
    rows = await _newest_rows(session, project.id)

    entries: list[SceneEntry] = []
    for plan in loaded.plans.entries:
        scene_id = plan.item["id"]
        refusal = _refusal(loaded, scene_id)
        clock = loaded.clocks.get(scene_id)
        shots: list[ShotEntry] = []
        for shot in plan.content["shots"] if plan.content is not None else []:
            if not is_graphic_shot(shot):
                continue
            key = shot_key(scene_id, shot["id"])
            row = rows.get(key)
            job = jobs.get(key)
            active = job is not None and job.status in store.ACTIVE_STATUSES
            material = (
                _material(shot, clock)
                if clock is not None and clock.blocked_reason is None
                else None
            )
            reasons = _out_of_date_reasons(row, material) if row is not None else []
            failure = _failure(job, row)
            status: Status = "none"
            if active:
                status = "writing"
            elif row is not None:
                status = "out_of_date" if reasons else "ready"
            elif failure is not None:
                status = "failed"
            blocked = refusal
            if blocked is None and active:
                blocked = BEING_WRITTEN_MESSAGE
            shots.append(
                ShotEntry(
                    shot=shot,
                    status=status,
                    reasons=reasons,
                    context=material.context if material is not None else None,
                    row=row,
                    beat_times=_beat_times(row),
                    job=job,
                    last_error=failure,
                    can_run=blocked is None,
                    blocked_reason=blocked,
                )
            )
        entries.append(SceneEntry(item=plan.item, shots=shots, blocked_reason=refusal))
    return ShotGraphicBriefsState(entries=entries, blocked_reason=None, wanted=True)


@memoized_state
async def state(session: AsyncSession, project: Project) -> ShotGraphicBriefsState:
    """The graphic shots of the newest plans with where each brief stands. Worked out on every
    read; nothing here is stored.
    """
    return await _build(session, project, await _load(session, project))
