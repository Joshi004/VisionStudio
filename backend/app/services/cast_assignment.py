"""Choosing which character and which place each scene shows, with a language model. Pure
functions, no I/O.

The model is given the project's cast (the closed list the characters and places were found
in) and the narration of every scene. For each scene it names *one* character at most and *one*
place at most, copying a name from the list, or says null. Code maps the names to the members and
drops a name that is not on the list, so a scene can never show somebody who is not in the cast.

A scene never shows two characters: the answer has one field for the character, not a list.

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
from app.services.cast import Cast

# Hidden reasoning tokens are billed as output (ANALYSIS.md Section 6.2, rule 4). The answer is a
# short line per scene.
MAX_TOKENS: Final = 16000
REASONING_EFFORT: Final = "high"
# A cast member's description is cut to this for the request: enough to tell them apart.
_BRIEF_CHARS: Final = 220

_SYSTEM_PROMPT: Final = "\n".join(
    [
        "You decide which character and which place each scene of a narrated video shows. A "
        "voiceover tells the story, and every scene is one picture made for a few seconds of the "
        "narration. Each character and place of the story has a reference picture, so a scene "
        "that shows one looks the same every time.",
        "",
        "Rules:",
        "1. For each scene choose at most one character and at most one place, only from the "
        "lists you are given, copying the name exactly. Use null for none.",
        "2. A scene shows at most ONE character: the one the narration is about at that moment, "
        "or the one who does what the narration says. If the narration names two, choose the "
        "one who acts or is looked at. Several people together are shown by their leader, or by "
        "none. A scene about a landscape, an object, a feeling or an event with no main "
        "character shows no character: use null.",
        "3. The place is where the scene happens. When the narration names no place, the scene "
        "happens where the previous scene did, if the story is still there. Otherwise use null.",
        "4. When the narration of a scene goes on from the previous one (he, she, they, the same "
        "action), keep the previous scene's character.",
        "5. Answer for every scene, in order, using the scene's number.",
        "",
        "Answer with one JSON object only, in exactly this form:",
        '{"scenes": [{"scene": 1, "character": "Name or null", "location": "Name or null"}]}',
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
    """Who and what one scene shows. Both may be None: the scene shows neither."""

    scene_id: int
    character_id: int | None
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
            chosen.append(Assignment(scene.id, None, None))
            continue
        character_name, location_name = _name(entry.get("character")), _name(entry.get("location"))
        character_id = characters.get(character_name) if character_name else None
        location_id = locations.get(location_name) if location_name else None
        unknown += (character_name is not None and character_id is None) + (
            location_name is not None and location_id is None
        )
        chosen.append(Assignment(scene.id, character_id, location_id))

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
    """
    if choice_is_authors(scene):
        return None
    return {
        "character_id": assignment.character_id,
        "location_id": assignment.location_id,
        "cast_assignment_source": "ai",
        "cast_assignment_job_id": job_id,
    }
