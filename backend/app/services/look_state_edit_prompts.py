"""The edit prompts that make a new look and a new environment state (PHASE-017).

A new look is made by editing the character's canonical front picture, and a new state by
editing the environment's canonical picture, so the face or the layout stays fixed and only the
wardrobe or the condition changes. The words are fixed here, in the same way as the angle
prompts of `services/character_looks.py`: no language model writes them. The only thing that
varies is the description PHASE-016 stored for the named look or state, which is a short line
of at most `look_state_resolution_writer.DESCRIPTION_MAX_CHARS` characters.

These are pure functions with no database and no network.
"""

from __future__ import annotations

from typing import Final

from app.providers.image_generator import MAX_PROMPT_CHARS

_LOOK_TEMPLATE: Final = (
    "The exact same character as the reference picture: the same face, hair, build, skin, "
    "pose, colours, plain white studio backdrop and the same even, soft light. Change only the "
    "clothes and accessories the character wears, to this: {description} The whole figure, "
    "head to feet, stays centred in the frame with a little space around it. Nothing else "
    "about the picture changes."
)

_STATE_TEMPLATE: Final = (
    "The exact same place as the reference picture: the same viewpoint, framing, layout, "
    "architecture, furniture and objects in the same positions, wide and empty with no "
    "people. Change only the condition of the place, to this: {description} Nothing else "
    "about the picture changes."
)


def _sentence(description: str) -> str:
    """The description as one finished sentence, so the template's last sentence starts
    cleanly after it.
    """
    text = " ".join(description.split())
    if not text:
        raise ValueError("A look or state needs a description to be drawn from.")
    return text if text[-1] in ".!?" else text + "."


def _checked(prompt: str) -> str:
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"The edit prompt must be at most {MAX_PROMPT_CHARS:,} characters.")
    return prompt


def look_edit_prompt(description: str) -> str:
    """The prompt that edits a character's front picture into the named look."""
    return _checked(_LOOK_TEMPLATE.format(description=_sentence(description)))


def state_edit_prompt(description: str) -> str:
    """The prompt that edits an environment's canonical picture into the named state."""
    return _checked(_STATE_TEMPLATE.format(description=_sentence(description)))
