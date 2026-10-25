"""The condensed story timeline that the music plan is written against (MUSIC-008,
`Music_implementation_phases.md` Section 4.3, level 1, and Section 4.4). Pure functions: no I/O,
no clock.

The shot plans give every scene's shots and speech units exact seconds
(`services/scene_timeline.py`). This module lays all scenes end to end, in seconds from the start
of the story, and keeps what music needs: scenes with their moods, shot cuts, speech units with
their text and speaker, events with their times, pauses, sound events and the gaps between
lines. It is the one thing the model reads about timing, and what anchors are resolved against.

**Story-wide references.** Ids of events, units and shots restart in every scene and are
renumbered with every version, so an anchor names a thing by a reference that carries its scene:

- `scene:<scene_id>`
- `shot:<scene_id>/<shot_id>`
- `unit:<scene_id>/<unit_id>`
- `event:<scene_id>/<event_id>`

Scene ids are slugs (lower case, digits and underscores), so `:` and `/` cannot clash with them.
The model never makes a reference up: code checks every one against `Index`.

**Time of an event.** An event has no time of its own. It is the time of the speech units that
voice it (the first unit's start to the last unit's end); an event that no unit voices (an
action, a sound event, a pause) takes the time of the shots that show it
(`source_event_ids`: the first such shot's start to the last such shot's end). An event that
neither a unit nor a shot carries is left out.

**Off screen.** No stored field marks a voice as off screen. A dialogue line counts as off
screen when its speaker is not among the characters the scene's definition chose.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final

from app.services import scene_timeline

# A gap between two speech units shorter than this is not listed: music cannot use it.
MIN_GAP_S: Final = 1.0
# How much of a spoken line, a shot description or an event the model is shown.
TEXT_MAX_CHARS: Final = 200
_DECIMALS: Final = 3

SCENE_PREFIX: Final = "scene"
SHOT_PREFIX: Final = "shot"
UNIT_PREFIX: Final = "unit"
EVENT_PREFIX: Final = "event"
REF_PREFIXES: Final = (SCENE_PREFIX, SHOT_PREFIX, UNIT_PREFIX, EVENT_PREFIX)

EDGES: Final = ("start", "end")


def scene_ref(scene_id: str) -> str:
    return f"{SCENE_PREFIX}:{scene_id}"


def shot_ref(scene_id: str, shot_id: str) -> str:
    return f"{SHOT_PREFIX}:{scene_id}/{shot_id}"


def unit_ref(scene_id: str, unit_id: str) -> str:
    return f"{UNIT_PREFIX}:{scene_id}/{unit_id}"


def event_ref(scene_id: str, event_id: str) -> str:
    return f"{EVENT_PREFIX}:{scene_id}/{event_id}"


@dataclass(frozen=True)
class SceneInput:
    """What the timeline needs of one scene. The caller has checked that its shot plan is
    current and its timeline has no blocking problem.
    """

    scene_id: str
    title: str
    # Where the scene starts in the story, in seconds.
    story_start_s: float
    timeline: scene_timeline.SceneTimeline
    # The stored lists of the newest shot plan, speech units and events of the scene.
    shots: list[dict[str, Any]]
    units: list[dict[str, Any]]
    events: list[dict[str, Any]]
    # The scene definition's mood (`start`, `middle`, `end`) and the ids of the characters it
    # chose.
    mood: dict[str, Any]
    characters: list[str]
    # Character names by id, to show a speaker by name.
    names: dict[str, str]


def _short(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= TEXT_MAX_CHARS:
        return one_line
    return one_line[: TEXT_MAX_CHARS - 3].rstrip() + "..."


def _round(value: float) -> float:
    return round(value, _DECIMALS)


def _unit_entries(scene: SceneInput) -> list[dict[str, Any]]:
    """The scene's speech units that some shot carries, in story seconds."""
    stored = {unit["id"]: unit for unit in scene.units}
    entries: list[dict[str, Any]] = []
    for span in scene.timeline.units:
        unit = stored.get(span.unit_id)
        if unit is None:
            continue
        speaker_id = unit.get("speaker_id")
        entries.append(
            {
                "ref": unit_ref(scene.scene_id, span.unit_id),
                "scene_id": scene.scene_id,
                "kind": span.kind,
                "speaker": scene.names.get(speaker_id, speaker_id) if speaker_id else None,
                "off_screen": bool(
                    span.kind == "dialogue"
                    and speaker_id is not None
                    and speaker_id not in scene.characters
                ),
                "text": _short(unit.get("text") or ""),
                "start_s": _round(scene.story_start_s + span.start_s),
                "end_s": _round(scene.story_start_s + span.end_s),
                "event_id": unit.get("event_id"),
            }
        )
    return entries


def _shot_entries(scene: SceneInput) -> list[dict[str, Any]]:
    stored = {shot["id"]: shot for shot in scene.shots}
    entries: list[dict[str, Any]] = []
    for span in scene.timeline.shots:
        shot = stored[span.shot_id]
        entries.append(
            {
                "ref": shot_ref(scene.scene_id, span.shot_id),
                "scene_id": scene.scene_id,
                "type": shot.get("type"),
                "description": _short(shot.get("description") or ""),
                "start_s": _round(scene.story_start_s + span.start_s),
                "end_s": _round(scene.story_start_s + span.end_s),
                "event_ids": list(shot.get("source_event_ids") or []),
            }
        )
    return entries


def _event_entries(
    scene: SceneInput, units: list[dict[str, Any]], shots: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    units_of: dict[str, list[dict[str, Any]]] = {}
    for unit in units:
        units_of.setdefault(unit["event_id"], []).append(unit)
    shots_of: dict[str, list[dict[str, Any]]] = {}
    for shot in shots:
        for event_id in shot["event_ids"]:
            shots_of.setdefault(event_id, []).append(shot)

    entries: list[dict[str, Any]] = []
    for event in scene.events:
        event_id = event["id"]
        voiced = units_of.get(event_id)
        shown = shots_of.get(event_id, [])
        carriers = voiced or shown
        if not carriers:
            continue
        kind = event["type"]
        entry: dict[str, Any] = {
            "ref": event_ref(scene.scene_id, event_id),
            "scene_id": scene.scene_id,
            "type": kind,
            "start_s": min(item["start_s"] for item in carriers),
            "end_s": max(item["end_s"] for item in carriers),
            "time_from": "unit" if voiced else "shot",
            # The shots that show it: a point sound that H3 makes must sit in one of them.
            "shots": [shot["ref"] for shot in shown],
        }
        if kind in ("action", "sound_event"):
            entry["description"] = _short(event.get("description") or "")
        if voiced:
            entry["units"] = [unit["ref"] for unit in voiced]
        entries.append(entry)
    return entries


def _gaps(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The silences between consecutive speech units of the whole story, at least `MIN_GAP_S`."""
    ordered = sorted(units, key=lambda unit: (unit["start_s"], unit["end_s"]))
    gaps: list[dict[str, Any]] = []
    for before, after in zip(ordered, ordered[1:], strict=False):
        length = after["start_s"] - before["end_s"]
        if length >= MIN_GAP_S:
            gaps.append(
                {
                    "after": before["ref"],
                    "before": after["ref"],
                    "start_s": before["end_s"],
                    "end_s": after["start_s"],
                }
            )
    return gaps


def build(scenes: list[SceneInput]) -> dict[str, Any]:
    """The condensed timeline of the whole story, in seconds from its start, scenes in story
    order. Every list is in time order.
    """
    scene_entries: list[dict[str, Any]] = []
    shot_entries: list[dict[str, Any]] = []
    unit_entries: list[dict[str, Any]] = []
    event_entries: list[dict[str, Any]] = []
    total = 0.0
    for scene in scenes:
        units = _unit_entries(scene)
        shots = _shot_entries(scene)
        end = _round(scene.story_start_s + scene.timeline.total_s)
        scene_entries.append(
            {
                "ref": scene_ref(scene.scene_id),
                "id": scene.scene_id,
                "title": scene.title,
                "start_s": _round(scene.story_start_s),
                "end_s": end,
                "mood": scene.mood,
            }
        )
        unit_entries.extend(units)
        shot_entries.extend(shots)
        event_entries.extend(_event_entries(scene, units, shots))
        total = max(total, end)
    return {
        "total_s": total,
        "scenes": scene_entries,
        "shots": shot_entries,
        "units": unit_entries,
        "events": event_entries,
        "gaps": _gaps(unit_entries),
    }


def sha256(timeline: dict[str, Any]) -> str:
    """A fingerprint of the timeline, to tell later whether it has changed."""
    text = json.dumps(timeline, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Looking things up ---------------------------------------------------------------------


@dataclass(frozen=True)
class Index:
    """What anchors are checked and resolved against."""

    total_s: float
    # Start and end in story seconds, by reference.
    spans: dict[str, tuple[float, float]]
    # For each sound event, the references of the shots that show it.
    sound_event_shots: dict[str, frozenset[str]]


def index_of(timeline: dict[str, Any]) -> Index:
    """The lookup tables of a timeline made by `build` (or read back from storage)."""
    spans: dict[str, tuple[float, float]] = {}
    for group in ("scenes", "shots", "units", "events"):
        for entry in timeline[group]:
            spans[entry["ref"]] = (float(entry["start_s"]), float(entry["end_s"]))
    sound_events = {
        entry["ref"]: frozenset(entry["shots"])
        for entry in timeline["events"]
        if entry["type"] == "sound_event"
    }
    return Index(total_s=float(timeline["total_s"]), spans=spans, sound_event_shots=sound_events)


def resolve(index: Index, ref: str, edge: str, relation: str) -> float | None:
    """The story second an anchor points at, or None when its reference does not exist.

    This is the nominal point, to show and to order by. It is the start or end of the thing,
    or its middle for `under` (somewhere inside it). The exact sample is found later, by code,
    inside a window around it (`Music_implementation_phases.md` Section 4.6).
    """
    span = index.spans.get(ref)
    if span is None or edge not in EDGES:
        return None
    if relation == "under":
        return _round((span[0] + span[1]) / 2)
    return _round(span[0] if edge == "start" else span[1])
