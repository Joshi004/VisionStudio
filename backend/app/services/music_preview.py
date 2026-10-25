"""Hear the music in context (MUSIC-012, `Music_implementation_phases.md` Section 4.9, MD-20).

A **preview** is a short sound-only file of the story's own mix: the shots' sound, the narration
and the music, made with the same timeline builder (`story_render_plan.build_plan`), the same
filters and the same loudness target as the final render, for one window of the story: a scene,
or a cue's placed span with two seconds on each side. It is the `preview_music_mix` job
(`jobs/preview_music_mix.py`), a local job: nothing is paid for and no model is asked.

The preview of a cue can be made with a take that is **not** selected. The pure placer
(`music_placer.place`) then runs again with that take in place of the selected one, and the
choices the language model made for the newest placement are reused (matched by the moment's
description; a choice that cannot be matched is left to the code). Nothing is saved from it.

This module starts a preview, works out the timeline and window a preview job renders, and reads
the newest preview. It imports `story_renders` and `music_placement`, and is imported by neither.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Project
from app.jobs import store
from app.services import (
    music_placement,
    music_placer,
    music_takes,
    render_commands,
    render_music,
    story_render_plan,
    story_renders,
)

JOB_TYPE: Final = "preview_music_mix"
# How much of the story is heard before and after a cue's own span.
PAD_S: Final = 2.0
_SCENE: Final = "scene"
_CUE: Final = "cue"
_NO_TAKE_AUDIO: Final = "That take has no sound to preview."
_NO_SUCH_TAKE: Final = "That take does not belong to a cue of the current plan."
_NO_SUCH_SCENE: Final = "The story has no such scene."
_NO_SUCH_CUE: Final = "The music plan has no such cue."
_ONE_TARGET: Final = "A preview is of one scene or one cue."
_MUSIC_OFF: Final = "Music is switched off for this project."
_NO_MUSIC_IN_CUE: Final = (
    "This cue has no music in the video (it may be a sound that the video model makes, or "
    "ambience, which is switched off)."
)


class MusicPreviewError(ValueError):
    """A preview that cannot be made. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class Target:
    """What a preview is of. Exactly one of `scene_id` and `cue_id`; `take_id` is a take to hear in
    place of the selected one.
    """

    scene_id: str | None
    cue_id: str | None
    take_id: int | None

    @property
    def key(self) -> str:
        """Two requests with the same key are the same preview (the job's `dedupe_key`)."""
        what = f"{_SCENE}:{self.scene_id}" if self.scene_id is not None else f"{_CUE}:{self.cue_id}"
        return f"{what}|take:{self.take_id}"

    def as_input(self) -> dict[str, Any]:
        return {
            "target": self.key,
            "scene_id": self.scene_id,
            "cue_id": self.cue_id,
            "take_id": self.take_id,
        }

    @classmethod
    def of_input(cls, job_input: Any) -> Target:
        """The target a preview job was made for."""
        raw = job_input if isinstance(job_input, dict) else {}
        scene_id, cue_id, take_id = raw.get("scene_id"), raw.get("cue_id"), raw.get("take_id")
        if (
            (scene_id is None) == (cue_id is None)
            or not (scene_id is None or isinstance(scene_id, str))
            or not (cue_id is None or isinstance(cue_id, str))
            or not (take_id is None or (isinstance(take_id, int) and not isinstance(take_id, bool)))
        ):
            raise MusicPreviewError("The preview's request cannot be read. Ask for it again.")
        return cls(scene_id, cue_id, take_id)


@dataclass(frozen=True)
class PreviewPlan:
    """What the preview job renders: the render's timeline (version 2, with the music) and the
    window of it, in samples at 48 kHz.
    """

    timeline: dict[str, Any]
    start_sample: int
    end_sample: int


async def _override(
    session: AsyncSession, project: Project, take_id: int | None
) -> dict[str, music_takes.TakeView] | None:
    """The take to hear, by the id of its item, or None when the selected takes are heard."""
    if take_id is None:
        return None
    state = await music_takes.state(session, project)
    for item in state.items:
        for take in item.takes:
            if take.row.id == take_id:
                if not take.usable:
                    raise MusicPreviewError(_NO_TAKE_AUDIO)
                return {item.item_id: take}
    raise MusicPreviewError(_NO_SUCH_TAKE)


def _target_error(target: Target, known: music_placement.Previewable) -> None:
    if (target.scene_id is None) == (target.cue_id is None):
        raise MusicPreviewError(_ONE_TARGET)
    if target.scene_id is not None and target.scene_id not in known.scene_ids:
        raise MusicPreviewError(_NO_SUCH_SCENE)
    if target.cue_id is not None and target.cue_id not in known.cue_ids:
        raise MusicPreviewError(_NO_SUCH_CUE)


async def start(session: AsyncSession, project: Project, target: Target) -> Job:
    """Queues the preview job, and commits. A preview of the same target that is already waiting
    or running is returned instead of a second one. Raises `MusicPreviewError` with the reason
    when a preview cannot be made now.
    """
    if not project.music_enabled:
        raise MusicPreviewError(_MUSIC_OFF)
    override = await _override(session, project, target.take_id)
    try:
        known = await music_placement.check_preview(session, project, override)
    except music_placement.MusicPlacementError as exc:
        raise MusicPreviewError(str(exc)) from exc
    _target_error(target, known)
    if override is None:
        gate = await render_music.gate(session, project)
        if gate.blocked_reason is not None:
            raise MusicPreviewError(gate.blocked_reason)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input=target.as_input(),
        dedupe_key="target",
    )
    return job


async def latest_job(session: AsyncSession, project_id: int) -> Job | None:
    """The project's newest preview job, whatever its status and target."""
    return await store.latest_job(session, project_id, JOB_TYPE)


# --- What a preview job renders ------------------------------------------------------------


def _choices_for(
    first: music_placer.PlacementResult, stored: dict[str, Any] | None
) -> dict[str, str | None]:
    """The answers to the placer's questions, taken from the newest placement's own choices:
    the same question (by id) with the same picked moment (by description). `None` for a question
    that has no such answer.
    """
    picked = {
        str(entry["id"]): entry.get("picked")
        for entry in (stored or {}).get("choices") or []
        if isinstance(entry, dict) and "id" in entry
    }
    answers: dict[str, str | None] = {}
    for question in first.pending:
        wanted = picked.get(question["id"])
        answers[question["id"]] = next(
            (c["id"] for c in question["candidates"] if wanted and c["description"] == wanted),
            None,
        )
    return answers


async def _source_with_take(
    session: AsyncSession,
    project: Project,
    override: dict[str, music_takes.TakeView],
) -> tuple[story_renders.RenderSources, story_render_plan.MusicSource]:
    """The render's sources, and the music placed again with the take in place of the selected."""
    gathered = await music_placement.gather(session, project, override)
    first = music_placer.place(gathered.data)
    newest = await music_placement.latest(session, project.id)
    final = first
    if first.pending:
        final = music_placer.place(
            gathered.data, _choices_for(first, newest.content if newest is not None else None)
        )
    mixes = await render_music.cue_mix(session, gathered.inputs)
    source = story_render_plan.MusicSource(
        placement_id=newest.id if newest is not None else 0,
        placement_version=newest.version if newest is not None else 0,
        content=final.content,
        cue_mix=mixes,
        ambience=project.ambience_enabled,
    )
    return gathered.sources, source


def _window(timeline: dict[str, Any], target: Target) -> tuple[int, int]:
    """The window of the story to hear, in samples: the scene's shots, or the cue's placed sounds
    with `PAD_S` before and after.
    """
    fps = int(timeline["fps"])
    total = render_commands.sample_count(int(timeline["total_frames"]), fps)
    if target.scene_id is not None:
        shots = [shot for shot in timeline["shots"] if shot["scene_id"] == target.scene_id]
        if not shots:
            raise MusicPreviewError(_NO_SUCH_SCENE)
        start = render_commands.sample_count(min(shot["start_frame"] for shot in shots), fps)
        end = render_commands.sample_count(
            max(shot["start_frame"] + shot["frames"] for shot in shots), fps
        )
        return start, min(end, total)

    music = timeline.get("music") or {}
    spans = [
        (int(sound["start_sample"]), int(sound["start_sample"]) + int(sound["length_samples"]))
        for sound in music.get("sounds") or []
        if sound["cue_id"] == target.cue_id
    ]
    if not spans:
        raise MusicPreviewError(_NO_MUSIC_IN_CUE)
    pad = round(PAD_S * render_commands.SAMPLE_RATE)
    return max(0, min(a for a, _ in spans) - pad), min(total, max(b for _, b in spans) + pad)


async def build(session: AsyncSession, project: Project, target: Target) -> PreviewPlan:
    """The timeline and window a preview job renders. Raises `MusicPreviewError` when the music
    or the story cannot be previewed now.
    """
    mix = await story_renders.mix_settings(session)
    try:
        override = await _override(session, project, target.take_id)
        if override is not None:
            sources, source = await _source_with_take(session, project, override)
        else:
            gate = await render_music.gate(session, project)
            if gate.blocked_reason is not None or gate.source is None:
                raise MusicPreviewError(gate.blocked_reason or _NO_MUSIC_IN_CUE)
            sources = await story_renders.next_render_sources(session, project)
            source = gate.source
        if sources.blocked_reason is not None or sources.plan is None:
            raise MusicPreviewError(sources.blocked_reason or "The story cannot be rendered now.")
        plan = story_render_plan.build_plan(
            sources.scenes,
            fps=project.fps,
            width=project.out_width,
            height=project.out_height,
            mix=mix,
            music=source,
        )
    except (music_placement.MusicPlacementError, story_render_plan.RenderPlanError) as exc:
        raise MusicPreviewError(str(exc)) from exc
    start, end = _window(plan.timeline, target)
    return PreviewPlan(timeline=plan.timeline, start_sample=start, end_sample=end)
