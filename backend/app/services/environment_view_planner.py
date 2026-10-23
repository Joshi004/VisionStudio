"""Planning the views of one environment of a story project (PHASE-052, `Path_ahead.md`
Section 46). Pure functions, no I/O.

The master picture of an environment shows the place from one camera. A scene that puts a
character with the stove behind them and another with the window behind them needs two more
pictures of the place, one for each of those backgrounds. The model reads the environment (its
spatial plan and the prompt of its master picture), the backgrounds the staged scenes need and
the views the library already has, and answers which views to reuse, which to add and, for every
scene, which views cover each background side and the group's. Code checks the answer.

Sides are relative to the master picture: `ahead` is what the master shows, `left` and `right`
are what lies to those sides of the camera, `behind` is what lies behind it. The master picture
is the implicit view `establishing` (side `ahead`, wide) and is always available.

The job that drives this is `jobs/plan_environment_views.py`; the call is made through
`jobs/llm_call.py`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from app.providers import llm
from app.services import environment_definition_writer as definition_writer
from app.services.image_prompt_writer import MAX_TOKENS, REASONING_EFFORT

ESTABLISHING: Final = "establishing"
SIDES: Final = definition_writer.SPATIAL_SIDES
FRAMINGS: Final = ("wide", "medium", "close")
# The most views one environment may have, the establishing view included.
MAX_VIEWS: Final = 12

SLUG_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
NAME_MAX_CHARS: Final = 60
DESCRIPTION_MAX_CHARS: Final = 400

_TASK: Final = "Plan the views of this environment for the scenes below."

_ANSWER_FORM: Final = {
    "reuse": ["id of an existing view to use again"],
    "views": [
        {
            "id": "lowercase_slug",
            "name": "short name",
            "side": "ahead | left | right | behind",
            "framing": "wide | medium | close",
            "zone": "id of a zone of the spatial plan, or null",
            "description": "what this view shows",
        }
    ],
    "scenes": [
        {
            "scene_id": "id of a scene below",
            "by_side": {"<side>": ["ids of the views that cover this background side"]},
            "group": ["ids of the views for shots of the whole group"],
        }
    ],
}

_INSTRUCTIONS: Final = "\n".join(
    [
        "You plan the views of one place for a film. The place has a master picture, drawn "
        "from one camera. Other pictures of the place are made by editing the master picture: "
        "each shows the same place from another direction, so that a character standing in "
        "one part of the room is shown with the right background behind them.",
        "",
        "How sides work (all relative to the master picture):",
        "- ahead: what the master picture shows. Left and right: what lies to the left and to "
        "the right of the master camera. Behind: what lies behind the master camera, which the "
        "master never shows.",
        "- The master picture is the view 'establishing' (side ahead, wide). It always exists "
        "and is never listed in 'views' or 'reuse'.",
        "- A scene gives, for each character, the side of the place that is behind them, and "
        "the side that is behind the group. A view covers a background side when its side is "
        "that side.",
        "",
        "Rules:",
        "1. For every scene, 'by_side' has an entry for each background side the scene lists, "
        "and the entry lists at least one view whose side is that side. 'group' lists at "
        "least one view whose side is the scene's group side. 'establishing' counts as side "
        "ahead.",
        "2. Reuse an existing view when it already shows what is needed (list its id in "
        "'reuse'); add a new view only for what no existing view shows. A new view's id is a "
        "lowercase slug that no existing view has and is not 'establishing'.",
        "3. A view's description says what it shows, from the camera's side of the place: "
        "what fills the frame, what stands in it and what is at its edges. Take it from the "
        "spatial plan (the text of that side and the zones), never invent what the plan does "
        "not contain. A new view's 'zone' is the id of the zone it looks at, or null.",
        "4. Use as few views as the scenes need, and never more than "
        f"{MAX_VIEWS - 1} besides 'establishing'. Every view you list must be used by at "
        "least one scene.",
        "5. A 'close' view is for a tight single shot of a person against that part of the "
        "place; a 'wide' view is for the group or the whole side. Use 'medium' when unsure.",
        "",
        "Answer with one JSON object only, in exactly this form:",
        json.dumps(_ANSWER_FORM, ensure_ascii=False, indent=2),
    ]
)


def parse_answer(content: str) -> dict[str, Any]:
    """The model's answer as an object. Raises ValueError."""
    answer = llm.parse_json_object(content)
    if not isinstance(answer, dict):
        raise ValueError("The model's answer is not a JSON object.")
    return answer


def build_request(
    *,
    environment: dict[str, Any],
    master_prompt: str | None,
    scenes: list[dict[str, Any]],
    existing_views: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    """The exact request body sent to the model. The scenes are `{scene_id, title,
    background_sides, group_side, characters}`; the existing views `{id, name, side, framing,
    zone, description}`. Nothing about the call is hidden from the job record: this body is
    stored on the job (`job.input.request`).
    """
    parts = [
        _TASK,
        "",
        "ENVIRONMENT:\n" + json.dumps(environment, ensure_ascii=False, indent=2),
    ]
    if master_prompt:
        parts += ["", "PROMPT OF THE MASTER PICTURE:\n" + master_prompt]
    parts += [
        "",
        "EXISTING VIEWS:\n" + json.dumps(existing_views, ensure_ascii=False, indent=2),
        "",
        "SCENES:\n" + json.dumps(scenes, ensure_ascii=False, indent=2),
        "",
        "Plan the views now.",
    ]
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _INSTRUCTIONS},
            {"role": "user", "content": "\n".join(parts)},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


def _text(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is missing.")
    text = " ".join(value.split())
    if len(text) > limit:
        raise ValueError(f"{label} is longer than {limit} characters.")
    return text


def _ids(value: object, label: str, known: dict[str, str]) -> list[str]:
    """A non-empty list of known view ids, each once. `known` maps an id to its side."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must list at least one view.")
    found: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in known:
            raise ValueError(f"{label} names the view {item!r}, which is not in the plan.")
        if item not in found:
            found.append(item)
    return found


def _new_view(value: object, taken: set[str], zone_ids: set[str], position: int) -> dict[str, Any]:
    label = f"View {position}"
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object.")
    slug = value.get("id")
    if not isinstance(slug, str) or not SLUG_PATTERN.match(slug) or slug == ESTABLISHING:
        raise ValueError(f"{label} needs an id of lowercase letters, digits and underscores.")
    if slug in taken:
        raise ValueError(f"The view id '{slug}' is used twice or by an existing view.")
    side = value.get("side")
    if side not in SIDES:
        raise ValueError(f"The view '{slug}' needs a side: {', '.join(SIDES)}.")
    framing = value.get("framing")
    if framing not in FRAMINGS:
        raise ValueError(f"The view '{slug}' needs a framing: {', '.join(FRAMINGS)}.")
    zone = value.get("zone")
    if zone is not None and zone not in zone_ids:
        raise ValueError(f"The view '{slug}' names the zone {zone!r}, which the plan lacks.")
    return {
        "id": slug,
        "name": _text(value.get("name"), f"The name of '{slug}'", NAME_MAX_CHARS),
        "side": side,
        "framing": framing,
        "zone": zone,
        "description": _text(
            value.get("description"), f"The description of '{slug}'", DESCRIPTION_MAX_CHARS
        ),
        "reused": False,
    }


def check_answer(
    answer: dict[str, Any],
    *,
    scenes: list[dict[str, Any]],
    existing: dict[str, dict[str, Any]],
    unusable: list[str],
    zone_ids: list[str],
) -> dict[str, Any]:
    """The plan as it is stored, or ValueError saying what is wrong. `scenes` are the ones the
    request listed (`scene_id`, `background_sides`, `group_side`); `existing` the library's
    views that may be reused, by id; `unusable` the ids of library views that may not be reused
    (made from another master picture) and whose ids are therefore taken. The stored plan is
    `{"views": [...], "scenes": [{"scene_id", "by_side", "group"}]}`: `views` holds the reused
    and the new views (never `establishing`), each with `reused`.
    """
    reuse_raw = answer.get("reuse", [])
    if not isinstance(reuse_raw, list) or not all(isinstance(item, str) for item in reuse_raw):
        raise ValueError("'reuse' must be a list of view ids.")
    views: list[dict[str, Any]] = []
    taken: set[str] = {ESTABLISHING}
    for slug in reuse_raw:
        if slug not in existing:
            raise ValueError(f"'reuse' names the view {slug!r}, which does not exist.")
        if slug in taken:
            raise ValueError(f"The view {slug!r} is reused twice.")
        taken.add(slug)
        views.append({**existing[slug], "id": slug, "reused": True})
    new_raw = answer.get("views", [])
    if not isinstance(new_raw, list):
        raise ValueError("'views' must be a list.")
    # A new view may not take the id of a reused view or of any existing one.
    blocked = taken | set(existing) | set(unusable)
    for position, value in enumerate(new_raw, start=1):
        view = _new_view(value, blocked, set(zone_ids), position)
        blocked.add(view["id"])
        views.append(view)
    if len(views) + 1 > MAX_VIEWS:
        raise ValueError(
            f"The plan has {len(views) + 1} views with 'establishing'; "
            f"at most {MAX_VIEWS} are allowed."
        )

    sides = {ESTABLISHING: "ahead", **{view["id"]: view["side"] for view in views}}

    answered = answer.get("scenes")
    if not isinstance(answered, list):
        raise ValueError("'scenes' must be a list.")
    by_scene: dict[str, dict[str, Any]] = {}
    for item in answered:
        if isinstance(item, dict) and isinstance(item.get("scene_id"), str):
            by_scene[item["scene_id"]] = item
    stored: list[dict[str, Any]] = []
    used: set[str] = set()
    for need in scenes:
        scene_id = need["scene_id"]
        item = by_scene.get(scene_id)
        if item is None:
            raise ValueError(f"The scene '{scene_id}' has no entry in 'scenes'.")
        by_side_raw = item.get("by_side")
        if not isinstance(by_side_raw, dict):
            raise ValueError(f"The scene '{scene_id}' needs a 'by_side' object.")
        by_side: dict[str, list[str]] = {}
        for side in need["background_sides"]:
            ids = _ids(by_side_raw.get(side), f"'{scene_id}' side {side}", sides)
            wrong = [slug for slug in ids if sides[slug] != side]
            if wrong:
                raise ValueError(
                    f"'{scene_id}' side {side} lists {wrong[0]!r}, whose side is {sides[wrong[0]]}."
                )
            by_side[side] = ids
            used.update(ids)
        group = _ids(item.get("group"), f"'{scene_id}' group", sides)
        wrong_group = [slug for slug in group if sides[slug] != need["group_side"]]
        if wrong_group:
            raise ValueError(
                f"The group of '{scene_id}' stands before the side {need['group_side']}, but "
                f"lists {wrong_group[0]!r}, whose side is {sides[wrong_group[0]]}."
            )
        used.update(group)
        stored.append({"scene_id": scene_id, "by_side": by_side, "group": group})
    unused = [view["id"] for view in views if view["id"] not in used]
    if unused:
        raise ValueError(f"The view {unused[0]!r} is not used by any scene.")
    return {"views": views, "scenes": stored}
