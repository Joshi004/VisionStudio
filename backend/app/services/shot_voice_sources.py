"""Which voice a presenter shot of a continuous explainer is heard with (FLOW-008, F-9).

Each presenter shot has a voice source: `take` (the default: the scene's voice take plays over the
shot and the clip's own sound is dropped) or `clip` (the take is silent for exactly the shot's span
and the selected clip's own sound plays there). The owner switches it on the shot generation board
when the lips look off against the take.

Only a switched shot is stored (`shot_voice_source`, one row means `clip`). The row names the shot
plan it was set on and counts only while that plan is still the scene's newest, so planning the
scene again puts every shot back on `take`: new cuts are new windows of the take. A new take of
the clip, or selecting another take, leaves the setting alone, and changing it makes the render
out of date and nothing else.
"""

from __future__ import annotations

from typing import Final, Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ShotVoiceSource
from app.services import cut_planning_writer, shot_plans, word_timings

VoiceSource = Literal["take", "clip"]
TAKE: Final[VoiceSource] = "take"
CLIP: Final[VoiceSource] = "clip"
SOURCES: Final = (TAKE, CLIP)

PRESENTER_TYPE: Final = "presenter"


class ShotVoiceSourceError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


def offered(project: Project) -> bool:
    """Whether the project has a voice source at all: a continuous explainer."""
    return word_timings.times_takes(project)


def is_presenter_shot(plan: shot_plans.SceneEntry, shot_id: str) -> bool:
    """Whether `shot_id` is a presenter shot of the scene's newest plan, which is a cut plan."""
    content = plan.content
    if content is None or not cut_planning_writer.is_cut_plan(content):
        return False
    return any(
        shot.get("id") == shot_id and shot.get("type") == PRESENTER_TYPE
        for shot in content.get("shots", [])
    )


async def clip_shots(session: AsyncSession, project: Project) -> set[tuple[str, str]]:
    """The `(scene id, shot id)` of every presenter shot switched to its clip's voice, counting
    only the switches made on the scene's newest plan. Empty for a project that has no voice
    source.
    """
    if not offered(project):
        return set()
    rows = (
        await session.execute(
            select(ShotVoiceSource)
            .where(ShotVoiceSource.project_id == project.id)
            .execution_options(populate_existing=True)
        )
    ).scalars()
    switched = list(rows)
    if not switched:
        return set()
    plans = await shot_plans.state(session, project)
    newest = {entry.item["id"]: entry for entry in plans.entries if entry.row is not None}
    kept: set[tuple[str, str]] = set()
    for row in switched:
        entry = newest.get(row.scene_id)
        if entry is not None and entry.row is not None and entry.row.id == row.shot_plan_id:
            kept.add((row.scene_id, row.shot_id))
    return kept


async def set_source(
    session: AsyncSession, project: Project, scene_id: str, shot_id: str, source: str
) -> VoiceSource:
    """Sets the voice source of one presenter shot and commits. `take` removes the switch and
    `clip` stores it against the scene's newest plan. Raises ShotVoiceSourceError.
    """
    if source not in SOURCES:
        raise ShotVoiceSourceError("The voice source must be 'take' or 'clip'.")
    if not offered(project):
        raise ShotVoiceSourceError(
            "Only a continuous explainer has a voice source: its other projects have no take."
        )
    plans = await shot_plans.state(session, project)
    entry = next((item for item in plans.entries if item.item["id"] == scene_id), None)
    if entry is None or entry.row is None:
        raise ShotVoiceSourceError(f"The scene '{scene_id}' has no planned shots.")
    if not is_presenter_shot(entry, shot_id):
        raise ShotVoiceSourceError(
            f"The shot '{shot_id}' is not a presenter shot of the newest plan of the scene "
            f"'{scene_id}'. Only a presenter shot has a voice in its clip."
        )

    existing = (
        await session.execute(
            select(ShotVoiceSource)
            .where(
                ShotVoiceSource.project_id == project.id,
                ShotVoiceSource.scene_id == scene_id,
                ShotVoiceSource.shot_id == shot_id,
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if source == TAKE:
        if existing is not None:
            await session.execute(delete(ShotVoiceSource).where(ShotVoiceSource.id == existing.id))
    elif existing is None:
        session.add(
            ShotVoiceSource(
                project_id=project.id,
                scene_id=scene_id,
                shot_id=shot_id,
                shot_plan_id=entry.row.id,
            )
        )
    else:
        existing.shot_plan_id = entry.row.id
    await session.commit()
    return CLIP if source == CLIP else TAKE
