"""The deterministic choice of a shot's reference pictures (PHASE-024, `Path_ahead.md` Section 28).

Pure functions: no database, no files, no clock. The caller (`services/shot_references.py`)
builds the **catalog**, the pictures that could matter to one shot, and `select` picks the
minimum set from it by a fixed rule:

1. The shot's `composition.shot_size` gives a Character Lab framing (`FRAMING_OF_SIZE`) and the
   framing gives the angles (`character_library.references_for`).
2. For each character visible in the shot, the focus character first and the others in the
   shot's own order, each of those angles is taken from the look the scene resolved to. When
   that look has no picture of the angle, the default look's picture is used and the entry says
   so (`fallback`).
3. The environment's picture is added last: the resolved state's, else the default one.
4. At most `H3_MAX_REFERENCE_IMAGES` pictures are kept. The environment is never dropped; the
   pictures of the last characters are.

A picture that is missing from both the resolved and the default look, or an environment with
no picture, makes the shot refuse (`ReferenceSelectionError`) with a sentence for the user.
Narration audio is never a reference, and a character who is not visible in the shot (an
unseen speaker) is not in the catalog's wanted list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

from app.providers.video_generator import H3_MAX_REFERENCE_IMAGES
from app.services import character_library
from app.services.shot_definition_writer import FRAMING_OF_SIZE

METHOD_DETERMINISTIC: Final = "deterministic"
# The pictures were chosen by the language model (PHASE-033, `services/reference_selection_writer`).
METHOD_LLM: Final = "llm"
# The pictures were chosen by the user (PHASE-038, `shot_references.save_manual`).
METHOD_MANUAL: Final = "manual"

# The `view` of an environment's picture. A character's picture has its angle as the view.
ENVIRONMENT_VIEW: Final = "environment"
# The id of the master picture as a view of the place (`shot_staging.ESTABLISHING`): its catalog
# `view` is `ENVIRONMENT_VIEW`. Every other view of the place has its own slug as the `view`.
ESTABLISHING_VIEW: Final = "establishing"
# The `variant` of the canonical picture of a character or an environment.
DEFAULT_VARIANT: Final = "default"


class ReferenceSelectionError(ValueError):
    """A shot that cannot be given its references. The message is meant to be shown."""


@dataclass(frozen=True)
class CatalogPicture:
    """One picture that could be a reference of the shot.

    `variant` is `default` or the slug of the named look or state the picture belongs to.
    `is_resolved` is True when it belongs to what the scene resolved to (the default pictures
    count as resolved when the scene resolved to the default).
    """

    lab_image_id: int
    kind: Literal["character", "environment"]
    subject_id: str
    subject_name: str
    view: str
    variant: str
    is_resolved: bool
    description: str

    @classmethod
    def from_dict(cls, data: Any) -> CatalogPicture | None:
        """A picture read back from `as_dict` (a stored catalog or a job's input), or None when
        `data` is not the right shape.
        """
        if not isinstance(data, dict):
            return None
        image_id = data.get("lab_image_id")
        kind = data.get("kind")
        if (
            not isinstance(image_id, int)
            or isinstance(image_id, bool)
            or kind not in ("character", "environment")
            or not isinstance(data.get("is_resolved"), bool)
            or not all(
                isinstance(data.get(key), str)
                for key in ("subject_id", "subject_name", "view", "variant", "description")
            )
        ):
            return None
        return cls(
            lab_image_id=image_id,
            kind=kind,
            subject_id=data["subject_id"],
            subject_name=data["subject_name"],
            view=data["view"],
            variant=data["variant"],
            is_resolved=data["is_resolved"],
            description=data["description"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "lab_image_id": self.lab_image_id,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "subject_name": self.subject_name,
            "view": self.view,
            "variant": self.variant,
            "is_resolved": self.is_resolved,
            "description": self.description,
        }


@dataclass(frozen=True)
class Selection:
    """The result: the framing used, who is first, the ordered pictures and notes for the user.
    `fallbacks` has the same length as `pictures`: True where the default look was used because
    the resolved look had no picture of the angle. `reasons` is the language model's reason for
    each picture (PHASE-033), or empty when the fixed rule chose.
    """

    shot_size: str
    framing: str
    focus_character_id: str | None
    pictures: list[CatalogPicture]
    fallbacks: list[bool]
    notes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def framing_for(shot_size: str) -> str:
    """The Character Lab framing for a `shot_size` of a shot definition."""
    framing = FRAMING_OF_SIZE.get(shot_size)
    if framing is None:
        raise ReferenceSelectionError(f"The shot size '{shot_size}' has no known framing.")
    return framing


def focus_character(composition: dict[str, Any], character_ids: list[str]) -> str | None:
    """The visible character the shot is focused on, or None when the focus is something else
    (the model writes the character's id there when it is a character, but it is free text).
    """
    focus = composition.get("focus")
    if not isinstance(focus, str):
        return None
    wanted = focus.strip().lower()
    return next((item for item in character_ids if item.lower() == wanted), None)


def visible_characters(content: dict[str, Any]) -> list[str]:
    """The ids of the characters visible in the shot, in the shot's own order."""
    return [
        entry["id"]
        for entry in content.get("characters") or []
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    ]


def ordered(character_ids: list[str], focus: str | None) -> list[str]:
    """The focus character first, then the others in the shot's own order."""
    if focus is None:
        return list(character_ids)
    return [focus, *(item for item in character_ids if item != focus)]


def environment_view(content: dict[str, Any]) -> str:
    """The catalog `view` of the environment picture the shot is framed in front of: the master
    picture's for `establishing` or for a specification made before views existed (PHASE-054).
    """
    view = (content.get("composition") or {}).get("view")
    if not isinstance(view, str) or view in ("", ESTABLISHING_VIEW):
        return ENVIRONMENT_VIEW
    return view


def environment_candidates(
    content: dict[str, Any], catalog: list[CatalogPicture]
) -> list[CatalogPicture]:
    """The environment pictures this shot may use: those of its view (the view's own and its
    pictures in the places' states), or the master picture's when the view has none yet.
    """
    pictures = [picture for picture in catalog if picture.kind == "environment"]
    wanted = environment_view(content)
    mine = [picture for picture in pictures if picture.view == wanted]
    return mine or [picture for picture in pictures if picture.view == ENVIRONMENT_VIEW]


def _pick(candidates: list[CatalogPicture]) -> tuple[CatalogPicture, bool] | None:
    """The resolved picture when there is one, else the default one (a fallback), else None."""
    for picture in candidates:
        if picture.is_resolved:
            return picture, False
    for picture in candidates:
        if picture.variant == DEFAULT_VARIANT:
            return picture, True
    return None


def select(content: dict[str, Any], catalog: list[CatalogPicture]) -> Selection:
    """Chooses the pictures for one shot from its specification (`content` of a
    `shot_definition`) and the catalog. Raises ReferenceSelectionError, naming everything that is
    missing at once.
    """
    composition = content.get("composition") or {}
    shot_size = composition.get("shot_size")
    if not isinstance(shot_size, str):
        raise ReferenceSelectionError("The shot has no shot size.")
    framing = framing_for(shot_size)
    angles = character_library.references_for(framing)  # type: ignore[arg-type]

    visible = visible_characters(content)
    focus = focus_character(composition, visible)

    chosen: list[tuple[CatalogPicture, bool]] = []
    missing: list[str] = []
    for character_id in ordered(visible, focus):
        mine = [
            picture
            for picture in catalog
            if picture.kind == "character" and picture.subject_id == character_id
        ]
        name = mine[0].subject_name if mine else character_id
        for angle in angles:
            found = _pick([picture for picture in mine if picture.view == angle])
            if found is None:
                missing.append(f"the {angle.replace('_', ' ')} picture of {name}")
            else:
                chosen.append(found)

    found_environment = _pick(environment_candidates(content, catalog))
    if found_environment is None:
        missing.append("the picture of the environment")

    if missing:
        raise ReferenceSelectionError(
            "These pictures are missing: "
            + ", ".join(missing)
            + ". Make the character and environment images first."
        )
    assert found_environment is not None

    notes: list[str] = []
    wanted_view = environment_view(content)
    if found_environment[0].view != wanted_view:
        notes.append(
            f"The picture of the view '{wanted_view}' does not exist: the master picture of the "
            "place is used."
        )
    elif found_environment[1]:
        notes.append(
            f"The view '{wanted_view}' has no picture in the state the scene uses: its default "
            "picture is used."
        )
    room = H3_MAX_REFERENCE_IMAGES - 1  # the environment always stays
    if len(chosen) > room:
        dropped = len(chosen) - room
        notes.append(
            f"{dropped} character picture{'s' if dropped != 1 else ''} left out: "
            f"the video model takes at most {H3_MAX_REFERENCE_IMAGES} pictures."
        )
        chosen = chosen[:room]
    chosen.append(found_environment)

    return Selection(
        shot_size=shot_size,
        framing=framing,
        focus_character_id=focus,
        pictures=[picture for picture, _fallback in chosen],
        fallbacks=[fallback for _picture, fallback in chosen],
        notes=notes,
    )


def manual(
    content: dict[str, Any], catalog: list[CatalogPicture], image_ids: list[int]
) -> Selection:
    """The user's choice of pictures (PHASE-038), in the order given. Each must be in the
    catalog, none may repeat, and there must be from 1 to `H3_MAX_REFERENCE_IMAGES` of them (what
    the video model takes). Anything beyond that is the user's call: unlike the fixed rule it
    does not insist on every angle or on the environment. Raises ReferenceSelectionError with a
    sentence for the user.

    `content` is the stored specification of the shot, which gives the shot size, the framing
    and the focus character.
    """
    composition = content.get("composition") or {}
    shot_size = composition.get("shot_size")
    if not isinstance(shot_size, str):
        raise ReferenceSelectionError("The shot has no shot size.")
    framing = framing_for(shot_size)

    if not 1 <= len(image_ids) <= H3_MAX_REFERENCE_IMAGES:
        raise ReferenceSelectionError(
            f"A shot needs from 1 to {H3_MAX_REFERENCE_IMAGES} reference pictures; "
            f"{len(image_ids)} were given."
        )
    by_id: dict[int, CatalogPicture] = {}
    for picture in catalog:
        by_id.setdefault(picture.lab_image_id, picture)
    pictures: list[CatalogPicture] = []
    for image_id in image_ids:
        picture = by_id.get(image_id)
        if picture is None:
            raise ReferenceSelectionError(
                f"The picture {image_id} is not one of the pictures this shot can use now."
            )
        if picture in pictures:
            raise ReferenceSelectionError(f"The picture {image_id} was chosen more than once.")
        pictures.append(picture)

    focus = focus_character(composition, visible_characters(content))
    return Selection(
        shot_size=shot_size,
        framing=framing,
        focus_character_id=focus,
        pictures=pictures,
        fallbacks=[not picture.is_resolved for picture in pictures],
    )
