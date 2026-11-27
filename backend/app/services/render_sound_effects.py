"""The sound effects a render uses (EXM-007, `Explainer_music_phases.md`).

A project with the `sound_effects` switch on and a graphic or evidence sound to make
(`sound_effects.wanted`) is rendered with the **selected take** of each sound (EXM-006). This
module reads those takes, with what their technical check measured (where the loudest moment is,
how long the sound is, how loud it is), and turns them into the `SoundEffectSource` that
`story_render_plan.build_plan` reads. It reads only: it does not wait for a take to be checked
and it starts nothing.

Unlike music, a missing sound does not ask for a placement step. A sound a moment of the render
needs but that has no selected take refuses the full render (the plan says which), and gives a
warning in a scene render (`story_render_plan._sound_effects_entry`).

`story_renders` imports this module only inside the function that needs it, as it does
`render_music`.
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Project
from app.services import sound_effects, story_render_plan
from app.services.storage import StorageError, get_storage

_NOT_MEASURED: Final = (
    "The {role} sound effect could not be measured, so it cannot be placed. Select another "
    "take of it in the Sound effects step, or make it again."
)


def _file_exists(path: str | None) -> bool:
    if not path:
        return False
    try:
        return get_storage().get_path(path).is_file()
    except StorageError:
        return False


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def take_source(role: str, view: sound_effects.TakeView) -> story_render_plan.SoundEffectTakeSource:
    """The selected take of a sound as the render plan reads it. A take whose check holds no
    length or loudest moment (it was never measured) gets a `problem`.
    """
    path = view.run.run.path if view.run is not None else None
    check = view.row.check_result if isinstance(view.row.check_result, dict) else {}
    facts = check.get("facts") if isinstance(check.get("facts"), dict) else {}
    length = _number(facts.get("duration_s"))
    peak = _number(facts.get("loudest_moment_s"))
    problem = None
    if length is None or length <= 0 or peak is None or peak < 0:
        problem = _NOT_MEASURED.format(role=role)
    return story_render_plan.SoundEffectTakeSource(
        role=role,
        take_id=view.row.id,
        path=path or "",
        file_exists=_file_exists(path),
        peak_s=peak or 0.0,
        length_s=length or 0.0,
        lufs=_number(facts.get("integrated_lufs")),
        problem=problem,
    )


async def gate(
    session: AsyncSession, project: Project
) -> story_render_plan.SoundEffectSource | None:
    """What the next render does about sound effects: a source when the project has them switched
    on and needs at least one (a role with no selected take is `None` in it), or None for a
    render without them.
    """
    if not sound_effects.wanted(project):
        return None
    current = await sound_effects.state(session, project)
    takes: dict[str, story_render_plan.SoundEffectTakeSource | None] = {}
    for view in current.roles:
        takes[view.role] = (
            take_source(view.role, view.selection) if view.selection is not None else None
        )
    level = await settings_service.get_int(session, settings_service.SOUND_EFFECT_LEVEL_KEY)
    return story_render_plan.SoundEffectSource(level_db=level, takes=takes)
