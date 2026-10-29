"""A story project's music placement: gathering what it is made from, starting the job, saving
its versions and reading them back (MUSIC-011, `Music_implementation_phases.md` Section 4.6 and
4.7).

Every version is a new `music_placement` row, and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). `content` is what
`services/music_placer.place` made. `inputs` records what it was made from, so whether it is out
of date is worked out when it is read and never stored.

**What a placement is made from.** The newest music plan and the cue details that belong to it,
the selected take of every cue and hit, and the timeline the next render will use (the shot
cuts on frame boundaries, where the narration speech and the dialogue sit). The render's own
sources are used (`story_renders.next_render_sources`), so the placement and the render cannot
disagree about a second. Sounds are measured with `audio_measurements` (cached by file hash): the
selected takes, the narration recordings (for the silences inside them) and the clips of the shots
that matter to a hit or a sound H3 makes (for their sudden sounds).

**When music can be placed.** Music is on, a current plan exists, every cue and hit has a current
selected take, and the render's timeline can be built. Nothing is placed when the plan has no cue
that needs a recording.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, MusicPlacement, MusicPlan, Project, ShotTake, SpeechUnitAudio
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    audio_analysis,
    audio_measurements,
    music_cues,
    music_placer,
    music_takes,
    music_timeline,
    render_commands,
    story_renders,
)
from app.services import music_plan_writer as plan_writer
from app.services.music_placer import Anchor
from app.services.storage import StorageError, get_storage

JOB_TYPE: Final = "place_music"

MUSIC_OFF_MESSAGE: Final = music_cues.MUSIC_OFF_MESSAGE
NOTHING_MESSAGE: Final = "No cue of the plan needs a recording, so there is nothing to place."

# A shot whose second is this close to a moment counts as showing it.
_SHOT_MARGIN_S: Final = 1.0


class MusicPlacementError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- What the placement is made from -------------------------------------------------------


@dataclass(frozen=True)
class _Collected:
    """What can be read without measuring a sound."""

    plan: MusicPlan | None
    items: list[music_takes.ItemView]
    sources: story_renders.RenderSources | None
    loaded: music_cues.Loaded | None
    inputs: dict[str, Any] | None
    blocked_reason: str | None


def _blocked(reason: str, plan: MusicPlan | None = None) -> _Collected:
    return _Collected(plan, [], None, None, None, reason)


def _item_block(item: music_takes.ItemView) -> str | None:
    """Why this item has no take to place, or None."""
    name = item.item_id
    selection = item.selection
    if selection is None or not selection.usable:
        return f"The cue '{name}' has no recording yet. Make the music first."
    if item.reasons and not item.locked:
        return f"The recording of '{name}' is out of date: {item.reasons[0]}"
    return None


def _timeline_hash(sources: story_renders.RenderSources) -> str:
    """A fingerprint of what decides the seconds of the placement: the shots with their frames
    and selected takes, the narration with its audio, and every speech unit's span.
    """
    assert sources.plan is not None
    timeline = sources.plan.timeline
    material = {
        "fps": timeline["fps"],
        "total_frames": timeline["total_frames"],
        "shots": [
            [
                shot["scene_id"],
                shot["shot_id"],
                shot["start_frame"],
                shot["frames"],
                shot["take_id"],
            ]
            for shot in timeline["shots"]
        ],
        "narration": [
            [item["scene_id"], item["unit_id"], item["audio_id"], item["start_ms"], item["seconds"]]
            for item in timeline["narration"]
        ],
        "units": [
            [
                music_timeline.unit_ref(scene.scene_id, unit.unit_id),
                round((scene.story_start_s or 0.0) + unit.start_s, 3),
                round((scene.story_start_s or 0.0) + unit.end_s, 3),
            ]
            for scene in sources.scenes
            for unit in scene.units
        ],
    }
    voice = timeline.get("voice")
    if voice is not None:
        # A continuous explainer (FLOW-008): where each scene's take starts. Added only then, so
        # no placement of another project goes out of date. Which presenter shots use their
        # clip's own voice is not part of it: that does not move a second of the story.
        material["voice"] = [
            [take["scene_id"], take["audio_id"], take["start_ms"], take["seconds"]]
            for take in voice["takes"]
        ]
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _setting_values(session: AsyncSession) -> dict[str, int]:
    return {
        "tight_ms": await settings_service.get_int(session, settings_service.MUSIC_PLACE_TIGHT_KEY),
        "loose_ms": await settings_service.get_int(session, settings_service.MUSIC_PLACE_LOOSE_KEY),
        "widen_pct": await settings_service.get_int(
            session, settings_service.MUSIC_PLACE_WIDEN_KEY
        ),
        "crossfade_ms": await settings_service.get_int(
            session, settings_service.MUSIC_CROSSFADE_KEY
        ),
    }


def _inputs(
    plan: MusicPlan,
    items: list[music_takes.ItemView],
    sources: story_renders.RenderSources,
    values: dict[str, int],
) -> dict[str, Any]:
    rows = {
        item.cue_view.row.id: item.cue_view.row for item in items if item.cue_view.row is not None
    }
    return {
        "plan": {"id": plan.id, "version": plan.version},
        "cues": [
            {
                "cue_id": row.cue_id,
                "row_id": row.id,
                "detail_sha256": music_takes.detail_sha(row.detail),
            }
            for row in sorted(rows.values(), key=lambda row: row.cue_id)
        ],
        "takes": [
            {"item_id": item.item_id, "take_id": item.selection.row.id}
            for item in items
            if item.selection is not None
        ],
        "timeline_sha256": _timeline_hash(sources),
        "settings": values,
        "analysis_version": audio_analysis.ANALYSIS_VERSION,
        "placer_version": music_placer.PLACER_VERSION,
    }


def _with_override(
    items: list[music_takes.ItemView], override: dict[str, music_takes.TakeView]
) -> list[music_takes.ItemView]:
    """The items with the take given for an item used in place of its selected one (the preview
    of a take that is not selected). The take counts as current: it is the owner's own pick.
    """
    return [
        replace(item, selection=override[item.item_id], reasons=[], locked=False)
        if item.item_id in override
        else item
        for item in items
    ]


async def _collect(
    session: AsyncSession,
    project: Project,
    override: dict[str, music_takes.TakeView] | None = None,
) -> _Collected:
    if not project.music_enabled:
        return _blocked(MUSIC_OFF_MESSAGE)
    takes = await music_takes.state(session, project)
    plan = takes.plan
    if plan is None or takes.blocked_reason is not None:
        return _blocked(takes.blocked_reason or music_cues.NO_PLAN_MESSAGE, plan)
    if not takes.items:
        return _Collected(plan, [], None, None, None, None)
    items = _with_override(takes.items, override) if override else takes.items
    for item in items:
        reason = _item_block(item)
        if reason is not None:
            return _blocked(reason, plan)
    sources = await story_renders.next_render_sources(session, project)
    if sources.blocked_reason is not None or sources.plan is None:
        return _blocked(sources.blocked_reason or "The story cannot be rendered yet.", plan)
    loaded = await music_cues.load(session, project)
    values = await _setting_values(session)
    return _Collected(plan, items, sources, loaded, _inputs(plan, items, sources, values), None)


# --- Gathering (measures the sounds) -------------------------------------------------------


@dataclass(frozen=True)
class Gathered:
    data: music_placer.PlacementInput
    inputs: dict[str, Any]
    plan: MusicPlan
    # What could not be measured (placing goes on without it), in plain words.
    unmeasured: list[str]
    # The scenes, speech and cuts the placement was made on, to draw next to it.
    timeline: dict[str, Any]
    # The story's render sources the placement was made on (the preview builds the render's own
    # timeline from them).
    sources: story_renders.RenderSources


@dataclass(frozen=True)
class _Layout:
    spans: dict[str, tuple[float, float]]
    cuts_s: list[float]
    total_samples: int
    fps: int


def _layout(sources: story_renders.RenderSources) -> _Layout:
    """Where every scene, shot and speech unit sits on the render's own timeline: shots on
    frame boundaries, units where the render puts them.
    """
    assert sources.plan is not None
    timeline = sources.plan.timeline
    fps = int(timeline["fps"])
    spans: dict[str, tuple[float, float]] = {}
    cuts: list[float] = []
    scenes: dict[str, tuple[float, float]] = {}
    for shot in timeline["shots"]:
        start = shot["start_frame"] / fps
        end = (shot["start_frame"] + shot["frames"]) / fps
        spans[music_timeline.shot_ref(shot["scene_id"], shot["shot_id"])] = (start, end)
        if shot["start_frame"] > 0:
            cuts.append(start)
        low, high = scenes.get(shot["scene_id"], (start, end))
        scenes[shot["scene_id"]] = (min(low, start), max(high, end))
    for scene_id, span in scenes.items():
        spans[music_timeline.scene_ref(scene_id)] = span
    for scene in sources.scenes:
        if scene.story_start_s is None:
            continue
        for unit in scene.units:
            spans[music_timeline.unit_ref(scene.scene_id, unit.unit_id)] = (
                scene.story_start_s + unit.start_s,
                scene.story_start_s + unit.end_s,
            )
    total = render_commands.sample_count(int(timeline["total_frames"]), fps)
    return _Layout(spans=spans, cuts_s=sorted(cuts), total_samples=total, fps=fps)


async def _measure_file(
    session: AsyncSession, path: str | None, sha256: str | None
) -> dict[str, Any] | None:
    """The measurements of a stored file, or None when it has none (missing or unreadable)."""
    if path is None or sha256 is None:
        return None
    try:
        return await audio_measurements.measure(session, get_storage().get_path(path), sha256)
    except (StorageError, audio_measurements.MeasurementError):
        return None


async def _speech(
    session: AsyncSession,
    sources: story_renders.RenderSources,
    layout: _Layout,
    unmeasured: list[str],
) -> list[music_placer.Speech]:
    """Every narration and dialogue unit as a span of the story, with the silences measured
    inside each narration's recording (the dialogue's sound is inside its clip: its span is
    treated as all speech).
    """
    assert sources.plan is not None
    if sources.plan.timeline.get("voice") is not None:
        return await _voice_speech(session, sources, layout, unmeasured)
    speech: list[music_placer.Speech] = []
    narration = sorted(sources.plan.timeline["narration"], key=lambda item: item["start_ms"])
    for position, entry in enumerate(narration):
        start = entry["start_ms"] / 1000
        end = start + float(entry["seconds"])
        if position + 1 < len(narration):
            end = min(end, narration[position + 1]["start_ms"] / 1000)
        end = min(end, layout.total_samples / music_placer.SAMPLE_RATE)
        silences: tuple[tuple[float, float], ...] = ()
        audio = await session.get(SpeechUnitAudio, entry["audio_id"])
        measurement = (
            await _measure_file(session, audio.path, audio.sha256) if audio is not None else None
        )
        ref = music_timeline.unit_ref(entry["scene_id"], entry["unit_id"])
        if measurement is None:
            unmeasured.append(f"the narration {ref}")
        else:
            silences = tuple(
                (start + float(item["start_s"]), min(start + float(item["end_s"]), end))
                for item in measurement.get("silences") or []
                if start + float(item["start_s"]) < end
            )
        speech.append(music_placer.Speech(ref, "narration", start, end, silences))
    for scene in sources.scenes:
        if scene.story_start_s is None:
            continue
        for unit in scene.units:
            if unit.kind != "dialogue":
                continue
            ref = music_timeline.unit_ref(scene.scene_id, unit.unit_id)
            start_s, end_s = layout.spans[ref]
            speech.append(music_placer.Speech(ref, "dialogue", start_s, end_s))
    return sorted(speech, key=lambda item: item.start_s)


async def _voice_speech(
    session: AsyncSession,
    sources: story_renders.RenderSources,
    layout: _Layout,
    unmeasured: list[str],
) -> list[music_placer.Speech]:
    """The speech of a continuous explainer (FLOW-008): each unit's span in its scene's take, with
    the silences measured inside the take (they are in the take's own seconds, so they are moved
    to the story and cut to the unit).
    """
    assert sources.plan is not None
    takes = {take["scene_id"]: take for take in sources.plan.timeline["voice"]["takes"]}
    end_of_story = layout.total_samples / music_placer.SAMPLE_RATE
    speech: list[music_placer.Speech] = []
    for scene in sources.scenes:
        take = takes.get(scene.scene_id)
        if scene.story_start_s is None or take is None:
            continue
        silences: list[tuple[float, float]] = []
        audio = await session.get(SpeechUnitAudio, take["audio_id"])
        measurement = (
            await _measure_file(session, audio.path, audio.sha256) if audio is not None else None
        )
        take_start = take["start_ms"] / 1000
        if measurement is None:
            unmeasured.append(f"the voice take of {music_timeline.scene_ref(scene.scene_id)}")
        else:
            silences = [
                (take_start + float(item["start_s"]), take_start + float(item["end_s"]))
                for item in measurement.get("silences") or []
            ]
        for unit in scene.units:
            ref = music_timeline.unit_ref(scene.scene_id, unit.unit_id)
            start, end = layout.spans[ref]
            end = min(end, end_of_story)
            inside = tuple(
                (max(low, start), min(high, end))
                for low, high in silences
                if low < end and high > start
            )
            speech.append(music_placer.Speech(ref, unit.kind, start, end, inside))
    return sorted(speech, key=lambda item: item.start_s)


def _first_shot_of_characters(plan: MusicPlan, loaded: music_cues.Loaded) -> dict[str, str]:
    """The first shot, in story order, that shows each character, by the character's id."""
    first: dict[str, str] = {}
    for shot in sorted(plan.timeline["shots"], key=lambda item: item["start_s"]):
        for character_id in loaded.shot_characters.get(shot["ref"], []):
            first.setdefault(character_id, shot["ref"])
    return first


def _is_first_entrance(
    cue: dict[str, Any], themes: dict[str, dict[str, Any]], first_shots: dict[str, str]
) -> bool:
    """Whether a themed score cue starts on the first shot that shows its theme's character."""
    if cue["kind"] != plan_writer.KIND_SCORE or not cue.get("theme_id"):
        return False
    stands_for = (themes.get(cue["theme_id"]) or {}).get("stands_for") or {}
    if stands_for.get("kind") != "character":
        return False
    return first_shots.get(str(stands_for.get("ref"))) == cue["start"]["ref"]


def _sound_of(
    item: music_takes.ItemView,
    measurement: dict[str, Any],
    *,
    important_start: bool,
) -> music_placer.Sound:
    """The selected take of an item as a sound to place."""
    selection = item.selection
    row = item.cue_view.row
    assert selection is not None and selection.run is not None and row is not None
    cue = item.cue_view.cue
    detail: dict[str, Any] = row.detail
    run = selection.run.run
    common: dict[str, Any] = {
        "item_id": item.item_id,
        "cue_id": cue["id"],
        "role": str(item.item["role"]),
        "intensity": int(cue.get("intensity") or 0),
        "take_id": selection.row.id,
        "lab_run_id": selection.row.lab_run_id,
        "path": str(run.path),
        "sha256": str(run.sha256),
        "duration_s": float(measurement.get("duration_s") or 0.0),
        "measurement": measurement,
    }
    if item.item["role"] == "hit":
        hit_id = item.item_id.split("/", 1)[1]
        hit = next((h for h in detail.get("hit_requests", []) if h["id"] == hit_id), None)
        if hit is None:
            raise MusicPlacementError(f"The cue '{cue['id']}' has no hit '{hit_id}'.")
        return music_placer.Sound(
            **common, kind="hit", summary=str(hit["description"]), at=Anchor.of(hit["at"])
        )
    if cue["kind"] in plan_writer.SPAN_KINDS:
        return music_placer.Sound(
            **common,
            kind=str(cue["kind"]),
            summary=str(cue["summary"]),
            start=Anchor.of(detail["start"]),
            end=Anchor.of(detail["end"]),
            start_style=cue.get("start_style"),
            end_style=cue.get("end_style"),
            fade_in_s=detail.get("fade_in_s"),
            fade_out_s=detail.get("fade_out_s"),
            mood_changes=tuple(
                Anchor.of(step["until"])
                for step in detail.get("internal_order", [])
                if step.get("until")
            ),
            important_start=important_start,
        )
    return music_placer.Sound(
        **common, kind=str(cue["kind"]), summary=str(cue["summary"]), at=Anchor.of(detail["at"])
    )


def _clip_shot_refs(
    anchor: Anchor,
    layout: _Layout,
    event_shots: dict[str, tuple[str, ...]],
) -> list[str]:
    """The shots whose H3 sound may hold the moment an anchor points at."""
    if anchor.ref in event_shots:
        return list(event_shots[anchor.ref])
    if anchor.ref.startswith(f"{music_timeline.SHOT_PREFIX}:"):
        return [anchor.ref]
    return [
        ref
        for ref, (start, end) in layout.spans.items()
        if ref.startswith(f"{music_timeline.SHOT_PREFIX}:")
        and start - _SHOT_MARGIN_S <= anchor.seconds <= end + _SHOT_MARGIN_S
    ]


async def _clips(
    session: AsyncSession,
    sources: story_renders.RenderSources,
    layout: _Layout,
    refs: set[str],
    unmeasured: list[str],
) -> dict[str, music_placer.Clip]:
    """The sudden sounds of the H3 clip of each shot in `refs`, on the story's seconds."""
    assert sources.plan is not None
    clips: dict[str, music_placer.Clip] = {}
    by_ref = {
        music_timeline.shot_ref(shot["scene_id"], shot["shot_id"]): shot
        for shot in sources.plan.timeline["shots"]
    }
    for ref in sorted(refs):
        shot = by_ref.get(ref)
        if shot is None or not shot["has_audio"]:
            continue
        take = await session.get(ShotTake, shot["take_id"])
        measurement = (
            await _measure_file(session, take.path, take.sha256) if take is not None else None
        )
        if measurement is None:
            unmeasured.append(f"the sound of the clip {ref}")
            continue
        start, end = layout.spans[ref]
        onsets = tuple(
            (start + float(item["time_s"]), float(item.get("strength") or 0.0))
            for item in measurement.get("onsets") or []
        )
        clips[ref] = music_placer.Clip(ref, start, end, onsets)
    return clips


def _timeline_summary(
    sources: story_renders.RenderSources, layout: _Layout, world: music_placer.World
) -> dict[str, Any]:
    """What the panel draws next to the music: the scenes, the speech and the shot cuts, in
    seconds of the render's own timeline.
    """
    scenes = []
    for scene in sources.scenes:
        ref = music_timeline.scene_ref(scene.scene_id)
        if ref in layout.spans:
            start, end = layout.spans[ref]
            scenes.append(
                {
                    "ref": ref,
                    "title": scene.title,
                    "start_s": round(start, 3),
                    "end_s": round(end, 3),
                }
            )
    return {
        "total_s": round(layout.total_samples / music_placer.SAMPLE_RATE, 3),
        "scenes": scenes,
        "speech": [
            {
                "ref": unit.ref,
                "kind": unit.kind,
                "start_s": round(unit.start_s, 3),
                "end_s": round(unit.end_s, 3),
            }
            for unit in world.speech
        ],
        "cuts_s": [round(cut, 3) for cut in layout.cuts_s],
    }


async def gather(
    session: AsyncSession,
    project: Project,
    override: dict[str, music_takes.TakeView] | None = None,
) -> Gathered:
    """Everything `music_placer.place` needs, with the sounds measured. Raises
    `MusicPlacementError` when music cannot be placed now. `override` is a take for an item
    (by item id) to use instead of the selected one: the preview of a take that is not selected
    yet. A placement is never saved from it.
    """
    collected = await _collect(session, project, override)
    if collected.blocked_reason is not None:
        raise MusicPlacementError(collected.blocked_reason)
    plan = collected.plan
    sources = collected.sources
    loaded = collected.loaded
    if plan is None or sources is None or loaded is None or collected.inputs is None:
        raise MusicPlacementError(NOTHING_MESSAGE)
    assert sources.plan is not None

    unmeasured: list[str] = []
    layout = _layout(sources)
    values: dict[str, int] = collected.inputs["settings"]
    params = music_placer.Params(
        tight_s=values["tight_ms"] / 1000,
        loose_s=values["loose_ms"] / 1000,
        widen_factor=values["widen_pct"] / 100,
        crossfade_s=values["crossfade_ms"] / 1000,
        fps=layout.fps,
    )

    themes = {
        theme["id"]: theme
        for theme in (loaded.bible.content.get("themes", []) if loaded.bible is not None else [])
    }
    first_shots = _first_shot_of_characters(plan, loaded)

    sounds: list[music_placer.Sound] = []
    for item in collected.items:
        selection = item.selection
        assert selection is not None and selection.run is not None
        run = selection.run.run
        measurement = await _measure_file(session, run.path, run.sha256)
        if measurement is None:
            raise MusicPlacementError(
                f"The recording of '{item.item_id}' could not be measured. Make it again."
            )
        cue = item.cue_view.cue
        sounds.append(
            _sound_of(
                item,
                measurement,
                important_start=_is_first_entrance(cue, themes, first_shots),
            )
        )

    event_shots = {
        entry["ref"]: tuple(ref for ref in entry["shots"] if ref in layout.spans)
        for entry in plan.timeline["events"]
        if entry["type"] == "sound_event" and entry.get("shots")
    }
    h3_sounds = [
        music_placer.H3Sound(
            cue_id=cue["id"],
            summary=str(cue["summary"]),
            at=Anchor.of(cue["at"]),
            shot_ref=cue["sound_request"]["shot"],
            event_ref=cue["sound_request"]["event"],
        )
        for cue in plan.content["cues"]
        if cue["kind"] == plan_writer.KIND_POINT
        and cue["maker"] == plan_writer.MAKER_H3
        and cue.get("sound_request")
    ]

    clip_refs: set[str] = {sound.shot_ref for sound in h3_sounds}
    for sound in sounds:
        if sound.at is not None:
            clip_refs.update(_clip_shot_refs(sound.at, layout, event_shots))
    for h3 in h3_sounds:
        clip_refs.update(_clip_shot_refs(h3.at, layout, event_shots))

    world = music_placer.World(
        total_samples=layout.total_samples,
        cuts_s=tuple(layout.cuts_s),
        speech=tuple(await _speech(session, sources, layout, unmeasured)),
        spans={**layout.spans, **music_placer.event_spans(plan.timeline, layout.spans)},
        event_shots=event_shots,
        clips=await _clips(session, sources, layout, clip_refs, unmeasured),
    )
    boundaries = tuple(
        music_placer.Boundary(item["from"], item["to"], item["join"])
        for item in plan.content.get("boundaries", [])
    )
    data = music_placer.PlacementInput(
        params=params,
        world=world,
        sounds=tuple(sounds),
        h3_sounds=tuple(h3_sounds),
        boundaries=boundaries,
    )
    return Gathered(
        data=data,
        inputs=collected.inputs,
        plan=plan,
        unmeasured=unmeasured,
        timeline=_timeline_summary(sources, layout, world),
        sources=sources,
    )


@dataclass(frozen=True)
class Previewable:
    """What a preview can be asked for: the scenes of the story and the cues of the plan."""

    scene_ids: frozenset[str]
    cue_ids: frozenset[str]


async def check_preview(
    session: AsyncSession,
    project: Project,
    override: dict[str, music_takes.TakeView] | None = None,
) -> Previewable:
    """Whether the music can be previewed now (nothing is measured). Raises
    `MusicPlacementError` with the reason when it cannot.
    """
    collected = await _collect(session, project, override)
    if collected.blocked_reason is not None:
        raise MusicPlacementError(collected.blocked_reason)
    plan, sources = collected.plan, collected.sources
    if plan is None or sources is None or not collected.items:
        raise MusicPlacementError(NOTHING_MESSAGE)
    return Previewable(
        scene_ids=frozenset(scene.scene_id for scene in sources.scenes),
        cue_ids=frozenset(str(cue["id"]) for cue in plan.content["cues"]),
    )


# --- Saving and reading versions -----------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> MusicPlacement | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(MusicPlacement)
        .where(MusicPlacement.project_id == project_id)
        .order_by(MusicPlacement.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def list_versions(session: AsyncSession, project_id: int) -> list[MusicPlacement]:
    """Every version of the project, newest first."""
    statement = (
        select(MusicPlacement)
        .where(MusicPlacement.project_id == project_id)
        .order_by(MusicPlacement.version.desc())
    )
    return list((await session.execute(statement)).scalars())


async def get_version(
    session: AsyncSession, project_id: int, version: int
) -> MusicPlacement | None:
    """One version of the project, or None when there is no such version."""
    statement = select(MusicPlacement).where(
        MusicPlacement.project_id == project_id, MusicPlacement.version == version
    )
    return (await session.execute(statement)).scalars().first()


async def save_placement(
    session: AsyncSession,
    *,
    project_id: int,
    plan_id: int,
    job_id: int,
    inputs: dict[str, Any],
    content: dict[str, Any],
) -> MusicPlacement:
    """Adds the next version. Flushes but does not commit: the job commits it together with
    finishing itself, so a job is never "succeeded" without its result.
    """
    statement = select(func.max(MusicPlacement.version)).where(
        MusicPlacement.project_id == project_id
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = MusicPlacement(
        project_id=project_id,
        version=(highest or 0) + 1,
        plan_id=plan_id,
        job_id=job_id,
        inputs=inputs,
        content=content,
    )
    session.add(row)
    await session.flush()
    return row


# --- Reading the state ---------------------------------------------------------------------


def _out_of_date_reasons(row: MusicPlacement, current: dict[str, Any]) -> list[str]:
    """Why a stored placement no longer matches what it would be made from, one sentence each."""
    saved = row.inputs if isinstance(row.inputs, dict) else {}
    reasons: list[str] = []
    if saved.get("plan") != current["plan"]:
        reasons.append("The music plan was written again since the music was placed.")
    if saved.get("cues") != current["cues"]:
        reasons.append("A cue was detailed again since the music was placed.")
    if saved.get("takes") != current["takes"]:
        reasons.append("A take was selected again since the music was placed.")
    if saved.get("timeline_sha256") != current["timeline_sha256"]:
        reasons.append(
            "The story's timeline changed since the music was placed (a shot take, the "
            "narration or a shot plan is different)."
        )
    if saved.get("settings") != current["settings"]:
        reasons.append("A placement setting has changed since the music was placed.")
    if (
        saved.get("analysis_version") != current["analysis_version"]
        or saved.get("placer_version") != current["placer_version"]
    ):
        reasons.append("The way sounds are measured or placed has changed.")
    return reasons


@dataclass(frozen=True)
class MusicPlacementState:
    """What the story workspace shows."""

    latest: MusicPlacement | None
    versions: list[MusicPlacement]
    # The newest job, whatever its status.
    job: Job | None
    out_of_date: bool
    reasons: list[str]
    # Why the music cannot be placed now, or None.
    blocked_reason: str | None
    music_enabled: bool
    # The plan has no cue that needs a recording: there is nothing to place.
    nothing_to_place: bool

    @property
    def active(self) -> bool:
        return self.job is not None and self.job.status in store.ACTIVE_STATUSES


@memoized_state
async def state(session: AsyncSession, project: Project) -> MusicPlacementState:
    """The project's music placement with where it stands. Worked out on every read; nothing
    here is stored and no sound is measured.
    """
    collected = await _collect(session, project)
    newest = await latest(session, project.id)
    reasons = (
        _out_of_date_reasons(newest, collected.inputs)
        if newest is not None and collected.inputs is not None
        else []
    )
    return MusicPlacementState(
        latest=newest,
        versions=await list_versions(session, project.id),
        job=await store.latest_job(session, project.id, JOB_TYPE),
        out_of_date=bool(reasons),
        reasons=reasons,
        blocked_reason=collected.blocked_reason,
        music_enabled=project.music_enabled,
        nothing_to_place=(
            project.music_enabled
            and collected.blocked_reason is None
            and collected.plan is not None
            and not collected.items
        ),
    )


# --- Starting a run ------------------------------------------------------------------------


async def start_run(session: AsyncSession, project: Project) -> Job:
    """Queues the job that places the music, and commits. If a placement job is already waiting
    or running, that job is returned and no new one is made.
    """
    collected = await _collect(session, project)
    if collected.blocked_reason is not None:
        raise MusicPlacementError(collected.blocked_reason)
    plan = collected.plan
    if plan is None or not collected.items:
        raise MusicPlacementError(NOTHING_MESSAGE)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={"plan_id": plan.id, "plan_version": plan.version},
    )
    return job
