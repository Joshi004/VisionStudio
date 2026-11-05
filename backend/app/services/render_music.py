"""The music a story render uses (MUSIC-012, `Music_implementation_phases.md` Section 4.9).

A render takes its music from the project's newest **music placement** (MUSIC-011): where every
sound sits on the finished video's timeline, in samples. This module decides whether the next
render may use it, and turns it into the `MusicSource` that `story_render_plan.build_plan` reads.

**The rule (the owner's choice).** With music on for the project, a render needs a current
placement: not missing, not out of date, not blocked. Otherwise Render is refused, with the reason
and the way out ("place the music, or switch music off"). With music off, or when the plan has no
cue that needs a recording, the render is made without music, as before.

This module imports `music_placement`, which imports `story_renders`, so `story_renders` imports
this module only inside the functions that need it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MusicCue, MusicPlacement, Project
from app.services import music_placement, story_render_plan

_WAY_OUT: Final = "Finish the music, or switch music off in the project's settings."
NOT_PLACED_MESSAGE: Final = (
    "The music has not been placed yet. Place the music first, or switch music off in the "
    "project's settings."
)
_UNDER_VOICE: Final = ("low", "medium")


@dataclass(frozen=True)
class MusicGate:
    """What the next render does about music: a source, a reason it cannot be made, or neither
    (no music in this render).
    """

    source: story_render_plan.MusicSource | None
    blocked_reason: str | None


async def cue_mix(session: AsyncSession, inputs: Any) -> dict[str, tuple[str, bool]]:
    """How each cue of a placement sits with the voices: `(under_voice, swell_in_gaps)` by cue id,
    from the cue rows the placement was made from (`inputs.cues`).
    """
    mixes: dict[str, tuple[str, bool]] = {}
    cues = inputs.get("cues") if isinstance(inputs, dict) else None
    for entry in cues or []:
        row = await session.get(MusicCue, entry["row_id"]) if isinstance(entry, dict) else None
        if row is None or not isinstance(row.detail, dict):
            continue
        note = row.detail.get("mix")
        note = note if isinstance(note, dict) else {}
        under = note.get("under_voice")
        mixes[row.cue_id] = (
            under if under in _UNDER_VOICE else story_render_plan.UNDER_VOICE_LOW,
            note.get("swell_in_gaps") is True,
        )
    return mixes


def source_of(
    row: MusicPlacement, mixes: dict[str, tuple[str, bool]], *, ambience: bool
) -> story_render_plan.MusicSource:
    """The placement row as a render's music source."""
    return story_render_plan.MusicSource(
        placement_id=row.id,
        placement_version=row.version,
        content=row.content,
        cue_mix=mixes,
        ambience=ambience,
    )


async def gate(session: AsyncSession, project: Project) -> MusicGate:
    """Whether the next render has music, and if it must, whether it can."""
    if not project.music_enabled:
        return MusicGate(None, None)
    state = await music_placement.state(session, project)
    if state.nothing_to_place:
        return MusicGate(None, None)
    if state.blocked_reason is not None:
        return MusicGate(None, f"{state.blocked_reason} {_WAY_OUT}")
    if state.latest is None:
        return MusicGate(None, NOT_PLACED_MESSAGE)
    if state.out_of_date:
        return MusicGate(
            None,
            f"The music placement is out of date: {state.reasons[0]} Place the music again, "
            "or switch music off in the project's settings.",
        )
    mixes = await cue_mix(session, state.latest.inputs)
    return MusicGate(source_of(state.latest, mixes, ambience=project.ambience_enabled), None)


@dataclass(frozen=True)
class SceneMusicGate:
    """What the next render of a scene does about music (SCN-011): the final placement when there
    is a current one, else a provisional placement made on the story's timing, else no music.
    """

    # The music to use, or None. With `provisional` and no source (a read that did not place
    # anything) the next render would place the music then.
    source: story_render_plan.MusicSource | None
    # Why the render has no music although the project wants it, or None.
    blocked_reason: str | None
    # The music is, or would be, a provisional placement.
    provisional: bool
    # What a provisional placement is made from now (`music_placement.input_differences` compares
    # it with what a render recorded), or None when none can be made.
    provisional_inputs: dict[str, Any] | None
    # A current final placement exists: it is what `source` is.
    final_current: bool
    # The refusal and the source of the full render's own gate, for the reasons of a render that
    # was made with a final placement.
    final: MusicGate


async def scene_gate(session: AsyncSession, project: Project, *, place: bool) -> SceneMusicGate:
    """The music of the next render of a scene. A current final placement is used as the full
    render uses it. Without one, the music is placed provisionally: the story's timing with a
    placeholder for every clip that is missing, the newest placement's choices and no model call.
    With `place` False nothing is measured or placed (a read): the answer only says whether the
    render would have music, and why not.
    """
    final = await gate(session, project)
    if final.source is not None:
        return SceneMusicGate(final.source, None, False, None, True, final)
    if final.blocked_reason is None:
        # Music is off, or the plan has nothing that needs a recording.
        return SceneMusicGate(None, None, False, None, False, final)
    check = await music_placement.provisional_check(session, project)
    if check.blocked_reason is not None:
        return SceneMusicGate(None, check.blocked_reason, False, None, False, final)
    if check.inputs is None:
        return SceneMusicGate(None, None, False, None, False, final)
    if not place:
        return SceneMusicGate(None, None, True, check.inputs, False, final)
    try:
        made = await music_placement.place_provisional(session, project)
    except music_placement.MusicPlacementError as exc:
        return SceneMusicGate(None, str(exc), False, None, False, final)
    mixes = await cue_mix(session, made.inputs)
    source = story_render_plan.MusicSource(
        placement_id=0,
        placement_version=0,
        content=made.content,
        cue_mix=mixes,
        ambience=project.ambience_enabled,
        provisional=made.inputs,
    )
    return SceneMusicGate(source, None, True, made.inputs, False, final)
