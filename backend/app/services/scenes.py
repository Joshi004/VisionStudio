"""Scenes in the database (ANALYSIS.md Section 5.2; DATABASE_STRUCTURE.md Section 4.4).

A proposal replaces all the scenes of a project in one transaction (`replace_scenes`). The
scenes belong to the newest `plan_scenes` job that succeeded. That job's input records the
voiceover and the script it was made from, so the scenes are *out of date* when either has
changed since, the same way a transcript is (`services/transcripts.py`).

Editing cuts (Phase 7) rebuilds only the scenes next to the cut (`apply_cut_edit`): the
scenes that continue keep their ids, so whatever points at them keeps pointing at them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, Job, Project, Scene, Transcript
from app.jobs import store
from app.services import scene_cuts, transcript_matching
from app.services.cut_edits import CutEdit
from app.services.scene_cuts import NO_INPUTS, Cut, SceneSpec, Word, has_inputs

PLAN_JOB: Final = "plan_scenes"

StaleReason = Literal["script_changed", "voiceover_changed"]

# How many of a project's newest proposal jobs the cache looks through.
_CACHE_LOOKBACK: Final = 100


async def list_scenes(session: AsyncSession, project_id: int) -> list[Scene]:
    statement = (
        select(Scene)
        .where(Scene.project_id == project_id)
        .order_by(Scene.index)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(statement)).scalars().all())


async def scenes_with_inputs(session: AsyncSession, project_id: int) -> int:
    """How many of the project's scenes hold a description, a frame or a clip."""
    return sum(1 for scene in await list_scenes(session, project_id) if has_inputs(scene))


async def replace_scenes(
    session: AsyncSession, project_id: int, specs: Sequence[SceneSpec]
) -> list[Scene]:
    """Deletes the project's scenes and inserts the new ones. Flushes, does not commit: the
    caller commits it together with the job that made them.

    Stored files are never deleted. Deleting a scene also deletes the jobs that point at it
    (ON DELETE CASCADE): none exist before Phase 9's clip jobs.
    """
    await session.execute(delete(Scene).where(Scene.project_id == project_id))
    scenes = [
        Scene(
            project_id=project_id,
            index=spec.index,
            start_s=spec.start_s,
            end_s=spec.end_s,
            text=spec.text,
            cut_source=spec.cut_source,
            cut_note=spec.cut_note,
        )
        for spec in specs
    ]
    session.add_all(scenes)
    await session.flush()
    return scenes


async def proposal_job(session: AsyncSession, project_id: int) -> Job | None:
    """The newest proposal that succeeded: the one the project's scenes came from."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == PLAN_JOB, Job.status == "succeeded")
        .order_by(Job.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


def stale_reasons(job: Job, project: Project) -> list[StaleReason]:
    """Why the scenes of this proposal no longer fit the project's voiceover or script."""
    recorded: Any = job.input if isinstance(job.input, dict) else {}
    reasons: list[StaleReason] = []
    if recorded.get("voiceover_asset_id") != project.voiceover_asset_id:
        reasons.append("voiceover_changed")
    if recorded.get("script_sha256") != transcript_matching.script_sha256(
        project.script_text or ""
    ):
        reasons.append("script_changed")
    return reasons


async def find_cached_answer(
    session: AsyncSession,
    project_id: int,
    input_hash: str,
    exclude_job_id: int,
    job_type: str = PLAN_JOB,
    scene_id: int | None = None,
) -> Job | None:
    """The newest earlier job of this type (a proposal, unless another is named) that sent
    exactly this request and kept a usable answer. For a job type with one job per scene,
    `scene_id` looks at that scene's jobs only (the lookback window would fill up otherwise).

    Any status counts: a job that failed after the paid call (interrupted by a restart,
    say) still holds the answer it paid for (ANALYSIS.md Section 6.2, rule 3). A job that
    itself reused an answer holds none, so a hit always points at the job that paid.
    """
    statement = select(Job).where(
        Job.project_id == project_id, Job.type == job_type, Job.id != exclude_job_id
    )
    if scene_id is not None:
        statement = statement.where(Job.scene_id == scene_id)
    statement = (
        statement.order_by(Job.id.desc())
        .limit(_CACHE_LOOKBACK)
        .execution_options(populate_existing=True)
    )
    for job in (await session.execute(statement)).scalars():
        if not isinstance(job.input, dict) or job.input.get("input_hash") != input_hash:
            continue
        output = job.output
        if (
            isinstance(output, dict)
            and output.get("answer_usable") is True
            and isinstance(output.get("answer"), dict)
        ):
            return job
    return None


@dataclass(frozen=True)
class ScenesState:
    # The newest plan_scenes job, whatever its status. None if there never was one.
    job: Job | None
    # The newest one that succeeded: where the scenes came from.
    proposal: Job | None
    scenes: list[Scene]
    stale_reasons: list[StaleReason]


async def scenes_state(session: AsyncSession, project: Project) -> ScenesState:
    job = await store.latest_job(session, project.id, PLAN_JOB)
    proposal = await proposal_job(session, project.id)
    scenes = await list_scenes(session, project.id)
    reasons = stale_reasons(proposal, project) if proposal is not None and scenes else []
    return ScenesState(job=job, proposal=proposal, scenes=scenes, stale_reasons=reasons)


# --- Editing cuts (Phase 7) -----------------------------------------------------------

_NO_SCENES = "There are no scenes yet. Propose scenes first."
_PROPOSAL_RUNNING = (
    "A proposal is in progress and will replace these scenes. Edit the cuts after it finishes."
)
_SCENES_STALE = "The scenes are out of date. Propose scenes again before editing the cuts."
_SCENES_NOT_MATCHING = (
    "These scenes no longer match their transcript. Propose scenes again before editing the cuts."
)


@dataclass(frozen=True)
class CutsView:
    """What an edit works on: the words the scenes were made from and the cuts that made them."""

    words: list[Word]
    cuts: list[Cut]
    audio_end_s: float


async def lock_scenes(session: AsyncSession, project_id: int) -> None:
    """Takes SQLite's write lock before an edit reads anything it will rely on.

    The driver begins a transaction at the first write, not at a read. This write changes
    nothing, but from here on no other writer can change the scenes until this transaction
    commits, so two edits sent at once run one after the other. The second one then reads
    the scenes the first left behind.
    """
    await session.execute(
        update(Scene)
        .where(Scene.project_id == project_id)
        .values(index=Scene.index)
        .execution_options(synchronize_session=False)
    )


async def cuts_view(session: AsyncSession, project: Project, state: ScenesState) -> CutsView | str:
    """The words and cuts behind the project's scenes, or the reason they cannot be edited.

    The words come from the transcript the proposal was made from, not from the newest
    transcript: a later transcript can have slightly different times, and editing must leave
    the scenes it does not touch exactly where they are.
    """
    if not state.scenes:
        return _NO_SCENES
    if state.job is not None and state.job.status in store.ACTIVE_STATUSES:
        return _PROPOSAL_RUNNING
    if state.stale_reasons:
        return _SCENES_STALE

    recorded: Any = state.proposal.input if state.proposal is not None else None
    transcript_id = recorded.get("transcript_id") if isinstance(recorded, dict) else None
    transcript = (
        await session.get(Transcript, transcript_id) if isinstance(transcript_id, int) else None
    )
    voiceover = (
        await session.get(Asset, project.voiceover_asset_id)
        if project.voiceover_asset_id is not None
        else None
    )
    if transcript is None or voiceover is None:
        return _SCENES_NOT_MATCHING
    try:
        words = scene_cuts.words_from_script_words(transcript.script_words)
        audio_end_s = scene_cuts.end_of_audio(voiceover.duration_s, words)
        cuts = scene_cuts.cuts_from_scenes(words, state.scenes, audio_end_s)
    except ValueError:
        return _SCENES_NOT_MATCHING
    return CutsView(words=words, cuts=cuts, audio_end_s=audio_end_s)


async def apply_cut_edit(
    session: AsyncSession,
    scenes: Sequence[Scene],
    edit: CutEdit,
    specs: Sequence[SceneSpec],
    *,
    clear_inputs: bool,
) -> None:
    """Writes one cut edit: rebuilds only the scenes in the edit's range.

    `scenes` are all the project's scenes in order, `specs` the scenes that replace the
    range (`edit.new_count` of them). A scene that continues keeps its id and is updated in
    place, a split adds one row, and a merge deletes the later scene (and, by ON DELETE
    CASCADE, its jobs). Stored files are never touched. Flushes, does not commit: the caller
    commits.

    The unique key on (project_id, index) is checked row by row, so the scenes after the
    range cannot be shifted by one in a single statement without colliding. They go through
    negative numbers instead: out of the way first, back into place at the end.
    """
    kept = min(edit.old_count, edit.new_count)
    shift = edit.new_count - edit.old_count
    old_rows = list(scenes[edit.first : edit.first + edit.old_count])
    project_id = old_rows[0].project_id
    after_range = edit.first + edit.old_count

    # 1. The scenes that disappear.
    for row in old_rows[kept:]:
        await session.delete(row)
    await session.flush()

    # 2. The scenes after the range, out of the way.
    if shift != 0:
        await session.execute(
            update(Scene)
            .where(Scene.project_id == project_id, Scene.index >= after_range)
            .values(index=-(Scene.index + 1))
            .execution_options(synchronize_session=False)
        )

    # 3. The scenes that continue, rebuilt in place.
    for row, spec in zip(old_rows[:kept], specs[:kept], strict=True):
        row.start_s = spec.start_s
        row.end_s = spec.end_s
        row.text = spec.text
        row.cut_source = spec.cut_source
        row.cut_note = spec.cut_note
        if clear_inputs:
            for column, value in NO_INPUTS.items():
                setattr(row, column, value)
    await session.flush()

    # 4. The scenes that are new. A split keeps the scene's clip sound preference.
    for position, spec in enumerate(specs[kept:], start=kept):
        session.add(
            Scene(
                project_id=project_id,
                index=edit.first + position,
                start_s=spec.start_s,
                end_s=spec.end_s,
                text=spec.text,
                cut_source=spec.cut_source,
                cut_note=spec.cut_note,
                use_clip_sound=old_rows[0].use_clip_sound,
            )
        )
    await session.flush()

    # 5. The scenes after the range, back into place.
    if shift != 0:
        await session.execute(
            update(Scene)
            .where(Scene.project_id == project_id, Scene.index < 0)
            .values(index=-Scene.index - 1 + shift)
            .execution_options(synchronize_session=False)
        )
        await session.flush()
