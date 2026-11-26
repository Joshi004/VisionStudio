"""The two sound effects of a continuous explainer (EXM-006, `Explainer_music_phases.md`: XM-8,
XM-9, XM-11).

A project with the `sound_effects` switch on has up to two sounds, made once and reused at every
graphic and evidence moment of that project (never by another project): the `graphic` sound,
when the project has graphics, and the `evidence` sound, when it has evidence. Each is made by
Stable Audio 3 (Music lab kind `sfx`) and works like a music take, without a music plan:

1. **Prompt.** `start_run` queues a `write_sound_effect` job: a language model writes one prompt
   for the sound from the Story Bible's tone and the Music Bible's palette. The job saves the
   takes (`save_round`): one for each of the `sound_effect_takes` seeds, each a Music lab run
   (`music_lab.add_run`) plus a `sound_effect_take` row.
2. **Check and selection.** When a take's audio is stored (`on_audio_stored`, called by the
   `lab_music` job), it is measured (MUSIC-003) and checked (`check_take`). The first take of a
   sound that passes is selected (`selected_by` is `auto`, MD-10). The claim is one atomic
   `UPDATE`, so two takes stored at the same moment cannot both win, and an owner's choice or a
   lock is never replaced.
3. **Retries.** A take that fails its check, while the sound has no selection, is made again with
   the same prompt and a new seed, up to `music_take_max_retries` in one round.
4. **The owner.** `select_take` (even one that failed its check), `reject` with a note (the
   `write_sound_effect` job rewrites the prompt from the note, and a new take is made, MD-23),
   `lock` the selected one, or make the sound again (`start_run`, a new round).

Nothing makes a sound out of date: a sound is done once it has a selected take. Nothing about
being selected, rejected or locked is stored as a flag that can go stale: the selected take is
the newest-selected one that is not rejected. This module creates rows and jobs. It never calls
the GPU server or the language model itself.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import settings as settings_service
from app.db.models import Job, LabMusicRun, Project, SoundEffectTake
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.jobs import store
from app.providers import music_generator
from app.services import (
    audio_measurements,
    evidence_claims,
    graphic_theme,
    music_bible,
    music_cue_writer,
    music_lab,
    music_models,
    projects,
    story_bible,
)
from app.services import sound_effect_writer as writer
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "write_sound_effect"
SELECTED_AUTO: Final = "auto"
SELECTED_OWNER: Final = "owner"

# The technical check (Planning decides, EXM-006). First guesses, to be tuned by ear: a sound
# that starts at once, has one clear loudest moment that is not at the very end, does not clip
# and dies away.
MIN_LENGTH_FRACTION: Final = 0.9
MAX_LEADING_SILENCE_S: Final = 0.1
MIN_TAIL_AFTER_PEAK_S: Final = 0.2

BRIEF_MAX_CHARS: Final = 1900
NOTE_MAX_CHARS: Final = writer.NOTE_MAX_CHARS

OFF_MESSAGE: Final = (
    "Sound effects are switched off for this project. Switch them on in the settings."
)
NOT_FOR_PROJECT_MESSAGE: Final = projects.SOUND_EFFECTS_ONLY_MESSAGE
NO_STORY_BIBLE_MESSAGE: Final = "Run the Story Bible first: the sounds are written with its help."
LOCKED_MESSAGE: Final = "This sound is locked. Unlock it first."
BUSY_MESSAGE: Final = "A prompt for this sound is being written, or its takes are being made. Wait."

TakeStatus = Literal["generating", "checking", "passed", "check_failed", "failed"]

# One backend process, so a module lock makes "count the retries, then add one" atomic.
_retry_lock = asyncio.Lock()


class SoundEffectError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- Which sounds a project needs ----------------------------------------------------------


def available(project: Project) -> bool:
    """Whether the project can have sound effects at all and has them switched on (XM-8): a
    continuous explainer with the switch on. Pure.
    """
    return (
        project.kind == projects.KIND_EXPLAINER
        and project.voice_track == projects.VOICE_CONTINUOUS
        and project.sound_effects
    )


def roles(project: Project) -> tuple[str, ...]:
    """The sounds the project needs: the graphic sound with graphics on, the evidence sound with
    evidence on. Empty when the switch is off. Pure.
    """
    if not available(project):
        return ()
    found: list[str] = []
    if graphic_theme.wanted(project):
        found.append(writer.ROLE_GRAPHIC)
    if evidence_claims.wanted(project):
        found.append(writer.ROLE_EVIDENCE)
    return tuple(found)


def wanted(project: Project) -> bool:
    """Whether the step has anything to make (the switch is on, and a sound is needed). Pure."""
    return bool(roles(project))


# --- Pure helpers --------------------------------------------------------------------------


def check_take(measurement: dict[str, Any], *, requested_s: float) -> dict[str, Any]:
    """Whether a take passes the technical check, from its MUSIC-003 measurement. Pure.

    A sound effect is short, so the check is about its shape: at least 90% of the length asked
    for, no clipping, no more than 0.1 s of silence at the start, one clear loudest moment that
    is not in the last 0.2 s, and an ending that dies away rather than a cut while loud.
    Returns `{passed, problems, facts}`; `facts` are the numbers the panel and the rewrite of a
    rejected prompt show (the same keys as a music take's).
    """
    loudness = measurement.get("loudness")
    loudness = loudness if isinstance(loudness, dict) else {}
    loudest = measurement.get("loudest_moment")
    loudest = loudest if isinstance(loudest, dict) else None
    ending = measurement.get("ending")
    ending = ending if isinstance(ending, dict) else {}
    duration = float(measurement.get("duration_s") or 0.0)
    leading = float(measurement.get("leading_silence_s") or 0.0)
    peak_s = loudest.get("time_s") if loudest is not None else None
    facts = {
        "duration_s": round(duration, 2),
        "leading_silence_s": round(leading, 2),
        "trailing_silence_s": round(float(measurement.get("trailing_silence_s") or 0.0), 2),
        "integrated_lufs": loudness.get("integrated_lufs"),
        "true_peak_dbtp": loudness.get("true_peak_dbtp"),
        "loudest_moment_s": peak_s,
        "ending_kind": ending.get("kind"),
    }
    problems: list[str] = []
    if duration < requested_s * MIN_LENGTH_FRACTION:
        problems.append(f"It is {duration:.2f} s long, and {requested_s:g} s were asked for.")
    if loudness.get("clipping"):
        problems.append("It clips (the sound reaches full scale).")
    if leading > MAX_LEADING_SILENCE_S:
        problems.append(f"It starts with {leading:.2f} s of silence.")
    if not isinstance(peak_s, int | float):
        problems.append("It has no clear loudest moment.")
    elif peak_s > duration - MIN_TAIL_AFTER_PEAK_S:
        problems.append("Its loudest moment is at the very end of the sound.")
    if ending.get("kind") != "decay":
        problems.append("It is cut off at its end instead of dying away.")
    return {"passed": not problems, "problems": problems, "facts": facts}


def _failed_check(message: str) -> dict[str, Any]:
    return {"passed": False, "problems": [message], "facts": None}


def _seed() -> int:
    return secrets.randbelow(music_models.SEED_MAX + 1)


# --- Reading the state ---------------------------------------------------------------------


@dataclass(frozen=True)
class TakeView:
    row: SoundEffectTake
    run: music_lab.RunRow | None
    selected: bool = False

    @property
    def usable(self) -> bool:
        return self.run is not None and self.run.run.path is not None

    @property
    def status(self) -> TakeStatus:
        if self.usable:
            check = self.row.check_result
            if not isinstance(check, dict):
                return "checking"
            return "passed" if check.get("passed") else "check_failed"
        job = self.run.job if self.run is not None else None
        if job is not None and job.status in store.ACTIVE_STATUSES:
            return "generating"
        return "failed"

    @property
    def active(self) -> bool:
        return self.status in ("generating", "checking")

    @property
    def problems(self) -> list[str]:
        check = self.row.check_result
        if isinstance(check, dict) and isinstance(check.get("problems"), list):
            return [str(problem) for problem in check["problems"]]
        job = self.run.job if self.run is not None else None
        if self.status == "failed":
            return [(job.error if job is not None and job.error else "The take was not made.")]
        return []


@dataclass(frozen=True)
class RoleView:
    """One sound (`graphic` or `evidence`) and where its takes stand."""

    role: str
    takes: list[TakeView]
    # The take that is used: the newest selected one that is not rejected.
    selection: TakeView | None
    locked: bool
    round: int
    retries_used: int
    # The newest `write_sound_effect` job of the sound.
    prompt_job: Job | None
    active: bool
    pending_retry: bool
    done: bool
    # What a run starts next: `generate`, `retry`, or None.
    action: str | None
    # Why nothing can be made now, or None.
    blocked_reason: str | None
    # Why it got nowhere (the prompt could not be written, no take passed its check), or None.
    last_error: str | None

    @property
    def label(self) -> str:
        return writer.LABELS[self.role]


@dataclass(frozen=True)
class SoundEffectsState:
    """What the project board shows."""

    # The project's switch (`sound_effects`) and whether it can have it at all.
    switched_on: bool
    wanted: bool
    roles: list[RoleView]
    blocked_reason: str | None
    max_retries: int
    takes_per_prompt: int


def _selection(takes: list[TakeView]) -> TakeView | None:
    chosen = [t for t in takes if t.row.selected_at is not None and t.row.rejected_at is None]
    if not chosen:
        return None
    return max(chosen, key=lambda t: (t.row.selected_at, t.row.id))  # type: ignore[arg-type,return-value]


def item_key(project_id: int, role: str) -> str:
    """The dedupe key of the `write_sound_effect` jobs of one sound."""
    return f"{project_id}/{role}"


async def _prompt_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest `write_sound_effect` job of each sound, by role."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == JOB_TYPE)
        .order_by(Job.id.asc())
        .execution_options(populate_existing=True)
    )
    found: dict[str, Job] = {}
    for job in (await session.execute(statement)).scalars():
        role = job.input.get("role") if isinstance(job.input, dict) else None
        if isinstance(role, str):
            found[role] = job
    return found


def _build_role(
    *,
    role: str,
    rows: list[SoundEffectTake],
    runs: dict[int, music_lab.RunRow],
    prompt_job: Job | None,
    max_retries: int,
    global_block: str | None,
) -> RoleView:
    takes = [
        TakeView(row, runs.get(row.lab_run_id) if row.lab_run_id is not None else None)
        for row in rows
    ]
    selection = _selection(takes)
    locked = any(t.row.locked_at is not None and t.row.rejected_at is None for t in takes)
    if selection is not None:
        chosen_id = selection.row.id
        takes = [TakeView(t.row, t.run, selected=t.row.id == chosen_id) for t in takes]
        selection = next(t for t in takes if t.row.id == chosen_id)

    round_no = max((t.row.round for t in takes), default=0)
    in_round = [t for t in takes if t.row.round == round_no]
    retried = {t.row.retry_of_id for t in takes if t.row.retry_of_id is not None}
    retries_used = sum(1 for t in in_round if t.row.retry_of_id is not None)
    failed = [
        t
        for t in in_round
        if t.status in ("failed", "check_failed")
        and t.row.rejected_at is None
        and t.row.id not in retried
    ]
    prompt_active = prompt_job is not None and prompt_job.status in store.ACTIVE_STATUSES
    active = prompt_active or any(t.active for t in takes)
    done = selection is not None
    pending_retry = selection is None and not active and retries_used < max_retries and bool(failed)

    action: str | None = None
    if not done and not active:
        if pending_retry:
            action = "retry"
        elif not takes:
            action = "generate"

    block = global_block if action is not None else None

    last_error: str | None = None
    prompt_failed = prompt_job is not None and prompt_job.status in ("failed", "cancelled")
    if not done and not active:
        if prompt_failed and (not takes or action is None):
            assert prompt_job is not None
            last_error = (
                f"The prompt could not be written: {prompt_job.error or 'the job failed'}. "
                "Make the sound again to start a new round."
            )
        elif takes and action is None:
            problems = next((t.problems for t in reversed(failed) if t.problems), [])
            last_error = "No take passed its check" + (
                f": {' '.join(problems)}" if problems else "."
            )

    return RoleView(
        role=role,
        takes=takes,
        selection=selection,
        locked=locked,
        round=round_no,
        retries_used=retries_used,
        prompt_job=prompt_job,
        active=active,
        pending_retry=pending_retry,
        done=done,
        action=action,
        blocked_reason=block,
        last_error=last_error,
    )


async def state(session: AsyncSession, project: Project) -> SoundEffectsState:
    """The project's sounds with where they stand. Worked out on every read."""
    max_retries = await settings_service.get_int(
        session, settings_service.MUSIC_TAKE_MAX_RETRIES_KEY
    )
    per_prompt = await settings_service.get_int(session, settings_service.SOUND_EFFECT_TAKES_KEY)
    needed = roles(project)
    if not needed:
        return SoundEffectsState(
            project.sound_effects, False, [], OFF_MESSAGE, max_retries, per_prompt
        )

    block: str | None = None
    if await story_bible.latest(session, project.id) is None:
        block = NO_STORY_BIBLE_MESSAGE

    statement = (
        select(SoundEffectTake)
        .where(SoundEffectTake.project_id == project.id)
        .order_by(SoundEffectTake.id.asc())
        .execution_options(populate_existing=True)
    )
    all_rows = list((await session.execute(statement)).scalars())
    run_ids = {row.lab_run_id for row in all_rows if row.lab_run_id is not None}
    runs = await music_lab.get_runs(session, run_ids)
    jobs = await _prompt_jobs(session, project.id)
    views = [
        _build_role(
            role=role,
            rows=[row for row in all_rows if row.role == role],
            runs=runs,
            prompt_job=jobs.get(role),
            max_retries=max_retries,
            global_block=block,
        )
        for role in needed
    ]
    return SoundEffectsState(True, True, views, block, max_retries, per_prompt)


def find_take(current: SoundEffectsState, take_id: int) -> tuple[RoleView, TakeView] | None:
    """The sound and the take view of a take, among the sounds the project needs."""
    for view in current.roles:
        for take in view.takes:
            if take.row.id == take_id:
                return view, take
    return None


# --- Starting takes ------------------------------------------------------------------------


async def _partition(session: AsyncSession) -> str:
    try:
        return await music_lab.generation_partition(session, writer.MODEL)
    except music_lab.MusicLabInputError as exc:
        raise SoundEffectError(str(exc)) from exc


async def _material(session: AsyncSession, project: Project) -> dict[str, Any]:
    """The context the model reads: the Story Bible, and the Music Bible's palette when music
    is on. Raises SoundEffectError when there is no Story Bible.
    """
    story = await story_bible.latest(session, project.id)
    if story is None:
        raise SoundEffectError(NO_STORY_BIBLE_MESSAGE)
    palette: dict[str, Any] | None = None
    if project.music_enabled and music_bible.explainer_music(project):
        bible = await music_bible.latest(session, project.id)
        palette = bible.content if bible is not None else None
    return writer.context(story.content, palette)


async def _queue_prompt_job(
    session: AsyncSession,
    project: Project,
    *,
    role: str,
    round_no: int,
    feedback: dict[str, Any] | None,
) -> Job | None:
    """Queues the job that writes the sound's prompt (and, when it ends, saves the takes).
    Returns None when a job of this sound is already active. Does not commit.
    """
    per_prompt = await settings_service.get_int(session, settings_service.SOUND_EFFECT_TAKES_KEY)
    job_input: dict[str, Any] = {
        "item_key": item_key(project.id, role),
        "role": role,
        "round": round_no,
        "material": await _material(session, project),
        "partition": await _partition(session),
        # One seed for each take, chosen now so a restart of the job cannot change them.
        "seeds": [_seed() for _ in range(1 if feedback is not None else per_prompt)],
        "feedback": feedback,
    }
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input=job_input,
        commit=False,
        dedupe_key="item_key",
    )
    return job if created else None


async def _add_take(
    session: AsyncSession,
    *,
    project_id: int,
    role: str,
    fields: dict[str, Any],
    round_no: int,
    retry_of_id: int | None,
    feedback: dict[str, Any] | None,
    partition: str,
    seed: int | None = None,
    prompt_job_id: int | None = None,
) -> tuple[SoundEffectTake, int | None]:
    """Adds one take and its Music lab run and GPU job, and flushes. Returns the take and the
    id of the GPU job. Does not commit.
    """
    seed = _seed() if seed is None else seed
    description = f"{writer.LABELS[role]}: {fields['prompt']}"
    try:
        brief = music_lab.clean_brief(
            writer.LAB_KIND, {"description": description[:BRIEF_MAX_CHARS]}
        )
    except music_lab.MusicLabInputError as exc:
        raise SoundEffectError(str(exc)) from exc
    body = music_generator.build_body(writer.MODEL, fields, seed=seed, partition=partition)
    made = await music_lab.add_run(
        session,
        model=writer.MODEL,
        kind=writer.LAB_KIND,
        brief=brief,
        fields=fields,
        seed=seed,
        body=body,
        group_key=f"sfx:{project_id}/{role}",
        project_id=project_id,
    )
    take = SoundEffectTake(
        project_id=project_id,
        role=role,
        round=round_no,
        retry_of_id=retry_of_id,
        lab_run_id=made.run.id,
        prompt_job_id=prompt_job_id,
        seed=seed,
        fields=fields,
        requested_s=float(fields["duration"]),
        feedback=feedback,
    )
    session.add(take)
    await session.flush()
    return take, made.job.id if made.job is not None else None


async def _start_retry(
    session: AsyncSession, project: Project, current: SoundEffectsState, view: RoleView
) -> list[int]:
    """Adds another take, with the same fields and a new seed, for each failed take of the round
    that has none yet, up to the setting. Returns the GPU job ids. Does not commit.
    """
    partition = await _partition(session)
    job_ids: list[int] = []
    in_round = [t for t in view.takes if t.row.round == view.round]
    retried = {t.row.retry_of_id for t in view.takes}
    budget = current.max_retries - view.retries_used
    for take in in_round:
        if budget <= 0:
            break
        if (
            take.status not in ("failed", "check_failed")
            or take.row.rejected_at is not None
            or take.row.id in retried
        ):
            continue
        _made, job_id = await _add_take(
            session,
            project_id=project.id,
            role=view.role,
            fields=take.row.fields,
            round_no=take.row.round,
            retry_of_id=take.row.id,
            feedback=take.row.feedback,
            partition=partition,
            prompt_job_id=take.row.prompt_job_id,
        )
        budget -= 1
        if job_id is not None:
            job_ids.append(job_id)
    return job_ids


async def start_run(
    session: AsyncSession, project: Project, *, role: str | None = None
) -> tuple[int, ...]:
    """Makes the sounds that are missing: every sound that needs it, or the one `role`. Commits.
    Returns the ids of the jobs it queued (none when everything is done or already being made).
    Raises SoundEffectError.

    Without `role` only a sound that has no takes, or has a failed take to retry, is started.
    With one, a sound that is done gets a new round too (more takes to choose from, none of
    which replaces the selection), unless it is locked.
    """
    await settle(project.id)
    current = await state(session, project)
    if not current.switched_on:
        raise SoundEffectError(OFF_MESSAGE)
    if not current.wanted:
        raise SoundEffectError(NOT_FOR_PROJECT_MESSAGE)
    if current.blocked_reason is not None:
        raise SoundEffectError(current.blocked_reason)

    todo: list[tuple[RoleView, str]] = []
    if role is not None:
        view = next((v for v in current.roles if v.role == role), None)
        if view is None:
            raise SoundEffectError(f"The project does not need the sound '{role}'.")
        if view.locked:
            raise SoundEffectError(LOCKED_MESSAGE)
        if view.active:
            return ()
        todo.append((view, "retry" if view.pending_retry else "round"))
    else:
        for view in current.roles:
            if view.action is not None:
                todo.append((view, "retry" if view.action == "retry" else "round"))

    job_ids: list[int] = []
    for view, mode in todo:
        if mode == "retry":
            job_ids.extend(await _start_retry(session, project, current, view))
        else:
            job = await _queue_prompt_job(
                session, project, role=view.role, round_no=view.round + 1, feedback=None
            )
            if job is not None:
                job_ids.append(job.id)
    await session.commit()
    return tuple(job_ids)


async def save_round(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    role: str,
    round_no: int,
    fields: dict[str, Any],
    seeds: list[int],
    partition: str,
) -> list[SoundEffectTake]:
    """Adds the takes of a new round, one for each seed, made from the prompt the job wrote.
    Flushes but does not commit: the job commits it together with finishing itself, so a job is
    never "succeeded" without its result.
    """
    takes: list[SoundEffectTake] = []
    for seed in seeds:
        take, _job_id = await _add_take(
            session,
            project_id=project_id,
            role=role,
            fields=fields,
            round_no=round_no,
            retry_of_id=None,
            feedback=None,
            partition=partition,
            seed=seed,
            prompt_job_id=job_id,
        )
        takes.append(take)
    return takes


async def save_feedback_take(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    role: str,
    task_take_id: int,
    round_no: int,
    claim: bool,
    fields: dict[str, Any],
    seed: int,
    partition: str,
) -> SoundEffectTake:
    """Adds the take made from a rewritten prompt, with its run and GPU job. Flushes but does not
    commit (see `save_round`). Raises SoundEffectError when the rejected take is gone.
    """
    rejected = await session.get(SoundEffectTake, task_take_id)
    if rejected is None:
        raise SoundEffectError("The rejected take is gone.")
    take, _job_id = await _add_take(
        session,
        project_id=project_id,
        role=role,
        fields=fields,
        round_no=round_no,
        retry_of_id=None,
        feedback={
            "of_take_id": task_take_id,
            "note": rejected.reject_note,
            "job_id": job_id,
            "claim": claim,
        },
        partition=partition,
        seed=seed,
        prompt_job_id=job_id,
    )
    return take


# --- When a take's audio is stored ---------------------------------------------------------


async def _check_run(
    session: AsyncSession, run: LabMusicRun, take: SoundEffectTake
) -> dict[str, Any]:
    if run.path is None or run.sha256 is None:
        return _failed_check("The run made no recording.")
    try:
        path = get_storage().get_path(run.path)
        measurement = await audio_measurements.measure(session, path, run.sha256)
    except (StorageError, audio_measurements.MeasurementError) as exc:
        return _failed_check(str(exc))
    return check_take(measurement, requested_s=take.requested_s)


async def _claim(session: AsyncSession, take: SoundEffectTake) -> bool:
    """Selects the take for an automatic run, only while nothing blocks it: no other take of the
    sound is selected and not rejected (a locked take is always one of them). One `UPDATE`, so
    two takes stored at the same moment cannot both win and an owner's choice is never replaced.
    """
    other = aliased(SoundEffectTake)
    blocking = (
        select(other.id)
        .where(
            other.project_id == take.project_id,
            other.role == take.role,
            other.id != take.id,
            other.rejected_at.is_(None),
            other.selected_at.is_not(None),
        )
        .exists()
    )
    statement = (
        update(SoundEffectTake)
        .where(
            SoundEffectTake.id == take.id,
            SoundEffectTake.selected_at.is_(None),
            SoundEffectTake.rejected_at.is_(None),
            ~blocking,
        )
        .values(selected_at=utcnow(), selected_by=SELECTED_AUTO)
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult[Any], await session.execute(statement))
    await session.commit()
    return result.rowcount == 1


async def _claim_take(take_id: int) -> bool:
    async with SessionLocal() as session:
        take = await session.get(SoundEffectTake, take_id)
        if take is None or take.rejected_at is not None or take.selected_at is not None:
            await session.commit()
            return False
        feedback = take.feedback if isinstance(take.feedback, dict) else None
        if feedback is not None and not feedback.get("claim", True):
            await session.commit()
            return False  # the owner rejected a take that was not the selected one
        role = take.role
        claimed = await _claim(session, take)
    if claimed:
        _logger.info("sound effect take %d of %s selected", take_id, role)
    return claimed


async def _retry(take_id: int) -> bool:
    """Makes a failed take again when the sound still has nothing selected and the round has
    retries left. True when it queued a job.
    """
    async with _retry_lock, SessionLocal() as session:
        take = await session.get(SoundEffectTake, take_id)
        if take is None or take.rejected_at is not None or take.selected_at is not None:
            await session.commit()
            return False
        project = await session.get(Project, take.project_id)
        if project is None or not available(project):
            await session.commit()
            return False
        try:
            current = await state(session, project)
            view = next((v for v in current.roles if v.role == take.role), None)
            if view is None or view.action != "retry" or view.blocked_reason is not None:
                await session.commit()
                return False
            job_ids = await _start_retry(session, project, current, view)
            await session.commit()
        except SoundEffectError:
            await session.rollback()
            _logger.exception("sound effect take %d: the retry could not be started", take_id)
            return False
    return bool(job_ids)


async def on_audio_stored(run_id: int) -> bool:
    """Called (best effort) once a `lab_music` job has stored its audio. When the run is a sound
    effect take, measures it and stores the check. A take that passed is selected when nothing
    blocks it (MD-10); one that failed is made again while the sound has nothing selected and
    the round has retries left. Returns True when it queued jobs. Does nothing (False) for a
    run that is no sound effect take.
    """
    async with SessionLocal() as session:
        take = (
            (
                await session.execute(
                    select(SoundEffectTake).where(SoundEffectTake.lab_run_id == run_id)
                )
            )
            .scalars()
            .first()
        )
        run = await session.get(LabMusicRun, run_id)
        if take is None or run is None:
            await session.commit()
            return False
        if take.check_result is None:
            take.check_result = await _check_run(session, run, take)
        passed = bool(take.check_result.get("passed"))
        take_id = take.id
        await session.commit()
    if passed:
        await _claim_take(take_id)
        return False
    return await _retry(take_id)


async def settle(project_id: int) -> bool:
    """Checks the takes whose audio is stored but that have no check (the hook of
    `on_audio_stored` failed or the app stopped in between), so that they can be selected or
    retried. Cheap when there is nothing to do. Returns True when it queued jobs.
    """
    async with SessionLocal() as session:
        statement = (
            select(SoundEffectTake.lab_run_id)
            .join(LabMusicRun, LabMusicRun.id == SoundEffectTake.lab_run_id)
            .where(
                SoundEffectTake.project_id == project_id,
                SoundEffectTake.check_result.is_(None),
                LabMusicRun.path.is_not(None),
            )
        )
        run_ids = [run_id for run_id in (await session.execute(statement)).scalars() if run_id]
        await session.commit()
    queued = False
    for run_id in run_ids:
        try:
            queued = await on_audio_stored(run_id) or queued
        except Exception:
            _logger.exception("sound effect take of run %d could not be settled", run_id)
    return queued


# --- The owner's actions -------------------------------------------------------------------


async def _find(
    session: AsyncSession, project: Project, take_id: int
) -> tuple[SoundEffectsState, RoleView, TakeView]:
    await settle(project.id)
    current = await state(session, project)
    found = find_take(current, take_id)
    if found is None:
        raise SoundEffectError("That is not a take of one of the project's sounds.")
    return current, found[0], found[1]


async def select_take(session: AsyncSession, project: Project, take_id: int) -> None:
    """The owner selects a take: any take with audio, even one that failed its check. Stops the
    sound's automatic retries. Commits. Raises SoundEffectError.
    """
    _current, view, take = await _find(session, project, take_id)
    if view.locked:
        raise SoundEffectError(LOCKED_MESSAGE)
    if take.row.rejected_at is not None:
        raise SoundEffectError("That take was rejected.")
    if not take.usable:
        raise SoundEffectError("That take has no recording yet.")
    row = await session.get(SoundEffectTake, take_id)
    assert row is not None
    row.selected_at = utcnow()
    row.selected_by = SELECTED_OWNER
    await session.commit()


async def reject(session: AsyncSession, project: Project, take_id: int, note: str) -> int:
    """The owner rejects a take with a note. The model rewrites the sound's prompt from the note
    (`write_sound_effect`), and a new take is made from it (MD-23). Commits. Returns the id of
    the job. A take whose rewrite failed can be rejected again to ask again. Raises
    SoundEffectError.
    """
    text = (note or "").strip()
    if not text:
        raise SoundEffectError("Say what is wrong with the take: the note is what the model reads.")
    if len(text) > NOTE_MAX_CHARS:
        raise SoundEffectError(f"The note must be at most {NOTE_MAX_CHARS:,} characters.")
    current, view, take = await _find(session, project, take_id)
    if view.locked:
        raise SoundEffectError(LOCKED_MESSAGE)
    if view.prompt_job is not None and view.prompt_job.status in store.ACTIVE_STATUSES:
        raise SoundEffectError(BUSY_MESSAGE)
    if not take.usable:
        raise SoundEffectError("That take has no recording yet, so there is nothing to reject.")
    already_answered = any(
        isinstance(other.row.feedback, dict) and other.row.feedback.get("of_take_id") == take_id
        for other in view.takes
    )
    if take.row.rejected_at is not None and already_answered:
        raise SoundEffectError("That take was already rejected and a new take was made from it.")
    if current.blocked_reason is not None:
        raise SoundEffectError(current.blocked_reason)

    row = await session.get(SoundEffectTake, take_id)
    assert row is not None
    was_selected = view.selection is not None and view.selection.row.id == take_id
    row.rejected_at = utcnow()
    row.reject_note = text
    job = await _queue_prompt_job(
        session,
        project,
        role=view.role,
        round_no=row.round + 1,
        feedback={
            "take_id": take_id,
            "rejected_fields": row.fields,
            "facts": music_cue_writer.facts_text(row.check_result),
            "note": text,
            "claim": was_selected,
        },
    )
    if job is None:
        await session.rollback()
        raise SoundEffectError(BUSY_MESSAGE)
    await session.commit()
    return job.id


async def lock(session: AsyncSession, project: Project, take_id: int) -> None:
    """Locks the selected take of a sound: it is never regenerated. Commits. Raises
    SoundEffectError.
    """
    _current, _view, take = await _find(session, project, take_id)
    if take.row.rejected_at is not None or not take.selected:
        raise SoundEffectError("Only the selected take of a sound can be locked. Select it first.")
    if take.row.locked_at is not None:
        return
    if not take.usable:
        raise SoundEffectError("That take has no recording yet.")
    row = await session.get(SoundEffectTake, take_id)
    assert row is not None
    row.locked_at = utcnow()
    await session.commit()
    _logger.info("sound effect take %d locked", take_id)


async def unlock(session: AsyncSession, project: Project, take_id: int) -> None:
    """Removes the lock of a take. Commits. Raises SoundEffectError."""
    _current, _view, take = await _find(session, project, take_id)
    if take.row.locked_at is None:
        return
    row = await session.get(SoundEffectTake, take_id)
    assert row is not None
    row.locked_at = None
    await session.commit()
