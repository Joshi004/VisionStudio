"""The detail and the prompts of a story project's music cues: starting the jobs that write them,
saving their versions, and reading them back (MUSIC-009, `Music_implementation_phases.md`
Section 4.2 and 4.3, levels 2 and 3, and the audit).

For every cue of the newest music plan that has something to generate, one `write_music_cue` job
runs (side by side with the others): level 2 writes the cue's exact anchors, the broad order of
moods, hit requests and mix notes, and level 3 writes the prompt wordings for the cue and for
each hit it asked for (`services/music_cue_writer`). One `audit_music_cues` job then checks all
prompts together against the Music Bible and applies its fixes as new rows.

Every row is a `music_cue` row for one cue of one plan version, and a stored row is never
changed (the artifact provenance convention, DATABASE_STRUCTURE.md Section 2.1). `inputs` records
the plan, the Music Bible, the theme and the shot definitions the row was built from, so whether
it is out of date is worked out when it is read and never stored.

**Pushback.** A cue may say the plan cannot work for it. While a revision of the plan is still
allowed (`music_cue_pushback_rounds`, and only for a plan the model wrote), the cue's job stops
after level 2 and stores the objection with `sent` true; `start_revision` then asks the plan's
reviser to write a new plan version from the objections. Once none is allowed, the objection is
kept with `sent` false and the cue gets its prompts anyway.

**A cue built on a theme** is text-to-music (MD-6, changed 2026-10-25): it takes the tempo, key
and time signature of the theme's version for its emotion, or of the canonical recording when the
emotion is not listed (`theme_for`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, MusicBible, MusicCue, MusicCueAudit, MusicPlan, Project
from app.jobs import store
from app.services import (
    music_bible,
    music_cue_writer,
    music_plan,
    music_plan_writer,
    music_themes,
    music_timeline,
    provenance,
    shot_definitions,
    speech_units,
)

JOB_TYPE: Final = "write_music_cue"
AUDIT_JOB_TYPE: Final = "audit_music_cues"
SOURCE_AI: Final = "ai"
SOURCE_AUDIT: Final = "audit"

MUSIC_OFF_MESSAGE: Final = "Music is switched off for this project. Switch it on in the settings."
NO_PLAN_MESSAGE: Final = "Plan the music first: the cues are detailed from the plan."
STALE_PLAN_MESSAGE: Final = "The music plan is out of date. Plan the music again first."
BUSY_MESSAGE: Final = "The cues are being detailed. Wait for them to finish first."


class MusicCueError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- Loading what the cues are made from ---------------------------------------------------


@dataclass(frozen=True)
class Loaded:
    """Everything a run or a read of the state needs, loaded once."""

    music_enabled: bool
    plan_state: music_plan.MusicPlanState
    bible: MusicBible | None
    names: dict[str, str]
    # The ids of the characters each shot's definition shows, and its definition row, both by
    # the shot's story-wide reference.
    shot_characters: dict[str, list[str]]
    shot_rows: dict[str, Any]
    themes: dict[str, music_themes.ThemeView]
    wordings: int
    handles_s: int
    pushback_rounds: int
    blocked_reason: str | None

    @property
    def plan(self) -> MusicPlan | None:
        return self.plan_state.latest


def _shots_blocked_reason(
    plan: MusicPlan, shot_rows: dict[str, Any], defined: set[str]
) -> str | None:
    titles = {scene["id"]: scene["title"] for scene in plan.timeline["scenes"]}
    for shot in plan.timeline["shots"]:
        if shot["ref"] not in defined:
            title = titles.get(shot["scene_id"], shot["scene_id"])
            return (
                f"Define the shots of the scene '{title}' first: "
                "cues are detailed with who is in each shot."
            )
    return None


async def load(session: AsyncSession, project: Project) -> Loaded:
    plan_state = await music_plan.state(session, project)
    bible = await music_bible.latest(session, project.id)
    wordings = await settings_service.get_int(session, settings_service.MUSIC_CUE_WORDINGS_KEY)
    handles = await settings_service.get_int(session, settings_service.MUSIC_CUE_HANDLES_KEY)
    rounds = await settings_service.get_int(session, settings_service.MUSIC_CUE_PUSHBACK_ROUNDS_KEY)

    names: dict[str, str] = {}
    shot_characters: dict[str, list[str]] = {}
    shot_rows: dict[str, Any] = {}
    themes: dict[str, music_themes.ThemeView] = {}
    blocked: str | None = None

    plan = plan_state.latest
    if not project.music_enabled:
        blocked = MUSIC_OFF_MESSAGE
    elif plan is None:
        blocked = NO_PLAN_MESSAGE
    elif plan_state.out_of_date:
        blocked = STALE_PLAN_MESSAGE
    if plan is not None:
        speech = await speech_units.state(session, project)
        names = {item["id"]: item["name"] for item in speech.characters}
        definitions = await shot_definitions.state(session, project)
        defined: set[str] = set()
        for scene in definitions.entries:
            for shot in scene.shots:
                ref = music_timeline.shot_ref(scene.item["id"], shot.shot["id"])
                if shot.status == "defined" and shot.row is not None and shot.content is not None:
                    defined.add(ref)
                    shot_rows[ref] = shot.row
                    shot_characters[ref] = [
                        character["id"] for character in shot.content.get("characters") or []
                    ]
        if blocked is None:
            blocked = _shots_blocked_reason(plan, shot_rows, defined)
        themes = {
            view.theme["id"]: view for view in (await music_themes.state(session, project)).themes
        }
    return Loaded(
        music_enabled=project.music_enabled,
        plan_state=plan_state,
        bible=bible,
        names=names,
        shot_characters=shot_characters,
        shot_rows=shot_rows,
        themes=themes,
        wordings=wordings,
        handles_s=handles,
        pushback_rounds=rounds,
        blocked_reason=blocked,
    )


# --- Themes --------------------------------------------------------------------------------


def _fold(text: str) -> str:
    return " ".join(text.split()).casefold()


def theme_for(
    cue: dict[str, Any], themes: dict[str, music_themes.ThemeView]
) -> tuple[dict[str, Any] | None, str | None]:
    """What a themed score cue is built on: `(theme, None)`, or `(None, reason)` when the theme
    has not been recorded. A cue with no theme gives `(None, None)`.

    The theme is the version recorded for the cue's emotion when there is one, else the
    canonical recording. Its tempo, key and time signature are fixed for the cue, and its
    caption is shown to the model so that the tune is described the same way (MD-6).
    """
    theme_id = cue["theme_id"]
    if cue["kind"] != music_plan_writer.KIND_SCORE or theme_id is None:
        return None, None
    view = themes.get(theme_id)
    if view is None or view.row is None:
        name = view.theme.get("name") if view is not None else theme_id
        return None, f"Record the theme '{name}' first: the cue is built on it."
    emotion = cue["emotion"]
    version = None
    if emotion:
        version = next(
            (
                item
                for item in view.versions
                if item.current and _fold(item.row.emotion) == _fold(emotion)
            ),
            None,
        )
    fields = dict(version.row.fields if version is not None else view.row.fields)
    return (
        {
            "theme_id": theme_id,
            "name": view.theme.get("name"),
            "stands_for": view.theme.get("stands_for"),
            "signature_instrument": view.theme.get("signature_instrument"),
            "emotion": emotion,
            "based_on": "version" if version is not None else "canonical",
            "caption": fields.get("caption"),
            "fields": {key: fields.get(key) for key in music_cue_writer.FIXED_FIELDS},
            "row_id": view.row.id,
            "row_version": view.row.version,
            "version_id": version.row.id if version is not None else None,
        },
        None,
    )


def avoid_list(bible_content: dict[str, Any]) -> list[str]:
    """What the Music Bible says to avoid, as a list of phrases."""
    sound_world = bible_content.get("sound_world")
    avoid = sound_world.get("avoid") if isinstance(sound_world, dict) else None
    return [item for item in avoid if isinstance(item, str)] if isinstance(avoid, list) else []


# --- Rows ----------------------------------------------------------------------------------


async def get_plan(session: AsyncSession, plan_id: int) -> MusicPlan | None:
    return await session.get(MusicPlan, plan_id)


async def newest_rows(session: AsyncSession, plan_id: int) -> dict[str, MusicCue]:
    """The newest row of each cue of a plan version, by the plan's cue id."""
    statement = (
        select(MusicCue)
        .where(MusicCue.plan_id == plan_id)
        .order_by(MusicCue.version.asc())
        .execution_options(populate_existing=True)
    )
    return {row.cue_id: row for row in (await session.execute(statement)).scalars()}


async def rows_by_ids(session: AsyncSession, ids: list[int]) -> list[MusicCue]:
    if not ids:
        return []
    statement = select(MusicCue).where(MusicCue.id.in_(ids)).order_by(MusicCue.id.asc())
    return list((await session.execute(statement)).scalars())


async def saved_orders(
    session: AsyncSession, plan_id: int, cue_ids: list[str]
) -> dict[str, list[str]]:
    """The broad order of moods of those cues, where their detail is already saved. Used so that
    a cue's prompt can see what its neighbours were asked to do.
    """
    rows = await newest_rows(session, plan_id)
    found: dict[str, list[str]] = {}
    for cue_id in cue_ids:
        row = rows.get(cue_id)
        order = row.detail.get("internal_order") if row is not None else None
        if isinstance(order, list):
            found[cue_id] = [step["mood"] for step in order]
    return found


async def _next_version(session: AsyncSession, plan_id: int, cue_id: str) -> int:
    statement = select(func.max(MusicCue.version)).where(
        MusicCue.plan_id == plan_id, MusicCue.cue_id == cue_id
    )
    return ((await session.execute(statement)).scalar_one_or_none() or 0) + 1


async def save_cue(
    session: AsyncSession,
    *,
    project_id: int,
    plan_id: int,
    cue_id: str,
    job_id: int,
    inputs: dict[str, Any],
    detail: dict[str, Any],
    items: list[dict[str, Any]],
    pushback: dict[str, Any] | None,
) -> MusicCue:
    """Adds the next version of a cue, made by the model (`source` is `ai`). Flushes but does
    not commit: the job commits it together with finishing itself.
    """
    row = MusicCue(
        project_id=project_id,
        plan_id=plan_id,
        cue_id=cue_id,
        version=await _next_version(session, plan_id, cue_id),
        source=SOURCE_AI,
        job_id=job_id,
        inputs=inputs,
        detail=detail,
        items=items,
        pushback=pushback,
    )
    session.add(row)
    await session.flush()
    return row


async def save_audit(
    session: AsyncSession,
    *,
    project_id: int,
    plan_id: int,
    job_id: int,
    audited: list[MusicCue],
    findings: dict[str, Any],
) -> MusicCueAudit:
    """Stores an audit and applies its fixes: every cue with a fix gets a new row (`source` is
    `audit`) whose items carry the fixed wordings. Flushes but does not commit.
    """
    fixes: list[dict[str, Any]] = findings["fixes"]
    result_ids: list[int] = []
    for row in audited:
        mine = [fix for fix in fixes if fix["item"].split("/")[0] == row.cue_id]
        if not mine:
            result_ids.append(row.id)
            continue
        changed = MusicCue(
            project_id=project_id,
            plan_id=plan_id,
            cue_id=row.cue_id,
            version=await _next_version(session, plan_id, row.cue_id),
            source=SOURCE_AUDIT,
            job_id=job_id,
            inputs={**row.inputs, "audit_of": {"id": row.id, "version": row.version}},
            detail=row.detail,
            items=music_cue_writer.apply_fixes(row.items, mine),
            pushback=None,
        )
        session.add(changed)
        await session.flush()
        result_ids.append(changed.id)
    audit = MusicCueAudit(
        project_id=project_id,
        plan_id=plan_id,
        job_id=job_id,
        inputs={"row_ids": [row.id for row in audited]},
        findings=findings,
        result_row_ids=result_ids,
    )
    session.add(audit)
    await session.flush()
    return audit


async def newest_audit(session: AsyncSession, plan_id: int) -> MusicCueAudit | None:
    statement = (
        select(MusicCueAudit)
        .where(MusicCueAudit.plan_id == plan_id)
        .order_by(MusicCueAudit.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def _cue_jobs(session: AsyncSession, project_id: int, plan_id: int) -> dict[str, Job]:
    """The newest `write_music_cue` job of each cue of this plan version."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == JOB_TYPE)
        .order_by(Job.id.asc())
        .execution_options(populate_existing=True)
    )
    found: dict[str, Job] = {}
    for job in (await session.execute(statement)).scalars():
        data = job.input if isinstance(job.input, dict) else {}
        if data.get("plan_id") == plan_id and isinstance(data.get("cue_id"), str):
            found[data["cue_id"]] = job
    return found


# --- Provenance and staleness --------------------------------------------------------------


def _inputs(
    loaded: Loaded, cue: dict[str, Any], theme: dict[str, Any] | None, shots: list[str]
) -> dict[str, Any]:
    """What a row of this cue is built from, in the shape of D-3."""
    plan = loaded.plan
    assert plan is not None and loaded.bible is not None
    return {
        "plan": {"id": plan.id, "version": plan.version},
        "bible": {"id": loaded.bible.id, "version": loaded.bible.version},
        "theme": (
            {
                "theme_id": theme["theme_id"],
                "row_id": theme["row_id"],
                "row_version": theme["row_version"],
                "version_id": theme["version_id"],
            }
            if theme
            else None
        ),
        "shots": [
            {
                "ref": ref,
                "id": loaded.shot_rows[ref].id,
                "version": loaded.shot_rows[ref].version,
            }
            for ref in shots
            if ref in loaded.shot_rows
        ],
        "settings": {"wordings": loaded.wordings, "handles_s": loaded.handles_s},
    }


def shots_in_window(loaded: Loaded, cue: dict[str, Any]) -> list[str]:
    """The shots whose definitions a cue's detail is written from."""
    plan = loaded.plan
    assert plan is not None
    context = music_cue_writer.span_context(
        plan.timeline, plan.content, cue, loaded.shot_characters, loaded.names
    )
    return music_cue_writer.span_shot_refs(context)


def job_inputs(loaded: Loaded, cue: dict[str, Any], theme: dict[str, Any] | None) -> dict[str, Any]:
    return _inputs(loaded, cue, theme, shots_in_window(loaded, cue))


def _out_of_date_reasons(row: MusicCue, loaded: Loaded) -> list[str]:
    """Why a row of the current plan is no longer current, one sentence each."""
    inputs = row.inputs if isinstance(row.inputs, dict) else {}
    reasons: list[str] = []
    if not provenance.same_row(inputs.get("bible"), loaded.bible):
        reasons.append("The Music Bible has been written again since this cue was detailed.")

    recorded_theme = inputs.get("theme")
    if isinstance(recorded_theme, dict):
        view = loaded.themes.get(recorded_theme.get("theme_id"))
        name = view.theme.get("name") if view is not None else recorded_theme.get("theme_id")
        if view is None or view.row is None or recorded_theme.get("row_id") != view.row.id:
            reasons.append(f"The theme '{name}' was recorded again since this cue was detailed.")
        else:
            cue = next((c for c in loaded.plan.content["cues"] if c["id"] == row.cue_id), None)
            current, _ = theme_for(cue, loaded.themes) if cue is not None else (None, None)
            if current is not None and current["version_id"] != recorded_theme.get("version_id"):
                reasons.append(
                    f"The recording of the theme '{name}' this cue is built on has changed."
                )

    for shot in inputs.get("shots") or []:
        current_row = loaded.shot_rows.get(shot.get("ref"))
        if current_row is None or not provenance.same_row(shot, current_row):
            reasons.append(f"The definition of the shot '{shot.get('ref')}' has changed.")
    settings = inputs.get("settings") if isinstance(inputs.get("settings"), dict) else {}
    if settings.get("wordings") != loaded.wordings:
        reasons.append("The setting for the number of wordings has changed.")
    elif row.items and settings.get("handles_s") != loaded.handles_s:
        reasons.append("The setting for the spare length of a cue has changed.")
    return reasons


# --- Reading the state ---------------------------------------------------------------------


@dataclass(frozen=True)
class CueView:
    """One cue of the newest plan and where its detail stands."""

    cue: dict[str, Any]
    # False for a silence and for a sound that H3 makes: there is nothing to write.
    makes_audio: bool
    row: MusicCue | None
    job: Job | None
    reasons: list[str]
    # Why it cannot be written now (its theme is not recorded), or None.
    blocked_reason: str | None
    done: bool
    active: bool

    @property
    def out_of_date(self) -> bool:
        return bool(self.reasons)

    @property
    def pushback(self) -> dict[str, Any] | None:
        return self.row.pushback if self.row is not None else None

    @property
    def waiting_for_revision(self) -> bool:
        pushback = self.pushback
        return bool(pushback and pushback.get("sent"))


@dataclass(frozen=True)
class MusicCuesState:
    """What the story workspace shows."""

    plan: MusicPlan | None
    cues: list[CueView]
    audit: MusicCueAudit | None
    audit_job: Job | None
    audit_current: bool
    audit_active: bool
    # The plan's job (a revision from the objections is one), whatever its status.
    plan_job: Job | None
    revision_pending: bool
    revision_active: bool
    revisions_used: int
    revisions_allowed: int
    blocked_reason: str | None
    music_enabled: bool
    wordings: int
    handles_s: int

    @property
    def detailed_rows(self) -> list[MusicCue]:
        return [view.row for view in self.cues if view.row is not None and view.row.items]


def revisions_used(plan: MusicPlan) -> int:
    pushback = plan.inputs.get("pushback") if isinstance(plan.inputs, dict) else None
    used = pushback.get("round") if isinstance(pushback, dict) else 0
    return used if isinstance(used, int) and not isinstance(used, bool) else 0


def revision_allowed(loaded: Loaded) -> bool:
    """Whether a cue's objection may still send the plan back: the model wrote the plan and the
    rounds are not used up.
    """
    plan = loaded.plan
    return (
        plan is not None
        and plan.source == music_plan.SOURCE_AI
        and revisions_used(plan) < loaded.pushback_rounds
    )


async def state(session: AsyncSession, project: Project) -> MusicCuesState:
    """The project's cue details with where they stand. Worked out on every read."""
    loaded = await load(session, project)
    plan = loaded.plan
    plan_job = loaded.plan_state.job
    if plan is None:
        return MusicCuesState(
            plan=None,
            cues=[],
            audit=None,
            audit_job=None,
            audit_current=False,
            audit_active=False,
            plan_job=plan_job,
            revision_pending=False,
            revision_active=False,
            revisions_used=0,
            revisions_allowed=loaded.pushback_rounds,
            blocked_reason=loaded.blocked_reason,
            music_enabled=loaded.music_enabled,
            wordings=loaded.wordings,
            handles_s=loaded.handles_s,
        )

    rows = await newest_rows(session, plan.id)
    jobs = await _cue_jobs(session, project.id, plan.id)
    allowed = revision_allowed(loaded)
    ready = loaded.blocked_reason is None
    views: list[CueView] = []
    for cue in plan.content["cues"]:
        makes = music_cue_writer.needs_audio(cue)
        row = rows.get(cue["id"]) if makes else None
        job = jobs.get(cue["id"]) if makes else None
        reasons = _out_of_date_reasons(row, loaded) if row is not None and ready else []
        _, theme_block = theme_for(cue, loaded.themes) if makes else (None, None)
        active = job is not None and job.status in store.ACTIVE_STATUSES
        waiting = bool(row is not None and row.pushback and row.pushback.get("sent"))
        done = (
            makes
            and row is not None
            and not reasons
            and (not waiting or allowed)
            and not (job is not None and job.status in store.ACTIVE_STATUSES)
        )
        views.append(
            CueView(
                cue=cue,
                makes_audio=makes,
                row=row,
                job=job,
                reasons=reasons,
                blocked_reason=theme_block,
                done=bool(done),
                active=active,
            )
        )

    audit = await newest_audit(session, plan.id)
    audit_job = await store.latest_job(session, project.id, AUDIT_JOB_TYPE)
    detailed = {view.row.id for view in views if view.row is not None and view.row.items}
    audit_current = audit is not None and bool(detailed) and set(audit.result_row_ids) == detailed
    pending = any(view.waiting_for_revision and not view.out_of_date for view in views)
    return MusicCuesState(
        plan=plan,
        cues=views,
        audit=audit,
        audit_job=audit_job,
        audit_current=audit_current,
        audit_active=audit_job is not None and audit_job.status in store.ACTIVE_STATUSES,
        plan_job=plan_job,
        revision_pending=pending and allowed,
        revision_active=plan_job is not None and plan_job.status in store.ACTIVE_STATUSES,
        revisions_used=revisions_used(plan),
        revisions_allowed=loaded.pushback_rounds,
        blocked_reason=loaded.blocked_reason,
        music_enabled=loaded.music_enabled,
        wordings=loaded.wordings,
        handles_s=loaded.handles_s,
    )


# --- Starting runs -------------------------------------------------------------------------


def _refuse_when_unable(loaded: Loaded) -> MusicPlan:
    if loaded.blocked_reason is not None:
        raise MusicCueError(loaded.blocked_reason)
    plan = loaded.plan
    assert plan is not None
    if loaded.bible is None:
        raise MusicCueError(music_plan.NO_BIBLE_MESSAGE)
    return plan


async def start_cue(
    session: AsyncSession, project: Project, cue_id: str, *, loaded: Loaded | None = None
) -> Job:
    """Queues the job that details one cue of the newest plan, and commits. If a job for this cue
    is already waiting or running, that job is returned and no new one is made. `loaded` is the
    result of `load`, for a caller that starts several cues.
    """
    loaded = loaded or await load(session, project)
    plan = _refuse_when_unable(loaded)
    assert loaded.bible is not None
    cue = next((item for item in plan.content["cues"] if item["id"] == cue_id), None)
    if cue is None:
        raise MusicCueError(f"The music plan has no cue '{cue_id}'.")
    if not music_cue_writer.needs_audio(cue):
        raise MusicCueError(f"The cue '{cue_id}' has nothing to generate.")
    theme, why_not = theme_for(cue, loaded.themes)
    if why_not is not None:
        raise MusicCueError(why_not)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "cue_id": cue_id,
            "plan_id": plan.id,
            "plan_version": plan.version,
            "bible": loaded.bible.content,
            "names": loaded.names,
            "shot_characters": loaded.shot_characters,
            "theme": theme,
            "wordings": loaded.wordings,
            "handles_s": loaded.handles_s,
            "pushback_allowed": revision_allowed(loaded),
            "avoid": avoid_list(loaded.bible.content),
            "saved_inputs": job_inputs(loaded, cue, theme),
        },
        dedupe_key="cue_id",
    )
    return job


async def start_run(
    session: AsyncSession, project: Project, *, cue_id: str | None = None
) -> list[Job]:
    """Queues a job for every cue that has no current detail (or for the one cue asked for,
    even if it has), and commits. Returns the jobs, including ones that were already waiting.
    """
    loaded = await load(session, project)
    _refuse_when_unable(loaded)
    current = await state(session, project)
    if cue_id is not None:
        return [await start_cue(session, project, cue_id, loaded=loaded)]
    jobs = [
        await start_cue(session, project, view.cue["id"], loaded=loaded)
        for view in current.cues
        if view.makes_audio and not view.done and view.blocked_reason is None
    ]
    if not jobs and not any(view.makes_audio for view in current.cues):
        raise MusicCueError("The plan has no cue that needs a prompt.")
    return jobs


async def start_audit(session: AsyncSession, project: Project) -> Job:
    """Queues the audit over every cue's prompts, and commits. Every cue that has something to
    generate must have its current detail and prompts first.
    """
    loaded = await load(session, project)
    plan = _refuse_when_unable(loaded)
    current = await state(session, project)
    wanted = [view for view in current.cues if view.makes_audio]
    if not wanted:
        raise MusicCueError("The plan has no cue that needs a prompt.")
    if any(not view.done or not (view.row and view.row.items) for view in wanted):
        raise MusicCueError("Detail every cue first: the audit reads all prompts together.")
    assert loaded.bible is not None and current.detailed_rows
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=AUDIT_JOB_TYPE,
        provider="llm",
        input={
            "plan_id": plan.id,
            "row_ids": [row.id for row in current.detailed_rows],
            "bible": loaded.bible.content,
            "avoid": avoid_list(loaded.bible.content),
        },
    )
    return job


async def start_revision(session: AsyncSession, project: Project) -> Job:
    """Queues the revision of the plan from the cues' waiting objections, and commits. The model
    writes a new plan version; the cues are detailed again for it.
    """
    loaded = await load(session, project)
    plan = _refuse_when_unable(loaded)
    if not revision_allowed(loaded):
        raise MusicCueError("The plan cannot be revised from the cues' objections any more.")
    current = await state(session, project)
    notes = [
        {
            "target": view.cue["id"],
            "problem": view.pushback["problem"],
            "suggestion": view.pushback["suggestion"],
        }
        for view in current.cues
        if view.waiting_for_revision and view.pushback is not None and not view.out_of_date
    ]
    if not notes:
        raise MusicCueError("No cue has an objection waiting.")
    try:
        return await music_plan.start_pushback_revision(
            session, project, plan_id=plan.id, notes=notes, pushback_round=revisions_used(plan) + 1
        )
    except music_plan.MusicPlanError as exc:
        raise MusicCueError(str(exc)) from exc
