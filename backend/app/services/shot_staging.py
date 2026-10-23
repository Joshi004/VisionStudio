"""What one shot is staged and framed from: the placements of its characters at the shot's start
and the views of its place that may stand behind it (PHASE-054, `Path_ahead.md` Section 46).
Pure functions, no I/O.

Code, not the model, works out the facts (D-12). From the scene's staging (`scene_staging`) it
takes where each character stands, which way they face, which side of the screen they are on and
which side of the place is behind them, **at the start of this shot** (every move that happened
before the shot's first event applied). From the environment's view plan
(`environment_views`) it takes the views that cover each background side, and so which views
may stand behind each character, and which behind the group. The model is shown this as
`STAGING AT THIS SHOT` and `VIEWS`, and only picks a view from the allowed list; code then writes
each visible character's `zone`, `screen_side` and `background_side` into the specification, so
the model cannot move anyone.

The stored form, `for_shot`'s result, is plain JSON: it is put on a job's input and read back.

```
{"characters": {"<id>": {"zone", "posture", "faces", "screen_side", "background_side"}},
 "axis": {"between", "camera_half", "note"}, "group_side": "...",
 "views": [{"id", "name", "side", "framing", "zone", "description", "allowed_for": [...]}]}
```

`allowed_for` lists the ids of the characters the view may stand behind and `"group"` when it may
stand behind a shot of the whole group.
"""

from __future__ import annotations

from typing import Any, Final

from app.services import scene_staging_writer

ESTABLISHING: Final = "establishing"
GROUP: Final = "group"
# A shot of one of these sizes shows the group and the place, even when it names a character.
_GROUP_SIZES: Final = ("wide", "extreme_wide")


def establishing_view(master_view: str | None) -> dict[str, Any]:
    """The master picture as a view: the implicit `establishing` view of every environment."""
    return {
        "id": ESTABLISHING,
        "name": "Establishing view",
        "side": "ahead",
        "framing": "wide",
        "zone": None,
        "description": master_view or "The place as the master picture shows it.",
    }


def first_event_of(shot_event_ids: list[str], scene_event_ids: list[str]) -> str | None:
    """The shot's earliest event in the scene's order, or None when it shows none of them."""
    positions = [scene_event_ids.index(item) for item in shot_event_ids if item in scene_event_ids]
    return scene_event_ids[min(positions)] if positions else None


def for_shot(
    *,
    staging: dict[str, Any],
    scene_event_ids: list[str],
    shot_event_ids: list[str],
    views: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    """The staging and the allowed views for one shot. `staging` is the stored content of the
    scene's newest staging; `views` the view plan's views, `establishing` included, each with
    `id, name, side, framing, zone, description`; `coverage` the plan's entry for this scene
    (`by_side` and `group`: the view ids that cover each background side and the group).
    """
    first = first_event_of(shot_event_ids, scene_event_ids)
    placed = scene_staging_writer.staging_at(staging, scene_event_ids, first)
    characters = {
        character_id: {
            key: item[key] for key in ("zone", "posture", "faces", "screen_side", "background_side")
        }
        for character_id, item in placed.items()
    }
    by_side = coverage.get("by_side", {})
    group_ids = set(coverage.get("group", []))
    shown: list[dict[str, Any]] = []
    for view in views:
        allowed = [
            character_id
            for character_id, item in characters.items()
            if view["id"] in by_side.get(item["background_side"], [])
        ]
        if view["id"] in group_ids:
            allowed.append(GROUP)
        if allowed:
            shown.append({**view, "allowed_for": allowed})
    return {
        "characters": characters,
        "axis": staging["axis"],
        "group_side": staging["group_side"],
        "views": shown,
    }


def view_key(
    composition: dict[str, Any], visible_ids: list[str], staging: dict[str, Any], *, exchange: bool
) -> str:
    """Whom the shot's background is chosen for: the id of the character it is focused on, or
    `group`. A shot is a single of a character when its focus is that visible character's id and
    it is neither a wide shot nor a rapid exchange; anything else shows the group.
    """
    focus = composition.get("focus")
    size = composition.get("shot_size")
    if (
        not exchange
        and size not in _GROUP_SIZES
        and isinstance(focus, str)
        and focus.strip() in visible_ids
        and focus.strip() in staging["characters"]
    ):
        return focus.strip()
    return GROUP


def allowed_view_ids(staging: dict[str, Any], key: str) -> list[str]:
    """The ids of the views that may stand behind a shot for `key` (a character id or `group`)."""
    return [view["id"] for view in staging["views"] if key in view["allowed_for"]]


def view_of(staging: dict[str, Any] | None, view_id: object) -> dict[str, Any] | None:
    """The view with this id among the shot's views, or None."""
    if staging is None or not isinstance(view_id, str):
        return None
    return next((view for view in staging["views"] if view["id"] == view_id), None)


def apply_to_characters(
    characters: list[dict[str, str]], staging: dict[str, Any]
) -> list[dict[str, str]]:
    """The visible characters with the placement code knows added: `zone`, `screen_side` and
    `background_side`, after the model's own fields. A character the staging does not place
    (cannot happen for a scene's character) keeps what the model wrote.
    """
    result: list[dict[str, str]] = []
    for character in characters:
        placed = staging["characters"].get(character["id"])
        if placed is None:
            result.append(character)
            continue
        result.append(
            {
                **character,
                "zone": placed["zone"],
                "screen_side": placed["screen_side"],
                "background_side": placed["background_side"],
            }
        )
    return result


def planner_block(staging: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    """The staging of a whole scene as the shot planner reads it: where each character stands
    at the start, the line the camera keeps to, the side seen behind the group, and who moves
    after which event. Names are added so the planner reads people, not ids.
    """
    return {
        "characters": [
            {
                "id": item["character_id"],
                "name": names.get(item["character_id"], item["character_id"]),
                **{key: item[key] for key in ("zone", "faces", "screen_side", "background_side")},
            }
            for item in staging["placements"]
        ],
        "axis": staging["axis"],
        "group_side": staging["group_side"],
        "moves": [
            {key: move[key] for key in ("after_event_id", "character_id", "zone")}
            for move in staging["moves"]
        ],
    }


def view_for_prompt(staging: dict[str, Any] | None, view_id: object) -> dict[str, str] | None:
    """The view a shot is framed in front of, as the prompt writer reads it: `{name, side,
    description}`, or None for a shot made before views existed.
    """
    view = view_of(staging, view_id)
    if view is None:
        return None
    return {"name": view["name"], "side": view["side"], "description": view["description"]}
