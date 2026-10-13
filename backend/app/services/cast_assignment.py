"""Choosing which characters and which place each scene shows, with a language model. Pure
functions, no I/O.

The model is given the project's cast (the closed list the characters and places were found
in) and the narration of every scene. For each scene it names the characters the scene shows (a
list: none, one or several, as it judges from the narration) and *one* place at most, copying
the names from the lists. Code maps the names to the members and drops a name that is not on the
list, so a scene can never show somebody who is not in the cast. The prompt never asks for a
number of characters: the only limit is the image model's (`cast.MAX_SCENE_CHARACTERS`), which
code applies to the answer.

1. `build_request`: the rules, the cast, and the scenes, as an OpenAI-style chat request.
2. `parse_answer`: the model's JSON, read defensively and mapped to the cast's ids.
3. `plan_write`: what a job may put into a scene as it is *now*. A choice the author made by hand
   is never overwritten.

The call is made by `providers/llm.py` and the job that drives it is `jobs/assign_cast.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.db.models import Scene
from app.providers import llm
from app.services.cast import MAX_SCENE_CHARACTERS, Cast

# Hidden reasoning tokens are billed as output (ANALYSIS.md Section 6.2, rule 4). The answer is a
# short line per scene.
MAX_TOKENS: Final = 16000
REASONING_EFFORT: Final = "high"
# A cast member's description is cut to this for the request: enough to tell them apart.
_BRIEF_CHARS: Final = 220

_SYSTEM_PROMPT: Final = "\n".join(
    [
        "You decide which characters and which place each scene of a narrated video shows. A "
        "voiceover tells the story, and every scene is one picture made for a few seconds of the "
        "narration. Each character and place of the story has a reference picture, so a scene "
        "that shows them looks the same every time.",
        "",
        "Rules:",
        "1. For each scene choose the characters it shows and at most one place, only from the "
        "lists you are given, copying each name exactly. A scene may show no character, one or "
        "several: choose the characters the narration puts in the picture. Use an empty list "
        "when there is none, and null when there is no place.",
        "2. A character is in the scene when the narration is about them at that moment, or "
        "they do what the narration says, or the narration says they are there. A scene about a "
        "landscape, an object, a feeling or an event with no character in it shows no "
        "character.",
        "3. The place is where the scene happens. When the narration names no place, the scene "
        "happens where the previous scene did, if the story is still there. Otherwise use null.",
        "4. When the narration of a scene goes on from the previous one (he, she, they, the same "
        "action), keep the characters the previous scene showed.",
        "5. Answer for every scene, in order, using the scene's number.",
        "",
        'Answer with one JSON object only, in exactly this form. "characters" is a list of '
        "names, an empty list for none:",
        '{"scenes": [{"scene": 1, "characters": ["Name", ...], "location": "Name or null"}]}',
    ]
)


def _brief(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= _BRIEF_CHARS:
        return one_line
    return one_line[: _BRIEF_CHARS - 1].rstrip() + "…"


def build_request(
    scenes: Sequence[Scene], cast: Cast, *, model: str, instructions: str | None
) -> dict[str, Any]:
    """The exact request body sent to the model. Nothing about the call is hidden from the
    job record: this body is stored on the job (`job.input.request`).
    """
    lines: list[str] = []
    if instructions and instructions.strip():
        lines += [
            "Author's instructions for the video (use what concerns who is in the scenes):",
            instructions.strip(),
            "",
        ]
    lines.append("Characters (use these names exactly):")
    lines += [f"- {c.name}: {_brief(c.appearance_description)}" for c in cast.characters] or [
        "none"
    ]
    lines += ["", "Places (use these names exactly):"]
    lines += [f"- {p.name}: {_brief(p.appearance_description)}" for p in cast.locations] or ["none"]
    lines += ["", "Scenes, with the narration of each:"]
    lines += [f"{scene.index + 1}. {' '.join(scene.text.split())}" for scene in scenes]
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- Reading the answer ---------------------------------------------------------------


@dataclass(frozen=True)
class Assignment:
    """Who and what one scene shows: its characters, in the order of their pictures (none, one
    or several), and its place, which may be None. A scene may show neither.
    """

    scene_id: int
    character_ids: tuple[int, ...]
    location_id: int | None


@dataclass(frozen=True)
class Assignments:
    scenes: list[Assignment]
    # How many names were not on the cast's lists (each counts as none), and how many scenes
    # the answer did not mention (each counts as showing neither).
    unknown_names: int
    missing_scenes: int


def _name(value: object) -> str | None:
    """The name in a field, or None when it says none (null, a blank, "none", "null")."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).casefold()
    return None if cleaned in ("", "none", "null", "n/a") else cleaned


def _names(value: object) -> list[str]:
    """The names in a field that holds a list of them. A single name (a model that wrote one
    instead of a list) counts as a list of one, and anything else as none.
    """
    items = value if isinstance(value, list) else [value]
    return [name for item in items if (name := _name(item)) is not None]


def parse_answer(content: str, scenes: Sequence[Scene], cast: Cast) -> Assignments:
    """The model's choices mapped to the cast. Raises ValueError, with a message fit for the
    user, when the answer is empty, is not JSON, has no scene list, or mentions fewer than half
    of the scenes.
    """
    if not content.strip():
        raise ValueError("The model's answer was empty.")
    answer = llm.parse_json_object(content)
    entries = answer.get("scenes") if isinstance(answer, dict) else None
    if not isinstance(entries, list):
        raise ValueError('The model\'s answer had no "scenes" list.')

    by_number: dict[int, dict[str, Any]] = {}
    for entry in entries:
        number = entry.get("scene") if isinstance(entry, dict) else None
        if isinstance(number, int) and not isinstance(number, bool):
            by_number.setdefault(number, entry)

    characters = {member.name.casefold(): member.id for member in cast.characters}
    locations = {member.name.casefold(): member.id for member in cast.locations}
    chosen: list[Assignment] = []
    unknown = 0
    missing = 0
    for scene in scenes:
        entry = by_number.get(scene.index + 1)
        if entry is None:
            missing += 1
            chosen.append(Assignment(scene.id, (), None))
            continue

        # "character" is read too: it is what an answer in the old one-character form says.
        character_ids: list[int] = []
        for name in _names(entry.get("characters", entry.get("character"))):
            character_id = characters.get(name)
            if character_id is None:
                unknown += 1
            elif character_id not in character_ids:
                character_ids.append(character_id)

        location_name = _name(entry.get("location"))
        location_id = locations.get(location_name) if location_name else None
        unknown += location_name is not None and location_id is None
        chosen.append(
            Assignment(scene.id, tuple(character_ids[:MAX_SCENE_CHARACTERS]), location_id)
        )

    if scenes and missing * 2 > len(scenes):
        raise ValueError(
            f"The model's answer covered only {len(scenes) - missing} of {len(scenes)} scenes."
        )
    return Assignments(scenes=chosen, unknown_names=unknown, missing_scenes=missing)


# --- What a job may write -----------------------------------------------------------------


def choice_is_authors(scene: Scene) -> bool:
    """A choice is the author's when its source is `manual`: it is never overwritten."""
    return scene.cast_assignment_source == "manual"


def plan_write(scene: Scene, assignment: Assignment, job_id: int) -> dict[str, Any] | None:
    """The columns a job sets on the scene as it is now, or None when the author has chosen
    since: the author's choice is kept. A scene the AI chose for, or none, may be written.

    The scene's characters are not columns: the job writes them (`cast.set_scene_characters`)
    for every scene this does not answer None for.
    """
    if choice_is_authors(scene):
        return None
    return {
        "location_id": assignment.location_id,
        "cast_assignment_source": "ai",
        "cast_assignment_job_id": job_id,
    }
