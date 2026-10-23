"""Choosing the reference pictures of one shot with a language model (PHASE-033). Pure
functions: no I/O, no clock.

One call per shot (`Path_ahead.md` Section 28, step 2). Code has already narrowed the options:
the catalog (`services/shot_references`) holds only the pictures of the characters visible in the
shot and of its environment, for the look and state the scene uses and the default ones. The
model reads the shot's specification and the catalog as text (every picture was made from a
prompt, so its description exists; the model never sees an image), and picks the fewest pictures
that are enough, with a short reason for each.

**What code decides (step 3).** The model's answer is only a set of picture ids with reasons.
`check_answer` refuses it, and the job asks once more and then falls back to the fixed rule
(`reference_selection.select`), unless:

- every id is in the catalog and none is repeated;
- no picture belongs to a character who is not visible in the shot, and every visible character
  has from `MIN_PER_CHARACTER` to `MAX_PER_CHARACTER` pictures, at most one of each view;
- the environment has exactly one picture, and it is one of the shot's view (PHASE-054);
- the whole set is at most `H3_MAX_REFERENCE_IMAGES` pictures (the video model's limit);
- for each view the picture of the look or state the scene uses is chosen when it has one: a
  default picture stands in only for a view the scene's look lacks (and is marked `fallback`).

The order is never the model's: the focus character first, then the others in the shot's order,
the environment last (the same as the fixed rule), so that `<Picture n>` in a later prompt means
the same thing whichever method chose. Within one character the model's order is kept.

- `build_request` makes the exact request body sent to the model.
- `parse_answer` reads the model's text as JSON (the same as for the other stages).
- `check_answer` checks the answer and returns a `reference_selection.Selection`.

The call is made by `jobs/llm_call.py`, the job is `jobs/select_shot_references.py`, and the rows
are saved by `services/shot_references.py`.
"""

from __future__ import annotations

import json
from typing import Any, Final

from app.providers.video_generator import H3_MAX_REFERENCE_IMAGES
from app.services import character_library, discovery_writer, reference_selection
from app.services.reference_selection import CatalogPicture, Selection

parse_answer = discovery_writer.parse_answer

# The answer is short; the budget is mostly for the reasoning that is billed as output.
MAX_TOKENS: Final = 8000
REASONING_EFFORT: Final = "high"

MIN_PER_CHARACTER: Final = 1
MAX_PER_CHARACTER: Final = 3
# A reason is one sentence; a longer one is cut rather than refused.
REASON_MAX_CHARS: Final = 300
# A picture's description is the prompt it was made from, which can be long.
DESCRIPTION_MAX_CHARS: Final = 600

INSTRUCTIONS: Final = (
    "You choose the reference pictures that a video model is conditioned on for ONE shot of a "
    "film. You are given the shot's specification and a CATALOG of candidate pictures, each "
    "described in text with its id, the subject it shows, its view and its look or state. You "
    "do not see the images.\n\n"
    "Rule: use the MINIMUM SUFFICIENT reference set. Every extra picture dilutes what the "
    "video model is told, so choose only the pictures this shot needs.\n\n"
    "Requirements (an answer that breaks one is refused):\n"
    f"- Choose between {MIN_PER_CHARACTER} and {MAX_PER_CHARACTER} pictures of EACH character "
    "listed in the shot's `characters`, with at most one picture of each view of a character. "
    "A character who is not listed in the shot's `characters` must not get a picture.\n"
    "- Choose exactly ONE picture of the environment. The CATALOG only lists the environment "
    "pictures of the view the shot is in front of (`environment_view` in the HINTS); that "
    "view is part of the shot's specification, so do not look for another.\n"
    f"- Choose at most {H3_MAX_REFERENCE_IMAGES} pictures in all.\n"
    "- Choose only ids that are in the CATALOG, each at most once.\n"
    "- Each catalog entry has `is_scene_look`: true when it is the look or state the scene "
    "uses. Where a view has a picture with `is_scene_look` true, choose that one, never the "
    "default picture of the same view. A default picture (`is_scene_look` false) may be chosen "
    "only for a view that has no scene picture.\n\n"
    "How to choose the views: `usual_views` lists the views that normally suit the shot size. "
    "Start from them, and change them only for a reason the shot's specification gives (for "
    "example a character who looks away, up or down, is turned, or is seen from behind, may "
    "need the profile, back or face view; a character who is hardly visible may need only one "
    "picture). A close shot of a face usually needs the face view; a wide shot only needs the "
    "front view. Do not add pictures 'just in case'.\n\n"
    "The order of your list does not matter: it is set by code.\n\n"
    "Answer with one JSON object and nothing else, in the form of the ANSWER FORM. `id` is a "
    "number copied from the CATALOG; `reason` is one short sentence saying why this picture is "
    "needed for this shot."
)

_ANSWER_FORM: Final = {"references": [{"id": 0, "reason": "..."}]}


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _cut(text: str, max_chars: int) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= max_chars:
        return one_line
    return one_line[: max_chars - 3].rstrip() + "..."


def _catalog_entry(picture: CatalogPicture) -> dict[str, Any]:
    return {
        "id": picture.lab_image_id,
        "kind": picture.kind,
        "subject_id": picture.subject_id,
        "subject_name": picture.subject_name,
        "view": picture.view,
        "look_or_state": picture.variant,
        "is_scene_look": picture.is_resolved,
        "description": _cut(picture.description, DESCRIPTION_MAX_CHARS),
    }


def usual_views(content: dict[str, Any]) -> list[str]:
    """The views the fixed rule would take for this shot's size, as a hint to the model. Raises
    ReferenceSelectionError when the shot has no usable shot size.
    """
    composition = content.get("composition") or {}
    shot_size = composition.get("shot_size")
    if not isinstance(shot_size, str):
        raise reference_selection.ReferenceSelectionError("The shot has no shot size.")
    framing = reference_selection.framing_for(shot_size)
    return list(character_library.references_for(framing))  # type: ignore[arg-type]


def narrowed_catalog(
    content: dict[str, Any], catalog: list[CatalogPicture]
) -> list[CatalogPicture]:
    """The catalog this shot may choose from: every picture of a character, and of the
    environment only those of the shot's view (`reference_selection.environment_candidates`).
    """
    return [
        *(picture for picture in catalog if picture.kind != "environment"),
        *reference_selection.environment_candidates(content, catalog),
    ]


def build_request(
    *, shot_definition: dict[str, Any], catalog: list[CatalogPicture], model: str
) -> dict[str, Any]:
    """The exact request body sent to the model. It is stored on the job (`job.input.request`),
    so nothing about the call is hidden from the job record.

    `shot_definition` is the stored specification of the shot (PHASE-022) and `catalog` the
    candidate pictures (PHASE-024).
    """
    hints = {
        "shot_size": (shot_definition.get("composition") or {}).get("shot_size"),
        "usual_views": usual_views(shot_definition),
        "focus": (shot_definition.get("composition") or {}).get("focus"),
        "characters_in_the_shot": reference_selection.visible_characters(shot_definition),
        "most_pictures": H3_MAX_REFERENCE_IMAGES,
        "environment_view": (shot_definition.get("composition") or {}).get("view"),
    }
    catalog = narrowed_catalog(shot_definition, catalog)
    parts = [
        "SHOT SPECIFICATION (JSON):\n" + _dump(shot_definition),
        "HINTS (JSON):\n" + _dump(hints),
        "CATALOG (JSON):\n" + _dump([_catalog_entry(picture) for picture in catalog]),
        "ANSWER FORM (JSON; the values here are only stand-ins):\n" + json.dumps(_ANSWER_FORM),
    ]
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        # Without this the stream carries no token counts, which the job records.
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
    }


# --- Checking the answer ------------------------------------------------------------------


def _picture_id(value: Any, position: int) -> int:
    """The id of item `position` (counting from 1), as a whole number. Raises ValueError."""
    if isinstance(value, bool):
        value = None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int):
        raise ValueError(f'Item {position} of the model\'s answer had no number "id".')
    return value


def _reason(value: Any, position: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Item {position} of the model\'s answer had no text "reason".')
    return _cut(value, REASON_MAX_CHARS)


def _label(picture: CatalogPicture) -> str:
    return f"the {picture.view.replace('_', ' ')} picture of {picture.subject_name}"


def check_answer(answer: Any, content: dict[str, Any], catalog: list[CatalogPicture]) -> Selection:
    """The checked choice: the pictures in the order of code, the model's reason for each.
    Raises ValueError, with a message fit for the user, when the answer breaks a requirement.

    `content` is the stored specification of the shot and `catalog` its candidate pictures.
    """
    items = answer.get("references") if isinstance(answer, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError('The model\'s answer had no list "references".')

    shot_size = (content.get("composition") or {}).get("shot_size")
    if not isinstance(shot_size, str):
        raise ValueError("The shot has no shot size.")
    framing = reference_selection.framing_for(shot_size)
    catalog = narrowed_catalog(content, catalog)

    by_id: dict[int, CatalogPicture] = {}
    for picture in catalog:
        by_id.setdefault(picture.lab_image_id, picture)

    chosen: dict[int, tuple[CatalogPicture, str]] = {}
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item {position} of the model's answer was not an object.")
        image_id = _picture_id(item.get("id"), position)
        reason = _reason(item.get("reason"), position)
        picture = by_id.get(image_id)
        if picture is None:
            raise ValueError(
                f"The model chose the picture {image_id}, which is not in the catalog."
            )
        if image_id in chosen:
            raise ValueError(f"The model chose the picture {image_id} more than once.")
        chosen[image_id] = (picture, reason)

    if len(chosen) > H3_MAX_REFERENCE_IMAGES:
        raise ValueError(
            f"The model chose {len(chosen)} pictures; the video model takes at most "
            f"{H3_MAX_REFERENCE_IMAGES}."
        )

    visible = reference_selection.visible_characters(content)
    for picture, _reason_text in chosen.values():
        if picture.kind == "character" and picture.subject_id not in visible:
            raise ValueError(
                f"The model chose {_label(picture)}, but they are not in the shot's characters."
            )

    # The scene's own picture of a view must be used when there is one.
    for picture, _reason_text in chosen.values():
        if picture.is_resolved:
            continue
        better = next(
            (
                other
                for other in catalog
                if other.is_resolved
                and other.kind == picture.kind
                and other.subject_id == picture.subject_id
                and other.view == picture.view
            ),
            None,
        )
        if better is not None:
            raise ValueError(
                f"The model chose the default {_label(picture)} (picture {picture.lab_image_id}) "
                f"although the picture {better.lab_image_id} of the look or state the scene "
                "uses exists."
            )

    focus = reference_selection.focus_character(content.get("composition") or {}, visible)
    pictures: list[CatalogPicture] = []
    reasons: list[str] = []
    for character_id in reference_selection.ordered(visible, focus):
        mine = [
            (picture, reason)
            for picture, reason in chosen.values()
            if picture.kind == "character" and picture.subject_id == character_id
        ]
        name = next(
            (picture.subject_name for picture in catalog if picture.subject_id == character_id),
            character_id,
        )
        if not MIN_PER_CHARACTER <= len(mine) <= MAX_PER_CHARACTER:
            raise ValueError(
                f"The model chose {len(mine)} pictures of {name}; each character in the shot "
                f"needs from {MIN_PER_CHARACTER} to {MAX_PER_CHARACTER}."
            )
        views = [picture.view for picture, _reason_text in mine]
        if len(set(views)) != len(views):
            raise ValueError(f"The model chose two pictures of the same view of {name}.")
        for picture, reason in mine:
            pictures.append(picture)
            reasons.append(reason)

    environment = [
        (picture, reason) for picture, reason in chosen.values() if picture.kind == "environment"
    ]
    if len(environment) != 1:
        raise ValueError(
            f"The model chose {len(environment)} pictures of the environment; it needs exactly 1."
        )
    pictures.append(environment[0][0])
    reasons.append(environment[0][1])

    return Selection(
        shot_size=shot_size,
        framing=framing,
        focus_character_id=focus,
        pictures=pictures,
        fallbacks=[not picture.is_resolved for picture in pictures],
        notes=[],
        reasons=reasons,
    )
